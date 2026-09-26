import numpy as np
import pandas as pd
from nhlpy import NHLClient

def get_upcoming_opponent(team_abbr="VGK", manual_opponent=None):
    if manual_opponent:
        return manual_opponent
    client = NHLClient()
    try:
        schedule = client.schedule.team_weekly_schedule(team_abbr=team_abbr)
        return "EDM" # Placeholder fallback
    except Exception:
        return "EDM"

def parse_duration_to_minutes(duration_str):
    if not duration_str:
        return 0.0
    parts = duration_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) + int(parts[1])/60.0
    return 0.0

def enrich_fatigue_df(fatigue_df, opp_sv_pct, season="20232024"):
    client = NHLClient()
    league_avg_sv_pct = 0.900
    goalie_multiplier = (1.0 - opp_sv_pct) / (1.0 - league_avg_sv_pct) if opp_sv_pct else 1.0

    enriched = []
    
    try:
        teams = client.stats.team_summary(start_season=season, end_season=season)
        vgk_team = [t for t in teams if 'Vegas' in t.get('teamFullName', '') or t.get('teamId') == 54]
        team_goals = vgk_team[0]['goalsFor'] if vgk_team else 250
    except Exception:
        team_goals = 250
        
    for idx, row in fatigue_df.iterrows():
        pid = row['Player_ID']
        try:
            stats = client.stats.player_career_stats(player_id=pid)
            season_totals = stats.get('seasonTotals', [])
            reg_stats = [s for s in season_totals if str(s.get('season')) == season and s.get('gameTypeId') == 2]
            
            if reg_stats:
                st = reg_stats[0]
                shots = st.get('shots', 0)
                goals = st.get('goals', 0)
                assists = st.get('assists', 0)
                avg_toi_str = st.get('avgToi', "00:00")
                avg_toi = parse_duration_to_minutes(avg_toi_str)
                gp = st.get('gamesPlayed', 1)
                shooting_pct = st.get('shootingPctg', 0.0)
                
                sog_per_60 = (shots / gp) / (avg_toi / 60) if avg_toi > 0 and gp > 0 else 0
                adjusted_toi = avg_toi * row['Fatigue_Modifier']
                expected_sog = sog_per_60 * (adjusted_toi / 60)
                
                pos = stats.get('position', 'F')
                league_avg_pos = 0.045 if pos == 'D' else 0.105
                
                p_base = (shots / (shots + 80)) * shooting_pct + (1 - shots / (shots + 80)) * league_avg_pos
                adjusted_shooting_pct = p_base * goalie_multiplier
                
                assist_share = assists / team_goals if team_goals > 0 else 0
            else:
                expected_sog = 0
                adjusted_shooting_pct = 0
                assist_share = 0
        except Exception as e:
            expected_sog = 0
            adjusted_shooting_pct = 0
            assist_share = 0
            
        new_row = row.to_dict()
        new_row['Expected_SOG'] = expected_sog
        new_row['Adjusted_Shooting_Pct'] = adjusted_shooting_pct
        new_row['Assist_Share'] = assist_share
        enriched.append(new_row)
        
    return pd.DataFrame(enriched)

def run_monte_carlo(fatigue_df, opp_stats, vgk_goalie_stats, iterations=10000):
    n_players = len(fatigue_df)
    
    lam_sog = fatigue_df['Expected_SOG'].to_numpy()[:, np.newaxis]
    sim_sog = np.random.poisson(lam=lam_sog, size=(n_players, iterations))
    
    p_goal = fatigue_df['Adjusted_Shooting_Pct'].to_numpy()[:, np.newaxis]
    sim_goals = np.random.binomial(n=sim_sog, p=p_goal)
    
    team_goals_per_sim = sim_goals.sum(axis=0)
    
    assist_shares = fatigue_df['Assist_Share'].to_numpy()[:, np.newaxis]
    sim_assists = np.random.binomial(n=team_goals_per_sim, p=assist_shares)
    
    opp_exp_sog = opp_stats['shots_per_game'] * fatigue_df['Fatigue_Modifier'].mean()
    opp_sim_sog = np.random.poisson(lam=opp_exp_sog, size=iterations)
    
    opp_goal_prob = (1.0 - vgk_goalie_stats['sv_pct'])
    opp_sim_goals = np.random.binomial(n=opp_sim_sog, p=opp_goal_prob)
    
    opp_goals_p1_p2 = np.random.binomial(n=opp_sim_goals, p=0.66)
    vgk_goals_p1_p2 = np.random.binomial(n=team_goals_per_sim, p=0.66)
    
    pulled_condition = (opp_goals_p1_p2 >= 4) & ((opp_goals_p1_p2 - vgk_goals_p1_p2) >= 3)
    pull_probability = np.mean(pulled_condition)
    
    return {
        "sim_sog": sim_sog,
        "sim_goals": sim_goals,
        "sim_assists": sim_assists,
        "pull_prob": pull_probability,
        "opp_sim_sog": opp_sim_sog,
        "opp_sim_goals": opp_sim_goals
    }

if __name__ == "__main__":
    from ingest import build_fatigue_matrix
    print("Building Fatigue Matrix...")
    fatigue_df = build_fatigue_matrix(season="20232024")
    
    opp_abbr = "EDM"
    client = NHLClient()
    
    print(f"Fetching Opponent stats for {opp_abbr}...")
    try:
        teams = client.stats.team_summary(start_season="20232024", end_season="20232024")
        opp_team_stats = [t for t in teams if 'Edmonton' in t.get('teamFullName', '')]
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
