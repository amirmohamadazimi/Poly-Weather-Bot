# Database

SQLite by default (`data/wxbot.sqlite3`); PostgreSQL works through
`WXBOT_APP__DATABASE_URL`. The schema is defined in `wxbot/db.py`. Rows are
appended, not overwritten: a new forecast, prediction or signal is a new row,
so the database records what was known at each moment.

| Table | One row per | Key columns |
|---|---|---|
| `markets` | Polymarket market (one bucket) | id, event, question, description, station, kind (high/low), local_date, unit, bucket_lo/hi, tokens, end_date, tradeable/skip_reason, closed, resolved_outcome |
| `market_snapshots` | market per cycle | best_bid, best_ask, last_price, yes_price, liquidity, volume, ts |
| `forecast_snapshots` | station × day × kind per fetch | source, values_c (per weather model), request, fetched_at |
| `weather_observations` | station × day × kind | value_c (observed high or low), n_reports, source |
| `predictions` | market per cycle | model_version, lead_days, mu_c, sigma_c, p_yes, inputs (everything the model used) |
| `signals` | market per cycle | side, model_prob, market_prob, entry_price, edge, EV, proposed_stake, decision, reason, rule_results |
| `paper_bets` | simulated bet | signal_id, side, entry_price, shares, stake, fee, fill (order-book levels), status, outcome, payout, pnl, bankroll_after, mode |
| `market_resolutions` | resolved market | outcome, raw API response |
| `bankroll_snapshots` | bankroll change | cash, open_exposure, equity, realized_pnl, reason |
| `calibration_params` | station × kind × lead | bias_c, sigma_c, n, fit window, backtest_run_id |
| `backtest_runs` | backtest | params, report |
| `system_events` | log event (info and up) | level, component, message, details |
| `bot_state` | key | last cycle, markets monitored, loop status |

`python main.py export DIR` writes every table to CSV.
