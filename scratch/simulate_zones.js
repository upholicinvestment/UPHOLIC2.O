// import pymongo
// import pandas as pd
// import numpy as np
// import os
// import sys

// MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
// db_name = os.getenv("MONGO_DB", "UPHOLIC2_O")

// client = pymongo.MongoClient(MONGO_URI)
// db = client[db_name]

// # Copy the exact functions from breakout_scanner.py to see what zones are generated
// def calculate_swing_highs_lows(df, window):
//     highs = df['high'].values
//     lows = df['low'].values
//     n = len(df)
    
//     swing_highs = np.zeros(n, dtype=bool)
//     swing_lows = np.zeros(n, dtype=bool)
    
//     for i in range(window, n - window):
//         if highs[i] == max(highs[i - window : i + window + 1]):
//             if highs[i] > highs[i - 1] or highs[i] > highs[i + 1]:
//                 swing_highs[i] = True
//         if lows[i] == min(lows[i - window : i + window + 1]):
//             if lows[i] < lows[i - 1] or lows[i] < lows[i + 1]:
//                 swing_lows[i] = True
//     return swing_highs, swing_lows

// def cluster_prices_into_zones(prices, zone_width_pct, min_touches):
//     if not prices:
//         return []
//     prices = sorted(prices)
//     zones = []
//     current_cluster = [prices[0]]
//     for i in range(1, len(prices)):
//         price = prices[i]
//         avg_cluster_price = sum(current_cluster) / len(current_cluster)
//         max_dist = avg_cluster_price * (zone_width_pct / 100)
//         if price - current_cluster[0] <= max_dist:
//             current_cluster.append(price)
//         else:
//             if len(current_cluster) >= min_touches:
//                 zones.append({
//                     "min": min(current_cluster),
//                     "max": max(current_cluster),
//                     "touches": len(current_cluster)
//                 })
//             current_cluster = [price]
//     if len(current_cluster) >= min_touches:
//         zones.append({
//             "min": min(current_cluster),
//             "max": max(current_cluster),
//             "touches": len(current_cluster)
//         })
//     return zones

// TIMEFRAME_MAP = {
//     "15 Minutes": ("15min", "INTRADAY"),
//     "30 Minutes": ("30min", "INTRADAY"),
//     "45 Minutes": ("45min", "INTRADAY"),
//     "1 Hour": ("60min", "INTRADAY"),
//     "2 Hours": ("120min", "INTRADAY"),
//     "3 Hours": ("180min", "INTRADAY"),
//     "4 Hours": ("240min", "INTRADAY"),
//     "1 Day": ("1D", "POSITIONAL"),
//     "1 Week": ("1W", "POSITIONAL")
// }

// # Try calculating for VOLTAS
// symbol = 'VOLTAS'
// col = db["optstk_history_1m"]
// cursor = col.find({"symbol": symbol}).sort("timestamp", 1)
// docs = list(cursor)

// if not docs:
//     print('No Voltase docs found in optstk_history_1m!')
//     sys.exit(0)

// df = pd.DataFrame(docs)
// df['timestamp'] = pd.to_datetime(df['timestamp'])
// df.set_index('timestamp', inplace=True)

// print(f"Loaded {len(df)} Voltase candles.")

// for tf_name, tf_info in TIMEFRAME_MAP.items():
//     tf_freq, mode = tf_info
//     df_resampled = df.resample(tf_freq).agg({
//         'open': 'first',
//         'high': 'max',
//         'low': 'min',
//         'close': 'last',
//         'volume': 'sum'
//     }).dropna()
    
//     # Check length
//     min_candles = 5 * 2 + 5 # swing_window=5
//     swing_window = 5
//     if tf_name == "1 Week":
//         min_candles = 3
//         swing_window = 1
//     elif tf_name == "1 Day":
//         min_candles = 10
//         swing_window = 3
        
//     print(f"\nTimeframe: {tf_name} | Length: {len(df_resampled)}")
//     if len(df_resampled) < min_candles:
//         print(f"  Skipping (too few candles: {len(df_resampled)} < {min_candles})")
//         continue
        
//     sh, sl = calculate_swing_highs_lows(df_resampled, swing_window)
//     df_resampled['swing_high'] = sh
//     df_resampled['swing_low'] = sl
    
//     high_prices = df_resampled[df_resampled['swing_high']]['high'].tolist()
//     low_prices = df_resampled[df_resampled['swing_low']]['low'].tolist()
    
//     min_touches = 3
//     if tf_name in ["1 Day", "1 Week"]:
//         min_touches = 2
        
//     resistances = cluster_prices_into_zones(high_prices, 0.5, min_touches)
//     supports = cluster_prices_into_zones(low_prices, 0.5, min_touches)
    
//     print(f"  Swing Highs: {len(high_prices)} | Resistances found: {len(resistances)}")
//     if resistances:
//         print(f"    Resistances: {resistances}")
//     print(f"  Swing Lows: {len(low_prices)} | Supports found: {len(supports)}")
//     if supports:
//         print(f"    Supports: {supports}")

// client.close()
