"""The paper-trading cycle:

collect markets -> collect forecasts -> predict -> signal -> paper bet
-> check resolutions -> settle -> snapshot bankroll.

Each step is isolated: a failure is logged to system_events and the rest of
the cycle still runs.
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import and_, desc, exists, func, or_, select, update

from wxbot.data.polymarket import Bucket, ParsedMarket, parse_time, resolved_outcome
from wxbot.data.stations import get_station
from wxbot.data.validation import validate_forecast, validate_observation
from wxbot.db import (
    Database, calibration_params, forecast_snapshots, forecast_values, market_criteria_history, market_price_history,
    market_snapshots, markets, paper_bets, predictions, signals, utcnow, weather_observations,
)
from wxbot.execution import portfolio
from wxbot.model.base import Calibration
from wxbot.model.normal import default_calibration
from wxbot.strategy import rules

log = logging.getLogger("wxbot.engine")


def local_today(tz: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(tz)).date()


def hours_to_day_end(local_date: str, tz: str, now: datetime) -> float:
    end = datetime.combine(date.fromisoformat(local_date) + timedelta(days=1), datetime.min.time(), ZoneInfo(tz))
    return (end - now).total_seconds() / 3600.0


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    t = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


VARIABLES = {"high": "temperature_2m_max", "low": "temperature_2m_min"}
PRICE_HISTORY_TRIES = 3  # fetches per resolved market before its price history is given up
# the CLOB itself is unreachable: stop this cycle's pass instead of trying every market
CLOB_DOWN = (requests.ConnectionError, requests.Timeout, requests.exceptions.RetryError)


class Engine:
    def __init__(self, cfg, db: Database, polymarket, forecaster, observer, predictor, broker, sizer,
                 clock=utcnow):
        self.cfg = cfg
        self.db = db
        self.pm = polymarket
        self.forecaster = forecaster
        self.observer = observer
        self.predictor = predictor
        self.broker = broker
        self.sizer = sizer
        self.clock = clock
        v = cfg.get("validation")
        self.validation = SimpleNamespace(**(v.as_dict() if v else {}), min_models=cfg.weather.min_models)

    # -- orchestration ------------------------------------------------------
    def run_cycle(self) -> dict:
        started = time.monotonic()
        self.db.set_state("bot_status", "running cycle")
        summary: dict = {}
        steps = [
            ("markets", self.collect_markets),
            ("forecasts", self.collect_forecasts),
            ("signals", self.predict_and_trade),
            ("settlement", self.settle),
            ("observations", self.maybe_collect_observations),
        ]
        for name, fn in steps:
            try:
                summary[name] = fn()
            except Exception as exc:  # keep the loop alive; record why
                log.exception("step %s failed", name)
                self.db.log_event("ERROR", name, f"{type(exc).__name__}: {exc}")
                summary[name] = {"error": str(exc)}
        portfolio.snapshot(self.db, self.cfg.bankroll.initial, "cycle")
        summary["seconds"] = round(time.monotonic() - started, 1)
        self.db.set_state("last_cycle", {"at": self.clock().isoformat(), "summary": summary})
        self.db.set_state("bot_status", "idle")
        log.info("cycle done %s", summary)
        return summary

    # -- 1. markets ---------------------------------------------------------
    def collect_markets(self) -> dict:
        parsed: list[ParsedMarket] = self.pm.discover(list(self.cfg.markets.kinds))
        now = self.clock()
        for pm in parsed:
            self._upsert_market(pm, now)
            # every market, tradeable or not, so skipped ones can still be studied later
            self.db.insert(market_snapshots, market_id=pm.id, ts=now, best_bid=pm.best_bid,
                           best_ask=pm.best_ask, last_price=pm.last_price, yes_price=pm.yes_price,
                           liquidity=pm.liquidity, volume=pm.volume)
        self.db.set_state("last_polymarket_update", now.isoformat())
        n_trade = sum(p.tradeable for p in parsed)
        self.db.set_state("markets_monitored", n_trade)
        return {"seen": len(parsed), "tradeable": n_trade}

    def _upsert_market(self, pm: ParsedMarket, now: datetime) -> None:
        b = pm.bucket or Bucket(None, None, "")
        values = dict(
            event_id=pm.event_id, event_title=pm.event_title, event_slug=pm.event_slug, question=pm.question,
            bucket_label=pm.bucket_label, city=pm.city, station=pm.station, kind=pm.kind,
            local_date=pm.local_date, unit=b.unit or None, bucket_lo=b.lo, bucket_hi=b.hi,
            yes_token=pm.yes_token, no_token=pm.no_token, end_date=pm.end_date,
            resolution_source=pm.resolution_source, description=pm.description, tradeable=pm.tradeable,
            skip_reason=pm.skip_reason, closed=pm.closed, last_seen=now,
            outcomes=pm.outcomes, pm_created_at=pm.created_at, criteria=pm.criteria,
        )
        mk = markets.c
        with self.db.engine.begin() as conn:
            old = conn.execute(select(mk.description, mk.resolution_source, mk.criteria, mk.last_seen)
                               .where(mk.id == pm.id)).first()
            if old is None:
                conn.execute(markets.insert().values(id=pm.id, first_seen=now, **values))
                return
            if (old.description, old.resolution_source) != (pm.description, pm.resolution_source):
                # Polymarket edited the rules: keep the text the market had until now
                conn.execute(market_criteria_history.insert().values(
                    market_id=pm.id, replaced_at=now, last_seen=old.last_seen, description=old.description,
                    resolution_source=old.resolution_source, criteria=old.criteria))
                log.info("market %s: resolution text changed", pm.id)
            # a market we already saw close/resolve never re-opens
            conn.execute(update(markets).where(mk.id == pm.id).values({**values, "closed": or_(mk.closed, pm.closed)}))

    def _open_tradeable_markets(self) -> list[dict]:
        rows = self.db.rows(select(markets).where(markets.c.tradeable.is_(True), markets.c.closed.is_(False)))
        now = self.clock()
        out = []
        for m in rows:
            st = get_station(m["station"])
            if st and hours_to_day_end(m["local_date"], st.tz, now) > 0:
                out.append(m)
        return out

    # -- 2. forecasts -------------------------------------------------------
    def collect_forecasts(self) -> dict:
        needed: dict[str, set] = {}
        for m in self._open_tradeable_markets():
            needed.setdefault(m["station"], set()).add((m["local_date"], m["kind"]))
        now = self.clock()
        stored = 0
        for code, keys in needed.items():
            st = get_station(code)
            try:
                by_kind, meta = self.forecaster.fetch(st)
            except Exception as exc:
                self.db.log_event("WARNING", "forecasts", f"{code}: {type(exc).__name__}: {exc}")
                continue
            runs = {m: _parse_time(t) for m, t in (meta.get("model_runs") or {}).items()}
            for local_date, kind in keys:
                values = by_kind.get(kind, {}).get(local_date)
                if values:
                    self._store_forecast(st, local_date, kind, values, runs, meta, now)
                    stored += 1
        if stored:
            self.db.set_state("last_weather_update", now.isoformat())
        return {"stations": len(needed), "snapshots": stored}

    def _store_forecast(self, st, local_date: str, kind: str, values: dict, runs: dict, meta: dict,
                        now: datetime) -> int:
        """One snapshot row (as before) plus one forecast_values row per model,
        each with its run time, horizon and validation verdict."""
        q = validate_forecast(values, runs, now, self.validation)
        used_runs = [runs[m] for m in q.clean if runs.get(m)]
        snap_id = self.db.insert(forecast_snapshots, fetched_at=now, source=self.forecaster.source,
                                 station=st.code, local_date=local_date, kind=kind, values_c=values,
                                 request=meta, issue_time=min(used_runs) if used_runs else None,
                                 quality=q.as_dict())
        day_end = hours_to_day_end(local_date, st.tz, now)
        for model, value in values.items():
            run = runs.get(model)
            horizon = day_end + ((now - run).total_seconds() / 3600 if run else 0.0)
            self.db.insert(forecast_values, snapshot_id=snap_id, source=self.forecaster.source, model=model,
                           station=st.code, lat=st.lat, lon=st.lon, variable=VARIABLES[kind],
                           target_date=local_date, issue_time=run,
                           issue_time_source="model_run" if run else "unknown",
                           horizon_hours=round(horizon, 2), value=value if isinstance(value, (int, float)) else None,
                           unit="C", valid=model in q.clean, problem=q.rejected.get(model), fetched_at=now)
        if not q.ok or q.rejected:
            self.db.log_event("WARNING", "validation", f"{st.code} {local_date} {kind}: "
                              f"errors={q.errors} rejected={q.rejected}", details=q.as_dict())
        return snap_id

    def _latest_forecast(self, station: str, local_date: str, kind: str) -> dict | None:
        fs = forecast_snapshots.c
        return self.db.one(select(forecast_snapshots).where(
            fs.station == station, fs.local_date == local_date, fs.kind == kind).order_by(desc(fs.id)).limit(1))

    def _calibration(self, station: str, kind: str, lead_days: int) -> Calibration:
        cp = calibration_params.c
        row = self.db.one(select(calibration_params).where(
            cp.station == station, cp.kind == kind, cp.lead_days == max(lead_days, 1),
        ).order_by(desc(cp.id)).limit(1))
        if row and row["n"] >= self.cfg.model.min_calibration_samples:
            return Calibration(bias_c=row["bias_c"], sigma_c=row["sigma_c"], n=row["n"], source="backtest")
        return default_calibration(list(self.cfg.model.default_sigma_c), lead_days)

    # -- 3. predictions, signals, paper bets ---------------------------------
    def predict_and_trade(self) -> dict:
        now = self.clock()
        n_pred = n_bets = 0
        for m in self._open_tradeable_markets():
            st = get_station(m["station"])
            fc = self._latest_forecast(m["station"], m["local_date"], m["kind"])
            if fc is None:
                continue
            lead_days = (date.fromisoformat(m["local_date"]) - local_today(st.tz, now)).days
            calib = self._calibration(m["station"], m["kind"], lead_days)
            bucket = Bucket(m["bucket_lo"], m["bucket_hi"], m["unit"])
            quality = fc.get("quality") or {"ok": True, "rejected": {}}
            values = {k: v for k, v in fc["values_c"].items() if k not in quality.get("rejected", {})}
            if not values:
                continue
            pred = self.predictor.predict(bucket, m["kind"], values, lead_days, calib)
            pred.inputs["data_quality"] = quality
            fetched_at = fc["fetched_at"] if fc["fetched_at"].tzinfo else fc["fetched_at"].replace(tzinfo=timezone.utc)
            pred.inputs["forecast_fetched_at"] = fetched_at.isoformat()
            pred.inputs["forecast_source"] = fc["source"]
            pred_id = self.db.insert(predictions, ts=now, market_id=m["id"], forecast_snapshot_id=fc["id"],
                                     model_version=pred.model_version, lead_days=lead_days, mu_c=pred.mu_c,
                                     sigma_c=pred.sigma_c, p_yes=pred.p_yes, inputs=pred.inputs)
            n_pred += 1
            forecast_age = (now - fetched_at).total_seconds() / 60.0
            if self._signal(m, st, pred, pred_id, forecast_age, now):
                n_bets += 1
        self.db.set_state("last_prediction_time", now.isoformat())
        return {"predictions": n_pred, "bets": n_bets}

    def _latest_snapshot(self, market_id: str) -> dict | None:
        ms = market_snapshots.c
        return self.db.one(select(market_snapshots).where(ms.market_id == market_id).order_by(desc(ms.id)).limit(1))

    def _signal(self, m: dict, st, pred, pred_id: int, forecast_age: float, now: datetime) -> bool:
        cfg = self.cfg
        snap = self._latest_snapshot(m["id"]) or {}
        bid, ask, yes_px = snap.get("best_bid"), snap.get("best_ask"), snap.get("yes_price")
        yes_mid = (bid + ask) / 2 if bid is not None and ask is not None else yes_px
        quotes = {  # side -> (model prob, top-of-book ask for that side, mid-implied prob)
            "YES": (pred.p_yes, ask if ask and ask < 1 else None, yes_mid),
            "NO": (1 - pred.p_yes, (1 - bid) if bid else None, None if yes_mid is None else 1 - yes_mid),
        }

        def score(side):
            p, px, _ = quotes[side]
            return (px is not None, p - px if px is not None else p)
        side = max(quotes, key=score)
        model_prob, top_price, market_prob = quotes[side]
        if top_price is not None:
            top_price = min(top_price + cfg.strategy.slippage, 0.999) * (1 + cfg.strategy.fee_rate)
        bank = portfolio.bankroll(self.db, cfg.bankroll.initial)
        ctx = rules.Context(
            side=side, model_prob=model_prob, market_prob=market_prob, entry_price=top_price,
            liquidity=snap.get("liquidity"), lead_hours=hours_to_day_end(m["local_date"], st.tz, now),
            n_models=len(pred.inputs["model_values_c"]), forecast_age_min=forecast_age, sigma_c=pred.sigma_c,
            market_open=not m["closed"], has_position=portfolio.has_open_position(self.db, m["id"]),
            daily_pnl=portfolio.daily_realized_pnl(self.db, now), initial_bankroll=cfg.bankroll.initial,
            data_valid=bool(pred.inputs.get("data_quality", {}).get("ok", True)),
        )
        results = rules.evaluate(ctx, cfg)
        fill = None
        sizing: dict = {}
        if not rules.failed(results):
            token = m["yes_token"] if side == "YES" else m["no_token"]
            asks = self.pm.get_asks(token)
            s, r = cfg.strategy, cfg.risk
            equity = bank.equity
            caps = {
                "sizer": self.sizer.stake(equity, model_prob, top_price),
                "max_bet": r.max_bet_pct * equity,
                "open_exposure_room": r.max_open_exposure_pct * equity - bank.open_exposure,
                "event_exposure_room": r.max_event_exposure_pct * equity
                - portfolio.event_exposure(self.db, m["event_id"]),
                "cash": bank.cash,
                "book_capacity": rules.book_capacity(asks, s.slippage, s.fee_rate, cfg.sizing.max_book_share),
            }
            budget = max(0.0, min(caps.values()))
            sizing = {"sizer": self.sizer.name, "equity": round(equity, 2),
                      "caps": {k: round(v, 2) for k, v in caps.items()}, "budget": round(budget, 2)}
            fill = rules.simulate_fill(asks, budget, s.slippage, s.fee_rate, cfg.sizing.max_book_share)
            ctx.entry_price = fill.avg_price if fill.shares else None
            ctx.stake = fill.total
            results = rules.evaluate(ctx, cfg)
            sizing["fill_levels"] = fill.levels
        bad = rules.failed(results)
        decision = "BET" if not bad else "NO_BET"
        price = ctx.entry_price
        edge = None if price is None else model_prob - price
        ev = None if not price else model_prob / price - 1
        results_out = results + ([{"rule": "sizing_detail", "passed": True, "value": sizing, "threshold": None}]
                                 if sizing else [])
        sig_id = self.db.insert(
            signals, ts=now, prediction_id=pred_id, market_id=m["id"], side=side, model_prob=model_prob,
            market_prob=market_prob, entry_price=price, edge=edge, ev_per_dollar=ev, confidence=model_prob,
            proposed_stake=ctx.stake, decision=decision,
            reason="all rules passed" if not bad else "failed: " + ", ".join(bad), rule_results=results_out)
        if decision == "BET":
            bet_id = self.broker.place(signal_id=sig_id, market=m, side=side, fill=fill, model_prob=model_prob,
                                       market_prob=market_prob, edge=edge, ev=ev)
            self.db.log_event("INFO", "paper_bet", f"bet #{bet_id}: {side} '{m['question']}' "
                              f"${fill.total:.2f} @ {fill.avg_price:.3f} (model {model_prob:.2f})")
            return True
        return False

    # -- 4. settlement ------------------------------------------------------
    def settle(self) -> dict:
        """Ask Polymarket about every market with an open bet or a past date.
        Untradeable markets are included so every market gets its result and close time."""
        now = self.clock()
        pb, mk = paper_bets.c, markets.c
        ids = {r["market_id"] for r in self.db.rows(select(pb.market_id).where(pb.status == "OPEN"))}
        cutoff = (now - timedelta(days=1)).date().isoformat()
        # markets without a bet, oldest first and capped, so a backlog is worked off over several cycles
        rest = self.db.rows(select(mk.id).where(and_(
            mk.kind.is_not(None), mk.resolved_outcome.is_(None), mk.local_date <= cutoff,
            mk.local_date >= (now - timedelta(days=10)).date().isoformat(), mk.id.not_in(ids)))
            .order_by(mk.local_date, mk.id))
        cap = int(self.cfg.markets.get("max_result_checks_per_cycle", 500))
        if len(rest) > cap:
            self.db.log_event("INFO", "settlement", f"{len(rest) - cap} markets left for later cycles")
        order = sorted(ids) + [r["id"] for r in rest[:cap]]
        settled = checked = 0
        for market_id in order:
            try:
                raw = self.pm.get_market(market_id)
            except Exception as exc:
                self.db.log_event("WARNING", "settlement", f"market {market_id}: {exc}")
                continue
            checked += 1
            outcome = resolved_outcome(raw)
            if raw.get("closed"):
                closed_time = parse_time(raw.get("closedTime"))
                with self.db.engine.begin() as conn:
                    conn.execute(update(markets).where(mk.id == market_id).values(
                        closed=True, **({"closed_time": closed_time} if closed_time else {})))
            if outcome:
                settled += len(self.broker.settle_market(market_id, outcome, {
                    "outcomePrices": raw.get("outcomePrices"), "umaResolutionStatus": raw.get("umaResolutionStatus"),
                    "closedTime": raw.get("closedTime")}))
        return {"checked": checked, "bets_settled": settled, "price_histories": self._store_price_histories(now)}

    def _store_price_histories(self, now: datetime) -> int:
        """Price series for recently resolved markets that do not have one yet,
        newest first and at most max_price_histories_per_cycle per cycle. Each
        market is tried at most PRICE_HISTORY_TRIES times (empty series and errors
        alike), so one bad market never blocks the others. If the CLOB itself is
        unreachable the pass stops and resumes next cycle."""
        if not self.cfg.markets.get("store_price_history", True):
            return 0
        mk, ph = markets.c, market_price_history.c
        todo = self.db.rows(select(mk.id, mk.price_history_tries).where(
            mk.resolved_outcome.is_not(None), mk.yes_token.is_not(None),
            func.coalesce(mk.price_history_tries, 0) < PRICE_HISTORY_TRIES,
            ~exists().where(ph.market_id == mk.id),
            mk.local_date >= (now - timedelta(days=10)).date().isoformat()).order_by(mk.local_date.desc(), mk.id))
        cap = int(self.cfg.markets.get("max_price_histories_per_cycle", 300))
        if len(todo) > cap:
            self.db.log_event("INFO", "price_history", f"{len(todo) - cap} markets left for later cycles")
        stored = 0
        for r in todo[:cap]:
            tries = (r["price_history_tries"] or 0) + 1
            try:
                got = self._store_price_history(r["id"], now)
            except Exception as exc:  # never let a history fetch break settlement
                got = None
                self.db.log_event("WARNING", "price_history",
                                  f"market {r['id']} (try {tries}): {type(exc).__name__}: {exc}")
                if isinstance(exc, CLOB_DOWN):
                    self._count_price_history_try(r["id"], tries)
                    break
            if got:
                stored += 1
                continue
            self._count_price_history_try(r["id"], tries)
            if got == 0:  # an empty series is normal for a market that never traded
                self.db.log_event("WARNING" if tries >= PRICE_HISTORY_TRIES else "INFO", "price_history",
                                  f"market {r['id']}: empty history (try {tries} of {PRICE_HISTORY_TRIES})")
        return stored

    def _count_price_history_try(self, market_id: str, tries: int) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(update(markets).where(markets.c.id == market_id).values(price_history_tries=tries))

    def _store_price_history(self, market_id: str, now: datetime) -> int:
        """Keep the YES price series of one resolved market for backtests: hourly,
        from creation to close, storing a point only when the price changed (a
        price holds until the next stored point; the last point is always kept)."""
        m = self.db.one(select(markets).where(markets.c.id == market_id))
        if not m or not m["yes_token"]:
            return 0
        start = _parse_time(m["pm_created_at"]) or _parse_time(m["first_seen"]) - timedelta(days=3)
        end = min(_parse_time(m["closed_time"]) or now, now)
        series = self.pm.get_price_history(m["yes_token"], start, end)
        if not series:
            return 0
        kept = [pt for i, pt in enumerate(series) if i == 0 or pt[1] != series[i - 1][1] or i == len(series) - 1]
        with self.db.engine.begin() as conn:
            conn.execute(market_price_history.insert(), [
                dict(market_id=market_id, token="YES", t=t, price=p, fetched_at=now) for t, p in kept])
        return 1

    # -- 5. observations ----------------------------------------------------
    def maybe_collect_observations(self, force: bool = False) -> dict:
        now = self.clock()
        last = self.db.get_state("last_observation_update")
        if not force and last and now - datetime.fromisoformat(last) < timedelta(hours=self.cfg.schedule.observation_hours):
            return {"skipped": True}
        mk = markets.c
        since = (now - timedelta(days=4)).date().isoformat()
        codes = {r["station"] for r in self.db.rows(select(mk.station).where(mk.tradeable.is_(True), mk.local_date >= since))}
        stored = 0
        for code in sorted(codes):
            st = get_station(code)
            end = local_today(st.tz, now) - timedelta(days=1)
            try:
                obs = self.observer.fetch(st, end - timedelta(days=3), end)
            except Exception as exc:
                self.db.log_event("WARNING", "observations", f"{code}: {type(exc).__name__}: {exc}")
                continue
            stored += self.store_observations(code, obs)
        self.db.set_state("last_observation_update", now.isoformat())
        return {"stations": len(codes), "new_rows": stored}

    def store_observations(self, code: str, obs: dict) -> int:
        wo = weather_observations.c
        stored = 0
        for kind, days in obs.items():
            for d, (value, n) in days.items():
                problem = validate_observation(value, n, self.validation)
                if problem:
                    self.db.log_event("WARNING", "validation", f"observation {code} {d} {kind} rejected: {problem}",
                                      details={"value_c": value, "n_reports": n})
                    continue
                prev = self.db.one(select(wo.value_c).where(wo.station == code, wo.local_date == d, wo.kind == kind,
                                                            wo.source == self.observer.source).order_by(desc(wo.id)).limit(1))
                if prev is None or abs(prev["value_c"] - value) > 1e-6:
                    self.db.insert(weather_observations, station=code, local_date=d, kind=kind, value_c=value,
                                   n_reports=n, source=self.observer.source, fetched_at=self.clock())
                    stored += 1
        return stored
