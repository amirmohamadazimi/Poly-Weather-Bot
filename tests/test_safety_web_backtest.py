from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import make_engine
from wxbot.backtest import MIN_TRAIN, run_backtest, walk_forward_fits
from wxbot.config import load_config
from wxbot.db import Database, calibration_params
from wxbot.execution.live import LIVE_ACK_ENV, LiveTradingDisabled
from wxbot.execution.paper import PaperBroker, make_broker
from wxbot.web.app import create_app


def test_paper_is_default(cfg):
    assert cfg.app.mode == "paper"
    assert isinstance(make_broker(cfg, None), PaperBroker)


def test_live_mode_refuses_even_with_ack(tmp_path, monkeypatch):
    cfg = load_config(env={"WXBOT_APP__MODE": "live", "WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path}/x.db"})
    with pytest.raises(LiveTradingDisabled, match=LIVE_ACK_ENV):
        make_broker(cfg, None)
    monkeypatch.setenv(LIVE_ACK_ENV, "yes")
    with pytest.raises(LiveTradingDisabled, match="not implemented"):
        make_broker(cfg, None)


def test_env_overrides(tmp_path):
    cfg = load_config(env={"WXBOT_STRATEGY__MIN_MODEL_PROB": "0.9", "WXBOT_WEATHER__MODELS": "a,b",
                           "WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path}/x.db"})
    assert cfg.strategy.min_model_prob == 0.9 and cfg.weather.models == ["a", "b"]


def test_dashboard_api(cfg):
    eng = make_engine(cfg)
    eng.run_cycle()
    client = TestClient(create_app(cfg, eng.db, now=eng.clock))
    assert "Weather Paper Bot" in client.get("/").text
    ov = client.get("/api/overview").json()
    assert ov["mode"] == "PAPER TRADING" and ov["n_bets"] == 1 and ov["real_money"] == 0
    mk = client.get("/api/markets").json()
    assert len(mk["markets"]) == 11 and mk["skipped"][0]["n"] == 11
    bet = client.get("/api/bets").json()[0]
    detail = client.get(f"/api/signals/{bet['signal_id']}").json()
    assert detail["bet"]["id"] == bet["id"] and detail["prediction"]["inputs"]
    assert client.get("/api/performance").status_code == 200
    st = client.get("/api/status").json()
    assert st["markets_monitored"] == "11" and st["active_positions"] == 1
    assert client.get("/export/all.zip").headers["content-type"] == "application/zip"
    assert client.get("/export/paper_bets.csv").status_code == 200
    assert client.get("/export/nope.csv").status_code == 404


def test_dashboard_password(tmp_path):
    cfg = load_config(env={"WXBOT_APP__DASHBOARD_PASSWORD": "s3cret",
                           "WXBOT_APP__DATABASE_URL": f"sqlite:///{tmp_path}/x.db"})
    client = TestClient(create_app(cfg, Database(cfg.app.database_url)))
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/overview", auth=("any", "s3cret")).status_code == 200
    assert client.get("/healthz").status_code == 200


class FakePrev:
    models = ["m1", "m2", "m3"]

    def __init__(self, early_bias, late_bias, switch):
        self.early, self.late, self.switch = early_bias, late_bias, switch

    def fetch(self, station, start, end, leads):
        out = {}
        for lead in leads:
            out[lead] = {"high": {}, "low": {}}
            d = start
            while d <= end:
                b = self.early if d < self.switch else self.late
                wiggle = ((d.toordinal() * 7) % 5 - 2) * 0.4
                out[lead]["high"][d.isoformat()] = {m: 20 + b + wiggle + i * 0.1 for i, m in enumerate(self.models)}
                d += timedelta(days=1)
        return out


class FakeObs:
    def fetch(self, station, start, end):
        days = {}
        d = start
        while d <= end:
            days[d.isoformat()] = (20.0, 24)
            d += timedelta(days=1)
        return {"high": days, "low": {}}


def test_backtest_fits_calibration_and_scores(cfg):
    db = Database(cfg.app.database_url)
    end = date(2026, 9, 26)
    rep = run_backtest(cfg, db, FakePrev(2.0, 2.0, end), FakeObs(), stations=["EGLC"], days=60, leads=(1,), end=end)
    assert rep["n_bucket_predictions"] > 0 and rep["brier"] is not None
    row = db.one(select(calibration_params).where(calibration_params.c.station == "EGLC"))
    assert row["bias_c"] == pytest.approx(2.0 + 0.1, abs=0.1) and row["n"] == 60
    # the live engine now uses the fitted params instead of the defaults
    eng = make_engine(cfg, db=db)
    assert eng._calibration("EGLC", "high", 1).source == "backtest"


def test_backtest_walk_forward_has_no_look_ahead():
    """Each day is scored with parameters fitted only on days whose observation
    existed when that forecast was issued (<= day - lead - 1)."""
    start = date(2026, 7, 1)
    rows = [(start + timedelta(days=k), {"m": 0.0}, 0.0) for k in range(40)]
    errors = [float(k) for k in range(40)]  # error on day k is k: any leak shifts the mean
    fits = list(walk_forward_fits(rows, errors, lead=2))
    assert fits[0][0] == MIN_TRAIN + 2           # first day with 14 known days
    for i, bias, _ in fits:
        known = [e for e, (d, _, _) in zip(errors, rows) if d <= rows[i][0] - timedelta(days=3)]
        assert bias == pytest.approx(sum(known) / len(known))
        assert max(known) == i - 3


def test_backtest_if_missing_skips_when_calibrated(cfg, monkeypatch, capsys):
    import main
    db = Database(cfg.app.database_url)
    db.insert(calibration_params, station="EGLC", kind="high", lead_days=1, bias_c=0.0, sigma_c=1.5, n=60)
    monkeypatch.setenv("WXBOT_APP__DATABASE_URL", cfg.app.database_url)
    assert main.main(["backtest", "--if-missing"]) == 0   # would hit the network if it ran
    assert "skipping backtest" in capsys.readouterr().out
