from nhlpy import NHLClient
from datetime import datetime, timedelta, timezone
import sys

def check_game():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    client = NHLClient()
    try:
        schedule = client.schedule.team_weekly_schedule(team_abbr="VGK")
        if any(g.get('gameDate') == yesterday for g in schedule):
            print("played=true")
            sys.exit(0)
    except Exception:
        pass
        
    print("played=false")
    sys.exit(0)

if __name__ == "__main__":
    check_game()
