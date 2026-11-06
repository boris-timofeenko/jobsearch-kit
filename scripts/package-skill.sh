#!/bin/bash
# Архив скилла для Claude без терминала (claude.ai / приложение: Settings → Capabilities → Skills → Upload).
# Там скилл не может запускать команды, поэтому в архив кладутся справочники: схема, пресеты, каталог стран.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=dist/jobsearch-setup.zip
TMP=$(mktemp -d)
mkdir -p "$TMP/jobsearch-setup/references/roles" dist
cp .claude/skills/jobsearch-setup/SKILL.md "$TMP/jobsearch-setup/"
cp docs/CONFIG.md docs/SETUP.md presets/countries.yaml presets/profile.example.yaml presets/config.example.yaml \
   "$TMP/jobsearch-setup/references/"
cp presets/roles/*.yaml "$TMP/jobsearch-setup/references/roles/"
rm -f "$OUT"
(cd "$TMP" && zip -qr - jobsearch-setup) > "$OUT"
rm -rf "$TMP"
echo "$OUT: $(unzip -l "$OUT" | tail -1)"
