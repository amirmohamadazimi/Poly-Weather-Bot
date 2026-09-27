"""Live trading safety boundary.

Phase 1 contains NO code that can sign or send an order: there is no wallet,
no private key handling and no authenticated Polymarket client anywhere in
this repository. `LiveBroker` exists only so the boundary is explicit.

Enabling live trading in a later phase must require ALL of:
  1. app.mode = "live" in the config file (default "paper"),
  2. the environment variable WXBOT_I_UNDERSTAND_LIVE_TRADING_USES_REAL_MONEY=yes,
  3. a real implementation of LiveBroker.place(), reviewed separately.
Until then any attempt fails loudly at startup instead of silently trading.
"""
from __future__ import annotations

import os

LIVE_ACK_ENV = "WXBOT_I_UNDERSTAND_LIVE_TRADING_USES_REAL_MONEY"


class LiveTradingDisabled(RuntimeError):
    pass


class LiveBroker:
    mode = "live"

    def __init__(self, *_, **__):
        if os.environ.get(LIVE_ACK_ENV) != "yes":
            raise LiveTradingDisabled(
                f"app.mode is 'live' but {LIVE_ACK_ENV}=yes is not set. Refusing to start.")
        raise LiveTradingDisabled("Live trading is not implemented in Phase 1 (paper trading only).")

    def place(self, *_, **__):  # pragma: no cover - unreachable by construction
        raise LiveTradingDisabled("Live trading is not implemented in Phase 1.")
