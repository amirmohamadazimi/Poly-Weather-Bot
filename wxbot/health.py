"""System health for the dashboard: is each data source working, is the
database reachable, which model and calibrator are in use, and when they were
last refitted. Reads the database only."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select

from wxbot.db import (
    Database, backtest_runs, bankroll_snapshots, calibration_params, market_resolutions, markets, model_versions,
    paper_bets, predictions, signals, system_events,
)
from wxbot.evaluation.metrics import latest_calibrators
from wxbot.experiment import current

# name, bot_state key of its last success, components whose warnings and errors
# are its failures, and the config key of how often it is fetched
SOURCES = [
    ("Polymarket markets", "last_polymarket_update", ("markets", "settlement"), "cycle"),
    ("Weather forecasts (Open-Meteo)", "last_weather_update", ("forecasts",), "cycle"),
    ("Station observations (METAR)", "last_observation_update", ("observations", "history"), "observations"),
]
STALE_INTERVALS = 3   # a source is stale after missing this many of its fetches
COUNTED_TABLES = {"markets": markets, "predictions": predictions, "signals": signals, "paper_bets": paper_bets,
                  "market_resolutions": market_resolutions, "system_events": system_events}


def as_utc(value) -> datetime | None:
    """bot_state holds ISO strings; SQLite returns naive datetimes, which are UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def source_status(db: Database, cfg, now: datetime) -> list[dict]:
    every = {"cycle": timedelta(minutes=float(cfg.schedule.cycle_minutes)),
             "observations": timedelta(hours=float(cfg.schedule.get("observation_hours", 6)))}
    ev = system_events.c
    out = []
    for name, key, components, interval in SOURCES:
        last_ok = as_utc(db.get_state(key))
        problem = db.one(select(ev.ts, ev.level, ev.component, ev.message)
                         .where(ev.component.in_(components), ev.level.in_(["WARNING", "ERROR"]))
                         .order_by(desc(ev.id)).limit(1))
        problem_at = as_utc(problem["ts"]) if problem else None
        stale_after = every[interval] * STALE_INTERVALS
        if last_ok is None:
            status = "failing" if problem else "no data yet"
        elif problem_at and problem_at > last_ok:
            status = "failing"
        elif now - last_ok > stale_after:
            status = "stale"
        else:
            status = "ok"
        out.append({"source": name, "status": status, "last_success": last_ok,
                    "stale_after_hours": round(stale_after.total_seconds() / 3600, 1),
                    "last_problem": problem and {**problem, "ts": problem_at}})
    return out


def database_status(db: Database) -> dict:
    out: dict = {"dialect": db.engine.dialect.name}
    try:
        out["rows"] = {name: db.one(select(func.count().label("n")).select_from(t))["n"]
                       for name, t in COUNTED_TABLES.items()}
        last = db.one(select(func.max(bankroll_snapshots.c.ts).label("t")))
        out["last_write"] = as_utc(last["t"]) if last else None
        out["ok"] = True
    except Exception as exc:  # report it rather than break the page
        out.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    path = db.engine.url.database if out["dialect"] == "sqlite" else None
    if path and os.path.exists(path):
        size = sum(os.path.getsize(p) for p in (path, path + "-wal") if os.path.exists(p))
        out.update(path=path, size_mb=round(size / 1e6, 1))
    return out


def model_status(db: Database) -> dict:
    mv = model_versions.c
    models = db.rows(select(mv.version, mv.name, mv.role, mv.calibration_version, mv.feature_set,
                            mv.role_changed_at).order_by(mv.id))
    cals = latest_calibrators(db)
    active = next((c for c in cals if c["selected"]), None)
    bias = db.one(select(func.max(calibration_params.c.fitted_at).label("t")))
    backtest = db.one(select(func.max(backtest_runs.c.finished_at).label("t")))
    return {
        "production": next((m for m in models if m["role"] == "production"), None),
        "shadows": [m for m in models if m["role"] == "shadow"],
        "calibrator": ({"version": active["version"], "method": active["method"], "fitted_at": active["fitted_at"]}
                       if active else {"version": "identity", "method": "none: raw probabilities"}),
        "last_calibrator_fit": as_utc(db.get_state("last_calibration_fit")),
        "last_calibrator_result": [{k: c[k] for k in ("method", "approved", "selected", "reason")} for c in cals],
        "last_bias_fit": as_utc(bias["t"]) if bias else None,
        "last_backtest": as_utc(backtest["t"]) if backtest else None,
    }


def system_health(db: Database, cfg, now: datetime) -> dict:
    sources = source_status(db, cfg, now)
    exp = current(db)
    successes = [s["last_success"] for s in sources if s["last_success"]]
    return {
        "sources": sources, "last_data_update": max(successes) if successes else None,
        "last_market_scan": as_utc(db.get_state("last_polymarket_update")),
        "last_prediction": as_utc(db.get_state("last_prediction_time")),
        "database": database_status(db), "model": model_status(db),
        "experiment": exp and {**{k: exp[k] for k in ("name", "initial_bankroll", "started_at", "git_ref")},
                               "code_ref": db.get_state("code_ref")},
    }
