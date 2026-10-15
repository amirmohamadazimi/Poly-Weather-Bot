"""Research only: runs the v2 model's network paths against the live APIs with
the bot's own code (checked out from the branch under test, on PYTHONPATH):
run times of every weather model, the 12-model forecast at a few stations, the
daily stats refresh for every enabled station into a scratch database, and one
prediction per station from the fetched forecast and the refreshed stats."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta

from wxbot.config import load_config
from wxbot.data.polymarket import Bucket
from wxbot.data.stations import STATIONS
from wxbot.data.weather import IEMObservations, OpenMeteoForecast, OpenMeteoPreviousRuns
from wxbot.db import Database
from wxbot.features import build_features
from wxbot.learning import model_stats
from wxbot.model.base import Calibration
from wxbot.model.weighted import WeightedMultiModel

CODES = ["EGLC", "KLGA", "RKSI"]


def counted(obj, calls: list) -> None:
    get = obj.session.get

    def wrapped(url, *a, **k):
        calls.append(url.split("?")[0])
        return get(url, *a, **k)
    obj.session.get = wrapped


def main() -> None:
    cfg = load_config()
    models = list(cfg.weather.models)
    print("models", models, flush=True)
    fc_calls: list = []
    fc = OpenMeteoForecast(models)
    counted(fc, fc_calls)
    t0 = time.time()
    print("runs", round(time.time() - t0, 1), json.dumps(fc.model_runs()), flush=True)
    forecasts = {}
    for code in CODES:
        st = STATIONS.get(code)
        if st is None:
            print("no station", code)
            continue
        n0, t0 = len(fc_calls), time.time()
        try:
            data, meta = fc.fetch(st)
        except Exception as exc:  # noqa: BLE001
            print("forecast", code, "error", repr(exc), flush=True)
            continue
        forecasts[code] = data
        per_model = {m: sum(m in data["high"][d] for d in data["high"]) for m in models}
        print("forecast", code, "requests", len(fc_calls) - n0, "secs", round(time.time() - t0, 1),
              "days", sorted(data["high"]), json.dumps(per_model), flush=True)
    db = Database(f"sqlite:///{tempfile.mkdtemp()}/probe.sqlite3")
    hist, obs = OpenMeteoPreviousRuns(models), IEMObservations()
    h_calls: list = []
    counted(hist, h_calls)
    t0 = time.time()
    out = model_stats.refresh(db, cfg, hist, obs, "weighted-multimodel-v1", datetime.now(UTC), force=True)
    print("refresh", round(time.time() - t0, 1), "s, requests", len(h_calls), json.dumps(out), flush=True)
    stats = model_stats.load(db)
    for key in sorted(stats):
        if key[0] in CODES and key[2] == 1:
            s = stats[key]
            print("stats", key, "days", s.n_days, "last", s.last_day, "sd", s.sd and round(s.sd, 3),
                  "bias", json.dumps({m: round(v, 2) for m, v in s.bias.items()}),
                  "rmse", json.dumps({m: round(v ** 0.5, 2) for m, v in s.mse.items()}), flush=True)
    model = WeightedMultiModel(min_models=int(cfg.weather.min_models))
    model.stats = stats
    cal = Calibration(bias_c=0.0, sigma_c=1.5, n=0, source="default")
    for code, data in forecasts.items():
        st = STATIONS[code]
        for d in sorted(data["high"])[1:4]:
            values = data["high"][d]
            lead = (date.fromisoformat(d) - datetime.now(UTC).date()).days
            feats = build_features(station=code, kind="high", local_date=d, values_c=values, lead_days=lead,
                                   issue_time=None, day_end=datetime.now(UTC) + timedelta(days=lead),
                                   climatology_c=[])
            mid = round(sum(values.values()) / len(values))
            p = model.predict(Bucket(mid, mid, "C"), "high", values, lead, cal, feats)
            print("predict", code, d, "lead", lead, "n_models", len(values),
                  None if p is None else {"mu": round(p.mu_c, 2), "sigma": round(p.sigma_c, 2),
                                          "p_mid": round(p.p_yes, 3), "spread": p.inputs.get("model_spread_c"),
                                          "weights": {m: round(w, 2) for m, w in p.inputs["weights"].items()}},
                  flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
