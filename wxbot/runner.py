"""Wiring and the autonomous background loop."""
from __future__ import annotations

import logging
import threading

from wxbot.data.polymarket import PolymarketClient
from wxbot.data.weather import IEMObservations, OpenMeteoForecast
from wxbot.db import Database, utcnow
from wxbot.engine import Engine
from wxbot.execution.paper import make_broker
from wxbot.model.registry import production_model, shadow_models
from wxbot.strategy.sizing import make_sizer

log = logging.getLogger("wxbot.runner")


def build_engine(cfg, db: Database | None = None) -> Engine:
    db = db or Database(cfg.app.database_url)
    return Engine(
        cfg=cfg, db=db,
        polymarket=PolymarketClient(tag_slug=cfg.markets.tag_slug),
        forecaster=OpenMeteoForecast(list(cfg.weather.models)),
        observer=IEMObservations(),
        predictor=production_model(cfg),
        shadows=shadow_models(cfg),
        broker=make_broker(cfg, db),
        sizer=make_sizer(cfg),
    )


class Runner:
    """Runs Engine.run_cycle every `cycle_minutes` in a daemon thread."""

    def __init__(self, engine: Engine, cycle_minutes: float):
        self.engine = engine
        self.interval = cycle_minutes * 60
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.paused = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="wxbot-loop", daemon=True)
        self._thread.start()
        self.engine.db.set_state("loop_started_at", utcnow().isoformat())

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def trigger(self) -> None:
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.engine.db.set_state("bot_status", "paused" if paused else "idle")
        self.engine.db.log_event("INFO", "runner", "loop paused" if paused else "loop resumed")

    def run_once(self) -> dict:
        with self._lock:  # never two cycles at once
            return self.engine.run_cycle()

    def _loop(self) -> None:
        log.info("autonomous loop started (every %.0f min)", self.interval / 60)
        while not self._stop.is_set():
            if not self.paused:
                try:
                    self.run_once()
                except Exception as exc:  # the loop must survive anything
                    log.exception("cycle crashed")
                    self.engine.db.log_event("ERROR", "runner", f"cycle crashed: {exc}")
            self._wake.wait(self.interval)
            self._wake.clear()
        log.info("autonomous loop stopped")

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
