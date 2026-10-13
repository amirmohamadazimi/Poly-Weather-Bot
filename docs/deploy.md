# Running on a server

This runs the bot on a VPS around the clock, so no personal computer has to
stay on (spec section 20). The server follows `main` the way experiment 2
does: it only ever runs a commit on which CI passed ([ci.md](ci.md)).

```
GitHub (main, CI passed) ──> deploy/update.sh on the server ──> Docker container
                                                                  ├─ database (./data)
                                                                  ├─ prediction engine + paper trader (the loop)
                                                                  └─ dashboard (:8000)
```

PAPER TRADING ONLY. Compose and the image force `app.mode = paper`, and the
bot needs no API keys or wallet: every source it uses is public.

## 1. A server

Any small Linux VPS works: 1 vCPU and 1–2 GB of memory are enough. Disk is
what to size: every cycle stores each open market's prediction and decision,
about 7 MB (measured on experiment 2's database). At the default 30-minute
cycle that is roughly 350 MB a day, about 10 GB a month; at the three-hour
pace of the Actions experiments it is about 55 MB a day. So use 40 GB of disk
at the default pace, or set `WXBOT_SCHEDULE__CYCLE_MINUTES=180` and 15 GB is
plenty. These steps assume Ubuntu 24.04 and a user with `sudo`.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
```

## 2. Install the bot

```bash
sudo git clone https://github.com/amirmohamadazimi/Poly-Weather-Bot /opt/Poly-Weather-Bot
cd /opt/Poly-Weather-Bot
sudo cp .env.example .env
sudo nano .env                 # set WXBOT_APP__DASHBOARD_PASSWORD; see the comments for the rest
sudo deploy/update.sh
```

`deploy/update.sh` finds the newest commit of `main` that passed CI, checks it
out, builds the image and starts it. The first start takes 10 to 15 minutes:
it loads three years of observed highs and lows and fits the station
bias/spread on 90 days of past forecasts before the dashboard comes up. Follow
it with `sudo docker compose logs -f`.

Settings go in `.env`, never in `config.toml` or other tracked files: a
deploy checks out a clean copy of the code, and changes to tracked files stop
it.

## 3. Open the dashboard

The dashboard listens on the server itself only (`127.0.0.1:8000`). The safest
way to see it is an SSH tunnel from your own computer:

```bash
ssh -L 8000:localhost:8000 you@your-server     # then open http://localhost:8000
```

To reach it directly instead, set `WXBOT_DASHBOARD_BIND=0.0.0.0` and a
dashboard password in `.env`, then apply it with `sudo docker compose up -d`
(the way to apply any change to `.env`). Docker's published ports bypass
`ufw`, so the password is what protects it.

## 4. Keep it updated

```bash
sudo cp deploy/wxbot.cron /etc/cron.d/wxbot
```

Every hour this runs `deploy/update.sh`: when a newer commit of `main` has
passed CI it backs up the database, rebuilds, restarts, and waits for the
health check. If the new version does not become healthy within 30 minutes
(`WXBOT_DEPLOY_WAIT`), it goes back to the version that was running. Once a
day it also makes a database backup. Its log is `/var/log/wxbot-deploy.log`.

To run a particular version instead (a tag, a branch or a commit):

```bash
sudo deploy/update.sh v2.1.0
```

Remove `/etc/cron.d/wxbot` first, or the next hourly run moves the server back
to the newest green commit of `main`.

Versions from before `deploy/update.sh` existed are refused, since deploying
one would stop the automatic updates.

## 5. Everyday commands

Run these in `/opt/Poly-Weather-Bot`:

| What | Command |
|---|---|
| Status | `sudo docker compose ps` (the health column) and `curl -s localhost:8000/healthz` |
| Logs | `sudo docker compose logs -f --tail 100` |
| Report | `sudo docker compose exec -u wxbot wxbot python main.py report` |
| Retrain now / roll back the model | `sudo docker compose exec -u wxbot wxbot python main.py retrain` / `... rollback` |
| Export tables to CSV | `sudo docker compose exec -u wxbot wxbot python main.py export data/exports` |
| Restart | `sudo docker compose restart` |
| Stop | `sudo docker compose down` |

Run commands as `-u wxbot`, the user the bot runs as: a command run as root
can leave database files the bot cannot write. The container restarts itself
after a crash and after a reboot, and its logs are capped at five 10 MB files.

## Backups

`backups/` holds compressed copies of the database: one before every deploy
(named after the version that was running) and one a day, the newest 7 kept
(`WXBOT_BACKUPS_KEEP`). They are SQLite online backups, so they are consistent
even while the bot is writing, and compress about 12 to 1.
`sudo deploy/backup.sh` makes one now.

To restore one:

```bash
sudo docker compose down
sudo sh -c 'gunzip -c backups/wxbot-YYYYMMDDTHHMMSSZ-....sqlite3.gz > data/wxbot.sqlite3'
sudo rm -f data/wxbot.sqlite3-wal data/wxbot.sqlite3-shm
sudo docker compose up -d
```

Copy `backups/` off the server now and then (for example with `rsync` or
`scp`); a backup on the same disk does not survive losing the server.

## Moving experiment 2 from GitHub Actions to the server

Experiment 2 ($100) runs on GitHub Actions and keeps its database on the
`paper-data-100` branch. To move it, run these steps in order, so the two
never run the experiment at the same time:

1. On GitHub, open **Actions → paper-trading-100 → ⋯ → Disable workflow**,
   and wait until no run is in progress.
2. On the server, before the first start (or after `sudo docker compose
   down`), put that database in place:

   ```bash
   cd /opt/Poly-Weather-Bot
   sudo git fetch origin paper-data-100
   sudo mkdir -p data && sudo rm -f data/wxbot.sqlite3-wal data/wxbot.sqlite3-shm
   sudo sh -c 'git show FETCH_HEAD:wxbot.sqlite3.gz | gunzip > data/wxbot.sqlite3'
   ```

   This replaces any database the server already started, so back that up
   first if it matters (`sudo deploy/backup.sh`).

3. Add the experiment's settings to `.env`. Actions schedules a cycle every
   three hours (and GitHub often starts them late); keep that pace so the
   experiment stays comparable:

   ```bash
   WXBOT_EXPERIMENT__NAME=exp2-100usd
   WXBOT_BANKROLL__INITIAL=100
   WXBOT_SCHEDULE__CYCLE_MINUTES=180
   ```

4. `sudo deploy/update.sh`. The report then comes from
   `sudo docker compose exec -u wxbot wxbot python main.py report`; the
   `paper-data-100` branch stops changing.

Experiment 1 ($1,000) stays on Actions: it runs its frozen code from the
`exp1-frozen` branch.

## Without Docker

`deploy/wxbot.service` is a systemd unit for a plain virtualenv install:

```bash
sudo useradd --system --create-home wxbot
sudo git clone https://github.com/amirmohamadazimi/Poly-Weather-Bot /opt/Poly-Weather-Bot
cd /opt/Poly-Weather-Bot
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo chown -R wxbot:wxbot /opt/Poly-Weather-Bot
sudo cp deploy/wxbot.service /etc/systemd/system/ && sudo systemctl enable --now wxbot
```

It does the same first-start setup as the image and forces paper mode. Its
dashboard listens on `127.0.0.1` unless `.env` sets `WXBOT_APP__HOST=0.0.0.0`.
`deploy/update.sh` and the cron file are for the Docker setup; without Docker,
update with `git pull` and `sudo systemctl restart wxbot`.

## Settings

Everything is an environment variable in `.env` (see `.env.example`); nothing
secret is in the repository.

| Kind | Variables |
|---|---|
| Dashboard | `WXBOT_DASHBOARD_BIND`, `WXBOT_APP__DASHBOARD_PASSWORD` |
| Database | `WXBOT_APP__DATABASE_URL` (SQLite in `./data` by default; PostgreSQL works) |
| Runtime | `WXBOT_SCHEDULE__CYCLE_MINUTES`, `WXBOT_APP__LOG_JSON`, `WXBOT_APP__LOG_LEVEL`, `WXBOT_BOOTSTRAP` |
| Experiment | `WXBOT_EXPERIMENT__NAME`, `WXBOT_BANKROLL__INITIAL` |
| Model | `WXBOT_LEARNING__ENABLED` and any other `[learning]` or `[model]` key |
| Deploys | `WXBOT_DEPLOY_WAIT`, `WXBOT_BACKUPS_KEEP`, `WXBOT_REPO` (for the scripts, set in the shell or the cron file) |
| API credentials | none: every source is public |
| Notifications | none yet |
