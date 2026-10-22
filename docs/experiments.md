# Experiments

## Experiment 1: $1,000, started 2026-09-27

* Runs on GitHub Actions (`.github/workflows/paper-trading.yml`) every 3 hours.
  In practice GitHub fires it every 7–8 hours.
* The code is pinned to the `exp1-frozen` branch (main at ee70e2d), so changes
  to `main` do not alter its model or rules mid-run. Do not push to that branch.
* State: `wxbot.sqlite3` and `REPORT.md` on the `paper-data` branch.
* No new bets since 2026-10-15 (experiment 3 took over); its runs go on so
  its open bets settle.

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
* Market anchor (from the fix for the losses, after 2026-10-12): bets only while
  the model combined with the market price beats the price alone on held-out
  resolved markets (README "Market anchor"). On the data so far that has never
  been the case, so from the run that picks this up the experiment places no
  new bets until the model earns them; open bets still settle. REPORT.md says
  so in its verdict and shows the latest fit.
* Same-day model (forward test, after 2026-10-13): a model that uses the
  station's reports from the market's own day (README "Same-day model"). In a
  backtest on Sep 27 to Oct 12 2026 against live order books (tight books
  only), the market was sharper at every hour of the day, e.g. log loss 0.103
  vs 0.005 with 4–6 h left and 0.318 vs 0.262 with 12–15 h left on
  highest-temperature markets, and every trading rule replayed at the recorded
  books lost (−6% to −53%). The bot runs the one version that could not be
  backtested, with the newest forecast, as a shadow model scored in REPORT.md;
  it can bet only 1–18 h before a market's day ends and only once its own
  anchor beats the market price on held-out markets. The research data
  (a year of METAR reports and day-ahead hourly forecasts) is on the
  `research-intraday` branch; `research/fit_nowcast.py` rebuilds the
  parameters from it.
* State: `wxbot.sqlite3.gz`, `REPORT.md` and `RESEARCH.md` on the
  `paper-data-100` branch.
* No new bets since 2026-10-15 (experiment 3 took over); its runs go on so
  its open bets settle, pinned to `normal-multimodel-v1`.

## Experiment 3: $100, 30 days, from 2026-10-15

* Runs on GitHub Actions (`.github/workflows/paper-trading-v3.yml`) every 3
  hours, offset from the others, from the newest commit of `main` that passed
  CI, like experiment 2. It starts when that workflow reaches `main`.
* Model: `weighted-multimodel-v1` (README "Production model"), at first betting
  only through the market anchor, which starts with no fit for this model and so
  places no bet until it has 300 resolved tight-book markets to judge it on.
  `normal-multimodel-v1`, `raw-forecast-v1`, `climatology-v1` and the
  same-day model are scored next to it as shadows.
* No bet in its first week: the anchor reached 300 markets on 2026-10-19 and
  was never approved (on 2026-10-21, 694 markets: model weight 0.06, holdout
  log loss 0.2568 with the model vs 0.2567 for the price alone). A replay of
  the forecast model's 229 bets it blocked (the first signal per market that
  failed no other rule): 125 settled, won 74.4% against 88.1% predicted and
  75.2% implied by the prices, a loss of $4.46 at $2 each. The same-day
  model's own anchor blocked 36 more (27 settled, a loss of $4.76).
* From 2026-10-22, by the owner's decision, it bets without the market check:
  the workflow sets `WXBOT_MARKET_ANCHOR__ENABLED=false`, so the rules use the
  model's calibrated probability, and the same-day model does not bet. The
  anchor is no longer refitted; REPORT.md says the check is off and shows its
  last fit. The switch is logged in `system_events`, and the database keeps
  it (`bot_state` `market_anchor_check`), so a report rebuilt from a
  downloaded copy says the same whatever the local config.
* The workflow pins the starting bankroll ($100), the name `exp3-v3-100usd`
  and the length (30 days).
* State: `wxbot.sqlite3.gz`, `REPORT.md` and `RESEARCH.md` on the
  `v3-paper-trade` branch.
* When it started, experiments 1 and 2 stopped opening bets (their workflows
  set `WXBOT_STRATEGY__MIN_MODEL_PROB=1.01`, which no probability reaches);
  their cycles go on so their open bets settle. Experiment 2 is pinned to
  `normal-multimodel-v1` and its five weather models.

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
