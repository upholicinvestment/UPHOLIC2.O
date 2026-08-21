#!/usr/bin/env python3
"""Read UPHOLIC2_O.snapshots and build the exact 5-minute feature schema
expected by Stock Breakout Retest IV Quiet Scanner v1.

This is data plumbing only. It does not alter the frozen scanner rules and it
never writes to MongoDB.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

FIELDS = [
    "source_id", "symbol", "security_id", "timestamp_ist", "bucket_ist", "trade_date", "expiry",
    "spot_price", "flip_distance_pct", "call_flow_slog", "put_flow_slog", "flow_balance",
    "ce_iv_oi_weighted", "pe_iv_oi_weighted", "iv4", "iv_skew", "iv_ratio",
    "iv4_change_5m", "top_strike_iv_change_5m", "near_ce_oi", "near_pe_oi",
    "near_total_oi", "near_ce_volume", "near_pe_volume", "near_total_volume",
    "near_oi_pcr", "near_volume_balance", "near_oi_change_balance", "near_premium_momentum",
    "near_iv_skew", "atm_ce_return", "atm_pe_return", "populated_contracts", "spot_first",
]


def finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def optional_finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def signed_log(value_: float) -> float:
    return float(np.sign(value_) * np.log1p(abs(value_)))


def parse_snapshot_ist(document: dict[str, Any]) -> datetime | None:
    text = document.get("ts_ist")
    if isinstance(text, str) and text.strip():
        cleaned = text.strip()
        if cleaned.endswith(" IST"):
            cleaned = cleaned[:-4]
        try:
            stamp = datetime.fromisoformat(cleaned)
            return stamp.replace(tzinfo=None)
        except ValueError:
            pass

    fetched = document.get("fetched_at")
    if isinstance(fetched, datetime):
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return fetched.astimezone(IST).replace(tzinfo=None)
    return None


def feature_from_snapshot(document: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = parse_snapshot_ist(document)
    spot = optional_finite(document.get("spot_price"))
    if timestamp is None or spot is None or spot <= 0:
        return None

    bucket = timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0, microsecond=0)
    flip = optional_finite(document.get("Flip_strike"))
    call_flow = finite(document.get("call_net_flow"))
    put_flow = finite(document.get("put_net_flow"))

    option_rows: list[dict[str, float | str]] = []
    options = document.get("options")
    if isinstance(options, list):
        for item in options:
            if not isinstance(item, dict):
                continue
            strike = optional_finite(item.get("strike"))
            kind = str(item.get("type", "")).strip().upper()
            if strike is None or kind not in {"CE", "PE"}:
                continue
            option_rows.append({
                "strike": strike,
                "type": kind,
                "ltp": finite(item.get("ltp")),
                "oi": finite(item.get("oi")),
                "iv": finite(item.get("iv")),
                "volume": finite(item.get("volume")),
                "previous_close": finite(item.get("previous_close_price")),
                "previous_oi": finite(item.get("previous_oi")),
                "previous_volume": finite(item.get("previous_volume")),
            })

    # EXACTLY matches the frozen feature builder: near chain = +/- 8% of spot.
    near = [item for item in option_rows if abs(float(item["strike"]) / spot - 1.0) <= 0.08]
    ce = [item for item in near if item["type"] == "CE"]
    pe = [item for item in near if item["type"] == "PE"]

    ce_oi = sum(float(item["oi"]) for item in ce)
    pe_oi = sum(float(item["oi"]) for item in pe)
    ce_volume_cumulative = sum(float(item["volume"]) for item in ce)
    pe_volume_cumulative = sum(float(item["volume"]) for item in pe)

    ce_volume = sum(max(float(item["volume"]) - float(item["previous_volume"]), 0.0) for item in ce)
    pe_volume = sum(max(float(item["volume"]) - float(item["previous_volume"]), 0.0) for item in pe)
    ce_oi_change = sum(float(item["oi"]) - float(item["previous_oi"]) for item in ce)
    pe_oi_change = sum(float(item["oi"]) - float(item["previous_oi"]) for item in pe)
    volume_denominator = ce_volume + pe_volume
    oi_change_denominator = abs(ce_oi_change) + abs(pe_oi_change)

    premium_returns = {
        kind: [
            (float(item["ltp"]) - float(item["previous_close"])) / float(item["previous_close"])
            for item in near
            if item["type"] == kind
            and float(item["previous_close"]) > 0
            and abs(float(item["strike"]) / spot - 1.0) <= 0.03
        ]
        for kind in ("CE", "PE")
    }

    iv_values = {
        kind: [float(item["iv"]) for item in near if item["type"] == kind and float(item["iv"]) > 0]
        for kind in ("CE", "PE")
    }

    atm: dict[str, dict[str, float | str] | None] = {}
    for kind in ("CE", "PE"):
        candidates = [item for item in option_rows if item["type"] == kind]
        atm[kind] = min(candidates, key=lambda item: abs(float(item["strike"]) - spot)) if candidates else None

    def atm_return(kind: str) -> float:
        item = atm[kind]
        if item is None or float(item["previous_close"]) <= 0:
            return 0.0
        return (float(item["ltp"]) - float(item["previous_close"])) / float(item["previous_close"])

    top_change = document.get("top_strike_iv_change_5m")
    if isinstance(top_change, dict):
        top_change_value = finite(top_change.get("change"))
    else:
        top_change_value = finite(top_change)

    return {
        "source_id": str(document.get("_id", "")),
        "symbol": str(document.get("symbol", "")).strip().upper(),
        "security_id": str(document.get("security_id", "")),
        "timestamp_ist": timestamp,
        "bucket_ist": bucket,
        "trade_date": timestamp.date().isoformat(),
        "expiry": str(document.get("expiry", "")),
        "spot_price": spot,
        "flip_distance_pct": (spot - flip) / spot if flip is not None else 0.0,
        "call_flow_slog": signed_log(call_flow),
        "put_flow_slog": signed_log(put_flow),
        "flow_balance": (call_flow - put_flow) / (abs(call_flow) + abs(put_flow)) if call_flow or put_flow else 0.0,
        "ce_iv_oi_weighted": finite(document.get("ce_iv_oi_weighted")),
        "pe_iv_oi_weighted": finite(document.get("pe_iv_oi_weighted")),
        "iv4": finite(document.get("iv4")),
        "iv_skew": finite(document.get("iv_skew")),
        "iv_ratio": finite(document.get("iv_ratio")),
        "iv4_change_5m": finite(document.get("iv4_change_5m")),
        "top_strike_iv_change_5m": top_change_value,
        "near_ce_oi": ce_oi,
        "near_pe_oi": pe_oi,
        "near_total_oi": ce_oi + pe_oi,
        "near_ce_volume": ce_volume_cumulative,
        "near_pe_volume": pe_volume_cumulative,
        "near_total_volume": ce_volume_cumulative + pe_volume_cumulative,
        "near_oi_pcr": pe_oi / ce_oi if ce_oi > 0 else 0.0,
        "near_volume_balance": (ce_volume - pe_volume) / volume_denominator if volume_denominator else 0.0,
        "near_oi_change_balance": (ce_oi_change - pe_oi_change) / oi_change_denominator if oi_change_denominator else 0.0,
        "near_premium_momentum": (np.mean(premium_returns["CE"]) if premium_returns["CE"] else 0.0)
        - (np.mean(premium_returns["PE"]) if premium_returns["PE"] else 0.0),
        "near_iv_skew": (np.mean(iv_values["PE"]) if iv_values["PE"] else 0.0)
        - (np.mean(iv_values["CE"]) if iv_values["CE"] else 0.0),
        "atm_ce_return": atm_return("CE"),
        "atm_pe_return": atm_return("PE"),
        "populated_contracts": len(option_rows),
    }


def aware_ist(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    return datetime.now(IST)


def utc_from_naive_ist(value: datetime) -> datetime:
    return value.replace(tzinfo=IST).astimezone(timezone.utc)


def read_existing(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=FIELDS)
    frame = pd.read_csv(path)
    if not frame.empty:
        frame["timestamp_ist"] = pd.to_datetime(frame["timestamp_ist"], format="mixed")
        frame["bucket_ist"] = pd.to_datetime(frame["bucket_ist"], format="mixed")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="mixed").dt.date.astype(str)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description="MongoDB -> frozen stock scanner 5-minute features")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-from", default="2026-08-18", help="IST date used only when output does not exist")
    parser.add_argument("--as-of", help="Optional IST cutoff, e.g. 2026-08-21 12:00:00")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    as_of_aware = aware_ist(args.as_of)
    as_of_naive = as_of_aware.replace(tzinfo=None)

    existing = pd.DataFrame(columns=FIELDS) if args.rebuild else read_existing(output)

    if existing.empty:
        query_start_naive = datetime.fromisoformat(f"{args.bootstrap_from} 00:00:00")
    else:
        # Re-read two complete buckets so a late snapshot can safely replace the latest rows.
        query_start_naive = pd.Timestamp(existing["bucket_ist"].max()).to_pydatetime() - pd.Timedelta(minutes=10)

    query_start_utc = utc_from_naive_ist(query_start_naive)
    query_end_utc = as_of_aware.astimezone(timezone.utc)

    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")

    projection = {
        "_id": 1,
        "fetched_at": 1,
        "ts_ist": 1,
        "symbol": 1,
        "security_id": 1,
        "expiry": 1,
        "spot_price": 1,
        "Flip_strike": 1,
        "call_net_flow": 1,
        "put_net_flow": 1,
        "ce_iv_oi_weighted": 1,
        "pe_iv_oi_weighted": 1,
        "iv4": 1,
        "iv_skew": 1,
        "iv_ratio": 1,
        "iv4_change_5m": 1,
        "top_strike_iv_change_5m": 1,
        "options": 1,
    }

    buckets: dict[tuple[str, str, datetime], dict[str, Any]] = {}
    snapshots_seen = 0

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        collection = client[db_name]["snapshots"]
        cursor = collection.find(
            {"fetched_at": {"$gte": query_start_utc, "$lte": query_end_utc}},
            projection,
        ).sort("fetched_at", 1).batch_size(200)

        for document in cursor:
            feature = feature_from_snapshot(document)
            if feature is None or not feature["symbol"]:
                continue
            bucket = feature["bucket_ist"]
            if bucket + pd.Timedelta(minutes=5) > as_of_naive:
                continue

            snapshots_seen += 1
            key = (feature["symbol"], feature["trade_date"], bucket)
            current = buckets.get(key)
            if current is None:
                buckets[key] = {
                    "first_time": feature["timestamp_ist"],
                    "first_spot": feature["spot_price"],
                    "last_time": feature["timestamp_ist"],
                    "row": feature,
                }
            else:
                if feature["timestamp_ist"] < current["first_time"]:
                    current["first_time"] = feature["timestamp_ist"]
                    current["first_spot"] = feature["spot_price"]
                if feature["timestamp_ist"] >= current["last_time"]:
                    current["last_time"] = feature["timestamp_ist"]
                    current["row"] = feature
    finally:
        client.close()

    new_rows: list[dict[str, Any]] = []
    for current in buckets.values():
        row = current["row"].copy()
        row["spot_first"] = current["first_spot"]
        new_rows.append(row)

    new_frame = pd.DataFrame(new_rows, columns=FIELDS)

    if not new_frame.empty:
        new_frame["timestamp_ist"] = pd.to_datetime(new_frame["timestamp_ist"])
        new_frame["bucket_ist"] = pd.to_datetime(new_frame["bucket_ist"])
        new_frame["trade_date"] = new_frame["trade_date"].astype(str)

        keys = ["symbol", "trade_date", "bucket_ist"]
        new_keys = set(map(tuple, new_frame[keys].itertuples(index=False, name=None)))
        if not existing.empty:
            keep_mask = [tuple(row) not in new_keys for row in existing[keys].itertuples(index=False, name=None)]
            existing = existing.loc[keep_mask]
        combined = pd.concat([existing, new_frame], ignore_index=True)
    else:
        combined = existing.copy()

    if combined.empty:
        raise RuntimeError("No completed five-minute feature rows are available.")

    combined["timestamp_ist"] = pd.to_datetime(combined["timestamp_ist"], format="mixed")
    combined["bucket_ist"] = pd.to_datetime(combined["bucket_ist"], format="mixed")
    combined["trade_date"] = pd.to_datetime(combined["trade_date"], format="mixed").dt.date.astype(str)
    combined = combined.drop_duplicates(["symbol", "trade_date", "bucket_ist"], keep="last")
    combined = combined.sort_values(["trade_date", "bucket_ist", "symbol"]).reset_index(drop=True)
    combined = combined.reindex(columns=FIELDS)

    partial = output.with_suffix(output.suffix + ".partial")
    combined.to_csv(partial, index=False)
    partial.replace(output)

    metadata = {
        "status": "DERIVED_READ_ONLY_SOURCE",
        "mongo_uri": mongo_uri,
        "database": db_name,
        "collection": "snapshots",
        "source_modified": False,
        "query_from_utc": query_start_utc.isoformat(),
        "query_to_utc": query_end_utc.isoformat(),
        "snapshots_seen_this_run": snapshots_seen,
        "five_minute_rows_total": int(len(combined)),
        "symbols": int(combined["symbol"].nunique()),
        "latest_bucket_ist": str(combined["bucket_ist"].max()),
        "output": str(output),
    }
    metadata_path = output.with_name("feature_metadata.json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
