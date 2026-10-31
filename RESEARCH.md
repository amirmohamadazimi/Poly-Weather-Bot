# Research report: exp3-v3-100usd

**Interim** (day 16 of 30). Mode: **PAPER TRADING**, real money used: **$0.00**.

Window: 2026-10-15 18:50 to 2026-11-14 18:50 UTC · 30 days · code ba8aea21905d (last 6c965d907eca) · generated 2026-10-31 16:13 UTC

## Verdict

**NOT SUPPORTED: the model's probabilities were reliably worse than the market's prices, so there is no edge to bet on.**

| Check | Result | Evidence |
|---|---|---|
| Enough settled bets | fail | 1 settled; 200 needed before a profit or loss means much |
| Returns above zero | fail | ROI on stakes -100.0%; an interval needs 5+ market days with settled bets |
| Better than the market | fail | log loss 0.1976 vs the market's 0.1791 on 2399 liquid markets; difference 0.0186 (95% interval 0.0092 to 0.0275, resampling 265 events; below zero is better) |
| Bets won as often as predicted | fail | won 0.0% against 83.0% predicted (-2.2 standard errors; within ±2 passes) |
| Profit not resting on a few bets | fail | P/L -$2.00; without the 5 best bets $0.00; first half -$2.00, second half $0.00 |

Success needs every check, not a positive P/L alone (spec section 17).

## Performance

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Ending bankroll | $98.00 |
| Total P/L | -$2.00 |
| Return on the starting bankroll | -2.0% |
| ROI on settled stakes | -100.0% |
| Bets (settled / open) | 1 (1 / 0) |
| Win rate (predicted) | 0.0% (83.0%) |
| Average bet | $2.00 |
| Average edge (probability minus price) | 24.9% |
| Average predicted probability | 83.0% |
| Average entry price | 0.581 |
| Brier score / log loss of the bets | 0.6897 / 1.7747 |
| Calibration error of the bets (ECE) | 83.0% |
| Maximum drawdown | $2.03 (2.0%) |

## Predictions

Every resolved market the model predicted, and the 2399 liquid ones (a market price, and enough liquidity to pass the bot's own check before betting), where the market's price is a real forecast to compare against. Lower is better for every score; skill is the share of the market's log loss the model avoided.

| Score | Model | Raw model | Market |
|---|---:|---:|---:|
| Log loss, all 3938 markets | 0.2046 | 0.2047 | |
| Brier score, all markets | 0.0633 | 0.0633 | |
| Calibration error (ECE), all markets | 1.0% | | |
| Log loss, 2399 liquid markets | 0.1976 | | 0.1791 |
| Brier score, liquid markets | 0.0616 | | 0.0561 |
| Calibration error (ECE), liquid markets | 1.2% | | 1.3% |
| Skill against the market | -10.4% | | |

## Was the edge stable?

P/L -$2.00. The 5 best bets made -$2.00; without them the rest made $0.00 (ROI n/a).

| Period | Bets | Staked | P/L | ROI |
|---|---:|---:|---:|---:|
| First half (from 2026-10-15) | 1 | $2.00 | -$2.00 | -100.0% |
| Second half (from 2026-10-23) | 0 | $0.00 | $0.00 | n/a |
| Week 1 (from 2026-10-15) | 1 | $2.00 | -$2.00 | -100.0% |

## Market types

| Bets on | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| high, range | 1 | 1 | 0.0% | 83.0% | -$2.00 | -100.0% |

| Predictions on | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high, or above | 182 | 0.0601 | 0.0144 | 182 | 0.0601 | 0.0498 | -20.8% |
| high, or below | 182 | 0.0179 | 0.0029 | 182 | 0.0179 | 0.0081 | -120.9% |
| high, range | 1638 | 0.2433 | 0.0766 | 1638 | 0.2433 | 0.2071 | -17.4% |
| low, or above | 176 | 0.0107 | 0.0001 | 57 | 0.0106 | 0.0571 | 81.5% |
| low, or below | 176 | 0.0315 | 0.0065 | 38 | 0.0101 | 0.0793 | 87.3% |
| low, range | 1584 | 0.2433 | 0.0754 | 302 | 0.2001 | 0.2433 | 17.8% |

| Side | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| NO | 1 | 1 | 0.0% | 83.0% | -$2.00 | -100.0% |

## Locations

By P/L of bets: too few groups with 5+ to rank.

By skill against the market: best Wellington (18.7%), Madrid (11.0%), Singapore (7.7%); worst Lucknow (-70.2%), Austin (-52.9%), Chicago (-47.6%).

| City | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| Los Angeles | 1 | 1 | 0.0% | 83.0% | -$2.00 | -100.0% |

| City | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ankara | 154 | 0.2376 | 0.0717 | 78 | 0.2336 | 0.1768 | -32.1% |
| Atlanta | 154 | 0.1863 | 0.0600 | 80 | 0.1554 | 0.1464 | -6.2% |
| Austin | 154 | 0.2155 | 0.0675 | 77 | 0.1941 | 0.1269 | -52.9% |
| Buenos Aires | 154 | 0.2658 | 0.0787 | 78 | 0.2561 | 0.2562 | 0.0% |
| Chengdu | 132 | 0.2285 | 0.0723 | 66 | 0.2504 | 0.2568 | 2.5% |
| Chicago | 154 | 0.1813 | 0.0549 | 78 | 0.1885 | 0.1277 | -47.6% |
| Dallas | 154 | 0.2113 | 0.0642 | 79 | 0.2062 | 0.1662 | -24.0% |
| Houston | 154 | 0.1605 | 0.0506 | 83 | 0.1538 | 0.1319 | -16.6% |
| London | 154 | 0.1490 | 0.0454 | 133 | 0.1401 | 0.1098 | -27.7% |
| Los Angeles | 154 | 0.2003 | 0.0636 | 84 | 0.2295 | 0.2063 | -11.2% |
| Lucknow | 132 | 0.1556 | 0.0471 | 67 | 0.1718 | 0.1009 | -70.2% |
| Madrid | 154 | 0.2060 | 0.0658 | 116 | 0.2096 | 0.2356 | 11.0% |
| Mexico City | 154 | 0.2017 | 0.0649 | 77 | 0.2179 | 0.1999 | -9.0% |
| Miami | 154 | 0.1802 | 0.0580 | 106 | 0.1858 | 0.1580 | -17.6% |
| Milan | 154 | 0.2628 | 0.0753 | 78 | 0.2018 | 0.1602 | -26.0% |
| Munich | 154 | 0.2576 | 0.0746 | 80 | 0.2783 | 0.2333 | -19.3% |
| NYC | 154 | 0.1540 | 0.0468 | 105 | 0.1349 | 0.1281 | -5.3% |
| San Francisco | 154 | 0.2232 | 0.0665 | 80 | 0.2173 | 0.2226 | 2.3% |
| Sao Paulo | 154 | 0.2172 | 0.0689 | 79 | 0.2191 | 0.1872 | -17.1% |
| Seattle | 154 | 0.2246 | 0.0685 | 81 | 0.2095 | 0.1703 | -23.0% |
| Seoul (Incheon) | 132 | 0.1748 | 0.0554 | 109 | 0.1817 | 0.1759 | -3.3% |
| Shanghai | 132 | 0.1916 | 0.0602 | 116 | 0.1891 | 0.1791 | -5.6% |
| Singapore | 66 | 0.1816 | 0.0605 | 66 | 0.1816 | 0.1967 | 7.7% |
| Tokyo | 132 | 0.2161 | 0.0700 | 119 | 0.2114 | 0.2024 | -4.4% |
| Toronto | 154 | 0.2008 | 0.0623 | 77 | 0.1890 | 0.1444 | -30.9% |
| Warsaw | 154 | 0.2142 | 0.0682 | 107 | 0.2240 | 0.2371 | 5.5% |
| Wellington | 132 | 0.2037 | 0.0637 | 100 | 0.1681 | 0.2068 | 18.7% |

## Weather variables

Which was more predictable: the day's highest or lowest temperature.

| Variable | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high | 2002 | 0.2061 | 0.0642 | 2002 | 0.2061 | 0.1747 | -18.0% |
| low | 1936 | 0.2029 | 0.0623 | 397 | 0.1547 | 0.2009 | 23.0% |

## Over- and underconfidence

The model's probability in bands against how often the outcome happened. A band is flagged when the gap is two standard errors or more.

| Predicted | Markets | Predicted mean | Happened | Standard errors | Reading |
|---|---:|---:|---:|---:|---|
| 0.0–0.1 | 2707 | 2.0% | 0.9% | -3.9 | underconfident |
| 0.1–0.2 | 429 | 14.7% | 14.9% | +0.1 |  |
| 0.2–0.3 | 357 | 24.9% | 24.9% | +0.0 |  |
| 0.3–0.4 | 315 | 34.6% | 36.2% | +0.6 |  |
| 0.4–0.5 | 102 | 43.2% | 46.1% | +0.6 |  |
| 0.5–0.6 | 24 | 53.2% | 62.5% | +0.9 |  |
| 0.6–0.7 | 3 | 66.0% | 100.0% | +1.2 |  |
| 0.9–1.0 | 1 | 97.9% | 100.0% | +0.1 |  |

| Bets at entry price | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| 0.50–0.80 | 1 | 1 | 0.0% | 83.0% | -$2.00 | -100.0% |

## Largest errors

The ten predictions with the highest log loss. The market's price is shown for liquid markets only.

| Day | City | Variable | Bucket | Model | Market | Outcome | Bet | Log loss |
|---|---|---|---|---:|---:|---|---|---:|
| 2026-10-16 | Milan | low | 14°C | 1.0% | illiquid | YES | – | 4.61 |
| 2026-10-17 | Milan | low | 14°C | 1.0% | illiquid | YES | – | 4.61 |
| 2026-10-20 | Munich | high | 9°C | 1.0% | 0.1% | YES | – | 4.61 |
| 2026-10-21 | San Francisco | low | 62–63°F | 1.0% | illiquid | YES | – | 4.59 |
| 2026-10-18 | Buenos Aires | low | 9°C | 1.3% | illiquid | YES | – | 4.31 |
| 2026-10-16 | Seattle | low | 46–47°F | 1.5% | illiquid | YES | – | 4.23 |
| 2026-10-21 | Ankara | high | 20°C or above | 2.2% | 1.9% | YES | – | 3.80 |
| 2026-10-21 | Munich | high | 11°C | 2.9% | 29.5% | YES | – | 3.55 |
| 2026-10-17 | Dallas | low | 46–47°F | 3.0% | illiquid | YES | – | 3.51 |
| 2026-10-16 | Chicago | high | 56–57°F | 3.4% | 21.5% | YES | – | 3.39 |

## Model versions

Model · station bias/spread set · probability calibrator.

| Version | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| weighted-multimodel-v1 · bias-sigma-20261015-backtest-run1 · identity | 3355 | 0.2059 | 0.0635 | 2039 | 0.1979 | 0.1797 | -10.1% |
| weighted-multimodel-v1 · bias-sigma-20261015-backtest-run1 · isotonic-20261021T0752 | 583 | 0.1971 | 0.0622 | 360 | 0.1962 | 0.1757 | -11.7% |

| Version | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|
| weighted-multimodel-v1 · bias-sigma-20261015-backtest-run1 · identity | 1 | 1 | 0.0% | 83.0% | -$2.00 | -100.0% |

## Operation

How continuously the bot ran: each completed cycle collects data, predicts, bets and settles.

| Measure | Value |
|---|---:|
| Cycles completed | 72 |
| First / last cycle (UTC) | 2026-10-15 18:55 / 2026-10-31 16:13 |
| Median time between cycles | 5.1 h |
| Longest gap | 9.0 h (2026-10-28 02:30 to 2026-10-28 11:29) |
| Finished days without a cycle | 0 of 16 |
| Errors logged | none |

## How this was computed

- Window: bets placed and predictions made up to the experiment's planned end. Predictions are each resolved market's decision prediction (the last made a day or more ahead), from the learning ledger.
- The market comparison uses liquid markets only: those with a price that passed the bot's liquidity check (strategy.min_liquidity_usd) when it looked. A thin market's mid price is a placeholder of a near-empty book (often 0.34 or 0.40), and comparing against it makes any model look better than the market.
- Intervals are 95% bootstrap intervals (2000 resamples, seed 7): returns resample whole market days, log-loss differences resample whole events, because outcomes on one day or one event move together.
- The verdict needs 200+ settled bets, returns above zero, log loss below the market's on liquid markets, a win rate within two standard errors of the predicted one, and a profit without the 5 best bets and in both halves.
- Regenerate with `python main.py research` on the experiment's database.

