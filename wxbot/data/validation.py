"""Data validation: decide which inputs are fit to price a market.

Nothing is silently changed. The raw values stay in the database; validation
records which model values were rejected and why, and whether the snapshot as
a whole is usable. A snapshot that fails validation produces NO BET.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Quality:
    ok: bool
    clean: dict[str, float]                                # model -> value that passed
    rejected: dict[str, str] = field(default_factory=dict)  # model -> reason
    errors: list[str] = field(default_factory=list)         # block the snapshot
    warnings: list[str] = field(default_factory=list)       # recorded, do not block

    def as_dict(self) -> dict:
        return {"ok": self.ok, "n_clean": len(self.clean), "rejected": self.rejected,
                "errors": self.errors, "warnings": self.warnings}


def validate_forecast(values_c: dict[str, float], model_runs: dict[str, datetime | None],
                      now: datetime, rules) -> Quality:
    """values_c: {model: daily high/low in degC}. rules: the [validation] config
    section plus weather.min_models (passed as rules.min_models)."""
    clean, rejected, warnings = {}, {}, []
    for model, v in values_c.items():
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            rejected[model] = "not_a_number"
        elif not rules.min_temp_c <= v <= rules.max_temp_c:
            rejected[model] = "out_of_range"
        elif (run := model_runs.get(model)) is not None and \
                (now - run).total_seconds() / 3600 > rules.max_model_run_age_hours:
            rejected[model] = "stale_model_run"
        else:
            clean[model] = float(v)
    if len(clean) >= 3:
        for model, v in clean.items():
            others = [x for m, x in clean.items() if m != model]
            if abs(v - statistics.median(others)) > rules.outlier_c:
                warnings.append(f"outlier:{model}")
    errors = []
    if len(clean) < rules.min_models:
        errors.append(f"too_few_valid_models:{len(clean)}<{rules.min_models}")
    return Quality(ok=not errors, clean=clean, rejected=rejected, errors=errors, warnings=warnings)


def validate_observation(value_c: float, n_reports: int | None, rules) -> str | None:
    """-> None when usable, else the reason it is not."""
    if value_c is None or not math.isfinite(value_c):
        return "not_a_number"
    if not rules.min_temp_c <= value_c <= rules.max_temp_c:
        return "out_of_range"
    if n_reports is not None and n_reports < rules.min_obs_reports:
        return "too_few_reports"
    return None
