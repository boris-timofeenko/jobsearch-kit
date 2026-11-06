#!/bin/bash
# Серверный прогон под systemd. Быстрый режим каждые 2 часа с 08:15 до 22:15 (JOBSEARCH_TZ), deep — в 00:15: ночью
# ему никто не мешает до утреннего прогона. --time-filter задаёт базовое окно (4 ч, утром 10 ч, deep 12 ч); каждый запрос сам
# расширяет его до своего последнего полного поиска (config.yaml: window_margin), так что пропущенный прогон дыры не
# оставляет. flock защищает единственную SQLite-базу от параллельных прогонов; о пропуске из-за долгого предыдущего
# прогона и о падении приходит сообщение в Telegram (ночью без звука).
set -u
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"     # claude CLI (native installer) для LLM-стадии по подписке
set -a; [ -f .env ] && . ./.env; set +a          # TELEGRAM_* и токены для самого прогона и для сообщений об ошибке
export JOBSEARCH_TZ="${JOBSEARCH_TZ:-Europe/Amsterdam}"
MODE="${1:-fast}"
mkdir -p data/logs
LOG="data/logs/$(date +%Y-%m-%d).log"
HOUR=$(TZ="$JOBSEARCH_TZ" date +%H)
SILENT=false; [ "$((10#$HOUR))" -lt 8 ] && SILENT=true      # как telegram.quiet_hours в config.yaml

tg() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || return 0
  curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" -d chat_id="$TELEGRAM_CHAT_ID" \
       -d disable_notification="$SILENT" --data-urlencode "text=$1" >/dev/null || true
}

exec 9>data/.run.lock
if ! flock -n 9; then
  echo "$(date -Is) another run is in progress, skipping ($MODE)" >> "$LOG"
  # the running one wrote its start below; one message per long run (a manual run writes no state, so no message)
  STARTED=""; [ -f data/.run.state ] && read -r STARTED HOLDER < data/.run.state
  if [ -n "$STARTED" ] && [ "$(cat data/.run.alerted 2>/dev/null)" != "$STARTED" ]; then
    echo "$STARTED" > data/.run.alerted
    MIN=$(( ($(date +%s) - STARTED) / 60 ))
    tg "⏳ jobsearch: прогон $MODE пропущен — $HOLDER идёт уже $((MIN / 60)) ч $((MIN % 60)) мин. Следующий прогон сам расширит окно поиска, вакансии не потеряются."
  fi
  exit 0
fi
echo "$(date +%s) $MODE" > data/.run.state

if [ "$MODE" = "deep" ]; then
  ARGS="--deep --time-filter r43200"; LIMIT=7.5h   # 00:15 -> 07:45, до утреннего прогона
elif [ "$HOUR" = "08" ]; then
  ARGS="--time-filter r36000"; LIMIT=3h        # первый прогон после ночной паузы: базовое окно 10 часов
else
  ARGS="--time-filter r14400"; LIMIT=3h
fi
echo "$(date -Is) === run $MODE ===" >> "$LOG"
# Бюджеты в config.yaml заканчивают прогон намного раньше; timeout — на случай зависания. Покрытие поиска пишется
# в базу только вместе с вакансиями, поэтому после остановки следующий прогон захватит пропущенное.
timeout --kill-after=2m "$LIMIT" .venv/bin/python -m jobsearch run $ARGS --notify --report-days 1 >> "$LOG" 2>&1
RC=$?                                      # capture before $(date) clobbers $?
echo "$(date -Is) === exit $RC ===" >> "$LOG"
rm -f data/.run.state
if [ "$RC" != "0" ]; then
  # tell the owner instead of failing silently; last log lines go into the message
  TAIL=$(tail -n 4 "$LOG" | cut -c1-300 | sed "s/[<>&]/ /g")
  WHY="упал с кодом $RC"; [ "$RC" = "124" ] && WHY="остановлен по таймауту $LIMIT"
  tg "⚠️ jobsearch: прогон $MODE $WHY
$TAIL"
fi
# логи старше 30 дней и отчёты старше 60 — в мусор
find data/logs -name '*.log' -mtime +30 -delete 2>/dev/null
find data/reports -type f -mtime +60 -delete 2>/dev/null
