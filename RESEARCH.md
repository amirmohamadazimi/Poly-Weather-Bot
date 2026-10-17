# Research report: exp3-v3-100usd

**Interim** (day 2 of 30). Mode: **PAPER TRADING**, real money used: **$0.00**.

Window: 2026-10-15 18:50 to 2026-11-14 18:50 UTC · 30 days · code ba8aea21905d · generated 2026-10-17 12:17 UTC

## Verdict

**NOT SUPPORTED: the model's probabilities were reliably worse than the market's prices, so there is no edge to bet on.**

| Check | Result | Evidence |
|---|---|---|
| Enough settled bets | fail | 0 settled; 200 needed before a profit or loss means much |
| Returns above zero | fail | ROI on stakes n/a; an interval needs 5+ market days with settled bets |
| Better than the market | fail | log loss 0.2189 vs the market's 0.1705 on 252 liquid markets; difference 0.0484 (95% interval 0.0172 to 0.0807, resampling 30 events; below zero is better) |
| Bets won as often as predicted | fail | no settled bets yet |
| Profit not resting on a few bets | fail | P/L $0.00; without the 5 best bets $0.00; first half $0.00, second half $0.00 |

Success needs every check, not a positive P/L alone (spec section 17).

## Performance

| Metric | Value |
|---|---:|
| Starting bankroll | $100.00 |
| Ending bankroll | $100.00 |
| Total P/L | $0.00 |
| Return on the starting bankroll | 0.0% |
| ROI on settled stakes | n/a |
| Bets (settled / open) | 0 (0 / 0) |
| Win rate (predicted) | n/a (n/a) |
| Average bet | n/a |
| Average edge (probability minus price) | n/a |
| Average predicted probability | n/a |
| Average entry price | n/a |
| Brier score / log loss of the bets | n/a / n/a |
| Calibration error of the bets (ECE) | n/a |
| Maximum drawdown | $0.00 (0.0%) |

## Predictions

Every resolved market the model predicted, and the 252 liquid ones (a market price, and enough liquidity to pass the bot's own check before betting), where the market's price is a real forecast to compare against. Lower is better for every score; skill is the share of the market's log loss the model avoided.

| Score | Model | Raw model | Market |
|---|---:|---:|---:|
| Log loss, all 440 markets | 0.2275 | 0.2275 | |
| Brier score, all markets | 0.0681 | 0.0681 | |
| Calibration error (ECE), all markets | 1.7% | | |
| Log loss, 252 liquid markets | 0.2189 | | 0.1705 |
| Brier score, liquid markets | 0.0669 | | 0.0542 |
| Calibration error (ECE), liquid markets | 3.6% | | 1.8% |
| Skill against the market | -28.4% | | |

## Was the edge stable?

P/L $0.00. The 5 best bets made $0.00; without them the rest made $0.00 (ROI n/a).

| Period | Bets | Staked | P/L | ROI |
|---|---:|---:|---:|---:|
| First half (from 2026-10-15) | 0 | $0.00 | $0.00 | n/a |
| Second half (from 2026-10-16) | 0 | $0.00 | $0.00 | n/a |

## Market types

| Bets on | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|

| Predictions on | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high, or above | 20 | 0.0837 | 0.0269 | 20 | 0.0837 | 0.0400 | -109.0% |
| high, or below | 20 | 0.0128 | 0.0002 | 20 | 0.0128 | 0.0097 | -31.7% |
| high, range | 180 | 0.2711 | 0.0826 | 180 | 0.2711 | 0.1977 | -37.2% |
| low, or above | 20 | 0.0101 | 0.0001 | 8 | 0.0101 | 0.0056 | -78.2% |
| low, or below | 20 | 0.0728 | 0.0177 | 1 | 0.0101 | 0.0070 | -43.1% |
| low, range | 180 | 0.2651 | 0.0789 | 23 | 0.1887 | 0.2755 | 31.5% |

| Side | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|

## Locations

By P/L of bets: too few groups with 5+ to rank.

By skill against the market: best Madrid (31.3%), Toronto (30.8%), Atlanta (15.0%); worst Dallas (-130.9%), Austin (-111.9%), Chicago (-84.0%).

| City | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|

| City | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ankara | 22 | 0.2092 | 0.0651 | 11 | 0.2063 | 0.1337 | -54.3% |
| Atlanta | 22 | 0.2228 | 0.0720 | 11 | 0.1614 | 0.1898 | 15.0% |
| Austin | 22 | 0.2875 | 0.0891 | 11 | 0.3360 | 0.1585 | -111.9% |
| Buenos Aires | 22 | 0.2707 | 0.0810 | 11 | 0.3343 | 0.3873 | 13.7% |
| Chicago | 22 | 0.3351 | 0.0986 | 11 | 0.4198 | 0.2281 | -84.0% |
| Dallas | 22 | 0.2821 | 0.0785 | 11 | 0.4190 | 0.1815 | -130.9% |
| Houston | 22 | 0.1159 | 0.0316 | 12 | 0.1486 | 0.1303 | -14.0% |
| London | 22 | 0.1407 | 0.0431 | 21 | 0.1135 | 0.1106 | -2.6% |
| Los Angeles | 22 | 0.2768 | 0.0890 | 12 | 0.2605 | 0.1454 | -79.2% |
| Madrid | 22 | 0.1417 | 0.0419 | 16 | 0.1172 | 0.1706 | 31.3% |
| Mexico City | 22 | 0.1811 | 0.0585 | 11 | 0.1656 | 0.1489 | -11.2% |
| Miami | 22 | 0.1810 | 0.0593 | 16 | 0.2377 | 0.1781 | -33.4% |
| Milan | 22 | 0.3875 | 0.0993 | 11 | 0.2482 | 0.1943 | -27.8% |
| Munich | 22 | 0.2404 | 0.0740 | 11 | 0.2762 | 0.2606 | -6.0% |
| NYC | 22 | 0.1728 | 0.0541 | 14 | 0.1532 | 0.1478 | -3.7% |
| San Francisco | 22 | 0.1755 | 0.0532 | 12 | 0.1847 | 0.1910 | 3.3% |
| Sao Paulo | 22 | 0.2721 | 0.0862 | 12 | 0.2722 | 0.1546 | -76.0% |
| Seattle | 22 | 0.3644 | 0.0952 | 12 | 0.2139 | 0.1349 | -58.6% |
| Toronto | 22 | 0.0959 | 0.0290 | 11 | 0.0119 | 0.0173 | 30.8% |
| Warsaw | 22 | 0.1969 | 0.0635 | 15 | 0.2419 | 0.2011 | -20.3% |

## Weather variables

Which was more predictable: the day's highest or lowest temperature.

| Variable | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| high | 220 | 0.2306 | 0.0701 | 220 | 0.2306 | 0.1662 | -38.7% |
| low | 220 | 0.2244 | 0.0661 | 32 | 0.1384 | 0.1996 | 30.7% |

## Over- and underconfidence

The model's probability in bands against how often the outcome happened. A band is flagged when the gap is two standard errors or more.

| Predicted | Markets | Predicted mean | Happened | Standard errors | Reading |
|---|---:|---:|---:|---:|---|
| 0.0–0.1 | 303 | 2.0% | 2.0% | +0.0 |  |
| 0.1–0.2 | 48 | 14.8% | 18.8% | +0.8 |  |
| 0.2–0.3 | 40 | 24.6% | 20.0% | -0.7 |  |
| 0.3–0.4 | 36 | 34.6% | 33.3% | -0.2 |  |
| 0.4–0.5 | 10 | 43.5% | 20.0% | -1.5 |  |
| 0.5–0.6 | 1 | 51.6% | 100.0% | +1.0 |  |
| 0.6–0.7 | 1 | 70.0% | 100.0% | +0.7 |  |
| 0.9–1.0 | 1 | 97.9% | 100.0% | +0.1 |  |

| Bets at entry price | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|

## Largest errors

The ten predictions with the highest log loss. The market's price is shown for liquid markets only.

| Day | City | Variable | Bucket | Model | Market | Outcome | Bet | Log loss |
|---|---|---|---|---:|---:|---|---|---:|
| 2026-10-16 | Milan | low | 14°C | 1.0% | illiquid | YES | – | 4.61 |
| 2026-10-16 | Seattle | low | 46–47°F | 1.5% | illiquid | YES | – | 4.23 |
| 2026-10-16 | Chicago | high | 56–57°F | 3.4% | 21.5% | YES | – | 3.39 |
| 2026-10-16 | Dallas | high | 66–67°F | 3.5% | 30.5% | YES | – | 3.36 |
| 2026-10-16 | Buenos Aires | high | 15°C | 7.6% | 4.5% | YES | – | 2.58 |
| 2026-10-16 | Austin | high | 74–75°F | 7.6% | 35.0% | YES | – | 2.58 |
| 2026-10-16 | Sao Paulo | high | 27°C | 10.5% | 34.5% | YES | – | 2.26 |
| 2026-10-16 | Los Angeles | high | 98–99°F | 12.5% | 37.5% | YES | – | 2.08 |
| 2026-10-16 | Atlanta | low | 58–59°F | 12.9% | illiquid | YES | – | 2.05 |
| 2026-10-16 | Munich | high | 20°C | 13.2% | 16.0% | YES | – | 2.03 |

## Model versions

Model · station bias/spread set · probability calibrator.

| Version | Markets | Log loss | Brier | Liquid markets | Log loss: model | market | Skill vs market |
|---|---:|---:|---:|---:|---:|---:|---:|
| weighted-multimodel-v1 · bias-sigma-20261015-backtest-run1 · identity | 440 | 0.2275 | 0.0681 | 252 | 0.2189 | 0.1705 | -28.4% |

| Version | Bets | Settled | Won | Predicted | P/L | ROI |
|---|---:|---:|---:|---:|---:|---:|

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

## How this was computed

- Window: bets placed and predictions made up to the experiment's planned end. Predictions are each resolved market's decision prediction (the last made a day or more ahead), from the learning ledger.
- The market comparison uses liquid markets only: those with a price that passed the bot's liquidity check (strategy.min_liquidity_usd) when it looked. A thin market's mid price is a placeholder of a near-empty book (often 0.34 or 0.40), and comparing against it makes any model look better than the market.
- Intervals are 95% bootstrap intervals (2000 resamples, seed 7): returns resample whole market days, log-loss differences resample whole events, because outcomes on one day or one event move together.
- The verdict needs 200+ settled bets, returns above zero, log loss below the market's on liquid markets, a win rate within two standard errors of the predicted one, and a profit without the 5 best bets and in both halves.
- Regenerate with `python main.py research` on the experiment's database.

