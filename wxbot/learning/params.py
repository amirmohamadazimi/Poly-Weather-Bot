"""Versioned station bias/spread parameters (param sets).

The production model centres its distribution on the multi-model forecast
minus a bias and spreads it by an error standard deviation, both fitted per
station, temperature kind and lead time (calibration_params). Every fit of
those numbers is a param set with a version, and exactly one set is in
production at a time. Every production prediction records the version it was
priced with (predictions.params_version), so any result can be traced to the
numbers behind it, and an old set is never edited or deleted.

Statuses: production (in use); previous (the set the production one replaced,
kept so the system can roll back); retired (an older previous); rolled_back
(deployed, then reverted because it did worse than the set before it);
rejected (fitted by retraining and not deployed: not approved, or approved
but beaten by another candidate); candidate (fitted by `backtest` while a
production set existed: stored, never used).
"""
from __future__ import annotations

import statistics
from datetime import date, datetime

from sqlalchemy import desc, or_, select, update

from wxbot.db import Database, calibration_params, param_sets
from wxbot.model.base import Calibration
from wxbot.model.normal import default_calibration

KINDS = ("high", "low")


def get(db: Database, *, status: str | None = None, version: str | None = None) -> dict | None:
    ps = param_sets.c
    query = select(param_sets).order_by(desc(ps.id)).limit(1)
    if status:
        query = query.where(ps.status == status)
    if version:
        query = query.where(ps.version == version)
    return db.one(query)


def production(db: Database) -> dict | None:
    return get(db, status="production")


def legacy(db: Database) -> dict | None:
    return db.one(select(param_sets).where(param_sets.c.legacy.is_(True)).limit(1))


def history(db: Database, limit: int = 50) -> list[dict]:
    return db.rows(select(param_sets).order_by(desc(param_sets.c.id)).limit(limit))


def version_match(column, ps: dict | None):
    """SQL condition on a params_version column: rows made under param set `ps`
    (None: rows made with no set, i.e. the default spreads). A legacy set also
    owns the rows stored before versions were recorded."""
    if ps is None:
        return column.is_(None)
    return or_(column == ps["version"], column.is_(None)) if ps["legacy"] else column == ps["version"]


class Params:
    """One param set's rows, looked up as the live model uses them: the newest
    row for the station, kind and lead (lead 0 uses lead 1's), and the default
    spread for that lead when there is none or it rests on too few days."""

    def __init__(self, ps: dict | None, rows: list[dict], cfg):
        self.ps = ps
        self.version = ps["version"] if ps else None
        self.default_sigma = list(cfg.model.default_sigma_c)
        self.min_samples = int(cfg.model.min_calibration_samples)
        self.rows: dict[tuple, dict] = {}
        for r in sorted(rows, key=lambda r: r.get("id") or 0):
            self.rows[(r["station"], r["kind"], r["lead_days"])] = r

    def calibration(self, station: str, kind: str, lead_days: int) -> Calibration:
        row = self.rows.get((station, kind, max(lead_days, 1)))
        if row and row["n"] >= self.min_samples:
            return Calibration(bias_c=row["bias_c"], sigma_c=row["sigma_c"], n=row["n"], source="backtest")
        return default_calibration(self.default_sigma, lead_days)


def load(db: Database, cfg, ps: dict | None) -> Params:
    if ps is None:
        return Params(None, [], cfg)
    cp = calibration_params.c
    return Params(ps, db.rows(select(calibration_params).where(cp.param_set_id == ps["id"])), cfg)


def fit(errors: list[float]) -> tuple[float, float]:
    """bias = mean(forecast - observed); sigma = their standard deviation."""
    return statistics.fmean(errors), statistics.pstdev(errors) if len(errors) > 1 else 0.0


def fit_rows(forecasts: dict, observations: dict, leads, start: date, end: date, min_models: int,
             min_samples: int) -> list[dict]:
    """bias/sigma per kind and lead from what each model forecast N days ahead
    (forecasts[lead][kind][day] = {model: value_c}) against the observed value
    (observations[kind][day] = (value_c, n_reports)), on days start..end only.
    Rows resting on fewer than min_samples days are left out."""
    out = []
    for lead in leads:
        for kind in KINDS:
            obs = observations.get(kind, {})
            errors = [statistics.fmean(v.values()) - obs[d][0]
                      for d, v in sorted(forecasts.get(lead, {}).get(kind, {}).items())
                      if start.isoformat() <= d <= end.isoformat() and d in obs and len(v) >= min_models]
            if len(errors) >= min_samples:
                bias, sigma = fit(errors)
                out.append({"kind": kind, "lead_days": lead, "bias_c": bias, "sigma_c": sigma, "n": len(errors),
                            "window_start": start.isoformat(), "window_end": end.isoformat()})
    return out


def store(db: Database, *, version: str, model_version: str, origin: str, status: str, rows: list[dict],
          now: datetime, backtest_run_id: int | None = None, **fields) -> int:
    """Insert a param set and its rows (rows carry station, kind, lead_days,
    bias_c, sigma_c, n, window_start, window_end)."""
    keep = ("station", "kind", "lead_days", "bias_c", "sigma_c", "n", "window_start", "window_end")
    with db.engine.begin() as conn:
        set_id = conn.execute(param_sets.insert().values(
            version=version, model_version=model_version, created_at=now, origin=origin, status=status,
            n_rows=len(rows), legacy=False, **fields)).inserted_primary_key[0]
        if rows:
            conn.execute(calibration_params.insert(), [
                {**{k: r[k] for k in keep}, "fitted_at": now, "param_set_id": set_id,
                 "backtest_run_id": backtest_run_id} for r in rows])
    return set_id


def deploy(db: Database, set_id: int, now: datetime) -> dict | None:
    """Make set `set_id` production. The production set becomes previous (kept
    for a rollback) and the old previous is retired. Returns the replaced set."""
    ps = param_sets.c
    old = production(db)
    with db.engine.begin() as conn:
        conn.execute(update(param_sets).where(ps.status == "previous").values(status="retired"))
        if old:
            conn.execute(update(param_sets).where(ps.id == old["id"]).values(status="previous", retired_at=now))
        conn.execute(update(param_sets).where(ps.id == set_id).values(
            status="production", deployed_at=now, replaces=old["version"] if old else None))
    return old


def rollback(db: Database, now: datetime, reason: str) -> tuple[dict, dict] | None:
    """Put the previous set back into production; the current one becomes
    rolled_back. Returns (reverted, reinstated), or None with no previous set."""
    ps = param_sets.c
    current, prev = production(db), get(db, status="previous")
    if current is None or prev is None:
        return None
    with db.engine.begin() as conn:
        conn.execute(update(param_sets).where(ps.id == current["id"]).values(
            status="rolled_back", retired_at=now,
            reason=(current["reason"] or "") + f" | rolled back {now:%Y-%m-%d %H:%M}Z: {reason}"))
        conn.execute(update(param_sets).where(ps.id == prev["id"]).values(status="production", deployed_at=now))
    return current, prev
