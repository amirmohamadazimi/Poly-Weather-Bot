"""Paper broker: records simulated fills and settles them. Never touches money."""
from __future__ import annotations

from sqlalchemy import select, update

from wxbot.db import Database, market_resolutions, markets, paper_bets, utcnow
from wxbot.execution import portfolio
from wxbot.execution.live import LiveBroker
from wxbot.strategy.rules import Fill


class PaperBroker:
    mode = "paper"

    def __init__(self, db: Database, initial_bankroll: float):
        self.db = db
        self.initial = initial_bankroll

    def place(self, *, signal_id: int, market: dict, side: str, fill: Fill, model_prob: float,
              market_prob: float | None, edge: float, ev: float) -> int:
        token = market["yes_token"] if side == "YES" else market["no_token"]
        bet_id = self.db.insert(
            paper_bets, signal_id=signal_id, market_id=market["id"], event_id=market["event_id"],
            side=side, token_id=token, opened_at=utcnow(), market_prob=market_prob,
            model_prob=model_prob, edge=edge, ev_per_dollar=ev, confidence=model_prob,
            entry_price=fill.avg_price, shares=fill.shares, stake=fill.total, fee=fill.fee,
            fill={"levels": fill.levels, "cost": fill.cost, "fee": fill.fee}, status="OPEN", mode="paper")
        portfolio.snapshot(self.db, self.initial, f"bet#{bet_id}")
        return bet_id

    def settle_market(self, market_id: str, outcome: str, raw: dict | None = None) -> list[int]:
        """Settle every open bet on a market that Polymarket resolved to `outcome`."""
        db = self.db
        if db.one(select(market_resolutions.c.market_id).where(market_resolutions.c.market_id == market_id)) is None:
            db.insert(market_resolutions, market_id=market_id, resolved_at=utcnow(), outcome=outcome, raw=raw)
        with db.engine.begin() as conn:
            conn.execute(update(markets).where(markets.c.id == market_id)
                         .values(closed=True, resolved_outcome=outcome))
        settled = []
        open_bets = db.rows(select(paper_bets).where(paper_bets.c.market_id == market_id,
                                                     paper_bets.c.status == "OPEN"))
        for bet in open_bets:
            won = bet["side"] == outcome
            payout = bet["shares"] if won else 0.0
            with db.engine.begin() as conn:
                conn.execute(update(paper_bets).where(paper_bets.c.id == bet["id"], paper_bets.c.status == "OPEN")
                             .values(status="WON" if won else "LOST", outcome=outcome, settled_at=utcnow(),
                                     payout=payout, pnl=payout - bet["stake"]))
            b = portfolio.bankroll(db, self.initial)
            with db.engine.begin() as conn:
                conn.execute(update(paper_bets).where(paper_bets.c.id == bet["id"])
                             .values(bankroll_after=round(b.equity, 6)))
            portfolio.snapshot(db, self.initial, f"settle#{bet['id']}")
            settled.append(bet["id"])
        return settled


def make_broker(cfg, db: Database):
    mode = cfg.app.mode
    if mode == "paper":
        return PaperBroker(db, cfg.bankroll.initial)
    if mode == "live":
        return LiveBroker()  # always raises in Phase 1
    raise ValueError(f"unknown app.mode {mode!r}; expected 'paper'")
