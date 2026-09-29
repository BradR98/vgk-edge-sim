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
    parts = str(duration_str).split(':')
    if len(parts) == 2:
        return int(parts[0]) + int(parts[1])/60.0
    return 0.0

def enrich_fatigue_df(fatigue_df, season="20262027"):
    client = NHLClient()
    enriched = []
    
    try:
        teams = client.stats.team_summary(start_season=season, end_season=season) or client.stats.team_summary(start_season="20252026", end_season="20252026")
        vgk_team = [t for t in teams if 'Vegas' in t.get('teamFullName', '') or t.get('teamId') == 54]
        team_goals = vgk_team[0]['goalsFor'] if vgk_team else 250
    except Exception:
        team_goals = 250
        
    for idx, row in fatigue_df.iterrows():
        pid = row['Player_ID']
        try:
            import os
            rolling_window = int(os.environ.get('ROLLING_GAMES_WINDOW', 15))
            
            try:
                curr_log = client.stats.player_game_log(player_id=str(pid), season_id=season, game_type=2)
            except Exception:
                curr_log = []
                
            curr_games_played = len(curr_log)
            shots, goals, assists, pim, total_toi = 0.0, 0.0, 0.0, 0.0, 0.0
            
            if curr_games_played >= rolling_window:
                target_games = curr_log[:rolling_window]
                shots = sum(g.get('shots', 0) for g in target_games)
                goals = sum(g.get('goals', 0) for g in target_games)
                assists = sum(g.get('assists', 0) for g in target_games)
                pim = sum(g.get('pim', 0) for g in target_games)
                total_toi = sum(parse_duration_to_minutes(g.get('toi', "00:00")) for g in target_games)
                gp = rolling_window
                avg_toi = total_toi / rolling_window if rolling_window > 0 else 0
            else:
                missing_games = rolling_window - curr_games_played
                shots = sum(g.get('shots', 0) for g in curr_log)
                goals = sum(g.get('goals', 0) for g in curr_log)
                assists = sum(g.get('assists', 0) for g in curr_log)
                pim = sum(g.get('pim', 0) for g in curr_log)
                total_toi = sum(parse_duration_to_minutes(g.get('toi', "00:00")) for g in curr_log)
                
                pad_shots, pad_goals, pad_assists, pad_pim, pad_toi_per_game = 0.0, 0.0, 0.0, 0.0, 0.0
                try:
                    stats = client.stats.player_career_stats(player_id=pid)
                    season_totals = stats.get('seasonTotals', [])
                    prev_season = "20252026" if season == "20262027" else str(int(season) - 10001)
                    prev_stats = [s for s in season_totals if str(s.get('season')) == prev_season and s.get('gameTypeId') == 2]
                    
                    if not prev_stats:
                        prev_stats = [s for s in season_totals if str(s.get('season')) == season and s.get('gameTypeId') == 2]
                    
                    if prev_stats:
                        st = prev_stats[0]
                        prev_gp = st.get('gamesPlayed', 1)
                        if prev_gp > 0:
                            pad_shots = (st.get('shots', 0) / prev_gp) * missing_games
                            pad_goals = (st.get('goals', 0) / prev_gp) * missing_games
                            pad_assists = (st.get('assists', 0) / prev_gp) * missing_games
                            pad_pim = (st.get('pim', 0) / prev_gp) * missing_games
                            pad_toi_per_game = parse_duration_to_minutes(st.get('avgToi', "00:00"))
                except Exception:
                    pass
                
                shots += pad_shots
                goals += pad_goals
                assists += pad_assists
                pim += pad_pim
                total_padded_toi = total_toi + (pad_toi_per_game * missing_games)
                gp = rolling_window
                avg_toi = total_padded_toi / rolling_window if rolling_window > 0 else 0
                
            shooting_pct = goals / shots if shots > 0 else 0.0
            sog_per_60 = (shots / gp) / (avg_toi / 60) if avg_toi > 0 and gp > 0 else 0
            pim_per_60 = (pim / gp) / (avg_toi / 60) if avg_toi > 0 and gp > 0 else 0
            
            pos = row.get('Position', 'F')
            league_avg_pos = 0.045 if pos == 'D' else 0.105
            
            p_base = (shots / (shots + 80)) * shooting_pct + (1 - shots / (shots + 80)) * league_avg_pos
            xg_per_shot = p_base
            
            team_goals_per_game = team_goals / 82.0 if team_goals > 0 else 3.0
            assist_share = (assists / gp) / team_goals_per_game if team_goals_per_game > 0 else 0

        except Exception as e:
            sog_per_60 = 0
            pim_per_60 = 0
            xg_per_shot = 0
            assist_share = 0
            avg_toi = 0.0
            pos = row.get('Position', 'F')
            
        new_row = row.to_dict()
        new_row['Avg_TOI'] = avg_toi
        new_row['Position'] = pos
        new_row['SOG_per_60'] = sog_per_60
        new_row['PIM_per_60'] = pim_per_60
        new_row['xG_per_Shot'] = xg_per_shot
        new_row['Assist_Share'] = assist_share
        enriched.append(new_row)
        
    return pd.DataFrame(enriched)

def run_full_handicap_simulation(
    skaters_df, 
    opp_team_stats, 
    vgk_goalies_list, 
    opp_goalie_stats, 
    ref_pim_scalar=1.0, 
    iterations=10000
):
    """
    Simulates 10,000 game iterations producing the complete player and goalie handicap.
    """
    n_skaters = len(skaters_df)
    
    # ---------------------------------------------------------
    # 1. SKATER PLAYING TIME (TOI)
    # ---------------------------------------------------------
    base_toi = (skaters_df['Avg_TOI'] * skaters_df['Fatigue_Modifier']).to_numpy()[:, np.newaxis]
    # Standard deviation of ~1.4 minutes per player's night
    sim_toi = np.random.normal(loc=base_toi, scale=1.4, size=(n_skaters, iterations))
    sim_toi = np.clip(sim_toi, 5.0, 32.0)  # Bound to realistic NHL ice times

    # ---------------------------------------------------------
    # 2. SKATER PIM
    # ---------------------------------------------------------
    pim_per_min = (skaters_df['PIM_per_60'] / 60.0).to_numpy()[:, np.newaxis]
    lam_penalties = (pim_per_min / 2.0) * sim_toi * ref_pim_scalar
    sim_minors = np.random.poisson(lam=lam_penalties)
    sim_pim = sim_minors * 2

    # ---------------------------------------------------------
    # 3. SKATER SHOTS ON NET (SOG)
    # ---------------------------------------------------------
    sog_per_min = (skaters_df['SOG_per_60'] / 60.0).to_numpy()[:, np.newaxis]
    opp_shot_suppression = opp_team_stats.get('shot_suppression_factor', 1.0)
    lam_sog = sog_per_min * sim_toi * opp_shot_suppression
    sim_sog = np.random.poisson(lam=lam_sog)

    # ---------------------------------------------------------
    # 4. SKATER xG & GOALS
    # ---------------------------------------------------------
    # Mean shot quality (xG per shot) regressed to positional baselines
    base_xg_per_shot = skaters_df['xG_per_Shot'].to_numpy()[:, np.newaxis]
    opp_goalie_multiplier = (1.0 - opp_goalie_stats['sv_pct']) / (1.0 - 0.905)
    
    # Total simulated xG for each player in each run
    sim_xg = sim_sog * base_xg_per_shot
    
    # Bernoulli goal conversions per shot
    adj_prob_per_shot = np.clip(base_xg_per_shot * opp_goalie_multiplier, 0.01, 0.35)
    sim_goals = np.random.binomial(n=sim_sog, p=adj_prob_per_shot)

    # ---------------------------------------------------------
    # 5. SKATER ASSISTS
    # ---------------------------------------------------------
    total_vgk_goals_per_run = sim_goals.sum(axis=0)  # Shape: (iterations,)
    assist_rates = skaters_df['Assist_Share'].to_numpy()[:, np.newaxis]
    sim_assists = np.random.binomial(n=total_vgk_goals_per_run, p=assist_rates)

    # Aggregate Skater Summary
    skater_summary = []
    for i, row in skaters_df.iterrows():
        sog_arr = sim_sog[i]
        goal_arr = sim_goals[i]
        ast_arr = sim_assists[i]
        toi_arr = sim_toi[i]
        pim_arr = sim_pim[i]
        xg_arr = sim_xg[i]
        
        skater_summary.append({
            "Name": row['Name'],
            "Pos": row.get('Position', 'F'),
            "Exp_TOI": round(float(np.mean(toi_arr)), 2),
            "Exp_PIM": round(float(np.mean(pim_arr)), 2),
            "PIM_Over_1.5_%": round(float(np.mean(pim_arr >= 2)) * 100, 1),
            "Exp_SOG": round(float(np.mean(sog_arr)), 2),
            "SOG_P50": round(float(np.percentile(sog_arr, 50)), 1),
            "SOG_P80": round(float(np.percentile(sog_arr, 80)), 1),
            "Exp_xG": round(float(np.mean(xg_arr)), 3),
            "Exp_Goals": round(float(np.mean(goal_arr)), 2),
            "Anytime_Goal_%": round(float(np.mean(goal_arr >= 1)) * 100, 1),
            "Exp_Assists": round(float(np.mean(ast_arr)), 2),
            "Over_0.5_Pt_%": round(float(np.mean((goal_arr + ast_arr) >= 1)) * 100, 1)
        })
    df_skaters_summary = pd.DataFrame(skater_summary)

    # ---------------------------------------------------------
    # 6. GOALIE SIMULATION (Shots Against, xGA, GA, GAA, Sv%, Pull%)
    # ---------------------------------------------------------
    team_fatigue = skaters_df['Fatigue_Modifier'].mean()
    exp_shots_against = opp_team_stats['shots_per_game'] * (2.0 - team_fatigue)
    sim_sa = np.random.poisson(lam=exp_shots_against, size=iterations)
    
    # Opponent xG per shot distribution against VGK structure
    opp_xg_per_shot = opp_team_stats.get('xg_per_shot', 0.088)
    sim_xga = sim_sa * opp_xg_per_shot
    
    goalie_summaries = []
    starter_sim_ga = None
    
    for idx, goalie in enumerate(vgk_goalies_list):
        # Heavy Bayesian Regression for Goalie (Option B: 2 parts league avg, 1 part true stat)
        goalie_base_sv = goalie['sv_pct']
        league_avg_sv = 0.905
        regressed_sv = (goalie_base_sv + league_avg_sv + league_avg_sv) / 3.0
        
        # Conversion rate is a blend of opponent shooting talent scaled by goalie talent vs average
        opp_conversion_rate = opp_xg_per_shot * ((1.0 - regressed_sv) / (1.0 - league_avg_sv))
        opp_conversion_rate = np.clip(opp_conversion_rate, 0.01, 0.35) # sanity bounds
        
        sim_ga = np.random.binomial(n=sim_sa, p=opp_conversion_rate)
        
        # Stash the starter's goals allowed array for OT calculations
        if idx == 0:
            starter_sim_ga = sim_ga
            
        # Calculate Sv% per run
        sim_sv_pct = np.where(sim_sa > 0, (sim_sa - sim_ga) / sim_sa, 1.0)
        
        # Pull condition at Period 2 (~66% through game)
        ga_p2 = np.random.binomial(n=sim_ga, p=0.66)
        vgk_goals_p2 = np.random.binomial(n=total_vgk_goals_per_run, p=0.66)
        pulled = (ga_p2 >= 4) & ((ga_p2 - vgk_goals_p2) >= 3) | (ga_p2 >= 5)
        
        goalie_summary = {
            "Goalie_Name": goalie['name'],
            "Exp_Shots_Against": round(float(np.mean(sim_sa)), 1),
            "Exp_xGA": round(float(np.mean(sim_xga)), 2),
            "Exp_GAA": round(float(np.mean(sim_ga)), 2),
            "Exp_Sv%": round(float(np.mean(sim_sv_pct)), 4),
            "Pull_Likelihood_%": round(float(np.mean(pulled) * 100), 2)
        }
        goalie_summaries.append(goalie_summary)
        
    df_goalies_summary = pd.DataFrame(goalie_summaries)
    
    # ---------------------------------------------------------
    # 7. GAME LINES & OT SIMULATION (Team Aggregates)
    # ---------------------------------------------------------
    # Sum the raw simulated arrays across all 18 skaters for each run
    vgk_sog_per_run = sim_sog.sum(axis=0)
    vgk_xg_per_run = sim_xg.sum(axis=0)
    vgk_assists_per_run = sim_assists.sum(axis=0)
    
    # Compare VGK goals to Opponent goals (assuming the Starter is in net)
    if starter_sim_ga is not None:
        ot_likelihood = np.mean(total_vgk_goals_per_run == starter_sim_ga) * 100
    else:
        ot_likelihood = 0.0
        
    game_lines = {
        "Exp_VGK_Goals": round(float(np.mean(total_vgk_goals_per_run)), 2),
        "Exp_VGK_xG": round(float(np.mean(vgk_xg_per_run)), 2),
        "Exp_VGK_Assists": round(float(np.mean(vgk_assists_per_run)), 2),
        "Exp_VGK_SOG": round(float(np.mean(vgk_sog_per_run)), 1),
        "Exp_Opp_Goals": round(float(np.mean(starter_sim_ga)) if starter_sim_ga is not None else 0.0, 2),
        "Exp_Opp_xG": round(float(np.mean(sim_xga)), 2),
        "Exp_Opp_SOG": round(float(np.mean(sim_sa)), 1),
        "OT_Likelihood_%": round(float(ot_likelihood), 2)
    }
    
    df_game_lines = pd.DataFrame([game_lines])

    return df_skaters_summary, df_goalies_summary, df_game_lines
