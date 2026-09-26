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
        team_data = boxscore.get(team_key, {})
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
    return actuals

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
    
    # 2. Find Yesterday's Game ID
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    # For testing/resilience if no game yesterday, you might want to look back a few days or pass manually
    schedule = client.schedule.team_weekly_schedule(team_abbr="VGK")
    
    target_game_id = None
    for day in schedule.get('gamesByDate', []):
        if day.get('date') == yesterday:
            target_game_id = day['games'][0]['id']
            break
            
    if not target_game_id:
        print(f"No VGK game played on {yesterday}. Exiting.")
        return

    # 3. Pull Final Boxscore
    try:
        boxscore = client.game_center.boxscore(game_id=target_game_id)
        actuals = parse_boxscore_stats(boxscore)
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
            
            actual_stat = actuals.get(player, {}).get(market, 0)
            
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
        ledger_records = ws_ledger.get_all_records()
        
        # Filter ledger for yesterday's game
        game_projections = [r for r in ledger_records if str(r.get('game_id')) == str(target_game_id)]
        
        if not game_projections:
            print("No sim ledger records found for this game. Skipping audit.")
            return
            
        audit_rows = []
        for proj in game_projections:
            name = proj.get('Name')
            record_type = proj.get('Record_Type')
            act = actuals.get(name)
            
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
                
        if audit_rows:
            ws_audit.append_rows(values=audit_rows, value_input_option="USER_ENTERED")
            print(f"Appended {len(audit_rows)} audit rows to Model_Audit.")
            
    except Exception as e:
        print(f"Model audit failed: {e}")

if __name__ == "__main__":
    run_post_mortem()
