"""BACKTEST.md: the market backtest's report as Markdown."""
from __future__ import annotations


def _n(x) -> str:
    return "–" if x is None else f"{x:,}"


def _f(x, nd: int = 4) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _pct(x, nd: int = 1) -> str:
    return "–" if x is None else f"{100 * x:.{nd}f}%"


def _money(x) -> str:
    return "–" if x is None else f"{'-' if x < 0 else ''}${abs(x):,.2f}"


def _ci(d: dict | None, fmt=_f) -> str:
    if not d or d.get("mean") is None:
        return "–"
    if d.get("lo") is None:
        return f"{fmt(d['mean'])} (too few events for an interval)"
    return f"{fmt(d['mean'])} ({fmt(d['lo'])} to {fmt(d['hi'])})"


def _roi(s: dict) -> str:
    if not s.get("bets"):
        return "–"
    if s.get("roi_lo") is None:
        return _pct(s["roi"])
    return f"{_pct(s['roi'])} ({_pct(s['roi_lo'])} to {_pct(s['roi_hi'])})"


def _bets_row(label: str, s: dict) -> str:
    if not s.get("bets"):
        return f"| {label} | 0 | – | – | – | – | – | – |"
    return (f"| {label} | {_n(s['bets'])} | {_n(s['won'])} | {_pct(s['win_rate'])} | {_pct(s['mean_predicted'])} | "
            f"{_f(s['mean_entry'], 3)} | {_money(s['pnl'])} | {_roi(s)} |")


def to_markdown(rep: dict) -> str:
    p, data, rp, sc = rep["params"], rep["data"], rep["replay"], rep["scores"]
    s = p["settings"]["backtest"]
    delay = float(s["forecast_delay_hours"])
    leads = ", ".join(f"lead {x} = {24 * int(x) - delay:g} h" for x in s["leads"])
    out = [
        "# Market backtest", "",
        f"{p['start']} to {p['end']} · run #{rep['run_id']}"
        + (f" · code {p['git_ref'][:12]}" if p.get("git_ref") else "")
        + (" · replayed from stored data only" if p["offline"] else ""),
        "",
        "Research only: historical markets replayed with simulated $1 and paper-bankroll bets. No money is involved.",
        "", "## Data", "",
        "| Markets in the window | Count |", "|---|---:|",
        f"| Events | {_n(data['events'])} |",
        f"| Markets | {_n(data['markets'])} |",
        f"| Not tradeable (station or rules not supported) | {_n(data['not_tradeable'])} |",
        f"| Tradeable, no result | {_n(data['tradeable_unresolved'])} |",
        f"| Tradeable with a result, no price history | {_n(data['tradeable_resolved_no_prices'])} |",
        f"| Tradeable with a result and prices | {_n(data['tradeable_resolved_with_prices'])} |",
        "",
    ]
    if data["not_tradeable_reasons"]:
        out += ["Not tradeable: " + "; ".join(f"{k} {_n(v)}" for k, v in data["not_tradeable_reasons"].items()) + ".",
                ""]
    skipped = {k: v for k, v in rp["skipped"].items() if v}
    out += [f"Decisions replayed: {_n(rp['rows'])} (one per market and lead)"
            + (". Skipped: " + "; ".join(f"{k} {_n(v)}" for k, v in skipped.items()) if skipped else "") + ".", "",
            "## How each decision was made", "",
            f"- Decision times: {leads} before the end of the market's local day. Lead N uses the forecast each "
            f"model issued at least N days before (Open-Meteo Previous Runs), assumed downloadable {delay:g} h "
            "after the run started, so it was available at the decision time.",
            "- Market price: the last hourly YES price at or before the decision time (a mid price). Buying costs "
            f"{s['half_spread']} more (half the spread), plus slippage and fees as configured.",
            "- Model: the production model with each station's bias and error spread fitted only on days that "
            "had ended before the decision. Calibrated: the live calibrator rule, refitted daily on markets whose "
            "result was already known.",
            "- Every source is clipped to the model's probability floor and ceiling before scoring.", "",
            f"## Probability scores ({_n(sc['n_common'])} decisions, {_n(sc['n_markets'])} markets, "
            f"{_n(sc['n_events'])} events)", "",
            "Lower is better. A difference with its whole interval below 0 beat the market on these markets. "
            "Intervals resample whole events.", "",
            "| Source | Brier | Log loss | Calibration error | Brier − market (95% CI) | Log loss − market (95% CI) |",
            "|---|---:|---:|---:|---|---|"]
    for e in sc["sources"]:
        out.append(f"| {e['label']} | {_f(e['brier'])} | {_f(e['log_loss'])} | {_f(e['ece'])} | "
                   f"{_ci(e.get('brier_minus_market')) if e['source'] != 'market' else '–'} | "
                   f"{_ci(e.get('log_loss_minus_market')) if e['source'] != 'market' else '–'} |")
    labels = {e["source"]: e["label"] for e in sc["sources"]}
    out += ["", "### Brier score by lead", "",
            "| Lead | Hours before day end | Decisions | " + " | ".join(labels.values()) + " |",
            "|---|---:|---:|" + "---:|" * len(labels)]
    for row in sc["by_lead"]:
        out.append(f"| {row['lead_days']} | {row['lead_hours']:g} | {_n(row['n'])} | "
                   + " | ".join(_f(row[k]) for k in labels) + " |")
    flat = rep["flat_stake"]
    head = ["| | Bets | Won | Win rate | Predicted | Mean entry | P/L | ROI (95% CI) |",
            "|---|---:|---:|---:|---:|---:|---:|---|"]
    out += ["", "## Flat $1 bets: live rules on the calibrated probability", "",
            "One $1 bet on every decision that passes the betting rules, at most one per market. ROI is P/L per "
            "dollar staked; the interval resamples whole events.", "", *head, _bets_row("All", flat)]
    out += [_bets_row(f"Lead {k}", v) for k, v in flat.get("by_lead", {}).items()]
    out += [_bets_row(f"{k} side", v) for k, v in flat.get("by_side", {}).items()]
    out += ["", "### The same rules with each probability", "", *head]
    out += [_bets_row(labels.get(k, k), v) for k, v in rep["flat_stake_by_source"].items()]
    out += ["", "### Sensitivity to the assumed half spread", "",
            "| Half spread | Bets | Win rate | Predicted | P/L | ROI |", "|---:|---:|---:|---:|---:|---:|"]
    for x in rep["half_spread_sensitivity"]:
        out.append(f"| {x['half_spread']} | {_n(x.get('bets', 0))} | {_pct(x.get('win_rate'))} | "
                   f"{_pct(x.get('mean_predicted'))} | {_money(x.get('pnl'))} | {_pct(x.get('roi'))} |")
    bk = rep["bankroll"]
    out += ["", f"## {_money(bk['initial'])} bankroll with the live sizing and risk caps", "",
            "| Start | End | P/L | ROI | Bets | Won | Staked | Max drawdown |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
            f"| {_money(bk['initial'])} | {_money(bk['final'])} | {_money(bk['pnl'])} | {_pct(bk['roi'])} | "
            f"{_n(bk['bets'])} | {_n(bk['won'])} | {_money(bk['staked'])} | {_money(bk['max_drawdown'])} "
            f"({_pct(bk['max_drawdown_pct'])}) |"]
    rounds = rep.get("calibration_rounds") or []
    used = [r for r in rounds if r["using"] != "identity"]
    out += ["", "## Probability calibrator", "",
            f"Refitted {len(rounds)} times as results came in. "
            + (f"First approved on {used[0]['fit_time'][:10]} ({used[0]['using']}, {used[0]['n']} markets known); "
               f"approved in {len(used)} of {len(rounds)} fits." if used
               else "Never approved: the calibrated probability is the model's.")]
    out += ["", "## Not replayed", ""] + [f"- {k.replace('_', ' ')}: {v}." for k, v in rep["not_replayed"].items()]
    return "\n".join(out) + "\n"
