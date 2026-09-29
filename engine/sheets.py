import os
import json
import gspread
import gspread_formatting as gsf
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

def update_game_day_tab(sh, df_goalie, df_skaters, metadata):
    """Overwrites the Game_Day tab for the Canvas HUD with Goalie Block and Skater Grid."""
    ws_live = sh.worksheet("Game_Day")
    ws_live.clear()
    
    # 1. Build Goalie Block (Rows 1-4)
    # Row 1: Header
    goalie_header = df_goalie.columns.values.tolist()
    # Row 2: Goalie Data
    goalie_data = df_goalie.values.tolist()[0]
    
    # 2. Build Skater Grid (Row 5 header, Row 6+ data)
    skater_header = df_skaters.columns.values.tolist()
    skater_data = df_skaters.values.tolist()
    
    # Combine everything with padding
    full_data = [
        [f"Game: VGK vs {metadata.get('opponent')} ({metadata.get('venue')})", f"Date: {metadata.get('game_date')}", f"Puck Drop: {metadata.get('start_time', 'N/A')}"],
        [], # Row 2 empty separator
        goalie_header,
        goalie_data,
        [], # Row 5 empty
        skater_header
    ] + skater_data
    
    ws_live.update(range_name="A1", values=full_data)
    
    # 3. Conditional Formatting for Top 3
    target_cols = ["PIM_Over_1.5_%", "Exp_SOG", "SOG_P80", "Anytime_Goal_%", "Exp_Assists", "Over_0.5_Pt_%"]
    
    def col_num_to_letter(n):
        string = ""
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            string = chr(65 + remainder) + string
        return string
        
    rules = gsf.get_conditional_format_rules(ws_live)
    rules.clear()
    
    start_row = 7
    end_row = 6 + len(skater_data)
    
    for col_name in target_cols:
        if col_name in skater_header:
            col_idx = skater_header.index(col_name)
            col_letter = col_num_to_letter(col_idx + 1)
            range_str = f"{col_letter}{start_row}:{col_letter}{end_row}"
            
            formula = f"={col_letter}{start_row}>=LARGE({col_letter}${start_row}:{col_letter}${end_row}, 3)"
            
            rule = gsf.ConditionalFormatRule(
                ranges=[gsf.GridRange.from_a1_range(range_str, ws_live)],
                booleanRule=gsf.BooleanRule(
                    condition=gsf.BooleanCondition('CUSTOM_FORMULA', [formula]),
                    format=gsf.CellFormat(backgroundColor=gsf.color(0.85, 0.93, 0.83))
                )
            )
            rules.append(rule)
            
    rules.save()
    print("Game_Day tab overwritten successfully with Hybrid Layout and Formatting.")

def append_sim_ledger(sh, df_goalie, df_skaters, metadata):
    """Appends to the historical database tab, flagging Record_Type."""
    ws_ledger = sh.worksheet("Sim_Ledger")
    
    # Process Skaters
    ledger_skaters = df_skaters.copy()
    ledger_skaters.insert(0, "Record_Type", "SKATER")
    
    # Process Goalie (aligning columns dynamically or just storing core metrics as JSON?)
    # The spec says "flat skater rows stamped with metadata... plus the goalie summary row flagged with Record_Type = 'GOALIE'"
    # To append perfectly flat, they should share a schema or we just align overlapping names.
    # We will align them by using a dictionary approach.
    ledger_goalie = df_goalie.copy()
    ledger_goalie.insert(0, "Record_Type", "GOALIE")
    # Rename Goalie_Name to Name to fit the Name column
    ledger_goalie.rename(columns={"Goalie_Name": "Name"}, inplace=True)
    
    # Combine rows
    combined_df = pd.concat([ledger_goalie, ledger_skaters], ignore_index=True)
    
    # Insert Metadata at the very front
    combined_df.insert(0, "game_id", metadata.get("game_id", "N/A"))
    combined_df.insert(1, "game_date", metadata.get("game_date", "N/A"))
    combined_df.insert(2, "opponent", metadata.get("opponent", "N/A"))
    combined_df.insert(3, "venue", metadata.get("venue", "N/A"))
    combined_df.insert(4, "sim_timestamp_utc", metadata.get("timestamp", "N/A"))
    
    # Fill NaNs with empty string so gspread doesn't break
    combined_df = combined_df.fillna("")
    
    data = combined_df.values.tolist()
    ws_ledger.append_rows(values=data, value_input_option="USER_ENTERED")
    print("Sim_Ledger tab appended successfully with Skater and Goalie rows.")
