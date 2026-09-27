"""Export the full audit trail (every table) as CSV files, individually or zipped."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import select

from wxbot.db import EXPORT_TABLES, Database, metadata


def table_csv(db: Database, name: str) -> str:
    table = metadata.tables[name]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.name for c in table.columns])
    with db.engine.connect() as conn:
        for row in conn.execute(select(table).order_by(*table.primary_key.columns)):
            writer.writerow([json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in row])
    return buf.getvalue()


def export_zip_bytes(db: Database, report: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in EXPORT_TABLES:
            zf.writestr(f"{name}.csv", table_csv(db, name))
        if report is not None:
            zf.writestr("report.json", json.dumps(report, indent=2, default=str))
    return buf.getvalue()


def export_to_dir(db: Database, out_dir: str | Path, report: dict | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in EXPORT_TABLES:
        (out / f"{name}.csv").write_text(table_csv(db, name), encoding="utf-8")
    if report is not None:
        (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return out
