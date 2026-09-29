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

def update_game_day_tab(sh, df_goalies, df_skaters, metadata):
    """Overwrites the Game_Day tab for the Canvas HUD with Goalie Block and Skater Grid."""
    ws_live = sh.worksheet("Game_Day")
    ws_live.clear()
    
    # 1. Build Goalie Block
    goalie_header = df_goalies.columns.values.tolist()
    goalie_data = df_goalies.values.tolist()
    
    # 2. Build Skater Grid
    skater_header = df_skaters.columns.values.tolist()
    skater_data = df_skaters.values.tolist()
    
    # Combine everything with padding
    full_data = [
        [f"Game: VGK vs {metadata.get('opponent')} ({metadata.get('venue')})", f"Date: {metadata.get('game_date')}", f"Puck Drop: {metadata.get('start_time', 'N/A')}"],
        [], # Row 2 empty separator
        goalie_header
    ] + goalie_data + [
        [], # Empty separator before skater grid
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
    
    start_row = 6 + len(goalie_data)
    end_row = start_row + len(skater_data) - 1
    
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

def update_game_lines_tab(sh, df_lines, metadata):
    """Overwrites the Game_Lines tab with Team-level metrics and OT odds."""
    try:
        ws_lines = sh.worksheet("Game_Lines")
    except Exception:
        ws_lines = sh.add_worksheet(title="Game_Lines", rows="100", cols="20")
        
    ws_lines.clear()
    
    header = df_lines.columns.values.tolist()
    data = df_lines.values.tolist()
    
    full_data = [
        [f"Game: VGK vs {metadata.get('opponent')} ({metadata.get('venue')})", f"Date: {metadata.get('game_date')}", f"Puck Drop: {metadata.get('start_time', 'N/A')}"],
        [],
        header
    ] + data
    
    ws_lines.update(range_name="A1", values=full_data)
    print("Game_Lines tab overwritten successfully.")

def append_sim_ledger(sh, df_goalies, df_skaters, metadata):
    """Appends to the historical database tab, flagging Record_Type."""
    ws_ledger = sh.worksheet("Sim_Ledger")
    
    # Process Skaters
    ledger_skaters = df_skaters.copy()
    ledger_skaters.insert(0, "Record_Type", "SKATER")
    
    # Process Goalies
    ledger_goalie = df_goalies.copy()
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
