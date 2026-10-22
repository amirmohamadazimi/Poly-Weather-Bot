"""The same-day model: its math, the station reports and hourly forecasts it
needs, its shadow predictions, its own market anchor and its report section."""
import math
import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from tests.conftest import FakeForecast, FakeObservations, make_engine
from wxbot.calibration import anchor as anchor_module
from wxbot.calibration.fit import day_end, gain_confidence
from wxbot.calibration.methods import sigmoid
from wxbot.data.polymarket import Bucket
from wxbot.data.stations import STATIONS
from wxbot.data.weather import IEMObservations
from wxbot.db import (
    forecast_snapshots, market_anchors, market_resolutions, market_snapshots, markets, model_versions, paper_bets,
    predictions, signals, station_reports, system_events,
)
from wxbot.model import nowcast
from wxbot.model.nowcast import (
    Nowcast, bounds_c, day_bounds, day_state, final_probability, hour_band, hourly_series, load_params,
)
from wxbot.model.registry import nowcast_model
from wxbot.report import build_report, same_day_scores, to_markdown

DAY = "2026-09-28"
MORNING = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)    # 11:00 in London, 13 h before its day ends
LONDON = ZoneInfo("Europe/London")
VERSION = load_params()["version"]


def profile(hour: float) -> float:
    """A day peaking at 18 C at 15:00 local."""
    return 11 + 7 * math.exp(-((hour - 15) / 4) ** 2)


class HourlyForecast(FakeForecast):
    """FakeForecast plus the hourly forecast of DAY (models 0.1 C apart, mean profile + 0.2)."""
    def fetch(self, station, days=5):
        by_kind, meta = super().fetch(station, days)
        by_kind["hourly"] = {DAY: {"time": [f"{DAY}T{h:02d}:00" for h in range(24)],
                                   "values": {m: [round(profile(h) + i / 10, 2) for h in range(24)]
                                              for i, m in enumerate(self.models)}}}
        return by_kind, meta


class Reports(FakeObservations):
    """One report at 20 past every UTC hour, following the profile (+ offset)."""
    def __init__(self, offset=0.0):
        self.offset = offset
        self.requests = []

    def fetch_reports(self, station, start, end):
        self.requests.append((station.code, start, end))
        out, t = [], start.replace(minute=20)
        while t <= end:
            local = t.astimezone(LONDON)
            out.append((t, profile(local.hour + local.minute / 60) + self.offset))
            t += timedelta(hours=1)
        return out


@pytest.fixture
def same_day(cfg):
    cfg._data["nowcast"]["enabled"] = True
    return cfg


def _engine(cfg, clock_now=MORNING, offset=0.0):
    from tests.conftest import Clock
    return make_engine(cfg, forecast=HourlyForecast(), clock=Clock(clock_now), observer=Reports(offset),
                       nowcast=nowcast_model(cfg))


# -- the model ---------------------------------------------------------------------------

def test_a_bucket_already_passed_gets_nothing_and_the_buckets_sum_to_one():
    # high so far 20 C: below 20 is impossible
    assert final_probability("high", 20.0, 19.0, 1.0, 18.5, 19.5) == 0.0
    assert final_probability("high", 20.0, 19.0, 1.0, None, 19.5) == 0.0
    # low so far 5 C: above 5 is impossible
    assert final_probability("low", 5.0, 6.0, 1.0, 5.5, 6.5) == 0.0
    for kind, m in (("high", 17.2), ("low", 9.4)):
        edges = [None, *[x + 0.5 for x in range(5, 25)], None]
        total = sum(final_probability(kind, m, 15.0, 1.3, lo, hi) for lo, hi in zip(edges, edges[1:]))
        assert total == pytest.approx(1.0)
    # the bucket holding the value so far takes P(nothing beats it)
    p_none_above = 0.5 * (1 + math.erf(2.5 / math.sqrt(2)))
    assert final_probability("high", 17.2, 15.0, 1.0, 16.5, 17.5) == pytest.approx(p_none_above)


def test_hour_bands_and_bucket_bounds():
    assert [hour_band(h) for h in (0.2, 1, 3.9, 5, 13, 23.9, 24)] == [0, 1, 3, 4, 8, 11, 11]
    assert bounds_c(Bucket(18, 18, "C")) == (17.5, 18.5)
    lo, hi = bounds_c(Bucket(70, 71, "F"))
    assert lo == pytest.approx((69.5 - 32) * 5 / 9) and hi == pytest.approx((71.5 - 32) * 5 / 9)
    assert bounds_c(Bucket(None, 13, "C")) == (None, 13.5)


def test_hourly_series_is_in_utc_and_needs_enough_models():
    hourly = {"time": ["2026-09-28T00:00", "2026-09-28T01:00"], "values": {"a": [10.0, None], "b": [12.0, 11.0]}}
    assert hourly_series(hourly, "Europe/London", 2) == [(datetime(2026, 9, 27, 23, tzinfo=UTC), 11.0)]
    assert len(hourly_series(hourly, "Europe/London", 1)) == 2
    assert hourly_series(None, "Europe/London", 1) == []


def test_day_state():
    start, end = day_bounds("Europe/London", DAY)
    assert (start, end) == (datetime(2026, 9, 27, 23, tzinfo=UTC), datetime(2026, 9, 28, 23, tzinfo=UTC))
    fc = [(start + timedelta(hours=h), 10.0 + h / 2) for h in range(25)]
    rep = [(start - timedelta(minutes=40), 30.0), (start + timedelta(minutes=50), 9.0),
           (start + timedelta(hours=5, minutes=50), 14.0), (start + timedelta(hours=6, minutes=50), 12.0)]
    s = day_state(rep, fc, start, end, start + timedelta(hours=7), "high")
    assert s["m"] == 14.0 and s["n_reports"] == 3                  # yesterday's 30 C does not count
    assert s["anom"] == pytest.approx(12.0 - (10.0 + 7 / 2))       # newest report vs the forecast at 07:00Z
    assert s["frem"] == 22.0                                       # forecast peak still to come
    assert day_state(rep, fc, start, end, start + timedelta(hours=7), "low")["m"] == 9.0
    assert day_state(rep[:1], fc, start, end, start + timedelta(hours=7), "high") is None   # no report today
    assert day_state(rep, [], start, end, start + timedelta(hours=7), "high") is None       # no forecast
    late = day_state(rep, fc, start, end, end, "high")
    assert late["frem"] == pytest.approx(10.0 + 7 / 2)             # no hour left: the forecast at the newest report


def test_predict_needs_a_recent_report_and_the_markets_own_day():
    model = Nowcast(load_params())
    start, _ = day_bounds("Europe/London", DAY)
    hourly = HourlyForecast().fetch(STATIONS["EGLC"])[0]["hourly"][DAY]
    reports = Reports().fetch_reports(STATIONS["EGLC"], start, MORNING)
    p = model.predict(Bucket(18, 18, "C"), "high", "EGLC", DAY, "Europe/London", reports, hourly, MORNING)
    assert 0.1 < p.p_yes < 0.5 and p.inputs["hour_band"] == 8 and p.inputs["station_known"]
    assert p.inputs["so_far_c"] == pytest.approx(max(v for _, v in reports), abs=1e-3)
    gone = model.predict(Bucket(None, 12, "C"), "high", "EGLC", DAY, "Europe/London", reports, hourly, MORNING)
    assert gone.p_yes == model.prob_floor                          # 12.5 C has already been passed
    stale = MORNING + timedelta(hours=3)                           # newest report 3 h 40 min old
    assert model.predict(Bucket(18, 18, "C"), "high", "EGLC", DAY, "Europe/London", reports, hourly, stale) is None
    assert model.predict(Bucket(18, 18, "C"), "high", "EGLC", "2026-09-29", "Europe/London", reports, hourly,
                         MORNING) is None                          # not the market's day yet
    other = model.predict(Bucket(18, 18, "C"), "high", "ZZZZ", DAY, "Europe/London", reports, hourly, MORNING)
    assert not other.inputs["station_known"] and other.inputs["station_bias_c"] == 0.0


def test_params_file_is_complete():
    p = load_params()
    assert p["hour_bands"] == nowcast.HOUR_BANDS
    for kind in ("high", "low"):
        assert len(p["bands"][kind]) == len(nowcast.HOUR_BANDS) - 1
        assert all(b["sigma"] >= 0.3 and b["n"] > 0 for b in p["bands"][kind])
    assert {"EGLC", "KLGA"} <= set(p["station_bias"])


# -- data collection ---------------------------------------------------------------------

def test_iem_reports_are_parsed_and_cut_to_the_window():
    text = "station,valid,tmpf\nLGA,2026-09-28 09:51,68.0\nLGA,2026-09-28 10:51,M\nLGA,2026-09-28 08:51,50\n" \
           "LGA,2026-09-28 11:51,70\nLGA,bad,70"

    class Resp:
        def __init__(self):
            self.text = text

        def raise_for_status(self):
            pass

    class Session:
        def __init__(self):
            self.params = None

        def get(self, url, params=None, timeout=None):
            self.params = dict(params)
            return Resp()

    sess = Session()
    got = IEMObservations(session=sess).fetch_reports(STATIONS["KLGA"], datetime(2026, 9, 28, 9, tzinfo=UTC),
                                                      datetime(2026, 9, 28, 11, 0, tzinfo=UTC))
    assert got == [(datetime(2026, 9, 28, 9, 51, tzinfo=UTC), pytest.approx(20.0))]
    assert sess.params["station"] == "LGA" and sess.params["hour2"] == 12
    assert [round(v, 2) for _, v in IEMObservations.parse_reports(text)] == [10.0, 20.0, 21.11]


def test_cycle_collects_todays_reports_and_hourly_forecast(same_day):
    eng = _engine(same_day)
    out = eng.run_cycle()
    assert out["reports"] == {"stations": 1, "new_reports": 11}       # 23:20Z .. 09:20Z
    assert eng.observer.requests == [("EGLC", datetime(2026, 9, 27, 23, tzinfo=UTC), MORNING)]
    assert eng.run_cycle()["reports"]["new_reports"] == 0             # nothing stored twice
    rows = eng.db.rows(select(station_reports))
    assert len(rows) == 11 and all(r["source"] == "fake-obs" for r in rows)
    snap = eng.db.one(select(forecast_snapshots).where(forecast_snapshots.c.local_date == DAY))
    assert len(snap["hourly_c"]["time"]) == 24 and len(snap["hourly_c"]["values"]) == 5


def test_a_day_other_than_the_stations_today_keeps_no_hourly_forecast(same_day):
    eng = make_engine(same_day, forecast=HourlyForecast(), observer=Reports(), nowcast=nowcast_model(same_day))
    eng.run_cycle()   # NOW is Sep 27 in London: the Sep 28 market is tomorrow
    assert all(s["hourly_c"] is None for s in eng.db.rows(select(forecast_snapshots)))
    assert eng.db.rows(select(station_reports)) == []


def test_reports_outside_the_validation_bounds_are_skipped(same_day):
    eng = _engine(same_day, offset=80.0)
    assert eng.run_cycle()["reports"]["new_reports"] == 0


def test_cycle_without_the_model_or_report_source_skips_reports(cfg):
    assert nowcast_model(cfg) is None                                  # [nowcast] enabled = false
    eng = make_engine(cfg, forecast=HourlyForecast())
    assert eng.collect_reports() == {"enabled": False}
    cfg._data["nowcast"]["enabled"] = True
    eng = make_engine(cfg, nowcast=nowcast_model(cfg))                  # FakeObservations has no fetch_reports
    assert eng.collect_reports() == {"enabled": False}


def test_report_source_failure_is_logged(same_day):
    class Down(Reports):
        def fetch_reports(self, station, start, end):
            raise TimeoutError("IEM down")

    from tests.conftest import Clock
    eng = make_engine(same_day, forecast=HourlyForecast(), clock=Clock(MORNING), observer=Down(),
                      nowcast=nowcast_model(same_day))
    assert eng.run_cycle()["reports"] == {"stations": 1, "new_reports": 0}


# -- shadow predictions and signals -------------------------------------------------------

def test_same_day_markets_get_shadow_predictions_that_are_not_traded(same_day):
    eng = _engine(same_day)
    out = eng.run_cycle()
    p = predictions.c
    rows = eng.db.rows(select(predictions).where(p.model_version == VERSION))
    assert len(rows) == 11 and out["signals"]["bets"] == 0
    assert all(r["role"] == "shadow" and r["feature_set"] == "same-day-v1" and r["lead_days"] == 0 for r in rows)
    assert sum(r["p_yes"] for r in rows) == pytest.approx(1.0, abs=0.02)
    assert all(r["inputs"]["production_prediction_id"] for r in rows)
    reg = eng.db.one(select(model_versions).where(model_versions.c.version == VERSION))
    assert reg["role"] == "shadow" and reg["name"] == "nowcast" and reg["feature_set"] == "same-day-v1"
    # the anchor is off in this config, so the signals stay the production model's
    linked = eng.db.rows(select(p.model_version).join(signals, signals.c.prediction_id == p.id))
    assert {r["model_version"] for r in linked} == {"normal-multimodel-v1"}


def test_broken_same_day_model_never_stops_the_cycle(same_day):
    eng = _engine(same_day)

    def boom(*a, **k):
        raise ValueError("bad params")

    eng.nowcast.predict = boom
    out = eng.run_cycle()
    assert out["signals"]["predictions"] == 11 and out["signals"]["shadow_predictions"] == 11   # the raw baseline
    assert eng.db.rows(select(predictions).where(predictions.c.model_version == VERSION)) == []
    events = eng.db.rows(select(system_events.c.message).where(system_events.c.component == "shadow_model"))
    assert any("ValueError: bad params" in e["message"] for e in events)


@pytest.fixture
def betting(same_day):
    same_day._data["market_anchor"]["enabled"] = True
    return same_day


def test_same_day_signals_wait_for_their_own_anchor(betting):
    eng = _engine(betting)
    out = eng.run_cycle()
    assert out["market_anchor"]["same_day"] == {"n": 0, "approved": False}
    assert out["signals"]["bets"] == 0
    s, p = signals.c, predictions.c
    rows = eng.db.rows(select(s.rule_results, p.model_version).join(predictions, p.id == s.prediction_id))
    assert len(rows) == 11 and {r["model_version"] for r in rows} == {VERSION}
    for r in rows:
        rules = {x["rule"]: x for x in r["rule_results"]}
        assert rules["time_to_resolution"]["passed"] and rules["time_to_resolution"]["threshold"] == "1.0..18.0 h"
        assert not rules["market_anchor"]["passed"]
    fit = anchor_module.latest(eng.db, anchor_module.SAME_DAY)
    assert fit["model_version"] == VERSION and "(0 predictions)" in fit["reason"]
    assert anchor_module.latest(eng.db)["model_version"] == "normal-multimodel-v1"


def test_an_approved_same_day_anchor_lets_it_bet(betting):
    eng = _engine(betting)
    eng.db.insert(market_anchors, version="anchor-test", model_version=VERSION, fitted_at=MORNING - timedelta(hours=1),
                  params={"a": 1.0, "b": 0.0, "c": 0.0}, approved=True, reason="test", scope="same-day")
    eng.db.set_state("last_anchor_fit", (MORNING - timedelta(hours=1)).isoformat())   # no refit this cycle
    out = eng.run_cycle()
    assert out["signals"]["bets"] >= 1
    bets = eng.db.rows(select(paper_bets.c.market_id, paper_bets.c.side, predictions.c.model_version)
                       .join(signals, signals.c.id == paper_bets.c.signal_id)
                       .join(predictions, predictions.c.id == signals.c.prediction_id))
    assert {b["model_version"] for b in bets} == {VERSION}
    assert ("1010", "NO") in {(b["market_id"], b["side"]) for b in bets}   # "23°C or higher" at 0.10: ruled out


def test_without_bet_the_same_day_model_only_shadows(betting):
    betting._data["nowcast"]["bet"] = False
    eng = _engine(betting)
    eng.run_cycle()
    p = predictions.c
    linked = eng.db.rows(select(p.model_version).join(signals, signals.c.prediction_id == p.id))
    assert {r["model_version"] for r in linked} == {"normal-multimodel-v1"}


def test_with_the_market_check_off_it_never_bets_even_with_an_approved_anchor(same_day):
    assert same_day.nowcast.bet and not same_day.market_anchor.enabled
    eng = _engine(same_day)
    eng.db.insert(market_anchors, version="anchor-test", model_version=VERSION, fitted_at=MORNING - timedelta(hours=1),
                  params={"a": 1.0, "b": 0.0, "c": 0.0}, approved=True, reason="test", scope="same-day")
    eng.run_cycle()
    p = predictions.c
    linked = eng.db.rows(select(p.model_version).join(signals, signals.c.prediction_id == p.id))
    assert linked and {r["model_version"] for r in linked} == {"normal-multimodel-v1"}


def test_outside_its_window_the_production_signal_stands(betting):
    eng = _engine(betting, clock_now=datetime(2026, 9, 28, 22, 30, tzinfo=UTC))   # 30 min left
    eng.run_cycle()
    p = predictions.c
    linked = eng.db.rows(select(p.model_version).join(signals, signals.c.prediction_id == p.id))
    assert {r["model_version"] for r in linked} == {"normal-multimodel-v1"}


# -- its anchor --------------------------------------------------------------------------

def _same_day_markets(db, n, model_noise, market_noise, seed=1, start=date(2026, 8, 1)):
    """n resolved EGLC markets, ten a day, each priced by the same-day model 12,
    6 and 2 h before its day ended (and once 20 h before, outside the window),
    with a tight book five minutes before each."""
    rng = random.Random(seed)
    mk, res, pr, sn = [], [], [], []
    for i in range(n):
        d = (start + timedelta(days=i // 10)).isoformat()
        end = day_end("EGLC", d)
        x = rng.uniform(-3.0, 1.0)
        outcome = "YES" if rng.random() < sigmoid(x) else "NO"
        m = f"s{i}"
        mk.append(dict(id=m, question=m, station="EGLC", local_date=d, first_seen=end, last_seen=end,
                       resolved_outcome=outcome))
        res.append(dict(market_id=m, resolved_at=end + timedelta(hours=12), outcome=outcome))
        for h in (20, 12, 6, 2):
            ts = end - timedelta(hours=h, minutes=i % 10)
            mid = min(0.97, max(0.03, sigmoid(x + rng.gauss(0, market_noise))))
            pr.append(dict(ts=ts, market_id=m, model_version=VERSION, role="shadow", feature_set="same-day-v1",
                           p_yes=sigmoid(x + rng.gauss(0, model_noise)), lead_days=0))
            sn.append(dict(market_id=m, ts=ts - timedelta(minutes=5), best_bid=mid - 0.01, best_ask=mid + 0.01,
                           liquidity=5000.0))
    with db.engine.begin() as conn:
        for table, rows in ((markets, mk), (market_resolutions, res), (predictions, pr), (market_snapshots, sn)):
            conn.execute(table.insert(), rows)
    return datetime.combine(start + timedelta(days=n // 10 + 3), datetime.min.time(), UTC)


def test_same_day_anchor_is_judged_by_market(betting):
    eng = _engine(betting)
    fit_time = _same_day_markets(eng.db, 400, model_noise=0.2, market_noise=1.5)
    data = anchor_module.nowcast_training_set(eng.db, betting, VERSION, fit_time)
    assert len(data) == 1200 and len({x[4] for x in data}) == 400        # the 20 h predictions are outside
    row = anchor_module.fit_nowcast_round(eng.db, betting, VERSION, fit_time)
    assert (row["n"], row["n_train"], row["n_holdout"]) == (400, 280, 120)
    assert row["approved"] and row["scope"] == "same-day" and row["reason"].endswith("(1200 predictions)")
    hold_from = row["holdout_from"]
    assert all(x[0] < hold_from for x in data if x[4] in {f"s{i}" for i in range(280)})
    fitted, version = anchor_module.active_anchor(eng.db, betting, VERSION, fit_time)
    assert fitted is not None and version == row["version"]
    assert anchor_module.latest(eng.db) is None                          # the decision model has no fit


def test_same_day_anchor_rejects_a_model_the_market_beats(betting):
    eng = _engine(betting)
    fit_time = _same_day_markets(eng.db, 400, model_noise=2.0, market_noise=0.2, seed=4)
    row = anchor_module.fit_nowcast_round(eng.db, betting, VERSION, fit_time)
    assert not row["approved"]


def test_cluster_bootstrap_counts_markets_not_rows():
    # one market with a big gain repeated many times is still one market
    raw = [0.5] * 30 + [0.5, 0.5]
    cal = [0.9] * 30 + [0.1, 0.9]
    ys = [1] * 30 + [1, 0]
    assert gain_confidence(raw, cal, ys) > 0.95
    assert gain_confidence(raw, cal, ys, groups=["a"] * 30 + ["b", "c"]) < 0.8


# -- report ------------------------------------------------------------------------------

def test_report_scores_the_same_day_model_against_the_market(betting):
    eng = _engine(betting)
    fit_time = _same_day_markets(eng.db, 400, model_noise=2.0, market_noise=0.2, seed=4)
    anchor_module.fit_nowcast_round(eng.db, betting, VERSION, fit_time)
    rep = build_report(eng.db, 100, fit_time, cfg=betting)
    scores = {s["hours_left"]: s for s in rep["same_day"]["scores"]}
    assert scores["all"]["n"] == 1600 and scores["all"]["markets"] == 400
    assert scores["0-3"]["n"] == 400 and scores["12-24"]["n"] == 800
    assert scores["all"]["log_loss_model"] > scores["all"]["log_loss_market"]
    md = to_markdown(rep)
    assert "## Same-day model (forward test)" in md and "**not approved**" in md
    assert "| 6-12 | 400 | 400 |" in md


def test_report_says_it_does_not_bet_with_the_market_check_off(same_day):
    eng = _engine(same_day)
    fit_time = _same_day_markets(eng.db, 400, model_noise=2.0, market_noise=0.2, seed=4)
    anchor_module.fit_nowcast_round(eng.db, same_day, VERSION, fit_time)    # fitted while the check was on
    md = to_markdown(build_report(eng.db, 100, fit_time, cfg=same_day))
    assert "With the market check off it does not bet." in md and "Last anchor fit" in md
    assert "It can bet only once" not in md and "Latest anchor fit" not in md


def test_report_verdict_names_an_approved_same_day_model(betting):
    eng = _engine(betting)
    eng.db.insert(market_anchors, version="a1", model_version="normal-multimodel-v1", fitted_at=MORNING,
                  approved=False, reason="the model adds nothing")
    eng.db.insert(market_anchors, version="a2", model_version=VERSION, fitted_at=MORNING, approved=True,
                  reason="beats the market price", scope="same-day", n=300, n_train=210, n_holdout=90)
    rep = build_report(eng.db, 100, MORNING, cfg=betting)
    assert any("The same-day model has, so it may bet" in v for v in rep["verdict"])
    assert "**approved**, beats the market price" in to_markdown(rep)


def test_report_leaves_the_section_out_without_same_day_data(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    assert "Same-day model" not in to_markdown(build_report(eng.db, 100, cfg=cfg))
    assert same_day_scores([])[-1] == {"hours_left": "all", "n": 0, "markets": 0, "log_loss_model": None,
                                       "log_loss_market": None, "brier_model": None, "brier_market": None}
