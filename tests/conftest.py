"""Offline fakes for Polymarket and weather sources (no network in tests)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from wxbot.config import load_config
from wxbot.data.polymarket import BookLevel, parse_market
from wxbot.db import Database
from wxbot.engine import Engine
from wxbot.execution.paper import make_broker
from wxbot.model.normal import NormalMultiModel
from wxbot.strategy.sizing import make_sizer

NOW = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)

# YES prices per bucket for "Highest temperature in London on September 28?"
LONDON_PRICES = {
    "13°C or below": 0.01, "14°C": 0.01, "15°C": 0.02, "16°C": 0.10, "17°C": 0.25, "18°C": 0.30,
    "19°C": 0.20, "20°C": 0.07, "21°C": 0.02, "22°C": 0.01, "23°C or higher": 0.10,  # <- mispriced tail
}


def london_event() -> dict:
    markets = []
    for i, (label, px) in enumerate(LONDON_PRICES.items()):
        num = label.split("°")[0]
        markets.append({
            "id": str(1000 + i), "question": f"Will the highest temperature in London be {label} on September 28?",
            "groupItemTitle": label, "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps([str(px), str(round(1 - px, 4))]),
            "clobTokenIds": json.dumps([f"y{1000 + i}", f"n{1000 + i}"]),
            "bestBid": round(px - 0.01, 4), "bestAsk": round(px + 0.01, 4), "lastTradePrice": px,
            "liquidityNum": 5000, "volumeNum": 12000, "closed": False, "endDate": "2026-09-28T12:00:00Z",
            "resolutionSource": "https://www.wunderground.com/history/daily/gb/london/EGLC",
            "description": f"This market will resolve to the temperature range that contains the highest "
                           f"temperature recorded at the London City Airport Station in degrees Celsius on 28 Sep '26 ({num}).",
        })
    return {"id": "ev1", "title": "Highest temperature in London on September 28?",
            "slug": "highest-temperature-in-london-on-september-28-2026", "endDate": "2026-09-28T12:00:00Z",
            "markets": markets}


def unknown_event() -> dict:
    ev = london_event()
    ev.update(id="ev2", title="Highest temperature in Atlantis on September 28?", slug="atlantis")
    for m in ev["markets"]:
        m["id"] = "9" + m["id"]
        m["resolutionSource"] = "https://www.wunderground.com/history/daily/xx/atlantis/ZZZZ"
    return ev


class FakePolymarket:
    def __init__(self, events):
        self.events = events
        self.resolved: dict[str, str] = {}
        self.book_requests: list[str] = []

    def discover(self, kinds=None):
        return [parse_market(ev, mk, kinds) for ev in self.events for mk in ev["markets"]]

    def get_market(self, market_id):
        for ev in self.events:
            for mk in ev["markets"]:
                if mk["id"] == market_id:
                    out = dict(mk)
                    if market_id in self.resolved:
                        out["closed"] = True
                        out["outcomePrices"] = json.dumps(["1", "0"] if self.resolved[market_id] == "YES" else ["0", "1"])
                    return out
        raise KeyError(market_id)

    def get_asks(self, token_id):
        self.book_requests.append(token_id)
        mid = token_id[1:]
        mk = next(m for ev in self.events for m in ev["markets"] if m["id"] == mid)
        ask = mk["bestAsk"] if token_id.startswith("y") else round(1 - mk["bestBid"], 4)
        return [BookLevel(ask, 200.0), BookLevel(round(ask + 0.01, 4), 500.0)]


class FakeForecast:
    source = "fake-forecast"
    models = ["m1", "m2", "m3", "m4", "m5"]

    def __init__(self, values=(17.6, 18.0, 18.2, 17.9, 18.3)):
        self.values = dict(zip(self.models, values))

    def fetch(self, station, days=5):
        by = {d: dict(self.values) for d in ("2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29")}
        return {"high": by, "low": {d: {k: v - 8 for k, v in vals.items()} for d, vals in by.items()}}, {"fake": True}


class FakeObservations:
    source = "fake-obs"

    def fetch(self, station, start, end):
        return {"high": {"2026-09-26": (18.0, 24)}, "low": {"2026-09-26": (9.0, 24)}}


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def cfg(tmp_path):
    return load_config(env={"WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path / 'test.sqlite3'}"})


def make_engine(cfg, db=None, pm=None, forecast=None, clock=None):
    db = db or Database(cfg.app.database_url)
    return Engine(cfg=cfg, db=db, polymarket=pm or FakePolymarket([london_event(), unknown_event()]),
                  forecaster=forecast or FakeForecast(), observer=FakeObservations(),
                  predictor=NormalMultiModel(cfg.model.version, cfg.model.prob_floor, cfg.model.prob_ceiling),
                  broker=make_broker(cfg, db), sizer=make_sizer(cfg), clock=clock or Clock())
