"""Prediction model interface. Swap models by implementing `Predictor`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from wxbot.data.polymarket import Bucket


@dataclass
class Calibration:
    bias_c: float        # mean(forecast - observed); subtracted from the forecast
    sigma_c: float       # std-dev of the forecast error
    n: int
    source: str          # "backtest" | "default"


@dataclass
class Prediction:
    p_yes: float
    mu_c: float
    sigma_c: float
    model_version: str
    inputs: dict = field(default_factory=dict)


class Predictor(Protocol):
    name: str
    version: str
    calibration_version: str    # how its inputs are calibrated ("none" for baselines)
    params: dict                # stored in the model registry

    def predict(self, bucket: Bucket, kind: str, model_values_c: dict[str, float], lead_days: int,
                calibration: Calibration, features=None) -> Prediction | None:
        """`features` is a wxbot.features.Features; None means the model declines to predict."""
