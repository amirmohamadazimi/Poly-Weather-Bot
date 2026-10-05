"""Dashboard: FastAPI JSON API + one HTML page. Reads the database only;
the prediction engine runs in its own loop (see runner.py)."""
from __future__ import annotations

import json
import secrets
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import desc, func, or_, select

from wxbot.data.polymarket import CRITERIA_SKIP
from wxbot.db import (
    EXPORT_TABLES, Database, markets, model_versions, paper_bets, predictions, signals, system_events, utcnow,
)
from wxbot.evaluation import metrics
from wxbot.evaluation.errors import error_analysis
from wxbot.execution.portfolio import latest_snapshots, open_positions
from wxbot.experiment import starting_bankroll
from wxbot.export import export_zip_bytes, table_csv
from wxbot import research
from wxbot.health import system_health
from wxbot.learning import summary as learning_summary
from wxbot.report import build_report, to_markdown

TEMPLATE = Path(__file__).parent / "templates" / "index.html"


def create_app(cfg, db: Database, runner=None, now=utcnow) -> FastAPI:
    app = FastAPI(title="Polymarket weather paper-trading bot", docs_url="/api/docs")

    def initial() -> float:  # the database's own starting bankroll (see wxbot/experiment.py)
        return starting_bankroll(db, cfg)
    password = cfg.app.get("dashboard_password", "") or ""
    basic = HTTPBasic(auto_error=False)

    def auth(creds: HTTPBasicCredentials | None = Depends(basic)):
        if not password:
            return
        if creds is None or not secrets.compare_digest(creds.password.encode(), password.encode()):
            raise HTTPException(401, "auth required", headers={"WWW-Authenticate": "Basic"})

    deps = [Depends(auth)]

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "mode": cfg.app.mode, "loop_alive": bool(runner and runner.alive)}

    @app.get("/", response_class=HTMLResponse, dependencies=deps)
    def index():
        return TEMPLATE.read_text(encoding="utf-8")

    @app.get("/api/overview", dependencies=deps)
    def overview():
        return metrics.overview(db, initial())

    @app.get("/api/markets", dependencies=deps)
    def active_markets():
        mk, s, p = markets.c, signals.c, predictions.c
        today = (now() - timedelta(days=1)).date().isoformat()
        latest = (select(s.market_id, func.max(s.id).label("sid")).group_by(s.market_id).subquery())
        rows = db.rows(
            select(mk.id, mk.event_title, mk.event_slug, mk.question, mk.bucket_label, mk.station, mk.local_date,
                   mk.kind, s.side, s.model_prob, s.calibrated_prob, s.market_prob, s.entry_price, s.edge,
                   s.ev_per_dollar, s.confidence, s.decision, s.reason, s.ts, s.id.label("signal_id"), p.p_yes,
                   p.calibrated_prob.label("calibrated_p_yes"), p.calibrator_version, p.mu_c, p.sigma_c)
            .join(latest, latest.c.market_id == mk.id).join(signals, s.id == latest.c.sid)
            .join(predictions, p.id == s.prediction_id)
            .where(mk.closed.is_(False), mk.local_date >= today)
            .order_by(mk.local_date, mk.event_title, mk.bucket_lo.is_(None).desc(), mk.bucket_lo))
        skipped = db.rows(select(mk.skip_reason, func.count().label("n"))
                          .where(mk.tradeable.is_(False), mk.closed.is_(False),
                                 or_(mk.local_date >= today, mk.local_date.is_(None)))
                          .group_by(mk.skip_reason))
        criteria = sum(r["n"] for r in skipped if (r["skip_reason"] or "").startswith(CRITERIA_SKIP))
        # the current quotes (latest snapshot) and any open position in each market
        snaps = latest_snapshots(db, [r["id"] for r in rows])
        held = {pos.market_id: pos for pos in open_positions(db)}
        for r in rows:
            snap = snaps.get(r["id"]) or {}
            r.update(yes_bid=snap.get("best_bid"), yes_ask=snap.get("best_ask"), yes_price=snap.get("yes_price"),
                     liquidity=snap.get("liquidity"), quoted_at=snap.get("ts"))
            pos = held.get(r["id"])
            r["position"] = pos and {"bet_id": pos.bet_id, "side": pos.side, "shares": pos.shares,
                                     "cost": pos.stake, "value": pos.value, "unrealized_pnl": pos.unrealized_pnl}
        return {"markets": rows, "skipped": skipped, "skipped_criteria": criteria}

    @app.get("/api/signals/{signal_id}", dependencies=deps)
    def signal_detail(signal_id: int):
        sig = db.one(select(signals).where(signals.c.id == signal_id))
        if not sig:
            raise HTTPException(404)
        pred = db.one(select(predictions).where(predictions.c.id == sig["prediction_id"]))
        market = db.one(select(markets).where(markets.c.id == sig["market_id"]))
        bet = db.one(select(paper_bets).where(paper_bets.c.signal_id == signal_id))
        return {"signal": sig, "prediction": pred, "market": market, "bet": bet}

    @app.get("/api/bets", dependencies=deps)
    def bets(q: str = "", status: str = "", side: str = ""):
        """Every paper bet, newest first. q searches the market, city, station,
        bucket, date, side and status (case-insensitive); "#12" finds bet 12."""
        b, mk = paper_bets.c, markets.c
        query = (select(paper_bets, mk.question, mk.event_title, mk.local_date, mk.bucket_label, mk.city, mk.station)
                 .join(markets, mk.id == b.market_id).order_by(desc(b.id)))
        if status:
            query = query.where(b.status == status.upper())
        if side:
            query = query.where(b.side == side.upper())
        for word in q.lower().split():
            if word.lstrip("#").isdigit() and word.startswith("#"):
                query = query.where(b.id == int(word[1:]))
                continue
            query = query.where(or_(*[func.lower(c).contains(word, autoescape=True) for c in (
                mk.question, mk.event_title, mk.bucket_label, mk.city, mk.station, mk.local_date, b.side, b.status)]))
        return db.rows(query)

    @app.get("/api/portfolio", dependencies=deps)
    def portfolio_view():
        return metrics.portfolio_view(db, cfg, now(), initial())

    @app.get("/api/errors", dependencies=deps)
    def errors():
        return error_analysis(db)

    @app.get("/api/learning", dependencies=deps)
    def learning():
        return {**learning_summary(db), "settings": cfg.learning.as_dict()}

    @app.get("/api/performance", dependencies=deps)
    def performance():
        return metrics.performance_series(db, initial())

    @app.get("/api/models", dependencies=deps)
    def models():
        return db.rows(select(model_versions).order_by(model_versions.c.id))

    @app.get("/api/status", dependencies=deps)
    def status():
        state = {k: db.get_state(k) for k in (
            "bot_status", "last_weather_update", "last_polymarket_update", "last_prediction_time",
            "last_observation_update", "markets_monitored", "loop_started_at", "last_cycle")}
        if state["last_cycle"]:
            state["last_cycle"] = json.loads(state["last_cycle"])
        events = db.rows(select(system_events).where(system_events.c.level.in_(["WARNING", "ERROR"]))
                         .order_by(desc(system_events.c.id)).limit(30))
        recent = db.rows(select(system_events).order_by(desc(system_events.c.id)).limit(15))
        return {
            **state, **system_health(db, cfg, now()), "mode": cfg.app.mode.upper(),
            "loop_alive": bool(runner and runner.alive),
            "paused": bool(runner and runner.paused), "cycle_minutes": cfg.schedule.cycle_minutes,
            "active_positions": db.one(select(func.count().label("n")).select_from(paper_bets)
                                       .where(paper_bets.c.status == "OPEN"))["n"],
            "problems": events, "recent_events": recent,
            "config": {k: cfg.as_dict()[k] for k in ("strategy", "sizing", "risk", "model", "weather")},
        }

    @app.post("/api/run-cycle", dependencies=deps)
    def run_cycle():
        if runner is None:
            raise HTTPException(409, "no runner")
        runner.trigger()
        return {"ok": True, "message": "cycle triggered"}

    @app.post("/api/pause", dependencies=deps)
    def pause(request: Request, paused: bool = True):
        if runner is None:
            raise HTTPException(409, "no runner")
        runner.set_paused(paused)
        return {"paused": runner.paused}

    @app.get("/api/report", dependencies=deps)
    def report():
        return build_report(db, initial())

    @app.get("/export/report.md", response_class=PlainTextResponse, dependencies=deps)
    def report_md():
        return to_markdown(build_report(db, initial()))

    @app.get("/api/research", dependencies=deps)
    def research_report():
        return research.build(db, initial())

    @app.get("/export/research.md", response_class=PlainTextResponse, dependencies=deps)
    def research_md():
        return research.to_markdown(research.build(db, initial()))

    @app.get("/export/all.zip", dependencies=deps)
    def export_all():
        data = export_zip_bytes(db, build_report(db, initial()))
        stamp = utcnow().strftime("%Y%m%d-%H%M")
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="wxbot-export-{stamp}.zip"'})

    @app.get("/export/{name}.csv", dependencies=deps)
    def export_table(name: str):
        if name not in EXPORT_TABLES:
            raise HTTPException(404)
        return Response(table_csv(db, name), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})

    return app
