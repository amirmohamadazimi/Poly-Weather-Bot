"""The experiment's research report (spec section 17, v2 M14): RESEARCH.md.

REPORT.md follows the experiment while it runs. This report answers the
question the experiment was run for, on the experiment's bets and predictions
up to its planned end (a database holds one experiment): did the strategy find
positive expected value, and is the evidence strong enough to believe it? It is interim while the
experiment runs, preliminary while bets from it are still open, and final
once the experiment is complete. Nothing in it is written to the database.

Section 17 says not to declare success on positive P/L alone, so the verdict
needs all five checks to pass, each shown with its numbers: enough settled
bets; returns whose 95% interval is above zero when whole market days are
resampled (bets on one day share its weather); predictions that beat the
market's prices on log loss; bets that won about as often as predicted; and a
profit that survives dropping the five best bets and holds in both halves of
the experiment.

Predictions are the learning ledger's (prediction_outcomes): each resolved
market's decision prediction, the last one made a day or more ahead. "Model"
is the probability the bot used (calibrated where a calibrator was active),
"raw" the model's before calibration, and "market" the mid price of YES when
the bot looked.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from wxbot.db import (Database, bankroll_snapshots, markets, paper_bets, prediction_outcomes, predictions, signals,
                      utcnow)
from wxbot.evaluation.metrics import LOG_LOSS_EPS, brier, calibration_bins, ece, liquid, log_loss, max_drawdown
from wxbot.evaluation.operation import operation
from wxbot.experiment import current, ends_at, progress

MIN_SETTLED = 200     # settled bets before a verdict can be more than inconclusive
TOP_N = 5             # the best bets the profit must survive without
MIN_GROUP = 5         # bets (or markets) a group needs to be named best or worst
BOOTSTRAP = 2000
SEED = 7              # fixed, so the same database gives the same report


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _loss(p: float, y: int) -> float:
    p = min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p))
    return -math.log(p if y else 1 - p)


def _mean(xs) -> float | None:
    xs = list(xs)
    return statistics.fmean(xs) if xs else None


def shape(lo, hi) -> str:
    return "or below" if lo is None else "or above" if hi is None else "range"


# -- data ---------------------------------------------------------------------------------------

def bets(db: Database, end: datetime) -> list[dict]:
    """The experiment's bets with their market and the versions that priced them
    (bets from before param sets were versioned belong to the legacy set, as in the ledger)."""
    from wxbot.learning.params import legacy
    old = legacy(db)
    b, mk, s, p = paper_bets.c, markets.c, signals.c, predictions.c
    decided = func.coalesce(s.ts, b.opened_at)   # the engine's clock when it decided to bet
    rows = db.rows(
        select(b.id, b.opened_at, decided.label("decided_at"), b.side, b.entry_price, b.stake, b.pnl, b.status,
               b.confidence, b.model_prob, b.market_prob, b.edge, b.event_id, mk.city, mk.station, mk.kind,
               mk.local_date, mk.bucket_lo, mk.bucket_hi, mk.bucket_label, mk.event_title, p.lead_days,
               p.model_version, p.params_version, p.calibrator_version)
        .join(markets, mk.id == b.market_id).outerjoin(signals, s.id == b.signal_id)
        .outerjoin(predictions, p.id == s.prediction_id)
        .where(decided < end).order_by(decided, b.id))
    for r in rows:
        r["won"] = r["status"] == "WON"
        r["settled"] = r["status"] in ("WON", "LOST")
        r["shape"] = shape(r["bucket_lo"], r["bucket_hi"])
        if r["params_version"] is None and r["model_version"] and old:
            r["params_version"] = old["version"]
    return rows


def ledger(db: Database, end: datetime) -> list[dict]:
    """Resolved markets' decision predictions made before the experiment's end. A
    market is liquid when it had a price and passed the bot's liquidity check:
    only those prices count as the market's view (metrics.market_yes)."""
    po = prediction_outcomes.c
    rows = db.rows(select(prediction_outcomes, signals.c.rule_results)
                   .outerjoin(signals, signals.c.id == po.signal_id)
                   .where(po.decision_time < end).order_by(po.local_date, po.market_id))
    for r in rows:
        r["shape"] = shape(r["bucket_lo"], r["bucket_hi"])
        r["liquid"] = r["market_yes"] is not None and liquid(r.pop("rule_results"))
    return rows


# -- statistics ---------------------------------------------------------------------------------

def cluster_ratio_ci(items: list, key: Callable, num: Callable, den: Callable) -> dict:
    """sum(num) / sum(den) with a 95% interval, resampling clusters whole."""
    sums: dict = defaultdict(lambda: [0.0, 0.0])
    for x in items:
        s = sums[key(x)]
        s[0] += num(x)
        s[1] += den(x)
    total_den = sum(v[1] for v in sums.values())
    out = {"value": sum(v[0] for v in sums.values()) / total_den if total_den else None, "lo": None, "hi": None,
           "n": len(items), "clusters": len(sums)}
    if len(sums) < 5:
        return out
    vals = list(sums.values())
    rng, m, stats = random.Random(SEED), len(vals), []
    for _ in range(BOOTSTRAP):
        pick = [vals[rng.randrange(m)] for _ in range(m)]
        d = sum(v[1] for v in pick)
        if d:
            stats.append(sum(v[0] for v in pick) / d)
    stats.sort()
    out.update(lo=stats[int(0.025 * len(stats))], hi=stats[int(0.975 * len(stats)) - 1])
    return out


def _prob(r: dict) -> float | None:
    """The probability the bet's side wins that the decision used: calibrated where a calibrator was active."""
    return r["model_prob"] if r["confidence"] is None else r["confidence"]


def bet_stats(rows: list[dict]) -> dict:
    settled = [r for r in rows if r["settled"]]
    scored = [(p, int(r["won"])) for r in settled if (p := _prob(r)) is not None]
    probs, outs = [p for p, _ in scored], [y for _, y in scored]
    staked = sum(r["stake"] for r in settled)
    pnl = sum(r["pnl"] or 0.0 for r in settled)
    won = sum(outs)
    var = sum(p * (1 - p) for p in probs)
    return {
        "n": len(rows), "settled": len(settled), "open": sum(r["status"] == "OPEN" for r in rows),
        "won": won, "staked": staked, "pnl": pnl, "roi": pnl / staked if staked else None,
        "win_rate": won / len(outs) if outs else None, "expected_win_rate": _mean(probs),
        "z": (won - sum(probs)) / math.sqrt(var) if var else None,
        "avg_stake": _mean(r["stake"] for r in rows),
        "avg_edge": _mean(r["edge"] for r in rows if r["edge"] is not None),
        "avg_prob": _mean(_prob(r) for r in rows if _prob(r) is not None),
        "avg_entry_price": _mean(r["entry_price"] for r in rows),
        "brier": brier(probs, outs), "log_loss": log_loss(probs, outs), "ece": ece(probs, outs),
    }


def prediction_stats(rows: list[dict]) -> dict:
    """The model's scores on every market (as used, and raw before calibration),
    and the model against the market's price on the liquid ones."""
    ys = [r["y"] for r in rows]
    used, raw = [r["p_used"] for r in rows], [r["p_yes"] for r in rows]
    liquid = [r for r in rows if r["liquid"]]
    ly = [r["y"] for r in liquid]
    model, mkt = [r["p_used"] for r in liquid], [r["market_yes"] for r in liquid]
    ll_model, ll_mkt = log_loss(model, ly), log_loss(mkt, ly)
    return {
        "n": len(rows), "brier_model": brier(used, ys), "brier_raw": brier(raw, ys),
        "log_loss_model": log_loss(used, ys), "log_loss_raw": log_loss(raw, ys), "ece_model": ece(used, ys),
        "share_yes": _mean(ys),
        "n_liquid": len(liquid), "log_loss_model_liquid": ll_model, "log_loss_market": ll_mkt,
        "brier_model_liquid": brier(model, ly), "brier_market": brier(mkt, ly),
        "ece_model_liquid": ece(model, ly), "ece_market": ece(mkt, ly),
        "skill": 1 - ll_model / ll_mkt if ll_model is not None and ll_mkt else None,
    }


def grouped(rows: list[dict], key: Callable, stats: Callable) -> list[dict]:
    groups: dict = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return [{"group": k, **stats(v)} for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))]


def reliability(rows: list[dict]) -> list[dict]:
    """The model's probabilities in ten bands against how often the outcome
    happened. A band is overconfident when its predictions were further from
    50% than the outcomes justify (90% predicted, 80% happened; or 5%
    predicted, 15% happened), by two standard errors or more."""
    bins = calibration_bins([r["p_used"] for r in rows], [r["y"] for r in rows])
    for b in bins:
        p, n = b["mean_pred"], b["n"]
        sd = math.sqrt(p * (1 - p) / n) if n and 0 < p < 1 else None
        z = b["z"] = (b["observed"] - p) / sd if sd else None
        b["reading"] = ("" if z is None or abs(z) < 2
                        else "overconfident" if (z < 0) == (p >= 0.5) else "underconfident")
    return bins


def concentration(rows: list[dict], start: datetime, end: datetime) -> dict:
    settled = sorted((r for r in rows if r["settled"]), key=lambda r: -(r["pnl"] or 0.0))
    total = sum(r["pnl"] or 0.0 for r in settled)
    top = settled[:TOP_N]
    mid = start + (end - start) / 2
    halves = [[r for r in settled if _utc(r["decided_at"]) < mid],
              [r for r in settled if _utc(r["decided_at"]) >= mid]]
    weeks: dict = defaultdict(list)
    for r in settled:
        weeks[(_utc(r["decided_at"]) - start).days // 7 + 1].append(r)
    staked = sum(r["stake"] for r in settled)
    return {
        "total_pnl": total, "top": [{k: r[k] for k in ("id", "local_date", "city", "kind", "bucket_label", "side",
                                                      "entry_price", "stake", "pnl")} for r in top],
        "top_pnl": sum(r["pnl"] or 0.0 for r in top),
        "without_top_pnl": total - sum(r["pnl"] or 0.0 for r in top),
        "without_top_roi": ((total - sum(r["pnl"] or 0.0 for r in top)) / (staked - sum(r["stake"] for r in top))
                            if staked - sum(r["stake"] for r in top) else None),
        "halves": [{"from": a.isoformat(), "to": b.isoformat(), **_pnl(h)}
                   for (a, b), h in zip(((start, mid), (mid, end)), halves)],
        "weeks": [{"week": w, "from": (start + timedelta(days=7 * (w - 1))).date().isoformat(), **_pnl(v)}
                  for w, v in sorted(weeks.items())],
        "roi_by_day": cluster_ratio_ci(settled, lambda r: r["local_date"], lambda r: r["pnl"] or 0.0,
                                       lambda r: r["stake"]),
    }


def _pnl(rows: list[dict]) -> dict:
    staked = sum(r["stake"] for r in rows)
    pnl = sum(r["pnl"] or 0.0 for r in rows)
    return {"bets": len(rows), "staked": staked, "pnl": pnl, "roi": pnl / staked if staked else None}


def versus_market(rows: list[dict]) -> dict:
    """Model log loss minus the market's per liquid market, averaged with a 95%
    interval that resamples whole events (the buckets of one city-day share an outcome)."""
    return cluster_ratio_ci([r for r in rows if r["liquid"]], lambda r: r["event_id"],
                            lambda r: _loss(r["p_used"], r["y"]) - _loss(r["market_yes"], r["y"]), lambda r: 1.0)


# -- the report ---------------------------------------------------------------------------------

def build(db: Database, initial: float, now: datetime | None = None) -> dict:
    from wxbot.execution.portfolio import bankroll
    now = now or utcnow()
    exp = current(db)
    end = ends_at(exp) or now
    window_end = min(end, now)
    prog = progress(db, exp, now)
    stage = {"complete": "final", "ended": "preliminary"}.get(prog["state"], "interim")
    bs, pr = bets(db, end), ledger(db, end)
    # the start: recorded, or for a database from before experiments were, its first snapshot; the first
    # cycle's decisions come seconds before its snapshot
    first = db.agg(select(func.min(bankroll_snapshots.c.ts).label("t")))["t"]
    times = [_utc(t) for t in (exp and exp["started_at"], first, bs and bs[0]["decided_at"]) if t]
    start = min(times) if times else now
    b, p = bet_stats(bs), prediction_stats(pr)
    bank = bankroll(db, initial)
    snaps = bankroll_snapshots.c
    eq = [r["equity"] for r in db.rows(select(snaps.equity).where(snaps.ts >= start, snaps.ts <= window_end)
                                       .order_by(snaps.id))]
    dd, dd_pct, _ = max_drawdown([initial] + eq)
    conc = concentration(bs, start, min(end, max(now, start)))
    vm = versus_market(pr)
    return {
        "stage": stage, "progress": prog, "generated_at": now.isoformat(),
        "experiment": exp and {k: exp[k] for k in ("name", "initial_bankroll", "started_at", "git_ref",
                                                   "planned_days")},
        "code_ref": db.get_state("code_ref"), "has_history": first is not None,
        "window": {"from": start.isoformat(), "to": end.isoformat(), "through": window_end.isoformat()},
        # "roi" and "pnl" are on settled stakes; the bankroll figures count open bets at the bid
        "performance": {**b, "starting_bankroll": initial, "ending_bankroll": bank.equity,
                        "total_pnl": bank.equity - initial, "return_on_bankroll": (bank.equity - initial) / initial,
                        "unrealized_pnl": bank.unrealized_pnl, "max_drawdown": dd, "max_drawdown_pct": dd_pct},
        "predictions": p, "versus_market": vm, "concentration": conc,
        "market_types": {"bets": grouped(bs, lambda r: f"{r['kind']}, {r['shape']}", bet_stats),
                         "predictions": grouped(pr, lambda r: f"{r['kind']}, {r['shape']}", prediction_stats)},
        "sides": grouped(bs, lambda r: r["side"], bet_stats),
        "locations": {"bets": grouped(bs, lambda r: r["city"] or r["station"], bet_stats),
                      "predictions": grouped(pr, lambda r: r["city"] or r["station"], prediction_stats)},
        "variables": grouped(pr, lambda r: r["kind"], prediction_stats),
        "leads": grouped(pr, lambda r: r["lead_days"], prediction_stats),
        "reliability": reliability(pr),
        "bet_prices": grouped(bs, lambda r: _price_band(r["entry_price"]), bet_stats),
        "largest_errors": [{k: r[k] for k in ("market_id", "local_date", "city", "kind", "bucket_lo", "bucket_hi",
                                              "unit", "p_used", "market_yes", "liquid", "outcome", "bet_status",
                                              "bet_pnl")}
                           | {"log_loss": _loss(r["p_used"], r["y"])}
                           for r in sorted(pr, key=lambda r: -_loss(r["p_used"], r["y"]))[:10]],
        "versions": {"predictions": grouped(pr, _version, prediction_stats),
                     "bets": grouped(bs, _version, bet_stats)},
        "operation": operation(db, exp, window_end),
        "verdict": verdict(b, p, vm, conc),
    }


def _price_band(p: float | None) -> str:
    if p is None:
        return "unknown"
    return next(label for cut, label in ((0.5, "0.00–0.50"), (0.8, "0.50–0.80"), (0.9, "0.80–0.90"),
                                         (0.95, "0.90–0.95"), (2, "0.95+")) if p < cut)


def _version(r: dict) -> str:
    return " · ".join(str(r.get(k) or "–") for k in ("model_version", "params_version", "calibrator_version"))


def verdict(b: dict, p: dict, vm: dict, conc: dict) -> dict:
    roi = conc["roi_by_day"]
    halves = conc["halves"]
    checks = [
        {"check": "Enough settled bets", "passed": b["settled"] >= MIN_SETTLED,
         "detail": f"{b['settled']} settled; {MIN_SETTLED} needed before a profit or loss means much"},
        {"check": "Returns above zero", "passed": roi["lo"] is not None and roi["lo"] > 0,
         "detail": (f"ROI on stakes {_pct(roi['value'])}, 95% interval {_pct(roi['lo'])} to {_pct(roi['hi'])} "
                    f"resampling {roi['clusters']} market days" if roi["lo"] is not None
                    else f"ROI on stakes {_pct(roi['value'])}; an interval needs 5+ market days with settled bets")},
        {"check": "Better than the market", "passed": vm["hi"] is not None and vm["hi"] < 0,
         "detail": (f"log loss {_num(p['log_loss_model_liquid'])} vs the market's {_num(p['log_loss_market'])} on "
                    f"{p['n_liquid']} liquid markets; difference {_num(vm['value'])} (95% interval {_num(vm['lo'])} "
                    f"to {_num(vm['hi'])}, resampling {vm['clusters']} events; below zero is better)"
                    if vm["value"] is not None else "no resolved liquid markets yet")},
        {"check": "Bets won as often as predicted", "passed": b["z"] is not None and abs(b["z"]) < 2,
         "detail": (f"won {_pct(b['win_rate'])} against {_pct(b['expected_win_rate'])} predicted "
                    f"({b['z']:+.1f} standard errors; within ±2 passes)" if b["z"] is not None
                    else "no settled bets yet")},
        {"check": "Profit not resting on a few bets", "passed": conc["without_top_pnl"] > 0
         and all(h["pnl"] > 0 for h in halves if h["bets"]) and sum(h["bets"] > 0 for h in halves) == 2,
         "detail": (f"P/L {_usd(conc['total_pnl'])}; without the {TOP_N} best bets {_usd(conc['without_top_pnl'])}; "
                    f"first half {_usd(halves[0]['pnl'])}, second half {_usd(halves[1]['pnl'])}")},
    ]
    passed = sum(c["passed"] for c in checks)
    if roi["hi"] is not None and roi["hi"] < 0:
        conclusion = "NOT SUPPORTED: the strategy lost money, and the 95% interval of its returns is below zero."
    elif vm["lo"] is not None and vm["lo"] > 0:
        conclusion = ("NOT SUPPORTED: the model's probabilities were reliably worse than the market's prices, so "
                      "there is no edge to bet on.")
    elif passed == len(checks):
        conclusion = ("SUPPORTED: every check passed. The strategy's positive expected value is supported by this "
                      "experiment; it still needs to hold on new markets.")
    elif not checks[0]["passed"]:
        conclusion = (f"INCONCLUSIVE: {b['settled']} settled bets are too few to tell skill from luck; "
                      f"{passed} of {len(checks)} checks passed.")
    else:
        conclusion = f"INCONCLUSIVE: {passed} of {len(checks)} checks passed; see each check below."
    return {"conclusion": conclusion, "checks": checks, "passed": passed}


# -- markdown -----------------------------------------------------------------------------------

def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x, nd=4) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def _usd(x) -> str:
    return "n/a" if x is None else f"{'-' if x < 0 else ''}${abs(x):,.2f}"


def _signed(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}"


def _bet(e: dict) -> str:
    if not e["bet_status"]:
        return "–"
    return e["bet_status"] if e["bet_pnl"] is None else f"{e['bet_status']} {_usd(e['bet_pnl'])}"


def _bets_table(groups: list[dict], title: str) -> list[str]:
    out = [f"| {title} | Bets | Settled | Won | Predicted | P/L | ROI |", "|---|---:|---:|---:|---:|---:|---:|"]
    out += [f"| {g['group']} | {g['n']} | {g['settled']} | {_pct(g['win_rate'])} | {_pct(g['expected_win_rate'])} | "
            f"{_usd(g['pnl'])} | {_pct(g['roi'])} |" for g in groups]
    return out


def _pred_table(groups: list[dict], title: str) -> list[str]:
    out = [f"| {title} | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    out += [f"| {g['group']} | {g['n']} | {_num(g['log_loss_model'])} | {_num(g['brier_model'])} | {g['n_liquid']} | "
            f"{_num(g['log_loss_model_liquid'])} | {_num(g['log_loss_market'])} | {_pct(g['skill'])} |"
            for g in groups]
    return out


def _best_worst(groups: list[dict], n_key: str, key: str, fmt: Callable) -> str:
    ok = [g for g in groups if g[n_key] >= MIN_GROUP and g[key] is not None]
    if len(ok) < 2:
        return f"too few groups with {MIN_GROUP}+ to rank"
    ok.sort(key=lambda g: g[key])
    best, worst = ok[-3:][::-1], ok[:3]

    def names(gs: list[dict]) -> str:
        return ", ".join(f"{g['group']} ({fmt(g[key])})" for g in gs)
    return f"best {names(best)}; worst {names(worst)}"


def to_markdown(rep: dict) -> str:
    exp, perf, p, v, conc = rep["experiment"], rep["performance"], rep["predictions"], rep["verdict"], \
        rep["concentration"]
    prog = rep["progress"]
    stage = {"final": "Final", "preliminary": "Preliminary", "interim": "Interim"}[rep["stage"]]
    status = {"final": "the experiment is complete: every bet has settled",
              "preliminary": f"the experiment has ended; {prog.get('open_bets')} bets are still to settle",
              "interim": (f"day {prog.get('day')} of {prog.get('planned_days')}" if prog.get("planned_days")
                          else f"day {prog.get('day')}, no planned end" if prog.get("day")
                          else "no planned end")}[rep["stage"]]
    lines = [
        "# Research report: " + (exp["name"] if exp else "experiment recorded before experiments were named"
                                 if rep["has_history"] else "no experiment yet"), "",
        f"**{stage}** ({status}). Mode: **PAPER TRADING**, real money used: **$0.00**.", "",
        f"Window: {rep['window']['from'][:16].replace('T', ' ')} to {rep['window']['to'][:16].replace('T', ' ')} UTC"
        + (f" · {exp['planned_days']} days" if exp and exp.get("planned_days") else "")
        + (f" · code {exp['git_ref'][:12]}" if exp and exp.get("git_ref") else "")
        + (f" (last {rep['code_ref'][:12]})" if rep.get("code_ref") and exp and rep["code_ref"] != exp.get("git_ref")
           else "")
        + f" · generated {rep['generated_at'][:16].replace('T', ' ')} UTC", "",
        "## Verdict", "", f"**{v['conclusion']}**", "",
        "| Check | Result | Evidence |", "|---|---|---|",
        *[f"| {c['check']} | {'pass' if c['passed'] else 'fail'} | {c['detail']} |" for c in v["checks"]],
        "", "Success needs every check, not a positive P/L alone (spec section 17).", "",
        "## Performance", "",
        "| Metric | Value |", "|---|---:|",
        f"| Starting bankroll | {_usd(perf['starting_bankroll'])} |",
        f"| Ending bankroll{' (open bets at the bid)' if perf['open'] else ''} | {_usd(perf['ending_bankroll'])} |",
        f"| Total P/L | {_usd(perf['total_pnl'])} |",
        f"| Return on the starting bankroll | {_pct(perf['return_on_bankroll'])} |",
        f"| ROI on settled stakes | {_pct(perf['roi'])} |",
        f"| Bets (settled / open) | {perf['n']} ({perf['settled']} / {perf['open']}) |",
        f"| Win rate (predicted) | {_pct(perf['win_rate'])} ({_pct(perf['expected_win_rate'])}) |",
        f"| Average bet | {_usd(perf['avg_stake'])} |",
        f"| Average edge (probability minus price) | {_pct(perf['avg_edge'])} |",
        f"| Average predicted probability | {_pct(perf['avg_prob'])} |",
        f"| Average entry price | {_num(perf['avg_entry_price'], 3)} |",
        f"| Brier score / log loss of the bets | {_num(perf['brier'])} / {_num(perf['log_loss'])} |",
        f"| Calibration error of the bets (ECE) | {_pct(perf['ece'])} |",
        f"| Maximum drawdown | {_usd(perf['max_drawdown'])} ({_pct(perf['max_drawdown_pct'])}) |",
        "",
        "## Predictions", "",
        f"Every resolved market the model predicted, and the {p['n_liquid']} liquid ones (a market price, and "
        "enough liquidity to pass the bot's own check before betting), where the market's price is a real "
        "forecast to compare against. Lower is better for every score; skill is the share of the market's log loss "
        "the model avoided.", "",
        "| Score | Model | Raw model | Market |", "|---|---:|---:|---:|",
        f"| Log loss, all {p['n']} markets | {_num(p['log_loss_model'])} | {_num(p['log_loss_raw'])} | |",
        f"| Brier score, all markets | {_num(p['brier_model'])} | {_num(p['brier_raw'])} | |",
        f"| Calibration error (ECE), all markets | {_pct(p['ece_model'])} | | |",
        f"| Log loss, {p['n_liquid']} liquid markets | {_num(p['log_loss_model_liquid'])} | | "
        f"{_num(p['log_loss_market'])} |",
        f"| Brier score, liquid markets | {_num(p['brier_model_liquid'])} | | {_num(p['brier_market'])} |",
        f"| Calibration error (ECE), liquid markets | {_pct(p['ece_model_liquid'])} | | {_pct(p['ece_market'])} |",
        f"| Skill against the market | {_pct(p['skill'])} | | |",
        "",
        "## Was the edge stable?", "",
        f"P/L {_usd(conc['total_pnl'])}. The {TOP_N} best bets made {_usd(conc['top_pnl'])}; without them the "
        f"rest made {_usd(conc['without_top_pnl'])} (ROI {_pct(conc['without_top_roi'])}).", "",
        "| Period | Bets | Staked | P/L | ROI |", "|---|---:|---:|---:|---:|",
        *[f"| {name} half (from {h['from'][:10]}) | {h['bets']} | {_usd(h['staked'])} | {_usd(h['pnl'])} | "
          f"{_pct(h['roi'])} |" for name, h in zip(("First", "Second"), conc["halves"])],
        *[f"| Week {w['week']} (from {w['from']}) | {w['bets']} | {_usd(w['staked'])} | {_usd(w['pnl'])} | "
          f"{_pct(w['roi'])} |" for w in conc["weeks"]],
        "",
        "## Market types", "",
        *_bets_table(rep["market_types"]["bets"], "Bets on"), "",
        *_pred_table(rep["market_types"]["predictions"], "Predictions on"), "",
        *_bets_table(rep["sides"], "Side"), "",
        "## Locations", "",
        f"By P/L of bets: {_best_worst(rep['locations']['bets'], 'settled', 'pnl', _usd)}.", "",
        f"By skill against the market: {_best_worst(rep['locations']['predictions'], 'n_liquid', 'skill', _pct)}.",
        "", *_bets_table(rep["locations"]["bets"], "City"), "",
        *_pred_table(rep["locations"]["predictions"], "City"), "",
        "## Weather variables", "",
        "Which was more predictable: the day's highest or lowest temperature"
        + (", and how far ahead." if len(rep["leads"]) > 1 else "."), "",
        *_pred_table(rep["variables"], "Variable"), "",
        *([*_pred_table(rep["leads"], "Days ahead"), ""] if len(rep["leads"]) > 1 else []),
        "## Over- and underconfidence", "",
        "The model's probability in bands against how often the outcome happened. A band is flagged when the "
        "gap is two standard errors or more.", "",
        "| Predicted | Markets | Predicted mean | Happened | Standard errors | Reading |",
        "|---|---:|---:|---:|---:|---|",
        *[f"| {b['bin'].replace('-', '–')} | {b['n']} | {_pct(b['mean_pred'])} | {_pct(b['observed'])} | "
          f"{_signed(b['z'])} | {b['reading']} |" for b in rep["reliability"]],
        "", *_bets_table(rep["bet_prices"], "Bets at entry price"), "",
        "## Largest errors", "",
        "The ten predictions with the highest log loss. The market's price is shown for liquid markets only.", "",
        "| Day | City | Variable | Bucket | Model | Market | Outcome | Bet | Log loss |",
        "|---|---|---|---|---:|---:|---|---|---:|",
        *[f"| {e['local_date']} | {e['city']} | {e['kind']} | {_bucket(e)} | {_pct(e['p_used'])} | "
          f"{_pct(e['market_yes']) if e['liquid'] else 'illiquid'} | {e['outcome']} | {_bet(e)} | "
          f"{_num(e['log_loss'], 2)} |"
          for e in rep["largest_errors"]],
        "",
        "## Model versions", "",
        "Model · station bias/spread set · probability calibrator.", "",
        *_pred_table(rep["versions"]["predictions"], "Version"), "",
        *_bets_table(rep["versions"]["bets"], "Version"),
    ]
    from wxbot.report import operation_lines
    lines += operation_lines(rep["operation"])
    lines += [
        "", "## How this was computed", "",
        "- Window: bets placed and predictions made up to the experiment's planned end. Predictions "
        "are each resolved market's decision prediction (the last made a day or more ahead), from the learning "
        "ledger.",
        "- The market comparison uses liquid markets only: those with a price that passed the bot's liquidity "
        "check (strategy.min_liquidity_usd) when it looked. A thin market's mid price is a placeholder of a "
        "near-empty book (often 0.34 or 0.40), and comparing against it makes any model look better than the "
        "market.",
        f"- Intervals are 95% bootstrap intervals ({BOOTSTRAP} resamples, seed {SEED}): returns resample whole market "
        f"days, log-loss differences resample whole events, because outcomes on one day or one event move "
        f"together.",
        f"- The verdict needs {MIN_SETTLED}+ settled bets, returns above zero, log loss below the market's on liquid "
        f"markets, a win "
        f"rate within two standard errors of the predicted one, and a profit without the {TOP_N} best bets and in "
        f"both halves.",
        "- Regenerate with `python main.py research` on the experiment's database.",
    ]
    return "\n".join(lines) + "\n"


def _bucket(e: dict) -> str:
    unit = "°F" if e.get("unit") == "F" else "°C"
    lo, hi = e["bucket_lo"], e["bucket_hi"]
    if lo is None:
        return f"{hi:g}{unit} or below"
    if hi is None:
        return f"{lo:g}{unit} or above"
    return f"{lo:g}{unit}" if lo == hi else f"{lo:g}–{hi:g}{unit}"
