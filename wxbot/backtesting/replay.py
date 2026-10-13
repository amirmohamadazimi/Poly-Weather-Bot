"""Replay stored historical markets at fixed decision times, using only what
was known at each one (no look-ahead).

Decision time. Lead N uses Open-Meteo's previous_dayN forecast. Its value for
every hour comes from a model run started at least N x 24 hours before that
hour; a run is assumed downloadable `forecast_delay_hours` after it starts. The
last hour of local day D is the binding one, so the day's high or low is surely
available at

    decision time = end of local day D - (24 N - forecast_delay_hours) hours

and that is when the market is priced. At that instant each row gets:

* market: the last YES price at or before it. A market not listed yet, or
  with no price point yet, is skipped and counted.
* model: the production model, with the station's bias and error spread for
  that lead fitted on days that ended before it (at most `train_days` back,
  observations through D - N - 1). With fewer than
  model.min_calibration_samples such days it uses the default spread and no
  bias, as the live bot does without a fitted calibration.
* raw forecast: the multi-model mean with the default spread, no bias.
* climatology: observed values from the same weeks of earlier years, through
  D - N - 1.
* calibrated: the model's probability through the calibrator the live
  approval rule (wxbot/calibration/fit.py) selects from markets whose result
  was known by the start of that refit period.
"""
from __future__ import annotations

import bisect
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from wxbot.calibration.fit import day_end, identity, judge, selected
from wxbot.data.polymarket import Bucket
from wxbot.db import (
    Database, historical_forecasts, market_price_history, market_resolutions, markets, weather_observations,
)
from wxbot.features import Features, climatology_window
from wxbot.model.base import Calibration
from wxbot.model.baselines import Climatology, RawForecast
from wxbot.model.normal import default_calibration
from wxbot.model.registry import production_model

RESULT_FALLBACK = timedelta(hours=48)   # result assumed known this long after the day ends without a close time

SKIPS = {
    "not_listed": "market not listed yet at the decision time",
    "no_forecast": "no stored forecast for this lead",
    "few_models": "fewer forecast models than weather.min_models",
    "no_price": "no price at or before the decision time",
}


def utc(t) -> datetime | None:
    if t is None:
        return None
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def lead_hours(lead: int, delay_hours: float) -> float:
    return 24.0 * lead - delay_hours


def decision_time(station: str, local_date: str, lead: int, delay_hours: float) -> datetime | None:
    end = day_end(station, local_date)
    return None if end is None else end - timedelta(hours=lead_hours(lead, delay_hours))


def price_at(series: tuple[list, list] | None, t: datetime) -> tuple[datetime, float] | None:
    """The last point at or before t of a (times, prices) series."""
    if not series:
        return None
    i = bisect.bisect_right(series[0], t)
    return None if i == 0 else (series[0][i - 1], series[1][i - 1])


def load_markets(db: Database, start: date, end: date, stations: list[str] | None = None) -> list[dict]:
    mk, r = markets.c, market_resolutions.c
    q = (select(mk.id, mk.event_id, mk.city, mk.station, mk.kind, mk.local_date, mk.unit, mk.bucket_lo, mk.bucket_hi,
                mk.bucket_label, mk.pm_created_at, mk.closed_time, r.outcome)
         .join(market_resolutions, r.market_id == mk.id)
         .where(mk.tradeable.is_(True), mk.local_date >= start.isoformat(), mk.local_date <= end.isoformat()))
    if stations:
        q = q.where(mk.station.in_(stations))
    return db.rows(q.order_by(mk.local_date, mk.station, mk.kind, mk.id))


def load_prices(db: Database, market_ids: list[str]) -> dict[str, tuple[list, list]]:
    ph = market_price_history.c
    out: dict[str, tuple[list, list]] = {}
    ids = list(market_ids)
    for i in range(0, len(ids), 900):  # SQLite caps the number of bound parameters
        for row in db.rows(select(ph.market_id, ph.t, ph.price).where(ph.market_id.in_(ids[i:i + 900]))
                           .order_by(ph.market_id, ph.t)):
            times, prices = out.setdefault(row["market_id"], ([], []))
            times.append(utc(row["t"]))
            prices.append(row["price"])
    return out


def load_forecasts(db: Database, stations: set[str]) -> dict[tuple, dict[str, dict[str, float]]]:
    """(station, kind, lead) -> {local_date: {model: value_c}}; a later fetch replaces an earlier one."""
    hf = historical_forecasts.c
    out: dict[tuple, dict] = defaultdict(lambda: defaultdict(dict))
    for r in db.rows(select(hf.station, hf.kind, hf.lead_days, hf.local_date, hf.model, hf.value_c)
                     .where(hf.station.in_(stations)).order_by(hf.id)):
        out[(r["station"], r["kind"], r["lead_days"])][r["local_date"]][r["model"]] = r["value_c"]
    return out


def load_observations(db: Database, stations: set[str]) -> dict[tuple, dict[str, float]]:
    """(station, kind) -> {local_date: value_c}; a later fetch replaces an earlier one."""
    wo = weather_observations.c
    out: dict[tuple, dict] = defaultdict(dict)
    for r in db.rows(select(wo.station, wo.kind, wo.local_date, wo.value_c)
                     .where(wo.station.in_(stations)).order_by(wo.id)):
        out[(r["station"], r["kind"])][r["local_date"]] = r["value_c"]
    return out


class BiasFits:
    """Walk-forward station bias and error spread per (station, kind, lead):
    for day D only days through D - lead - 1 count, so every observation used
    ended before the decision time."""

    def __init__(self, cfg, forecasts: dict, observations: dict):
        self.cfg = cfg
        self.forecasts = forecasts
        self.observations = observations
        self.train_days = int(cfg.backtest.train_days)
        self.min_n = int(cfg.model.min_calibration_samples)
        self.min_models = int(cfg.weather.min_models)
        self._errors: dict[tuple, list[tuple[str, float]]] = {}
        self._cache: dict[tuple, tuple[Calibration, int]] = {}

    def errors(self, station: str, kind: str, lead: int) -> list[tuple[str, float]]:
        key = (station, kind, lead)
        if key not in self._errors:
            obs = self.observations.get((station, kind), {})
            self._errors[key] = sorted(
                (d, statistics.fmean(v.values()) - obs[d])
                for d, v in self.forecasts.get(key, {}).items() if d in obs and len(v) >= self.min_models)
        return self._errors[key]

    def get(self, station: str, kind: str, lead: int, local_date: str) -> tuple[Calibration, int]:
        key = (station, kind, lead, local_date)
        if key not in self._cache:
            last = date.fromisoformat(local_date) - timedelta(days=lead + 1)
            first = (last - timedelta(days=self.train_days - 1)).isoformat()
            known = [e for d, e in self.errors(station, kind, lead) if first <= d <= last.isoformat()]
            if len(known) >= self.min_n:
                cal = Calibration(bias_c=statistics.fmean(known), sigma_c=statistics.pstdev(known), n=len(known),
                                  source="walk-forward")
            else:
                cal = default_calibration(list(self.cfg.model.default_sigma_c), lead)
            self._cache[key] = (cal, len(known))
        return self._cache[key]


def replay(cfg, db: Database, start: date, end: date, stations: list[str] | None = None) -> dict:
    """-> {"rows": [one per market and lead], "skipped": {reason: n}, "calibration_rounds": [...]}"""
    b = cfg.backtest
    delay = float(b.forecast_delay_hours)
    leads = [int(x) for x in b.leads]
    mc = cfg.model
    model = production_model(cfg)
    window = int(mc.get("climatology_window_days", 7))
    raw = RawForecast(list(mc.default_sigma_c), mc.prob_floor, mc.prob_ceiling)
    clim = Climatology(window, int(mc.get("climatology_min_samples", 20)), mc.prob_floor, mc.prob_ceiling)

    mks = load_markets(db, start, end, stations)
    codes = {m["station"] for m in mks}
    prices = load_prices(db, [m["id"] for m in mks])
    forecasts = load_forecasts(db, codes)
    observations = load_observations(db, codes)
    fits = BiasFits(cfg, forecasts, observations)
    min_models = int(cfg.weather.min_models)
    history_cache: dict[tuple, list] = {}

    def climatology_samples(station: str, kind: str, local_date: str, lead: int) -> list[float]:
        last = (date.fromisoformat(local_date) - timedelta(days=lead + 1)).isoformat()
        key = (station, kind, local_date, lead)
        if key not in history_cache:
            known = {d: v for d, v in observations.get((station, kind), {}).items() if d <= last}
            history_cache[key] = climatology_window(known, local_date, window)
        return history_cache[key]

    rows, skipped = [], {k: 0 for k in SKIPS}
    for m in mks:
        end_t = day_end(m["station"], m["local_date"])
        if end_t is None:
            continue
        bucket = Bucket(m["bucket_lo"], m["bucket_hi"], m["unit"])
        # a result is never known before the day ends, whatever the close time says
        closed = utc(m["closed_time"])
        known_at = max(closed, end_t) if closed else end_t + RESULT_FALLBACK
        created = utc(m["pm_created_at"])
        for lead in leads:
            t = end_t - timedelta(hours=lead_hours(lead, delay))
            if created is not None and created > t:
                skipped["not_listed"] += 1
                continue
            values = forecasts.get((m["station"], m["kind"], lead), {}).get(m["local_date"])
            if not values:
                skipped["no_forecast"] += 1
                continue
            if len(values) < min_models:
                skipped["few_models"] += 1
                continue
            point = price_at(prices.get(m["id"]), t)
            if point is None:
                skipped["no_price"] += 1
                continue
            calib, bias_n = fits.get(m["station"], m["kind"], lead, m["local_date"])
            pred = model.predict(bucket, m["kind"], values, lead, calib)
            p_raw = raw.predict(bucket, m["kind"], values, lead, calib).p_yes
            c = clim.predict(bucket, m["kind"], values, lead, calib,
                             Features({}, climatology_samples(m["station"], m["kind"], m["local_date"], lead)))
            rows.append({
                "market_id": m["id"], "event_id": m["event_id"], "city": m["city"], "station": m["station"],
                "kind": m["kind"], "local_date": m["local_date"], "bucket_label": m["bucket_label"], "lead_days": lead,
                "lead_hours": lead_hours(lead, delay), "decision_time": t, "price_time": point[0],
                "market_prob": point[1], "p_climatology": c.p_yes if c else None, "p_raw_forecast": p_raw,
                "p_model": pred.p_yes, "p_calibrated": None, "calibrator_version": None, "n_models": len(values),
                "mu_c": pred.mu_c, "sigma_c": pred.sigma_c, "bias_c": calib.bias_c, "bias_n": bias_n,
                "outcome": 1 if m["outcome"] == "YES" else 0, "known_at": known_at,
            })
    rounds = walk_forward_calibration(rows, cfg, model.version)
    return {"rows": rows, "skipped": skipped, "calibration_rounds": rounds, "markets": len(mks)}


def walk_forward_calibration(rows: list[dict], cfg, model_version: str) -> list[dict]:
    """Set p_calibrated on every row, refitting every calibration.refit_hours
    (from midnight UTC before the first decision) on the markets whose result
    was known by then, with the live approval rule. Training uses one row per
    market, as the live fit does: the latest decision at least
    strategy.min_lead_hours before the end of the market's day."""
    if not rows:
        return []
    min_lead = float(cfg.strategy.min_lead_hours)
    latest: dict[str, dict] = {}
    for r in rows:
        if r["lead_hours"] >= min_lead and (r["market_id"] not in latest
                                            or r["decision_time"] > latest[r["market_id"]]["decision_time"]):
            latest[r["market_id"]] = r
    train = sorted(latest.values(), key=lambda r: r["known_at"])
    step = timedelta(hours=float(cfg.calibration.refit_hours))
    ordered = sorted(rows, key=lambda r: r["decision_time"])
    first = ordered[0]["decision_time"]
    t = first.replace(hour=0, minute=0, second=0, microsecond=0)
    rounds, cal, used, i = [], identity(), -1, 0
    while i < len(ordered):
        n_known = bisect.bisect_right([r["known_at"] for r in train], t)
        if n_known != used:  # new results since the last fit: refit (same data gives the same fit)
            used = n_known
            data = sorted((r["decision_time"], r["p_model"], r["outcome"]) for r in train[:n_known])
            judged = judge(data, cfg, model_version, t)
            cal = selected(judged, cfg)
            rounds.append({"fit_time": t, "n": n_known, "using": cal.version,
                           "methods": {j["method"]: {"approved": j["approved"], "reason": j["reason"]}
                                       for j in judged}})
        while i < len(ordered) and ordered[i]["decision_time"] < t + step:
            ordered[i]["p_calibrated"] = cal(ordered[i]["p_model"])
            ordered[i]["calibrator_version"] = cal.version
            i += 1
        t += step
    return rounds
