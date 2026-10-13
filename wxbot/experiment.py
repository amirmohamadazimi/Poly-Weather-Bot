"""Experiment identity: which experiment a database holds.

The first engine start on a database records the experiment's name, starting
bankroll, start time, code version and settings in `experiments`. A database
holds one experiment: starting it again with a different bankroll is refused,
because the ledger's cash is computed from the starting bankroll and the
results would silently change. When the code version changes between runs
(an experiment that runs from main picks up merged changes), the change is
logged, so every result can be tied to the code that produced it.

An experiment can have a planned length (experiment.days, recorded once). After
it the bot opens no new bets (the `experiment_open` rule), open bets still
settle, and once the last one has the experiment is complete:
EXPERIMENT_ENDED and EXPERIMENT_COMPLETE are logged once each.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from wxbot.db import Database, bankroll_snapshots, experiments, paper_bets

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
    exp = cfg.get("experiment")
    days = int((exp.get("days") if exp else 0) or 0) or None
    if row is None:
        first = db.one(select(func.min(bankroll_snapshots.c.ts).label("t")))
        db.insert(experiments, name=(exp.get("name") if exp else None) or "unnamed", initial_bankroll=initial,
                  started_at=(first or {}).get("t") or now, git_ref=git_ref(env), config=redact(cfg.as_dict()),
                  created_at=now, planned_days=days)
        row = current(db)
        assert row is not None   # inserted just above
        db.log_event("INFO", "experiment", f"experiment '{row['name']}' recorded: ${initial:,.2f} starting bankroll"
                     + (f", {days} days, until {ends_at(row):%Y-%m-%d %H:%M} UTC" if days else ""))
    elif days and row["planned_days"] is None:
        # an experiment under way gets its length once; later config changes do not move its end
        with db.engine.begin() as conn:
            conn.execute(update(experiments).where(experiments.c.id == row["id"]).values(planned_days=days))
        row = current(db)
        assert row is not None
        db.log_event("INFO", "experiment", f"experiment '{row['name']}' runs for {days} days, "
                     f"until {ends_at(row):%Y-%m-%d %H:%M} UTC")
    record_code_version(db, env)
    return row


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)   # SQLite returns naive UTC


def ends_at(exp: dict | None) -> datetime | None:
    """When the experiment stops opening bets; None for one with no planned end."""
    if not exp or not exp.get("planned_days"):
        return None
    return _utc(exp["started_at"]) + timedelta(days=exp["planned_days"])


def is_open(exp: dict | None, now: datetime) -> bool:
    end = ends_at(exp)
    return end is None or _utc(now) < end


def progress(db: Database, exp: dict | None, now: datetime) -> dict:
    """Where the experiment stands: running (day N of planned_days), ended (no
    new bets, some still open) or complete (ended, every bet settled)."""
    if not exp:
        return {"state": "none"}
    end = ends_at(exp)
    day = (_utc(now) - _utc(exp["started_at"])).days + 1
    open_bets = db.agg(select(func.count().label("n")).select_from(paper_bets)
                       .where(paper_bets.c.status == "OPEN"))["n"]
    state = "running" if end is None or _utc(now) < end else ("ended" if open_bets else "complete")
    return {"state": state, "day": min(day, exp["planned_days"]) if end else day,
            "planned_days": exp.get("planned_days"), "ends_at": end and end.isoformat(), "open_bets": open_bets,
            "ended_at": db.get_state("experiment_ended_at"), "completed_at": db.get_state("experiment_completed_at")}


def check_end(db: Database, exp: dict | None, now: datetime) -> dict:
    """Log the end of the experiment, and its completion once every bet has
    settled, each once. Run every cycle, after settlement."""
    p = progress(db, exp, now)
    if exp is None:
        return p
    if p["state"] in ("ended", "complete") and not p["ended_at"]:
        db.set_state("experiment_ended_at", now.isoformat())
        db.log_event("INFO", "experiment", f"EXPERIMENT_ENDED: '{exp['name']}' reached its {exp['planned_days']} "
                     f"days; no new bets from now on, {p['open_bets']} open bets still settle",
                     code="EXPERIMENT_ENDED", details={"ends_at": p["ends_at"], "open_bets": p["open_bets"]})
    if p["state"] == "complete" and not p["completed_at"]:
        db.set_state("experiment_completed_at", now.isoformat())
        db.log_event("INFO", "experiment", f"EXPERIMENT_COMPLETE: every bet of '{exp['name']}' has settled",
                     code="EXPERIMENT_COMPLETE")
    return progress(db, exp, now)
