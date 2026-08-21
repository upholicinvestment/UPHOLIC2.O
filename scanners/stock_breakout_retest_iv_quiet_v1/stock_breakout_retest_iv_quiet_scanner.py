"""Frozen stock breakout/extension/retest forward scanner.

Research-only scanner. It never connects to a broker and never places orders.
The source feature files are read-only. All timestamps are interpreted as IST.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


IST = ZoneInfo("Asia/Kolkata")
SCANNER_NAME = "Stock Breakout Retest IV Quiet Scanner v1"
SCANNER_STATUS = "EXPERIMENTAL_FORWARD_WATCHLIST_ONLY"
DEFAULT_FORWARD_START = "2026-08-20 09:15:00"

LOCKED_PARAMETERS: dict[str, Any] = {
    "direction": "LONG_ONLY",
    "bar_minutes": 5,
    "completed_candles_only": True,
    "structure_lookback_bars": 120,
    "resistance_zone_pct": 0.003,
    "minimum_separated_touches": 3,
    "touch_gap_minutes": 20,
    "minimum_intervening_pullback_pct": 0.003,
    "breakout_buffer_pct": 0.0005,
    "state1_time_start_ist": "09:45",
    "state1_time_end_ist": "14:45",
    "state1_ce_iv_change_15_minimum": 0.5,
    "extension_target_pct": 0.01,
    "extension_horizon_calendar_days": 10,
    "retest_horizon_calendar_days": 10,
    "retest_option_volume_ratio_maximum": 0.25,
    "entry": "NEXT_COMPLETED_5_MINUTE_SNAPSHOT_OPEN_PROXY",
    "target": "OBSERVED_EXTENSION_HIGH_BEFORE_RETEST",
    "stop": "LOWER_RESISTANCE_ZONE_BOUNDARY",
    "maximum_active_states_per_symbol": 1,
    "orders_enabled": False,
}

REQUIRED_COLUMNS = {
    "symbol",
    "trade_date",
    "bucket_ist",
    "timestamp_ist",
    "spot_price",
    "spot_first",
    "near_total_volume",
    "near_ce_oi",
    "near_pe_oi",
    "near_total_oi",
    "ce_iv_oi_weighted",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_naive_ist(value: str | pd.Timestamp | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(IST).replace(tzinfo=None))
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Kolkata").tz_localize(None)
    return stamp


def safe_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def stable_id(*values: object) -> str:
    text = "|".join(str(value) for value in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def validate_locked_rule(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    supplied = document.get("parameters")
    if supplied != LOCKED_PARAMETERS:
        raise ValueError(
            "LOCKED_RULE.json does not match the audited scanner constants. "
            "Restore the original package; do not edit thresholds during the forward test."
        )
    return document


def load_features(paths: list[Path], as_of: pd.Timestamp) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for path in paths:
        resolved = path.resolve()
        frame = pd.read_csv(resolved)
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError(f"{resolved} is missing required fields: {missing}")
        frame["source_feature_file"] = str(resolved)
        parts.append(frame)
    if not parts:
        raise ValueError("At least one feature file is required.")
    frame = pd.concat(parts, ignore_index=True)
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    # Real exports mix timestamps with and without fractional seconds.
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="mixed").dt.normalize()
    frame["bucket_ist"] = pd.to_datetime(frame["bucket_ist"], format="mixed")
    frame["timestamp_ist"] = pd.to_datetime(frame["timestamp_ist"], format="mixed")
    frame = frame[frame["bucket_ist"] + pd.Timedelta(minutes=5) <= as_of].copy()
    frame = frame.drop_duplicates(["symbol", "trade_date", "bucket_ist"], keep="last")
    frame = frame.sort_values(["symbol", "bucket_ist"]).reset_index(drop=True)
    numeric = [
        column
        for column in frame.columns
        if column
        not in {
            "symbol",
            "trade_date",
            "bucket_ist",
            "timestamp_ist",
            "source_id",
            "security_id",
            "expiry",
            "source_feature_file",
        }
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")

    prepared: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol", sort=False):
        group = group.sort_values("bucket_ist").copy()
        daily = group.groupby("trade_date", group_keys=False)
        group["ce_iv_change_15"] = (
            group["ce_iv_oi_weighted"] - daily["ce_iv_oi_weighted"].shift(3)
        )
        group["option_volume_delta"] = daily["near_total_volume"].diff().clip(lower=0)
        group["symbol"] = symbol
        prepared.append(group)
    if not prepared:
        return frame.assign(ce_iv_change_15=np.nan, option_volume_delta=np.nan)
    return pd.concat(prepared, ignore_index=True).replace([np.inf, -np.inf], np.nan)


def clustered_positions(timestamps: np.ndarray, positions: np.ndarray) -> list[int]:
    if not len(positions):
        return []
    selected = [int(positions[0])]
    for position in positions[1:]:
        current = int(position)
        gap = pd.Timestamp(timestamps[current]) - pd.Timestamp(timestamps[selected[-1]])
        if gap >= pd.Timedelta(minutes=LOCKED_PARAMETERS["touch_gap_minutes"]):
            selected.append(current)
    return selected


def state1_candidate(
    group: pd.DataFrame, index: int, forward_start: pd.Timestamp
) -> dict[str, Any] | None:
    row = group.iloc[index]
    event_time = pd.Timestamp(row["bucket_ist"])
    if event_time < forward_start:
        return None
    if not (
        pd.Timestamp(LOCKED_PARAMETERS["state1_time_start_ist"]).time()
        <= event_time.time()
        <= pd.Timestamp(LOCKED_PARAMETERS["state1_time_end_ist"]).time()
    ):
        return None
    bars = int(LOCKED_PARAMETERS["structure_lookback_bars"])
    start = max(0, index - bars)
    history = group.iloc[start:index]
    if len(history) < 12:
        return None
    prices = history["spot_price"].to_numpy(dtype=float)
    if not np.isfinite(prices).all():
        return None
    level = float(np.max(prices))
    current_price = safe_float(row["spot_price"])
    previous_price = safe_float(group.iloc[index - 1]["spot_price"])
    if level <= 0 or not np.isfinite(current_price) or not np.isfinite(previous_price):
        return None
    buffer_pct = float(LOCKED_PARAMETERS["breakout_buffer_pct"])
    current_gap = current_price / level - 1.0
    previous_gap = previous_price / level - 1.0
    if current_gap < buffer_pct or previous_gap > buffer_pct:
        return None
    zone = float(LOCKED_PARAMETERS["resistance_zone_pct"])
    hits = np.flatnonzero(prices >= level * (1.0 - zone))
    clusters = clustered_positions(history["bucket_ist"].to_numpy(), hits)
    if len(clusters) < int(LOCKED_PARAMETERS["minimum_separated_touches"]):
        return None
    first, last = clusters[0], clusters[-1]
    pullback = float((level - np.min(prices[first : last + 1])) / level)
    if pullback < float(LOCKED_PARAMETERS["minimum_intervening_pullback_pct"]):
        return None
    ce_iv_change = safe_float(row["ce_iv_change_15"])
    if not np.isfinite(ce_iv_change) or ce_iv_change < float(
        LOCKED_PARAMETERS["state1_ce_iv_change_15_minimum"]
    ):
        return None
    option_volume = safe_float(row["option_volume_delta"])
    if not np.isfinite(option_volume) or option_volume <= 0:
        return None
    state_id = stable_id(
        SCANNER_NAME,
        row["symbol"],
        event_time.isoformat(),
        f"{level:.8f}",
        f"{current_price:.8f}",
    )
    return {
        "state_id": state_id,
        "symbol": row["symbol"],
        "stage": "WAIT_EXTENSION",
        "state1_time_ist": event_time,
        "state1_price": current_price,
        "resistance_level": level,
        "touch_count": len(clusters),
        "intervening_pullback_pct": pullback,
        "break_distance_pct": current_gap,
        "state1_ce_iv_change_15": ce_iv_change,
        "state1_option_volume": option_volume,
        "extension_deadline_ist": event_time
        + pd.Timedelta(days=int(LOCKED_PARAMETERS["extension_horizon_calendar_days"])),
    }


def event_record(active: dict[str, Any], event_type: str, timestamp: pd.Timestamp, **extra: Any) -> dict[str, Any]:
    record = {
        "event_id": stable_id(active["state_id"], event_type, timestamp.isoformat()),
        "state_id": active["state_id"],
        "symbol": active["symbol"],
        "event_type": event_type,
        "event_time_ist": timestamp,
        "state1_time_ist": active["state1_time_ist"],
        "resistance_level": active["resistance_level"],
    }
    record.update(extra)
    return record


def scan_symbol(group: pd.DataFrame, forward_start: pd.Timestamp) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    group = group.sort_values("bucket_ist").reset_index(drop=True)
    events: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    last_time: pd.Timestamp | None = None
    last_price = float("nan")

    for index, row in group.iterrows():
        timestamp = pd.Timestamp(row["bucket_ist"])
        price = safe_float(row["spot_price"])
        if timestamp < forward_start or not np.isfinite(price):
            last_time, last_price = timestamp, price
            continue
        released_this_row = False

        if active is not None and active["stage"] == "WAIT_EXTENSION":
            if timestamp > active["extension_deadline_ist"]:
                events.append(event_record(active, "STATE_EXPIRED", timestamp, reason="ONE_PERCENT_EXTENSION_NOT_REACHED"))
                active = None
                released_this_row = True
            elif timestamp > active["state1_time_ist"] and price >= active["resistance_level"] * (
                1.0 + float(LOCKED_PARAMETERS["extension_target_pct"])
            ):
                active["stage"] = "WAIT_RETEST"
                active["state2_time_ist"] = timestamp
                active["state2_price"] = price
                active["extension_high"] = price
                active["retest_deadline_ist"] = timestamp + pd.Timedelta(
                    days=int(LOCKED_PARAMETERS["retest_horizon_calendar_days"])
                )
                events.append(event_record(active, "STATE2_EXTENSION_REACHED", timestamp, price=price))

        elif active is not None and active["stage"] == "WAIT_RETEST":
            active["extension_high"] = max(active["extension_high"], price)
            if timestamp > active["retest_deadline_ist"]:
                events.append(event_record(active, "STATE_EXPIRED", timestamp, reason="RETEST_NOT_SEEN_IN_TEN_DAYS"))
                active = None
                released_this_row = True
            else:
                zone = float(LOCKED_PARAMETERS["resistance_zone_pct"])
                lower = active["resistance_level"] * (1.0 - zone)
                upper = active["resistance_level"] * (1.0 + zone)
                if lower <= price <= upper:
                    retest_volume = safe_float(row["option_volume_delta"])
                    ratio = (
                        retest_volume / active["state1_option_volume"]
                        if active["state1_option_volume"] > 0 and np.isfinite(retest_volume)
                        else float("nan")
                    )
                    active["state3_time_ist"] = timestamp
                    active["state3_price"] = price
                    active["retest_option_volume"] = retest_volume
                    active["pullback_volume_ratio"] = ratio
                    if np.isfinite(ratio) and ratio <= float(
                        LOCKED_PARAMETERS["retest_option_volume_ratio_maximum"]
                    ):
                        active["stage"] = "PENDING_ENTRY"
                        active["target_price"] = active["extension_high"]
                        active["stop_price"] = lower
                        active["trade_deadline_ist"] = timestamp + pd.Timedelta(
                            days=int(LOCKED_PARAMETERS["retest_horizon_calendar_days"])
                        )
                        signal_id = stable_id(active["state_id"], "SIGNAL", timestamp.isoformat())
                        active["signal_id"] = signal_id
                        events.append(
                            event_record(
                                active,
                                "SIGNAL_READY",
                                timestamp,
                                signal_id=signal_id,
                                side="BUY",
                                retest_price=price,
                                pullback_volume_ratio=ratio,
                                target_price=active["target_price"],
                                stop_price=active["stop_price"],
                                action="WATCH_NEXT_COMPLETED_5_MINUTE_SNAPSHOT",
                            )
                        )
                    else:
                        events.append(
                            event_record(
                                active,
                                "RETEST_REJECTED",
                                timestamp,
                                reason="PULLBACK_OPTION_VOLUME_ABOVE_25_PERCENT_OR_MISSING",
                                retest_price=price,
                                pullback_volume_ratio=ratio,
                            )
                        )
                        active = None
                        released_this_row = True

        elif active is not None and active["stage"] == "PENDING_ENTRY":
            if timestamp > active["state3_time_ist"]:
                entry_price = safe_float(row.get("spot_first", row["spot_price"]))
                active["stage"] = "TRADE_ACTIVE"
                active["entry_time_ist"] = timestamp
                active["entry_price"] = entry_price
                events.append(
                    event_record(
                        active,
                        "PAPER_ENTRY",
                        timestamp,
                        signal_id=active["signal_id"],
                        side="BUY",
                        entry_price=entry_price,
                        target_price=active["target_price"],
                        stop_price=active["stop_price"],
                    )
                )

        if active is not None and active["stage"] == "TRADE_ACTIVE":
            exit_reason: str | None = None
            exit_price = price
            exit_time = timestamp
            if timestamp > active["trade_deadline_ist"]:
                exit_reason = "TIME_EXIT_10_CALENDAR_DAYS"
                if last_time is not None and np.isfinite(last_price):
                    exit_time, exit_price = last_time, last_price
            elif price <= active["stop_price"]:
                exit_reason = "SUPPORT_FAILED"
            elif price >= active["target_price"]:
                exit_reason = "EXTENSION_HIGH_RETESTED"
            if exit_reason is not None:
                pnl_bps = (
                    (exit_price / active["entry_price"] - 1.0) * 10_000
                    if active["entry_price"] > 0
                    else float("nan")
                )
                events.append(
                    event_record(
                        active,
                        "PAPER_EXIT",
                        exit_time,
                        signal_id=active["signal_id"],
                        exit_reason=exit_reason,
                        entry_price=active["entry_price"],
                        exit_price=exit_price,
                        pnl_bps=pnl_bps,
                    )
                )
                active = None
                released_this_row = True

        if active is None and not released_this_row and index > 0:
            candidate = state1_candidate(group, index, forward_start)
            if candidate is not None:
                active = candidate
                events.append(
                    event_record(
                        active,
                        "STATE1_BREAKOUT",
                        timestamp,
                        price=price,
                        ce_iv_change_15=active["state1_ce_iv_change_15"],
                        option_volume=active["state1_option_volume"],
                        touch_count=active["touch_count"],
                        intervening_pullback_pct=active["intervening_pullback_pct"],
                    )
                )
        last_time, last_price = timestamp, price
    return events, active


def frame_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(records) if records else pd.DataFrame()


def json_ready(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat(sep=" ")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"notified_signal_ids": [], "updated_at_ist": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise ValueError(f"Ledger is unreadable: {path}")
    value.setdefault("notified_signal_ids", [])
    return value


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def html_table(frame: pd.DataFrame, columns: list[str]) -> str:
    available = [column for column in columns if column in frame.columns]
    if frame.empty or not available:
        return "<p>None.</p>"
    head = "".join(f"<th>{escape(column)}</th>" for column in available)
    rows: list[str] = []
    for values in frame[available].tail(100).itertuples(index=False, name=None):
        cells = []
        for value in values:
            if isinstance(value, (float, np.floating)):
                display = "" if not np.isfinite(value) else f"{value:.4f}"
            else:
                display = str(value)
            cells.append(f"<td>{escape(display)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def dashboard(summary: dict[str, Any], states: pd.DataFrame, signals: pd.DataFrame, events: pd.DataFrame) -> str:
    status_color = "#a13b13" if summary["data_status"] != "FRESH" else "#075b3a"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{SCANNER_NAME}</title>
<style>body{{font-family:Segoe UI,Arial;margin:32px;background:#f5f3ed;color:#17231d}}h1{{color:#075b3a}}.card{{background:white;padding:20px;margin:16px 0;border:1px solid #d6d8d3}}.status{{color:{status_color};font-weight:700}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#e7f1eb}}</style></head><body>
<h1>{SCANNER_NAME}</h1><div class="card"><span class="status">{escape(summary['data_status'])}</span><br>
As of: {escape(summary['as_of_ist'])} IST<br>Latest completed bucket: {escape(summary['latest_completed_bucket_ist'])}<br>
New signals this run: {summary['new_signals_this_run']}<br><b>Research watchlist only—no orders.</b></div>
<div class="card"><h2>Current states</h2>{html_table(states, ['symbol','stage','state1_time_ist','resistance_level','state2_time_ist','state3_time_ist','target_price','stop_price'])}</div>
<div class="card"><h2>Forward signals</h2>{html_table(signals, ['symbol','event_time_ist','retest_price','pullback_volume_ratio','target_price','stop_price','signal_id'])}</div>
<div class="card"><h2>Latest events</h2>{html_table(events, ['symbol','event_time_ist','event_type','price','reason','pnl_bps'])}</div>
<p>Frozen rule version 1. Threshold changes invalidate the forward test.</p></body></html>"""


def run_scan(
    features: list[Path],
    output: Path,
    locked_rule: Path,
    ledger_path: Path,
    forward_start: pd.Timestamp,
    as_of: pd.Timestamp,
    max_stale_minutes: int,
) -> dict[str, Any]:
    rule_document = validate_locked_rule(locked_rule)
    frame = load_features(features, as_of)
    if frame.empty:
        raise ValueError("No completed five-minute rows were available at the requested as-of time.")
    events: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for symbol, group in frame.groupby("symbol", sort=True):
        symbol_events, active = scan_symbol(group, forward_start)
        events.extend(symbol_events)
        if active is not None:
            states.append(active.copy())
    event_frame = frame_from_records(events)
    if not event_frame.empty:
        event_frame = event_frame.sort_values(["event_time_ist", "symbol", "event_type"]).reset_index(drop=True)
    state_frame = frame_from_records(states)
    signal_frame = (
        event_frame[event_frame["event_type"].eq("SIGNAL_READY")].copy()
        if not event_frame.empty
        else pd.DataFrame()
    )
    trade_frame = (
        event_frame[event_frame["event_type"].isin(["PAPER_ENTRY", "PAPER_EXIT"])].copy()
        if not event_frame.empty
        else pd.DataFrame()
    )

    ledger = load_ledger(ledger_path)
    notified = set(str(value) for value in ledger["notified_signal_ids"])
    signal_ids = set(signal_frame.get("signal_id", pd.Series(dtype=str)).dropna().astype(str))
    new_ids = sorted(signal_ids - notified)
    new_signal_frame = (
        signal_frame[signal_frame["signal_id"].astype(str).isin(new_ids)].copy()
        if not signal_frame.empty
        else pd.DataFrame()
    )
    ledger["notified_signal_ids"] = sorted(notified | signal_ids)
    ledger["updated_at_ist"] = as_of.isoformat(sep=" ")
    ledger["forward_start_ist"] = forward_start.isoformat(sep=" ")
    atomic_text(ledger_path, json.dumps(json_ready(ledger), indent=2))

    latest_bucket = pd.Timestamp(frame["bucket_ist"].max())
    staleness = max(0.0, (as_of - (latest_bucket + pd.Timedelta(minutes=5))).total_seconds() / 60.0)
    data_status = "FRESH" if staleness <= max_stale_minutes else "STALE_DATA"
    summary = {
        "scanner": SCANNER_NAME,
        "status": SCANNER_STATUS,
        "data_status": data_status,
        "as_of_ist": as_of.isoformat(sep=" "),
        "forward_start_ist": forward_start.isoformat(sep=" "),
        "latest_completed_bucket_ist": latest_bucket.isoformat(sep=" "),
        "staleness_minutes": round(staleness, 2),
        "symbols_scanned": int(frame["symbol"].nunique()),
        "completed_five_minute_rows": int(len(frame)),
        "active_states": int(len(state_frame)),
        "signals_since_forward_start": int(len(signal_frame)),
        "new_signals_this_run": int(len(new_signal_frame)),
        "paper_entries": int((event_frame.get("event_type", pd.Series(dtype=str)) == "PAPER_ENTRY").sum()),
        "paper_exits": int((event_frame.get("event_type", pd.Series(dtype=str)) == "PAPER_EXIT").sum()),
        "locked_rule_sha256": sha256_file(locked_rule),
        "source_feature_files": [
            {"path": str(path.resolve()), "sha256": sha256_file(path.resolve())} for path in features
        ],
        "parameters": rule_document["parameters"],
        "warnings": [
            "Experimental forward watchlist only; not approved for live trading.",
            "No broker connection and no order placement are present.",
            "Spot values are snapshots, not verified stock OHLC candles.",
            "Option volume is a near-chain cumulative-volume increment proxy.",
            "A stale-data status invalidates real-time interpretation.",
        ],
        "raw_source_modified": False,
    }

    output.mkdir(parents=True, exist_ok=True)
    atomic_csv(output / "event_log.csv", event_frame)
    atomic_csv(output / "current_states.csv", state_frame)
    atomic_csv(output / "forward_signals.csv", signal_frame)
    atomic_csv(output / "new_signals_this_run.csv", new_signal_frame)
    atomic_csv(output / "paper_trade_events.csv", trade_frame)
    atomic_text(output / "scanner_summary.json", json.dumps(json_ready(summary), indent=2))
    atomic_text(output / "scanner_dashboard.html", dashboard(summary, state_frame, signal_frame, event_frame))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=SCANNER_NAME)
    parser.add_argument("--features", required=True, nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--locked-rule", type=Path, default=Path(__file__).with_name("LOCKED_RULE.json")
    )
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--forward-start", default=DEFAULT_FORWARD_START)
    parser.add_argument("--as-of", help="Optional IST replay cutoff, for example 2026-08-21 12:00:00")
    parser.add_argument("--max-stale-minutes", type=int, default=15)
    args = parser.parse_args()
    output = args.output.resolve()
    ledger = args.ledger.resolve() if args.ledger else output / "notification_ledger.json"
    summary = run_scan(
        features=[path.resolve() for path in args.features],
        output=output,
        locked_rule=args.locked_rule.resolve(),
        ledger_path=ledger,
        forward_start=parse_naive_ist(args.forward_start),
        as_of=parse_naive_ist(args.as_of),
        max_stale_minutes=args.max_stale_minutes,
    )
    print(json.dumps(json_ready(summary), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
