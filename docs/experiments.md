# Experiments

## Experiment 1: $1,000, started 2026-09-27

* Runs on GitHub Actions (`.github/workflows/paper-trading.yml`) every 3 hours.
  In practice GitHub fires it every 7–8 hours.
* The code is pinned to the `exp1-frozen` branch (main at ee70e2d), so changes
  to `main` do not alter its model or rules mid-run. Do not push to that branch.
* State: `wxbot.sqlite3` and `REPORT.md` on the `paper-data` branch.

## Experiment 2: $100, 30 days (planned)

Starts once the v2 milestones it needs (M2–M6 in [roadmap.md](roadmap.md)) are
merged. It will run from `main` with its own state branch. Its first run also
loads observation history (`python main.py climatology --if-missing`) so the
climatology baseline can be scored from day one.

## Reproducing an experiment

1. Check out the code the experiment ran (for experiment 1, `git checkout exp1-frozen`).
2. Download `wxbot.sqlite3` from its state branch into `data/`.
3. `python main.py report` rebuilds the report from the stored rows, and
   `python main.py export DIR` dumps every table. Every bet links to the
   signal, prediction and forecast snapshot that produced it, with the exact
   inputs and order-book levels used.
4. `python main.py backtest --days 90` re-runs the walk-forward forecast
   backtest. It uses the forecasts each weather model actually issued before
   each day (Open-Meteo Previous Runs), so it has no look-ahead.
