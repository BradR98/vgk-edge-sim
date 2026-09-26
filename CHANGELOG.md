# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - Initial Release

### Added
- **Ingestion Engine (`engine/ingest.py`)**: Aggregates NHL EDGE tracking data, Shift Chart TOI (3rd period strain), and Schedule timezones into an exponential `Fatigue_Modifier`.
- **Monte Carlo Engine (`engine/monte_carlo.py`)**: Runs 10,000 iterations for SOG, Goals, and Assists using NumPy vectorized Poisson and Binomial distributions. Implemented sample-size shrinkage for xG regression and opponent goalie Save Percentage scalar.
- **Scout and Fire Pipeline**: Created `.github/workflows/Auto_1_Scout.yml` and `.github/workflows/Auto_2_Sim.yml`.
- **Dynamic Scheduler (`engine/scout_schedule.py`)**: Handles the lock-check and API dispatch for GitHub Actions to bypass global cron queue delays and ensure execution 15-30 minutes prior to puck drop.
