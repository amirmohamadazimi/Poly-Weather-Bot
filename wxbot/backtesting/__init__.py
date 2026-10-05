"""Historical market backtest (v2 M8): replay closed Polymarket temperature
markets at the prices that were on offer, with only the information that
existed at each decision time, and compare the naive baseline, the raw
forecast, the model, the calibrated model and the market price on the same
markets. Then run the live betting rules over the same decisions.

    collect.py   fetch and store closed markets, prices, forecasts, observations
    replay.py    build the decision rows (no look-ahead)
    evaluate.py  scores, flat-stake and bankroll simulations
    report.py    BACKTEST.md

It writes only to its own database (backtest.database_url) and never touches
a paper-trading experiment. Research only: nothing here can place an order.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import func, select, update

# imported under other names, so wxbot.backtesting.<module> stays the module
from wxbot.backtesting.collect import collect as collect_data
from wxbot.backtesting.evaluate import evaluate as evaluate_rows
from wxbot.backtesting.replay import SKIPS
from wxbot.backtesting.replay import replay as replay_rows
from wxbot.db import Database, backtest_predictions, backtest_runs, market_price_history, markets, utcnow
from wxbot.experiment import git_ref, redact

SETTINGS = ("backtest", "model", "calibration", "strategy", "sizing", "risk", "bankroll", "weather")


def data_summary(db: Database, start: date, end: date, stations: list[str] | None = None) -> dict:
    """Every market stored for the window and why any was left out."""
    mk, ph = markets.c, market_price_history.c
    window = [mk.local_date >= start.isoformat(), mk.local_date <= end.isoformat()]
    if stations:
        window.append(mk.station.in_(stations))

    def count(*where) -> int:
        return db.agg(select(func.count().label("n")).select_from(markets).where(*window, *where))["n"]

    reasons: dict[str, int] = {}
    for r in db.rows(select(mk.skip_reason, func.count().label("n")).where(*window, mk.tradeable.is_(False))
                     .group_by(mk.skip_reason)):
        key = (r["skip_reason"] or "unknown").split(":")[0]
        reasons[key] = reasons.get(key, 0) + r["n"]
    has_prices = select(ph.market_id).where(ph.market_id == mk.id).exists()
    return {
        "events": db.agg(select(func.count(func.distinct(mk.event_id)).label("n")).where(*window))["n"],
        "markets": count(),
        "not_tradeable": sum(reasons.values()),
        "not_tradeable_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "tradeable_unresolved": count(mk.tradeable.is_(True), mk.resolved_outcome.is_(None)),
        "tradeable_resolved_no_prices": count(mk.tradeable.is_(True), mk.resolved_outcome.is_not(None), ~has_prices),
        "tradeable_resolved_with_prices": count(mk.tradeable.is_(True), mk.resolved_outcome.is_not(None), has_prices),
    }


def _jsonable(value):
    return json.loads(json.dumps(value, default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else str(v)))


def run_market_backtest(cfg, db: Database, start: date, end: date, *, sources: tuple | None = None,
                        stations: list[str] | None = None, now: datetime | None = None) -> dict:
    """sources: (polymarket, previous-runs forecaster, observer) to fetch what is
    missing first; None replays only what the database already holds."""
    now = now or utcnow()
    b = cfg.backtest
    params = {"kind": "markets", "start": start.isoformat(), "end": end.isoformat(), "stations": stations,
              "leads": list(b.leads), "forecast_delay_hours": b.forecast_delay_hours, "half_spread": b.half_spread,
              "offline": sources is None, "git_ref": git_ref(),
              "settings": redact({k: cfg.get(k).as_dict() for k in SETTINGS if cfg.get(k) is not None})}
    run_id = db.insert(backtest_runs, started_at=now, params=params)
    collected = None
    if sources:
        pm, forecaster, observer = sources
        collected = collect_data(cfg, db, pm, forecaster, observer, start, end, stations, now)
    replayed = replay_rows(cfg, db, start, end, stations)
    rows = replayed["rows"]
    report = evaluate_rows(rows, cfg)
    report.update(run_id=run_id, params=params, collected=collected, data=data_summary(db, start, end, stations),
                  replay={"markets": replayed["markets"], "rows": len(rows),
                          "skipped": {SKIPS[k]: v for k, v in replayed["skipped"].items()}},
                  calibration_rounds=replayed["calibration_rounds"])
    report = _jsonable(report)
    keep = [c.name for c in backtest_predictions.columns if c.name not in ("id", "run_id")]
    with db.engine.begin() as conn:
        for i in range(0, len(rows), 5000):
            conn.execute(backtest_predictions.insert(),
                         [{"run_id": run_id, **{k: r.get(k) for k in keep}} for r in rows[i:i + 5000]])
        conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id)
                     .values(finished_at=utcnow(), report=report))
    return report
