"""Walk-forward fitting, approval and selection of probability calibrators.

Training data: for every market whose result was recorded by the fit time,
the production model's last prediction made at least `min_lead_hours` before
the end of the market's local day: one row per market, so markets the bot
priced on many cycles are not overweighted.

Approval: rows are ordered by decision time and the newest `holdout_fraction`
is held out. A method is fitted on the older rows only and approved when, on
the holdout, its Brier score AND log loss are both lower than the raw
probabilities', at least `min_samples` markets were available, and the log-loss
gain is not luck: in at least `min_confidence` of 2,000 bootstrap resamples of
the holdout the calibrated probabilities still win. The approved method with
the lowest holdout log loss is selected, and is used until the next fit round.
A round with nothing approved means identity (raw probabilities). Every fit is
kept.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from wxbot.calibration.methods import FIT, calibrate
from wxbot.data.stations import get_station
from wxbot.db import Database, market_resolutions, markets, predictions, prob_calibrators
from wxbot.evaluation.metrics import LOG_LOSS_EPS, PRODUCTION, brier, log_loss

BOOTSTRAP = 2000


@dataclass
class Calibrator:
    method: str
    version: str
    params: dict | None
    prob_floor: float = 0.01
    prob_ceiling: float = 0.99

    def __call__(self, p: float) -> float:
        if self.method == "identity":
            return p
        return min(self.prob_ceiling, max(self.prob_floor, calibrate(self.method, self.params, p)))


def identity() -> Calibrator:
    return Calibrator("identity", "identity", None)


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def day_end(station: str, local_date: str) -> datetime | None:
    """End of the station's local day, in UTC (the database stores naive UTC)."""
    st = get_station(station)
    if st is None or not local_date:
        return None
    end = datetime.combine(date.fromisoformat(local_date) + timedelta(days=1), datetime.min.time(), ZoneInfo(st.tz))
    return end.astimezone(timezone.utc)


def training_set(db: Database, model_version: str, fit_time: datetime,
                 min_lead_hours: float) -> list[tuple[datetime, float, int]]:
    """[(decision time, raw p_yes, outcome 1/0)], oldest decision first."""
    mk, r, p = markets.c, market_resolutions.c, predictions.c
    cutoff: dict[str, tuple[datetime, int]] = {}
    for m in db.rows(select(mk.id, mk.station, mk.local_date, r.outcome)
                     .join(market_resolutions, r.market_id == mk.id).where(r.resolved_at <= fit_time)):
        end = day_end(m["station"], m["local_date"])
        if end is not None:
            cutoff[m["id"]] = (min(end - timedelta(hours=min_lead_hours), fit_time), 1 if m["outcome"] == "YES" else 0)
    best: dict[str, tuple[datetime, float]] = {}
    rows = db.rows(select(p.market_id, p.ts, p.p_yes).join(market_resolutions, r.market_id == p.market_id)
                   .where(r.resolved_at <= fit_time, p.model_version == model_version, PRODUCTION).order_by(p.id))
    for x in rows:
        if x["market_id"] not in cutoff:
            continue
        ts = _utc(x["ts"])
        if ts <= cutoff[x["market_id"]][0]:
            best[x["market_id"]] = (ts, x["p_yes"])   # rows are in id order: the last one wins
    return sorted((ts, p_, cutoff[mid][1]) for mid, (ts, p_) in best.items())


def _loss(p: float, o: int) -> float:
    p = min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, p))
    return -math.log(p) if o else -math.log(1 - p)


def gain_confidence(raw: list[float], cal: list[float], outcomes: list[int], seed: int = 7) -> float:
    """Share of bootstrap resamples of the holdout in which the calibrated
    probabilities have the lower mean log loss (deterministic: fixed seed)."""
    gains = [_loss(r, o) - _loss(c, o) for r, c, o in zip(raw, cal, outcomes)]
    rng, n = random.Random(seed), len(gains)
    wins = sum(sum(gains[rng.randrange(n)] for _ in range(n)) > 0 for _ in range(BOOTSTRAP))
    return wins / BOOTSTRAP


def judge(data: list[tuple[datetime, float, int]], cfg, model_version: str, fit_time: datetime) -> list[dict]:
    """Fit every configured method on the older rows of `data` (oldest decision
    first) and judge it on the newest. Stores nothing: fit_round stores the
    round, and the market backtest replays it day by day."""
    c = cfg.calibration
    floor, ceiling = cfg.model.prob_floor, cfg.model.prob_ceiling
    n = len(data)
    n_hold = int(round(n * float(c.holdout_fraction)))
    train, hold = data[:n - n_hold], data[n - n_hold:]
    hold_p, hold_o = [p for _, p, _ in hold], [o for _, _, o in hold]
    before = (brier(hold_p, hold_o), log_loss(hold_p, hold_o))
    out = []
    for method in c.methods:
        row = dict(version=f"{method}-{fit_time.strftime('%Y%m%dT%H%M')}", method=method, model_version=model_version,
                   fitted_at=fit_time, n=n, n_train=len(train), n_holdout=len(hold),
                   train_from=train[0][0] if train else None, train_to=train[-1][0] if train else None,
                   holdout_from=hold[0][0] if hold else None, holdout_to=hold[-1][0] if hold else None,
                   params=None, brier_before=before[0], log_loss_before=before[1], brier_after=None,
                   log_loss_after=None, improvement_confidence=None, approved=False, selected=False)
        if n < int(c.min_samples) or len(train) < 2 or not hold:
            row["reason"] = f"only {n} resolved markets (need {c.min_samples})"
            out.append(row)
            continue
        kw = {"min_block": int(c.get("isotonic_min_block", 20))} if method == "isotonic" else {}
        params = FIT[method]([p for _, p, _ in train], [o for _, _, o in train], **kw)
        cal = Calibrator(method, row["version"], params, floor, ceiling)
        after = [cal(p) for p in hold_p]
        conf = gain_confidence(hold_p, after, hold_o)
        row.update(params=params, brier_after=brier(after, hold_o), log_loss_after=log_loss(after, hold_o),
                   improvement_confidence=conf)
        need = float(c.get("min_confidence", 0.95))
        if not (row["brier_after"] < before[0] and row["log_loss_after"] < before[1]):
            row["reason"] = "does not beat raw probabilities on both Brier and log loss"
        elif conf < need:
            row["reason"] = f"gain not reliable: wins in {conf:.0%} of bootstrap resamples (need {need:.0%})"
        else:
            row["approved"] = True
            row["reason"] = f"beats raw probabilities on the holdout ({conf:.0%} of bootstrap resamples)"
        out.append(row)
    approved = [r for r in out if r["approved"]]
    if approved:
        min(approved, key=lambda r: r["log_loss_after"])["selected"] = True
    return out


def selected(rows: list[dict], cfg) -> Calibrator:
    """The calibrator a judged round selected; identity if none was approved."""
    row = next((r for r in rows if r["selected"]), None)
    if row is None:
        return identity()
    return Calibrator(row["method"], row["version"], row["params"], cfg.model.prob_floor, cfg.model.prob_ceiling)


def fit_round(db: Database, cfg, model_version: str, fit_time: datetime) -> list[dict]:
    """Fit every configured method, judge it on the holdout, store the round."""
    out = judge(training_set(db, model_version, fit_time, float(cfg.strategy.min_lead_hours)), cfg, model_version,
                fit_time)
    with db.engine.begin() as conn:
        for row in out:
            conn.execute(prob_calibrators.insert().values(**row))
    return out


def active_calibrator(db: Database, cfg, model_version: str, now: datetime) -> Calibrator:
    """The selected calibrator of the newest fit round at or before `now`; identity if none."""
    pc = prob_calibrators.c
    latest = db.one(select(func.max(pc.fitted_at).label("t")).where(pc.model_version == model_version,
                                                                     pc.fitted_at <= now))
    if not latest or latest["t"] is None:
        return identity()
    row = db.one(select(prob_calibrators).where(pc.model_version == model_version, pc.fitted_at == latest["t"],
                                                pc.selected.is_(True)))
    if row is None:
        return identity()
    return Calibrator(row["method"], row["version"], row["params"], cfg.model.prob_floor, cfg.model.prob_ceiling)
