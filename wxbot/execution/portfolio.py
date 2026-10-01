"""Virtual bankroll, derived entirely from the paper_bets ledger.

cash = initial - stakes of all bets + payouts of settled bets. Nothing is kept
in memory, so a restart can never lose or double-count money.

Open positions are marked to market: each is valued at what selling it would
fetch now, the best bid of the side held in the market's latest snapshot (the
NO bid is 1 - the YES ask). Without a bid the side's displayed price is used,
and without a snapshot the position stays at cost; `marked_by` says which.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from wxbot.db import Database, bankroll_snapshots, market_snapshots, markets, paper_bets, utcnow


@dataclass
class Position:
    bet_id: int
    market_id: str
    side: str
    shares: float
    stake: float
    entry_price: float
    mark_price: float | None   # per share; None = no quote, valued at cost
    marked_by: str             # bid | price | cost
    snapshot_ts: datetime | None = None

    @property
    def value(self) -> float:
        return self.stake if self.mark_price is None else self.shares * self.mark_price

    @property
    def unrealized_pnl(self) -> float:
        return self.value - self.stake


@dataclass
class Bankroll:
    initial: float
    cash: float
    open_exposure: float               # stakes of open bets, at cost
    realized_pnl: float
    positions: list[Position] = field(default_factory=list)

    @property
    def market_value(self) -> float:
        return sum(p.value for p in self.positions) if self.positions else self.open_exposure

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.open_exposure

    @property
    def equity(self) -> float:
        """Cash plus open positions marked to market."""
        return self.cash + self.market_value

    @property
    def book_equity(self) -> float:
        """Cash plus open positions at cost."""
        return self.cash + self.open_exposure


def mark_price(side: str, snap: dict | None) -> tuple[float | None, str]:
    """Liquidation price per share of `side` from a market snapshot of YES quotes."""
    if not snap:
        return None, "cost"
    bid, ask, px = snap.get("best_bid"), snap.get("best_ask"), snap.get("yes_price")
    side_bid = bid if side == "YES" else (None if ask is None else 1 - ask)
    if side_bid is not None and 0 < side_bid <= 1:
        return side_bid, "bid"
    side_px = px if side == "YES" else (None if px is None else 1 - px)
    if side_px is not None and 0 <= side_px <= 1:
        return side_px, "price"
    return None, "cost"


def latest_snapshots(db: Database, market_ids: list[str]) -> dict[str, dict]:
    if not market_ids:
        return {}
    ms = market_snapshots.c
    last = (select(func.max(ms.id).label("sid")).where(ms.market_id.in_(market_ids))
            .group_by(ms.market_id).subquery())
    return {r["market_id"]: r for r in db.rows(select(market_snapshots).join(last, last.c.sid == ms.id))}


def open_positions(db: Database) -> list[Position]:
    pb = paper_bets.c
    bets = db.rows(select(pb.id, pb.market_id, pb.side, pb.shares, pb.stake, pb.entry_price)
                   .where(pb.status == "OPEN").order_by(pb.id))
    snaps = latest_snapshots(db, sorted({b["market_id"] for b in bets}))
    out = []
    for b in bets:
        snap = snaps.get(b["market_id"])
        price, how = mark_price(b["side"], snap)
        out.append(Position(b["id"], b["market_id"], b["side"], b["shares"], b["stake"], b["entry_price"],
                            price, how, snap["ts"] if snap else None))
    return out


def bankroll(db: Database, initial: float) -> Bankroll:
    pb = paper_bets.c
    row = db.one(select(
        func.coalesce(func.sum(pb.stake), 0.0).label("staked"),
        func.coalesce(func.sum(pb.payout), 0.0).label("paid"),
        func.coalesce(func.sum(pb.pnl), 0.0).label("pnl"),
    ))
    open_row = db.one(select(func.coalesce(func.sum(pb.stake), 0.0).label("open")).where(pb.status == "OPEN"))
    return Bankroll(initial=initial, cash=initial - row["staked"] + row["paid"],
                    open_exposure=open_row["open"], realized_pnl=row["pnl"], positions=open_positions(db))


def event_exposure(db: Database, event_id: str) -> float:
    pb = paper_bets.c
    row = db.one(select(func.coalesce(func.sum(pb.stake), 0.0).label("x"))
                 .where(pb.status == "OPEN", pb.event_id == event_id))
    return row["x"]


def station_day_exposure(db: Database, station: str | None, local_date: str | None) -> float:
    """Open stakes on every market for one station and day, high and low together:
    they depend on the same weather, so they tend to win or lose together."""
    if not station or not local_date:
        return 0.0
    pb, mk = paper_bets.c, markets.c
    row = db.one(select(func.coalesce(func.sum(pb.stake), 0.0).label("x"))
                 .join(markets, mk.id == pb.market_id)
                 .where(pb.status == "OPEN", mk.station == station, mk.local_date == local_date))
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
              market_value=round(b.market_value, 6), unrealized_pnl=round(b.unrealized_pnl, 6),
              equity=round(b.equity, 6), realized_pnl=round(b.realized_pnl, 6), reason=reason)
    return b
