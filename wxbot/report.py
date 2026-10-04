"""End-of-experiment performance report (markdown + JSON)."""
from __future__ import annotations

import json

from sqlalchemy import desc, select

from wxbot.db import Database, markets, paper_bets, system_events
from wxbot.evaluation.errors import error_analysis
from wxbot.evaluation.metrics import latest_calibrators, model_comparison, overview, prediction_calibration
from wxbot.learning import summary as learning_summary


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x, nd=4) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def build_report(db: Database, initial: float) -> dict:
    ov = overview(db, initial)
    cal = prediction_calibration(db)
    return {"overview": ov, "prediction_calibration": cal, "model_comparison": model_comparison(db),
            "calibrators": latest_calibrators(db), "errors": error_analysis(db),
            "model_updates": learning_summary(db, limit=10),
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


def model_updates(mu: dict | None) -> list[str]:
    """The station bias/spread param sets: which is in use, and every retraining
    and rollback (wxbot/learning/)."""
    if not mu or not mu["sets"]:
        return []
    prod = mu["production"]
    out = ["", "## Model updates", "",
           (f"Station bias and error spread in use: **{prod['version']}** ({prod['origin']}, fitted on "
            f"{prod['train_from']} to {prod['train_to']}, in production since {str(prod['deployed_at'])[:16]})."
            if prod else "Station bias and error spread in use: the default spreads (no parameter set yet)."),
           "A retrained set replaces it only if it scores better on markets none of the candidates was fitted on; "
           "the replaced set is kept and put back if the new one then does reliably worse.", "",
           "| Set | Status | Trained on | Out-of-sample markets | Brier production → set | "
           "Log loss production → set | Decision |", "|---|---|---|---:|---|---|---|"]
    for s in mu["sets"]:
        ev = s["evaluation"] or {}
        trained = f"{s['train_from']} to {s['train_to']}" if s["train_from"] else "–"
        scores = (f"{_num(ev['brier_old'])} → {_num(ev['brier_new'])} | "
                  f"{_num(ev['log_loss_old'])} → {_num(ev['log_loss_new'])}") if ev.get("n") else "– | –"
        out.append(f"| {s['version']} | {s['status']} | {trained} | {ev.get('n', '–')} | {scores} | "
                   f"{s['reason'] or ''} |")
    return out


def to_markdown(rep: dict) -> str:
    ov, cal = rep["overview"], rep["prediction_calibration"]
    exp = ov.get("experiment")
    lines = [
        "# Paper-trading performance report", "",
        f"Mode: **{ov['mode']}** · real money used: **${ov['real_money']:.2f}**", "",
        *([f"Experiment: **{exp['name']}** · started {str(exp['started_at'])[:16]} UTC · starting bankroll "
           f"${exp['initial_bankroll']:,.2f}" + (f" · code {exp['git_ref'][:12]}" if exp.get("git_ref") else "")
           + (f" (now {exp['code_ref'][:12]})" if exp.get("code_ref") and exp["code_ref"] != exp.get("git_ref")
              else ""), ""]
          if exp else []),
        "## Verdict", "", *[f"- {n}" for n in rep["verdict"]], "",
        "## Results", "",
        "| Metric | Value |", "|---|---:|",
        f"| Starting bankroll | ${ov['starting_bankroll']:.2f} |",
        f"| Equity (open bets at the bid) | ${ov['equity']:.2f} |",
        f"| Cash available | ${ov['cash']:.2f} |",
        f"| Open positions: count / cost / value at the bid | {ov['n_open_positions']} / "
        f"${ov['open_exposure']:.2f} / ${ov['market_value']:.2f} |",
        f"| Realized / unrealized P/L | ${ov['realized_pnl']:.2f} / ${ov['unrealized_pnl']:.2f} |",
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
    positions = ov.get("positions") or []
    if positions:
        lines += ["", "## Open positions", "",
                  "Valued at the best bid of the side held in the latest market snapshot "
                  "(the side's last price when there is no bid, cost when there is no snapshot).", "",
                  "| Bet | Market | Side | Shares | Cost | Entry | Mark | Value | Unrealized |",
                  "|---:|---|---|---:|---:|---:|---:|---:|---:|"]
        for p in positions:
            mark = "cost" if p["mark_price"] is None else f"{p['mark_price']:.3f}"
            if p["marked_by"] == "price":
                mark += " (price)"
            lines.append(f"| {p['bet_id']} | {p['question'] or p['market_id']} | {p['side']} | {p['shares']:.2f} | "
                         f"${p['stake']:.2f} | {p['entry_price']:.3f} | {mark} | ${p['value']:.2f} | "
                         f"${p['unrealized_pnl']:.2f} |")
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
    lines += model_updates(rep.get("model_updates"))
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
    err = rep.get("errors")
    if err and err["n"]:
        lines += ["", "## Recurring weaknesses", "",
                  f"Where the model was wrong in a consistent way, on {err['n']} resolved markets and "
                  f"{err['bets']['n']} settled bets: groups with at least {err['min_group']} markets "
                  f"({err['min_bet_group']} bets) and a gap of at least {err['flag_z']:g} standard errors. "
                  "The dashboard's Learning tab has every breakdown.", ""]
        if err["weaknesses"]:
            lines += ["| Where | Breakdown | Group | n | Weakness | Evidence |", "|---|---|---|---:|---|---|"]
            lines += [f"| {w['scope']} | {w['dimension']} | {w['group']} | {w['n']} | {w['flag']} | {w['detail']} |"
                      for w in err["weaknesses"][:12]]
        else:
            lines.append("None flagged yet.")
        counts = ", ".join(f"{c['class']} {c['n']}" for c in err["classes"])
        lines += ["", f"Error classes: {counts}."]
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
