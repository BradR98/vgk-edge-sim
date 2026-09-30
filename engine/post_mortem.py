import os
import sys
import gspread
import pandas as pd
from datetime import datetime, timedelta, timezone
from nhlpy import NHLClient
from engine.sheets import authenticate_gspread, get_workbook

def calculate_payout(odds, stake):
    """Calculates profit based on American odds."""
    if odds > 0:
        return stake * (odds / 100.0)
    else:
        return stake / (abs(odds) / 100.0)

def parse_boxscore_stats(boxscore):
    actuals = {}
    for team_key in ['awayTeam', 'homeTeam']:
        team_data = boxscore.get('playerByGameStats', {}).get(team_key, {})
        for pos_group in ['forwards', 'defense', 'goalies']:
            for player in team_data.get(pos_group, []):
                name = player.get('name', {}).get('default', 'Unknown')
                
                # Use strict lowercase for market mapping
                if pos_group == 'goalies':
                    actuals[name] = {
                        'shots against': player.get('shotsAgainst', 0),
                        'goals against': player.get('goalsAgainst', 0),
                        'save percentage': player.get('savePctg', 0.0),
                    }
                else:
                    actuals[name] = {
                        'sog': player.get('sog', 0),
                        'goals': player.get('goals', 0),
                        'assists': player.get('assists', 0),
                        'points': player.get('points', 0),
                        'pim': player.get('pim', 0)
                    }
                    
    # Parse Team Actuals
    away_score = boxscore.get('awayTeam', {}).get('score', 0)
    away_sog = boxscore.get('awayTeam', {}).get('sog', 0)
    home_score = boxscore.get('homeTeam', {}).get('score', 0)
    home_sog = boxscore.get('homeTeam', {}).get('sog', 0)
    
    is_vgk_home = boxscore.get('homeTeam', {}).get('abbrev') == 'VGK'
    
    team_actuals = {
        'vgk_goals': home_score if is_vgk_home else away_score,
        'vgk_sog': home_sog if is_vgk_home else away_sog,
        'opp_goals': away_score if is_vgk_home else home_score,
        'opp_sog': away_sog if is_vgk_home else home_sog,
        'went_to_ot': boxscore.get('gameOutcome', {}).get('lastPeriodType') in ['OT', 'SO']
    }
    
    return actuals, team_actuals

def get_actuals_for_player(actuals_dict, player_str, player_mapping):
    """Matches user input or simulation full names against the boxscore using the Player_Map tab."""
    # 1. Exact match
    if player_str in actuals_dict:
        return actuals_dict[player_str]
        
    # 2. Map lookup
    mapped_name = player_mapping.get(player_str.lower().strip())
    if mapped_name and mapped_name in actuals_dict:
        return actuals_dict[mapped_name]
            
    return {}

def run_post_mortem():
    # 1. Init API and Sheets
    client = NHLClient()
    
    if not os.environ.get("GCP_CREDENTIALS") or not os.environ.get("SPREADSHEET_ID"):
        print("Missing GCP credentials. Exiting post_mortem.")
        return
        
    gc = authenticate_gspread()
    sh = get_workbook(gc)
    
    try:
        ws_wagers = sh.worksheet("Wager_Tracker")
    except Exception:
        # Create Wager_Tracker if it doesn't exist
        ws_wagers = sh.add_worksheet(title="Wager_Tracker", rows="1000", cols="20")
        ws_wagers.append_row(["Game_ID", "Player", "Market", "Line", "Odds", "Stake", "Actual", "Grade", "Payout", "Running_Bankroll"])
        
    try:
        ws_audit = sh.worksheet("Model_Audit")
    except Exception:
        ws_audit = sh.add_worksheet(title="Model_Audit", rows="1000", cols="20")
        ws_audit.append_row(["Game_ID", "Player", "Record_Type", "Metric", "Projection", "Actual", "Diff"])
        
    # Load Player_Map
    try:
        ws_map = sh.worksheet("Player_Map")
        # Check if it needs auto-populating
        if len(ws_map.get_all_values()) <= 1:
            raise Exception("Needs population")
    except Exception:
        try:
            ws_map = sh.worksheet("Player_Map")
            ws_map.clear()
        except Exception:
            ws_map = sh.add_worksheet(title="Player_Map", rows="500", cols="5")
            
        ws_map.append_row(["Boxscore_Name", "Full_Name", "Alias_1", "Alias_2", "Alias_3"])
        
        try:
            # Dynamically fetch active roster and build mapping table
            season = "20262027"
            roster = client.teams.team_roster("VGK", season)
            new_rows = []
            for pos_group in ['forwards', 'defensemen', 'goalies']:
                for p in roster.get(pos_group, []):
                    f_name = p.get("firstName", {}).get("default", "")
                    l_name = p.get("lastName", {}).get("default", "")
                    if f_name and l_name:
                        boxscore_name = f"{f_name[0]}. {l_name}"
                        full_name = f"{f_name} {l_name}"
                        alias_1 = l_name
                        alias_2 = f"{f_name[0]}{l_name}"
                        new_rows.append([boxscore_name, full_name, alias_1, alias_2, ""])
            
            if new_rows:
                ws_map.append_rows(values=new_rows, value_input_option="USER_ENTERED")
                print("Auto-populated Player_Map with active roster.")
        except Exception as e:
            print(f"Failed to auto-populate Player_Map: {e}")
        
    player_mapping = {}
    for row in ws_map.get_all_values()[1:]:
        if not row or not row[0]: continue
        box_name = row[0].strip()
        for alias in row:
            if alias.strip():
                player_mapping[alias.strip().lower()] = box_name
    
    # 2. Find Yesterday's Game ID
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    # For testing/resilience if no game yesterday, you might want to look back a few days or pass manually
    try:
        schedule = client.schedule.team_weekly_schedule(team_abbr="VGK")
    except Exception as e:
        print(f"Could not fetch NHL schedule or no games this week: {e}. Exiting gracefully.")
        return
    
    target_game_id = None
    for game in schedule:
        if game.get('gameDate') == yesterday:
            target_game_id = game['id']
            break
            
    if not target_game_id:
        print(f"No VGK game played on {yesterday}. Exiting.")
        return

    # 3. Pull Final Boxscore
    try:
        boxscore = client.game_center.boxscore(game_id=target_game_id)
        actuals, team_actuals = parse_boxscore_stats(boxscore)
    except Exception as e:
        print(f"Failed to fetch boxscore for {target_game_id}: {e}")
        return

    # 4. Grade Open Wagers
    wagers = ws_wagers.get_all_records()
    updates = []
    
    current_bankroll = 1000.00
    for w in wagers:
        if w.get('Running_Bankroll'):
            try:
                current_bankroll = float(w['Running_Bankroll'])
            except:
                pass
    
    for i, wager in enumerate(wagers):
        if str(wager.get('Game_ID')) == str(target_game_id) and not wager.get('Grade'):
            player = str(wager.get('Player', ''))
            market = str(wager.get('Market', '')).lower()
            
            try:
                line = float(wager.get('Line', 0))
                stake = float(wager.get('Stake', 0))
                odds = int(wager.get('Odds', -110))
            except Exception:
                continue
            
            player_actuals = get_actuals_for_player(actuals, player, player_mapping)
            actual_stat = player_actuals.get(market, 0)
            
            if actual_stat > line:
                grade = "WIN"
                profit = calculate_payout(odds, stake)
                current_bankroll += profit
            elif actual_stat == line:
                grade = "PUSH"
                profit = 0
            else:
                grade = "LOSS"
                profit = -stake
                current_bankroll -= stake
                
            # H I J K mapping: Actual, Grade, Payout, Running_Bankroll
            # Index i+2 because lists are 0-indexed and headers are row 1
            updates.append({
                'range': f'G{i+2}:J{i+2}', 
                'values': [[actual_stat, grade, round(profit, 2), round(current_bankroll, 2)]]
            })

    if updates:
        ws_wagers.batch_update(updates)
        print(f"Graded {len(updates)} wagers. New Bankroll: ${current_bankroll:.2f}")
    else:
        print("No open wagers to grade for this game.")

    # 5. Run the Model Audit
    try:
        ws_ledger = sh.worksheet("Sim_Ledger")
        raw_data = ws_ledger.get_all_values()
        
        if len(raw_data) < 2:
            print("No sim ledger records found for this game. Skipping audit.")
            return
            
        headers = raw_data[0]
        # Deduplicate and clean headers
        clean_headers = []
        for i, h in enumerate(headers):
            if not h or h == "":
                clean_headers.append(f"BLANK_{i}")
            elif h in clean_headers:
                clean_headers.append(f"{h}_{i}")
            else:
                clean_headers.append(h)
                
        ledger_records = []
        for row in raw_data[1:]:
            record = {}
            for i, val in enumerate(row):
                if i < len(clean_headers):
                    try:
                        # Convert numeric strings to floats if possible, just like get_all_records does
                        record[clean_headers[i]] = float(val) if '.' in val else int(val)
                    except ValueError:
                        record[clean_headers[i]] = val
            ledger_records.append(record)
        
        # Filter ledger for yesterday's game
        game_projections = [r for r in ledger_records if str(r.get('game_id')) == str(target_game_id)]
        
        if not game_projections:
            print("No sim ledger records found for this game. Skipping audit.")
            return
            
        audit_rows = []
        for proj in game_projections:
            name = proj.get('Name')
            record_type = proj.get('Record_Type')
            act = get_actuals_for_player(actuals, str(name), player_mapping)
            
            if not act:
                continue
                
            if record_type == "SKATER":
                # Check SOG
                exp_sog = proj.get('Exp_SOG', 0)
                act_sog = act.get('sog', 0)
                audit_rows.append([target_game_id, name, record_type, "SOG", exp_sog, act_sog, round(act_sog - exp_sog, 2)])
                
                # Check Goals
                exp_goals = proj.get('Exp_Goals', 0)
                act_goals = act.get('goals', 0)
                audit_rows.append([target_game_id, name, record_type, "Goals", exp_goals, act_goals, round(act_goals - exp_goals, 2)])
                
            elif record_type == "GOALIE":
                # Check Shots Against
                exp_sa = proj.get('Exp_Shots_Against', 0)
                act_sa = act.get('shots against', 0)
                audit_rows.append([target_game_id, name, record_type, "Shots Against", exp_sa, act_sa, round(act_sa - exp_sa, 2)])
                
                # Check Goals Against
                exp_ga = proj.get('Exp_GAA', 0)
                act_ga = act.get('goals against', 0)
                audit_rows.append([target_game_id, name, record_type, "Goals Against", exp_ga, act_ga, round(act_ga - exp_ga, 2)])
                
        # 5b. Audit Team Lines (VGK and Opponent)
        try:
            ws_team = sh.worksheet("Team_Ledger")
            team_raw_data = ws_team.get_all_values()
            
            team_updates = []
            
            if len(team_raw_data) >= 2:
                team_headers = team_raw_data[0]
                team_clean_headers = []
                for i, h in enumerate(team_headers):
                    if not h or h == "":
                        team_clean_headers.append(f"BLANK_{i}")
                    elif h in team_clean_headers:
                        team_clean_headers.append(f"{h}_{i}")
                    else:
                        team_clean_headers.append(h)
                
                team_records = []
                for row in team_raw_data[1:]:
                    record = {}
                    for i, val in enumerate(row):
                        if i < len(team_clean_headers):
                            try:
                                record[team_clean_headers[i]] = float(val) if '.' in val else int(val)
                            except ValueError:
                                record[team_clean_headers[i]] = val
                    team_records.append(record)
                    
                # We want the row index for batch_update (1-indexed, +1 for header = enumerate + 2)
                for idx, tr in enumerate(team_records):
                    if str(tr.get('game_id')) == str(target_game_id):
                        # Audit Goals
                        exp_vgk_goals = tr.get('Exp_VGK_Goals', 0)
                        exp_opp_goals = tr.get('Exp_Opp_Goals', 0)
                        act_vgk_goals = team_actuals.get('vgk_goals', 0)
                        act_opp_goals = team_actuals.get('opp_goals', 0)
                        audit_rows.append([target_game_id, "VGK", "TEAM", "Goals", exp_vgk_goals, act_vgk_goals, round(act_vgk_goals - exp_vgk_goals, 2)])
                        audit_rows.append([target_game_id, tr.get('opponent', 'OPP'), "TEAM", "Goals", exp_opp_goals, act_opp_goals, round(act_opp_goals - exp_opp_goals, 2)])
                        
                        # Audit SOG
                        exp_vgk_sog = tr.get('Exp_VGK_SOG', 0)
                        exp_opp_sog = tr.get('Exp_Opp_SOG', 0)
                        act_vgk_sog = team_actuals.get('vgk_sog', 0)
                        act_opp_sog = team_actuals.get('opp_sog', 0)
                        audit_rows.append([target_game_id, "VGK", "TEAM", "SOG", exp_vgk_sog, act_vgk_sog, round(act_vgk_sog - exp_vgk_sog, 2)])
                        audit_rows.append([target_game_id, tr.get('opponent', 'OPP'), "TEAM", "SOG", exp_opp_sog, act_opp_sog, round(act_opp_sog - exp_opp_sog, 2)])
                        
                        # Backfill Team_Ledger Actuals columns (Columns N through R)
                        # Headers are 13 columns long, so we update the 5 actual columns at the end
                        # Column letters: 13=M, so N to R
                        row_num = idx + 2
                        went_to_ot = "TRUE" if team_actuals.get('went_to_ot') else "FALSE"
                        team_updates.append({
                            'range': f'N{row_num}:R{row_num}',
                            'values': [[act_vgk_goals, act_vgk_sog, act_opp_goals, act_opp_sog, went_to_ot]]
                        })
                
                if team_updates:
                    ws_team.batch_update(team_updates)
                    print(f"Backfilled actuals for {len(team_updates)} Team_Ledger rows.")
                
        except Exception as e:
            print(f"Team ledger audit failed: {e}")
                
        if audit_rows:
            ws_audit.append_rows(values=audit_rows, value_input_option="USER_ENTERED")
            print(f"Appended {len(audit_rows)} audit rows to Model_Audit.")
            
    except Exception as e:
        print(f"Model audit failed: {e}")

if __name__ == "__main__":
    run_post_mortem()
