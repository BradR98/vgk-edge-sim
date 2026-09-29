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
    
    # Execution Window: 15 to 30 minutes
    if 15 <= minutes_to_drop <= 30:
        print("Within execution window. Checking lock...")
        trigger_simulation(game_id)
    else:
        print("Outside execution window. Exiting silently.")

def trigger_simulation(game_id):
    gh_token = os.environ.get("GH_TOKEN")
    gh_repo = os.environ.get("GH_REPO")
    
    if not gh_token or not gh_repo:
        print("GitHub credentials missing. Cannot trigger workflow or check locks. Exiting.")
        return
        
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {gh_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    var_url = f"https://api.github.com/repos/{gh_repo}/actions/variables/LATEST_SIM_GAME_ID"
    
    # 1. Check if we already fired for this game
    r_var = requests.get(var_url, headers=headers)
    var_exists = r_var.status_code == 200
    
    if var_exists:
        current_lock = r_var.json().get('value', '')
        if current_lock == str(game_id):
            print(f"Lock exists for Game ID {game_id}. Workflow already triggered.")
            return
            
    # 2. Fire the workflow dispatch
    dispatch_url = f"https://api.github.com/repos/{gh_repo}/actions/workflows/Auto_2_Sim.yml/dispatches"
    payload = {"ref": "main"}
    r_disp = requests.post(dispatch_url, headers=headers, json=payload)
    
    if r_disp.status_code == 204:
        print("Successfully dispatched Auto_2_Sim.yml!")
    else:
        print(f"Failed to dispatch workflow: {r_disp.status_code} {r_disp.text}")
        return
        
    # 3. Update the lock variable
    var_payload = {"name": "LATEST_SIM_GAME_ID", "value": str(game_id)}
    if var_exists:
        r_update = requests.patch(var_url, headers=headers, json=var_payload)
        if r_update.status_code == 204:
            print("Successfully updated LATEST_SIM_GAME_ID lock.")
    else:
        r_create = requests.post(f"https://api.github.com/repos/{gh_repo}/actions/variables", headers=headers, json=var_payload)
        if r_create.status_code == 201:
            print("Successfully created LATEST_SIM_GAME_ID lock.")

if __name__ == "__main__":
    check_and_trigger()
