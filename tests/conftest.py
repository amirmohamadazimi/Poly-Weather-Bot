"""Offline fakes for Polymarket and weather sources (no network in tests)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from wxbot.config import load_config
from wxbot.data.polymarket import BookLevel, parse_market
from wxbot.db import Database
from wxbot.engine import Engine
from wxbot.execution.paper import make_broker
from wxbot.model.registry import production_model, shadow_models
from wxbot.strategy.sizing import make_sizer

NOW = datetime(2026, 9, 27, 6, 0, tzinfo=UTC)

# YES prices per bucket for "Highest temperature in London on September 28?"
LONDON_PRICES = {
    "13°C or below": 0.01, "14°C": 0.01, "15°C": 0.02, "16°C": 0.10, "17°C": 0.25, "18°C": 0.30,
    "19°C": 0.20, "20°C": 0.07, "21°C": 0.02, "22°C": 0.01, "23°C or higher": 0.10,  # <- mispriced tail
}


NOAA_EGLC = "https://www.weather.gov/wrh/timeseries?site=EGLC"


def market_description(extreme="highest", station="London City Airport", unit="Celsius", day="28 Sep '26",
                       source="NOAA", link=NOAA_EGLC) -> str:
    """Polymarket's current resolution wording, built from the live NOAA and
    Wunderground templates (verbatim copies are in tests/fixtures/)."""
    eg = "9°C" if unit == "Celsius" else "21°F"
    no_data = ("In the event that there is no data for the observation date by 11:59 PM ET on the day following "
               "the observation date, this market will resolve to the lowest bracket.\n\n")
    timing = ("This market will resolve once the first data point for the following date has been published on "
              "the resolution source, or by 11:59 PM ET on the day following the observation date, whichever "
              "comes first.\n\n")
    precision = (f"The resolution source for this market measures temperatures to whole degrees {unit} (eg, {eg}). "
                 "Thus, this is the level of precision that will be used when resolving the market.")
    if source == "NOAA":
        return (
            f"This market will resolve to the temperature range that contains the {extreme} temperature recorded "
            f"by NOAA at the {station} Station in degrees {unit} on {day}.\n\n"
            f"The resolution source for this market will be information from NOAA, specifically the {extreme} "
            f'reading under the "Temp" column for all times on this day, available here: {link}\n\n'
            "If NOAA data for the observation date is unavailable by 11:59 PM ET on the day following the "
            "observation date, the Weather Underground Daily Observations table will be used as the resolution "
            "source.\n\n" + no_data +
            'To toggle between Fahrenheit and Celsius, click the "Switch to Metric Units" button until the '
            "relevant table displays °C.\n\n" + timing + precision)
    return (
        f"This market will resolve based on the {extreme} temperature recorded in the 'Daily Observations' table "
        "on Weather Underground, not the figure displayed in the 'Day High & Low' summary section; in the event "
        "of any discrepancy between the two, the Daily Observations table shall be the primary resolution source "
        "not the Day High & Low section.\n\n"
        f"This market will resolve to the temperature range that contains the {extreme} temperature recorded "
        f"at the {station} Station in degrees {unit} on {day}.\n\n"
        f"The resolution source for this market will be information from {source}, specifically the {extreme} "
        f"temperature recorded for all times on this day for the {station} Station, available here: {link}.\n\n"
        + no_data +
        "To toggle between Fahrenheit and Celsius, click the gear icon next to the search bar and switch the "
        "Temperature setting between °F and °C.\n\n" + timing + precision)


def london_event() -> dict:
    markets = []
    for i, (label, px) in enumerate(LONDON_PRICES.items()):
        markets.append({
            "id": str(1000 + i), "question": f"Will the highest temperature in London be {label} on September 28?",
            "groupItemTitle": label, "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps([str(px), str(round(1 - px, 4))]),
            "clobTokenIds": json.dumps([f"y{1000 + i}", f"n{1000 + i}"]),
            "bestBid": round(px - 0.01, 4), "bestAsk": round(px + 0.01, 4), "lastTradePrice": px,
            "liquidityNum": 5000, "volumeNum": 12000, "closed": False, "endDate": "2026-09-28T12:00:00Z",
            "createdAt": "2026-09-26T10:00:00Z",
            "resolutionSource": NOAA_EGLC,
            "description": market_description(),
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
        m["description"] = market_description(station="Atlantis Intl", source="Wunderground",
                                              link=m["resolutionSource"])
    return ev


class FakePolymarket:
    def __init__(self, events):
        self.events = events
        self.resolved: dict[str, str] = {}
        self.book_requests: list[str] = []
        self.history_requests: list[tuple] = []
        self.history_error: Exception | None = None             # every token
        self.history_errors: dict[str, Exception] = {}          # one token
        self.history_series: dict[str, list] = {}                # token -> [(t, p)], [] = empty

    def discover(self, kinds=None):
        return [parse_market(ev, mk, kinds) for ev in self.events for mk in ev["markets"]]

    def get_market(self, market_id):
        for ev in self.events:
            for mk in ev["markets"]:
                if mk["id"] == market_id:
                    out = dict(mk)
                    if market_id in self.resolved:
                        out["closed"] = True
                        out["closedTime"] = "2026-09-29 12:00:00+00"
                        won = self.resolved[market_id] == "YES"
                        out["outcomePrices"] = json.dumps(["1", "0"] if won else ["0", "1"])
                    return out
        raise KeyError(market_id)

    def get_price_history(self, token_id, start, end, fidelity_min=60):
        self.history_requests.append((token_id, start, end))
        if self.history_error or token_id in self.history_errors:
            raise self.history_error or self.history_errors[token_id]
        if token_id in self.history_series:
            return self.history_series[token_id]
        return [(start + timedelta(hours=h), round(0.1 + h / 100, 4)) for h in range(3)]

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


def make_engine(cfg, db=None, pm=None, forecast=None, clock=None, shadows=None):
    db = db or Database(cfg.app.database_url)
    return Engine(cfg=cfg, db=db, polymarket=pm or FakePolymarket([london_event(), unknown_event()]),
                  forecaster=forecast or FakeForecast(), observer=FakeObservations(),
                  predictor=production_model(cfg), broker=make_broker(cfg, db), sizer=make_sizer(cfg),
                  clock=clock or Clock(), shadows=shadow_models(cfg) if shadows is None else shadows)
