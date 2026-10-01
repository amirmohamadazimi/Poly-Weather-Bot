"""Model registry: every model version the bot has run, and which one trades.

`production` is [model] version: its predictions create signals. `shadow`
models ([model] shadow_models) are priced on every market and scored, never
traded. A version that leaves the config becomes `retired`. Rows are never
deleted, so every stored prediction can be traced to its model.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from wxbot.db import Database, model_versions
from wxbot.features import FEATURE_SET
from wxbot.model.baselines import Climatology, RawForecast
from wxbot.model.normal import NormalMultiModel


def production_model(cfg) -> NormalMultiModel:
    return NormalMultiModel(cfg.model.version, cfg.model.prob_floor, cfg.model.prob_ceiling)


def shadow_models(cfg) -> list:
    m = cfg.model
    known = {
        "raw-forecast-v1": lambda: RawForecast(list(m.default_sigma_c), m.prob_floor, m.prob_ceiling),
        "climatology-v1": lambda: Climatology(m.get("climatology_window_days", 7),
                                              m.get("climatology_min_samples", 20), m.prob_floor, m.prob_ceiling),
    }
    unknown = [v for v in m.get("shadow_models", []) if v not in known]
    if unknown:
        raise ValueError(f"unknown shadow model(s) in [model] shadow_models: {unknown}; known: {sorted(known)}")
    return [known[v]() for v in m.get("shadow_models", [])]


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
                    feature_set=FEATURE_SET, params=m.params, role=role, created_at=now, role_changed_at=now))
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
