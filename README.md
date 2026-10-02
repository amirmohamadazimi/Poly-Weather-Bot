# Polymarket weather paper-trading bot

Prices Polymarket's daily city temperature markets with a calibrated weather
model, compares the model's probability with the market price, and records a
**paper** bet when the price offers enough expected value. It runs unattended,
settles bets when Polymarket resolves the markets, and shows everything on a
local dashboard.

> **Paper trading only.** There is no wallet, no private key and no code that can
> place an order anywhere in this repository. See [Safety boundary](#safety-boundary).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Or with [uv](https://docs.astral.sh/uv/), which installs the exact locked
versions from `uv.lock`: `uv sync` then `uv run python main.py`.

Open <http://localhost:8000>. The bot starts with a virtual $100 and runs a
cycle every 30 minutes. Stop it with Ctrl+C; everything is kept in
`data/wxbot.sqlite3`, so it picks up where it left off on restart.

Recommended before the experiment starts (fits per-station forecast bias and
error from the last 90 days, and reports how well calibrated the model was):

```bash
python main.py backtest
```

Other commands:

| Command | What it does |
|---|---|
| `python main.py` | Dashboard + autonomous loop |
| `python main.py once` | One cycle, print a summary, exit |
| `python main.py worker` | Loop without the dashboard |
| `python main.py web` | Dashboard only (e.g. a second process reading the same DB) |
| `python main.py backtest [--days 90] [--stations EGLC,KLGA]` | Walk-forward forecast backtest, stores calibration |
| `python main.py backtest-markets [report.json] [--days 14 \| --start D --end D] [--stations ...] [--offline]` | Replays closed markets at their historical prices in its own database; prints BACKTEST.md |
| `python main.py calibrate` | Refit the probability calibrators now (each cycle refits once a day) |
| `python main.py report` | End-of-experiment performance report (markdown) |
| `python main.py export [DIR]` | Every table as CSV plus `report.json` |

The dashboard also has **Export everything (zip)**.

## Which markets, and why

Polymarket lists a "Highest temperature in *City* on *Date*?" event (and some
"Lowest temperature" ones) for 20+ cities every day. Each event is a ladder of
yes/no buckets (`16°C`, `17°C`, ..., `25°C or higher`; US cities use 2°F ranges)
resolving on one airport station's reading. These are the best fit for a
one-month experiment:

* **Predictable:** 1–3 day temperature forecasts are among the most skilful
  forecasts there are, and the station is named in the market.
* **Many samples:** dozens of events resolve every day, so a month gives
  hundreds of settled predictions, enough to judge calibration.
* **Fast feedback:** resolved within a day.

## How a bet happens

```
markets (Gamma API) ─┐
forecasts (Open-Meteo, 5 models) ─┼─> prediction ─> calibrated probability ─> signal (rules) ─> paper bet ─> settlement ─> stats
calibration (backtest) ─┘                                                                        (Polymarket resolution)
```

1. **Discover** open `daily-temperature` events. The resolution station is read
   from the market's own resolution source (e.g. `wunderground.com/.../EGLC`);
   markets whose station is not in `wxbot/data/stations.py` are shown but never traded.
   The resolution rules in the market text are checked too (see
   [Resolution criteria](#resolution-criteria)).
2. **Forecast** the station's daily max/min for its local calendar day from five
   Open-Meteo models (ECMWF, GFS, ICON, GEM, JMA).
3. **Predict** with `normal-multimodel-v1`: a normal distribution centred on the
   bias-corrected model mean, with sigma = the larger of the backtest error and
   the models' disagreement. Bucket probability accounts for whole-degree
   reporting. Probabilities are clamped to 1–99%. Two baselines are priced on
   the same inputs but never traded (see [Models and baselines](#models-and-baselines)).
4. **Calibrate** the probability with the approved probability calibrator, if
   there is one (see [Probability calibration](#probability-calibration)).
   Otherwise the model's own probability is used unchanged.
5. **Signal:** pick the better side (YES or NO) and check every rule on the
   calibrated probability. A prediction of 95% is *not* a bet unless the price
   leaves an edge.
6. **Paper bet:** size it, then simulate the fill by walking the real CLOB order
   book (taking at most 25% of each level, plus slippage and fees).
7. **Settle** when Polymarket resolves the market (prices pinned to 1/0).

Every row is insert-only, and the chain bet → signal (with every rule result
and sizing cap) → prediction (with every model input) → forecast snapshot lets
you reconstruct exactly why each bet was made. Click any row in the dashboard to see it.

### Rules (all in `config.toml`)

| Rule | Default |
|---|---|
| Calibrated probability of the side bought (confidence) | ≥ 0.80 |
| Edge = calibrated probability − effective entry price | ≥ 0.05 |
| Expected value per $1 | ≥ 0.04 |
| Entry price | 0.03 – 0.97 |
| Market liquidity | ≥ $300 |
| Time until the end of the local target day | 18 – 96 h |
| Models available / forecast age | ≥ 3 / ≤ 180 min |
| Forecast sigma | ≤ 3.5 °C |
| No existing position in that market | |
| Daily realised loss | < 5% of starting bankroll |

### Data validation

Every forecast value is checked before use (`[validation]` in `config.toml`):
values that are not numbers, outside -70..60 °C, or from a model run more than
36 hours old are rejected and the reason is stored. If fewer than
`min_models` values survive, the snapshot is marked invalid and the
`data_validation` rule blocks any bet. Raw values are kept as fetched, and
`forecast_values` stores each model's value with its run time and horizon, so
a backtest can see exactly what was known when.

### Resolution criteria

Each market's description states what it resolves on, for example
"...contains the highest temperature recorded by NOAA at the London City
Airport Station in degrees Celsius on 28 Sep '26" and "...measures temperatures
to whole degrees Celsius". `parse_criteria` in `wxbot/data/polymarket.py` reads
that text and `check_criteria` compares it with how the bot would price the
market. A market is not traded when:

* the text says highest and the title lowest (or the reverse), or mentions both;
* the text's unit (Celsius/Fahrenheit) differs from the bucket's;
* the text's date differs from the title's date, or cannot be read;
* the precision is not stated as whole degrees of the bucket's unit;
* the resolution link is not a recognised source (NOAA/weather.gov,
  Wunderground, Hong Kong Observatory), or the text names a different source;
* the text and the link name different station codes;
* the rule sentence itself is not recognised, or a second rule sentence (for
  example an appended clarification) says something different.

The reason is stored in `markets.skip_reason` (prefixed `resolution criteria:`)
and the parsed rules in `markets.criteria`; the dashboard shows how many
markets were skipped for this. If Polymarket edits a market's text, the earlier
version is kept in `market_criteria_history`.

Checked against the 7,051 real markets in the running experiment's database
(2026-10-01): all 4,070 that were tradeable stay tradeable, and 6,875 (97.5%)
pass with no problem. The other 176 are all Hong Kong Observatory markets,
which use a different rule sentence and one-decimal precision; that station was
already disabled. `tests/fixtures/` holds verbatim copies of the live wordings
the tests use.

### Market data kept for research

Every cycle stores a snapshot (bid, ask, last trade, YES price, liquidity,
volume) for every market seen, tradeable or not. `markets` keeps the outcomes,
Polymarket's creation time, end and close time, resolution source, description,
parsed criteria and the resolution result. Results are fetched for every
market, tradeable or not.

After a market resolves, its hourly YES price history from creation to close
is fetched once from the CLOB (`/prices-history`) into `market_price_history`
for later backtests. Only points where the price changed are stored (a price
holds until the next point). A fetch that fails or comes back empty is retried
on later cycles, at most 3 times per market; if the CLOB cannot be reached at
all, that cycle's pass stops and resumes next cycle. Either way settlement is
never blocked. Each cycle fetches at most `max_price_histories_per_cycle`
histories (newest markets first) and checks at most
`max_result_checks_per_cycle` results for markets without a bet, so a backlog
is worked off over several cycles. Turn price history off with `[markets]
store_price_history = false`. A backtest using these prices must only read
points with `t` at or before its decision time.

### Models and baselines

Every model sees the same feature set (`wxbot/features.py`, version `fs-v1`):
the models' mean, spread, minimum and maximum, how many models, lead time,
forecast horizon (hours from the oldest model run to the end of the target
day), station, kind, month and day of year, and the station's climatology
(mean and spread of past observations near that date) with the forecast's
anomaly from it. The features are stored with each production prediction.

| Model | Role | What it is |
|---|---|---|
| `normal-multimodel-v1` | production | Bias-corrected model mean, backtest-fitted sigma (above). The only model that trades |
| `raw-forecast-v1` | shadow | The same normal model on the raw model mean, with no station bias correction and the default sigma for the lead time |
| `climatology-v1` | shadow | How often the observed high/low, in whole degrees, fell in the bucket on days within 7 days of the same date in past years. Ignores the forecast; no prediction with fewer than 20 past days |

Shadow models are listed in `[model] shadow_models`. Their predictions are
stored with `role = "shadow"` and never create a signal or a bet. The
`model_versions` table is the registry: each model version, its calibration
version, feature set, parameters and current role (production, shadow or
retired). A version removed from the config is marked retired, never deleted.
Changing a model means giving it a new version.

Climatology needs past observations: `python main.py climatology --years 3`
loads them from the IEM METAR archive (one request per station-year, about
2 minutes for all stations). They are stored as ordinary observations,
fetched at load time, so no prediction uses an observation before it was
loaded.

The report's **Model comparison** scores each model's prediction from the
same cycle as the production model's last prediction made a day or more ahead,
with Brier score and log loss. Each row is compared with the production model
and the market price on exactly the markets that model predicted. On the
running experiment's 1,672 resolved markets (2026-10-01), production scored
Brier 0.0679 and log loss 0.220, the raw forecast replayed on the same stored
inputs 0.0725 and 0.243, and the market price 0.0733 and 0.242.

### Probability calibration

A model can rank outcomes well and still be over- or under-confident: if its
90% predictions come true 80% of the time, every 90% should be read as 80%.
`wxbot/calibration/` learns that map from resolved markets:

* **isotonic**: a non-decreasing step function (pool-adjacent-violators), with
  every step resting on at least 20 markets and the ends pinned to 0 and 1.
* **platt**: `sigmoid(a · logit(p) + b)`, a smooth two-parameter fit.

Each fit uses only what was known at fit time: markets whose result the bot
had recorded, one prediction per market (the latest made at least 18 h before
the end of the target day, as a bet would be). The newest 30% of those markets,
by decision time, are held out. A method is approved only when, on the
holdout, it beats the raw probabilities on **both** Brier score and log loss,
at least 200 markets were available, and the log-loss gain holds in 95% of
2,000 bootstrap resamples of the holdout. The approved method with the lowest
holdout log loss is used until the next fit, a day later. With nothing approved,
the raw probability is used. Every fit is kept in `prob_calibrators`, and every
prediction records the calibrator it used.

Each signal's first rule result shows the model's probability, the calibrated
probability, the calibrator and the market's probability. The report adds log
loss, expected calibration error and reliability bins for the calibrated
probabilities, and the latest fit with its holdout scores.

On the running experiment's data (1,837 resolved markets, 2026-10-01), neither
method passes: isotonic improved log loss slightly (0.2311 → 0.2298) but not
Brier, and won in only 67% of resamples; Platt was worse on Brier. So the raw
probabilities stay in use.

### Sizing and risk

The bankroll starts at a virtual $100. `fixed_fraction` (2% of equity, so $2
per bet at the start) is the default; `fractional_kelly` (quarter Kelly) is
available with `[sizing] method`. Stakes under $1 are not placed. The stake is
then capped by: 2% of equity per bet, 30% total open exposure, 5% per event
(all buckets of one city, day and high/low), 8% per city-day (its high and low
events together, since the same weather decides both), available cash, and the
visible order-book depth. Each bet stores every cap, the one that bound, the
budget and the order-book levels taken (`paper_bets.sizing`), plus the quotes
it traded on (`paper_bets.market_snapshot`).

Equity counts open bets **marked to market**: at the best bid of the side held
in the latest market snapshot (for NO, 1 − the YES ask), which is what selling
it would fetch now. Without a bid the side's last price is used, and without a
snapshot the bet stays at cost. The report lists every open position with its
cost, mark, value and unrealized P/L.

Cash can never go negative: the paper broker refuses, and logs, any fill that
costs more than the cash the ledger holds, is empty, is not a number, or is
priced above $1 a share. A refused fill turns its signal into a NO_BET.

The first start on a database records the experiment in `experiments`: its
name (`[experiment] name`), starting bankroll, start time, code version
(`WXBOT_GIT_REF` or `GITHUB_SHA`) and settings, with passwords and database
credentials removed. The report names it. A database holds one experiment, so
starting it with a different bankroll is refused.

## Evaluation

The dashboard and `python main.py report` show bankroll (cash, open positions
at cost and at the bid, realized and unrealized P/L), P/L, ROI on staked
money with a bootstrap 95% interval, win rate against the win rate the model
predicted, drawdown, and **calibration of every prediction on every resolved
market** (not only the ones bet on) with the market's own Brier score as a
benchmark, log loss and expected calibration error, raw and calibrated, and
the model comparison above. The report states plainly when
there are too few settled bets to conclude anything.

The dashboard (`python main.py web`, http://localhost:8000) has seven tabs:

* **Overview:** starting bankroll, current equity, P/L, ROI and active positions, then cash, realized and unrealized P/L, win rate against the predicted win rate, drawdown.
* **Live markets:** every monitored market with its current YES bid and ask, the forecast, the raw and calibrated probability, the market's probability, entry price, edge, EV, the signal and any open position. Click a row for every rule's value and threshold.
* **Portfolio:** open positions at cost and at the bid, what each would pay if it wins, its largest possible loss and share of equity, and how much of each risk limit (total, per event, per city-day, daily loss) is in use.
* **Bet history:** every paper bet, searchable by city, date, bucket or `#id`, and filtered by status and side.
* **Model performance:** bankroll, P/L, drawdown, wins and losses, calibration (raw and calibrated), model vs market, and Brier score, log loss and accuracy (did the most likely bucket win) by market day for the model and the market, plus the model comparison.
* **Learning:** where the model goes wrong. Every resolved market gets an error class (85% and NO is significant overconfidence; 25% and YES is underestimation), and predictions and bets are broken down by city, lead time, highest or lowest, the bucket's distance from the forecast, probability band, how much the weather models disagreed, distance from the climate normal, liquidity and model version. A group is flagged as a weakness (overconfident, YES too often or too rarely, worse than the market) only with 30+ markets (15+ bets) and a gap of 3+ standard errors, so chance alone rarely flags one; REPORT.md lists the same weaknesses. The largest errors are listed with any bet placed on them.
* **System health:** each data source's last success and status (ok, stale after three missed fetches, failing when its latest warning is newer than its latest success), last market scan and prediction, database size and row counts, the production and shadow models, the calibrator in use and when calibration was last refitted, the experiment and code version, and recent errors.

The dashboard and report always count from the database's own starting
bankroll (its experiment's, or the one its bankroll history implies), so a
downloaded database shows its own numbers whatever the local config says.

There are two backtests.

`backtest` scores the forecast model walk-forward: each day is priced with
bias/sigma fitted only on observations available when that forecast was issued,
using the forecasts each model actually issued 1–3 days ahead (Open-Meteo
Previous Runs API) and METAR observations (Iowa Environmental Mesonet), on a
ladder of synthetic buckets. It also fits the calibration the live model uses.

`backtest-markets` replays real closed Polymarket markets at the prices that
were on offer, using only what was known at each decision time (v2 M8):

* **Decision times.** Lead N uses the forecast each model issued at least N days
  earlier (Previous Runs `previous_dayN`), assumed downloadable 8 hours after
  the run started. The decision is made when that is surely available: 16, 40
  and 64 hours before the end of the market's local day for leads 1 to 3.
* **Prices.** The last hourly CLOB price at or before the decision time. Buying
  costs half a spread (1 cent by default) more, plus the configured slippage and
  fee; ROI is also shown at 0 to 3 cents.
* **Five sources on the same markets:** climatology (the naive baseline), the
  raw forecast, the model with station bias and spread fitted only on days that
  had ended, the model through the calibrator the live approval rule would have
  picked from results already known (refitted daily), and the market price.
  Brier score, log loss and calibration error, with the difference from the
  market and a 95% interval that resamples whole events.
* **The live betting rules** on the same decisions: $1 flat bets (is there an
  edge at all, by lead and side, and with each probability source), and a
  $100 bankroll with the live sizing and every risk cap. Liquidity and
  order-book depth cannot be replayed (Polymarket only shows them after a
  market closed) and are listed as such.
* **Nothing hidden.** Every market listed for the window is stored, so the report
  counts what was not tradeable, had no result or never traded, and every
  decision skipped (not listed yet, no forecast, no price). Every replayed
  decision is kept in `backtest_predictions`.

It keeps its own database (`[backtest] database_url`), so it never mixes with an
experiment, and stores everything it fetches there first: a re-run fetches only
what is missing, and `--offline` replays stored data only. On GitHub, run
**Actions → backtest → Run workflow**; the report shows on the run's summary
page and the database is a downloadable artifact. A 14-day window makes about
one CLOB request per tradeable market, so it takes roughly half an hour.

## Configuration

`config.toml` holds every setting. Any value can be overridden with an
environment variable `WXBOT_<SECTION>__<KEY>`, e.g.
`WXBOT_STRATEGY__MIN_MODEL_PROB=0.85`, `WXBOT_SCHEDULE__CYCLE_MINUTES=15`, or
`WXBOT_CONFIG=/etc/wxbot.toml` for another file.

## Running in the cloud for free (GitHub Actions)

`.github/workflows/paper-trading.yml` runs one cycle every 3 hours on GitHub's
servers, so no computer has to stay on. It starts once this workflow is on the
default branch (`main`). To start immediately, open **Actions → paper-trading →
Run workflow**.

* **State:** the database is kept, gzipped, on the `paper-data` branch. Each
  run restores it, runs `python main.py once`, and pushes it back as a single
  replacement commit, so the repo does not grow. The very first run also fits calibration
  (`backtest --if-missing`, about 10 minutes).
* **Backups:** each run also uploads the database as a workflow artifact, kept for 14 days.
* **Cost:** about 8 runs a day at about 6 minutes each comes to roughly 1,500
  minutes a month, inside the 2,000 free minutes a private repo gets. Change
  the `cron` line to run more or less often. Bets need 18 or more hours of lead
  time, so 3 hours between runs loses very little.

**Seeing results**

* Quickest: open `REPORT.md` on the `paper-data` branch on GitHub (it works on
  a phone). It shows bankroll, P/L, ROI, calibration, results and every bet by
  market day, and the bot's status, and is rewritten every run. The same report appears on each
  run's summary page under Actions.
* Full dashboard: download `wxbot.sqlite3.gz` from the `paper-data` branch
  (open the file on GitHub and click the download button), unzip it (`gunzip
  wxbot.sqlite3.gz`, or 7-Zip on Windows), save it as `data/wxbot.sqlite3` in
  your local copy, and run `python main.py web`. It is stored gzipped because
  GitHub refuses files over 100 MB.
  `web` only reads the data: it never trades or writes to the database, so it
  is safe while the cloud bot keeps running. Or use `python main.py report` / `export`.
* Do not run `python main.py` (the loop) on your own machine at the same time
  unless you want a second, separate experiment.

The scheduled workflow runs experiment 1 from the frozen `exp1-frozen`
branch, not from `main`; see [docs/experiments.md](docs/experiments.md).

`.github/workflows/paper-trading-100.yml` runs experiment 2 ($100) the same
way from `main`, with its state on the `paper-data-100` branch and its runs
offset from experiment 1's. Its first runs also load three years of observed
highs and lows for the climatology baseline. GitHub fires scheduled runs about
every 7–8 hours in practice, so the two experiments together use roughly 1,400
of the 2,000 free minutes a month.

## Running on a server (Phase 2)

```bash
cp .env.example .env        # set a dashboard password
docker compose up -d --build
```

`restart: unless-stopped` brings it back after crashes and reboots, and the
database lives in `./data`. Without Docker, `deploy/wxbot.service` is a systemd
unit. Set `WXBOT_APP__LOG_JSON=true` for one-JSON-object-per-line logs. To use
PostgreSQL, install `psycopg[binary]` and set `WXBOT_APP__DATABASE_URL`.

## Safety boundary

* `app.mode` defaults to `paper`; `PaperBroker` only writes rows to the database.
* `mode = "live"` makes the app refuse to start. It additionally requires
  `WXBOT_I_UNDERSTAND_LIVE_TRADING_USES_REAL_MONEY=yes`, and even then
  `LiveBroker` raises because it is deliberately not implemented
  (`wxbot/execution/live.py`). Tests check both.
* The Polymarket client only issues public GET requests.

## Project layout

```
main.py                     CLI entry point
config.toml                 all settings
wxbot/data/                 Polymarket, Open-Meteo, METAR clients; station table
wxbot/model/                predictor interface, normal multi-model v1, baselines, registry
wxbot/features.py           the feature set every model sees
wxbot/calibration/          isotonic and Platt probability calibration, walk-forward fit and approval
wxbot/history.py            loads past observations for the climatology baseline
wxbot/strategy/             betting rules, fill simulation, sizing
wxbot/execution/            paper broker (cash check), bankroll ledger and mark-to-market, live-trading guard
wxbot/experiment.py         records which experiment a database holds
wxbot/evaluation/           metrics (ROI, drawdown, Brier, log loss, ECE, model comparison), error analysis
wxbot/health.py             data-source, database and model status for the dashboard
wxbot/engine.py             one cycle: collect -> predict -> bet -> settle
wxbot/runner.py             background loop
wxbot/backtest.py           walk-forward forecast backtest + calibration fit
wxbot/backtesting/          market backtest: collect, replay with no look-ahead, evaluate, BACKTEST.md
wxbot/web/                  dashboard (FastAPI + one HTML page)
tests/                      offline tests (no network)
```

Run the tests with `pip install -r requirements-dev.txt && pytest` (or `uv run pytest`).

## Documentation

* [docs/architecture.md](docs/architecture.md): the pipeline stages and where each lives
* [docs/database.md](docs/database.md): every table and what one row means
* [docs/experiments.md](docs/experiments.md): running experiments and how to reproduce them
* [docs/roadmap.md](docs/roadmap.md): v2 gap analysis and milestone plan

## Known limitations (v1)

* Hong Kong resolves on the Observatory's 0.1 °C reading; bucket edges are not
  yet verified, so it is disabled. Other stations can be added in `stations.py`.
* METAR hourly reports can miss a short peak between reports; Weather
  Underground uses the same reports, so this mostly cancels out.
