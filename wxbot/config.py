"""Configuration: config.toml plus WXBOT_<SECTION>__<KEY> environment overrides."""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENV_PREFIX = "WXBOT_"


def _coerce(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return json.loads(raw) if raw.strip().startswith("[") else [s.strip() for s in raw.split(",") if s.strip()]
    return raw


class Config:
    """Nested dict with attribute access: cfg.strategy.min_model_prob."""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            value = self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        return Config(value) if isinstance(value, dict) else value

    def get(self, name: str, default: Any = None) -> Any:
        value = self._data.get(name, default)
        return Config(value) if isinstance(value, dict) else value

    def as_dict(self) -> dict:
        return json.loads(json.dumps(self._data))


def load_config(path: str | os.PathLike | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(path or env.get("WXBOT_CONFIG") or ROOT / "config.toml")
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    for key, raw in env.items():
        if not key.startswith(ENV_PREFIX) or "__" not in key:
            continue
        section, _, name = key[len(ENV_PREFIX):].lower().partition("__")
        if section in data and name in data[section]:
            data[section][name] = _coerce(raw, data[section][name])
    # sqlite paths are relative to the project root, not the working directory
    for section in ("app", "backtest"):
        url = data.get(section, {}).get("database_url")
        if url and url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///"):]
            if rel != ":memory:":
                full = (ROOT / rel).resolve()
                full.parent.mkdir(parents=True, exist_ok=True)
                data[section]["database_url"] = f"sqlite:///{full}"
    return Config(data)
