"""Polymarket weather paper-trading bot.

    python main.py               # dashboard + autonomous paper-trading loop
    python main.py once          # run one cycle and exit
    python main.py worker        # loop only (no dashboard)
    python main.py web           # dashboard only (reads the database)
    python main.py backtest      # walk-forward forecast backtest + fit calibration
                                 #   (--if-missing: only when no calibration is stored yet)
    python main.py backtest-markets [JSON]
                                 # replay closed markets at historical prices (own database;
                                 #   --start/--end or --days; --offline: stored data only)
    python main.py calibrate     # refit the probability calibrators now (the cycle does it daily)
    python main.py climatology   # load --years of observed highs/lows for the climatology baseline
                                 #   (--if-missing: only when no history was loaded yet)
    python main.py report        # print the performance report
    python main.py export DIR    # write every table as CSV (+ report.json) to DIR

PAPER TRADING ONLY. No code in this project can place a real order.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading

from wxbot.config import load_config
from wxbot.db import Database
from wxbot.logging_setup import setup_logging

BANNER = """
==============================================================
  Weather paper-trading bot · MODE: {mode} · real money: $0
  Virtual bankroll: ${initial:,.2f} · database: {db}
==============================================================
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "once", "worker", "web", "backtest", "backtest-markets", "calibrate",
                                 "climatology", "report", "export"])
    parser.add_argument("path", nargs="?",
                        help="export: output directory; backtest-markets: also write the report as JSON here")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--days", type=int, help="backtest window in days (backtest 90, backtest-markets 14)")
    parser.add_argument("--start", help="backtest-markets: first market day, YYYY-MM-DD")
    parser.add_argument("--end", help="backtest-markets: last market day, YYYY-MM-DD (default: two days ago)")
    parser.add_argument("--offline", action="store_true", help="backtest-markets: replay stored data, fetch nothing")
    parser.add_argument("--stations", help="backtest/climatology: comma-separated station codes (default: all enabled)")
    parser.add_argument("--years", type=int, default=3, help="climatology: years of history to load")
    parser.add_argument("--if-missing", action="store_true",
                        help="backtest/climatology: skip when the database already holds it")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.app.log_level, cfg.app.log_json)
    log = logging.getLogger("wxbot")
    if cfg.app.mode != "paper":
        # make_broker() refuses anything but paper; fail before touching anything else
        from wxbot.execution.paper import make_broker
        make_broker(cfg, None)
    research = args.command == "backtest-markets"  # its own database, never an experiment's
    url = cfg.backtest.database_url if research else cfg.app.database_url
    db = Database(url)
    print(BANNER.format(mode=cfg.app.mode.upper(), initial=cfg.bankroll.initial, db=url.split("@")[-1]),
          file=sys.stderr)
    if research:
        return backtest_markets(cfg, db, args)

    from wxbot.experiment import starting_bankroll
    if args.command == "report":
        from wxbot.report import build_report, to_markdown
        print(to_markdown(build_report(db, starting_bankroll(db, cfg))))
        return 0
    if args.command == "export":
        from wxbot.export import export_to_dir
        from wxbot.report import build_report
        out = export_to_dir(db, args.path or "exports", build_report(db, starting_bankroll(db, cfg)))
        print(f"exported to {out.resolve()}")
        return 0
    if args.command == "backtest":
        from wxbot.backtest import run_backtest
        from wxbot.db import calibration_params
        if args.if_missing and db.one(calibration_params.select().limit(1)):
            print("calibration already present; skipping backtest")
            return 0
        from wxbot.data.weather import IEMObservations, OpenMeteoPreviousRuns
        stations = [s.strip().upper() for s in args.stations.split(",")] if args.stations else None
        rep = run_backtest(cfg, db, OpenMeteoPreviousRuns(list(cfg.weather.models)), IEMObservations(),
                           stations=stations, days=args.days or 90)
        print(json.dumps({k: v for k, v in rep.items() if k != "stations"}, indent=2, default=str))
        return 0

    if args.command == "web":  # read-only: no engine, so nothing is written to the database
        from wxbot.web.app import create_app
        serve(cfg, create_app(cfg, db))
        return 0

    from wxbot.runner import Runner, build_engine
    engine = build_engine(cfg, db)
    if args.command == "calibrate":
        from wxbot.evaluation.metrics import latest_calibrators
        print(json.dumps({"summary": engine.maybe_fit_calibration(force=True), "fits": latest_calibrators(db)},
                         indent=2, default=str))
        return 0
    if args.command == "climatology":
        from wxbot.history import load_history
        if args.if_missing and db.get_state("history_loaded_at"):
            print("observation history already loaded; skipping")
            return 0
        stations = [s.strip().upper() for s in args.stations.split(",")] if args.stations else None
        print(json.dumps(load_history(engine, args.years, engine.clock().date(), stations), indent=2))
        return 0
    runner = Runner(engine, cfg.schedule.cycle_minutes)

    if args.command == "once":
        print(json.dumps(runner.run_once(), indent=2, default=str))
        return 0

    stop = threading.Event()

    def _shutdown(*_):
        log.info("shutting down")
        runner.stop()
        stop.set()
    signal.signal(signal.SIGTERM, _shutdown)

    if args.command == "worker":
        runner.start()
        signal.signal(signal.SIGINT, _shutdown)
        stop.wait()
        return 0

    from wxbot.web.app import create_app
    if cfg.schedule.autostart:
        runner.start()
    serve(cfg, create_app(cfg, db, runner))
    runner.stop()
    return 0


def backtest_markets(cfg, db: Database, args) -> int:
    from datetime import date, timedelta

    from wxbot.backtesting import run_market_backtest
    from wxbot.backtesting.report import to_markdown
    from wxbot.db import utcnow
    end = date.fromisoformat(args.end) if args.end else utcnow().date() - timedelta(days=2)
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=(args.days or 14) - 1)
    stations = [s.strip().upper() for s in args.stations.split(",")] if args.stations else None
    sources = None
    if not args.offline:
        from wxbot.data.polymarket import PolymarketClient
        from wxbot.data.weather import IEMObservations, OpenMeteoPreviousRuns
        sources = (PolymarketClient(tag_slug=cfg.markets.tag_slug), OpenMeteoPreviousRuns(list(cfg.weather.models)),
                   IEMObservations())
    rep = run_market_backtest(cfg, db, start, end, sources=sources, stations=stations)
    print(to_markdown(rep))
    if args.path:
        with open(args.path, "w") as fh:
            json.dump(rep, fh, indent=2)
    if not rep["scores"]["n_rows"]:
        print("no decisions could be replayed for this window", file=sys.stderr)
        return 1
    return 0


def serve(cfg, app) -> None:
    import uvicorn
    print(f"Dashboard: http://{'localhost' if cfg.app.host in ('127.0.0.1', '0.0.0.0') else cfg.app.host}:{cfg.app.port}",
          file=sys.stderr)
    uvicorn.run(app, host=cfg.app.host, port=cfg.app.port, log_level=cfg.app.log_level.lower(), access_log=False)


if __name__ == "__main__":
    sys.exit(main())
