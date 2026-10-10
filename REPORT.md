# Paper-trading performance report

Mode: **PAPER TRADING** · real money used: **$0.00**

Experiment: **exp2-100usd** · started 2026-10-01 21:48 UTC · starting bankroll $100.00 · code 266ddda9e1b6

## Verdict

- Only 84 settled bets: too few to conclude anything about profitability (aim for several hundred).
- ROI 95% interval -20.8% to 8.7% includes zero: no evidence either way.
- Bets won 66.7% against 87.3% predicted (under-performing by 20.6 points).
- Across 4464 resolved markets the model's Brier score 0.0681 was better than the market's 0.0902.

## Results

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Equity (open bets at the bid) | $86.89 |
| Cash available | $69.58 |
| Open positions: count / cost / value at the bid | 12 / $20.55 / $17.31 |
| Realized / unrealized P/L | $-9.87 / $-3.24 |
| Total P/L | $-13.11 |
| Return on bankroll | -13.1% |
| ROI on settled stakes | -6.2% |
| ROI 95% bootstrap interval | -20.8% to 8.7% |
| Bets placed / settled / open | 96 / 84 / 12 |
| Win rate (predicted) | 66.7% (87.3%) |
| Average confidence | 87.3% |
| Average edge | 0.1679 |
| Brier on bets: model / market | 0.2586 / 0.2032 |
| Max drawdown | $17.42 (16.7%) |

## Calibration of all predictions on resolved markets

Markets: 4464 · Brier model 0.0681 · market 0.0902 · log loss 0.2239 · expected calibration error 0.0119

| Predicted bin | n | Mean predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 2943 | 2.3% | 1.6% |
| 0.1-0.2 | 657 | 14.7% | 15.8% |
| 0.2-0.3 | 495 | 24.5% | 22.2% |
| 0.3-0.4 | 290 | 34.4% | 36.9% |
| 0.4-0.5 | 71 | 43.9% | 49.3% |
| 0.5-0.6 | 7 | 53.9% | 42.9% |
| 0.7-0.8 | 1 | 73.1% | 100.0% |

## Open positions

Valued at the best bid of the side held in the latest market snapshot (the side's last price when there is no bid, cost when there is no snapshot).

| Bet | Market | Side | Shares | Cost | Entry | Mark | Value | Unrealized |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 85 | Will the highest temperature in London be 16°C on October 10? | NO | 3.93 | $1.83 | 0.465 | 0.003 | $0.01 | $-1.82 |
| 86 | Will the highest temperature in Seoul (Incheon) be 23°C on October 10? | NO | 3.17 | $1.82 | 0.575 | 0.999 | $3.17 | $1.34 |
| 87 | Will the highest temperature in Milan be 20°C on October 10? | NO | 2.48 | $1.80 | 0.725 | 0.999 | $2.48 | $0.68 |
| 88 | Will the highest temperature in Madrid be 25°C on October 10? | NO | 3.30 | $1.80 | 0.545 | 0.009 | $0.03 | $-1.77 |
| 89 | Will the highest temperature in Chicago be between 82-83°F on October 10? | NO | 2.92 | $1.80 | 0.615 | 0.360 | $1.05 | $-0.75 |
| 90 | Will the highest temperature in Atlanta be between 66-67°F on October 10? | NO | 2.35 | $1.80 | 0.765 | 0.710 | $1.67 | $-0.13 |
| 91 | Will the highest temperature in Atlanta be between 68-69°F on October 10? | NO | 2.43 | $1.66 | 0.685 | 0.520 | $1.26 | $-0.40 |
| 92 | Will the highest temperature in Atlanta be between 64-65°F on October 10? | NO | 1.14 | $1.07 | 0.937 | 0.920 | $1.05 | $-0.02 |
| 93 | Will the lowest temperature in London be 8°C on October 11? | NO | 2.28 | $1.75 | 0.765 | 0.710 | $1.62 | $-0.13 |
| 94 | Will the highest temperature in Seoul (Incheon) be 25°C on October 11? | NO | 3.32 | $1.74 | 0.525 | 0.500 | $1.66 | $-0.08 |
| 95 | Will the highest temperature in Seoul (Incheon) be 26°C on October 11? | NO | 2.66 | $1.74 | 0.655 | 0.620 | $1.65 | $-0.09 |
| 96 | Will the highest temperature in Munich be 13°C on October 11? | NO | 2.60 | $1.74 | 0.670 | 0.640 | $1.66 | $-0.08 |

## Probability calibrators (latest fit)

Fitted 2026-10-09 23:26 on 4006 resolved markets (2804 to fit, the newest 1202 to judge).

| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |
|---|---|---|---|---|
| isotonic | 0.0721 → 0.0718 | 0.2364 → 0.2372 | no: does not beat raw probabilities on both Brier and log loss |  |
| platt | 0.0721 → 0.0718 | 0.2364 → 0.2362 | no: gain not reliable: wins in 61% of bootstrap resamples (need 95%) |  |

## Model comparison

Each model's prediction from the same cycle as the production model's last prediction made 1+ day ahead, on 4464 resolved markets. Each row is scored on the markets that model predicted, and the production columns on exactly those markets. Lower is better.

| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |
|---|---|---:|---:|---:|---:|---:|
| climatology-v1 | shadow | 4464 | 0.0903 | 0.3205 | 0.0681 | 0.2239 |
| normal-multimodel-v1 | production | 4464 | 0.0681 | 0.2239 | 0.0681 | 0.2239 |
| raw-forecast-v1 | shadow | 4464 | 0.0731 | 0.2467 | 0.0681 | 0.2239 |
| market price (mid) | benchmark | 4464 | 0.0902 | 0.2911 | 0.0681 | 0.2239 |

## Results by market day

| Market day | Bets | Won | Lost | Open | Staked | Settled P/L |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-11 | 4 | 0 | 0 | 4 | $6.97 | $0.00 |
| 2026-10-10 | 8 | 0 | 0 | 8 | $13.58 | $0.00 |
| 2026-10-09 | 10 | 6 | 4 | 0 | $18.12 | $-2.96 |
| 2026-10-08 | 12 | 7 | 5 | 0 | $23.20 | $-5.19 |
| 2026-10-07 | 11 | 8 | 3 | 0 | $21.38 | $1.44 |
| 2026-10-06 | 4 | 1 | 3 | 0 | $7.50 | $-4.97 |
| 2026-10-05 | 14 | 10 | 4 | 0 | $25.62 | $2.42 |
| 2026-10-04 | 12 | 8 | 4 | 0 | $22.61 | $-3.24 |
| 2026-10-03 | 7 | 5 | 2 | 0 | $13.25 | $-0.36 |
| 2026-10-02 | 14 | 11 | 3 | 0 | $27.23 | $2.99 |

## Every bet, by market day

### 2026-10-11

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 93 | 2026-10-10 15:56 | Lowest temperature in London on October 11? 8°C | NO | 0.765 | 90.2% | 73.5% | $1.75 | OPEN |  |
| 94 | 2026-10-10 15:56 | Highest temperature in Seoul (Incheon) on October 11? 25°C | NO | 0.525 | 85.0% | 51.0% | $1.74 | OPEN |  |
| 95 | 2026-10-10 15:56 | Highest temperature in Seoul (Incheon) on October 11? 26°C | NO | 0.655 | 83.7% | 63.5% | $1.74 | OPEN |  |
| 96 | 2026-10-10 15:56 | Highest temperature in Munich on October 11? 13°C | NO | 0.670 | 92.6% | 65.0% | $1.74 | OPEN |  |

### 2026-10-10

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 85 | 2026-10-09 17:09 | Highest temperature in London on October 10? 16°C | NO | 0.465 | 83.9% | 45.5% | $1.83 | OPEN |  |
| 86 | 2026-10-09 17:09 | Highest temperature in Seoul (Incheon) on October 10? 23°C | NO | 0.575 | 82.6% | 56.5% | $1.82 | OPEN |  |
| 87 | 2026-10-09 23:26 | Highest temperature in Milan on October 10? 20°C | NO | 0.725 | 80.5% | 71.5% | $1.80 | OPEN |  |
| 88 | 2026-10-09 23:26 | Highest temperature in Madrid on October 10? 25°C | NO | 0.545 | 82.9% | 52.5% | $1.80 | OPEN |  |
| 89 | 2026-10-09 23:26 | Highest temperature in Chicago on October 10? 82-83°F | NO | 0.615 | 83.4% | 60.0% | $1.80 | OPEN |  |
| 90 | 2026-10-09 23:26 | Highest temperature in Atlanta on October 10? 66-67°F | NO | 0.765 | 95.1% | 75.0% | $1.80 | OPEN |  |
| 91 | 2026-10-09 23:26 | Highest temperature in Atlanta on October 10? 68-69°F | NO | 0.685 | 89.1% | 66.5% | $1.66 | OPEN |  |
| 92 | 2026-10-10 07:40 | Highest temperature in Atlanta on October 10? 64-65°F | NO | 0.937 | 99.0% | 92.8% | $1.07 | OPEN |  |

### 2026-10-09

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 75 | 2026-10-08 17:33 | Lowest temperature in Seoul (Incheon) on October 9? 14°C | NO | 0.565 | 88.5% | 54.0% | $1.85 | LOST | $-1.85 |
| 76 | 2026-10-08 17:33 | Highest temperature in Seoul (Incheon) on October 9? 22°C | NO | 0.695 | 85.3% | 68.0% | $1.85 | WON | $0.81 |
| 77 | 2026-10-08 23:53 | Highest temperature in London on October 9? 20°C | NO | 0.705 | 82.3% | 69.0% | $1.82 | LOST | $-1.82 |
| 78 | 2026-10-08 23:53 | Highest temperature in Munich on October 9? 15°C | NO | 0.585 | 89.1% | 56.5% | $1.82 | WON | $1.29 |
| 79 | 2026-10-09 07:56 | Highest temperature in Atlanta on October 9? 72-73°F | NO | 0.691 | 86.0% | 67.0% | $1.85 | LOST | $-1.85 |
| 80 | 2026-10-09 07:56 | Highest temperature in Chicago on October 9? 72-73°F | NO | 0.725 | 85.1% | 70.0% | $1.85 | WON | $0.70 |
| 81 | 2026-10-09 07:56 | Highest temperature in Chicago on October 9? 74-75°F | NO | 0.746 | 91.8% | 74.0% | $1.84 | WON | $0.63 |
| 82 | 2026-10-09 07:56 | Highest temperature in Los Angeles on October 9? 76-77°F | NO | 0.551 | 82.8% | 53.5% | $1.84 | LOST | $-1.84 |
| 83 | 2026-10-09 07:56 | Highest temperature in Los Angeles on October 9? 78-79°F | NO | 0.770 | 82.9% | 74.5% | $1.84 | WON | $0.55 |
| 84 | 2026-10-09 07:56 | Highest temperature in San Francisco on October 9? 64-65°F | NO | 0.785 | 92.0% | 76.8% | $1.56 | WON | $0.43 |

### 2026-10-08

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 63 | 2026-10-07 17:32 | Highest temperature in Munich on October 8? 19°C | NO | 0.715 | 84.1% | 70.0% | $1.97 | WON | $0.78 |
| 64 | 2026-10-07 17:32 | Highest temperature in Madrid on October 8? 20°C | NO | 0.726 | 80.6% | 72.4% | $1.97 | LOST | $-1.97 |
| 65 | 2026-10-07 17:32 | Highest temperature in Chengdu on October 8? 24°C | NO | 0.775 | 89.8% | 75.5% | $1.97 | WON | $0.57 |
| 66 | 2026-10-07 17:32 | Highest temperature in Chengdu on October 8? 25°C | NO | 0.695 | 81.8% | 67.5% | $1.97 | LOST | $-1.97 |
| 67 | 2026-10-07 23:43 | Highest temperature in Lucknow on October 8? 28°C | NO | 0.814 | 89.4% | 78.9% | $1.96 | WON | $0.45 |
| 68 | 2026-10-07 23:43 | Highest temperature in Lucknow on October 8? 29°C | NO | 0.755 | 81.1% | 70.0% | $1.96 | LOST | $-1.96 |
| 69 | 2026-10-07 23:43 | Highest temperature in Munich on October 8? 17°C | NO | 0.875 | 94.8% | 86.5% | $1.95 | WON | $0.28 |
| 70 | 2026-10-08 07:56 | Highest temperature in Dallas on October 8? 90-91°F | NO | 0.665 | 86.3% | 64.0% | $1.92 | LOST | $-1.92 |
| 71 | 2026-10-08 07:56 | Highest temperature in Atlanta on October 8? 82-83°F | NO | 0.705 | 84.3% | 68.5% | $1.92 | WON | $0.80 |
| 72 | 2026-10-08 07:56 | Highest temperature in Austin on October 8? 92-93°F | NO | 0.641 | 80.3% | 62.5% | $1.92 | WON | $1.08 |
| 73 | 2026-10-08 07:56 | Highest temperature in Los Angeles on October 8? 80-81°F | NO | 0.685 | 86.1% | 66.5% | $1.92 | LOST | $-1.92 |
| 74 | 2026-10-08 07:56 | Highest temperature in Los Angeles on October 8? 82-83°F | NO | 0.755 | 84.5% | 73.5% | $1.79 | WON | $0.58 |

### 2026-10-07

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 52 | 2026-10-06 16:54 | Highest temperature in Seoul (Incheon) on October 7? 21°C | NO | 0.715 | 90.1% | 70.0% | $1.99 | WON | $0.79 |
| 53 | 2026-10-06 16:54 | Highest temperature in Wellington on October 7? 17°C | NO | 0.795 | 90.8% | 76.5% | $1.99 | WON | $0.51 |
| 54 | 2026-10-06 16:54 | Highest temperature in Milan on October 7? 17°C | NO | 0.883 | 97.8% | 87.2% | $1.99 | WON | $0.26 |
| 55 | 2026-10-06 16:54 | Highest temperature in Milan on October 7? 18°C | NO | 0.605 | 88.5% | 59.0% | $1.99 | LOST | $-1.99 |
| 56 | 2026-10-06 16:54 | Highest temperature in Madrid on October 7? 21°C | NO | 0.750 | 86.5% | 73.0% | $1.99 | WON | $0.66 |
| 57 | 2026-10-06 16:54 | Highest temperature in Warsaw on October 7? 22°C | NO | 0.715 | 83.0% | 70.0% | $1.98 | WON | $0.79 |
| 58 | 2026-10-06 16:54 | Highest temperature in Chengdu on October 7? 26°C | NO | 0.755 | 83.0% | 73.5% | $1.98 | WON | $0.64 |
| 59 | 2026-10-06 16:54 | Highest temperature in Dallas on October 7? 86-87°F | NO | 0.445 | 81.8% | 43.0% | $1.98 | WON | $2.47 |
| 60 | 2026-10-06 16:54 | Highest temperature in Austin on October 7? 90-91°F | NO | 0.635 | 80.1% | 61.5% | $1.98 | LOST | $-1.98 |
| 61 | 2026-10-06 23:12 | Highest temperature in Ankara on October 7? 21°C | NO | 0.695 | 83.2% | 68.0% | $1.93 | WON | $0.85 |
| 62 | 2026-10-06 23:12 | Highest temperature in Dallas on October 7? 88-89°F | NO | 0.780 | 89.5% | 74.4% | $1.58 | LOST | $-1.58 |

### 2026-10-06

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 48 | 2026-10-05 16:21 | Lowest temperature in London on October 6? 13°C | NO | 0.755 | 94.0% | 69.5% | $1.99 | LOST | $-1.99 |
| 49 | 2026-10-05 16:21 | Highest temperature in London on October 6? 22°C | NO | 0.785 | 87.2% | 77.0% | $1.99 | WON | $0.54 |
| 50 | 2026-10-06 08:02 | Highest temperature in Dallas on October 6? 86-87°F | NO | 0.685 | 85.6% | 65.5% | $1.99 | LOST | $-1.99 |
| 51 | 2026-10-06 08:02 | Highest temperature in Chicago on October 6? 74-75°F | NO | 0.590 | 86.6% | 57.0% | $1.53 | LOST | $-1.53 |

### 2026-10-05

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 34 | 2026-10-04 17:48 | Highest temperature in London on October 5? 23°C | NO | 0.755 | 85.4% | 73.0% | $2.00 | WON | $0.65 |
| 35 | 2026-10-04 17:48 | Highest temperature in Madrid on October 5? 25°C | NO | 0.775 | 82.7% | 76.0% | $2.00 | WON | $0.58 |
| 36 | 2026-10-04 17:48 | Highest temperature in Chengdu on October 5? 20°C | NO | 0.415 | 92.4% | 39.5% | $2.00 | WON | $2.82 |
| 37 | 2026-10-04 17:48 | Highest temperature in Chengdu on October 5? 21°C | NO | 0.735 | 84.6% | 71.5% | $1.31 | LOST | $-1.31 |
| 38 | 2026-10-04 22:28 | Highest temperature in Madrid on October 5? 26°C | NO | 0.855 | 92.9% | 84.0% | $1.96 | LOST | $-1.96 |
| 39 | 2026-10-04 22:28 | Highest temperature in Chicago on October 5? 68-69°F | NO | 0.565 | 89.4% | 54.0% | $1.96 | LOST | $-1.96 |
| 40 | 2026-10-04 22:28 | Highest temperature in Chicago on October 5? 70-71°F | NO | 0.914 | 98.3% | 90.0% | $1.96 | WON | $0.18 |
| 41 | 2026-10-04 22:28 | Highest temperature in Dallas on October 5? 84-85°F | NO | 0.735 | 91.7% | 71.5% | $1.05 | WON | $0.38 |
| 42 | 2026-10-05 01:09 | Highest temperature in Atlanta on October 5? 74-75°F | NO | 0.791 | 91.5% | 77.5% | $1.98 | LOST | $-1.98 |
| 43 | 2026-10-05 01:09 | Highest temperature in Austin on October 5? 86-87°F | NO | 0.495 | 81.2% | 48.0% | $1.42 | WON | $1.45 |
| 44 | 2026-10-05 07:37 | Highest temperature in San Francisco on October 5? 78-79°F | NO | 0.795 | 87.9% | 78.5% | $2.00 | WON | $0.52 |
| 45 | 2026-10-05 07:37 | Highest temperature in San Francisco on October 5? 80-81°F | NO | 0.705 | 87.1% | 67.5% | $2.00 | WON | $0.84 |
| 46 | 2026-10-05 07:37 | Highest temperature in Sao Paulo on October 5? 24°C | NO | 0.675 | 80.6% | 67.5% | $2.00 | WON | $0.96 |
| 47 | 2026-10-05 07:37 | Highest temperature in Mexico City on October 5? 22°C | NO | 0.615 | 80.3% | 60.0% | $2.00 | WON | $1.25 |

### 2026-10-04

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 22 | 2026-10-03 12:41 | Highest temperature in London on October 4? 22°C | NO | 0.555 | 86.3% | 54.5% | $2.03 | LOST | $-2.03 |
| 23 | 2026-10-03 12:41 | Highest temperature in London on October 4? 23°C | NO | 0.895 | 96.2% | 88.0% | $2.02 | WON | $0.24 |
| 24 | 2026-10-03 12:41 | Highest temperature in Seoul (Incheon) on October 4? 22°C | NO | 0.775 | 89.8% | 75.5% | $2.02 | WON | $0.59 |
| 25 | 2026-10-03 12:41 | Highest temperature in Ankara on October 4? 20°C | NO | 0.695 | 91.9% | 68.5% | $1.11 | WON | $0.49 |
| 26 | 2026-10-03 17:33 | Highest temperature in Lucknow on October 4? 33°C | NO | 0.535 | 80.1% | 51.5% | $2.00 | LOST | $-2.00 |
| 27 | 2026-10-03 17:33 | Highest temperature in Munich on October 4? 21°C | NO | 0.735 | 81.2% | 71.5% | $2.00 | WON | $0.72 |
| 28 | 2026-10-03 17:33 | Highest temperature in Tokyo on October 4? 22°C | NO | 0.745 | 83.2% | 73.0% | $2.00 | LOST | $-2.00 |
| 29 | 2026-10-03 17:33 | Highest temperature in Shanghai on October 4? 21°C | NO | 0.902 | 98.2% | 89.3% | $2.00 | WON | $0.22 |
| 30 | 2026-10-03 17:33 | Highest temperature in Shanghai on October 4? 22°C | NO | 0.535 | 89.9% | 52.0% | $1.49 | WON | $1.29 |
| 31 | 2026-10-03 22:22 | Highest temperature in Madrid on October 4? 23°C | NO | 0.755 | 81.6% | 73.5% | $2.03 | WON | $0.66 |
| 32 | 2026-10-04 10:43 | Highest temperature in Chicago on October 4? 72-73°F | NO | 0.475 | 83.6% | 46.5% | $2.01 | LOST | $-2.01 |
| 33 | 2026-10-04 10:43 | Highest temperature in Chicago on October 4? 74-75°F | NO | 0.765 | 96.6% | 75.0% | $1.90 | WON | $0.58 |

### 2026-10-03

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 14 | 2026-10-01 21:55 | Lowest temperature in London on October 3? 12°C | NO | 0.879 | 96.2% | 76.5% | $1.97 | WON | $0.27 |
| 15 | 2026-10-01 21:55 | Highest temperature in Seoul (Incheon) on October 3? 21°C | NO | 0.745 | 92.2% | 73.5% | $1.70 | LOST | $-1.70 |
| 17 | 2026-10-02 23:11 | Highest temperature in London on October 3? 22°C | NO | 0.825 | 87.9% | 81.5% | $2.09 | WON | $0.44 |
| 18 | 2026-10-03 07:00 | Highest temperature in Atlanta on October 3? 80-81°F | NO | 0.877 | 95.6% | 86.2% | $2.03 | WON | $0.28 |
| 19 | 2026-10-03 07:00 | Highest temperature in Chicago on October 3? 68-69°F | NO | 0.415 | 84.9% | 39.5% | $1.40 | LOST | $-1.40 |
| 20 | 2026-10-03 12:41 | Highest temperature in Seattle on October 3? 70-71°F | NO | 0.725 | 89.0% | 71.5% | $2.03 | WON | $0.77 |
| 21 | 2026-10-03 12:41 | Highest temperature in Los Angeles on October 3? 98-99°F | NO | 0.675 | 80.1% | 66.0% | $2.03 | WON | $0.98 |

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

Last cycle: 2026-10-10T15:59:31.269369+00:00 · markets monitored: 1727

```
{
 "markets": {
  "seen": 3102,
  "tradeable": 1727
 },
 "forecasts": {
  "stations": 27,
  "snapshots": 153
 },
 "calibration": {
  "skipped": true
 },
 "signals": {
  "predictions": 1683,
  "shadow_predictions": 3366,
  "bets": 4
 },
 "settlement": {
  "checked": 515,
  "bets_settled": 3,
  "price_histories": 300
 },
 "observations": {
  "stations": 27,
  "new_rows": 6
 },
 "seconds": 185.4
}
```

Recent warnings and errors:

- 2026-10-10 15:56 WARNING validation: RJTT 2026-10-11 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: RJTT 2026-10-11 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: RJTT 2026-10-12 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: RJTT 2026-10-12 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: NZWN 2026-10-11 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: NZWN 2026-10-11 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: NZWN 2026-10-12 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: NZWN 2026-10-12 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: RKSI 2026-10-11 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-10 15:56 WARNING validation: RKSI 2026-10-11 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}

