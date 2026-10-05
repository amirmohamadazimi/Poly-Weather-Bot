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
  it. Because it runs from `main`, merged improvements reach it, but only once
  their CI has passed: each run uses the newest commit of `main` on which the
  `tests` workflow passed ([ci.md](ci.md)). Each run records its commit,
  every change of code version is logged in `system_events`, and the report
  shows the commit it started on and the one running now.
* Length (from v2 M13): 30 days from its start at 2026-10-01 21:48 UTC, so it
  stops opening bets at **2026-10-31 21:48 UTC**. The workflow pins
  `WXBOT_EXPERIMENT__DAYS=30`, and the length is stored with the experiment the
  first time, so no later setting can move the end. After it, every signal
  fails the `experiment_open` rule; the runs go on settling the open bets,
  then log `EXPERIMENT_COMPLETE`. REPORT.md and the dashboard show the day
  ("day 4 of 30"), and then "ended" and "complete".
* Operation: REPORT.md's "Operation" section counts the cycles, the median and
  longest gap between them, finished days with none, and the errors logged.
  GitHub fires the 3-hourly schedule late: the first three days had 13 cycles,
  a median of 5.3 hours apart, the longest gap 8.9 hours.
* Learning (from v2 M9): once a week the cycle retrains the station bias and
  spread and deploys a new set only if it beats the one in use on markets it
  was not fitted on; a deployed set that then does worse is rolled back. Every
  prediction records the set that priced it, and REPORT.md lists every set, so
  results can be split by model version. `WXBOT_LEARNING__ENABLED=false` keeps
  the model fixed instead.
* Its first run loads three years of observation history
  (`python main.py climatology --if-missing`; retried on later runs if it
  fails) so the climatology baseline is scored from day one, and fits the
  forecast calibration (`backtest --if-missing`).
* Research report (from v2 M14): each run also writes `RESEARCH.md`, which
  answers whether the experiment found positive EV, with a verdict that needs
  five checks to pass, not a positive P/L. It is interim until the end,
  preliminary while the last bets settle, then final.
* State: `wxbot.sqlite3.gz`, `REPORT.md` and `RESEARCH.md` on the
  `paper-data-100` branch.

## Reproducing an experiment

1. Check out the code the experiment ran (for experiment 1, `git checkout exp1-frozen`).
2. Download `wxbot.sqlite3` from its state branch into `data/`.
3. `python main.py report` and `python main.py research` rebuild the reports
   from the stored rows (the research report is the same every time: its
   resampling uses a fixed seed), and `python main.py export DIR` dumps every
   table. Every bet links to the
   signal, prediction and forecast snapshot that produced it, with the exact
   inputs and order-book levels used.
4. `python main.py backtest --days 90` re-runs the walk-forward forecast
   backtest. It uses the forecasts each weather model actually issued before
   each day (Open-Meteo Previous Runs), so it has no look-ahead.
