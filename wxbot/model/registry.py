"""Model registry: every model version the bot has run, and which one trades.

`production` is [model] version: its predictions create signals. `shadow`
models ([model] shadow_models) are priced on every market and scored, never
traded. The same-day model ([nowcast]) is registered as a shadow too: it can
create signals only through its own market anchor (wxbot/model/nowcast.py).
A version that leaves the config becomes `retired`. Rows are never deleted,
so every stored prediction can be traced to its model.

With the v2 model (weighted-multimodel) in production, [weather] models lists
every model it combines, and the models built before it (normal-multimodel-v1,
raw-forecast-v1, the same-day model, the station bias/spread sets and the
backtests that fit them) still see only the five they were built on, [model]
v1_models, so they behave exactly as before.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from wxbot.db import Database, model_versions
from wxbot.features import FEATURE_SET
from wxbot.model.baselines import Climatology, RawForecast
from wxbot.model.normal import NormalMultiModel
from wxbot.model.nowcast import Nowcast, load_params
from wxbot.model.weighted import WeightedMultiModel

V1_VERSION = "normal-multimodel-v1"


def is_weighted(cfg) -> bool:
    """True when production is the v2 model, which learns its own biases daily
    (wxbot/learning/model_stats.py) instead of using the station bias/spread sets."""
    return str(cfg.model.version).startswith(WeightedMultiModel.name)


def v1_models(cfg) -> list[str]:
    """The weather models the models built before v2 average."""
    return list(cfg.model.v1_models) if is_weighted(cfg) else list(cfg.weather.models)


def production_model(cfg):
    m = cfg.model
    if is_weighted(cfg):
        return WeightedMultiModel(m.version, m.prob_floor, m.prob_ceiling, min_models=int(cfg.weather.min_models))
    return NormalMultiModel(m.version, m.prob_floor, m.prob_ceiling)


def param_model(cfg) -> NormalMultiModel:
    """The model the station bias/spread sets are for (retraining, market backtest)."""
    m = cfg.model
    return NormalMultiModel(V1_VERSION if is_weighted(cfg) else m.version, m.prob_floor, m.prob_ceiling)


class OnlyModels:
    """A model priced on its own weather models out of the longer list fetched
    for the v2 model; version, name and params are the wrapped model's."""

    def __init__(self, model, models: list[str]):
        self.model, self.models = model, set(models)

    def __getattr__(self, name: str):
        return getattr(self.model, name)

    def predict(self, bucket, kind: str, model_values_c: dict[str, float], lead_days: int, calibration,
                features=None):
        values = {k: v for k, v in model_values_c.items() if k in self.models}
        return self.model.predict(bucket, kind, values, lead_days, calibration, features) if values else None


def shadow_models(cfg) -> list:
    """[model] shadow_models; one with the production version is skipped (it is production)."""
    m = cfg.model
    known = {
        V1_VERSION: lambda: NormalMultiModel(V1_VERSION, m.prob_floor, m.prob_ceiling),
        "raw-forecast-v1": lambda: RawForecast(list(m.default_sigma_c), m.prob_floor, m.prob_ceiling),
        "climatology-v1": lambda: Climatology(m.get("climatology_window_days", 7),
                                              m.get("climatology_min_samples", 20), m.prob_floor, m.prob_ceiling),
    }
    unknown = [v for v in m.get("shadow_models", []) if v not in known]
    if unknown:
        raise ValueError(f"unknown shadow model(s) in [model] shadow_models: {unknown}; known: {sorted(known)}")
    models = [known[v]() for v in m.get("shadow_models", []) if v != m.version]
    return [OnlyModels(x, v1_models(cfg)) for x in models] if is_weighted(cfg) else models


def nowcast_model(cfg) -> Nowcast | None:
    """The same-day model ([nowcast], wxbot/model/nowcast.py), or None when it is off."""
    c = cfg.get("nowcast")
    if not c or not c.enabled:
        return None
    return Nowcast(load_params(), c.prob_floor, c.prob_ceiling, c.max_report_age_minutes, c.min_models,
                   models=v1_models(cfg) if is_weighted(cfg) else None)


def sync_registry(db: Database, production, shadows: list, now: datetime) -> list[str]:
    """Make the registry match the running models; returns what changed."""
    mv = model_versions.c
    roles = {production.version: "production", **{s.version: "shadow" for s in shadows}}
    models = {m.version: m for m in [production, *shadows]}
    rows = db.rows(select(mv.version, mv.role, mv.params))
    current = {r["version"]: r["role"] for r in rows}
    changes = [f"{r['version']}: params differ from the registry ({r['params']} -> {models[r['version']].params}); "
               "bump the version when a model changes" for r in rows
               if r["version"] in models and r["params"] != models[r["version"]].params]
    with db.engine.begin() as conn:
        for version, role in roles.items():
            m = models[version]
            if version not in current:
                conn.execute(model_versions.insert().values(
                    name=m.name, version=version, calibration_version=m.calibration_version,
                    feature_set=getattr(m, "feature_set", FEATURE_SET), params=m.params, role=role, created_at=now,
                    role_changed_at=now))
                changes.append(f"{version} registered as {role}")
            elif current[version] != role:
                conn.execute(update(model_versions).where(mv.version == version).values(role=role, role_changed_at=now))
                changes.append(f"{version}: {current[version]} -> {role}")
        for version, role in current.items():
            if version not in roles and role != "retired":
                conn.execute(update(model_versions).where(mv.version == version)
                             .values(role="retired", role_changed_at=now))
                changes.append(f"{version}: {role} -> retired")
    return changes
