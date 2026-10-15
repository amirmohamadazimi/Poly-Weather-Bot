"""Daily refresh of the v2 model's learned biases and errors (wxbot/model/weighted.py).

Once every refresh_hours, for every enabled station: what each weather model
forecast 1 to 3 days ahead over the last `days` days (Open-Meteo Previous
Runs) and the station's observed highs and lows (METARs) are walked through in
date order (weighted.walk), and the resulting per-model bias and error and the
combined forecast's error are stored in model_stats, one row per station, kind
and lead. Rows are never updated or deleted, so every prediction can be traced
to the stats it used (its inputs carry stats_last_day). A station whose data
cannot be fetched keeps its previous rows and is tried again on its own after
retry_hours, as is the whole refresh when it stored nothing. The engine loads
the newest row of each station, kind and lead before every cycle's predictions.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from wxbot.data.stations import STATIONS
from wxbot.db import Database, model_stats
from wxbot.model.weighted import Stats, walk

LEADS = (1, 2, 3)


def due(db: Database, now: datetime) -> bool:
    nxt = db.get_state("next_model_stats_at")
    return nxt is None or now >= datetime.fromisoformat(nxt)


def pending_retry(db: Database) -> dict:
    """{"at": iso time, "stations": [codes]} of the stations that failed in the last refresh, or {}."""
    raw = db.get_state("model_stats_retry")
    return json.loads(raw) if raw else {}


def refresh(db: Database, cfg, history, observer, model_version: str, now: datetime, force: bool = False) -> dict:
    """Fit and store every enabled station's stats when due, or retry the
    stations that failed last time; see the module docstring."""
    c = cfg.model_stats
    retry_after = timedelta(hours=float(c.retry_hours))
    stations = [s for _, s in sorted(STATIONS.items()) if s.enabled]
    full = force or due(db, now)
    if not full:
        retry = pending_retry(db)
        if not retry or now < datetime.fromisoformat(retry["at"]):
            return {"skipped": "not due", "next": db.get_state("next_model_stats_at")}
        stations = [s for s in stations if s.code in set(retry["stations"])]
    if history is None or observer is None:
        return {"skipped": "no source of past forecasts and observations"}
    days, pause = int(c.days), float(c.get("pause_seconds", 0))
    min_reports = int(cfg.validation.min_obs_reports)
    if full:   # should anything below crash, try again after retry_hours
        db.set_state("next_model_stats_at", (now + retry_after).isoformat())
    stored, failed = 0, {}
    for i, st in enumerate(stations):
        end = now.astimezone(ZoneInfo(st.tz)).date() - timedelta(days=1)   # the last whole local day
        start = end - timedelta(days=days - 1)
        if i and pause:
            time.sleep(pause)      # spread the requests out (Open-Meteo's per-minute limit)
        try:
            fc = history.fetch(st, start, end, list(LEADS))
            obs = observer.fetch(st, start, end)
        except Exception as exc:  # one station's failure only leaves its previous rows in place
            failed[st.code] = f"{type(exc).__name__}: {exc}"
            continue
        rows = []
        for kind in ("high", "low"):
            observed = {d: v for d, (v, n) in obs.get(kind, {}).items() if n is None or n >= min_reports}
            for lead in LEADS:
                by_day = fc.get(lead, {}).get(kind, {})
                stats, _ = walk([(d, by_day[d], observed.get(d)) for d in sorted(by_day)])
                rows.append(dict(fitted_at=now, model_version=model_version, station=st.code, kind=kind,
                                 lead_days=lead, window_start=start.isoformat(), window_end=end.isoformat(),
                                 n_days=stats.n_days, last_day=stats.last_day, sd_c=stats.sd,
                                 stats=stats.as_dict()))
        with db.engine.begin() as conn:
            conn.execute(model_stats.insert(), rows)
        stored += len(rows)
    result = {"at": now.isoformat(), "retry": not full, "stations": len(stations) - len(failed), "rows": stored,
              "failed": failed, "days": days}
    db.set_state("last_model_stats", result)
    if full and stored:
        db.set_state("next_model_stats_at", (now + timedelta(hours=float(c.refresh_hours))).isoformat())
    # a full refresh that stored nothing is itself retried after retry_hours (next_model_stats_at)
    db.set_state("model_stats_retry", {"at": (now + retry_after).isoformat(), "stations": sorted(failed)}
                 if failed and (stored or not full) else "")
    level = "WARNING" if failed else "INFO"
    db.log_event(level, "model_stats", f"{model_version}: biases and errors refitted for "
                 f"{result['stations']} stations on the last {days} days" + (" (retry)" if not full else "")
                 + (f"; {len(failed)} failed, tried again after {c.retry_hours} h" if failed else ""), details=result)
    return result


def load(db: Database) -> dict[tuple[str, str, int], Stats]:
    """The newest stats of every station, kind and lead."""
    ms = model_stats.c
    newest = select(func.max(ms.id)).group_by(ms.station, ms.kind, ms.lead_days)
    return {(r["station"], r["kind"], r["lead_days"]): Stats.from_dict(r["stats"])
            for r in db.rows(select(ms.station, ms.kind, ms.lead_days, ms.stats).where(ms.id.in_(newest)))}
