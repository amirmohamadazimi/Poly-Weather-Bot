from datetime import datetime, timezone

import pytest

from tests.conftest import london_event, unknown_event
from wxbot.data.polymarket import Bucket, parse_bucket, parse_market, parse_station, parse_title, resolved_outcome
from wxbot.data.weather import IEMObservations, daily_extreme, split_model_series
from wxbot.data.stations import STATIONS


@pytest.mark.parametrize("label,expected", [
    ("16°C", Bucket(16, 16, "C")),
    ("15°C or below", Bucket(None, 15, "C")),
    ("25°C or higher", Bucket(25, None, "C")),
    ("80-81°F", Bucket(80, 81, "F")),
    ("79°F or below", Bucket(None, 79, "F")),
    ("90°F or above", Bucket(90, None, "F")),
    ("-2°C", Bucket(-2, -2, "C")),
    ("Will it be 70-71°F?", Bucket(70, 71, "F")),
    ("no temperature here", None),
])
def test_parse_bucket(label, expected):
    assert parse_bucket(label) == expected


def test_parse_title_with_and_without_year():
    end = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    assert parse_title("Highest temperature in London on September 28?", end) == ("high", "London", "2026-09-28")
    assert parse_title("Lowest temperature in NYC on January 2, 2027", end) == ("low", "NYC", "2027-01-02")
    # a late-December market listed in early January keeps the previous year
    assert parse_title("Highest temperature in Seoul on December 31?",
                       datetime(2027, 1, 1, tzinfo=timezone.utc))[2] == "2026-12-31"
    assert parse_title("Will it rain in London?", end) == (None, None, None)


def test_parse_station_sources():
    assert parse_station("https://www.wunderground.com/history/daily/cn/jinan/ZSJN", "") == "ZSJN"
    assert parse_station("https://www.weather.gov/wrh/timeseries?site=eglc", "") == "EGLC"
    assert parse_station("https://www.weather.gov.hk/en/cis/climat.htm", "") == "HKO"
    assert parse_station("", "") is None


def test_parse_market_tradeable_and_skips():
    ev = london_event()
    pm = parse_market(ev, ev["markets"][5], ["high", "low"])
    assert pm.tradeable and pm.station == "EGLC" and pm.local_date == "2026-09-28"
    assert pm.bucket == Bucket(18, 18, "C") and pm.yes_token == "y1005" and pm.no_token == "n1005"
    bad = unknown_event()
    assert parse_market(bad, bad["markets"][0]).skip_reason == "station ZZZZ not in station table"
    assert parse_market(ev, ev["markets"][0], ["low"]).skip_reason == "kind 'high' disabled"


def test_hong_kong_is_not_traded():
    assert not STATIONS["HKO"].enabled


def test_resolved_outcome():
    assert resolved_outcome({"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["0","1"]'}) == "NO"
    assert resolved_outcome({"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}) == "YES"
    assert resolved_outcome({"closed": False, "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}) is None
    assert resolved_outcome({"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'}) is None


def test_open_meteo_parsing():
    hourly = {"time": [f"2026-09-28T{h:02d}:00" for h in range(24)] + ["2026-09-29T00:00"],
              "temperature_2m_m1": [10 + h * 0.5 for h in range(24)] + [5],
              "temperature_2m_m2": [None] * 25}
    series = split_model_series(hourly, "temperature_2m", ["m1", "m2", "m3"])
    assert set(series) == {"m1", "m2"}
    assert daily_extreme(hourly["time"], series["m1"], "high") == {"2026-09-28": 21.5}
    assert daily_extreme(hourly["time"], series["m2"], "high") == {}  # incomplete days are dropped


def test_iem_csv_uses_local_day():
    st = STATIONS["KLGA"]
    rows = ["station,valid,tmpf"]
    # 2026-09-28 local (EDT, UTC-4) runs 04:00Z 28th .. 04:00Z 29th
    for h in range(24):
        rows.append(f"LGA,2026-09-28 {h:02d}:51,{60 + h}")
    rows += ["LGA,2026-09-29 00:51,95", "LGA,2026-09-29 01:51,M", "LGA,2026-09-29 02:51,70", "LGA,2026-09-29 03:51,70"]
    from datetime import date
    out = IEMObservations.parse_csv("\n".join(rows), st, date(2026, 9, 28), date(2026, 9, 28))
    assert round(out["high"]["2026-09-28"][0], 2) == round((95 - 32) * 5 / 9, 2)
    assert IEMObservations.iem_id("KLGA") == "LGA" and IEMObservations.iem_id("EGLC") == "EGLC"


def test_forecast_falls_back_to_one_request_per_model():
    import requests
    from wxbot.data.weather import OpenMeteoForecast

    times = [f"2026-09-28T{h:02d}:00" for h in range(24)]

    class Resp:
        def __init__(self, status, body):
            self.status_code, self.body, self.text = status, body, str(body)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)

        def json(self):
            return self.body

    class Session:
        def get(self, url, params=None, timeout=None):
            models = params["models"].split(",")
            if len(models) > 1 or models[0] == "bad_model":
                return Resp(400, {"error": True, "reason": "unknown model"})
            return Resp(200, {"hourly": {"time": times, "temperature_2m": [15.0 + h / 10 for h in range(24)]}})

    by_kind, meta = OpenMeteoForecast(["good_a", "bad_model", "good_b"], session=Session()).fetch(STATIONS["EGLC"])
    assert by_kind["high"]["2026-09-28"] == {"good_a": 17.3, "good_b": 17.3}
