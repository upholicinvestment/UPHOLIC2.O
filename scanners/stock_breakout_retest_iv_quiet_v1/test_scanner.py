from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "stock_breakout_retest_iv_quiet_scanner.py"
SPEC = importlib.util.spec_from_file_location("frozen_scanner", MODULE_PATH)
scanner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scanner)


def synthetic_feature_file(tmp_path: Path, retest_increment: float = 200.0) -> tuple[Path, pd.Timestamp]:
    rows = []
    cumulative = 0.0
    dates = [pd.Timestamp("2026-08-20"), pd.Timestamp("2026-08-21"), pd.Timestamp("2026-08-24")]
    counter = 0
    for day_number, day in enumerate(dates):
        for bar in range(76):
            stamp = day + pd.Timedelta(hours=9, minutes=15 + 5 * bar)
            price = 99.0
            if day_number == 1 and bar in {10, 18, 26}:
                price = 100.0
            if day_number == 1 and bar in {14, 22}:
                price = 99.4
            iv = 10.0
            increment = 100.0
            # State 1 occurs after 12 same-day bars, with a +0.6 IV-point change.
            if day_number == 2 and bar == 12:
                price, iv, increment = 100.10, 10.6, 1000.0
            elif day_number == 2 and bar == 13:
                price, increment = 101.20, 500.0
            elif day_number == 2 and bar == 14:
                price, increment = 100.20, retest_increment
            elif day_number == 2 and bar == 15:
                price, increment = 100.25, 100.0
            elif day_number == 2 and bar == 16:
                price, increment = 101.30, 100.0
            if bar == 0:
                cumulative = 1000.0
            else:
                cumulative += increment
            rows.append(
                {
                    "source_id": f"row-{counter}",
                    "symbol": "TESTCO",
                    "security_id": "1",
                    "timestamp_ist": stamp + pd.Timedelta(minutes=4),
                    "bucket_ist": stamp,
                    "trade_date": day,
                    "expiry": "2026-08-27",
                    "spot_price": price,
                    "spot_first": price,
                    "near_total_volume": cumulative,
                    "near_ce_oi": 10000.0,
                    "near_pe_oi": 9000.0,
                    "near_total_oi": 19000.0,
                    "ce_iv_oi_weighted": iv,
                }
            )
            counter += 1
    path = tmp_path / "features.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    state3_time = dates[2] + pd.Timedelta(hours=9, minutes=15 + 5 * 14)
    return path, state3_time


def run(tmp_path: Path, retest_increment: float, as_of: pd.Timestamp) -> dict:
    feature_path, _ = synthetic_feature_file(tmp_path, retest_increment)
    output = tmp_path / "results"
    return scanner.run_scan(
        features=[feature_path],
        output=output,
        locked_rule=MODULE_PATH.with_name("LOCKED_RULE.json"),
        ledger_path=tmp_path / "ledger.json",
        forward_start=pd.Timestamp("2026-08-20 09:15:00"),
        as_of=as_of,
        max_stale_minutes=10_000,
    )


def test_quiet_retest_generates_one_signal_and_paper_exit(tmp_path: Path) -> None:
    summary = run(tmp_path, 200.0, pd.Timestamp("2026-08-24 11:00:00"))
    signals = pd.read_csv(tmp_path / "results" / "forward_signals.csv")
    events = pd.read_csv(tmp_path / "results" / "event_log.csv")
    assert summary["signals_since_forward_start"] == 1
    assert len(signals) == 1
    assert signals.iloc[0]["pullback_volume_ratio"] <= 0.25
    assert "PAPER_ENTRY" in set(events["event_type"])
    assert "PAPER_EXIT" in set(events["event_type"])
    assert "EXTENSION_HIGH_RETESTED" in set(events.get("exit_reason", []))


def test_high_volume_first_retest_is_rejected(tmp_path: Path) -> None:
    summary = run(tmp_path, 400.0, pd.Timestamp("2026-08-24 11:00:00"))
    events = pd.read_csv(tmp_path / "results" / "event_log.csv")
    assert summary["signals_since_forward_start"] == 0
    assert "RETEST_REJECTED" in set(events["event_type"])


def test_incomplete_retest_bucket_is_not_used(tmp_path: Path) -> None:
    _, state3_time = synthetic_feature_file(tmp_path, 200.0)
    feature_path = tmp_path / "features.csv"
    output = tmp_path / "results"
    summary = scanner.run_scan(
        features=[feature_path],
        output=output,
        locked_rule=MODULE_PATH.with_name("LOCKED_RULE.json"),
        ledger_path=tmp_path / "ledger.json",
        forward_start=pd.Timestamp("2026-08-20 09:15:00"),
        as_of=state3_time + pd.Timedelta(minutes=2),
        max_stale_minutes=10_000,
    )
    assert summary["signals_since_forward_start"] == 0


def test_rule_file_cannot_drift(tmp_path: Path) -> None:
    changed = json.loads(MODULE_PATH.with_name("LOCKED_RULE.json").read_text(encoding="utf-8"))
    changed["parameters"]["extension_target_pct"] = 0.02
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    try:
        scanner.validate_locked_rule(path)
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("A changed locked rule must be rejected")
