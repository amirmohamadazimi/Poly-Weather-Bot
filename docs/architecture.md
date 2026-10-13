# Architecture

One cycle (`wxbot/engine.py`, `Engine.run_cycle`) runs these stages in order.
Each stage is a function or class that can be replaced without touching the
others, and a failure in one stage is logged and does not stop the rest.

| Stage | Code | Writes |
|---|---|---|
| Market discovery | `wxbot/data/polymarket.py` (`PolymarketClient`, `parse_market`) | `markets`, `market_snapshots` |
| Resolution-criteria check | `wxbot/data/polymarket.py` (`parse_criteria`, `check_criteria`) | `markets.criteria`, `markets.tradeable/skip_reason` |
| Weather forecasts | `wxbot/data/weather.py` (`ForecastSource` interface, `OpenMeteoForecast`) | `forecast_snapshots`, `forecast_values` |
| Data validation | `wxbot/data/validation.py` | `forecast_snapshots.quality`, `forecast_values.valid/problem` |
| Station reports (same-day model) | `wxbot/data/weather.py` (`IEMObservations.fetch_reports`), `Engine.collect_reports`, for stations with a market on their local today | `station_reports`, `forecast_snapshots.hourly_c` (that day only) |
| Features | `wxbot/features.py` (`build_features`, climatology window) | `predictions.inputs.features`, `predictions.feature_set` |
| Prediction | `wxbot/model/` (`Predictor` interface, `NormalMultiModel`) | `predictions` (role production) |
| Shadow baselines | `wxbot/model/baselines.py` (`RawForecast`, `Climatology`) | `predictions` (role shadow; never a signal) |
| Same-day model | `wxbot/model/nowcast.py` (`Nowcast`, parameters in `nowcast_params.json` from `research/fit_nowcast.py`); 1–18 h before a market's day ends it makes the signal, through its own anchor | `predictions` (role shadow, feature_set `same-day-v1`) |
| Probability calibration | `wxbot/calibration/` (`fit_round` once a day as its own stage, `active_calibrator` each cycle) | `prob_calibrators`, `predictions.calibrated_prob/calibrator_version` |
| Market anchor | `wxbot/calibration/anchor.py` (`fit_round` and, for the same-day model, `fit_nowcast_round` once a day as their own stage, `active_anchor` each cycle; no bet while the newest fit is not approved) | `market_anchors` (scope `same-day` for the same-day model), the `market_anchor` rule and `anchored` probability in `signals.rule_results` |
| Model registry | `wxbot/model/registry.py` (`sync_registry`, at engine start) | `model_versions` |
| Market pricing and signal | `wxbot/strategy/rules.py` (`simulate_fill`, `evaluate`), on the anchored probability (the calibrated one with the anchor off) | `signals` (raw and used probability) |
| Risk and sizing | `wxbot/strategy/sizing.py`, `wxbot/execution/portfolio.py` | `signals.proposed_stake`, `rule_results` |
| Paper trading | `wxbot/execution/paper.py` (`PaperBroker`: refuses fills that would overdraw cash), `wxbot/execution/portfolio.py` (ledger, mark-to-market) | `paper_bets` (with sizing and quotes), `bankroll_snapshots` |
| Experiment identity | `wxbot/experiment.py` (`ensure_experiment`, at engine start) | `experiments` |
| Resolution and settlement | `Engine.settle` | `market_resolutions`, `paper_bets`, `markets.closed_time` |
| Experiment end | `wxbot/experiment.py` (`check_end`, each cycle after settlement; the `experiment_open` rule stops new bets after `planned_days`) | `bot_state`, `system_events` (EXPERIMENT_ENDED, EXPERIMENT_COMPLETE) |
| Price history (after resolution) | `Engine._store_price_histories`, `PolymarketClient.get_price_history` | `market_price_history` |
| Observations | `wxbot/data/weather.py` (`IEMObservations`) | `weather_observations` |
| Learning ledger | `wxbot/learning/outcomes.py` (`record`, each cycle after settlement) | `prediction_outcomes`, `system_events` (SIGNIFICANT_MODEL_ERROR) |
| Retraining and rollback | `wxbot/learning/retrain.py` (`retrain` when due, `check_rollback` each cycle), `wxbot/learning/params.py` (versioned sets; the engine prices with the production set) | `param_sets`, `calibration_params`, `predictions.params_version`, `system_events` (MODEL_RETRAINED, MODEL_DEPLOYED, MODEL_ROLLBACK) |
| Calibration (offline) | `wxbot/backtest.py` (the first param set) | `calibration_params`, `param_sets`, `backtest_runs` |
| Observation history (offline) | `wxbot/history.py` (`python main.py climatology`) | `weather_observations` |
| Market backtest (offline, own database) | `wxbot/backtesting/` (`collect`, `replay` with no look-ahead, `evaluate`, `report`; `python main.py backtest-markets`) | `historical_forecasts`, `backtest_predictions`, `backtest_runs`, plus closed `markets`, `market_resolutions`, `market_price_history`, `weather_observations` |
| Evaluation | `wxbot/evaluation/metrics.py` (incl. `model_comparison`, `daily_scores`, `portfolio_view`), `wxbot/evaluation/operation.py` (cycles, gaps, errors), `wxbot/report.py` | REPORT.md, dashboard |
| Research report | `wxbot/research.py` (`build`, `verdict`, `to_markdown`; `python main.py research`) | RESEARCH.md, `/api/research`, `/export/research.md` |
| Error analysis | `wxbot/evaluation/errors.py` (`error_analysis`: error classes, breakdowns, flagged weaknesses) | dashboard Learning tab, REPORT.md |
| System health | `wxbot/health.py` (data sources, database, model, param set and calibrator, last retraining and refits) | dashboard System health tab |

Every bet can be traced back: `paper_bets.signal_id` → `signals.prediction_id`
→ `predictions.forecast_snapshot_id` → the forecast values and request used.

The live-trading boundary is in `wxbot/execution/live.py`: `make_broker`
returns `PaperBroker` unless `app.mode = "live"`, and in live mode it always
raises.

The v2 plan (data validation, features, probability calibration, error
analysis, model registry and retraining) is in [roadmap.md](roadmap.md).
