# Paper-trading performance report

Mode: **PAPER TRADING** · real money used: **$0.00**

Experiment: **exp2-100usd** · started 2026-10-01 21:48 UTC · starting bankroll $100.00 · code 266ddda9e1b6

## Verdict

- Only 15 settled bets: too few to conclude anything about profitability (aim for several hundred).
- ROI 95% interval -27.3% to 33.7% includes zero: no evidence either way.
- Bets won 73.3% against 87.9% predicted (under-performing by 14.5 points).
- Across 419 resolved markets the model's Brier score 0.0664 was better than the market's 0.0993.

## Results

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Equity (open bets at the bid) | $101.51 |
| Cash available | $71.04 |
| Open positions: count / cost / value at the bid | 16 / $30.25 / $30.47 |
| Realized / unrealized P/L | $1.29 / $0.22 |
| Total P/L | $1.51 |
| Return on bankroll | 1.5% |
| ROI on settled stakes | 4.5% |
| ROI 95% bootstrap interval | -27.3% to 33.7% |
| Bets placed / settled / open | 31 / 15 / 16 |
| Win rate (predicted) | 73.3% (87.9%) |
| Average confidence | 88.1% |
| Average edge | 0.1553 |
| Brier on bets: model / market | 0.2186 / 0.1982 |
| Max drawdown | $4.66 (4.5%) |

## Calibration of all predictions on resolved markets

Markets: 419 · Brier model 0.0664 · market 0.0993 · log loss 0.2112 · expected calibration error 0.0182

| Predicted bin | n | Mean predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 281 | 2.1% | 1.1% |
| 0.1-0.2 | 51 | 13.8% | 13.7% |
| 0.2-0.3 | 45 | 24.6% | 28.9% |
| 0.3-0.4 | 33 | 34.8% | 39.4% |
| 0.4-0.5 | 7 | 44.3% | 28.6% |
| 0.5-0.6 | 2 | 52.2% | 50.0% |

## Open positions

Valued at the best bid of the side held in the latest market snapshot (the side's last price when there is no bid, cost when there is no snapshot).

| Bet | Market | Side | Shares | Cost | Entry | Mark | Value | Unrealized |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 14 | Will the lowest temperature in London be 12°C on October 3? | NO | 2.25 | $1.97 | 0.879 | 0.971 | $2.18 | $0.21 |
| 17 | Will the highest temperature in London be 22°C on October 3? | NO | 2.53 | $2.09 | 0.825 | 0.999 | $2.53 | $0.44 |
| 18 | Will the highest temperature in Atlanta be between 80-81°F on October 3? | NO | 2.32 | $2.03 | 0.877 | 0.999 | $2.31 | $0.28 |
| 19 | Will the highest temperature in Chicago be between 68-69°F on October 3? | NO | 3.37 | $1.40 | 0.415 | 0.002 | $0.01 | $-1.39 |
| 20 | Will the highest temperature in Seattle be between 70-71°F on October 3? | NO | 2.80 | $2.03 | 0.725 | 0.930 | $2.60 | $0.57 |
| 21 | Will the highest temperature in Los Angeles be between 98-99°F on October 3? | NO | 3.00 | $2.03 | 0.675 | 0.999 | $3.00 | $0.97 |
| 22 | Will the highest temperature in London be 22°C on October 4? | NO | 3.65 | $2.03 | 0.555 | 0.470 | $1.72 | $-0.31 |
| 23 | Will the highest temperature in London be 23°C on October 4? | NO | 2.26 | $2.02 | 0.895 | 0.890 | $2.01 | $-0.01 |
| 24 | Will the highest temperature in Seoul (Incheon) be 22°C on October 4? | NO | 2.61 | $2.02 | 0.775 | 0.710 | $1.85 | $-0.17 |
| 25 | Will the highest temperature in Ankara be 20°C on October 4? | NO | 1.60 | $1.11 | 0.695 | 0.780 | $1.25 | $0.14 |
| 26 | Will the highest temperature in Lucknow be 33°C on October 4? | NO | 3.74 | $2.00 | 0.535 | 0.490 | $1.83 | $-0.17 |
| 27 | Will the highest temperature in Munich be 21°C on October 4? | NO | 2.72 | $2.00 | 0.735 | 0.650 | $1.77 | $-0.23 |
| 28 | Will the highest temperature in Tokyo be 22°C on October 4? | NO | 2.68 | $2.00 | 0.745 | 0.710 | $1.90 | $-0.09 |
| 29 | Will the highest temperature in Shanghai be 21°C on October 4? | NO | 2.21 | $2.00 | 0.902 | 0.934 | $2.07 | $0.07 |
| 30 | Will the highest temperature in Shanghai be 22°C on October 4? | NO | 2.78 | $1.49 | 0.535 | 0.540 | $1.50 | $0.01 |
| 31 | Will the highest temperature in Madrid be 23°C on October 4? | NO | 2.69 | $2.03 | 0.755 | 0.720 | $1.94 | $-0.09 |

## Probability calibrators (latest fit)

Fitted 2026-10-02 23:11 on 1 resolved markets (1 to fit, the newest 0 to judge).

| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |
|---|---|---|---|---|
| isotonic | n/a → n/a | n/a → n/a | no: only 1 resolved markets (need 200) |  |
| platt | n/a → n/a | n/a → n/a | no: only 1 resolved markets (need 200) |  |

## Model comparison

Each model's prediction from the same cycle as the production model's last prediction made 1+ day ahead, on 419 resolved markets. Each row is scored on the markets that model predicted, and the production columns on exactly those markets. Lower is better.

| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |
|---|---|---:|---:|---:|---:|---:|
| climatology-v1 | shadow | 419 | 0.0984 | 0.3432 | 0.0664 | 0.2112 |
| normal-multimodel-v1 | production | 419 | 0.0664 | 0.2112 | 0.0664 | 0.2112 |
| raw-forecast-v1 | shadow | 419 | 0.0721 | 0.2367 | 0.0664 | 0.2112 |
| market price (mid) | benchmark | 419 | 0.0993 | 0.3084 | 0.0664 | 0.2112 |

## Results by market day

| Market day | Bets | Won | Lost | Open | Staked | Settled P/L |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-04 | 10 | 0 | 0 | 10 | $18.70 | $0.00 |
| 2026-10-03 | 7 | 0 | 1 | 6 | $13.25 | $-1.70 |
| 2026-10-02 | 14 | 11 | 3 | 0 | $27.23 | $2.99 |

## Every bet, by market day

### 2026-10-04

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 22 | 2026-10-03 12:41 | Highest temperature in London on October 4? 22°C | NO | 0.555 | 86.3% | 54.5% | $2.03 | OPEN |  |
| 23 | 2026-10-03 12:41 | Highest temperature in London on October 4? 23°C | NO | 0.895 | 96.2% | 88.0% | $2.02 | OPEN |  |
| 24 | 2026-10-03 12:41 | Highest temperature in Seoul (Incheon) on October 4? 22°C | NO | 0.775 | 89.8% | 75.5% | $2.02 | OPEN |  |
| 25 | 2026-10-03 12:41 | Highest temperature in Ankara on October 4? 20°C | NO | 0.695 | 91.9% | 68.5% | $1.11 | OPEN |  |
| 26 | 2026-10-03 17:33 | Highest temperature in Lucknow on October 4? 33°C | NO | 0.535 | 80.1% | 51.5% | $2.00 | OPEN |  |
| 27 | 2026-10-03 17:33 | Highest temperature in Munich on October 4? 21°C | NO | 0.735 | 81.2% | 71.5% | $2.00 | OPEN |  |
| 28 | 2026-10-03 17:33 | Highest temperature in Tokyo on October 4? 22°C | NO | 0.745 | 83.2% | 73.0% | $2.00 | OPEN |  |
| 29 | 2026-10-03 17:33 | Highest temperature in Shanghai on October 4? 21°C | NO | 0.902 | 98.2% | 89.3% | $2.00 | OPEN |  |
| 30 | 2026-10-03 17:33 | Highest temperature in Shanghai on October 4? 22°C | NO | 0.535 | 89.9% | 52.0% | $1.49 | OPEN |  |
| 31 | 2026-10-03 22:22 | Highest temperature in Madrid on October 4? 23°C | NO | 0.755 | 81.6% | 73.5% | $2.03 | OPEN |  |

### 2026-10-03

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 14 | 2026-10-01 21:55 | Lowest temperature in London on October 3? 12°C | NO | 0.879 | 96.2% | 76.5% | $1.97 | OPEN |  |
| 15 | 2026-10-01 21:55 | Highest temperature in Seoul (Incheon) on October 3? 21°C | NO | 0.745 | 92.2% | 73.5% | $1.70 | LOST | $-1.70 |
| 17 | 2026-10-02 23:11 | Highest temperature in London on October 3? 22°C | NO | 0.825 | 87.9% | 81.5% | $2.09 | OPEN |  |
| 18 | 2026-10-03 07:00 | Highest temperature in Atlanta on October 3? 80-81°F | NO | 0.877 | 95.6% | 86.2% | $2.03 | OPEN |  |
| 19 | 2026-10-03 07:00 | Highest temperature in Chicago on October 3? 68-69°F | NO | 0.415 | 84.9% | 39.5% | $1.40 | OPEN |  |
| 20 | 2026-10-03 12:41 | Highest temperature in Seattle on October 3? 70-71°F | NO | 0.725 | 89.0% | 71.5% | $2.03 | OPEN |  |
| 21 | 2026-10-03 12:41 | Highest temperature in Los Angeles on October 3? 98-99°F | NO | 0.675 | 80.1% | 66.0% | $2.03 | OPEN |  |

### 2026-10-02

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 1 | 2026-10-01 21:55 | Lowest temperature in London on October 2? 12°C | NO | 0.522 | 91.1% | 45.0% | $2.00 | WON | $1.83 |
| 2 | 2026-10-01 21:55 | Highest temperature in Ankara on October 2? 16°C | NO | 0.685 | 80.5% | 67.5% | $1.99 | WON | $0.92 |
| 3 | 2026-10-01 21:55 | Highest temperature in Warsaw on October 2? 22°C | NO | 0.665 | 84.7% | 65.5% | $1.99 | WON | $1.00 |
| 4 | 2026-10-01 21:55 | Highest temperature in Chengdu on October 2? 23°C | NO | 0.755 | 87.5% | 74.0% | $1.99 | WON | $0.65 |
| 5 | 2026-10-01 21:55 | Highest temperature in NYC on October 2? 88-89°F | NO | 0.870 | 92.9% | 85.5% | $1.99 | WON | $0.30 |
| 6 | 2026-10-01 21:55 | Highest temperature in Chicago on October 2? 66-67°F | NO | 0.635 | 88.2% | 62.0% | $1.99 | LOST | $-1.99 |
| 7 | 2026-10-01 21:55 | Highest temperature in Austin on October 2? 82-83°F | NO | 0.755 | 82.5% | 73.5% | $1.98 | WON | $0.64 |
| 8 | 2026-10-01 21:55 | Highest temperature in Houston on October 2? 92-93°F | NO | 0.802 | 88.0% | 78.6% | $1.98 | WON | $0.49 |
| 9 | 2026-10-01 21:55 | Highest temperature in Seattle on October 2? 72-73°F | NO | 0.805 | 89.2% | 78.0% | $1.98 | WON | $0.48 |
| 10 | 2026-10-01 21:55 | Highest temperature in San Francisco on October 2? 74-75°F | NO | 0.775 | 84.9% | 76.5% | $1.98 | LOST | $-1.98 |
| 11 | 2026-10-01 21:55 | Highest temperature in San Francisco on October 2? 76-77°F | NO | 0.655 | 84.7% | 64.5% | $1.98 | WON | $1.04 |
| 12 | 2026-10-01 21:55 | Highest temperature in Mexico City on October 2? 22°C | NO | 0.905 | 98.5% | 89.0% | $1.98 | WON | $0.21 |
| 13 | 2026-10-01 21:55 | Highest temperature in Mexico City on October 2? 23°C | NO | 0.705 | 87.0% | 69.0% | $1.98 | WON | $0.83 |
| 16 | 2026-10-02 10:42 | Highest temperature in Houston on October 2? 90-91°F | NO | 0.685 | 86.3% | 67.0% | $1.43 | LOST | $-1.43 |

## Bot status

Last cycle: 2026-10-03T22:23:31.062806+00:00 · markets monitored: 1595

```
{
 "markets": {
  "seen": 2706,
  "tradeable": 1595
 },
 "forecasts": {
  "stations": 27,
  "snapshots": 136
 },
 "calibration": {
  "skipped": true
 },
 "signals": {
  "predictions": 1496,
  "shadow_predictions": 2992,
  "bets": 1
 },
 "settlement": {
  "checked": 38,
  "bets_settled": 0,
  "price_histories": 110
 },
 "observations": {
  "skipped": true
 },
 "seconds": 63.4
}
```

Recent warnings and errors:

- 2026-10-03 22:22 WARNING validation: WSSS 2026-10-04 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: WSSS 2026-10-05 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: ZUUU 2026-10-04 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: ZUUU 2026-10-05 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: ZUUU 2026-10-04 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: ZUUU 2026-10-05 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: EPWA 2026-10-04 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: EPWA 2026-10-05 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: EPWA 2026-10-04 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-03 22:22 WARNING validation: EPWA 2026-10-05 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}

