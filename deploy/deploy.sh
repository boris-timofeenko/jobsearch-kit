#!/bin/bash
# Выложить проект на свой VPS и (пере)установить: код, my/ и .env копируются rsync'ом, база data/ на сервере не
# трогается. Повторный запуск = обновление (после `git pull`).
#
#   deploy/deploy.sh root@203.0.113.10            # ключ по умолчанию из ~/.ssh
#   SSH_KEY=~/.ssh/id_ed25519_vps deploy/deploy.sh root@203.0.113.10
#
# Нужен root (или пользователь с sudo без пароля): ставятся пакеты и systemd-юниты. Сам поиск работает от
# отдельного пользователя jobsearch в /opt/jobsearch.
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:?укажи адрес: deploy/deploy.sh root@<ip>}"
SSH_OPTS=(-o ConnectTimeout=15)
[ -n "${SSH_KEY:-}" ] && SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)

[ -f my/profile.yaml ] || { echo "нет my/profile.yaml — сначала настрой профиль (docs/SETUP.md)" >&2; exit 1; }
[ -f .env ] || { echo "нет .env — скопируй .env.example и заполни токены" >&2; exit 1; }

echo "→ проверка SSH: $TARGET"
ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$TARGET" true || { echo "нет SSH-доступа к $TARGET по ключу" >&2; exit 1; }

echo "→ копирую проект в /opt/jobsearch"
ssh "${SSH_OPTS[@]}" "$TARGET" "command -v rsync >/dev/null || (apt-get update -qq && apt-get install -y -qq rsync >/dev/null); mkdir -p /opt/jobsearch"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .venv --exclude data --exclude '__pycache__' --exclude .pytest_cache \
  --exclude 'extension/node_modules' --exclude 'extension/web-ext-artifacts' --exclude .DS_Store \
  ./ "$TARGET":/opt/jobsearch/

echo "→ установка на сервере"
ssh "${SSH_OPTS[@]}" "$TARGET" "bash /opt/jobsearch/deploy/install-server.sh"
