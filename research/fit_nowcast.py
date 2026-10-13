"""Fit the same-day model's parameters (wxbot/model/nowcast_params.json).

    git fetch origin research-intraday
    git checkout origin/research-intraday -- research/data    # the inputs (~8 MB), kept off main
    python -m research.fit_nowcast research/data 2025-10-01 2026-09-20 > wxbot/model/nowcast_params.json

Inputs (research/fetch_intraday.py): every METAR report per station, and the
hourly forecast issued a day ahead (Open-Meteo Previous Runs), averaged over
the models when at least two have a value. For every station, local day and
whole hour t, the reports known at t - DELAY give the day so far
(wxbot/model/nowcast.py day_state) and the extreme of the later reports is
what was still to come, R. Station biases are the mean of R - frem per station
and kind; alpha, beta and sigma are a least-squares line of the rest of R -
frem on the anomaly, per kind and hour band. The output depends only on the
inputs and the window, so the same data gives the same file.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from wxbot.data.stations import _STATIONS
from wxbot.model.nowcast import HOUR_BANDS, day_bounds, day_state, hour_band

DELAY = timedelta(minutes=20)   # a report counts as known this long after its time
MIN_MODELS = 2
MIN_SIGMA_C = 0.3


def load_reports(path: Path) -> dict[str, list[tuple[datetime, float]]]:
    out: dict[str, list] = defaultdict(list)
    with gzip.open(path, "rt") as fh:
        for r in csv.DictReader(fh):
            try:
                t = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                out[r["station"]].append((t, (float(r["tmpf"]) - 32.0) * 5.0 / 9.0))
            except ValueError:
                continue
    return {s: sorted(v) for s, v in out.items()}


def load_forecast(path: Path) -> dict[str, list[tuple[datetime, float]]]:
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with gzip.open(path, "rt") as fh:
        for r in csv.DictReader(fh):
            acc[r["station"]][r["time"]].append(float(r["t_c"]))
    return {s: sorted((datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC), sum(v) / len(v))
                      for t, v in hours.items() if len(v) >= MIN_MODELS) for s, hours in acc.items()}


def rows(reports: dict, forecast: dict, first: date, last: date) -> list[tuple]:
    """(kind, hour band, station, frem, anom, R) for every station, day and hour."""
    out = []
    for st in _STATIONS:
        if st.code not in reports or st.code not in forecast:
            continue
        rep, fc = reports[st.code], forecast[st.code]
        rt, ft = [t for t, _ in rep], [t for t, _ in fc]
        d = first
        while d <= last:
            start, end = day_bounds(st.tz, d.isoformat())
            day_rep = rep[bisect.bisect_left(rt, start):bisect.bisect_left(rt, end)]
            day_fc = fc[bisect.bisect_left(ft, start - timedelta(hours=2)):bisect.bisect_right(ft, end)]
            t = start.replace(minute=0, second=0) + timedelta(hours=1)
            while t < end - timedelta(minutes=15):
                cut = t - DELAY
                later = [v for u, v in day_rep if u > cut]
                for kind in ("high", "low"):
                    s = day_state(day_rep, day_fc, start, end, cut, kind)
                    if s is None or not later:
                        continue
                    r = max(later) if kind == "high" else min(later)
                    out.append((kind, hour_band((end - t).total_seconds() / 3600), st.code, s["frem"], s["anom"], r))
                t += timedelta(hours=1)
            d += timedelta(days=1)
    return out


def fit(data: list[tuple]) -> tuple[dict, dict]:
    """-> ({(station, kind): bias}, {(kind, band): {alpha, beta, sigma, n}})."""
    acc: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0])
    for kind, _, st, frem, _, r in data:
        acc[(st, kind)][0] += r - frem
        acc[(st, kind)][1] += 1
    bias = {k: s / n for k, (s, n) in acc.items()}
    groups: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for kind, band, st, frem, anom, r in data:
        groups[(kind, band)].append((anom, r - frem - bias[(st, kind)]))
    bands = {}
    for key, g in groups.items():
        n = len(g)
        mx, my = sum(a for a, _ in g) / n, sum(y for _, y in g) / n
        sxx = sum((a - mx) ** 2 for a, _ in g)
        beta = sum((a - mx) * (y - my) for a, y in g) / sxx if sxx > 1e-9 else 0.0
        alpha = my - beta * mx
        sd = math.sqrt(sum((y - alpha - beta * a) ** 2 for a, y in g) / max(1, n - 2))
        bands[key] = {"alpha": alpha, "beta": beta, "sigma": max(sd, MIN_SIGMA_C), "n": n}
    return bias, bands


def params_file(bias: dict, bands: dict, n_rows: int, first: date, last: date, version: str) -> dict:
    def r6(x: float) -> float:
        return round(x, 6)
    stations: dict[str, dict] = defaultdict(dict)
    for (st, kind), b in sorted(bias.items()):
        stations[st][kind] = r6(b)
    return {
        "version": version, "train_from": first.isoformat(), "train_to": last.isoformat(), "rows": n_rows,
        "report_delay_minutes": DELAY.total_seconds() / 60,
        "inputs": "IEM METAR reports (report types 3 and 4); Open-Meteo Previous Runs temperature_2m_previous_day1, "
                  f"mean of at least {MIN_MODELS} of the [weather] models",
        "hour_bands": HOUR_BANDS, "station_bias": dict(stations),
        "bands": {kind: [{k: (r6(v) if isinstance(v, float) else v) for k, v in bands[(kind, i)].items()}
                         for i in range(len(HOUR_BANDS) - 1)] for kind in ("high", "low")},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("data", type=Path, help="folder with metar.csv.gz and prev_day1.csv.gz")
    ap.add_argument("first", type=date.fromisoformat)
    ap.add_argument("last", type=date.fromisoformat)
    ap.add_argument("--version", default="nowcast-v1")
    a = ap.parse_args()
    data = rows(load_reports(a.data / "metar.csv.gz"), load_forecast(a.data / "prev_day1.csv.gz"), a.first, a.last)
    bias, bands = fit(data)
    print(json.dumps(params_file(bias, bands, len(data), a.first, a.last, a.version), indent=1))


if __name__ == "__main__":
    main()
