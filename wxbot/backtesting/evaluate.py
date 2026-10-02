"""Score replayed decisions and simulate the betting rules on them.

Scores. Every source is scored on the same rows (those where all five have a
probability), each clipped to [model.prob_floor, model.prob_ceiling] as the
model is. Differences against the market get a 95% interval from a bootstrap
that resamples whole events (all buckets and leads of one city, day and
high/low together), because those rows are not independent.

Strategy. The live rules (wxbot/strategy/rules.py) decide each row, in
decision-time order, at most one bet per market. The ask is the historical
price plus `half_spread` (the NO ask is 1 - price + half_spread), then the
configured slippage and fee. Two rules cannot be replayed (NOT_REPLAYED).
* Flat stake: $1 on every bet, no bankroll: is there an edge at all?
* Bankroll: the configured sizer and every risk cap from strategy, sizing and
  risk, starting at bankroll.initial; bets settle when their result was known.
"""
from __future__ import annotations

import heapq
import math
import random
import statistics
from collections import defaultdict

from wxbot.evaluation.metrics import brier, calibration_bins, ece, log_loss, max_drawdown
from wxbot.strategy import rules
from wxbot.strategy.sizing import make_sizer

SOURCES = (("climatology", "p_climatology"), ("raw_forecast", "p_raw_forecast"), ("model", "p_model"),
           ("calibrated", "p_calibrated"), ("market", "market_prob"))
LABELS = {"climatology": "Climatology (naive)", "raw_forecast": "Raw forecast", "model": "Model",
          "calibrated": "Calibrated model", "market": "Market price"}
NOT_REPLAYED = {
    "liquidity": "the liquidity Polymarket shows for a closed market is from after it closed",
    "data_quality_freshness": "forecasts are used from when they were surely available; fetch age does not apply",
    "book_depth": "the historical order book is not available: every bet is assumed to fill at the ask",
}


def _clip(p: float, cfg) -> float:
    return min(cfg.model.prob_ceiling, max(cfg.model.prob_floor, p))


def _loss(p: float, y: int) -> float:
    return -math.log(p) if y else -math.log(1 - p)


def cluster_mean_ci(pairs: list[tuple[object, float]], n_boot: int = 2000, seed: int = 7) -> dict:
    """Mean of the values with a 95% interval, resampling clusters (keys) whole."""
    sums: dict = defaultdict(float)
    counts: dict = defaultdict(int)
    for k, v in pairs:
        sums[k] += v
        counts[k] += 1
    n = sum(counts.values())
    if not n:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "clusters": 0}
    keys = list(sums)
    out = {"mean": sum(sums.values()) / n, "lo": None, "hi": None, "n": n, "clusters": len(keys)}
    if len(keys) < 5:
        return out
    s, c = [sums[k] for k in keys], [counts[k] for k in keys]
    rng, m = random.Random(seed), len(keys)
    stats = []
    for _ in range(n_boot):
        idx = [rng.randrange(m) for _ in range(m)]
        stats.append(sum(s[i] for i in idx) / sum(c[i] for i in idx))
    stats.sort()
    out.update(lo=stats[int(0.025 * n_boot)], hi=stats[int(0.975 * n_boot) - 1])
    return out


def scores(rows: list[dict], cfg, n_boot: int = 2000) -> dict:
    common = [r for r in rows if all(r[k] is not None for _, k in SOURCES)]
    ys = [r["outcome"] for r in common]
    probs = {name: [_clip(r[key], cfg) for r in common] for name, key in SOURCES}
    market = probs["market"]
    out = {"n_rows": len(rows), "n_common": len(common), "n_markets": len({r["market_id"] for r in common}),
           "n_events": len({r["event_id"] for r in common}), "sources": []}
    for name, key in SOURCES:
        p = probs[name]
        entry = {"source": name, "label": LABELS[name], "n_available": sum(r[key] is not None for r in rows),
                 "brier": brier(p, ys), "log_loss": log_loss(p, ys), "ece": ece(p, ys)}
        if name != "market" and common:
            entry["brier_minus_market"] = cluster_mean_ci(
                [(r["event_id"], (a - y) ** 2 - (b - y) ** 2) for r, a, b, y in zip(common, p, market, ys)], n_boot)
            entry["log_loss_minus_market"] = cluster_mean_ci(
                [(r["event_id"], _loss(a, y) - _loss(b, y)) for r, a, b, y in zip(common, p, market, ys)], n_boot)
        out["sources"].append(entry)
    by_lead = defaultdict(list)
    for i, r in enumerate(common):
        by_lead[r["lead_days"]].append(i)
    out["by_lead"] = [{"lead_days": lead, "lead_hours": common[idx[0]]["lead_hours"], "n": len(idx),
                       **{name: brier([probs[name][i] for i in idx], [ys[i] for i in idx]) for name, _ in SOURCES}}
                      for lead, idx in sorted(by_lead.items())]
    out["calibration"] = {name: calibration_bins(probs[name], ys) for name in ("model", "calibrated", "market")}
    return out


def _quote(r: dict, p_yes: float, half_spread: float, strategy) -> tuple[str, float, float | None, float]:
    """-> (side, probability it wins, expected entry price or None, its mid price)."""
    price = r["market_prob"]
    yes_ask, no_ask = price + half_spread, 1 - price + half_spread
    quotes = {"YES": (p_yes, yes_ask if yes_ask < 1 else None, price),
              "NO": (1 - p_yes, no_ask if no_ask < 1 else None, 1 - price)}
    side = rules.best_side(quotes)
    prob, ask, mid = quotes[side]
    return side, prob, rules.quoted_entry(ask, strategy), mid


def _context(r: dict, side: str, prob: float, entry: float | None, mid: float, cfg, daily_pnl: float,
             initial: float) -> rules.Context:
    return rules.Context(
        side=side, model_prob=prob, market_prob=mid, entry_price=entry,
        liquidity=cfg.strategy.min_liquidity_usd,  # not replayed: see NOT_REPLAYED
        lead_hours=r["lead_hours"], n_models=r["n_models"], forecast_age_min=0.0, sigma_c=r["sigma_c"],
        market_open=True, has_position=False, daily_pnl=daily_pnl, initial_bankroll=initial)


def _won(side: str, outcome: int) -> bool:
    return (side == "YES") == (outcome == 1)


def flat_stake(rows: list[dict], cfg, prob_key: str = "p_calibrated", half_spread: float | None = None,
               n_boot: int = 2000, record: bool = False) -> dict:
    """$1 on every row the rules pass, first passing row per market. With
    `record`, each row gets the decision (side, entry_price, decision, reason,
    pnl_per_dollar) for storage."""
    hs = float(cfg.backtest.half_spread) if half_spread is None else half_spread
    held: set = set()
    bets = []
    for r in sorted(rows, key=lambda r: (r["decision_time"], r["market_id"])):
        p = r[prob_key]
        if p is None:
            continue
        if r["market_id"] in held:
            if record:
                r.update(side=None, entry_price=None, decision="HELD", reason="already bet at an earlier lead",
                         pnl_per_dollar=None)
            continue
        side, prob, entry, mid = _quote(r, p, hs, cfg.strategy)
        failed = rules.failed(rules.evaluate(_context(r, side, prob, entry, mid, cfg, 0.0, 1.0), cfg))
        pnl = None
        if not failed:
            held.add(r["market_id"])
            pnl = (1 / entry - 1) if _won(side, r["outcome"]) else -1.0
            bets.append({"event_id": r["event_id"], "side": side, "lead_days": r["lead_days"], "prob": prob,
                         "entry": entry, "won": _won(side, r["outcome"]), "pnl": pnl})
        if record:
            r.update(side=side, entry_price=entry, decision="NO_BET" if failed else "BET",
                     reason="failed: " + ", ".join(failed) if failed else "all replayed rules passed",
                     pnl_per_dollar=pnl)
    return {"half_spread": hs, "prob": prob_key, **_bet_summary(bets, n_boot),
            "by_lead": {lead: _bet_summary([b for b in bets if b["lead_days"] == lead], 0)
                        for lead in sorted({b["lead_days"] for b in bets})},
            "by_side": {side: _bet_summary([b for b in bets if b["side"] == side], 0)
                        for side in sorted({b["side"] for b in bets})}}


def _bet_summary(bets: list[dict], n_boot: int) -> dict:
    if not bets:
        return {"bets": 0}
    out = {"bets": len(bets), "won": sum(b["won"] for b in bets),
           "win_rate": statistics.fmean(b["won"] for b in bets),
           "mean_predicted": statistics.fmean(b["prob"] for b in bets),
           "mean_entry": statistics.fmean(b["entry"] for b in bets),
           "pnl": sum(b["pnl"] for b in bets)}
    roi = cluster_mean_ci([(b["event_id"], b["pnl"]) for b in bets], n_boot) if n_boot else None
    out["roi"] = out["pnl"] / len(bets)
    if roi:
        out["roi_lo"], out["roi_hi"] = roi["lo"], roi["hi"]
    return out


def bankroll(rows: list[dict], cfg, prob_key: str = "p_calibrated") -> dict:
    """The live sizing and risk caps on a virtual bankroll. Equity for sizing is
    cash plus open bets at cost (the bot marks them to market)."""
    initial = float(cfg.bankroll.initial)
    hs = float(cfg.backtest.half_spread)
    s, risk = cfg.strategy, cfg.risk
    sizer = make_sizer(cfg)
    cash, realized = initial, 0.0
    open_heap: list = []                      # (known_at, seq, bet)
    open_by_event: dict = defaultdict(float)
    open_by_day: dict = defaultdict(float)
    pnl_by_day: dict = defaultdict(float)     # realized P/L per UTC day of settlement
    held: set = set()
    curve, bets, seq = [], [], 0

    def settle(until):
        nonlocal cash, realized
        while open_heap and (until is None or open_heap[0][0] <= until):
            known_at, _, b = heapq.heappop(open_heap)
            payout = b["shares"] if b["won"] else 0.0
            cash += payout
            realized += payout - b["stake"]
            pnl_by_day[known_at.date()] += payout - b["stake"]
            open_by_event[b["event_id"]] -= b["stake"]
            open_by_day[b["day"]] -= b["stake"]
            curve.append((known_at, cash + sum(x[2]["stake"] for x in open_heap)))

    for r in sorted(rows, key=lambda r: (r["decision_time"], r["market_id"])):
        settle(r["decision_time"])
        p = r[prob_key]
        if p is None or r["market_id"] in held:
            continue
        side, prob, entry, mid = _quote(r, p, hs, s)
        ctx = _context(r, side, prob, entry, mid, cfg, pnl_by_day[r["decision_time"].date()], initial)
        if rules.failed(rules.evaluate(ctx, cfg)):
            continue
        exposure = sum(x[2]["stake"] for x in open_heap)
        equity = cash + exposure
        day = (r["station"], r["local_date"])
        caps = {"sizer": sizer.stake(equity, prob, entry), "max_bet": risk.max_bet_pct * equity,
                "open_exposure_room": risk.max_open_exposure_pct * equity - exposure,
                "event_exposure_room": risk.max_event_exposure_pct * equity - open_by_event[r["event_id"]],
                "station_day_exposure_room": risk.max_station_day_exposure_pct * equity - open_by_day[day],
                "cash": cash}
        ctx.stake = max(0.0, min(caps.values()))
        if rules.failed(rules.evaluate(ctx, cfg)):
            continue
        b = {"event_id": r["event_id"], "day": day, "stake": ctx.stake, "shares": ctx.stake / entry,
             "won": _won(side, r["outcome"])}
        cash -= b["stake"]
        open_by_event[r["event_id"]] += b["stake"]
        open_by_day[day] += b["stake"]
        held.add(r["market_id"])
        seq += 1
        heapq.heappush(open_heap, (r["known_at"], seq, b))
        bets.append(b)
    settle(None)
    equity = [initial] + [e for _, e in curve]
    dd, dd_pct, _ = max_drawdown(equity)
    final = cash
    staked = sum(b["stake"] for b in bets)
    return {"initial": initial, "final": final, "pnl": final - initial, "roi": (final - initial) / initial,
            "bets": len(bets), "won": sum(b["won"] for b in bets), "staked": staked,
            "return_on_stakes": (final - initial) / staked if staked else None,
            "max_drawdown": dd, "max_drawdown_pct": dd_pct,
            "curve": [{"t": t.isoformat(), "equity": round(e, 4)} for t, e in curve]}


def evaluate(rows: list[dict], cfg) -> dict:
    b = cfg.backtest
    n_boot = int(b.get("bootstrap", 2000))
    main = flat_stake(rows, cfg, "p_calibrated", n_boot=n_boot, record=True)
    return {
        "scores": scores(rows, cfg, n_boot),
        "flat_stake": main,
        "flat_stake_by_source": {name: flat_stake(rows, cfg, key, n_boot=n_boot) if name != "calibrated" else main
                                 for name, key in SOURCES if name != "market"},
        "half_spread_sensitivity": [
            {"half_spread": hs, **{k: v for k, v in flat_stake(rows, cfg, "p_calibrated", hs, n_boot=0).items()
                                   if k in ("bets", "win_rate", "mean_predicted", "roi", "pnl")}}
            for hs in b.get("half_spread_sensitivity", [])],
        "bankroll": bankroll(rows, cfg),
        "not_replayed": NOT_REPLAYED,
    }
