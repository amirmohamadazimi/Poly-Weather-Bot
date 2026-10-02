"""Experiment identity: which experiment a database holds.

The first engine start on a database records the experiment's name, starting
bankroll, start time, code version and settings in `experiments`. A database
holds one experiment: starting it again with a different bankroll is refused,
because the ledger's cash is computed from the starting bankroll and the
results would silently change. When the code version changes between runs
(an experiment that runs from main picks up merged changes), the change is
logged, so every result can be tied to the code that produced it.
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


def recorded_bankroll(db: Database) -> float | None:
    """The starting bankroll this database was run with: its experiment's, or
    for a database from before experiments were recorded, the one its bankroll
    snapshots imply (cash + open stakes - realized P/L equals the starting
    bankroll in every snapshot). None for a new database."""
    row = current(db)
    if row:
        return row["initial_bankroll"]
    snap = db.one(select(bankroll_snapshots).order_by(bankroll_snapshots.c.id).limit(1))
    return None if snap is None else round(snap["cash"] + snap["open_exposure"] - snap["realized_pnl"], 2)


def starting_bankroll(db: Database, cfg) -> float:
    """What the dashboard and report count from: the database's own starting
    bankroll, so a downloaded experiment shows its numbers whatever the local
    config says; the config's for a new database."""
    recorded = recorded_bankroll(db)
    return float(cfg.bankroll.initial) if recorded is None else recorded


def record_code_version(db: Database, env=None) -> str | None:
    """Keep `code_ref` in bot_state current and log each change of code version."""
    ref = git_ref(env)
    prev = db.get_state("code_ref")
    if ref and ref != prev:
        db.set_state("code_ref", ref)
        if prev:
            db.log_event("INFO", "experiment", f"code version changed: {prev[:12]} -> {ref[:12]}",
                         details={"from": prev, "to": ref})
    return ref or prev


def ensure_experiment(db: Database, cfg, now: datetime, env=None) -> dict:
    """The database's experiment, recorded on first use. A database that
    already has bankroll history (from before experiments were recorded)
    starts at its first snapshot."""
    row = current(db)
    initial = float(cfg.bankroll.initial)
    recorded = recorded_bankroll(db)
    if recorded is not None and abs(recorded - initial) > 0.005:
        name = row["name"] if row else "recorded before experiments were named"
        raise ValueError(f"this database holds experiment '{name}', which started with "
                         f"${recorded:,.2f}; the config says ${initial:,.2f}. "
                         "Use a new database for a new experiment.")
    if row is None:
        exp = cfg.get("experiment")
        first = db.one(select(func.min(bankroll_snapshots.c.ts).label("t")))
        db.insert(experiments, name=(exp.get("name") if exp else None) or "unnamed", initial_bankroll=initial,
                  started_at=(first or {}).get("t") or now, git_ref=git_ref(env), config=redact(cfg.as_dict()),
                  created_at=now)
        row = current(db)
        db.log_event("INFO", "experiment", f"experiment '{row['name']}' recorded: ${initial:,.2f} starting bankroll")
    record_code_version(db, env)
    return row
