"""v2 M6: the $100 paper engine, mark-to-market, the cash invariant, the
city-day exposure cap, the sizing record and experiment identity."""
import json
import math
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text

from tests.conftest import NOW, make_engine
from wxbot.config import load_config
from wxbot.db import Database, bankroll_snapshots, experiments, markets, paper_bets, signals, system_events
from wxbot.evaluation.metrics import overview
from wxbot.execution import portfolio
from wxbot.execution.paper import BrokerRefused, PaperBroker
from wxbot.experiment import ensure_experiment, record_code_version, redact
from wxbot.report import build_report, to_markdown
from wxbot.strategy import rules
from wxbot.strategy.rules import Fill

TAIL = "1010"          # "23°C or higher": YES bid 0.09 / ask 0.11, the bot buys NO
SHARES = 2.0 / 0.915   # $2 at the NO ask 0.91 plus 0.005 slippage


def _tail(eng) -> dict:
    return next(m for m in eng.pm.events[0]["markets"] if m["id"] == TAIL)


# -- $100 defaults and what a bet records ---------------------------------------------

def test_defaults_are_a_conservative_100_dollar_run(cfg):
    assert cfg.bankroll.initial == 100.0
    assert cfg.sizing.method == "fixed_fraction" and cfg.sizing.fraction == 0.02 and cfg.sizing.min_stake == 1.0
    assert cfg.risk.max_bet_pct == 0.02 and cfg.risk.max_station_day_exposure_pct >= cfg.risk.max_event_exposure_pct


def test_bet_records_its_sizing_and_the_quotes_it_traded_on(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    bet = eng.db.one(select(paper_bets))
    assert bet["stake"] == pytest.approx(2.0)
    sz = bet["sizing"]
    assert sz["sizer"] == "fixed_fraction" and sz["equity"] == pytest.approx(100.0) and sz["cash"] == pytest.approx(100)
    assert set(sz["caps"]) == {"sizer", "max_bet", "open_exposure_room", "event_exposure_room",
                               "station_day_exposure_room", "cash", "book_capacity"}
    assert sz["caps"]["station_day_exposure_room"] == pytest.approx(8.0) and sz["budget"] == pytest.approx(2.0)
    assert sz["binding_cap"] in ("sizer", "max_bet") and sz["fill_levels"] == [[0.91, pytest.approx(SHARES, abs=1e-4)]]
    snap = bet["market_snapshot"]
    assert snap["side"] == "NO" and snap["bid"] == pytest.approx(0.89) and snap["ask"] == pytest.approx(0.91)
    assert snap["mid"] == pytest.approx(0.90) and snap["yes_bid"] == 0.09 and snap["yes_ask"] == 0.11
    assert snap["liquidity"] == 5000 and snap["book_best_ask"] == 0.91 and snap["snapshot_id"]


# -- mark-to-market -----------------------------------------------------------------------

def test_mark_price_uses_the_bid_of_the_side_held():
    snap = {"best_bid": 0.30, "best_ask": 0.34, "yes_price": 0.32}
    assert portfolio.mark_price("YES", snap) == (0.30, "bid")
    assert portfolio.mark_price("NO", snap) == (pytest.approx(0.66), "bid")
    assert portfolio.mark_price("YES", {"best_bid": None, "best_ask": 0.34, "yes_price": 0.32}) == (0.32, "price")
    assert portfolio.mark_price("NO", {"best_bid": 0.3, "best_ask": None, "yes_price": 0.32}) == (
        pytest.approx(0.68), "price")
    assert portfolio.mark_price("YES", None) == (None, "cost")


def test_open_positions_are_marked_to_market(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    b = portfolio.bankroll(eng.db, 100)
    assert b.cash == pytest.approx(98.0) and b.open_exposure == pytest.approx(2.0)
    assert b.market_value == pytest.approx(SHARES * 0.89) and b.unrealized_pnl == pytest.approx(SHARES * 0.89 - 2)
    assert b.equity == pytest.approx(98 + SHARES * 0.89) and b.book_equity == pytest.approx(100.0)
    # the market moves our way: YES ask 0.03, so NO can be sold at 0.97
    _tail(eng).update(bestBid=0.01, bestAsk=0.03)
    eng.clock.now += timedelta(minutes=30)
    eng.collect_markets()
    ov = overview(eng.db, 100)
    assert ov["market_value"] == pytest.approx(SHARES * 0.97) and ov["unrealized_pnl"] == pytest.approx(SHARES * 0.97 - 2)
    assert ov["equity"] == pytest.approx(98 + SHARES * 0.97) and ov["total_pnl"] == pytest.approx(SHARES * 0.97 - 2)
    assert ov["n_open_positions"] == 1 and ov["marked_by"] == {"bid": 1, "price": 0, "cost": 0}
    pos = ov["positions"][0]
    assert pos["side"] == "NO" and pos["mark_price"] == pytest.approx(0.97) and "23°C or higher" in pos["question"]
    snap = portfolio.snapshot(eng.db, 100, "test")
    row = eng.db.rows(select(bankroll_snapshots))[-1]
    assert row["market_value"] == pytest.approx(SHARES * 0.97) and row["equity"] == pytest.approx(snap.equity)
    md = to_markdown(build_report(eng.db, 100))
    assert "## Open positions" in md and "| NO | 2.19 | $2.00 | 0.915 | 0.970 |" in md
    assert "| Realized / unrealized P/L | $0.00 / $0.12 |" in md


def test_settled_positions_leave_the_marks(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    eng.pm.resolved[TAIL] = "NO"
    eng.clock.now += timedelta(days=2)
    eng.settle()
    b = portfolio.bankroll(eng.db, 100)
    assert b.positions == [] and b.unrealized_pnl == 0 and b.equity == pytest.approx(98 + SHARES)


# -- cash can never go negative --------------------------------------------------------------

def _market_row(cfg):
    db = Database(cfg.app.database_url)
    db.insert(markets, id="m1", question="q", event_id="e1", yes_token="y", no_token="n", first_seen=NOW,
              last_seen=NOW, station="EGLC", local_date="2026-09-28", kind="high")
    return db, db.one(select(markets))


def _place(broker, market, fill):
    sig = broker.db.insert(signals, ts=NOW, market_id=market["id"], side="NO", decision="BET")
    return broker.place(signal_id=sig, market=market, side="NO", fill=fill, model_prob=0.9, market_prob=0.8,
                        edge=0.1, ev=0.1)


@pytest.mark.parametrize("fill, problem", [
    (Fill(shares=200, cost=150, fee=0, levels=[]), "only $100"),          # more than the cash
    (Fill(shares=100, cost=99.99, fee=0.02, levels=[]), "only $100"),     # the fee tips it over
    (Fill(shares=math.nan, cost=5, fee=0, levels=[]), "finite"),
    (Fill(shares=10, cost=math.inf, fee=0, levels=[]), "finite"),
    (Fill(shares=0, cost=0, fee=0, levels=[]), "empty"),
    (Fill(shares=-10, cost=-5, fee=0, levels=[]), "empty"),
    (Fill(shares=10, cost=5, fee=-1, levels=[]), "negative fee"),
    (Fill(shares=1, cost=5, fee=0, levels=[]), "outside (0, 1]"),         # $5 a share for a $1 payout
])
def test_broker_refuses_bad_fills_and_logs_why(cfg, fill, problem):
    db, market = _market_row(cfg)
    broker = PaperBroker(db, 100)
    with pytest.raises(BrokerRefused, match=problem.replace("$", r"\$").replace("(", r"\(").replace(")", r"\)")
                       .replace("]", r"\]")):
        _place(broker, market, fill)
    assert db.rows(select(paper_bets)) == [] and portfolio.bankroll(db, 100).cash == 100
    assert db.one(select(system_events).where(system_events.c.component == "paper_broker",
                                              system_events.c.level == "WARNING"))


def test_the_last_dollar_can_be_spent_but_never_more(cfg):
    db, market = _market_row(cfg)
    broker = PaperBroker(db, 100)
    _place(broker, market, Fill(shares=110, cost=99.0, fee=0.99, levels=[]))
    assert portfolio.bankroll(db, 100).cash == pytest.approx(0.01)
    with pytest.raises(BrokerRefused):
        _place(broker, market, Fill(shares=1, cost=0.02, fee=0, levels=[]))
    _place(broker, market, Fill(shares=1, cost=0.01, fee=0, levels=[]))
    assert portfolio.bankroll(db, 100).cash == pytest.approx(0.0, abs=1e-12)
    assert portfolio.bankroll(db, 100).cash >= 0


def test_all_in_sizing_still_never_overdraws(cfg):
    # every cap opened up and a sizer that wants the whole bankroll on each bet
    cfg._data["sizing"]["fraction"] = 1.0
    cfg._data["risk"].update(max_bet_pct=10.0, max_open_exposure_pct=10.0, max_event_exposure_pct=10.0,
                             max_station_day_exposure_pct=10.0)
    eng = make_engine(cfg)
    for _ in range(3):
        eng.run_cycle()
        eng.clock.now += timedelta(minutes=30)
        assert portfolio.bankroll(eng.db, 100).cash >= 0
    bets = eng.db.rows(select(paper_bets))
    assert sum(b["stake"] for b in bets) <= 100 and bets[0]["stake"] == pytest.approx(100, abs=1e-5)
    assert all(row["cash"] >= 0 for row in eng.db.rows(select(bankroll_snapshots)))


def test_a_refused_fill_turns_the_signal_into_no_bet(cfg, monkeypatch):
    # sizing upstream goes wrong: the fill costs ten times the bankroll
    monkeypatch.setattr(rules, "simulate_fill", lambda *a, **k: Fill(shares=2000, cost=1000, fee=0, levels=[]))
    eng = make_engine(cfg)
    eng.run_cycle()
    assert eng.db.rows(select(paper_bets)) == [] and portfolio.bankroll(eng.db, 100).cash == 100
    sig = eng.db.one(select(signals).where(signals.c.market_id == TAIL))
    assert sig["decision"] == "NO_BET" and sig["reason"].startswith("paper broker refused: costs $1000")


# -- correlated exposure: one city, one day ------------------------------------------------

def test_station_day_exposure_counts_high_and_low_together(cfg):
    db, _ = _market_row(cfg)
    for mid, kind, day in (("lo", "low", "2026-09-28"), ("other", "high", "2026-09-29")):
        db.insert(markets, id=mid, question=mid, first_seen=NOW, last_seen=NOW, station="EGLC", local_date=day,
                  kind=kind)
    for mid, stake, status in (("m1", 2.0, "OPEN"), ("lo", 3.0, "OPEN"), ("other", 4.0, "OPEN"), ("lo", 5.0, "WON")):
        db.insert(paper_bets, market_id=mid, side="NO", entry_price=0.9, shares=stake / 0.9, stake=stake,
                  status=status, opened_at=NOW)
    assert portfolio.station_day_exposure(db, "EGLC", "2026-09-28") == pytest.approx(5.0)
    assert portfolio.station_day_exposure(db, "KLGA", "2026-09-28") == 0


def test_city_day_cap_blocks_a_bet_when_the_other_event_is_loaded(cfg):
    db = Database(cfg.app.database_url)
    # $7.50 already open on London's lowest temperature for the same day
    db.insert(markets, id="lo", question="Lowest temperature in London on September 28?", first_seen=NOW,
              last_seen=NOW, station="EGLC", local_date="2026-09-28", kind="low")
    db.insert(paper_bets, market_id="lo", event_id="ev-low", side="NO", entry_price=0.9, shares=7.5 / 0.9, stake=7.5,
              status="OPEN", opened_at=NOW)
    eng = make_engine(cfg, db=db)
    eng.run_cycle()
    assert len(db.rows(select(paper_bets))) == 1                       # nothing new on the high event
    sig = db.one(select(signals).where(signals.c.market_id == TAIL))
    sizing = next(r["value"] for r in sig["rule_results"] if r["rule"] == "sizing_detail")
    assert sizing["binding_cap"] == "station_day_exposure_room"
    assert sizing["caps"]["station_day_exposure_room"] == pytest.approx(0.08 * 100 - 7.5)
    assert "position_size" in sig["reason"]


# -- experiment identity -------------------------------------------------------------------------

def test_first_start_records_the_experiment(cfg, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123def4567890")
    cfg._data["app"]["dashboard_password"] = "hunter2"
    eng = make_engine(cfg)
    make_engine(cfg, db=eng.db)                                        # a restart adds nothing
    rows = eng.db.rows(select(experiments))
    assert len(rows) == 1
    exp = rows[0]
    assert exp["name"] == "paper-100" and exp["initial_bankroll"] == 100.0 and exp["git_ref"] == "abc123def4567890"
    assert exp["started_at"].replace(tzinfo=None) == NOW.replace(tzinfo=None)
    assert exp["config"]["bankroll"]["initial"] == 100.0
    assert exp["config"]["app"]["dashboard_password"] == "<redacted>" and "hunter2" not in json.dumps(exp["config"])
    eng.run_cycle()
    md = to_markdown(build_report(eng.db, 100))
    assert "Experiment: **paper-100** · started 2026-09-27 06:00 UTC · starting bankroll $100.00 · code abc123def456" in md


def test_a_different_bankroll_on_the_same_database_is_refused(cfg):
    eng = make_engine(cfg)
    cfg._data["bankroll"]["initial"] = 1000.0
    with pytest.raises(ValueError, match="started with \\$100.00; the config says \\$1,000.00"):
        make_engine(cfg, db=eng.db)


def test_an_older_database_starts_at_its_first_bankroll_snapshot(cfg):
    db = Database(cfg.app.database_url)
    first = NOW - timedelta(days=4)
    db.insert(bankroll_snapshots, ts=first, cash=100, open_exposure=0, equity=100, realized_pnl=0, reason="cycle")
    exp = ensure_experiment(db, cfg, NOW, env={})
    assert exp["started_at"].replace(tzinfo=None) == first.replace(tzinfo=None) and exp["git_ref"] is None


def test_each_change_of_code_version_is_logged(cfg):
    db = Database(cfg.app.database_url)
    assert record_code_version(db, env={}) is None and db.get_state("code_ref") is None
    record_code_version(db, env={"GITHUB_SHA": "aaaa1111bbbb2222"})
    record_code_version(db, env={"GITHUB_SHA": "aaaa1111bbbb2222"})          # same code: nothing to log
    record_code_version(db, env={"GITHUB_SHA": "cccc3333dddd4444"})
    msgs = [e["message"] for e in db.rows(select(system_events).where(system_events.c.component == "experiment"))]
    assert msgs == ["code version changed: aaaa1111bbbb -> cccc3333dddd"]
    assert record_code_version(db, env={}) == "cccc3333dddd4444"              # a local run keeps the last known


def test_report_shows_the_code_now_running(cfg, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "aaaa1111bbbb2222")
    eng = make_engine(cfg)
    monkeypatch.setenv("GITHUB_SHA", "cccc3333dddd4444")
    make_engine(cfg, db=eng.db)
    md = to_markdown(build_report(eng.db, 100))
    assert "code aaaa1111bbbb (now cccc3333dddd)" in md


def test_the_experiment_workflow_pins_its_bankroll_and_name(tmp_path):
    cfg = load_config(env={"WXBOT_BANKROLL__INITIAL": "100", "WXBOT_EXPERIMENT__NAME": "exp2-100usd",
                           "WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path / 'x.sqlite3'}"})
    assert cfg.bankroll.initial == 100.0 and cfg.experiment.name == "exp2-100usd"


def test_redact_removes_secrets_from_the_config_snapshot():
    out = redact({"app": {"database_url": "postgresql://bot:s3cret@db:5432/wx", "dashboard_password": "pw",
                          "port": 8000},
                  "x": {"api_key": "k", "token_ids": ["a"], "note": "https://example.com/path"}})
    assert out["app"] == {"database_url": "postgresql://<redacted>@db:5432/wx", "dashboard_password": "<redacted>",
                          "port": 8000}
    assert out["x"]["api_key"] == "<redacted>" and out["x"]["note"] == "https://example.com/path"


# -- migration ---------------------------------------------------------------------------------------

def test_migration_adds_m6_columns_to_an_old_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.sqlite3'}"
    db = Database(url)
    with db.engine.begin() as conn:     # tables from before v2 M6
        for table, col in (("paper_bets", "sizing"), ("paper_bets", "market_snapshot"),
                           ("bankroll_snapshots", "market_value"), ("bankroll_snapshots", "unrealized_pnl")):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
        conn.execute(text("DROP TABLE experiments"))
    db = Database(url)
    insp = inspect(db.engine)
    assert {"sizing", "market_snapshot"} <= {c["name"] for c in insp.get_columns("paper_bets")}
    assert {"market_value", "unrealized_pnl"} <= {c["name"] for c in insp.get_columns("bankroll_snapshots")}
    assert "experiments" in insp.get_table_names()
    json.dumps(overview(db, 100), default=str)
