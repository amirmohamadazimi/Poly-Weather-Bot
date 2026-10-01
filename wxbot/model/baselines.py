"""Baselines priced next to the production model on every market.

They run as "shadow" models: their predictions are stored and scored (see
`evaluation.metrics.model_comparison`) but never create signals or bets. A
model that cannot beat them has no skill worth trading on.
"""
from __future__ import annotations

import math
import statistics

from wxbot.data.polymarket import Bucket
from wxbot.model.base import Calibration, Prediction
from wxbot.model.normal import NormalMultiModel, c_to_unit, default_calibration


class RawForecast:
    """The multi-model mean as issued, with no station bias correction and the
    default error spread for the lead time: the production model without its
    calibration."""
    name = "raw-forecast"
    calibration_version = "none"

    def __init__(self, default_sigma_c: list[float], prob_floor: float = 0.01, prob_ceiling: float = 0.99,
                 version: str = "raw-forecast-v1"):
        self.version = version
        self.default_sigma_c = list(default_sigma_c)
        self._model = NormalMultiModel(version, prob_floor, prob_ceiling)
        self.params = {**self._model.params, "default_sigma_c": self.default_sigma_c}

    def predict(self, bucket: Bucket, kind: str, model_values_c: dict[str, float], lead_days: int,
                calibration: Calibration, features=None) -> Prediction:
        return self._model.predict(bucket, kind, model_values_c, lead_days,
                                   default_calibration(self.default_sigma_c, lead_days))


def whole_degrees(x: float) -> int:
    """Round half up, as a whole-degree reading would be reported."""
    return math.floor(x + 0.5)


class Climatology:
    """How often the observed high (or low), in whole degrees of the bucket's
    unit, fell in the bucket on past days within `window_days` of the same
    calendar date (any year). Ignores the forecast. With fewer than
    `min_samples` days it makes no prediction."""
    name = "climatology"
    calibration_version = "none"

    def __init__(self, window_days: int = 7, min_samples: int = 20, prob_floor: float = 0.01,
                 prob_ceiling: float = 0.99, version: str = "climatology-v1"):
        self.version = version
        self.window_days = window_days
        self.min_samples = min_samples
        self.prob_floor = prob_floor
        self.prob_ceiling = prob_ceiling
        self.params = {"window_days": window_days, "min_samples": min_samples,
                       "prob_floor": prob_floor, "prob_ceiling": prob_ceiling}

    def predict(self, bucket: Bucket, kind: str, model_values_c: dict[str, float], lead_days: int,
                calibration: Calibration, features=None) -> Prediction | None:
        samples = features.climatology_c if features is not None else []
        if len(samples) < self.min_samples:
            return None
        readings = [whole_degrees(c_to_unit(v, bucket.unit)) for v in samples]
        k = sum((bucket.lo is None or r >= bucket.lo) and (bucket.hi is None or r <= bucket.hi) for r in readings)
        raw_p = k / len(samples)
        return Prediction(
            p_yes=min(self.prob_ceiling, max(self.prob_floor, raw_p)), mu_c=statistics.fmean(samples),
            sigma_c=statistics.pstdev(samples), model_version=self.version,
            inputs={"n": len(samples), "k": k, "raw_p_yes": raw_p, "window_days": self.window_days})
