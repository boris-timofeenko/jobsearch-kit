#!/bin/bash
# Плановый прогон на своём компьютере (launchd на Mac, cron на Linux): сбор → эвристики → LLM → отчёт → Telegram.
# Первый прогон дня после 12:00 идёт в режиме --deep (все запросы LinkedIn без потолков и hiring.cafe), остальные
# быстрые. Логи в data/logs/.
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"   # claude CLI для оценки по подписке
set -a; [ -f .env ] && . ./.env; set +a
mkdir -p data/logs
MODE=""
if [ "$(date +%H)" -ge 12 ] && [ "$(cat data/.last-deep 2>/dev/null)" != "$(date +%F)" ]; then
  MODE="--deep"; date +%F > data/.last-deep
fi
exec .venv/bin/python -m jobsearch run --time-filter r86400 --notify $MODE "$@" >> "data/logs/$(date +%F).log" 2>&1
