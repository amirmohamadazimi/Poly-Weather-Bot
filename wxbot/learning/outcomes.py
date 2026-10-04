"""The learning ledger (spec section 13): one row per resolved market, written
once its result is known, joining what was predicted, with which model,
parameters and calibrator, from which weather data and features, at what market
price and conditions, what was decided, and what happened, with the error class
and scores. It is the data retraining and the rollback check are judged on.

Each market is recorded on the production model's decision prediction: its
last one made at least a day before the target day, as in the error analysis.
Rows are only ever added.
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import select

from wxbot.db import (
    Database, market_resolutions, markets, paper_bets, prediction_outcomes, predictions, signals,
)
from wxbot.evaluation.errors import bucket_distance, classify
from wxbot.evaluation.metrics import LOG_LOSS_EPS, decision_predictions
from wxbot.learning import params

SIGNIFICANT = ("significant overconfidence", "significant underestimation")
LISTED = 20   # significant errors listed in one event
INPUTS = ("model_values_c", "calibration", "features", "data_quality", "forecast_fetched_at")


def _loss(p: float, y: int) -> float:
    p = min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p))
    return -math.log(p) if y else -math.log(1 - p)


def pending(db: Database) -> list[dict]:
    """Decision predictions of resolved markets that have no ledger row yet."""
    p, r, mk, s = predictions.c, market_resolutions.c, markets.c, signals.c
    latest = decision_predictions(1)
    rows = db.rows(
        select(p.id.label("prediction_id"), p.market_id, p.ts, p.model_version, p.params_version,
               p.calibrator_version, p.feature_set, p.lead_days, p.mu_c, p.sigma_c, p.p_yes, p.calibrated_prob,
               p.inputs, p.forecast_snapshot_id, mk.event_id, mk.city, mk.station, mk.kind, mk.local_date, mk.unit,
               mk.bucket_lo, mk.bucket_hi, r.outcome, r.resolved_at, s.id.label("signal_id"), s.side,
               s.market_prob, s.entry_price, s.decision, s.reason, s.rule_results)
        .join(latest, latest.c.pid == p.id).join(markets, mk.id == p.market_id)
        .join(market_resolutions, r.market_id == p.market_id).outerjoin(signals, s.prediction_id == p.id)
        .where(p.market_id.not_in(select(prediction_outcomes.c.market_id)))
        .order_by(mk.local_date, p.market_id, s.id))
    out: dict[str, dict] = {}
    for x in rows:
        out[x["market_id"]] = x    # one signal per prediction; should there be more, the last one
    return list(out.values())


def record(db: Database, now: datetime) -> dict:
    """Write the ledger row of every newly resolved market. Returns how many
    were added and the significant errors among them."""
    todo = pending(db)
    if not todo:
        return {"recorded": 0}
    pb = paper_bets.c
    bets: dict[str, dict] = {}
    ids = [x["market_id"] for x in todo]
    for i in range(0, len(ids), 500):
        for b in db.rows(select(pb.id, pb.market_id, pb.side, pb.status, pb.stake, pb.pnl)
                         .where(pb.market_id.in_(ids[i:i + 500])).order_by(pb.id)):
            bets.setdefault(b["market_id"], b)   # at most one per market; should there be more, the first
    legacy = params.legacy(db)
    rows = [_row(x, bets.get(x["market_id"]), legacy, now) for x in todo]
    with db.engine.begin() as conn:
        for i in range(0, len(rows), 1000):
            conn.execute(prediction_outcomes.insert(), rows[i:i + 1000])
    significant = sorted((r for r in rows if r["error_class"] in SIGNIFICANT), key=lambda r: -r["brier"])
    if significant:
        db.log_event("INFO", "learning", f"SIGNIFICANT_MODEL_ERROR: {len(significant)} of {len(rows)} newly "
                     "resolved markets were significant errors (80% or more on an outcome that did not "
                     "happen, or 20% or less on one that did)", code="SIGNIFICANT_MODEL_ERROR", details={"errors": [
                         {k: r[k] for k in ("market_id", "local_date", "station", "kind", "lead_days", "p_yes",
                                            "outcome", "error_class", "market_yes", "bet_status", "bet_pnl")}
                         for r in significant[:LISTED]]})
    return {"recorded": len(rows), "significant_errors": len(significant)}


def _row(x: dict, bet: dict | None, legacy: dict | None, now: datetime) -> dict:
    inputs = x["inputs"] or {}
    y = 1 if x["outcome"] == "YES" else 0
    mp = x["market_prob"]
    market_yes = None if mp is None else (mp if x["side"] == "YES" else 1 - mp)
    liquidity = next((rr.get("value") for rr in x["rule_results"] or [] if rr.get("rule") == "liquidity"), None)
    distance = bucket_distance(x["bucket_lo"], x["bucket_hi"], x["unit"], x["mu_c"], x["sigma_c"])
    p = x["p_yes"]
    return {
        "market_id": x["market_id"], "prediction_id": x["prediction_id"], "signal_id": x["signal_id"],
        "bet_id": bet and bet["id"], "recorded_at": now, "resolved_at": x["resolved_at"],
        "decision_time": x["ts"], "model_version": x["model_version"],
        # predictions from before versions were recorded belong to the legacy set
        "params_version": x["params_version"] or (legacy and legacy["version"]),
        "calibrator_version": x["calibrator_version"], "feature_set": x["feature_set"], "event_id": x["event_id"],
        "station": x["station"], "city": x["city"], "kind": x["kind"], "local_date": x["local_date"],
        "lead_days": x["lead_days"], "unit": x["unit"], "bucket_lo": x["bucket_lo"], "bucket_hi": x["bucket_hi"],
        "forecast_snapshot_id": x["forecast_snapshot_id"], "forecast_source": inputs.get("forecast_source"),
        "n_models": len(inputs.get("model_values_c") or {}), "model_spread_c": inputs.get("model_spread_c"),
        "mu_c": x["mu_c"], "sigma_c": x["sigma_c"],
        "distance_sigma": None if distance is None else round(distance, 4),
        "p_yes": p, "p_used": p if x["calibrated_prob"] is None else x["calibrated_prob"],
        "market_yes": market_yes, "liquidity": liquidity, "outcome": x["outcome"], "y": y,
        "error_class": classify(p, y), "brier": (p - y) ** 2, "log_loss": _loss(p, y),
        "market_brier": None if market_yes is None else (market_yes - y) ** 2,
        "decision": x["decision"], "side": x["side"], "entry_price": x["entry_price"], "reason": x["reason"],
        "bet_side": bet and bet["side"], "bet_status": bet and bet["status"], "bet_stake": bet and bet["stake"],
        "bet_pnl": bet and bet["pnl"],
        "inputs": {k: inputs[k] for k in INPUTS if k in inputs},
    }
