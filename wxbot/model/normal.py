"""v1 model: normal distribution around the bias-corrected multi-model mean.

P(bucket) = P(lo - 0.5 <= T < hi + 0.5) in the market's unit, because the
official reading is reported in whole degrees. The spread is the larger of
the backtest-calibrated error and the disagreement between models, and the
result is clamped so no outcome is ever treated as certain.
"""
from __future__ import annotations

import math
import statistics

from wxbot.data.polymarket import Bucket
from wxbot.model.base import Calibration, Prediction


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def c_to_unit(value_c: float, unit: str) -> float:
    return value_c * 9.0 / 5.0 + 32.0 if unit == "F" else value_c


def bucket_probability(bucket: Bucket, mu: float, sigma: float) -> float:
    """mu/sigma already in the bucket's unit."""
    upper = 1.0 if bucket.hi is None else norm_cdf((bucket.hi + 0.5 - mu) / sigma)
    lower = 0.0 if bucket.lo is None else norm_cdf((bucket.lo - 0.5 - mu) / sigma)
    return max(0.0, upper - lower)


def default_calibration(default_sigma_c: list[float], lead_days: int) -> Calibration:
    idx = min(max(lead_days, 0), len(default_sigma_c) - 1)
    return Calibration(bias_c=0.0, sigma_c=float(default_sigma_c[idx]), n=0, source="default")


class NormalMultiModel:
    def __init__(self, version: str = "normal-multimodel-v1", prob_floor: float = 0.01,
                 prob_ceiling: float = 0.99):
        self.version = version
        self.prob_floor = prob_floor
        self.prob_ceiling = prob_ceiling

    @staticmethod
    def combine(model_values_c: dict[str, float]) -> tuple[float, float]:
        vals = list(model_values_c.values())
        mean = statistics.fmean(vals)
        spread = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        return mean, spread

    def predict(self, bucket: Bucket, kind: str, model_values_c: dict[str, float],
                lead_days: int, calibration: Calibration) -> Prediction:
        if not model_values_c:
            raise ValueError("no model values")
        raw_mean, spread = self.combine(model_values_c)
        mu_c = raw_mean - calibration.bias_c
        sigma_c = max(calibration.sigma_c, spread, 0.3)
        scale = 9.0 / 5.0 if bucket.unit == "F" else 1.0
        mu_u = c_to_unit(mu_c, bucket.unit)
        sigma_u = sigma_c * scale
        raw_p = bucket_probability(bucket, mu_u, sigma_u)
        p = min(self.prob_ceiling, max(self.prob_floor, raw_p))
        return Prediction(
            p_yes=p, mu_c=mu_c, sigma_c=sigma_c, model_version=self.version,
            inputs={
                "kind": kind, "lead_days": lead_days, "model_values_c": model_values_c,
                "raw_mean_c": round(raw_mean, 3), "model_spread_c": round(spread, 3),
                "calibration": vars(calibration), "unit": bucket.unit,
                "bucket": {"lo": bucket.lo, "hi": bucket.hi},
                "mu_unit": round(mu_u, 3), "sigma_unit": round(sigma_u, 3),
                "raw_p_yes": raw_p,
            },
        )
