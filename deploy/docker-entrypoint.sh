#!/bin/sh
# Container start (Dockerfile ENTRYPOINT). PAPER TRADING ONLY.
#
# 1. As root: make the data directory (a bind mount may be root-owned on the
#    host) writable by the unprivileged `wxbot` user, then re-run this script
#    as that user. The bot itself never runs as root.
# 2. For the bot (`run` or `worker`): on a new database, load the observation
#    history for the climatology baseline and fit the first station
#    bias/spread set, as the GitHub Actions experiment does on its first run.
#    Both skip themselves once done. If the weather archives cannot be reached
#    the step is skipped rather than retried for every station, so the bot
#    still starts; it runs again at the next start. WXBOT_BOOTSTRAP=false
#    skips it.
# 3. Start `python main.py` with the container's command (default: run).
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data
  chown -R wxbot:wxbot /app/data
  exec setpriv --reuid=wxbot --regid=wxbot --init-groups "$0" "$@"
fi

case "${1:-run}" in
  run|worker)
    if [ "${WXBOT_BOOTSTRAP:-true}" = "false" ]; then
      :
    elif ! python -c "import requests; from wxbot.data.weather import IEM_ASOS, PREVIOUS_RUNS; [requests.get(u, timeout=10) for u in (IEM_ASOS, PREVIOUS_RUNS)]" 2>/dev/null; then
      echo "warning: the weather archives are unreachable; first-start setup skipped until the next start" >&2
    else
      python main.py climatology --if-missing --years 3 \
        || echo "warning: observation history did not load; it is retried at the next start" >&2
      python main.py backtest --if-missing \
        || echo "warning: the first bias/spread fit failed; default spreads are used until it succeeds" >&2
    fi
    ;;
esac

exec python main.py "$@"
