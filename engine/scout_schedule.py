import os
import requests
import datetime
from dateutil import parser
from nhlpy import NHLClient

def check_and_trigger():
    print("Scouting for VGK games...")
    client = NHLClient()
    
    try:
        games = client.schedule.team_weekly_schedule(team_abbr="VGK")
    except Exception as e:
        print(f"Failed to fetch schedule: {e}")
        return
        
    if not games:
        print("No games in the current schedule window.")
        return
        
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Find the game scheduled for today or very soon
    upcoming_games = []
    for g in games:
        game_time_str = g.get('startTimeUTC')
        if not game_time_str:
            continue
        game_time = parser.parse(game_time_str)
        
        # Only look at games that haven't started yet
        if game_time > now:
            upcoming_games.append((g, game_time))
            
    if not upcoming_games:
        print("No upcoming unplayed games found.")
        return
        
    # Sort by closest game time
    upcoming_games.sort(key=lambda x: x[1])
    next_game, next_game_time = upcoming_games[0]
    game_id = str(next_game['id'])
    
    time_to_puck_drop = next_game_time - now
    minutes_to_drop = time_to_puck_drop.total_seconds() / 60.0
    
    print(f"Next Game ID: {game_id} starts in {minutes_to_drop:.1f} minutes.")
    
    scout_mode = os.environ.get("SCOUT_MODE", "PREGAME")
    
    if scout_mode == "MORNING":
        # If the game is within the next 24 hours (1440 minutes)
        if minutes_to_drop < 1440:
            print("Morning Scout: Game is today. Triggering simulation...")
            trigger_simulation()
        else:
            print("Morning Scout: No game within 24 hours.")
    else:
        # Execution Window: 105 < minutes <= 120 guarantees exactly one trigger for a 15-min cron
        if 105 < minutes_to_drop <= 120:
            print("Pregame Scout: Within 120-minute execution window. Triggering simulation...")
            trigger_simulation()
        else:
            print("Pregame Scout: Outside 120-minute execution window. Exiting silently.")

def trigger_simulation():
    gh_token = os.environ.get("GH_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    
    if not gh_token or not gh_repo:
        print("GitHub credentials missing. Cannot trigger workflow. Exiting.")
        return
        
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {gh_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    # Fire the workflow dispatch
    dispatch_url = f"https://api.github.com/repos/{gh_repo}/actions/workflows/Auto_2_Sim.yml/dispatches"
    payload = {"ref": "master"}
    r_disp = requests.post(dispatch_url, headers=headers, json=payload)
    
    if r_disp.status_code == 204:
        print("Successfully dispatched Auto_2_Sim.yml!")
    else:
        print(f"Failed to dispatch workflow: {r_disp.status_code} {r_disp.text}")

if __name__ == "__main__":
    check_and_trigger()
