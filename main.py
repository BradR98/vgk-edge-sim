import os
import datetime
from nhlpy import NHLClient
import pandas as pd
import numpy as np

from engine.ingest import build_fatigue_matrix
from engine.monte_carlo import enrich_fatigue_df, run_monte_carlo, get_upcoming_opponent
from engine.sheets import authenticate_gspread, get_workbook, update_game_day_tab, append_sim_ledger

def get_game_metadata(client, team_abbr="VGK"):
    try:
        schedule = client.schedule.team_weekly_schedule(team_abbr=team_abbr)
        games = schedule.get('games', [])
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Grab the earliest unplayed game
        upcoming = [g for g in games if datetime.datetime.fromisoformat(g['startTimeUTC'].replace('Z', '+00:00')) > now]
        if not upcoming:
            upcoming = [games[-1]] if games else []
            
        if upcoming:
            game = upcoming[0]
            game_id = game.get('id', 'N/A')
            game_date = game.get('gameDate', 'N/A')
            away_team = game.get('awayTeam', {}).get('abbrev', 'N/A')
            home_team = game.get('homeTeam', {}).get('abbrev', 'N/A')
            
            opponent = away_team if home_team == team_abbr else home_team
            venue = "Home" if home_team == team_abbr else "Away"
            
            return {
                "game_id": str(game_id),
                "game_date": str(game_date),
                "opponent": opponent,
                "venue": venue,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
    except Exception as e:
        print(f"Failed to fetch metadata: {e}")
        
    return {
        "game_id": "UNKNOWN",
        "game_date": "UNKNOWN",
        "opponent": "EDM",
        "venue": "UNKNOWN",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

def main():
    print("Initializing NHL Client and fetching metadata...")
    client = NHLClient()
    metadata = get_game_metadata(client, team_abbr="VGK")
    opp_abbr = metadata['opponent']
    print(f"Opponent matched: {opp_abbr}")
    
    print("Building Fatigue Matrix...")
    fatigue_df = build_fatigue_matrix(season="20232024")
    
    print(f"Fetching Opponent stats for {opp_abbr}...")
    try:
        teams = client.stats.team_summary(start_season="20232024", end_season="20232024")
        opp_team_stats = [t for t in teams if opp_abbr in t.get('teamFullName', '') or opp_abbr in t.get('teamAbbrevs', '')]
        if not opp_team_stats:
             opp_team_stats = [t for t in teams if opp_abbr in t.get('teamFullName', '')]
        shots_against = opp_team_stats[0].get('shotsAgainstPerGame', 30.0) if opp_team_stats else 30.0
    except Exception:
        shots_against = 30.0
        
    opp_stats = {'shots_per_game': shots_against}
    
    try:
        goalies = client.stats.goalie_stats_summary(start_season="20232024", end_season="20232024", limit=200)
        opp_goalies = [g for g in goalies if g.get('teamAbbrevs') and opp_abbr in g['teamAbbrevs']]
        opp_sv_pct = opp_goalies[0].get('savePct', 0.900) if opp_goalies else 0.900
        
        vgk_goalies = [g for g in goalies if g.get('teamAbbrevs') and 'VGK' in g['teamAbbrevs']]
        vgk_sv_pct = vgk_goalies[0].get('savePct', 0.900) if vgk_goalies else 0.900
    except Exception:
        opp_sv_pct = 0.900
        vgk_sv_pct = 0.900
        
    vgk_goalie_stats = {'sv_pct': vgk_sv_pct}
    
    print("Enriching DataFrame with player season stats and xG regression...")
    fatigue_df = enrich_fatigue_df(fatigue_df, opp_sv_pct, season="20232024")
    
    print("Running 10,000 Monte Carlo simulations...")
    results = run_monte_carlo(fatigue_df, opp_stats, vgk_goalie_stats, iterations=10000)
    
    print(f"\nGoalie Pull Probability: {results['pull_prob']*100:.2f}%")
    
    out = []
    for idx, row in fatigue_df.iterrows():
        p_sog = results['sim_sog'][idx]
        p_goals = results['sim_goals'][idx]
        
        out.append({
            "Name": row['Name'],
            "SOG_Mean": round(np.mean(p_sog), 2),
            "SOG_P50": np.percentile(p_sog, 50),
            "SOG_P80": np.percentile(p_sog, 80),
            "Over_2.5_SOG_%": round(np.mean(p_sog >= 3) * 100, 1),
            "Anytime_Goal_%": round(np.mean(p_goals >= 1) * 100, 1),
            "Multi_Point_%": round(np.mean((p_goals + results['sim_assists'][idx]) >= 2) * 100, 1)
        })
    
    summary_df = pd.DataFrame(out)
    print("\nSimulation Results (Top 10):")
    print(summary_df.head(10).to_string(index=False))
    
    # Push to Google Sheets if credentials are present
    if os.environ.get("GCP_CREDENTIALS") and os.environ.get("SPREADSHEET_ID"):
        print("\nPushing results to Google Sheets...")
        try:
            gc = authenticate_gspread()
            sh = get_workbook(gc)
            update_game_day_tab(sh, summary_df)
            append_sim_ledger(sh, summary_df, metadata)
        except Exception as e:
            print(f"Failed to push to Google Sheets: {e}")
    else:
        print("\nGCP_CREDENTIALS or SPREADSHEET_ID not found in environment. Skipping Google Sheets push.")

if __name__ == "__main__":
    main()
