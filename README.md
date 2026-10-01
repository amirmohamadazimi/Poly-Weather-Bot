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

Open <http://localhost:8000>. The bot starts with a virtual $1,000 and runs a
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
forecasts (Open-Meteo, 5 models) ─┼─> prediction ─> signal (rules) ─> paper bet ─> settlement ─> stats
calibration (backtest) ─┘                                               (Polymarket resolution)
```

1. **Discover** open `daily-temperature` events. The resolution station is read
   from the market's own resolution source (e.g. `wunderground.com/.../EGLC`);
   markets whose station is not in `wxbot/data/stations.py` are shown but never traded.
2. **Forecast** the station's daily max/min for its local calendar day from five
   Open-Meteo models (ECMWF, GFS, ICON, GEM, JMA).
3. **Predict** with `normal-multimodel-v1`: a normal distribution centred on the
   bias-corrected model mean, with sigma = the larger of the backtest error and
   the models' disagreement. Bucket probability accounts for whole-degree
   reporting. Probabilities are clamped to 1–99%.
4. **Signal:** pick the better side (YES or NO) and check every rule. A prediction
   of 95% is *not* a bet unless the price leaves an edge.
5. **Paper bet:** size it, then simulate the fill by walking the real CLOB order
   book (taking at most 25% of each level, plus slippage and fees).
6. **Settle** when Polymarket resolves the market (prices pinned to 1/0).

Every row is insert-only, and the chain bet → signal (with every rule result
and sizing cap) → prediction (with every model input) → forecast snapshot lets
you reconstruct exactly why each bet was made. Click any row in the dashboard to see it.

### Rules (all in `config.toml`)

| Rule | Default |
|---|---|
| Model probability of the side bought (confidence) | ≥ 0.80 |
| Edge = model probability − effective entry price | ≥ 0.05 |
| Expected value per $1 | ≥ 0.04 |
| Entry price | 0.03 – 0.97 |
| Market liquidity | ≥ $300 |
| Time until the end of the local target day | 18 – 96 h |
| Models available / forecast age | ≥ 3 / ≤ 180 min |
| Forecast sigma | ≤ 3.5 °C |
| No existing position in that market | |
| Daily realised loss | < 5% of starting bankroll |

### Sizing and risk

`fixed_fraction` (1% of equity) by default; `fractional_kelly` (quarter Kelly) is
available with `[sizing] method`. The stake is then capped by: 2% of equity per
bet, 30% total open exposure, 5% per city-day event, available cash, and the
visible order-book depth.

## Evaluation

The dashboard and `python main.py report` show bankroll, P/L, ROI on staked
money with a bootstrap 95% interval, win rate against the win rate the model
predicted, drawdown, and **calibration of every prediction on every resolved
market** (not only the ones bet on) with the market's own Brier score as a
benchmark. The report states plainly when there are too few settled bets to
conclude anything.

The backtest scores the forecast model walk-forward: each day is priced with
bias/sigma fitted only on observations available when that forecast was issued,
using the forecasts each model actually issued 1–3 days ahead (Open-Meteo
Previous Runs API) and METAR observations (Iowa Environmental Mesonet).
Historical market prices are not replayed in v1, so the backtest measures
forecast skill and calibration; the paper run measures P/L at real prices.

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
  a phone). It shows bankroll, P/L, ROI, calibration, the latest 30 bets and
  the bot's status, and is rewritten every run. The same report appears on each
  run's summary page under Actions.
* Full dashboard: download `wxbot.sqlite3.gz` from the `paper-data` branch
  (open the file on GitHub and click the download button), unzip it (`gunzip
  wxbot.sqlite3.gz`, or 7-Zip on Windows), save it as `data/wxbot.sqlite3` in
  your local copy, and run `python main.py web`. It is stored gzipped because
  GitHub refuses files over 100 MB.
  `web` only reads the data and never trades, so it is safe while the
  cloud bot keeps running. Or use `python main.py report` / `export`.
* Do not run `python main.py` (the loop) on your own machine at the same time
  unless you want a second, separate experiment.

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
wxbot/model/                predictor interface + normal multi-model v1
wxbot/strategy/             betting rules, fill simulation, sizing
wxbot/execution/            paper broker, bankroll ledger, live-trading guard
wxbot/evaluation/           metrics (ROI, drawdown, Brier, calibration)
wxbot/engine.py             one cycle: collect -> predict -> bet -> settle
wxbot/runner.py             background loop
wxbot/backtest.py           walk-forward backtest + calibration fit
wxbot/web/                  dashboard (FastAPI + one HTML page)
tests/                      offline tests (no network)
```

Run the tests with `pip install -r requirements-dev.txt && pytest`.

## Known limitations (v1)

* Hong Kong resolves on the Observatory's 0.1 °C reading; bucket edges are not
  yet verified, so it is disabled. Other stations can be added in `stations.py`.
* METAR hourly reports can miss a short peak between reports; Weather
  Underground uses the same reports, so this mostly cancels out.
* Open bets are valued at cost until they settle (no mark-to-market).
