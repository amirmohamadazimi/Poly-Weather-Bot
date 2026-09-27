"""Polymarket weather paper-trading bot.

    python main.py               # dashboard + autonomous paper-trading loop
    python main.py once          # run one cycle and exit
    python main.py worker        # loop only (no dashboard)
    python main.py web           # dashboard only (reads the database)
    python main.py backtest      # walk-forward forecast backtest + fit calibration
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
                        choices=["run", "once", "worker", "web", "backtest", "report", "export"])
    parser.add_argument("path", nargs="?", help="output directory for export")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--days", type=int, default=90, help="backtest window in days")
    parser.add_argument("--stations", help="backtest: comma-separated station codes (default: all enabled)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.app.log_level, cfg.app.log_json)
    log = logging.getLogger("wxbot")
    if cfg.app.mode != "paper":
        # make_broker() refuses anything but paper; fail before touching anything else
        from wxbot.execution.paper import make_broker
        make_broker(cfg, None)
    db = Database(cfg.app.database_url)
    safe_db = cfg.app.database_url.split("@")[-1]
    print(BANNER.format(mode=cfg.app.mode.upper(), initial=cfg.bankroll.initial, db=safe_db), file=sys.stderr)

    if args.command == "report":
        from wxbot.report import build_report, to_markdown
        print(to_markdown(build_report(db, cfg.bankroll.initial)))
        return 0
    if args.command == "export":
        from wxbot.export import export_to_dir
        from wxbot.report import build_report
        out = export_to_dir(db, args.path or "exports", build_report(db, cfg.bankroll.initial))
        print(f"exported to {out.resolve()}")
        return 0
    if args.command == "backtest":
        from wxbot.backtest import run_backtest
        from wxbot.data.weather import IEMObservations, OpenMeteoPreviousRuns
        stations = [s.strip().upper() for s in args.stations.split(",")] if args.stations else None
        rep = run_backtest(cfg, db, OpenMeteoPreviousRuns(list(cfg.weather.models)), IEMObservations(),
                           stations=stations, days=args.days)
        print(json.dumps({k: v for k, v in rep.items() if k != "stations"}, indent=2, default=str))
        return 0

    from wxbot.runner import Runner, build_engine
    engine = build_engine(cfg, db)
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

    import uvicorn
    from wxbot.web.app import create_app
    if args.command == "run" and cfg.schedule.autostart:
        runner.start()
    app = create_app(cfg, db, runner if args.command == "run" else None)
    print(f"Dashboard: http://{'localhost' if cfg.app.host in ('127.0.0.1', '0.0.0.0') else cfg.app.host}:{cfg.app.port}",
          file=sys.stderr)
    uvicorn.run(app, host=cfg.app.host, port=cfg.app.port, log_level=cfg.app.log_level.lower(), access_log=False)
    runner.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
