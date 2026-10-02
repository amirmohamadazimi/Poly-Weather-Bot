"""v2 M8: historical market backtest. Collection, the no-look-ahead replay,
scores against the market, and the betting rules on historical prices."""
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.conftest import market_description
from wxbot.backtesting import replay as replay_module
from wxbot.backtesting import run_market_backtest
from wxbot.backtesting.evaluate import bankroll, cluster_mean_ci, flat_stake, scores
from wxbot.backtesting.replay import BiasFits, decision_time, price_at, walk_forward_calibration
from wxbot.backtesting.report import to_markdown
from wxbot.config import load_config
from wxbot.data import polymarket as pm_module
from wxbot.data.polymarket import PolymarketClient
from wxbot.db import Database, backtest_predictions, backtest_runs, historical_forecasts, weather_observations

UTC = timezone.utc
DAYS = ["2026-09-20", "2026-09-21", "2026-09-22"]
LABELS = ["12°C or below"] + [f"{x}°C" for x in range(13, 22)] + ["22°C or higher"]
JUMP_HOUR = 10   # prices jump to the result at 10:00 UTC on the market day, after every decision


def bt_cfg(tmp_path, **extra):
    env = {"WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path / 'app.sqlite3'}",
           "WXBOT_BACKTEST__DATABASE_URL": f"sqlite:///{tmp_path / 'bt.sqlite3'}",
           "WXBOT_BACKTEST__TRAIN_DAYS": "30", "WXBOT_BACKTEST__CLIMATOLOGY_YEARS": "2",
           "WXBOT_BACKTEST__BOOTSTRAP": "200", **extra}
    return load_config(env=env)


def observed(d: date) -> float:
    return 17.0 + ((d.toordinal() * 3) % 5 - 2) * 0.5


def whole(x: float) -> int:
    return math.floor(x + 0.5)


def winner(local_date: str) -> str:
    v = whole(observed(date.fromisoformat(local_date)))
    return "12°C or below" if v <= 12 else "22°C or higher" if v >= 22 else f"{v}°C"


def london_closed_event(local_date: str, created: str) -> dict:
    d = date.fromisoformat(local_date)
    month = d.strftime("%B")
    markets = []
    for i, label in enumerate(LABELS):
        mid = f"{d.day}{i:02d}"
        won = label == winner(local_date)
        markets.append({
            "id": mid, "question": f"Will the highest temperature in London be {label} on {month} {d.day}?",
            "groupItemTitle": label, "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["1", "0"] if won else ["0", "1"]),
            "clobTokenIds": json.dumps([f"y{mid}", f"n{mid}"]), "liquidityNum": 1000, "volumeNum": 5000,
            "closed": True, "endDate": f"{local_date}T12:00:00Z", "createdAt": created,
            "closedTime": f"{(d + timedelta(days=1)).isoformat()} 00:30:00+00",
            "resolutionSource": "https://www.weather.gov/wrh/timeseries?site=EGLC",
            "description": market_description(day=d.strftime("%-d %b '%y")),
        })
    return {"id": f"ev{d.day}", "title": f"Highest temperature in London on {month} {d.day}?",
            "slug": f"london-{local_date}", "endDate": f"{local_date}T12:00:00Z", "markets": markets}


def atlantis_event() -> dict:
    ev = london_closed_event("2026-09-20", "2026-09-17T06:00:00Z")
    ev.update(id="evA", title="Highest temperature in Atlantis on September 20?")
    for m in ev["markets"]:
        m["id"] = "9" + m["id"]
        m["resolutionSource"] = "https://www.wunderground.com/history/daily/xx/atlantis/ZZZZ"
        m["description"] = market_description(station="Atlantis Intl", source="Wunderground",
                                              link=m["resolutionSource"], day="20 Sep '26")
    return ev


class FakeClosed:
    """Closed events and hourly price histories, offline."""

    def __init__(self):
        self.events = [london_closed_event("2026-09-20", "2026-09-17T06:00:00Z"),
                       london_closed_event("2026-09-21", "2026-09-18T06:00:00Z"),
                       # listed after the lead-3 decision for its day (2026-09-20 07:00 UTC)
                       london_closed_event("2026-09-22", "2026-09-20T12:00:00Z"),
                       atlantis_event()]
        self.history_requests = []
        self.empty = {"y2105"}   # one market that never traded

    def list_closed_events(self, start, end):
        return self.events

    def get_price_history(self, token_id, start, end, fidelity_min=60):
        self.history_requests.append(token_id)
        if token_id in self.empty:
            return []
        mid = token_id[1:]
        m = next(m for ev in self.events for m in ev["markets"] if m["id"] == mid)
        won = json.loads(m["outcomePrices"])[0] == "1"
        jump = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00")).replace(hour=JUMP_HOUR)
        t = start.replace(minute=0, second=0, microsecond=0)
        out = []
        while t <= end:
            out.append((t, (0.99 if won else 0.01) if t >= jump else 0.09))
            t += timedelta(hours=1)
        return out


class FakePrevRuns:
    source = "fake-previous-runs"
    models = ["m1", "m2", "m3"]

    def __init__(self):
        self.requests = []

    def fetch(self, station, start, end, leads):
        self.requests.append((station.code, start, end))
        out = {}
        for lead in leads:
            out[lead] = {"high": {}, "low": {}}
            d = start
            while d <= end:
                err = 1.0 + 0.1 * lead + ((d.toordinal() * 7) % 3 - 1) * 0.3
                vals = {m: observed(d) + err + (i - 1) * 0.2 for i, m in enumerate(self.models)}
                out[lead]["high"][d.isoformat()] = vals
                out[lead]["low"][d.isoformat()] = {m: v - 8 for m, v in vals.items()}
                d += timedelta(days=1)
        return out


class FakeIEM:
    source = "fake-iem"

    def __init__(self):
        self.requests = []

    def fetch(self, station, start, end):
        self.requests.append((station.code, start, end))
        out = {"high": {}, "low": {}}
        d = start
        while d <= end:
            out["high"][d.isoformat()] = (observed(d), 24)
            out["low"][d.isoformat()] = (observed(d) - 8, 24)
            d += timedelta(days=1)
        return out


def run(cfg, db, sources=None, offline=False):
    srcs = None if offline else (sources or (FakeClosed(), FakePrevRuns(), FakeIEM()))
    return run_market_backtest(cfg, db, date(2026, 9, 20), date(2026, 9, 22), sources=srcs,
                               now=datetime(2026, 10, 2, 12, tzinfo=UTC))


# -- decision times and prices -------------------------------------------------------

def test_decision_time_is_when_the_forecast_was_surely_available():
    # London is on BST: 20 Sep ends at 23:00 UTC
    assert decision_time("EGLC", "2026-09-20", 1, 8) == datetime(2026, 9, 20, 7, tzinfo=UTC)
    assert decision_time("EGLC", "2026-09-20", 3, 8) == datetime(2026, 9, 18, 7, tzinfo=UTC)
    # New York on EDT: 20 Sep ends at 04:00 UTC on the 21st
    assert decision_time("KLGA", "2026-09-20", 2, 8) == datetime(2026, 9, 19, 12, tzinfo=UTC)


def test_price_at_takes_the_last_point_at_or_before():
    t0 = datetime(2026, 9, 20, 5, tzinfo=UTC)
    series = ([t0, t0 + timedelta(hours=1), t0 + timedelta(hours=3)], [0.1, 0.2, 0.9])
    assert price_at(series, t0 - timedelta(minutes=1)) is None
    assert price_at(series, t0 + timedelta(hours=1)) == (t0 + timedelta(hours=1), 0.2)
    assert price_at(series, t0 + timedelta(hours=2, minutes=59)) == (t0 + timedelta(hours=1), 0.2)
    assert price_at(None, t0) is None


def test_closed_events_listing(monkeypatch):
    calls = []

    def fake_get_json(session, url, params=None):
        calls.append(params)
        page = [{"id": "old", "endDate": "2026-09-01T12:00:00Z"},
                {"id": "in", "endDate": "2026-09-21T12:00:00Z"},
                {"id": "late", "endDate": "2026-09-30T12:00:00Z"}]
        return page if len(calls) == 1 else [{"id": "never", "endDate": "2026-09-21T12:00:00Z"}]

    monkeypatch.setattr(pm_module, "get_json", fake_get_json)
    events = PolymarketClient(session=object()).list_closed_events(date(2026, 9, 20), date(2026, 9, 22), page_size=3)
    assert [e["id"] for e in events] == ["in"]
    assert len(calls) == 1   # an event past the window ends the paging, even if end_date_max was ignored
    assert calls[0]["closed"] == "true" and calls[0]["tag_slug"] == "daily-temperature"
    assert calls[0]["end_date_min"] == "2026-09-19T00:00:00Z" and calls[0]["end_date_max"] == "2026-09-24T00:00:00Z"


# -- end to end ----------------------------------------------------------------------

def test_market_backtest_end_to_end(tmp_path):
    cfg = bt_cfg(tmp_path)
    db = Database(cfg.backtest.database_url)
    sources = (FakeClosed(), FakePrevRuns(), FakeIEM())
    rep = run(cfg, db, sources)

    # every listed market is counted, including the ones that could not be replayed
    assert rep["data"]["events"] == 4 and rep["data"]["markets"] == 44
    assert rep["data"]["not_tradeable"] == 11 and rep["data"]["tradeable_resolved_no_prices"] == 1
    skipped = rep["replay"]["skipped"]
    assert skipped["market not listed yet at the decision time"] == 11   # 22 Sep at lead 3
    assert skipped["no price at or before the decision time"] == 3       # the market that never traded
    assert rep["replay"]["rows"] == 3 * 11 * 3 - 11 - 3

    rows = db.rows(select(backtest_predictions))
    assert len(rows) == rep["replay"]["rows"]
    for r in rows:
        assert r["price_time"] <= r["decision_time"]
        assert r["market_prob"] == 0.09            # never the post-jump price
        assert r["bias_n"] >= 20 and r["bias_c"] == pytest.approx(1.0 + 0.1 * r["lead_days"], abs=0.15)
        assert r["p_climatology"] is not None and r["p_raw_forecast"] is not None
        assert r["calibrator_version"] == "identity"   # far fewer than calibration.min_samples results
        assert r["p_calibrated"] == r["p_model"]
    assert {r["decision"] for r in rows} <= {"BET", "NO_BET", "HELD"}

    # the model knew the weather; the market priced every bucket at 9%
    by = {e["source"]: e for e in rep["scores"]["sources"]}
    assert by["model"]["brier"] < by["raw_forecast"]["brier"] < by["market"]["brier"]
    assert by["model"]["brier_minus_market"]["mean"] < 0
    assert rep["flat_stake"]["bets"] > 0 and rep["flat_stake"]["pnl"] > 0
    assert rep["bankroll"]["bets"] > 0 and rep["bankroll"]["final"] > rep["bankroll"]["initial"]

    run_row = db.one(select(backtest_runs))
    assert run_row["finished_at"] is not None and run_row["params"]["kind"] == "markets"
    assert run_row["report"]["replay"]["rows"] == rep["replay"]["rows"]

    md = to_markdown(rep)
    assert "# Market backtest" in md and "| Market price |" in md and "## Not replayed" in md

    # a second run fetches nothing already stored and replays the same decisions
    fake_pm, fake_fc, fake_obs = sources
    before = (len(fake_pm.history_requests), len(fake_fc.requests), len(fake_obs.requests))
    rep2 = run(cfg, db, sources)
    assert len(fake_fc.requests) == before[1] and len(fake_obs.requests) == before[2]
    assert len(fake_pm.history_requests) == before[0] + 1   # only the empty one is tried again
    assert rep2["scores"] == rep["scores"]
    assert db.one(select(historical_forecasts.c.id).order_by(historical_forecasts.c.id.desc()))["id"] == \
        sum(1 for _ in db.rows(select(historical_forecasts.c.id)))
    # and offline replays the stored data the same way
    assert run(cfg, db, offline=True)["scores"] == rep["scores"]


def test_later_observations_never_reach_a_decision(tmp_path):
    """Changing what was observed on or after day D - lead changes nothing the
    model or the climatology baseline said for day D at that lead."""
    cfg = bt_cfg(tmp_path)
    db = Database(cfg.backtest.database_url)
    run(cfg, db)
    before = {(r["market_id"], r["lead_days"]): r for r in replay_module.replay(cfg, db, date(2026, 9, 20),
                                                                              date(2026, 9, 22))["rows"]}
    for d in ("2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22"):
        for kind in ("high", "low"):
            db.insert(weather_observations, station="EGLC", local_date=d, kind=kind, value_c=40.0, n_reports=24,
                      source="tamper")
    after = replay_module.replay(cfg, db, date(2026, 9, 20), date(2026, 9, 22))["rows"]
    changed = []
    for r in after:
        b = before[(r["market_id"], r["lead_days"])]
        last_known = date.fromisoformat(r["local_date"]) - timedelta(days=r["lead_days"] + 1)
        touched = any(date.fromisoformat(d) <= last_known for d in ("2026-09-19", "2026-09-20", "2026-09-21"))
        if not touched:
            assert (r["bias_c"], r["p_model"], r["p_climatology"]) == (b["bias_c"], b["p_model"], b["p_climatology"])
        else:
            changed.append(r)
    # 21 and 22 Sep at lead 1 do see the tampered 19th and 20th: the test can tell
    assert any(r["bias_c"] != before[(r["market_id"], r["lead_days"])]["bias_c"] for r in changed)


def test_bias_fit_is_walk_forward():
    cfg = load_config(env={"WXBOT_BACKTEST__TRAIN_DAYS": "30"})
    start = date(2026, 7, 1)
    days = [(start + timedelta(days=k)).isoformat() for k in range(80)]
    forecasts = {("EGLC", "high", 2): {d: {"a": float(k), "b": float(k), "c": float(k)} for k, d in enumerate(days)}}
    observations = {("EGLC", "high"): {d: 0.0 for d in days}}   # error on day k is k
    fits = BiasFits(cfg, forecasts, observations)
    cal, n = fits.get("EGLC", "high", 2, days[60])
    known = list(range(60 - 3 - 29, 60 - 3 + 1))                  # days 28..57: through D - 3, at most 30
    assert n == 30 and cal.bias_c == pytest.approx(sum(known) / len(known)) and cal.source == "walk-forward"
    cal, n = fits.get("EGLC", "high", 2, days[10])               # too few past days: defaults, no bias
    assert n == 8 and cal.bias_c == 0.0 and cal.source == "default"


def test_walk_forward_calibration_uses_only_known_results(monkeypatch):
    cfg = load_config(env={"WXBOT_CALIBRATION__MIN_SAMPLES": "40"})
    t0 = datetime(2026, 9, 1, 6, tzinfo=UTC)
    rows = []
    for k in range(400):  # an overconfident model: says 90%, right 60% of the time
        t = t0 + timedelta(hours=3 * k)
        rows.append({"market_id": str(k), "decision_time": t, "known_at": t + timedelta(hours=40),
                     "lead_hours": 40.0, "p_model": 0.9, "outcome": int(k % 5 < 3)})
    seen = []
    real_judge = replay_module.judge

    def spy(data, cfg_, version, fit_time):
        known = {r["decision_time"]: r for r in rows}
        assert all(t <= fit_time and known[t]["known_at"] <= fit_time for t, _, _ in data)
        seen.append((fit_time, len(data)))
        return real_judge(data, cfg_, version, fit_time)

    monkeypatch.setattr(replay_module, "judge", spy)
    rounds = walk_forward_calibration(rows, cfg, "normal-multimodel-v1")
    assert seen and seen[0][1] == 0 and [n for _, n in seen] == sorted(n for _, n in seen)
    assert len(rounds) == len(seen)
    first = [r for r in rows if r["decision_time"] < t0.replace(hour=0) + timedelta(days=1)]
    assert all(r["p_calibrated"] == 0.9 and r["calibrator_version"] == "identity" for r in first)
    late = rows[-1]
    assert late["calibrator_version"] != "identity" and late["p_calibrated"] == pytest.approx(0.6, abs=0.1)


# -- scoring and strategy --------------------------------------------------------------

def _row(i, p_model, market, outcome, lead=2, event=None, t=None, sigma=1.0):
    t = t or datetime(2026, 9, 20, 7, tzinfo=UTC) + timedelta(minutes=i)
    return {"market_id": f"m{i}", "event_id": event or f"e{i // 5}", "station": "EGLC", "local_date": "2026-09-22",
            "lead_days": lead, "lead_hours": 24.0 * lead - 8, "decision_time": t, "known_at": t + timedelta(days=2),
            "market_prob": market, "p_climatology": 0.5, "p_raw_forecast": p_model, "p_model": p_model,
            "p_calibrated": p_model, "n_models": 5, "sigma_c": sigma, "outcome": outcome}


def test_scores_compare_on_the_same_rows():
    cfg = load_config()
    rows = [_row(i, 0.95 if i % 2 else 0.05, 0.5, i % 2) for i in range(100)]
    rows.append({**_row(100, 0.9, 0.5, 1), "p_climatology": None})   # not in the common set
    sc = scores(rows, cfg, n_boot=200)
    assert sc["n_rows"] == 101 and sc["n_common"] == 100 and sc["n_events"] == 20
    by = {e["source"]: e for e in sc["sources"]}
    assert by["market"]["brier"] == pytest.approx(0.25) and by["model"]["brier"] == pytest.approx(0.0025)
    diff = by["model"]["brier_minus_market"]
    assert diff["mean"] == pytest.approx(0.0025 - 0.25) and diff["hi"] < 0 and diff["clusters"] == 20
    assert "brier_minus_market" not in by["market"]


def test_cluster_interval_resamples_whole_events():
    pairs = [("a", 1.0)] * 50 + [("b", 0.0)] * 50 + [(k, 0.5) for k in "cdefg"]
    out = cluster_mean_ci(pairs, n_boot=500)
    assert out["clusters"] == 7 and out["n"] == 105 and out["mean"] == pytest.approx(52.5 / 105)
    assert out["lo"] < 0.3 and out["hi"] > 0.7   # two big clusters dominate: the interval is wide


def test_flat_stake_applies_the_live_rules_once_per_market():
    cfg = load_config()
    t = datetime(2026, 9, 20, 7, tzinfo=UTC)
    rows = [
        _row(1, 0.05, 0.15, 0, lead=3, t=t),                                     # NO at 1-0.15+0.01: wins
        {**_row(1, 0.05, 0.15, 0, lead=2, t=t + timedelta(days=1))},             # same market later: held
        _row(2, 0.60, 0.50, 1, lead=3, t=t),                                     # 60% < 80% confidence
        _row(3, 0.99, 0.95, 0, lead=1, t=t),                                     # 16 h: too late to bet
    ]
    out = flat_stake(rows, cfg, record=True, n_boot=0)
    assert out["bets"] == 1 and out["won"] == 1
    entry = (1 - 0.15 + 0.01 + cfg.strategy.slippage) * (1 + cfg.strategy.fee_rate)
    assert rows[0]["side"] == "NO" and rows[0]["entry_price"] == pytest.approx(entry)
    assert rows[0]["pnl_per_dollar"] == pytest.approx(1 / entry - 1) and out["pnl"] == pytest.approx(1 / entry - 1)
    assert rows[1]["decision"] == "HELD"
    assert rows[2]["decision"] == "NO_BET" and "confidence" in rows[2]["reason"]
    assert rows[3]["decision"] == "NO_BET" and "time_to_resolution" in rows[3]["reason"]
    # a wider spread leaves less edge: the same bet fails at a 6-cent half spread
    assert flat_stake(rows, cfg, half_spread=0.06, n_boot=0)["bets"] == 0


def test_bankroll_uses_the_live_caps_and_settles_when_known():
    cfg = load_config()
    t = datetime(2026, 9, 20, 7, tzinfo=UTC)
    # 40 winning NO bets on separate events and days, decided hourly, each known two days later
    rows = []
    for i in range(40):
        r = _row(i, 0.02, 0.15, 0, lead=3, event=f"e{i}", t=t + timedelta(hours=i))
        r["local_date"] = f"2026-09-{20 + i % 10:02d}"
        rows.append(r)
    out = bankroll(rows, cfg)
    entry = (1 - 0.15 + 0.01 + cfg.strategy.slippage) * (1 + cfg.strategy.fee_rate)
    assert out["initial"] == cfg.bankroll.initial == 100.0
    # 2% of equity per bet; open bets are capped at 30% of equity, so the 16th waits for settlements
    assert out["bets"] == 15 and out["won"] == 15
    assert out["staked"] == pytest.approx(sum(2.0 * 1 for _ in range(15)), rel=0.05)
    assert out["final"] == pytest.approx(100 + out["staked"] * (1 / entry - 1), rel=1e-6)
    assert out["max_drawdown"] == 0.0 and out["curve"][-1]["equity"] == pytest.approx(out["final"])


# -- command line -----------------------------------------------------------------------

def test_cli_uses_its_own_database_and_fails_with_nothing_to_replay(tmp_path, monkeypatch, capsys):
    import main
    app_db, bt_db = tmp_path / "app.sqlite3", tmp_path / "bt.sqlite3"
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", f"sqlite:///{app_db}")
    monkeypatch.setenv("WXBOT_BACKTEST__DATABASE_URL", f"sqlite:///{bt_db}")
    out_json = tmp_path / "rep.json"
    assert main.main(["backtest-markets", str(out_json), "--offline", "--start", "2026-09-20",
                      "--end", "2026-09-22"]) == 1
    assert bt_db.exists() and not app_db.exists()
    assert "# Market backtest" in capsys.readouterr().out
    assert json.loads(out_json.read_text())["params"]["offline"] is True
