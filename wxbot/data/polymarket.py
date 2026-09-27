"""Polymarket read-only data: market discovery (Gamma API) and order books (CLOB).

Nothing in this module can place an order: it only issues GET requests to
public endpoints and needs no keys or wallet.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from wxbot.data.http import get_json, make_session
from wxbot.data.stations import get_station

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

TITLE_RE = re.compile(
    r"^(?P<kind>highest|lowest) temperature in (?P<city>.+?) on (?P<month>[a-z]+) (?P<day>\d{1,2})"
    r"(?:,? (?P<year>\d{4}))?\??$", re.I)
WU_RE = re.compile(r"wunderground\.com/history/[a-z]+/[a-z-]+/[^/\s]+/(?P<code>[a-z0-9]{3,4})\b", re.I)
NOAA_RE = re.compile(r"[?&]site=(?P<code>[a-z0-9]{3,4})\b", re.I)
RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)\s*°\s*([CF])", re.I)
SINGLE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°\s*([CF])", re.I)
BELOW_WORDS = ("or below", "or lower", "or less", "and below", "or under")
ABOVE_WORDS = ("or higher", "or above", "or more", "and above", "or over")


@dataclass
class Bucket:
    lo: float | None   # inclusive whole-degree lower edge; None = open
    hi: float | None   # inclusive whole-degree upper edge; None = open
    unit: str          # "C" | "F"


@dataclass
class ParsedMarket:
    id: str
    event_id: str
    event_title: str
    event_slug: str
    question: str
    bucket_label: str
    city: str | None
    station: str | None
    kind: str | None
    local_date: str | None
    bucket: Bucket | None
    yes_token: str | None
    no_token: str | None
    end_date: datetime | None
    resolution_source: str
    description: str
    best_bid: float | None
    best_ask: float | None
    last_price: float | None
    yes_price: float | None
    liquidity: float | None
    volume: float | None
    closed: bool
    resolved_outcome: str | None
    tradeable: bool = False
    skip_reason: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def _jlist(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value)
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def _f(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_bucket(label: str) -> Bucket | None:
    text = (label or "").strip().replace("º", "°")
    m = RANGE_RE.search(text)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        return Bucket(lo, hi, m.group(3).upper())
    m = SINGLE_RE.search(text)
    if not m:
        return None
    x, unit, low = float(m.group(1)), m.group(2).upper(), text.lower()
    if any(w in low for w in BELOW_WORDS) or text.startswith(("≤", "<")):
        return Bucket(None, x, unit)
    if any(w in low for w in ABOVE_WORDS) or text.startswith(("≥", ">")):
        return Bucket(x, None, unit)
    return Bucket(x, x, unit)


def parse_station(resolution_source: str, description: str) -> str | None:
    for text in (resolution_source or "", description or ""):
        m = WU_RE.search(text) or NOAA_RE.search(text)
        if m:
            return m.group("code").upper()
        if "weather.gov.hk" in text or "Hong Kong Observatory" in text:
            return "HKO"
    return None


def parse_title(title: str, end_date: datetime | None) -> tuple[str | None, str | None, str | None]:
    """-> (kind, city, local_date ISO). The year comes from the title or the end date."""
    m = TITLE_RE.match((title or "").strip())
    if not m:
        return None, None, None
    month = MONTHS.get(m.group("month").lower())
    if not month:
        return None, None, None
    day = int(m.group("day"))
    if m.group("year"):
        year = int(m.group("year"))
    else:
        ref = (end_date or datetime.now(timezone.utc)).date()
        # pick the year that puts the date closest to the market's end date
        year = min((ref.year - 1, ref.year, ref.year + 1),
                   key=lambda y: abs((_safe_date(y, month, day) - ref).days))
    try:
        d = date(year, month, day)
    except ValueError:
        return None, None, None
    kind = "high" if m.group("kind").lower() == "highest" else "low"
    return kind, m.group("city").strip(), d.isoformat()


def _safe_date(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError:
        return date(y, m, 28)


def resolved_outcome(market: dict) -> str | None:
    """YES/NO once Polymarket has settled the market (prices pinned to 1/0)."""
    if not market.get("closed"):
        return None
    prices = [_f(p) for p in _jlist(market.get("outcomePrices"))]
    outcomes = [str(o).lower() for o in _jlist(market.get("outcomes"))]
    if len(prices) != 2 or None in prices or outcomes[:2] != ["yes", "no"]:
        return None
    if prices[0] >= 0.99 and prices[1] <= 0.01:
        return "YES"
    if prices[1] >= 0.99 and prices[0] <= 0.01:
        return "NO"
    return None


def parse_market(event: dict, market: dict, kinds: list[str] | None = None) -> ParsedMarket:
    end_date = _dt(market.get("endDate") or event.get("endDate"))
    title = event.get("title") or ""
    kind, city, local_date = parse_title(title, end_date)
    res_src = market.get("resolutionSource") or event.get("resolutionSource") or ""
    desc = market.get("description") or event.get("description") or ""
    station = parse_station(res_src, desc)
    label = market.get("groupItemTitle") or ""
    bucket = parse_bucket(label) or parse_bucket(market.get("question") or "")
    tokens = _jlist(market.get("clobTokenIds"))
    outcomes = [str(o).lower() for o in _jlist(market.get("outcomes"))]
    prices = [_f(p) for p in _jlist(market.get("outcomePrices"))]
    yes_idx = outcomes.index("yes") if "yes" in outcomes else 0
    no_idx = 1 - yes_idx
    pm = ParsedMarket(
        id=str(market.get("id")), event_id=str(event.get("id")), event_title=title,
        event_slug=event.get("slug") or "", question=market.get("question") or "",
        bucket_label=label, city=city, station=station, kind=kind, local_date=local_date,
        bucket=bucket,
        yes_token=str(tokens[yes_idx]) if len(tokens) == 2 else None,
        no_token=str(tokens[no_idx]) if len(tokens) == 2 else None,
        end_date=end_date, resolution_source=res_src, description=desc,
        best_bid=_f(market.get("bestBid")), best_ask=_f(market.get("bestAsk")),
        last_price=_f(market.get("lastTradePrice")),
        yes_price=prices[yes_idx] if len(prices) == 2 else None,
        liquidity=_f(market.get("liquidityNum") or market.get("liquidity")),
        volume=_f(market.get("volumeNum") or market.get("volume")),
        closed=bool(market.get("closed")), resolved_outcome=resolved_outcome(market), raw=market,
    )
    st = get_station(station)
    if kind is None or local_date is None:
        pm.skip_reason = "title not recognised"
    elif kinds and kind not in kinds:
        pm.skip_reason = f"kind '{kind}' disabled"
    elif bucket is None:
        pm.skip_reason = f"bucket label not recognised: {label!r}"
    elif station is None:
        pm.skip_reason = "resolution station not found in market text"
    elif st is None:
        pm.skip_reason = f"station {station} not in station table"
    elif not st.enabled:
        pm.skip_reason = f"station {station} disabled: {st.note}"
    elif pm.yes_token is None:
        pm.skip_reason = "no order-book tokens"
    else:
        pm.tradeable = True
    return pm


@dataclass
class BookLevel:
    price: float
    size: float


class PolymarketClient:
    def __init__(self, session=None, tag_slug: str = "daily-temperature"):
        self.session = session or make_session()
        self.tag_slug = tag_slug

    def list_events(self, lookback_days: int = 2, page_size: int = 100, max_pages: int = 20) -> list[dict]:
        """Open daily-temperature events whose end date is recent or upcoming."""
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        events, offset = [], 0
        for _ in range(max_pages):
            page = get_json(self.session, f"{GAMMA}/events", {
                "tag_slug": self.tag_slug, "closed": "false", "end_date_min": since,
                "limit": page_size, "offset": offset, "order": "endDate", "ascending": "true"})
            if not isinstance(page, list) or not page:
                break
            events.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return events

    def discover(self, kinds: list[str] | None = None) -> list[ParsedMarket]:
        out = []
        for ev in self.list_events():
            for mk in ev.get("markets") or []:
                out.append(parse_market(ev, mk, kinds))
        return out

    def get_market(self, market_id: str) -> dict:
        return get_json(self.session, f"{GAMMA}/markets/{market_id}")

    def get_asks(self, token_id: str) -> list[BookLevel]:
        """Ask side of the CLOB book for one outcome token, best (cheapest) first."""
        book = get_json(self.session, f"{CLOB}/book", {"token_id": token_id})
        levels = [BookLevel(float(a["price"]), float(a["size"])) for a in book.get("asks") or []]
        return sorted(levels, key=lambda lv: lv.price)
