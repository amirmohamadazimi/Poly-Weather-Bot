#!/bin/sh
# Deploy the newest approved version of the bot and restart it (spec section 20).
#
#   sudo deploy/update.sh           the newest commit of main on which CI passed
#   sudo deploy/update.sh v2.1.0    a tag, branch or commit you name instead
#
# It backs up the database, checks the code out, rebuilds and restarts the
# container, and waits for its health check. If a version that was running is
# replaced by one that does not become healthy, it goes back to the old one.
# deploy/wxbot.cron runs it every hour to follow main. docs/deploy.md has the
# whole server guide. PAPER TRADING ONLY: compose forces app.mode = paper.
#
# Everything runs inside main(), so a checkout that changes this file cannot
# change the copy the shell is running.
set -eu

REPO="${WXBOT_REPO:-amirmohamadazimi/Poly-Weather-Bot}"
WAIT="${WXBOT_DEPLOY_WAIT:-1800}"   # seconds to wait for the health check

short() { printf '%.12s' "$1"; }

# the newest push to main whose `tests` workflow (lint, types, tests, build) passed
green_commit() {
  curl -fsS --retry 3 -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/actions/workflows/tests.yml/runs?branch=main&event=push&status=success&per_page=1" |
    python3 -c 'import json, sys; r = json.load(sys.stdin)["workflow_runs"]; print(r[0]["head_sha"] if r else "")'
}

container() { docker compose ps -q wxbot; }

running() { [ -n "$(docker compose ps -q --status running wxbot)" ]; }

up() { WXBOT_GIT_REF="$1" docker compose up -d --build; }

# 0 once the container reports healthy; 1 if it turns unhealthy, keeps
# restarting, or is not healthy within $WAIT seconds
healthy() {
  cid=$(container)
  restarts=$(docker inspect -f '{{.RestartCount}}' "$cid")
  waited=0
  while [ "$waited" -lt "$WAIT" ]; do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")
    case "$status" in
      healthy) return 0 ;;
      unhealthy) return 1 ;;
    esac
    [ "$(docker inspect -f '{{.RestartCount}}' "$cid")" = "$restarts" ] || return 1
    sleep 10
    waited=$((waited + 10))
  done
  return 1
}

main() {
  cd "$(dirname "$0")/.."
  if [ $# -gt 0 ]; then
    if git fetch --quiet origin "$1" 2>/dev/null; then   # a tag, branch or full commit hash
      target=$(git rev-parse "FETCH_HEAD^{commit}")
    else                                                 # e.g. a short commit hash
      git fetch --quiet --tags origin
      target=$(git rev-parse --verify "$1^{commit}")
    fi
  else
    target=$(green_commit)
    if [ -z "$target" ]; then
      echo "error: no commit of main has passed CI; nothing deployed" >&2
      return 1
    fi
    git fetch --quiet origin "$target"
  fi
  if ! git cat-file -e "$target:deploy/update.sh" 2>/dev/null; then
    echo "error: $(short "$target") predates deploy/update.sh; deploying it would stop automatic updates" >&2
    return 1
  fi
  current=$(git rev-parse HEAD)
  was_running=no
  if running; then
    was_running=yes
  fi
  if [ "$target" = "$current" ] && [ "$was_running" = yes ]; then
    echo "already running $(short "$target")"
    return 0
  fi

  deploy/backup.sh "$(short "$current")"
  git checkout --quiet --detach "$target"
  echo "deploying $(short "$target") (was $(short "$current"))"
  up "$target"
  if [ "$was_running" = no ]; then
    # a first start loads observation history and fits the model first (up to
    # about 15 minutes); there is no running version to go back to
    echo "started $(short "$target"); follow the first start with: docker compose logs -f"
    return 0
  fi
  if healthy; then
    echo "deployed $(short "$target")"
    return 0
  fi
  echo "error: $(short "$target") did not become healthy; going back to $(short "$current")" >&2
  docker compose logs --tail 50 wxbot >&2 || true
  git checkout --quiet --detach "$current"
  up "$current"
  return 1
}

main "$@"
exit $?
