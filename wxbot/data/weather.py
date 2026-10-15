"""Weather data sources.

* Forecasts: Open-Meteo multi-model hourly forecast at the resolution station,
  reduced to the daily max/min over the station's local calendar day.
* Historical forecasts (backtest): Open-Meteo Previous Runs API, i.e. what each
  model predicted 1..N days ahead, so the backtest never sees later runs.
* Observations (ground truth): hourly METAR reports from the Iowa Environmental
  Mesonet archive, the same reports Weather Underground shows for a station.

All free, no API keys. Each class is small so a source can be swapped out.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from wxbot.data.http import get_json, make_session
from wxbot.data.stations import Station

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
IEM_ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
# Open-Meteo publishes each model dataset's latest run at /data/<dataset>/static/meta.json
# (field last_run_initialisation_time, unix seconds). Forecast-API model name -> dataset.
# The "seamless" models blend regional and global runs; the global dataset's run
# time is used for them, so treat it as the latest run available at fetch time.
# A dataset whose data ends before now has been retired (cmc_gem_gdps stopped on
# 2026-05-26 when GEM moved to cmc_gem_gdps_15km): its run time cannot describe
# the values served, so it counts as unknown rather than stale.
OPEN_METEO_META = "https://api.open-meteo.com/data/{dataset}/static/meta.json"
OPEN_METEO_DATASETS = {
    "ecmwf_ifs025": "ecmwf_ifs025", "gfs_seamless": "ncep_gfs013", "icon_seamless": "dwd_icon",
    "gem_seamless": "cmc_gem_gdps_15km", "jma_seamless": "jma_gsm",
    # the models added for weighted-multimodel-v1
    "ecmwf_ifs": "ecmwf_ifs", "ecmwf_aifs025_single": "ecmwf_aifs025_single",
    "ukmo_seamless": "ukmo_global_deterministic_10km", "meteofrance_seamless": "meteofrance_arpege_world025",
    "cma_grapes_global": "cma_grapes_global", "ncep_nbm_conus": "ncep_nbm_conus", "ncep_hrrr_conus": "ncep_hrrr_conus",
}

MIN_HOURS_PER_DAY = 20  # a model's day needs this many hourly values to count
log = logging.getLogger("wxbot.weather")


def fetch_hourly(session, url: str, params: dict, models: list[str]) -> tuple[dict, dict]:
    """One request for all models; if the API rejects the set (e.g. one model is
    not offered by that endpoint), fall back to one request per model."""
    import requests
    try:
        data = get_json(session, url, {**params, "models": ",".join(models)})
        return data, data.get("hourly") or {}
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 400 or len(models) == 1:
            raise
        log.warning("%s rejected model list (%s); retrying per model", url, exc.response.text[:200])
    merged: dict = {}
    data = {}
    for m in models:
        try:
            data = get_json(session, url, {**params, "models": m})
        except requests.HTTPError as exc:
            log.warning("model %s unavailable at %s: %s", m, url, exc)
            continue
        hourly = data.get("hourly") or {}
        merged.setdefault("time", hourly.get("time"))
        for key, series in hourly.items():
            if key != "time":
                merged[f"{key}_{m}"] = series
    return data, merged


def daily_extreme(times: list[str], values: list, kind: str) -> dict[str, float]:
    """Hourly local-time series -> {local_date: max or min} for complete days."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for t, v in zip(times, values):
        if v is not None:
            by_day[t[:10]].append(float(v))
    fn = max if kind == "high" else min
    return {d: fn(vs) for d, vs in by_day.items() if len(vs) >= MIN_HOURS_PER_DAY}


def split_model_series(hourly: dict, variable: str, models: list[str]) -> dict[str, list]:
    """Open-Meteo names series '<variable>_<model>' when several models are asked for."""
    if len(models) == 1 and variable in hourly:
        return {models[0]: hourly[variable]}
    return {m: hourly[f"{variable}_{m}"] for m in models if f"{variable}_{m}" in hourly}


class ForecastSource(Protocol):
    """What the engine needs from a forecast provider. Add a provider by
    implementing this; nothing else in the pipeline changes."""
    source: str
    models: list[str]

    def fetch(self, station: Station, days: int = 5) -> tuple[dict, dict]:
        """-> ({kind: {local_date: {model: value_c}}}, meta). meta may carry
        "model_runs": {model: ISO time of the run the values came from}. An
        optional "hourly" kind, {local_date: {"time": [local ISO hours],
        "values": {model: [value_c or None]}}}, feeds the same-day model."""
        ...


class OpenMeteoForecast:
    source = "open-meteo"
    META_TTL_S = 1800

    def __init__(self, models: list[str], session=None):
        self.models = list(models)
        self.session = session or make_session()
        self._runs: dict[str, tuple[float, str | None]] = {}   # model -> (fetched monotonic, iso run)

    def model_runs(self) -> dict[str, str | None]:
        """Latest run time per model, cached for 30 minutes. A failed or unknown
        lookup gives None: the value is still used, its run time is unknown."""
        out = {}
        for m in self.models:
            hit = self._runs.get(m)
            if hit and time.monotonic() - hit[0] < self.META_TTL_S:
                out[m] = hit[1]
                continue
            run = None
            dataset = OPEN_METEO_DATASETS.get(m)
            if dataset:
                try:
                    meta = get_json(self.session, OPEN_METEO_META.format(dataset=dataset))
                    ts, data_end = meta.get("last_run_initialisation_time"), meta.get("data_end_time")
                    if data_end and int(data_end) < time.time():
                        log.warning("run time for %s unknown: dataset %s ended %s", m, dataset,
                                    datetime.fromtimestamp(int(data_end), UTC).isoformat())
                    elif ts:
                        run = datetime.fromtimestamp(int(ts), UTC).isoformat()
                except Exception as exc:  # noqa: BLE001 - metadata is optional
                    log.warning("run time for %s unavailable: %s", m, exc)
            self._runs[m] = (time.monotonic(), run)
            out[m] = run
        return out

    def fetch(self, station: Station, days: int = 5) -> tuple[dict, dict]:
        """-> ({kind: {local_date: {model: value_c}}, "hourly": {local_date: {"time": [...],
        "values": {model: [...]}}}}, request_meta)."""
        params = {
            "latitude": station.lat, "longitude": station.lon, "hourly": "temperature_2m",
            "timezone": station.tz, "forecast_days": days, "past_days": 1, "temperature_unit": "celsius",
        }
        data, hourly = fetch_hourly(self.session, OPEN_METEO, params, self.models)
        params["models"] = ",".join(self.models)
        times = hourly.get("time") or []
        out: dict[str, dict] = {"high": defaultdict(dict), "low": defaultdict(dict)}
        hours: dict[str, list[int]] = defaultdict(list)   # local date -> indexes of its hours
        for i, t in enumerate(times):
            hours[t[:10]].append(i)
        by_hour: dict[str, dict] = {d: {"time": [times[i] for i in idx], "values": {}} for d, idx in hours.items()}
        for model, series in split_model_series(hourly, "temperature_2m", self.models).items():
            for kind in ("high", "low"):
                for d, v in daily_extreme(times, series, kind).items():
                    out[kind][d][model] = round(v, 2)
            for d, idx in hours.items():
                by_hour[d]["values"][model] = [None if series[i] is None else round(float(series[i]), 2) for i in idx]
        meta = {"url": OPEN_METEO, "params": params, "model_runs": self.model_runs(),
                "generationtime_ms": data.get("generationtime_ms"), "timezone": data.get("timezone")}
        return {**{k: dict(v) for k, v in out.items()}, "hourly": by_hour}, meta


class OpenMeteoPreviousRuns:
    """Archived forecasts as issued N days before the target hour (no look-ahead)."""
    source = "open-meteo-previous-runs"

    def __init__(self, models: list[str], session=None):
        self.models = list(models)
        self.session = session or make_session()

    def fetch(self, station: Station, start: date, end: date, leads: list[int]) -> dict:
        """-> {lead: {kind: {local_date: {model: value_c}}}}"""
        variables = [f"temperature_2m_previous_day{lead}" for lead in leads]
        params = {
            "latitude": station.lat, "longitude": station.lon, "hourly": ",".join(variables),
            "timezone": station.tz, "start_date": start.isoformat(), "end_date": end.isoformat(),
        }
        _, hourly = fetch_hourly(self.session, PREVIOUS_RUNS, params, self.models)
        times = hourly.get("time") or []
        out: dict = {}
        for lead, var in zip(leads, variables):
            out[lead] = {"high": defaultdict(dict), "low": defaultdict(dict)}
            for model, series in split_model_series(hourly, var, self.models).items():
                for kind in ("high", "low"):
                    for d, v in daily_extreme(times, series, kind).items():
                        out[lead][kind][d][model] = v
        return out


class IEMObservations:
    """Station daily high/low in degC from archived METARs (Iowa Environmental
    Mesonet), and the individual reports of the day so far for the same-day model."""
    source = "iem-metar"

    def __init__(self, session=None):
        self.session = session or make_session()

    @staticmethod
    def iem_id(code: str) -> str:
        # IEM keys US ASOS stations by their 3-letter id (KLGA -> LGA)
        return code[1:] if len(code) == 4 and code.startswith("K") else code

    def fetch(self, station: Station, start: date, end: date) -> dict[str, dict[str, tuple[float, int]]]:
        """-> {kind: {local_date: (value_c, n_reports)}} for local days start..end."""
        tz = ZoneInfo(station.tz)
        utc_start = datetime.combine(start, datetime.min.time(), tz).astimezone(UTC) - timedelta(hours=1)
        utc_end = (datetime.combine(end + timedelta(days=1), datetime.min.time(), tz).astimezone(UTC)
                   + timedelta(hours=1))
        return self.parse_csv(self._get(station, utc_start, utc_end), station, start, end)

    def fetch_reports(self, station: Station, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        """The station's reports from `start` to `end` (UTC): [(report time, temp_c)], oldest first."""
        text = self._get(station, start, end + timedelta(hours=1))   # the API's end is a whole hour
        return [(t, v) for t, v in self.parse_reports(text) if start <= t <= end]

    def _get(self, station: Station, utc_start: datetime, utc_end: datetime) -> str:
        params = [
            ("station", self.iem_id(station.code)), ("data", "tmpf"),
            ("year1", utc_start.year), ("month1", utc_start.month), ("day1", utc_start.day),
            ("hour1", utc_start.hour),
            ("year2", utc_end.year), ("month2", utc_end.month), ("day2", utc_end.day),
            ("hour2", utc_end.hour),
            ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"),
            ("trace", "T"), ("direct", "no"), ("report_type", "3"), ("report_type", "4"),
        ]
        resp = self.session.get(IEM_ASOS, params=params, timeout=(10, 60))
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def parse_reports(text: str) -> list[tuple[datetime, float]]:
        """IEM CSV -> [(report time UTC, temp_c)], oldest first; missing values skipped."""
        out = []
        for row in csv.DictReader(io.StringIO(text)):
            raw = (row.get("tmpf") or "").strip()
            if raw in ("", "M", "T"):
                continue
            try:
                ts = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                out.append((ts, (float(raw) - 32.0) * 5.0 / 9.0))
            except (KeyError, ValueError):
                continue
        return sorted(out)

    @staticmethod
    def parse_csv(text: str, station: Station, start: date, end: date) -> dict:
        tz = ZoneInfo(station.tz)
        by_day: dict[str, list[float]] = defaultdict(list)
        for ts, temp_c in IEMObservations.parse_reports(text):
            local_day = ts.astimezone(tz).date()
            if start <= local_day <= end:
                by_day[local_day.isoformat()].append(temp_c)
        out: dict = {"high": {}, "low": {}}
        for d, temps in by_day.items():
            if len(temps) >= 18:  # at least ~hourly coverage of the day
                out["high"][d] = (round(max(temps), 2), len(temps))
                out["low"][d] = (round(min(temps), 2), len(temps))
        return out
