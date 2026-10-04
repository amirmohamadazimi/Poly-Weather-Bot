# Database

SQLite by default (`data/wxbot.sqlite3`); PostgreSQL works through
`WXBOT_APP__DATABASE_URL`. The schema is defined in `wxbot/db.py`. Rows are
appended, not overwritten: a new forecast, prediction or signal is a new row,
so the database records what was known at each moment.

| Table | One row per | Key columns |
|---|---|---|
| `markets` | Polymarket market (one bucket) | id, event, question, description, resolution_source, station, kind (high/low), local_date, unit, bucket_lo/hi, tokens, outcomes, pm_created_at (Polymarket creation time), end_date, closed_time (set at settlement), criteria (parsed resolution rules and any problems, see below), tradeable/skip_reason, closed, resolved_outcome |
| `market_snapshots` | market per cycle (every market seen, tradeable or not) | best_bid, best_ask, last_price, yes_price, liquidity, volume, ts |
| `market_price_history` | price change of a resolved market | market_id, token (YES), t, price, fetched_at; fetched once from CLOB `/prices-history` (hourly, creation to close) after resolution; only points where the price changed, plus the last one, so a price holds until the next row |
| `market_criteria_history` | earlier version of a market's rules text | market_id, description, resolution_source, criteria (as parsed then), last_seen (last cycle with this text), replaced_at (first cycle with the new text). Written only when Polymarket edits a market; `markets` holds the current text |
| `predictions` | model × market per cycle | model_version, role (production or shadow; empty on rows from before v2 M4, all production), feature_set, lead_days, mu_c, sigma_c, p_yes, calibrated_prob and calibrator_version (production only, from v2 M5: p_yes after the active calibrator, or `identity` when none was approved), params_version (production only, from v2 M9: the station bias/spread set it was priced with; empty before M9, which means the legacy set, or with no set), inputs (production: every model input plus `features`; shadow: `production_prediction_id` and the few numbers specific to that model) |
| `prob_calibrators` | calibrator fit (one per method per fit round) | version, method (isotonic, platt), model_version, fitted_at, n / n_train / n_holdout, train and holdout windows (decision times), params, holdout brier and log loss before (raw) and after (calibrated), improvement_confidence (share of bootstrap resamples where it wins), approved, selected (the one used until the next round), reason, params_version (from v2 M9: the station bias/spread set whose predictions it was fitted on and is applied to) |
| `model_versions` | model version ever run | name, version, calibration_version, feature_set, params, role (production, shadow or retired), created_at, role_changed_at. The one table besides `markets` updated in place: only `role` and `role_changed_at` change |
| `forecast_snapshots` | station × day × kind per fetch | source, values_c (per weather model, as fetched), request, fetched_at, issue_time (oldest model run used), quality (validation verdict: ok, rejected models and why, errors, warnings) |
| `forecast_values` | model value per fetch | source, model, station, lat/lon, variable, target_date, issue_time and issue_time_source (model_run or unknown), horizon_hours, value, unit, valid, problem |
| `weather_observations` | station × day × kind | value_c (observed high or low), n_reports, source |
| `signals` | market per cycle | side, model_prob (raw), calibrated_prob (what the rules used; from v2 M5), market_prob, entry_price, edge, EV, proposed_stake, decision, reason, rule_results |
| `paper_bets` | simulated bet | signal_id, side, entry_price, shares, stake, fee, fill (order-book levels), status, outcome, payout, pnl, bankroll_after, mode, sizing (from v2 M6: sizer, equity, cash, open exposure, every cap, the binding cap, budget, fill levels), market_snapshot (from v2 M6: the snapshot's YES bid/ask/price and liquidity, the held side's bid/ask/mid, the order book's best ask) |
| `market_resolutions` | resolved market | outcome, raw API response |
| `bankroll_snapshots` | bankroll change | cash, open_exposure (at cost), market_value (open bets at the bid of the side held), unrealized_pnl, equity (cash + market value from v2 M6; cash + open exposure before), realized_pnl, reason |
| `experiments` | experiment (one per database) | name, initial_bankroll, started_at (first bankroll snapshot, or the first start), git_ref, config (settings at the start, secrets removed), created_at |
| `calibration_params` | station × kind × lead in a parameter set | bias_c, sigma_c, n, fit window, backtest_run_id, param_set_id (from v2 M9) |
| `param_sets` | fit of the station bias/spread (v2 M9) | version, model_version, origin (backtest, retrain, legacy), status (production, previous, retired, rolled_back, rejected, candidate), train_from/train_to/train_days (days fitted), n_rows, n_carried (rows kept from production), evaluation (holdout comparison with production: markets, events, stations, Brier and log loss of each, log loss of the probabilities used, station-bootstrap confidence), approved, reason, deployed_at, retired_at, replaces, legacy (owns the predictions stored before versions were recorded). Only status, deployed_at, retired_at, replaces and (on a rollback) reason change |
| `prediction_outcomes` | resolved market: the learning ledger (v2 M9) | prediction_id, signal_id, bet_id, resolved_at, decision_time, model_version, params_version, calibrator_version, feature_set, station, city, kind, local_date, lead_days, bucket, forecast_snapshot_id, forecast_source, n_models, model_spread_c, mu_c, sigma_c, distance_sigma, p_yes, p_used, market_yes, liquidity, outcome, y, error_class, brier, log_loss, market_brier, decision, side, entry_price, reason, bet_side/status/stake/pnl, inputs (model values, calibration, features, data quality). Written once per market, from the production model's last prediction made a day or more ahead |
| `backtest_runs` | backtest | params (kind `markets` for the market backtest: window, leads, delay, half spread, git_ref, the settings used), report |
| `historical_forecasts` | model forecast for a station × day × kind × lead (market backtest) | source, lead_days (Previous Runs `previous_dayN`: from runs at least N × 24 h before each hour), model, value_c, fetched_at |
| `backtest_predictions` | replayed decision: market × lead (market backtest) | run_id, decision_time, price_time (the price point used, never after the decision), market_prob, p_climatology, p_raw_forecast, p_model, p_calibrated, calibrator_version, n_models, mu_c, sigma_c, bias_c and bias_n (walk-forward station bias and the days it was fitted on), outcome, and the flat-stake decision: side, entry_price, decision (BET, NO_BET, HELD), reason, pnl_per_dollar |
| `system_events` | log event (info and up) | level, component, message, details, code (from v2 M9: e.g. MODEL_RETRAINED, MODEL_DEPLOYED, MODEL_ROLLBACK, SIGNIFICANT_MODEL_ERROR, PAPER_BET_OPENED) |
| `bot_state` | key | last cycle, markets monitored, loop status |

`markets`, `model_versions` and `param_sets` are the only tables updated in
place. Each discovery refreshes a market's descriptive fields, and a closed or
resolved market never re-opens; the registry only ever changes a model's role;
a parameter set only changes status (its rows in `calibration_params` never
change).

`markets.criteria` holds what `parse_criteria` read from the description:
`rule_found`, `extreme` (high/low), `unit`, `station_name`, `date`,
`date_text`, `precision` and `precision_unit`, `primary_source` (from the
link), `named_sources` (from the text), `station_codes`, `extremes_mentioned`,
`units_mentioned`, `rules_agree` (false when a second rule sentence says
something different), `no_data_rule`, `fallback_source` (used if the primary
source has no data, e.g. Wunderground for NOAA markets), `hourly_only` (US
markets that resolve on NOAA's hourly rows only), and `problems` (every
mismatch found; empty when the market's text agrees with its title and bucket).

`markets.price_history_tries` counts failed or empty price-history fetches;
after 3 the market is not asked again.

`market_price_history` is fetched after the fact, so for any backtest only
points with `t` at or before the decision time may be used.

The market backtest (`python main.py backtest-markets`) uses its own database,
`[backtest] database_url` (`data/backtest.sqlite3`), with this same schema: it
stores the closed markets of its window in `markets`, `market_resolutions`
(resolved_at = Polymarket's close time) and `market_price_history`, the
observations in `weather_observations`, and adds `historical_forecasts` and
`backtest_predictions`. An experiment's database never gets these rows.

`python main.py export DIR` writes every table to CSV.

## Migrations

`create_all` adds new tables but never new columns to an existing table.
`wxbot/migrations.py` lists every column added after its table first shipped
and adds it when missing, on every start. Add a line there whenever a column
is added to an existing table. It also gives a database from before v2 M9 its
first parameter set: the existing `calibration_params` rows become the legacy
production set.
