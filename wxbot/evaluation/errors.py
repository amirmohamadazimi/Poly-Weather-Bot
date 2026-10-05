"""Error analysis: where and how the model is wrong (v2 M7; M9 builds the learning loop on it).

Every resolved market is scored on the production model's decision
prediction, its last one made at least a day before the target day (as in the
calibration metrics), so each group is judged on what the bot knew while it
could still bet. Each prediction gets an error class (spec section 13), and the
predictions are grouped by city, temperature kind, the bucket's distance from
the forecast, probability band, how much the weather models disagreed, how far
the forecast was from the climate normal, market liquidity and model version.
Lead time is grouped on every market's last prediction at each lead.

A group is flagged only on strong evidence: at least MIN_GROUP markets
(MIN_BET_GROUP settled bets) and a gap of at least FLAG_Z standard errors, so
chance alone rarely flags any of the ~50 groups shown. The tests are
approximate: the buckets of one event are not independent (exactly one wins).
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select

from wxbot.db import Database, markets, paper_bets, predictions, signals
from wxbot.evaluation.metrics import LOG_LOSS_EPS, brier, log_loss, resolved_rows
from wxbot.model.normal import c_to_unit

MIN_GROUP = 30        # resolved markets in a group before it can be flagged
MIN_BET_GROUP = 15    # settled bets in a group before it can be flagged
FLAG_Z = 3.0          # standard errors a gap must reach to be flagged
LARGEST = 20          # largest errors listed
NEAR_ALL = 0.9        # a group with this share of the sample is not listed apart from the overall flag

CLASSES = ["right side", "overconfidence", "significant overconfidence", "underestimation",
           "significant underestimation"]


def classify(p: float, outcome: int) -> str:
    """The error class of a YES probability `p` given the outcome (1 = YES).
    85% and NO is significant overconfidence; 25% and YES is underestimation."""
    if outcome:
        return "right side" if p >= 0.5 else ("underestimation" if p > 0.2 else "significant underestimation")
    return "right side" if p < 0.5 else ("overconfidence" if p < 0.8 else "significant overconfidence")


def bucket_distance(lo: float | None, hi: float | None, unit: str | None, mu_c: float | None,
                    sigma_c: float | None) -> float | None:
    """How far the forecast mean is from the bucket, in forecast standard
    deviations; 0 when the bucket contains it. Buckets are whole degrees, so
    "18°C" covers 17.5 to 18.5."""
    if mu_c is None or not sigma_c or (lo is None and hi is None):
        return None
    unit = unit or "C"
    mu, sd = c_to_unit(mu_c, unit), sigma_c * (9 / 5 if unit == "F" else 1)
    low = -math.inf if lo is None else lo - 0.5
    high = math.inf if hi is None else hi + 0.5
    gap = low - mu if mu < low else (mu - high if mu > high else 0.0)
    return gap / sd


def _band(x: float | None, edges: list[float], labels: list[str]) -> str:
    if x is None:
        return "unknown"
    for edge, label in zip(edges, labels):
        if x < edge:
            return label
    return labels[-1]


def distance_band(d: float | None) -> str:
    if d is None:
        return "unknown"
    return "contains the forecast" if d == 0 else _band(d, [1, 2], ["within 1σ", "1–2σ away", "over 2σ away"])


def prob_band(p: float) -> str:
    return _band(p, [0.05, 0.2, 0.5, 0.8, 0.95], ["0–5%", "5–20%", "20–50%", "50–80%", "80–95%", "95–100%"])


def lead_label(d: int | None) -> str:
    return "unknown" if d is None else ("same day" if d <= 0 else "1 day" if d == 1 else
                                        f"{d} days" if d < 4 else "4+ days")


def _spread(x: dict) -> float | None:
    return (x.get("inputs") or {}).get("model_spread_c")


def _anomaly(x: dict) -> str:
    """Forecast mean against the station's climate normal for the day, in climate standard deviations."""
    f = (x.get("inputs") or {}).get("features") or {}
    a, sd = f.get("anomaly_c"), f.get("clim_std_c")
    if a is None or not sd:
        return "unknown"
    z = a / sd
    return "near normal (within 1σ)" if abs(z) < 1 else (
        ("warmer" if z > 0 else "colder") + (" than normal (1–2σ)" if abs(z) < 2 else " than normal (2σ+, extreme)"))


DIMENSIONS = [  # key, title, group label of a row
    ("city", "City", lambda x: x["city"] or x["station"] or "unknown"),
    ("kind", "Highest or lowest temperature", lambda x: x["kind"] or "unknown"),
    ("bucket", "Bucket vs forecast", lambda x: distance_band(x["distance"])),
    ("prob", "Predicted probability", lambda x: prob_band(x["p_yes"])),
    ("spread", "Weather-model disagreement", lambda x: _band(_spread(x), [0.5, 1, 2],
                                                            ["under 0.5°C", "0.5–1°C", "1–2°C", "2°C+"])),
    ("anomaly", "Forecast vs climate normal", _anomaly),
    ("liquidity", "Market liquidity", lambda x: _band(x["liquidity"], [1000, 5000, 20000],
                                                      ["under $1k", "$1k–5k", "$5k–20k", "$20k+"])),
    ("model", "Model version", lambda x: x["model_version"]),
]


def _z(num: float, var: float) -> float | None:
    return num / math.sqrt(var) if var > 0 else None


def group_stats(rows: list[dict]) -> dict:
    """Scores of one group of resolved predictions and the evidence of a weakness.
    bias: mean YES probability minus the share that resolved YES.
    confidence gap: mean probability of the side predicted minus how often that side happened.
    vs market: mean Brier difference, model minus market, on markets with a price."""
    n = len(rows)
    ps, ys = [x["p_yes"] for x in rows], [x["y"] for x in rows]
    conf = [max(p, 1 - p) for p in ps]
    hit = [int((p >= 0.5) == bool(y)) for p, y in zip(ps, ys)]
    paired = [x for x in rows if x["market_yes"] is not None]
    diffs = [(x["p_yes"] - x["y"]) ** 2 - (x["market_yes"] - x["y"]) ** 2 for x in paired]
    z_market = None
    if len(diffs) > 1 and statistics.stdev(diffs) > 0:
        z_market = statistics.fmean(diffs) / (statistics.stdev(diffs) / math.sqrt(len(diffs)))
    classes = Counter(classify(p, y) for p, y in zip(ps, ys))
    out = {
        "n": n, "n_yes": sum(ys), "mean_pred": statistics.fmean(ps), "observed": statistics.fmean(ys),
        "bias": statistics.fmean(ps) - statistics.fmean(ys),
        "z_bias": _z(sum(ps) - sum(ys), sum(p * (1 - p) for p in ps)),
        "confidence": statistics.fmean(conf), "right_side": statistics.fmean(hit),
        "z_confidence": _z(sum(conf) - sum(hit), sum(c * (1 - c) for c in conf)),
        "brier": brier(ps, ys), "log_loss": log_loss(ps, ys),
        "n_market": len(paired),
        "brier_model_paired": brier([x["p_yes"] for x in paired], [x["y"] for x in paired]),
        "brier_market": brier([x["market_yes"] for x in paired], [x["y"] for x in paired]),
        "z_vs_market": z_market,
        "significant_errors": classes["significant overconfidence"] + classes["significant underestimation"],
    }
    out["flags"] = _flags(out)
    return out


def _flags(s: dict) -> list[dict]:
    flags = []
    if s["n"] >= MIN_GROUP:
        z = s["z_confidence"]
        if z is not None and abs(z) >= FLAG_Z:
            flags.append({"flag": "overconfident" if z > 0 else "underconfident", "weakness": True, "z": z,
                          "detail": f"{s['confidence'] * 100:.1f}% sure of the side it predicted on average; "
                                    f"that side happened {s['right_side'] * 100:.1f}% of the time"})
        z = s["z_bias"]
        if z is not None and abs(z) >= FLAG_Z:
            flags.append({"flag": "YES too often" if z > 0 else "YES too rarely", "weakness": True, "z": z,
                          "detail": f"predicted {s['mean_pred'] * 100:.1f}% YES on average; "
                                    f"{s['observed'] * 100:.1f}% resolved YES"})
    z = s["z_vs_market"]
    if s["n_market"] >= MIN_GROUP and z is not None and abs(z) >= FLAG_Z:
        flags.append({"flag": "worse than the market" if z > 0 else "better than the market", "weakness": z > 0,
                      "z": z, "detail": f"Brier {s['brier_model_paired']:.4f} vs the market's "
                                        f"{s['brier_market']:.4f} on {s['n_market']} markets"})
    return flags


def _grouped(rows: list[dict], label, stats) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for x in rows:
        by[label(x)].append(x)
    out = [{"group": g, **stats(xs)} for g, xs in by.items()]
    return sorted(out, key=lambda g: (g["group"] == "unknown", -g["n"], g["group"]))


# -- bets -------------------------------------------------------------------------

def settled_bets(db: Database) -> list[dict]:
    b, mk, s, p = paper_bets.c, markets.c, signals.c, predictions.c
    rows = db.rows(select(b.id, b.market_id, b.side, b.entry_price, b.stake, b.pnl, b.status, b.confidence,
                          b.model_prob, mk.city, mk.station, mk.kind, mk.unit, mk.bucket_lo, mk.bucket_hi,
                          p.lead_days, p.mu_c, p.sigma_c)
                   .join(markets, mk.id == b.market_id).join(signals, s.id == b.signal_id)
                   .join(predictions, p.id == s.prediction_id)
                   .where(b.status.in_(["WON", "LOST"])).order_by(b.id))
    for x in rows:
        x["won"] = int(x["status"] == "WON")
        x["conf"] = x["confidence"] if x["confidence"] is not None else x["model_prob"]
        x["distance"] = bucket_distance(x["bucket_lo"], x["bucket_hi"], x["unit"], x["mu_c"], x["sigma_c"])
    return rows


BET_DIMENSIONS = [
    ("city", "City", lambda x: x["city"] or x["station"] or "unknown"),
    ("side", "Side", lambda x: x["side"]),
    ("lead", "Lead time", lambda x: lead_label(x["lead_days"])),
    ("bucket", "Bucket vs forecast", lambda x: distance_band(x["distance"])),
    ("price", "Entry price", lambda x: _band(x["entry_price"], [0.5, 0.8, 0.9, 0.95],
                                             ["under 0.50", "0.50–0.80", "0.80–0.90", "0.90–0.95", "0.95+"])),
    ("kind", "Highest or lowest temperature", lambda x: x["kind"] or "unknown"),
]


def bet_stats(rows: list[dict]) -> dict:
    conf = [x["conf"] for x in rows]
    won = sum(x["won"] for x in rows)
    staked = sum(x["stake"] for x in rows)
    pnl = sum(x["pnl"] or 0.0 for x in rows)
    s = {"n": len(rows), "won": won, "win_rate": won / len(rows), "expected_win_rate": statistics.fmean(conf),
         "staked": staked, "pnl": pnl, "roi": pnl / staked if staked else None,
         "z_confidence": _z(sum(conf) - won, sum(c * (1 - c) for c in conf))}
    z = s["z_confidence"]
    s["flags"] = []
    if s["n"] >= MIN_BET_GROUP and z is not None and abs(z) >= FLAG_Z:
        s["flags"].append({"flag": "overconfident" if z > 0 else "underconfident", "weakness": z > 0, "z": z,
                           "detail": f"won {s['win_rate'] * 100:.0f}% of {s['n']} bets against "
                                     f"{s['expected_win_rate'] * 100:.0f}% predicted; "
                                     f"P/L {'-' if pnl < 0 else ''}${abs(pnl):,.2f}"})
    return s


# -- everything ------------------------------------------------------------------------

def error_analysis(db: Database, min_lead_days: int = 1) -> dict:
    rows = resolved_rows(db, min_lead_days)
    for x in rows:
        x["distance"] = bucket_distance(x["bucket_lo"], x["bucket_hi"], x["unit"], x["mu_c"], x["sigma_c"])
        x["class"] = classify(x["p_yes"], x["y"])
    leads = resolved_rows(db, per_lead=True)
    dims: list[dict[str, Any]] = [{"key": "all", "title": "All resolved markets",
             "groups": [{"group": "all", **group_stats(rows)}] if rows else []}]
    dims += [{"key": k, "title": t, "groups": _grouped(rows, f, group_stats)} for k, t, f in DIMENSIONS]
    dims.insert(2, {"key": "lead", "title": "Lead time (each market's last prediction at every lead)",
                    "groups": sorted(_grouped(leads, lambda x: lead_label(x["lead_days"]), group_stats),
                                     key=lambda g: (g["group"] == "unknown", g["group"] != "same day", g["group"]))})
    bets = settled_bets(db)
    bet_dims: list[dict[str, Any]] = [{"key": "all", "title": "All settled bets",
                                       "groups": [{"group": "all", **bet_stats(bets)}] if bets else []}]
    bet_dims += [{"key": k, "title": t, "groups": _grouped(bets, f, bet_stats)} for k, t, f in BET_DIMENSIONS]

    weaknesses = []
    for scope, ds in (("predictions", dims), ("bets", bet_dims)):
        overall = ds[0]["groups"][0] if ds[0]["groups"] else None
        same_as_all = {f["flag"] for f in overall["flags"]} if overall else set()
        overall_n = overall["n"] if overall else 0
        for d in ds:
            for g in d["groups"]:
                for f in g["flags"]:
                    # a group that is nearly the whole sample only repeats the overall flag
                    if f["weakness"] and not (d["key"] != "all" and f["flag"] in same_as_all
                                              and g["n"] >= NEAR_ALL * overall_n):
                        weaknesses.append({"scope": scope, "dimension": d["title"], "group": g["group"],
                                           "n": g["n"], **f})
    weaknesses.sort(key=lambda w: -abs(w["z"]))

    bet_by_market: dict[str, list[dict]] = defaultdict(list)
    for x in db.rows(select(paper_bets.c.market_id, paper_bets.c.side, paper_bets.c.pnl, paper_bets.c.status)):
        bet_by_market[x["market_id"]].append(x)
    clip = lambda p: min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p))  # noqa: E731
    worst = sorted(rows, key=lambda x: -abs(x["p_yes"] - x["y"]))[:LARGEST]
    largest = [{
        "market_id": x["market_id"], "question": x["question"], "local_date": x["local_date"],
        "city": x["city"] or x["station"], "lead_days": x["lead_days"], "p_yes": x["p_yes"], "used": x["used"],
        "market_yes": x["market_yes"], "outcome": x["outcome"], "class": x["class"],
        "log_loss": -math.log(clip(x["p_yes"]) if x["y"] else 1 - clip(x["p_yes"])),
        "distance": None if x["distance"] is None else round(x["distance"], 2),
        "bets": bet_by_market.get(x["market_id"], []),
    } for x in worst if abs(x["p_yes"] - x["y"]) >= 0.5]
    counts = Counter(x["class"] for x in rows)
    return {
        "n": len(rows), "min_lead_days": min_lead_days, "min_group": MIN_GROUP, "min_bet_group": MIN_BET_GROUP,
        "flag_z": FLAG_Z,
        "classes": [{"class": c, "n": counts[c], "share": counts[c] / len(rows) if rows else None} for c in CLASSES],
        "dimensions": dims, "bets": {"n": len(bets), "dimensions": bet_dims},
        "weaknesses": weaknesses, "largest_errors": largest,
    }
