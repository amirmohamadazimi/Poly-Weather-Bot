"""End-of-experiment performance report (markdown + JSON)."""
from __future__ import annotations

import json

from sqlalchemy import desc, select

from wxbot.db import Database, markets, paper_bets, system_events
from wxbot.evaluation.metrics import latest_calibrators, model_comparison, overview, prediction_calibration


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x, nd=4) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def build_report(db: Database, initial: float) -> dict:
    ov = overview(db, initial)
    cal = prediction_calibration(db)
    return {"overview": ov, "prediction_calibration": cal, "model_comparison": model_comparison(db),
            "calibrators": latest_calibrators(db),
            "verdict": verdict(ov, cal),
            "status": status(db), "bets": all_bets(db)}


def status(db: Database) -> dict:
    last = db.get_state("last_cycle")
    problems = db.rows(select(system_events.c.ts, system_events.c.level, system_events.c.component,
                              system_events.c.message)
                       .where(system_events.c.level.in_(["WARNING", "ERROR"]))
                       .order_by(desc(system_events.c.id)).limit(10))
    return {"last_cycle": json.loads(last) if last else None,
            "markets_monitored": db.get_state("markets_monitored"), "recent_problems": problems}


def all_bets(db: Database) -> list[dict]:
    """Every bet ever placed, newest market day first."""
    b, mk = paper_bets.c, markets.c
    return db.rows(select(b.id, b.opened_at, b.side, b.entry_price, b.model_prob, b.market_prob, b.edge,
                          b.stake, b.status, b.pnl, mk.event_title, mk.bucket_label, mk.local_date)
                   .join(markets, mk.id == b.market_id).order_by(desc(mk.local_date), b.id))


def by_day(bets: list[dict]) -> list[dict]:
    days: dict[str, dict] = {}
    for bet in bets:
        d = days.setdefault(bet["local_date"], {"day": bet["local_date"], "bets": [], "won": 0, "lost": 0,
                                                "open": 0, "staked": 0.0, "pnl": 0.0})
        d["bets"].append(bet)
        d["staked"] += bet["stake"]
        d[{"WON": "won", "LOST": "lost"}.get(bet["status"], "open")] += 1
        d["pnl"] += bet["pnl"] or 0.0
    return list(days.values())


def verdict(ov: dict, cal: dict) -> list[str]:
    notes = []
    n = ov["n_settled"]
    if n < 100:
        notes.append(f"Only {n} settled bets: too few to conclude anything about profitability "
                     "(aim for several hundred).")
    ci = ov["roi_95ci"]
    if ci:
        lo, hi = ci
        if lo > 0:
            notes.append(f"ROI 95% interval {_pct(lo)} to {_pct(hi)} is above zero: evidence of positive returns.")
        elif hi < 0:
            notes.append(f"ROI 95% interval {_pct(lo)} to {_pct(hi)} is below zero: the strategy lost money.")
        else:
            notes.append(f"ROI 95% interval {_pct(lo)} to {_pct(hi)} includes zero: no evidence either way.")
    if ov["win_rate"] is not None and ov["expected_win_rate"] is not None:
        gap = ov["win_rate"] - ov["expected_win_rate"]
        notes.append(f"Bets won {_pct(ov['win_rate'])} against {_pct(ov['expected_win_rate'])} predicted "
                     f"({'over' if gap >= 0 else 'under'}-performing by {abs(gap) * 100:.1f} points).")
    if cal["brier_model"] is not None and cal["brier_market"] is not None:
        better = cal["brier_model"] < cal["brier_market"]
        notes.append(f"Across {cal['n_market']} resolved markets the model's Brier score {_num(cal['brier_model'])} "
                     f"was {'better' if better else 'worse'} than the market's {_num(cal['brier_market'])}.")
    return notes


def to_markdown(rep: dict) -> str:
    ov, cal = rep["overview"], rep["prediction_calibration"]
    lines = [
        "# Paper-trading performance report", "",
        f"Mode: **{ov['mode']}** · real money used: **${ov['real_money']:.2f}**", "",
        "## Verdict", "", *[f"- {n}" for n in rep["verdict"]], "",
        "## Results", "",
        "| Metric | Value |", "|---|---:|",
        f"| Starting bankroll | ${ov['starting_bankroll']:.2f} |",
        f"| Equity (open bets at cost) | ${ov['equity']:.2f} |",
        f"| Total P/L | ${ov['total_pnl']:.2f} |",
        f"| Return on bankroll | {_pct(ov['return_on_bankroll'])} |",
        f"| ROI on settled stakes | {_pct(ov['roi_on_staked'])} |",
        f"| ROI 95% bootstrap interval | {' to '.join(_pct(x) for x in ov['roi_95ci']) if ov['roi_95ci'] else 'n/a'} |",
        f"| Bets placed / settled / open | {ov['n_bets']} / {ov['n_settled']} / {ov['n_open']} |",
        f"| Win rate (predicted) | {_pct(ov['win_rate'])} ({_pct(ov['expected_win_rate'])}) |",
        f"| Average confidence | {_pct(ov['avg_confidence'])} |",
        f"| Average edge | {_num(ov['avg_edge'])} |",
        f"| Brier on bets: model / market | {_num(ov['brier_bets'])} / {_num(ov['brier_market_on_bets'])} |",
        f"| Max drawdown | ${ov['max_drawdown']:.2f} ({_pct(ov['max_drawdown_pct'])}) |", "",
        "## Calibration of all predictions on resolved markets", "",
        f"Markets: {cal['n']} · Brier model {_num(cal['brier_model'])} · market {_num(cal['brier_market'])} · "
        f"log loss {_num(cal.get('log_loss_model'))} · expected calibration error {_num(cal.get('ece_model'))}", "",
        "| Predicted bin | n | Mean predicted | Observed |", "|---|---:|---:|---:|",
        *[f"| {b['bin']} | {b['n']} | {_pct(b['mean_pred'])} | {_pct(b['observed'])} |" for b in cal["bins"]],
    ]
    if cal.get("n_calibrated"):
        lines += ["", f"After calibration ({cal['n_calibrated']} of {cal['n']} markets had an approved calibrator): "
                  f"Brier {_num(cal['brier_calibrated'])} · log loss {_num(cal['log_loss_calibrated'])} · "
                  f"expected calibration error {_num(cal['ece_calibrated'])}", "",
                  "| Calibrated bin | n | Mean calibrated | Observed |", "|---|---:|---:|---:|",
                  *[f"| {b['bin']} | {b['n']} | {_pct(b['mean_pred'])} | {_pct(b['observed'])} |"
                    for b in cal["bins_calibrated"]]]
    cals = rep.get("calibrators")
    if cals:
        lines += ["", "## Probability calibrators (latest fit)", "",
                  f"Fitted {str(cals[0]['fitted_at'])[:16]} on {cals[0]['n']} resolved markets "
                  f"({cals[0]['n_train']} to fit, the newest {cals[0]['n_holdout']} to judge).", "",
                  "| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |",
                  "|---|---|---|---|---|"]
        lines += [f"| {c['method']} | {_num(c['brier_before'])} → {_num(c['brier_after'])} | "
                  f"{_num(c['log_loss_before'])} → {_num(c['log_loss_after'])} | "
                  f"{'yes' if c['approved'] else 'no: ' + (c['reason'] or '')} | {'yes' if c['selected'] else ''} |"
                  for c in cals]
    comp = rep.get("model_comparison")
    if comp:
        lines += ["", "## Model comparison", "",
                  f"Each model's prediction from the same cycle as the production model's last prediction made "
                  f"{comp['min_lead_days']}+ day ahead, on {comp['n_markets']} resolved markets. Each row is scored "
                  "on the markets that model predicted, and the production columns on exactly those markets. "
                  "Lower is better.", "",
                  "| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        lines += [f"| {m['model']} | {m['role']} | {m['n']} | {_num(m['brier'])} | {_num(m['log_loss'])} | "
                  f"{_num(m['production_brier'])} | {_num(m['production_log_loss'])} |" for m in comp["models"]]
    days = by_day(rep.get("bets") or [])
    if days:
        lines += ["", "## Results by market day", "",
                  "| Market day | Bets | Won | Lost | Open | Staked | Settled P/L |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        lines += [f"| {d['day']} | {len(d['bets'])} | {d['won']} | {d['lost']} | {d['open']} | "
                  f"${d['staked']:.2f} | ${d['pnl']:.2f} |" for d in days]
        lines += ["", "## Every bet, by market day"]
        for d in days:
            lines += ["", f"### {d['day']}", "",
                      "| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |",
                      "|---:|---|---|---|---:|---:|---:|---:|---|---:|"]
            for b in d["bets"]:
                pnl = "" if b["pnl"] is None else f"${b['pnl']:.2f}"
                lines.append(f"| {b['id']} | {str(b['opened_at'])[:16]} | {b['event_title']} {b['bucket_label']} | "
                             f"{b['side']} | {b['entry_price']:.3f} | {_pct(b['model_prob'])} | "
                             f"{_pct(b['market_prob'])} | ${b['stake']:.2f} | {b['status']} | {pnl} |")
    st = rep.get("status")
    if st:
        last = st["last_cycle"] or {}
        lines += ["", "## Bot status", "",
                  f"Last cycle: {last.get('at', 'never')} · markets monitored: {st['markets_monitored'] or 0}", ""]
        if last.get("summary"):
            lines += ["```", json.dumps(last["summary"], indent=1, default=str), "```"]
        if st["recent_problems"]:
            lines += ["", "Recent warnings and errors:", ""]
            lines += [f"- {str(p['ts'])[:16]} {p['level']} {p['component']}: {p['message'][:200]}"
                      for p in st["recent_problems"]]
    return "\n".join(lines) + "\n"
