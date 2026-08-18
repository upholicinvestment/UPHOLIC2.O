import streamlit as st
import pymongo
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os
from datetime import datetime, timedelta, timezone
from streamlit_autorefresh import st_autorefresh
from dotenv import load_dotenv

load_dotenv()  # Load MONGO_URI, MONGO_DB etc. from .env

st.set_page_config(
    page_title="Upholic | IV4 Leaderboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def is_market_open():
    # India is UTC +5:30
    tz_india = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(tz_india)
    
    # Weekday check (0=Monday, 4=Friday, 5=Saturday, 6=Sunday)
    if now_ist.weekday() >= 5:
        return False
        
    # Time check (9:15 AM to 3:40 PM IST)
    market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now_ist.replace(hour=15, minute=40, second=0, microsecond=0)
    
    return market_open <= now_ist <= market_close

# Autorefresh the dashboard every 5 seconds to load instant updates without manual refresh (only during market hours)
if is_market_open():
    st_autorefresh(interval=5000, key="alerts_log_refresher")

# Initialize Session State for Alert Log
if "live_alerts_log" not in st.session_state:
    st.session_state["live_alerts_log"] = []
if "toasted_alerts" not in st.session_state:
    st.session_state["toasted_alerts"] = set()
if "live_v2_alerts_log" not in st.session_state:
    st.session_state["live_v2_alerts_log"] = []
if "toasted_v2_alerts" not in st.session_state:
    st.session_state["toasted_v2_alerts"] = set()
if "session_start_time" not in st.session_state:
    st.session_state["session_start_time"] = datetime.now() - timedelta(seconds=15)

# ─── Premium CSS ──────────────────────────────────────────────────────────────
st.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
}
.stApp {
    background: #060b14 !important;
}
.main .block-container {
    padding: 1.5rem 2.5rem 3rem !important;
    max-width: 1600px !important;
}
header[data-testid="stHeader"] { background: transparent !important; }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, .stDeployButton { display: none !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0d1117; }
::-webkit-scrollbar-thumb { background: #2a3a5c; border-radius: 3px; }

/* ── Top header banner ── */
.header-banner {
    background: linear-gradient(135deg, #0f1f3d 0%, #0c1628 50%, #06101e 100%);
    border: 1px solid rgba(59,130,246,0.2);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.header-title {
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(90deg, #60a5fa, #a78bfa, #34d399);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
    margin: 0;
}
.header-sub {
    color: #64748b;
    font-size: 0.85rem;
    margin-top: 4px;
}
.header-badge {
    background: rgba(34,197,94,0.12);
    border: 1px solid rgba(34,197,94,0.3);
    color: #22c55e;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 4px 14px;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.pulse-dot {
    width: 8px; height: 8px;
    background: #22c55e;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
    display: inline-block;
}
@keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
    70%  { box-shadow: 0 0 0 6px rgba(34,197,94,0); }
    100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
}

/* ── Rank cards ── */
.rank-card {
    background: linear-gradient(145deg, #0f1e38, #0a1628);
    border-radius: 16px;
    padding: 22px 26px;
    border: 1px solid rgba(255,255,255,0.07);
    height: 100%;
    position: relative;
    overflow: hidden;
    transition: transform 0.2s, border-color 0.2s;
}
.rank-card:hover { transform: translateY(-2px); }
.rank-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
}
.rank-card.gold::before  { background: linear-gradient(90deg, #f59e0b, #fbbf24); border-color: rgba(245,158,11,0.3); }
.rank-card.silver::before{ background: linear-gradient(90deg, #94a3b8, #cbd5e1); }
.rank-card.bronze::before{ background: linear-gradient(90deg, #cd7f32, #d97706); }
.rank-card.gold   { border-color: rgba(245,158,11,0.25); }
.rank-card.silver { border-color: rgba(148,163,184,0.25); }
.rank-card.bronze { border-color: rgba(205,127,50,0.25); }

.rank-medal { font-size: 1.6rem; line-height: 1; }
.rank-symbol {
    font-size: 1.35rem;
    font-weight: 700;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.5px;
    margin: 6px 0 2px;
}
.rank-iv4 {
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -1px;
    line-height: 1;
    margin: 6px 0;
}
.rank-card.gold   .rank-iv4 { color: #fbbf24; }
.rank-card.silver .rank-iv4 { color: #cbd5e1; }
.rank-card.bronze .rank-iv4 { color: #d97706; }
.rank-sub {
    display: flex;
    gap: 16px;
    margin-top: 12px;
    flex-wrap: wrap;
}
.rank-pill {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 0.72rem;
    color: #94a3b8;
    font-family: 'JetBrains Mono', monospace;
}
.rank-pill span { color: #e2e8f0; font-weight: 600; }
.rank-watermark {
    position: absolute;
    right: 20px;
    bottom: 14px;
    font-size: 4rem;
    font-weight: 900;
    opacity: 0.04;
    color: #fff;
    font-family: 'Inter', sans-serif;
    line-height: 1;
}

/* ── Section label ── */
.section-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #475569;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.05);
}

/* ── Stats strip ── */
.stats-strip {
    display: flex;
    gap: 16px;
    margin-bottom: 28px;
}
.stat-box {
    flex: 1;
    background: #0d1625;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 16px 20px;
    text-align: center;
}
.stat-num {
    font-size: 1.6rem;
    font-weight: 700;
    color: #60a5fa;
    font-family: 'JetBrains Mono', monospace;
}
.stat-lbl {
    font-size: 0.72rem;
    color: #64748b;
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

/* ── Chart container ── */
.chart-card {
    background: #0d1625;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px;
    padding: 4px;
    margin-bottom: 20px;
}

/* ── Filter bar ── */
.filter-bar {
    background: #0d1625;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 24px;
}
.stTextInput > div > div > input {
    background: #060b14 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.9rem !important;
}
.stTextInput > div > div > input:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 2px rgba(59,130,246,0.15) !important;
}
label[data-testid="stWidgetLabel"] {
    color: #64748b !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.8px !important;
    text-transform: uppercase !important;
}
.stNumberInput > div > div > input {
    background: #060b14 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #e2e8f0 !important;
    font-family: 'JetBrains Mono', monospace !important;
    border-radius: 8px !important;
}

/* ── Refresh button ── */
.stButton > button {
    background: linear-gradient(135deg, #1e3a5f, #1e3070) !important;
    color: #93c5fd !important;
    border: 1px solid rgba(59,130,246,0.35) !important;
    border-radius: 8px !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    padding: 6px 18px !important;
    letter-spacing: 0.5px !important;
    transition: all 0.15s !important;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #2a4a7f, #2a3d80) !important;
    border-color: rgba(96,165,250,0.6) !important;
    color: #bfdbfe !important;
}

/* ── Table ── */
.iv4-table { width: 100%; border-collapse: collapse; }
.iv4-table th {
    background: #060b14;
    color: #475569;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 12px 14px;
    text-align: right;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.iv4-table th:first-child, .iv4-table th:nth-child(2) { text-align: left; }
.iv4-table td {
    padding: 10px 14px;
    font-size: 0.82rem;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    text-align: right;
    color: #cbd5e1;
    font-family: 'JetBrains Mono', monospace;
}
.iv4-table td:first-child { text-align: center; }
.iv4-table td:nth-child(2) { text-align: left; font-weight: 600; color: #e2e8f0; }
.iv4-table tr:hover td { background: rgba(255,255,255,0.025); }
.iv4-table tr:last-child td { border-bottom: none; }
.rank-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    font-size: 0.72rem;
    font-weight: 700;
}
.rank-top3 { background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); }
.rank-top10 { background: rgba(96,165,250,0.1); color: #60a5fa; border: 1px solid rgba(96,165,250,0.2); }
.rank-rest  { background: rgba(255,255,255,0.05); color: #64748b; border: 1px solid rgba(255,255,255,0.07); }
.iv4-val { color: #34d399; font-weight: 700; }
.iv4-low { color: #f87171; font-weight: 700; }
.ce-iv { color: #60a5fa; }
.pe-iv { color: #f472b6; }
.skew-pos { color: #f87171; }
.skew-neg { color: #34d399; }

/* ── Breakout Signals ── */
.sig-bullish { color: #34d399 !important; font-weight: 700; }
.sig-bearish { color: #f87171 !important; font-weight: 700; }
.sig-squeeze { color: #60a5fa !important; font-weight: 700; }
.sig-covering { color: #a78bfa !important; font-weight: 700; }
.sig-neutral { color: #64748b !important; }

/* ── Streamlit dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: 12px !important;
    overflow: hidden !important;
}

/* ── Tabs design ── */
button[data-baseweb="tab"] {
    font-size: 0.9rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    color: #64748b !important;
    background: transparent !important;
    border: none !important;
    padding: 10px 20px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #60a5fa !important;
    border-bottom: 2px solid #3b82f6 !important;
}
</style>
""")


# ─── DB Helper ────────────────────────────────────────────────────────────────
@st.cache_resource
def get_db():
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")
    return pymongo.MongoClient(uri)[db_name]


@st.cache_data(ttl=30)
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
        
        # Rename keys to align with dashboard legacy names
        df = df.rename(columns={
            "symbol": "underlying_symbol",
            "spot_price": "last_price"
        })
        
        # Ensure all required columns exist to prevent KeyError
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
        st.error(f"MongoDB error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=30)
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
        
        # Ensure all required columns exist to prevent KeyError
        for col_name in ["iv4", "ce_iv_oi_weighted", "pe_iv_oi_weighted", "ts_ist"]:
            if col_name not in df_hist.columns:
                df_hist[col_name] = 0.0 if col_name != "ts_ist" else ""
                
        for c in ["iv4", "ce_iv_oi_weighted", "pe_iv_oi_weighted"]:
            df_hist[c] = pd.to_numeric(df_hist[c], errors="coerce").fillna(0)
        return df_hist
    except Exception as e:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_all_stocks_history_today():
    try:
        col = get_db()["snapshots"]
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor = col.find({
            "ts_ist": { "$regex": f"^{today_str}" }
        }, {
            "symbol": 1, "spot_price": 1, "call_net_flow": 1, 
            "put_net_flow": 1, "iv_ratio": 1, "Flip_strike": 1, "ts_ist": 1
        }).sort("ts", 1)
        
        docs = list(cursor)
        if not docs:
            return pd.DataFrame(columns=["timestamp", "symbol", "spot", "call_net_flow", "put_net_flow", "iv_ratio", "Flip_strike"])
            
        df_hist = pd.DataFrame(docs).drop(columns=["_id"], errors="ignore")
        
        # Ensure all columns exist to prevent KeyError on old schemas
        for col_name in ["symbol", "spot_price", "call_net_flow", "put_net_flow", "iv_ratio", "Flip_strike", "ts_ist"]:
            if col_name not in df_hist.columns:
                df_hist[col_name] = 0.0 if col_name != "symbol" and col_name != "ts_ist" else ""
                
        df_hist = df_hist.rename(columns={
            "ts_ist": "timestamp",
            "symbol": "symbol",
            "spot_price": "spot"
        })
        
        required_cols = ["timestamp", "symbol", "spot", "call_net_flow", "put_net_flow", "iv_ratio", "Flip_strike"]
        df_hist = df_hist[required_cols]
        
        for c in ["spot", "call_net_flow", "put_net_flow", "iv_ratio", "Flip_strike"]:
            df_hist[c] = pd.to_numeric(df_hist[c], errors="coerce").fillna(0.0)
        return df_hist
    except Exception as e:
        st.error(f"Error loading stock history: {e}")
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
            t_ist = d.get("ts_ist", "")
            alerts.append({
                "timestamp": t_ist,
                "symbol": d.get("symbol", ""),
                "timeframe": d.get("timeframe", "15m"),
                "direction": d.get("direction", ""),
                "spot": d.get("spot", 0.0),
                "details": d.get("details", ""),
                "mode": d.get("mode", "INTRADAY")
            })
        return alerts
    except Exception as e:
        st.error(f"Error loading live alerts: {e}")
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
            t_ist = d.get("ts_ist", "")
            alerts.append({
                "timestamp": t_ist,
                "symbol": d.get("symbol", ""),
                "timeframe": d.get("timeframe", "15m"),
                "direction": d.get("direction", ""),
                "spot": d.get("spot", 0.0),
                "details": d.get("details", ""),
                "mode": d.get("mode", "INTRADAY")
            })
        return alerts
    except Exception as e:
        st.error(f"Error loading live V2 alerts: {e}")
        return []


def iv4_color(v):
    if v >= 40:   return "#f87171"
    elif v >= 25: return "#fbbf24"
    elif v >= 15: return "#34d399"
    return "#64748b"


# ─── Algorithmic Breakout Formulas ──────────────────────────────────────────
def calculate_iv_edge(df_options, spot_price, otm_threshold_pct=1.5):
    calls = df_options[df_options['type'] == 'CE'].copy()
    puts = df_options[df_options['type'] == 'PE'].copy()
    
    otm_call_strike = spot_price * (1 + (otm_threshold_pct / 100))
    otm_put_strike = spot_price * (1 - (otm_threshold_pct / 100))
    
    otm_calls = calls[calls['strike'] >= otm_call_strike].copy()
    otm_puts = puts[puts['strike'] <= otm_put_strike].copy()
    
    vw_iv_call = np.average(otm_calls['iv'], weights=otm_calls['volume']) if not otm_calls.empty and otm_calls['volume'].sum() > 0 else 0
    vw_iv_put = np.average(otm_puts['iv'], weights=otm_puts['volume']) if not otm_puts.empty and otm_puts['volume'].sum() > 0 else 0
    
    iv_ratio = vw_iv_call / vw_iv_put if vw_iv_put > 0 else 0
    iv_skew = vw_iv_put - vw_iv_call 
    
    otm_calls['net_flow'] = otm_calls['oi_change'] * otm_calls['premium_change']
    otm_puts['net_flow'] = otm_puts['oi_change'] * otm_puts['premium_change']
    
    call_flow_momentum = otm_calls['net_flow'].sum()
    put_flow_momentum = otm_puts['net_flow'].sum()
    
    signal = "NEUTRAL"
    if iv_ratio > 1.2 and call_flow_momentum > 0:
        signal = "BULLISH DIVERGENCE (Call IV Expanding + Premium Build)"
    elif iv_ratio < 0.8 and put_flow_momentum > 0:
        signal = "BEARISH DIVERGENCE (Put IV Expanding + Put Premium Build)"
    elif iv_ratio > 1.2 and call_flow_momentum < 0:
        signal = "CALL SHORT-COVERING SQUEEZE (Call IV Expanding + Premium Unwind)"
    elif iv_ratio < 0.8 and put_flow_momentum < 0:
        signal = "PUT SHORT-COVERING (Put IV Expanding + Put Premium Unwind)"
        
    return {
        "spot_price": spot_price,
        "vw_iv_call": round(vw_iv_call, 2),
        "vw_iv_put": round(vw_iv_put, 2),
        "iv_ratio": round(iv_ratio, 3),
        "iv_skew": round(iv_skew, 2),
        "call_flow_net": round(call_flow_momentum, 2),
        "put_flow_net": round(put_flow_momentum, 2),
        "edge_signal": signal
    }


def run_market_scanner(df_market_snapshot):
    results = []
    tickers = df_market_snapshot['symbol'].unique()
    for ticker in tickers:
        ticker_data = df_market_snapshot[df_market_snapshot['symbol'] == ticker]
        current_spot = ticker_data['spot_close'].iloc[0] 
        edge = calculate_iv_edge(ticker_data, current_spot)
        edge['symbol'] = ticker
        results.append(edge)
        
    df_signals = pd.DataFrame(results)
    if df_signals.empty:
        return pd.DataFrame()
    cols = ['symbol', 'edge_signal', 'spot_price', 'iv_ratio', 'iv_skew', 'vw_iv_call', 'vw_iv_put', 'call_flow_net', 'put_flow_net']
    df_signals = df_signals[cols]
    return df_signals.sort_values(by='iv_ratio', ascending=False)


def parse_db_options_df(doc):
    rows = []
    symbol = doc.get("symbol")
    spot_price = doc.get("spot_price", 0)
    options = doc.get("options", [])
    if not isinstance(options, list):
        return pd.DataFrame()
        
    for item in options:
        strike = item.get("strike")
        opt_type = item.get("type")
        if not strike or not opt_type:
            continue
            
        iv = item.get("iv") or 0
        oi = item.get("oi") or 0
        prev_oi = item.get("previous_oi") or 0
        volume = item.get("volume") or 0
        last_price = item.get("ltp") or 0
        prev_close = item.get("previous_close_price") or 0
        
        oi_change = oi - prev_oi
        premium_change = last_price - prev_close
        
        rows.append({
            "symbol": symbol,
            "strike": strike,
            "type": opt_type,
            "iv": iv,
            "volume": volume,
            "oi_change": oi_change,
            "premium_change": premium_change,
            "spot_close": spot_price
        })
            
    return pd.DataFrame(rows)


@st.cache_data(ttl=30)
def load_breakout_signals():
    try:
        col = get_db()["latest_snapshot"]
        docs = list(col.find({}, {
            "symbol": 1, "spot_price": 1, "options": 1
        }))
        if not docs:
            return pd.DataFrame()
            
        all_rows = []
        for doc in docs:
            df_opt = parse_db_options_df(doc)
            if not df_opt.empty:
                all_rows.append(df_opt)
                
        if not all_rows:
            return pd.DataFrame()
            
        df_snapshot = pd.concat(all_rows, ignore_index=True)
        return run_market_scanner(df_snapshot)
    except Exception as e:
        st.error(f"Signal scanner error: {e}")
        return pd.DataFrame()


# ─── Refresh ──────────────────────────────────────────────────────────────────
if st.button("⟳  Refresh"):
    st.cache_data.clear()
    st.rerun()

df = load_data()

# Load live alerts from MongoDB (directly generated by backend stock-by-stock)
db_alerts = load_live_breakout_alerts_today()
db_v2_alerts = load_live_v2_alerts_today()

# Check and toast new V1 alerts (process oldest to newest so newest toast appears on top)
for a in reversed(db_alerts):
    alert_key = f"{a['symbol']}_{a['direction']}_{a['timestamp']}"
    if alert_key not in st.session_state["toasted_alerts"]:
        st.session_state["toasted_alerts"].add(alert_key)
        
        # Parse alert timestamp to compare with session start time
        alert_dt = None
        try:
            t_clean = a['timestamp'].replace(' IST', '')
            if '.' in t_clean:
                alert_dt = datetime.strptime(t_clean, "%Y-%m-%d %H:%M:%S.%f")
            else:
                alert_dt = datetime.strptime(t_clean, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
            
        # Only toast if the alert occurred AFTER the session started (to prevent re-toasting historic alerts on reload)
        if alert_dt and alert_dt > st.session_state["session_start_time"]:
            st.toast(f"🚨 {a['symbol']} {a['direction']} Breakout! {a['details']}", icon="🚨")

# Check and toast new V2 alerts
for a in reversed(db_v2_alerts):
    alert_key = f"v2_{a['symbol']}_{a['direction']}_{a['timestamp']}"
    if alert_key not in st.session_state["toasted_v2_alerts"]:
        st.session_state["toasted_v2_alerts"].add(alert_key)
        
        alert_dt = None
        try:
            t_clean = a['timestamp'].replace(' IST', '')
            if '.' in t_clean:
                alert_dt = datetime.strptime(t_clean, "%Y-%m-%d %H:%M:%S.%f")
            else:
                alert_dt = datetime.strptime(t_clean, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
            
        if alert_dt and alert_dt > st.session_state["session_start_time"]:
            st.toast(f"🔥 V2 Early Breakout: {a['symbol']} {a['direction']}! {a['details']}", icon="🔥")

# Update log in session state (newest on top)
st.session_state["live_alerts_log"] = db_alerts
st.session_state["live_v2_alerts_log"] = db_v2_alerts

@st.cache_data(ttl=30)
def load_spikes_by_date_range(start_date_str, end_date_str):
    """Load spikes from the iv4_spikes collection for a given date range (YYYY-MM-DD)."""
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
        st.error(f"Error loading spikes for range {start_date_str} to {end_date_str}: {e}")
        return pd.DataFrame()

def render_all_movers_page():
    st.html("""
    <div class="header-banner">
      <div>
        <div class="header-title">⚡ All Volatility Movers &amp; Shakers</div>
        <div class="header-sub">Showing all positive and negative changes in Implied Volatility (IV4)</div>
      </div>
      <div style="text-align:right;">
        <div class="header-badge"><span class="pulse-dot"></span> Live</div>
      </div>
    </div>
    """)
    
    # Initialize movers_start_date and movers_end_date if not present
    if "movers_start_date" not in st.session_state or "movers_end_date" not in st.session_state:
        if not df.empty and "ts_ist" in df.columns:
            try:
                latest_ts_str = df.iloc[0]["ts_ist"].split(" ")[0]
                latest_date = datetime.strptime(latest_ts_str, "%Y-%m-%d").date()
                st.session_state["movers_start_date"] = latest_date
                st.session_state["movers_end_date"] = latest_date
            except Exception:
                st.session_state["movers_start_date"] = datetime.now().date()
                st.session_state["movers_end_date"] = datetime.now().date()
        else:
            st.session_state["movers_start_date"] = datetime.now().date()
            st.session_state["movers_end_date"] = datetime.now().date()

    earliest_d = datetime.strptime("2026-08-10", "%Y-%m-%d").date()
    today_d = datetime.now().date()

    # Action Bar for navigation: Back button + date navigation side by side
    col_back, col_nav = st.columns([2, 8])
    
    with col_back:
        if st.button("◀ Go Back", key="go_back_movers_btn"):
            st.session_state["current_page"] = "main"
            st.rerun()
            
    with col_nav:
        nav_col1, nav_col2, nav_col3 = st.columns([1, 4, 1])
        with nav_col1:
            at_min = (st.session_state["movers_start_date"] <= earliest_d)
            if st.button("◀", key="prev_movers_day", help="Shift range back by 1 day", disabled=at_min):
                st.session_state["movers_start_date"] -= timedelta(days=1)
                st.session_state["movers_end_date"] -= timedelta(days=1)
                st.rerun()
        with nav_col2:
            # We align it with a date_input (calendar range selector)
            selected_dates = st.date_input(
                label="Select Date Range",
                value=(st.session_state["movers_start_date"], st.session_state["movers_end_date"]),
                min_value=earliest_d,
                max_value=today_d,
                key="movers_date_input",
                label_visibility="collapsed"
            )
            
            # Handle st.date_input returning a tuple of length 1 or 2
            if isinstance(selected_dates, tuple) or isinstance(selected_dates, list):
                if len(selected_dates) == 1:
                    start_date = selected_dates[0]
                    end_date = selected_dates[0]
                elif len(selected_dates) == 2:
                    start_date = selected_dates[0]
                    end_date = selected_dates[1]
                else:
                    start_date = st.session_state["movers_start_date"]
                    end_date = st.session_state["movers_end_date"]
            else:
                start_date = selected_dates
                end_date = selected_dates
                
            if (start_date != st.session_state["movers_start_date"]) or (end_date != st.session_state["movers_end_date"]):
                st.session_state["movers_start_date"] = start_date
                st.session_state["movers_end_date"] = end_date
                st.rerun()
                
        with nav_col3:
            at_max = (st.session_state["movers_end_date"] >= today_d)
            if st.button("▶", key="next_movers_day", help="Shift range forward by 1 day", disabled=at_max):
                st.session_state["movers_start_date"] += timedelta(days=1)
                st.session_state["movers_end_date"] += timedelta(days=1)
                st.rerun()
                
    st.html("<div style='margin-bottom:20px'></div>")
    
    # Load spikes/crushes for selected date range
    start_date_str = st.session_state["movers_start_date"].strftime("%Y-%m-%d")
    end_date_str = st.session_state["movers_end_date"].strftime("%Y-%m-%d")
    spikes_crushes_df = load_spikes_by_date_range(start_date_str, end_date_str)
    
    change_df = spikes_crushes_df[spikes_crushes_df["iv4_change_5m"] != 0].copy() if not spikes_crushes_df.empty else pd.DataFrame()
    
    m_col_up, m_col_down = st.columns(2)
    
    # Format date label
    if start_date_str == end_date_str:
        date_lbl = st.session_state["movers_start_date"].strftime("%d %b %Y")
    else:
        date_lbl = f"{st.session_state['movers_start_date'].strftime('%d %b')} - {st.session_state['movers_end_date'].strftime('%d %b %Y')}"
    
    with m_col_up:
        st.markdown(f"**🔥 Volatility Spikes ({date_lbl})**")
        spikes = pd.DataFrame()
        if not change_df.empty:
            spikes = change_df[change_df["iv4_change_5m"] > 0].sort_values("iv4_change_5m", ascending=False)
            
        if not spikes.empty:
            csv_spikes = spikes.to_csv(index=False)
            st.download_button(
                label="📥 Download Spikes CSV",
                data=csv_spikes,
                file_name=f"volatility_spikes_{start_date_str}_to_{end_date_str}.csv",
                mime="text/csv",
                key="download_spikes_btn"
            )
            
        rows_up = ""
        if spikes.empty:
            rows_up = "<tr><td colspan='5' style='text-align:center;color:#64748b;padding:20px;'>No spikes in this range</td></tr>"
        else:
            for _, r in spikes.iterrows():
                # Extract time part
                time_str = "—"
                if "ts_ist" in r and r["ts_ist"]:
                    try:
                        # If multi-day range, include date in the time column to be clear
                        if start_date_str != end_date_str:
                            time_str = r["ts_ist"][:16] # "YYYY-MM-DD HH:MM"
                        else:
                            time_str = r["ts_ist"].split(" ")[1][:8] # "HH:MM:SS"
                    except Exception:
                        pass
                        
                strike_info = "—"
                if isinstance(r.get("top_strike_iv_change_5m"), dict):
                    ts = r["top_strike_iv_change_5m"]
                    strike_info = f"<span class='ce-iv' style='font-weight:600'>{ts.get('strike')} {ts.get('side')}</span> ({ts.get('change'):+.2f}%)"
                
                rows_up += f"""
                <tr>
                  <td style="color:#64748b;font-family:'JetBrains Mono';font-size:0.75rem">{time_str}</td>
                  <td style="text-align:left;font-weight:600;color:#e2e8f0">{r['underlying_symbol']}</td>
                  <td>{r['iv4']:.2f}%</td>
                  <td style="color:#34d399;font-weight:700">+{r['iv4_change_5m']:.2f}%</td>
                  <td style="font-size:0.75rem;color:#94a3b8">{strike_info}</td>
                </tr>
                """
                
        table_up_html = f"""
        <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:12px;overflow:hidden;">
          <table class="iv4-table">
            <thead>
              <tr>
                <th style="text-align:left">Time</th>
                <th style="text-align:left">Symbol</th>
                <th>IV4</th>
                <th>Change</th>
                <th>Top Strike Driver</th>
              </tr>
            </thead>
            <tbody>
              {rows_up}
            </tbody>
          </table>
        </div>
        """
        st.html(table_up_html)

    with m_col_down:
        st.markdown(f"**❄️ Volatility Crushes ({date_lbl})**")
        crushes = pd.DataFrame()
        if not change_df.empty:
            crushes = change_df[change_df["iv4_change_5m"] < 0].sort_values("iv4_change_5m", ascending=True)
            
        if not crushes.empty:
            csv_crushes = crushes.to_csv(index=False)
            st.download_button(
                label="📥 Download Crushes CSV",
                data=csv_crushes,
                file_name=f"volatility_crushes_{start_date_str}_to_{end_date_str}.csv",
                mime="text/csv",
                key="download_crushes_btn"
            )
            
        rows_down = ""
        if crushes.empty:
            rows_down = "<tr><td colspan='5' style='text-align:center;color:#64748b;padding:20px;'>No crushes in this range</td></tr>"
        else:
            for _, r in crushes.iterrows():
                # Extract time part
                time_str = "—"
                if "ts_ist" in r and r["ts_ist"]:
                    try:
                        if start_date_str != end_date_str:
                            time_str = r["ts_ist"][:16] # "YYYY-MM-DD HH:MM"
                        else:
                            time_str = r["ts_ist"].split(" ")[1][:8] # "HH:MM:SS"
                    except Exception:
                        pass
                        
                strike_info = "—"
                if isinstance(r.get("top_strike_iv_change_5m"), dict):
                    ts = r["top_strike_iv_change_5m"]
                    strike_info = f"<span class='pe-iv' style='font-weight:600'>{ts.get('strike')} {ts.get('side')}</span> ({ts.get('change'):+.2f}%)"
                
                rows_down += f"""
                <tr>
                  <td style="color:#64748b;font-family:'JetBrains Mono';font-size:0.75rem">{time_str}</td>
                  <td style="text-align:left;font-weight:600;color:#e2e8f0">{r['underlying_symbol']}</td>
                  <td>{r['iv4']:.2f}%</td>
                  <td style="color:#f87171;font-weight:700">{r['iv4_change_5m']:.2f}%</td>
                  <td style="font-size:0.75rem;color:#94a3b8">{strike_info}</td>
                </tr>
                """
                
        table_down_html = f"""
        <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:12px;overflow:hidden;">
          <table class="iv4-table">
            <thead>
              <tr>
                <th style="text-align:left">Time</th>
                <th style="text-align:left">Symbol</th>
                <th>IV4</th>
                <th>Change</th>
                <th>Top Strike Driver</th>
              </tr>
            </thead>
            <tbody>
              {rows_down}
            </tbody>
          </table>
        </div>
        """
        st.html(table_down_html)

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "main"

if st.session_state["current_page"] == "movers_all":
    render_all_movers_page()
    st.stop()

# ─── Header Banner ────────────────────────────────────────────────────────────
total = len(df)
ts_str = df.iloc[0]["ts_ist"] if not df.empty and "ts_ist" in df.columns else "—"
avg_iv4 = round(df["iv4"].mean(), 2) if not df.empty else 0
high_iv4 = round(df["iv4"].max(), 2) if not df.empty else 0

st.html(f"""
<div class="header-banner">
  <div>
    <div class="header-title">⚡ Upholic Trading Terminal</div>
    <div class="header-sub">Advanced Implied Volatility Analytics &amp; Breakout Signals &nbsp;·&nbsp; Updated every 15 min</div>
  </div>
  <div style="text-align:right;">
    <div class="header-badge"><span class="pulse-dot"></span> Live</div>
    <div style="color:#475569; font-size:0.72rem; margin-top:8px;">Last sync: {ts_str}</div>
  </div>
</div>
""")

@st.cache_data(ttl=300)
def get_earliest_alert_date(collection_name="v1_scanner_alerts"):
    """Return the earliest date (as date object) that has alerts in the collection."""
    try:
        col = get_db()[collection_name]
        # Find the document with the smallest timestamp
        doc = col.find_one({}, {"ts_ist": 1}, sort=[("timestamp", 1)])
        if not doc:
            return datetime.now().date()
        ts = doc.get("ts_ist", "")
        date_part = ts.split(" ")[0]  # "YYYY-MM-DD"
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except Exception:
        return datetime.now().date()


def render_alert_action_bar(collection_name, mode_filter, table_key, live_log_key, toast_state_key):
    """Render a tab-specific action bar for clearing and downloading alerts."""
    today_date = datetime.now().date()
    act_col1, act_col2, act_col3 = st.columns([2, 2, 4])
    
    with act_col1:
        has_alerts_today = any(a.get("mode", "INTRADAY") == mode_filter for a in st.session_state.get(live_log_key, []))
        if has_alerts_today:
            if st.button(f"🗑️ Clear {mode_filter.title()} Alerts", key=f"clear_{table_key}"):
                try:
                    col = get_db()[collection_name]
                    col.delete_many({
                        "ts_ist": { "$regex": f"^{today_date.strftime('%Y-%m-%d')}" },
                        "mode": mode_filter
                    })
                except Exception as e:
                    st.error(f"Error clearing alerts: {e}")
                # Remove matching items from live log
                st.session_state[live_log_key] = [
                    a for a in st.session_state[live_log_key]
                    if a.get("mode", "INTRADAY") != mode_filter
                ]
                st.session_state[toast_state_key].clear()
                st.rerun()

    with act_col2:
        st.markdown(f"**📥 Download {mode_filter.title()} CSV**")
        
    with act_col3:
        dl_col1, dl_col2, dl_col3 = st.columns([1, 1, 1])
        with dl_col1:
            dl_start = st.date_input("From Date", value=today_date, key=f"dl_start_{table_key}", label_visibility="collapsed")
        with dl_col2:
            dl_end = st.date_input("To Date", value=today_date, key=f"dl_end_{table_key}", label_visibility="collapsed")
        with dl_col3:
            if st.button("⬇️ Download CSV", key=f"dl_btn_{table_key}"):
                all_dl_alerts = []
                cur_date = dl_start
                while cur_date <= dl_end:
                    date_str = cur_date.strftime("%Y-%m-%d")
                    day_alerts = load_alerts_by_date(date_str, collection_name)
                    filtered_alerts = [a for a in day_alerts if a.get("mode", "INTRADAY") == mode_filter]
                    all_dl_alerts.extend(filtered_alerts)
                    cur_date += timedelta(days=1)
                
                if all_dl_alerts:
                    dl_df = pd.DataFrame(all_dl_alerts)[["timestamp", "symbol", "timeframe", "direction", "spot", "details", "mode"]]
                    dl_df.columns = ["Alert Time", "Symbol", "Timeframe", "Direction", "Spot Price", "Trigger Details", "Mode"]
                    csv_data = dl_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label=f"✅ Save {len(all_dl_alerts)} rows",
                        data=csv_data,
                        file_name=f"{mode_filter.lower()}_alerts_{dl_start}_to_{dl_end}.csv",
                        mime="text/csv",
                        key=f"dl_save_{table_key}"
                    )
                else:
                    st.warning(f"No {mode_filter.lower()} alerts found for selected range.")


# Reusable alerts table renderer with built-in < > day navigation
def render_alerts_table(alerts_list, empty_message, table_key="default", collection_name="v1_scanner_alerts", mode_filter="INTRADAY"):
    today_d = datetime.now().date()

    # Init per-table navigation date in session state
    nav_key = f"nav_date_{table_key}"
    if nav_key not in st.session_state:
        st.session_state[nav_key] = today_d  # start on today

    viewing_date = st.session_state[nav_key]
    is_today = (viewing_date == today_d)

    # ── Compact nav bar: right-aligned < date > ───────────────────────────
    earliest_d = get_earliest_alert_date(collection_name)
    nav_left, nav_right = st.columns([6, 3])
    with nav_right:
        nb1, nb2, nb3, nb4 = st.columns([1.2, 1.5, 1.2, 0.1])
        with nb1:
            at_min = (viewing_date <= earliest_d)
            if st.button("◀", key=f"prev_{table_key}", help=f"Previous day (oldest: {earliest_d.strftime('%d %b')})", disabled=at_min):
                st.session_state[nav_key] -= timedelta(days=1)
                st.rerun()
        with nb2:
            lbl = "Today" if is_today else viewing_date.strftime("%d %b %Y")
            st.markdown(
                f"<div style='text-align:center;padding:6px 4px;color:#60a5fa;font-weight:700;font-size:0.82rem;white-space:nowrap;'>{lbl}</div>",
                unsafe_allow_html=True
            )
        with nb3:
            is_disabled = (viewing_date >= today_d)
            if st.button("▶", key=f"next_{table_key}", help="Next day", disabled=is_disabled):
                nxt = st.session_state[nav_key] + timedelta(days=1)
                if nxt <= today_d:
                    st.session_state[nav_key] = nxt
                    st.rerun()

    # Decide which data to show
    if is_today:
        display_alerts = [a for a in alerts_list if a.get("mode", "INTRADAY") == mode_filter]
    else:
        date_str = viewing_date.strftime("%Y-%m-%d")
        hist = load_alerts_by_date(date_str, collection_name)
        display_alerts = [a for a in hist if a.get("mode", "INTRADAY") == mode_filter]

    if not display_alerts:
        st.info(empty_message if is_today else f"No alerts found for {viewing_date.strftime('%d %b %Y')}.")
        return

    rows_alert_html = ""
    for idx, a in enumerate(display_alerts):
        dir_class = "sig-bullish" if a["direction"] == "BULLISH" else "sig-bearish"
        row_num = idx + 1
        rows_alert_html += f"""
        <tr>
          <td style="text-align:center;color:#475569;font-size:0.75rem;font-weight:600;width:40px;">{row_num}</td>
          <td>{a['timestamp']}</td>
          <td><b>{a['symbol']}</b></td>
          <td><span style="font-family:'JetBrains Mono';font-size:0.75rem;padding:3px 8px;background:rgba(255,255,255,0.05);border-radius:4px;">{a['timeframe'].upper()}</span></td>
          <td><span class="{dir_class}" style="font-weight:800;letter-spacing:0.5px;">{a['direction']}</span></td>
          <td>₹{a['spot']:,.2f}</td>
          <td style="text-align:left;color:#94a3b8;font-family:'Inter'">{a['details']}</td>
        </tr>"""

    table_alert_html = f"""
    <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;overflow-x:auto;">
      <table class="iv4-table">
        <thead>
          <tr>
            <th style="text-align:center;width:40px;">#</th>
            <th style="text-align:left">Alert Time</th>
            <th style="text-align:left">Symbol</th>
            <th style="text-align:left">Timeframe</th>
            <th style="text-align:left">Direction</th>
            <th>Spot Price</th>
            <th style="text-align:left">Trigger Details</th>
          </tr>
        </thead>
        <tbody>
          {rows_alert_html}
        </tbody>
      </table>
    </div>
    <div style="margin-top:10px;color:#334155;font-size:0.71rem;text-align:right">
      {len(display_alerts)} alerts &nbsp;·&nbsp; {'Today' if is_today else viewing_date.strftime('%d %b %Y')}
    </div>
    """
    st.html(table_alert_html)


@st.cache_data(ttl=60)
def load_alerts_by_date(date_str, collection_name="v1_scanner_alerts"):
    """Load alerts from MongoDB for a given date string (YYYY-MM-DD)."""
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
            t_ist = d.get("ts_ist", "")
            alerts.append({
                "timestamp": t_ist,
                "symbol": d.get("symbol", ""),
                "timeframe": d.get("timeframe", "15m"),
                "direction": d.get("direction", ""),
                "spot": d.get("spot", 0.0),
                "details": d.get("details", ""),
                "mode": d.get("mode", "INTRADAY")
            })
        return alerts
    except Exception as e:
        st.error(f"Error loading alerts for {date_str}: {e}")
        return []

# Create Tabs
tab1, tab2, tab3, tab4 = st.tabs(["🏆 Volatility Leaderboard", "🎯 Breakout Scanner", "🔔 Live Alerts Log (V1)", "🔥 Early Breakouts (V2)"])

# ─── TAB 1: Volatility Leaderboard ────────────────────────────────────────────
with tab1:
    # Stats strip
    st.html("""<div class="section-label">Market Overview</div>""")
    s1, s2, s3, s4 = st.columns(4)
    def stat_box(col, num, lbl):
        col.html(f"""
        <div class="stat-box">
          <div class="stat-num">{num}</div>
          <div class="stat-lbl">{lbl}</div>
        </div>""")

    stat_box(s1, total, "Total Stocks")
    stat_box(s2, f"{high_iv4:.2f}%", "Highest IV4")
    stat_box(s3, f"{avg_iv4:.2f}%", "Avg IV4")
    stat_box(s4, len(df[df["iv4"] >= 30]) if not df.empty else 0, "High Volatility (≥30%)")

    st.html("<div style='margin-bottom:28px'></div>")

    if df.empty:
        st.warning("⚠️ No data yet in `latest_snapshot`. Start your backend and wait for the first 15-minute cycle to complete.")
    else:
        # Top 3 Podium
        st.html("""<div class="section-label">🏆 Top Ranked Stocks by IV4</div>""")
        medals = [("gold", "🥇", "1"), ("silver", "🥈", "2"), ("bronze", "🥉", "3")]
        cols3 = st.columns(3)

        for i, (cls, medal, num) in enumerate(medals):
            if i >= len(df): continue
            row = df.iloc[i]
            sym = row["underlying_symbol"]
            iv4 = row["iv4"]
            spot = row["last_price"]
            ce_iv = row.get("ce_iv_oi_weighted", 0)
            pe_iv = row.get("pe_iv_oi_weighted", 0)
            skew = row.get("iv_skew", 0)
            expiry = row.get("expiry", "—")
            with cols3[i]:
                st.html(f"""
                <div class="rank-card {cls}">
                  <div class="rank-watermark">#{num}</div>
                  <div class="rank-medal">{medal}</div>
                  <div class="rank-symbol">{sym}</div>
                  <div class="rank-iv4">{iv4:.2f}<span style="font-size:1rem;font-weight:500;color:#94a3b8">%</span></div>
                  <div class="rank-sub">
                    <div class="rank-pill">Spot <span>₹{spot:,.2f}</span></div>
                    <div class="rank-pill">CE <span style="color:#60a5fa">{ce_iv:.2f}%</span></div>
                    <div class="rank-pill">PE <span style="color:#f472b6">{pe_iv:.2f}%</span></div>
                    <div class="rank-pill">Skew <span style="color:{'#f87171' if skew > 0 else '#34d399'}">{skew:+.3f}</span></div>
                  </div>
                  <div style="margin-top:12px;font-size:0.68rem;color:#334155">Expiry: {expiry}</div>
                </div>
                """)

        st.html("<div style='margin-bottom:28px'></div>")

        # Movers & Shakers
        col_lbl, col_btn = st.columns([8, 2])
        with col_lbl:
            st.html("""<div class="section-label">⚡ Volatility Movers &amp; Shakers (15-Minute Change)</div>""")
        with col_btn:
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            if st.button("See All ↗", key="see_all_movers_btn"):
                st.session_state["current_page"] = "movers_all"
                st.rerun()

        m_col_up, m_col_down = st.columns(2)
        change_df = df[df["iv4_change_5m"] != 0].copy()

        with m_col_up:
            st.markdown("**🔥 Volatility Spikes (Top 5 Positive Changes)**")
            spikes = pd.DataFrame()
            if not change_df.empty:
                spikes = change_df[change_df["iv4_change_5m"] > 0].sort_values("iv4_change_5m", ascending=False).head(5)
            
            rows_up = ""
            if spikes.empty:
                rows_up = "<tr><td colspan='4' style='text-align:center;color:#64748b;padding:20px;'>No spikes in last 15m (waiting for next cycle)</td></tr>"
            else:
                for _, r in spikes.iterrows():
                    strike_info = "—"
                    if isinstance(r.get("top_strike_iv_change_5m"), dict):
                        ts = r["top_strike_iv_change_5m"]
                        strike_info = f"<span class='ce-iv' style='font-weight:600'>{ts.get('strike')} {ts.get('side')}</span> ({ts.get('change'):+.2f}%)"
                    
                    rows_up += f"""
                    <tr>
                      <td style="text-align:left;font-weight:600;color:#e2e8f0">{r['underlying_symbol']}</td>
                      <td>{r['iv4']:.2f}%</td>
                      <td style="color:#34d399;font-weight:700">+{r['iv4_change_5m']:.2f}%</td>
                      <td style="font-size:0.75rem;color:#94a3b8">{strike_info}</td>
                    </tr>
                    """
                    
            table_up_html = f"""
            <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:12px;overflow:hidden;">
              <table class="iv4-table">
                <thead>
                  <tr>
                    <th style="text-align:left">Symbol</th>
                    <th>IV4</th>
                    <th>Change</th>
                    <th>Top Strike Driver</th>
                  </tr>
                </thead>
                <tbody>
                  {rows_up}
                </tbody>
              </table>
            </div>
            """
            st.html(table_up_html)

        with m_col_down:
            st.markdown("**❄️ Volatility Crushes (Top 5 Negative Changes)**")
            crushes = pd.DataFrame()
            if not change_df.empty:
                crushes = change_df[change_df["iv4_change_5m"] < 0].sort_values("iv4_change_5m", ascending=True).head(5)
            
            rows_down = ""
            if crushes.empty:
                rows_down = "<tr><td colspan='4' style='text-align:center;color:#64748b;padding:20px;'>No crushes in last 15m (waiting for next cycle)</td></tr>"
            else:
                for _, r in crushes.iterrows():
                    strike_info = "—"
                    if isinstance(r.get("top_strike_iv_change_5m"), dict):
                        ts = r["top_strike_iv_change_5m"]
                        strike_info = f"<span class='pe-iv' style='font-weight:600'>{ts.get('strike')} {ts.get('side')}</span> ({ts.get('change'):+.2f}%)"
                    
                    rows_down += f"""
                    <tr>
                      <td style="text-align:left;font-weight:600;color:#e2e8f0">{r['underlying_symbol']}</td>
                      <td>{r['iv4']:.2f}%</td>
                      <td style="color:#f87171;font-weight:700">{r['iv4_change_5m']:.2f}%</td>
                      <td style="font-size:0.75rem;color:#94a3b8">{strike_info}</td>
                    </tr>
                    """
                    
            table_down_html = f"""
            <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:12px;overflow:hidden;">
              <table class="iv4-table">
                <thead>
                  <tr>
                    <th style="text-align:left">Symbol</th>
                    <th>IV4</th>
                    <th>Change</th>
                    <th>Top Strike Driver</th>
                  </tr>
                </thead>
                <tbody>
                  {rows_down}
                </tbody>
              </table>
            </div>
            """
            st.html(table_down_html)

        st.html("<div style='margin-bottom:28px'></div>")

        # Charts
        st.html("""<div class="section-label">📊 Volatility Analytics</div>""")
        cc1, cc2 = st.columns([3, 2])

        with cc1:
            top30 = df.head(30)
            colors = [iv4_color(v) for v in top30["iv4"]]
            fig = go.Figure(go.Bar(
                x=top30["underlying_symbol"],
                y=top30["iv4"],
                marker_color=colors,
                marker_line_width=0,
                text=[f"{v:.1f}%" for v in top30["iv4"]],
                textposition="outside",
                textfont=dict(size=9, color="#94a3b8"),
            ))
            fig.update_layout(
                title=dict(text="Top 30 Stocks — Overall IV4", font=dict(color="#94a3b8", size=13), x=0),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(13,22,37,1)",
                margin=dict(l=10, r=10, t=40, b=80),
                xaxis=dict(tickangle=-45, tickfont=dict(size=9, color="#64748b", family="JetBrains Mono"),
                           gridcolor="rgba(255,255,255,0.04)", showgrid=False),
                yaxis=dict(tickfont=dict(size=10, color="#64748b"), gridcolor="rgba(255,255,255,0.04)",
                           ticksuffix="%"),
                bargap=0.25, height=360,
                font=dict(family="Inter"),
            )
            st.html('<div class="chart-card">')
            st.plotly_chart(fig, width="stretch")
            st.html('</div>')

        with cc2:
            plot_df = df[df["ce_iv_oi_weighted"] > 0].head(50)
            fig2 = px.scatter(
                plot_df,
                x="ce_iv_oi_weighted", y="pe_iv_oi_weighted",
                size="iv4", color="iv4",
                hover_name="underlying_symbol",
                color_continuous_scale="Plasma",
                labels={"ce_iv_oi_weighted": "CE IV (%)", "pe_iv_oi_weighted": "PE IV (%)"},
                size_max=30,
            )
            fig2.update_layout(
                title=dict(text="CE IV vs PE IV Dispersion", font=dict(color="#94a3b8", size=13), x=0),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(13,22,37,1)",
                margin=dict(l=10, r=10, t=40, b=10),
                xaxis=dict(tickfont=dict(size=10, color="#64748b"), gridcolor="rgba(255,255,255,0.04)",
                           ticksuffix="%"),
                yaxis=dict(tickfont=dict(size=10, color="#64748b"), gridcolor="rgba(255,255,255,0.04)",
                           ticksuffix="%"),
                coloraxis_colorbar=dict(tickfont=dict(color="#64748b"), title=dict(text="IV4%", font=dict(color="#64748b"))),
                height=360, font=dict(family="Inter"),
            )
            st.html('<div class="chart-card">')
            st.plotly_chart(fig2, width="stretch")
            st.html('</div>')

        # Intraday Trajectory Chart
        st.html("""<div class="section-label">📈 Intraday IV4 Analytics (Today)</div>""")

        symbols = sorted(df["underlying_symbol"].unique())
        sel_stock = st.selectbox("SELECT STOCK FOR INTRADAY ANALYSIS", options=symbols)
        
        if sel_stock:
            hist_df = load_stock_history(sel_stock)
            if hist_df.empty:
                st.info(f"No intraday history found for {sel_stock} today. Start your backend and wait for the first 15-minute cycle.")
            else:
                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=hist_df["ts_ist"].apply(lambda x: x.split(" ")[1][:5] if len(x.split(" ")) > 1 else x),
                    y=hist_df["iv4"],
                    mode="lines+markers",
                    name="Overall IV4",
                    line=dict(color="#fbbf24", width=3),
                    marker=dict(size=6)
                ))
                fig_line.add_trace(go.Scatter(
                    x=hist_df["ts_ist"].apply(lambda x: x.split(" ")[1][:5] if len(x.split(" ")) > 1 else x),
                    y=hist_df["ce_iv_oi_weighted"],
                    mode="lines",
                    name="Call IV (Weighted)",
                    line=dict(color="#60a5fa", width=1.5, dash="dash")
                ))
                fig_line.add_trace(go.Scatter(
                    x=hist_df["ts_ist"].apply(lambda x: x.split(" ")[1][:5] if len(x.split(" ")) > 1 else x),
                    y=hist_df["pe_iv_oi_weighted"],
                    mode="lines",
                    name="Put IV (Weighted)",
                    line=dict(color="#f472b6", width=1.5, dash="dash")
                ))
                
                fig_line.update_layout(
                    title=dict(text=f"Today's IV4 Trajectory for {sel_stock}", font=dict(color="#94a3b8", size=14)),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(13,22,37,1)",
                    margin=dict(l=20, r=20, t=50, b=50),
                    xaxis=dict(
                        tickfont=dict(size=10, color="#64748b", family="JetBrains Mono"),
                        gridcolor="rgba(255,255,255,0.04)"
                    ),
                    yaxis=dict(
                        tickfont=dict(size=10, color="#64748b"),
                        gridcolor="rgba(255,255,255,0.04)",
                        ticksuffix="%"
                    ),
                    legend=dict(
                        font=dict(color="#94a3b8"),
                        bgcolor="rgba(0,0,0,0)"
                    ),
                    height=380,
                    font=dict(family="Inter")
                )
                st.html('<div class="chart-card">')
                st.plotly_chart(fig_line, width="stretch")
                st.html('</div>')

        st.html("<div style='margin-bottom:28px'></div>")

        # Filter bar
        st.html('<div class="filter-bar">')
        fc1, fc2, fc3 = st.columns([3, 1, 1])
        with fc1:
            search = st.text_input("SEARCH SYMBOL", placeholder="e.g. RELIANCE, HDFC, INFY…").strip().upper()
        with fc2:
            top_n = st.number_input("TOP N", min_value=5, max_value=250, value=50, step=5)
        with fc3:
            min_iv4 = st.number_input("MIN IV4 (%)", min_value=0.0, max_value=200.0, value=0.0, step=1.0)
        st.html('</div>')

        # Leaderboard Table
        st.html("""<div class="section-label">📋 Full Leaderboard</div>""")

        filtered = df.copy()
        if search:
            filtered = filtered[filtered["underlying_symbol"].str.contains(search, na=False)]
        if min_iv4 > 0:
            filtered = filtered[filtered["iv4"] >= min_iv4]
        filtered = filtered.head(int(top_n))

        def rank_badge(r):
            cls = "rank-top3" if r <= 3 else ("rank-top10" if r <= 10 else "rank-rest")
            return f'<span class="rank-num {cls}">{r}</span>'

        def skew_cell(v):
            cls = "skew-pos" if v > 0 else "skew-neg"
            sign = "+" if v > 0 else ""
            return f'<span class="{cls}">{sign}{v:.4f}</span>'

        def iv4_cell(v):
            color = iv4_color(v)
            return f'<span style="color:{color};font-weight:700">{v:.2f}%</span>'

        rows_html = ""
        for _, r in filtered.iterrows():
            change_val = r.get("iv4_change_5m", 0)
            change_class = "skew-pos" if change_val > 0 else ("skew-neg" if change_val < 0 else "")
            change_sign = "+" if change_val > 0 else ""
            change_text = f"<span class='{change_class}' style='font-weight:700'>{change_sign}{change_val:.2f}%</span>" if change_val != 0 else "<span style='color:#475569;'>—</span>"

            strike_info = "<span style='color:#475569;'>—</span>"
            ts = r.get("top_strike_iv_change_5m")
            if isinstance(ts, dict):
                side_class = "ce-iv" if ts.get("side") == "CE" else "pe-iv"
                strike_info = f"<span class='{side_class}' style='font-weight:600'>{ts.get('strike')} {ts.get('side')}</span> <span style='font-size:0.75rem;color:#64748b'>({ts.get('change'):+.2f}%)</span>"

            rows_html += f"""
            <tr>
              <td>{rank_badge(int(r['rank']))}</td>
              <td>{r['underlying_symbol']}</td>
              <td>₹{r['last_price']:,.2f}</td>
              <td>{iv4_cell(r['iv4'])}</td>
              <td>{change_text}</td>
              <td>{strike_info}</td>
              <td><span class="ce-iv">{r['ce_iv_oi_weighted']:.2f}%</span></td>
              <td><span class="pe-iv">{r['pe_iv_oi_weighted']:.2f}%</span></td>
              <td>{skew_cell(r['iv_skew'])}</td>
              <td style="color:#94a3b8">{r['iv_ratio']:.4f}</td>
              <td style="color:#475569;font-size:0.7rem">{r.get('expiry','—')}</td>
            </tr>"""

        table_html = f"""
        <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;overflow-x:auto;">
          <table class="iv4-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Spot</th>
                <th>IV4 Overall</th>
                <th>15m Change</th>
                <th>Top Strike Driver</th>
                <th>CE IV</th>
                <th>PE IV</th>
                <th>IV Skew</th>
                <th>IV Ratio</th>
                <th>Expiry</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </div>
        <div style="margin-top:10px;color:#334155;font-size:0.71rem;text-align:right">
          Showing {len(filtered)} of {total} stocks &nbsp;·&nbsp; Last sync: {ts_str}
        </div>
        """
        st.html(table_html)


# ─── TAB 2: Breakout Scanner ──────────────────────────────────────────────────
with tab2:
    st.html("""<div class="section-label">🎯 IV Breakout Scanner (Algorithmic Signals)</div>""")
    
    # Load signals
    df_signals = load_breakout_signals()
    
    if df_signals.empty:
        st.warning("⚠️ No signals available yet. Start your backend to populate option chain ticks in MongoDB.")
    else:
        # Signal summaries
        sig_counts = df_signals["edge_signal"].value_counts()
        total_bullish = sig_counts.get("BULLISH DIVERGENCE (Call IV Expanding + Premium Build)", 0)
        total_bearish = sig_counts.get("BEARISH DIVERGENCE (Put IV Expanding + Put Premium Build)", 0)
        total_call_squeeze = sig_counts.get("CALL SHORT-COVERING SQUEEZE (Call IV Expanding + Premium Unwind)", 0)
        total_put_squeeze = sig_counts.get("PUT SHORT-COVERING (Put IV Expanding + Put Premium Unwind)", 0)
        
        c1, c2, c3, c4 = st.columns(4)
        stat_box(c1, total_bullish, "Bullish Divergences")
        stat_box(c2, total_bearish, "Bearish Divergences")
        stat_box(c3, total_call_squeeze, "Call Squeezes")
        stat_box(c4, total_put_squeeze, "Put Coverings")
        
        st.html("<div style='margin-bottom:28px'></div>")
        
        # Filters
        st.html('<div class="filter-bar">')
        fc_sig1, fc_sig2 = st.columns([3, 1])
        with fc_sig1:
            sig_types = [
                "ALL SIGNALS", 
                "BULLISH DIVERGENCE", 
                "BEARISH DIVERGENCE", 
                "CALL SHORT-COVERING SQUEEZE", 
                "PUT SHORT-COVERING", 
                "NEUTRAL"
            ]
            selected_sig_filter = st.selectbox("FILTER BY SIGNAL TYPE", options=sig_types)
        with fc_sig2:
            sort_by = st.selectbox("SORT BY", options=[
                "IV Ratio (Descending)", 
                "IV Ratio (Ascending)", 
                "IV Skew (Descending)", 
                "IV Skew (Ascending)"
            ])
        st.html('</div>')
        
        # Apply filters
        filtered_sig = df_signals.copy()
        if selected_sig_filter != "ALL SIGNALS":
            filtered_sig = filtered_sig[filtered_sig["edge_signal"].str.contains(selected_sig_filter, na=False)]
            
        # Apply sorting
        if sort_by == "IV Ratio (Descending)":
            filtered_sig = filtered_sig.sort_values(by="iv_ratio", ascending=False)
        elif sort_by == "IV Ratio (Ascending)":
            filtered_sig = filtered_sig.sort_values(by="iv_ratio", ascending=True)
        elif sort_by == "IV Skew (Descending)":
            filtered_sig = filtered_sig.sort_values(by="iv_skew", ascending=False)
        elif sort_by == "IV Skew (Ascending)":
            filtered_sig = filtered_sig.sort_values(by="iv_skew", ascending=True)
            
        def get_signal_class(s):
            if "BULLISH" in s: return "sig-bullish"
            if "BEARISH" in s: return "sig-bearish"
            if "CALL SHORT-COVERING" in s: return "sig-squeeze"
            if "PUT SHORT-COVERING" in s: return "sig-covering"
            return "sig-neutral"
            
        rows_sig_html = ""
        for idx, r in filtered_sig.reset_index(drop=True).iterrows():
            sig_class = get_signal_class(r['edge_signal'])
            rows_sig_html += f"""
            <tr>
              <td><span class="rank-num rank-rest">{idx + 1}</span></td>
              <td><b>{r['symbol']}</b></td>
              <td><span class="{sig_class}">{r['edge_signal']}</span></td>
              <td>₹{r['spot_price']:,.2f}</td>
              <td style="font-weight:700">{r['iv_ratio']:.3f}</td>
              <td>{r['iv_skew']:+.2f}</td>
              <td>{r['vw_iv_call']:.2f}%</td>
              <td>{r['vw_iv_put']:.2f}%</td>
              <td style="color:{'#34d399' if r['call_flow_net'] >= 0 else '#f87171'}">{r['call_flow_net']:+,.2f}</td>
              <td style="color:{'#34d399' if r['put_flow_net'] >= 0 else '#f87171'}">{r['put_flow_net']:+,.2f}</td>
            </tr>"""
            
        table_sig_html = f"""
        <div style="background:#0d1625;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;overflow-x:auto;">
          <table class="iv4-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Edge Signal</th>
                <th>Spot</th>
                <th>IV Ratio</th>
                <th>IV Skew</th>
                <th>VW Call IV</th>
                <th>VW Put IV</th>
                <th>Call Net Flow</th>
                <th>Put Net Flow</th>
              </tr>
            </thead>
            <tbody>
              {rows_sig_html}
            </tbody>
          </table>
        </div>
        <div style="margin-top:10px;color:#334155;font-size:0.71rem;text-align:right">
          Showing {len(filtered_sig)} signals &nbsp;·&nbsp; Last sync: {ts_str}
        </div>
        """
        st.html(table_sig_html)


# ─── TAB 3: Live Alerts Log ───────────────────────────────────────────────────
with tab3:
    st.html("""<div class="section-label">🔔 Live Breakout Crossing Alerts</div>""")

    # ── Sub-tabs (no yesterday tab) ───────────────────────────────────────────
    subtab1, subtab2 = st.tabs(["🚀 Intraday Breakouts", "📅 Positional Breakouts"])

    with subtab1:
        render_alert_action_bar(
            collection_name="v1_scanner_alerts",
            mode_filter="INTRADAY",
            table_key="v1_intraday",
            live_log_key="live_alerts_log",
            toast_state_key="toasted_alerts"
        )
        st.html("<div style='margin-bottom:12px'></div>")
        render_alerts_table(
            st.session_state["live_alerts_log"],
            "No intraday breakout alerts triggered yet today. Make sure your background scanner is running during market hours.",
            table_key="v1_intraday",
            collection_name="v1_scanner_alerts",
            mode_filter="INTRADAY"
        )

    with subtab2:
        render_alert_action_bar(
            collection_name="v1_scanner_alerts",
            mode_filter="POSITIONAL",
            table_key="v1_positional",
            live_log_key="live_alerts_log",
            toast_state_key="toasted_alerts"
        )
        st.html("<div style='margin-bottom:12px'></div>")
        render_alerts_table(
            st.session_state["live_alerts_log"],
            "No positional breakout alerts triggered yet today. Positional alerts are evaluated on daily/weekly candles.",
            table_key="v1_positional",
            collection_name="v1_scanner_alerts",
            mode_filter="POSITIONAL"
        )


# ─── TAB 4: Early Breakouts (V2) ──────────────────────────────────────────────
with tab4:
    st.html("""<div class="section-label">🔥 Live Early Breakout &amp; Breakdown Alerts (V2)</div>""")

    # ── Sub-tabs (no yesterday tab) ───────────────────────────────────────────
    v2_subtab1, v2_subtab2 = st.tabs(["🚀 Intraday Breakouts", "📅 Positional Breakouts"])

    with v2_subtab1:
        render_alert_action_bar(
            collection_name="v2_scanner_alerts",
            mode_filter="INTRADAY",
            table_key="v2_intraday",
            live_log_key="live_v2_alerts_log",
            toast_state_key="toasted_v2_alerts"
        )
        st.html("<div style='margin-bottom:12px'></div>")
        render_alerts_table(
            st.session_state["live_v2_alerts_log"],
            "No early intraday breakout alerts triggered yet today. Make sure your background scanner is running during market hours.",
            table_key="v2_intraday",
            collection_name="v2_scanner_alerts",
            mode_filter="INTRADAY"
        )

    with v2_subtab2:
        render_alert_action_bar(
            collection_name="v2_scanner_alerts",
            mode_filter="POSITIONAL",
            table_key="v2_positional",
            live_log_key="live_v2_alerts_log",
            toast_state_key="toasted_v2_alerts"
        )
        st.html("<div style='margin-bottom:12px'></div>")
        render_alerts_table(
            st.session_state["live_v2_alerts_log"],
            "No early positional breakout alerts triggered yet today. Positional alerts are evaluated on daily/weekly candles.",
            table_key="v2_positional",
            collection_name="v2_scanner_alerts",
            mode_filter="POSITIONAL"
        )
