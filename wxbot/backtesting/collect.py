"""Collect what a market backtest replays: closed Polymarket events with their
results and hourly price histories, the forecasts each model issued N days
ahead (Open-Meteo Previous Runs), and observed daily highs and lows (METAR).

Everything is stored in the backtest database before any replay, so a replay
runs offline, can be repeated exactly, and can be audited row by row. Data
already stored is not fetched again.

Every market Polymarket lists for the window is stored, traded or not and
tradeable or not, so the report can count what was left out and why instead of
silently keeping only the markets that survived (survivorship bias).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import exists, func, select, update

from wxbot.calibration.fit import day_end
from wxbot.data.polymarket import Bucket, ParsedMarket, parse_market, parse_time, price_changes
from wxbot.data.stations import STATIONS
from wxbot.data.validation import validate_observation
from wxbot.db import (
    Database, historical_forecasts, market_price_history, market_resolutions, markets, utcnow, weather_observations,
)

log = logging.getLogger("wxbot.backtesting")
PRICE_HISTORY_TRIES = 3   # fetches per market before its price history is given up
COVERED = 0.9             # a station's range counts as stored when this share of its days is


def collect(cfg, db: Database, pm, forecaster, observer, start: date, end: date,
            stations: list[str] | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    out = {"markets": collect_markets(cfg, db, pm, start, end, stations, now)}
    mk = markets.c
    codes = stations or sorted({r["station"] for r in db.rows(select(mk.station).distinct().where(
        mk.tradeable.is_(True), mk.local_date >= start.isoformat(), mk.local_date <= end.isoformat()))})
    out["forecasts"] = collect_forecasts(cfg, db, forecaster, codes, start, end, now)
    out["observations"] = collect_observations(cfg, db, observer, codes, start, end, now)
    return out


def _store_market(db: Database, p: ParsedMarket, closed_time: datetime | None, now: datetime) -> bool:
    """Insert or refresh one market and its result; True when it was new."""
    b = p.bucket or Bucket(None, None, "")
    values = dict(
        event_id=p.event_id, event_title=p.event_title, event_slug=p.event_slug, question=p.question,
        bucket_label=p.bucket_label, city=p.city, station=p.station, kind=p.kind, local_date=p.local_date,
        unit=b.unit or None, bucket_lo=b.lo, bucket_hi=b.hi, yes_token=p.yes_token, no_token=p.no_token,
        end_date=p.end_date, resolution_source=p.resolution_source, description=p.description,
        tradeable=p.tradeable, skip_reason=p.skip_reason, closed=p.closed, resolved_outcome=p.resolved_outcome,
        outcomes=p.outcomes, pm_created_at=p.created_at, criteria=p.criteria, closed_time=closed_time, last_seen=now)
    mk, r = markets.c, market_resolutions.c
    with db.engine.begin() as conn:
        new = conn.execute(select(mk.id).where(mk.id == p.id)).first() is None
        if new:
            conn.execute(markets.insert().values(id=p.id, first_seen=now, **values))
        else:
            conn.execute(update(markets).where(mk.id == p.id).values(**values))
        if p.resolved_outcome and conn.execute(select(r.market_id).where(r.market_id == p.id)).first() is None:
            conn.execute(market_resolutions.insert().values(
                market_id=p.id, resolved_at=closed_time or now, outcome=p.resolved_outcome,
                raw={"outcomePrices": p.raw.get("outcomePrices"), "closedTime": p.raw.get("closedTime"),
                     "umaResolutionStatus": p.raw.get("umaResolutionStatus")}))
    return new


def collect_markets(cfg, db: Database, pm, start: date, end: date, stations: list[str] | None,
                    now: datetime) -> dict:
    events = pm.list_closed_events(start, end)
    kinds = list(cfg.markets.kinds)
    lo, hi = start.isoformat(), end.isoformat()
    seen = new = 0
    for ev in events:
        for raw in ev.get("markets") or []:
            p = parse_market(ev, raw, kinds)
            # an unreadable title is stored (and counted as skipped); a readable one outside the window is not ours
            if p.local_date is not None and not lo <= p.local_date <= hi:
                continue
            if stations and p.station not in stations:
                continue
            seen += 1
            new += _store_market(db, p, parse_time(raw.get("closedTime")), now)
    return {"events": len(events), "markets": seen, "new_markets": new,
            "price_histories": collect_price_histories(db, pm, start, end, stations, now)}


def collect_price_histories(db: Database, pm, start: date, end: date, stations: list[str] | None,
                            now: datetime) -> dict:
    """Hourly YES price from listing to close for every resolved tradeable
    market that has none stored yet. A price is stored only where it changed."""
    from wxbot.engine import CLOB_DOWN
    mk, ph = markets.c, market_price_history.c
    q = select(mk.id, mk.station, mk.local_date, mk.yes_token, mk.pm_created_at, mk.closed_time,
               mk.price_history_tries).where(
        mk.tradeable.is_(True), mk.resolved_outcome.is_not(None), mk.yes_token.is_not(None),
        mk.local_date >= start.isoformat(), mk.local_date <= end.isoformat(),
        func.coalesce(mk.price_history_tries, 0) < PRICE_HISTORY_TRIES, ~exists().where(ph.market_id == mk.id))
    if stations:
        q = q.where(mk.station.in_(stations))
    todo = db.rows(q.order_by(mk.local_date, mk.id))
    stored = empty = failed = 0
    for i, m in enumerate(todo):
        if i and i % 250 == 0:
            log.info("price histories: %d of %d", i, len(todo))
        close = parse_time(m["closed_time"])
        if close is None:
            end_of_day = day_end(m["station"], m["local_date"])
            if end_of_day is None:   # unknown station: nothing to fetch it for
                continue
            close = end_of_day + timedelta(days=2)
        opened = parse_time(m["pm_created_at"]) or close - timedelta(days=5)
        try:
            series = pm.get_price_history(m["yes_token"], opened - timedelta(hours=1), close)
        except Exception as exc:  # one bad market never stops the rest
            failed += 1
            _count_try(db, m)
            db.log_event("WARNING", "backtest", f"price history {m['id']}: {type(exc).__name__}: {exc}")
            if isinstance(exc, CLOB_DOWN):
                break
            continue
        if not series:
            empty += 1
            _count_try(db, m)
            continue
        with db.engine.begin() as conn:
            conn.execute(market_price_history.insert(), [
                dict(market_id=m["id"], token="YES", t=t, price=p, fetched_at=now) for t, p in price_changes(series)])
        stored += 1
    return {"to_fetch": len(todo), "stored": stored, "empty": empty, "failed": failed}


def _count_try(db: Database, m: dict) -> None:
    with db.engine.begin() as conn:
        conn.execute(update(markets).where(markets.c.id == m["id"])
                     .values(price_history_tries=(m["price_history_tries"] or 0) + 1))


def _days(a: date, b: date) -> int:
    return (b - a).days + 1


def collect_forecasts(cfg, db: Database, forecaster, codes: list[str], start: date, end: date,
                      now: datetime) -> dict:
    """previous_dayN forecasts from before the training window to the end."""
    b = cfg.backtest
    leads = [int(x) for x in b.leads]
    lo = start - timedelta(days=int(b.train_days) + max(leads) + 1)
    hf = historical_forecasts.c
    out: dict[str, int | str] = {}
    for code in codes:
        have = {(r["kind"], r["lead_days"], r["local_date"], r["model"]) for r in db.rows(
            select(hf.kind, hf.lead_days, hf.local_date, hf.model).where(
                hf.station == code, hf.local_date >= lo.isoformat(), hf.local_date <= end.isoformat()))}
        days = {(k, lead, d) for k, lead, d, _ in have}
        if all(sum((k, lead) == (kind, x) for k, x, _ in days) >= COVERED * _days(lo, end)
               for kind in ("high", "low") for lead in leads):
            out[code] = "already stored"
            continue
        try:
            fc = forecaster.fetch(STATIONS[code], lo, end, leads)
        except Exception as exc:
            db.log_event("WARNING", "backtest", f"forecasts {code}: {type(exc).__name__}: {exc}")
            out[code] = f"failed: {type(exc).__name__}"
            continue
        rows = [dict(source=forecaster.source, station=code, kind=kind, local_date=d, lead_days=lead, model=model,
                     value_c=float(v), fetched_at=now)
                for lead, by_kind in fc.items() for kind, by_day in by_kind.items()
                for d, values in by_day.items() for model, v in values.items()
                if v is not None and (kind, lead, d, model) not in have]
        if rows:
            with db.engine.begin() as conn:
                conn.execute(historical_forecasts.insert(), rows)
        out[code] = len(rows)
    return out


def collect_observations(cfg, db: Database, observer, codes: list[str], start: date, end: date,
                         now: datetime) -> dict:
    """Observed highs/lows for the training window and the climatology years,
    one request per station and year."""
    b = cfg.backtest
    rules = SimpleNamespace(**cfg.validation.as_dict())
    first = start - timedelta(days=int(b.train_days) + max(int(x) for x in b.leads) + 1)
    years = int(b.get("climatology_years", 0))
    if years:
        first = min(first, start - timedelta(days=365 * years + int(cfg.model.get("climatology_window_days", 7)) + 1))
    wo = weather_observations.c
    out: dict[str, dict] = {}
    for code in codes:
        stored, failed, skipped = 0, 0, 0
        hi = end
        while hi >= first:
            lo = max(first, hi - timedelta(days=364))
            have = {(r["kind"], r["local_date"]) for r in db.rows(select(wo.kind, wo.local_date).where(
                wo.station == code, wo.local_date >= lo.isoformat(), wo.local_date <= hi.isoformat()))}
            if sum(k == "high" for k, _ in have) >= COVERED * _days(lo, hi):
                skipped += 1
            else:
                try:
                    obs = observer.fetch(STATIONS[code], lo, hi)
                except Exception as exc:
                    failed += 1
                    db.log_event("WARNING", "backtest", f"observations {code} {lo}..{hi}: {type(exc).__name__}: {exc}")
                    obs = {}
                rows = [dict(station=code, local_date=d, kind=kind, value_c=v, n_reports=n, source=observer.source,
                             fetched_at=now)
                        for kind, by_day in obs.items() for d, (v, n) in by_day.items()
                        if (kind, d) not in have and validate_observation(v, n, rules) is None]
                if rows:
                    with db.engine.begin() as conn:
                        conn.execute(weather_observations.insert(), rows)
                stored += len(rows)
            hi = lo - timedelta(days=1)
        out[code] = {"stored": stored, "years_already_stored": skipped, "failed_requests": failed}
    return out
