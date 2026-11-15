# Справочник настроек

Три файла твоих и один общий:

- `my/profile.yaml` — кто, какую роль, где. Обязательный.
- `my/config.yaml` — переопределения `config.yaml`. Слияние по ключам: `llm: {model_cli: opus}` меняет только
  модель; список заменяет список целиком.
- `.env` — секреты.
- `config.yaml` — общие значения по умолчанию, в git. Не правь его, иначе `git pull` будет конфликтовать.

После правок профиля: `python -m jobsearch check --fast`, затем `python -m jobsearch reanalyze`.

## Переключатели (`switches`)

Блок в начале `my/profile.yaml`: короткие ответы, которых хватает, чтобы начать. `python -m jobsearch init` в
терминале задаёт их вопросами по одному. Переключатель главнее такого же поля ниже в профиле: если они расходятся,
`check` покажет «switches.X перекрывает …». Без блока `switches` профиль работает по-старому, через поля
`candidate` и `target`.

| переключатель | значения | что меняет |
|---|---|---|
| `goal` | `both` · `relocate` · `remote` | `relocate`: remote-вакансии не показываются, LinkedIn не ищет remote, remote-агрегаторы (Remotive, RemoteOK, We Work Remotely…) выключены. `remote`: страны не используются, только remote по Европе |
| `countries` | список кодов, первый — основная | страны переезда, у каждой свой трек; коды и пороги — `presets/countries.yaml` |
| `eu_offices` | `true` · `false` | офис или гибрид в другой стране ЕС (трек `eu`); `false` — такие вакансии не показываются |
| `visa` | `needed` · `not_needed` | `not_needed`: «EU citizens only», «no sponsorship», требования разрешения на работу не отсекают; порог визы не применяется |
| `based_in` | страна по-английски | remote «только для жителей» этой страны подходит |
| `languages` | список | рабочие языки; объявление на другом языке или с требованием другого языка — по `other_language` |
| `other_language` | `skip` · `flag` · `any` | вакансия требует язык не из списка: `skip` — отсеять; `flag` — показать с пометкой «язык: нужен …» (объявления целиком на незнакомом языке всё равно отсеиваются); `any` — язык не учитывать вообще |
| `level` | `junior` · `mid` · `senior` · `lead` | senior и выше: junior отсеиваются, mid помечаются; mid: junior помечаются; junior: senior опускаются вниз |
| `salary_min` | `visa` · число · `0` | `visa`: порог визы страны из каталога, только в странах переезда (без визы — не отсекать); число: свой минимум €/мес гросс для всех вакансий, включая remote; `0`: не отсекать по зарплате. Ниже 90% порога — отсев, от 90 до 100% — пометка. Распознаются суммы в евро; минимум по коллективному договору (Австрия) окладом не считается |
| `salary_target` | число | желаемый гросс €/мес: выше — плюс к score |
| `contract` | `penalize` · `skip` · `ok` | B2B, фриланс, почасовая ставка. `penalize`: явная почасовая ставка и фриланс в офисе отсеиваются, остальной контракт −2 к fit; `skip`: любой контракт отсеивается (кроме вакансий с явной визой); `ok`: без отсева и штрафа |
| `outsourcing` | `penalize` · `skip` · `ok` | аутсорс и аутстафф (EPAM, Luxoft, BairesDev…), определяет модель: −1 к fit / отсев / ничего |
| `agencies` | `penalize` · `skip` · `ok` | рекрутер, работодатель не назван: −15 к score и −1 к fit / отсев / ничего |
| `public_sector` | `skip` · `ok` | госсектор, оборонка, допуск: отсев / только пометка |
| `ai` | `neutral` · `prefer` · `avoid` | роль про AI/LLM (поле модели `ai_role`): `prefer` +2/+2/+1 к fit (AI-first / AI в продукте / AI-инструменты), `avoid` −2/−1/0 |
| `cv` | путь или `none` | резюме: `.docx` и `.tex` — «CV под вакансию» в их же оформлении, `.md` — через встроенный шаблон, `.pdf`/`.txt` — только текст. Ниже, «Резюме» |

Отсевы, которые включает переключатель, подписаны «отсев по настройке: …», чтобы их было видно в `list --all`.
Размер штрафа можно задать числом в `target.fit_adjustments` (`contractor`, `consultancy`, `agency`): переключатель
решает, есть ли штраф, число — какой. `ok` обнуляет штраф, какое бы число ни стояло.

## Резюме

| формат | «CV под вакансию» | автозаполнение форм | на сервере ставится |
|---|---|---|---|
| `.docx` (Word, Google Docs → Файл → Скачать → .docx) | в твоём же оформлении: DOCX, плюс PDF, если есть LibreOffice | контакты, навыки, опыт; образование руками | LibreOffice Writer |
| `.tex` | PDF | всё | TeX Live |
| `.md` (формат — `presets/cv/example.md`) | PDF по шаблону `presets/cv/template.tex` | всё | TeX Live |
| `.pdf`, `.txt` | нет: экспортируй в DOCX или перепиши в Markdown | нет | — |

DOCX разбирается по заголовкам разделов: Summary / Profile / About, Skills, Experience (стиль «Заголовок» или
короткая строка жирным или капсом). Навыки — строки «Название: a, b, c». Роль — список буллетов после строк с
должностью и датами. Другие названия разделов задаются в `my/cv_bank.yaml`:

```yaml
docx:
  summary: "кратко обо мне"
  experience: "where i worked"
pin: ["payout service"]          # буллеты с этими словами не скрываются
```

Что нашлось в резюме, показывает `python -m jobsearch cv --inspect`. Правки пишутся только в изменённые абзацы.
Абзац, где внутри разное форматирование (жирное слово в буллете) или ссылка, не переписывается: правка уходит в
отчёт как «Отклонено проверкой». Буллеты переставляются и скрываются целиком, со своим стилем и нумерацией.

`my/cv_bank.yaml` необязателен для любого формата: варианты заголовка (`headlines`), навыки, которые можно добавить
под вакансию (`skills.extra`), синонимы для мелких правок, строки про локацию и визу по трекам (`relocation`). Формат
— в `AGENTS.md`, раздел «CV под вакансию».

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
| `keywords` | короткие слова: поиск по сайтам крупных компаний, теги RemoteOK, Workable search, Remotive без категории |
| `categories` | категории досок: `remotive`, `jobicy`, `weworkremotely` (список), `themuse`, `remoteok` (теги), `workable` (запросы), `arbeitsagentur` (немецкие названия) |
| `title_include` | регэкспы: заголовок должен совпасть хотя бы с одним |
| `title_exclude` | регэкспы: совпал — заголовок выброшен |
| `title_boost` | `{регэксп: баллы}` — слова ядра роли в заголовке, плюс к score |
| `stack` | `{регэксп: вес}` — совпадения в тексте, плюс к score (до 20 в сумме) |
| `focus` | `[{name, regex, score, fit}]` — сильнейшие темы: score вне потолка stack, fit — к итоговому fit при fit модели ≥ 5 |
| `penalties` | `[{name, regex, unless, score}]` — красные флаги в тексте: пометка и минус к score |
| `off_domain` | `{name, title, desc}` — «не тот домен» до модели (для QA — железо и производство); модель может снять этот отсев |

Регулярные выражения — Python, регистр не важен. В YAML пиши их в одинарных кавычках: `'\b(backend|api)\b'`.

### target

| поле | что | по умолчанию |
|---|---|---|
| `country` | основная страна: код из `presets/countries.yaml`, `{code: de, …переопределения}` или `none` (то же, что первый код `switches.countries`) | — |
| `countries` | дополнительные страны переезда (коды или словари) | `[]` |
| `eu_offices` | офис в другой стране ЕС подходит (то же, что `switches.eu_offices`) | `true` |
| `remote` | искать remote по Европе (`switches.goal`) | `true` |
| `salary_floor_month` | порог, если не задан у страны | порог основной страны |
| `salary_target_month` | желаемый месячный гросс, € | — |
| `remote_base` | откуда работать remote — для модели | `based_in` |
| `goal_note` | приоритеты своими словами — для модели, на fit не влияет | — |
| `fit_adjustments` | поправки к fit, ниже | |
| `location_penalty` | `{трек: штраф}`, отрицательное — бонус | считается сам |
| `track_label`, `remote_track_label`, `remote_entity_label` | подписи треков в отчёте и Telegram | из каталога |

Поля страны (в каталоге и для переопределения): `name`, `label`, `city`, `location_regex`, `local_languages`,
`salary_floor_month`, `salary_floor_under_30`, `visa_scheme`, `sponsor_register` (`ind` только у Нидерландов),
`geo`. Своя страна вне каталога описывается целиком: минимум `code`, `name`, `location_regex`.

#### Треки

Каждая вакансия попадает в один трек, по нему сортируются отчёт и Telegram:

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
fit ≥ 5: бонус не вытаскивает слабую вакансию. Каждая поправка видна в карточке: «fit: модель 7 −1 локация +2 виза
явно = 8».

| ключ | когда | по умолчанию |
|---|---|---|
| `sponsorship_yes` | виза обещана в тексте явно | 2 |
| `relocation_yes` | помощь с переездом без слова «виза» | 1 |
| `ai_first` | работа строится вокруг AI-агентов | 0 |
| `ai_product` | роль делает или тестирует AI/LLM-функции | 0 |
| `ai_tooling` | от роли ждут AI-инструментов | 0 |
| `agency` | рекрутер, конечный работодатель не назван | −1 |
| `consultancy` | аутсорс, аутстафф, body leasing | −1 |
| `contractor` | B2B, фриланс, contract (0, если виза обещана) | −2 |
| `low_competition` / `low_competition_max` | ≤ N откликов на LinkedIn | 1 / 25 |
| `high_competition` / `high_competition_min` | ≥ N откликов | −1 / 150 |

### Списки компаний

| поле | что |
|---|---|
| `known_companies` | `{applied, rejected, paused, planned}` — пометка «уже в воронке», applied/rejected −30 к score |
| `exclude_companies` | не показывать совсем, описания не грузятся |
| `agency_companies` | кадровые агентства: пометка и минус к score |
| `sponsor_aliases` | `{имя на доске: юрлицо в реестре IND}`, когда автосовпадение не срабатывает |

## my/config.yaml

Всё, чего здесь нет, берётся из `config.yaml` (там комментарии к каждому ключу). Чаще всего меняют:

| ключ | что |
|---|---|
| `company_files` | списки досок: `my/companies.yaml`, `boards/curated.yaml`, `boards/nl-ind-sponsors.yaml`, `boards/de-large.yaml` |
| `aggregators` | агрегаторы в каждом прогоне; есть ещё `iamexpat`, `undutchables` (NL), `arbeitsagentur` (DE) |
| `aggregators_deep` | только в глубоком ночном прогоне (по умолчанию `hiringcafe`) |
| `linkedin.locations` | `[{name, remote, max_pages, queries}]`; по умолчанию — из `target`: страны, remote по ЕС и, если живёшь в стране ЕС, remote в ней (общий поиск по ЕС упирается в 1000 карточек и теряет такие вакансии) |
| `linkedin.queries` | по умолчанию `role.queries` |
| `hiringcafe.queries`, `hiringcafe.countries` | по умолчанию — из профиля |
| `telegram.min_fit` | порог fit для карточки (4) |
| `telegram.max_per_company` | карточек от одной компании за прогон (2) |
| `telegram.quiet_hours` | часы без звука (`"00:00-08:00"`) |
| `llm.backend` | `auto` / `api` / `cli` / `off` |
| `llm.model_cli`, `llm.model_cli_country` | модели по подписке: для всех и для вакансий в целевых странах |
| `llm.model_api`, `llm.model_api_country` | то же для API |
| `llm.max_per_run` | не больше N оценок за прогон (300) |
| `llm.min_score_remote` | remote и `eu` идут к модели только от этого score (45) |
| `cv.*` | «CV под вакансию»: `bank` (путь к `my/cv_bank.yaml`), модель, число правок, страниц; само резюме — `switches.cv` |

## .env

| ключ | что |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | бот и твой чат |
| `CLAUDE_CODE_OAUTH_TOKEN` | подписка Claude на сервере (`claude setup-token`) |
| `ANTHROPIC_API_KEY` | оплата по API вместо подписки |
| `JOBSEARCH_TZ` | часовой пояс расписания и времени в сообщениях (`Europe/Amsterdam`) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | агрегатор Adzuna по основной стране |
| `JINA_API_KEY` | резервный транспорт hiring.cafe, необязательно |
| `HC_CHROME` | `on` — на сервер ставится Chrome для обхода Cloudflare у hiring.cafe |
| `AMO_JWT_ISSUER`, `AMO_JWT_SECRET` | подпись браузерного расширения для Firefox |

Переменные окружения для запуска: `JOBSEARCH_MY` (другая папка вместо `my/`) и `JOBSEARCH_DATA` (вместо `data/`) —
например, два человека на одном сервере или тесты.

## Как считается score

Эвристика до модели: 40 + уровень в заголовке (senior/lead +12 для senior-кандидата) + `title_boost` + спонсор IND
(+15, при нечётком совпадении +8) + зарплата (выше цели +10, выше порога +4, ниже −20) + `stack` (до 20) + `focus`
− `penalties` − агентство 15 − воронка. Remote и `eu` уходят к модели при score ≥ `llm.min_score_remote`. После
модели итоговый score = 0.4 × эвристика + 6 × итоговый fit.
