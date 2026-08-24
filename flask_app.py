import os
import json
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from dotenv import load_dotenv

# Load env vars
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')

# ─── DB Connection Helper ─────────────────────────────────────────────────────
def get_db():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")
    return pymongo.MongoClient(uri)[db_name]

# ─── Data Loaders from breakout_scanner_ui.py ─────────────────────────────────
def load_data():
    try:
        col = get_db()["latest_snapshot"]
        cursor = col.find({}, {
            "symbol": 1, "spot_price": 1, "expiry": 1,
            "iv4": 1, "ce_iv_oi_weighted": 1, "pe_iv_oi_weighted": 1,
            "iv_skew": 1, "iv_ratio": 1, "ts_ist": 1,
            "iv4_change_5m": 1, "top_strike_iv_change_5m": 1
        })
        docs = list(cursor)
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
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor = col.find({
            "symbol": symbol,
            "ts_ist": { "$regex": f"^{today_str}" }
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
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor = col.find({
            "ts_ist": { "$regex": f"^{today_str}" }
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
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor = col.find({
            "ts_ist": { "$regex": f"^{today_str}" }
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


if __name__ == '__main__':
    # Streamlit ran on 8101, Flask will run on 8101 to replace it completely
    port = int(os.getenv("STREAMLIT_SERVER_PORT", 8101))
    print(f"Starting Flask trading terminal on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
