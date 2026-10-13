"""v2 M4: feature set, baselines, model registry, shadow predictions, model comparison."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from tests.conftest import NOW, FakeForecast, make_engine
from wxbot.data.polymarket import Bucket
from wxbot.db import (
    Database, market_resolutions, markets, model_versions, paper_bets, predictions, signals, system_events,
    weather_observations,
)
from wxbot.evaluation.metrics import model_comparison, prediction_calibration
from wxbot.features import FEATURE_SET, Features, climatology_window, days_apart, observed_history
from wxbot.history import load_history
from wxbot.model.base import Calibration
from wxbot.model.baselines import Climatology, RawForecast
from wxbot.model.normal import NormalMultiModel, default_calibration
from wxbot.model.registry import shadow_models
from wxbot.report import build_report, to_markdown
from wxbot.web.app import create_app

VALUES = {"m1": 17.6, "m2": 18.0, "m3": 18.2, "m4": 17.9, "m5": 18.3}
C18 = Bucket(18, 18, "C")


class RunForecast(FakeForecast):
    """FakeForecast that also reports each model's run time (00Z on NOW's day)."""
    def fetch(self, station, days=5):
        values, _ = super().fetch(station, days)
        return values, {"model_runs": {m: "2026-09-27T00:00:00+00:00" for m in self.models}}


class YearsOfObservations:
    """Observer returning a fixed high/low for every requested day."""
    source = "fake-obs"

    def __init__(self, high=18.0, low=10.0, fail_year_starting=None):
        self.high, self.low, self.fail = high, low, fail_year_starting
        self.requests = []

    def fetch(self, st, start, end):
        self.requests.append((st.code, start, end))
        if self.fail and start.year == self.fail:
            raise RuntimeError("IEM timeout")
        days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
        return {"high": {d: (self.high, 24) for d in days}, "low": {d: (self.low, 24) for d in days}}


def _obs(db, station, d, value, fetched_at, kind="high"):
    db.insert(weather_observations, station=station, local_date=d, kind=kind, value_c=value, n_reports=24,
              source="fake-obs", fetched_at=fetched_at)


# -- feature set ------------------------------------------------------------------

def test_features_are_stored_with_every_prediction(cfg):
    eng = make_engine(cfg, forecast=RunForecast())
    eng.run_cycle()
    prod = eng.db.rows(select(predictions).where(predictions.c.role == "production"))
    assert prod and all(p["feature_set"] == FEATURE_SET for p in prod)
    f = prod[0]["inputs"]["features"]
    assert f["feature_set"] == FEATURE_SET and f["station"] == "EGLC" and f["kind"] == "high"
    assert f["forecast_mean_c"] == 18.0 and f["n_models"] == 5
    assert f["forecast_spread_c"] == pytest.approx(0.245, abs=1e-3)
    assert f["forecast_min_c"] == 17.6 and f["forecast_max_c"] == 18.3
    assert f["month"] == 9 and f["day_of_year"] == date(2026, 9, 28).timetuple().tm_yday and f["lead_days"] == 1
    # oldest run 2026-09-27 00Z to the end of 28 Sep in London (23:00Z)
    assert f["horizon_hours"] == 47.0
    assert f["clim_n"] == 0 and f["clim_mean_c"] is None and f["anomaly_c"] is None


def test_calendar_distance_wraps_the_year():
    assert days_apart(date(2025, 12, 30), date(2026, 1, 2)) == 3
    assert days_apart(date(2024, 2, 29), date(2026, 3, 1)) == 1
    assert days_apart(date(2025, 6, 1), date(2026, 9, 28)) > 100


def test_climatology_window_uses_only_past_known_observations(cfg):
    db = Database(cfg.app.database_url)
    before, after = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    _obs(db, "EGLC", "2025-09-28", 17.0, before)     # same date last year: in
    _obs(db, "EGLC", "2025-10-04", 15.0, before)     # 6 days away: in
    _obs(db, "EGLC", "2025-10-10", 30.0, before)     # 12 days away: out of the window
    _obs(db, "EGLC", "2026-09-25", 19.0, before)     # 3 days before: in
    _obs(db, "EGLC", "2026-09-25", 19.5, before)     # re-fetched: the later value replaces it
    _obs(db, "EGLC", "2026-09-26", 40.0, after)      # fetched after the decision: out
    _obs(db, "EGLC", "2026-09-28", 40.0, before)     # the target day itself: out
    _obs(db, "EGLC", "2025-09-28", 5.0, before, kind="low")  # other kind: out
    hist = observed_history(db, "EGLC", "high", NOW)
    assert sorted(climatology_window(hist, "2026-09-28", 7)) == [15.0, 17.0, 19.5]


# -- baselines --------------------------------------------------------------------

def test_raw_forecast_ignores_station_calibration():
    sigmas = [1.4, 1.7, 2.1, 2.5, 3.0]
    fitted = Calibration(bias_c=2.0, sigma_c=0.8, n=60, source="backtest")
    raw = RawForecast(sigmas).predict(C18, "high", VALUES, 1, fitted)
    expected = NormalMultiModel("raw-forecast-v1").predict(C18, "high", VALUES, 1, default_calibration(sigmas, 1))
    assert raw.model_version == "raw-forecast-v1" and raw.mu_c == pytest.approx(18.0)
    assert raw.sigma_c == 1.7 and raw.p_yes == pytest.approx(expected.p_yes)
    assert raw.p_yes != pytest.approx(NormalMultiModel().predict(C18, "high", VALUES, 1, fitted).p_yes)


def test_climatology_is_the_observed_frequency_in_whole_degrees():
    # 17.6 and 18.4 read as 18; 16.5 rounds half up to 17
    samples = [17.6] * 10 + [18.4] * 5 + [16.5] * 5
    clim = Climatology(window_days=7, min_samples=20)
    p = clim.predict(C18, "high", VALUES, 1, None, Features({}, samples))
    assert p.p_yes == 0.75 and p.inputs["n"] == 20 and p.inputs["k"] == 15
    assert clim.predict(Bucket(17, 17, "C"), "high", VALUES, 1, None, Features({}, samples)).p_yes == 0.25
    assert clim.predict(Bucket(None, 16, "C"), "high", VALUES, 1, None, Features({}, samples)).p_yes == 0.01  # floor
    # 17.6 C = 63.7 F -> 64; 18.4 C = 65.1 F -> 65; 16.5 C = 61.7 F -> 62
    assert clim.predict(Bucket(64, 65, "F"), "high", VALUES, 1, None, Features({}, samples)).p_yes == 0.75


def test_climatology_declines_with_too_few_samples():
    clim = Climatology(min_samples=20)
    assert clim.predict(C18, "high", VALUES, 1, None, Features({}, [18.0] * 19)) is None
    assert clim.predict(C18, "high", VALUES, 1, None, None) is None


# -- shadow predictions -------------------------------------------------------------

def test_shadow_predictions_are_stored_but_never_trade(cfg):
    eng = make_engine(cfg)
    eng.observer = YearsOfObservations()
    load_history(eng, 3, NOW.date(), ["EGLC"])
    out = eng.run_cycle()["signals"]
    rows = eng.db.rows(select(predictions))
    prod = [r for r in rows if r["role"] == "production"]
    shadow = [r for r in rows if r["role"] == "shadow"]
    assert out["predictions"] == len(prod) == 11 and out["shadow_predictions"] == len(shadow) == 22
    assert {r["model_version"] for r in shadow} == {"raw-forecast-v1", "climatology-v1"}
    prod_ids = {r["id"] for r in prod}
    assert all(r["inputs"]["production_prediction_id"] in prod_ids for r in shadow)
    assert all("features" not in r["inputs"] and "model_values_c" not in r["inputs"] for r in shadow)
    sig = eng.db.rows(select(signals))
    assert len(sig) == len(prod) and {s["prediction_id"] for s in sig} == prod_ids
    assert len(eng.db.rows(select(paper_bets))) == 1
    clim = next(r for r in shadow if r["model_version"] == "climatology-v1")
    # history is 18.0 every day: every reading falls in the 18°C bucket
    assert clim["inputs"]["n"] >= 20
    assert next(r for r in prod if r["id"] == clim["inputs"]["production_prediction_id"])["inputs"]["features"][
        "clim_mean_c"] == 18.0


def test_broken_shadow_model_never_stops_the_production_model(cfg):
    class Broken:
        name, version, calibration_version, params = "broken", "broken-v1", "none", {}

        def predict(self, *a, **k):
            raise ZeroDivisionError("bad baseline")
    eng = make_engine(cfg, shadows=[Broken()])
    out = eng.run_cycle()["signals"]
    assert out["predictions"] == 11 and out["shadow_predictions"] == 0 and out["bets"] == 1
    events = eng.db.rows(select(system_events).where(system_events.c.component == "shadow_model"))
    assert len(events) == 1 and "ZeroDivisionError" in events[0]["message"]


# -- registry -----------------------------------------------------------------------

def _registry(db):
    return {r["version"]: r for r in db.rows(select(model_versions))}


def test_registry_lists_production_and_shadow_models(cfg):
    eng = make_engine(cfg)
    reg = _registry(eng.db)
    assert {v: r["role"] for v, r in reg.items()} == {
        "normal-multimodel-v1": "production", "raw-forecast-v1": "shadow", "climatology-v1": "shadow"}
    assert reg["normal-multimodel-v1"]["calibration_version"] == "station-bias-sigma-v1"
    assert reg["climatology-v1"]["params"]["window_days"] == 7 and reg["raw-forecast-v1"]["feature_set"] == FEATURE_SET
    make_engine(cfg, db=eng.db)                         # restart: nothing changes
    assert len(eng.db.rows(select(model_versions))) == 3


def test_registry_retires_models_that_leave_the_config(cfg):
    eng = make_engine(cfg)
    cfg._data["model"]["version"] = "normal-multimodel-v2"
    cfg._data["model"]["shadow_models"] = ["raw-forecast-v1"]
    make_engine(cfg, db=eng.db)
    roles = {v: r["role"] for v, r in _registry(eng.db).items()}
    assert roles == {"normal-multimodel-v1": "retired", "raw-forecast-v1": "shadow", "climatology-v1": "retired",
                     "normal-multimodel-v2": "production"}
    ev = system_events.c
    msgs = [e["message"] for e in eng.db.rows(select(system_events).where(ev.component == "model_registry"))]
    assert "normal-multimodel-v1: production -> retired" in msgs
    assert "normal-multimodel-v2 registered as production" in msgs


def test_registry_flags_changed_params_without_a_new_version(cfg):
    eng = make_engine(cfg)
    cfg._data["model"]["climatology_window_days"] = 10
    make_engine(cfg, db=eng.db)
    ev = system_events.c
    msgs = [e["message"] for e in eng.db.rows(select(system_events).where(ev.component == "model_registry"))]
    assert any(m.startswith("climatology-v1: params differ") for m in msgs)


def test_unknown_shadow_model_fails_at_startup(cfg):
    cfg._data["model"]["shadow_models"] = ["crystal-ball-v1"]
    with pytest.raises(ValueError, match="crystal-ball-v1"):
        shadow_models(cfg)


# -- model comparison ---------------------------------------------------------------

def _market(db, mid, outcome):
    db.insert(markets, id=mid, question=mid, first_seen=NOW, last_seen=NOW, resolved_outcome=outcome)
    db.insert(market_resolutions, market_id=mid, resolved_at=NOW, outcome=outcome)


def _pred(db, mid, ts, version, role, p, lead=1):
    return db.insert(predictions, ts=ts, market_id=mid, model_version=version, role=role, p_yes=p, lead_days=lead)


def _comparison_db(cfg):
    db = Database(cfg.app.database_url)
    t0, t1, t2 = NOW - timedelta(hours=10), NOW, NOW + timedelta(hours=10)
    _market(db, "A", "YES")
    _market(db, "B", "NO")
    for mid, prod, raw in (("A", 0.8, 0.6), ("B", 0.3, 0.4)):
        _pred(db, mid, t0, "normal-multimodel-v1", None, 0.5)          # older cycle (pre-M4 row): not used
        _pred(db, mid, t0, "raw-forecast-v1", "shadow", 0.9)
        pid = _pred(db, mid, t1, "normal-multimodel-v1", "production", prod)
        _pred(db, mid, t1, "raw-forecast-v1", "shadow", raw)
        db.insert(signals, ts=t1, prediction_id=pid, market_id=mid, side="YES", model_prob=prod,
                  market_prob={"A": 0.7, "B": 0.2}[mid], decision="NO_BET",
                  rule_results=[{"rule": "liquidity", "passed": True, "value": 2500}])
        _pred(db, mid, t2, "normal-multimodel-v1", "production", 0.99, lead=0)  # same day: too late
    _pred(db, "A", t1, "climatology-v1", "shadow", 0.5)                 # climatology only predicted A
    return db


def test_model_comparison_scores_each_model_on_the_same_markets(cfg):
    comp = model_comparison(_comparison_db(cfg))
    rows = {m["model"]: m for m in comp["models"]}
    assert comp["n_markets"] == 2
    prod = rows["normal-multimodel-v1"]
    assert prod["n"] == 2 and prod["brier"] == pytest.approx((0.2 ** 2 + 0.3 ** 2) / 2)
    raw = rows["raw-forecast-v1"]
    assert raw["n"] == 2 and raw["brier"] == pytest.approx((0.4 ** 2 + 0.4 ** 2) / 2)
    assert raw["production_brier"] == pytest.approx(prod["brier"])
    clim = rows["climatology-v1"]                          # scored on A only, against production on A only
    assert clim["n"] == 1 and clim["brier"] == pytest.approx(0.25) and clim["production_brier"] == pytest.approx(0.04)
    assert clim["log_loss"] == pytest.approx(0.693147, abs=1e-5)
    assert clim["production_log_loss"] == pytest.approx(0.223144, abs=1e-5)
    mkt = rows["market price (mid)"]
    assert mkt["n"] == 2 and mkt["brier"] == pytest.approx((0.3 ** 2 + 0.2 ** 2) / 2)


def test_prediction_calibration_ignores_shadow_predictions(cfg):
    cal = prediction_calibration(_comparison_db(cfg))
    assert cal["n"] == 2 and cal["brier_model"] == pytest.approx((0.2 ** 2 + 0.3 ** 2) / 2)


def test_comparison_is_in_the_report_and_api(cfg):
    db = _comparison_db(cfg)
    md = to_markdown(build_report(db, 1000))
    assert "## Model comparison" in md and "| raw-forecast-v1 |" in md
    assert "| market price (mid) | benchmark | 2 |" in md
    make_engine(cfg, db=db)
    api = TestClient(create_app(cfg, db))
    assert {m["model"] for m in api.get("/api/performance").json()["model_comparison"]["models"]} >= {
        "raw-forecast-v1", "climatology-v1"}
    assert [m["version"] for m in api.get("/api/models").json()] == [
        "normal-multimodel-v1", "raw-forecast-v1", "climatology-v1"]


# -- history for climatology --------------------------------------------------------

def test_history_load_fetches_each_year_once_and_never_duplicates(cfg):
    eng = make_engine(cfg)
    eng.observer = YearsOfObservations()
    out = load_history(eng, 2, date(2026, 9, 27), ["EGLC", "KLGA"])
    assert out["EGLC"] == {"stored": 2 * 365 * 2, "failed_years": 0}
    reqs = [r for r in eng.observer.requests if r[0] == "EGLC"]
    assert reqs == [("EGLC", date(2025, 9, 27), date(2026, 9, 26)), ("EGLC", date(2024, 9, 27), date(2025, 9, 26))]
    assert load_history(eng, 2, date(2026, 9, 27), ["EGLC"])["EGLC"]["stored"] == 0
    assert eng.db.get_state("history_loaded_at")


def test_history_load_survives_a_failed_year(cfg):
    eng = make_engine(cfg)
    eng.observer = YearsOfObservations(fail_year_starting=2024)
    out = load_history(eng, 2, date(2026, 9, 27), ["EGLC"])
    assert out["EGLC"] == {"stored": 365 * 2, "failed_years": 1}
    assert eng.db.one(select(system_events).where(system_events.c.message.like("EGLC 2024-09-27%IEM timeout")))


def test_history_load_that_fails_completely_is_retried_next_time(cfg):
    eng = make_engine(cfg)
    eng.observer = YearsOfObservations(fail_year_starting=2025)
    assert load_history(eng, 1, date(2026, 9, 27), ["EGLC", "KLGA"]) == {
        "EGLC": {"stored": 0, "failed_years": 1}, "KLGA": {"stored": 0, "failed_years": 1}}
    assert eng.db.get_state("history_loaded_at") is None
    eng.observer = YearsOfObservations()
    load_history(eng, 1, date(2026, 9, 27), ["EGLC"])
    assert eng.db.get_state("history_loaded_at")


def test_climatology_cli_skips_when_history_is_loaded(cfg, tmp_path, monkeypatch, capsys):
    import main
    db = Database(cfg.app.database_url)
    db.set_state("history_loaded_at", NOW.isoformat())
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", cfg.app.database_url)
    assert main.main(["climatology", "--if-missing"]) == 0
    assert "already loaded" in capsys.readouterr().out


# -- migration ----------------------------------------------------------------------

def test_migration_adds_prediction_role_and_registry_to_an_old_database(tmp_path, cfg):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:     # a predictions table from before v2 M4
        conn.execute(text("ALTER TABLE predictions DROP COLUMN role"))
        conn.execute(text("ALTER TABLE predictions DROP COLUMN feature_set"))
        conn.execute(text("DROP TABLE model_versions"))
    db = Database(url)
    cols = {c["name"] for c in inspect(db.engine).get_columns("predictions")}
    assert {"role", "feature_set"} <= cols and "model_versions" in inspect(db.engine).get_table_names()
    json.dumps(model_comparison(db))
