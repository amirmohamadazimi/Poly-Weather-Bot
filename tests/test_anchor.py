"""The market anchor: the model combined with the market price, fitted and
approved walk-forward, and the bot betting only while it beats the price."""
import random
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.conftest import NOW, make_engine
from wxbot.calibration import anchor as anchor_module
from wxbot.calibration.anchor import Anchor, active_anchor, fit_anchor, fit_round, tight_mid, training_set
from wxbot.calibration.fit import day_end
from wxbot.calibration.methods import logit, sigmoid
from wxbot.db import (
    Database, market_anchors, market_resolutions, market_snapshots, markets, paper_bets, predictions, signals,
    system_events,
)
from wxbot.report import build_report, to_markdown

MODEL = "normal-multimodel-v1"


@pytest.fixture
def on(cfg):
    cfg._data["market_anchor"]["enabled"] = True
    return cfg


def _priced_markets(db, n, model_noise, market_noise, seed=1, start=date(2026, 8, 1)):
    """n resolved EGLC markets, ten a day, each priced once 24 h before its day
    ended, with a tight book five minutes before that. The true YES probability
    is sigmoid(x); the model and the market each see x plus their own noise."""
    rng = random.Random(seed)
    mk, res, pr, sn = [], [], [], []
    for i in range(n):
        d = (start + timedelta(days=i // 10)).isoformat()
        end = day_end("EGLC", d)
        x = rng.uniform(-3.0, 1.0)
        outcome = "YES" if rng.random() < sigmoid(x) else "NO"
        model = sigmoid(x + rng.gauss(0, model_noise))
        mid = min(0.97, max(0.03, sigmoid(x + rng.gauss(0, market_noise))))
        ts = end - timedelta(hours=24) + timedelta(minutes=i % 10)
        m = f"m{i}"
        mk.append(dict(id=m, question=m, station="EGLC", local_date=d, first_seen=NOW, last_seen=NOW,
                       resolved_outcome=outcome))
        res.append(dict(market_id=m, resolved_at=end + timedelta(hours=12), outcome=outcome))
        pr.append(dict(ts=ts, market_id=m, model_version=MODEL, role="production", p_yes=model, lead_days=1))
        sn.append(dict(market_id=m, ts=ts - timedelta(minutes=5), best_bid=mid - 0.01, best_ask=mid + 0.01,
                       liquidity=5000.0))
    with db.engine.begin() as conn:
        for table, rows in ((markets, mk), (market_resolutions, res), (predictions, pr), (market_snapshots, sn)):
            conn.execute(table.insert(), rows)
    return datetime.combine(start + timedelta(days=n // 10 + 3), datetime.min.time(), UTC)


# -- the fit --------------------------------------------------------------------------

def test_tight_mid_needs_both_sides_and_a_narrow_spread():
    assert tight_mid(0.24, 0.26, 0.05) == pytest.approx(0.25)
    assert tight_mid(0.20, 0.25, 0.05) == pytest.approx(0.225)      # exactly max_spread is tight
    assert tight_mid(0.20, 0.30, 0.05) is None
    assert tight_mid(None, 0.30, 0.05) is None and tight_mid(0.0, 0.02, 0.05) is None
    assert tight_mid(0.99, 1.0, 0.05) is None and tight_mid(0.3, 0.3, 0.05) is None


def test_fit_gives_no_weight_to_a_model_that_knows_nothing():
    rng = random.Random(2)
    xs = [rng.uniform(-3, 1) for _ in range(3000)]
    ys = [int(rng.random() < sigmoid(x)) for x in xs]
    market = [sigmoid(x) for x in xs]
    model = [sigmoid(rng.uniform(-3, 1)) for _ in xs]             # noise
    fit = fit_anchor(model, market, ys)
    assert fit["a"] == pytest.approx(0.0, abs=0.1) and fit["b"] == pytest.approx(1.0, abs=0.15)


def test_fit_weights_a_model_that_knows_what_the_price_does_not():
    rng = random.Random(3)
    xs = [rng.uniform(-3, 1) for _ in range(3000)]
    ys = [int(rng.random() < sigmoid(x)) for x in xs]
    model = [sigmoid(x) for x in xs]
    market = [sigmoid(x + rng.gauss(0, 1.5)) for x in xs]          # a noisy price
    fit = fit_anchor(model, market, ys)
    assert fit["a"] > 0.5 and fit["a"] > fit["b"]


def test_anchor_combines_and_clamps():
    a = Anchor("anchor-x", {"a": 0.0, "b": 1.0, "c": 0.0})
    assert a(0.9, 0.3) == pytest.approx(0.3)                         # the price alone
    b = Anchor("anchor-y", {"a": 0.5, "b": 0.5, "c": 0.0})
    assert b(0.8, 0.2) == pytest.approx(sigmoid(0.5 * logit(0.8) + 0.5 * logit(0.2)))
    assert Anchor("anchor-z", {"a": 0.0, "b": 1.0, "c": -20.0})(0.5, 0.5) == 0.01


# -- training data ----------------------------------------------------------------------

def _market(db, mid, outcome, resolved_at, local_date="2026-09-28"):
    db.insert(markets, id=mid, question=mid, station="EGLC", local_date=local_date, first_seen=NOW, last_seen=NOW,
              resolved_outcome=outcome)
    if resolved_at is not None:
        db.insert(market_resolutions, market_id=mid, resolved_at=resolved_at, outcome=outcome)


def _book(db, mid, ts, bid, ask, liquidity=5000.0):
    db.insert(market_snapshots, market_id=mid, ts=ts, best_bid=bid, best_ask=ask, liquidity=liquidity)


def _pred(db, mid, ts, p, role="production"):
    db.insert(predictions, ts=ts, market_id=mid, model_version=MODEL, role=role, p_yes=p, lead_days=1)


def test_training_set_pairs_each_decision_with_the_book_it_saw(on):
    db = Database(on.app.database_url)
    end = day_end("EGLC", "2026-09-28")
    decided = end - timedelta(hours=19)
    _market(db, "A", "YES", end + timedelta(hours=12))
    _book(db, "A", decided - timedelta(hours=1), 0.39, 0.41)
    _book(db, "A", decided + timedelta(minutes=30), 0.79, 0.81)      # after the decision: not what it saw
    _pred(db, "A", end - timedelta(hours=40), 0.2)
    _pred(db, "A", decided, 0.3)                                      # the decision: latest 18+ h ahead
    _pred(db, "A", end - timedelta(hours=17), 0.9)                    # too close to the end of the day
    _pred(db, "A", decided, 0.95, role="shadow")
    for name, bid, ask, liq in (("W", 0.20, 0.40, 5000.0),            # wide book
                                ("L", 0.39, 0.41, 50.0),               # illiquid
                                ("Z", 0.0, 0.02, 5000.0)):             # no bid
        _market(db, name, "NO", end + timedelta(hours=12))
        _book(db, name, decided - timedelta(hours=1), bid, ask, liq)
        _pred(db, name, decided, 0.3)
    _market(db, "E", "NO", end + timedelta(hours=12))                 # no book before the decision
    _book(db, "E", decided + timedelta(hours=1), 0.39, 0.41)
    _pred(db, "E", decided, 0.3)
    _market(db, "U", "NO", None)                                      # never resolved
    _book(db, "U", decided - timedelta(hours=1), 0.39, 0.41)
    _pred(db, "U", decided, 0.3)
    fit_time = datetime(2026, 10, 1, tzinfo=UTC)
    assert training_set(db, on, MODEL, fit_time) == [(decided, 0.3, pytest.approx(0.40), 1)]
    assert training_set(db, on, MODEL, end + timedelta(hours=1)) == []   # A's result was not known yet


# -- approval ------------------------------------------------------------------------------

def test_approved_when_the_model_adds_to_the_price(on):
    db = Database(on.app.database_url)
    fit_time = _priced_markets(db, 500, model_noise=0.2, market_noise=1.5)
    row = fit_round(db, on, MODEL, fit_time)
    assert row["approved"] and row["n"] == 500 and row["n_train"] == 350 and row["n_holdout"] == 150
    assert row["train_to"] <= row["holdout_from"]
    assert row["log_loss_anchored"] < row["log_loss_market"] and row["brier_anchored"] < row["brier_market"]
    assert row["params"]["a"] > 0.3 and row["improvement_confidence"] >= 0.95
    anchor, version = active_anchor(db, on, MODEL, fit_time)
    assert anchor is not None and version == row["version"] == anchor.version


def test_not_approved_when_the_price_already_knows(on):
    db = Database(on.app.database_url)
    fit_time = _priced_markets(db, 500, model_noise=1.5, market_noise=0.05)
    row = fit_round(db, on, MODEL, fit_time)
    assert not row["approved"] and abs(row["params"]["a"]) < 0.2
    assert row["log_loss_model"] > row["log_loss_market"]
    anchor, why = active_anchor(db, on, MODEL, fit_time)
    assert anchor is None and why == row["reason"]


def test_needs_min_markets(on):
    db = Database(on.app.database_url)
    fit_time = _priced_markets(db, 100, model_noise=0.2, market_noise=1.5)
    row = fit_round(db, on, MODEL, fit_time)
    assert not row["approved"] and row["params"] is None
    assert row["reason"] == "only 100 resolved markets with a tight book (need 300)"


def test_rejects_a_gain_that_could_be_luck(on, monkeypatch):
    db = Database(on.app.database_url)
    fit_time = _priced_markets(db, 500, model_noise=0.2, market_noise=1.5)
    monkeypatch.setattr(anchor_module, "gain_confidence", lambda *a, **k: 0.9)
    row = fit_round(db, on, MODEL, fit_time)
    assert not row["approved"]
    assert row["reason"] == "gain over the market price not reliable: 90% of bootstrap resamples (need 95%)"


def test_newest_fit_decides_and_old_fits_are_kept(on):
    db = Database(on.app.database_url)
    t1, t2 = NOW - timedelta(days=2), NOW - timedelta(days=1)
    db.insert(market_anchors, version="anchor-1", model_version=MODEL, fitted_at=t1,
              params={"a": 0.5, "b": 0.5, "c": 0.0}, approved=True)
    db.insert(market_anchors, version="anchor-2", model_version=MODEL, fitted_at=t2, approved=False,
              reason="the model adds nothing")
    assert active_anchor(db, on, MODEL, t1 + timedelta(hours=1))[1] == "anchor-1"
    assert active_anchor(db, on, MODEL, NOW) == (None, "the model adds nothing")
    assert active_anchor(db, on, "other-model-v1", NOW) == (None, "not fitted yet")
    assert active_anchor(db, on, MODEL, t1 - timedelta(hours=1)) == (None, "not fitted yet")
    assert len(db.rows(select(market_anchors))) == 2


# -- the engine ------------------------------------------------------------------------------

def _rule(sig, name):
    return next((r for r in sig["rule_results"] if r["rule"] == name), None)


def test_without_an_approved_anchor_no_bet_is_placed(on):
    eng = make_engine(on)
    summary = eng.run_cycle()
    assert summary["market_anchor"] == {"n": 0, "approved": False}
    sigs = eng.db.rows(select(signals))
    assert sigs and all(s["decision"] == "NO_BET" for s in sigs)
    checks = [_rule(s, "market_anchor") for s in sigs]
    assert all(c and not c["passed"] and c["value"].startswith("no approved anchor: only 0") for c in checks)
    assert eng.db.rows(select(paper_bets)) == []
    assert eng.db.one(select(system_events).where(system_events.c.component == "market_anchor"))
    assert eng.run_cycle()["market_anchor"] == {"skipped": True}     # refit at most every refit_hours
    md = to_markdown(build_report(eng.db, on.bankroll.initial, NOW))
    assert "## Market anchor (latest fit)" in md and "New bets are paused" in md


def test_an_approved_anchor_sets_the_probability_the_rules_use(on):
    db = Database(on.app.database_url)
    # the market price pushed well down: every bucket's YES is far less likely than its mid says
    db.insert(market_anchors, version="anchor-test", model_version=MODEL, fitted_at=NOW - timedelta(hours=1),
              params={"a": 0.0, "b": 1.0, "c": -3.0}, approved=True, reason="test")
    db.set_state("last_anchor_fit", (NOW - timedelta(hours=1)).isoformat())
    on._data["risk"].update(max_event_exposure_pct=1.0, max_station_day_exposure_pct=1.0)
    eng = make_engine(on, db=db)
    assert eng.run_cycle()["market_anchor"] == {"skipped": True}
    bets = db.rows(select(paper_bets))
    assert bets and all(b["side"] == "NO" for b in bets)
    for b in bets:
        sig = db.one(select(signals).where(signals.c.id == b["signal_id"]))
        probs = sig["rule_results"][0]["value"]
        snap = db.one(select(market_snapshots).where(market_snapshots.c.market_id == b["market_id"])
                      .order_by(market_snapshots.c.id.desc()).limit(1))
        mid = (snap["best_bid"] + snap["best_ask"]) / 2
        expected = max(0.01, sigmoid(logit(mid) - 3.0))
        assert probs["anchored"] == pytest.approx(expected, abs=1e-6) and probs["calibrator"] == "anchor-test"
        assert b["confidence"] == pytest.approx(1 - expected, abs=1e-6)
        check = _rule(sig, "market_anchor")
        assert check["passed"] and check["value"] == "anchor-test"
    # a bucket whose book has no bid is not priced, so it cannot be bet on
    wide = [s for s in db.rows(select(signals)) if not _rule(s, "market_anchor")["passed"]]
    assert wide and all(_rule(s, "market_anchor")["value"].startswith("no tight book") for s in wide)
    assert not any(b["signal_id"] in {s["id"] for s in wide} for b in bets)


def test_anchor_off_keeps_the_model_only_rules(cfg):
    eng = make_engine(cfg)
    assert eng.run_cycle()["market_anchor"] == {"enabled": False}
    sigs = eng.db.rows(select(signals))
    assert sigs and all(_rule(s, "market_anchor") is None for s in sigs)
    assert all("anchored" not in s["rule_results"][0]["value"] for s in sigs)
    assert len(eng.db.rows(select(paper_bets))) == 1


def test_turned_off_after_fits_it_bets_on_the_model_and_the_report_says_so(cfg):
    db = Database(cfg.app.database_url)
    db.insert(market_anchors, version="anchor-old", model_version=MODEL, fitted_at=NOW - timedelta(days=1), n=694,
              n_train=486, n_holdout=208, params={"a": 0.06, "b": 1.06, "c": 0.11}, approved=False,
              reason="the model adds nothing to the market price")
    eng = make_engine(cfg, db=db)
    assert eng.run_cycle()["market_anchor"] == {"enabled": False}
    sigs = db.rows(select(signals))
    assert sigs and all(_rule(s, "market_anchor") is None for s in sigs)
    assert len(db.rows(select(paper_bets))) == 1                   # the unapproved fit no longer stops it
    assert anchor_module.latest(db)["version"] == "anchor-old"     # and is not refitted while the check is off
    rep = build_report(db, cfg.bankroll.initial, NOW, cfg=cfg)
    assert not any("paused" in v for v in rep["verdict"])
    assert any(v.startswith("The market check is off") and "was not approved: the model adds nothing" in v
               for v in rep["verdict"])
    md = to_markdown(rep)
    assert "## Market anchor (off, last fit)" in md and "no longer refitted" in md
    assert "## Market anchor (latest fit)" not in md and "The bot bets only on the model combined" not in md
