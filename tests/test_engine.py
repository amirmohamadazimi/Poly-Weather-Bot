import io
import zipfile

import pytest
from sqlalchemy import select

from tests.conftest import Clock, FakeForecast, FakePolymarket, london_event, make_engine
from datetime import timedelta
from wxbot.db import Database, forecast_snapshots, paper_bets, predictions, signals
from wxbot.execution import portfolio
from wxbot.export import export_zip_bytes
from wxbot.report import build_report, to_markdown

TAIL_MARKET = "1010"  # "23°C or higher", priced 0.10 while the forecast is ~18°C


def test_full_cycle_places_one_audited_bet(cfg):
    eng = make_engine(cfg)
    summary = eng.run_cycle()
    assert summary["markets"] == {"seen": 22, "tradeable": 11}
    assert summary["signals"]["predictions"] == 11
    bets = eng.db.rows(select(paper_bets))
    assert len(bets) == 1
    bet = bets[0]
    assert bet["market_id"] == TAIL_MARKET and bet["side"] == "NO" and bet["status"] == "OPEN"
    assert bet["stake"] == pytest.approx(10.0)          # 1% of $1,000
    assert bet["entry_price"] == pytest.approx(0.915)   # NO ask 0.91 + 0.005 slippage
    assert bet["model_prob"] >= 0.8 and bet["edge"] >= 0.05
    # the decision can be reconstructed: bet -> signal -> prediction -> forecast snapshot
    sig = eng.db.one(select(signals).where(signals.c.id == bet["signal_id"]))
    assert sig["decision"] == "BET" and all(r["passed"] for r in sig["rule_results"])
    pred = eng.db.one(select(predictions).where(predictions.c.id == sig["prediction_id"]))
    assert pred["inputs"]["model_values_c"] and pred["model_version"] == cfg.model.version
    fc = eng.db.one(select(forecast_snapshots).where(forecast_snapshots.c.id == pred["forecast_snapshot_id"]))
    assert fc["station"] == "EGLC" and fc["local_date"] == "2026-09-28"
    # every other market got a NO_BET signal with its reason recorded
    others = eng.db.rows(select(signals).where(signals.c.decision == "NO_BET"))
    assert len(others) == 10 and all(s["reason"].startswith("failed:") for s in others)


def test_no_duplicate_bets_and_history_not_overwritten(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.clock.now += timedelta(minutes=30)
    eng.run_cycle()
    assert len(eng.db.rows(select(paper_bets))) == 1
    assert len(eng.db.rows(select(predictions))) == 22     # appended, never replaced
    last = eng.db.rows(select(signals).where(signals.c.market_id == TAIL_MARKET))[-1]
    assert "no_existing_position" in last["reason"]


def test_restart_keeps_bankroll_and_settlement(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    before = portfolio.bankroll(eng.db, 1000)
    assert before.cash == pytest.approx(990.0) and before.equity == pytest.approx(1000.0)

    # "restart": brand-new Database/Engine objects on the same file
    pm = FakePolymarket([london_event()])
    pm.resolved[TAIL_MARKET] = "NO"
    eng2 = make_engine(cfg, db=Database(cfg.app.database_url), pm=pm, clock=Clock(eng.clock.now + timedelta(days=2)))
    assert portfolio.bankroll(eng2.db, 1000).cash == pytest.approx(990.0)
    eng2.run_cycle()
    bet = eng2.db.one(select(paper_bets))
    assert bet["status"] == "WON"
    shares = 10.0 / 0.915
    assert bet["payout"] == pytest.approx(shares) and bet["pnl"] == pytest.approx(shares - 10.0)
    after = portfolio.bankroll(eng2.db, 1000)
    assert after.cash == pytest.approx(1000 + shares - 10) and after.open_exposure == 0
    assert bet["bankroll_after"] == pytest.approx(after.equity)


def test_losing_bet_and_report(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.pm.resolved[TAIL_MARKET] = "YES"
    eng.clock.now += timedelta(days=2)
    eng.settle()
    bet = eng.db.one(select(paper_bets))
    assert bet["status"] == "LOST" and bet["pnl"] == pytest.approx(-10.0)
    rep = build_report(eng.db, 1000)
    ov = rep["overview"]
    assert ov["n_settled"] == 1 and ov["win_rate"] == 0 and ov["total_pnl"] == pytest.approx(-10.0)
    assert ov["max_drawdown"] == pytest.approx(10.0)
    assert "too few" in rep["verdict"][0]
    assert "PAPER TRADING" in to_markdown(rep)


def test_uncertain_forecast_blocks_bets(cfg):
    eng = make_engine(cfg, forecast=FakeForecast(values=(12.0, 24.0, 18.0, 15.0, 21.0)))
    eng.run_cycle()
    assert eng.db.rows(select(paper_bets)) == []


def test_step_failure_is_logged_and_cycle_continues(cfg):
    class Broken(FakeForecast):
        def fetch(self, station, days=5):
            raise RuntimeError("open-meteo down")
    eng = make_engine(cfg, forecast=Broken())
    summary = eng.run_cycle()
    assert summary["forecasts"]["snapshots"] == 0 and "seconds" in summary
    assert "open-meteo down" in eng.db.rows(select(__import__("wxbot.db", fromlist=["x"]).system_events))[0]["message"]


def test_observations_stored_once(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.maybe_collect_observations(force=True)
    from wxbot.db import weather_observations
    assert len(eng.db.rows(select(weather_observations))) == 2


def test_export_zip_contains_every_table(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    zf = zipfile.ZipFile(io.BytesIO(export_zip_bytes(eng.db, build_report(eng.db, 1000))))
    names = set(zf.namelist())
    assert {"paper_bets.csv", "signals.csv", "predictions.csv", "report.json"} <= names
    assert zf.read("paper_bets.csv").decode().count("\n") == 2


def test_resolved_market_is_never_bet_again(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.pm.resolved[TAIL_MARKET] = "NO"
    eng.settle()                      # resolved early, while still listed as open
    eng.clock.now += timedelta(minutes=30)
    eng.run_cycle()
    assert len(eng.db.rows(select(paper_bets))) == 1
