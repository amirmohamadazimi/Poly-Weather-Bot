# Research report: exp2-100usd

**Interim** (day 24 of 30). Mode: **PAPER TRADING**, real money used: **$0.00**.

Window: 2026-10-01 21:48 to 2026-10-31 21:48 UTC · 30 days · code 266ddda9e1b6 (last 6c965d907eca) · generated 2026-10-24 21:51 UTC

## Verdict

**NOT SUPPORTED: the model's probabilities were reliably worse than the market's prices, so there is no edge to bet on.**

| Check | Result | Evidence |
|---|---|---|
| Enough settled bets | fail | 114 settled; 200 needed before a profit or loss means much |
| Returns above zero | fail | ROI on stakes -7.3%, 95% interval -18.7% to 2.6% resampling 12 market days |
| Better than the market | fail | log loss 0.2089 vs the market's 0.1798 on 7227 liquid markets; difference 0.0291 (95% interval 0.0230 to 0.0348, resampling 821 events; below zero is better) |
| Bets won as often as predicted | fail | won 64.9% against 87.3% predicted (-7.3 standard errors; within ±2 passes) |
| Profit not resting on a few bets | fail | P/L -$15.40; without the 5 best bets -$25.55; first half -$15.40, second half $0.00 |

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

Every resolved market the model predicted, and the 7227 liquid ones (a market price, and enough liquidity to pass the bot's own check before betting), where the market's price is a real forecast to compare against. Lower is better for every score; skill is the share of the market's log loss the model avoided.

| Score | Model | Raw model | Market |
|---|---:|---:|---:|
| Log loss, all 12076 markets | 0.2219 | 0.2219 | |
| Brier score, all markets | 0.0679 | 0.0679 | |
| Calibration error (ECE), all markets | 0.9% | | |
| Log loss, 7227 liquid markets | 0.2089 | | 0.1798 |
| Brier score, liquid markets | 0.0636 | | 0.0556 |
| Calibration error (ECE), liquid markets | 1.0% | | 1.3% |
| Skill against the market | -16.2% | | |

## Was the edge stable?

P/L -$15.40. The 5 best bets made $10.15; without them the rest made -$25.55 (ROI -12.7%).

| Period | Bets | Staked | P/L | ROI |
|---|---:|---:|---:|---:|
| First half (from 2026-10-01) | 114 | $210.25 | -$15.40 | -7.3% |
| Second half (from 2026-10-13) | 0 | $0.00 | $0.00 | n/a |
| Week 1 (from 2026-10-01) | 76 | $144.49 | -$7.95 | -5.5% |
| Week 2 (from 2026-10-08) | 38 | $65.76 | -$7.44 | -11.3% |

## Market types

| Bets on | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| high, range | 109 | 109 | 65.1% | 87.1% | -$14.19 | -7.1% |
| low, range | 5 | 5 | 60.0% | 92.0% | -$1.20 | -12.6% |

| Predictions on | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high, or above | 559 | 0.0453 | 0.0090 | 558 | 0.0447 | 0.0288 | -55.0% |
| high, or below | 559 | 0.0276 | 0.0052 | 559 | 0.0276 | 0.0184 | -49.7% |
| high, range | 5030 | 0.2629 | 0.0813 | 5030 | 0.2629 | 0.2171 | -21.1% |
| low, or above | 539 | 0.0177 | 0.0013 | 165 | 0.0166 | 0.0409 | 59.5% |
| low, or below | 538 | 0.0663 | 0.0170 | 147 | 0.0124 | 0.0474 | 73.9% |
| low, range | 4851 | 0.2622 | 0.0811 | 768 | 0.1861 | 0.2180 | 14.6% |

| Side | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| NO | 114 | 114 | 64.9% | 87.3% | -$15.40 | -7.3% |

## Locations

By P/L of bets: best Munich ($1.86), Chengdu ($1.40), Seoul (Incheon) ($0.82); worst Chicago (-$7.22), Dallas (-$4.39), Madrid (-$3.83).

By skill against the market: best Singapore (0.6%), Madrid (0.6%), Tokyo (-1.1%); worst Chicago (-66.0%), Los Angeles (-51.8%), Munich (-48.0%).

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
| Ankara | 440 | 0.2454 | 0.0721 | 226 | 0.2147 | 0.1749 | -22.8% |
| Atlanta | 462 | 0.2055 | 0.0647 | 240 | 0.2015 | 0.1539 | -31.0% |
| Austin | 462 | 0.2328 | 0.0706 | 234 | 0.2143 | 0.1670 | -28.4% |
| Buenos Aires | 462 | 0.2539 | 0.0758 | 240 | 0.2457 | 0.2360 | -4.1% |
| Chengdu | 440 | 0.2317 | 0.0705 | 223 | 0.2504 | 0.2314 | -8.2% |
| Chicago | 462 | 0.2150 | 0.0685 | 241 | 0.2292 | 0.1381 | -66.0% |
| Dallas | 462 | 0.2202 | 0.0669 | 243 | 0.2277 | 0.1905 | -19.5% |
| Houston | 462 | 0.1904 | 0.0603 | 244 | 0.1836 | 0.1426 | -28.7% |
| London | 462 | 0.1926 | 0.0599 | 398 | 0.1704 | 0.1447 | -17.8% |
| Los Angeles | 462 | 0.2752 | 0.0793 | 241 | 0.2892 | 0.1905 | -51.8% |
| Lucknow | 440 | 0.1981 | 0.0613 | 229 | 0.1880 | 0.1311 | -43.4% |
| Madrid | 462 | 0.2202 | 0.0673 | 296 | 0.1925 | 0.1936 | 0.6% |
| Mexico City | 462 | 0.2124 | 0.0653 | 233 | 0.2277 | 0.1924 | -18.3% |
| Miami | 462 | 0.1873 | 0.0593 | 333 | 0.1498 | 0.1329 | -12.7% |
| Milan | 462 | 0.2319 | 0.0715 | 239 | 0.2031 | 0.1554 | -30.7% |
| Munich | 462 | 0.2410 | 0.0706 | 235 | 0.2440 | 0.1649 | -48.0% |
| NYC | 462 | 0.1980 | 0.0620 | 336 | 0.1615 | 0.1503 | -7.5% |
| San Francisco | 462 | 0.2370 | 0.0727 | 242 | 0.2434 | 0.2274 | -7.0% |
| Sao Paulo | 460 | 0.2326 | 0.0691 | 234 | 0.2601 | 0.2196 | -18.4% |
| Seattle | 462 | 0.1988 | 0.0629 | 248 | 0.1956 | 0.1833 | -6.8% |
| Seoul (Incheon) | 440 | 0.2367 | 0.0726 | 336 | 0.2108 | 0.1890 | -11.6% |
| Shanghai | 440 | 0.2222 | 0.0683 | 371 | 0.2114 | 0.1988 | -6.4% |
| Singapore | 220 | 0.1898 | 0.0607 | 220 | 0.1898 | 0.1910 | 0.6% |
| Tokyo | 440 | 0.2171 | 0.0675 | 356 | 0.1854 | 0.1834 | -1.1% |
| Toronto | 462 | 0.2400 | 0.0719 | 232 | 0.2285 | 0.2146 | -6.5% |
| Warsaw | 462 | 0.2409 | 0.0716 | 273 | 0.2231 | 0.2159 | -3.3% |
| Wellington | 440 | 0.2096 | 0.0664 | 284 | 0.1866 | 0.1753 | -6.4% |

## Weather variables

Which was more predictable: the day's highest or lowest temperature.

| Variable | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high | 6148 | 0.2217 | 0.0678 | 6147 | 0.2217 | 0.1819 | -21.8% |
| low | 5928 | 0.2222 | 0.0680 | 1080 | 0.1366 | 0.1677 | 18.6% |

## Over- and underconfidence

The model's probability in bands against how often the outcome happened. A band is flagged when the gap is two standard errors or more.

| Predicted | Markets | Predicted mean | Happened | Standard errors | Reading |
|---|---:|---:|---:|---:|---|
| 0.0–0.1 | 7959 | 2.4% | 1.4% | -5.8 | underconfident |
| 0.1–0.2 | 1802 | 14.8% | 15.9% | +1.3 |  |
| 0.2–0.3 | 1308 | 24.5% | 24.7% | +0.2 |  |
| 0.3–0.4 | 801 | 34.1% | 35.0% | +0.5 |  |
| 0.4–0.5 | 186 | 43.6% | 46.2% | +0.7 |  |
| 0.5–0.6 | 17 | 53.9% | 58.8% | +0.4 |  |
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
| 2026-10-20 | Munich | high | 9°C | 1.0% | 0.1% | YES | – | 4.61 |
| 2026-10-22 | Los Angeles | high | 70–71°F | 1.0% | 35.0% | YES | – | 4.61 |
| 2026-10-08 | Warsaw | high | 20°C | 1.1% | 0.2% | YES | – | 4.50 |
| 2026-10-06 | Madrid | low | 13°C | 1.4% | illiquid | YES | – | 4.28 |
| 2026-10-07 | Mexico City | high | 20°C | 1.5% | 1.6% | YES | – | 4.19 |
| 2026-10-21 | Munich | high | 11°C | 1.5% | 32.0% | YES | – | 4.19 |
| 2026-10-05 | Dallas | high | 86–87°F | 1.5% | 7.0% | YES | – | 4.18 |

## Model versions

Model · station bias/spread set · probability calibrator.

| Version | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| normal-multimodel-v1 · bias-sigma-20261001-initial · identity | 6567 | 0.2235 | 0.0682 | 3851 | 0.2103 | 0.1838 | -14.4% |
| normal-multimodel-v1 · bias-sigma-20261013T004035-90d · identity | 4277 | 0.2181 | 0.0670 | 2639 | 0.2041 | 0.1750 | -16.6% |
| normal-multimodel-v1 · bias-sigma-20261020T011335-90d · identity | 1232 | 0.2268 | 0.0694 | 737 | 0.2193 | 0.1764 | -24.3% |

| Version | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| normal-multimodel-v1 · bias-sigma-20261001-initial · identity | 114 | 114 | 64.9% | 87.3% | -$15.40 | -7.3% |

## Operation

How continuously the bot ran: each completed cycle collects data, predicts, bets and settles.

| Measure | Value |
|---|---:|
| Cycles completed | 96 |
| First / last cycle (UTC) | 2026-10-01 21:56 / 2026-10-24 21:51 |
| Median time between cycles | 5.6 h |
| Longest gap | 10.7 h (2026-10-12 01:42 to 2026-10-12 12:26) |
| Finished days without a cycle | 0 of 23 |
| Errors logged | none |

## How this was computed

- Window: bets placed and predictions made up to the experiment's planned end. Predictions are each resolved market's decision prediction (the last made a day or more ahead), from the learning ledger.
- The market comparison uses liquid markets only: those with a price that passed the bot's liquidity check (strategy.min_liquidity_usd) when it looked. A thin market's mid price is a placeholder of a near-empty book (often 0.34 or 0.40), and comparing against it makes any model look better than the market.
- Intervals are 95% bootstrap intervals (2000 resamples, seed 7): returns resample whole market days, log-loss differences resample whole events, because outcomes on one day or one event move together.
- The verdict needs 200+ settled bets, returns above zero, log loss below the market's on liquid markets, a win rate within two standard errors of the predicted one, and a profit without the 5 best bets and in both halves.
- Regenerate with `python main.py research` on the experiment's database.

