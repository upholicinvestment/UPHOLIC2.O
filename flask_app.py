import os
import json
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from dotenv import load_dotenv

# Load env vars
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')

# ─── DB Connection Helper ─────────────────────────────────────────────────────
_mongo_client = None

def get_db():
    global _mongo_client
    if _mongo_client is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        _mongo_client = pymongo.MongoClient(uri, maxPoolSize=50, serverSelectionTimeoutMS=2000)
    db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")
    return _mongo_client[db_name]


# ─── Market Trading Date Helper ────────────────────────────────────────────────
def get_active_trading_date():
    """
    Returns the active trading date string (YYYY-MM-DD) according to Indian market rules:
    - On weekdays (Mon-Fri) AFTER 09:15 AM: STRICTLY Today's date (live session).
    - On weekdays (Mon-Fri) BEFORE 09:15 AM: Previous working trading day (yesterday, or Friday if Monday morning).
    - On weekends (Saturday/Sunday): Previous Friday (last completed working trading day).
    - After 15:30: Today's completed session data remains active until next day 09:15 AM.
    """
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    
    weekday = now_ist.weekday()  # 0=Mon, ..., 4=Fri, 5=Sat, 6=Sun
    time_min = now_ist.hour * 60 + now_ist.minute
    market_open_min = 9 * 60 + 15  # 09:15 AM IST
    
    if weekday == 5:  # Saturday -> Friday
        active_dt = now_ist - timedelta(days=1)
    elif weekday == 6:  # Sunday -> Friday
        active_dt = now_ist - timedelta(days=2)
    else:
        # Weekday (Mon-Fri)
        if time_min >= market_open_min:
            # AFTER 09:15 AM -> ALWAYS STRICTLY TODAY'S LIVE DATA
            active_dt = now_ist
        else:
            # Before 09:15 AM -> Last trading day (Friday if Mon, else yesterday)
            if weekday == 0:
                active_dt = now_ist - timedelta(days=3)
            else:
                active_dt = now_ist - timedelta(days=1)
                
    return active_dt.strftime("%Y-%m-%d")


def is_live_market_open():
    """Returns True if current time is within live market trading hours (Mon-Fri 09:15 - 15:40 IST)."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + timedelta(hours=5, minutes=30)
    if now_ist.weekday() >= 5:
        return False
    time_min = now_ist.hour * 60 + now_ist.minute
    return (9 * 60 + 15) <= time_min <= (15 * 60 + 40)


# ─── Data Loaders from breakout_scanner_ui.py ─────────────────────────────────
def load_data():
    try:
        active_date = get_active_trading_date()
        col = get_db()["latest_snapshot"]
        
        # If market is open (after 09:15 AM on weekday), filter strictly for today's snapshot
        query = {}
        if is_live_market_open():
            query["ts_ist"] = { "$regex": f"^{active_date}" }

        cursor = col.find(query, {
            "symbol": 1, "spot_price": 1, "expiry": 1,
            "iv4": 1, "ce_iv_oi_weighted": 1, "pe_iv_oi_weighted": 1,
            "iv_skew": 1, "iv_ratio": 1, "ts_ist": 1,
            "iv4_change_5m": 1, "top_strike_iv_change_5m": 1
        })
        docs = list(cursor)
        if not docs:
            # If no live docs yet for today during first minutes, fallback to latest
            docs = list(col.find({}, {
                "symbol": 1, "spot_price": 1, "expiry": 1,
                "iv4": 1, "ce_iv_oi_weighted": 1, "pe_iv_oi_weighted": 1,
                "iv_skew": 1, "iv_ratio": 1, "ts_ist": 1,
                "iv4_change_5m": 1, "top_strike_iv_change_5m": 1
            }))
        if not docs:
            return pd.DataFrame()
        df = pd.DataFrame(docs).drop(columns=["_id"], errors="ignore")
        
        df = df.rename(columns={
            "symbol": "underlying_symbol",
            "spot_price": "last_price"
        })
        
        required_columns = [
            "underlying_symbol", "last_price", "expiry", "iv4", 
            "ce_iv_oi_weighted", "pe_iv_oi_weighted", "iv_skew", 
            "iv_ratio", "ts_ist", "iv4_change_5m", "top_strike_iv_change_5m"
        ]
        for col_name in required_columns:
            if col_name not in df.columns:
                df[col_name] = 0.0 if col_name not in ["underlying_symbol", "expiry", "ts_ist", "top_strike_iv_change_5m"] else ""
        
        for c in ["last_price", "iv4", "ce_iv_oi_weighted", "pe_iv_oi_weighted", "iv_skew", "iv_ratio", "iv4_change_5m"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df = df.sort_values("iv4", ascending=False).reset_index(drop=True)
        df.insert(0, "rank", df.index + 1)
        return df
    except Exception as e:
        print(f"MongoDB error load_data: {e}")
        return pd.DataFrame()


def load_stock_history(symbol):
    try:
        col = get_db()["snapshots"]
        active_date = get_active_trading_date()
        cursor = col.find({
            "symbol": symbol,
            "ts_ist": { "$regex": f"^{active_date}" }
        }, {
            "iv4": 1, "ce_iv_oi_weighted": 1, "pe_iv_oi_weighted": 1, "ts_ist": 1
        }).sort("ts", 1)
        
        docs = list(cursor)
        if not docs:
            return pd.DataFrame()
        df_hist = pd.DataFrame(docs).drop(columns=["_id"], errors="ignore")
        
        for col_name in ["iv4", "ce_iv_oi_weighted", "pe_iv_oi_weighted", "ts_ist"]:
            if col_name not in df_hist.columns:
                df_hist[col_name] = 0.0 if col_name != "ts_ist" else ""
                
        for c in ["iv4", "ce_iv_oi_weighted", "pe_iv_oi_weighted"]:
            df_hist[c] = pd.to_numeric(df_hist[c], errors="coerce").fillna(0)
        return df_hist
    except Exception as e:
        print(f"MongoDB error load_stock_history: {e}")
        return pd.DataFrame()


def load_live_breakout_alerts_today():
    try:
        col = get_db()["v1_scanner_alerts"]
        active_date = get_active_trading_date()
        cursor = col.find({
            "ts_ist": { "$regex": f"^{active_date}" }
        }).sort("timestamp", -1)
        
        docs = list(cursor)
        if not docs:
            return []
            
        alerts = []
        for d in docs:
            alerts.append({
                "timestamp": d.get("ts_ist", ""),
                "symbol": d.get("symbol", ""),
                "timeframe": d.get("timeframe", "15m"),
                "direction": d.get("direction", ""),
                "spot": d.get("spot", 0.0),
                "details": d.get("details", ""),
                "mode": d.get("mode", "INTRADAY")
            })
        return alerts
    except Exception as e:
        print(f"MongoDB error load_live_breakout_alerts_today: {e}")
        return []


def load_live_v2_alerts_today():
    try:
        col = get_db()["v2_scanner_alerts"]
        active_date = get_active_trading_date()
        cursor = col.find({
            "ts_ist": { "$regex": f"^{active_date}" }
        }).sort("timestamp", -1)
        
        docs = list(cursor)
        if not docs:
            return []
            
        alerts = []
        for d in docs:
            alerts.append({
                "timestamp": d.get("ts_ist", ""),
                "symbol": d.get("symbol", ""),
                "timeframe": d.get("timeframe", "15m"),
                "direction": d.get("direction", ""),
                "spot": d.get("spot", 0.0),
                "details": d.get("details", ""),
                "mode": d.get("mode", "INTRADAY")
            })
        return alerts
    except Exception as e:
        print(f"MongoDB error load_live_v2_alerts_today: {e}")
        return []
        return alerts
    except Exception as e:
        print(f"MongoDB error load_live_v2_alerts_today: {e}")
        return []


def load_live_breakout_scanner_alerts_today():
    try:
        col = get_db()["breakoutscanner_alerts"]
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor = col.find({
            "ts_ist": { "$regex": f"^{today_str}" }
        }).sort("fetched_at", -1)
        
        docs = list(cursor)
        if not docs:
            return []
            
        alerts = []
        for d in docs:
            alerts.append({
                "timestamp": d.get("ts_ist", ""),
                "symbol": d.get("symbol", ""),
                "edge_signal": d.get("edge_signal", ""),
                "spot_price": d.get("spot_price", 0.0),
                "iv_ratio": d.get("iv_ratio", 0.0),
                "iv_skew": d.get("iv_skew", 0.0),
                "vw_iv_call": d.get("vw_iv_call", 0.0),
                "vw_iv_put": d.get("vw_iv_put", 0.0),
                "call_flow_net": d.get("call_flow_net", 0.0),
                "put_flow_net": d.get("put_flow_net", 0.0)
            })
        return alerts
    except Exception as e:
        print(f"MongoDB error load_live_breakout_scanner_alerts_today: {e}")
        return []


def load_breakout_scanner_alerts_by_date(date_str):
    try:
        col = get_db()["breakoutscanner_alerts"]
        cursor = col.find({
            "ts_ist": { "$regex": f"^{date_str}" }
        }).sort("fetched_at", -1)
        
        docs = list(cursor)
        if not docs:
            return []
            
        alerts = []
        for d in docs:
            alerts.append({
                "timestamp": d.get("ts_ist", ""),
                "symbol": d.get("symbol", ""),
                "edge_signal": d.get("edge_signal", ""),
                "spot_price": d.get("spot_price", 0.0),
                "iv_ratio": d.get("iv_ratio", 0.0),
                "iv_skew": d.get("iv_skew", 0.0),
                "vw_iv_call": d.get("vw_iv_call", 0.0),
                "vw_iv_put": d.get("vw_iv_put", 0.0),
                "call_flow_net": d.get("call_flow_net", 0.0),
                "put_flow_net": d.get("put_flow_net", 0.0)
            })
        return alerts
    except Exception as e:
        print(f"MongoDB error load_breakout_scanner_alerts_by_date: {e}")
        return []


def load_alerts_by_date(date_str, collection_name="v1_scanner_alerts"):
    try:
        col = get_db()[collection_name]
        cursor = col.find({
            "ts_ist": { "$regex": f"^{date_str}" }
        }).sort("timestamp", -1)
        docs = list(cursor)
        if not docs:
            return []
        alerts = []
        if collection_name == "poi_scanner_alerts":
            for d in docs:
                alerts.append({
                    "Alert Time (IST)": d.get("ts_ist", ""),
                    "Symbol": d.get("symbol", ""),
                    "Spot Price": d.get("spot_price", 0.0),
                    "Price Change %": d.get("price_change_pct", 0.0),
                    "Price Change": d.get("price_change", 0.0),
                    "Total OI": d.get("total_oi", 0),
                    "OI Change %": d.get("oi_change_pct", 0.0),
                    "OI Change": d.get("oi_change", 0),
                    "Market Sentiment": d.get("label", ""),
                    "Quadrant": d.get("quadrant", ""),
                    "PCR": d.get("pcr", 0.0),
                    "Top Strike Driver": d.get("top_strike", "")
                })
        else:
            for d in docs:
                alerts.append({
                    "timestamp": d.get("ts_ist", ""),
                    "symbol": d.get("symbol", ""),
                    "timeframe": d.get("timeframe", "15m"),
                    "direction": d.get("direction", ""),
                    "spot": d.get("spot", 0.0),
                    "details": d.get("details", ""),
                    "mode": d.get("mode", "INTRADAY")
                })
        return alerts
    except Exception as e:
        print(f"MongoDB error load_alerts_by_date: {e}")
        return []


# ─── Frozen Retest Results Loading ────────────────────────────────────────────
ubuntu_path = Path("/home/ubuntu/UPHOLIC2.O/scanners/stock_breakout_retest_iv_quiet_v1/runtime/results")
local_path = Path("scanners/stock_breakout_retest_iv_quiet_v1/runtime/results")
FROZEN_SCANNER_RESULTS_DIR = ubuntu_path if ubuntu_path.exists() else local_path

def _read_frozen_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _frozen_records_json_safe(frame: pd.DataFrame) -> list:
    """Convert a DataFrame to strict browser-safe JSON records.

    pandas DataFrames may contain NaN/Infinity values after reading sparse CSVs.
    JSON sent to browsers must use null for those values.
    """
    if frame is None or frame.empty:
        return []

    return json.loads(
        frame.to_json(
            orient="records",
            date_format="iso",
        )
    )


def load_frozen_retest_results():
    root = FROZEN_SCANNER_RESULTS_DIR
    summary = {}
    summary_path = root / "scanner_summary.json"
    try:
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary = {"_load_error": str(exc)}

    return {
        "summary": summary,
        "new_signals": _read_frozen_csv(root / "new_signals_this_run.csv"),
        "forward_signals": _read_frozen_csv(root / "forward_signals.csv"),
        "states": _read_frozen_csv(root / "current_states.csv"),
        "trades": _read_frozen_csv(root / "paper_trade_events.csv"),
        "events": _read_frozen_csv(root / "event_log.csv"),
    }


def load_spikes_by_date_range(start_date_str, end_date_str):
    try:
        col = get_db()["iv4_spikes"]
        start_query = f"{start_date_str} 00:00:00"
        end_query = f"{end_date_str} 23:59:59"
        cursor = col.find({
            "ts_ist": { "$gte": start_query, "$lte": end_query }
        }, {
            "options": 0
        }).sort("fetched_at", -1)
        docs = list(cursor)
        if not docs:
            return pd.DataFrame()
        df_spikes = pd.DataFrame(docs).drop(columns=["_id"], errors="ignore")
        df_spikes = df_spikes.rename(columns={
            "symbol": "underlying_symbol",
            "spot_price": "last_price"
        })
        return df_spikes
    except Exception as e:
        print(f"MongoDB error load_spikes_by_date_range: {e}")
        return pd.DataFrame()


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/overview')
def get_overview():
    df = load_data()
    if df.empty:
        return jsonify({
            "total": 0, "highest_iv": 0.0, "avg_iv": 0.0, "high_vol_count": 0, "ts_ist": "—"
        })
    total = len(df)
    ts_str = df.iloc[0]["ts_ist"] if "ts_ist" in df.columns else "—"
    avg_iv4 = round(df["iv4"].mean(), 2)
    high_iv4 = round(df["iv4"].max(), 2)
    high_vol_count = int(len(df[df["iv4"] >= 30]))
    return jsonify({
        "total": total,
        "highest_iv": high_iv4,
        "avg_iv": avg_iv4,
        "high_vol_count": high_vol_count,
        "ts_ist": ts_str
    })


@app.route('/api/leaderboard')
def get_leaderboard():
    df = load_data()
    if df.empty:
        return jsonify([])
        
    search = request.args.get('search', '').strip().upper()
    limit = int(request.args.get('limit', 50))
    min_iv = float(request.args.get('min_iv', 0.0))
    
    filtered = df.copy()
    if search:
        filtered = filtered[filtered["underlying_symbol"].str.contains(search, na=False)]
    if min_iv > 0:
        filtered = filtered[filtered["iv4"] >= min_iv]
        
    filtered = filtered.head(limit)
    return jsonify(filtered.to_dict(orient='records'))


@app.route('/api/movers')
def get_movers():
    df = load_data()
    if df.empty:
        return jsonify({"spikes": [], "crushes": []})
        
    change_df = df[df["iv4_change_5m"] != 0].copy()
    
    spikes = []
    crushes = []
    if not change_df.empty:
        spikes_df = change_df[change_df["iv4_change_5m"] > 0].sort_values("iv4_change_5m", ascending=False).head(5)
        spikes = spikes_df.to_dict(orient='records')
        
        crushes_df = change_df[change_df["iv4_change_5m"] < 0].sort_values("iv4_change_5m", ascending=True).head(5)
        crushes = crushes_df.to_dict(orient='records')
        
    return jsonify({
        "spikes": spikes,
        "crushes": crushes
    })


@app.route('/api/history/<symbol>')
def get_history(symbol):
    df_hist = load_stock_history(symbol)
    if df_hist.empty:
        return jsonify([])
    return jsonify(df_hist.to_dict(orient='records'))


@app.route('/api/alerts/v1')
def get_alerts_v1():
    date_str = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    alerts = load_alerts_by_date(date_str, "v1_scanner_alerts")
    return jsonify(alerts)


@app.route('/api/alerts/v2')
def get_alerts_v2():
    date_str = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    alerts = load_alerts_by_date(date_str, "v2_scanner_alerts")
    return jsonify(alerts)


@app.route('/api/alerts/breakout')
def get_alerts_breakout():
    date_str = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    alerts = load_breakout_scanner_alerts_by_date(date_str)
    return jsonify(alerts)


@app.route('/api/frozen/summary')
def get_frozen_summary():
    payload = load_frozen_retest_results()
    
    # Convert pandas DataFrames to strict browser-safe JSON records.
    out = {
        "summary": payload["summary"],
        "new_signals": _frozen_records_json_safe(payload["new_signals"]),
        "forward_signals": _frozen_records_json_safe(payload["forward_signals"]),
        "states": _frozen_records_json_safe(payload["states"]),
        "trades": _frozen_records_json_safe(payload["trades"]),
        "events": _frozen_records_json_safe(payload["events"])
    }
    return jsonify(out)


@app.route('/api/alerts/clear', methods=['POST'])
def clear_alerts():
    data = request.json or {}
    collection = data.get("collection")
    mode_filter = data.get("mode")
    
    if not collection:
        return jsonify({"status": "error", "message": "Missing collection parameter"}), 400
        
    try:
        col = get_db()[collection]
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        query = {"ts_ist": { "$regex": f"^{today_str}" }}
        if mode_filter:
            query["mode"] = mode_filter
            
        col.delete_many(query)
        return jsonify({"status": "success", "message": "Alerts cleared successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/alerts/download')
def download_alerts():
    collection = request.args.get('collection')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    mode_filter = request.args.get('mode')
    
    if not collection or not start_date or not end_date:
        return "Missing parameters", 400
        
    try:
        dl_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        dl_end = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        all_alerts = []
        cur_date = dl_start
        while cur_date <= dl_end:
            date_str = cur_date.strftime("%Y-%m-%d")
            day_alerts = load_alerts_by_date(date_str, collection)
            if mode_filter:
                day_alerts = [a for a in day_alerts if a.get("mode") == mode_filter]
            all_alerts.extend(day_alerts)
            cur_date += timedelta(days=1)
            
        if not all_alerts:
            return "No alerts found in selected range", 404
            
        df_dl = pd.DataFrame(all_alerts)
        csv_path = Path("temp_alerts.csv")
        df_dl.to_csv(csv_path, index=False)
        
        return send_file(
            csv_path,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{collection}_export.csv"
        )
    except Exception as e:
        return str(e), 500


# ─── Price & OI Combination Scanner Data Loader & API ─────────────────────────

def load_price_oi_scanner_data(date_str=None):
    """
    Sub-10ms High-Speed Price & OI Scanner Data Loader.
    Strictly queries indexed poi_scanner_alerts for target_date.
    If no alerts exist for that date, returns a clean empty list.
    """
    try:
        db = get_db()
        active_date = get_active_trading_date()
        target_date = date_str if date_str else active_date

        alerts_col = db["poi_scanner_alerts"]
        
        # Query strictly for target_date
        query = {"ts_ist": {"$regex": f"^{target_date}"}}
        db_alerts = list(alerts_col.find(query, {"_id": 0}).sort("timestamp", -1).limit(100))

        summary = {
            "total": len(db_alerts),
            "long_buildup": len([a for a in db_alerts if a.get("quadrant") == "LONG_BUILDUP"]),
            "short_covering": len([a for a in db_alerts if a.get("quadrant") == "SHORT_COVERING"]),
            "short_buildup": len([a for a in db_alerts if a.get("quadrant") == "SHORT_BUILDUP"]),
            "long_unwinding": len([a for a in db_alerts if a.get("quadrant") == "LONG_UNWINDING"]),
        }
        return {"summary": summary, "items": db_alerts}

    except Exception as e:
        print(f"MongoDB error load_price_oi_scanner_data: {e}")
        return {"summary": {"total": 0, "long_buildup": 0, "short_covering": 0, "short_buildup": 0, "long_unwinding": 0}, "items": []}

    except Exception as e:
        print(f"MongoDB error load_price_oi_scanner_data: {e}")
        return {"summary": {"total": 0, "long_buildup": 0, "short_covering": 0, "short_buildup": 0, "long_unwinding": 0}, "items": []}


@app.route('/api/scanners/price-oi')
def get_price_oi_scanner():
    date_str = request.args.get('date', '').strip()
    data = load_price_oi_scanner_data(date_str)
    
    category = request.args.get('category', '').strip().upper()
    search = request.args.get('search', '').strip().upper()
    min_oi = float(request.args.get('min_oi', 0.0))
    
    items = data["items"]
    if category:
        items = [x for x in items if x["quadrant"] == category]
    if search:
        items = [x for x in items if search in x["symbol"]]
    if min_oi > 0:
        items = [x for x in items if abs(x["oi_change_pct"]) >= min_oi]
        
    return jsonify({
        "summary": data["summary"],
        "items": items
    })


@app.route('/api/scanners/price-oi/download')
def download_price_oi_scanner():
    date_str = request.args.get('date', '').strip()
    data = load_price_oi_scanner_data(date_str)
    items = data.get('items', [])
    
    if not items:
        return "No alerts found for selected date", 404
        
    df = pd.DataFrame(items)
    column_mapping = {
        'ts_ist': 'Alert Time (IST)',
        'symbol': 'Symbol',
        'label': 'Sentiment / Quadrant',
        'spot_price': 'Spot Price (₹)',
        'price_change': 'Price Change (₹)',
        'price_change_pct': 'Price Change %',
        'total_oi': 'Total Open Interest',
        'oi_change': 'OI Change (Contracts)',
        'oi_change_pct': 'OI Change %',
        'call_oi': 'Total Call OI',
        'put_oi': 'Total Put OI',
        'pcr': 'PCR',
        'top_strike': 'Top Strike Driver'
    }
    cols_to_keep = [c for c in column_mapping.keys() if c in df.columns]
    df_export = df[cols_to_keep].rename(columns=column_mapping)
    
    csv_path = Path("Price_OI_Alerts_Export.csv")
    df_export.to_csv(csv_path, index=False)
    
    filename = f"Price_OI_Alerts_{date_str or 'Today'}.csv"
    return send_file(
        csv_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


if __name__ == '__main__':
    port = int(os.getenv("STREAMLIT_SERVER_PORT", 8101))
    print(f"Starting Flask trading terminal on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
