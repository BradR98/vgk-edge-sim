import sys
from nhlpy import NHLClient

def fetch_vgk_roster_and_edge(season="20252026"):
    """
    Initializes the NHL API client and pulls down the VGK roster 
    and baseline EDGE tracking stats.
    """
    client = NHLClient()
    print("NHL Client initialized. Fetching VGK roster...")
    
    try:
        # 1. Pull the active roster
        roster = client.teams.team_roster(team_abbr="VGK", season=season)
        
        # Parse the forwards and defensemen to get their IDs
        skaters = roster.get('forwards', []) + roster.get('defensemen', [])
        
        print(f"Retrieved {len(skaters)} skaters. Fetching EDGE data for top line...")
        
        # 2. Example: Pull EDGE speed/distance data for the first player to test
        if skaters:
            test_player = skaters[0]
            player_id = test_player['id']
            player_name = f"{test_player['firstName']['default']} {test_player['lastName']['default']}"
            
            # This hits the undocumented EDGE endpoints
            edge_stats = client.edge.skater_skating_speed_detail(player_id=player_id, season=season)
            
            print(f"\n--- EDGE Data for {player_name} ---")
            try:
                top_speed = edge_stats['skatingSpeedDetails']['maxSkatingSpeed']['imperial']
            except (KeyError, TypeError):
                top_speed = 'N/A'
            print(f"Top Speed: {top_speed} mph")
            print("Successfully connected to NHL EDGE API endpoints.")
            
        return roster

    except Exception as e:
        print(f"Failed to fetch data: {e}")
        sys.exit(1)

if __name__ == "__main__":
    vgk_roster = fetch_vgk_roster_and_edge()
    
    # Next steps: 
    # 1. Pass roster to engine/ingest.py to build the baseline matrices
    # 2. Run engine/monte_carlo.py 10,000 times
