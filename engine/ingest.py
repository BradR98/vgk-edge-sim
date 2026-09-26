import pandas as pd
import math
from nhlpy import NHLClient

# Timezones to calculate Travel Penalties
TEAM_TZ = {
    'ANA': -8, 'LAK': -8, 'SJS': -8, 'VAN': -8, 'SEA': -8, 'VGK': -8,
    'CGY': -7, 'COL': -7, 'EDM': -7, 'UTA': -7, 'ARI': -7,
    'CHI': -6, 'DAL': -6, 'MIN': -6, 'NSH': -6, 'STL': -6, 'WPG': -6,
    'BOS': -5, 'BUF': -5, 'CAR': -5, 'CBJ': -5, 'DET': -5, 'FLA': -5,
    'TBL': -5, 'TOR': -5, 'MTL': -5, 'NJD': -5, 'NYI': -5, 'NYR': -5,
    'PHI': -5, 'PIT': -5, 'WSH': -5, 'OTT': -5
}

def calculate_travel_penalty(prev_game_home, curr_game_home):
    """
    Calculates travel penalty based on timezones lost or gained.
    West to East (Losing hours) = -0.05 per timezone
    East to West (Gaining hours) = -0.02 per timezone
    """
    if prev_game_home not in TEAM_TZ or curr_game_home not in TEAM_TZ:
        return 0.0
    
    prev_tz = TEAM_TZ[prev_game_home]
    curr_tz = TEAM_TZ[curr_game_home]
    
    tz_diff = curr_tz - prev_tz
    if tz_diff > 0:
        # West to East
        return tz_diff * 0.05
    elif tz_diff < 0:
        # East to West
        return abs(tz_diff) * 0.02
    return 0.0

def parse_duration_to_minutes(duration_str):
    if not duration_str:
        return 0.0
    parts = duration_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) + int(parts[1])/60.0
    return 0.0

def build_fatigue_matrix(team_abbr="VGK", season="20252026", k_constant=0.5):
    client = NHLClient()
    
    # 1. Active Roster
    roster = client.teams.team_roster(team_abbr=team_abbr, season=season)
    skaters = roster.get('forwards', []) + roster.get('defensemen', [])
    
    # 2. Get schedule to find last game and current game to determine back-to-back
    sched = client.schedule.team_season_schedule(team_abbr, season=season)
    games = sched.get('games', [])
    # For simulation purposes, assume the last 2 games in the schedule represent prev and curr
    # Realistically, we'd find the latest played game. Let's just grab the last 2 games from regular season
    reg_games = [g for g in games if g.get('gameType') == 2]
    if len(reg_games) < 2:
        print("Not enough games to calculate fatigue.")
        return pd.DataFrame()
    
    prev_game = reg_games[-2]
    curr_game = reg_games[-1]
    
    prev_home = prev_game['homeTeam']['abbrev']
    curr_home = curr_game['homeTeam']['abbrev']
    
    travel_penalty = calculate_travel_penalty(prev_home, curr_home)
    
    matrix = []
    
    # 3. Process each skater
    for skater in skaters:
        player_id = skater['id']
        name = f"{skater['firstName']['default']} {skater['lastName']['default']}"
        
        # EDGE Data: Distance
        try:
            dist_data = client.edge.skater_skating_distance_detail(player_id=player_id, season=season)
            # Find the total season distance details
            details = dist_data.get('skatingDistanceDetails', [])
            all_strength = next((d for d in details if d.get('strengthCode') == 'all'), None)
            
            if all_strength:
                season_dist_game_max = all_strength.get('distanceMaxGame', {}).get('imperial', 3.5)
                # Approximate season avg dist as roughly 80% of max game for baseline
                season_avg_dist = season_dist_game_max * 0.8
                # Simulating prev game dist as we can't query single game directly without all game logs
                prev_game_dist = season_dist_game_max * 0.9 
            else:
                season_avg_dist = 3.5
                prev_game_dist = 3.5
        except Exception:
            season_avg_dist = 3.5
            prev_game_dist = 3.5
            
        # EDGE Data: Bursts
        try:
            speed_data = client.edge.skater_skating_speed_detail(player_id=player_id, season=season)
            bursts = speed_data.get('skatingSpeedDetails', {}).get('burstsOver22', {}).get('value', 0)
            # Season total bursts, divide by 82 for average
            season_avg_bursts = bursts / 82.0 if bursts else 2.0
            prev_game_bursts = season_avg_bursts * 1.1 # Placeholder
        except Exception:
            season_avg_bursts = 2.0
            prev_game_bursts = 2.0
            
        # Deltas
        dist_delta_pct = max(0, (prev_game_dist - season_avg_dist) / season_avg_dist) if season_avg_dist else 0
        burst_delta_pct = max(0, (prev_game_bursts - season_avg_bursts) / season_avg_bursts) if season_avg_bursts else 0
        
        # We will use 3rd period TOI from shift chart if available
        third_per_toi = 0.0
        try:
            shifts = client.game_center.shift_chart_data(prev_game['id'])
            if shifts and 'data' in shifts:
                player_shifts = [s for s in shifts['data'] if s.get('playerId') == player_id and s.get('period') == 3]
                third_per_toi = sum(parse_duration_to_minutes(s.get('duration', '00:00')) for s in player_shifts)
        except Exception:
            pass
            
        # Calculate Overload and Modifier
        # Adding an extra penalty factor if 3rd period TOI is heavily loaded (> 6 mins)
        toi_strain = 0.05 if third_per_toi > 6.0 else 0.0
        
        overload = dist_delta_pct + burst_delta_pct + travel_penalty + toi_strain
        
        # Exponential decay
        fatigue_modifier = 1.0 * math.exp(-k_constant * overload)
        
        # Cap to prevent unreasonable projection drops
        fatigue_modifier = max(0.80, min(1.0, fatigue_modifier))
        
        matrix.append({
            'Player_ID': player_id,
            'Name': name,
            'Season_Avg_Dist': round(season_avg_dist, 2),
            'Prev_Game_Dist': round(prev_game_dist, 2),
            'Prev_Game_Bursts': round(prev_game_bursts, 1),
            'Third_Per_TOI': round(third_per_toi, 1),
            'Travel_Penalty': round(travel_penalty, 3),
            'Fatigue_Modifier': round(fatigue_modifier, 3)
        })
        
    df = pd.DataFrame(matrix)
    return df

if __name__ == "__main__":
    print("Building Fatigue Matrix for VGK...")
    df = build_fatigue_matrix(season="20252026")
    print("\nVGK Fatigue Matrix:")
    print(df.head(10).to_string(index=False))
