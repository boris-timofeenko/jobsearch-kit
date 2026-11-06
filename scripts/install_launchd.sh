#!/bin/bash
# Расписание на Mac: прогоны в заданные часы и (с --bot) Telegram-бот, который всегда запущен.
#   scripts/install_launchd.sh                 # прогоны в 09:00, 13:00, 18:00
#   scripts/install_launchd.sh 8 12 16 20 --bot
# Снять: scripts/install_launchd.sh --remove
# Папка проекта не должна лежать в ~/Documents, ~/Desktop или ~/Downloads: macOS не даёт launchd читать их, и
# расписание молча падает с «Operation not permitted». Хорошее место — ~/jobsearch.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS=~/Library/LaunchAgents
RUN=local.jobsearch.run
BOT=local.jobsearch.bot
uid=$(id -u)
if [ "${1:-}" = "--remove" ]; then
  for l in $RUN $BOT; do launchctl bootout gui/$uid/$l 2>/dev/null || true; rm -f $AGENTS/$l.plist; done
  echo "снято"; exit 0
fi
case "$DIR" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    echo "проект лежит в $DIR — launchd туда не пускает. Перенеси папку, например: mv \"$DIR\" ~/jobsearch" >&2; exit 1;;
esac
HOURS=(); WITH_BOT=false
for x in "$@"; do [ "$x" = "--bot" ] && WITH_BOT=true || HOURS+=("$x"); done
[ ${#HOURS[@]} -gt 0 ] || HOURS=(9 13 18)
mkdir -p "$AGENTS" "$DIR/data/logs"
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo "<plist version=\"1.0\"><dict><key>Label</key><string>$RUN</string>"
  echo "<key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/scripts/run-local.sh</string></array>"
  echo "<key>StartCalendarInterval</key><array>"
  for h in "${HOURS[@]}"; do echo "<dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>5</integer></dict>"; done
  echo "</array>"
  echo "<key>StandardOutPath</key><string>$DIR/data/logs/launchd.out</string>"
  echo "<key>StandardErrorPath</key><string>$DIR/data/logs/launchd.err</string>"
  echo "</dict></plist>"
} > "$AGENTS/$RUN.plist"
launchctl bootout gui/$uid/$RUN 2>/dev/null || true
launchctl bootstrap gui/$uid "$AGENTS/$RUN.plist"
echo "прогоны: ${HOURS[*]} ч (ноутбук должен быть включён; пропущенный во сне прогон launchd догонит при пробуждении)"
if $WITH_BOT; then
  cat > "$AGENTS/$BOT.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>$BOT</string>
<key>ProgramArguments</key><array><string>$DIR/.venv/bin/python</string><string>-m</string><string>jobsearch</string><string>bot</string></array>
<key>WorkingDirectory</key><string>$DIR</string>
<key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$DIR/data/logs/bot.out</string>
<key>StandardErrorPath</key><string>$DIR/data/logs/bot.err</string>
</dict></plist>
PLIST
  launchctl bootout gui/$uid/$BOT 2>/dev/null || true
  launchctl bootstrap gui/$uid "$AGENTS/$BOT.plist"
  echo "бот запущен (кнопки под карточками работают, пока Mac не спит)"
fi
launchctl list | grep jobsearch
