import pymongo
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")

client = pymongo.MongoClient(MONGO_URI)
db = client[db_name]

# Load Voltase candles
symbol = 'VOLTAS'
col = db["optstk_history_1m"]
cursor = col.find({"symbol": symbol}).sort("timestamp", 1)
docs = list(cursor)

df = pd.DataFrame(docs)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

# Build zones using data BEFORE today
df_before_today = df[df.index < '2026-08-10']

# TIMEFRAME_MAP
TIMEFRAME_MAP = {
    "15 Minutes": ("15min", "INTRADAY"),
    "30 Minutes": ("30min", "INTRADAY"),
    "45 Minutes": ("45min", "INTRADAY"),
    "1 Hour": ("60min", "INTRADAY"),
}

def calculate_swing_highs_lows(df, window):
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)
    for i in range(window, n - window):
        if highs[i] == max(highs[i - window : i + window + 1]):
            if highs[i] > highs[i - 1] or highs[i] > highs[i + 1]:
                swing_highs[i] = True
        if lows[i] == min(lows[i - window : i + window + 1]):
            if lows[i] < lows[i - 1] or lows[i] < lows[i + 1]:
                swing_lows[i] = True
    return swing_highs, swing_lows

def cluster_prices_into_zones(prices, zone_width_pct, min_touches):
    if not prices:
        return []
    prices = sorted(prices)
    zones = []
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

sr_zones = {}
latest_data = {}

for tf_name, tf_info in TIMEFRAME_MAP.items():
    tf_freq, mode = tf_info
    df_resampled = df_before_today.resample(tf_freq).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    sh, sl = calculate_swing_highs_lows(df_resampled, 5)
    df_resampled['swing_high'] = sh
    df_resampled['swing_low'] = sl
    high_prices = df_resampled[df_resampled['swing_high']]['high'].tolist()
    low_prices = df_resampled[df_resampled['swing_low']]['low'].tolist()
    
    resistances = cluster_prices_into_zones(high_prices, 0.5, 3)
    supports = cluster_prices_into_zones(low_prices, 0.5, 3)
    
    sr_zones[tf_name] = {"resistance": resistances, "support": supports}
    latest_data[tf_name] = df_resampled

print("Zones loaded.")

# Now simulate processing today's candles one by one
today_candles = df[df.index >= '2026-08-10']
print(f"Today candles to process: {len(today_candles)}")

# Group by day or just process chronologically
for idx, row in today_candles.iterrows():
    # Update resampled dataframes
    for tf_name, tf_info in TIMEFRAME_MAP.items():
        tf_freq, mode = tf_info
        df_existing = latest_data[tf_name]
        
        # Resample the single tick
        tick_df = pd.DataFrame([row])
        tick_df.index = [idx]
        df_new_resampled = tick_df.resample(tf_freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        
        for res_idx, new_row in df_new_resampled.iterrows():
            if res_idx in df_existing.index:
                df_existing.loc[res_idx, 'high'] = max(df_existing.loc[res_idx, 'high'], new_row['high'])
                df_existing.loc[res_idx, 'low'] = min(df_existing.loc[res_idx, 'low'], new_row['low'])
                df_existing.loc[res_idx, 'close'] = new_row['close']
                df_existing.loc[res_idx, 'volume'] = df_existing.loc[res_idx, 'volume'] + new_row['volume']
            else:
                df_existing.loc[res_idx] = new_row
                
        latest_data[tf_name] = df_existing
        latest_candle = df_existing.iloc[-1]
        prev_candles = df_existing.iloc[:-1]
        
        # Evaluate
        close = latest_candle['close']
        open_val = latest_candle['open']
        volume = latest_candle['volume']
        
        zones = sr_zones[tf_name]
        resistances = zones["resistance"]
        supports = zones["support"]
        
        avg_vol = prev_candles['volume'].tail(20).mean() if len(prev_candles) > 0 else 0
        
        # Scenario A: volume_confirmation = True
        vol_confirm_true = volume >= 1.5 * avg_vol if (avg_vol > 0) else True
        # Scenario B: volume_confirmation = False
        vol_confirm_false = True
        
        for res in resistances:
            zone_max = res['max']
            zone_min = res['min']
            breakout_threshold = zone_max * 1.001
            
            if close >= breakout_threshold and open_val <= zone_max:
                print(f"[POTENTIAL BREAKOUT] {tf_name} at {idx} | Close: {close} | Open: {open_val} | VolConfirmTrue: {vol_confirm_true} | VolConfirmFalse: {vol_confirm_false}")
                
        for sup in supports:
            zone_max = sup['max']
            zone_min = sup['min']
            breakdown_threshold = zone_min * 0.999
            
            if close <= breakdown_threshold and open_val >= zone_min:
                print(f"[POTENTIAL BREAKDOWN] {tf_name} at {idx} | Close: {close} | Open: {open_val} | VolConfirmTrue: {vol_confirm_true} | VolConfirmFalse: {vol_confirm_false}")

client.close()
