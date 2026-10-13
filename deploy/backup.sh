#!/bin/sh
# Save a consistent copy of the SQLite database to backups/, safe while the bot
# is running, and keep the newest $WXBOT_BACKUPS_KEEP (default 7).
#
#   sudo deploy/backup.sh [label]     e.g. the code version it was running
#
# deploy/update.sh runs it before every deploy and deploy/wxbot.cron once a
# day. To restore one, see docs/deploy.md ("Backups").
set -eu

KEEP="${WXBOT_BACKUPS_KEEP:-7}"

main() {
  cd "$(dirname "$0")/.."
  db=data/wxbot.sqlite3
  if [ ! -f "$db" ]; then
    echo "no database at $db yet; nothing to back up"
    return 0
  fi
  mkdir -p backups
  out="backups/wxbot-$(date -u +%Y%m%dT%H%M%SZ)${1:+-$1}.sqlite3"
  # SQLite's online backup: a consistent copy even while the bot writes
  python3 -c 'import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()' "$db" "$out"
  gzip -9 "$out"
  # keep the newest $KEEP (names this script made: no spaces)
  # shellcheck disable=SC2012
  ls -1t backups/wxbot-*.sqlite3.gz | tail -n +"$((KEEP + 1))" | xargs -r rm -f
  echo "backed up the database to $out.gz"
}

main "$@"
exit $?
