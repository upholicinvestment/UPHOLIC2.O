import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        env[parts[0].strip()] = parts[1].strip()
    return env

def main():
    print("=== DHAN WIDE-FORMAT HISTORICAL DATA EXPORTER ===")
    
    # 1. Load env and credentials
    env = load_env()
    token = env.get("DHAN_TOKEN")
    client_id = env.get("DHAN_CLIENT_ID")
    
    if not token or not client_id:
        print("[-] Error: Missing DHAN_TOKEN or DHAN_CLIENT_ID in .env file!")
        return

    # 2. Load symbols
    symbols_file = "symbols.json"
    if not os.path.exists(symbols_file):
        print(f"[-] Error: Symbols file '{symbols_file}' not found!")
        return
        
    with open(symbols_file, "r") as f:
        symbols_list = json.load(f)
        
    total_symbols = len(symbols_list)
    print(f"[+] Loaded {total_symbols} symbols from '{symbols_file}'.")

    # 3. Setup API config
    url = "https://api.dhan.co/v2/charts/intraday"
    headers = {
        "access-token": token,
        "client-id": client_id,
        "Content-Type": "application/json"
    }
    
    # Date Range: 10, 11, 12 Aug 2026
    payload_base = {
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": "1",
        "fromDate": "2026-08-10",
        "toDate": "2026-08-12"
    }

    # 4. Fetch loop
    data_points = []
    summary_list = []
    
    start_time_all = time.time()
    for idx, sym_entry in enumerate(symbols_list, 1):
        symbol = sym_entry.get("symbol")
        sec_id = sym_entry.get("securityId")
        
        print(f"[{idx}/{total_symbols}] Fetching {symbol} (ID: {sec_id})... ", end="", flush=True)
        
        payload = payload_base.copy()
        payload["securityId"] = str(sec_id)
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                res_data = res.json()
                # Dhan returns candles in data['candles'] or directly
                candles = res_data.get("data", {}).get("candles", [])
                if not candles:
                    # check root just in case
                    candles = res_data.get("candles", [])
                    
                if candles:
                    # Parse candles: list of [open, high, low, close, volume, timestamp]
                    for c in candles:
                        c_open, c_high, c_low, c_close, c_volume, c_ts = c[0], c[1], c[2], c[3], c[4], c[5]
                        dt_ist = datetime.fromtimestamp(c_ts, tz=timezone(timedelta(hours=5, minutes=30)))
                        
                        data_points.append({
                            "Datetime (IST)": dt_ist.strftime("%Y-%m-%d %H:%M:%S"),
                            "Symbol": symbol,
                            "Price": float(c_close)
                        })
                    
                    print(f"Success ({len(candles)} candles)")
                    summary_list.append({
                        "Symbol": symbol,
                        "Security ID": sec_id,
                        "Status": "Success",
                        "Candles": len(candles),
                        "Details": ""
                    })
                else:
                    print("Empty")
                    summary_list.append({
                        "Symbol": symbol,
                        "Security ID": sec_id,
                        "Status": "Empty",
                        "Candles": 0,
                        "Details": "No candle data returned"
                    })
            else:
                print(f"Failed (HTTP {res.status_code})")
                summary_list.append({
                    "Symbol": symbol,
                    "Security ID": sec_id,
                    "Status": "Error",
                    "Candles": 0,
                    "Details": f"HTTP {res.status_code}: {res.text[:100]}"
                })
        except Exception as e:
            error_msg = str(e)
            print(f"Error ({error_msg})")
            summary_list.append({
                "Symbol": symbol,
                "Security ID": sec_id,
                "Status": "Error",
                "Candles": 0,
                "Details": error_msg
            })
            
        # Respect API rates politely
        time.sleep(0.1)

    duration = time.time() - start_time_all
    print(f"\n[+] Fetch complete! Total time: {duration/60:.2f} minutes.")
    
    # 5. Create Wide DataFrame
    if not data_points:
        print("[-] Error: No data points fetched. Cannot write CSV files.")
        return
        
    print("[+] Pivoting data to wide format (Symbols as columns, Datetime as index)...")
    df = pd.DataFrame(data_points)
    
    # Pivot: Datetime (IST) as Index, Symbol as Columns, Price as Values
    df_pivot = df.pivot(index="Datetime (IST)", columns="Symbol", values="Price")
    
    # Sort index chronologically
    df_pivot.index = pd.to_datetime(df_pivot.index)
    df_pivot = df_pivot.sort_index()
    df_pivot.index = df_pivot.index.strftime('%Y-%m-%d %H:%M:%S')
    
    # Reset index to make Datetime (IST) a column
    df_csv = df_pivot.reset_index()
    df_sum = pd.DataFrame(summary_list)
    
    # 6. Export to CSV
    filename = "Dhan_Historical_Stock_Prices_1M_Aug10_12.csv"
    summary_filename = "Dhan_Historical_Stock_Prices_1M_Aug10_12_Summary.csv"
    print(f"[+] Writing data to CSV file: {filename}...")
    df_csv.to_csv(filename, index=False)
    
    print(f"[+] Writing summary to CSV file: {summary_filename}...")
    df_sum.to_csv(summary_filename, index=False)
    
    print(f"[+] CSV files successfully saved:\n  - '{filename}'\n  - '{summary_filename}'")

if __name__ == "__main__":
    main()
