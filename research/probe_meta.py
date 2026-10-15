"""Research only: which Open-Meteo dataset metadata files exist, with their latest
run time, and which time step each forecast model returns hourly."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import requests

META = "https://api.open-meteo.com/data/{}/static/meta.json"
DATASETS = [
    "cmc_gem_gdps", "cmc_gem_gdps_15km", "cmc_gem_gdps_25km", "cmc_gem_gdps15", "cmc_gem_global", "cmc_gdps",
    "cmc_gem_rdps", "cmc_gem_hrdps", "cmc_gem_hrdps_continental", "cmc_gem_hrdps_west", "cmc_gem_geps",
    "cmc_gem_geps025", "gem_global", "gem_seamless", "ncep_gfs013", "jma_gsm", "dwd_icon",
]
MODELS = ["gem_seamless", "gem_global", "gem_regional", "gem_hrdps_continental"]


def main() -> None:
    out = {"checked_at": datetime.now(UTC).isoformat(), "meta": {}, "hourly": {}}
    for ds in DATASETS:
        try:
            r = requests.get(META.format(ds), timeout=30)
            j = r.json() if r.ok else None
            ts = j.get("last_run_initialisation_time") if j else None
            out["meta"][ds] = {"status": r.status_code, "last_run": ts and datetime.fromtimestamp(int(ts), UTC).isoformat(),
                               "meta": {k: v for k, v in (j or {}).items() if k != "crs_wkt"}}
        except Exception as exc:  # noqa: BLE001
            out["meta"][ds] = {"error": str(exc)}
        print("meta", ds, json.dumps(out["meta"][ds]), flush=True)
        time.sleep(0.5)
    for lat, lon, name in ((40.7769, -73.874, "KLGA"),):
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
