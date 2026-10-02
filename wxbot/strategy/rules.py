"""Betting rules: turn a prediction into a trading signal (BET / NO_BET).

Prediction -> Signal -> Paper bet. A confident prediction is not enough: every
rule below must pass, and each result is stored with the signal so the
decision can be audited later.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fill:
    shares: float
    cost: float          # dollars paid for shares (incl. slippage)
    fee: float
    levels: list         # [(price, shares)] taken from the book

    @property
    def total(self) -> float:
        return self.cost + self.fee

    @property
    def avg_price(self) -> float:
        """Effective price per share including slippage and fees."""
        return self.total / self.shares if self.shares else float("inf")


def simulate_fill(asks: list, budget: float, slippage: float, fee_rate: float,
                  max_book_share: float) -> Fill:
    """Walk the ask side (best first) spending up to `budget` dollars incl. fees.

    Only `max_book_share` of each level is taken, so the simulation never
    assumes we could sweep the whole visible book at quoted prices.
    """
    shares = cost = 0.0
    levels = []
    remaining = budget
    for lv in asks:
        price = min(lv.price + slippage, 0.999)
        per_share = price * (1.0 + fee_rate)
        avail = lv.size * max_book_share
        if avail <= 0 or remaining <= 0:
            continue
        take = min(avail, remaining / per_share)
        if take <= 0:
            break
        shares += take
        cost += take * price
        remaining -= take * per_share
        levels.append((round(lv.price, 4), round(take, 4)))
        if remaining <= 1e-9:
            break
    return Fill(shares=shares, cost=cost, fee=cost * fee_rate, levels=levels)


def book_capacity(asks: list, slippage: float, fee_rate: float, max_book_share: float) -> float:
    """Dollars that could be spent under the book-share cap."""
    return sum(lv.size * max_book_share * min(lv.price + slippage, 0.999) * (1 + fee_rate) for lv in asks)


def best_side(quotes: dict[str, tuple]) -> str:
    """quotes: side -> (probability the side wins, its ask or None, ...). The
    side with an ask and the larger probability-minus-ask; without any ask, the
    more likely side."""
    def score(side):
        p, px = quotes[side][0], quotes[side][1]
        return (px is not None, p - px if px is not None else p)
    return max(quotes, key=score)


def quoted_entry(ask: float | None, strategy) -> float | None:
    """Expected price per share when buying at `ask`: slippage, then the fee."""
    if ask is None:
        return None
    return min(ask + strategy.slippage, 0.999) * (1 + strategy.fee_rate)


@dataclass
class Context:
    side: str
    model_prob: float            # probability the side we'd buy wins
    market_prob: float | None    # mid-implied probability of that side
    entry_price: float | None    # expected effective price per share
    liquidity: float | None
    lead_hours: float
    n_models: int
    forecast_age_min: float
    sigma_c: float
    market_open: bool
    has_position: bool
    daily_pnl: float
    initial_bankroll: float
    stake: float | None = None   # None during the pre-check, before sizing
    data_valid: bool = True      # forecast snapshot passed data/validation.py
    extra: dict = field(default_factory=dict)


def _r(rule: str, passed: bool, value, threshold) -> dict:
    return {"rule": rule, "passed": bool(passed),
            "value": round(value, 4) if isinstance(value, float) else value, "threshold": threshold}


def evaluate(ctx: Context, cfg) -> list[dict]:
    s = cfg.strategy
    price = ctx.entry_price
    edge = None if price is None else ctx.model_prob - price
    ev = None if not price else ctx.model_prob / price - 1.0
    results = [
        _r("market_open", ctx.market_open, ctx.market_open, True),
        _r("confidence", ctx.model_prob >= s.min_model_prob, ctx.model_prob, f">= {s.min_model_prob}"),
        _r("price_available", price is not None, price, "ask exists"),
        _r("edge", edge is not None and edge >= s.min_edge, edge, f">= {s.min_edge}"),
        _r("expected_value", ev is not None and ev >= s.min_ev_per_dollar, ev, f">= {s.min_ev_per_dollar}"),
        _r("entry_price_range", price is not None and s.min_entry_price <= price <= s.max_entry_price,
           price, f"{s.min_entry_price}..{s.max_entry_price}"),
        _r("liquidity", (ctx.liquidity or 0) >= s.min_liquidity_usd, ctx.liquidity, f">= {s.min_liquidity_usd}"),
        _r("time_to_resolution", s.min_lead_hours <= ctx.lead_hours <= s.max_lead_hours,
           round(ctx.lead_hours, 1), f"{s.min_lead_hours}..{s.max_lead_hours} h"),
        _r("data_validation", ctx.data_valid, ctx.data_valid, True),
        _r("data_quality_models", ctx.n_models >= cfg.weather.min_models, ctx.n_models,
           f">= {cfg.weather.min_models}"),
        _r("data_quality_freshness", ctx.forecast_age_min <= cfg.weather.max_forecast_age_minutes,
           round(ctx.forecast_age_min, 1), f"<= {cfg.weather.max_forecast_age_minutes} min"),
        _r("forecast_uncertainty", ctx.sigma_c <= s.max_sigma_c, ctx.sigma_c, f"<= {s.max_sigma_c} C"),
        _r("no_existing_position", not ctx.has_position, ctx.has_position, False),
    ]
    limit = cfg.risk.daily_loss_limit_pct * ctx.initial_bankroll
    results.append(_r("daily_loss_limit", limit <= 0 or ctx.daily_pnl > -limit,
                      round(ctx.daily_pnl, 2), f"> -{round(limit, 2)}" if limit > 0 else "off"))
    if ctx.stake is not None:
        results.append(_r("position_size", ctx.stake >= cfg.sizing.min_stake, round(ctx.stake, 2),
                          f">= {cfg.sizing.min_stake} after risk caps"))
    return results


def failed(results: list[dict]) -> list[str]:
    return [r["rule"] for r in results if not r["passed"]]
