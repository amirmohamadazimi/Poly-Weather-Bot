"""Load past observed daily highs and lows (IEM METAR archive) so the
climatology baseline has years of history to draw on.

Rows are stored like any other observation, with fetched_at = the load time,
so a prediction only uses them once they were actually loaded.
"""
from __future__ import annotations

from datetime import date, timedelta

from wxbot.data.stations import STATIONS


def load_history(engine, years: int, today: date, stations: list[str] | None = None) -> dict:
    """Fetch up to `years` years before `today`, one request per station-year."""
    codes = stations or sorted(c for c, s in STATIONS.items() if s.enabled)
    out = {}
    for code in codes:
        st = STATIONS[code]
        stored = failed = 0
        end = today - timedelta(days=1)
        for _ in range(years):
            start = end - timedelta(days=364)
            try:
                stored += engine.store_observations(code, engine.observer.fetch(st, start, end), quiet=True)
            except Exception as exc:  # one bad year never stops the rest
                failed += 1
                engine.db.log_event("WARNING", "history", f"{code} {start}..{end}: {type(exc).__name__}: {exc}")
            end = start - timedelta(days=1)
        engine.db.log_event("INFO", "history", f"{code}: {stored} observed highs/lows stored, {failed} years failed")
        out[code] = {"stored": stored, "failed_years": failed}
    engine.db.set_state("history_loaded_at", engine.clock().isoformat())
    return out
