# VGK EDGE Sim - Deployment Guide

## 1. Local Setup

1. Create a virtual environment: `python3 -m venv venv`
2. Activate the environment: `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Run the simulation manually: `python engine/monte_carlo.py`

## 2. GitHub Actions Setup

To deploy the automated pipeline, you need to configure a specific GitHub secret to allow the Scout action to trigger the Simulation action and update repository variables.

1. Generate a **Fine-grained Personal Access Token (PAT)** in your GitHub developer settings.
2. Grant the token **Variables (Read and write)** and **Actions (Read and write)** permissions for this specific repository.
3. Go to your repository **Settings > Secrets and variables > Actions**.
4. Add a new secret named `GH_TOKEN` and paste your PAT.
5. The `GH_REPO` variable is automatically injected by the runner using `${{ github.repository }}`.

## 3. How the Pipeline Works

- **Auto_1_Scout_Game_Time**: Runs every 15 minutes during prime NHL windows (22:00 to 05:00 UTC).
- If the puck drops in exactly 15-30 minutes, it checks the `LATEST_SIM_GAME_ID` repository variable.
- If the game hasn't been simulated yet, it fires a `workflow_dispatch` event to start **Auto_2_Sim** and updates the lock variable.
- **Auto_2_Sim** spins up, installs the environment, runs the ingestion and monte carlo engines, and outputs the 10,000-iteration player projections matrix.
