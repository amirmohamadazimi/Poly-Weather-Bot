"""Schema migrations.

`metadata.create_all()` creates missing tables but never adds a column to a
table that already exists, so a database created by an older version (for
example the running experiment's) would miss columns added later. Every column
added after its table first shipped is listed here and added when missing.
Running this on every start is safe: it only touches what is absent.
"""
from __future__ import annotations

import logging

from sqlalchemy import JSON, DateTime, Engine, Float, Integer, String, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

log = logging.getLogger("wxbot.migrations")

# (table, column, type), in the order they were introduced
ADDED_COLUMNS = [
    ("forecast_snapshots", "issue_time", DateTime(timezone=True)),   # v2 M2
    ("forecast_snapshots", "quality", JSON()),                       # v2 M2
    ("markets", "outcomes", JSON()),                                 # v2 M3
    ("markets", "pm_created_at", DateTime(timezone=True)),           # v2 M3
    ("markets", "criteria", JSON()),                                 # v2 M3
    ("markets", "closed_time", DateTime(timezone=True)),             # v2 M3
    ("markets", "price_history_tries", Integer()),                   # v2 M3
    ("predictions", "role", String(12)),                             # v2 M4
    ("predictions", "feature_set", String(20)),                      # v2 M4
    ("predictions", "calibrated_prob", Float()),                     # v2 M5
    ("predictions", "calibrator_version", String(60)),               # v2 M5
    ("signals", "calibrated_prob", Float()),                         # v2 M5
    ("paper_bets", "sizing", JSON()),                                # v2 M6
    ("paper_bets", "market_snapshot", JSON()),                       # v2 M6
    ("bankroll_snapshots", "market_value", Float()),                 # v2 M6
    ("bankroll_snapshots", "unrealized_pnl", Float()),               # v2 M6
    ("system_events", "code", String(40)),                           # v2 M9
    ("predictions", "params_version", String(60)),                   # v2 M9
    ("prob_calibrators", "params_version", String(60)),              # v2 M9
    ("calibration_params", "param_set_id", Integer()),               # v2 M9
]


def migrate(engine: Engine) -> list[str]:
    """Add any missing columns; returns 'table.column' for each one added."""
    added = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, type_ in ADDED_COLUMNS:
            if table not in tables:
                continue
            if column in {c["name"] for c in insp.get_columns(table)}:
                continue
            ddl = type_.compile(dialect=engine.dialect)
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
            added.append(f"{table}.{column}")
            log.info("migration: added column %s.%s", table, column)
    adopt_legacy_params(engine)
    return added


def adopt_legacy_params(engine: Engine) -> str | None:
    """A database from before v2 M9 has station bias/spread rows but no param
    set. They become the first production set, marked legacy: predictions and
    calibrators stored before M9 (no params_version) belong to it. Runs only
    while no param set exists, so it never touches a database already on M9."""
    from wxbot.db import calibration_params, param_sets   # wxbot.db imports this module when it opens a database
    cp = calibration_params.c
    try:
        with engine.begin() as conn:
            if conn.execute(select(func.count()).select_from(param_sets)).scalar():
                return None
            rows = conn.execute(select(func.count().label("n"), func.min(cp.fitted_at).label("first"),
                                       func.max(cp.fitted_at).label("last"), func.min(cp.window_start).label("start"),
                                       func.max(cp.window_end).label("end")).where(cp.param_set_id.is_(None))).first()
            if not rows.n:
                return None
            version = f"bias-sigma-{rows.last:%Y%m%d}-initial"
            set_id = conn.execute(param_sets.insert().values(
                version=version, created_at=rows.first, origin="legacy", status="production", train_from=rows.start,
                train_to=rows.end, n_rows=rows.n, n_carried=0, approved=True, deployed_at=rows.first, legacy=True,
                reason="fitted by `backtest` before versioned parameter sets existed")).inserted_primary_key[0]
            conn.execute(update(calibration_params).where(cp.param_set_id.is_(None)).values(param_set_id=set_id))
    except IntegrityError:   # another process starting at the same moment adopted them first
        return None
    log.info("migration: station bias/spread rows adopted as param set %s", version)
    return version
