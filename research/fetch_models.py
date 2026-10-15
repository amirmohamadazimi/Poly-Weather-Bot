"""Research data pull for the forecast-model study (run by
.github/workflows/research-models.yml, which has network access).

1. Probes which Open-Meteo models the Previous Runs API serves, on a week at
   three stations (US, Europe, Asia) -> research/data/models_probe.csv.
2. For every market station (the bot's table plus the cities it does not trade
   yet, EXTRA below), the max and min over the station's local day of
   temperature_2m_previous_day{1,2,3} for every served model ->
   research/data/daily_prev.csv.gz (station, local_date, lead, model, tmax_c,
   tmin_c, n_hours). previous_dayN at hour h comes from the run made N days
   before h, so lead N is the day's forecast as known about N days before.
3. METAR reports for the EXTRA stations -> research/data/metar_extra.csv.gz.
4. MOS guidance from the IEM archive for the US stations (NBM extended "NBE"
   and GFS extended "MEX"), best effort -> research/data/mos_<model>.csv.gz.

    python -m research.fetch_models 2025-10-01 2026-10-15 probe            # prints the served models
    python -m research.fetch_models 2025-10-01 2026-10-15 daily 0 5 m1,m2  # stations i with i % 5 == 0
    python -m research.fetch_models 2025-10-01 2026-10-15 metar
    python -m research.fetch_models 2025-10-01 2026-10-15 mos
"""
from __future__ import annotations

import csv
import gzip
import io
import sys
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from wxbot.data.http import make_session
from wxbot.data.stations import _STATIONS, Station
from wxbot.data.weather import IEM_ASOS, PREVIOUS_RUNS, IEMObservations

START, END = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
session = make_session()
IEM_MOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
LEADS = (1, 2, 3)
MAX_MODELS = 16

# Market stations the bot's table does not have yet (from the markets' resolution sources).
EXTRA = [
    Station("OEJN", "Jeddah", 21.6796, 39.1565, "Asia/Riyadh"),
    Station("LTFM", "Istanbul Airport", 41.2753, 28.7519, "Europe/Istanbul"),
    Station("LLBG", "Tel Aviv Ben Gurion", 32.0114, 34.8867, "Asia/Jerusalem"),
    Station("LFPB", "Paris Le Bourget", 48.9694, 2.4414, "Europe/Paris"),
    Station("FACT", "Cape Town", -33.9649, 18.6017, "Africa/Johannesburg"),
    Station("EHAM", "Amsterdam Schiphol", 52.3105, 4.7683, "Europe/Amsterdam"),
    Station("EFHK", "Helsinki-Vantaa", 60.3172, 24.9633, "Europe/Helsinki"),
    Station("UUWW", "Moscow Vnukovo", 55.5915, 37.2615, "Europe/Moscow"),
    Station("ZUCK", "Chongqing Jiangbei", 29.7192, 106.6417, "Asia/Shanghai"),
    Station("ZSQD", "Qingdao Jiaodong", 36.3614, 120.0883, "Asia/Shanghai"),
    Station("ZHHH", "Wuhan Tianhe", 30.7838, 114.2081, "Asia/Shanghai"),
    Station("ZGSZ", "Shenzhen Bao'an", 22.6393, 113.8107, "Asia/Shanghai"),
    Station("ZGGG", "Guangzhou Baiyun", 23.3924, 113.2988, "Asia/Shanghai"),
    Station("ZBAA", "Beijing Capital", 40.0801, 116.5846, "Asia/Shanghai"),
    Station("RKPK", "Busan Gimhae", 35.1795, 128.9382, "Asia/Seoul"),
    Station("RCSS", "Taipei Songshan", 25.0697, 121.5525, "Asia/Taipei"),
    Station("OPKC", "Karachi Jinnah", 24.9065, 67.1608, "Asia/Karachi"),
    Station("KBKF", "Buckley SFB", 39.7017, -104.7517, "America/Denver"),
    Station("WMKK", "Kuala Lumpur Intl", 2.7456, 101.7099, "Asia/Kuala_Lumpur"),
    Station("RPLL", "Manila NAIA", 14.5086, 121.0198, "Asia/Manila"),
    Station("MPMG", "Panama Albrook", 8.9733, -79.5556, "America/Panama"),
]
STATIONS = [s for s in _STATIONS if s.code != "HKO"] + EXTRA

# In order of preference; the first MAX_MODELS the archive serves are pulled.
CANDIDATES = [
    "ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless", "jma_seamless",   # the bot's five
    "ecmwf_aifs025_single", "ukmo_seamless", "meteofrance_seamless", "ecmwf_ifs",
    "gfs_graphcast025", "ncep_nbm_conus", "ncep_hrrr_conus", "kma_seamless", "cma_grapes_global",
    "bom_access_global", "metno_seamless", "knmi_seamless", "dmi_seamless", "italia_meteo_arpae_icon_2i",
    "meteoswiss_icon_ch2", "ukmo_global_deterministic_10km", "meteofrance_arpege_world", "ecmwf_aifs025",
]


def get(url: str, params, tries: int = 6, timeout=(10, 240)):
    for attempt in range(tries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                print(f"  429 from {url}, waiting", file=sys.stderr, flush=True)
                time.sleep(65)
                continue
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            print(f"  attempt {attempt + 1} failed: {str(exc)[:300]}", file=sys.stderr, flush=True)
            time.sleep(15 * (attempt + 1))
    return None


def probe() -> list[str]:
    sites = [s for s in STATIONS if s.code in ("KLGA", "EGLC", "RKSI")]
    first, last = END - timedelta(days=40), END - timedelta(days=34)
    served = []
    with open(OUT / "models_probe.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "station", "values", "non_null"])
        for m in CANDIDATES:
            best = 0.0
            for st in sites:
                resp = get(PREVIOUS_RUNS, {"latitude": st.lat, "longitude": st.lon,
                                           "hourly": "temperature_2m_previous_day1", "models": m, "timezone": "UTC",
                                           "start_date": first.isoformat(), "end_date": last.isoformat()}, tries=2)
                vals = []
                if resp is not None:
                    hourly = resp.json().get("hourly") or {}
                    vals = next((v for k, v in hourly.items() if k.startswith("temperature_2m_previous_day1")), [])
                nn = sum(v is not None for v in vals)
                w.writerow([m, st.code, len(vals), nn])
                best = max(best, nn / len(vals) if vals else 0.0)
                time.sleep(0.5)
            print(f"probe {m}: {best:.0%} of hours served", file=sys.stderr, flush=True)
            if best >= 0.8:
                served.append(m)
    return served[:MAX_MODELS]


def daily_prev(models: list[str], part: int, parts: int) -> None:
    chunks = [models[i:i + 5] for i in range(0, len(models), 5)]
    with gzip.open(OUT / f"daily_prev_{part}.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["station", "local_date", "lead", "model", "tmax_c", "tmin_c", "n_hours"])
        for st in STATIONS[part::parts]:
            z = ZoneInfo(st.tz)
            n = 0
            for chunk in chunks:
                params = {"latitude": st.lat, "longitude": st.lon, "timezone": "UTC",
                          "hourly": ",".join(f"temperature_2m_previous_day{k}" for k in LEADS),
                          "models": ",".join(chunk), "start_date": (START - timedelta(days=1)).isoformat(),
                          "end_date": (END + timedelta(days=1)).isoformat()}
                resp = get(PREVIOUS_RUNS, params)
                if resp is None:
                    print(f"{st.code}: {chunk} failed", flush=True)
                    continue
                hourly = resp.json().get("hourly") or {}
                times = [datetime.fromisoformat(t).replace(tzinfo=UTC).astimezone(z) for t in hourly.get("time") or []]
                for key, series in hourly.items():
                    if not key.startswith("temperature_2m_previous_day"):
                        continue
                    rest = key[len("temperature_2m_previous_day"):]
                    lead_s, _, model = rest.partition("_")
                    model = model or chunk[0]
                    days: dict[date, list[float]] = defaultdict(list)
                    for t, v in zip(times, series):
                        if v is not None:
                            days[t.date()].append(v)
                    for d, vs in sorted(days.items()):
                        if START <= d <= END and len(vs) >= 18:
                            w.writerow([st.code, d.isoformat(), int(lead_s), model, max(vs), min(vs), len(vs)])
                            n += 1
                time.sleep(4)
            print(f"{st.code}: {n} daily values", flush=True)


def metar_extra() -> None:
    with gzip.open(OUT / "metar_extra.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["station", "valid", "tmpf"])
        for st in EXTRA:
            params = [("station", IEMObservations.iem_id(st.code)), ("data", "tmpf"),
                      ("year1", START.year), ("month1", START.month), ("day1", START.day),
                      ("year2", END.year), ("month2", END.month), ("day2", END.day),
                      ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"),
                      ("trace", "T"), ("direct", "no"), ("report_type", "3"), ("report_type", "4")]
            resp = get(IEM_ASOS, params, tries=3)
            n = 0
            if resp is not None:
                for row in csv.DictReader(io.StringIO(resp.text)):
                    t = (row.get("tmpf") or "").strip()
                    if t not in ("", "M", "T"):
                        w.writerow([st.code, row["valid"], t])
                        n += 1
            print(f"{st.code}: {n} METAR reports", flush=True)
            time.sleep(2)


def mos(model: str) -> None:
    us = [s for s in STATIONS if s.code.startswith("K")]
    with gzip.open(OUT / f"mos_{model.lower()}.csv.gz", "wt", newline="") as fh:
        header_done = False
        for st in us:
            n = 0
            d = START
            while d <= END:
                e = min(d + timedelta(days=31), END + timedelta(days=1))
                resp = get(IEM_MOS, {"station": st.code, "model": model, "sts": f"{d.isoformat()}T00:00Z",
                                     "ets": f"{e.isoformat()}T00:00Z", "format": "csv"}, tries=2, timeout=(10, 120))
                d = e
                if resp is None or not resp.text.strip():
                    continue
                lines = resp.text.strip().splitlines()
                if not lines[0].lower().startswith(("station", "runtime", "model")):
                    print(f"{st.code} {model}: unexpected reply {lines[0][:200]}", flush=True)
                    break
                if not header_done:
                    fh.write(lines[0] + "\n")
                    header_done = True
                for line in lines[1:]:
                    fh.write(line + "\n")
                    n += 1
                time.sleep(1)
            print(f"{st.code} {model}: {n} rows", flush=True)


if __name__ == "__main__":
    step = sys.argv[3]
    if step == "probe":
        print(",".join(probe()))
    elif step == "daily":
        daily_prev(sys.argv[6].split(","), int(sys.argv[4]), int(sys.argv[5]))
    elif step == "metar":
        metar_extra()
    elif step == "mos":
        for m in ("NBE", "MEX"):
            mos(m)
