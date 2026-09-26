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
