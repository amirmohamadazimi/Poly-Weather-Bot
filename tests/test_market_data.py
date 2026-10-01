"""v2 M3: resolution criteria, market fields, price history, migrations."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from tests.conftest import NOAA_EGLC, FakePolymarket, london_event, make_engine, market_description
from wxbot.data.polymarket import CRITERIA_SKIP, PolymarketClient, parse_criteria, parse_market
from wxbot.db import Database, market_price_history, market_snapshots, markets, paper_bets, system_events
from wxbot.web.app import create_app

TAIL_MARKET = "1010"
JINAN_WU = "https://www.wunderground.com/history/daily/cn/jinan/ZSJN"


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
    start, end = datetime(2026, 9, 26, tzinfo=timezone.utc), datetime(2026, 9, 29, tzinfo=timezone.utc)
    out = PolymarketClient(session=s).get_price_history("tok", start, end)
    assert s.url.endswith("/prices-history") and s.params["market"] == "tok" and s.params["fidelity"] == 60
    assert s.params["startTs"] == int(start.timestamp()) and s.params["endTs"] == int(end.timestamp())
    assert [p for _, p in out] == [0.12, 0.15] and out[0][0].tzinfo is not None


def test_migration_adds_market_columns_to_an_old_database(tmp_path, cfg):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:      # a markets table from before v2 M3
        for col in ("outcomes", "pm_created_at", "criteria", "closed_time"):
            conn.execute(text(f"ALTER TABLE markets DROP COLUMN {col}"))
        conn.execute(text("DROP TABLE market_price_history"))
        conn.execute(text("INSERT INTO markets (id, question, first_seen, last_seen) "
                          "VALUES ('old1', 'an old market', '2026-09-01', '2026-09-01')"))
    db = Database(url)
    cols = {c["name"] for c in inspect(db.engine).get_columns("markets")}
    assert {"outcomes", "pm_created_at", "criteria", "closed_time"} <= cols
    assert "market_price_history" in inspect(db.engine).get_table_names()
    assert db.one(select(markets).where(markets.c.id == "old1"))["question"] == "an old market"
    eng = make_engine(cfg, db=db)
    assert eng.collect_markets()["tradeable"] == 11
    assert db.one(select(markets).where(markets.c.id == "1005"))["outcomes"] == ["Yes", "No"]
