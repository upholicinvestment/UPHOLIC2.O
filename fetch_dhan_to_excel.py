import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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

    # Data collection list for 1-minute close prices
    data_points = []
    summary_list = []
    
    ist = timezone(timedelta(hours=5, minutes=30))
    
    # 4. Fetch loop
    print("\n[+] Starting data fetch from Dhan API (with 0.1s delay between calls)...")
    start_time_all = time.time()
    
    for index, item in enumerate(symbols_list, start=1):
        symbol = item.get("symbol")
        security_id = item.get("security_id")
        exchange_segment = item.get("exchange_segment", "NSE_EQ")
        
        print(f"[{index}/{total_symbols}] Fetching {symbol} (ID: {security_id})...", end="", flush=True)
        
        payload = payload_base.copy()
        payload["securityId"] = str(security_id)
        payload["exchangeSegment"] = exchange_segment
        
        success = False
        retries = 2
        candles_count = 0
        error_msg = ""
        
        for attempt in range(retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                if response.status_code == 200:
                    res_json = response.json()
                    
                    # Parse arrays
                    closes = res_json.get("close", [])
                    timestamps = res_json.get("timestamp", [])
                    
                    candles_count = len(timestamps)
                    
                    if candles_count > 0:
                        # Populate raw data
                        for i in range(candles_count):
                            dt = datetime.fromtimestamp(timestamps[i], tz=timezone.utc).astimezone(ist)
                            dt_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                            data_points.append({
                                "Symbol": symbol,
                                "Datetime (IST)": dt_str,
                                "Price": closes[i]
                            })
                        
                        success = True
                        break
                    else:
                        error_msg = "API returned 200 but empty candle lists"
                else:
                    error_msg = f"HTTP Error {response.status_code}: {response.text}"
            except Exception as e:
                error_msg = str(e)
            
            # Brief wait before retry
            time.sleep(0.5)
            
        if success:
            print(f" Success ({candles_count} candles)")
            summary_list.append({
                "Symbol": symbol,
                "Security ID": security_id,
                "Status": "Success",
                "Candles": candles_count,
                "Details": ""
            })
        else:
            print(f" Failed: {error_msg}")
            summary_list.append({
                "Symbol": symbol,
                "Security ID": security_id,
                "Status": "Failed",
                "Candles": 0,
                "Details": error_msg
            })
            
        # Respect API rates politely
        time.sleep(0.1)

    duration = time.time() - start_time_all
    print(f"\n[+] Fetch complete! Total time: {duration/60:.2f} minutes.")
    
    # 5. Create Wide DataFrame
    if not data_points:
        print("[-] Error: No data points fetched. Cannot write Excel file.")
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
    df_excel = df_pivot.reset_index()
    
    df_sum = pd.DataFrame(summary_list)
    
    # 6. Export to Excel
    filename = "Dhan_Historical_Stock_Prices_1M_Aug10_12.xlsx"
    print(f"[+] Writing data to Excel file: {filename}...")
    
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df_excel.to_excel(writer, sheet_name="Stock_Prices_1M", index=False)
        df_sum.to_excel(writer, sheet_name="Fetch_Summary", index=False)
        
    # Apply premium styling to Excel sheets efficiently
    print("[+] Applying premium styling to Excel sheets...")
    wb = openpyxl.load_workbook(filename)
    
    # Colors and Fonts
    font_family = "Segoe UI"
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid") # Navy Blue
    
    data_font = Font(name=font_family, size=10)
    zebra_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid") # Soft light blue-gray
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    left_align = Alignment(horizontal="left", vertical="center")
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")
    
    # Format Sheet 1: Stock_Prices_1M
    ws_prices = wb["Stock_Prices_1M"]
    ws_prices.views.sheetView[0].showGridLines = True
    
    # Style Header Row (Row 1)
    for col_idx in range(1, ws_prices.max_column + 1):
        cell = ws_prices.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border
        
    # Style Data Rows
    # To run instantly without slow cell-by-cell loops:
    # 1. Format Datetime column (Col 1)
    # 2. Format Stock Price columns (Col 2 to Max Column)
    print("  - Styling prices worksheet...")
    for col_idx in range(1, ws_prices.max_column + 1):
        col_letter = get_column_letter(col_idx)
        ws_prices.column_dimensions[col_letter].width = 15 # set a clean fixed width for all columns
        
        # Style each cell in this column
        for row_idx in range(2, ws_prices.max_row + 1):
            cell = ws_prices.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            
            # Apply light zebra fill
            if row_idx % 2 == 0:
                cell.fill = zebra_fill
            else:
                cell.fill = white_fill
                
            # Alignments & formats
            if col_idx == 1:
                cell.alignment = center_align
            else:
                cell.alignment = right_align
                cell.number_format = "0.00"

    # Format Sheet 2: Fetch_Summary
    ws_sum = wb["Fetch_Summary"]
    ws_sum.views.sheetView[0].showGridLines = True
    
    # Style Header Row
    for col_idx in range(1, ws_sum.max_column + 1):
        cell = ws_sum.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border
        
    # Style Data Rows
    print("  - Styling summary worksheet...")
    for row_idx in range(2, ws_sum.max_row + 1):
        is_even = (row_idx % 2 == 0)
        row_fill = zebra_fill if is_even else white_fill
        
        status_val = ws_sum.cell(row=row_idx, column=3).value
        status_color = "E2EFDA" if status_val == "Success" else "FCE4D6"
        status_fill = PatternFill(start_color=status_color, end_color=status_color, fill_type="solid")
        
        for col_idx in range(1, ws_sum.max_column + 1):
            cell = ws_sum.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = thin_border
            
            if col_idx == 3:
                cell.fill = status_fill
                cell.font = Font(name=font_family, size=10, bold=True, color="375623" if status_val == "Success" else "C65911")
                cell.alignment = center_align
            else:
                cell.fill = row_fill
                if col_idx in [1, 2]:
                    cell.alignment = left_align
                elif col_idx == 4:
                    cell.alignment = center_align
                    cell.number_format = "#,##0"
                else:
                    cell.alignment = left_align
                    
    # Auto-adjust column widths for summary sheet
    for col in ws_sum.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_sum.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Save workbook
    wb.save(filename)
    print(f"[+] Excel file successfully saved and formatted: '{filename}'")

if __name__ == "__main__":
    main()
