# Paper-trading performance report

Mode: **PAPER TRADING** · real money used: **$0.00**

Experiment: **exp3-v3-100usd** · started 2026-10-15 18:50 UTC · starting bankroll $100.00 · code ba8aea21905d (now 6c965d907eca) · day 10 of 30, ends 2026-11-14 18:50 UTC

## Verdict

- Only 1 settled bets: too few to conclude anything about profitability (aim for several hundred).
- Bets won 0.0% against 83.0% predicted (under-performing by 83.0 points).
- Across 2398 resolved liquid markets the model's Brier score 0.0616 was worse than the market's 0.0561.
- The market check is off: bets use the model's own probability, without first checking that it beats the market price on held-out markets. Its last fit (2026-10-21 07:52 UTC) was not approved: the model adds nothing to the market price on the holdout (Brier or log loss not lower). See Market anchor below.

## Results

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Equity (open bets at the bid) | $98.00 |
| Cash available | $98.00 |
| Open positions: count / cost / value at the bid | 0 / $0.00 / $0.00 |
| Realized / unrealized P/L | $-2.00 / $0.00 |
| Total P/L | $-2.00 |
| Return on bankroll | -2.0% |
| ROI on settled stakes | -100.0% |
| ROI 95% bootstrap interval | n/a |
| Bets placed / settled / open | 1 / 1 / 0 |
| Win rate (predicted) | 0.0% (83.0%) |
| Average confidence | 83.0% |
| Average edge | 0.2491 |
| Brier on bets: model / market | 0.6897 / 0.3080 |
| Max drawdown | $2.03 (2.0%) |

## Calibration of all predictions on resolved markets

Markets: 3936 · Brier model 0.0634 · log loss 0.2048 · expected calibration error 0.0112 · on the 2398 liquid markets, Brier model 0.0616 vs market 0.0561

| Predicted bin | n | Mean predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 2690 | 2.0% | 0.9% |
| 0.1-0.2 | 425 | 14.7% | 14.4% |
| 0.2-0.3 | 389 | 24.9% | 25.2% |
| 0.3-0.4 | 302 | 34.5% | 36.1% |
| 0.4-0.5 | 114 | 43.4% | 46.5% |
| 0.5-0.6 | 14 | 52.7% | 78.6% |
| 0.6-0.7 | 1 | 70.0% | 100.0% |
| 0.9-1.0 | 1 | 97.9% | 100.0% |

After calibration (583 of 3936 markets had an approved calibrator): Brier 0.0633 · log loss 0.2047 · expected calibration error 0.0102

| Calibrated bin | n | Mean calibrated | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 2705 | 2.0% | 0.9% |
| 0.1-0.2 | 429 | 14.7% | 14.9% |
| 0.2-0.3 | 357 | 24.9% | 24.9% |
| 0.3-0.4 | 315 | 34.6% | 36.2% |
| 0.4-0.5 | 102 | 43.2% | 46.1% |
| 0.5-0.6 | 24 | 53.2% | 62.5% |
| 0.6-0.7 | 3 | 66.0% | 100.0% |
| 0.9-1.0 | 1 | 97.9% | 100.0% |

## Probability calibrators (latest fit)

Fitted 2026-10-24 17:32 on 4019 resolved markets (2813 to fit, the newest 1206 to judge).

| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |
|---|---|---|---|---|
| isotonic | 0.0716 → 0.0715 | 0.2252 → 0.2248 | no: gain not reliable: wins in 59% of bootstrap resamples (need 95%) |  |
| platt | 0.0716 → 0.0711 | 0.2252 → 0.2232 | no: gain not reliable: wins in 90% of bootstrap resamples (need 95%) |  |

## Market anchor (off, last fit)

The market check is off ([market_anchor] enabled = false): the bot bets on the model's own probability, and the anchor is no longer refitted. This is its last fit, from before it was turned off.

Fitted 2026-10-21 07:52 UTC on 694 resolved markets with a tight book (486 to fit, the newest 208 to judge): **not approved**, the model adds nothing to the market price on the holdout (Brier or log loss not lower).

Weights: model 0.06, market price 1.06, constant 0.11 (a model weight near zero means the price already holds what the model knows).

| On the holdout | Brier | Log loss |
|---|---:|---:|
| Market price | 0.0839 | 0.2567 |
| Model alone | 0.0967 | 0.2969 |
| Model + market | 0.0834 | 0.2568 |

## Same-day model (forward test)

On each market's own day the same-day model prices every bucket from the station's reports so far and the newest hourly forecast. It is scored here against the market's mid price at the same moment, on resolved markets whose book was tight then (lower is better). With the market check off it does not bet.

| Hours left | Predictions | Markets | Log loss: model / market | Brier: model / market |
|---|---:|---:|---|---|
| 0-3 | 112 | 105 | 0.0024 / 0.0060 | 0.0002 / 0.0001 |
| 3-6 | 222 | 212 | 0.0307 / 0.0532 | 0.0078 / 0.0123 |
| 6-12 | 616 | 575 | 0.0763 / 0.0240 | 0.0157 / 0.0049 |
| 12-24 | 2909 | 1501 | 0.2808 / 0.2271 | 0.0871 / 0.0714 |
| all | 3859 | 1580 | 0.2257 / 0.1782 | 0.0686 / 0.0553 |

Last anchor fit 2026-10-21 07:52 UTC on 651 markets (456 to fit, the newest 195 to judge): **not approved**, the model adds nothing to the market price on the holdout (Brier or log loss not lower) (1005 predictions).

## Model updates

Station bias and error spread in use: **bias-sigma-20261015-backtest-run1** (backtest, fitted on 2026-07-17 to 2026-10-14, in production since 2026-10-15 18:53).
A retrained set replaces it only if it scores better on markets none of the candidates was fitted on; the replaced set is kept and put back if the new one then does reliably worse.

| Set | Status | Trained on | Out-of-sample markets | Brier production → set | Log loss production → set | Decision |
|---|---|---|---:|---|---|---|
| bias-sigma-20261015-backtest-run1 | production | 2026-07-17 to 2026-10-14 | – | – | – | first fit: nothing to compare it with |

## Model comparison

Each model's prediction from the same cycle as the production model's last prediction made 1+ day ahead, on 3936 resolved markets. Each row is scored on the markets that model predicted, and the production columns on exactly those markets; the market price only on markets that passed the liquidity check, since a thin market's mid is a placeholder. Lower is better.

| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |
|---|---|---:|---:|---:|---:|---:|
| climatology-v1 | shadow | 3936 | 0.0932 | 0.3386 | 0.0634 | 0.2048 |
| normal-multimodel-v1 | shadow | 3936 | 0.0671 | 0.2192 | 0.0634 | 0.2048 |
| raw-forecast-v1 | shadow | 3936 | 0.0710 | 0.2361 | 0.0634 | 0.2048 |
| weighted-multimodel-v1 | production | 3936 | 0.0634 | 0.2048 | 0.0634 | 0.2048 |
| weighted-multimodel-v1 calibrated | production | 583 | 0.0622 | 0.1971 | 0.0625 | 0.1982 |
| market price (mid) | benchmark | 2398 | 0.0561 | 0.1791 | 0.0617 | 0.1979 |

## Recurring weaknesses

Where the model was wrong in a consistent way, on 3936 resolved markets and 1 settled bets: groups with at least 30 markets (15 bets) and a gap of at least 3 standard errors. The dashboard's Learning tab has every breakdown.

| Where | Breakdown | Group | n | Weakness | Evidence |
|---|---|---|---:|---|---|
| predictions | Highest or lowest temperature | high | 2001 | worse than the market | Brier 0.0643 vs the market's 0.0556 on 2001 markets |
| predictions | Bucket vs forecast | within 1σ | 746 | worse than the market | Brier 0.1800 vs the market's 0.1523 on 444 markets |
| predictions | Predicted probability | 20–50% | 805 | worse than the market | Brier 0.2129 vs the market's 0.1885 on 480 markets |
| predictions | Market liquidity | $1k–5k | 2032 | worse than the market | Brier 0.0550 vs the market's 0.0494 on 2032 markets |
| predictions | All resolved markets | all | 3936 | worse than the market | Brier 0.0617 vs the market's 0.0561 on 2398 markets |
| predictions | Predicted probability | 0–5% | 2409 | underconfident | 98.7% sure of the side it predicted on average; that side happened 99.5% of the time |
| predictions | Predicted probability | 0–5% | 2409 | YES too often | predicted 1.3% YES on average; 0.5% resolved YES |
| predictions | Weather-model disagreement | 0.5–1°C | 1441 | worse than the market | Brier 0.0597 vs the market's 0.0515 on 1032 markets |
| predictions | Bucket vs forecast | 1–2σ away | 717 | YES too often | predicted 6.6% YES on average; 3.5% resolved YES |
| predictions | Bucket vs forecast | 1–2σ away | 717 | underconfident | 93.4% sure of the side it predicted on average; that side happened 96.5% of the time |
| predictions | Bucket vs forecast | over 2σ away | 2115 | YES too often | predicted 1.1% YES on average; 0.3% resolved YES |
| predictions | Bucket vs forecast | over 2σ away | 2115 | underconfident | 98.9% sure of the side it predicted on average; that side happened 99.7% of the time |

Error classes: right side 3588, overconfidence 3, significant overconfidence 0, underestimation 260, significant underestimation 85.

## Operation

How continuously the bot ran: each completed cycle collects data, predicts, bets and settles.

| Measure | Value |
|---|---:|
| Cycles completed | 46 |
| First / last cycle (UTC) | 2026-10-15 18:55 / 2026-10-24 22:37 |
| Median time between cycles | 4.8 h |
| Longest gap | 8.3 h (2026-10-21 23:28 to 2026-10-22 07:47) |
| Finished days without a cycle | 0 of 9 |
| Errors logged | none |

## Results by market day

| Market day | Bets | Won | Lost | Open | Staked | Settled P/L |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-22 | 1 | 0 | 1 | 0 | $2.00 | $-2.00 |

## Every bet, by market day

### 2026-10-22

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 1 | 2026-10-22 12:36 | Highest temperature in Los Angeles on October 22? 70-71°F | NO | 0.581 | 83.0% | 55.5% | $2.00 | LOST | $-2.00 |

## Bot status

Last cycle: 2026-10-24T22:37:37.512389+00:00 · markets monitored: 0

```
{
 "markets": {
  "seen": 2673,
  "tradeable": 0
 },
 "forecasts": {
  "stations": 0,
  "snapshots": 0
 },
 "reports": {
  "stations": 0,
  "new_reports": 0
 },
 "model_stats": {
  "at": "2026-10-24T22:34:59.338146+00:00",
  "retry": true,
  "stations": 0,
  "rows": 0,
  "failed": {
   "ZSJN": "no usable data: too few days with both forecasts and observations"
  },
  "days": 120,
  "loaded": 192
 },
 "calibration": {
  "skipped": true
 },
 "market_anchor": {
  "enabled": false
 },
 "signals": {
  "predictions": 0,
  "shadow_predictions": 0,
  "bets": 0
 },
 "settlement": {
  "checked": 500,
  "bets_settled": 0,
  "price_histories": 300
 },
 "experiment": {
  "state": "running",
  "day": 10,
  "planned_days": 30,
  "ends_at": "2026-11-14T18:50:42.284968+00:00",
  "open_bets": 0,
  "ended_at": null,
  "completed_at": null
 },
 "observations": {
  "stations": 27,
  "new_rows": 22
 },
 "learning": {
  "outcomes": {
   "recorded": 0
  },
  "rollback": {
   "skipped": "the production model (weighted-multimodel) refits its own biases daily (wxbot/learning/model_stats.py), so the station bias/spread sets are not retrained"
  },
  "retrain": {
   "skipped": "the production model (weighted-multimodel) refits its own biases daily (wxbot/learning/model_stats.py), so the station bias/spread sets are not retrained"
  }
 },
 "seconds": 165.0
}
```

Recent warnings and errors:

- 2026-10-24 22:35 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-24 17:32 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 32 stations on the last 120 days; 1 failed, tried again after 3 h
- 2026-10-24 12:47 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-24 07:25 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-23 23:14 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-23 18:30 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-23 13:39 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 32 stations on the last 120 days; 1 failed, tried again after 3 h
- 2026-10-23 07:42 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-22 23:28 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-22 18:39 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h

