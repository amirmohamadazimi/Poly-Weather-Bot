"""v2 production model: skill-weighted multi-model forecast with learned station biases.

For every station, temperature kind and lead, each weather model's recent
errors against the observed daily high (or low) give, as exponentially
weighted (EW) means over the observed days so far:

    bias_m  of (observed - forecast_m), half-life BIAS_HALF_LIFE days
    mse_m   of (observed - (forecast_m + bias_m))^2, half-life SD_HALF_LIFE days,
            where bias_m is the bias as known the day before

The forecast is the weighted mean of the bias-corrected models present today,

    mu = sum_m w_m (forecast_m + bias_m) / sum_m w_m,   w_m = 1 / max(mse_m, MIN_MSE),

and its spread

    log sigma = a0 + a1 log(max(sd, 0.2)) + a2 log(spread + 0.1),

where sd is the EW (SD_HALF_LIFE) root mean square error of mu itself on the
days so far, spread the standard deviation of today's bias-corrected model
values, and a0..a2 per kind and lead come from weighted_params.json (fitted by
research/fit_weighted.py). P(bucket) is then taken as in normal-multimodel-v1.

The errors come from Open-Meteo Previous Runs (previous_dayN: what each model
forecast N days ahead) against the station's METAR highs and lows, refreshed
once a day (wxbot/learning/model_stats.py). Lead L uses previous_day max(L, 1).
Backtested on Jun 1 to Sep 26 2026 (each day priced with the stats the bot
would have had) the day-ahead high's mean absolute error fell from 0.89 C
(normal-multimodel-v1), 0.86 C (five-model mean with the same rolling bias)
and 1.18 C (raw five-model mean) to 0.81 C. Against liquid market prices it
is still the weaker forecast (README "Production model"), so it bets only
through the market anchor like every production model.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from wxbot.data.polymarket import Bucket
from wxbot.model.base import Calibration, Prediction
from wxbot.model.normal import MIN_SIGMA_C, bucket_probability, c_to_unit

PARAMS_FILE = Path(__file__).with_name("weighted_params.json")
BIAS_HALF_LIFE = 10.0
SD_HALF_LIFE = 30.0
MIN_DAYS = 10          # a model needs this many observed days before it is used
MIN_MSE = 0.05


class EW:
    """Exponentially weighted mean over the values added so far (pandas
    ewm(halflife).mean() with adjust=True and missing values skipped)."""
    __slots__ = ("decay", "num", "den", "n")

    def __init__(self, half_life: float, num: float = 0.0, den: float = 0.0, n: int = 0):
        self.decay = math.exp(-math.log(2.0) / half_life)
        self.num, self.den, self.n = num, den, n

    def add(self, x: float) -> None:
        self.num = self.num * self.decay + x
        self.den = self.den * self.decay + 1.0
        self.n += 1

    @property
    def value(self) -> float | None:
        return self.num / self.den if self.n >= MIN_DAYS and self.den > 0 else None


@dataclass
class Stats:
    """One station, kind and lead: per-model bias and error, and the combined forecast's error."""
    bias: dict[str, float] = field(default_factory=dict)
    mse: dict[str, float] = field(default_factory=dict)
    sd: float | None = None
    n_days: int = 0
    last_day: str | None = None

    def as_dict(self) -> dict:
        return {"bias": {m: round(v, 4) for m, v in self.bias.items()},
                "mse": {m: round(v, 4) for m, v in self.mse.items()},
                "sd": None if self.sd is None else round(self.sd, 4), "n_days": self.n_days, "last_day": self.last_day}

    @classmethod
    def from_dict(cls, d: dict) -> Stats:
        return cls(bias=dict(d.get("bias") or {}), mse=dict(d.get("mse") or {}), sd=d.get("sd"),
                   n_days=int(d.get("n_days") or 0), last_day=d.get("last_day"))


def combine(values_c: dict[str, float], stats: Stats) -> tuple[float, float, dict[str, float]] | None:
    """-> (mu, spread of the bias-corrected values, weights) from the models
    that have both a value today and enough history; None if there are none."""
    corrected, weights = {}, {}
    for m, v in values_c.items():
        if m in stats.bias and m in stats.mse:
            corrected[m] = v + stats.bias[m]
            weights[m] = 1.0 / max(stats.mse[m], MIN_MSE)
    if not corrected:
        return None
    total = sum(weights.values())
    mu = sum(weights[m] * corrected[m] for m in corrected) / total
    vals = list(corrected.values())
    spread = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return mu, spread, {m: w / total for m, w in weights.items()}


def walk(days: list[tuple[str, dict[str, float], float | None]],
         states: list[tuple[str, Stats]] | None = None) -> tuple[Stats, list[dict]]:
    """Run through (day, {model: forecast_c}, observed_c or None) in date order.
    Each day is priced with what was known before it, then its observation
    updates the state. -> (the state after the last day, per-day records of
    {day, mu, spread, sd, obs} for the days that could be priced). With
    `states`, the state after each observed day is appended to it as (day, Stats):
    what a refresh whose window ended that day would load."""
    bias: dict[str, EW] = {}
    mse: dict[str, EW] = {}
    sd = EW(SD_HALF_LIFE)
    out, n_days, last = [], 0, None
    for day, values, obs in days:
        state = _snapshot(bias, mse, sd)
        c = combine(values, state)
        if c is not None:
            out.append({"day": day, "mu": c[0], "spread": c[1], "sd": state.sd, "obs": obs})
        if obs is None:
            continue
        n_days, last = n_days + 1, day
        for m, v in values.items():
            b = bias.get(m)
            if b is not None and b.value is not None:
                mse.setdefault(m, EW(SD_HALF_LIFE)).add((obs - v - b.value) ** 2)
            bias.setdefault(m, EW(BIAS_HALF_LIFE)).add(obs - v)
        if c is not None:
            sd.add((obs - c[0]) ** 2)
        if states is not None:
            states.append((day, _snapshot(bias, mse, sd, n_days, last)))
    return _snapshot(bias, mse, sd, n_days, last), out


def _snapshot(bias: dict[str, EW], mse: dict[str, EW], sd: EW, n_days: int = 0, last: str | None = None) -> Stats:
    return Stats(bias={m: e.value for m, e in bias.items() if e.value is not None},
                 mse={m: e.value for m, e in mse.items() if e.value is not None},
                 sd=_sqrt(sd.value), n_days=n_days, last_day=last)


def _sqrt(x: float | None) -> float | None:
    return None if x is None else math.sqrt(x)


def sigma(a: list[float], sd: float, spread: float) -> float:
    return math.exp(a[0] + a[1] * math.log(max(sd, 0.2)) + a[2] * math.log(spread + 0.1))


def load_params(path: Path = PARAMS_FILE) -> dict:
    return json.loads(path.read_text())


class WeightedMultiModel:
    """Production model v2. `stats` maps (station, kind, lead) to Stats; the
    engine sets it from the latest daily fit before each cycle's predictions."""
    name = "weighted-multimodel"
    calibration_version = "ew-model-bias-v1"   # per station/kind/lead/model EW bias and error, refreshed daily

    def __init__(self, version: str = "weighted-multimodel-v1", prob_floor: float = 0.01, prob_ceiling: float = 0.99,
                 fitted: dict | None = None, min_models: int = 3):
        self.version = version
        self.prob_floor, self.prob_ceiling = prob_floor, prob_ceiling
        self.fitted = fitted if fitted is not None else load_params()
        self.min_models = min_models
        self.stats: dict[tuple[str, str, int], Stats] = {}
        digest = hashlib.sha256(json.dumps(self.fitted, sort_keys=True).encode()).hexdigest()[:16]
        self.params = {"prob_floor": prob_floor, "prob_ceiling": prob_ceiling, "params_sha256": digest,
                       "bias_half_life_days": BIAS_HALF_LIFE, "sd_half_life_days": SD_HALF_LIFE,
                       "min_days": MIN_DAYS, "min_mse": MIN_MSE, "min_models": min_models}

    def predict(self, bucket: Bucket, kind: str, model_values_c: dict[str, float], lead_days: int,
                calibration: Calibration, features=None) -> Prediction | None:
        """None (no prediction, so no signal) without a station, without the
        day's stats, or with fewer than min_models models that have them."""
        station = (features.values.get("station") if features is not None else None)
        lead = min(max(lead_days, 1), len(self.fitted["sigma"][kind]))
        st = self.stats.get((station, kind, lead)) if station else None
        if st is None or st.sd is None:
            return None
        c = combine(model_values_c, st)
        if c is None or len(c[2]) < self.min_models:
            return None
        mu_c, spread, weights = c
        a = self.fitted["sigma"][kind][lead - 1]
        sigma_c = max(sigma(a, st.sd, spread), MIN_SIGMA_C)
        scale = 9.0 / 5.0 if bucket.unit == "F" else 1.0
        mu_u, sigma_u = c_to_unit(mu_c, bucket.unit), sigma_c * scale
        raw_p = bucket_probability(bucket, mu_u, sigma_u)
        p = min(self.prob_ceiling, max(self.prob_floor, raw_p))
        raw = list(model_values_c.values())
        return Prediction(p_yes=p, mu_c=mu_c, sigma_c=sigma_c, model_version=self.version, inputs={
            "kind": kind, "lead_days": lead_days, "stats_lead": lead, "model_values_c": model_values_c,
            # as normal-multimodel-v1 records it: the raw models' disagreement (error analysis, ledger)
            "model_spread_c": round(statistics.pstdev(raw), 3) if len(raw) > 1 else 0.0,
            "weights": {m: round(w, 4) for m, w in weights.items()},
            "bias_c": {m: round(st.bias[m], 3) for m in weights}, "corrected_spread_c": round(spread, 3),
            "error_sd_c": round(st.sd, 3), "stats_days": st.n_days, "stats_last_day": st.last_day,
            "unit": bucket.unit, "bucket": {"lo": bucket.lo, "hi": bucket.hi},
            "mu_unit": round(mu_u, 3), "sigma_unit": round(sigma_u, 3), "raw_p_yes": raw_p,
            "calibration": vars(calibration)})
