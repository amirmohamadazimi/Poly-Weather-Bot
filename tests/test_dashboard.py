"""v2 M7: dashboard. Live-market prices and positions, the portfolio view,
bet search, model-performance series, error analysis and system health."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import NOW, FakeForecast, make_engine
from wxbot.db import Database, market_resolutions, markets, paper_bets, predictions, signals
from wxbot.evaluation.errors import FLAG_Z, bucket_distance, classify, error_analysis
from wxbot.evaluation.metrics import daily_scores, resolved_rows
from wxbot.health import as_utc
from wxbot.report import build_report, to_markdown
from wxbot.web.app import create_app

TAIL_MARKET = "1010"   # "23°C or higher": the engine's one bet, NO
WINNER = "1005"        # "18°C"
MODEL = "normal-multimodel-v1"


def _client(eng):
    return TestClient(create_app(eng.cfg, eng.db, now=eng.clock))


def _resolve_london(eng):
    for i in range(11):
        eng.pm.resolved[str(1000 + i)] = "YES" if str(1000 + i) == WINNER else "NO"
    eng.clock.now += timedelta(days=2)
    eng.settle()


# -- error classes and bucket distance ------------------------------------------------

@pytest.mark.parametrize("p, outcome, expected", [
    (0.85, 0, "significant overconfidence"),   # the spec's examples
    (0.25, 1, "underestimation"),
    (0.6, 0, "overconfidence"), (0.1, 1, "significant underestimation"),
    (0.7, 1, "right side"), (0.3, 0, "right side"), (0.5, 1, "right side"), (0.5, 0, "overconfidence"),
])
def test_error_classes(p, outcome, expected):
    assert classify(p, outcome) == expected


def test_bucket_distance_in_forecast_standard_deviations():
    assert bucket_distance(18, 18, "C", 18.4, 1.0) == 0                       # 18°C covers 17.5 to 18.5
    assert bucket_distance(18, 18, "C", 20.0, 1.0) == pytest.approx(1.5)
    assert bucket_distance(None, 13, "C", 18.0, 1.7) == pytest.approx(4.5 / 1.7)   # open lower tail
    assert bucket_distance(23, None, "C", 18.0, 2.0) == pytest.approx(2.25)
    # °F bucket: 85°F is 29.444°C; σ 1°C is 1.8°F
    assert bucket_distance(80, 81, "F", (85 - 32) * 5 / 9, 1.0) == pytest.approx(3.5 / 1.8)
    assert bucket_distance(18, 18, "C", None, 1.0) is None and bucket_distance(None, None, "C", 18, 1) is None


# -- error analysis on synthetic resolved markets ----------------------------------

def _resolved(db, mid, p, outcome, city="London", station="EGLC", market_yes=None, lead=1, event="e", day="2026-09-28",
              lo=18.0, hi=18.0, mu=18.0, sigma=1.0, ts=NOW):
    if db.one(select(markets.c.id).where(markets.c.id == mid)) is None:
        db.insert(markets, id=mid, event_id=event, question=f"q{mid}", city=city, station=station, kind="high",
                  local_date=day, unit="C", bucket_lo=lo, bucket_hi=hi, first_seen=NOW, last_seen=NOW,
                  resolved_outcome=outcome)
        db.insert(market_resolutions, market_id=mid, resolved_at=NOW + timedelta(days=2), outcome=outcome)
    pid = db.insert(predictions, ts=ts, market_id=mid, model_version=MODEL, role="production", p_yes=p,
                    lead_days=lead, mu_c=mu, sigma_c=sigma, inputs={"model_spread_c": 0.8})
    if market_yes is not None:
        db.insert(signals, ts=ts, prediction_id=pid, market_id=mid, side="YES", market_prob=market_yes,
                  decision="NO_BET", rule_results=[{"rule": "liquidity", "passed": True, "value": 2500}])
    return pid


def _synthetic(db):
    # NYC: 90% YES every time, but only half resolve YES; the market knew better (60%)
    for i in range(60):
        _resolved(db, f"n{i}", 0.9, "YES" if i % 2 else "NO", city="NYC", station="KNYC", market_yes=0.6)
    # London: 10% YES, and 10% resolve YES: well calibrated, same as the market
    for i in range(100):
        _resolved(db, f"l{i}", 0.1, "YES" if i % 10 == 0 else "NO", market_yes=0.1)


def test_error_analysis_flags_a_consistent_weakness_and_not_a_sound_group(cfg):
    db = Database(cfg.app.database_url)
    _synthetic(db)
    e = error_analysis(db)
    assert e["n"] == 160
    city = next(d for d in e["dimensions"] if d["key"] == "city")["groups"]
    nyc, london = (next(g for g in city if g["group"] == c) for c in ("NYC", "London"))
    assert nyc["confidence"] == pytest.approx(0.9) and nyc["right_side"] == pytest.approx(0.5)
    assert {f["flag"] for f in nyc["flags"]} == {"overconfident", "YES too often", "worse than the market"}
    assert all(f["z"] >= FLAG_Z for f in nyc["flags"])
    assert london["flags"] == [] and london["bias"] == pytest.approx(0.0)
    listed = {(w["dimension"], w["group"], w["flag"]) for w in e["weaknesses"]}
    assert ("City", "NYC", "overconfident") in listed and not any(g == "London" for _, g, _ in listed)
    assert [abs(w["z"]) for w in e["weaknesses"]] == sorted((abs(w["z"]) for w in e["weaknesses"]), reverse=True)
    classes = {c["class"]: c["n"] for c in e["classes"]}
    assert classes["significant overconfidence"] == 30 and classes["significant underestimation"] == 10
    assert classes["right side"] == 120
    # largest errors: wrong-side predictions only, the worst first
    assert e["largest_errors"] and all(abs(x["p_yes"] - (x["outcome"] == "YES")) >= 0.5 for x in e["largest_errors"])
    assert e["largest_errors"][0]["log_loss"] >= e["largest_errors"][-1]["log_loss"] - 1e-9
    liquidity = next(d for d in e["dimensions"] if d["key"] == "liquidity")["groups"]
    assert [g["group"] for g in liquidity] == ["$1k–5k"]


def test_small_groups_are_never_flagged(cfg):
    db = Database(cfg.app.database_url)
    for i in range(10):                                    # 0% hit rate at 95%, but only 10 markets
        _resolved(db, f"s{i}", 0.95, "NO", market_yes=0.5)
    e = error_analysis(db)
    assert e["weaknesses"] == []


def test_a_group_that_is_nearly_everything_does_not_repeat_the_overall_flag(cfg):
    db = Database(cfg.app.database_url)
    for i in range(60):
        _resolved(db, f"n{i}", 0.9, "YES" if i % 2 else "NO", market_yes=0.6)
    e = error_analysis(db)
    flagged = {(w["dimension"], w["group"]) for w in e["weaknesses"]}
    assert ("All resolved markets", "all") in flagged and ("City", "London") not in flagged


def test_lead_time_uses_the_last_prediction_at_each_lead(cfg):
    db = Database(cfg.app.database_url)
    _resolved(db, "a", 0.3, "YES", lead=2, ts=NOW)
    _resolved(db, "a", 0.4, "YES", lead=1, ts=NOW + timedelta(hours=6))
    _resolved(db, "a", 0.8, "YES", lead=1, ts=NOW + timedelta(hours=12))
    _resolved(db, "a", 0.99, "YES", lead=0, ts=NOW + timedelta(hours=30))
    by_lead = {x["lead_days"]: x["p_yes"] for x in resolved_rows(db, per_lead=True)}
    assert by_lead == {2: 0.3, 1: 0.8, 0: 0.99}
    assert [x["p_yes"] for x in resolved_rows(db)] == [0.8]          # the decision: last made 1+ day ahead
    lead = next(d for d in error_analysis(db)["dimensions"] if d["key"] == "lead")["groups"]
    assert [g["group"] for g in lead] == ["same day", "1 day", "2 days"]


def test_daily_scores_compare_model_and_market_on_the_same_markets(cfg):
    db = Database(cfg.app.database_url)
    # one event, three buckets: the model's favourite won, the market's did not
    _resolved(db, "b1", 0.6, "YES", market_yes=0.3, event="ev")
    _resolved(db, "b2", 0.3, "NO", market_yes=0.6, event="ev")
    _resolved(db, "b3", 0.1, "NO", market_yes=0.1, event="ev")
    _resolved(db, "b4", 0.5, "NO", event="ev2")                     # no market price: left out
    _resolved(db, "c1", 0.2, "NO", market_yes=0.2, event="ev3", day="2026-09-29")
    days = daily_scores(resolved_rows(db))
    assert [d["day"] for d in days] == ["2026-09-28", "2026-09-29"]
    d = days[0]
    assert d["n"] == 3 and d["n_events"] == 1
    assert d["top_bucket_model"] == 1.0 and d["top_bucket_market"] == 0.0
    assert d["brier_model"] == pytest.approx((0.16 + 0.09 + 0.01) / 3)
    assert d["brier_market"] == pytest.approx((0.49 + 0.36 + 0.01) / 3)
    assert days[1]["n_events"] == 0 and days[1]["top_bucket_model"] is None   # no event with a winner


def _bet(db, i, won, conf=0.9, side="NO"):
    mid = f"bet{i}"
    pid = _resolved(db, mid, 1 - conf, "NO" if won else "YES", market_yes=0.3)
    sig = db.insert(signals, ts=NOW, prediction_id=pid, market_id=mid, side=side, decision="BET")
    db.insert(paper_bets, signal_id=sig, market_id=mid, event_id="e", side=side, opened_at=NOW, entry_price=0.7,
              shares=10 / 0.7, stake=10.0, status="WON" if won else "LOST", confidence=conf, model_prob=conf, edge=0.2,
              pnl=10 / 0.7 - 10 if won else -10.0, mode="paper")


def test_overconfident_bets_are_flagged(cfg):
    db = Database(cfg.app.database_url)
    for i in range(20):
        _bet(db, i, won=i % 2 == 0)                    # 50% won at 90% confidence
    e = error_analysis(db)
    overall = e["bets"]["dimensions"][0]["groups"][0]
    assert overall["n"] == 20 and overall["win_rate"] == 0.5 and overall["expected_win_rate"] == pytest.approx(0.9)
    assert overall["flags"][0]["flag"] == "overconfident" and "-$" in overall["flags"][0]["detail"]
    assert any(w["scope"] == "bets" and w["flag"] == "overconfident" for w in e["weaknesses"])
    md = to_markdown(build_report(db, 100))
    assert "## Recurring weaknesses" in md and "overconfident" in md


# -- API ------------------------------------------------------------------------------

def test_live_markets_show_current_quotes_calibrated_probability_and_position(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    rows = {r["id"]: r for r in _client(eng).get("/api/markets").json()["markets"]}
    tail = rows[TAIL_MARKET]
    assert tail["yes_bid"] == pytest.approx(0.09) and tail["yes_ask"] == pytest.approx(0.11)
    assert tail["calibrated_prob"] == pytest.approx(tail["model_prob"])      # no calibrator approved yet
    pos = tail["position"]
    assert pos["side"] == "NO" and pos["cost"] == pytest.approx(2.0)
    assert pos["value"] == pytest.approx(2.0 / 0.915 * 0.89)                 # at the NO bid, 1 - 0.11
    assert rows[WINNER]["position"] is None


def test_portfolio_shows_payout_exposure_and_limits(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    pf = _client(eng).get("/api/portfolio").json()
    shares = 2.0 / 0.915
    (p,) = pf["positions"]
    assert p["potential_payout"] == pytest.approx(shares) and p["max_loss"] == pytest.approx(2.0)
    assert p["max_profit"] == pytest.approx(shares - 2.0) and p["value"] == pytest.approx(shares * 0.89)
    assert p["pct_of_equity"] == pytest.approx(2.0 / pf["equity"])
    assert p["hours_left"] == pytest.approx(41.0)          # NOW 06:00Z to 2026-09-28 23:00Z (London midnight)
    assert pf["scenarios"]["all_lose"] == pytest.approx(98.0)
    assert pf["scenarios"]["all_win"] == pytest.approx(98.0 + shares)
    caps = {c["limit_name"]: c for c in pf["caps"]}
    total = caps["Total open exposure"]
    assert total["used"] == pytest.approx(2.0) and total["limit"] == pytest.approx(0.3 * pf["equity"])
    assert caps["Largest event"]["group"] == "Highest temperature in London on September 28?"
    assert caps["Largest city-day (high and low together)"]["group"] == "London 2026-09-28"
    assert pf["by_city_day"][0]["cost"] == pytest.approx(2.0)


def test_bet_history_search_and_filters(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    client = _client(eng)
    n = lambda q: len(client.get("/api/bets", params=q).json())  # noqa: E731
    assert n({}) == 1
    assert n({"q": "london"}) == 1 and n({"q": "LONDON 23°c"}) == 1 and n({"q": "atlantis"}) == 0
    assert n({"q": "%"}) == 0 and n({"q": "_"}) == 0                           # wildcards are literal
    assert n({"q": "#1"}) == 1 and n({"q": "#2"}) == 0 and n({"q": "2026-09-28"}) == 1
    assert n({"status": "open"}) == 1 and n({"status": "WON"}) == 0
    assert n({"side": "no"}) == 1 and n({"side": "YES"}) == 0


def test_performance_has_daily_scores_and_calibrated_bins(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve_london(eng)
    perf = _client(eng).get("/api/performance").json()
    (day,) = perf["daily_scores"]
    assert day["day"] == "2026-09-28" and day["n"] == 11 and day["n_events"] == 1
    assert day["top_bucket_model"] == 1.0 and day["brier_model"] < 0.1
    assert perf["prediction_calibration"]["bins_calibrated"]


def test_errors_endpoint_after_markets_resolve(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    _resolve_london(eng)
    e = _client(eng).get("/api/errors").json()
    assert e["n"] == 11 and e["bets"]["n"] == 1 and sum(c["n"] for c in e["classes"]) == 11
    bucket = next(d for d in e["dimensions"] if d["key"] == "bucket")["groups"]
    assert sum(g["n"] for g in bucket) == 11 and "contains the forecast" in {g["group"] for g in bucket}


def test_system_health_reports_sources_database_model_and_experiment(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    st = _client(eng).get("/api/status").json()
    assert {s["source"]: s["status"] for s in st["sources"]} == {
        "Polymarket markets": "ok", "Weather forecasts (Open-Meteo)": "ok", "Station observations (METAR)": "ok"}
    assert st["last_market_scan"].startswith("2026-09-27T06:00") and st["last_prediction"]
    assert st["database"]["ok"] and st["database"]["rows"]["paper_bets"] == 1 and st["database"]["size_mb"] >= 0
    assert st["model"]["production"]["version"] == MODEL
    assert {m["version"] for m in st["model"]["shadows"]} == {"raw-forecast-v1", "climatology-v1"}
    assert st["model"]["calibrator"]["version"] == "identity" and st["model"]["last_calibrator_fit"]
    assert st["experiment"]["name"] == cfg.experiment.name and st["experiment"]["initial_bankroll"] == 100
    # three missed cycles later, the sources are stale
    eng.clock.now += timedelta(hours=2)
    assert {s["status"] for s in _client(eng).get("/api/status").json()["sources"][:2]} == {"stale"}


def test_a_failing_source_is_shown_as_failing(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()

    class Broken(FakeForecast):
        def fetch(self, station, days=5):
            raise RuntimeError("open-meteo down")
    eng.forecaster = Broken()
    eng.clock.now += timedelta(minutes=30)
    eng.run_cycle()
    src = {s["source"]: s for s in _client(eng).get("/api/status").json()["sources"]}
    weather = src["Weather forecasts (Open-Meteo)"]
    assert weather["status"] == "failing" and "open-meteo down" in weather["last_problem"]["message"]
    assert src["Polymarket markets"]["status"] == "ok"


def test_dashboard_page_has_every_section(cfg):
    eng = make_engine(cfg)
    html = _client(eng).get("/").text
    for tab in ("overview", "markets", "portfolio", "bets", "performance", "learning", "status"):
        assert f'data-t="{tab}"' in html and f'id="{tab}"' in html
    assert "PAPER TRADING" in html and "Real money: $0" in html


def test_as_utc():
    assert as_utc("2026-09-27T06:00:00+00:00") == NOW
    assert as_utc(datetime(2026, 9, 27, 6)) == NOW                          # naive SQLite value = UTC
    assert as_utc(datetime(2026, 9, 27, 8, tzinfo=timezone(timedelta(hours=2)))) == NOW
    assert as_utc(None) is None and as_utc("not a date") is None
