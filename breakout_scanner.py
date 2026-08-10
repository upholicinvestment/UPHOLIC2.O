import os
import sys
import time
import json
import pymongo
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scanner_config.json")
try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
except Exception as e:
    print(f"[WARN] Failed to load config from {CONFIG_PATH}, using defaults. Error: {e}")
    config = {
        "scan_interval_sec": 60,
        "zone_width_pct": 0.5,
        "swing_window": 5,
        "min_touches": 3,
        "breakout_confirm_pct": 0.1,
        "volume_confirmation": True,
        "alert_cooldown_min": 30,
        "market_open": "09:15",
        "market_close": "15:30"
    }

print("[CONFIG] Loaded Scanner Configuration:")
print(json.dumps(config, indent=2))

# Database connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")

try:
    client = pymongo.MongoClient(MONGO_URI)
    db = client[db_name]
    print(f"[DB] Connected to MongoDB -> {db_name}")
except Exception as e:
    print(f"[ERROR] Failed to connect to MongoDB: {e}")
    sys.exit(1)

# Mapping timeframes to pandas frequencies: (pandas frequency, mode)
TIMEFRAME_MAP = {
    "15 Minutes": ("15min", "INTRADAY"),
    "30 Minutes": ("30min", "INTRADAY"),
    "45 Minutes": ("45min", "INTRADAY"),
    "1 Hour": ("60min", "INTRADAY"),
    "2 Hours": ("120min", "INTRADAY"),
    "3 Hours": ("180min", "INTRADAY"),
    "4 Hours": ("240min", "INTRADAY"),
    "1 Day": ("1D", "POSITIONAL"),
    "1 Week": ("1W", "POSITIONAL")
}

# Global in-memory states
sr_zones = {}  # zones[symbol][timeframe] = { 'resistance': [[min, max, touches], ...], 'support': [...] }
latest_data = {}  # latest_data[symbol][timeframe] = DataFrame (resampled candles)
last_processed_ts = None
alert_cooldowns = {}  # alert_cooldowns[key] = datetime (last alert time)

def get_ts_ist_string(date_obj):
    # Format Date object as IST string
    ist_time = date_obj + timedelta(hours=5.5)
    return ist_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " IST"

def is_market_open():
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5.5) # IST
    if now.weekday() >= 5: # Saturday/Sunday
        return False
        
    time_str = now.strftime("%H:%M")
    return config["market_open"] <= time_str <= config["market_close"]

def calculate_swing_highs_lows(df, window):
    # Detect Swing Highs and Swing Lows
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    
    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)
    
    for i in range(window, n - window):
        # Swing High check
        if highs[i] == max(highs[i - window : i + window + 1]):
            if highs[i] > highs[i - 1] or highs[i] > highs[i + 1]:
                swing_highs[i] = True
                
        # Swing Low check
        if lows[i] == min(lows[i - window : i + window + 1]):
            if lows[i] < lows[i - 1] or lows[i] < lows[i + 1]:
                swing_lows[i] = True
                
    return swing_highs, swing_lows

def cluster_prices_into_zones(prices, zone_width_pct, min_touches):
    if not prices:
        return []
        
    prices = sorted(prices)
    zones = []
    
    # We cluster prices that are within zone_width_pct of each other
    current_cluster = [prices[0]]
    
    for i in range(1, len(prices)):
        price = prices[i]
        avg_cluster_price = sum(current_cluster) / len(current_cluster)
        max_dist = avg_cluster_price * (zone_width_pct / 100)
        
        if price - current_cluster[0] <= max_dist:
            current_cluster.append(price)
        else:
            if len(current_cluster) >= min_touches:
                zones.append({
                    "min": min(current_cluster),
                    "max": max(current_cluster),
                    "touches": len(current_cluster)
                })
            current_cluster = [price]
            
    if len(current_cluster) >= min_touches:
        zones.append({
            "min": min(current_cluster),
            "max": max(current_cluster),
            "touches": len(current_cluster)
        })
        
    return zones

def build_sr_zones_for_stock(symbol, df_1m):
    if df_1m.empty:
        return
        
    sr_zones[symbol] = {}
    latest_data[symbol] = {}
    
    for tf_name, tf_info in TIMEFRAME_MAP.items():
        tf_freq, mode = tf_info
        
        # Resample 1m data to target timeframe
        df_resampled = df_1m.resample(tf_freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        # Determine minimum required candles for swing calculations
        min_candles = config["swing_window"] * 2 + 5
        swing_window = config["swing_window"]
        
        if tf_name == "1 Week":
            min_candles = 3
            swing_window = 1
        elif tf_name == "1 Day":
            min_candles = 10
            swing_window = 3
            
        if len(df_resampled) < min_candles:
            continue
            
        # 1. Detect Swing Points
        sh, sl = calculate_swing_highs_lows(df_resampled, swing_window)
        df_resampled['swing_high'] = sh
        df_resampled['swing_low'] = sl
        
        # 2. Extract Prices
        high_prices = df_resampled[df_resampled['swing_high']]['high'].tolist()
        low_prices = df_resampled[df_resampled['swing_low']]['low'].tolist()
        
        # 3. Cluster into Zones
        min_touches = config["min_touches"]
        if tf_name in ["1 Day", "1 Week"]:
            min_touches = 2  # Support lower touch threshold on longer timelines
            
        resistances = cluster_prices_into_zones(high_prices, config["zone_width_pct"], min_touches)
        supports = cluster_prices_into_zones(low_prices, config["zone_width_pct"], min_touches)
        
        sr_zones[symbol][tf_name] = {
            "resistance": resistances,
            "support": supports
        }
        latest_data[symbol][tf_name] = df_resampled

def build_all_zones():
    global last_processed_ts
    print("[SR] Building Support & Resistance zones for all stocks...")
    
    # Resolve symbols from instruments collection
    stocks_cursor = db["instruments"].aggregate([
        { "$match": { "exch_id": "NSE", "segment": "D", "instrument": "OPTSTK" } },
        { "$group": { "_id": "$underlying_symbol" } }
    ])
    symbols = [item["_id"] for item in stocks_cursor if item["_id"]]
    print(f"[INFO] Found {len(symbols)} active symbols to calculate.")
    
    col = db["optstk_history_1m"]
    
    completed = 0
    start_time = time.time()
    
    for symbol in symbols:
        cursor = col.find({"symbol": symbol}).sort("timestamp", 1)
        docs = list(cursor)
        if not docs:
            continue
            
        df = pd.DataFrame(docs)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # Keep track of latest timestamp loaded
        max_ts = df.index.max()
        if last_processed_ts is None or max_ts > last_processed_ts:
            last_processed_ts = max_ts
            
        build_sr_zones_for_stock(symbol, df)
        
        completed += 1
        if completed % 30 == 0 or completed == len(symbols):
            elapsed = time.time() - start_time
            print(f"   [+] Calculated S&R zones for {completed}/{len(symbols)} stocks... ({elapsed:.1f}s)")
    print("[OK] Completed S&R zone building.")

def check_v2_pattern(symbol, tf_name, df, direction, close, open_val, mode):
    # Extract chronological list of swing points from this resampled timeframe
    swings = []
    for idx, row in df.iterrows():
        if row['swing_high']:
            swings.append({'type': 'high', 'price': row['high'], 'time': idx})
        if row['swing_low']:
            swings.append({'type': 'low', 'price': row['low'], 'time': idx})
            
    if len(swings) < 4:
        return
        
    # Get last 4 swing points (oldest to newest: p4 -> p3 -> p2 -> p1)
    p4, p3, p2, p1 = swings[-4], swings[-3], swings[-2], swings[-1]
    
    if direction == "BULLISH":
        # Expect sequence: High (R1), Low (S1), High (R2), Low (S2)
        if p4['type'] == 'high' and p3['type'] == 'low' and p2['type'] == 'high' and p1['type'] == 'low':
            r1, s1, r2, s2 = p4['price'], p3['price'], p2['price'], p1['price']
            
            # 1. R1 > R2 (Primary resistance is higher than secondary resistance)
            # 2. S1 and S2 are close to each other (Double Bottom support level within 2%)
            # 3. R2 is a valid retracement (rests between support and primary resistance)
            is_r_higher = r1 > r2 * 1.01
            is_s_double_bottom = abs(s1 - s2) / max(s1, s2) <= 0.02
            is_r2_valid_retracement = s1 < r2 < r1
            
            if is_r_higher and is_s_double_bottom and is_r2_valid_retracement:
                # Breakout check: Close broke above R2, but still below R1
                if close >= r2 * 1.001 and close < r1:
                    strength = "Strong" if abs(s1 - s2) / s1 <= 0.01 else "Medium"
                    try:
                        db["v2_scanner_alerts"].insert_one({
                          "timestamp": datetime.now(),
                          "ts_ist": get_ts_ist_string(datetime.now()),
                          "symbol": symbol,
                          "timeframe": tf_name,
                          "direction": "BULLISH",
                          "mode": mode,
                          "spot": float(close),
                          "details": f"V2 Early Cup-and-Handle: Broke secondary resistance {r2:.2f} (Cup high: {r1:.2f}) | Support: {s2:.2f} | Strength: {strength}"
                        })
                        print(f"[V2 ALERT] {symbol} ({tf_name}) Bullish V2 Crossover!")
                    except Exception as ex:
                        print(f"[WARN] Failed to insert V2 alert: {ex}")
                        
    elif direction == "BEARISH":
        # Expect sequence: Low (S1), High (R1), Low (S2), High (R2)
        if p4['type'] == 'low' and p3['type'] == 'high' and p2['type'] == 'low' and p1['type'] == 'high':
            s1, r1, s2, r2 = p4['price'], p3['price'], p2['price'], p1['price']
            
            # 1. S1 < S2 (Primary support is lower than secondary support)
            # 2. R1 and R2 are close to each other (Double Top resistance level within 2%)
            # 3. S2 is a valid retracement (rests between resistance and primary support)
            is_s_lower = s1 < s2 * 0.99
            is_r_double_top = abs(r1 - r2) / max(r1, r2) <= 0.02
            is_s2_valid_retracement = s1 < s2 < r1
            
            if is_s_lower and is_r_double_top and is_s2_valid_retracement:
                # Breakdown check: Close broke below S2, but still above S1
                if close <= s2 * 0.999 and close > s1:
                    strength = "Strong" if abs(r1 - r2) / r1 <= 0.01 else "Medium"
                    try:
                        db["v2_scanner_alerts"].insert_one({
                          "timestamp": datetime.now(),
                          "ts_ist": get_ts_ist_string(datetime.now()),
                          "symbol": symbol,
                          "timeframe": tf_name,
                          "direction": "BEARISH",
                          "mode": mode,
                          "spot": float(close),
                          "details": f"V2 Early Breakdown: Broke secondary support {s2:.2f} (Primary low: {s1:.2f}) | Resistance: {r2:.2f} | Strength: {strength}"
                        })
                        print(f"[V2 ALERT] {symbol} ({tf_name}) Bearish V2 Crossover!")
                    except Exception as ex:
                        print(f"[WARN] Failed to insert V2 alert: {ex}")

def evaluate_breakout_breakdown(symbol, tf_name, latest_candle, prev_candles, df_all):
    close = latest_candle['close']
    open_val = latest_candle['open']
    volume = latest_candle['volume']
    
    zones = sr_zones.get(symbol, {}).get(tf_name, {})
    resistances = zones.get("resistance", [])
    supports = zones.get("support", [])
    
    # Average volume of previous 20 candles for confirmation
    avg_vol = prev_candles['volume'].tail(20).mean() if len(prev_candles) > 0 else 0
    vol_confirm = volume >= 1.5 * avg_vol if (avg_vol > 0 and config["volume_confirmation"]) else True
    
    # Resolve timeframe mode
    mode = TIMEFRAME_MAP[tf_name][1]
    
    # 1. Evaluate Resistance Breakout
    for res in resistances:
        zone_max = res['max']
        zone_min = res['min']
        
        breakout_threshold = zone_max * (1 + config["breakout_confirm_pct"] / 100)
        
        if close >= breakout_threshold and open_val <= zone_max:
            cooldown_key = f"{symbol}_{tf_name}_BULLISH"
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if cooldown_key in alert_cooldowns and now - alert_cooldowns[cooldown_key] < timedelta(minutes=config["alert_cooldown_min"]):
                continue
                
            if vol_confirm:
                strength = "Strong" if res['touches'] >= 5 else "Medium"
                alert_cooldowns[cooldown_key] = now
                
                print(f"[BREAKOUT] {symbol} ({tf_name}) broke resistance {zone_min:.2f}-{zone_max:.2f} at Close={close:.2f} | Vol={volume} (Avg={avg_vol:.0f})")
                
                try:
                    db["v1_scanner_alerts"].insert_one({
                      "timestamp": now,
                      "ts_ist": get_ts_ist_string(now),
                      "symbol": symbol,
                      "timeframe": tf_name,
                      "direction": "BULLISH",
                      "mode": mode,
                      "spot": float(close),
                      "details": f"Resistance Breakout: {zone_min:.2f}-{zone_max:.2f} | Close: {close:.2f} | Volume: {(volume/avg_vol):.1f}x Average | Strength: {strength}"
                    })
                    
                    # Evaluate V2 cup-and-handle pattern checks across all timeframes
                    for v2_tf, v2_info in TIMEFRAME_MAP.items():
                        if symbol in latest_data and v2_tf in latest_data[symbol]:
                            v2_df = latest_data[symbol][v2_tf]
                            if not v2_df.empty:
                                v2_latest = v2_df.iloc[-1]
                                check_v2_pattern(symbol, v2_tf, v2_df, "BULLISH", v2_latest['close'], v2_latest['open'], v2_info[1])
                except Exception as ex:
                    print(f"[WARN] Failed to insert alert: {ex}")

    # 2. Evaluate Support Breakdown
    for sup in supports:
        zone_max = sup['max']
        zone_min = sup['min']
        
        breakdown_threshold = zone_min * (1 - config["breakout_confirm_pct"] / 100)
        
        if close <= breakdown_threshold and open_val >= zone_min:
            cooldown_key = f"{symbol}_{tf_name}_BEARISH"
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if cooldown_key in alert_cooldowns and now - alert_cooldowns[cooldown_key] < timedelta(minutes=config["alert_cooldown_min"]):
                continue
                
            if vol_confirm:
                strength = "Strong" if sup['touches'] >= 5 else "Medium"
                alert_cooldowns[cooldown_key] = now
                
                print(f"[BREAKDOWN] {symbol} ({tf_name}) broke support {zone_min:.2f}-{zone_max:.2f} at Close={close:.2f} | Vol={volume} (Avg={avg_vol:.0f})")
                
                try:
                    db["v1_scanner_alerts"].insert_one({
                      "timestamp": now,
                      "ts_ist": get_ts_ist_string(now),
                      "symbol": symbol,
                      "timeframe": tf_name,
                      "direction": "BEARISH",
                      "mode": mode,
                      "spot": float(close),
                      "details": f"Support Breakdown: {zone_min:.2f}-{zone_max:.2f} | Close: {close:.2f} | Volume: {(volume/avg_vol):.1f}x Average | Strength: {strength}"
                    })
                    
                    # Evaluate V2 breakdown checks across all timeframes
                    for v2_tf, v2_info in TIMEFRAME_MAP.items():
                        if symbol in latest_data and v2_tf in latest_data[symbol]:
                            v2_df = latest_data[symbol][v2_tf]
                            if not v2_df.empty:
                                v2_latest = v2_df.iloc[-1]
                                check_v2_pattern(symbol, v2_tf, v2_df, "BEARISH", v2_latest['close'], v2_latest['open'], v2_info[1])
                except Exception as ex:
                    print(f"[WARN] Failed to insert alert: {ex}")

def scan_latest_candles():
    global last_processed_ts
    if last_processed_ts is None:
        return
        
    col = db["optstk_history_1m"]
    new_docs = list(col.find({"timestamp": {"$gt": last_processed_ts}}).sort("timestamp", 1))
    
    if not new_docs:
        return
        
    print(f"[TIME] Found {len(new_docs)} new 1-minute ticks. Scanning for breakouts...")
    df_new = pd.DataFrame(new_docs)
    df_new['timestamp'] = pd.to_datetime(df_new['timestamp'])
    
    last_processed_ts = df_new['timestamp'].max()
    
    for symbol, group in df_new.groupby('symbol'):
        group.set_index('timestamp', inplace=True)
        
        for tf_name, tf_info in TIMEFRAME_MAP.items():
            tf_freq, mode = tf_info
            
            if symbol not in latest_data or tf_name not in latest_data[symbol]:
                continue
                
            df_existing = latest_data[symbol][tf_name]
            
            df_new_resampled = group.resample(tf_freq).agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            if df_new_resampled.empty:
                continue
                
            for idx, new_row in df_new_resampled.iterrows():
                if idx in df_existing.index:
                    df_existing.loc[idx, 'high'] = max(df_existing.loc[idx, 'high'], new_row['high'])
                    df_existing.loc[idx, 'low'] = min(df_existing.loc[idx, 'low'], new_row['low'])
                    df_existing.loc[idx, 'close'] = new_row['close']
                    df_existing.loc[idx, 'volume'] = df_existing.loc[idx, 'volume'] + new_row['volume']
                else:
                    df_existing.loc[idx] = new_row
                    
            latest_data[symbol][tf_name] = df_existing
            
            latest_candle = df_existing.iloc[-1]
            prev_candles = df_existing.iloc[:-1]
            evaluate_breakout_breakdown(symbol, tf_name, latest_candle, prev_candles, df_existing)

def main():
    global last_processed_ts, config
    print("[START] Starting Multi-Timeframe Breakout Scanner...")
    build_all_zones()
    
    if last_processed_ts is not None:
        last_processed_ts = last_processed_ts - timedelta(hours=8)
        print(f"[START] Startup scan enabled: scanning all candles since {last_processed_ts}")
        
    # Ensure indexing is set up on target alerts collections
    db["v1_scanner_alerts"].create_index([("timestamp", -1)])
    db["v1_scanner_alerts"].create_index([("mode", 1)])
    db["v2_scanner_alerts"].create_index([("timestamp", -1)])
    db["v2_scanner_alerts"].create_index([("mode", 1)])
    
    print(f"[LOOP] Monitoring loop started. Interval: {config['scan_interval_sec']} seconds.")
    
    while True:
        try:
            # Dynamically reload config so changes take effect without restart
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, "r") as f:
                        config = json.load(f)
                except Exception:
                    pass
            
            if is_market_open():
                scan_latest_candles()
            else:
                pass
        except Exception as e:
            print(f"[ERROR] Error in scan loop: {e}")
            
        time.sleep(config["scan_interval_sec"])

if __name__ == "__main__":
    main()
