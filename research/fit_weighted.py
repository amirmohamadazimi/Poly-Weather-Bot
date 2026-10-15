"""Fit the v2 model's spread parameters (wxbot/model/weighted_params.json).

    git fetch origin research-intraday
    git checkout origin/research-intraday -- research/data    # the inputs (~30 MB), kept off main
    python -m research.fit_weighted research/data 2025-12-01 2026-10-12 > wxbot/model/weighted_params.json

Inputs (research/fetch_models.py, research/fetch_intraday.py): the daily max and
min of every model's previous_dayN forecast per station (daily_prev_*.csv.gz)
and the stations' METAR reports (metar.csv.gz, metar_extra.csv.gz). For every
station, kind and lead the model is walked through the days in order
(wxbot/model/weighted.py walk), and each day D is priced as the bot prices a
market at that lead: with the state after day D - lead - 1, the last whole day
before the decision day D - lead (wxbot/learning/model_stats.py refits up to
the station's local yesterday), and only with at least MIN_MODELS models.
a0..a2 of log sigma = a0 + a1 log(sd) + a2 log(spread + 0.1) are the
maximum-likelihood fit of a normal error on the days first..last, per kind and
lead. Days before `first` only warm up the running biases. The output depends
only on the inputs and the window. --evaluate scores a window: its mean
absolute error is out of sample (each day uses only earlier days), but its log
loss uses the fitted spread parameters, so it is in sample for days inside the
fit window.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from wxbot.model.normal import bucket_probability
from wxbot.data.polymarket import Bucket
from wxbot.model.weighted import BIAS_HALF_LIFE, SD_HALF_LIFE, Stats, combine, walk

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless", "jma_seamless", "ecmwf_ifs",
          "ecmwf_aifs025_single", "ukmo_seamless", "meteofrance_seamless", "cma_grapes_global",
          "ncep_nbm_conus", "ncep_hrrr_conus"]
LEADS = (1, 2, 3)
MIN_REPORTS = 18
MIN_MODELS = 3     # [weather] min_models: the bot prices nothing with fewer models that have stats
# Market stations not in the bot's table (research/fetch_models.py EXTRA): more days for the fit.
EXTRA_TZ = {
    "OEJN": "Asia/Riyadh", "LTFM": "Europe/Istanbul", "LLBG": "Asia/Jerusalem", "LFPB": "Europe/Paris",
    "FACT": "Africa/Johannesburg", "EHAM": "Europe/Amsterdam", "EFHK": "Europe/Helsinki", "UUWW": "Europe/Moscow",
    "ZUCK": "Asia/Shanghai", "ZSQD": "Asia/Shanghai", "ZHHH": "Asia/Shanghai", "ZGSZ": "Asia/Shanghai",
    "ZGGG": "Asia/Shanghai", "ZBAA": "Asia/Shanghai", "RKPK": "Asia/Seoul", "RCSS": "Asia/Taipei",
    "OPKC": "Asia/Karachi", "KBKF": "America/Denver", "WMKK": "Asia/Kuala_Lumpur", "RPLL": "Asia/Manila",
    "MPMG": "America/Panama",
}


def station_zones() -> dict[str, str]:
    from wxbot.data.stations import _STATIONS
    return {**EXTRA_TZ, **{s.code: s.tz for s in _STATIONS if s.enabled}}


def load_observed(data: Path, zones: dict[str, str]) -> dict[tuple[str, str], dict[str, float]]:
    """-> {(station, kind): {local_date: value_c}} from METAR reports, days with >= MIN_REPORTS reports."""
    per_day: dict[tuple[str, str], list[float]] = defaultdict(list)
    for name in ("metar.csv.gz", "metar_extra.csv.gz"):
        path = data / name
        if not path.exists():
            continue
        with gzip.open(path, "rt") as fh:
            for r in csv.DictReader(fh):
                st = r["station"]
                if st not in zones:
                    continue
                try:
                    t = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                    c = (float(r["tmpf"]) - 32.0) * 5.0 / 9.0
                except ValueError:
                    continue
                per_day[(st, t.astimezone(ZoneInfo(zones[st])).date().isoformat())].append(c)
    out: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for (st, d), vs in per_day.items():
        if len(vs) >= MIN_REPORTS:
            out[(st, "high")][d] = max(vs)
            out[(st, "low")][d] = min(vs)
    return out


def load_forecasts(data: Path) -> dict[tuple[str, str, int], dict[str, dict[str, float]]]:
    """-> {(station, kind, lead): {local_date: {model: value_c}}}"""
    out: dict[tuple[str, str, int], dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for path in sorted(data.glob("daily_prev_*.csv.gz")):
        with gzip.open(path, "rt") as fh:
            for r in csv.DictReader(fh):
                if r["model"] not in MODELS:
                    continue
                lead = int(r["lead"])
                out[(r["station"], "high", lead)][r["local_date"]][r["model"]] = float(r["tmax_c"])
                out[(r["station"], "low", lead)][r["local_date"]][r["model"]] = float(r["tmin_c"])
    return out


def series(fc: dict[str, dict[str, float]], obs: dict[str, float]) -> list[tuple[str, dict[str, float], float | None]]:
    return [(d, {m: v for m, v in sorted(fc[d].items(), key=lambda kv: MODELS.index(kv[0]))}, obs.get(d))
            for d in sorted(fc)]


def priced_as_live(days: list[tuple[str, dict[str, float], float | None]], lead: int) -> list[dict]:
    """{day, mu, spread, sd, obs} for each observed day D, priced with the state
    after day D - lead - 1 (see the module docstring)."""
    states: list[tuple[str, Stats]] = []
    walk(days, states)
    known = [d for d, _ in states]
    out = []
    for day, values, obs in days:
        if obs is None:
            continue
        cutoff = (date.fromisoformat(day) - timedelta(days=lead + 1)).isoformat()
        i = bisect.bisect_right(known, cutoff) - 1
        if i < 0 or states[i][1].sd is None:
            continue
        st = states[i][1]
        c = combine(values, st)
        if c is None or len(c[2]) < MIN_MODELS:
            continue
        out.append({"day": day, "mu": c[0], "spread": c[1], "sd": st.sd, "obs": obs})
    return out


def fit_sigma(rows: list[dict]) -> list[float]:
    """Newton steps on the mean normal negative log likelihood in a (convex in a)."""
    xs = [(1.0, math.log(max(r["sd"], 0.2)), math.log(r["spread"] + 0.1), r["obs"] - r["mu"]) for r in rows]
    a = [0.0, 1.0, 0.0]
    for _ in range(100):
        g = [0.0] * 3
        h = [[0.0] * 3 for _ in range(3)]
        for x0, x1, x2, res in xs:
            x = (x0, x1, x2)
            ls = a[0] * x0 + a[1] * x1 + a[2] * x2
            z2 = res * res * math.exp(-2 * ls)
            for i in range(3):
                g[i] += x[i] * (1 - z2)
                for j in range(3):
                    h[i][j] += x[i] * x[j] * 2 * z2
        n = len(xs)
        g = [v / n for v in g]
        h = [[v / n for v in row] for row in h]
        step = _solve(h, g)
        a = [a[i] - step[i] for i in range(3)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return [round(v, 6) for v in a]


def _solve(h: list[list[float]], g: list[float]) -> list[float]:
    m = [row[:] + [g[i]] for i, row in enumerate(h)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(3):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [m[r][k] - f * m[c][k] for k in range(4)]
    return [m[i][3] / m[i][i] for i in range(3)]


def bucket_log_loss(mu: float, sd: float, obs: float, us: bool) -> float:
    """-log P(the observed whole-degree bucket): 2 F pairs (70-71) for US stations, 1 C elsewhere."""
    if us:
        v = math.floor(obs * 9 / 5 + 32 + 0.5)
        lo = v - (v % 2)
        b, mu_u, sd_u = Bucket(lo, lo + 1, "F"), mu * 9 / 5 + 32, sd * 9 / 5
    else:
        v = math.floor(obs + 0.5)
        b, mu_u, sd_u = Bucket(v, v, "C"), mu, sd
    return -math.log(max(bucket_probability(b, mu_u, sd_u), 1e-4))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("data", type=Path)
    ap.add_argument("first", type=date.fromisoformat)
    ap.add_argument("last", type=date.fromisoformat)
    ap.add_argument("--version", default="weighted-multimodel-v1")
    ap.add_argument("--evaluate", nargs=2, metavar=("FROM", "TO"), help="also print scores on this window")
    a = ap.parse_args()
    zones = station_zones()
    observed = load_observed(a.data, zones)
    forecasts = load_forecasts(a.data)
    rows: dict[tuple[str, int], list[dict]] = defaultdict(list)
    evals: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for (st, kind, lead), fc in sorted(forecasts.items()):
        for r in priced_as_live(series(fc, observed.get((st, kind), {})), lead):
            r["station"] = st
            if a.first.isoformat() <= r["day"] <= a.last.isoformat():
                rows[(kind, lead)].append(r)
            if a.evaluate and a.evaluate[0] <= r["day"] <= a.evaluate[1]:
                evals[(kind, lead)].append(r)
    fitted = {kind: [fit_sigma(rows[(kind, lead)]) for lead in LEADS] for kind in ("high", "low")}
    if a.evaluate:
        from wxbot.model.weighted import sigma
        for (kind, lead), rs in sorted(evals.items()):
            p = fitted[kind][lead - 1]
            mae = sum(abs(r["obs"] - r["mu"]) for r in rs) / len(rs)
            bll = sum(bucket_log_loss(r["mu"], sigma(p, r["sd"], r["spread"]), r["obs"], r["station"].startswith("K"))
                      for r in rs) / len(rs)
            print(f"{kind} lead {lead}: {len(rs)} days, MAE {mae:.3f} C, whole-bucket log loss {bll:.3f}",
                  file=sys.stderr)
    print(json.dumps({
        "version": a.version, "train_from": a.first.isoformat(), "train_to": a.last.isoformat(),
        "rows": {f"{k}_{lead}": len(rows[(k, lead)]) for k in ("high", "low") for lead in LEADS},
        "models": MODELS, "bias_half_life_days": BIAS_HALF_LIFE, "sd_half_life_days": SD_HALF_LIFE,
        "inputs": "Open-Meteo Previous Runs temperature_2m_previous_dayN daily max/min per model; "
                  f"METAR daily max/min (days with >= {MIN_REPORTS} reports)",
        "sigma": fitted,
    }, indent=1))


if __name__ == "__main__":
    main()
