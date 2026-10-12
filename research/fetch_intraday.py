"""Research data pull (run by .github/workflows/research-fetch.yml, which has
network access): every METAR report for each station, and the hourly
forecasts issued a day ahead, for a same-day nowcast study.

Writes research/data/metar.csv.gz (station, valid UTC, tmpf) and
research/data/prev_day1.csv.gz (station, time UTC, model, temperature_2m in C
from the run made at least 24 h before that hour).
"""
from __future__ import annotations

import csv
import gzip
import io
import sys
import time
from datetime import date
from pathlib import Path

from wxbot.config import load_config
from wxbot.data.http import make_session
from wxbot.data.stations import _STATIONS
from wxbot.data.weather import IEM_ASOS, PREVIOUS_RUNS, IEMObservations

START, END = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
session = make_session()
models = list(load_config().weather.models)

with gzip.open(OUT / "metar.csv.gz", "wt", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["station", "valid", "tmpf"])
    for st in _STATIONS:
        params = [("station", IEMObservations.iem_id(st.code)), ("data", "tmpf"),
                  ("year1", START.year), ("month1", START.month), ("day1", START.day),
                  ("year2", END.year), ("month2", END.month), ("day2", END.day),
                  ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"),
                  ("trace", "T"), ("direct", "no"), ("report_type", "3"), ("report_type", "4")]
        for attempt in range(3):
            try:
                resp = session.get(IEM_ASOS, params=params, timeout=(10, 180))
                resp.raise_for_status()
                break
            except Exception as exc:  # noqa: BLE001
                print(f"{st.code}: IEM attempt {attempt + 1} failed: {exc}", flush=True)
                time.sleep(10)
        else:
            continue
        n = 0
        for row in csv.DictReader(io.StringIO(resp.text)):
            t = (row.get("tmpf") or "").strip()
            if t in ("", "M", "T"):
                continue
            w.writerow([st.code, row["valid"], t])
            n += 1
        print(f"{st.code}: {n} METAR reports", flush=True)
        time.sleep(2)

with gzip.open(OUT / "prev_day1.csv.gz", "wt", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["station", "time", "model", "t_c"])
    for st in _STATIONS:
        params = {"latitude": st.lat, "longitude": st.lon, "hourly": "temperature_2m_previous_day1",
                  "models": ",".join(models), "timezone": "UTC",
                  "start_date": START.isoformat(), "end_date": END.isoformat()}
        try:
            resp = session.get(PREVIOUS_RUNS, params=params, timeout=(10, 180))
            resp.raise_for_status()
            hourly = resp.json().get("hourly") or {}
        except Exception as exc:  # noqa: BLE001
            print(f"{st.code}: previous runs failed: {exc}", flush=True)
            continue
        times = hourly.get("time") or []
        n = 0
        for key, series in hourly.items():
            if not key.startswith("temperature_2m_previous_day1"):
                continue
            model = key[len("temperature_2m_previous_day1"):].lstrip("_") or models[0]
            for t, v in zip(times, series):
                if v is not None:
                    w.writerow([st.code, t, model, v])
                    n += 1
        print(f"{st.code}: {n} hourly forecast values", flush=True)
        time.sleep(1)
