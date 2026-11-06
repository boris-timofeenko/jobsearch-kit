#!/usr/bin/env bash
# Signed .xpi for release Firefox (permanent install): uploads the code to addons.mozilla.org as an unlisted add-on
# (not shown in the catalogue), waits for the automatic review and saves the signed file to web-ext-artifacts/.
# Keys: addons.mozilla.org → Developer Hub → Tools → Manage API Keys; put them into the project's .env as
#   AMO_JWT_ISSUER=user:…   AMO_JWT_SECRET=…
# AMO accepts every version once, so a version that was already signed is bumped (0.1.0 → 0.1.1) before upload.
set -euo pipefail
cd "$(dirname "$0")"

env_value() { grep -E "^$1=" ../.env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
export WEB_EXT_API_KEY="${AMO_JWT_ISSUER:-$(env_value AMO_JWT_ISSUER)}"
export WEB_EXT_API_SECRET="${AMO_JWT_SECRET:-$(env_value AMO_JWT_SECRET)}"
if [[ -z "$WEB_EXT_API_KEY" || -z "$WEB_EXT_API_SECRET" ]]; then
  echo "Нет ключей AMO: добавь AMO_JWT_ISSUER и AMO_JWT_SECRET в .env (addons.mozilla.org → Developer Hub → Manage API Keys)" >&2
  exit 1
fi

# personal files must not leave the machine: check what the package would contain
tmp=$(mktemp -d "${TMPDIR:-/tmp}/job-autofill.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
npx --yes web-ext@8 build --artifacts-dir "$tmp" >/dev/null 2>&1
if unzip -l "$tmp"/*.zip | grep -E "profile\.json|cv\.pdf|\.tex$|\.yaml$"; then
  echo "В пакет попали личные файлы, подпись остановлена: проверь ignoreFiles в web-ext-config.mjs" >&2
  exit 1
fi

version=$(node -p "require('./manifest.json').version")
if ls web-ext-artifacts/*-"$version".xpi >/dev/null 2>&1; then
  version=$(node -e "
    const fs = require('fs'); const m = JSON.parse(fs.readFileSync('manifest.json', 'utf8'));
    const v = m.version.split('.').map(Number); v[2] += 1; m.version = v.join('.');
    fs.writeFileSync('manifest.json', fs.readFileSync('manifest.json', 'utf8').replace(/\"version\": \"[^\"]+\"/, '\"version\": \"' + m.version + '\"'));
    console.log(m.version);")
  echo "версия $version (предыдущая уже подписана)"
fi

npx --yes web-ext@8 sign --channel unlisted --artifacts-dir web-ext-artifacts
echo
echo "Готово: $(ls -t web-ext-artifacts/*.xpi | head -1)"
echo "Firefox: about:addons → ⚙ → «Установить дополнение из файла…» → этот .xpi; затем в настройках расширения импортировать profile.json и cv.pdf"
