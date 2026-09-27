"""Virtual bankroll, derived entirely from the paper_bets ledger.

cash = initial - stakes of all bets + payouts of settled bets. Nothing is kept
in memory, so a restart can never lose or double-count money.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from wxbot.db import Database, bankroll_snapshots, paper_bets, utcnow


@dataclass
class Bankroll:
    initial: float
    cash: float
    open_exposure: float
    realized_pnl: float

    @property
    def equity(self) -> float:
        return self.cash + self.open_exposure


def bankroll(db: Database, initial: float) -> Bankroll:
    pb = paper_bets.c
    row = db.one(select(
        func.coalesce(func.sum(pb.stake), 0.0).label("staked"),
        func.coalesce(func.sum(pb.payout), 0.0).label("paid"),
        func.coalesce(func.sum(pb.pnl), 0.0).label("pnl"),
    ))
    open_row = db.one(select(func.coalesce(func.sum(pb.stake), 0.0).label("open")).where(pb.status == "OPEN"))
    return Bankroll(initial=initial, cash=initial - row["staked"] + row["paid"],
                    open_exposure=open_row["open"], realized_pnl=row["pnl"])


def event_exposure(db: Database, event_id: str) -> float:
    pb = paper_bets.c
    row = db.one(select(func.coalesce(func.sum(pb.stake), 0.0).label("x"))
                 .where(pb.status == "OPEN", pb.event_id == event_id))
    return row["x"]


def has_open_position(db: Database, market_id: str) -> bool:
    pb = paper_bets.c
    return db.one(select(pb.id).where(pb.status == "OPEN", pb.market_id == market_id)) is not None


def daily_realized_pnl(db: Database, now: datetime | None = None) -> float:
    now = now or utcnow()
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pb = paper_bets.c
    row = db.one(select(func.coalesce(func.sum(pb.pnl), 0.0).label("x")).where(pb.settled_at >= start))
    return row["x"]


def snapshot(db: Database, initial: float, reason: str) -> Bankroll:
    b = bankroll(db, initial)
    db.insert(bankroll_snapshots, ts=utcnow(), cash=round(b.cash, 6), open_exposure=round(b.open_exposure, 6),
              equity=round(b.equity, 6), realized_pnl=round(b.realized_pnl, 6), reason=reason)
    return b
