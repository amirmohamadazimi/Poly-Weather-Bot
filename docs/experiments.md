# Experiments

## Experiment 1: $1,000, started 2026-09-27

* Runs on GitHub Actions (`.github/workflows/paper-trading.yml`) every 3 hours.
  In practice GitHub fires it every 7–8 hours.
* The code is pinned to the `exp1-frozen` branch (main at ee70e2d), so changes
  to `main` do not alter its model or rules mid-run. Do not push to that branch.
* State: `wxbot.sqlite3` and `REPORT.md` on the `paper-data` branch.

## Experiment 2: $100, 30 days

* Runs on GitHub Actions (`.github/workflows/paper-trading-100.yml`) every 3
  hours, offset from experiment 1, from the code on `main`. It starts when that
  workflow reaches `main` (or with **Actions → paper-trading-100 → Run workflow**).
* Settings: the defaults in `config.toml` ($100, 2% or $2 per bet, at least $1
  a bet, and the exposure caps listed in the README). The workflow pins the
  starting bankroll and the name `exp2-100usd`.
* Identity: the first run records the experiment in the `experiments` table
  (name, starting bankroll, start time, commit, settings), and REPORT.md names
  it. Because it runs from `main`, merged improvements reach it; each run
  records its commit, every change of code version is logged in
  `system_events`, and the report shows the commit it started on and the one
  running now.
* Its first run loads three years of observation history
  (`python main.py climatology --if-missing`; retried on later runs if it
  fails) so the climatology baseline is scored from day one, and fits the
  forecast calibration (`backtest --if-missing`).
* State: `wxbot.sqlite3.gz` and `REPORT.md` on the `paper-data-100` branch.

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
