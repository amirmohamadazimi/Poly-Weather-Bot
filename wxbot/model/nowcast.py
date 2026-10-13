"""Same-day model ("nowcast"), run as a forward test.

On a market's own day part of the answer is already known: the station's
reports so far give the high (or low) up to now, m. What is left is the
extreme of the hours still to come, R, and the day's final value is
V = max(m, R) for a high (min(m, R) for a low). R is taken as normal,

    R ~ N(frem + bias[station, kind] + alpha[kind, band] + beta[kind, band] * anom, sigma[kind, band]),

where frem is the forecast's extreme over the hours left, anom is the newest
report minus the forecast for its hour (a day running warm tends to stay
warm), and band is the hours left until the end of the local day
(HOUR_BANDS). P(bucket) = P(lo - 0.5 <= V < hi + 0.5) in the market's unit, as
for the production model, so a bucket below the high so far (above the low so
far) gets the floor.

The parameters (nowcast_params.json) were fitted by research/fit_nowcast.py on
a year of hourly station reports and the forecast issued a day ahead. In the
bot the forecast is the newest one, from the cycle's forecast snapshot.
Backtested on Sep 27 to Oct 12 2026 against live order books, the market
price was the better forecast at every hour of the day (docs/experiments.md),
so the model prices every same-day market as a shadow model and can bet only
through its own market anchor (wxbot/calibration/anchor.py), which approves
it only after it has beaten the market price on resolved markets.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from wxbot.data.polymarket import Bucket
from wxbot.model.base import Prediction

PARAMS_FILE = Path(__file__).with_name("nowcast_params.json")
FEATURE_SET = "same-day-v1"   # predictions.feature_set: station reports so far + hourly forecast
HOUR_BANDS = [0, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 24.01]   # hours left until the end of the local day
MATCH = timedelta(hours=1)   # the forecast hour compared with the newest report must be this close to it


def hour_band(hours_left: float) -> int:
    return max(i for i, b in enumerate(HOUR_BANDS[:-1]) if hours_left >= b)


def day_bounds(tz: str, local_date: str) -> tuple[datetime, datetime]:
    """Start and end of a station's local day, in UTC."""
    z, d = ZoneInfo(tz), date.fromisoformat(local_date)
    return (datetime.combine(d, datetime.min.time(), z).astimezone(UTC),
            datetime.combine(d + timedelta(days=1), datetime.min.time(), z).astimezone(UTC))


def hourly_series(hourly: dict | None, tz: str, min_models: int) -> list[tuple[datetime, float]]:
    """A forecast snapshot's hourly_c -> [(UTC hour, mean of the models)];
    hours with fewer than `min_models` values are left out."""
    if not hourly:
        return []
    z = ZoneInfo(tz)
    series = list((hourly.get("values") or {}).values())
    out = []
    for i, t in enumerate(hourly.get("time") or []):
        vals = [s[i] for s in series if i < len(s) and s[i] is not None]
        if len(vals) >= min_models:
            out.append((datetime.fromisoformat(t).replace(tzinfo=z).astimezone(UTC), sum(vals) / len(vals)))
    return sorted(out)


def day_state(reports: list[tuple[datetime, float]], forecast: list[tuple[datetime, float]], start: datetime,
              end: datetime, cut: datetime, kind: str) -> dict | None:
    """The day as known at `cut`. `reports` and `forecast` are sorted [(UTC
    time, temp_c)]. m is the extreme of the reports from `start` to `cut`,
    frem the forecast's extreme after `cut` until `end` (its value at the
    newest report when no hour is left), anom the newest report minus the
    forecast for its hour. None without a report yet or a forecast hour
    near the newest one."""
    rt = [t for t, _ in reports]
    lo, hi = bisect.bisect_left(rt, start), bisect.bisect_right(rt, cut)
    if hi <= lo:
        return None
    last_t, last_v = reports[hi - 1]
    ft = [t for t, _ in forecast]
    j = bisect.bisect_left(ft, last_t - MATCH / 2)
    if j >= len(ft) or abs(ft[j] - last_t) > MATCH:
        return None
    f_now = forecast[j][1]
    rest = [v for _, v in forecast[bisect.bisect_right(ft, cut):bisect.bisect_right(ft, end)]]
    pick = max if kind == "high" else min
    return {"m": pick(v for _, v in reports[lo:hi]), "n_reports": hi - lo, "last_report": last_t,
            "last_report_c": last_v, "frem": pick(rest) if rest else f_now, "anom": last_v - f_now}


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def final_probability(kind: str, m: float, mu: float, sigma: float, lo_c: float | None, hi_c: float | None) -> float:
    """P(lo_c <= V < hi_c), V = max(m, R) for a high and min(m, R) for a low,
    R ~ N(mu, sigma). A None bound is open."""
    if kind == "high":
        def below(x: float) -> float:     # P(V < x)
            return 0.0 if x <= m else _ncdf((x - mu) / sigma)
        return max(0.0, (1.0 if hi_c is None else below(hi_c)) - (0.0 if lo_c is None else below(lo_c)))

    def at_least(x: float) -> float:      # P(V >= x)
        return 0.0 if x > m else 1 - _ncdf((x - mu) / sigma)
    return max(0.0, (1.0 if lo_c is None else at_least(lo_c)) - (0.0 if hi_c is None else at_least(hi_c)))


def bounds_c(bucket: Bucket) -> tuple[float | None, float | None]:
    """Whole-degree bucket [lo, hi] in its unit -> continuous bounds [lo - 0.5, hi + 0.5) in C."""
    def conv(x: float) -> float:
        return (x - 32.0) * 5.0 / 9.0 if bucket.unit == "F" else x
    lo = None if bucket.lo is None else conv(bucket.lo - 0.5)
    return lo, (None if bucket.hi is None else conv(bucket.hi + 0.5))


def load_params(path: Path = PARAMS_FILE) -> dict:
    return json.loads(path.read_text())


class Nowcast:
    name = "nowcast"
    calibration_version = "none"
    feature_set = FEATURE_SET

    def __init__(self, fitted: dict, prob_floor: float = 0.001, prob_ceiling: float = 0.999,
                 max_report_age_minutes: float = 120, min_models: int = 2):
        self.fitted = fitted
        self.version = fitted["version"]
        self.prob_floor, self.prob_ceiling = prob_floor, prob_ceiling
        self.max_report_age = timedelta(minutes=max_report_age_minutes)
        self.min_models = min_models
        digest = hashlib.sha256(json.dumps(fitted, sort_keys=True).encode()).hexdigest()[:16]
        self.params = {"params_sha256": digest, "train_from": fitted["train_from"], "train_to": fitted["train_to"],
                       "max_report_age_minutes": max_report_age_minutes, "min_models": min_models,
                       "prob_floor": prob_floor, "prob_ceiling": prob_ceiling}

    def predict(self, bucket: Bucket, kind: str, station: str, local_date: str, tz: str,
                reports: list[tuple[datetime, float]], hourly: dict | None, now: datetime) -> Prediction | None:
        """None outside the market's day, without a report in the last
        max_report_age_minutes, or without the hourly forecast."""
        start, end = day_bounds(tz, local_date)
        hours_left = (end - now).total_seconds() / 3600
        if not start < now < end:
            return None
        s = day_state(reports, hourly_series(hourly, tz, self.min_models), start, end, now, kind)
        if s is None or now - s["last_report"] > self.max_report_age:
            return None
        band = hour_band(hours_left)
        fit = self.fitted["bands"][kind][band]
        known = station in self.fitted["station_bias"]
        bias = self.fitted["station_bias"].get(station, {}).get(kind, 0.0)
        mu = s["frem"] + bias + fit["alpha"] + fit["beta"] * s["anom"]
        lo_c, hi_c = bounds_c(bucket)
        p = final_probability(kind, s["m"], mu, fit["sigma"], lo_c, hi_c)
        p = min(self.prob_ceiling, max(self.prob_floor, p))
        return Prediction(p_yes=p, mu_c=mu, sigma_c=fit["sigma"], model_version=self.version, inputs={
            "so_far_c": round(s["m"], 3), "n_reports": s["n_reports"], "last_report": s["last_report"].isoformat(),
            "last_report_c": round(s["last_report_c"], 3), "forecast_rest_c": round(s["frem"], 3),
            "anomaly_c": round(s["anom"], 3), "hours_left": round(hours_left, 2), "hour_band": band,
            "station_bias_c": round(bias, 3), "station_known": known, "alpha": fit["alpha"], "beta": fit["beta"],
            "bucket": {"lo": bucket.lo, "hi": bucket.hi, "unit": bucket.unit}})
