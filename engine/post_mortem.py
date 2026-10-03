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

def parse_num(val, default=0.0):
    """Safely converts string/number values with $, commas, +, or spaces into a float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace('$', '').replace(',', '').replace('+', '')
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default

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
    game_date = boxscore.get('gameDate', '')
    venue = 'Home' if is_vgk_home else 'Away'

    team_actuals = {
        'vgk_goals': home_score if is_vgk_home else away_score,
        'vgk_sog': home_sog if is_vgk_home else away_sog,
        'opp_goals': away_score if is_vgk_home else home_score,
        'opp_sog': away_sog if is_vgk_home else home_sog,
        'went_to_ot': boxscore.get('gameOutcome', {}).get('lastPeriodType') in ['OT', 'SO'],
        'game_date': game_date,
        'venue': venue
    }

    return actuals, team_actuals

def get_actuals_for_player(actuals_dict, player_str, player_mapping):
    """Matches user input or simulation full names against the boxscore using the Player_Map tab."""
    p_clean = str(player_str).strip()
    p_lower = p_clean.lower()
    
    if not p_clean:
        return {}

    # 1. Direct exact match
    if p_clean in actuals_dict:
        return actuals_dict[p_clean]

    # 2. Case-insensitive exact match
    for k, v in actuals_dict.items():
        if k.lower() == p_lower:
            return v
        
    # 3. Map lookup via Terminology_Ranges
    mapped_name = player_mapping.get(p_lower)
    if mapped_name:
        if mapped_name in actuals_dict:
            return actuals_dict[mapped_name]
        for k, v in actuals_dict.items():
            if k.lower() == mapped_name.lower():
                return v

    # 4. Partial substring matching fallback
    for k, v in actuals_dict.items():
        k_lower = k.lower()
        if p_lower in k_lower or k_lower in p_lower:
            return v

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
        # Create Wager_Tracker with new schema
        ws_wagers = sh.add_worksheet(title="Wager_Tracker", rows="1000", cols="20")
        # Row 1: Kelly Criterion controls (checkbox/formulas wired via Apps Script 'Setup Wager Tracker')
        ws_wagers.update(range_name="A1:E1", values=[["Kelly Criterion Betting:", "FALSE", "Kelly Criterion turned off", "", ""]])
        # Row 2: Column headers
        ws_wagers.update(range_name="A2:M2", values=[["Game_ID", "Date", "Venue", "Player/Team", "Market", "Line", "Pick", "Odds", "Stake", "Result", "Grade", "Payout", "Running P&L"]])
        
    try:
        ws_audit = sh.worksheet("Model_Audit")
    except Exception:
        ws_audit = sh.add_worksheet(title="Model_Audit", rows="1000", cols="20")
        ws_audit.append_row(["Game_ID", "Player", "Record_Type", "Metric", "Projection", "Actual", "Diff"])
        
    # Load Terminology_Ranges tab (Player Map + Market Map)
    MARKET_DEFAULTS = [
        # Internal_Key          | Display_Name                    | Sportsbook_Alias_1          | Sportsbook_Alias_2      | Sportsbook_Alias_3
        ["sog",                 "SKATER Total Shots on Goal",    "Total Shots on Goal",        "Shots on Goal",          "Player SOG"],
        ["goals",               "SKATER Total Goals",            "Total Goals",                "Player Goals",           "Anytime Goal"],
        ["assists",             "SKATER Total Assists",          "Total Assists",              "Player Assists",         ""],
        ["points",              "SKATER Total Points",           "Total Points",               "Player Points",          ""],
        ["pim",                 "SKATER PIM",                   "Penalty Minutes",            "Player PIM",             ""],
        ["moneyline",           "Money Line – OT Included",     "Moneyline",                  "ML",                     ""],
        ["handicap",            "Handicap – OT Included",       "Puck Line",                  "Spread",                 ""],
        ["team_total",          "Total – OT Included",          "Game Total",                 "Over/Under",             "O/U"],
        ["team_total_ot",       "Team Total – OT Included",     "Team Total",                 "",                       ""],
        ["moneyline_1p",        "Money Line – 1st Period",      "1st Period ML",              "",                       ""],
        ["handicap_1p",         "Handicap – 1st Period",        "1st Period Puck Line",       "",                       ""],
        ["total_1p",            "Total – 1st Period",           "1st Period Total",           "1P O/U",                 ""],
        ["team_total_1p",       "Team Total – 1st Period",      "1st Period Team Total",      "",                       ""],
        ["moneyline_2p",        "Money Line – 2nd Period",      "2nd Period ML",              "",                       ""],
        ["handicap_2p",         "Handicap – 2nd Period",        "2nd Period Puck Line",       "",                       ""],
        ["total_2p",            "Total – 2nd Period",           "2nd Period Total",           "2P O/U",                 ""],
        ["team_total_2p",       "Team Total – 2nd Period",      "2nd Period Team Total",      "",                       ""],
        ["moneyline_3p",        "Money Line – 3rd Period",      "3rd Period ML",              "",                       ""],
        ["handicap_3p",         "Handicap – 3rd Period",        "3rd Period Puck Line",       "",                       ""],
        ["total_3p",            "Total – 3rd Period",           "3rd Period Total",           "3P O/U",                 ""],
        ["team_total_3p",       "Team Total – 3rd Period",      "3rd Period Team Total",      "",                       ""],
        ["moneyline_reg",       "Money Line – Regulation Time", "Regulation ML",              "",                       ""],
        ["handicap_reg",        "Handicap – Regulation Time",   "Regulation Puck Line",       "",                       ""],
        ["total_reg",           "Total – Regulation Time",      "Regulation Total",           "",                       ""],
        ["team_total_reg",      "Team Total – Regulation Time", "Regulation Team Total",      "",                       ""],
        ["correct_score",       "Correct Score",                "",                           "",                       ""],
        ["exact_total_goals",   "Exact Total Goals",            "",                           "",                       ""],
        ["moneyline_and_total", "Moneyline and Total Goals",    "",                           "",                       ""],
        ["team_goals",          "TEAM Goals",                   "",                           "",                       ""],
        ["team_win_to_nil",     "TEAM To Win to Nil",           "Win to Nil",                 "",                       ""],
        ["team_to_score",       "TEAM To Score",                "To Score",                   "",                       ""],
        ["total_goals_range",   "Total Goals Range",            "",                           "",                       ""],
    ]

    try:
        ws_terms = sh.worksheet("Terminology_Ranges")
        all_vals = ws_terms.get_all_values()
        # Re-populate if: empty, only headers, or market alias columns are still blank (old format)
        market_rows = [r for r in all_vals[1:] if len(r) > 6 and r[6].strip()]
        aliases_populated = any(len(r) > 8 and r[8].strip() for r in market_rows)
        if len(all_vals) <= 1 or not aliases_populated:
            raise Exception("Needs population")
    except Exception:
        try:
            ws_terms = sh.worksheet("Terminology_Ranges")
            ws_terms.clear()
            ws_terms.resize(rows=500, cols=16)  # ensure M-N columns exist for team table
        except Exception:
            # Also try to delete legacy Player_Map tab if it exists
            try:
                old = sh.worksheet("Player_Map")
                sh.del_worksheet(old)
            except Exception:
                pass
            ws_terms = sh.add_worksheet(title="Terminology_Ranges", rows="500", cols="16")

        # Write Player Map section header (A1:E1)
        ws_terms.update(range_name="A1:E1", values=[["Boxscore_Name", "Full_Name", "Alias_1", "Alias_2", "Alias_3"]])

        # Write Market Map section header (G1:K1)
        ws_terms.update(range_name="G1:K1", values=[["Internal_Key", "Display_Name", "Sportsbook_Alias_1", "Sportsbook_Alias_2", "Sportsbook_Alias_3"]])

        # Auto-populate Player Map from roster
        try:
            season = "20262027"
            roster = client.teams.team_roster("VGK", season)
            player_rows = []
            for pos_group in ['forwards', 'defensemen', 'goalies']:
                for p in roster.get(pos_group, []):
                    f_name = p.get("firstName", {}).get("default", "")
                    l_name = p.get("lastName", {}).get("default", "")
                    if f_name and l_name:
                        player_rows.append([
                            f"{f_name[0]}. {l_name}",
                            f"{f_name} {l_name}",
                            l_name,
                            f"{f_name[0]}{l_name}",
                            ""
                        ])
            if player_rows:
                ws_terms.update(range_name=f"A2:E{1 + len(player_rows)}", values=player_rows)
                # Add VGK at the bottom of the Player/Team dropdown column
                vgk_row = 2 + len(player_rows)
                ws_terms.update(range_name=f"A{vgk_row}:B{vgk_row}", values=[["VGK", "VGK"]])
                print(f"Auto-populated {len(player_rows)} players + VGK into Terminology_Ranges.")
        except Exception as e:
            print(f"Failed to auto-populate player rows: {e}")

        # Write Market Map rows starting at G2
        if MARKET_DEFAULTS:
            ws_terms.update(range_name=f"G2:K{1 + len(MARKET_DEFAULTS)}", values=MARKET_DEFAULTS)
            print(f"Populated {len(MARKET_DEFAULTS)} market entries into Terminology_Ranges.")

        # Write NHL Team conversion table (M-N)
        NHL_TEAMS = [
            ["Team_Full_Name",         "Abbrev"],
            ["Anaheim Ducks",          "ANA"],
            ["Boston Bruins",          "BOS"],
            ["Buffalo Sabres",         "BUF"],
            ["Calgary Flames",         "CGY"],
            ["Carolina Hurricanes",    "CAR"],
            ["Chicago Blackhawks",     "CHI"],
            ["Colorado Avalanche",     "COL"],
            ["Columbus Blue Jackets",  "CBJ"],
            ["Dallas Stars",           "DAL"],
            ["Detroit Red Wings",      "DET"],
            ["Edmonton Oilers",        "EDM"],
            ["Florida Panthers",       "FLA"],
            ["Los Angeles Kings",      "LAK"],
            ["Minnesota Wild",         "MIN"],
            ["Montr\u00e9al Canadiens","MTL"],
            ["Nashville Predators",    "NSH"],
            ["New Jersey Devils",      "NJD"],
            ["New York Islanders",     "NYI"],
            ["New York Rangers",       "NYR"],
            ["Ottawa Senators",        "OTT"],
            ["Philadelphia Flyers",    "PHI"],
            ["Pittsburgh Penguins",    "PIT"],
            ["San Jose Sharks",        "SJS"],
            ["Seattle Kraken",         "SEA"],
            ["St. Louis Blues",        "STL"],
            ["Tampa Bay Lightning",    "TBL"],
            ["Toronto Maple Leafs",    "TOR"],
            ["Utah Hockey Club",       "UTA"],
            ["Vancouver Canucks",      "VAN"],
            ["Vegas Golden Knights",   "VGK"],
            ["Washington Capitals",    "WSH"],
            ["Winnipeg Jets",          "WPG"],
        ]
        ws_terms.update(range_name=f"M1:N{len(NHL_TEAMS)}", values=NHL_TEAMS)
        print(f"Populated NHL team conversion table into Terminology_Ranges.")

    # Build player_mapping dict from columns A-E
    all_vals = ws_terms.get_all_values()
    player_mapping = {}
    for row in all_vals[1:]:
        if not row or not row[0].strip():
            continue
        box_name = row[0].strip()
        for alias in row[:5]:
            if alias.strip():
                player_mapping[alias.strip().lower()] = box_name

    # Build market_mapping dict from columns G-K
    # Any alias or display name → internal_key
    market_mapping = {}
    for row in all_vals[1:]:
        if len(row) < 8 or not row[6].strip():
            continue
        internal_key = row[6].strip().lower()
        for term in row[6:11]:
            if term.strip():
                market_mapping[term.strip().lower()] = internal_key

    # 2. Find all unique Game_IDs with ungraded wagers in Wager_Tracker
    # Row 1 = Kelly Criterion controls, Row 2 = headers, Row 3+ = data
    wagers_raw = ws_wagers.get_all_values()
    if len(wagers_raw) < 2:
        print("No wagers found in Wager_Tracker. Exiting.")
        return

    wager_headers = wagers_raw[1] if len(wagers_raw) >= 2 else []  # Row 2
    wager_records = []
    for idx, row in enumerate(wagers_raw[2:]):  # Data starts at Row 3 (idx 0 -> row_num 3)
        row_num = idx + 3
        record = {'_row_num': row_num}
        for i, val in enumerate(row):
            if i < len(wager_headers):
                record[wager_headers[i]] = val
        if any(v.strip() for v in row):
            wager_records.append(record)

    # Collect unique game IDs that have at least one ungraded wager
    ungraded_game_ids = list(dict.fromkeys(
        str(r.get('Game_ID', '')).strip()
        for r in wager_records
        if not str(r.get('Grade', '')).strip() and str(r.get('Game_ID', '')).strip()
    ))

    if not ungraded_game_ids:
        print("No ungraded wagers found. Nothing to do.")
        return

    print(f"Found {len(ungraded_game_ids)} game(s) with ungraded wagers: {ungraded_game_ids}")

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
        for wager in wager_records:
            if str(wager.get('Game_ID', '')).strip() != game_id_str:
                continue
            if str(wager.get('Grade', '')).strip():
                continue  # already graded

            row_num = wager.get('_row_num')
            player = str(wager.get('Player/Team', ''))
            market_raw = str(wager.get('Market', '')).strip()

            # Resolve market through Terminology_Ranges market map
            internal_market = market_mapping.get(market_raw.lower(), market_raw.lower())

            # Gradeable markets (player stats + team markets)
            gradeable_markets = {
                'sog', 'goals', 'assists', 'points', 'pim',
                'shots against', 'goals against', 'save percentage',
                'team_goals', 'team_total', 'moneyline'
            }
            if internal_market not in gradeable_markets:
                print(f"  Row {row_num}: Market '{market_raw}' → '{internal_market}' is not yet auto-gradeable. Skipping.")
                continue

            try:
                line = parse_num(wager.get('Line'), 0.0)
                stake = parse_num(wager.get('Stake'), 0.0)
                odds = int(parse_num(wager.get('Odds'), -110))
            except Exception as e:
                print(f"  Skipping row {row_num} — could not parse Line/Stake/Odds: {dict(wager)} | Error: {e}")
                continue

            # Resolve actual stat
            if internal_market in ['team_goals', 'team_total', 'moneyline']:
                pt_lower = player.lower()
                is_vgk = pt_lower in ['vgk', 'vegas golden knights', 'vegas']
                if internal_market == 'team_goals' or (is_vgk and internal_market == 'goals'):
                    actual_stat = team_actuals.get('vgk_goals', 0)
                elif internal_market == 'team_total':
                    actual_stat = team_actuals.get('vgk_goals', 0) + team_actuals.get('opp_goals', 0)
                elif internal_market == 'moneyline' and is_vgk:
                    actual_stat = 1 if team_actuals.get('vgk_goals', 0) > team_actuals.get('opp_goals', 0) else 0
                else:
                    actual_stat = 0
            else:
                player_actuals = get_actuals_for_player(actuals, player, player_mapping)
                actual_stat = player_actuals.get(internal_market, 0)

            # Evaluate Pick (Over vs Under)
            pick = str(wager.get('Pick', '')).strip().lower()
            is_under = pick.startswith('u') or 'under' in pick or pick == '<'

            if is_under:
                if actual_stat < line:
                    grade = "WIN"
                    profit = calculate_payout(odds, stake)
                elif actual_stat == line:
                    grade = "PUSH"
                    profit = 0.0
                else:
                    grade = "LOSS"
                    profit = -stake
            else:  # Over (default)
                if actual_stat > line:
                    grade = "WIN"
                    profit = calculate_payout(odds, stake)
                elif actual_stat == line:
                    grade = "PUSH"
                    profit = 0.0
                else:
                    grade = "LOSS"
                    profit = -stake

            all_wager_updates.append({
                'range': f'B{row_num}:C{row_num}',
                'values': [[team_actuals.get('game_date', ''), team_actuals.get('venue', '')]]
            })
            all_wager_updates.append({
                'range': f'J{row_num}:M{row_num}',
                'values': [[actual_stat, grade, round(profit, 2), f'=SUM($L$3:L{row_num})']]
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
        ws_wagers.batch_update(all_wager_updates, value_input_option='USER_ENTERED')
        print(f"\nGraded {len(all_wager_updates)} wagers across {len(ungraded_game_ids)} game(s).")
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

