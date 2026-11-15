# jobsearch

Несколько раз в день (на сервере — каждые два часа) собирает свежие вакансии под твою роль из LinkedIn (без
аккаунта), с сотен досок компаний и десятка агрегаторов. Очевидно неподходящее выкидывает сразу: не та роль, нужен
язык, которого нет, без визы, зарплата ниже порога. Остальное по полному тексту оценивает модель Claude, и в
Telegram приходит только то, что прошло. Всё складывается в SQLite, под каждой карточкой в боте кнопки «Откликнулся
/ Позже / Скрыть».

Сделано для поиска работы с переездом в ЕС (или remote из Европы) и рассчитано на IT-роли: в комплекте пресеты для
QA, backend, frontend, mobile, DevOps, data и product. Страна, роль, стек, уровень и всё остальное личное лежат в
одном файле `my/profile.yaml`. Код у всех общий.

Так выглядит карточка в Telegram:

```
🇩🇪 Германия
fit 11/10 · откликаться · Senior Backend Engineer (Python) — Acme Payments
Berlin, Germany · hybrid · €6500/мес · 👥 18 откликов
Платёжный процессинг на FastAPI и Kafka, команда из 6 человек, есть онколл. Проверить, нужен ли немецкий
для общения с банками-партнёрами.
⚠️ фокус: Payments · LLM: визовая поддержка явно ✅ · fit: модель 7 +1 Germany +2 виза явно +1 мало откликов (18) = 11
[✅ Откликнулся] [⏳ Позже] [🙈 Скрыть]
[📄 CV под вакансию]
```

## Настройка за один разговор (Claude Code)

Удобнее всего настраивать в [Claude Code](https://claude.com/claude-code) с моделью Opus: он прочитает резюме,
задаст несколько вопросов, заполнит профиль, проверит его на реальных заголовках, поможет завести бота и поставит
расписание.

```bash
git clone https://github.com/boris-timofeenko/jobsearch-kit ~/jobsearch
cd ~/jobsearch
claude
```

И напиши: «настрой jobsearch под меня, вот резюме: …» (или `/jobsearch-setup`). Скилл лежит в
`.claude/skills/jobsearch-setup/`.

На Mac клонируй в `~/jobsearch`, а не в `~/Documents`, `~/Desktop` или `~/Downloads`: из этих папок macOS не даёт
запускать задачи по расписанию.

Без Claude Code — по [docs/SETUP.md](docs/SETUP.md), около часа: после установки `.venv/bin/python -m jobsearch
init` спросит роль и переключатели прямо в терминале. Скилл можно загрузить и в приложение Claude без терминала
(Settings → Capabilities → Skills): архив собирает `scripts/package-skill.sh` в `dist/jobsearch-setup.zip` (у кого
есть клон — собери и передай). Там он по резюме подготовит `my/profile.yaml` и `my/config.yaml`, а команды
придётся выполнить самому.

## Переключатели

Главное настраивается короткими ответами в начале `my/profile.yaml`:

```yaml
switches:
  goal: both                    # relocate — только переезд · remote — только удалёнка · both
  countries: [de, nl]           # страны переезда, первая — основная
  eu_offices: true              # офис в другой стране ЕС тоже рассматриваю
  visa: needed                  # not_needed — есть гражданство или ВНЖ ЕС
  languages: [English, Russian]
  other_language: skip          # вакансия требует другой язык: skip · flag (показать с пометкой) · any
  level: senior
  salary_min: visa              # порог визы страны · свой минимум €/мес · 0
  contract: penalize            # B2B и фриланс: skip · penalize · ok
  outsourcing: penalize         # аутсорс и аутстафф: skip · penalize · ok
  agencies: penalize            # рекрутеры: skip · penalize · ok
  cv: my/cv.docx                # .docx или .tex — «CV под вакансию» в том же оформлении, .md — через шаблон
```

Полный список и что меняет каждый — [docs/CONFIG.md](docs/CONFIG.md#переключатели-switches). Резюме подходит в Word
(Google Docs экспортирует .docx), LaTeX или Markdown: кнопка «CV под вакансию» вернёт его же, переставив буллеты
и навыки под вакансию.

## Что понадобится

- Mac или Linux с Python 3.9+ и git. Для круглосуточной работы — VPS за €4–5 в месяц (Hetzner CX22 и подобные).
- Telegram и бот от @BotFather (две минуты).
- Модель Claude: подписка Pro/Max (оценка идёт через `claude` CLI) или API-ключ. На API одна вакансия стоит около
  цента, в день оценивается 30–200 вакансий.

## Как это устроено

```
LinkedIn ─┐
доски ────┼─→ уже в базе? ─→ описания ─→ эвристики ─→ дубли ─→ модель ─→ SQLite ─→ отчёт HTML + Telegram
агрегаторы┘                  (полный текст) (skip с причиной)      (fit 0–10 + поправки)
```

1. **Сбор.** LinkedIn ищет по `role.queries` в основной стране, дополнительных странах и remote по Европе. Доски
   компаний — публичные API Greenhouse, Lever, Ashby, Recruitee, Workable, SmartRecruiters, Teamtailor, Personio,
   Workday и корпоративные сайты (SuccessFactors, Phenom). Плюс агрегаторы: Remotive, RemoteOK, We Work Remotely,
   Himalayas, Working Nomads, Landing.jobs, Arbeitnow, Jobicy, The Muse, Workable search, Adzuna, в глубоком прогоне
   hiring.cafe (на сервере — ночью). И Telegram-каналы с вакансиями из твоего списка: открытые читаются без
   аккаунта, посты модель разбирает на отдельные вакансии.
2. **Эвристики** бесплатно отсекают очевидное и раскладывают вакансии по трекам: основная страна, дополнительные
   страны, офис в другой стране ЕС, remote. У каждого отсева записана причина, ничего не удаляется.
3. **Модель** читает полный текст и отвечает структурой: та ли это роль, fit 0–10 по совпадению стека и уровня,
   обязательный язык, ограничения по резидентству, виза, режим работы, тип работодателя. Страну, визу, аутсорс и
   контракт модель в fit не учитывает: это делает код поправками, которые видны в карточке.
4. **Выход**: карточки в Telegram (fit ≥ 4, не больше двух от компании), HTML-отчёт, база для `list`/`report`.

Подробно: путь вакансии, все причины отсева и как считается оценка — [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md);
устройство кода и история решений — [AGENTS.md](AGENTS.md).

## Где что лежит

| | что | в git |
|---|---|---|
| `my/profile.yaml` | ты: резюме для модели, роль, страны, воронка | нет |
| `my/config.yaml` | твои переопределения `config.yaml`: доски, агрегаторы, LinkedIn, лимиты | нет |
| `my/companies.yaml` | свои компании | нет |
| `my/cv.docx` / `.tex` / `.md`, `my/cv_bank.yaml` | резюме для кнопки «CV под вакансию» (по желанию) | нет |
| `.env` | токены Telegram и Claude | нет |
| `data/` | база, отчёты, логи | нет |
| `presets/` | пресеты ролей, каталог стран, примеры | да |
| `boards/` | общие списки досок компаний | да |
| `config.yaml` | общие настройки источников и лимитов | да |

Справочник полей — [docs/CONFIG.md](docs/CONFIG.md).

## Каждый день

```bash
.venv/bin/python -m jobsearch report --hours 24      # отчёт за сутки → data/reports/latest.html
.venv/bin/python -m jobsearch list --last-run        # что нашёл последний прогон
.venv/bin/python -m jobsearch list --all --hours 24  # всё, включая отсеянное, с причинами
.venv/bin/python -m jobsearch mark <id> applied      # то же, что кнопка в боте
```

В боте: кнопки под карточками, `/applied`, `/later`, `/interview`, `/stats`, `/cv <id>`.

## Обновление

```bash
git pull
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m jobsearch check
deploy/deploy.sh jobsearch-vps     # если стоит на сервере (имя хоста — docs/SETUP.md, шаг 9)
```

`my/`, `.env` и `data/` обновление не трогает.

## Чего тут нет и не будет

- Отклики сами не отправляются. Есть браузерное расширение, которое заполняет форму отклика из резюме
  ([extension/README.md](extension/README.md)), но кнопку «Отправить» жмёшь ты.
- Indeed, Glassdoor, StepStone, XING не подключены: антибот или запрет в robots.txt.
- Реестр спонсоров есть только у Нидерландов (IND): если нужна виза, им проверяется каждый работодатель с
  вакансией в Нидерландах. Для других стран о визе судит модель по тексту.
- Интерфейс, отчёты и заметки модели — на русском.
