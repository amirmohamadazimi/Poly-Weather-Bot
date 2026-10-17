# Research report: exp2-100usd

**Interim** (day 16 of 30). Mode: **PAPER TRADING**, real money used: **$0.00**.

Window: 2026-10-01 21:48 to 2026-10-31 21:48 UTC · 30 days · code 266ddda9e1b6 (last ba8aea21905d) · generated 2026-10-17 16:38 UTC

## Verdict

**NOT SUPPORTED: the model's probabilities were reliably worse than the market's prices, so there is no edge to bet on.**

| Check | Result | Evidence |
|---|---|---|
| Enough settled bets | fail | 114 settled; 200 needed before a profit or loss means much |
| Returns above zero | fail | ROI on stakes -7.3%, 95% interval -18.7% to 2.6% resampling 12 market days |
| Better than the market | fail | log loss 0.2089 vs the market's 0.1806 on 5078 liquid markets; difference 0.0284 (95% interval 0.0208 to 0.0352, resampling 586 events; below zero is better) |
| Bets won as often as predicted | fail | won 64.9% against 87.3% predicted (-7.3 standard errors; within ±2 passes) |
| Profit not resting on a few bets | fail | P/L -$15.40; without the 5 best bets -$25.55; first half -$10.35, second half -$5.05 |

Success needs every check, not a positive P/L alone (spec section 17).

## Performance

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Ending bankroll | $84.60 |
| Total P/L | -$15.40 |
| Return on the starting bankroll | -15.4% |
| ROI on settled stakes | -7.3% |
| Bets (settled / open) | 114 (114 / 0) |
| Win rate (predicted) | 64.9% (87.3%) |
| Average bet | $1.84 |
| Average edge (probability minus price) | 17.7% |
| Average predicted probability | 87.3% |
| Average entry price | 0.696 |
| Brier score / log loss of the bets | 0.2717 / 0.7965 |
| Calibration error of the bets (ECE) | 22.4% |
| Maximum drawdown | $21.17 (20.3%) |

## Predictions

Every resolved market the model predicted, and the 5078 liquid ones (a market price, and enough liquidity to pass the bot's own check before betting), where the market's price is a real forecast to compare against. Lower is better for every score; skill is the share of the market's log loss the model avoided.

| Score | Model | Raw model | Market |
|---|---:|---:|---:|
| Log loss, all 8580 markets | 0.2226 | 0.2226 | |
| Brier score, all markets | 0.0680 | 0.0680 | |
| Calibration error (ECE), all markets | 1.1% | | |
| Log loss, 5078 liquid markets | 0.2089 | | 0.1806 |
| Brier score, liquid markets | 0.0635 | | 0.0557 |
| Calibration error (ECE), liquid markets | 1.1% | | 1.1% |
| Skill against the market | -15.7% | | |

## Was the edge stable?

P/L -$15.40. The 5 best bets made $10.15; without them the rest made -$25.55 (ROI -12.7%).

| Period | Bets | Staked | P/L | ROI |
|---|---:|---:|---:|---:|
| First half (from 2026-10-01) | 86 | $162.57 | -$10.35 | -6.4% |
| Second half (from 2026-10-09) | 28 | $47.68 | -$5.05 | -10.6% |
| Week 1 (from 2026-10-01) | 76 | $144.49 | -$7.95 | -5.5% |
| Week 2 (from 2026-10-08) | 38 | $65.76 | -$7.44 | -11.3% |

## Market types

| Bets on | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| high, range | 109 | 109 | 65.1% | 87.1% | -$14.19 | -7.1% |
| low, range | 5 | 5 | 60.0% | 92.0% | -$1.20 | -12.6% |

| Predictions on | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high, or above | 397 | 0.0396 | 0.0074 | 397 | 0.0396 | 0.0210 | -88.7% |
| high, or below | 397 | 0.0266 | 0.0047 | 397 | 0.0266 | 0.0227 | -17.0% |
| high, range | 3573 | 0.2657 | 0.0821 | 3573 | 0.2657 | 0.2213 | -20.1% |
| low, or above | 383 | 0.0169 | 0.0012 | 116 | 0.0161 | 0.0292 | 44.9% |
| low, or below | 383 | 0.0778 | 0.0214 | 110 | 0.0117 | 0.0414 | 71.7% |
| low, range | 3447 | 0.2605 | 0.0804 | 485 | 0.1690 | 0.2078 | 18.7% |

| Side | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| NO | 114 | 114 | 64.9% | 87.3% | -$15.40 | -7.3% |

## Locations

By P/L of bets: best Munich ($1.86), Chengdu ($1.40), Seoul (Incheon) ($0.82); worst Chicago (-$7.22), Dallas (-$4.39), Madrid (-$3.83).

By skill against the market: best Toronto (5.9%), Singapore (0.3%), Seattle (-2.7%); worst Chicago (-59.0%), Los Angeles (-58.5%), Munich (-46.8%).

| City | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| Ankara | 3 | 3 | 100.0% | 85.2% | $2.25 | 44.7% |
| Atlanta | 7 | 7 | 57.1% | 91.5% | -$3.77 | -30.7% |
| Austin | 4 | 4 | 75.0% | 81.0% | $1.19 | 16.3% |
| Chengdu | 6 | 6 | 66.7% | 86.5% | $1.40 | 12.5% |
| Chicago | 12 | 12 | 50.0% | 89.5% | -$7.22 | -33.0% |
| Dallas | 6 | 6 | 33.3% | 86.0% | -$4.39 | -42.7% |
| Houston | 2 | 2 | 50.0% | 87.1% | -$0.94 | -27.6% |
| London | 12 | 12 | 66.7% | 88.6% | -$2.61 | -11.3% |
| Los Angeles | 8 | 8 | 50.0% | 86.0% | -$3.80 | -25.9% |
| Lucknow | 3 | 3 | 33.3% | 83.6% | -$3.51 | -59.3% |
| Madrid | 6 | 6 | 50.0% | 84.5% | -$3.83 | -32.6% |
| Mexico City | 3 | 3 | 100.0% | 88.6% | $2.28 | 38.4% |
| Milan | 4 | 4 | 75.0% | 86.9% | -$0.37 | -4.9% |
| Munich | 8 | 8 | 75.0% | 86.7% | $1.86 | 12.9% |
| NYC | 1 | 1 | 100.0% | 92.9% | $0.30 | 15.0% |
| San Francisco | 6 | 6 | 66.7% | 86.6% | -$0.43 | -4.0% |
| Sao Paulo | 1 | 1 | 100.0% | 80.6% | $0.96 | 48.1% |
| Seattle | 2 | 2 | 100.0% | 89.1% | $1.25 | 31.2% |
| Seoul (Incheon) | 12 | 12 | 66.7% | 87.3% | $0.82 | 3.8% |
| Shanghai | 2 | 2 | 100.0% | 94.0% | $1.51 | 43.4% |
| Tokyo | 2 | 2 | 50.0% | 84.3% | -$0.94 | -24.9% |
| Warsaw | 2 | 2 | 100.0% | 83.9% | $1.79 | 45.1% |
| Wellington | 2 | 2 | 100.0% | 93.8% | $0.79 | 21.0% |

| City | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ankara | 308 | 0.2448 | 0.0720 | 159 | 0.2124 | 0.1715 | -23.8% |
| Atlanta | 330 | 0.2123 | 0.0664 | 171 | 0.2189 | 0.1589 | -37.8% |
| Austin | 330 | 0.2469 | 0.0748 | 168 | 0.2289 | 0.1840 | -24.4% |
| Buenos Aires | 330 | 0.2515 | 0.0754 | 173 | 0.2528 | 0.2374 | -6.5% |
| Chengdu | 308 | 0.2263 | 0.0688 | 157 | 0.2506 | 0.2222 | -12.8% |
| Chicago | 330 | 0.2212 | 0.0704 | 173 | 0.2381 | 0.1498 | -59.0% |
| Dallas | 330 | 0.2137 | 0.0652 | 175 | 0.2420 | 0.1989 | -21.7% |
| Houston | 330 | 0.1907 | 0.0603 | 174 | 0.1868 | 0.1457 | -28.2% |
| London | 330 | 0.2016 | 0.0627 | 288 | 0.1792 | 0.1605 | -11.7% |
| Los Angeles | 330 | 0.2764 | 0.0799 | 173 | 0.2893 | 0.1825 | -58.5% |
| Lucknow | 308 | 0.1989 | 0.0616 | 161 | 0.1887 | 0.1443 | -30.8% |
| Madrid | 330 | 0.2216 | 0.0672 | 198 | 0.1805 | 0.1722 | -4.8% |
| Mexico City | 330 | 0.2085 | 0.0640 | 168 | 0.2232 | 0.1849 | -20.7% |
| Miami | 330 | 0.1896 | 0.0600 | 240 | 0.1418 | 0.1264 | -12.2% |
| Milan | 330 | 0.2295 | 0.0706 | 172 | 0.1987 | 0.1547 | -28.5% |
| Munich | 330 | 0.2121 | 0.0642 | 166 | 0.2037 | 0.1387 | -46.8% |
| NYC | 330 | 0.2065 | 0.0648 | 242 | 0.1667 | 0.1614 | -3.3% |
| San Francisco | 330 | 0.2318 | 0.0714 | 175 | 0.2341 | 0.2251 | -4.0% |
| Sao Paulo | 330 | 0.2353 | 0.0685 | 168 | 0.2765 | 0.2330 | -18.7% |
| Seattle | 330 | 0.1998 | 0.0628 | 178 | 0.1949 | 0.1897 | -2.7% |
| Seoul (Incheon) | 308 | 0.2416 | 0.0736 | 229 | 0.2010 | 0.1937 | -3.8% |
| Shanghai | 308 | 0.2295 | 0.0699 | 252 | 0.2169 | 0.2048 | -5.9% |
| Singapore | 154 | 0.1877 | 0.0603 | 154 | 0.1877 | 0.1883 | 0.3% |
| Tokyo | 308 | 0.2226 | 0.0693 | 239 | 0.1812 | 0.1759 | -3.0% |
| Toronto | 330 | 0.2418 | 0.0722 | 166 | 0.2202 | 0.2341 | 5.9% |
| Warsaw | 330 | 0.2498 | 0.0733 | 179 | 0.2263 | 0.2142 | -5.7% |
| Wellington | 308 | 0.2007 | 0.0637 | 180 | 0.1802 | 0.1548 | -16.4% |

## Weather variables

Which was more predictable: the day's highest or lowest temperature.

| Variable | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high | 4367 | 0.2234 | 0.0683 | 4367 | 0.2234 | 0.1851 | -20.7% |
| low | 4213 | 0.2218 | 0.0678 | 711 | 0.1197 | 0.1529 | 21.7% |

## Over- and underconfidence

The model's probability in bands against how often the outcome happened. A band is flagged when the gap is two standard errors or more.

| Predicted | Markets | Predicted mean | Happened | Standard errors | Reading |
|---|---:|---:|---:|---:|---|
| 0.0–0.1 | 5678 | 2.3% | 1.4% | -4.4 | underconfident |
| 0.1–0.2 | 1246 | 14.8% | 16.6% | +1.8 |  |
| 0.2–0.3 | 925 | 24.5% | 23.0% | -1.1 |  |
| 0.3–0.4 | 570 | 34.2% | 35.4% | +0.6 |  |
| 0.4–0.5 | 145 | 43.8% | 45.5% | +0.4 |  |
| 0.5–0.6 | 13 | 54.5% | 53.8% | -0.0 |  |
| 0.6–0.7 | 1 | 65.6% | 100.0% | +0.7 |  |
| 0.7–0.8 | 1 | 73.1% | 100.0% | +0.6 |  |
| 0.8–0.9 | 1 | 87.0% | 100.0% | +0.4 |  |

| Bets at entry price | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| 0.00–0.50 | 9 | 9 | 33.3% | 84.6% | -$3.88 | -24.2% |
| 0.50–0.80 | 86 | 86 | 62.8% | 86.0% | -$13.04 | -8.2% |
| 0.80–0.90 | 15 | 15 | 86.7% | 93.5% | $0.85 | 2.9% |
| 0.90–0.95 | 4 | 4 | 100.0% | 98.5% | $0.68 | 9.7% |

## Largest errors

The ten predictions with the highest log loss. The market's price is shown for liquid markets only.

| Day | City | Variable | Bucket | Model | Market | Outcome | Bet | Log loss |
|---|---|---|---|---:|---:|---|---|---:|
| 2026-10-03 | Warsaw | low | 4°C | 1.0% | illiquid | YES | – | 4.61 |
| 2026-10-08 | Sao Paulo | high | 33°C | 1.0% | 6.0% | YES | – | 4.61 |
| 2026-10-15 | Austin | low | 64–65°F | 1.0% | illiquid | YES | – | 4.61 |
| 2026-10-08 | Warsaw | high | 20°C | 1.1% | 0.2% | YES | – | 4.50 |
| 2026-10-06 | Madrid | low | 13°C | 1.4% | illiquid | YES | – | 4.28 |
| 2026-10-07 | Mexico City | high | 20°C | 1.5% | 1.6% | YES | – | 4.19 |
| 2026-10-05 | Dallas | high | 86–87°F | 1.5% | 7.0% | YES | – | 4.18 |
| 2026-10-13 | Sao Paulo | high | 25°C | 2.2% | 21.0% | YES | – | 3.83 |
| 2026-10-12 | Los Angeles | high | 68–69°F | 2.3% | 55.0% | YES | LOST -$1.71 | 3.78 |
| 2026-10-16 | Los Angeles | high | 98–99°F | 2.7% | 31.5% | YES | – | 3.63 |

## Model versions

Model · station bias/spread set · probability calibrator.

| Version | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| normal-multimodel-v1 · bias-sigma-20261001-initial · identity | 6567 | 0.2235 | 0.0682 | 3851 | 0.2103 | 0.1838 | -14.4% |
| normal-multimodel-v1 · bias-sigma-20261013T004035-90d · identity | 2013 | 0.2196 | 0.0675 | 1227 | 0.2046 | 0.1706 | -19.9% |

| Version | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| normal-multimodel-v1 · bias-sigma-20261001-initial · identity | 114 | 114 | 64.9% | 87.3% | -$15.40 | -7.3% |

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

## How this was computed

- Window: bets placed and predictions made up to the experiment's planned end. Predictions are each resolved market's decision prediction (the last made a day or more ahead), from the learning ledger.
- The market comparison uses liquid markets only: those with a price that passed the bot's liquidity check (strategy.min_liquidity_usd) when it looked. A thin market's mid price is a placeholder of a near-empty book (often 0.34 or 0.40), and comparing against it makes any model look better than the market.
- Intervals are 95% bootstrap intervals (2000 resamples, seed 7): returns resample whole market days, log-loss differences resample whole events, because outcomes on one day or one event move together.
- The verdict needs 200+ settled bets, returns above zero, log loss below the market's on liquid markets, a win rate within two standard errors of the predicted one, and a profit without the 5 best bets and in both halves.
- Regenerate with `python main.py research` on the experiment's database.

