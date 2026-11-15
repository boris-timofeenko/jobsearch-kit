# Справочник настроек

Три файла твоих и один общий:

- `my/profile.yaml` — кто, какую роль, где. Обязательный.
- `my/config.yaml` — переопределения `config.yaml`. Слияние по ключам: `llm: {model_cli: opus}` меняет только
  модель; список заменяет список целиком.
- `.env` — секреты.
- `config.yaml` — общие значения по умолчанию, в git. Не правь его, иначе `git pull` будет конфликтовать.

Резюме и его банк — `my/cv.*` и `my/cv_bank.yaml`, ниже. Что из всего этого получается с вакансией —
[HOW-IT-WORKS.md](HOW-IT-WORKS.md).

После правок профиля: `.venv/bin/python -m jobsearch check --fast`, затем `.venv/bin/python -m jobsearch reanalyze`.

## Переключатели (`switches`)

Блок в начале `my/profile.yaml`: короткие ответы, которых хватает, чтобы начать. `python -m jobsearch init` в
терминале (без `--role`) задаёт их вопросами по одному. Переключатель главнее такого же поля ниже в профиле: если
они расходятся, `check` покажет «switches.X перекрывает …». Без блока `switches` профиль работает по-старому, через
поля `candidate` и `target`.

| переключатель | значения | что меняет |
|---|---|---|
| `goal` | `both` · `relocate` · `remote` | `relocate`: remote-вакансии не показываются, LinkedIn не ищет remote, remote-агрегаторы (Remotive, RemoteOK, We Work Remotely, Working Nomads, Himalayas, Jobicy) выключаются, если в `my/config.yaml` нет своего списка `aggregators`. `remote`: страны не используются, офисы не показываются (и `eu_offices` тоже), только remote по Европе. Источники, которые ищут по стране (hiring.cafe, поиск Workable, Adzuna), при `remote` молчат |
| `countries` | список кодов, первый — основная | страны переезда, у каждой свой трек; коды и пороги — `presets/countries.yaml`. Вместо кода можно словарь с переопределениями: `[{code: de, salary_floor_month: 4225}, nl]` |
| `eu_offices` | `true` · `false` | офис или гибрид в другой стране ЕС (трек `eu`); `false` — такие вакансии не показываются |
| `visa` | `needed` · `not_needed` | `not_needed`: «EU citizens only», «no sponsorship», требования разрешения на работу в ЕС не отсекают, реестр IND не проверяется, порог визы не применяется |
| `based_in` | страна по-английски | где живёшь: remote или любая вакансия «только для живущих в X» подходит, если X — эта страна (кроме требования её гражданства). Если страна в ЕС и цель не только переезд, LinkedIn отдельно ищет remote в ней |
| `languages` | список | рабочие языки; объявление на другом языке или с требованием другого языка — по `other_language` |
| `other_language` | `skip` · `flag` · `any` | `skip` — отсеять и объявления на незнакомом языке, и требование такого языка; `flag` — требование языка становится пометкой «язык: нужен …», а объявления целиком на незнакомом языке по-прежнему отсеиваются; `any` — по языку ничего не отсеивается, остаются пометки |
| `level` | `junior` · `mid` · `senior` · `lead` | senior и выше: junior отсеиваются, mid помечаются; mid: junior помечаются; junior: senior опускаются вниз |
| `salary_min` | `visa` · число · `0` | `visa`: порог визы страны из каталога, только в странах переезда; без визы — не отсекать. Число: свой минимум €/мес гросс для всех вакансий, включая remote. `0`: не отсекать по зарплате. Ниже 90% порога — отсев «зарплата ~€X < порога €Y», от 90 до 100% — пометка. Распознаются только суммы в евро; минимум по коллективному договору (Австрия) окладом не считается |
| `salary_target` | число | желаемый гросс €/мес: выше — плюс к score |
| `contract` | `penalize` · `skip` · `ok` | B2B, фриланс, почасовая ставка. `penalize`: явная почасовая ставка и фриланс с работой в офисе отсеиваются, остальной контракт −2 к fit (без штрафа, если виза обещана); `skip`: любые признаки контракта отсеиваются — до модели по тексту, после модели, если она видит контракт; `ok`: без отсева и штрафа |
| `outsourcing` | `penalize` · `skip` · `ok` | аутсорс и аутстафф (EPAM, Luxoft, BairesDev…), определяет модель: −1 к fit / отсев / ничего |
| `agencies` | `penalize` · `skip` · `ok` | рекрутер, работодатель не назван: −15 к score и −1 к fit / отсев / ничего |
| `public_sector` | `skip` · `ok` | госсектор, оборонка, допуск: отсев / только пометка |
| `ai` | `neutral` · `prefer` · `avoid` | роль про AI/LLM (поле модели `ai_role`): `prefer` +2/+2/+1 к fit (AI-first / AI в продукте / AI-инструменты), `avoid` −2/−1/0 |
| `cv` | путь или `none` | резюме: `.docx` и `.tex` — «CV под вакансию» в их же оформлении, `.md` — через встроенный шаблон, `.pdf`/`.txt` — только текст. Ниже, «Резюме» |

Отсевы, которые включает переключатель, подписаны «отсев по настройке: …» (кроме зарплаты и языка: у них своя
подпись), чтобы их было видно в `list --all`. Размер поправок можно задать числом в `target.fit_adjustments`
(`contractor`, `consultancy`, `agency`, `ai_first`, `ai_product`, `ai_tooling`): переключатель решает, есть ли
поправка, число — какая. Только `ok` у `contract`, `outsourcing`, `agencies` обнуляет штраф, какое бы число ни стояло.

## Резюме

| формат | «CV под вакансию» | автозаполнение форм | что нужно |
|---|---|---|---|
| `.docx` (Word, Google Docs → Файл → Скачать → .docx) | в твоём же оформлении: DOCX, плюс PDF, если есть LibreOffice | контакты, навыки, опыт; образование руками | для PDF — LibreOffice |
| `.tex` | PDF | всё, что есть в резюме | LaTeX |
| `.md` (формат — `presets/cv/example.md`) | PDF по шаблону `presets/cv/template.tex` | всё, что есть в резюме | LaTeX |
| `.pdf`, `.txt` | нет: экспортируй в DOCX или перепиши в Markdown | нет | — |

На сервере LaTeX или LibreOffice ставит `deploy.sh` по формату из `switches.cv`; на своём компьютере — сам
([SETUP.md](SETUP.md), шаг 2). Адрес, индекс, срок уведомления и другие ответы для форм, которых в резюме не бывает,
берутся из `autofill:` в `my/cv_bank.yaml`.

DOCX разбирается по заголовкам разделов: Summary / Profile / About, Skills, Experience (стиль «Заголовок» или
короткая строка жирным или капсом). Навыки — строки «Название: a, b, c». Роль — список буллетов после строк с
должностью и датами. Свои названия разделов (регулярные выражения, добавляются к обычным) и закреплённые буллеты —
в `my/cv_bank.yaml`:

```yaml
docx:
  summary: "кратко обо мне"
  experience: "where i worked"
pin: ["payout service"]          # буллеты с этими словами не скрываются
```

Что нашлось в резюме, показывает `.venv/bin/python -m jobsearch cv --inspect`. Правки пишутся только в изменённые
абзацы. Абзац, где внутри разное форматирование (жирное слово в буллете) или ссылка, не переписывается: правка
уходит в отчёт как «Отклонено проверкой». Буллеты переставляются и скрываются целиком, со своим стилем и нумерацией.
Если PDF вырос больше `cv.max_pages`, по одному убираются последние незакреплённые буллеты самой длинной роли; без
PDF (DOCX без LibreOffice) страницы не проверяются. В tex закрепление — `% cv:pin` в конце `\item`, в Markdown —
`<!-- pin -->`.

## my/cv_bank.yaml

Необязательный файл для «CV под вакансию» и автозаполнения. Без него резюме тоже подстраивается: модель только
переставляет куски и делает мелкие правки.

```yaml
headlines:                       # из каких заголовков резюме бот выбирает; без списка заголовок не меняется
  - Senior Backend Engineer
  - Senior Backend Engineer · Python, Kafka
skills:
  extra:                         # что можно добавить в строку навыков, если вакансия прямо это просит
    Backend: [gRPC, GraphQL]
  aliases:                       # вариант написания, если вакансия пишет именно так
    PostgreSQL: [Postgres]
synonyms:                        # слова, которыми модель может заменять друг друга в мелких правках
  - [end-to-end, E2E]
  - [led, managed]
relocation:                      # строки «где живу» и «право на работу» в шапке, по треку вакансии
  default: {location: "Located in Tbilisi, Georgia.", workauth: "Need a work permit."}
  de: {location: "Relocating to Germany.", workauth: "Eligible for the EU Blue Card."}
  eu: {location: "Open to relocation {to_country}."}
  countries:                     # для трека eu: страна из локации вакансии
    Ireland: {workauth: "Need a Critical Skills Employment Permit."}
docx: {summary: "...", skills: "...", experience: "..."}   # см. «Резюме»
pin: ["..."]                     # см. «Резюме», только DOCX
autofill:                        # ответы для формы отклика, которых нет в резюме
  address: "Example street 1"
  postal_code: "0105"
  notice_period: "1 month"
  available_from: 2027-01-01
  work_authorized: false
  heard_about: LinkedIn
  salary: {monthly: 6000, annual: 72000, text: "EUR 6,000 gross per month"}
  years: {skills: {python: 6, kafka: 3}}          # стаж по инструменту; иначе такие поля формы остаются пустыми
  # ещё: location, country, country_aliases, email, website, nationality, citizenship_country, date_of_birth,
  #      available_text, gender
```

Строки `relocation` подставляются в макросы `\cvlocation` / `\cvworkauth` (tex и md) или заменяют абзац резюме,
совпадающий с `relocation.default` (DOCX). Подстановки: `{to_country}` («to Germany» или «within the EU»),
`{country}`.

## my/profile.yaml

### candidate

| поле | что | по умолчанию |
|---|---|---|
| `name` | имя для файла CV | — |
| `summary` | резюме для модели: роль, годы, стек, домены, чего нет | обязательно |
| `languages` | рабочие языки (то же, что `switches.languages`) | обязательно |
| `seniority` | `junior` / `mid` / `senior` / `lead` (то же, что `switches.level`) | `senior` |
| `needs_visa` | нужна ли виза в ЕС (то же, что `switches.visa`) | `true` |
| `based_in` | страна, где живёшь (то же, что `switches.based_in`) | — |
| `citizenship_note` | одна фраза для модели | — |
| `birth_year` | для порогов «до 30 лет» (Нидерланды) | — |

### role

| поле | что |
|---|---|
| `name` | название роли для модели |
| `definition` | что считается этой ролью (поле модели `is_target_role`) |
| `not_this_role` | соседние роли и ложные совпадения: модель скажет «не та роль», вакансия отсеется |
| `strengths` | сильнейшие стороны: модель считает их весомым совпадением |
| `small_gap` | что для этой роли «мелкий пробел» на шкале fit 7–8 |
| `queries` | названия вакансий для LinkedIn, Adzuna, Bundesagentur, hiring.cafe; широкие первыми |
| `hiringcafe_queries` | свои запросы для hiring.cafe (иначе первые два `queries`) |
| `keywords` | короткие слова: поиск по сайтам крупных компаний и Workday, теги RemoteOK, поиск Workable, Remotive без категории |
| `categories` | категории досок: `remotive`, `jobicy`, `weworkremotely` (список), `themuse`, `remoteok` (теги), `workable` (запросы), `arbeitsagentur` (немецкие названия) |
| `title_include` | регэкспы: заголовок должен совпасть хотя бы с одним. Пусто — не проходит ничего (`check` скажет) |
| `title_exclude` | регэкспы: совпал — заголовок выброшен. Пусто — ничего не выбрасывается |
| `title_boost` | `{регэксп: баллы}` — слова ядра роли в заголовке, плюс к score; считается первый совпавший |
| `stack` | `{регэксп: вес}` — совпадения в тексте, плюс к score (до 20 в сумме) |
| `focus` | `[{name, regex, score, fit}]` — сильнейшие темы: score (по умолчанию 0) вне потолка stack, fit (0) — к итоговому fit; положительный — при fit модели ≥ 5, отрицательный — всегда |
| `penalties` | `[{name, regex, unless, score}]` — красные флаги в тексте вакансии: пометка и минус к score (по умолчанию 10) |
| `off_domain` | `{name, title, desc}` — «не тот домен» до модели (для QA — железо и производство); модель может снять этот отсев |

Регулярные выражения — Python, регистр не важен. В YAML пиши их в одинарных кавычках: `'\b(backend|api)\b'`.

### target

| поле | что | по умолчанию |
|---|---|---|
| `country` | основная страна: код из каталога, английское имя («Germany»), `{code: de, …переопределения}` или `none`. С `switches.countries` его задаёт первый код списка | — |
| `countries` | дополнительные страны переезда (коды или словари) | `[]` |
| `eu_offices` | офис в другой стране ЕС подходит (то же, что `switches.eu_offices`) | `true` |
| `remote` | искать remote по Европе (`switches.goal`) | `true` |
| `salary_floor_month` | порог зарплаты, если не задан у страны. Без визы и без `switches.salary_min` это свой минимум для всех вакансий | порог основной страны |
| `salary_target_month` | желаемый месячный гросс, € (то же, что `switches.salary_target`) | — |
| `remote_base` | откуда работать remote — для модели | `based_in` |
| `goal_note` | приоритеты своими словами — для модели, на fit не влияет | — |
| `fit_adjustments` | поправки к fit, ниже | |
| `location_penalty` | `{трек: штраф}`, отрицательное — бонус | считается сам |
| `track_label` | подпись трека основной страны | `label` из каталога |
| `remote_track_label`, `remote_entity_label` | подписи треков `remote` и `remote_nl` | «🌍 Remote EU», «🇳🇱🌍 Remote EU у компаний с NL-юрлицом в реестре IND» |

Поля страны (в каталоге и для переопределения): `name`, `label`, `city` (по нему модель оценивает «как будто
вакансия там», The Muse ищет по нему), `location_regex`, `salary_floor_month`, `salary_floor_under_30`,
`visa_scheme`, `sponsor_register` (`ind` только у Нидерландов), `geo` (без него страна не ищется на hiring.cafe),
`local_languages` (справочно: отсев по языку идёт по тексту самой вакансии — нидерландский, немецкий, французский).
Своя страна вне каталога описывается целиком: минимум `code`, `name`, `location_regex`.

Старая плоская форма тоже читается: поля основной страны прямо в `target` — `country: Netherlands`,
`location_regex`, `visa_scheme`, `sponsor_register`, `city`, `code`, `local_language` (`nl` / `de` / `none`).

#### Треки

Каждая вакансия попадает в один трек. По трекам разбиты отчёт и сводка прогона в Telegram; карточки в Telegram идут
по score.

| трек | что | `location_penalty` по умолчанию |
|---|---|---|
| код основной страны | вакансия в основной стране | −1 (бонус +1) |
| коды доп. стран | в дополнительной стране | 1 |
| `eu` | офис или гибрид в другой стране ЕС | 2 |
| `remote_nl` | remote у компании с NL-юрлицом в реестре IND | 2 |
| `remote` | remote в Европе | 3 (при `country: none` — 0) |
| `other` | вне ЕС и не remote | в отчёты не попадает |

#### fit_adjustments

Итоговый fit = fit модели (только совпадение роли) + поправки. Положительные применяются, только если модель дала
fit ≥ 5: бонус не вытаскивает слабую вакансию; отрицательные — всегда. Каждая поправка видна в карточке:
«fit: модель 7 −1 локация +2 виза явно = 8».

| ключ | когда | по умолчанию |
|---|---|---|
| `sponsorship_yes` | виза обещана в тексте явно (только если виза нужна) | 2 |
| `relocation_yes` | помощь с переездом без слова «виза» | 1 |
| `ai_first` | работа строится вокруг AI-агентов | 0 (`ai: prefer` → 2) |
| `ai_product` | роль делает или тестирует AI/LLM-функции | 0 (`ai: prefer` → 2) |
| `ai_tooling` | от роли ждут AI-инструментов | 0 (`ai: prefer` → 1) |
| `agency` | рекрутер, конечный работодатель не назван | −1 |
| `consultancy` | аутсорс, аутстафф, body leasing | −1 |
| `contractor` | B2B, фриланс, contract (0, если виза обещана) | −2 |
| `low_competition` / `low_competition_max` | ≤ N откликов на LinkedIn | 1 / 25 |
| `high_competition` / `high_competition_min` | ≥ N откликов | −1 / 150 |

Старые имена ключей тоже читаются: `ai_qa_first`, `ai_qa_product`, `ai_qa_tooling`, `hourly_contract`.

### Списки компаний

| поле | что |
|---|---|
| `known_companies` | `{applied, rejected, paused, planned}` (ключи любые) — пометка «уже в воронке: <ключ>», applied и rejected −30 к score, остальные −10 |
| `exclude_companies` | не показывать совсем, описания не грузятся |
| `agency_companies` | кадровые агентства: пометка «агентство/рекрутер» и −15 к score (при `agencies: penalize`) |
| `sponsor_aliases` | `{имя на доске: юрлицо в реестре IND}`, когда автосовпадение не срабатывает |

## my/config.yaml

Всё, чего здесь нет, берётся из `config.yaml` (там комментарии к ключам). Чаще всего меняют:

| ключ | что |
|---|---|
| `company_files` | списки досок: `my/companies.yaml`, `boards/curated.yaml`, `boards/nl-ind-sponsors.yaml`, `boards/de-large.yaml` |
| `aggregators` | агрегаторы в каждом прогоне. Свой список заменяет общий целиком; есть ещё `iamexpat`, `undutchables` (NL), `arbeitsagentur` (DE). Adzuna ищет только в основной стране и только если Adzuna там есть (из каталога — nl, de, be, fr, es, at, it, pl) |
| `aggregators_deep` | только в глубоком прогоне (по умолчанию `hiringcafe`) |
| `linkedin.enabled` | `false` — без LinkedIn |
| `linkedin.locations` | `[{name, remote, max_pages, queries}]`; по умолчанию — из `target`: основная страна (все запросы, 100 страниц), остальные страны и remote по ЕС (первые четыре запроса, 50 страниц) и, если живёшь в стране ЕС, remote в ней (30 страниц): общий поиск по ЕС упирается в 1000 карточек и теряет такие вакансии |
| `linkedin.queries` | по умолчанию `role.queries` |
| `linkedin.time_filter` | окно поиска, когда `run` запущен без `--time-filter` (неделя; дальше каждый запрос всё равно ищет не дальше 3 дней назад, `window_max`) |
| `hiringcafe.queries`, `hiringcafe.countries` | по умолчанию — из профиля |
| `hiringcafe.fresh_days`, `max_calls`, `jina_delay` | свежесть выдачи (21 день), потолок запросов на поиск (60), пауза резервного транспорта (3.5 с) |
| `tg_channels.channels` | каналы и группы Telegram с вакансиями: имена, `@имя` или ссылки `t.me/…` (по умолчанию пусто). Открытые каналы читаются без аккаунта, группы — после `tg-login`. SETUP.md, «Telegram-каналы» |
| `tg_channels.days` | первое чтение канала — за столько дней (30); посты старше на разбор не идут |
| `tg_channels.max_pages`, `extract_per_run` | потолок страниц веб-просмотра на канал за прогон (40, по ~20 постов) и постов на разбор моделью за прогон (200) |
| `telegram.min_fit` | порог fit для карточки (4); у отчёта порог всегда 4 |
| `telegram.max_per_company` | карточек от одной компании за прогон (2) |
| `telegram.summary_always` | сводка прогона даже без карточек (`true`) |
| `telegram.quiet_when_empty` | молчать совсем, если карточек нет (`false`) |
| `telegram.quiet_hours` | часы без звука (`"00:00-08:00"`) |
| `llm.enabled`, `llm.backend` | выключить модель; `auto` / `api` / `cli` / `off` |
| `llm.model_cli`, `llm.model_cli_country` | модели по подписке: для всех и для вакансий в странах переезда |
| `llm.model_api`, `llm.model_api_country` | то же для API |
| `llm.max_per_run` | не больше N оценок за прогон (300) |
| `llm.min_score_remote` | remote и `eu` идут к модели только от этого score (45) |
| `llm.skip_low_yield_after` | компания с N оценками и ни одной fit ≥ 4 к модели больше не идёт (20; 0 — выключить) |
| `cv.*` | «CV под вакансию»: `bank` (путь к `my/cv_bank.yaml`), `model_cli`/`model_api` (Opus), `max_edits` (5), `max_pages` (2); само резюме — `switches.cv` (`cv.source`, `cv.tex` — для профилей без переключателей) |

## .env

| ключ | что |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | бот и твой чат |
| `CLAUDE_CODE_OAUTH_TOKEN` | подписка Claude на сервере (`claude setup-token`) |
| `ANTHROPIC_API_KEY` (или `ANTHROPIC_AUTH_TOKEN`) | оплата по API вместо подписки; если задан, подписка не используется |
| `JOBSEARCH_TZ` | часовой пояс расписания и времени в сообщениях (`Europe/Amsterdam`) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | агрегатор Adzuna по основной стране |
| `JINA_API_KEY` (или `HC_JINA_KEY`) | резервный транспорт hiring.cafe, необязательно |
| `HC_CHROME` | `auto` · `on` · `off`: резервный транспорт hiring.cafe через настоящий Chrome. `auto` включает его, если на машине есть Chrome, Xvfb и утилиты; `on` — ещё и `deploy.sh` ставит их на сервер. В `.env.example` — `off` |
| `TG_API_ID`, `TG_API_HASH` | приложение на my.telegram.org для чтения Telegram-групп аккаунтом (`tg-login`); открытым каналам не нужны |
| `AMO_JWT_ISSUER`, `AMO_JWT_SECRET` | подпись браузерного расширения для Firefox |

Переменные окружения для запуска: `JOBSEARCH_MY` (другая папка вместо `my/`) и `JOBSEARCH_DATA` (вместо `data/`) —
например, два человека на одном сервере или тесты.

## Как считается score

Подробно, по слагаемым, — [HOW-IT-WORKS.md](HOW-IT-WORKS.md#6-score). Коротко: 40 + уровень в заголовке +
`title_boost` + спонсор IND + зарплата (сравнивается с желаемой и с порогом; у remote и `eu` порог — основной
страны) + `stack` (до 20) + `focus` − `penalties` − агентство − воронка, от 0 до 100 (у отсеянных не выше 25).
Remote и `eu` уходят к модели при score ≥ `llm.min_score_remote`. После модели итоговый score = 0.4 × эвристика +
6 × итоговый fit, без потолка.
