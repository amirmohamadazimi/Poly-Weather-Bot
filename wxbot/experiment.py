"""Experiment identity: which experiment a database holds.

The first engine start on a database records the experiment's name, starting
bankroll, start time, code version and settings in `experiments`. A database
holds one experiment: starting it again with a different bankroll is refused,
because the ledger's cash is computed from the starting bankroll and the
results would silently change.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from sqlalchemy import func, select

from wxbot.db import Database, bankroll_snapshots, experiments

SECRET_KEY_RE = re.compile(r"password|secret|token|api_?key|private", re.I)
URL_CREDENTIALS_RE = re.compile(r"//[^/@\s]+@")


def redact(value, key: str = ""):
    """The settings with secrets removed: secret-looking keys blanked, and
    credentials stripped from URLs (e.g. a PostgreSQL database_url)."""
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        if value and SECRET_KEY_RE.search(key):
            return "<redacted>"
        return URL_CREDENTIALS_RE.sub("//<redacted>@", value)
    return value


def git_ref(env=None) -> str | None:
    env = os.environ if env is None else env
    return env.get("WXBOT_GIT_REF") or env.get("GITHUB_SHA") or None


def current(db: Database) -> dict | None:
    return db.one(select(experiments).order_by(experiments.c.id).limit(1))


def ensure_experiment(db: Database, cfg, now: datetime, env=None) -> dict:
    """The database's experiment, recorded on first use. A database that
    already has bankroll history (from before experiments were recorded)
    starts at its first snapshot."""
    row = current(db)
    initial = float(cfg.bankroll.initial)
    if row is None:
        exp = cfg.get("experiment")
        first = db.one(select(func.min(bankroll_snapshots.c.ts).label("t")))
        db.insert(experiments, name=(exp.get("name") if exp else None) or "unnamed", initial_bankroll=initial,
                  started_at=(first or {}).get("t") or now, git_ref=git_ref(env), config=redact(cfg.as_dict()),
                  created_at=now)
        row = current(db)
        db.log_event("INFO", "experiment", f"experiment '{row['name']}' recorded: ${initial:,.2f} starting bankroll")
    elif abs(row["initial_bankroll"] - initial) > 1e-9:
        raise ValueError(f"this database holds experiment '{row['name']}', which started with "
                         f"${row['initial_bankroll']:,.2f}; the config says ${initial:,.2f}. "
                         "Use a new database for a new experiment.")
    return row
