#!/usr/bin/env python3
"""
UPHOLIC Frozen Scanner Live Runner

Production supervisor for:
    1) mongo_feature_adapter.py
    2) stock_breakout_retest_iv_quiet_scanner.py

Design goals:
- Keep the frozen scanner and its rule file unchanged.
- Poll MongoDB cheaply for new snapshot activity.
- Run the pipeline only when a NEW COMPLETED 5-minute bucket is available.
- Give the 208-symbol ingestion cycle a short chance to finish before scanning.
- Never overlap adapter/scanner runs.
- Use child processes so pandas/numpy memory is released after every cycle.
- Persist the last successful bucket so service restarts/reboots recover cleanly.
- Back off on MongoDB or child-process failures instead of busy-looping.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import math
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

IST = ZoneInfo("Asia/Kolkata")

RUNNER_VERSION = "1.0.0"
DEFAULT_BOOTSTRAP_FROM = "2026-08-18"
DEFAULT_POLL_SECONDS = 3.0
DEFAULT_OFF_HOURS_POLL_SECONDS = 30.0
DEFAULT_SETTLE_SECONDS = 12.0
DEFAULT_COVERAGE_TIMEOUT_SECONDS = 45.0
DEFAULT_READY_COVERAGE_RATIO = 0.98
DEFAULT_RETRY_SECONDS = 15.0
DEFAULT_ADAPTER_TIMEOUT_SECONDS = 1800
DEFAULT_SCANNER_TIMEOUT_SECONDS = 600

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
load_dotenv(PROJECT_ROOT / ".env")

STOP_REQUESTED = False


def log_setup() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def request_stop(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logging.info("shutdown requested (signal=%s)", signum)


def parse_hhmm(value: str, fallback: str) -> dt_time:
    text = (value or fallback).strip()
    try:
        hour, minute = [int(part) for part in text.split(":", 1)]
        return dt_time(hour=hour, minute=minute)
    except Exception:
        hour, minute = [int(part) for part in fallback.split(":", 1)]
        return dt_time(hour=hour, minute=minute)


def floor_5m(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 5) * 5, second=0, microsecond=0)


def as_aware_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def parse_bucket(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" IST", "").strip())
    except (TypeError, ValueError):
        return None
    return as_aware_ist(parsed)


def format_bucket(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_aware_ist(value).replace(tzinfo=None).isoformat(sep=" ")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def latest_summary_bucket(scanner_summary: Path) -> datetime | None:
    summary = load_json(scanner_summary)
    return parse_bucket(summary.get("latest_completed_bucket_ist"))


def load_initial_bucket(state_file: Path, scanner_summary: Path) -> datetime | None:
    candidates: list[datetime] = []

    state = load_json(state_file)
    state_bucket = parse_bucket(state.get("last_successful_bucket_ist"))
    if state_bucket is not None:
        candidates.append(state_bucket)

    summary_bucket = latest_summary_bucket(scanner_summary)
    if summary_bucket is not None:
        candidates.append(summary_bucket)

    return max(candidates) if candidates else None


def latest_snapshot_ist(collection: Any) -> tuple[datetime | None, str | None]:
    doc = collection.find_one(
        {},
        {"_id": 1, "fetched_at": 1, "ts_ist": 1},
        sort=[("fetched_at", -1)],
    )
    if not doc:
        return None, None

    fetched = doc.get("fetched_at")
    if isinstance(fetched, datetime):
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        stamp = fetched.astimezone(IST)
    else:
        text = doc.get("ts_ist")
        if not isinstance(text, str) or not text.strip():
            return None, str(doc.get("_id", ""))
        cleaned = text.strip()
        if cleaned.endswith(" IST"):
            cleaned = cleaned[:-4]
        try:
            stamp = datetime.fromisoformat(cleaned).replace(tzinfo=IST)
        except ValueError:
            return None, str(doc.get("_id", ""))

    return stamp, str(doc.get("_id", ""))


def latest_completed_bucket(latest_data_ist: datetime, now_ist: datetime) -> datetime | None:
    """
    A bucket is valid only after its five-minute window has ended.

    Example:
      now=14:12, newest raw snapshot=14:10:03 -> latest complete bucket=14:05
      now=14:12, newest raw snapshot=14:09:58 -> latest complete bucket=14:05
    """
    wall_clock_complete = floor_5m(now_ist) - timedelta(minutes=5)
    data_bucket = floor_5m(latest_data_ist)

    if data_bucket + timedelta(minutes=5) <= now_ist:
        data_complete = data_bucket
    else:
        data_complete = data_bucket - timedelta(minutes=5)

    candidate = min(wall_clock_complete, data_complete)
    return candidate


def normalize_market_candidate(
    candidate: datetime | None,
    market_open: dt_time,
    market_close: dt_time,
) -> datetime | None:
    """Reject pre-open buckets and clamp post-close activity to the final market bucket."""
    if candidate is None or candidate.weekday() >= 5:
        return None

    open_dt = datetime.combine(candidate.date(), market_open, tzinfo=IST)
    close_dt = datetime.combine(candidate.date(), market_close, tzinfo=IST)
    last_bucket_start = floor_5m(close_dt - timedelta(microseconds=1))

    if candidate < open_dt:
        return None
    if candidate > last_bucket_start:
        return last_bucket_start
    return candidate


def bucket_symbol_coverage(collection: Any, bucket_ist: datetime) -> int:
    start_utc = as_aware_ist(bucket_ist).astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=5)

    pipeline = [
        {
            "$match": {
                "fetched_at": {
                    "$gte": start_utc,
                    "$lt": end_utc,
                }
            }
        },
        {"$group": {"_id": "$symbol"}},
        {"$count": "symbols"},
    ]

    rows = list(collection.aggregate(pipeline, allowDiskUse=False))
    if not rows:
        return 0
    return int(rows[0].get("symbols", 0))


def market_window(now_ist: datetime, market_open: dt_time, market_close: dt_time) -> bool:
    if now_ist.weekday() >= 5:
        return False
    # Keep the fast polling window a few minutes beyond market close so the final
    # completed bucket can be processed promptly.
    close_dt = datetime.combine(now_ist.date(), market_close, tzinfo=IST) + timedelta(minutes=10)
    open_dt = datetime.combine(now_ist.date(), market_open, tzinfo=IST) - timedelta(minutes=5)
    return open_dt <= now_ist <= close_dt


def tail(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    return text[-limit:]


def run_child(
    name: str,
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    logging.info("%s starting", name)

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )

    elapsed = time.monotonic() - started

    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} failed rc={completed.returncode} elapsed={elapsed:.1f}s "
            f"stdout_tail={tail(completed.stdout)!r} stderr_tail={tail(completed.stderr)!r}"
        )

    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {}

    if completed.stderr:
        # pandas FutureWarnings and similar non-fatal warnings stay visible without
        # dumping unbounded child output into journald.
        logging.warning("%s stderr: %s", name, tail(completed.stderr, 2000).strip())

    logging.info("%s finished in %.2fs", name, elapsed)
    return payload


def ensure_required_paths(
    adapter: Path,
    scanner: Path,
    locked_rule: Path,
    features: Path,
    results: Path,
    state_file: Path,
) -> None:
    for path in (adapter, scanner, locked_rule):
        if not path.exists():
            raise FileNotFoundError(f"Required file missing: {path}")

    features.parent.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    state_file.parent.mkdir(parents=True, exist_ok=True)


def acquire_single_instance_lock(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError(f"Another live runner already owns {lock_file}") from exc

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuous production supervisor for the frozen breakout/retest scanner"
    )
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--off-hours-poll-seconds", type=float, default=DEFAULT_OFF_HOURS_POLL_SECONDS)
    parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_SECONDS)
    parser.add_argument("--coverage-timeout-seconds", type=float, default=DEFAULT_COVERAGE_TIMEOUT_SECONDS)
    parser.add_argument("--ready-coverage-ratio", type=float, default=DEFAULT_READY_COVERAGE_RATIO)
    parser.add_argument("--retry-seconds", type=float, default=DEFAULT_RETRY_SECONDS)
    parser.add_argument(
        "--expected-symbols",
        type=int,
        default=int(os.getenv("TOTAL_SYMBOLS", "208")),
    )
    parser.add_argument("--bootstrap-from", default=DEFAULT_BOOTSTRAP_FROM)
    parser.add_argument("--adapter-timeout-seconds", type=int, default=DEFAULT_ADAPTER_TIMEOUT_SECONDS)
    parser.add_argument("--scanner-timeout-seconds", type=int, default=DEFAULT_SCANNER_TIMEOUT_SECONDS)

    parser.add_argument("--features", type=Path, default=BASE_DIR / "runtime/features/stock_option_features_5m.csv")
    parser.add_argument("--results", type=Path, default=BASE_DIR / "runtime/results")
    parser.add_argument("--locked-rule", type=Path, default=BASE_DIR / "LOCKED_RULE.json")
    parser.add_argument("--ledger", type=Path, default=BASE_DIR / "runtime/notification_ledger.json")
    parser.add_argument("--state-file", type=Path, default=BASE_DIR / "runtime/live_runner_state.json")
    parser.add_argument("--lock-file", type=Path, default=BASE_DIR / "runtime/live_runner.lock")

    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.poll_seconds < 1:
        raise ValueError("--poll-seconds must be >= 1")
    if args.off_hours_poll_seconds < args.poll_seconds:
        raise ValueError("--off-hours-poll-seconds must be >= --poll-seconds")
    if args.settle_seconds < 0:
        raise ValueError("--settle-seconds must be >= 0")
    if args.coverage_timeout_seconds < args.settle_seconds:
        raise ValueError("--coverage-timeout-seconds must be >= --settle-seconds")
    if not (0 < args.ready_coverage_ratio <= 1):
        raise ValueError("--ready-coverage-ratio must be > 0 and <= 1")
    if args.expected_symbols < 1:
        raise ValueError("--expected-symbols must be >= 1")


def main() -> int:
    global STOP_REQUESTED

    log_setup()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    parser = build_parser()
    args = parser.parse_args()
    validate_args(args)

    adapter = BASE_DIR / "mongo_feature_adapter.py"
    scanner = BASE_DIR / "stock_breakout_retest_iv_quiet_scanner.py"

    features = args.features.resolve()
    results = args.results.resolve()
    locked_rule = args.locked_rule.resolve()
    ledger = args.ledger.resolve()
    state_file = args.state_file.resolve()
    lock_file = args.lock_file.resolve()
    scanner_summary_file = results / "scanner_summary.json"

    ensure_required_paths(
        adapter=adapter,
        scanner=scanner,
        locked_rule=locked_rule,
        features=features,
        results=results,
        state_file=state_file,
    )

    lock_handle = acquire_single_instance_lock(lock_file)

    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")
    market_open = parse_hhmm(os.getenv("MARKET_OPEN_TIME", "09:15"), "09:15")
    market_close = parse_hhmm(os.getenv("MARKET_CLOSE_TIME", "15:40"), "15:40")

    ready_symbols = max(
        1,
        min(
            args.expected_symbols,
            math.ceil(args.expected_symbols * args.ready_coverage_ratio),
        ),
    )

    last_successful_bucket = load_initial_bucket(state_file, scanner_summary_file)
    consecutive_failures = 0
    next_retry_monotonic = 0.0
    last_wait_log = 0.0

    logging.info(
        "runner v%s starting | db=%s collection=snapshots poll=%.1fs "
        "expected_symbols=%d ready_symbols=%d settle=%.1fs coverage_timeout=%.1fs "
        "last_successful_bucket=%s",
        RUNNER_VERSION,
        db_name,
        args.poll_seconds,
        args.expected_symbols,
        ready_symbols,
        args.settle_seconds,
        args.coverage_timeout_seconds,
        format_bucket(last_successful_bucket),
    )

    client = MongoClient(
        mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000,
        tz_aware=True,
        retryReads=True,
        appname="upholic-frozen-live-runner",
    )

    try:
        while not STOP_REQUESTED:
            now_ist = datetime.now(IST)

            try:
                collection = client[db_name]["snapshots"]

                latest_ist, latest_id = latest_snapshot_ist(collection)
                if latest_ist is None:
                    logging.warning("no snapshot document available yet")
                    time.sleep(args.off_hours_poll_seconds)
                    continue

                candidate = normalize_market_candidate(
                    latest_completed_bucket(latest_ist, now_ist),
                    market_open,
                    market_close,
                )
                if candidate is None:
                    time.sleep(args.poll_seconds)
                    continue

                needs_run = (
                    last_successful_bucket is None
                    or candidate > last_successful_bucket
                )

                if not needs_run:
                    sleep_for = (
                        args.poll_seconds
                        if market_window(now_ist, market_open, market_close)
                        else args.off_hours_poll_seconds
                    )
                    time.sleep(sleep_for)
                    continue

                if time.monotonic() < next_retry_monotonic:
                    time.sleep(min(args.poll_seconds, max(0.2, next_retry_monotonic - time.monotonic())))
                    continue

                bucket_end = candidate + timedelta(minutes=5)
                settle_until = bucket_end + timedelta(seconds=args.settle_seconds)
                hard_deadline = bucket_end + timedelta(seconds=args.coverage_timeout_seconds)

                if now_ist < settle_until:
                    time.sleep(min(args.poll_seconds, max(0.2, (settle_until - now_ist).total_seconds())))
                    continue

                coverage = bucket_symbol_coverage(collection, candidate)
                now_ist = datetime.now(IST)

                if coverage < ready_symbols and now_ist < hard_deadline:
                    now_mono = time.monotonic()
                    if now_mono - last_wait_log >= 10:
                        logging.info(
                            "waiting for bucket %s coverage %d/%d (ready at %d, timeout in %.1fs)",
                            format_bucket(candidate),
                            coverage,
                            args.expected_symbols,
                            ready_symbols,
                            max(0.0, (hard_deadline - now_ist).total_seconds()),
                        )
                        last_wait_log = now_mono
                    time.sleep(args.poll_seconds)
                    continue

                if coverage < ready_symbols:
                    logging.warning(
                        "coverage timeout for bucket %s: %d/%d symbols; running anyway so pipeline does not stall",
                        format_bucket(candidate),
                        coverage,
                        args.expected_symbols,
                    )
                else:
                    logging.info(
                        "new completed bucket %s ready: coverage %d/%d; starting pipeline",
                        format_bucket(candidate),
                        coverage,
                        args.expected_symbols,
                    )

                adapter_cmd = [
                    sys.executable,
                    str(adapter),
                    "--output",
                    str(features),
                    "--bootstrap-from",
                    args.bootstrap_from,
                ]

                scanner_cmd = [
                    sys.executable,
                    str(scanner),
                    "--features",
                    str(features),
                    "--output",
                    str(results),
                    "--locked-rule",
                    str(locked_rule),
                    "--ledger",
                    str(ledger),
                ]

                adapter_summary = run_child(
                    "feature-adapter",
                    adapter_cmd,
                    cwd=BASE_DIR,
                    timeout_seconds=args.adapter_timeout_seconds,
                )

                scanner_summary = run_child(
                    "frozen-scanner",
                    scanner_cmd,
                    cwd=BASE_DIR,
                    timeout_seconds=args.scanner_timeout_seconds,
                )

                scanner_bucket = parse_bucket(
                    scanner_summary.get("latest_completed_bucket_ist")
                ) or latest_summary_bucket(scanner_summary_file)

                if scanner_bucket is None:
                    raise RuntimeError(
                        "scanner completed but latest_completed_bucket_ist was unavailable"
                    )

                if scanner_bucket < candidate:
                    raise RuntimeError(
                        f"scanner only reached {format_bucket(scanner_bucket)} "
                        f"while candidate was {format_bucket(candidate)}"
                    )

                last_successful_bucket = scanner_bucket
                consecutive_failures = 0
                next_retry_monotonic = 0.0

                state_payload = {
                    "runner": "UPHOLIC Frozen Scanner Live Runner",
                    "runner_version": RUNNER_VERSION,
                    "updated_at_ist": datetime.now(IST).replace(tzinfo=None).isoformat(sep=" "),
                    "last_successful_bucket_ist": format_bucket(last_successful_bucket),
                    "trigger_candidate_bucket_ist": format_bucket(candidate),
                    "bucket_symbol_coverage": coverage,
                    "expected_symbols": args.expected_symbols,
                    "ready_symbols": ready_symbols,
                    "latest_snapshot_id_seen": latest_id,
                    "latest_snapshot_ist_seen": latest_ist.replace(tzinfo=None).isoformat(sep=" "),
                    "consecutive_failures": 0,
                    "adapter": {
                        "snapshots_seen_this_run": adapter_summary.get("snapshots_seen_this_run"),
                        "five_minute_rows_total": adapter_summary.get("five_minute_rows_total"),
                        "symbols": adapter_summary.get("symbols"),
                        "latest_bucket_ist": adapter_summary.get("latest_bucket_ist"),
                    },
                    "scanner": {
                        "data_status": scanner_summary.get("data_status"),
                        "symbols_scanned": scanner_summary.get("symbols_scanned"),
                        "active_states": scanner_summary.get("active_states"),
                        "signals_since_forward_start": scanner_summary.get("signals_since_forward_start"),
                        "new_signals_this_run": scanner_summary.get("new_signals_this_run"),
                        "paper_entries": scanner_summary.get("paper_entries"),
                        "paper_exits": scanner_summary.get("paper_exits"),
                    },
                }
                atomic_json(state_file, state_payload)

                logging.info(
                    "pipeline OK bucket=%s data_status=%s symbols=%s active_states=%s "
                    "signals=%s new_signals=%s",
                    format_bucket(last_successful_bucket),
                    scanner_summary.get("data_status"),
                    scanner_summary.get("symbols_scanned"),
                    scanner_summary.get("active_states"),
                    scanner_summary.get("signals_since_forward_start"),
                    scanner_summary.get("new_signals_this_run"),
                )

            except subprocess.TimeoutExpired as exc:
                consecutive_failures += 1
                delay = min(60.0, args.retry_seconds * max(1, consecutive_failures))
                next_retry_monotonic = time.monotonic() + delay
                logging.exception(
                    "child timeout after %ss; retrying in %.1fs",
                    exc.timeout,
                    delay,
                )
                time.sleep(min(args.poll_seconds, delay))

            except (PyMongoError, RuntimeError, OSError, ValueError) as exc:
                consecutive_failures += 1
                delay = min(60.0, args.retry_seconds * max(1, consecutive_failures))
                next_retry_monotonic = time.monotonic() + delay
                logging.error(
                    "runner cycle failed (%s); consecutive_failures=%d retry_in=%.1fs",
                    exc,
                    consecutive_failures,
                    delay,
                )

                state = load_json(state_file)
                state.update(
                    {
                        "runner": "UPHOLIC Frozen Scanner Live Runner",
                        "runner_version": RUNNER_VERSION,
                        "updated_at_ist": datetime.now(IST).replace(tzinfo=None).isoformat(sep=" "),
                        "last_successful_bucket_ist": format_bucket(last_successful_bucket),
                        "consecutive_failures": consecutive_failures,
                        "last_error": str(exc),
                    }
                )
                atomic_json(state_file, state)
                time.sleep(min(args.poll_seconds, delay))

    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
        except Exception:
            pass
        logging.info("runner stopped cleanly")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
