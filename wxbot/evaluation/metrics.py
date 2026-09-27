"""Performance and calibration metrics for the dashboard and the final report."""
from __future__ import annotations

import random
import statistics

from sqlalchemy import func, select

from wxbot.db import Database, bankroll_snapshots, market_resolutions, markets, paper_bets, predictions, signals


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


def calibration_bins(probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict]:
    bins = [[] for _ in range(n_bins)]
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


def overview(db: Database, initial: float) -> dict:
    from wxbot.execution.portfolio import bankroll
    bets = db.rows(select(paper_bets).order_by(paper_bets.c.id))
    settled = [b for b in bets if b["status"] in ("WON", "LOST")]
    wins = [b for b in settled if b["status"] == "WON"]
    staked = sum(b["stake"] for b in settled)
    pnl = sum(b["pnl"] for b in settled)
    bank = bankroll(db, initial)
    eq = [r["equity"] for r in db.rows(select(bankroll_snapshots.c.equity).order_by(bankroll_snapshots.c.id))]
    dd, dd_pct, _ = max_drawdown([initial] + eq)
    probs = [b["model_prob"] for b in settled]
    outs = [1 if b["status"] == "WON" else 0 for b in settled]
    ci = bootstrap_roi_ci([b["stake"] for b in settled], [b["pnl"] for b in settled])
    return {
        "mode": "PAPER TRADING", "real_money": 0.0,
        "starting_bankroll": initial, "cash": bank.cash, "open_exposure": bank.open_exposure,
        "equity": bank.equity, "total_pnl": bank.equity - initial, "realized_pnl": pnl,
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


def prediction_calibration(db: Database, min_lead_days: int = 1) -> dict:
    """Calibration over ALL resolved markets (not only bets): the model's last
    prediction made at least `min_lead_days` ahead, versus what happened."""
    p, r = predictions.c, market_resolutions.c
    latest = (select(func.max(p.id).label("pid")).join(market_resolutions, r.market_id == p.market_id)
              .where(p.lead_days >= min_lead_days).group_by(p.market_id).subquery())
    rows = db.rows(select(p.p_yes, p.market_id, r.outcome).join(latest, latest.c.pid == p.id)
                   .join(market_resolutions, r.market_id == p.market_id))
    probs = [x["p_yes"] for x in rows]
    outs = [1 if x["outcome"] == "YES" else 0 for x in rows]
    # market benchmark: mid-implied YES probability on the signal made from the same prediction
    s = signals.c
    mk = {}
    for x in db.rows(select(s.market_id, s.side, s.market_prob).join(latest, latest.c.pid == s.prediction_id)):
        if x["market_prob"] is not None:
            mk[x["market_id"]] = x["market_prob"] if x["side"] == "YES" else 1 - x["market_prob"]
    paired = [(mk[x["market_id"]], o) for x, o in zip(rows, outs) if x["market_id"] in mk]
    return {
        "n": len(rows), "brier_model": brier(probs, outs),
        "brier_market": brier([a for a, _ in paired], [o for _, o in paired]), "n_market": len(paired),
        "bins": calibration_bins(probs, outs),
    }


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
    }


def market_count(db: Database) -> int:
    return db.one(select(func.count().label("n")).select_from(markets).where(markets.c.tradeable.is_(True)))["n"]
