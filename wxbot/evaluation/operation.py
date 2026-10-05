"""How the experiment ran (spec section 17: it should "operate continuously and
autonomously"): the cycles it completed, the gaps between them, the finished
days with none, and the cycle steps that failed. A cycle is counted by the
bankroll snapshot it writes when it finishes."""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from wxbot.db import Database, bankroll_snapshots, system_events
from wxbot.experiment import ends_at


def _day(t: datetime) -> date:
    return t.date()   # stored as UTC


def operation(db: Database, exp: dict | None, now: datetime) -> dict:
    bs, ev = bankroll_snapshots.c, system_events.c
    since = exp["started_at"] if exp else None
    q = select(bs.ts).where(bs.reason == "cycle")
    errors = select(ev.component, func.count().label("n")).where(ev.level == "ERROR")
    if since is not None:
        q, errors = q.where(bs.ts >= since), errors.where(ev.ts >= since)
    times = [r["ts"].replace(tzinfo=None) for r in db.rows(q.order_by(bs.ts))]
    out: dict = {"cycles": len(times), "first": times[0] if times else None, "last": times[-1] if times else None,
                 "median_gap_hours": None, "longest_gap_hours": None, "longest_gap": None,
                 "days": 0, "days_without_cycle": [],
                 "step_errors": {r["component"]: r["n"] for r in db.rows(errors.group_by(ev.component))}}
    if not times:
        return out
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
    if gaps:
        i = max(range(len(gaps)), key=gaps.__getitem__)
        out.update(median_gap_hours=round(statistics.median(gaps), 2), longest_gap_hours=round(gaps[i], 2),
                   longest_gap=[times[i].isoformat(), times[i + 1].isoformat()])
    end = ends_at(exp)
    # finished days only: today (or the end day) is still under way
    last_day = _day(min(now.replace(tzinfo=None), end.replace(tzinfo=None)) if end else now.replace(tzinfo=None))
    last_day -= timedelta(days=1)
    first_day = _day(since.replace(tzinfo=None)) if since is not None else _day(times[0])
    days = [first_day + timedelta(days=i) for i in range(max(0, (last_day - first_day).days + 1))]
    ran = {_day(t) for t in times}
    out.update(days=len(days), days_without_cycle=[d.isoformat() for d in days if d not in ran])
    return out
