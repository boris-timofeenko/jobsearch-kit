# Настройка руками

Всё то же самое делает скилл `/jobsearch-setup` в Claude Code за один разговор. Эта инструкция — для тех, кто
хочет понимать каждый шаг или настраивает без Claude Code. Займёт около часа, из них полчаса на профиль.
Что происходит с вакансией внутри и почему она могла не прийти — [HOW-IT-WORKS.md](HOW-IT-WORKS.md).

Команды ниже выполняются из папки проекта.

## 1. Поставить

Нужны Python 3.9 или новее (`python3 --version`) и git. На Mac подходит системный `python3`; если его нет, macOS сама
предложит поставить Command Line Tools. На Ubuntu и Debian для `venv` нужен пакет `python3-venv`
(`sudo apt install python3-venv`).

```bash
git clone https://github.com/boris-timofeenko/jobsearch-kit ~/jobsearch
cd ~/jobsearch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```

В конце должно быть «… passed». На системном Python с Mac каждая команда печатает предупреждение `NotOpenSSLWarning`
— оно безвредно.

На Mac держи проект в `~/jobsearch` или другой папке вне `~/Documents`, `~/Desktop`, `~/Downloads`: в эти три
папки macOS не пускает фоновые задачи, и расписание (шаг 9) будет молча падать.

## 2. Создать профиль

```bash
.venv/bin/python -m jobsearch init
```

`init` спросит роль (ближайший пресет: `qa`, `backend`, `frontend`, `mobile`, `devops`, `data`, `product`) и
переключатели — короткие ответы про цель, страны, визу, языки, зарплату. Enter оставляет значение в скобках. Появятся
`my/profile.yaml`, `my/config.yaml`, `my/companies.yaml` и `.env`. С `--role` вопросов не будет, в профиль ляжет
пример: `init --role backend`. Все поля — в [CONFIG.md](CONFIG.md), здесь — что важно.

### Переключатели

Блок `switches` в начале профиля. Ответы `init` уже там, поменять можно в любой момент:

```yaml
switches:
  goal: both                    # relocate — только переезд · remote — только удалёнка · both
  work_modes: [remote, hybrid, onsite]   # формат: remote · hybrid · onsite
  countries: [de, nl]           # страны переезда, первая — основная (коды из presets/countries.yaml)
  offices: [eu]                 # офис в других странах региона: eu · europe · cis · middle_east · world · коды · none
  visa: needed                  # not_needed — есть гражданство или ВНЖ в этих странах
  based_in: Georgia
  languages: [English, Russian]
  other_language: skip          # вакансия требует язык не из списка: skip · flag · any
  level: senior
  salary_currency: EUR          # валюта сумм ниже: EUR · RUB · USD…
  salary_min: visa              # visa · свой минимум в месяц · 0
  salary_target: 6000
  contract: penalize            # skip · penalize · ok
  outsourcing: penalize
  agencies: penalize
  public_sector: skip
  ai: neutral                   # prefer · neutral · avoid
  cv: my/cv.docx
```

Что меняет каждый — в [CONFIG.md](CONFIG.md#переключатели-switches). Главное:

- Страны — не только ЕС: в каталоге есть Великобритания, Швейцария, Норвегия, Сербия, Черногория, Турция, Россия,
  Беларусь, Казахстан, Узбекистан, Кыргызстан, Армения, Грузия, Азербайджан, ОАЭ, Израиль, США и Канада. Страны нет —
  опиши её прямо в профиле: `countries: [{code: br, name: Brazil, location_regex: '\b(brazil|são paulo|sao paulo)',
  part: americas}]`. `part` — часть света (eu, europe, cis, middle_east, americas, asia): по ней решается, какие
  remote-вакансии тебе доступны.
- `work_modes` — формат работы: `remote`, `hybrid`, `onsite`, любые сочетания. Только `[remote]` — до модели
  отсеиваются вакансии, где об удалёнке ни слова, после модели — те, что она признала офисом или гибридом. Без
  `remote` — LinkedIn не ищет remote, remote-доски выключаются, remote-вакансии не показываются. Сам LinkedIn формат
  фильтровать не умеет (гостевой поиск игнорирует этот фильтр), поэтому формат решают текст и модель.
- `offices` — офис или гибрид в странах, которые не в `countries`, но куда тоже готов переехать: регион (`eu`,
  `europe`, `cis` — СНГ и Кавказ, `middle_east`, `americas`, `asia`), коды стран (`[rs, ae]`), `world` или `none`.
  Без этой строки — `eu`, если основная страна в ЕС, иначе `none`.
- Remote подходит, если в его локации нет мест только из чужих частей света: живущему в Грузии подходят «Remote,
  EMEA» и «Remote, Moscow», но не «Remote, US»; живущему в США — наоборот. Европа и СНГ считаются одной частью.
- `visa: not_needed`, если у тебя гражданство или ВНЖ в целевых странах: тогда «no visa sponsorship» не мешает, а
  порог визы не применяется. «EU citizens only» не мешает, только когда все целевые страны в ЕС.
- `salary_currency`: в какой валюте `salary_min` и `salary_target`. Для России — `RUB`: тогда «от 250 000 ₽» в
  вакансии сравнивается с твоим минимумом, а в карточках суммы в рублях. Курсы — `currency_rates` в `config.yaml`.
- `other_language: flag` — если учишь местный язык: английские объявления с требованием этого языка придут с
  пометкой. Объявления целиком на незнакомом языке по-прежнему отсеиваются; чтобы видеть и их — `any` (в Нидерландах
  и Германии это вдвое больше вакансий и оценок модели).
- `salary_min: visa` берёт порог визы из `presets/countries.yaml`. **Пороги — ориентиры на 2026 год**: проверь цифру
  своей визы на официальном сайте и, если отличается, задай свою: `salary_min: 4300` (тогда она действует везде,
  и для remote тоже) или порог одной страны прямо в списке: `countries: [{code: de, salary_floor_month: 4225}, nl]`.
- `contract`: `ok`, если B2B или фриланс тебе подходят; `penalize` (по умолчанию) опускает контракты ниже, но явную
  почасовую ставку и фриланс с работой в офисе отсеивает; `skip` — нужен только найм в штат.

### Резюме

`switches.cv` — путь к резюме. Положи файл в `my/`:

- **Word или Google Docs** → `my/cv.docx` (в Google Docs: Файл → Скачать → Microsoft Word). Кнопка «CV под вакансию»
  вернёт его же, переставив буллеты и навыки под вакансию. PDF получится, если стоит LibreOffice: на сервере он
  ставится сам, на Mac — `brew install --cask libreoffice`; без него придёт DOCX.
- **LaTeX** → `my/cv.tex`.
- **Нет удобного файла** → `my/cv.md` по образцу `presets/cv/example.md`: PDF соберётся по встроенному шаблону.
- **Только PDF** → для профиля его хватит (из него пишется `candidate.summary`), а для «CV под вакансию» сохрани
  резюме в DOCX или перепиши в Markdown.

Для `.tex` и `.md` нужен LaTeX. На сервере его ставит `deploy.sh`. Если бот работает на твоём компьютере: на Mac
`brew install --cask mactex-no-gui` (около 5 ГБ), на Ubuntu
`sudo apt install --no-install-recommends texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended lmodern`.

Проверить, что нашлось в резюме: `.venv/bin/python -m jobsearch cv --inspect`. Варианты заголовка, навыки «можно
добавить под вакансию» и строки про визу — в необязательном `my/cv_bank.yaml`, формат в
[CONFIG.md](CONFIG.md#mycv_bankyaml).

### candidate

```yaml
candidate:
  name: Anna Petrova
  summary: |
    Backend-разработчик, 6 лет: Python (FastAPI, Django), PostgreSQL, Kafka, Kubernetes, AWS.
    Последние 3 года — платёжный сервис в финтехе, веду двух разработчиков. Go и Java в резюме нет.
  citizenship_note: "Гражданство Казахстана, живёт в Грузии"
```

`summary` — главное поле: модель сравнивает каждую вакансию с этим текстом. Перескажи резюме фактами: роль, годы,
стек, домены, масштаб. Обязательно допиши, чего у тебя **нет** из типичного для роли, иначе модель решит, что
Java-вакансия тебе подходит «с мелким пробелом». `birth_year` нужен только для Нидерландов: до 30 лет порог визы HSM
ниже.

### role

Пресет уже заполнен. Что стоит поправить:

- `strengths` — одна фраза о самых сильных твоих сторонах; модель считает их весомым совпадением.
- `queries` — названия вакансий для поиска, **самые широкие первыми**: в обычном прогоне дополнительные страны и
  remote ищутся только по первым четырём.
- `stack` — темы из твоего резюме с весами 1–3. Влияют только на порядок и на то, дойдёт ли remote-вакансия до
  модели, ничего не отсекают.
- `focus` — 1–3 темы, где ты сильнее всего (например, `Payments` или `Kubernetes operators`): плюс к score и к fit.
- `not_this_role` — соседние роли, которые модель должна отвергать. Это самый сильный рычаг против мусора.
- `title_include` / `title_exclude` — регулярные выражения для заголовков. Проверь их на шаге 3.

### target (необязательно)

`goal_note` — абзац своими словами о приоритетах (что важнее: страна, деньги, продукт, стек). Модель учитывает его
в заметках, но не в fit. `fit_adjustments` — размер поправок к оценке после модели, если штраф по умолчанию кажется
слишком большим или маленьким.

### Воронка и исключения

- `known_companies.applied` — куда уже откликнулся: вакансии этих компаний помечаются и уходят вниз.
- `exclude_companies` — кого не показывать совсем.

## 3. Проверить

```bash
.venv/bin/python -m jobsearch check --fast
```

Покажет роль, страны, переключатели, что и где будет искаться, есть ли токены, и список проблем, если они есть.
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
  - boards/curated.yaml          # ~220 софтверных компаний NL/ЕС/remote — подходит почти всем, кроме поиска в России и СНГ
  - boards/nl-ind-sponsors.yaml  # если ищешь в Нидерландах: 432 работодателя-спонсора
  - boards/de-large.yaml         # если в Германии: 72 крупных работодателя
```

Свои компании — найди их доски командой `discover`, она печатает готовые строки:

```bash
.venv/bin/python -m jobsearch discover "Mollie" "Personio" "N26"
```

Допиши строки в конец `my/companies.yaml` (если в файле есть строка `[]`, удали её). Если компания не нашлась, у
неё своя система найма или доска на платформе, которую `discover` не перебирает, — её вакансии будут приходить с
LinkedIn.

Агрегаторы по умолчанию годятся всем. Список в `my/config.yaml` заменяет общий целиком, поэтому, чтобы добавить
местные (`iamexpat` и `undutchables` для Нидерландов, `arbeitsagentur` для Германии), выпиши весь:

```yaml
aggregators: [arbeitnow, landingjobs, himalayas, remotive, remoteok, workingnomads, weworkremotely, themuse, jobicy,
              adzuna, workable_search, iamexpat, undutchables]
```

При `goal: relocate` remote-агрегаторы (Remotive, RemoteOK, We Work Remotely, Working Nomads, Himalayas, Jobicy)
выключаются сами, но только пока своего списка нет — в своём не пиши их. Бесплатные ключи Adzuna
(developer.adzuna.com) в `.env` включают ещё один источник по основной стране (Adzuna есть не везде: из каталога —
nl, de, be, fr, es, at, it, pl).

### Telegram-каналы с вакансиями (по желанию)

Каналы вроде «вакансии QA» или «работа с релокацией» — ещё один источник. Список — в `my/config.yaml`, можно
ссылками:

```yaml
tg_channels:
  channels: [forallqa, https://t.me/wantapply_qa_jobs, "@dev_connectablejobs"]
```

```bash
.venv/bin/python -m jobsearch tg-check
```

`tg-check` ничего не сохраняет: печатает по каждому каналу, сколько постов за 30 дней и сколько из них с заголовком
твоей роли. Если постов с заголовком почти нет, а вакансии в канале видны глазами — заголовки там на другом языке:
добавь их в `role.title_include` (например `'тестировщ'`) и проверь `check --title "…"`.

Открытые каналы читаются через их публичную веб-страницу `t.me/s/<имя>`, без аккаунта Telegram: банить нечего.
Каждый прогон берёт только посты новее прочитанных, первый — за 30 дней (`tg_channels.days`). Посты со строкой-заголовком
твоей роли модель разбирает на вакансии (работодатель, город, remote или офис, ссылка), дальше они идут как вакансии
с любого сайта. Карточка ведёт на пост: там способ отклика.

**Группы** (и каналы, где веб-страница выключена) так не читаются: `tg-check` пометит их 🔒. Их можно читать
твоим аккаунтом Telegram:

1. на my.telegram.org → API development tools заведи приложение, `api_id` и `api_hash` впиши в `.env` как
   `TG_API_ID` и `TG_API_HASH`;
2. ```bash
   .venv/bin/python -m jobsearch tg-login
   ```
   номер, код из Telegram и пароль 2FA вводишь сам. Сессия ляжет в `data/tg.session` — это полный доступ к аккаунту,
   никому её не отдавай.

Прогон подключается на несколько секунд, читает историю группы, не вступая в неё, и отключается. В группы и каналы
ничего не пишет и не подписывается: массовые вступления Telegram считает спамом, здесь их нет. Если аккаунт уже
используется другой программой на этом же компьютере, не копируй её файл сессии: `tg-login` делает отдельный вход,
а два клиента на одной сессии мешают друг другу. На сервере `tg-login` выполняй там (шаг 9, «Свой сервер»): сессия с ноутбука не переносится.

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
- **API-ключ** с console.anthropic.com в `ANTHROPIC_API_KEY=`. Одна оценка — около цента. Если задан ключ, подписка
  не используется.

`.venv/bin/python -m jobsearch check` (без `--fast`) покажет, какой вариант подхватился.

Модели по умолчанию — Sonnet. Если подписка большая, для вакансий в целевых странах (их немного) можно включить
Opus в `my/config.yaml`: `llm: {model_cli_country: opus}`.

## 7. Первый прогон

```bash
.venv/bin/python -m jobsearch run --time-filter r259200
```

Ищет за последние 3 дня, обычно 20–40 минут; если LinkedIn в этот день ограничивает запросы, до полутора часов.
Telegram в первом прогоне не пишет, флаг `--notify` включает отправку. Потом:

```bash
.venv/bin/python -m jobsearch report --hours 72               # → data/reports/latest.html
.venv/bin/python -m jobsearch report --hours 72 --unchecked   # если модель ещё не подключена
open data/reports/latest.html                                 # Linux: xdg-open
```

В отчёте только то, что прошло модель с fit ≥ 4, по трекам. У каждой вакансии — заметка модели и пометки:
почему fit такой, что проверить. Если модель подключилась после прогона, `assess --days 3` оценит уже собранное;
такие вакансии видны в отчёте, а в Telegram не уходят. Пример карточек в Telegram:

```bash
.venv/bin/python -m jobsearch telegram-test --sample 3
```

## 8. Калибровка

Самое полезное, что можно сделать в первый день: посмотреть, что отсеялось.

```bash
.venv/bin/python -m jobsearch list --all --hours 72 --limit 300
```

У каждой вакансии видны score, трек и причины (все причины — в [HOW-IT-WORKS.md](HOW-IT-WORKS.md#4-отсев-и-пометки)).
Типичные исправления:

| видишь | правишь |
|---|---|
| нужной вакансии нет в базе вовсе | `title_include` (проверь `check --title "…"`) или добавь компанию через `discover` |
| отсеяна «заголовок на немецком» / «текст на …» / «нужен … язык» | `switches.languages`; `other_language: flag` или `any` |
| в отчёте чужая роль | `title_exclude` и `not_this_role` |
| «зарплата … < порога» | `switches.salary_min` |
| хорошая вакансия с низким fit | `summary`, `strengths`, `small_gap`; почитай заметку модели |
| вакансия в стране, которую ты бы рассмотрел, внизу | добавить страну в `switches.countries` |

После правок:

```bash
.venv/bin/python -m jobsearch check --fast
.venv/bin/python -m jobsearch reanalyze                  # пересчитать всё собранное; оценки модели сохраняются
.venv/bin/python -m jobsearch assess --again --days 3    # если правил summary/роль: переоценить моделью
```

`reanalyze` прячет вакансии, чей заголовок после правки фильтра больше не проходит, а `reanalyze --prune` удаляет их
из базы (кроме тех, где ты уже нажимал кнопку). Оценки модели `reanalyze` не пересчитывает — для этого `assess
--again`, он тратит подписку, поэтому только за указанный период.

## 9. Расписание

Выбери одно место: компьютер или сервер. Два расписания с одним ботом мешают друг другу — второй бот перехватывает
нажатия кнопок.

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
@reboot cd /home/anna/jobsearch && mkdir -p data/logs && PATH=$HOME/.local/bin:$PATH .venv/bin/python -m jobsearch bot >> data/logs/bot.log 2>&1
```

`PATH` с `~/.local/bin` нужен боту, чтобы найти `claude` для кнопки «CV под вакансию». Строка `@reboot` запускает
бота только после перезагрузки; сейчас — той же командой с `&` в конце. Если бот упал, cron его не поднимет:
перезапусти руками или перенеси всё на сервер.

### Свой сервер (VPS)

Подойдёт любой VPS с Ubuntu 22.04+ или Debian 12 и 2 ГБ памяти (Hetzner CX22 ~€4 в месяц). Нужен вход по
SSH-ключу под root. Удобнее всего завести для сервера короткое имя — тогда все команды ниже работают без лишних флагов:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vps         # если ключа ещё нет
ssh-copy-id -i ~/.ssh/id_ed25519_vps root@<ip>        # или добавь ключ при создании сервера
cat >> ~/.ssh/config <<EOF

Host jobsearch-vps
  HostName <ip>
  User root
  IdentityFile ~/.ssh/id_ed25519_vps
EOF
deploy/deploy.sh jobsearch-vps
```

`deploy.sh` копирует проект вместе с `my/` и `.env` в `/opt/jobsearch` и ставит:

- Python-окружение, прогоняет тесты;
- Claude CLI, если в `.env` есть `CLAUDE_CODE_OAUTH_TOKEN`, а `ANTHROPIC_API_KEY` пуст;
- LaTeX или LibreOffice — по формату резюме;
- systemd: прогоны каждые два часа с 08:15 до 22:15, глубокий ночью в 00:15, бот — постоянно (если в `.env` есть
  токен бота).

Часовой пояс — `JOBSEARCH_TZ` в `.env`. Ночные сообщения приходят без звука.

**Если уже были прогоны на компьютере**, сначала сними там расписание (`scripts/install_launchd.sh --remove` или
строки из `crontab -e`, и останови бота), потом перенеси базу — иначе первый серверный прогон пришлёт всё найденное
заново:

```bash
deploy/deploy.sh jobsearch-vps --with-db
```

`--with-db` снимает копию базы безопасно даже при работающем боте, на время копирования останавливает бота и
таймеры на сервере и запускает их снова. Без флага база на сервере не трогается.

На сервере:

```bash
ssh jobsearch-vps
systemctl start --no-block jobsearch.service           # прогон сейчас, не дожидаясь конца
tail -f /opt/jobsearch/data/logs/$(date +%F).log       # лог
systemctl list-timers | grep jobsearch                 # расписание
journalctl -u jobsearch-bot -f                         # бот
```

Если прогон упал или его остановил таймаут, бот пришлёт сообщение с хвостом лога.

Telegram-группы через аккаунт (шаг 4, «Telegram-каналы»): `TG_API_ID` и `TG_API_HASH` приедут с `.env`, а войти
нужно на самом сервере, от пользователя, под которым идут прогоны:

```bash
ssh -t jobsearch-vps 'cd /opt/jobsearch && sudo -u jobsearch .venv/bin/python -m jobsearch tg-login'
```

## 10. Каждый день

- Карточки приходят в Telegram. Кнопки: ✅ Откликнулся, ⏳ Позже, 🙈 Скрыть (сворачивает карточку в одну строку с
  кнопкой «Вернуть»).
- `/applied`, `/later`, `/interview` — списки; `/stats` — сколько всего; `/mark <id> rejected` — любой статус;
  `/cv <id>` — то же, что кнопка «CV под вакансию».
- «📄 CV под вакансию» присылает резюме, подстроенное под вакансию: тот же файл из `switches.cv` (DOCX, LaTeX или
  Markdown) с переставленными буллетами и навыками и отчётом, что изменено.
- Изменилась цель (другая страна, отказ от контрактов) — правь профиль, `check --fast`, `reanalyze`. Если всё
  работает на сервере, после правки — `deploy/deploy.sh jobsearch-vps`, а `reanalyze` там:
  ```bash
  ssh jobsearch-vps 'sudo -u jobsearch bash -c "cd /opt/jobsearch && .venv/bin/python -m jobsearch reanalyze"'
  ```

## 11. Обновить код

```bash
git pull
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest -q tests
deploy/deploy.sh jobsearch-vps          # если на сервере
```

`my/`, `.env` и `data/` обновление не трогает.

## Если что-то не так

| проблема | что делать |
|---|---|
| `настройка: нет my/profile.yaml` | шаг 2 |
| `настройка: …companies.yaml: YAML не разбирается` | в `my/companies.yaml` осталась строка `[]` перед дописанными компаниями — удали её |
| `LLM: недоступен` | шаг 6; на сервере проверь так: `ssh jobsearch-vps 'sudo -u jobsearch bash -c "cd /opt/jobsearch && set -a && . ./.env && ~/.local/bin/claude -p ok"'` — должно ответить |
| `Not logged in` в этой проверке | токен скопирован не целиком: заново `claude setup-token`, вставить руками, `deploy/deploy.sh jobsearch-vps` |
| в логе много `429` от LinkedIn | это волны ограничений на его стороне, бывают по 1–3 дня; следующие прогоны догонят пропущенное сами |
| расписание на Mac не запускается | проект лежит в `~/Documents` или подобной папке — перенеси, пересоздай `.venv`, переустанови расписание |
| «CV под вакансию» не меняет DOCX | `cv --inspect`: если разделы не нашлись, добавь их названия в `my/cv_bank.yaml` → `docx:` (CONFIG.md, «Резюме») |
| «CV под вакансию» падает с `pdflatex не установлен` | резюме `.tex` или `.md`, а LaTeX нет — шаг 2, «Резюме». На Mac, если LaTeX стоит, переустанови расписание (`scripts/install_launchd.sh … --bot`): бот из старой версии скрипта не знал путь `/Library/TeX/texbin` |
| бот не реагирует на кнопки | на сервере `systemctl status jobsearch-bot`; на Mac `scripts/install_launchd.sh … --bot`; не запущен ли второй бот на другом компьютере |
| в Telegram ничего | пустой дайджест — нормально; `list --last-run --all` покажет, что нашлось и почему не прошло |
| `database is locked` | база занята другим процессом подольше 30 секунд: `run` руками, пока идёт плановый, или `reanalyze` во время прогона |
