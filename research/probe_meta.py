"""Research only: which Open-Meteo dataset metadata files exist, with their latest
run time, and which time step each forecast model returns hourly."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import requests

META = "https://api.open-meteo.com/data/{}/static/meta.json"
DATASETS = [
    "ecmwf_ifs025", "ecmwf_ifs", "ecmwf_ifs04", "ecmwf_aifs025_single", "ecmwf_aifs025", "ncep_gfs013", "ncep_gfs025",
    "dwd_icon", "cmc_gem_gdps", "jma_gsm", "ukmo_global_deterministic_10km", "ukmo_uk_deterministic_2km",
    "meteofrance_arpege_world025", "meteofrance_arpege_europe", "meteofrance_arome_france0025", "cma_grapes_global",
    "ncep_nbm_conus", "ncep_hrrr_conus", "ncep_hrrr_conus_15min",
]
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless", "jma_seamless", "ecmwf_ifs",
          "ecmwf_aifs025_single", "ukmo_seamless", "meteofrance_seamless", "cma_grapes_global", "ncep_nbm_conus",
          "ncep_hrrr_conus"]


def main() -> None:
    out = {"checked_at": datetime.now(UTC).isoformat(), "meta": {}, "hourly": {}}
    for ds in DATASETS:
        try:
            r = requests.get(META.format(ds), timeout=30)
            j = r.json() if r.ok else None
            ts = j.get("last_run_initialisation_time") if j else None
            out["meta"][ds] = {"status": r.status_code, "last_run": ts and datetime.fromtimestamp(int(ts), UTC).isoformat(),
                               "keys": sorted(j)[:12] if j else None}
        except Exception as exc:  # noqa: BLE001
            out["meta"][ds] = {"error": str(exc)}
        print("meta", ds, json.dumps(out["meta"][ds]), flush=True)
        time.sleep(0.5)
    for lat, lon, name in ((40.7769, -73.874, "KLGA"), (51.5048, 0.0495, "EGLC")):
        for m in MODELS:
            try:
                r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=60, params={
                    "latitude": lat, "longitude": lon, "hourly": "temperature_2m", "models": m, "forecast_days": 3,
                    "past_days": 1, "timezone": "UTC"})
                vals = (r.json().get("hourly") or {}).get("temperature_2m") if r.ok else None
                res = {"status": r.status_code, "n": len(vals or []), "non_null": sum(v is not None for v in vals or [])}
            except Exception as exc:  # noqa: BLE001
                res = {"error": str(exc)}
            out["hourly"][f"{name}:{m}"] = res
            print("hourly", name, m, json.dumps(res), flush=True)
            time.sleep(0.5)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
