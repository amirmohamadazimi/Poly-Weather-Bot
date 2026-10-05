"""The paper-trading cycle:

collect markets -> collect forecasts -> predict -> signal -> paper bet
-> check resolutions -> settle -> learn (wxbot/learning/) -> snapshot bankroll.

Each step is isolated: a failure is logged to system_events and the rest of
the cycle still runs.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import and_, desc, exists, func, select, update

from wxbot.calibration.fit import active_calibrator, fit_round
from wxbot.data.polymarket import Bucket, ParsedMarket, parse_time, price_changes, resolved_outcome
from wxbot.data.stations import get_station
from wxbot.data.validation import validate_forecast, validate_observation
from wxbot.db import (
    Database, forecast_snapshots, forecast_values, market_criteria_history, market_price_history, market_snapshots,
    markets, paper_bets, predictions, signals, utcnow, weather_observations,
)
from wxbot.execution import portfolio
from wxbot.execution.paper import BrokerRefused
from wxbot.experiment import check_end, ensure_experiment, is_open
from wxbot.features import FEATURE_SET, Features, build_features, climatology_window, observed_history
from wxbot.learning import learn, outcomes, retrain
from wxbot.learning import params as param_sets
from wxbot.model.base import Calibration
from wxbot.model.registry import sync_registry
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
    return t if t.tzinfo else t.replace(tzinfo=UTC)


VARIABLES = {"high": "temperature_2m_max", "low": "temperature_2m_min"}
# what a shadow prediction keeps of its model's inputs; the rest is on the production prediction
SHADOW_INPUTS = ("raw_p_yes", "mu_unit", "sigma_unit", "n", "k", "window_days")
# the cash cap leaves a millionth of a dollar so float rounding in the fill can
# never make the paper broker refuse a bet sized to the last of the cash
CASH_MARGIN = 1e-6
PRICE_HISTORY_TRIES = 3  # fetches per resolved market before its price history is given up
# the CLOB itself is unreachable: stop this cycle's pass instead of trying every market
CLOB_DOWN = (requests.ConnectionError, requests.Timeout, requests.exceptions.RetryError)


class Engine:
    def __init__(self, cfg, db: Database, polymarket, forecaster, observer, predictor, broker, sizer,
                 clock=utcnow, shadows=(), history=None):
        self.cfg = cfg
        self.db = db
        self.pm = polymarket
        self.forecaster = forecaster
        self.observer = observer
        self.predictor = predictor
        self.shadows = list(shadows)  # priced and stored on every market, never traded
        self.broker = broker
        self.sizer = sizer
        self.history = history    # past forecasts (Open-Meteo Previous Runs) for retraining; None = no retraining
        self.clock = clock
        v = cfg.get("validation")
        self.validation = SimpleNamespace(**(v.as_dict() if v else {}), min_models=cfg.weather.min_models)
        for change in sync_registry(db, predictor, self.shadows, self.clock()):
            db.log_event("INFO", "model_registry", change)
        self.experiment = ensure_experiment(db, cfg, self.clock())

    # -- orchestration ------------------------------------------------------
    def run_cycle(self) -> dict:
        started = time.monotonic()
        self.db.set_state("bot_status", "running cycle")
        summary: dict = {}
        steps = [
            ("markets", self.collect_markets),
            ("forecasts", self.collect_forecasts),
            ("calibration", self.maybe_fit_calibration),
            ("signals", self.predict_and_trade),
            ("settlement", self.settle),
            ("experiment", self.check_experiment),
            ("observations", self.maybe_collect_observations),
            ("learning", self.learn),
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
            closed = True if pm.closed else mk.closed
            conn.execute(update(markets).where(mk.id == pm.id).values({**values, "closed": closed}))

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

    def _params(self) -> param_sets.Params:
        """The production station bias/spread param set (wxbot/learning/params.py)."""
        return param_sets.load(self.db, self.cfg, param_sets.production(self.db))

    def _calibration(self, station: str, kind: str, lead_days: int) -> Calibration:
        return self._params().calibration(station, kind, lead_days)

    # -- 3. probability calibration ---------------------------------------
    def maybe_fit_calibration(self, force: bool = False) -> dict:
        """Refit the probability calibrators at most every refit_hours (DB only,
        no network); see wxbot/calibration/fit.py for the approval rule."""
        now = self.clock()
        last = self.db.get_state("last_calibration_fit")
        hours = float(self.cfg.calibration.refit_hours)
        if not force and last and now - datetime.fromisoformat(last) < timedelta(hours=hours):
            return {"skipped": True}
        rows = fit_round(self.db, self.cfg, self.predictor.version, now, param_sets.production(self.db))
        self.db.set_state("last_calibration_fit", now.isoformat())
        chosen = next((r["version"] for r in rows if r["selected"]), "identity")
        self.db.log_event("INFO", "calibration", f"fit on {rows[0]['n'] if rows else 0} resolved markets: "
                          f"using {chosen}", details={r["method"]: {k: r[k] for k in (
                              "approved", "reason", "brier_before", "brier_after", "log_loss_before",
                              "log_loss_after")} for r in rows})
        return {"n": rows[0]["n"] if rows else 0, "using": chosen}

    # -- 4. predictions, signals, paper bets ---------------------------------
    def predict_and_trade(self) -> dict:
        now = self.clock()
        n_pred = n_shadow = n_bets = 0
        params = self._params()
        calibrator = active_calibrator(self.db, self.cfg, self.predictor.version, now, params.ps)
        history: dict[tuple, dict] = {}     # observed values per (station, kind), read once per cycle
        features: dict[tuple, Features] = {}  # per (station, day, kind, forecast)
        shadow_errors: dict[str, str] = {}
        for m in self._open_tradeable_markets():
            st = get_station(m["station"])
            fc = self._latest_forecast(m["station"], m["local_date"], m["kind"])
            if st is None or fc is None:
                continue
            lead_days = (date.fromisoformat(m["local_date"]) - local_today(st.tz, now)).days
            calib = params.calibration(m["station"], m["kind"], lead_days)
            bucket = Bucket(m["bucket_lo"], m["bucket_hi"], m["unit"])
            quality = fc.get("quality") or {"ok": True, "rejected": {}}
            values = {k: v for k, v in fc["values_c"].items() if k not in quality.get("rejected", {})}
            if not values:
                continue
            key = (m["station"], m["local_date"], m["kind"], fc["id"])
            if key not in features:
                features[key] = self._features(m, st, fc, values, lead_days, now, history)
            feats = features[key]
            pred = self.predictor.predict(bucket, m["kind"], values, lead_days, calib, feats)
            pred.inputs["data_quality"] = quality
            fetched_at = fc["fetched_at"] if fc["fetched_at"].tzinfo else fc["fetched_at"].replace(tzinfo=UTC)
            pred.inputs["forecast_fetched_at"] = fetched_at.isoformat()
            pred.inputs["forecast_source"] = fc["source"]
            pred.inputs["features"] = feats.values
            cal_p = calibrator(pred.p_yes)
            pred_id = self.db.insert(predictions, ts=now, market_id=m["id"], forecast_snapshot_id=fc["id"],
                                     model_version=pred.model_version, lead_days=lead_days, mu_c=pred.mu_c,
                                     sigma_c=pred.sigma_c, p_yes=pred.p_yes, inputs=pred.inputs,
                                     role="production", feature_set=FEATURE_SET, calibrated_prob=cal_p,
                                     calibrator_version=calibrator.version, params_version=params.version)
            n_pred += 1
            n_shadow += self._shadow_predictions(m, fc, bucket, values, lead_days, calib, feats, pred_id, now,
                                                 shadow_errors)
            forecast_age = (now - fetched_at).total_seconds() / 60.0
            if self._signal(m, st, pred, pred_id, forecast_age, now, cal_p, calibrator.version):
                n_bets += 1
        for version, err in shadow_errors.items():
            self.db.log_event("WARNING", "shadow_model", f"{version}: {err}")
        self.db.set_state("last_prediction_time", now.isoformat())
        return {"predictions": n_pred, "shadow_predictions": n_shadow, "bets": n_bets}

    def _features(self, m: dict, st, fc: dict, values: dict, lead_days: int, now: datetime, history: dict):
        hkey = (m["station"], m["kind"])
        if hkey not in history:
            history[hkey] = observed_history(self.db, m["station"], m["kind"], now)
        window = int(self.cfg.model.get("climatology_window_days", 7))
        day_end = now + timedelta(hours=hours_to_day_end(m["local_date"], st.tz, now))
        return build_features(station=m["station"], kind=m["kind"], local_date=m["local_date"], values_c=values,
                              lead_days=lead_days, issue_time=_parse_time(fc.get("issue_time")), day_end=day_end,
                              climatology_c=climatology_window(history[hkey], m["local_date"], window))

    def _shadow_predictions(self, m, fc, bucket, values, lead_days, calib, feats, pred_id, now, errors) -> int:
        """Baselines on the same inputs. Stored for scoring only: never a signal or a bet."""
        n = 0
        for model in self.shadows:
            try:
                sp = model.predict(bucket, m["kind"], values, lead_days, calib, feats)
            except Exception as exc:  # a broken baseline never stops the production model
                errors[model.version] = f"{type(exc).__name__}: {exc}"
                continue
            if sp is None:
                continue
            inputs = {"production_prediction_id": pred_id, **{k: sp.inputs[k] for k in SHADOW_INPUTS if k in sp.inputs}}
            self.db.insert(predictions, ts=now, market_id=m["id"], forecast_snapshot_id=fc["id"],
                           model_version=sp.model_version, lead_days=lead_days, mu_c=sp.mu_c, sigma_c=sp.sigma_c,
                           p_yes=sp.p_yes, inputs=inputs, role="shadow", feature_set=FEATURE_SET)
            n += 1
        return n

    def _latest_snapshot(self, market_id: str) -> dict | None:
        ms = market_snapshots.c
        return self.db.one(select(market_snapshots).where(ms.market_id == market_id).order_by(desc(ms.id)).limit(1))

    def _signal(self, m: dict, st, pred, pred_id: int, forecast_age: float, now: datetime,
                cal_p: float, calibrator_version: str) -> bool:
        """Every rule uses the calibrated probability (the raw one when no
        calibrator is approved); the raw model probability is kept alongside."""
        cfg = self.cfg
        snap = self._latest_snapshot(m["id"]) or {}
        bid, ask, yes_px = snap.get("best_bid"), snap.get("best_ask"), snap.get("yes_price")
        yes_mid = (bid + ask) / 2 if bid is not None and ask is not None else yes_px
        quotes = {  # side -> (calibrated prob, top-of-book ask for that side, mid-implied prob)
            "YES": (cal_p, ask if ask and ask < 1 else None, yes_mid),
            "NO": (1 - cal_p, (1 - bid) if bid else None, None if yes_mid is None else 1 - yes_mid),
        }
        side = rules.best_side(quotes)
        model_prob, top_ask, market_prob = quotes[side]
        raw_prob = pred.p_yes if side == "YES" else 1 - pred.p_yes
        top_price = rules.quoted_entry(top_ask, cfg.strategy)
        bank = portfolio.bankroll(self.db, cfg.bankroll.initial)
        ctx = rules.Context(
            side=side, model_prob=model_prob, market_prob=market_prob, entry_price=top_price,
            liquidity=snap.get("liquidity"), lead_hours=hours_to_day_end(m["local_date"], st.tz, now),
            n_models=len(pred.inputs["model_values_c"]), forecast_age_min=forecast_age, sigma_c=pred.sigma_c,
            market_open=not m["closed"], has_position=portfolio.has_open_position(self.db, m["id"]),
            daily_pnl=portfolio.daily_realized_pnl(self.db, now), initial_bankroll=cfg.bankroll.initial,
            experiment_open=is_open(self.experiment, now),
            data_valid=bool(pred.inputs.get("data_quality", {}).get("ok", True)),
        )
        results = rules.evaluate(ctx, cfg)
        fill = None
        sizing: dict = {}
        if not rules.failed(results):
            token = m["yes_token"] if side == "YES" else m["no_token"]
            asks = self.pm.get_asks(token)
            s, r = cfg.strategy, cfg.risk
            equity = bank.equity  # open positions marked to market
            caps = {
                "sizer": self.sizer.stake(equity, model_prob, top_price),
                "max_bet": r.max_bet_pct * equity,
                "open_exposure_room": r.max_open_exposure_pct * equity - bank.open_exposure,
                "event_exposure_room": r.max_event_exposure_pct * equity
                - portfolio.event_exposure(self.db, m["event_id"]),
                # high and low markets of one city-day move with the same weather
                "station_day_exposure_room": r.max_station_day_exposure_pct * equity
                - portfolio.station_day_exposure(self.db, m["station"], m["local_date"]),
                "cash": bank.cash - CASH_MARGIN,
                "book_capacity": rules.book_capacity(asks, s.slippage, s.fee_rate, cfg.sizing.max_book_share),
            }
            budget = max(0.0, min(caps.values()))
            sizing = {"sizer": self.sizer.name, "equity": round(equity, 4), "cash": round(bank.cash, 4),
                      "open_exposure": round(bank.open_exposure, 4), "caps": {k: round(v, 4) for k, v in caps.items()},
                      "binding_cap": min(caps, key=lambda k: caps[k]), "budget": round(budget, 4)}
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
        probabilities = {"model": round(raw_prob, 6), "calibrated": round(model_prob, 6),
                         "calibrator": calibrator_version,
                         "market": None if market_prob is None else round(market_prob, 6)}
        results_out = ([{"rule": "probabilities", "passed": True, "value": probabilities, "threshold": None}]
                       + results + ([{"rule": "sizing_detail", "passed": True, "value": sizing, "threshold": None}]
                                    if sizing else []))
        sig_id = self.db.insert(
            signals, ts=now, prediction_id=pred_id, market_id=m["id"], side=side, model_prob=raw_prob,
            calibrated_prob=model_prob, market_prob=market_prob, entry_price=price, edge=edge, ev_per_dollar=ev,
            confidence=model_prob,
            proposed_stake=ctx.stake, decision=decision,
            reason="all rules passed" if not bad else "failed: " + ", ".join(bad), rule_results=results_out)
        if decision == "BET":
            assert fill is not None   # a bet passed the rules, so it was sized and filled
            try:
                bet_id = self.broker.place(signal_id=sig_id, market=m, side=side, fill=fill, model_prob=raw_prob,
                                           market_prob=market_prob, edge=edge, ev=ev, confidence=model_prob,
                                           sizing=sizing, market_snapshot=self._trade_snapshot(snap, side, asks))
            except BrokerRefused as exc:
                with self.db.engine.begin() as conn:
                    conn.execute(update(signals).where(signals.c.id == sig_id).values(
                        decision="NO_BET", reason=f"paper broker refused: {exc}"))
                return False
            self.db.log_event("INFO", "paper_bet", f"bet #{bet_id}: {side} '{m['question']}' "
                              f"${fill.total:.2f} @ {fill.avg_price:.3f} (model {raw_prob:.2f}, "
                              f"calibrated {model_prob:.2f})", code="PAPER_BET_OPENED")
            return True
        return False

    @staticmethod
    def _trade_snapshot(snap: dict, side: str, asks: list) -> dict:
        """The quotes when a bet was placed: the market snapshot used for the
        decision, the held side's bid/ask/mid, and the order book's best ask."""
        bid, ask = snap.get("best_bid"), snap.get("best_ask")
        side_bid = bid if side == "YES" else (None if ask is None else round(1 - ask, 6))
        side_ask = ask if side == "YES" else (None if bid is None else round(1 - bid, 6))
        return {"snapshot_id": snap.get("id"), "ts": snap["ts"].isoformat() if snap.get("ts") else None,
                "yes_bid": bid, "yes_ask": ask, "yes_price": snap.get("yes_price"),
                "liquidity": snap.get("liquidity"), "side": side, "bid": side_bid, "ask": side_ask,
                "mid": None if side_bid is None or side_ask is None else round((side_bid + side_ask) / 2, 6),
                "book_best_ask": asks[0].price if asks else None, "book_levels": len(asks)}

    # -- 5. settlement ------------------------------------------------------
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
                settled += len(self.broker.settle_market(market_id, outcome, resolved_at=now, raw={
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
        start = _parse_time(m["pm_created_at"]) or (_parse_time(m["first_seen"]) or now) - timedelta(days=3)
        end = min(_parse_time(m["closed_time"]) or now, now)
        series = self.pm.get_price_history(m["yes_token"], start, end)
        if not series:
            return 0
        kept = price_changes(series)
        with self.db.engine.begin() as conn:
            conn.execute(market_price_history.insert(), [
                dict(market_id=market_id, token="YES", t=t, price=p, fetched_at=now) for t, p in kept])
        return 1

    # -- 6. observations ----------------------------------------------------
    def maybe_collect_observations(self, force: bool = False) -> dict:
        now = self.clock()
        last = self.db.get_state("last_observation_update")
        every = timedelta(hours=self.cfg.schedule.observation_hours)
        if not force and last and now - datetime.fromisoformat(last) < every:
            return {"skipped": True}
        mk = markets.c
        since = (now - timedelta(days=4)).date().isoformat()
        codes = {r["station"] for r in self.db.rows(
            select(mk.station).where(mk.tradeable.is_(True), mk.local_date >= since))}
        stored = 0
        for code in sorted(codes):
            st = get_station(code)
            if st is None:
                continue
            end = local_today(st.tz, now) - timedelta(days=1)
            try:
                obs = self.observer.fetch(st, end - timedelta(days=3), end)
            except Exception as exc:
                self.db.log_event("WARNING", "observations", f"{code}: {type(exc).__name__}: {exc}")
                continue
            stored += self.store_observations(code, obs)
        self.db.set_state("last_observation_update", now.isoformat())
        return {"stations": len(codes), "new_rows": stored}

    def store_observations(self, code: str, obs: dict, quiet: bool = False) -> int:
        """Append observed highs/lows that are new or changed; `quiet` skips the
        per-day warning for rejected days (history loads log one summary)."""
        wo = weather_observations.c
        stored = 0
        for kind, days in obs.items():
            for d, (value, n) in days.items():
                problem = validate_observation(value, n, self.validation)
                if problem:
                    if not quiet:
                        self.db.log_event("WARNING", "validation", f"observation {code} {d} {kind} rejected: "
                                          f"{problem}", details={"value_c": value, "n_reports": n})
                    continue
                prev = self.db.one(select(wo.value_c).where(
                    wo.station == code, wo.local_date == d, wo.kind == kind, wo.source == self.observer.source,
                ).order_by(desc(wo.id)).limit(1))
                if prev is None or abs(prev["value_c"] - value) > 1e-6:
                    self.db.insert(weather_observations, station=code, local_date=d, kind=kind, value_c=value,
                                   n_reports=n, source=self.observer.source, fetched_at=self.clock())
                    stored += 1
        return stored

    # -- 7. learning ---------------------------------------------------------
    def check_experiment(self) -> dict:
        """After the experiment's planned end: log that it ended, and that it is
        complete once its last bet has settled (wxbot/experiment.py)."""
        return check_end(self.db, self.experiment, self.clock())

    def learn(self) -> dict:
        """Record newly resolved markets in the learning ledger, roll back a
        deployed param set that does worse than the one before it, and retrain
        when due (wxbot/learning/)."""
        return learn(self.db, self.cfg, self.history, self.observer, self.clock())

    def retrain(self) -> dict:
        """Retrain now, whether due or not (python main.py retrain)."""
        recorded = outcomes.record(self.db, self.clock())
        return {"outcomes": recorded, **retrain.retrain(self.db, self.cfg, self.history, self.observer,
                                                          self.clock(), force=True)}
