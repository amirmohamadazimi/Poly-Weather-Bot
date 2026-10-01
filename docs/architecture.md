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
| Prediction | `wxbot/model/` (`Predictor` interface, `NormalMultiModel`) | `predictions` |
| Market pricing and signal | `wxbot/strategy/rules.py` (`simulate_fill`, `evaluate`) | `signals` |
| Risk and sizing | `wxbot/strategy/sizing.py`, `wxbot/execution/portfolio.py` | `signals.proposed_stake`, `rule_results` |
| Paper trading | `wxbot/execution/paper.py` (`PaperBroker`) | `paper_bets`, `bankroll_snapshots` |
| Resolution and settlement | `Engine.settle` | `market_resolutions`, `paper_bets`, `markets.closed_time` |
| Price history (after resolution) | `Engine._store_price_histories`, `PolymarketClient.get_price_history` | `market_price_history` |
| Observations | `wxbot/data/weather.py` (`IEMObservations`) | `weather_observations` |
| Calibration (offline) | `wxbot/backtest.py` | `calibration_params`, `backtest_runs` |
| Evaluation | `wxbot/evaluation/metrics.py`, `wxbot/report.py` | REPORT.md, dashboard |

Every bet can be traced back: `paper_bets.signal_id` → `signals.prediction_id`
→ `predictions.forecast_snapshot_id` → the forecast values and request used.

The live-trading boundary is in `wxbot/execution/live.py`: `make_broker`
returns `PaperBroker` unless `app.mode = "live"`, and in live mode it always
raises.

The v2 plan (data validation, features, probability calibration, error
analysis, model registry and retraining) is in [roadmap.md](roadmap.md).
