"""v2 M14: the research report. It answers whether the experiment found positive
EV, and is built so a positive P/L alone cannot pass: five checks with their
numbers, intervals that resample whole days and events, the market compared
only where its price was a real forecast, and the same report from the same
database every time."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import NOW, make_engine
from wxbot import research
from wxbot.db import (Database, bankroll_snapshots, experiments, market_resolutions, markets, metadata,
                      prediction_outcomes, predictions, signals)
from wxbot.evaluation.metrics import log_loss, market_yes, prediction_calibration, resolved_rows
from wxbot.web.app import create_app

TAIL = "1010"   # the market the bot bets on in the fake event (NO at 0.91)
LIQUID = [{"rule": "liquidity", "passed": True, "value": 2500.0, "threshold": ">= 300"}]
THIN = [{"rule": "liquidity", "passed": False, "value": 15.0, "threshold": ">= 300"}]


def _market(db, mid, event="e", day="2026-09-28"):
    db.insert(markets, id=mid, event_id=event, question=f"q{mid}", city="London", station="EGLC", kind="high",
              local_date=day, unit="C", bucket_lo=18.0, bucket_hi=18.0, first_seen=NOW, last_seen=NOW)


def _ledger(db, mid, p, y, market, rules, event="e"):
    """A resolved market in the learning ledger, with the signal its market price came from."""
    _market(db, mid, event)
    sid = db.insert(signals, ts=NOW, market_id=mid, side="YES", market_prob=market, decision="NO_BET",
                    rule_results=rules)
    db.insert(prediction_outcomes, market_id=mid, signal_id=sid, decision_time=NOW, event_id=event, city="London",
              station="EGLC", kind="high", local_date="2026-09-28", lead_days=1, unit="C", bucket_lo=18.0,
              bucket_hi=18.0, p_yes=p, p_used=p, market_yes=market, liquidity=rules[0]["value"],
              outcome="YES" if y else "NO", y=y, model_version="m1", params_version="ps1",
              calibrator_version="identity")


def _counts(db) -> dict:
    with db.engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar() for t in metadata.sorted_tables}


# -- the market as a benchmark ----------------------------------------------------------------

def test_the_market_price_counts_only_where_the_market_was_liquid():
    assert market_yes({"side": "YES", "market_prob": 0.3, "rule_results": LIQUID}) == 0.3
    assert market_yes({"side": "NO", "market_prob": 0.3, "rule_results": LIQUID}) == pytest.approx(0.7)
    assert market_yes({"side": "YES", "market_prob": 0.4, "rule_results": THIN}) is None
    assert market_yes({"side": "YES", "market_prob": 0.4, "rule_results": None}) is None
    assert market_yes({"side": "YES", "market_prob": None, "rule_results": LIQUID}) is None
    assert market_yes(None) is None


def test_a_thin_markets_placeholder_price_does_not_make_the_model_look_good(cfg):
    db = Database(cfg.app.database_url)
    for i in range(10):     # liquid: the market (90%) knew better than the model (60%)
        _ledger(db, f"l{i}", 0.6, 1, 0.9, LIQUID, event=f"e{i}")
    for i in range(30):     # thin: a placeholder mid of 0.40 on markets that resolved NO
        _ledger(db, f"t{i}", 0.02, 0, 0.4, THIN, event=f"t{i // 3}")
    rows = research.ledger(db, NOW + timedelta(days=1))
    p = research.prediction_stats(rows)
    assert p["n"] == 40 and p["n_liquid"] == 10
    assert p["log_loss_market"] < p["log_loss_model_liquid"] and p["skill"] < 0
    vm = research.versus_market(rows)
    assert vm["clusters"] == 10 and vm["lo"] > 0          # reliably worse than the market where it counts
    # counted naively, the placeholders would have made the model look better
    ys = [r["y"] for r in rows]
    assert log_loss([r["p_used"] for r in rows], ys) < log_loss([r["market_yes"] for r in rows], ys)


def test_the_dashboard_and_report_compare_on_liquid_markets_only(cfg):
    db = Database(cfg.app.database_url)
    for mid, rules, p, y in (("A", LIQUID, 0.8, 1), ("B", THIN, 0.1, 0)):
        _market(db, mid)
        db.insert(market_resolutions, market_id=mid, resolved_at=NOW + timedelta(days=2), outcome="YES" if y else "NO")
        pid = db.insert(predictions, ts=NOW, market_id=mid, model_version="normal-multimodel-v1", role="production",
                        p_yes=p, lead_days=1)
        db.insert(signals, ts=NOW, prediction_id=pid, market_id=mid, side="YES", market_prob=0.4, decision="NO_BET",
                  rule_results=rules)
    assert {x["market_id"]: x["market_yes"] for x in resolved_rows(db)} == {"A": 0.4, "B": None}
    cal = prediction_calibration(db)
    assert cal["n"] == 2 and cal["n_market"] == 1
    assert cal["brier_market"] == pytest.approx(0.36) and cal["brier_model_on_market"] == pytest.approx(0.04)


# -- statistics -------------------------------------------------------------------------------

def test_intervals_resample_whole_clusters_and_repeat_exactly():
    items = [{"day": i % 10, "pnl": 1.0 if i % 3 else -2.0, "stake": 1.0} for i in range(100)]
    ci = research.cluster_ratio_ci(items, lambda r: r["day"], lambda r: r["pnl"], lambda r: r["stake"])
    assert ci["clusters"] == 10 and ci["n"] == 100
    assert ci["lo"] <= ci["value"] <= ci["hi"]
    assert ci == research.cluster_ratio_ci(items, lambda r: r["day"], lambda r: r["pnl"], lambda r: r["stake"])
    few = research.cluster_ratio_ci(items[:4], lambda r: r["day"], lambda r: r["pnl"], lambda r: r["stake"])
    assert few["clusters"] == 4 and few["lo"] is None and few["hi"] is None


def test_reliability_flags_over_and_underconfidence_on_both_sides():
    rows = ([{"p_used": 0.9, "y": int(i < 70)} for i in range(100)]          # 90% predicted, 70% happened
            + [{"p_used": 0.05, "y": int(i < 15)} for i in range(100)]       # 5% predicted, 15% happened
            + [{"p_used": 0.75, "y": int(i < 90)} for i in range(100)]       # 75% predicted, 90% happened
            + [{"p_used": 0.35, "y": int(i < 36)} for i in range(100)])      # about right
    reading = {b["bin"]: b["reading"] for b in research.reliability(rows)}
    assert reading == {"0.0-0.1": "overconfident", "0.3-0.4": "", "0.7-0.8": "underconfident",
                       "0.9-1.0": "overconfident"}


def _bet(i, pnl, day, hours=0.0, stake=2.0):
    return {"id": i, "settled": True, "won": pnl > 0, "status": "WON" if pnl > 0 else "LOST", "pnl": pnl,
            "stake": stake, "decided_at": NOW + timedelta(hours=hours), "local_date": day, "city": "London",
            "kind": "high", "bucket_label": "18°C", "side": "NO", "entry_price": 0.8}


def test_concentration_drops_the_best_bets_and_splits_the_window():
    rows = ([_bet(i, 10.0, "2026-09-28") for i in range(5)]                  # five big wins on day one
            + [_bet(10 + i, -1.0, f"2026-10-{1 + i % 9:02d}", hours=24 * (1 + i % 9)) for i in range(20)])
    c = research.concentration(rows, NOW, NOW + timedelta(days=10))
    assert c["total_pnl"] == 30.0 and c["top_pnl"] == 50.0 and c["without_top_pnl"] == -20.0
    assert [h["bets"] for h in c["halves"]] == [15, 10] and c["halves"][1]["pnl"] == -10.0
    assert [w["week"] for w in c["weeks"]] == [1, 2]
    assert c["roi_by_day"]["clusters"] == 10


# -- the verdict ------------------------------------------------------------------------------

def _verdict(settled=250, roi=(0.05, 0.01, 0.09), vm=(-0.02, -0.03, -0.01), z=0.5, without_top=5.0,
             halves=(3.0, 4.0)):
    b = {"settled": settled, "z": z, "win_rate": 0.85, "expected_win_rate": 0.86}
    p = {"log_loss_model_liquid": 0.20, "log_loss_market": 0.22, "n_liquid": 500}
    v = {"value": vm[0], "lo": vm[1], "hi": vm[2], "clusters": 80}
    conc = {"roi_by_day": {"value": roi[0], "lo": roi[1], "hi": roi[2], "clusters": 30}, "total_pnl": 20.0,
            "without_top_pnl": without_top, "halves": [{"bets": 100, "pnl": h} for h in halves]}
    return research.verdict(b, p, v, conc)


def test_only_every_check_passing_supports_positive_ev():
    v = _verdict()
    assert v["passed"] == 5 and v["conclusion"].startswith("SUPPORTED")


@pytest.mark.parametrize("kwargs", [
    {"settled": 31},                     # a profit on too few bets
    {"without_top": -1.0},               # a profit that rests on a few bets
    {"halves": (8.0, -1.0)},             # a profit from the first half only
    {"z": -2.4},                         # bets won less often than predicted
    {"vm": (-0.01, -0.03, 0.01)},        # not reliably better than the market
    {"roi": (0.05, -0.02, 0.12)},        # returns whose interval includes zero
])
def test_a_positive_pnl_alone_is_not_success(kwargs):
    v = _verdict(**kwargs)
    assert v["passed"] == 4 and v["conclusion"].startswith("INCONCLUSIVE")


def test_losses_or_a_better_market_mean_not_supported():
    lost = _verdict(roi=(-0.2, -0.3, -0.1), halves=(-1.0, -2.0), without_top=-10.0)
    assert lost["conclusion"].startswith("NOT SUPPORTED: the strategy lost money")
    beaten = _verdict(vm=(0.04, 0.02, 0.05))                     # profitable, but the market predicted better
    assert beaten["conclusion"].startswith("NOT SUPPORTED: the model's probabilities were reliably worse")


# -- the report over an experiment --------------------------------------------------------------

def test_the_report_follows_the_experiment_from_interim_to_final(cfg):
    cfg._data["experiment"]["days"] = 1
    eng = make_engine(cfg)
    eng.run_cycle()
    before = _counts(eng.db)
    rep = research.build(eng.db, 100, NOW + timedelta(hours=1))
    assert _counts(eng.db) == before                             # building it writes nothing
    assert rep["stage"] == "interim" and rep["performance"]["n"] == 1 and rep["performance"]["open"] == 1
    md = research.to_markdown(rep)
    for heading in ("# Research report: ", "## Verdict", "## Performance", "## Predictions", "## Was the edge stable?",
                    "## Market types", "## Locations", "## Weather variables", "## Over- and underconfidence",
                    "## Largest errors", "## Model versions", "## Operation", "## How this was computed"):
        assert heading in md, heading
    assert "**Interim** (day 1 of 1)" in md and "PAPER TRADING" in md and "**INCONCLUSIVE: " in md
    assert md == research.to_markdown(research.build(eng.db, 100, NOW + timedelta(hours=1)))   # reproducible

    eng.clock.now = NOW + timedelta(days=1, minutes=1)           # the end: no new bets, the open one still to settle
    eng.run_cycle()
    assert research.build(eng.db, 100, eng.clock.now)["stage"] == "preliminary"
    eng.pm.resolved[TAIL] = "NO"
    eng.clock.now = NOW + timedelta(days=2)
    eng.run_cycle()
    eng.run_cycle()
    rep = research.build(eng.db, 100, eng.clock.now)
    assert rep["stage"] == "final" and rep["performance"]["settled"] == 1 and rep["performance"]["won"] == 1
    assert "**Final** (the experiment is complete" in research.to_markdown(rep)


def test_the_window_counts_the_first_cycle_and_ends_at_the_planned_end(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    assert research.bets(eng.db, NOW - timedelta(minutes=1)) == []          # decided after this end
    bet = research.bets(eng.db, NOW + timedelta(days=1))[0]
    # a database from before experiments were recorded starts at its first snapshot, which the first
    # cycle's decisions come just before: they still count
    with eng.db.engine.begin() as conn:
        conn.execute(experiments.delete())
        conn.execute(bankroll_snapshots.update().values(ts=NOW + timedelta(seconds=30)))
    rep = research.build(eng.db, 100, NOW + timedelta(hours=1))
    assert rep["performance"]["n"] == 1 and rep["window"]["from"] == research._utc(bet["decided_at"]).isoformat()
    assert rep["experiment"] is None


def test_command_and_dashboard(cfg, monkeypatch, capsys):
    import main
    eng = make_engine(cfg)
    eng.run_cycle()
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", cfg.app.database_url)
    assert main.main(["research"]) == 0
    assert capsys.readouterr().out.startswith("# Research report: ")
    api = TestClient(create_app(cfg, eng.db))
    assert api.get("/api/research").json()["verdict"]["checks"][0]["check"] == "Enough settled bets"
    assert api.get("/export/research.md").text.startswith("# Research report: ")
    assert 'href="/export/research.md"' in api.get("/").text
