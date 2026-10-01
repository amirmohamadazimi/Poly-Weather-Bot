"""Schema migrations.

`metadata.create_all()` creates missing tables but never adds a column to a
table that already exists, so a database created by an older version (for
example the running experiment's) would miss columns added later. Every column
added after its table first shipped is listed here and added when missing.
Running this on every start is safe: it only touches what is absent.
"""
from __future__ import annotations

import logging

from sqlalchemy import JSON, DateTime, Engine, Integer, inspect, text

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
    return added
