# Paper-trading performance report

Mode: **PAPER TRADING** · real money used: **$0.00**

Experiment: **exp3-v3-100usd** · started 2026-10-15 18:50 UTC · starting bankroll $100.00 · code ba8aea21905d · day 2 of 30, ends 2026-11-14 18:50 UTC

## Verdict

- Only 0 settled bets: too few to conclude anything about profitability (aim for several hundred).
- Across 252 resolved liquid markets the model's Brier score 0.0669 was worse than the market's 0.0542.
- New bets are paused: the model has not yet beaten the market price on held-out markets (latest fit 2026-10-16 22:56 UTC: only 0 resolved markets with a tight book (need 300)). See Market anchor below.

## Results

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Equity (open bets at the bid) | $100.00 |
| Cash available | $100.00 |
| Open positions: count / cost / value at the bid | 0 / $0.00 / $0.00 |
| Realized / unrealized P/L | $0.00 / $0.00 |
| Total P/L | $0.00 |
| Return on bankroll | 0.0% |
| ROI on settled stakes | n/a |
| ROI 95% bootstrap interval | n/a |
| Bets placed / settled / open | 0 / 0 / 0 |
| Win rate (predicted) | n/a (n/a) |
| Average confidence | n/a |
| Average edge | n/a |
| Brier on bets: model / market | n/a / n/a |
| Max drawdown | $0.00 (0.0%) |

## Calibration of all predictions on resolved markets

Markets: 440 · Brier model 0.0681 · log loss 0.2275 · expected calibration error 0.0168 · on the 252 liquid markets, Brier model 0.0669 vs market 0.0542

| Predicted bin | n | Mean predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 303 | 2.0% | 2.0% |
| 0.1-0.2 | 48 | 14.8% | 18.8% |
| 0.2-0.3 | 40 | 24.6% | 20.0% |
| 0.3-0.4 | 36 | 34.6% | 33.3% |
| 0.4-0.5 | 10 | 43.5% | 20.0% |
| 0.5-0.6 | 1 | 51.6% | 100.0% |
| 0.6-0.7 | 1 | 70.0% | 100.0% |
| 0.9-1.0 | 1 | 97.9% | 100.0% |

## Probability calibrators (latest fit)

Fitted 2026-10-16 22:56 on 0 resolved markets (0 to fit, the newest 0 to judge).

| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |
|---|---|---|---|---|
| isotonic | n/a → n/a | n/a → n/a | no: only 0 resolved markets (need 200) |  |
| platt | n/a → n/a | n/a → n/a | no: only 0 resolved markets (need 200) |  |

## Market anchor (latest fit)

The bot bets only on the model combined with the market price, and only while that combination beats the market price alone on resolved markets it was not fitted on.

Fitted 2026-10-16 22:56 UTC on 0 resolved markets with a tight book (0 to fit, the newest 0 to judge): **not approved**, only 0 resolved markets with a tight book (need 300).

## Same-day model (forward test)

On each market's own day the same-day model prices every bucket from the station's reports so far and the newest hourly forecast. It is scored here against the market's mid price at the same moment, on resolved markets whose book was tight then (lower is better). It can bet only once its own market anchor beats the market price on held-out markets.

| Hours left | Predictions | Markets | Log loss: model / market | Brier: model / market |
|---|---:|---:|---|---|
| 0-3 | 3 | 3 | 0.0521 / 0.0103 | 0.0068 / 0.0002 |
| 3-6 | 14 | 13 | 0.1477 / 0.3752 | 0.0512 / 0.1226 |
| 6-12 | 64 | 63 | 0.2697 / 0.0322 | 0.0479 / 0.0081 |
| 12-24 | 280 | 175 | 0.3037 / 0.2422 | 0.0928 / 0.0809 |
| all | 361 | 214 | 0.2896 / 0.2082 | 0.0825 / 0.0690 |

Latest anchor fit 2026-10-16 22:56 UTC on 50 markets (35 to fit, the newest 15 to judge): **not approved**, only 50 resolved markets with a tight book (need 300) (58 predictions).

## Model updates

Station bias and error spread in use: **bias-sigma-20261015-backtest-run1** (backtest, fitted on 2026-07-17 to 2026-10-14, in production since 2026-10-15 18:53).
A retrained set replaces it only if it scores better on markets none of the candidates was fitted on; the replaced set is kept and put back if the new one then does reliably worse.

| Set | Status | Trained on | Out-of-sample markets | Brier production → set | Log loss production → set | Decision |
|---|---|---|---:|---|---|---|
| bias-sigma-20261015-backtest-run1 | production | 2026-07-17 to 2026-10-14 | – | – | – | first fit: nothing to compare it with |

## Model comparison

Each model's prediction from the same cycle as the production model's last prediction made 1+ day ahead, on 440 resolved markets. Each row is scored on the markets that model predicted, and the production columns on exactly those markets; the market price only on markets that passed the liquidity check, since a thin market's mid is a placeholder. Lower is better.

| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |
|---|---|---:|---:|---:|---:|---:|
| climatology-v1 | shadow | 440 | 0.0963 | 0.3553 | 0.0681 | 0.2275 |
| normal-multimodel-v1 | shadow | 440 | 0.0684 | 0.2288 | 0.0681 | 0.2275 |
| raw-forecast-v1 | shadow | 440 | 0.0684 | 0.2304 | 0.0681 | 0.2275 |
| weighted-multimodel-v1 | production | 440 | 0.0681 | 0.2275 | 0.0681 | 0.2275 |
| market price (mid) | benchmark | 252 | 0.0542 | 0.1705 | 0.0669 | 0.2189 |

## Recurring weaknesses

Where the model was wrong in a consistent way, on 440 resolved markets and 0 settled bets: groups with at least 30 markets (15 bets) and a gap of at least 3 standard errors. The dashboard's Learning tab has every breakdown.

| Where | Breakdown | Group | n | Weakness | Evidence |
|---|---|---|---:|---|---|
| predictions | Highest or lowest temperature | high | 220 | worse than the market | Brier 0.0701 vs the market's 0.0532 on 220 markets |

Error classes: right side 403, overconfidence 0, significant overconfidence 0, underestimation 22, significant underestimation 15.

## Operation

How continuously the bot ran: each completed cycle collects data, predicts, bets and settles.

| Measure | Value |
|---|---:|
| Cycles completed | 10 |
| First / last cycle (UTC) | 2026-10-15 18:55 / 2026-10-17 12:17 |
| Median time between cycles | 4.8 h |
| Longest gap | 6.0 h (2026-10-16 07:22 to 2026-10-16 13:22) |
| Finished days without a cycle | 0 of 2 |
| Errors logged | none |

## Bot status

Last cycle: 2026-10-17T12:17:18.016131+00:00 · markets monitored: 1639

```
{
 "markets": {
  "seen": 3003,
  "tradeable": 1639
 },
 "forecasts": {
  "stations": 27,
  "snapshots": 149
 },
 "reports": {
  "stations": 27,
  "new_reports": 204
 },
 "model_stats": {
  "at": "2026-10-17T12:16:11.379439+00:00",
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
  "skipped": true
 },
 "signals": {
  "predictions": 1639,
  "shadow_predictions": 5500,
  "bets": 0
 },
 "settlement": {
  "checked": 185,
  "bets_settled": 0,
  "price_histories": 300
 },
 "experiment": {
  "state": "running",
  "day": 2,
  "planned_days": 30,
  "ends_at": "2026-11-14T18:50:42.284968+00:00",
  "open_bets": 0,
  "ended_at": null,
  "completed_at": null
 },
 "observations": {
  "skipped": true
 },
 "learning": {
  "outcomes": {
   "recorded": 130,
   "significant_errors": 9
  },
  "rollback": {
   "skipped": "the production model (weighted-multimodel) refits its own biases daily (wxbot/learning/model_stats.py), so the station bias/spread sets are not retrained"
  },
  "retrain": {
   "skipped": "the production model (weighted-multimodel) refits its own biases daily (wxbot/learning/model_stats.py), so the station bias/spread sets are not retrained"
  }
 },
 "seconds": 77.6
}
```

Recent warnings and errors:

- 2026-10-17 12:16 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-17 07:03 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-16 22:56 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 32 stations on the last 120 days; 1 failed, tried again after 3 h
- 2026-10-16 18:11 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-16 13:21 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-16 07:20 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-15 23:07 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 0 stations on the last 120 days (retry); 1 failed, tried again after 3 h
- 2026-10-15 18:55 WARNING model_stats: weighted-multimodel-v1: biases and errors refitted for 32 stations on the last 120 days; 1 failed, tried again after 3 h

