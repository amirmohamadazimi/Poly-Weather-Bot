"""US MOS guidance from the IEM archive for the forecast-model study (run by
.github/workflows/research-mos.yml): NBM extended ("NBE": txn = 12 h max/min,
xnd = its spread) and GFS extended ("MEX": n_x = max/min), every run.

Writes research/data/mos_fixed.csv.gz: model, station, runtime, ftime, value_f, sd_f.
The archive's column set changed over the year, so each reply is parsed by its
own header.

    python -m research.fetch_mos 2025-10-01 2026-10-15
"""
from __future__ import annotations

import csv
import gzip
import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from research.fetch_models import EXTRA, IEM_MOS, get
from wxbot.data.stations import _STATIONS

START, END = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
OUT = Path(__file__).parent / "data"
VALUE = {"NBE": "txn", "MEX": "n_x"}

if __name__ == "__main__":
    us = [s for s in _STATIONS + EXTRA if s.code.startswith("K")]
    with gzip.open(OUT / "mos_fixed.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "station", "runtime", "ftime", "value_f", "sd_f"])
        for model, col in VALUE.items():
            for st in us:
                n, d = 0, START
                while d <= END:
                    e = min(d + timedelta(days=31), END + timedelta(days=1))
                    resp = get(IEM_MOS, {"station": st.code, "model": model, "sts": f"{d.isoformat()}T00:00Z",
                                         "ets": f"{e.isoformat()}T00:00Z", "format": "csv"}, tries=3, timeout=(10, 120))
                    d = e
                    if resp is None or not resp.text.strip():
                        continue
                    for row in csv.DictReader(io.StringIO(resp.text)):
                        v = (row.get(col) or "").strip()
                        if v in ("", "M"):
                            continue
                        w.writerow([model, st.code, row["runtime"], row["ftime"], v, (row.get("xnd") or "").strip()])
                        n += 1
                    time.sleep(0.5)
                print(f"{st.code} {model}: {n} rows", flush=True)
