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
    
    # 2. Find all unique Game_IDs with ungraded wagers in Wager_Tracker
    wagers_raw = ws_wagers.get_all_values()
    if len(wagers_raw) < 2:
        print("No wagers found in Wager_Tracker. Exiting.")
        return

    wager_headers = wagers_raw[0]
    wager_records = []
    for row in wagers_raw[1:]:
        record = {}
        for i, val in enumerate(row):
            if i < len(wager_headers):
                record[wager_headers[i]] = val
        wager_records.append(record)

    # Collect unique game IDs that have at least one ungraded wager
    # Grade column index = 7 (col H, 0-indexed)
    grade_col_idx = wager_headers.index('Grade') if 'Grade' in wager_headers else 7
    ungraded_game_ids = list(dict.fromkeys(
        str(r.get('Game_ID', '')).strip()
        for r in wager_records
        if not str(r.get('Grade', '')).strip() and str(r.get('Game_ID', '')).strip()
    ))

    if not ungraded_game_ids:
        print("No ungraded wagers found. Nothing to do.")
        return

    print(f"Found {len(ungraded_game_ids)} game(s) with ungraded wagers: {ungraded_game_ids}")

    # 3. Maintain a running bankroll starting from the last graded entry
    current_bankroll = 1000.00
    for r in wager_records:
        if str(r.get('Running_Bankroll', '')).strip():
            try:
                current_bankroll = float(r['Running_Bankroll'])
            except:
                pass

    # Preload sheets needed for audit
    try:
        ws_ledger = sh.worksheet("Sim_Ledger")
        sim_raw = ws_ledger.get_all_values()
        sim_headers = sim_raw[0] if sim_raw else []
        clean_sim_headers = []
        for i, h in enumerate(sim_headers):
            if not h:
                clean_sim_headers.append(f"BLANK_{i}")
            elif h in clean_sim_headers:
                clean_sim_headers.append(f"{h}_{i}")
            else:
                clean_sim_headers.append(h)
        sim_records = []
        for row in sim_raw[1:]:
            rec = {}
            for i, val in enumerate(row):
                if i < len(clean_sim_headers):
                    try:
                        rec[clean_sim_headers[i]] = float(val) if '.' in str(val) else int(val)
                    except (ValueError, TypeError):
                        rec[clean_sim_headers[i]] = val
            sim_records.append(rec)
    except Exception as e:
        print(f"Could not load Sim_Ledger: {e}")
        sim_records = []

    try:
        ws_team = sh.worksheet("Team_Ledger")
        team_raw = ws_team.get_all_values()
        team_headers = team_raw[0] if team_raw else []
        clean_team_headers = []
        for i, h in enumerate(team_headers):
            if not h:
                clean_team_headers.append(f"BLANK_{i}")
            elif h in clean_team_headers:
                clean_team_headers.append(f"{h}_{i}")
            else:
                clean_team_headers.append(h)
        team_records = []
        for row in team_raw[1:]:
            rec = {}
            for i, val in enumerate(row):
                if i < len(clean_team_headers):
                    try:
                        rec[clean_team_headers[i]] = float(val) if '.' in str(val) else int(val)
                    except (ValueError, TypeError):
                        rec[clean_team_headers[i]] = val
            team_records.append(rec)
    except Exception as e:
        print(f"Could not load Team_Ledger: {e}")
        team_records = []

    # 4. Process each ungraded game
    all_wager_updates = []
    all_audit_rows = []
    all_team_updates = []

    for game_id_str in ungraded_game_ids:
        try:
            game_id = int(game_id_str)
        except ValueError:
            print(f"Skipping invalid Game_ID: {game_id_str}")
            continue

        print(f"\n--- Grading Game {game_id} ---")

        # Fetch boxscore
        try:
            boxscore = client.game_center.boxscore(game_id=game_id)
            actuals, team_actuals = parse_boxscore_stats(boxscore)
        except Exception as e:
            print(f"Failed to fetch boxscore for {game_id}: {e}. Skipping.")
            continue

        # Grade all ungraded wagers for this game
        for i, wager in enumerate(wager_records):
            if str(wager.get('Game_ID', '')).strip() != game_id_str:
                continue
            if str(wager.get('Grade', '')).strip():
                continue  # already graded

            player = str(wager.get('Player', ''))
            market = str(wager.get('Market', '')).lower()

            try:
                line = float(wager.get('Line', 0) or 0)
                stake = float(wager.get('Stake', 0) or 0)
                odds = int(float(wager.get('Odds', -110) or -110))
            except Exception as e:
                print(f"  Skipping row {i+2} — could not parse Line/Stake/Odds: {dict(wager)} | Error: {e}")
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

            all_wager_updates.append({
                'range': f'G{i+2}:J{i+2}',
                'values': [[actual_stat, grade, round(profit, 2), round(current_bankroll, 2)]]
            })

        # Model Audit: Sim_Ledger projections vs actuals
        game_projections = [r for r in sim_records if str(r.get('game_id')) == game_id_str]
        for proj in game_projections:
            name = proj.get('Name')
            record_type = proj.get('Record_Type')
            act = get_actuals_for_player(actuals, str(name), player_mapping)
            if not act:
                continue
            if record_type == "SKATER":
                exp_sog = proj.get('Exp_SOG', 0)
                act_sog = act.get('sog', 0)
                all_audit_rows.append([game_id, name, record_type, "SOG", exp_sog, act_sog, round(act_sog - exp_sog, 2)])
                exp_goals = proj.get('Exp_Goals', 0)
                act_goals = act.get('goals', 0)
                all_audit_rows.append([game_id, name, record_type, "Goals", exp_goals, act_goals, round(act_goals - exp_goals, 2)])
            elif record_type == "GOALIE":
                exp_sa = proj.get('Exp_Shots_Against', 0)
                act_sa = act.get('shots against', 0)
                all_audit_rows.append([game_id, name, record_type, "Shots Against", exp_sa, act_sa, round(act_sa - exp_sa, 2)])
                exp_ga = proj.get('Exp_GAA', 0)
                act_ga = act.get('goals against', 0)
                all_audit_rows.append([game_id, name, record_type, "Goals Against", exp_ga, act_ga, round(act_ga - exp_ga, 2)])

        # Team Audit: Backfill actuals into Team_Ledger
        for idx, tr in enumerate(team_records):
            if str(tr.get('game_id')) != game_id_str:
                continue
            act_vgk_goals = team_actuals.get('vgk_goals', 0)
            act_vgk_sog = team_actuals.get('vgk_sog', 0)
            act_opp_goals = team_actuals.get('opp_goals', 0)
            act_opp_sog = team_actuals.get('opp_sog', 0)
            exp_vgk_goals = tr.get('Exp_VGK_Goals', 0)
            exp_opp_goals = tr.get('Exp_Opp_Goals', 0)
            exp_vgk_sog = tr.get('Exp_VGK_SOG', 0)
            exp_opp_sog = tr.get('Exp_Opp_SOG', 0)
            all_audit_rows.append([game_id, "VGK", "TEAM", "Goals", exp_vgk_goals, act_vgk_goals, round(act_vgk_goals - exp_vgk_goals, 2)])
            all_audit_rows.append([game_id, tr.get('opponent', 'OPP'), "TEAM", "Goals", exp_opp_goals, act_opp_goals, round(act_opp_goals - exp_opp_goals, 2)])
            all_audit_rows.append([game_id, "VGK", "TEAM", "SOG", exp_vgk_sog, act_vgk_sog, round(act_vgk_sog - exp_vgk_sog, 2)])
            all_audit_rows.append([game_id, tr.get('opponent', 'OPP'), "TEAM", "SOG", exp_opp_sog, act_opp_sog, round(act_opp_sog - exp_opp_sog, 2)])
            went_to_ot = "TRUE" if team_actuals.get('went_to_ot') else "FALSE"
            all_team_updates.append({
                'range': f'N{idx+2}:R{idx+2}',
                'values': [[act_vgk_goals, act_vgk_sog, act_opp_goals, act_opp_sog, went_to_ot]]
            })

    # 5. Write all results in batch
    if all_wager_updates:
        ws_wagers.batch_update(all_wager_updates)
        print(f"\nGraded {len(all_wager_updates)} wagers across {len(ungraded_game_ids)} game(s). Final Bankroll: ${current_bankroll:.2f}")
    else:
        print("No wager updates to write.")

    if all_team_updates:
        ws_team.batch_update(all_team_updates)
        print(f"Backfilled actuals for {len(all_team_updates)} Team_Ledger row(s).")

    if all_audit_rows:
        ws_audit.append_rows(values=all_audit_rows, value_input_option="USER_ENTERED")
        print(f"Appended {len(all_audit_rows)} rows to Model_Audit.")

if __name__ == "__main__":
    run_post_mortem()

