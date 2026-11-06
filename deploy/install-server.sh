#!/bin/bash
# Установка на VPS (Debian 12 / Ubuntu 22.04+), запускается deploy/deploy.sh от root. Идемпотентно.
# Пользователь jobsearch, venv, зависимости, тесты, systemd: прогоны по таймеру и Telegram-бот.
# Дополнительно и только когда нужно: LaTeX (если есть my/cv.tex), Claude CLI (если в .env подписочный токен),
# Chrome под Xvfb для резервного транспорта hiring.cafe (если в .env HC_CHROME=on).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
APP=/opt/jobsearch
cd "$APP"
envval() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }

echo "  пакеты"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync curl sqlite3 >/dev/null
if [ -f my/cv.tex ]; then
  echo "  LaTeX для «CV под вакансию» (~1 ГБ, только первый раз)"
  apt-get install -y -qq --no-install-recommends texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-recommended texlive-fonts-extra texlive-lang-cyrillic >/dev/null
fi
if [ "$(envval HC_CHROME)" = "on" ]; then
  echo "  Chrome + Xvfb для hiring.cafe"
  apt-get install -y -qq --no-install-recommends xvfb xdotool scrot xclip >/dev/null
  [ -x /usr/bin/google-chrome ] || { curl -fsSL -o /tmp/google-chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && apt-get install -y -qq /tmp/google-chrome.deb >/dev/null; }
fi

id -u jobsearch >/dev/null 2>&1 || useradd -m -r -s /bin/bash jobsearch
mkdir -p data/reports data/logs
chown -R jobsearch:jobsearch "$APP"
chmod 600 .env

echo "  Python-окружение и тесты"
sudo -u jobsearch bash -c "cd $APP && { [ -d .venv ] || python3 -m venv .venv; } && .venv/bin/pip install -q --upgrade pip \
  && .venv/bin/pip install -q -r requirements.txt && .venv/bin/python -m pytest -q tests 2>&1 | tail -1"

if [ -n "$(envval CLAUDE_CODE_OAUTH_TOKEN)" ] && [ -z "$(envval ANTHROPIC_API_KEY)" ]; then
  if [ ! -x /home/jobsearch/.local/bin/claude ]; then
    echo "  Claude CLI для оценки по подписке"
    sudo -u jobsearch bash -c "curl -fsSL https://claude.ai/install.sh | bash" >/dev/null
  fi
fi

TZ_NAME="$(envval JOBSEARCH_TZ)"; TZ_NAME="${TZ_NAME:-Europe/Amsterdam}"
echo "  systemd (часовой пояс расписания: $TZ_NAME)"
for u in deploy/jobsearch.service deploy/jobsearch-deep.service deploy/jobsearch-bot.service \
         deploy/jobsearch.timer deploy/jobsearch-deep.timer; do
  sed "s#Europe/Amsterdam#$TZ_NAME#g" "$u" > "/etc/systemd/system/$(basename "$u")"
done
systemctl daemon-reload
systemctl enable --now jobsearch.timer jobsearch-deep.timer >/dev/null 2>&1
if [ -n "$(envval TELEGRAM_BOT_TOKEN)" ]; then
  systemctl enable jobsearch-bot.service >/dev/null 2>&1 && systemctl restart jobsearch-bot.service
fi
sudo -u jobsearch bash -c "cd $APP && PATH=/home/jobsearch/.local/bin:\$PATH .venv/bin/python -m jobsearch check" || true
systemctl list-timers --no-pager | grep jobsearch || true
echo "готово. Первый прогон руками: systemctl start jobsearch.service; лог: tail -f $APP/data/logs/\$(date +%F).log"
