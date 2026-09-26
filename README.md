# VGK EDGE Sim

A mathematically rigorous Monte Carlo simulation engine for the Vegas Golden Knights, driven by NHL EDGE tracking data and real-time shift metrics.

## Architecture

This project uses a **Scout and Fire** automated pipeline via GitHub Actions to ensure simulations run perfectly timed with puck drops, bypassing standard cron queue limitations.

1. **Ingest Engine (`engine/ingest.py`)**: Pulls previous game tracking data (distance, speed bursts, TOI) and compares it to season baselines to generate a dynamic `Fatigue_Modifier`.
2. **Monte Carlo Engine (`engine/monte_carlo.py`)**: Runs a fully vectorized 10,000-iteration simulation using `numpy` to generate robust player props (SOG, Goals, Assists) and Goalie pull probabilities.
3. **Automated Scout (`engine/scout_schedule.py`)**: A lightweight Python script that polls the NHL schedule to dynamically trigger the simulation pipeline exactly 15-30 minutes before puck drop.

## Setup

See the [GUIDE.md](GUIDE.md) for detailed configuration and deployment instructions.
