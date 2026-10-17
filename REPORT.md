# Paper-trading performance report

Mode: **PAPER TRADING** · real money used: **$0.00**

Experiment: **exp2-100usd** · started 2026-10-01 21:48 UTC · starting bankroll $100.00 · code 266ddda9e1b6 (now ba8aea21905d) · day 16 of 30, ends 2026-10-31 21:48 UTC

## Verdict

- ROI 95% interval -20.7% to 5.6% includes zero: no evidence either way.
- Bets won 64.9% against 87.3% predicted (under-performing by 22.4 points).
- Across 5078 resolved liquid markets the model's Brier score 0.0635 was worse than the market's 0.0557.
- New bets are paused: the model has not yet beaten the market price on held-out markets (latest fit 2026-10-17 16:37 UTC: the model adds nothing to the market price on the holdout (Brier or log loss not lower)). See Market anchor below.

## Results

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Equity (open bets at the bid) | $84.60 |
| Cash available | $84.60 |
| Open positions: count / cost / value at the bid | 0 / $0.00 / $0.00 |
| Realized / unrealized P/L | $-15.40 / $0.00 |
| Total P/L | $-15.40 |
| Return on bankroll | -15.4% |
| ROI on settled stakes | -7.3% |
| ROI 95% bootstrap interval | -20.7% to 5.6% |
| Bets placed / settled / open | 114 / 114 / 0 |
| Win rate (predicted) | 64.9% (87.3%) |
| Average confidence | 87.3% |
| Average edge | 0.1773 |
| Brier on bets: model / market | 0.2717 / 0.2029 |
| Max drawdown | $21.17 (20.3%) |

## Calibration of all predictions on resolved markets

Markets: 8580 · Brier model 0.0680 · log loss 0.2226 · expected calibration error 0.0113 · on the 5078 liquid markets, Brier model 0.0635 vs market 0.0557

| Predicted bin | n | Mean predicted | Observed |
|---|---:|---:|---:|
| 0.0-0.1 | 5678 | 2.3% | 1.4% |
| 0.1-0.2 | 1246 | 14.8% | 16.6% |
| 0.2-0.3 | 925 | 24.5% | 23.0% |
| 0.3-0.4 | 570 | 34.2% | 35.4% |
| 0.4-0.5 | 145 | 43.8% | 45.5% |
| 0.5-0.6 | 13 | 54.5% | 53.8% |
| 0.6-0.7 | 1 | 65.6% | 100.0% |
| 0.7-0.8 | 1 | 73.1% | 100.0% |
| 0.8-0.9 | 1 | 87.0% | 100.0% |

## Probability calibrators (latest fit)

Fitted 2026-10-16 17:39 on 1532 resolved markets (1072 to fit, the newest 460 to judge).

| Method | Holdout Brier raw → calibrated | Holdout log loss raw → calibrated | Approved | In use |
|---|---|---|---|---|
| isotonic | 0.0714 → 0.0711 | 0.2363 → 0.2369 | no: does not beat raw probabilities on both Brier and log loss |  |
| platt | 0.0714 → 0.0711 | 0.2363 → 0.2356 | no: gain not reliable: wins in 61% of bootstrap resamples (need 95%) |  |

## Market anchor (latest fit)

The bot bets only on the model combined with the market price, and only while that combination beats the market price alone on resolved markets it was not fitted on.

Fitted 2026-10-17 16:37 UTC on 724 resolved markets with a tight book (507 to fit, the newest 217 to judge): **not approved**, the model adds nothing to the market price on the holdout (Brier or log loss not lower).

Weights: model -0.06, market price 1.31, constant 0.18 (a model weight near zero means the price already holds what the model knows).

| On the holdout | Brier | Log loss |
|---|---:|---:|
| Market price | 0.0849 | 0.2626 |
| Model alone | 0.1045 | 0.3398 |
| Model + market | 0.0858 | 0.2670 |

## Same-day model (forward test)

On each market's own day the same-day model prices every bucket from the station's reports so far and the newest hourly forecast. It is scored here against the market's mid price at the same moment, on resolved markets whose book was tight then (lower is better). It can bet only once its own market anchor beats the market price on held-out markets.

| Hours left | Predictions | Markets | Log loss: model / market | Brier: model / market |
|---|---:|---:|---|---|
| 0-3 | 5 | 5 | 0.1439 / 0.0074 | 0.0516 / 0.0001 |
| 3-6 | 21 | 20 | 0.1783 / 0.2558 | 0.0561 / 0.0820 |
| 6-12 | 234 | 211 | 0.1862 / 0.0627 | 0.0370 / 0.0182 |
| 12-24 | 1274 | 752 | 0.2905 / 0.2273 | 0.0898 / 0.0709 |
| all | 1534 | 786 | 0.2726 / 0.2019 | 0.0811 / 0.0628 |

Latest anchor fit 2026-10-17 16:37 UTC on 623 markets (436 to fit, the newest 187 to judge): **not approved**, the model adds nothing to the market price on the holdout (Brier or log loss not lower) (892 predictions).

## Model updates

Station bias and error spread in use: **bias-sigma-20261013T004035-90d** (retrain, fitted on 2026-07-05 to 2026-10-02, in production since 2026-10-13 00:40).
A retrained set replaces it only if it scores better on markets none of the candidates was fitted on; the replaced set is kept and put back if the new one then does reliably worse.

| Set | Status | Trained on | Out-of-sample markets | Brier production → set | Log loss production → set | Decision |
|---|---|---|---:|---|---|---|
| bias-sigma-20261013T004035-90d | production | 2026-07-05 to 2026-10-02 | 3692 | 0.0679 → 0.0678 | 0.2227 → 0.2224 | better on 3692 out-of-sample markets: Brier 0.0679 → 0.0678, log loss 0.2227 → 0.2224, in 97% of station resamples |
| bias-sigma-20261013T004035-60d | rejected | 2026-08-04 to 2026-10-02 | 3692 | 0.0679 → 0.0675 | 0.2227 → 0.2214 | gain not reliable: wins in 86% of station resamples (need 95%) |
| bias-sigma-20261013T004035-30d | rejected | 2026-09-03 to 2026-10-02 | 3692 | 0.0679 → 0.0670 | 0.2227 → 0.2203 | gain not reliable: wins in 86% of station resamples (need 95%) |
| bias-sigma-20261001-initial | previous | 2026-07-03 to 2026-09-30 | – | – | – | fitted by `backtest` before versioned parameter sets existed |

## Model comparison

Each model's prediction from the same cycle as the production model's last prediction made 1+ day ahead, on 8580 resolved markets. Each row is scored on the markets that model predicted, and the production columns on exactly those markets; the market price only on markets that passed the liquidity check, since a thin market's mid is a placeholder. Lower is better.

| Model | Role | Markets | Brier | Log loss | Production Brier | Production log loss |
|---|---|---:|---:|---:|---:|---:|
| climatology-v1 | shadow | 8580 | 0.0903 | 0.3229 | 0.0680 | 0.2226 |
| normal-multimodel-v1 | production | 8580 | 0.0680 | 0.2226 | 0.0680 | 0.2226 |
| raw-forecast-v1 | shadow | 8580 | 0.0726 | 0.2440 | 0.0680 | 0.2226 |
| market price (mid) | benchmark | 5078 | 0.0557 | 0.1806 | 0.0635 | 0.2089 |

## Recurring weaknesses

Where the model was wrong in a consistent way, on 8580 resolved markets and 114 settled bets: groups with at least 30 markets (15 bets) and a gap of at least 3 standard errors. The dashboard's Learning tab has every breakdown.

| Where | Breakdown | Group | n | Weakness | Evidence |
|---|---|---|---:|---|---|
| predictions | Highest or lowest temperature | high | 4367 | worse than the market | Brier 0.0683 vs the market's 0.0578 on 4367 markets |
| bets | All settled bets | all | 114 | overconfident | won 65% of 114 bets against 87% predicted; P/L -$15.40 |
| predictions | All resolved markets | all | 8580 | worse than the market | Brier 0.0635 vs the market's 0.0557 on 5078 markets |
| predictions | Bucket vs forecast | within 1σ | 1936 | worse than the market | Brier 0.1578 vs the market's 0.1316 on 1065 markets |
| predictions | Market liquidity | $1k–5k | 4322 | worse than the market | Brier 0.0525 vs the market's 0.0458 on 4322 markets |
| bets | Entry price | 0.50–0.80 | 86 | overconfident | won 63% of 86 bets against 86% predicted; P/L -$13.04 |
| predictions | Forecast vs climate normal | near normal (within 1σ) | 5995 | worse than the market | Brier 0.0626 vs the market's 0.0548 on 3646 markets |
| predictions | Predicted probability | 20–50% | 1640 | worse than the market | Brier 0.2007 vs the market's 0.1746 on 923 markets |
| predictions | Bucket vs forecast | over 2σ away | 4034 | underconfident | 98.9% sure of the side it predicted on average; that side happened 99.8% of the time |
| predictions | Bucket vs forecast | over 2σ away | 4034 | YES too often | predicted 1.1% YES on average; 0.2% resolved YES |
| bets | Bucket vs forecast | within 1σ | 60 | overconfident | won 58% of 60 bets against 84% predicted; P/L -$13.96 |
| bets | Lead time | 1 day | 49 | overconfident | won 63% of 49 bets against 88% predicted; P/L -$11.16 |

Error classes: right side 7804, overconfidence 6, significant overconfidence 0, underestimation 481, significant underestimation 289.

## Operation

How continuously the bot ran: each completed cycle collects data, predicts, bets and settles.

| Measure | Value |
|---|---:|
| Cycles completed | 62 |
| First / last cycle (UTC) | 2026-10-01 21:56 / 2026-10-17 16:38 |
| Median time between cycles | 6.3 h |
| Longest gap | 10.7 h (2026-10-12 01:42 to 2026-10-12 12:26) |
| Finished days without a cycle | 0 of 16 |
| Errors logged | none |

## Results by market day

| Market day | Bets | Won | Lost | Open | Staked | Settled P/L |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-13 | 3 | 1 | 2 | 0 | $4.94 | $-2.92 |
| 2026-10-12 | 7 | 6 | 1 | 0 | $12.10 | $4.10 |
| 2026-10-11 | 12 | 6 | 6 | 0 | $20.72 | $-5.20 |
| 2026-10-10 | 8 | 5 | 3 | 0 | $13.58 | $-1.51 |
| 2026-10-09 | 10 | 6 | 4 | 0 | $18.12 | $-2.96 |
| 2026-10-08 | 12 | 7 | 5 | 0 | $23.20 | $-5.19 |
| 2026-10-07 | 11 | 8 | 3 | 0 | $21.38 | $1.44 |
| 2026-10-06 | 4 | 1 | 3 | 0 | $7.50 | $-4.97 |
| 2026-10-05 | 14 | 10 | 4 | 0 | $25.62 | $2.42 |
| 2026-10-04 | 12 | 8 | 4 | 0 | $22.61 | $-3.24 |
| 2026-10-03 | 7 | 5 | 2 | 0 | $13.25 | $-0.36 |
| 2026-10-02 | 14 | 11 | 3 | 0 | $27.23 | $2.99 |

## Every bet, by market day

### 2026-10-13

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 112 | 2026-10-12 12:23 | Highest temperature in Seoul (Incheon) on October 13? 20°C | NO | 0.845 | 97.3% | 81.5% | $1.70 | WON | $0.31 |
| 113 | 2026-10-12 12:23 | Highest temperature in Seoul (Incheon) on October 13? 21°C | NO | 0.585 | 89.2% | 56.0% | $1.70 | LOST | $-1.70 |
| 114 | 2026-10-12 12:23 | Highest temperature in Munich on October 13? 15°C | NO | 0.813 | 89.1% | 79.0% | $1.53 | LOST | $-1.53 |

### 2026-10-12

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 105 | 2026-10-11 16:24 | Highest temperature in Seoul (Incheon) on October 12? 25°C | NO | 0.625 | 82.4% | 60.5% | $1.78 | WON | $1.07 |
| 106 | 2026-10-11 16:24 | Highest temperature in Seoul (Incheon) on October 12? 26°C | NO | 0.575 | 81.9% | 56.0% | $1.78 | WON | $1.32 |
| 107 | 2026-10-11 16:24 | Highest temperature in Wellington on October 12? 20°C | NO | 0.865 | 96.8% | 85.0% | $1.78 | WON | $0.28 |
| 108 | 2026-10-11 20:30 | Highest temperature in London on October 12? 19°C | NO | 0.755 | 82.3% | 74.0% | $1.68 | WON | $0.54 |
| 109 | 2026-10-12 01:39 | Highest temperature in Munich on October 12? 14°C | NO | 0.575 | 81.6% | 55.5% | $1.67 | WON | $1.23 |
| 110 | 2026-10-12 12:23 | Highest temperature in Los Angeles on October 12? 66-67°F | NO | 0.555 | 89.1% | 53.5% | $1.71 | WON | $1.37 |
| 111 | 2026-10-12 12:23 | Highest temperature in Los Angeles on October 12? 68-69°F | NO | 0.705 | 97.6% | 69.0% | $1.71 | LOST | $-1.71 |

### 2026-10-11

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 93 | 2026-10-10 15:56 | Lowest temperature in London on October 11? 8°C | NO | 0.765 | 90.2% | 73.5% | $1.75 | WON | $0.54 |
| 94 | 2026-10-10 15:56 | Highest temperature in Seoul (Incheon) on October 11? 25°C | NO | 0.525 | 85.0% | 51.0% | $1.74 | WON | $1.58 |
| 95 | 2026-10-10 15:56 | Highest temperature in Seoul (Incheon) on October 11? 26°C | NO | 0.655 | 83.7% | 63.5% | $1.74 | LOST | $-1.74 |
| 96 | 2026-10-10 15:56 | Highest temperature in Munich on October 11? 13°C | NO | 0.670 | 92.6% | 65.0% | $1.74 | WON | $0.86 |
| 97 | 2026-10-10 20:16 | Highest temperature in Munich on October 11? 14°C | NO | 0.455 | 80.7% | 44.0% | $1.77 | LOST | $-1.77 |
| 98 | 2026-10-10 20:16 | Highest temperature in Tokyo on October 11? 25°C | NO | 0.625 | 85.5% | 60.5% | $1.77 | WON | $1.06 |
| 99 | 2026-10-10 20:16 | Highest temperature in Milan on October 11? 20°C | NO | 0.725 | 80.9% | 71.5% | $1.76 | WON | $0.67 |
| 100 | 2026-10-11 01:11 | Highest temperature in Dallas on October 11? 90-91°F | NO | 0.525 | 81.0% | 51.0% | $1.75 | LOST | $-1.75 |
| 101 | 2026-10-11 07:46 | Highest temperature in Chicago on October 11? 78-79°F | NO | 0.415 | 88.1% | 39.5% | $1.81 | LOST | $-1.81 |
| 102 | 2026-10-11 07:46 | Highest temperature in Chicago on October 11? 80-81°F | NO | 0.875 | 98.0% | 85.5% | $1.81 | WON | $0.26 |
| 103 | 2026-10-11 07:46 | Highest temperature in Los Angeles on October 11? 72-73°F | NO | 0.325 | 84.8% | 30.5% | $1.81 | LOST | $-1.81 |
| 104 | 2026-10-11 07:46 | Highest temperature in San Francisco on October 11? 64-65°F | NO | 0.755 | 83.0% | 73.5% | $1.27 | LOST | $-1.27 |

### 2026-10-10

| # | Opened (UTC) | Market | Side | Entry | Model | Market | Stake | Status | P/L |
|---:|---|---|---|---:|---:|---:|---:|---|---:|
| 85 | 2026-10-09 17:09 | Highest temperature in London on October 10? 16°C | NO | 0.465 | 83.9% | 45.5% | $1.83 | LOST | $-1.83 |
| 86 | 2026-10-09 17:09 | Highest temperature in Seoul (Incheon) on October 10? 23°C | NO | 0.575 | 82.6% | 56.5% | $1.82 | WON | $1.35 |
| 87 | 2026-10-09 23:26 | Highest temperature in Milan on October 10? 20°C | NO | 0.725 | 80.5% | 71.5% | $1.80 | WON | $0.68 |
| 88 | 2026-10-09 23:26 | Highest temperature in Madrid on October 10? 25°C | NO | 0.545 | 82.9% | 52.5% | $1.80 | LOST | $-1.80 |
| 89 | 2026-10-09 23:26 | Highest temperature in Chicago on October 10? 82-83°F | NO | 0.615 | 83.4% | 60.0% | $1.80 | WON | $1.13 |
| 90 | 2026-10-09 23:26 | Highest temperature in Atlanta on October 10? 66-67°F | NO | 0.765 | 95.1% | 75.0% | $1.80 | WON | $0.55 |
| 91 | 2026-10-09 23:26 | Highest temperature in Atlanta on October 10? 68-69°F | NO | 0.685 | 89.1% | 66.5% | $1.66 | LOST | $-1.66 |
| 92 | 2026-10-10 07:40 | Highest temperature in Atlanta on October 10? 64-65°F | NO | 0.937 | 99.0% | 92.8% | $1.07 | WON | $0.07 |

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

Last cycle: 2026-10-17T16:38:03.156336+00:00 · markets monitored: 1694

```
{
 "markets": {
  "seen": 3047,
  "tradeable": 1694
 },
 "forecasts": {
  "stations": 27,
  "snapshots": 148
 },
 "reports": {
  "stations": 27,
  "new_reports": 159
 },
 "model_stats": {
  "enabled": false
 },
 "calibration": {
  "skipped": true
 },
 "market_anchor": {
  "n": 724,
  "approved": false,
  "same_day": {
   "n": 623,
   "approved": false
  }
 },
 "signals": {
  "predictions": 1628,
  "shadow_predictions": 3839,
  "bets": 0
 },
 "settlement": {
  "checked": 22,
  "bets_settled": 0,
  "price_histories": 114
 },
 "experiment": {
  "state": "running",
  "day": 16,
  "planned_days": 30,
  "ends_at": "2026-10-31T21:48:19.113159+00:00",
  "open_bets": 0,
  "ended_at": null,
  "completed_at": null
 },
 "observations": {
  "stations": 27,
  "new_rows": 18
 },
 "learning": {
  "outcomes": {
   "recorded": 0
  },
  "rollback": {
   "monitoring": "bias-sigma-20261013T004035-90d",
   "markets": 2013,
   "kept": true
  },
  "retrain": {
   "skipped": "not due",
   "next": "2026-10-20T00:40:35.573826+00:00"
  }
 },
 "seconds": 58.6
}
```

Recent warnings and errors:

- 2026-10-15 17:51 WARNING validation: WSSS 2026-10-17 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: WSSS 2026-10-16 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZUUU 2026-10-16 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZUUU 2026-10-17 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZUUU 2026-10-16 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZUUU 2026-10-17 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZSPD 2026-10-16 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZSPD 2026-10-17 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZSPD 2026-10-16 high: errors=[] rejected={'gem_seamless': 'stale_model_run'}
- 2026-10-15 17:51 WARNING validation: ZSPD 2026-10-17 low: errors=[] rejected={'gem_seamless': 'stale_model_run'}

