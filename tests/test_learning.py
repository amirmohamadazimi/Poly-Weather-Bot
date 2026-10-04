"""v2 M9: the learning ledger, versioned bias/spread param sets, retraining with
an out-of-sample approval rule, and rollback."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.conftest import Clock, FakePolymarket, london_event, make_engine
from wxbot.calibration.fit import active_calibrator
from wxbot.data.polymarket import Bucket
from wxbot.db import (
    Database, calibration_params, market_resolutions, markets, param_sets, prediction_outcomes, predictions,
    prob_calibrators, system_events,
)
from wxbot.learning import outcomes, params, retrain
from wxbot.model.registry import production_model

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
STATIONS = ["EGLC", "LFPG", "LEMD", "EDDM", "LIMC", "EPWA"]
HOLDOUT = [date(2026, 10, 2) + timedelta(days=k) for k in range(7)]
NOISE = [-0.6, -0.2, 0.2, 0.6, -0.4, 0.4, 0.0]
OFFSETS = [-0.4, -0.2, 0.0, 0.2, 0.4]
TAIL_MARKET = "1010"


def truth(station: str, d: date) -> float:
    return 14.0 + STATIONS.index(station) + (d.toordinal() % 4) * 0.7


def forecast(station: str, d: date, bias: float) -> dict:
    """What the five weather models said: the truth plus a bias plus noise."""
    e = NOISE[(d.toordinal() + STATIONS.index(station)) % 7]
    return {f"m{i}": truth(station, d) + bias + e + o for i, o in enumerate(OFFSETS)}


class FakeHistory:
    """Open-Meteo Previous Runs stand-in: forecasts biased by `bias`."""

    def __init__(self, bias: float, fail: tuple = ()):
        self.bias, self.fail, self.calls = bias, fail, []

    def fetch(self, st, start, end, leads):
        self.calls.append((st.code, start, end, tuple(leads)))
        if st.code in self.fail:
            raise ConnectionError("down")
        days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
        return {lead: {"high": {d.isoformat(): forecast(st.code, d, self.bias) for d in days}, "low": {}}
                for lead in leads}


class FakeTruth:
    def __init__(self):
        self.calls = []

    def fetch(self, st, start, end):
        self.calls.append((st.code, start, end))
        days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
        return {"high": {d.isoformat(): (truth(st.code, d), 24) for d in days}, "low": {}}


def make_set(db, cfg, bias: float, sigma: float, now: datetime, deploy: bool = True, version: str | None = None):
    rows = [{"station": s, "kind": "high", "lead_days": lead, "bias_c": bias, "sigma_c": sigma, "n": 60,
             "window_start": "2026-06-01", "window_end": "2026-08-30"} for s in STATIONS for lead in (1, 2, 3)]
    set_id = params.store(db, version=version or f"set-bias{bias}-{now:%H%M%S}", model_version=cfg.model.version,
                          origin="backtest", status="candidate", rows=rows, now=now)
    if deploy:
        params.deploy(db, set_id, now)
    return params.get(db, version=version or f"set-bias{bias}-{now:%H%M%S}")


def priced_markets(db, cfg, ps: dict | None, days=HOLDOUT, stations=STATIONS, bias: float = 2.0) -> int:
    """Resolved markets the bot priced a day ahead with param set `ps`, whose
    forecasts were `bias` too warm. 13 buckets per station and day."""
    model, p = production_model(cfg), params.load(db, cfg, ps)
    n = 0
    for s in stations:
        for d in days:
            values = forecast(s, d, bias)
            obs, centre = round(truth(s, d)), round(truth(s, d) + bias)
            buckets = ([(None, centre - 6)] + [(x, x) for x in range(centre - 5, centre + 6)]
                       + [(centre + 6, None)])
            for k, (lo, hi) in enumerate(buckets):
                mid = f"{s}-{d}-{k}"
                db.insert(markets, id=mid, event_id=f"{s}-{d}", station=s, city=s, kind="high",
                          local_date=d.isoformat(), unit="C", bucket_lo=lo, bucket_hi=hi, tradeable=True,
                          question=f"{s} {d} {lo}-{hi}")
                pred = model.predict(Bucket(lo, hi, "C"), "high", values, 1, p.calibration(s, "high", 1))
                db.insert(predictions, ts=datetime.combine(d, datetime.min.time(), UTC) - timedelta(hours=12),
                          market_id=mid, model_version=pred.model_version, lead_days=1, mu_c=pred.mu_c,
                          sigma_c=pred.sigma_c, p_yes=pred.p_yes, inputs=pred.inputs, role="production",
                          params_version=ps and ps["version"])
                hit = (lo is None or obs >= lo) and (hi is None or obs <= hi)
                db.insert(market_resolutions, market_id=mid, outcome="YES" if hit else "NO",
                          resolved_at=datetime.combine(d, datetime.min.time(), UTC) + timedelta(days=1, hours=6))
                n += 1
    return n


def events(db, code: str) -> list[dict]:
    return db.rows(select(system_events).where(system_events.c.code == code))


# -- the ledger --------------------------------------------------------------------

def test_ledger_records_every_resolved_market_once_with_its_error_class(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    for mk in london_event()["markets"]:
        eng.pm.resolved[mk["id"]] = "YES" if mk["groupItemTitle"] == "18°C" else "NO"
    eng.clock.now += timedelta(days=2)
    summary = eng.run_cycle()
    assert summary["learning"]["outcomes"]["recorded"] == 11
    assert summary["learning"]["retrain"] == {"skipped": "no source of past forecasts and observations"}
    rows = eng.db.rows(select(prediction_outcomes).order_by(prediction_outcomes.c.market_id))
    assert len(rows) == 11 and {r["outcome"] for r in rows} == {"YES", "NO"}
    for r in rows:   # every field the spec asks for is there
        assert r["model_version"] == cfg.model.version and r["prediction_id"] and r["signal_id"]
        assert r["inputs"]["model_values_c"] and r["inputs"]["features"] and r["forecast_source"] == "fake-forecast"
        assert r["decision"] in ("BET", "NO_BET") and r["market_yes"] is not None and r["liquidity"] == 5000
        assert r["brier"] == pytest.approx((r["p_yes"] - r["y"]) ** 2) and r["error_class"]
    tail = next(r for r in rows if r["market_id"] == TAIL_MARKET)
    assert tail["bet_side"] == "NO" and tail["bet_status"] == "WON" and tail["bet_pnl"] > 0
    assert tail["market_yes"] == pytest.approx(0.10) and tail["error_class"] == "right side"
    winner = next(r for r in rows if r["y"] == 1)
    assert winner["error_class"] in ("right side", "underestimation", "significant underestimation")
    # written once: the next cycle adds nothing
    eng.clock.now += timedelta(hours=1)
    assert eng.run_cycle()["learning"]["outcomes"] == {"recorded": 0}
    assert len(eng.db.rows(select(prediction_outcomes))) == 11
    # the stored inputs reproduce every prediction exactly
    assert retrain.reprice(rows, eng._params(), cfg) == pytest.approx([r["p_yes"] for r in rows], abs=1e-12)


def test_significant_errors_are_logged_with_a_code(cfg):
    db = Database(cfg.app.database_url)
    ps = make_set(db, cfg, 0.0, 0.5, NOW - timedelta(days=30))   # sharp and 2 degrees off: big misses
    priced_markets(db, cfg, ps, days=HOLDOUT[:1], stations=STATIONS[:1])
    out = outcomes.record(db, NOW)
    assert out["recorded"] == 13 and out["significant_errors"] >= 1
    ev = events(db, "SIGNIFICANT_MODEL_ERROR")
    assert len(ev) == 1 and ev[0]["details"]["errors"][0]["error_class"].startswith("significant")


# -- param sets ------------------------------------------------------------------

def test_predictions_record_the_param_set_they_were_priced_with(cfg):
    db = Database(cfg.app.database_url)
    eng = make_engine(cfg, db=db)
    assert eng._calibration("EGLC", "high", 1).source == "default"   # no set yet
    ps = make_set(db, cfg, 1.0, 1.2, NOW - timedelta(days=30))
    cal = eng._calibration("EGLC", "high", 1)
    assert (cal.bias_c, cal.sigma_c, cal.source) == (1.0, 1.2, "backtest")
    eng.run_cycle()
    prod = db.rows(select(predictions).where(predictions.c.role == "production"))
    assert prod and {p["params_version"] for p in prod} == {ps["version"]}
    # a set that is not production is never used, whatever its id
    make_set(db, cfg, 5.0, 3.0, NOW, deploy=False)
    assert eng._calibration("EGLC", "high", 1).bias_c == 1.0


def test_a_database_from_before_param_sets_adopts_its_rows_as_production(cfg):
    db = Database(cfg.app.database_url)
    db.insert(calibration_params, station="EGLC", kind="high", lead_days=1, bias_c=0.7, sigma_c=1.1, n=60,
              window_start="2026-06-01", window_end="2026-08-30", fitted_at=datetime(2026, 9, 27, tzinfo=UTC))
    db.insert(prob_calibrators, version="platt-old", method="platt", model_version=cfg.model.version,
              fitted_at=datetime(2026, 9, 29, tzinfo=UTC), params={"a": 1.0, "b": 0.0}, approved=True,
              selected=True)
    db = Database(cfg.app.database_url)     # restart on the M9 code
    ps = params.production(db)
    assert ps["legacy"] and ps["origin"] == "legacy" and ps["version"] == "bias-sigma-20260927-initial"
    assert db.one(select(calibration_params))["param_set_id"] == ps["id"]
    assert make_engine(cfg, db=db)._calibration("EGLC", "high", 1).bias_c == 0.7
    # calibrators fitted before M9 belong to the legacy set, and to no later one
    assert active_calibrator(db, cfg, cfg.model.version, NOW, ps).version == "platt-old"
    new = make_set(db, cfg, 0.0, 1.0, NOW)
    assert active_calibrator(db, cfg, cfg.model.version, NOW, new).version == "identity"
    Database(cfg.app.database_url)          # adopting happens once
    assert len(db.rows(select(param_sets))) == 2


def test_backtest_stores_a_candidate_once_a_production_set_exists(cfg):
    from tests.test_safety_web_backtest import FakeObs, FakePrev
    from wxbot.backtest import run_backtest
    db = Database(cfg.app.database_url)
    end = date(2026, 9, 26)
    first = run_backtest(cfg, db, FakePrev(2.0, 2.0, end), FakeObs(), stations=["EGLC"], days=30, leads=(1,), end=end)
    assert first["param_set"]["production"]
    second = run_backtest(cfg, db, FakePrev(0.0, 0.0, end), FakeObs(), stations=["EGLC"], days=30, leads=(1,),
                          end=end)
    assert not second["param_set"]["production"]
    assert params.production(db)["version"] == first["param_set"]["version"]
    assert params.get(db, version=second["param_set"]["version"])["status"] == "candidate"
    assert make_engine(cfg, db=db)._calibration("EGLC", "high", 1).bias_c == pytest.approx(2.1, abs=0.1)


# -- retraining --------------------------------------------------------------------

def test_retraining_deploys_a_set_that_is_better_out_of_sample(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))     # misses the models' 2 degree warm bias
    n = priced_markets(db, cfg, old, bias=2.0)
    outcomes.record(db, NOW)
    hist, obs = FakeHistory(bias=2.0), FakeTruth()
    out = retrain.retrain(db, cfg, hist, obs, NOW)
    # no look-ahead: fitted only on days that ended before the first holdout decision
    assert out["holdout"] == "2026-10-02 to 2026-10-08" and out["n_holdout"] == n
    assert out["train_to"] == "2026-09-28" and {c[2] for c in hist.calls} == {date(2026, 9, 28)}
    assert {c[1] for c in hist.calls} == {date(2026, 9, 28) - timedelta(days=89)}
    new = params.production(db)
    assert out["deployed"] == new["version"] and new["origin"] == "retrain" and new["replaces"] == old["version"]
    ev = new["evaluation"]
    assert ev["n"] == n and ev["n_stations"] == 6 and ev["confidence"] == 1.0
    assert ev["log_loss_new"] < ev["log_loss_old"] and ev["brier_new"] < ev["brier_old"]
    assert params.get(db, version=old["version"])["status"] == "previous"   # kept for a rollback
    assert len(db.rows(select(param_sets).where(param_sets.c.origin == "retrain"))) == 3   # every window stored
    assert all(r["window_end"] == "2026-09-28" for r in db.rows(select(calibration_params)
                                                                 .where(calibration_params.c.param_set_id == new["id"])))
    cal = params.load(db, cfg, new).calibration("EGLC", "high", 1)
    assert cal.bias_c == pytest.approx(2.0, abs=0.1)
    assert len(events(db, "MODEL_RETRAINED")) == 1 and len(events(db, "MODEL_DEPLOYED")) == 1
    assert json.loads(db.get_state("last_retrain"))["deployed"] == new["version"]
    # next one in a week
    assert retrain.retrain(db, cfg, hist, obs, NOW + timedelta(days=1))["skipped"] == "not due"
    # the new set starts with raw probabilities: no calibrator was fitted on its predictions
    assert active_calibrator(db, cfg, cfg.model.version, NOW, new).version == "identity"


def test_retraining_keeps_production_when_the_candidates_are_worse(cfg):
    db = Database(cfg.app.database_url)
    good = make_set(db, cfg, 2.0, 0.45, NOW - timedelta(days=30))
    priced_markets(db, cfg, good, bias=2.0)
    outcomes.record(db, NOW)
    out = retrain.retrain(db, cfg, FakeHistory(bias=0.5), FakeTruth(), NOW)   # the past looked different
    assert out["deployed"] is None and out["kept"] == good["version"]
    assert params.production(db)["version"] == good["version"]
    rejected = db.rows(select(param_sets).where(param_sets.c.status == "rejected"))
    assert len(rejected) == 3 and not any(r["approved"] for r in rejected)
    assert all("not better" in r["reason"] for r in rejected)
    assert events(db, "MODEL_DEPLOYED") == [] and "kept" in events(db, "MODEL_RETRAINED")[0]["message"]


def test_retraining_waits_for_enough_out_of_sample_markets(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old, days=HOLDOUT[:2], stations=STATIONS[:3])   # 78 markets
    outcomes.record(db, NOW)
    hist = FakeHistory(bias=2.0)
    out = retrain.retrain(db, cfg, hist, FakeTruth(), NOW)
    assert out["skipped"].startswith("only 78 resolved markets") and hist.calls == []
    assert db.get_state("next_retrain_at") is None    # tried again next cycle, without fetching anything


def test_retraining_needs_markets_from_enough_stations(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old, stations=STATIONS[:3])   # 273 markets, 3 stations
    outcomes.record(db, NOW)
    retrain.retrain(db, cfg, FakeHistory(bias=2.0), FakeTruth(), NOW)
    assert params.production(db)["version"] == old["version"]
    assert all("only 3 stations" in r["reason"]
               for r in db.rows(select(param_sets).where(param_sets.c.status == "rejected")))


def test_a_station_that_cannot_be_fetched_keeps_its_production_rows(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old, bias=2.0)
    outcomes.record(db, NOW)
    out = retrain.retrain(db, cfg, FakeHistory(bias=2.0, fail=("EPWA",)), FakeTruth(), NOW)
    assert set(out["failed"]) == {"EPWA"}
    new = params.production(db)
    assert new["n_carried"] == 3 and new["evaluation"]["failed_stations"] == {"EPWA": "ConnectionError: down"}
    assert params.load(db, cfg, new).calibration("EPWA", "high", 1).bias_c == 0.0


def test_retraining_with_no_data_at_all_retries_the_next_day(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old)
    outcomes.record(db, NOW)
    out = retrain.retrain(db, cfg, FakeHistory(2.0, fail=tuple(STATIONS)), FakeTruth(), NOW)
    assert out["error"] == "no data" and params.production(db)["version"] == old["version"]
    assert datetime.fromisoformat(db.get_state("next_retrain_at")) == NOW + timedelta(hours=24)


def test_learning_can_be_turned_off(cfg, monkeypatch):
    from wxbot.config import load_config
    off = load_config(env={"WXBOT_APP__DATABASE_URL": cfg.app.database_url, "WXBOT_LEARNING__ENABLED": "false"})
    db = Database(off.app.database_url)
    old = make_set(db, off, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, off, old)
    outcomes.record(db, NOW)
    assert retrain.retrain(db, off, FakeHistory(2.0), FakeTruth(), NOW) == {"skipped": "learning is disabled"}
    assert retrain.check_rollback(db, off, NOW) == {"skipped": "learning is disabled"}


# -- rollback ----------------------------------------------------------------------

def test_a_deployed_set_that_does_worse_is_rolled_back(cfg):
    db = Database(cfg.app.database_url)
    good = make_set(db, cfg, 2.0, 0.45, NOW - timedelta(days=30), version="good")
    bad = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=9), version="bad")    # replaces it
    assert params.get(db, version="good")["status"] == "previous"
    priced_markets(db, cfg, bad, days=HOLDOUT[:1], stations=STATIONS[:2])
    outcomes.record(db, NOW)
    assert retrain.check_rollback(db, cfg, NOW) == {"monitoring": "bad", "markets": 26, "need": 200}
    priced_markets(db, cfg, bad, days=HOLDOUT[1:])
    outcomes.record(db, NOW)
    assert retrain.check_rollback(db, cfg, NOW) == {"rolled_back": "bad", "reinstated": "good"}
    assert params.production(db)["version"] == "good"
    reverted = params.get(db, version="bad")
    assert reverted["status"] == "rolled_back" and "rolled back" in reverted["reason"]
    ev = events(db, "MODEL_ROLLBACK")
    assert len(ev) == 1 and ev[0]["level"] == "WARNING" and ev[0]["details"]["reinstated"] == "good"
    assert retrain.check_rollback(db, cfg, NOW) == {"skipped": "no previous set to compare with"}
    assert good["id"] == params.production(db)["id"]


def test_a_deployed_set_that_does_better_stays(cfg):
    db = Database(cfg.app.database_url)
    make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30), version="bad")
    good = make_set(db, cfg, 2.0, 0.45, NOW - timedelta(days=9), version="good")
    priced_markets(db, cfg, good)
    outcomes.record(db, NOW)
    assert retrain.check_rollback(db, cfg, NOW)["kept"] is True
    assert params.production(db)["version"] == "good" and events(db, "MODEL_ROLLBACK") == []


def test_manual_rollback(cfg, monkeypatch, capsys):
    import main
    db = Database(cfg.app.database_url)
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", cfg.app.database_url)
    make_set(db, cfg, 2.0, 0.45, NOW - timedelta(days=30), version="first")
    assert main.main(["rollback"]) == 1                     # nothing to go back to
    assert "no previous" in capsys.readouterr().out
    make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=9), version="second")
    assert main.main(["rollback"]) == 0
    assert json.loads(capsys.readouterr().out) == {"rolled_back": "second", "reinstated": "first"}
    assert params.production(db)["version"] == "first"
    assert events(db, "MODEL_ROLLBACK")[0]["details"]["manual"] is True


def test_engine_retrains_in_its_cycle_when_given_past_forecasts(cfg):
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old, bias=2.0)
    eng = make_engine(cfg, db=db, pm=FakePolymarket([]), clock=Clock(NOW))
    eng.history, eng.observer = FakeHistory(2.0), FakeTruth()
    out = eng.learn()
    assert out["outcomes"]["recorded"] == 546 and out["retrain"]["deployed"]
    assert eng._params().version == out["retrain"]["deployed"]


def test_dashboard_report_and_health_show_model_updates(cfg):
    from fastapi.testclient import TestClient

    from wxbot.report import build_report, to_markdown
    from wxbot.web.app import create_app
    db = Database(cfg.app.database_url)
    old = make_set(db, cfg, 0.0, 1.0, NOW - timedelta(days=30))
    priced_markets(db, cfg, old, bias=2.0)
    outcomes.record(db, NOW)
    out = retrain.retrain(db, cfg, FakeHistory(2.0), FakeTruth(), NOW)
    client = TestClient(create_app(cfg, db, now=lambda: NOW))
    u = client.get("/api/learning").json()
    assert u["production"]["version"] == out["deployed"] and len(u["sets"]) == 4 and u["ledger_rows"] == 546
    assert u["settings"]["min_markets"] == 200 and u["last_retrain"]["deployed"] == out["deployed"]
    assert {e["code"] for e in u["events"]} >= {"MODEL_RETRAINED", "MODEL_DEPLOYED"}
    m = client.get("/api/status").json()["model"]
    assert m["params"]["version"] == out["deployed"] and m["last_retrain"]["deployed"] == out["deployed"]
    assert "Model updates" in client.get("/").text
    md = to_markdown(build_report(db, 100))
    assert "## Model updates" in md and out["deployed"] in md and "| previous |" in md
