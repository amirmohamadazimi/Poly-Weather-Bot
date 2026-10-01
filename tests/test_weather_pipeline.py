"""v2 M2: forecast revisions, validation, migrations."""
import math
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import inspect, select, text

from tests.conftest import NOW, FakeForecast, make_engine
from wxbot.data.validation import validate_forecast, validate_observation
from wxbot.data.weather import OpenMeteoForecast
from wxbot.db import Database, forecast_snapshots, forecast_values, paper_bets, signals, weather_observations

RULES = SimpleNamespace(min_temp_c=-70, max_temp_c=60, max_model_run_age_hours=36, outlier_c=8,
                        min_obs_reports=18, min_models=3)


def test_validation_rejects_bad_values_and_records_why():
    runs = {"m4": NOW - timedelta(hours=50)}
    q = validate_forecast({"m1": 18.0, "m2": math.nan, "m3": 999.0, "m4": 18.2, "m5": 18.1, "m6": 30.0},
                          runs, NOW, RULES)
    assert q.rejected == {"m2": "not_a_number", "m3": "out_of_range", "m4": "stale_model_run"}
    assert set(q.clean) == {"m1", "m5", "m6"} and q.ok
    assert q.warnings == ["outlier:m6"]


def test_validation_blocks_when_too_few_models_survive():
    q = validate_forecast({"m1": 18.0, "m2": 200.0, "m3": None}, {}, NOW, RULES)
    assert not q.ok and q.errors == ["too_few_valid_models:1<3"]


def test_observation_validation():
    assert validate_observation(18.0, 24, RULES) is None
    assert validate_observation(80.0, 24, RULES) == "out_of_range"
    assert validate_observation(18.0, 5, RULES) == "too_few_reports"


class RunsForecast(FakeForecast):
    def __init__(self, values=(17.6, 18.0, 18.2, 17.9, 18.3), run_age_h=6):
        super().__init__(values)
        self.run_age_h = run_age_h

    def fetch(self, station, days=5):
        by_kind, _ = super().fetch(station, days)
        run = (NOW - timedelta(hours=self.run_age_h)).isoformat()
        return by_kind, {"model_runs": {m: run for m in self.models}}


def test_every_model_value_is_stored_with_run_time_and_horizon(cfg):
    eng = make_engine(cfg, forecast=RunsForecast())
    eng.run_cycle()
    snap = eng.db.one(select(forecast_snapshots).where(forecast_snapshots.c.local_date == "2026-09-28",
                                                      forecast_snapshots.c.kind == "high"))
    assert snap["quality"]["ok"] and snap["issue_time"] is not None
    vals = eng.db.rows(select(forecast_values).where(forecast_values.c.snapshot_id == snap["id"]))
    assert len(vals) == 5 and all(v["valid"] and v["issue_time_source"] == "model_run" for v in vals)
    v = vals[0]
    assert v["variable"] == "temperature_2m_max" and v["lat"] and v["unit"] == "C"
    # London 2026-09-28 ends 23:00Z on the 28th: 41 h after NOW, plus the run's 6 h age
    assert v["horizon_hours"] == 47.0
    assert len(eng.db.rows(select(paper_bets))) == 1   # behaviour unchanged for clean data


def test_corrupt_forecast_means_no_bet(cfg):
    eng = make_engine(cfg, forecast=RunsForecast(values=(17.6, 999.0, -500.0, 17.9, float("nan"))))
    eng.run_cycle()
    assert eng.db.rows(select(paper_bets)) == []
    sig = eng.db.rows(select(signals).where(signals.c.market_id == "1010"))[-1]
    assert "data_validation" in sig["reason"] and "data_quality_models" in sig["reason"]
    stored = eng.db.rows(select(forecast_values).where(forecast_values.c.valid.is_(False)))
    assert {r["problem"] for r in stored} == {"out_of_range", "not_a_number"}


def test_stale_model_runs_are_rejected(cfg):
    eng = make_engine(cfg, forecast=RunsForecast(run_age_h=48))
    eng.run_cycle()
    assert eng.db.rows(select(paper_bets)) == []
    snap = eng.db.one(select(forecast_snapshots).limit(1))
    assert not snap["quality"]["ok"] and set(snap["quality"]["rejected"].values()) == {"stale_model_run"}


def test_unknown_run_time_is_recorded_not_guessed(cfg):
    eng = make_engine(cfg)      # FakeForecast reports no run times
    eng.run_cycle()
    v = eng.db.one(select(forecast_values).limit(1))
    assert v["issue_time"] is None and v["issue_time_source"] == "unknown"


def test_bad_observation_is_not_stored(cfg):
    eng = make_engine(cfg)
    assert eng.store_observations("EGLC", {"high": {"2026-09-26": (75.0, 24)}, "low": {}}) == 0
    assert eng.db.rows(select(weather_observations)) == []


def test_run_time_lookup_failure_degrades_to_unknown():
    class Down:
        def get(self, *a, **kw):
            raise ConnectionError("meta down")
    om = OpenMeteoForecast(["ecmwf_ifs025", "not_a_model"], session=Down())
    assert om.model_runs() == {"ecmwf_ifs025": None, "not_a_model": None}


def test_migration_adds_columns_to_an_old_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:      # make it look like a database from before v2
        conn.execute(text("ALTER TABLE forecast_snapshots DROP COLUMN quality"))
        conn.execute(text("ALTER TABLE forecast_snapshots DROP COLUMN issue_time"))
        conn.execute(text("DROP TABLE forecast_values"))
    db = Database(url)
    cols = {c["name"] for c in inspect(db.engine).get_columns("forecast_snapshots")}
    assert {"quality", "issue_time"} <= cols
    assert "forecast_values" in inspect(db.engine).get_table_names()
