import os
import sys
from datetime import datetime
import pymongo
import pandas as pd

# Add root folder to python path so we can import breakout_scanner_ui
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set env variables before importing
os.environ["MONGO_URI"] = "mongodb://localhost:27017/UPHOLIC2_O"

from breakout_scanner_ui import (
    get_db,
    load_data,
    load_stock_history,
    load_all_stocks_history_today,
    load_live_breakout_alerts_today,
    load_live_v2_alerts_today,
    load_breakout_signals,
    parse_db_options_df
)

def run_tests():
    print("=== STARTING STREAMLIT UI DATABASE CONNECTOR TESTS ===")
    
    db = get_db()
    print(f"Connected to database: {db.name}")
    
    # 1. Prepare mock snapshot matching our independent flat options schema
    today_str = datetime.now().strftime("%Y-%m-%d")
    mock_doc = {
        "symbol": "TATA_STEEL",
        "security_id": "3012",
        "spot_price": 150.0,
        "expiry": "2026-08-25",
        "fetched_at": datetime.now(),
        "ts_ist": f"{today_str} 14:15:00.000 IST",
        "iv4": 22.5,
        "ce_iv_oi_weighted": 21.0,
        "pe_iv_oi_weighted": 24.0,
        "iv_skew": 3.0,
        "iv_ratio": 1.143,
        "call_net_flow": 12000.0,
        "put_net_flow": -8000.0,
        "Flip_strike": 150,
        "iv4_change_5m": 0.5,
        "top_strike_iv_change_5m": {
            "strike": 150,
            "side": "CE",
            "old_iv": 20.5,
            "new_iv": 21.0,
            "change": 0.5
        },
        "options": [
            {
                "strike": 150,
                "type": "CE",
                "ltp": 5.2,
                "oi": 50000,
                "previous_close_price": 5.0,
                "previous_oi": 48000,
                "volume": 2000,
                "iv": 21.0
            },
            {
                "strike": 150,
                "type": "PE",
                "ltp": 4.8,
                "oi": 40000,
                "previous_close_price": 4.9,
                "previous_oi": 38000,
                "volume": 1800,
                "iv": 24.0
            }
        ]
    }
    
    # 2. Write mock data to latest_snapshot and snapshots
    print("\nInserting test data into 'latest_snapshot' and 'snapshots' collections...")
    db.latest_snapshot.update_one({"symbol": "TATA_STEEL"}, {"$set": mock_doc}, upsert=True)
    
    snapshot_hist_doc = mock_doc.copy()
    snapshot_hist_doc["ts"] = datetime.now()
    db.snapshots.insert_one(snapshot_hist_doc)
    
    # Write mock alerts (both V1 and V2)
    mock_alert = {
        "timestamp": datetime.now(),
        "ts_ist": f"{today_str} 14:15:00.000 IST",
        "symbol": "TATA_STEEL",
        "direction": "BULLISH",
        "mode": "INTRADAY",
        "spot": 151.2,
        "details": "Crossed Flip. Flow: +ve"
    }
    db.v1_scanner_alerts.insert_one(mock_alert)
    db.v2_scanner_alerts.insert_one(mock_alert)
    print("Mock database setup complete.")
    
    # Clear Streamlit cache so functions fetch the newly inserted mock data
    load_data.clear()
    load_stock_history.clear()
    load_all_stocks_history_today.clear()
    load_breakout_signals.clear()
    
    # 3. Test load_data
    print("\n[Test 1] Testing load_data()...")
    df_data = load_data()
    print("Loaded data columns:", df_data.columns.tolist())
    assert not df_data.empty, "Data should not be empty"
    tata_row = df_data[df_data["underlying_symbol"] == "TATA_STEEL"].iloc[0]
    print(f"Tata Steel row - IV4: {tata_row['iv4']}%, Last Price: {tata_row['last_price']}, Expiry: {tata_row['expiry']}")
    assert tata_row["iv4"] == 22.5
    assert tata_row["last_price"] == 150.0
    assert tata_row["expiry"] == "2026-08-25"
    print("[OK] load_data() test passed.")
    
    # 4. Test load_stock_history
    print("\n[Test 2] Testing load_stock_history()...")
    df_hist = load_stock_history("TATA_STEEL")
    print(f"Loaded {len(df_hist)} history entries for TATA_STEEL today.")
    assert not df_hist.empty, "Stock history should not be empty"
    assert "iv4" in df_hist.columns
    print("[OK] load_stock_history() test passed.")
    
    # 5. Test load_all_stocks_history_today
    print("\n[Test 3] Testing load_all_stocks_history_today()...")
    df_all_hist = load_all_stocks_history_today()
    print("Loaded all stocks history columns:", df_all_hist.columns.tolist())
    assert not df_all_hist.empty, "All stocks history should not be empty"
    print("[OK] load_all_stocks_history_today() test passed.")
    
    # 6. Test load_live_breakout_alerts_today (V1)
    print("\n[Test 4] Testing load_live_breakout_alerts_today()...")
    alerts = load_live_breakout_alerts_today()
    print(f"Loaded {len(alerts)} alerts.")
    assert len(alerts) > 0, "Should load at least 1 alert"
    assert alerts[0]["symbol"] == "TATA_STEEL"
    assert alerts[0]["direction"] == "BULLISH"
    print("[OK] load_live_breakout_alerts_today() test passed.")
    
    # Test load_live_v2_alerts_today
    print("\n[Test 4.5] Testing load_live_v2_alerts_today()...")
    v2_alerts = load_live_v2_alerts_today()
    print(f"Loaded {len(v2_alerts)} V2 alerts.")
    assert len(v2_alerts) > 0, "Should load at least 1 V2 alert"
    assert v2_alerts[0]["symbol"] == "TATA_STEEL"
    print("[OK] load_live_v2_alerts_today() test passed.")
    
    # 7. Test parse_db_options_df & load_breakout_signals
    print("\n[Test 5] Testing parse_db_options_df() and load_breakout_signals()...")
    df_opt = parse_db_options_df(mock_doc)
    print("Parsed options dataframe:")
    print(df_opt)
    assert len(df_opt) == 2, "Should parse exactly 2 option legs"
    
    df_sigs = load_breakout_signals()
    print("Breakout signals:")
    print(df_sigs)
    assert not df_sigs.empty
    print("[OK] parse_db_options_df() and load_breakout_signals() test passed.")
    
    # 8. Clean up mock database records
    print("\nCleaning up database records...")
    db.latest_snapshot.delete_one({"symbol": "TATA_STEEL"})
    db.snapshots.delete_many({"symbol": "TATA_STEEL"})
    db.v1_scanner_alerts.delete_many({"symbol": "TATA_STEEL"})
    db.v2_scanner_alerts.delete_many({"symbol": "TATA_STEEL"})
    print("Cleanup completed.")
    
    print("\n=== ALL STREAMLIT UI DATABASE CONNECTOR TESTS PASSED! ===")

if __name__ == "__main__":
    run_tests()
