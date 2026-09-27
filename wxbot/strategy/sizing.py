"""Position sizing. Add a new sizer by adding a class with `stake(...)`."""
from __future__ import annotations


class FixedFraction:
    name = "fixed_fraction"

    def __init__(self, fraction: float):
        self.fraction = fraction

    def stake(self, bankroll: float, model_prob: float, price: float) -> float:
        return bankroll * self.fraction


class FractionalKelly:
    """Kelly for a binary share bought at `price` paying 1: f* = (p - price) / (1 - price)."""
    name = "fractional_kelly"

    def __init__(self, multiplier: float):
        self.multiplier = multiplier

    def stake(self, bankroll: float, model_prob: float, price: float) -> float:
        if price >= 1.0:
            return 0.0
        f = (model_prob - price) / (1.0 - price)
        return max(0.0, bankroll * f * self.multiplier)


def make_sizer(cfg) -> FixedFraction | FractionalKelly:
    if cfg.sizing.method == "fractional_kelly":
        return FractionalKelly(cfg.sizing.kelly_multiplier)
    if cfg.sizing.method == "fixed_fraction":
        return FixedFraction(cfg.sizing.fraction)
    raise ValueError(f"unknown sizing method {cfg.sizing.method!r}")
