"""v2 M5: probability calibration (isotonic, Platt), walk-forward fitting,
approval, and the engine using the calibrated probability."""
import json
import random
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from tests.conftest import NOW, make_engine
from wxbot.calibration import fit as fit_module
from wxbot.calibration.fit import Calibrator, active_calibrator, day_end, fit_round, gain_confidence, training_set
from wxbot.calibration.methods import apply_isotonic, apply_platt, calibrate, fit_isotonic, fit_platt
from wxbot.db import (
    Database, market_resolutions, markets, paper_bets, predictions, prob_calibrators, signals, system_events,
)
from wxbot.evaluation.metrics import ece, model_comparison, prediction_calibration
from wxbot.report import build_report, to_markdown
from wxbot.web.app import create_app

MODEL = "normal-multimodel-v1"
LEVELS = [0.02, 0.1, 0.3, 0.5, 0.7, 0.9, 0.98]


# -- isotonic -----------------------------------------------------------------------

def test_isotonic_pools_adjacent_violators():
    fit = fit_isotonic([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1], min_block=1)
    assert fit["x"] == pytest.approx([0.1, 0.25, 0.4])
    assert fit["y"] == pytest.approx([0.0, 0.5, 1.0]) and fit["n"] == [1, 2, 1]


def test_isotonic_is_monotone_on_noisy_data():
    rng = random.Random(3)
    probs = [rng.random() for _ in range(500)]
    outs = [int(rng.random() < p) for p in probs]
    fit = fit_isotonic(probs, outs, min_block=10)
    assert fit["y"] == sorted(fit["y"]) and min(fit["n"]) >= 10 and sum(fit["n"]) == 500
    grid = [apply_isotonic(fit, i / 100) for i in range(101)]
    assert grid == sorted(grid)


def test_isotonic_merges_small_blocks_so_two_lucky_markets_move_nothing():
    probs = [0.5] * 100 + [0.85, 0.85]
    outs = [0, 1] * 50 + [1, 1]                # 50% at 0.5, then two lucky 85% predictions
    loose = fit_isotonic(probs, outs, min_block=1)
    assert apply_isotonic(loose, 0.85) == pytest.approx(1.0)     # the step a 2-market block makes
    fit = fit_isotonic(probs, outs, min_block=20)
    assert fit["n"] == [102] and apply_isotonic(fit, 0.85) < 0.95


def test_isotonic_pools_equal_probabilities_whatever_their_order():
    # 0.01 is the probability floor, so many predictions share it exactly
    fit = fit_isotonic([0.01] * 40 + [0.5] * 40, [1] * 4 + [0] * 36 + [1, 0] * 20, min_block=1)
    assert fit["x"] == pytest.approx([0.01, 0.5]) and fit["y"] == pytest.approx([0.1, 0.5])


def test_isotonic_is_anchored_at_0_and_1_beyond_the_data():
    fit = {"x": [0.2, 0.6], "y": [0.1, 0.5], "n": [30, 30]}
    assert apply_isotonic(fit, 0.0) == 0.0 and apply_isotonic(fit, 1.0) == 1.0
    assert apply_isotonic(fit, 0.1) == pytest.approx(0.05) and apply_isotonic(fit, 0.4) == pytest.approx(0.3)
    assert apply_isotonic(fit, 0.8) == pytest.approx(0.75)


# -- Platt ----------------------------------------------------------------------------

def test_platt_leaves_well_calibrated_probabilities_alone():
    probs, outs = [], []
    for p in (0.1, 0.3, 0.5, 0.7, 0.9):
        k = round(p * 200)
        probs += [p] * 200
        outs += [1] * k + [0] * (200 - k)
    fit = fit_platt(probs, outs)
    assert fit["a"] == pytest.approx(1.0, abs=0.05) and fit["b"] == pytest.approx(0.0, abs=0.05)


def test_platt_shrinks_overconfident_probabilities():
    rng = random.Random(5)
    probs = [rng.choice(LEVELS) for _ in range(2000)]
    outs = [int(rng.random() < 0.5 + (p - 0.5) * 0.5) for p in probs]
    fit = fit_platt(probs, outs)
    assert 0 < fit["a"] < 1
    assert 0.6 < apply_platt(fit, 0.98) < 0.85 and 0.15 < apply_platt(fit, 0.02) < 0.4


def test_platt_stays_finite_on_separable_data():
    fit = fit_platt([0.1, 0.2, 0.3, 0.7, 0.8, 0.9], [0, 0, 0, 1, 1, 1])
    assert all(abs(v) < 50 for v in fit.values())
    assert apply_platt(fit, 0.1) < 0.5 < apply_platt(fit, 0.9)


def test_identity_and_clamping():
    assert calibrate("identity", None, 0.123) == 0.123
    cal = Calibrator("platt", "platt-x", {"a": 0.0, "b": 10.0}, prob_floor=0.01, prob_ceiling=0.99)
    assert cal(0.5) == 0.99 and Calibrator("platt", "x", {"a": 0.0, "b": -10.0})(0.5) == 0.01


# -- training data: walk-forward, no look-ahead --------------------------------------

def _market(db, mid, local_date, outcome, resolved_at, station="EGLC"):
    db.insert(markets, id=mid, question=mid, station=station, local_date=local_date, first_seen=NOW, last_seen=NOW,
              resolved_outcome=outcome)
    if resolved_at is not None:
        db.insert(market_resolutions, market_id=mid, resolved_at=resolved_at, outcome=outcome)


def _pred(db, mid, ts, p, role="production", version=MODEL, cal=None, cal_version=None):
    return db.insert(predictions, ts=ts, market_id=mid, model_version=version, role=role, p_yes=p, lead_days=1,
                     calibrated_prob=cal, calibrator_version=cal_version)


def test_day_end_is_local_midnight_after_the_target_day():
    end = day_end("EGLC", "2026-09-28")
    assert end == datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc) and end.tzinfo == timezone.utc  # BST


def test_training_set_uses_only_what_was_known_at_fit_time(cfg):
    db = Database(cfg.app.database_url)
    end = day_end("EGLC", "2026-09-28")                         # 2026-09-28 23:00Z; 18 h before: 05:00Z
    _market(db, "A", "2026-09-28", "YES", end + timedelta(hours=12))
    _pred(db, "A", end - timedelta(hours=40), 0.6)
    _pred(db, "A", end - timedelta(hours=19), 0.7)                  # the decision: latest 18+ h ahead
    _pred(db, "A", end - timedelta(hours=17), 0.95)                 # too close to the end of the day
    _pred(db, "A", end - timedelta(hours=19), 0.1, role="shadow", version="raw-forecast-v1")
    _pred(db, "A", end - timedelta(hours=19), 0.2, version="other-model-v1")
    _market(db, "B", "2026-09-28", "NO", datetime(2026, 10, 5, tzinfo=timezone.utc))   # resolved after the fit
    _pred(db, "B", end - timedelta(hours=19), 0.9)
    _market(db, "C", "2026-09-28", "NO", None)                     # never resolved
    _pred(db, "C", end - timedelta(hours=19), 0.9)
    fit_time = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert training_set(db, MODEL, fit_time, 18) == [(end - timedelta(hours=19), 0.7, 1)]
    assert training_set(db, MODEL, end + timedelta(hours=1), 18) == []   # A's result was not known yet


def _resolved_markets(db, n, truth, seed=1, start=date(2026, 8, 1)):
    """n resolved EGLC markets, ten a day, each priced once 24 h before its day ended."""
    rng = random.Random(seed)
    mk, res, pr = [], [], []
    for i in range(n):
        d = (start + timedelta(days=i // 10)).isoformat()
        end = day_end("EGLC", d)
        p = LEVELS[i % len(LEVELS)]
        outcome = "YES" if rng.random() < truth(p) else "NO"
        mid = f"m{i}"
        mk.append(dict(id=mid, question=mid, station="EGLC", local_date=d, first_seen=NOW, last_seen=NOW,
                       resolved_outcome=outcome))
        res.append(dict(market_id=mid, resolved_at=end + timedelta(hours=12), outcome=outcome))
        pr.append(dict(ts=end - timedelta(hours=24) + timedelta(minutes=i % 10), market_id=mid, model_version=MODEL,
                       role="production", p_yes=p, lead_days=1))
    with db.engine.begin() as conn:
        conn.execute(markets.insert(), mk)
        conn.execute(market_resolutions.insert(), res)
        conn.execute(predictions.insert(), pr)
    return datetime.combine(start + timedelta(days=n // 10 + 3), datetime.min.time(), timezone.utc)


def overconfident(p):
    return 0.5 + (p - 0.5) * 0.5


# -- approval and selection -------------------------------------------------------------

def test_fit_round_approves_a_calibrator_that_fixes_overconfidence(cfg):
    db = Database(cfg.app.database_url)
    fit_time = _resolved_markets(db, 300, overconfident)
    rows = fit_round(db, cfg, MODEL, fit_time)
    assert {r["method"] for r in rows} == {"isotonic", "platt"}
    for r in rows:
        assert r["n"] == 300 and r["n_train"] == 210 and r["n_holdout"] == 90
        assert r["train_to"] <= r["holdout_from"]                    # the holdout is the newest decisions
        assert r["approved"] and r["improvement_confidence"] >= 0.95
        assert r["brier_after"] < r["brier_before"] and r["log_loss_after"] < r["log_loss_before"]
    best = min(rows, key=lambda r: r["log_loss_after"])
    assert [r["selected"] for r in rows] == [r is best for r in rows]
    assert len(db.rows(select(prob_calibrators))) == 2
    cal = active_calibrator(db, cfg, MODEL, fit_time)
    assert cal.version == best["version"] and cal(0.98) < 0.9 and cal(0.02) > 0.1


def test_fit_round_keeps_raw_probabilities_that_are_already_calibrated(cfg):
    db = Database(cfg.app.database_url)
    fit_time = _resolved_markets(db, 300, lambda p: p)
    rows = fit_round(db, cfg, MODEL, fit_time)
    assert not any(r["approved"] for r in rows) and all(r["reason"] for r in rows)
    assert active_calibrator(db, cfg, MODEL, fit_time).method == "identity"


def test_fit_round_needs_min_samples(cfg):
    db = Database(cfg.app.database_url)
    fit_time = _resolved_markets(db, 50, overconfident)
    rows = fit_round(db, cfg, MODEL, fit_time)
    assert [r["reason"] for r in rows] == ["only 50 resolved markets (need 200)"] * 2
    assert not any(r["approved"] for r in rows) and all(r["params"] is None for r in rows)
    assert active_calibrator(db, cfg, MODEL, fit_time).method == "identity"


def test_fit_round_rejects_a_gain_that_could_be_luck(cfg, monkeypatch):
    db = Database(cfg.app.database_url)
    fit_time = _resolved_markets(db, 300, overconfident)
    monkeypatch.setattr(fit_module, "gain_confidence", lambda *a, **k: 0.9)
    rows = fit_round(db, cfg, MODEL, fit_time)
    assert not any(r["approved"] for r in rows)
    assert rows[0]["reason"] == "gain not reliable: wins in 90% of bootstrap resamples (need 95%)"


def test_gain_confidence_counts_bootstrap_wins():
    raw, outs = [0.5] * 100, [1] * 100
    assert gain_confidence(raw, [0.6] * 100, outs) == 1.0
    assert gain_confidence(raw, [0.4] * 100, outs) == 0.0
    one = [0.5] * 99 + [0.6]                                       # better on one market only
    conf = gain_confidence(raw, one, outs)
    assert 0.5 < conf < 0.75 and gain_confidence(raw, one, outs) == conf   # deterministic


def test_newest_round_decides_and_old_fits_are_kept(cfg):
    db = Database(cfg.app.database_url)
    t1, t2 = NOW - timedelta(days=2), NOW - timedelta(days=1)
    common = dict(method="platt", model_version=MODEL, params={"a": 0.5, "b": 0.0})
    db.insert(prob_calibrators, version="platt-1", fitted_at=t1, approved=True, selected=True, **common)
    db.insert(prob_calibrators, version="platt-2", fitted_at=t2, approved=False, selected=False, **common)
    assert active_calibrator(db, cfg, MODEL, t1 + timedelta(hours=1)).version == "platt-1"
    assert active_calibrator(db, cfg, MODEL, NOW).version == "identity"
    assert active_calibrator(db, cfg, "other-model-v1", NOW).version == "identity"
    assert len(db.rows(select(prob_calibrators))) == 2


# -- the engine ---------------------------------------------------------------------------

def test_without_an_approved_calibrator_the_raw_probability_decides(cfg):
    eng = make_engine(cfg)
    summary = eng.run_cycle()
    assert summary["calibration"] == {"n": 0, "using": "identity"}
    preds = eng.db.rows(select(predictions).where(predictions.c.role == "production"))
    assert preds and all(p["calibrator_version"] == "identity" and p["calibrated_prob"] == p["p_yes"] for p in preds)
    sigs = eng.db.rows(select(signals))
    assert all(s["calibrated_prob"] == pytest.approx(s["model_prob"]) for s in sigs)
    first = sigs[0]["rule_results"][0]
    assert first["rule"] == "probabilities" and first["value"]["calibrator"] == "identity"
    assert first["value"]["model"] == first["value"]["calibrated"]
    assert len(eng.db.rows(select(paper_bets))) == 1                 # unchanged from before M5
    assert eng.db.one(select(system_events).where(system_events.c.component == "calibration",
                                    system_events.c.level == "INFO"))
    assert eng.run_cycle()["calibration"] == {"skipped": True}       # refit at most every refit_hours


def test_an_approved_calibrator_drives_confidence_edge_and_ev(cfg):
    db = Database(cfg.app.database_url)
    # a calibrator saying every bucket is ~1% YES, fitted an hour ago
    db.insert(prob_calibrators, version="platt-test", method="platt", model_version=MODEL,
              fitted_at=NOW - timedelta(hours=1), params={"a": 0.0, "b": -10.0}, approved=True, selected=True)
    db.set_state("last_calibration_fit", (NOW - timedelta(hours=1)).isoformat())
    cfg._data["risk"].update(max_event_exposure_pct=1.0, max_station_day_exposure_pct=1.0)  # every bucket may bet
    eng = make_engine(cfg, db=db)
    eng.run_cycle()
    preds = db.rows(select(predictions).where(predictions.c.role == "production"))
    assert all(p["calibrator_version"] == "platt-test" and p["calibrated_prob"] == 0.01 for p in preds)
    bets = db.rows(select(paper_bets))
    assert len(bets) > 1 and all(b["side"] == "NO" and b["confidence"] == pytest.approx(0.99) for b in bets)
    # a bet the raw model alone would not have made: its own probability is under min_model_prob
    low = [b for b in bets if b["model_prob"] < cfg.strategy.min_model_prob]
    assert low
    sig = db.one(select(signals).where(signals.c.id == low[0]["signal_id"]))
    probs = sig["rule_results"][0]["value"]
    assert probs["calibrator"] == "platt-test" and probs["calibrated"] == pytest.approx(0.99)
    assert probs["model"] == pytest.approx(low[0]["model_prob"], abs=1e-6)
    assert sig["edge"] == pytest.approx(0.99 - sig["entry_price"])


# -- metrics, report, API, CLI, migration ---------------------------------------------------

def test_expected_calibration_error():
    assert ece([0.1, 0.1, 0.9, 0.9], [0, 1, 1, 1]) == pytest.approx((2 * 0.4 + 2 * 0.1) / 4)
    assert ece([], []) is None


def test_calibrated_probabilities_are_scored_next_to_raw(cfg):
    db = Database(cfg.app.database_url)
    for mid, outcome, raw, cal in (("A", "YES", 0.6, 0.8), ("B", "NO", 0.4, 0.2)):
        _market(db, mid, "2026-09-28", outcome, NOW)
        pid = _pred(db, mid, NOW, raw, cal=cal, cal_version="platt-x")
        db.insert(signals, ts=NOW, prediction_id=pid, market_id=mid, side="YES", model_prob=raw, market_prob=0.5,
                  decision="NO_BET")
    cal = prediction_calibration(db)
    assert cal["n_calibrated"] == 2 and cal["brier_model"] == pytest.approx(0.16)
    assert cal["brier_calibrated"] == pytest.approx(0.04) and cal["bins_calibrated"]
    rows = {m["model"]: m for m in model_comparison(db)["models"]}
    assert rows[f"{MODEL} calibrated"]["brier"] == pytest.approx(0.04)
    assert rows[f"{MODEL} calibrated"]["production_brier"] == pytest.approx(0.16)


def test_calibrators_are_in_the_report_and_api(cfg):
    db = Database(cfg.app.database_url)
    fit_round(db, cfg, MODEL, _resolved_markets(db, 300, overconfident))
    md = to_markdown(build_report(db, 1000))
    assert "## Probability calibrators (latest fit)" in md and "| isotonic |" in md and "| platt |" in md
    assert "expected calibration error" in md
    perf = TestClient(create_app(cfg, db)).get("/api/performance").json()
    assert {c["method"] for c in perf["calibrators"]} == {"isotonic", "platt"}
    assert "ece_model" in perf["prediction_calibration"] and "bins_calibrated" in perf["prediction_calibration"]


def test_calibrate_cli_fits_now(cfg, monkeypatch, capsys):
    import main
    db = Database(cfg.app.database_url)
    _resolved_markets(db, 300, overconfident, start=date(2024, 1, 1))   # the CLI fits at the real time
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", cfg.app.database_url)
    assert main.main(["calibrate"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["n"] == 300 and out["summary"]["using"] != "identity"
    assert {f["method"] for f in out["fits"]} == {"isotonic", "platt"}


def test_migration_adds_calibration_columns_to_an_old_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:     # tables from before v2 M5
        conn.execute(text("ALTER TABLE predictions DROP COLUMN calibrated_prob"))
        conn.execute(text("ALTER TABLE predictions DROP COLUMN calibrator_version"))
        conn.execute(text("ALTER TABLE signals DROP COLUMN calibrated_prob"))
        conn.execute(text("DROP TABLE prob_calibrators"))
    db = Database(url)
    insp = inspect(db.engine)
    assert {"calibrated_prob", "calibrator_version"} <= {c["name"] for c in insp.get_columns("predictions")}
    assert "calibrated_prob" in {c["name"] for c in insp.get_columns("signals")}
    assert "prob_calibrators" in insp.get_table_names()
    json.dumps(prediction_calibration(db))
