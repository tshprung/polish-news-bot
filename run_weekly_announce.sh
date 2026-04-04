#!/bin/bash
# Schedule with cron (Jerusalem time), e.g. Sunday 18:00:
#   CRON_TZ=Asia/Jerusalem
#   0 18 * * 0 /opt/polish_news/run_weekly_announce.sh
set -a
source /opt/polish_news/.env
set +a
/opt/polish_news/venv/bin/python /opt/polish_news/weekly_announce.py >> /opt/polish_news/bot.log 2>&1
