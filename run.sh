#!/bin/bash
# Schedule with cron: once per hour (Warsaw clock), e.g.
#   CRON_TZ=Europe/Warsaw
#   0 * * * * /opt/polish_news/run.sh
export TZ=Europe/Warsaw
set -a
source /opt/polish_news/.env
set +a
ARGS=()
if [ "$1" = "send-email-digest" ]; then
  ARGS+=(--send-email-digest "$2")
fi

flock -n /tmp/polish_news.lock bash -c '
  start=$(date +%s)
  /opt/polish_news/venv/bin/python /opt/polish_news/main.py "$@" >> /opt/polish_news/bot.log 2>&1
  dur=$(( $(date +%s) - start ))
  if [ "$dur" -gt 300 ]; then
    sleep 300
  fi
' bash "${ARGS[@]}"
