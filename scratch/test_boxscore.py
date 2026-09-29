from nhlpy import NHLClient
import json
client = NHLClient()
boxscore = client.game_center.boxscore(game_id=2025020005) # Just use a past game to see the format
print(json.dumps(boxscore.get('awayTeam', {}), indent=2)[:500])
print(json.dumps(boxscore.get('gameOutcome', {}), indent=2)[:500])
