"""End-of-experiment performance report (markdown + JSON)."""
from __future__ import annotations

from wxbot.db import Database
from wxbot.evaluation.metrics import overview, prediction_calibration


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _num(x, nd=4) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def build_report(db: Database, initial: float) -> dict:
    ov = overview(db, initial)
    cal = prediction_calibration(db)
    return {"overview": ov, "prediction_calibration": cal, "verdict": verdict(ov, cal)}


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
        f"Markets: {cal['n']} · Brier model {_num(cal['brier_model'])} · market {_num(cal['brier_market'])}", "",
        "| Predicted bin | n | Mean predicted | Observed |", "|---|---:|---:|---:|",
        *[f"| {b['bin']} | {b['n']} | {_pct(b['mean_pred'])} | {_pct(b['observed'])} |" for b in cal["bins"]],
    ]
    return "\n".join(lines) + "\n"
