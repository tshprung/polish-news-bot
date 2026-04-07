#!/bin/bash
export TZ=Europe/Warsaw
set -a
source /opt/polish_news/.env
set +a
/opt/polish_news/venv/bin/python /opt/polish_news/main.py >> /opt/polish_news/bot.log 2>&1
