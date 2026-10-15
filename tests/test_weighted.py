"""The v2 production model (weighted-multimodel-v1) and its daily bias refresh."""
import statistics
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from research.fit_weighted import priced_as_live
from tests.conftest import NOW, Clock, FakeForecast, make_engine
from wxbot.config import load_config
from wxbot.data.polymarket import Bucket
from wxbot.db import Database, model_stats, predictions, signals
from wxbot.engine import only_models
from wxbot.features import build_features
from wxbot.learning import model_stats as stats_refresh
from wxbot.learning import retrain
from wxbot.model.base import Calibration
from wxbot.model.nowcast import hourly_series
from wxbot.model.registry import (
    OnlyModels, V1_VERSION, is_weighted, nowcast_model, param_model, production_model, shadow_models, v1_models,
)
from wxbot.model.weighted import EW, MIN_DAYS, Stats, WeightedMultiModel, combine, load_params, sigma, walk

V1 = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless", "jma_seamless"]
ALL = V1 + ["ecmwf_ifs", "ukmo_seamless"]
OFFSETS = {m: (i - 3) * 0.6 for i, m in enumerate(ALL)}   # each model's own bias, in C
NOISE = [-0.5, 0.3, 0.1, -0.2, 0.4, -0.1, 0.0]
CAL = Calibration(bias_c=0.0, sigma_c=1.5, n=0, source="default")


def wcfg(tmp_path, **extra):
    env = {"WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path / 'w.sqlite3'}", "WXBOT_MARKET_ANCHOR__ENABLED": "false",
           "WXBOT_NOWCAST__ENABLED": "false", "WXBOT_MODEL__VERSION": "weighted-multimodel-v1",
           "WXBOT_WEATHER__MODELS": ",".join(ALL), "WXBOT_MODEL_STATS__PAUSE_SECONDS": "0", **extra}
    return load_config(env=env)


def truth(code: str, d: date) -> float:
    return 15.0 + (d.toordinal() % 5) * 0.8 + len(code) * 0.1


def forecast(code: str, d: date, models=ALL) -> dict:
    """The truth minus each model's own bias, plus noise that is larger for later models."""
    e = NOISE[d.toordinal() % 7]
    return {m: truth(code, d) - OFFSETS[m] + e * (1 + i) for i, m in enumerate(models)}


class FakeHistory:
    def __init__(self, fail=()):
        self.fail, self.calls = fail, []

    def fetch(self, st, start, end, leads):
        self.calls.append((st.code, start, end, tuple(leads)))
        if st.code in self.fail:
            raise ConnectionError("down")
        days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
        by_day = {d.isoformat(): forecast(st.code, d) for d in days}
        return {lead: {"high": by_day, "low": {k: {m: v - 8 for m, v in vals.items()} for k, vals in by_day.items()}}
                for lead in leads}


class FakeTruth:
    def fetch(self, st, start, end):
        days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
        return {"high": {d.isoformat(): (truth(st.code, d), 24) for d in days},
                "low": {d.isoformat(): (truth(st.code, d) - 8, 24) for d in days}}


def series(n: int, code: str = "EGLC", start: date = date(2026, 5, 1)):
    days = [start + timedelta(days=k) for k in range(n)]
    return [(d.isoformat(), forecast(code, d), truth(code, d)) for d in days]


def test_ew_is_an_exponentially_weighted_mean_once_it_has_enough_days():
    e = EW(half_life=1.0)
    for x in [1.0] + [0.0] * (MIN_DAYS - 1):
        assert e.value is None
        e.add(x)
    weights = [0.5 ** k for k in range(MIN_DAYS)]
    assert e.value == pytest.approx(weights[-1] / sum(weights))


def test_walk_learns_each_models_bias_and_prices_each_day_before_seeing_it():
    final, recs = walk(series(80))
    for m, off in OFFSETS.items():
        assert final.bias[m] == pytest.approx(off, abs=0.3)
    # the bias-corrected combination beats the plain mean of the models
    late = [r for r in recs if r["sd"] is not None][-30:]
    plain = [abs(sum(fc.values()) / len(fc) - obs) for _, fc, obs in series(80)][-30:]
    assert sum(abs(r["mu"] - r["obs"]) for r in late) < sum(plain)
    # no look-ahead: changing a later observation leaves every earlier record as it was
    data = series(80)
    data[60] = (data[60][0], data[60][1], data[60][2] + 9.0)
    _, changed = walk(data)
    n = sum(r["day"] <= data[60][0] for r in recs)          # up to and including the changed day
    priced = [(r["mu"], r["sd"], r["spread"]) for r in recs]
    assert [(r["mu"], r["sd"], r["spread"]) for r in changed][:n] == priced[:n]
    assert [(r["mu"], r["sd"]) for r in changed][n:] != [x[:2] for x in priced][n:]


def test_walk_can_keep_the_state_after_every_observed_day():
    data = series(40)
    data[5] = (data[5][0], data[5][1], None)
    states: list = []
    final, _ = walk(data, states)
    assert [d for d, _ in states] == [d for d, _, obs in data if obs is not None]
    assert states[-1][1].as_dict() == final.as_dict()
    # each state is the walk stopped after that day
    upto, _ = walk(data[:20])
    assert dict(states)[data[19][0]].as_dict() == upto.as_dict()


def test_the_fit_prices_each_day_with_the_state_the_live_bot_would_have():
    data = series(80)
    states: list = []
    walk(data, states)
    known = dict(states)
    forecasts = {d: fc for d, fc, _ in data}
    for lead in (1, 3):
        recs = priced_as_live(data, lead)
        assert recs and all(r["obs"] is not None for r in recs)
        r = recs[-1]
        cutoff = (date.fromisoformat(r["day"]) - timedelta(days=lead + 1)).isoformat()
        mu, _, _ = combine(forecasts[r["day"]], known[cutoff])
        assert r["mu"] == pytest.approx(mu) and r["sd"] == known[cutoff].sd
    # a later lead is priced with an older state, so it starts later
    assert priced_as_live(data, 3)[0]["day"] > priced_as_live(data, 1)[0]["day"]


def test_days_without_an_observation_are_priced_but_teach_nothing():
    data = series(40)
    gap = [(d, fc, None if i % 2 else obs) for i, (d, fc, obs) in enumerate(data)]
    final, recs = walk(gap)
    assert final.n_days == 20 and final.last_day == data[-2][0]
    assert any(r["obs"] is None for r in recs)


def test_combine_weights_the_more_accurate_model_more():
    st = Stats(bias={"a": 1.0, "b": -1.0}, mse={"a": 0.25, "b": 1.0}, sd=0.8)
    mu, spread, w = combine({"a": 10.0, "b": 12.0, "c": 99.0}, st)   # c has no history: left out
    assert w == pytest.approx({"a": 0.8, "b": 0.2})
    assert mu == pytest.approx(0.8 * 11.0 + 0.2 * 11.0) and spread == 0.0
    assert combine({"c": 1.0}, st) is None


def test_sigma_widens_with_past_error_and_todays_disagreement():
    a = load_params()["sigma"]["high"][0]
    assert sigma(a, 1.0, 0.5) > sigma(a, 0.6, 0.5)
    assert sigma(a, 1.0, 1.5) > sigma(a, 1.0, 0.5)
    assert sigma(a, 0.0, 0.0) == sigma(a, 0.2, 0.0)        # sd is floored


def stats_for(code: str = "EGLC") -> dict:
    final, _ = walk(series(80, code))
    return {(code, "high", lead): final for lead in (1, 2, 3)}


def features(code: str = "EGLC", values=None):
    return build_features(station=code, kind="high", local_date="2026-09-28", values_c=values or {"x": 1.0},
                          lead_days=1, issue_time=None, day_end=NOW + timedelta(hours=42), climatology_c=[])


def test_prediction_needs_the_stations_stats_and_enough_models():
    model = WeightedMultiModel()
    b = Bucket(17, 17, "C")
    values = forecast("EGLC", date(2026, 7, 20))
    assert model.predict(b, "high", values, 1, CAL, features()) is None          # no stats loaded
    model.stats = stats_for()
    assert model.predict(b, "high", values, 1, CAL, None) is None                # no station
    assert model.predict(b, "high", {k: values[k] for k in V1[:2]}, 1, CAL, features()) is None   # 2 < 3 models
    p = model.predict(b, "high", values, 1, CAL, features())
    assert p is not None and p.model_version == "weighted-multimodel-v1"
    assert p.inputs["stats_lead"] == 1 and sum(p.inputs["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert set(p.inputs["bias_c"]) == set(values)
    # the disagreement of the raw model values, as the older models record it
    assert p.inputs["model_spread_c"] == pytest.approx(statistics.pstdev(values.values()), abs=1e-3)
    # lead 0 (the market's own day) and leads past 3 use the nearest fitted lead
    assert model.predict(b, "high", values, 0, CAL, features()).inputs["stats_lead"] == 1
    assert model.predict(b, "high", values, 5, CAL, features()).inputs["stats_lead"] == 3


def test_bucket_probabilities_over_a_ladder_add_up_to_one():
    model = WeightedMultiModel(prob_floor=0.0, prob_ceiling=1.0)
    model.stats = stats_for()
    values = forecast("EGLC", date(2026, 7, 20))
    ladder = [Bucket(None, 9, "C")] + [Bucket(x, x, "C") for x in range(10, 26)] + [Bucket(26, None, "C")]
    total = sum(model.predict(b, "high", values, 1, CAL, features()).p_yes for b in ladder)
    assert total == pytest.approx(1.0, abs=1e-6)
    f = model.predict(Bucket(60, 61, "F"), "high", values, 1, CAL, features())
    assert f.inputs["unit"] == "F" and f.inputs["sigma_unit"] == pytest.approx(f.sigma_c * 1.8, abs=1e-3)


def test_registry_switches_production_and_keeps_the_older_models_on_their_own_models(tmp_path):
    cfg = wcfg(tmp_path)
    assert is_weighted(cfg) and isinstance(production_model(cfg), WeightedMultiModel)
    assert v1_models(cfg) == V1 and param_model(cfg).version == V1_VERSION
    shadows = shadow_models(cfg)
    assert [s.version for s in shadows] == [V1_VERSION, "raw-forecast-v1", "climatology-v1"]
    assert all(isinstance(s, OnlyModels) for s in shadows)
    v1 = shadows[0]
    values = forecast("EGLC", date(2026, 7, 20))
    p = v1.predict(Bucket(17, 17, "C"), "high", values, 1, CAL, features())
    assert set(p.inputs["model_values_c"]) == set(V1)
    assert v1.predict(Bucket(17, 17, "C"), "high", {"ukmo_seamless": 17.0}, 1, CAL) is None
    assert nowcast_model(wcfg(tmp_path, WXBOT_NOWCAST__ENABLED="true")).models == set(V1)
    # with v1 in production nothing is wrapped and the v1 shadow is production itself
    v1cfg = load_config(env={"WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path / 'v1.sqlite3'}",
                             "WXBOT_MODEL__VERSION": V1_VERSION})
    assert not is_weighted(v1cfg) and [s.version for s in shadow_models(v1cfg)] == ["raw-forecast-v1",
                                                                                     "climatology-v1"]
    assert nowcast_model(v1cfg).models is None


def test_same_day_model_reads_only_its_own_models_from_the_hourly_forecast():
    hourly = {"time": ["2026-09-28T00:00"], "values": {"a": [10.0], "b": [12.0], "z": [30.0]}}
    assert hourly_series(hourly, "UTC", 2)[0][1] == pytest.approx(52 / 3)
    assert hourly_series(hourly, "UTC", 2, {"a", "b"})[0][1] == pytest.approx(11.0)
    assert hourly_series(hourly, "UTC", 3, {"a", "b"}) == []


def test_refresh_stores_stats_for_every_enabled_station_and_waits_a_day(tmp_path):
    cfg = wcfg(tmp_path)
    db = Database(cfg.app.database_url)
    hist = FakeHistory(fail=("KLGA",))
    out = stats_refresh.refresh(db, cfg, hist, FakeTruth(), "weighted-multimodel-v1", NOW)
    assert out["failed"] == {"KLGA": "ConnectionError: down"} and out["rows"] == out["stations"] * 6
    eglc = [c for c in hist.calls if c[0] == "EGLC"][0]
    assert eglc[2] == date(2026, 9, 26) and (eglc[2] - eglc[1]).days == int(cfg.model_stats.days) - 1
    loaded = stats_refresh.load(db)
    assert ("KLGA", "high", 1) not in loaded and loaded[("EGLC", "low", 3)].sd is not None
    assert loaded[("EGLC", "high", 1)].bias["ukmo_seamless"] == pytest.approx(OFFSETS["ukmo_seamless"], abs=0.3)
    retry_h = float(cfg.model_stats.retry_hours)
    assert stats_refresh.refresh(db, cfg, hist, FakeTruth(), "x", NOW + timedelta(hours=1))["skipped"] == "not due"
    # after retry_hours only the failed station is fetched again
    hist2 = FakeHistory()
    out = stats_refresh.refresh(db, cfg, hist2, FakeTruth(), "weighted-multimodel-v1", NOW + timedelta(hours=retry_h))
    assert out["retry"] and out["stations"] == 1 and out["rows"] == 6 and not out["failed"]
    assert [c[0] for c in hist2.calls] == ["KLGA"] and ("KLGA", "high", 1) in stats_refresh.load(db)
    assert stats_refresh.pending_retry(db) == {}
    assert stats_refresh.refresh(db, cfg, hist, FakeTruth(), "x", NOW + timedelta(hours=23))["skipped"] == "not due"
    # the next day's refresh adds rows; the newest ones are loaded and the old ones kept
    later = NOW + timedelta(hours=25)
    stats_refresh.refresh(db, cfg, FakeHistory(), FakeTruth(), "weighted-multimodel-v1", later)
    rows = db.rows(select(model_stats).where(model_stats.c.station == "EGLC", model_stats.c.kind == "high",
                                             model_stats.c.lead_days == 1))
    assert len(rows) == 2 and rows[-1]["window_end"] == "2026-09-27"
    assert stats_refresh.load(db)[("EGLC", "high", 1)].last_day == "2026-09-27"


def test_a_station_that_fails_again_is_retried_again_and_never_blocks_the_daily_refresh(tmp_path):
    cfg = wcfg(tmp_path)
    db = Database(cfg.app.database_url)
    retry = timedelta(hours=float(cfg.model_stats.retry_hours))
    stats_refresh.refresh(db, cfg, FakeHistory(fail=("KLGA",)), FakeTruth(), "w", NOW)
    hist = FakeHistory(fail=("KLGA",))
    out = stats_refresh.refresh(db, cfg, hist, FakeTruth(), "w", NOW + retry)
    assert out["retry"] and out["rows"] == 0 and list(out["failed"]) == ["KLGA"] and len(hist.calls) == 1
    assert stats_refresh.pending_retry(db) == {"at": (NOW + 2 * retry).isoformat(), "stations": ["KLGA"]}
    # the daily refresh is still due on time and fetches every station
    full = FakeHistory()
    out = stats_refresh.refresh(db, cfg, full, FakeTruth(), "w", NOW + timedelta(hours=24))
    assert not out["retry"] and not out["failed"] and len(full.calls) == out["stations"] > 1
    assert stats_refresh.pending_retry(db) == {}


def test_a_refresh_that_fetches_nothing_retries_sooner(tmp_path):
    cfg = wcfg(tmp_path)
    db = Database(cfg.app.database_url)
    from wxbot.data.stations import STATIONS
    every = tuple(STATIONS)
    out = stats_refresh.refresh(db, cfg, FakeHistory(fail=every), FakeTruth(), "w", NOW)
    assert out["rows"] == 0
    nxt = datetime.fromisoformat(db.get_state("next_model_stats_at"))
    assert nxt == NOW + timedelta(hours=float(cfg.model_stats.retry_hours))
    assert stats_refresh.refresh(db, cfg, None, None, "w", nxt)["skipped"].startswith("no source")


class TwelveModelForecast(FakeForecast):
    models = ALL

    def __init__(self):
        super().__init__(tuple(forecast("EGLC", date(2026, 9, 28)).values()))


def test_engine_cycle_with_the_v2_model_in_production(tmp_path):
    cfg = wcfg(tmp_path)
    eng = make_engine(cfg, forecast=TwelveModelForecast(), clock=Clock(NOW))
    eng.history, eng.observer = FakeHistory(), FakeTruth()
    out = eng.run_cycle()
    assert out["model_stats"]["loaded"] > 0 and "error" not in out["signals"]
    prod = eng.db.rows(select(predictions).where(predictions.c.role == "production"))
    assert len(prod) == 11 and {p["model_version"] for p in prod} == {"weighted-multimodel-v1"}
    assert set(prod[0]["inputs"]["weights"]) == set(ALL)
    v1 = eng.db.rows(select(predictions).where(predictions.c.model_version == V1_VERSION))
    assert len(v1) == 11 and all(p["role"] == "shadow" for p in v1)
    # the station bias/spread sets are not retrained while the v2 model is in production
    assert out["learning"]["retrain"] == {"skipped": retrain.WEIGHTED}
    assert retrain.check_rollback(eng.db, cfg, NOW) == {"skipped": retrain.WEIGHTED}


def test_markets_of_a_station_without_stats_get_no_prediction_but_still_their_shadows(tmp_path):
    cfg = wcfg(tmp_path)
    eng = make_engine(cfg, forecast=TwelveModelForecast(), clock=Clock(NOW))   # no history: no stats
    out = eng.run_cycle()
    assert out["model_stats"]["loaded"] == 0 and out["signals"]["no_prediction"] == 11
    assert out["signals"]["predictions"] == 0
    assert not eng.db.rows(select(signals))          # no production prediction: no signal, no bet
    shadows = eng.db.rows(select(predictions).where(predictions.c.role == "shadow"))
    assert {p["model_version"] for p in shadows} >= {V1_VERSION, "raw-forecast-v1"}
    assert all(p["inputs"].get("production_prediction_id") is None for p in shadows)


def test_only_models_recounts_a_forecasts_quality_for_the_models_it_keeps():
    values = {m: 15.0 for m in ALL}
    quality = {"ok": True, "n_clean": 7, "errors": [], "rejected": {"ukmo_seamless": "stale_model_run",
               "gfs_seamless": "out_of_range"}, "warnings": ["outlier:ecmwf_ifs", "outlier:jma_seamless"]}
    vals, q = only_models(values, quality, set(V1), 3)
    assert set(vals) == set(V1) and q["ok"] and q["n_clean"] == 5
    assert q["rejected"] == {"gfs_seamless": "out_of_range"} and q["warnings"] == ["outlier:jma_seamless"]
    failing = {**quality, "ok": False, "errors": ["too_few_valid_models:2<3"]}
    vals, q = only_models(values, failing, {"a", "jma_seamless"}, 3)
    assert vals == {"jma_seamless": 15.0} and not q["ok"] and q["errors"] == ["too_few_valid_models:1<3"]


def test_every_configured_weather_model_has_a_run_time_source():
    """So the stale-run check ([validation] max_model_run_age_hours) covers every model."""
    from wxbot.data.weather import OPEN_METEO_DATASETS
    assert set(load_config(env={}).weather.models) <= set(OPEN_METEO_DATASETS)
