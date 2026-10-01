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
| 1 | Core objective | Partial | Calibration, Brier, edge, EV, P/L, ROI with a bootstrap interval, and drawdown | Log loss, risk-adjusted return (Sharpe/Sortino), stability by city, variable and lead, and performance over time by week |
| 2 | Architecture | Partial | A pipeline of collect → forecast → predict → signal → risk → paper → settle → evaluate; swappable model and broker classes | No separate data-validation, feature, calibration, error-analysis or model-improvement stages |
| 3 | GitHub-first repo | Partial | Git, CI tests, README, .env.example, Dockerfile, compose, a .gitignore with no secrets | LICENSE, pyproject/uv.lock, `config/`, `docs/`, `scripts/`, `migrations/`, `notebooks/`; README sections on DB structure, learning and reproducing experiments |
| 4 | Data collection | Partial | Append-only forecast snapshots (source, station, date, per-model values, fetch time); METAR highs and lows from IEM | The forecast's issue (model run) time and horizon aren't stored as columns. Only one provider (Open-Meteo, 5 models). No validation stage or lat/lon on rows. Observations are daily extremes only |
| 5 | Polymarket layer | Have | Discovery; question, description, outcomes, creation/end/close time, resolution source and result; bucket/station/unit parsing; snapshots of price, liquidity and volume for every market; a tested resolution-criteria check (extreme, unit, date, whole-degree precision, source, station code) that makes mismatching markets untradeable; resolved markets' CLOB price history (v2 M3) | Snapshots only at cycle times (no tick data); price history is YES only |
| 6 | Prediction engine | Have | A bias-corrected multi-model normal (production); climatology and raw-forecast baselines priced on every market as shadow models; a versioned feature set; side-by-side Brier and log-loss comparison on identical markets (v2 M4) | Logistic, GBM and Bayesian models come later |
| 7 | Probability calibration | Have | Station bias/σ fitted walk-forward; isotonic and Platt calibrators fitted walk-forward and approved only when they beat raw probabilities on a time-ordered holdout (Brier, log loss, bootstrap); calibrated probability on every prediction and signal; log loss, ECE and reliability bins, raw and calibrated (v2 M5) | Reliability-diagram charts on the dashboard (M7) |
| 8 | Market edge | Have | Model vs implied probability, edge, EV after slippage and fees | No gap |
| 9 | Betting signal | Partial | All 80%/edge/EV/liquidity/uncertainty/time/exposure rules on the calibrated probability, each recorded with value and threshold; the raw, calibrated and market probabilities on every signal (v2 M5) | A rule on the model's track record in similar situations. Add the readable decision card |
| 10 | $100 bankroll | Partial | A persistent ledger-derived bankroll; cash, exposure, equity, realized P/L, drawdown | Starting bankroll is $1,000 (config). No mark-to-market unrealized P/L. A tested non-negative-cash invariant |
| 11 | Risk management | Partial | Per-bet, total, per-event and cash caps; daily loss limit; sizing recorded on signals | Correlated-exposure cap (same city/day across events, same region); sizing method recorded per bet |
| 12 | Paper engine | Have | Fills walk the real order book; the book at entry is stored; settlement and P/L; no real orders possible | Mark-to-market while open (see 10) |
| 13 | Learning from mistakes | Missing | Every prediction stores inputs, model version, forecast and market price | Error classification after resolution, and recurring-failure analysis by location, lead, variable, extremes, disagreement, liquidity and model version |
| 14 | Model versioning | Have | `model_versions` registry (version, calibration version, feature set, params, role); every prediction carries its model version, role and feature set (v2 M4) | Calibrator fits are versioned in `prob_calibrators` and every prediction records the one it used (v2 M5) |
| 15 | Continuous learning | Missing | Calibration refits only on the first run | A retrain → validate → compare with production → approval rule → deploy/rollback pipeline |
| 16 | Backtesting | Partial | A walk-forward forecast backtest with no look-ahead (Previous Runs API) | Naive vs forecast vs model vs calibrated vs market comparison; a market-price backtest using historical Polymarket prices |
| 17 | 30-day $100 experiment | Partial | A $1,000 version is running on GitHub Actions; REPORT.md | The $100 run itself; report sections on log loss, segments, over- and under-confidence, largest errors, model versions and edge concentration |
| 18 | Dashboard | Partial | Overview, markets, bet history, performance, status | Calibrated probability column, portfolio mark value, searchable history, log loss and calibration charts, an error-analysis tab, model version and last retrain in health |
| 19 | Notifications | Missing | None | An optional notifier interface (log/webhook/email) for the listed events |
| 20 | Server deployment | Partial | Docker, compose, systemd unit, env config; the actual runs are on GitHub Actions | A documented VPS deploy that pulls a tagged release |
| 21 | CI | Partial | pytest on PRs and main | Lint (ruff), type check (mypy on core), Docker build, staging vs production split |
| 22 | Observability | Partial | JSON logs; a system_events table | A standard event vocabulary (DATA_UPDATE, PAPER_BET_OPENED, MODEL_DEPLOYED, …) |
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
| 6 | $100 paper engine | Partial | $100 experiment config, mark-to-market, correlated exposure, non-negative cash invariant, separate experiment ids |
| 7 | Dashboard | Partial | Calibrated probability, portfolio, search, new charts, health fields |
| 8 | Historical backtesting | Partial | Baselines vs model vs market, with historical prices |
| 9 | Error analysis and learning | Missing | Error classes, failure patterns, retrain/approve/rollback pipeline |
| 10 | Docker | Have | Compose service for the dashboard plus worker; small fixes only |
| 11 | CI and tests | Partial | ruff, mypy, Docker build, coverage of new parts |
| 12 | Server deployment | Partial | VPS guide plus tagged-release deploy; the Actions runner stays the default since there's no server |
| 13 | 30-day experiment | Partial | Start the $100 run on Actions once M2–M6 are merged |
| 14 | Research report | Partial | Full end-of-experiment report from section 17 |

## Notes

- **Schema changes.** The running database was created by `create_all`, which doesn't add columns to existing tables. v2 needs a small migration step (`migrations/`) before it changes any table.
- **GitHub Actions minutes.** Two experiments at roughly 6 minutes per run, with runs every 7–8 hours as GitHub actually schedules them, come to about 1,400 of the 2,000 free minutes a month.
