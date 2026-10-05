"""Performance and calibration metrics for the dashboard and the final report."""
from __future__ import annotations

import math
from datetime import datetime
import random
import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import and_, func, or_, select

from wxbot.db import (
    Database, bankroll_snapshots, market_resolutions, markets, model_versions, paper_bets, predictions,
    prob_calibrators, signals,
)

# rows from before v2 M4 have no role: they were all made by the production model
PRODUCTION = or_(predictions.c.role.is_(None), predictions.c.role == "production")


def liquid(rule_results) -> bool:
    """Whether a signal's market passed the bot's liquidity check (strategy.min_liquidity_usd)."""
    return any(rr.get("rule") == "liquidity" and rr.get("passed") for rr in rule_results or [])


def market_yes(sig: dict | None) -> float | None:
    """The market's YES probability from a signal (its mid price): the benchmark
    the model is compared against. None without a price, and for a market that
    failed the liquidity check: there the mid of a near-empty book is a
    placeholder (often 0.34 or 0.40), not a forecast, and counting it makes any
    model look better than the market."""
    if not sig or sig.get("market_prob") is None or not liquid(sig.get("rule_results")):
        return None
    return sig["market_prob"] if sig["side"] == "YES" else 1 - sig["market_prob"]
LOG_LOSS_EPS = 1e-3  # probabilities are clipped to [eps, 1 - eps] so one certain miss is not infinite


def max_drawdown(equity: list[float]) -> tuple[float, float, list[float]]:
    """-> (max drawdown in $, as fraction of the peak, drawdown series in $)."""
    peak = float("-inf")
    series, worst, worst_pct = [], 0.0, 0.0
    for e in equity:
        peak = max(peak, e)
        dd = peak - e
        series.append(dd)
        if dd > worst:
            worst, worst_pct = dd, (dd / peak if peak > 0 else 0.0)
    return worst, worst_pct, series


def brier(probs: list[float], outcomes: list[int]) -> float | None:
    if not probs:
        return None
    return statistics.fmean((p - o) ** 2 for p, o in zip(probs, outcomes))


def log_loss(probs: list[float], outcomes: list[int]) -> float | None:
    if not probs:
        return None
    clip = [min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p)) for p in probs]
    return statistics.fmean(-math.log(p) if o else -math.log(1 - p) for p, o in zip(clip, outcomes))


def ece(probs: list[float], outcomes: list[int], n_bins: int = 10) -> float | None:
    """Expected calibration error: the gap between mean prediction and observed
    frequency in each of n_bins equal-width bins, weighted by the bin's share."""
    if not probs:
        return None
    bins = calibration_bins(probs, outcomes, n_bins)
    return sum(b["n"] * abs(b["mean_pred"] - b["observed"]) for b in bins) / len(probs)


def calibration_bins(probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict]:
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, o in zip(probs, outcomes):
        bins[min(int(p * n_bins), n_bins - 1)].append((p, o))
    out = []
    for i, b in enumerate(bins):
        if b:
            out.append({"bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}", "n": len(b),
                        "mean_pred": statistics.fmean(p for p, _ in b),
                        "observed": statistics.fmean(o for _, o in b)})
    return out


def bootstrap_roi_ci(stakes: list[float], pnls: list[float], n: int = 2000, seed: int = 7) -> tuple | None:
    """95% interval for ROI (sum pnl / sum stake) by resampling settled bets."""
    if len(stakes) < 5:
        return None
    rng = random.Random(seed)
    idx = range(len(stakes))
    rois = []
    for _ in range(n):
        sample = [rng.choice(idx) for _ in idx]
        s = sum(stakes[i] for i in sample)
        rois.append(sum(pnls[i] for i in sample) / s if s else 0.0)
    rois.sort()
    return rois[int(0.025 * n)], rois[int(0.975 * n) - 1]


def overview(db: Database, initial: float, now: datetime | None = None) -> dict:
    from wxbot.execution.portfolio import bankroll
    from wxbot.db import utcnow
    from wxbot.experiment import current, progress
    bets = db.rows(select(paper_bets).order_by(paper_bets.c.id))
    settled = [b for b in bets if b["status"] in ("WON", "LOST")]
    wins = [b for b in settled if b["status"] == "WON"]
    staked = sum(b["stake"] for b in settled)
    pnl = sum(b["pnl"] for b in settled)
    bank = bankroll(db, initial)
    eq = [r["equity"] for r in db.rows(select(bankroll_snapshots.c.equity).order_by(bankroll_snapshots.c.id))]
    dd, dd_pct, _ = max_drawdown([initial] + eq)
    # the probability the decision used: calibrated when a calibrator was active
    probs = [b["model_prob"] if b["confidence"] is None else b["confidence"] for b in settled]
    outs = [1 if b["status"] == "WON" else 0 for b in settled]
    ci = bootstrap_roi_ci([b["stake"] for b in settled], [b["pnl"] for b in settled])
    questions = {r["id"]: r for r in db.rows(select(markets.c.id, markets.c.question, markets.c.local_date)
                                              .where(markets.c.id.in_([p.market_id for p in bank.positions])))}
    positions = [{
        "bet_id": p.bet_id, "market_id": p.market_id, "question": questions.get(p.market_id, {}).get("question"),
        "local_date": questions.get(p.market_id, {}).get("local_date"), "side": p.side,
        "shares": round(p.shares, 4), "stake": round(p.stake, 4), "entry_price": round(p.entry_price, 4),
        "mark_price": None if p.mark_price is None else round(p.mark_price, 6), "marked_by": p.marked_by,
        "value": round(p.value, 4),
        "unrealized_pnl": round(p.unrealized_pnl, 4),
    } for p in bank.positions]
    exp = current(db)
    return {
        "mode": "PAPER TRADING", "real_money": 0.0,
        "experiment": exp and {**{k: exp[k] for k in ("name", "initial_bankroll", "started_at", "git_ref")},
                               "code_ref": db.get_state("code_ref"), "progress": progress(db, exp, now or utcnow())},
        "starting_bankroll": initial, "cash": bank.cash, "available_cash": bank.cash,
        "open_exposure": bank.open_exposure, "market_value": bank.market_value,
        "unrealized_pnl": bank.unrealized_pnl, "book_equity": bank.book_equity,
        # equity and total P/L count open positions at the bid of the side held
        "equity": bank.equity, "total_pnl": bank.equity - initial, "realized_pnl": pnl,
        "n_open_positions": len(positions), "positions": positions,
        "marked_by": {k: sum(p["marked_by"] == k for p in positions) for k in ("bid", "price", "cost")},
        "roi_on_staked": pnl / staked if staked else None,
        "return_on_bankroll": (bank.equity - initial) / initial,
        "roi_95ci": ci,
        "n_bets": len(bets), "n_open": len(bets) - len(settled) - sum(b["status"] == "VOID" for b in bets),
        "n_settled": len(settled), "n_won": len(wins),
        "win_rate": len(wins) / len(settled) if settled else None,
        "avg_confidence": statistics.fmean(b["confidence"] for b in bets) if bets else None,
        "avg_edge": statistics.fmean(b["edge"] for b in bets) if bets else None,
        "avg_entry_price": statistics.fmean(b["entry_price"] for b in bets) if bets else None,
        "expected_win_rate": statistics.fmean(probs) if probs else None,
        "brier_bets": brier(probs, outs),
        "brier_market_on_bets": brier([b["market_prob"] for b in settled if b["market_prob"] is not None],
                                      [o for b, o in zip(settled, outs) if b["market_prob"] is not None]),
        "max_drawdown": dd, "max_drawdown_pct": dd_pct,
    }


def portfolio_view(db: Database, cfg, now, initial: float) -> dict:
    """Open positions with what each could pay and what it risks, and how much
    of every exposure limit is in use (the limits the engine sizes bets with)."""
    from wxbot.calibration.fit import day_end
    from wxbot.execution.portfolio import bankroll, daily_realized_pnl
    risk = cfg.risk
    bank = bankroll(db, initial)
    equity = bank.equity
    b, mk = paper_bets.c, markets.c
    info = {r["id"]: r for r in db.rows(
        select(b.id, b.opened_at, b.event_id, b.confidence, b.model_prob, b.market_prob, b.edge, mk.question,
               mk.event_title, mk.bucket_label, mk.city, mk.station, mk.local_date, mk.kind)
        .join(markets, mk.id == b.market_id).where(b.status == "OPEN"))}
    positions: list[dict[str, Any]] = []
    for p in bank.positions:
        r = info.get(p.bet_id, {})
        conf = r.get("confidence") if r.get("confidence") is not None else r.get("model_prob")
        try:
            hours_left = (day_end(r["station"], r["local_date"]) - now).total_seconds() / 3600
        except Exception:  # unknown station or date
            hours_left = None
        positions.append({
            "bet_id": p.bet_id, "market_id": p.market_id, "question": r.get("question"),
            "event_title": r.get("event_title"), "bucket_label": r.get("bucket_label"), "city": r.get("city"),
            "station": r.get("station"), "local_date": r.get("local_date"), "opened_at": r.get("opened_at"),
            "side": p.side, "shares": p.shares, "entry_price": p.entry_price, "cost": p.stake,
            "mark_price": p.mark_price, "marked_by": p.marked_by, "value": p.value, "unrealized_pnl": p.unrealized_pnl,
            # each share pays $1 if the side held wins
            "potential_payout": p.shares, "max_profit": p.shares - p.stake, "max_loss": p.stake,
            "pct_of_equity": p.stake / equity if equity > 0 else None,
            "confidence": conf, "expected_pnl": None if conf is None else conf * p.shares - p.stake,
            "market_prob": r.get("market_prob"), "edge": r.get("edge"),
            "hours_left": None if hours_left is None else round(hours_left, 1),
        })

    def groups(key, label):
        out: dict = {}
        for p in positions:
            k = key(p)
            g = out.setdefault(k, {"group": label(p), "n": 0, "cost": 0.0, "value": 0.0})
            g["n"] += 1
            g["cost"] += p["cost"]
            g["value"] += p["value"]
        return sorted(out.values(), key=lambda g: -g["cost"])

    events = groups(lambda p: info.get(p["bet_id"], {}).get("event_id"), lambda p: p["event_title"])
    city_days = groups(lambda p: (p["station"], p["local_date"]),
                       lambda p: f"{p['city'] or p['station']} {p['local_date']}")
    daily = daily_realized_pnl(db, now)

    def cap(name, used, pct, base, group=None):
        limit = pct * base
        return {"limit_name": name, "group": group, "used": used, "limit": limit, "pct": pct,
                "share": used / limit if limit > 0 else None}
    caps = [
        cap("Total open exposure", bank.open_exposure, risk.max_open_exposure_pct, equity),
        cap("Largest event", events[0]["cost"] if events else 0.0, risk.max_event_exposure_pct, equity,
            events[0]["group"] if events else None),
        cap("Largest city-day (high and low together)", city_days[0]["cost"] if city_days else 0.0,
            risk.max_station_day_exposure_pct, equity, city_days[0]["group"] if city_days else None),
        cap("Realized loss today (UTC)", max(0.0, -daily), risk.daily_loss_limit_pct, initial),
    ]
    payout = sum(p["potential_payout"] for p in positions)
    expected = [p["expected_pnl"] for p in positions if p["expected_pnl"] is not None]
    return {
        "equity": equity, "cash": bank.cash, "starting_bankroll": initial,
        "totals": {"n": len(positions), "cost": bank.open_exposure, "value": bank.market_value,
                   "unrealized_pnl": bank.unrealized_pnl, "potential_payout": payout,
                   "max_profit": payout - bank.open_exposure,
                   "expected_pnl": sum(expected) if expected else None},
        # what equity would be if every open position lost / won
        "scenarios": {"all_lose": bank.cash, "all_win": bank.cash + payout},
        "caps": caps, "by_event": events, "by_city_day": city_days, "positions": positions,
    }


def prediction_calibration(db: Database, min_lead_days: int = 1) -> dict:
    """Calibration over ALL resolved markets (not only bets): the model's last
    prediction made at least `min_lead_days` ahead, versus what happened."""
    p, r = predictions.c, market_resolutions.c
    latest = decision_predictions(min_lead_days)
    rows = db.rows(select(p.p_yes, p.calibrated_prob, p.calibrator_version, p.market_id, r.outcome)
                   .join(latest, latest.c.pid == p.id).join(market_resolutions, r.market_id == p.market_id))
    probs = [x["p_yes"] for x in rows]
    cal = [x["p_yes"] if x["calibrated_prob"] is None else x["calibrated_prob"] for x in rows]
    outs = [1 if x["outcome"] == "YES" else 0 for x in rows]
    # market benchmark: mid-implied YES probability on the signal made from the same prediction, liquid markets
    s = signals.c
    mk = {}
    for x in db.rows(select(s.market_id, s.side, s.market_prob, s.rule_results)
                     .join(latest, latest.c.pid == s.prediction_id)):
        if (m := market_yes(x)) is not None:
            mk[x["market_id"]] = m
    paired = [(mk[x["market_id"]], c, o) for x, c, o in zip(rows, cal, outs) if x["market_id"] in mk]
    return {
        "n": len(rows), "brier_model": brier(probs, outs), "log_loss_model": log_loss(probs, outs),
        "ece_model": ece(probs, outs),
        # calibrated = what the rules used (the raw probability where no calibrator was active)
        "n_calibrated": sum(x["calibrator_version"] not in (None, "identity") for x in rows),
        "brier_calibrated": brier(cal, outs), "log_loss_calibrated": log_loss(cal, outs),
        "ece_calibrated": ece(cal, outs), "bins_calibrated": calibration_bins(cal, outs),
        # model (as used) and market on the same liquid markets
        "brier_market": brier([m for m, _, _ in paired], [o for _, _, o in paired]), "n_market": len(paired),
        "brier_model_on_market": brier([c for _, c, _ in paired], [o for _, _, o in paired]),
        "log_loss_market": log_loss([m for m, _, _ in paired], [o for _, _, o in paired]),
        "log_loss_model_on_market": log_loss([c for _, c, _ in paired], [o for _, _, o in paired]),
        "bins": calibration_bins(probs, outs),
    }


def decision_predictions(min_lead_days: int = 1):
    """Subquery: per resolved market, the id of the production model's last
    prediction made at least `min_lead_days` before the target day."""
    p, r = predictions.c, market_resolutions.c
    return (select(func.max(p.id).label("pid")).join(market_resolutions, r.market_id == p.market_id)
            .where(p.lead_days >= min_lead_days, PRODUCTION).group_by(p.market_id).subquery())


def resolved_rows(db: Database, min_lead_days: int = 1, per_lead: bool = False) -> list[dict]:
    """One row per resolved market: the production model's decision prediction
    (its last made `min_lead_days`+ days ahead), the market, the outcome `y`, the
    probability the rules used (`used`: calibrated, or raw without a calibrator),
    and the market's mid-implied YES probability (`market_yes`) and liquidity from
    the signal made from that same prediction (None for a market that failed the
    liquidity check: see market_yes()). per_lead=True instead gives one
    row per market and lead time: the last prediction made at each lead."""
    p, r, mk, s = predictions.c, market_resolutions.c, markets.c, signals.c
    if per_lead:
        latest = (select(func.max(p.id).label("pid")).join(market_resolutions, r.market_id == p.market_id)
                  .where(PRODUCTION, p.lead_days.is_not(None)).group_by(p.market_id, p.lead_days).subquery())
    else:
        latest = decision_predictions(min_lead_days)
    rows = db.rows(select(p.id.label("prediction_id"), p.market_id, p.ts, p.model_version, p.lead_days, p.mu_c,
                          p.sigma_c, p.p_yes, p.calibrated_prob, p.calibrator_version, p.inputs, mk.event_id,
                          mk.event_title, mk.question, mk.bucket_label, mk.city, mk.station, mk.kind, mk.local_date,
                          mk.unit, mk.bucket_lo, mk.bucket_hi, r.outcome)
                   .join(latest, latest.c.pid == p.id).join(markets, mk.id == p.market_id)
                   .join(market_resolutions, r.market_id == p.market_id).order_by(mk.local_date, p.market_id, p.id))
    sigs = {x["prediction_id"]: x for x in db.rows(
        select(s.prediction_id, s.side, s.market_prob, s.rule_results).join(latest, latest.c.pid == s.prediction_id)
        .order_by(s.id))}
    for x in rows:
        x["y"] = 1 if x["outcome"] == "YES" else 0
        x["used"] = x["p_yes"] if x["calibrated_prob"] is None else x["calibrated_prob"]
        sig = sigs.get(x["prediction_id"]) or {}
        x["market_yes"] = market_yes(sig)
        x["liquidity"] = next((rr.get("value") for rr in sig.get("rule_results") or []
                               if rr.get("rule") == "liquidity"), None)
    return rows


def daily_scores(rows: list[dict]) -> list[dict]:
    """Per target day, on the markets that had a market price: Brier score and
    log loss of the model (raw and as used) and of the market price, and how
    often the bucket each thought most likely won (events whose buckets all
    had a price and exactly one of which resolved YES)."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for x in rows:
        if x["market_yes"] is not None:
            by_day[x["local_date"]].append(x)
    out = []
    for day in sorted(by_day):
        xs = by_day[day]
        ys = [x["y"] for x in xs]
        events: dict[str, list[dict]] = defaultdict(list)
        for x in xs:
            events[x["event_id"]].append(x)
        whole = [ev for ev in events.values() if len(ev) >= 2 and sum(x["y"] for x in ev) == 1]
        top = lambda ev, k: max(ev, key=lambda r: r[k])["y"]  # noqa: E731
        out.append({
            "day": day, "n": len(xs),
            "brier_model": brier([x["p_yes"] for x in xs], ys), "brier_used": brier([x["used"] for x in xs], ys),
            "brier_market": brier([x["market_yes"] for x in xs], ys),
            "log_loss_model": log_loss([x["p_yes"] for x in xs], ys),
            "log_loss_used": log_loss([x["used"] for x in xs], ys),
            "log_loss_market": log_loss([x["market_yes"] for x in xs], ys),
            "n_events": len(whole),
            "top_bucket_model": statistics.fmean(top(ev, "p_yes") for ev in whole) if whole else None,
            "top_bucket_market": statistics.fmean(top(ev, "market_yes") for ev in whole) if whole else None,
        })
    return out


def _scores(probs: dict[str, float], outcome: dict[str, int], ids) -> tuple:
    ids = sorted(ids)
    ps, os_ = [probs[i] for i in ids], [outcome[i] for i in ids]
    return brier(ps, os_), log_loss(ps, os_)


def model_comparison(db: Database, min_lead_days: int = 1) -> dict:
    """Every model scored at the same moments. For each resolved market the
    moment is the cycle of the production model's last prediction made at least
    `min_lead_days` ahead; each model's prediction from that same cycle is used.
    A model is compared with production (and the market price) on exactly the
    markets it predicted, so the scores in one row are always like for like."""
    p, r, s = predictions.c, market_resolutions.c, signals.c
    latest = decision_predictions(min_lead_days)
    moment = select(p.market_id, p.ts, p.id.label("pid")).join(latest, latest.c.pid == p.id).subquery()
    rows = db.rows(select(p.id, p.market_id, p.model_version, p.role, p.p_yes, p.calibrated_prob,
                          p.calibrator_version, r.outcome)
                   .join(moment, and_(moment.c.market_id == p.market_id, moment.c.ts == p.ts))
                   .join(market_resolutions, r.market_id == p.market_id).order_by(p.id))
    outcome: dict[str, int] = {}
    production: dict[str, float] = {}
    by_model: dict[str, dict[str, float]] = defaultdict(dict)
    calibrated: dict[str, dict[str, float]] = defaultdict(dict)
    for x in rows:  # ordered by id, so a repeated cycle keeps its last prediction
        outcome[x["market_id"]] = 1 if x["outcome"] == "YES" else 0
        by_model[x["model_version"]][x["market_id"]] = x["p_yes"]
        if x["role"] in (None, "production"):
            production[x["market_id"]] = x["p_yes"]
            if x["calibrator_version"] not in (None, "identity"):
                calibrated[x["model_version"] + " calibrated"][x["market_id"]] = x["calibrated_prob"]
    market: dict[str, float] = {}
    for x in db.rows(select(s.market_id, s.side, s.market_prob, s.rule_results)
                     .join(moment, moment.c.pid == s.prediction_id)):
        if (m := market_yes(x)) is not None:
            market[x["market_id"]] = m
    roles = {x["version"]: x["role"] for x in db.rows(select(model_versions.c.version, model_versions.c.role))}
    out = []
    for version, probs in sorted({**by_model, **calibrated}.items()):
        ids = probs.keys() & production.keys()
        b, ll = _scores(probs, outcome, ids)
        pb, pll = _scores(production, outcome, ids)
        out.append({"model": version, "role": roles.get(version, "production"), "n": len(ids),
                    "brier": b, "log_loss": ll, "production_brier": pb, "production_log_loss": pll})
    ids = market.keys() & production.keys()
    b, ll = _scores(market, outcome, ids)
    pb, pll = _scores(production, outcome, ids)
    out.append({"model": "market price (mid)", "role": "benchmark", "n": len(ids), "brier": b, "log_loss": ll,
                "production_brier": pb, "production_log_loss": pll})
    return {"n_markets": len(outcome), "min_lead_days": min_lead_days, "models": out}


def performance_series(db: Database, initial: float) -> dict:
    snaps = db.rows(select(bankroll_snapshots).order_by(bankroll_snapshots.c.id))
    eq = [s["equity"] for s in snaps]
    _, _, dd = max_drawdown([initial] + eq)
    settled = db.rows(select(paper_bets).where(paper_bets.c.status.in_(["WON", "LOST"]))
                      .order_by(paper_bets.c.settled_at, paper_bets.c.id))
    cum, cum_pnl = 0.0, []
    for b in settled:
        cum += b["pnl"]
        cum_pnl.append({"t": str(b["settled_at"]), "pnl": round(cum, 4), "won": b["status"] == "WON",
                        "bet_pnl": round(b["pnl"], 4)})
    scatter = [{"model": b["model_prob"], "market": b["market_prob"], "won": b["status"] == "WON"}
               for b in db.rows(select(paper_bets))]
    return {
        "bankroll": [{"t": str(s["ts"]), "equity": round(s["equity"], 4), "cash": round(s["cash"], 4)} for s in snaps],
        "drawdown": [{"t": str(s["ts"]), "dd": round(d, 4)} for s, d in zip(snaps, dd[1:])],
        "cumulative_pnl": cum_pnl,
        "bets_scatter": scatter,
        "bet_calibration": calibration_bins([b["model_prob"] for b in settled],
                                            [1 if b["status"] == "WON" else 0 for b in settled]),
        "prediction_calibration": prediction_calibration(db),
        "model_comparison": model_comparison(db),
        "calibrators": latest_calibrators(db),
        "daily_scores": daily_scores(resolved_rows(db)),
    }


def latest_calibrators(db: Database) -> list[dict]:
    """The newest calibration fit round: one row per method."""
    pc = prob_calibrators.c
    last = db.one(select(func.max(pc.fitted_at).label("t")))
    if not last or last["t"] is None:
        return []
    return db.rows(select(pc.version, pc.method, pc.model_version, pc.fitted_at, pc.n, pc.n_train, pc.n_holdout,
                          pc.brier_before, pc.brier_after, pc.log_loss_before, pc.log_loss_after, pc.approved,
                          pc.selected, pc.reason).where(pc.fitted_at == last["t"]).order_by(pc.id))


def market_count(db: Database) -> int:
    return db.agg(select(func.count().label("n")).select_from(markets).where(markets.c.tradeable.is_(True)))["n"]
