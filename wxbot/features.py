"""Feature set: the numbers every model sees for one station, day and kind.

Built once per (station, local day, kind, forecast) in a cycle and stored with
the production prediction, so any prediction can be reproduced and every model
is compared on exactly the same inputs. Bump FEATURE_SET whenever a feature is
added, removed or computed differently.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select

from wxbot.db import Database, weather_observations

FEATURE_SET = "fs-v1"


@dataclass
class Features:
    values: dict                                             # stored in predictions.inputs["features"]
    climatology_c: list[float] = field(default_factory=list)  # observed values in the window (not stored)


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(x, nd)


def _same_day(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=year, day=28)


def days_apart(d: date, target: date) -> int:
    """Calendar distance ignoring the year: 30 Dec and 2 Jan are 3 days apart."""
    return min(abs((_same_day(d, y) - target).days) for y in (target.year - 1, target.year, target.year + 1))


def observed_history(db: Database, station: str, kind: str, known_at: datetime) -> dict[str, float]:
    """Observed daily high (or low) per local day, using only rows fetched by
    `known_at`; a later fetch of the same day replaces an earlier one."""
    wo = weather_observations.c
    rows = db.rows(select(wo.local_date, wo.value_c)
                   .where(wo.station == station, wo.kind == kind, wo.fetched_at <= known_at).order_by(wo.id))
    return {r["local_date"]: r["value_c"] for r in rows}


def climatology_window(history: dict[str, float], local_date: str, window_days: int) -> list[float]:
    """Values observed before `local_date` within `window_days` of its calendar date, any year."""
    target = date.fromisoformat(local_date)
    return [v for d, v in sorted(history.items())
            if d < local_date and days_apart(date.fromisoformat(d), target) <= window_days]


def build_features(*, station: str, kind: str, local_date: str, values_c: dict[str, float], lead_days: int,
                   issue_time: datetime | None, day_end: datetime, climatology_c: list[float]) -> Features:
    vals = list(values_c.values())
    mean = statistics.fmean(vals)
    clim_mean = statistics.fmean(climatology_c) if climatology_c else None
    d = date.fromisoformat(local_date)
    return Features(values={
        "feature_set": FEATURE_SET, "station": station, "kind": kind,
        "month": d.month, "day_of_year": d.timetuple().tm_yday, "lead_days": lead_days,
        # hours from the oldest model run used to the end of the target day
        "horizon_hours": _r((day_end - issue_time).total_seconds() / 3600, 1) if issue_time else None,
        "n_models": len(vals), "forecast_mean_c": _r(mean),
        "forecast_spread_c": _r(statistics.pstdev(vals) if len(vals) > 1 else 0.0),
        "forecast_min_c": _r(min(vals)), "forecast_max_c": _r(max(vals)),
        "clim_n": len(climatology_c), "clim_mean_c": _r(clim_mean),
        "clim_std_c": _r(statistics.pstdev(climatology_c)) if len(climatology_c) > 1 else None,
        "anomaly_c": _r(mean - clim_mean) if clim_mean is not None else None,
    }, climatology_c=climatology_c)
