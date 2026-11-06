# Настройка руками

Всё то же самое делает скилл `/jobsearch-setup` в Claude Code за один разговор. Эта инструкция — для тех, кто
хочет понимать каждый шаг или настраивает без Claude Code. Займёт около часа, из них полчаса на профиль.

Команды ниже выполняются из папки проекта. `python -m jobsearch` везде означает `.venv/bin/python -m jobsearch`.

## 1. Поставить

Нужны Python 3.9 или новее (`python3 --version`) и git. На Mac подходит системный `python3`; если его нет, macOS сама предложит поставить Command Line Tools.

```bash
git clone https://github.com/boris-timofeenko/jobsearch-kit ~/jobsearch
cd ~/jobsearch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```

Последняя строка должна закончиться словом `passed`.

На Mac держи проект в `~/jobsearch` или другой папке вне `~/Documents`, `~/Desktop`, `~/Downloads`: в эти три
папки macOS не пускает фоновые задачи, и расписание (шаг 9) будет молча падать.

## 2. Создать профиль

Выбери пресет, ближайший к своей роли: `qa`, `backend`, `frontend`, `mobile`, `devops`, `data`, `product`.

```bash
.venv/bin/python -m jobsearch init --role backend
```

Появятся `my/profile.yaml` (пример профиля с выбранной ролью), `my/config.yaml`, `my/companies.yaml` и `.env`.
Дальше правишь `my/profile.yaml` сверху вниз. Все поля описаны в [CONFIG.md](CONFIG.md), здесь — что важно.

### candidate

```yaml
candidate:
  name: Anna Petrova
  summary: |
    Backend-разработчик, 6 лет: Python (FastAPI, Django), PostgreSQL, Kafka, Kubernetes, AWS.
    Последние 3 года — платёжный сервис в финтехе, веду двух разработчиков. Go и Java в резюме нет.
  languages: [English, Russian]
  seniority: senior
  needs_visa: true
  based_in: Georgia
  citizenship_note: "Гражданство Казахстана, живёт в Грузии"
```

- `summary` — главное поле: модель сравнивает каждую вакансию с этим текстом. Перескажи резюме фактами: роль, годы,
  стек, домены, масштаб. Обязательно допиши, чего у тебя **нет** из типичного для роли, иначе модель решит, что
  Java-вакансия тебе подходит «с мелким пробелом».
- `languages` — все рабочие языки, включая родной. Вакансия, где обязателен язык не из списка, отсекается.
- `seniority`: junior, mid, senior или lead. От senior и выше junior-вакансии отсекаются, mid помечаются; для
  junior наоборот, senior-вакансии опускаются вниз.
- `needs_visa: false`, если есть гражданство ЕС/ЕЭЗ: тогда «EU citizens only» и «no visa sponsorship» не мешают.
- `based_in` — где живёшь: remote-вакансия «только для жителей X» не отсекается, если X — эта страна.
- `birth_year` нужен только для Нидерландов: до 30 лет порог зарплаты для визы HSM ниже.

### role

Пресет уже заполнен. Что стоит поправить:

- `strengths` — одна фраза о самых сильных твоих сторонах; модель считает их весомым совпадением.
- `queries` — названия вакансий для поиска, **самые широкие первыми**: дополнительные страны и remote ищутся только
  по первым четырём.
- `stack` — темы из твоего резюме с весами 1–3. Влияют только на порядок и на то, дойдёт ли remote-вакансия до
  модели, ничего не отсекают.
- `focus` — 1–3 темы, где ты сильнее всего (например, `Payments` или `Kubernetes operators`): плюс к score и к fit.
- `not_this_role` — соседние роли, которые модель должна отвергать. Это самый сильный рычаг против мусора.
- `title_include` / `title_exclude` — регулярные выражения для заголовков. Проверь их на шаге 3.

### target

```yaml
target:
  country: de                 # основная страна
  countries: [nl, at]         # дополнительные
  remote: true                # и remote по Европе
  salary_target_month: 6000
```

Коды стран: nl, de, be, fr, es, pt, ie, at, pl, cz, se, dk, fi, it, lu. Для каждой страны в
`presets/countries.yaml` уже есть города, языки, визовая схема и порог зарплаты. **Пороги — ориентиры на 2026 год**:
проверь цифру своей визы на официальном сайте и, если отличается, переопредели:

```yaml
  country: {code: de, salary_floor_month: 4225}
```

Вакансия, где зарплата указана и ниже 90% порога, отсекается; между 90% и 100% — только пометка.

Только remote без переезда: `country: none` и `countries: []`.

`goal_note` — абзац своими словами о приоритетах (что важнее: страна, деньги, продукт, стек). Модель учитывает его
в заметках, но не в fit. `fit_adjustments` — поправки к оценке после модели: например, `contractor: -2` опускает
контракты, `ai_first: 2` поднимает роли, построенные вокруг AI.

### Воронка и исключения

- `known_companies.applied` — куда уже откликнулся: такие вакансии помечаются и уходят вниз.
- `exclude_companies` — кого не показывать совсем.

## 3. Проверить

```bash
.venv/bin/python -m jobsearch check --fast
```

Покажет роль, страны с порогами, что и где будет искаться, есть ли токены, и список проблем, если они есть.
Потом проверь фильтр заголовков на настоящих названиях — подходящих и соседних:

```bash
.venv/bin/python -m jobsearch check --title "Senior Backend Engineer" "Python Developer (m/w/d)" \
  "Software Engineer, Payments" "Frontend Engineer" "DevOps Engineer" "Sales Engineer"
```

Каждый ❌ у подходящего заголовка — дописать вариант в `title_include`; каждый ✅ у чужого — в `title_exclude`.
Регулярные выражения можно проверять на regex101.com (режим Python).

## 4. Доски компаний и агрегаторы

В `my/config.yaml` выбери списки досок:

```yaml
company_files:
  - my/companies.yaml
  - boards/curated.yaml          # ~220 софтверных компаний NL/ЕС/remote — подходит почти всем
  - boards/nl-ind-sponsors.yaml  # если ищешь в Нидерландах: 432 работодателя-спонсора
  - boards/de-large.yaml         # если в Германии: 72 крупных работодателя
```

Свои компании — найди их доски командой `discover`, она печатает готовые строки:

```bash
.venv/bin/python -m jobsearch discover "Mollie" "Personio" "N26"
```

Скопируй строки в `my/companies.yaml`. Если компания не нашлась, у неё своя система найма, её вакансии будут
приходить с LinkedIn.

Агрегаторы по умолчанию годятся всем. Для Нидерландов добавь `iamexpat` и `undutchables`, для Германии
`arbeitsagentur`; бесплатные ключи Adzuna (developer.adzuna.com) включают ещё один источник по основной стране.

## 5. Telegram-бот

1. В Telegram открой @BotFather, отправь `/newbot`, придумай имя и username (должен кончаться на `bot`).
   BotFather пришлёт токен вида `7123456789:AAH...` — впиши его в `.env` в `TELEGRAM_BOT_TOKEN=`.
2. Найди своего бота по username и отправь ему любое сообщение.
3. Узнай свой chat id (подставь токен):
   ```bash
   curl -s "https://api.telegram.org/bot<ТОКЕН>/getUpdates" | grep -o '"chat":{"id":[0-9-]*' | head -1
   ```
   Число после `"id":` впиши в `TELEGRAM_CHAT_ID=`. Бот слушает только этот чат.
4. Проверь:
   ```bash
   .venv/bin/python -m jobsearch telegram-test
   ```

## 6. Модель Claude

Без модели всё работает, но в Telegram приходят только вакансии, оценённые моделью, так что она нужна.

- **Подписка Claude (Pro или Max)** на своём компьютере: установи Claude Code
  (`curl -fsSL https://claude.ai/install.sh | bash`), запусти `claude` и залогинься. Больше ничего не нужно.
- **Подписка на сервере** (там нет браузера для входа): на своём компьютере выполни `claude setup-token`, пройди
  вход в браузере и **скопируй токен руками** (начинается с `sk-ant-oat01-`, длина 108 символов) в `.env`:
  `CLAUDE_CODE_OAUTH_TOKEN=`. Не вырезай его скриптом из вывода терминала: в строку попадают управляющие символы и
  токен портится.
- **API-ключ** с console.anthropic.com в `ANTHROPIC_API_KEY=`. Одна оценка — около цента.

`.venv/bin/python -m jobsearch check` (без `--fast`) покажет, какой вариант подхватился.

Модели по умолчанию — Sonnet. Если подписка большая, для вакансий в целевых странах (их немного) можно включить
Opus в `my/config.yaml`: `llm: {model_cli_country: opus}`.

## 7. Первый прогон

```bash
.venv/bin/python -m jobsearch run --time-filter r259200
```

Ищет за последние 3 дня, идёт 15–40 минут (LinkedIn отвечает медленно, это нормально). Telegram в первом
прогоне не пишет, флаг `--notify` включает отправку. Потом:

```bash
.venv/bin/python -m jobsearch report --hours 72    # → data/reports/latest.html
open data/reports/latest.html                      # Linux: xdg-open
```

В отчёте только то, что прошло модель с fit ≥ 4, по трекам. У каждой вакансии — заметка модели и пометки:
почему fit такой, что проверить. Пример карточек в Telegram:

```bash
.venv/bin/python -m jobsearch telegram-test --sample 3
```

## 8. Калибровка

Самое полезное, что можно сделать в первый день: посмотреть, что отсеялось.

```bash
.venv/bin/python -m jobsearch list --all --hours 72 --limit 300
```

У каждой вакансии видны score, трек и причины. Типичные исправления:

| видишь | правишь |
|---|---|
| нужная вакансия отсеяна «заголовок…» или её нет вовсе | `title_include` |
| в отчёте чужая роль | `title_exclude` и `not_this_role` |
| «нужен другой язык», а ты его знаешь | `candidate.languages` |
| «зарплата … < порога» | `salary_floor_month` страны |
| хорошая вакансия с низким fit | `summary`, `strengths`, `small_gap`; почитай `note` модели |
| вакансия в стране, которую ты бы рассмотрел, внизу | добавить страну в `countries` |

После правок:

```bash
.venv/bin/python -m jobsearch check --fast
.venv/bin/python -m jobsearch reanalyze      # пересчитать всё уже собранное; оценки модели сохраняются
```

## 9. Расписание

### Mac

```bash
scripts/install_launchd.sh 9 13 18 --bot
```

Прогоны в 9:05, 13:05 и 18:05 (первый после полудня — глубокий: все запросы LinkedIn и hiring.cafe), бот работает
постоянно. Если Mac спал, launchd выполнит пропущенный прогон при пробуждении. Снять: `scripts/install_launchd.sh
--remove`. Логи: `data/logs/`.

### Linux-компьютер

`crontab -e` и строки (путь свой):

```
5 9,13,18 * * * /home/anna/jobsearch/scripts/run-local.sh
@reboot cd /home/anna/jobsearch && .venv/bin/python -m jobsearch bot >> data/logs/bot.log 2>&1
```

### Свой сервер (VPS)

Подойдёт любой VPS с Ubuntu 22.04+ или Debian 12 и 2 ГБ памяти (Hetzner CX22 ~€4 в месяц). Нужен вход по
SSH-ключу под root:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vps        # если ключа ещё нет
ssh-copy-id -i ~/.ssh/id_ed25519_vps root@<ip>       # или добавь ключ при создании сервера
SSH_KEY=~/.ssh/id_ed25519_vps deploy/deploy.sh root@<ip>
```

`deploy.sh` копирует проект вместе с `my/` и `.env` в `/opt/jobsearch`, ставит Python-окружение и тесты, Claude
CLI (если в `.env` есть `CLAUDE_CODE_OAUTH_TOKEN`), LaTeX (если есть `my/cv.tex`) и systemd: прогоны каждые два
часа с 08:15 до 22:15, глубокий ночью в 00:15, бот — постоянно. Часовой пояс — `JOBSEARCH_TZ` в `.env`. Ночные
сообщения приходят без звука.

Если уже были прогоны на компьютере, перенеси базу, иначе первый серверный прогон пришлёт всё найденное заново:

```bash
scp data/jobs.db root@<ip>:/opt/jobsearch/data/
ssh root@<ip> 'chown jobsearch:jobsearch /opt/jobsearch/data/jobs.db'
```

На сервере:

```bash
systemctl start jobsearch.service                      # прогон сейчас
tail -f /opt/jobsearch/data/logs/$(date +%F).log       # лог
systemctl list-timers | grep jobsearch                 # расписание
journalctl -u jobsearch-bot -f                         # бот
```

Если прогон упал или его остановил таймаут, бот пришлёт сообщение с хвостом лога.

## 10. Каждый день

- Карточки приходят в Telegram. Кнопки: ✅ Откликнулся, ⏳ Позже, 🙈 Скрыть (сворачивает карточку).
- `/applied`, `/later`, `/interview` — списки; `/stats` — сколько всего; `/mark <id> rejected` — любой статус.
- «📄 CV под вакансию» работает, если положить LaTeX-резюме в `my/cv.tex` (и, по желанию, `my/cv_bank.yaml` с
  вариантами заголовков и синонимами; формат — в `AGENTS.md`, раздел «CV под вакансию»).
- Изменилась цель (другая страна, отказ от контрактов) — правь профиль, `check --fast`, `reanalyze`, на сервере
  ещё `deploy/deploy.sh`.

## 11. Обновить код

```bash
git pull
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest -q tests
deploy/deploy.sh root@<ip>          # если на сервере
```

## Если что-то не так

| проблема | что делать |
|---|---|
| `настройка: нет my/profile.yaml` | шаг 2 |
| `LLM: недоступен` | шаг 6; на сервере `sudo -u jobsearch /home/jobsearch/.local/bin/claude -p ok` должен ответить |
| в логе много `429` от LinkedIn | это волны ограничений на его стороне, бывают по 1–3 дня; следующие прогоны догонят пропущенное сами |
| `Not logged in` у `claude` на сервере | токен скопирован не целиком: заново `claude setup-token`, вставить руками |
| расписание на Mac не запускается | проект лежит в `~/Documents` или подобной папке — перенеси, пересоздай `.venv`, переустанови расписание |
| бот не реагирует на кнопки | на сервере `systemctl status jobsearch-bot`; на Mac `scripts/install_launchd.sh … --bot` |
| в Telegram ничего | пустой дайджест — нормально; `list --last-run` покажет, что нашлось и почему не прошло |
| `database is locked` | два прогона одновременно; на сервере это исключено, на компьютере не запускай `run` руками, пока идёт плановый |
