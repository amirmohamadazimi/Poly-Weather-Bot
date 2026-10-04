"""Retraining with an out-of-sample approval rule, and automatic rollback.

Retraining (at most every retrain_days, and on `python main.py retrain`):

1. Holdout: the ledger rows (outcomes.py) of the newest holdout_days market
   days. They are never used for fitting.
2. Retraining: candidates are fitted from what each weather model forecast N
   days ahead (Open-Meteo Previous Runs) against observed highs and lows, one
   per training window in train_days, on days that ended before the first
   holdout decision could have been made (holdout start - 1 - the longest
   lead), so no holdout weather leaks into a candidate. A station, kind and
   lead with too few days keeps production's row.
3. Out-of-sample evaluation: every holdout prediction is priced again with each
   candidate and with production, from the inputs stored when it was made.
4. Approval: a candidate is approved only if, on at least min_markets holdout
   markets, its Brier score AND log loss are lower than production's, the gain
   holds in min_confidence of bootstrap resamples of whole stations (a
   station's days are not independent), and its log loss is no worse than that
   of the probabilities the bot actually used (calibrated, when a calibrator was
   approved). Doing better on the data it was fitted on counts for nothing.
5. Deploy: the approved candidate with the lowest log loss becomes production;
   the old production set is kept as previous. Every candidate is stored, with
   its evaluation, whether approved or not.

Production's own fit may cover part of the holdout (it was fitted earlier on
then-recent days); that can only favour production, so it never makes a worse
candidate look better.

Rollback (every cycle, database only): once the deployed set has priced
min_markets markets that resolved, it is compared with the previous set on
exactly those markets. If the previous set does better by the same rule, it
is put back and the deployed set is marked rolled_back.

Learning never changes anything but these parameters, and only through this
rule; `[learning] enabled = false` turns both off.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from wxbot.data.polymarket import Bucket
from wxbot.data.stations import get_station
from wxbot.db import Database, prediction_outcomes
from wxbot.evaluation.metrics import LOG_LOSS_EPS
from wxbot.learning import params
from wxbot.model.registry import production_model

MIN_STATIONS = 5     # fewer stations than this cannot give a meaningful station bootstrap


def _loss(p: float, y: int) -> float:
    p = min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p))
    return -math.log(p) if y else -math.log(1 - p)


def _mean(xs) -> float | None:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def ledger(db: Database, model_version: str, *where) -> list[dict]:
    po = prediction_outcomes.c
    return db.rows(select(prediction_outcomes).where(po.model_version == model_version, *where)
                   .order_by(po.local_date, po.market_id))


def reprice(rows: list[dict], p: params.Params, cfg) -> list[float]:
    """The production model's probability for each ledger row with param set
    `p`, from the model values stored when the prediction was made."""
    model = production_model(cfg)
    return [model.predict(Bucket(x["bucket_lo"], x["bucket_hi"], x["unit"]), x["kind"],
                          x["inputs"]["model_values_c"], x["lead_days"],
                          p.calibration(x["station"], x["kind"], x["lead_days"])).p_yes for x in rows]


def station_confidence(rows: list[dict], gains: list[float], n_boot: int, seed: int = 7) -> float | None:
    """Share of bootstrap resamples of whole stations in which the mean gain is
    above zero (deterministic: fixed seed). None with too few stations."""
    sums: dict[str, float] = defaultdict(float)
    for x, g in zip(rows, gains):
        sums[x["station"]] += g
    keys = sorted(sums)
    if len(keys) < MIN_STATIONS:
        return None
    s = [sums[k] for k in keys]
    rng, m = random.Random(seed), len(keys)
    wins = 0
    for _ in range(n_boot):   # the resample's total gain has the sign of its mean
        idx = [rng.randrange(m) for _ in range(m)]
        wins += sum(s[i] for i in idx) > 0
    return wins / n_boot


def compare(rows: list[dict], new: params.Params, old: params.Params, cfg, new_probs: list[float] | None = None,
            old_probs: list[float] | None = None) -> dict:
    """Scores of two param sets on the same ledger rows (lower is better), and
    how reliably `new` beats `old` on log loss across stations."""
    ys = [x["y"] for x in rows]
    pn = new_probs if new_probs is not None else reprice(rows, new, cfg)
    po = old_probs if old_probs is not None else reprice(rows, old, cfg)
    used = [x["p_used"] for x in rows]
    gains = [_loss(b, y) - _loss(a, y) for a, b, y in zip(pn, po, ys)]
    n_boot = int(cfg.learning.get("bootstrap", 2000))
    return {
        "n": len(rows), "n_events": len({x["event_id"] for x in rows}), "n_stations": len({x["station"] for x in rows}),
        "from": rows[0]["local_date"] if rows else None, "to": rows[-1]["local_date"] if rows else None,
        "brier_new": _mean((p - y) ** 2 for p, y in zip(pn, ys)), "brier_old": _mean((p - y) ** 2 for p, y in zip(po, ys)),
        "log_loss_new": _mean(_loss(p, y) for p, y in zip(pn, ys)),
        "log_loss_old": _mean(_loss(p, y) for p, y in zip(po, ys)),
        "log_loss_used": _mean(_loss(p, y) for p, y in zip(used, ys)),
        "confidence": station_confidence(rows, gains, n_boot) if rows else None,
    }


def judge(ev: dict, cfg, guard_used: bool = True) -> tuple[bool, str]:
    """The approval rule (see the module docstring)."""
    L = cfg.learning
    need, conf = float(L.min_confidence), ev["confidence"]
    if ev["n"] < int(L.min_markets):
        return False, f"only {ev['n']} out-of-sample markets (need {L.min_markets})"
    if conf is None:
        return False, f"markets from only {ev['n_stations']} stations (need {MIN_STATIONS} to judge reliability)"
    if not (ev["brier_new"] < ev["brier_old"] and ev["log_loss_new"] < ev["log_loss_old"]):
        return False, "not better on both Brier score and log loss"
    if conf < need:
        return False, f"gain not reliable: wins in {conf:.0%} of station resamples (need {need:.0%})"
    if guard_used and ev["log_loss_new"] > ev["log_loss_used"]:
        return False, (f"log loss {ev['log_loss_new']:.4f} is worse than the calibrated probabilities the bot used "
                       f"({ev['log_loss_used']:.4f})")
    return True, (f"better on {ev['n']} out-of-sample markets: Brier {ev['brier_old']:.4f} → {ev['brier_new']:.4f}, "
                  f"log loss {ev['log_loss_old']:.4f} → {ev['log_loss_new']:.4f}, in {conf:.0%} of station resamples")


def due(db: Database, cfg, now: datetime) -> bool:
    nxt = db.get_state("next_retrain_at")
    return nxt is None or now >= datetime.fromisoformat(nxt)


def _schedule(db: Database, now: datetime, hours: float) -> None:
    db.set_state("next_retrain_at", (now + timedelta(hours=hours)).isoformat())


def retrain(db: Database, cfg, history, observer, now: datetime, force: bool = False) -> dict:
    """One retraining round; see the module docstring. `history` fetches past
    forecasts (Open-Meteo Previous Runs), `observer` observed highs/lows."""
    L = cfg.learning
    if not force and not L.enabled:
        return {"skipped": "learning is disabled"}
    if not force and not due(db, cfg, now):
        return {"skipped": "not due", "next": db.get_state("next_retrain_at")}
    if history is None or observer is None:
        return {"skipped": "no source of past forecasts and observations"}
    model_version = cfg.model.version
    po = prediction_outcomes.c
    span = db.one(select(func.min(po.local_date).label("first"), func.max(po.local_date).label("last"))
                  .where(po.model_version == model_version))
    if not span or span["last"] is None:
        return {"skipped": "no resolved markets recorded yet"}
    last = date.fromisoformat(span["last"])
    hold_from = max(last - timedelta(days=int(L.holdout_days) - 1), date.fromisoformat(span["first"]))
    leads = [int(x) for x in cfg.backtest.leads]
    train_to = hold_from - timedelta(days=1 + max(leads))
    # every training day's observation was known when each holdout prediction was made
    holdout = [x for x in ledger(db, model_version, po.local_date >= hold_from.isoformat())
               if (x["inputs"] or {}).get("model_values_c")
               and date.fromisoformat(x["local_date"]) - timedelta(days=(x["lead_days"] or 0) + 1) >= train_to]
    if len(holdout) < int(L.min_markets):
        return {"skipped": f"only {len(holdout)} resolved markets in the holdout (need {L.min_markets})"}

    windows = sorted({int(d) for d in L.train_days})
    start = train_to - timedelta(days=max(windows) - 1)
    prod = params.production(db)
    current = params.load(db, cfg, prod)
    codes = sorted({x["station"] for x in holdout} | {k[0] for k in current.rows})
    _schedule(db, now, float(L.get("retry_hours", 24)))   # should anything below fail, try again later
    fetched, failed = {}, {}
    for code in codes:
        st = get_station(code)
        if st is None:
            continue
        try:
            fetched[code] = (history.fetch(st, start, train_to, leads), observer.fetch(st, start, train_to))
        except Exception as exc:  # one station's failure only leaves its production rows in place
            failed[code] = f"{type(exc).__name__}: {exc}"
    if not fetched:
        db.log_event("WARNING", "learning", f"retraining failed: no past forecasts or observations "
                     f"({len(failed)} stations)", details={"failed": failed})
        return {"error": "no data", "failed": failed}

    old_probs = reprice(holdout, current, cfg)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    candidates = []
    for days in windows:
        rows = []
        for code, (fc, obs) in fetched.items():
            rows += [{"station": code, **r} for r in params.fit_rows(
                fc, obs, leads, train_to - timedelta(days=days - 1), train_to, int(cfg.weather.min_models),
                int(cfg.model.min_calibration_samples))]
        have = {(r["station"], r["kind"], r["lead_days"]) for r in rows}
        carried = [dict(r) for k, r in current.rows.items() if k not in have]
        cand = params.Params({"version": f"bias-sigma-{stamp}-{days}d", "legacy": False}, rows + carried, cfg)
        ev = compare(holdout, cand, current, cfg, old_probs=old_probs)
        ok, reason = judge(ev, cfg)
        candidates.append({"days": days, "rows": rows + carried, "n_fitted": len(rows), "n_carried": len(carried),
                           "version": cand.version, "evaluation": ev, "approved": ok, "reason": reason})
    approved = [c for c in candidates if c["approved"]]
    chosen = min(approved, key=lambda c: c["evaluation"]["log_loss_new"]) if approved else None
    for c in candidates:
        if c["approved"] and c is not chosen:
            c["reason"] = f"approved, but {chosen['version']} did better: " + c["reason"]
        c["id"] = params.store(
            db, version=c["version"], model_version=model_version, origin="retrain", status="rejected",
            rows=c["rows"], now=now, train_from=(train_to - timedelta(days=c["days"] - 1)).isoformat(),
            train_to=train_to.isoformat(), train_days=c["days"], n_carried=c["n_carried"],
            evaluation={**c["evaluation"], "production": prod and prod["version"], "failed_stations": failed},
            approved=c["approved"], reason=c["reason"])
    summary = {c["version"]: {"approved": c["approved"], "reason": c["reason"]} for c in candidates}
    holdout_span = f"{hold_from} to {last}"
    db.log_event("INFO", "learning", f"MODEL_RETRAINED: {len(candidates)} candidates judged on {len(holdout)} "
                 f"markets ({holdout_span}): " + (f"deploying {chosen['version']}" if chosen else
                                                   f"kept {prod['version'] if prod else 'the default spreads'}"),
                 code="MODEL_RETRAINED", details={"candidates": summary, "failed_stations": failed,
                                                  "train_to": train_to.isoformat(), "holdout": holdout_span})
    if chosen:
        params.deploy(db, chosen["id"], now)
        db.log_event("INFO", "learning", f"MODEL_DEPLOYED: {chosen['version']} replaces "
                     f"{prod['version'] if prod else 'the default spreads'}: {chosen['reason']}",
                     code="MODEL_DEPLOYED", details={"version": chosen["version"], **chosen["evaluation"]})
    _schedule(db, now, 24 * float(L.retrain_days))
    result = {"at": now.isoformat(), "holdout": holdout_span, "n_holdout": len(holdout),
              "train_to": train_to.isoformat(), "deployed": chosen and chosen["version"],
              "kept": None if chosen else (prod and prod["version"]), "candidates": summary, "failed": failed}
    db.set_state("last_retrain", result)
    return result


def check_rollback(db: Database, cfg, now: datetime) -> dict:
    """Compare the deployed set with the one it replaced on the resolved
    markets it priced; put the previous set back if it does reliably better."""
    if not cfg.learning.enabled:
        return {"skipped": "learning is disabled"}
    prod, prev = params.production(db), params.get(db, status="previous")
    if prod is None or prev is None:
        return {"skipped": "no previous set to compare with"}
    rows = [x for x in ledger(db, cfg.model.version, prediction_outcomes.c.params_version == prod["version"])
            if (x["inputs"] or {}).get("model_values_c")]
    if len(rows) < int(cfg.learning.min_markets):
        return {"monitoring": prod["version"], "markets": len(rows), "need": int(cfg.learning.min_markets)}
    ev = compare(rows, params.load(db, cfg, prev), params.load(db, cfg, prod), cfg,
                 old_probs=[x["p_yes"] for x in rows])
    worse, reason = judge(ev, cfg, guard_used=False)
    db.set_state("last_rollback_check", {"at": now.isoformat(), "version": prod["version"],
                                         "previous": prev["version"], "rollback": worse, **ev})
    if not worse:
        return {"monitoring": prod["version"], "markets": len(rows), "kept": True}
    params.rollback(db, now, f"{prev['version']} {reason}")
    db.log_event("WARNING", "learning", f"MODEL_ROLLBACK: {prod['version']} did worse than {prev['version']}, "
                 f"which is back in production: {prev['version']} {reason}", code="MODEL_ROLLBACK",
                 details={"reverted": prod["version"], "reinstated": prev["version"], **ev})
    return {"rolled_back": prod["version"], "reinstated": prev["version"]}


def manual_rollback(db: Database, now: datetime) -> dict:
    done = params.rollback(db, now, "rolled back by hand (python main.py rollback)")
    if done is None:
        return {"error": "no previous param set to roll back to"}
    reverted, reinstated = done
    db.log_event("WARNING", "learning", f"MODEL_ROLLBACK: {reverted['version']} rolled back by hand; "
                 f"{reinstated['version']} is back in production", code="MODEL_ROLLBACK",
                 details={"reverted": reverted["version"], "reinstated": reinstated["version"], "manual": True})
    return {"rolled_back": reverted["version"], "reinstated": reinstated["version"]}
