# Platform v2: gap analysis

This compares amir's long-term spec (posted 2026-10-01) with the code on `main` at ee70e2d (`amirmohamadazimi/Poly-Weather-Bot`).

Legend: **Have** = exists and is tested · **Partial** = exists but is missing what the spec asks for · **Missing** = not built.

## Defaults while v2 is built

- **The $1,000 experiment keeps running unchanged.** Its scheduled runs are pinned to a frozen copy of today's code, so no v2 change can alter its model or rules partway through.
- **The new 30-day, $100 experiment (section 17) starts once the v2 pieces it needs are merged.** The coordinator is confirming this with amir.
- **The layout moves gradually.** I'm moving toward the spec's `src/` layout only where it helps, with no big-bang rewrite. pyproject plus uv is in.
- **Paper only.** The live-trading boundary stays as it is.

## By section

| # | Section | Status | What exists | Gap |
|---|---|---|---|---|
| 1 | Core objective | Partial | Calibration, Brier, log loss, edge, EV, P/L, ROI with a bootstrap interval, drawdown; scores by market day and breakdowns by city, variable, lead and more (v2 M7) | Risk-adjusted return (Sharpe/Sortino) and performance by week |
| 2 | Architecture | Partial | A pipeline of collect → forecast → predict → signal → risk → paper → settle → evaluate; swappable model and broker classes | No separate data-validation, feature, calibration, error-analysis or model-improvement stages |
| 3 | GitHub-first repo | Partial | Git, CI tests, README, .env.example, Dockerfile, compose, a .gitignore with no secrets | LICENSE, pyproject/uv.lock, `config/`, `docs/`, `scripts/`, `migrations/`, `notebooks/`; README sections on DB structure, learning and reproducing experiments |
| 4 | Data collection | Partial | Append-only forecast snapshots (source, station, date, per-model values, fetch time); METAR highs and lows from IEM | The forecast's issue (model run) time and horizon aren't stored as columns. Only one provider (Open-Meteo, 5 models). No validation stage or lat/lon on rows. Observations are daily extremes only |
| 5 | Polymarket layer | Have | Discovery; question, description, outcomes, creation/end/close time, resolution source and result; bucket/station/unit parsing; snapshots of price, liquidity and volume for every market; a tested resolution-criteria check (extreme, unit, date, whole-degree precision, source, station code) that makes mismatching markets untradeable; resolved markets' CLOB price history (v2 M3) | Snapshots only at cycle times (no tick data); price history is YES only |
| 6 | Prediction engine | Have | A bias-corrected multi-model normal (production); climatology and raw-forecast baselines priced on every market as shadow models; a versioned feature set; side-by-side Brier and log-loss comparison on identical markets (v2 M4) | Logistic, GBM and Bayesian models come later |
| 7 | Probability calibration | Have | Station bias/σ fitted walk-forward; isotonic and Platt calibrators fitted walk-forward and approved only when they beat raw probabilities on a time-ordered holdout (Brier, log loss, bootstrap); calibrated probability on every prediction and signal; log loss, ECE and reliability bins, raw and calibrated (v2 M5); reliability diagram of raw and calibrated probabilities on the dashboard (v2 M7) | No gap |
| 8 | Market edge | Have | Model vs implied probability, edge, EV after slippage and fees | No gap |
| 9 | Betting signal | Partial | All 80%/edge/EV/liquidity/uncertainty/time/exposure rules on the calibrated probability, each recorded with value and threshold; the raw, calibrated and market probabilities on every signal (v2 M5) | A rule on the model's track record in similar situations. Add the readable decision card |
| 10 | $100 bankroll | Have | A persistent ledger-derived $100 bankroll; cash, exposure, open positions marked at the bid, realized and unrealized P/L, equity, drawdown; the paper broker refuses any fill that would make cash negative (v2 M6) | No gap |
| 11 | Risk management | Partial | Per-bet, total, per-event, per-city-day (high and low together) and cash caps; daily loss limit; every cap and the binding one recorded on each bet (v2 M6) | A regional correlation cap (neighbouring cities) |
| 12 | Paper engine | Have | Fills walk the real order book; the book and quotes at entry are stored; settlement and P/L; marked to market while open; no real orders possible | No gap |
| 13 | Learning from mistakes | Have | Every prediction stores inputs, model version, forecast and market price; after resolution each is classified (overconfidence, underestimation, significant or not) and grouped by city, lead, variable, bucket distance from the forecast, distance from the climate normal, model disagreement, liquidity and model version, with weaknesses flagged only at 3+ standard errors, on the dashboard's Learning tab and in REPORT.md (v2 M7). The learning ledger `prediction_outcomes` stores, per resolved market, the prediction, its versions, weather inputs, features, forecast source, market price and liquidity, decision, bet result, outcome and error class (v2 M9) | Feeding flagged weaknesses into the signal rules is left to evidence: a rule change is a new model version |
| 14 | Model versioning | Have | `model_versions` registry (version, calibration version, feature set, params, role); every prediction carries its model version, role and feature set (v2 M4), calibrator (v2 M5) and station bias/spread set (v2 M9); a new set replaces production only after an out-of-sample comparison (v2 M9) | No gap |
| 15 | Continuous learning | Have | Weekly retraining of the station bias/spread: candidates fitted before a holdout, judged on it against production (Brier and log loss, station bootstrap), deployed only if approved; the previous set is kept and restored automatically if the new one does worse (v2 M9). Calibrators refit daily with their own approval rule (v2 M5) | No gap |
| 16 | Backtesting | Have | A walk-forward forecast backtest with no look-ahead (Previous Runs API), and a market backtest (v2 M8) replaying closed Polymarket markets at the price on offer at each decision time, with forecasts, station bias, climatology and calibrator all limited to what was known then; naive vs raw forecast vs model vs calibrated vs market on the same markets, the live betting rules as flat bets and on a $100 bankroll, every excluded market counted | No gap. Liquidity and order-book depth cannot be replayed (not in Polymarket's history) |
| 17 | 30-day $100 experiment | Partial | A $1,000 version is running on GitHub Actions; REPORT.md | The $100 run itself; report sections on log loss, segments, over- and under-confidence, largest errors, model versions and edge concentration |
| 18 | Dashboard | Have | Overview (starting bankroll, equity, P/L, ROI, positions); live markets with current bid/ask, raw and calibrated probability, edge, EV and position; portfolio with mark value, payout, max loss and every risk limit's use; searchable bet history; charts of bankroll, P/L, drawdown, calibration (raw and calibrated), Brier, log loss, accuracy and model vs market; a Learning tab; system health with data-source status, database, model, calibrator and last refits (v2 M7) | No gap |
| 19 | Notifications | Missing | None | An optional notifier interface (log/webhook/email) for the listed events |
| 20 | Server deployment | Partial | Docker image that runs unprivileged, forces paper mode, keeps `.env` out, does the first-start setup and caps its logs; compose, systemd unit, env config; the actual runs are on GitHub Actions | A documented VPS deploy that pulls a tagged release |
| 21 | CI | Have | Lint (ruff), types (mypy on all of `wxbot`), tests with a 90% coverage floor, a clean-install build check and a Docker job on every PR; experiment 2 only runs commits of main that passed CI ([ci.md](ci.md)) | Automatic deploys to a server (M12) |
| 22 | Observability | Partial | JSON logs; a system_events table with an event `code` (v2 M9: MODEL_RETRAINED, MODEL_DEPLOYED, MODEL_ROLLBACK, SIGNIFICANT_MODEL_ERROR, PAPER_BET_OPENED) | Codes on the remaining events (DATA_UPDATE, MARKET_DISCOVERED, MARKET_RESOLVED, PAPER_BET_SETTLED, …) |
| 23 | Failure handling | Partial | Timeouts; retries with backoff incl. 429; stale-forecast and model-count rules; /healthz | Response caching; a validation stage that blocks bets on corrupt data |
| 24 | Testing | Partial | 53 tests covering parsing, model, rules, sizing, full cycle, settlement, duplicates, safety, backtest leakage | Calibration, data validation, API-failure, DB-operation and end-to-end resolution tests for the new parts |
| 25 | Safety boundary | Have | Paper is the default; live needs an env acknowledgement and still raises; PAPER shown in the dashboard | Add an explicit RESEARCH mode label |
| 26 | Final architecture | Partial | See rows 2–23 | No gap beyond those rows |
| 27 | Development strategy | — | — | The milestones below |

## By milestone

| M | Milestone | Status | PR plan |
|---|---|---|---|
| 1 | Working local app | Have | Repo foundations PR: pyproject/uv, LICENSE, docs/, README gaps, and pinning the $1,000 experiment to a frozen tag |
| 2 | Weather-data pipeline | Partial | Forecast revisions table (issue time, horizon, per-model rows, lat/lon), validation stage, source interface for a second provider |
| 3 | Polymarket data pipeline | Have | Done on `v2-m3-market-data`: outcomes, creation/close time, per-market snapshots, price history, resolution-criteria checks |
| 4 | Basic prediction model | Have | Done on `v2-m4-prediction-models`: climatology and raw-forecast baselines, model registry, side-by-side scoring |
| 5 | Probability calibration | Have | Done on `v2-m5-calibration`: isotonic/Platt layer with walk-forward approval, calibrated probability through to signals, log loss, ECE, reliability data |
| 6 | $100 paper engine | Have | Done on `v2-m6-paper-engine`: $100 defaults, mark-to-market, city-day exposure cap, non-negative cash invariant, experiments table |
| 7 | Dashboard | Have | Done on `v2-m7-dashboard`: live prices and calibrated probability, portfolio and risk limits, bet search, Brier/log-loss/accuracy charts, Learning tab, system health |
| 8 | Historical backtesting | Have | Done on `v2-m8-backtest`: `backtest-markets` and the manual `backtest` workflow; report BACKTEST.md |
| 9 | Error analysis and learning | Have | Done on `v2-m9-learning`: learning ledger with error classes, versioned bias/spread sets, weekly retrain with out-of-sample approval, automatic and manual rollback |
| 10 | Docker | Have | Non-root image forced to paper mode, first-start setup, log caps, and a CI job that starts it |
| 11 | CI and tests | Have | ruff, mypy, coverage floor, build check, and the CI gate on experiment 2 ([ci.md](ci.md)) |
| 12 | Server deployment | Partial | VPS guide plus tagged-release deploy; the Actions runner stays the default since there's no server |
| 13 | 30-day experiment | Partial | `paper-trading-100.yml` runs the $100 experiment from main (state on `paper-data-100`); running since 2026-10-01 21:48 UTC |
| 14 | Research report | Partial | Full end-of-experiment report from section 17 |

## Notes

- **Schema changes.** The running database was created by `create_all`, which doesn't add columns to existing tables. v2 needs a small migration step (`migrations/`) before it changes any table.
- **GitHub Actions minutes.** Two experiments at roughly 6 minutes per run, with runs every 7–8 hours as GitHub actually schedules them, come to about 1,400 of the 2,000 free minutes a month. A 14-day market backtest adds roughly 30 minutes per run, so run it sparingly on Actions or locally.
