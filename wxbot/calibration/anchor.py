"""Market anchor: bet only where the model adds something to the market price.

Both paper experiments lost money although each bet looked like a large edge:
on markets with a real two-sided book the market's price was the better
forecast (research report, M14), and the bets sat exactly where the model
disagreed with the price most, which is where the model was most often wrong.
A model that knows nothing the price does not has no edge to bet on, however
confident it is.

The probability the betting rules use is therefore the model's combined with
the market's mid price,

    anchored = sigmoid(a * logit(p_model) + b * logit(p_market) + c),

fitted by logistic regression on resolved markets. a = 0 means the price is all
that counts; a > 0 means the model carries information the price does not.

Training data: as for the calibrators (fit.py), one row per resolved market:
the production model's last prediction made at least strategy.min_lead_hours
before the end of the market's local day (and priced with the param set in
use), next to the market's book in the latest snapshot at or before it. Only
markets whose book was tight then count (both sides quoted, spread at most
max_spread, liquidity at least strategy.min_liquidity_usd), because the mid of
a wide book is not a price anyone could trade at.

Approval: rows are ordered by decision time and the newest holdout_fraction is
held out. The anchor is fitted on the older rows and approved only if, on the
holdout, its Brier score and log loss are both lower than the market price's,
at least min_markets markets were available, and the log-loss gain over the
price holds in min_confidence of 2,000 bootstrap resamples. Every fit is kept
in market_anchors and the newest one at or before a cycle is in force. While it
is not approved the market_anchor rule fails and no bet is placed; predictions
and signals are still recorded, so the evidence keeps building.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, select

from wxbot.calibration.fit import _utc, day_end, gain_confidence
from wxbot.calibration.methods import logit, sigmoid
from wxbot.db import Database, market_anchors, market_resolutions, market_snapshots, markets, predictions
from wxbot.evaluation.metrics import PRODUCTION, brier, log_loss
from wxbot.learning.params import version_match

RIDGE = 1e-3   # keeps the fit finite when the data are separable


@dataclass
class Anchor:
    version: str
    params: dict
    prob_floor: float = 0.01
    prob_ceiling: float = 0.99

    def __call__(self, p_model: float, p_market: float) -> float:
        z = self.params["a"] * logit(p_model) + self.params["b"] * logit(p_market) + self.params["c"]
        return min(self.prob_ceiling, max(self.prob_floor, sigmoid(z)))


def tight_mid(bid: float | None, ask: float | None, max_spread: float) -> float | None:
    """The YES mid when both sides are quoted and the spread is at most
    `max_spread`; None otherwise."""
    if bid is None or ask is None or not 0 < bid < ask < 1 or ask - bid > max_spread + 1e-9:
        return None
    return (bid + ask) / 2


def fit_anchor(p_model: list[float], p_market: list[float], outcomes: list[int], iterations: int = 50) -> dict:
    """Logistic regression of the outcome on logit(p_model), logit(p_market)
    and a constant, by Newton's method with a small ridge."""
    xs = [(logit(m), logit(k), 1.0) for m, k in zip(p_model, p_market)]
    beta = [0.0, 1.0, 0.0]   # start from "the market price is right"
    for _ in range(iterations):
        g = [RIDGE * b for b in beta]
        h = [[RIDGE if i == j else 0.0 for j in range(3)] for i in range(3)]
        for x, y in zip(xs, outcomes):
            p = sigmoid(sum(b * v for b, v in zip(beta, x)))
            w = p * (1 - p)
            for i in range(3):
                g[i] += (p - y) * x[i]
                for j in range(3):
                    h[i][j] += w * x[i] * x[j]
        step = _solve(h, g)
        beta = [b - s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return {"a": beta[0], "b": beta[1], "c": beta[2]}


def _solve(m: list[list[float]], v: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (the ridge keeps m invertible)."""
    n = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for i in range(n):
        piv = max(range(i, n), key=lambda k: abs(a[k][i]))
        a[i], a[piv] = a[piv], a[i]
        for k in range(i + 1, n):
            f = a[k][i] / a[i][i]
            for j in range(i, n + 1):
                a[k][j] -= f * a[i][j]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (a[i][n] - sum(a[i][j] * x[j] for j in range(i + 1, n))) / a[i][i]
    return x


def training_set(db: Database, cfg, model_version: str, fit_time: datetime,
                 param_set: dict | None = None) -> list[tuple[datetime, float, float, int]]:
    """[(decision time, model p_yes, market YES mid, outcome 1/0)], oldest first."""
    mk, r, p, ms = markets.c, market_resolutions.c, predictions.c, market_snapshots.c
    min_lead = float(cfg.strategy.min_lead_hours)
    cutoff: dict[str, tuple[datetime, int]] = {}
    for m in db.rows(select(mk.id, mk.station, mk.local_date, r.outcome)
                     .join(market_resolutions, r.market_id == mk.id).where(r.resolved_at <= fit_time)):
        end = day_end(m["station"], m["local_date"])
        if end is not None:
            cutoff[m["id"]] = (min(end - timedelta(hours=min_lead), fit_time), 1 if m["outcome"] == "YES" else 0)
    best: dict[str, tuple[datetime, float]] = {}
    for x in db.rows(select(p.market_id, p.ts, p.p_yes).join(market_resolutions, r.market_id == p.market_id)
                     .where(r.resolved_at <= fit_time, p.model_version == model_version, PRODUCTION,
                            version_match(p.params_version, param_set)).order_by(p.id)):
        if x["market_id"] in cutoff and _utc(x["ts"]) <= cutoff[x["market_id"]][0]:
            best[x["market_id"]] = (_utc(x["ts"]), x["p_yes"])   # rows are in id order: the last one wins
    max_spread = float(cfg.market_anchor.max_spread)
    min_liquidity = float(cfg.strategy.min_liquidity_usd)
    ids = list(best)
    out = []
    for i in range(0, len(ids), 500):
        books: dict[str, list[tuple]] = {}
        for s in db.rows(select(ms.market_id, ms.ts, ms.best_bid, ms.best_ask, ms.liquidity)
                         .where(ms.market_id.in_(ids[i:i + 500])).order_by(ms.market_id, ms.ts, ms.id)):
            books.setdefault(s["market_id"], []).append((_utc(s["ts"]), s["best_bid"], s["best_ask"], s["liquidity"]))
        for mid, snaps in books.items():
            ts, p_yes = best[mid]
            j = bisect.bisect_right([t for t, *_ in snaps], ts) - 1
            if j < 0:
                continue
            _, bid, ask, liquidity = snaps[j]
            price = tight_mid(bid, ask, max_spread)
            if price is not None and (liquidity or 0) >= min_liquidity:
                out.append((ts, p_yes, price, cutoff[mid][1]))
    return sorted(out)


def judge(data: list[tuple[datetime, float, float, int]], cfg, model_version: str, fit_time: datetime) -> dict:
    """Fit on the older rows of `data` (oldest decision first), judge on the
    newest against the market price alone. Stores nothing."""
    c = cfg.market_anchor
    n = len(data)
    n_hold = int(round(n * float(c.holdout_fraction)))
    train, hold = data[:n - n_hold], data[n - n_hold:]
    row: dict = dict(version=f"anchor-{fit_time.strftime('%Y%m%dT%H%M')}", model_version=model_version,
               fitted_at=fit_time, n=n, n_train=len(train), n_holdout=len(hold),
               train_from=train[0][0] if train else None, train_to=train[-1][0] if train else None,
               holdout_from=hold[0][0] if hold else None, holdout_to=hold[-1][0] if hold else None,
               params=None, brier_market=None, brier_model=None, brier_anchored=None, log_loss_market=None,
               log_loss_model=None, log_loss_anchored=None, improvement_confidence=None, approved=False)
    if n < int(c.min_markets) or len(train) < 2 or not hold:
        row["reason"] = f"only {n} resolved markets with a tight book (need {c.min_markets})"
        return row
    params = fit_anchor([m for _, m, _, _ in train], [k for _, _, k, _ in train], [y for *_, y in train])
    anchor = Anchor(row["version"], params, cfg.model.prob_floor, cfg.model.prob_ceiling)
    model = [m for _, m, _, _ in hold]
    market = [k for _, _, k, _ in hold]
    ys = [y for *_, y in hold]
    anchored = [anchor(m, k) for m, k in zip(model, market)]
    conf = gain_confidence(market, anchored, ys)
    row.update(params=params, brier_market=brier(market, ys), brier_model=brier(model, ys),
               brier_anchored=brier(anchored, ys), log_loss_market=log_loss(market, ys),
               log_loss_model=log_loss(model, ys), log_loss_anchored=log_loss(anchored, ys),
               improvement_confidence=conf)
    need = float(c.min_confidence)
    if not (row["brier_anchored"] < row["brier_market"] and row["log_loss_anchored"] < row["log_loss_market"]):
        row["reason"] = "the model adds nothing to the market price on the holdout (Brier or log loss not lower)"
    elif conf < need:
        row["reason"] = f"gain over the market price not reliable: {conf:.0%} of bootstrap resamples (need {need:.0%})"
    else:
        row["approved"] = True
        row["reason"] = f"beats the market price on the holdout ({conf:.0%} of bootstrap resamples)"
    return row


def fit_round(db: Database, cfg, model_version: str, fit_time: datetime, param_set: dict | None = None) -> dict:
    """Fit and judge the anchor on the predictions of `param_set`, store the fit."""
    row = judge(training_set(db, cfg, model_version, fit_time, param_set), cfg, model_version, fit_time)
    row["params_version"] = param_set and param_set["version"]
    db.insert(market_anchors, **row)
    return row


def active_anchor(db: Database, cfg, model_version: str, now: datetime,
                  param_set: dict | None = None) -> tuple[Anchor | None, str]:
    """The newest fit at or before `now` for `param_set`: (anchor, its version)
    when approved, else (None, why not)."""
    a = market_anchors.c
    row = db.one(select(market_anchors).where(a.model_version == model_version,
                                              version_match(a.params_version, param_set), a.fitted_at <= now)
                 .order_by(desc(a.fitted_at), desc(a.id)).limit(1))
    if row is None:
        return None, "not fitted yet"
    if not row["approved"]:
        return None, row["reason"] or "not approved"
    return Anchor(row["version"], row["params"], cfg.model.prob_floor, cfg.model.prob_ceiling), row["version"]


def latest(db: Database) -> dict | None:
    """The newest anchor fit, for the report."""
    return db.one(select(market_anchors).order_by(desc(market_anchors.c.fitted_at), desc(market_anchors.c.id)).limit(1))
