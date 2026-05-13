#!/bin/bash
# Schedule with cron: once per hour (Warsaw clock), e.g.
#   CRON_TZ=Europe/Warsaw
#   0 * * * * /opt/polish_news/run.sh
export TZ=Europe/Warsaw
set -a
source /opt/polish_news/.env
set +a
ARGS=()
MODE="hourly"
if [ "$1" = "send-email-digest" ]; then
  ARGS+=(--send-email-digest "$2")
  MODE="digest"
fi

FLOCK_ARGS=(-n)
if [ "$MODE" = "digest" ]; then
  FLOCK_ARGS=(-w 1200)
fi

flock "${FLOCK_ARGS[@]}" /tmp/polish_news.lock bash -c '
  start=$(date +%s)
  /opt/polish_news/venv/bin/python /opt/polish_news/main.py "$@" >> /opt/polish_news/bot.log 2>&1
  dur=$(( $(date +%s) - start ))
  if [ "$dur" -gt 300 ]; then
    sleep 300
  fi
' bash "${ARGS[@]}"

if [ "$?" -ne 0 ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR run.sh: could not acquire lock (/tmp/polish_news.lock) mode=$MODE" >> /opt/polish_news/bot.log
fi
