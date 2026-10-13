"""v2 M3: resolution criteria, market fields, price history, migrations."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text, update

from tests.conftest import NOAA_EGLC, FakePolymarket, london_event, make_engine, market_description
from wxbot.data.polymarket import CRITERIA_SKIP, PolymarketClient, check_criteria, parse_criteria, parse_market
from wxbot.db import (
    Database, market_criteria_history, market_price_history, market_resolutions, market_snapshots, markets, paper_bets,
    system_events,
)
from wxbot.engine import PRICE_HISTORY_TRIES
from wxbot.web.app import create_app

TAIL_MARKET = "1010"
JINAN_WU = "https://www.wunderground.com/history/daily/cn/jinan/ZSJN"
FIXTURES = Path(__file__).parent / "fixtures"


def jinan_event() -> dict:
    ev = london_event()
    ev.update(id="ev3", title="Lowest temperature in Jinan on September 28?", slug="jinan")
    for m in ev["markets"]:
        m["id"] = "3" + m["id"]
        m["resolutionSource"] = JINAN_WU
        m["description"] = market_description(extreme="lowest", station="Jinan Yaoqiang International Airport",
                                              source="Wunderground", link=JINAN_WU)
    return ev


def test_noaa_wording_is_parsed():
    c = parse_criteria(market_description(), NOAA_EGLC)
    assert c["rule_found"] and c["extreme"] == "high" and c["unit"] == "C" and c["date"] == "2026-09-28"
    assert c["station_name"] == "London City Airport" and c["station_codes"] == ["EGLC"]
    assert c["primary_source"] == "NOAA" and c["named_sources"] == ["NOAA"]
    assert c["precision"] == "whole_degrees" and c["precision_unit"] == "C"


def test_wunderground_wording_is_parsed_and_tradeable():
    c = parse_criteria(jinan_event()["markets"][0]["description"], JINAN_WU)
    assert c["extreme"] == "low" and c["station_name"] == "Jinan Yaoqiang International Airport"
    assert c["primary_source"] == "Wunderground" and c["named_sources"] == ["Wunderground"]
    assert c["station_codes"] == ["ZSJN"] and c["date"] == "2026-09-28"
    ev = jinan_event()
    pm = parse_market(ev, ev["markets"][5], ["high", "low"])
    assert pm.tradeable and pm.kind == "low" and pm.station == "ZSJN" and pm.criteria["problems"] == []


def test_other_date_spellings():
    for day in ("28 September '26", "September 28, 2026", "Sept 28, 2026", "28 Sep ’26"):
        assert parse_criteria(market_description(day=day), NOAA_EGLC)["date"] == "2026-09-28", day


@pytest.mark.parametrize("change,problem", [
    ({"description": market_description(extreme="lowest")}, "text says low temperature, title says high"),
    ({"description": market_description(unit="Fahrenheit")}, "text unit F, bucket unit C"),
    ({"description": market_description(day="29 Sep '26")}, "text date 2026-09-29, title date 2026-09-28"),
    ({"description": market_description(day="the 28th")}, "text date not recognised"),
    ({"description": market_description().replace("to whole degrees Celsius", "to tenths of a degree Celsius")},
     "precision not stated as whole degrees"),
    ({"resolutionSource": "https://example.com/obs?site=EGLC"}, "resolution source not recognised"),
    ({"description": market_description(source="Wunderground")}, "text names Wunderground as source, link is NOAA"),
    ({"description": market_description(link="https://www.weather.gov/wrh/timeseries?site=EGLL")},
     "conflicting station codes: EGLC, EGLL"),
    ({"description": market_description() + " The lowest temperature is also reported."},
     "text mentions both highest and lowest temperature"),
    ({"description": "Resolves to the London reading."}, "resolution rule sentence not recognised"),
    ({"description": market_description().replace("specifically the highest reading",
                                                  "specifically the lowest reading")},
     "text mentions both highest and lowest temperature"),
    ({"description": market_description() + "\n\nThe resolution source reports in degrees Fahrenheit."},
     "text mentions both Celsius and Fahrenheit"),
    ({"description": market_description().replace("whole degrees Celsius (eg, 9°C)", "whole degrees Fahrenheit")},
     "precision unit F, bucket unit C"),
    ({"description": market_description() + "\n\nClarification: this market will resolve to the temperature range "
                     "that contains the highest temperature recorded by NOAA at the London City Airport Station "
                     "in degrees Celsius on 29 Sep '26."},
     "text has resolution rule sentences that disagree"),
])
def test_each_criteria_mismatch_makes_market_untradeable(change, problem):
    ev = london_event()
    mk = {**ev["markets"][5], **change}
    pm = parse_market(ev, mk, ["high", "low"])
    assert not pm.tradeable
    assert pm.skip_reason.startswith(CRITERIA_SKIP) and problem in pm.skip_reason
    assert any(problem in p for p in pm.criteria["problems"])


def test_market_fields_and_criteria_skips_are_stored(cfg):
    ev = london_event()
    ev["markets"][0]["description"] = market_description(day="29 Sep '26")
    eng = make_engine(cfg, pm=FakePolymarket([ev]))
    eng.run_cycle()
    good = eng.db.one(select(markets).where(markets.c.id == "1005"))
    assert good["outcomes"] == ["Yes", "No"] and good["pm_created_at"] is not None
    assert good["criteria"]["primary_source"] == "NOAA" and good["criteria"]["problems"] == []
    bad = eng.db.one(select(markets).where(markets.c.id == "1000"))
    assert not bad["tradeable"] and bad["skip_reason"].startswith(CRITERIA_SKIP)
    assert bad["criteria"]["date"] == "2026-09-29"
    # untradeable markets still get price/liquidity/volume snapshots
    snap = eng.db.one(select(market_snapshots).where(market_snapshots.c.market_id == "1000"))
    assert snap["volume"] == 12000 and snap["liquidity"] == 5000
    api = TestClient(create_app(cfg, eng.db, now=eng.clock)).get("/api/markets").json()
    assert api["skipped_criteria"] == 1


def test_price_history_stored_once_after_resolution(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.pm.resolved[TAIL_MARKET] = "NO"
    eng.clock.now += timedelta(days=2)
    assert eng.settle()["price_histories"] == 1
    rows = eng.db.rows(select(market_price_history))
    assert len(rows) == 3 and {r["market_id"] for r in rows} == {TAIL_MARKET} and rows[0]["token"] == "YES"
    token, start, _ = eng.pm.history_requests[0]
    assert token == "y" + TAIL_MARKET and start.isoformat().startswith("2026-09-26T10:00")
    m = eng.db.one(select(markets).where(markets.c.id == TAIL_MARKET))
    assert m["resolved_outcome"] == "NO" and m["closed_time"] is not None
    eng.settle()
    assert len(eng.pm.history_requests) == 1 and len(eng.db.rows(select(market_price_history))) == 3


def test_price_history_failure_never_breaks_settlement(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.pm.resolved[TAIL_MARKET] = "NO"
    eng.pm.history_error = RuntimeError("CLOB down")
    eng.clock.now += timedelta(days=2)
    out = eng.settle()
    assert out["bets_settled"] == 1 and out["price_histories"] == 0
    assert eng.db.one(select(paper_bets))["status"] == "WON"
    assert eng.db.one(select(system_events).where(system_events.c.component == "price_history"))
    eng.pm.history_error = None          # retried on the next cycle
    assert eng.settle()["price_histories"] == 1


def test_client_reads_prices_history():
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"history": [{"t": 1790000000, "p": 0.12}, {"t": 1790003600, "p": "0.15"}]}

    class Session:
        def get(self, url, params=None, timeout=None):
            self.url, self.params = url, params
            return Resp()

    s = Session()
    start, end = datetime(2026, 9, 26, tzinfo=UTC), datetime(2026, 9, 29, tzinfo=UTC)
    out = PolymarketClient(session=s).get_price_history("tok", start, end)
    assert s.url.endswith("/prices-history") and s.params["market"] == "tok" and s.params["fidelity"] == 60
    assert s.params["startTs"] == int(start.timestamp()) and s.params["endTs"] == int(end.timestamp())
    assert [p for _, p in out] == [0.12, 0.15] and out[0][0].tzinfo is not None


def test_migration_adds_market_columns_to_an_old_database(tmp_path, cfg):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:      # a markets table from before v2 M3
        for col in ("outcomes", "pm_created_at", "criteria", "closed_time", "price_history_tries"):
            conn.execute(text(f"ALTER TABLE markets DROP COLUMN {col}"))
        conn.execute(text("DROP TABLE market_price_history"))
        conn.execute(text("INSERT INTO markets (id, question, first_seen, last_seen) "
                          "VALUES ('old1', 'an old market', '2026-09-01', '2026-09-01')"))
    db = Database(url)
    cols = {c["name"] for c in inspect(db.engine).get_columns("markets")}
    assert {"outcomes", "pm_created_at", "criteria", "closed_time", "price_history_tries"} <= cols
    assert "market_price_history" in inspect(db.engine).get_table_names()
    assert db.one(select(markets).where(markets.c.id == "old1"))["question"] == "an old market"
    eng = make_engine(cfg, db=db)
    assert eng.collect_markets()["tradeable"] == 11
    assert db.one(select(markets).where(markets.c.id == "1005"))["outcomes"] == ["Yes", "No"]


# -- verbatim Polymarket descriptions (tests/fixtures, copied from live markets) --

@pytest.mark.parametrize("name,link,kind,unit,station", [
    ("london_highest", NOAA_EGLC.replace("EGLC", "eglc"), "high", "C", "EGLC"),
    ("london_lowest", NOAA_EGLC.replace("EGLC", "eglc"), "low", "C", "EGLC"),
    ("nyc_highest", "https://www.weather.gov/wrh/timeseries?site=klga", "high", "F", "KLGA"),
    ("jinan_lowest", JINAN_WU, "low", "C", "ZSJN"),
    ("tel_aviv_highest", "", "high", "C", "LLBG"),   # no "Station" suffix, empty resolutionSource
])
def test_real_descriptions_parse_cleanly(name, link, kind, unit, station):
    text_ = (FIXTURES / f"{name}.txt").read_text()
    c = parse_criteria(text_, link)
    assert c["rule_found"] and c["rules_agree"] and c["extreme"] == kind and c["unit"] == unit
    assert c["date"] == "2026-09-28" and c["station_codes"] == [station]
    assert c["precision"] == "whole_degrees" and c["precision_unit"] == unit
    assert check_criteria(c, kind, unit, "2026-09-28") == []


def test_real_noaa_description_keeps_fallback_and_hourly_rules():
    nyc = parse_criteria((FIXTURES / "nyc_highest.txt").read_text(), "")
    assert nyc["primary_source"] == "NOAA" and nyc["fallback_source"] == "Wunderground" and nyc["hourly_only"]
    london = parse_criteria((FIXTURES / "london_highest.txt").read_text(), "")
    assert london["fallback_source"] == "Wunderground" and not london["hourly_only"]
    assert london["no_data_rule"] == "lowest bracket"


def test_real_markets_stay_tradeable():
    for name, link, label in (("london_highest", NOAA_EGLC, "18°C"), ("jinan_lowest", JINAN_WU, "18°C")):
        ev = london_event() if name.startswith("london") else {
            **london_event(), "title": "Lowest temperature in Jinan on September 28?"}
        mk = next(m for m in ev["markets"] if m["groupItemTitle"] == label)
        pm = parse_market(ev, {**mk, "description": (FIXTURES / f"{name}.txt").read_text(),
                               "resolutionSource": link}, ["high", "low"])
        assert pm.tradeable, (name, pm.skip_reason)


def test_real_hong_kong_description_is_not_tradeable():
    c = parse_criteria((FIXTURES / "hong_kong_highest.txt").read_text(), "https://www.weather.gov.hk/en/cis/climat.htm")
    problems = check_criteria(c, "high", "C", "2026-09-28")
    assert c["primary_source"] == "HKO"
    assert problems == ["resolution rule sentence not recognised", "precision not stated as whole degrees"]


def test_real_wording_swap_to_lowest_reading_is_caught():
    text_ = (FIXTURES / "london_highest.txt").read_text().replace("highest reading", "lowest reading")
    problems = check_criteria(parse_criteria(text_, NOAA_EGLC), "high", "C", "2026-09-28")
    assert problems == ["text mentions both highest and lowest temperature"]


# -- criteria history ---------------------------------------------------------

def test_criteria_history_keeps_only_replaced_text(cfg):
    eng = make_engine(cfg)
    eng.collect_markets()
    eng.collect_markets()                      # same text again
    assert eng.db.rows(select(market_criteria_history)) == []
    first = eng.db.one(select(markets).where(markets.c.id == "1005"))
    eng.pm.events[0]["markets"][5]["description"] = market_description(day="29 Sep '26")
    eng.clock.now += timedelta(hours=3)
    eng.collect_markets()
    rows = eng.db.rows(select(market_criteria_history))
    assert len(rows) == 1 and rows[0]["market_id"] == "1005"
    assert rows[0]["description"] == first["description"] and rows[0]["criteria"]["problems"] == []
    assert rows[0]["replaced_at"] > rows[0]["last_seen"]
    now = eng.db.one(select(markets).where(markets.c.id == "1005"))
    assert "29 Sep" in now["description"] and not now["tradeable"]


# -- settlement of untradeable markets -------------------------------------------

def test_untradeable_markets_get_their_result(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    skipped = eng.db.one(select(markets).where(markets.c.id == "91005"))
    assert not skipped["tradeable"]
    eng.pm.resolved["91005"] = "YES"
    eng.clock.now += timedelta(days=2)
    eng.settle()
    m = eng.db.one(select(markets).where(markets.c.id == "91005"))
    assert m["resolved_outcome"] == "YES" and m["closed"] and m["closed_time"] is not None
    assert eng.db.one(select(market_resolutions).where(market_resolutions.c.market_id == "91005"))


def test_result_checks_without_bets_are_capped(cfg):
    cfg._data["markets"]["max_result_checks_per_cycle"] = 5
    eng = make_engine(cfg)
    eng.run_cycle()
    open_bets = {r["market_id"] for r in eng.db.rows(select(paper_bets.c.market_id))}
    eng.clock.now += timedelta(days=2)
    asked = []
    get_market = eng.pm.get_market
    eng.pm.get_market = lambda mid: asked.append(mid) or get_market(mid)
    eng.settle()
    assert open_bets <= set(asked) and len(asked) == len(open_bets) + 5
    assert eng.db.one(select(system_events).where(system_events.c.message.like("%left for later cycles")))


# -- price history ---------------------------------------------------------------

def _resolve(eng, *ids):
    for mid in ids:
        eng.pm.resolved[mid] = "NO"
    eng.clock.now += timedelta(days=2)


def _tries(eng, mid):
    return eng.db.one(select(markets.c.price_history_tries).where(markets.c.id == mid))["price_history_tries"]


def test_one_failing_market_does_not_block_the_others(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve(eng, "1009", "1010")
    eng.pm.history_errors["y1009"] = ValueError("bad point")   # 1009 is asked first
    assert eng.settle()["price_histories"] == 1
    assert {r["market_id"] for r in eng.db.rows(select(market_price_history))} == {"1010"}
    assert _tries(eng, "1009") == 1
    for _ in range(PRICE_HISTORY_TRIES):
        eng.settle()
    assert _tries(eng, "1009") == PRICE_HISTORY_TRIES
    n = len(eng.pm.history_requests)
    eng.settle()                                               # given up: not asked again
    assert len(eng.pm.history_requests) == n


def test_unreachable_clob_stops_the_pass(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve(eng, "1009", "1010")
    eng.pm.history_error = requests.ConnectionError("no route")
    assert eng.settle()["price_histories"] == 0
    assert [t for t, _, _ in eng.pm.history_requests] == ["y1009"]
    eng.pm.history_error = None
    assert eng.settle()["price_histories"] == 2


def test_empty_history_is_tried_three_times_then_given_up(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve(eng, TAIL_MARKET)
    eng.pm.history_series["y" + TAIL_MARKET] = []
    for _ in range(PRICE_HISTORY_TRIES + 2):
        eng.settle()
    assert len(eng.pm.history_requests) == PRICE_HISTORY_TRIES and _tries(eng, TAIL_MARKET) == PRICE_HISTORY_TRIES
    levels = [r["level"] for r in eng.db.rows(select(system_events.c.level)
                                                .where(system_events.c.component == "price_history"))]
    assert levels == ["INFO"] * (PRICE_HISTORY_TRIES - 1) + ["WARNING"]


def test_price_histories_are_capped_newest_first(cfg):
    cfg._data["markets"]["max_price_histories_per_cycle"] = 1
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve(eng, "1009", "1010")
    with eng.db.engine.begin() as conn:
        conn.execute(update(markets).where(markets.c.id == "1010").values(local_date="2026-09-29"))
    assert eng.settle()["price_histories"] == 1
    assert [t for t, _, _ in eng.pm.history_requests] == ["y1010"]
    assert eng.settle()["price_histories"] == 1
    assert eng.settle()["price_histories"] == 0


def test_price_history_keeps_only_price_changes_until_close(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve(eng, TAIL_MARKET)
    t0 = datetime(2026, 9, 27, tzinfo=UTC)
    prices = [0.10, 0.10, 0.12, 0.12, 0.12, 0.05, 0.05]
    eng.pm.history_series["y" + TAIL_MARKET] = [(t0 + timedelta(hours=h), p) for h, p in enumerate(prices)]
    eng.clock.now += timedelta(days=1)         # well after the close
    eng.settle()
    rows = eng.db.rows(select(market_price_history).order_by(market_price_history.c.t))
    assert [(r["t"].hour, r["price"]) for r in rows] == [(0, 0.10), (2, 0.12), (5, 0.05), (6, 0.05)]
    _, _, end = eng.pm.history_requests[0]
    assert end == datetime(2026, 9, 29, 12, tzinfo=UTC)   # the market's close, not now


def test_dashboard_lists_markets_whose_title_did_not_parse(cfg):
    ev = london_event()
    ev["title"] = "Temperature in London this week?"
    eng = make_engine(cfg, pm=FakePolymarket([ev]))
    eng.collect_markets()
    api = TestClient(create_app(cfg, eng.db, now=eng.clock)).get("/api/markets").json()
    assert {r["skip_reason"]: r["n"] for r in api["skipped"]} == {"title not recognised": 11}
