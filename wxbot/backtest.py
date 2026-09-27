"""Historical backtest of the forecast model (walk-forward, no look-ahead).

For every station and lead time it pairs the forecast each model actually
issued N days ahead (Open-Meteo Previous Runs) with the observed daily
high/low (METAR archive). It then:

1. Walks forward day by day. The bias/sigma used to price day D at lead L are
   fitted only on days whose observation was known when that forecast was
   issued (<= D - L - 1). Every whole-degree bucket is priced like a market
   bucket and scored against what happened: Brier, log loss, calibration, and
   the hit rate of >= 80% calls.
2. Fits bias/sigma on the full window and stores them in calibration_params,
   which the live model uses from then on.

Historical Polymarket prices are not replayed in v1, so this measures
forecast skill and calibration, not trading P/L; the paper-trading run
measures P/L under real prices.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, timedelta

from wxbot.data.polymarket import Bucket
from wxbot.data.stations import STATIONS, Station
from wxbot.db import Database, backtest_runs, calibration_params, utcnow
from wxbot.evaluation.metrics import brier, calibration_bins
from wxbot.model.normal import NormalMultiModel, c_to_unit

log = logging.getLogger("wxbot.backtest")
MIN_TRAIN = 14


def unit_for(station: Station) -> str:
    return "F" if station.code.startswith("K") else "C"


def fit(errors: list[float]) -> tuple[float, float]:
    bias = statistics.fmean(errors)
    sigma = statistics.pstdev(errors) if len(errors) > 1 else 0.0
    return bias, sigma


def walk_forward_fits(rows: list, errors: list[float], lead: int):
    """Yield (index, bias, sigma) fitted only on days whose observation was
    already known when day rows[index] was forecast `lead` days ahead."""
    for i, (d, _, _) in enumerate(rows):
        cutoff = d - timedelta(days=lead + 1)
        known = [errors[j] for j, (dj, _, _) in enumerate(rows) if dj <= cutoff]
        if len(known) >= MIN_TRAIN:
            yield (i, *fit(known))


def bucket_pairs(predictor: NormalMultiModel, values: dict, obs_c: float, unit: str, bias: float, sigma: float,
                 lead: int, kind: str) -> list[tuple[float, int]]:
    """Price a ladder of 1-degree buckets (with open ends) around the forecast."""
    from wxbot.model.base import Calibration
    mu = c_to_unit(statistics.fmean(values.values()) - bias, unit)
    center = round(mu)
    obs = round(c_to_unit(obs_c, unit))
    ladder = [Bucket(None, center - 6, unit)] + [Bucket(x, x, unit) for x in range(center - 5, center + 6)] \
        + [Bucket(center + 6, None, unit)]
    cal = Calibration(bias_c=bias, sigma_c=sigma, n=0, source="walk-forward")
    out = []
    for b in ladder:
        p = predictor.predict(b, kind, values, lead, cal).p_yes
        hit = (b.lo is None or obs >= b.lo) and (b.hi is None or obs <= b.hi)
        out.append((p, int(hit)))
    return out


def run_backtest(cfg, db: Database, forecaster, observer, stations: list[str] | None = None,
                 days: int = 90, leads: tuple[int, ...] = (1, 2, 3), end: date | None = None) -> dict:
    predictor = NormalMultiModel(cfg.model.version, cfg.model.prob_floor, cfg.model.prob_ceiling)
    end = end or (date.today() - timedelta(days=1))
    start = end - timedelta(days=days - 1)
    codes = stations or [s.code for s in STATIONS.values() if s.enabled]
    run_id = db.insert(backtest_runs, started_at=utcnow(),
                       params={"stations": codes, "days": days, "leads": list(leads), "start": start.isoformat(),
                               "end": end.isoformat(), "models": list(forecaster.models)})
    pairs_all: list[tuple[float, int]] = []
    per_station, fitted = {}, 0
    for code in codes:
        st = STATIONS[code]
        try:
            fc = forecaster.fetch(st, start, end, list(leads))
            obs = observer.fetch(st, start, end)
        except Exception as exc:
            log.warning("backtest %s skipped: %s", code, exc)
            per_station[code] = {"error": str(exc)}
            continue
        unit = unit_for(st)
        stats = {}
        for lead in leads:
            for kind in ("high", "low"):
                rows = []  # (date, values, obs_c)
                for d, values in sorted(fc.get(lead, {}).get(kind, {}).items()):
                    if d in obs[kind] and len(values) >= cfg.weather.min_models:
                        rows.append((date.fromisoformat(d), values, obs[kind][d][0]))
                errors = [statistics.fmean(v.values()) - o for _, v, o in rows]
                pairs, abs_err = [], []
                for i, bias, sigma in walk_forward_fits(rows, errors, lead):
                    d, values, o = rows[i]
                    spread = statistics.pstdev(values.values())
                    pairs += bucket_pairs(predictor, values, o, unit, bias, max(sigma, spread, 0.3), lead, kind)
                    abs_err.append(abs(errors[i] - bias))
                pairs_all += pairs
                key = f"{kind}_lead{lead}"
                if len(errors) >= cfg.model.min_calibration_samples:
                    bias, sigma = fit(errors)
                    db.insert(calibration_params, fitted_at=utcnow(), station=code, kind=kind, lead_days=lead,
                              bias_c=bias, sigma_c=sigma, n=len(errors), window_start=start.isoformat(),
                              window_end=end.isoformat(), backtest_run_id=run_id)
                    fitted += 1
                    stats[key] = {"n": len(errors), "bias_c": round(bias, 3), "sigma_c": round(sigma, 3),
                                  "walk_forward_mae_c": round(statistics.fmean(abs_err), 3) if abs_err else None,
                                  "brier": brier(*zip(*pairs)) if pairs else None}
                else:
                    stats[key] = {"n": len(errors), "note": "too few days to fit"}
        per_station[code] = stats
    report = summarize(pairs_all)
    report.update({"stations": per_station, "calibration_rows_fitted": fitted, "run_id": run_id,
                   "note": "Forecast skill only; no historical market prices replayed."})
    from sqlalchemy import update
    with db.engine.begin() as conn:
        conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id)
                     .values(finished_at=utcnow(), report=report))
    return report


def summarize(pairs: list[tuple[float, int]]) -> dict:
    if not pairs:
        return {"n_bucket_predictions": 0}
    probs, outs = [p for p, _ in pairs], [o for _, o in pairs]
    eps = 1e-6
    logloss = -statistics.fmean(o * math.log(max(p, eps)) + (1 - o) * math.log(max(1 - p, eps)) for p, o in pairs)
    confident = [(p, o) if p >= 0.8 else (1 - p, 1 - o) for p, o in pairs if p >= 0.8 or p <= 0.2]
    return {
        "n_bucket_predictions": len(pairs), "brier": brier(probs, outs), "log_loss": logloss,
        "calibration": calibration_bins(probs, outs),
        "confident_calls": {
            "n": len(confident),
            "mean_predicted": statistics.fmean(p for p, _ in confident) if confident else None,
            "hit_rate": statistics.fmean(o for _, o in confident) if confident else None,
        },
    }
