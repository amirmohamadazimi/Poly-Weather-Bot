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
| `predictions` | model × market per cycle | model_version, role (production or shadow; empty on rows from before v2 M4, all production), feature_set, lead_days, mu_c, sigma_c, p_yes, inputs (production: every model input plus `features`; shadow: `production_prediction_id` and the few numbers specific to that model) |
| `model_versions` | model version ever run | name, version, calibration_version, feature_set, params, role (production, shadow or retired), created_at, role_changed_at. The one table besides `markets` updated in place: only `role` and `role_changed_at` change |
| `forecast_snapshots` | station × day × kind per fetch | source, values_c (per weather model, as fetched), request, fetched_at, issue_time (oldest model run used), quality (validation verdict: ok, rejected models and why, errors, warnings) |
| `forecast_values` | model value per fetch | source, model, station, lat/lon, variable, target_date, issue_time and issue_time_source (model_run or unknown), horizon_hours, value, unit, valid, problem |
| `weather_observations` | station × day × kind | value_c (observed high or low), n_reports, source |
| `signals` | market per cycle | side, model_prob, market_prob, entry_price, edge, EV, proposed_stake, decision, reason, rule_results |
| `paper_bets` | simulated bet | signal_id, side, entry_price, shares, stake, fee, fill (order-book levels), status, outcome, payout, pnl, bankroll_after, mode |
| `market_resolutions` | resolved market | outcome, raw API response |
| `bankroll_snapshots` | bankroll change | cash, open_exposure, equity, realized_pnl, reason |
| `calibration_params` | station × kind × lead | bias_c, sigma_c, n, fit window, backtest_run_id |
| `backtest_runs` | backtest | params, report |
| `system_events` | log event (info and up) | level, component, message, details |
| `bot_state` | key | last cycle, markets monitored, loop status |

`markets` and `model_versions` are the only tables updated in place. Each
discovery refreshes a market's descriptive fields, and a closed or resolved
market never re-opens; the registry only ever changes a model's role.

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

`python main.py export DIR` writes every table to CSV.

## Migrations

`create_all` adds new tables but never new columns to an existing table.
`wxbot/migrations.py` lists every column added after its table first shipped
and adds it when missing, on every start. Add a line there whenever a column
is added to an existing table.
