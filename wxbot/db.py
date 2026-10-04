"""Database schema and helpers (SQLAlchemy Core: SQLite now, PostgreSQL later).

Rows in forecast_snapshots, predictions and signals are insert-only, so every
paper bet can be traced back to the exact data and rule results behind it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
    create_engine, event, insert, select, update,
)
from sqlalchemy.engine import Engine

metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(name: str = "created_at", **kw) -> Column:
    return Column(name, DateTime(timezone=True), default=utcnow, nullable=False, **kw)


system_events = Table(
    "system_events", metadata,
    Column("id", Integer, primary_key=True),
    _ts("ts", index=True),
    Column("level", String(10), nullable=False),
    Column("component", String(40), nullable=False),
    Column("message", Text, nullable=False),
    Column("details", JSON),
    Column("code", String(40), index=True),           # event code, e.g. MODEL_DEPLOYED (v2 M9)
)

bot_state = Table(  # small key/value store: last update times, loop status
    "bot_state", metadata,
    Column("key", String(60), primary_key=True),
    Column("value", Text),
    _ts("updated_at"),
)

weather_observations = Table(
    "weather_observations", metadata,
    Column("id", Integer, primary_key=True),
    Column("station", String(10), nullable=False, index=True),
    Column("local_date", String(10), nullable=False),
    Column("kind", String(4), nullable=False),        # high | low
    Column("value_c", Float, nullable=False),
    Column("n_reports", Integer),
    Column("source", String(40), nullable=False),
    _ts("fetched_at"),
)

forecast_snapshots = Table(
    "forecast_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    _ts("fetched_at", index=True),
    Column("source", String(40), nullable=False),
    Column("station", String(10), nullable=False, index=True),
    Column("local_date", String(10), nullable=False),
    Column("kind", String(4), nullable=False),
    Column("values_c", JSON, nullable=False),         # {model_name: value_c}
    Column("request", JSON),                          # url + params used
    Column("issue_time", DateTime(timezone=True)),    # oldest model run used; None if unknown
    Column("quality", JSON),                          # validation result, see data/validation.py
)

market_price_history = Table(  # CLOB traded-price series, stored once a market resolves
    "market_price_history", metadata,          # a point only where the price changed: it holds until the next
    Column("id", Integer, primary_key=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    Column("token", String(3), nullable=False),        # YES
    Column("t", DateTime(timezone=True), nullable=False),
    Column("price", Float, nullable=False),
    _ts("fetched_at"),
)

market_criteria_history = Table(  # earlier rules text of a market, written when Polymarket edits it
    "market_criteria_history", metadata,          # (markets holds the current text)
    Column("id", Integer, primary_key=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    _ts("replaced_at"),                                # first seen with the new text
    Column("last_seen", DateTime(timezone=True)),      # last seen with this text
    Column("description", Text),
    Column("resolution_source", Text),
    Column("criteria", JSON),                          # parse_criteria() output incl. problems
)

forecast_values = Table(  # one row per model value: what each model said, from which run
    "forecast_values", metadata,
    Column("id", Integer, primary_key=True),
    Column("snapshot_id", Integer, ForeignKey("forecast_snapshots.id"), index=True),
    Column("source", String(40), nullable=False),
    Column("model", String(40), nullable=False),
    Column("station", String(10), nullable=False, index=True),
    Column("lat", Float),
    Column("lon", Float),
    Column("variable", String(30), nullable=False),     # temperature_2m_max | temperature_2m_min
    Column("target_date", String(10), nullable=False),  # station-local calendar day
    Column("issue_time", DateTime(timezone=True)),      # model run (initialisation) time, if known
    Column("issue_time_source", String(20)),            # model_run | unknown
    Column("horizon_hours", Float),                     # from issue (or fetch) time to the end of the target day
    Column("value", Float),
    Column("unit", String(1), nullable=False, default="C"),
    Column("valid", Boolean, nullable=False),
    Column("problem", String(60)),                      # why it was rejected, if not valid
    _ts("fetched_at", index=True),
)

markets = Table(
    "markets", metadata,
    Column("id", String(40), primary_key=True),       # Polymarket market id
    Column("event_id", String(40), index=True),
    Column("event_title", Text),
    Column("event_slug", Text),
    Column("question", Text),
    Column("bucket_label", String(40)),
    Column("city", String(60)),
    Column("station", String(10)),
    Column("kind", String(4)),
    Column("local_date", String(10), index=True),
    Column("unit", String(1)),
    Column("bucket_lo", Float),                       # None = open-ended
    Column("bucket_hi", Float),
    Column("yes_token", Text),
    Column("no_token", Text),
    Column("end_date", DateTime(timezone=True)),
    Column("resolution_source", Text),
    Column("description", Text),
    Column("tradeable", Boolean, default=False),      # parsed + station known
    Column("skip_reason", Text),
    Column("closed", Boolean, default=False),
    Column("resolved_outcome", String(3)),            # YES | NO
    Column("outcomes", JSON),                         # as listed by Polymarket, e.g. ["Yes", "No"]
    Column("pm_created_at", DateTime(timezone=True)),  # when Polymarket created the market
    Column("criteria", JSON),                         # parsed resolution rules + any mismatch found
    Column("closed_time", DateTime(timezone=True)),   # Polymarket closedTime, set at settlement
    Column("price_history_tries", Integer),           # failed or empty price-history fetches so far
    _ts("first_seen"),
    _ts("last_seen"),
)

market_snapshots = Table(
    "market_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    _ts("ts"),
    Column("best_bid", Float),
    Column("best_ask", Float),
    Column("last_price", Float),
    Column("yes_price", Float),
    Column("liquidity", Float),
    Column("volume", Float),
)

predictions = Table(
    "predictions", metadata,
    Column("id", Integer, primary_key=True),
    _ts("ts", index=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    Column("forecast_snapshot_id", Integer, ForeignKey("forecast_snapshots.id")),
    Column("model_version", String(40), nullable=False),
    Column("lead_days", Integer),
    Column("mu_c", Float),
    Column("sigma_c", Float),
    Column("p_yes", Float, nullable=False),
    Column("inputs", JSON),                           # everything the model used
    Column("role", String(12)),                       # production | shadow (None = before v2 M4: production)
    Column("feature_set", String(20)),                # see wxbot/features.py
    Column("calibrated_prob", Float),                 # p_yes after the active calibrator (production only)
    Column("calibrator_version", String(60)),         # prob_calibrators.version, or "identity"
    Column("params_version", String(60)),             # param_sets.version priced with (production only, v2 M9)
)

prob_calibrators = Table(  # every probability-calibrator fit; the newest round's selected one is active
    "prob_calibrators", metadata,
    Column("id", Integer, primary_key=True),
    Column("version", String(60), nullable=False),
    Column("method", String(12), nullable=False),      # isotonic | platt
    Column("model_version", String(40), nullable=False, index=True),
    _ts("fitted_at"),
    Column("n", Integer),                              # resolved markets available
    Column("n_train", Integer),
    Column("n_holdout", Integer),
    Column("train_from", DateTime(timezone=True)),     # decision times covered
    Column("train_to", DateTime(timezone=True)),
    Column("holdout_from", DateTime(timezone=True)),
    Column("holdout_to", DateTime(timezone=True)),
    Column("params", JSON),
    Column("brier_before", Float),                     # on the holdout: raw probabilities
    Column("brier_after", Float),                      # on the holdout: calibrated
    Column("log_loss_before", Float),
    Column("log_loss_after", Float),
    Column("improvement_confidence", Float),           # share of holdout bootstrap resamples where it wins
    Column("approved", Boolean, nullable=False),
    Column("selected", Boolean, nullable=False),       # the one used until the next fit round
    Column("reason", Text),
    Column("params_version", String(60)),              # fitted on (and applied to) this param set only (v2 M9)
)

model_versions = Table(  # model registry: every model version the bot has run, and its current role
    "model_versions", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(40), nullable=False),
    Column("version", String(40), nullable=False, unique=True),
    Column("calibration_version", String(40)),
    Column("feature_set", String(20)),
    Column("params", JSON),
    Column("role", String(12), nullable=False),        # production | shadow | retired
    _ts("created_at"),
    Column("role_changed_at", DateTime(timezone=True)),
    Column("notes", Text),
)

signals = Table(
    "signals", metadata,
    Column("id", Integer, primary_key=True),
    _ts("ts", index=True),
    Column("prediction_id", Integer, ForeignKey("predictions.id"), index=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    Column("side", String(3)),                        # YES | NO (best side)
    Column("model_prob", Float),                      # raw model probability of that side
    Column("calibrated_prob", Float),                 # after calibration; what the rules use
    Column("market_prob", Float),                     # mid-implied prob of that side
    Column("entry_price", Float),                     # fill price incl. slippage+fee
    Column("edge", Float),
    Column("ev_per_dollar", Float),
    Column("confidence", Float),
    Column("proposed_stake", Float),
    Column("decision", String(10)),                   # BET | NO_BET
    Column("reason", Text),
    Column("rule_results", JSON),                     # [{rule, passed, value, threshold}]
)

paper_bets = Table(
    "paper_bets", metadata,
    Column("id", Integer, primary_key=True),
    Column("signal_id", Integer, ForeignKey("signals.id"), unique=True),
    Column("market_id", String(40), ForeignKey("markets.id"), index=True),
    Column("event_id", String(40), index=True),
    Column("side", String(3), nullable=False),
    Column("token_id", Text),
    _ts("opened_at"),
    Column("market_prob", Float),
    Column("model_prob", Float),
    Column("edge", Float),
    Column("ev_per_dollar", Float),
    Column("confidence", Float),
    Column("entry_price", Float, nullable=False),     # avg price per share paid
    Column("shares", Float, nullable=False),
    Column("stake", Float, nullable=False),           # dollars spent incl. fee
    Column("fee", Float, default=0.0),
    Column("fill", JSON),                             # order-book levels walked
    Column("status", String(8), default="OPEN", index=True),  # OPEN | WON | LOST | VOID
    Column("outcome", String(3)),
    Column("settled_at", DateTime(timezone=True)),
    Column("payout", Float),
    Column("pnl", Float),
    Column("bankroll_after", Float),
    Column("mode", String(8), nullable=False, default="paper"),
    Column("sizing", JSON),                           # sizer, equity, every cap, budget, fill levels (v2 M6)
    Column("market_snapshot", JSON),                  # quotes when the bet was placed (v2 M6)
)

market_resolutions = Table(
    "market_resolutions", metadata,
    Column("market_id", String(40), ForeignKey("markets.id"), primary_key=True),
    _ts("resolved_at"),
    Column("outcome", String(3), nullable=False),
    Column("raw", JSON),
)

bankroll_snapshots = Table(
    "bankroll_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    _ts("ts", index=True),
    Column("cash", Float, nullable=False),
    Column("open_exposure", Float, nullable=False),   # stakes of open bets, at cost
    Column("equity", Float, nullable=False),          # cash + open bets marked to market (at cost before v2 M6)
    Column("realized_pnl", Float, nullable=False),
    Column("reason", String(40)),
    Column("market_value", Float),                    # open bets at the bid of the side held (v2 M6)
    Column("unrealized_pnl", Float),                  # market_value - open_exposure (v2 M6)
)

experiments = Table(  # what this database is: one experiment per database
    "experiments", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(60), nullable=False),
    Column("initial_bankroll", Float, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("git_ref", String(80)),                    # WXBOT_GIT_REF or GITHUB_SHA when the row was created
    Column("config", JSON),                           # settings at the start, secrets removed
    _ts("created_at"),
)

calibration_params = Table(
    "calibration_params", metadata,
    Column("id", Integer, primary_key=True),
    _ts("fitted_at"),
    Column("station", String(10), index=True),
    Column("kind", String(4)),
    Column("lead_days", Integer),
    Column("bias_c", Float),                          # mean(forecast - observed)
    Column("sigma_c", Float),
    Column("n", Integer),
    Column("window_start", String(10)),
    Column("window_end", String(10)),
    Column("backtest_run_id", Integer),
    Column("param_set_id", Integer, index=True),       # param_sets.id (v2 M9)
)

param_sets = Table(  # every fit of the station bias/spread parameters; one is production (v2 M9, wxbot/learning/)
    "param_sets", metadata,
    Column("id", Integer, primary_key=True),
    Column("version", String(60), nullable=False, unique=True),
    Column("model_version", String(40)),
    _ts("created_at"),
    Column("origin", String(12)),                     # backtest | retrain | legacy (fitted before v2 M9)
    Column("status", String(12), nullable=False, index=True),
    # production | previous (kept for a rollback) | retired | rolled_back | rejected | candidate
    Column("train_from", String(10)),                 # market days of forecasts and observations fitted
    Column("train_to", String(10)),
    Column("train_days", Integer),
    Column("n_rows", Integer),                        # station/kind/lead rows fitted
    Column("n_carried", Integer),                     # rows kept from production (too few days or no data)
    Column("evaluation", JSON),                       # out-of-sample comparison with production
    Column("approved", Boolean),
    Column("reason", Text),
    Column("deployed_at", DateTime(timezone=True)),   # last time it became production
    Column("retired_at", DateTime(timezone=True)),    # last time it left production
    Column("replaces", String(60)),                   # the production version it replaced
    Column("legacy", Boolean, nullable=False, default=False),  # predictions without params_version belong to it
)

prediction_outcomes = Table(  # the learning ledger: every resolved market's decision prediction (v2 M9)
    "prediction_outcomes", metadata,
    Column("id", Integer, primary_key=True),
    Column("market_id", String(40), ForeignKey("markets.id"), unique=True),
    Column("prediction_id", Integer, ForeignKey("predictions.id")),
    Column("signal_id", Integer),
    Column("bet_id", Integer),
    _ts("recorded_at"),
    Column("resolved_at", DateTime(timezone=True)),
    Column("decision_time", DateTime(timezone=True)),  # when the prediction was made
    Column("model_version", String(40), index=True),
    Column("params_version", String(60), index=True),
    Column("calibrator_version", String(60)),
    Column("feature_set", String(20)),
    Column("event_id", String(40)),
    Column("station", String(10), index=True),
    Column("city", String(60)),
    Column("kind", String(4)),
    Column("local_date", String(10), index=True),
    Column("lead_days", Integer),
    Column("unit", String(1)),
    Column("bucket_lo", Float),
    Column("bucket_hi", Float),
    Column("forecast_snapshot_id", Integer),
    Column("forecast_source", String(40)),
    Column("n_models", Integer),
    Column("model_spread_c", Float),
    Column("mu_c", Float),
    Column("sigma_c", Float),
    Column("distance_sigma", Float),                   # forecast mean's distance from the bucket, in sigmas
    Column("p_yes", Float, nullable=False),            # the model's probability
    Column("p_used", Float),                           # what the rules used (calibrated)
    Column("market_yes", Float),                       # market's mid-implied YES probability then
    Column("liquidity", Float),
    Column("outcome", String(3), nullable=False),
    Column("y", Integer, nullable=False),              # 1 = YES
    Column("error_class", String(30), index=True),     # wxbot/evaluation/errors.py classify(p_yes, y)
    Column("brier", Float),
    Column("log_loss", Float),
    Column("market_brier", Float),
    Column("decision", String(10)),                    # the signal: BET | NO_BET
    Column("side", String(3)),
    Column("entry_price", Float),
    Column("reason", Text),
    Column("bet_side", String(3)),                     # the paper bet on this market, if any
    Column("bet_status", String(8)),
    Column("bet_stake", Float),
    Column("bet_pnl", Float),
    Column("inputs", JSON),                            # model values, calibration, features, data quality
)

backtest_runs = Table(
    "backtest_runs", metadata,
    Column("id", Integer, primary_key=True),
    _ts("started_at"),
    Column("finished_at", DateTime(timezone=True)),
    Column("params", JSON),
    Column("report", JSON),
)

historical_forecasts = Table(  # market backtest: what each model forecast N days ahead (Previous Runs)
    "historical_forecasts", metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(40), nullable=False),
    Column("station", String(10), nullable=False, index=True),
    Column("kind", String(4), nullable=False),
    Column("local_date", String(10), nullable=False),
    Column("lead_days", Integer, nullable=False),      # previous_dayN: from runs at least N x 24 h before
    Column("model", String(40), nullable=False),
    Column("value_c", Float, nullable=False),          # daily high/low over the station's local day
    _ts("fetched_at"),
)

backtest_predictions = Table(  # market backtest: every replayed decision and what each source said then
    "backtest_predictions", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("backtest_runs.id"), index=True),
    Column("market_id", String(40), index=True),
    Column("lead_days", Integer),
    Column("decision_time", DateTime(timezone=True)),
    Column("price_time", DateTime(timezone=True)),     # the price point used: the last at or before the decision
    Column("market_prob", Float),                      # YES price then
    Column("p_climatology", Float),
    Column("p_raw_forecast", Float),
    Column("p_model", Float),
    Column("p_calibrated", Float),
    Column("calibrator_version", String(60)),
    Column("n_models", Integer),
    Column("mu_c", Float),
    Column("sigma_c", Float),
    Column("bias_c", Float),                           # walk-forward station bias used
    Column("bias_n", Integer),                         # past days it was fitted on (0 = default spread, no bias)
    Column("outcome", Integer),                        # 1 = YES
    Column("side", String(3)),                         # flat-stake strategy: the side the rules looked at
    Column("entry_price", Float),
    Column("decision", String(10)),                    # BET | NO_BET | HELD (already bet at an earlier lead)
    Column("reason", Text),
    Column("pnl_per_dollar", Float),                   # flat $1 stake; None without a bet
)

EXPORT_TABLES = [
    "paper_bets", "signals", "predictions", "forecast_snapshots", "forecast_values", "markets",
    "market_snapshots", "market_price_history", "market_criteria_history", "market_resolutions", "bankroll_snapshots",
    "weather_observations", "calibration_params", "backtest_runs", "model_versions", "prob_calibrators",
    "experiments", "system_events", "historical_forecasts", "backtest_predictions", "param_sets",
    "prediction_outcomes",
]


class Database:
    def __init__(self, url: str):
        kw = {"future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine: Engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(conn, _):  # noqa: ANN001
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        metadata.create_all(self.engine)
        from wxbot.migrations import migrate
        migrate(self.engine)

    # -- tiny helpers -------------------------------------------------------
    def insert(self, table: Table, **values) -> int:
        with self.engine.begin() as conn:
            res = conn.execute(insert(table).values(**values))
            pk = res.inserted_primary_key
            return pk[0] if pk else None

    def rows(self, stmt) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt)]

    def one(self, stmt) -> dict | None:
        rows = self.rows(stmt)
        return rows[0] if rows else None

    def set_state(self, key: str, value) -> None:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        with self.engine.begin() as conn:
            done = conn.execute(update(bot_state).where(bot_state.c.key == key)
                                .values(value=text, updated_at=utcnow())).rowcount
            if not done:
                conn.execute(insert(bot_state).values(key=key, value=text, updated_at=utcnow()))

    def get_state(self, key: str, default=None):
        row = self.one(select(bot_state.c.value).where(bot_state.c.key == key))
        return default if row is None else row["value"]

    def log_event(self, level: str, component: str, message: str, details: dict | None = None,
                  code: str | None = None) -> None:
        self.insert(system_events, ts=utcnow(), level=level, component=component,
                    message=message[:2000], details=details, code=code)
