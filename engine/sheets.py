import os
import json
import gspread
import pandas as pd

def authenticate_gspread():
    creds_json = os.environ.get("GCP_CREDENTIALS")
    if not creds_json:
        raise ValueError("GCP_CREDENTIALS not found.")
    creds_dict = json.loads(creds_json)
    return gspread.service_account_from_dict(creds_dict)

def get_workbook(gc):
    sheet_id = os.environ.get("SPREADSHEET_ID")
    if not sheet_id:
        raise ValueError("SPREADSHEET_ID not found.")
    return gc.open_by_key(sheet_id)

def update_game_day_tab(sh, df):
    """Overwrites the Game_Day tab for the Canvas HUD."""
    ws_live = sh.worksheet("Game_Day")
    ws_live.clear()
    
    # Convert DataFrame to a list of lists, including the header
    data = [df.columns.values.tolist()] + df.values.tolist()
    
    ws_live.update(range_name="A1", values=data)
    print("Game_Day tab overwritten successfully.")

def append_sim_ledger(sh, df, metadata):
    """Appends to the historical database tab."""
    ws_ledger = sh.worksheet("Sim_Ledger")
    
    ledger_df = df.copy()
    # Insert metadata at the front
    ledger_df.insert(0, "game_id", metadata.get("game_id", "N/A"))
    ledger_df.insert(1, "game_date", metadata.get("game_date", "N/A"))
    ledger_df.insert(2, "opponent", metadata.get("opponent", "N/A"))
    ledger_df.insert(3, "venue", metadata.get("venue", "N/A"))
    ledger_df.insert(4, "sim_timestamp_utc", metadata.get("timestamp", "N/A"))
    
    # Convert DataFrame to list of lists (excluding header since we are appending)
    data = ledger_df.values.tolist()
    
    ws_ledger.append_rows(values=data, value_input_option="USER_ENTERED")
    print("Sim_Ledger tab appended successfully.")
