#!/bin/bash
# Плановый прогон на своём компьютере (launchd на Mac, cron на Linux): сбор → эвристики → LLM → отчёт → Telegram.
# Первый прогон дня после 12:00 идёт в режиме --deep (все запросы LinkedIn без потолков и hiring.cafe), остальные
# быстрые. Логи в data/logs/. Пока идёт один прогон, следующий не стартует (база одна): папка-замок data/.run.lock.d,
# старше 8 часов считается брошенной.
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"   # claude CLI для оценки по подписке
set -a; [ -f .env ] && . ./.env; set +a
mkdir -p data/logs
LOG="data/logs/$(date +%F).log"
LOCK=data/.run.lock.d
find "$LOCK" -maxdepth 0 -mmin +480 -exec rmdir {} \; 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') предыдущий прогон ещё идёт, пропускаю" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK"' EXIT
MODE=""
if [ "$(date +%H)" -ge 12 ] && [ "$(cat data/.last-deep 2>/dev/null)" != "$(date +%F)" ]; then
  MODE="--deep"; date +%F > data/.last-deep
fi
.venv/bin/python -m jobsearch run --time-filter r86400 --notify $MODE "$@" >> "$LOG" 2>&1
