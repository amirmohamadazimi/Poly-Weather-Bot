"""v2 M13: the 30-day experiment. A planned length, recorded once; no new bets
after it while open ones settle; ended and complete logged once each; and a
record of how continuously the bot ran."""
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from tests.conftest import NOW, make_engine
from wxbot.db import Database, bankroll_snapshots, experiments, paper_bets, signals, system_events
from wxbot.evaluation.operation import operation
from wxbot.experiment import ends_at, ensure_experiment, progress
from wxbot.report import build_report, to_markdown
from wxbot.strategy import rules

TAIL = "1010"   # the market the bot bets on in the fake event (NO at 0.91)
ROOT = Path(__file__).resolve().parents[1]


def _events(db, code):
    return [e["message"] for e in db.rows(select(system_events).where(system_events.c.code == code))]


def test_a_planned_length_is_recorded_once_and_cannot_move(cfg):
    cfg._data["experiment"]["days"] = 30
    eng = make_engine(cfg)
    exp = eng.db.one(select(experiments))
    assert exp["planned_days"] == 30
    assert ends_at(exp).isoformat() == "2026-10-27T06:00:00+00:00"
    msgs = [e["message"] for e in eng.db.rows(select(system_events).where(system_events.c.component == "experiment"))]
    assert any("30 days, until 2026-10-27 06:00 UTC" in m for m in msgs)
    cfg._data["experiment"]["days"] = 10                     # a later config change
    make_engine(cfg, db=eng.db)
    assert eng.db.one(select(experiments))["planned_days"] == 30


def test_an_experiment_under_way_gets_its_length_once(cfg):
    db = Database(cfg.app.database_url)
    exp = ensure_experiment(db, cfg, NOW, env={})            # days = 0: no end
    assert exp["planned_days"] is None and ends_at(exp) is None
    cfg._data["experiment"]["days"] = 30                     # the workflow pins it later
    exp = ensure_experiment(db, cfg, NOW + timedelta(days=3), env={})
    exp = ensure_experiment(db, cfg, NOW + timedelta(days=4), env={})
    assert exp["planned_days"] == 30 and ends_at(exp).isoformat() == "2026-10-27T06:00:00+00:00"
    msgs = [e["message"] for e in db.rows(select(system_events).where(system_events.c.component == "experiment"))]
    assert sum("runs for 30 days, until 2026-10-27 06:00 UTC" in m for m in msgs) == 1


def test_after_the_end_no_new_bets_and_open_ones_settle(cfg):
    cfg._data["experiment"]["days"] = 1
    eng = make_engine(cfg)
    eng.run_cycle()
    assert len(eng.db.rows(select(paper_bets))) == 1
    assert progress(eng.db, eng.experiment, NOW)["state"] == "running"

    eng.clock.now = NOW + timedelta(days=1, minutes=1)       # past the end; the bet is still open
    before = {s["id"] for s in eng.db.rows(select(signals))}
    eng.run_cycle()
    eng.run_cycle()
    new = [s for s in eng.db.rows(select(signals)) if s["id"] not in before]
    assert new and all(s["decision"] == "NO_BET" and "experiment_open" in s["reason"] for s in new)
    assert len(eng.db.rows(select(paper_bets))) == 1
    p = progress(eng.db, eng.experiment, eng.clock.now)
    assert p["state"] == "ended" and p["open_bets"] == 1 and p["day"] == 1
    assert len(_events(eng.db, "EXPERIMENT_ENDED")) == 1 and _events(eng.db, "EXPERIMENT_COMPLETE") == []

    eng.pm.resolved[TAIL] = "NO"                             # the open bet still settles
    eng.clock.now = NOW + timedelta(days=2)
    eng.run_cycle()
    eng.run_cycle()
    assert eng.db.one(select(paper_bets))["status"] == "WON"
    assert progress(eng.db, eng.experiment, eng.clock.now)["state"] == "complete"
    assert len(_events(eng.db, "EXPERIMENT_ENDED")) == 1 and len(_events(eng.db, "EXPERIMENT_COMPLETE")) == 1
    md = to_markdown(build_report(eng.db, 100, eng.clock.now))
    assert "· **complete**: ended " in md and "after 1 days, every bet settled" in md


def test_the_rule_refuses_a_bet_after_the_end(cfg):
    ctx = rules.Context(side="NO", model_prob=0.95, market_prob=0.85, entry_price=0.86, liquidity=5000,
                        lead_hours=40, n_models=5, forecast_age_min=10, sigma_c=1.0, market_open=True,
                        has_position=False, daily_pnl=0, initial_bankroll=100, experiment_open=False)
    assert rules.failed(rules.evaluate(ctx, cfg)) == ["experiment_open"]


def test_operation_counts_cycles_gaps_and_days_without_one(cfg):
    cfg._data["experiment"]["days"] = 30
    db = Database(cfg.app.database_url)
    exp = ensure_experiment(db, cfg, NOW, env={})
    for hours in (0, 3, 6, 6 + 50, 6 + 53):                  # nothing ran on the 28th and the 29th
        db.insert(bankroll_snapshots, ts=NOW + timedelta(hours=hours), cash=100, open_exposure=0, equity=100,
                  realized_pnl=0, reason="cycle")
    db.insert(bankroll_snapshots, ts=NOW + timedelta(hours=1), cash=98, open_exposure=2, equity=100,
              realized_pnl=0, reason="bet#1")                # not a cycle
    db.log_event("ERROR", "forecasts", "HTTPError: 503")
    db.log_event("ERROR", "forecasts", "HTTPError: 503")
    op = operation(db, exp, NOW + timedelta(hours=72))      # the 30th is under way, so it is not counted
    assert op["cycles"] == 5 and op["median_gap_hours"] == 3.0 and op["longest_gap_hours"] == 50.0
    assert op["longest_gap"][0].startswith("2026-09-27T12:00") and op["longest_gap"][1].startswith("2026-09-29T14:00")
    assert op["days"] == 3 and op["days_without_cycle"] == ["2026-09-28"]
    assert operation(db, exp, NOW + timedelta(hours=1))["days"] == 0      # the first day is not over
    assert op["step_errors"] == {"forecasts": 2}


def test_report_and_dashboard_show_the_day_and_how_the_bot_ran(cfg):
    from fastapi.testclient import TestClient

    from wxbot.web.app import create_app
    cfg._data["experiment"]["days"] = 30
    eng = make_engine(cfg)
    eng.run_cycle()
    md = to_markdown(build_report(eng.db, 100, NOW))
    assert "· day 1 of 30, ends 2026-10-27 06:00 UTC" in md
    assert "## Operation" in md and "| Cycles completed | 1 |" in md
    exp = TestClient(create_app(cfg, eng.db)).get("/api/overview").json()["experiment"]
    assert exp["progress"]["planned_days"] == 30 and exp["progress"]["state"] in ("running", "ended", "complete")


def test_the_experiment_workflow_pins_30_days():
    wf = (ROOT / ".github/workflows/paper-trading-100.yml").read_text()
    assert 'WXBOT_EXPERIMENT__DAYS: "30"' in wf
