# AGENTS.md — как устроен jobsearch и почему так

Для агента или человека, который дорабатывает код. Порядок чтения: этот файл → `my/profile.yaml` владельца (кто он,
какая роль и страны) → `docs/CONFIG.md` (все поля). Объяснение логики для пользователя, без кода, —
`docs/HOW-IT-WORKS.md`: при правке правил обновляй и его. Настройка под нового человека — скилл
`.claude/skills/jobsearch-setup`, ручная — `docs/SETUP.md`.

Проект вырос из личного поиска senior QA с переездом в Нидерланды (сентябрь–ноябрь 2026) и обобщён на любые
IT-роли и страны ЕС. Правила откалиброваны на ~31 тыс. реальных вакансий того поиска; цифры и даты ниже — оттуда.

## Назначение и треки

Несколько раз в день собрать вакансии по роли владельца, дёшево отсеять шум, спорное оценить моделью по полному
тексту, прислать в Telegram только новое и прошедшее проверку, всё сложить в SQLite.

Треки (`jobs.track`), порядок в отчёте и Telegram:
- код основной страны (`target.country`, например `nl` или `de`) — переезд туда. Для Нидерландов работодатель
  сверяется с реестром признанных спонсоров IND.
- коды дополнительных стран (`target.countries`) — тоже переезд, свой трек у каждой.
- `eu` — офис или гибрид в любой другой стране ЕС/ЕЭЗ (`filters.EU_LOC`). Модель переводит сюда remote-вакансию,
  если по тексту она офисная.
- `remote_nl` — remote у компании с NL-юрлицом в реестре IND (заход через remote-найм; только когда IND включён).
- `remote` — остальной remote в Европе.
- `other` — вне ЕС и не remote. В отчёты не попадает.
Порядок определения: страна из списка → remote (если не только для не-ЕС) → EU по локации → other.
При `target.country: none` основной страны нет, remote идёт первым.

## Структура

```
jobsearch/
  config.py       где лежат файлы владельца (my/, data/), сборка конфига, каталог стран, проверки (`check`)
  cli.py          команды; cmd_run — весь конвейер; load_cfg = config.load + configure() всех модулей
  filters.py      эвристики: заголовок, язык, уровень, спонсорство, зарплата, треки, score; configure(profile)
  llm.py          рубрика (шаблон RULES_TEMPLATE), Assessment (pydantic), бэкенды api/cli, apply_assessment
  sponsors.py     реестр IND: загрузка, нормализация имён, сопоставление (точное / префиксное «≈»)
  sources/        linkedin.py (гостевой поиск), ats.py (ATS и корпоративные сайты), aggregators.py,
                  expat_boards.py (iamexpat, undutchables), hc_chrome.py (резервный транспорт hiring.cafe)
  db.py           SQLite: jobs, coverage (когда поиск LinkedIn последний раз дошёл до конца)
  http.py         requests.Session: темп, повтор после 429, счётчики ответов
  report.py       markdown/html отчёты, карточки Telegram, подписи и порядок треков
  notify.py       Telegram sendMessage, .env
  bot.py          long-polling бот: кнопки статусов, команды, «CV под вакансию»
  cvgen.py        CV под вакансию: разбор tex, план модели (CvPlan), проверка правок, pdflatex
  discover.py     поиск ATS-доски компании по вариантам слага; массовый перебор с проверкой локации
  autofill.py     profile.json для браузерного расширения автозаполнения (tex, md, docx)
  cv_docx.py      резюме в DOCX: разбор по разделам, запись правок в документ, PDF через LibreOffice
  cv_markdown.py  резюме в Markdown → tex по presets/cv/template.tex
  wizard.py       вопросы `init` в терминале → блок switches
presets/          roles/*.yaml (пресеты ролей), countries.yaml (каталог стран), cv/ (шаблон и пример Markdown), примеры для `init`
boards/           общие списки досок: curated (отобранные), nl-ind-sponsors, de-large
my/               (не в git) profile.yaml, config.yaml, companies.yaml, cv.docx|tex|md, cv_bank.yaml
data/             (не в git) jobs.db, sponsors.json, reports/, logs/, runs.log, .run.lock, .run.state
deploy/           deploy.sh (rsync + install), install-server.sh, run-server.sh, systemd-юниты
scripts/          run-local.sh, install_launchd.sh (Mac), package-skill.sh (архив скилла для claude.ai)
discovery/        списки имён для массового `discover --file` (de_large.txt)
extension/        WebExtension автозаполнения форм отклика (Firefox MV3)
tests/            pytest; fixtures/my — QA-профиль, на котором калибровались правила
```

## Конфигурация

`config.load()` склеивает `config.yaml` (общие значения, в git) с `my/config.yaml` (deep merge, список заменяет
список), читает `my/profile.yaml` и нормализует `target`: код страны разворачивается из `presets/countries.yaml`
(город, регэксп локации, порог зарплаты, визовая схема, реестр, координаты; `local_languages` только справочно —
ни одно правило его не читает), поля профиля поверх. Плоский
формат прежней однопользовательской версии (`country: Netherlands`, `location_regex`, `track_label` прямо в
`target`) тоже читается. `salary_floor_under_30` берётся вместо `salary_floor_month`, если `candidate.birth_year`
моложе 30 лет.

Из профиля выводится то, что не задано в `my/config.yaml`: `linkedin.queries` = `role.queries`; `linkedin.locations`
(`config.default_linkedin_locations`) = основная страна (все запросы, до 100 страниц) + каждая доп. страна (первые
четыре запроса, 50 страниц) + при `target.remote` «European Union» remote (то же) и remote в стране
`candidate.based_in`, если она в ЕС/ЕЭЗ (30 страниц; общий поиск по ЕС упирается в 1000 карточек); `hiringcafe.queries`
и `countries` (только страны с `geo` в каталоге: без них hiring.cafe страну пропускает, при `goal: remote` стран нет
вовсе). Без `target.remote` и без своего `aggregators` из списка агрегаторов убираются `REMOTE_ONLY_AGGREGATORS`.
Затем `cli.load_cfg` вызывает `configure()` у `filters`, `llm`, `report`, `ats`, `aggregators`: модули держат
правила в глобальных переменных и пересобирают их из профиля целиком — пустое поле значит «пусто», а не встроенные
QA-значения, с которыми модули стартуют (`title_exclude: []` — без исключений, `stack: {}` — без очков).

`JOBSEARCH_MY` / `JOBSEARCH_DATA` переносят `my/` и `data/` (тесты используют `tests/fixtures/my` и временную папку).

**Переключатели.** `switches` в начале профиля — короткие ответы (варианты — `config.SWITCH_VALUES`; `countries`,
`eu_offices`, `based_in`, `languages`, `salary_min`, `salary_target`, `cv` разбираются отдельно); `config.apply_switches`
раскладывает их в `candidate`, `target`, `target.fit_adjustments` и `profile["prefs"]` до нормализации стран.
Переключатель главнее такого же поля ниже, расхождение попадает в `profile["_notes"]` и печатается `check`; неверное
значение — в `_problems`. Без блока действуют `config.DEFAULT_PREFS` — поведение, на котором калибровались правила
(регрессия 15.11 на снимке боевой базы, 34 678 вакансий: профиль без `switches` даёт тот же результат, что опубликованная версия, до строки; `other_language: flag` + `contract: ok` на тех же данных открывают 1 428 отсеянных, из них с fit модели ≥ 4 — 98).
`filters.configure` держит переключатели в `LANG_MODE`, `CONTRACT`, `AGENCIES`, `OUTSOURCING`, `PUBLIC_SECTOR`,
`SALARY_MIN`, `REMOTE_OK`, `EU_OFFICES`; `llm.apply_assessment` читает их оттуда. Отсев по переключателю подписан
`filters.SETTING` («отсев по настройке: …»), пометка вместо отсева начинается не со слова из `llm.SKIP_PREFIXES`
(«язык: нужен …», «ставка …», «ты живёшь в …», «не по роли: …»), иначе `rescuable` приняла бы её за отсев. Трек,
который цель исключает (remote при `goal: relocate`, `eu` при `eu_offices: false` или `goal: remote`), даёт
`verdict=other` (`filters.out_of_goal`): вакансия хранится, но не оценивается и не отправляется; после модели
проверка повторяется, потому что модель может перевести remote в `eu`. Числа в `fit_adjustments`, заданные руками,
главнее значений переключателей (`setdefault`); только `ok` у `contract`/`outsourcing`/`agencies` обнуляет штраф.
`init` без `--role` в терминале или с `--ask` (`wizard.py`) задаёт переключатели вопросами и пишет ответы в блок,
сохраняя комментарии.

Роль целиком в `role`: `name`/`definition`/`not_this_role`/`strengths`/`small_gap` — текст рубрики;
`queries`/`keywords`/`categories` — поиск; `title_include`/`title_exclude` — фильтр заголовков;
`title_boost`/`stack`/`focus`/`penalties` — score; `off_domain` — отсев «не тот домен», который модель может снять.
Всё, что раньше было зашито под QA (правило «железо», «только ручное тестирование», бонус SDET в заголовке, ключевые
слова корпоративных сайтов, категории агрегаторов), теперь живёт в `presets/roles/qa.yaml`.

## Конвейер прогона (`cli.cmd_run`)

1. **Сбор.** LinkedIn (`sources/linkedin.search`): по 10 карточек на страницу, до `max_pages`, ранний стоп после
   `idle_pages` (5) страниц подряд без заголовка по роли. `--deep` снимает потолки: все запросы, 100 страниц, без
   раннего стопа. Окно поиска у каждого запроса своё (`search_window`): не меньше `--time-filter` и до начала его
   последнего полного поиска из таблицы `coverage` плюс `window_margin` (2 ч на позднюю индексацию), не больше
   `window_max` (3 дня). Пропущенный, оборванный или убитый прогон дыры не оставляет. Запрос, на котором LinkedIn
   перестал отвечать (`complete=False`), покрытым не считается. Бюджеты `search_budget_min` (fast 70, deep 340 мин)
   и три оборванных запроса подряд останавливают поиск, оставшиеся ждут следующего прогона. Сортировку по дате
   гостевой поиск игнорирует, поэтому «листать до известной» нельзя.
   Доски компаний (`collect_boards`, 8 потоков, своя сессия на поток): заголовок по роли + локация в целевой стране,
   ЕС, remote или пустая (`filters.in_search_area`; регэкспы стран тоже, потому что Personio и Teamtailor пишут один
   город). Дубли одной роли по городам схлопываются (`merge_duplicates`). Агрегаторы — `aggregators`, медленные и
   ночные — `aggregators_deep`.
2. **Дедуп по id.** Известные id получают `last_seen` и дальше не идут.
3. **Описания** (`fetch_descriptions`): LinkedIn detail, Workday, Teamtailor, SmartRecruiters, Bundesagentur,
   hiring.cafe, schema.org JobPosting корпоративных сайтов. Основная страна первой, лимит `detail_fetch_limit` и
   бюджет `detail_budget_min`. Для `exclude_companies` не грузится. Описания грузятся и копиям: дедуп по отпечатку
   идёт после эвристик, ему нужны вердикт и текст.
4. **Эвристики** (`filters.analyze`, `safe_analyze` ловит исключения).
5. **Дедуп по отпечатку** (`mark_duplicates`): `Job.fingerprint()` (компания + заголовок без «(m/w/d)» и хвостов)
   против базы и разобранных в этом прогоне → `verdict=dup`, к оригиналу дописывается город, и оригинал из того же
   прогона разбирается заново, чтобы трек учёл новый город. Оригинал, закрытый эвристиками, прошедшую копию не
   поглощает. Посредники, скрывающие работодателя (`filters.PARTNER_LISTING`, Jobgether), публикуют роли разных
   клиентов под одним заголовком: для них дубль — только при похожем тексте (`same_posting`, difflib ≥ 0.85).
6. **Backfill**: старые записи без описания (`backfill_limit`) дозагружаются, разбираются заново и вместе с новыми
   идут к модели (`refreshed`). Затем `skip_low_yield` закрывает компании без шансов.
7. **LLM** (`llm.select_candidates` → `assess_many` → `apply_assessment`).
8. **Запись**, отчёт после прогона (`report.write_reports` без `stamp`: `<YYYY-MM-DD>.{md,html}`, второй прогон за
   день перезаписывает, + `latest.html`; вакансии за `--report-days`, по умолчанию 14, на сервере 1; файл
   `<дата-время>-lastrun` пишет только `report --last-run`), Telegram по `fresh` (новые и refreshed этого прогона, с
   оценкой, `llm_fit >= telegram.min_fit`; сводка — по `summary_always` / `quiet_when_empty`; `notified=1`
   ставится, если ушли все карточки), `runs.log`.
Каждая стадия записи коммитит: бот пишет клики в ту же SQLite (WAL, busy timeout 30 с).

Время: быстрый прогон ~13 минут (LinkedIn 6–7, описания 3–7, LLM 1–5), deep 40–80.

**LinkedIn и 429.** С 10.10.2026 гостевой API волнами по 1–3 дня отвечает 429 примерно на 20% запросов, без
`Retry-After`; волны не зависят от нашего объёма. Длинные паузы превращали быстрый прогон в 2–5 часов, поэтому
сейчас 429 стоит 8–15 с × номер попытки (до 5 попыток), темп замедляется не больше чем вдвое. Счётчики — в логе,
в сводку Telegram — только если были 429 или запросы без ответа.

## Доски компаний

ATS со слаговыми API (`ats.FETCHERS`): greenhouse, lever, ashby, recruitee, workable (виджет, все вакансии одним
запросом), smartrecruiters (страницами по 100; доска больше 500 — поиском по `role.keywords`), teamtailor
(`jobs.rss`: полный список с городами и текстом), personio. Поиском по `role.keywords` (`ats.KEYWORDS`), а не
целиком, читаются workday (до 5 страниц по 20 на слово; `total` только на первой странице; «3 Locations»
раскрывается запросом к вакансии) и корпоративные сайты: `rmk` (SAP SuccessFactors), `beesite` (Milch & Zucker),
`phenom` (POST `/widgets`, минимальное тело).

`discover "Name"` пробует варианты слага на восьми слаговых ATS (`discover.PROBES`: без workday, rmk, beesite,
phenom). Массовый перебор: `discover --file names.txt --area <код>` (код разворачивается в регэксп только для стран
из профиля, иначе строка сама считается регэкспом: `--area de` без Германии в target ищет подстроку «de»)
(или `--from-ind --all --limit 0 --area nl` по всему реестру IND, ~2 ч в 48 потоков): доска остаётся, только если на
ней есть вакансия с локацией в стране — одноимённые чужие компании и пустые доски отсеиваются сами. Вариант «первое
слово» в массовом переборе не пробуется (находит чужие компании). Перебор с одного IP приводит Workable к 429 на
сутки: гонять с ноутбука, не с сервера и не накануне прогона. Списки в `boards/` собраны так 06.11.2026.

## Эвристики (`filters.py`)

Скип с причиной (`reasons`), ничего не удаляется:
- язык: текст на нидерландском/немецком/французском (`detect_lang`, частотность стоп-слов), заголовок на
  нидерландском/немецком/другом европейском — если языка нет в `candidate.languages` (правило «не английский
  заголовок» выключается, когда кандидат знает другой европейский язык). Обязательный другой язык по тексту
  (`dutch_required`, `other_language_required` — только языки, которых нет у кандидата); предложения со словами
  plus/preferably/nice to have игнорируются, разбор по `sentences()` с делением по переносам строк. Двуязычные
  объявления (`mixed:nl`, `mixed:de`, `mixed:fr`) не режутся, если заголовок не нидерландский и не немецкий: пометка,
  язык решает модель; требование языка в их тексте (`dutch_required`, `other_language_required`) всё равно
  проверяется. Всё языковое — по `other_language` (`LANG_MODE`).
- уровень: от `candidate.seniority` (junior 0 … lead 3). Senior+: junior-заголовок — скип, medior — пометка −10.
  Mid: junior — пометка −10. Junior: senior-заголовок −15, junior +12.
- clearance / оборонка / гос; `exclude_companies`.
- `role.off_domain` — «не тот домен» (для QA — железо и производство: самое склонное к ложным срабатываниям правило).
  Такие скипы уходят к модели, и если она говорит `is_target_role`, скип снимается (`llm.rescuable`).
- без спонсорства (`NO_SPONSOR`, только при `needs_visa`; аудит 12.09: 23 срабатывания, все верные). «Must be based
  in …» (`LOCAL_ONLY`) закрывает только remote; требование часового пояса («located in or able to work within CEST
  time zone», `TIME_ZONE`) — только пометка; для стран переезда и `eu` — пометка, если `residency_blocks` не
  видит признаков закрытости (only при кандидатах/жителях, currently/already, гражданство и разрешения на нескольких
  языках, local hiring / local candidates, EU/EEA, visa/sponsor/relocat, outside / won't be considered, другая
  страна или место вне ЕС в цитате; для `eu` ещё «fully remote» — `REMOTE_JOB`). Требование жить в стране
  `candidate.based_in` (`filters.lives_there`: и в `NO_SPONSOR`, и в `residency_blocks`) не мешает, если в цитате нет
  гражданства, nationality или passport. Без визы (`needs_visa: false`) гражданство, разрешения, спонсорство и цитата
  только про ЕС («EU citizens only») не считаются.
- freelance on-site; зарплата ниже 90% порога страны (`parse_salary` не считает окладом суммы после слов budget /
  relocation / allowance / bonus… — в том числе когда метка на отдельной строке, «Relocation support⏎: up to
  €2,500», — суммы в миллионах и минимум по коллективному договору, который по закону пишут австрийские объявления,
  `COLLECTIVE_MINIMUM`; аудит 25.09 по 300 отсевам, тестовая настройка 15.11); ближе к порогу — пометка. Распознаются
  только суммы в евро.
- явная оплата за час или день (`pay_rate`: сумма в валюте на час/день, не компенсация, без окладной альтернативы;
  калибровка 24.09 по 11 тыс. объявлений). Иначе — мягкая пометка «почасовая/дневная ставка или контракт».

Пометки без скипа: агентство (по тексту или `agency_companies`, −15), «уже в воронке», «компания не найдена в
реестре IND», hybrid/office в remote-вакансии (решает модель), `role.penalties`, фокус (`role.focus`: score вне
потолка стека, fit — после модели).

Score: 40 + уровень + `title_boost` (первый совпавший) + спонсор IND 15 (8 при «≈») + зарплата (≥ цели +10, ≥ порога
+4, ниже −20; порог у remote и `eu` — основной страны) + стек до 20 + фокус − `penalties` − агентство 15 − воронка
(applied/rejected 30, прочие 10) − medior 10 − «описание не загружено» 5; от 0 до 100, у отсеянных не выше 25.
Бонусов за страну в score нет: география учитывается ровно один раз — поправкой к fit после модели. Итог после
модели: `0.4·score + 6·fit`, без потолка, чтобы порядок наверху держался.

Реестр IND (только при `needs_visa` и стране с `sponsor_register: ind`): `data/sponsors.json`, 30 дней. `normalize()` убирает юридические и географические слова. Совпадение
точное, иначе префиксное или нечёткое ≥ 0.92 — такие помечаются «≈». `sponsor_aliases`, когда имя на доске не
совпадает с юрлицом.

## LLM-стадия (`llm.py`)

Компании с 20+ оценками и лучшим итоговым fit < 4 (без статусов владельца, не в `known_companies`) на модель больше
не идут (`skip_low_yield_after`). Кандидаты (`select_candidates`): `verdict=live` или отсев только по `off_domain`;
страны и `remote_nl` всегда, `remote` и `eu` — от `min_score_remote`; описание ≥ 300 символов; `other` — никогда.
Лимит `max_per_run`; порядок: все страны переезда, `eu`, `remote_nl`, `remote`, внутри — по score. Текст режется
до 6000 символов.

Рубрика — шаблон `RULES_TEMPLATE`, `configure()` подставляет роль, уровень, город основной страны, визовые
формулировки. Главное правило: fit 0–10 измеряет **только** совпадение роли (стек, уровень, тип работы, домен), «как
будто вакансия в <city>, работодатель спонсирует визу, зарплата и режим подходят». Страну, визу, тип работодателя
и найма модель в fit учитывать не должна: без этого она занижала fit за «не та страна». Сначала — основной язык или
технология роли: чего нет в профиле, то чужой стек, не больше 5–6 (до этого C#/.NET-вакансия получала 7 у
Python/TS-кандидата). Цели кандидата идут отдельным блоком после правил с пометкой «на fit не влияют».

Ответ — `Assessment`: is_target_role, seniority, residency_restriction (цитата), language_requirement, work_mode,
remote_scope, sponsorship, relocation, pay_basis, ai_role (ai_first/product/tooling/none), salary_month_eur,
is_agency, employer_type (direct/consultancy/recruiter/unknown), employment (employee/contractor/unknown), fit,
verdict, note. При `employer_type: unknown` и `is_agency` тип выводится из эвристики «агентство».
Оценки QA-версии в базе (`is_software_qa`, `ai_qa`, `automation_level`) читаются через `legacy_fields`.
«unknown»/null в полях да/нет — значение по умолчанию (модель так отвечала, и вакансии оставались без оценки).
Отсутствующий `verdict` выводится из fit; обрезанный JSON восстанавливается (`extract_json`), один повтор.

`apply_assessment`: skip за «не та роль», резидентство (через `residency_blocks`), язык, которого нет у кандидата
(`language_gap`: альтернатива «Ukrainian or Russian» или «German (or English)» закрывается одним известным языком;
«German and English» — нет; только при `other_language: skip`, иначе пометка), уровень junior для senior+, явный
отказ в визе для страны переезда (при `needs_visa`), почасовая оплата (если `contract` не `ok`), и по переключателям
со значением `skip`: рекрутер (`agencies`), аутсорс (`outsourcing`), контракт (`contract`, кроме явно обещанной визы). Голый `verdict=skip` модели — лишь пометка «слабое соответствие». remote → `eu`/`other`, если
модель видит офис.

Итоговый fit = fit модели + поправки (`target.fit_adjustments`, `location_penalty`, `role.focus`): локация, виза явно
+2 или переезд +1 (только если в тексте есть слова про визу/переезд — `VISA_TEXT`: модель читала строку «Спонсор
IND по реестру» как обещание), AI-бонусы, фокус, рекрутер −1, аутсорс −1, контракт −2 (без штрафа при явной визе),
конкуренция по откликам. Значения по умолчанию (`config.default_location_penalty`, `llm.FIT_ADJ_DEFAULT`):
основная страна +1, доп. страны −1, `eu` и `remote_nl` −2, `remote` −3 (при цели remote — 0), виза +2 (только при
`needs_visa`), переезд +1, AI 0/0/0 (`ai: prefer` 2/2/1, `avoid` −2/−1/0). Положительные — только при fit модели
≥ 5: бонус не вытаскивает слабую роль; отрицательные — всегда. Верхнего
предела нет: «fit 12/10» — модель 9 плюс бонусы. Разложение — в пометке «fit: модель 7 −1 локация +2 виза явно = 8».

Бэкенды (`pick_backend`, `llm.backend: auto|api|cli|off`, `llm.enabled`): `ApiBackend` (SDK `messages.parse`, system
с cache_control) при `ANTHROPIC_API_KEY` или `ANTHROPIC_AUTH_TOKEN`, иначе `CliBackend` (`claude -p --system-prompt …
--tools "" --no-session-persistence`, `stdin=DEVNULL`), если проверочный вызов `claude` прошёл. `assess` оценивает
собранное без оценки; `assess --again --days N` переоценивает и оценённое, сначала заново прогнав эвристики. Замер CLI/sonnet:
~3k токенов, ~6 с на вакансию; без `--system-prompt`/`--tools ""` было ~135k токенов на вызов. Результаты пишутся
по мере оценки, прерывание ничего не теряет.

## Отчёты, Telegram, бот

`report --last-run` / отчёт после `run`: `verdict='live'`, есть оценка, `llm_fit ≥ 4` (всегда 4, не
`telegram.min_fit`), не `ignored`, группы по трекам. `--unchecked` — все live, кроме скрытых, независимо от оценки;
`--all` — всё.

Telegram: первым сообщением сводка прогона (собрано, новых, по трекам; `summary_always`, `quiet_when_empty`),
затем карточка на вакансию с кнопками — только новые и refreshed этого прогона с fit ≥ `telegram.min_fit`, по score,
не больше `max_per_company` (2) от компании (аутстафф публикует одну роль под разными заголовками) и 40 за прогон;
`notified=1` ставится, если ушли все. Оценённое командой `assess` не отправляется. В `quiet_hours` — без звука.

Бот (`bot.py`): long-polling `getUpdates` по IPv4 (через IPv6 у Hetzner обновления приходили с опозданием 20–40 с,
и Telegram отвергал ответы на нажатия). callback_data `m:<status>:<rowid>`. Реагирует только на `TELEGRAM_CHAT_ID`. Кнопки: applied, later, ignored («Скрыть»
сворачивает карточку в строку с кнопкой «Вернуть»), «CV под вакансию»; команды `/applied`, `/later`, `/interview`,
`/stats`, `/mark <id> <статус> [заметка]`, `/cv <id>`.
После каждого апдейта откатывает незавершённую транзакцию (упавший клик оставлял BEGIN, и бот видел базу на тот
момент до перезапуска). «CV под вакансию» собирается в фоновом потоке, по одному за раз. Юниту бота нужен
`~/.local/bin` в PATH для `claude`.

## CV под вакансию (`cvgen.py`, `cv_docx.py`, `cv_markdown.py`)

Резюме — `switches.cv` (иначе `cv.source` / `cv.tex` в конфиге), формат по расширению (`config.cv_source`):
- `.tex` — как есть. Точки подстройки: макросы `\cvheadline`, `\cvlocation`, `\cvworkauth`, `\cvkeywords`, абзац
  после `\cvsection{SUMMARY}` (с начала строки, не в комментарии), строки `\skillrow{…}{…}`, `\item` внутри
  `duties`; `% cv:pin` — буллет не скрывается. Ключевые слова вакансии уходят в `\cvkeywords` (свойства PDF).
- `.md` — `cv_markdown.convert` переводит в tex по `presets/cv/template.tex` (те же макросы), дальше путь `.tex`.
  Формат — `presets/cv/example.md`; `<!-- pin -->` = `% cv:pin`. Автозаполнение тоже работает через этот tex.
- `.docx` — `cv_docx.parse` раскладывает документ в ту же `cvgen.Cv` (заголовок = абзац, равный одному из
  `headlines` банка; summary, навыки «Метка: a, b», роли = буллеты после строк-заголовков в разделе Experience;
  разделы ищутся по заголовкам, другие названия — `cv_bank.docx`). Модель получает тот же промпт, `apply_plan` —
  те же проверки. `cv_docx.render` пишет в документ только изменённое: буллеты двигаются и удаляются целыми
  абзацами (стиль и нумерация остаются), новый текст идёт в run, где он начинался, если хвост абзаца в одном
  форматировании; иначе (жирное слово, ссылка, поле) правка отклоняется и попадает в отчёт. Нетронутые абзацы не
  переписываются. Закрепление — подстроки `pin:` в банке; ключевые слова — в свойства документа. PDF — LibreOffice
  (`cv_docx.to_pdf`, свой профиль на вызов): тогда приходят и PDF, и DOCX, без него — только DOCX; лимит страниц
  проверяется только при PDF. `cv --inspect` печатает, что нашлось.
- `.pdf`, `.txt` — только текст для профиля; кнопка объясняет, как получить DOCX или Markdown.

Модель (по умолчанию Opus) возвращает `CvPlan`, `apply_plan` применяет и отбрасывает лишнее: заголовок только из
`headlines`, s1 всегда первым, навыки только переставляются, добавляются из `skills.extra`, если вакансия их
упоминает, и заменяются вариантом из `skills.aliases`; правки текста (`check_edit`, не больше `cv.max_edits`) — без
новых цифр и чужих слов (в summary можно слова из навыков и заголовков), длина 0.8–1.3 от исходной, похожесть ≥ 0.75
после сведения синонимов. Если страниц больше `cv.max_pages`, `trim_one` по одному скрывает последний незакреплённый
буллет самой длинной роли (до 12 раз). Строки «Located in» / «Work authorisation» (`relocation_lines`):
`relocation.<трек>`, для `eu` — `relocation.eu` и `relocation.countries.<страна из локации>`, иначе `default`;
подстановки `{to_country}`, `{country}`; в DOCX заменяются абзацы, равные `relocation.default`. Кэш
`data/cv/<компания>-<хэш>.json` со списком файлов, хэш от `VERSION`, байтов резюме, банка, id и текста вакансии и
модели; при смене логики поднять `VERSION`. Формат банка — `docs/CONFIG.md`, «my/cv_bank.yaml». До 15.11 в `build_for_job` трек вакансии затирал подстроенное резюме (`t`), и
кнопка падала на первом клике: сквозной тест `tests/test_cv_build.py` с подставной моделью ловит такое.

## hiring.cafe

Ночной источник (`aggregators_deep`): официальный read-only MCP (`/api/mcp`, `search_jobs`, `get_job_details`), без
аккаунта. Пагинации нет (до 25 на ответ): после страницы, упёршейся в лимит, следующая идёт без её работодателей, а
они перечитываются пачкой через `company_names`. Ищет только по странам профиля с `geo` в каталоге (при
`goal: remote` — ничего). Цепочка при пустом или ошибочном ответе: Chrome под Xvfb (`sources/hc_chrome.py`,
`HC_CHROME=auto|on|off`: `auto` включает, если на машине есть google-chrome, Xvfb, xdotool, scrot, xclip и pillow;
`on` ещё и ставит их через `install-server.sh`; решает Cloudflare кликом по чекбоксу, истина в пикселях кадра, не в
титуле окна) → Jina Reader (`/classic?searchState=…`) → официальный ChatGPT MCP. Сбой hiring.cafe не задевает
остальные источники. Офлайн-тесты всех fallback — `tests/test_sources.py`.

## Сервер и расписание

`deploy/deploy.sh <хост> [--with-db]` — rsync проекта (с `my/` и `.env`, без `data/` и `.venv`) в `/opt/jobsearch`;
с `--with-db` ещё снимок `data/jobs.db` (`sqlite3 .backup`) заменяет серверную базу при остановленных боте и
таймерах (стёрты `-wal`/`-shm`: копия поверх открытой WAL-базы видна как пустая); затем
`install-server.sh`: пакеты, пользователь `jobsearch`, venv, тесты, Claude CLI (если `CLAUDE_CODE_OAUTH_TOKEN` и нет
API-ключа), LaTeX (резюме .tex/.md) или LibreOffice (резюме .docx), Chrome (если `HC_CHROME=on`), systemd с часовым поясом из `JOBSEARCH_TZ`.
`run-server.sh fast|deep`: flock на `data/.run.lock`, fast = `--time-filter r14400 --notify` (в 08 — `r36000`),
deep = `--deep --time-filter r43200 --notify`; `timeout` 3 ч / 7,5 ч, код 124 приходит в Telegram. Пропуск из-за
занятого lock — одно сообщение на долгий прогон. `--report-days 1`: серверный отчёт за сутки. Таймеры: fast
08,10,…,22:15, deep 00:15, `Persistent=true`. При
смене `OnCalendar` с `Persistent=true` systemd сразу запускает «пропущенный» слот: после такого деплоя
`touch /var/lib/systemd/timers/stamp-<таймер>` и `systemctl restart <таймер>`.

Mac: `scripts/install_launchd.sh [часы…] [--bot] [--remove]` генерирует LaunchAgents под текущую папку (по умолчанию
9, 13, 18 в :05; `--bot` — бот с KeepAlive; в PATH бота `/Library/TeX/texbin`, иначе MacTeX не виден и CV из .tex/.md
не собирается). `scripts/run-local.sh` (Mac и cron): окно `r86400`, первый прогон после
12:00 — `--deep`, замок `data/.run.lock.d` (старше 8 ч считается брошенным) вместо flock, которого на Mac нет. launchd не читает `~/Documents`,
`~/Desktop`, `~/Downloads` (TCC) — скрипт отказывается ставить расписание оттуда.

Токен подписки для сервера (`claude setup-token`) копируется руками: вывод идёт через Ink с кодом сброса цвета
внутри строки, и при автоматическом захвате терялась буква префикса.

## Тесты

`pytest -q tests`. `conftest.py` подставляет `tests/fixtures/my` (QA-профиль калибровки) и временную `data/`.
`test_switches.py` — каждый переключатель и его взаимодействие с полями профиля; `test_cv_docx.py` и
`test_cv_build.py` — разбор и запись DOCX, сквозная сборка CV во всех форматах с подставной моделью;
`test_config.py` — нормализация стран, все пресеты (заполненность, регэкспы, заголовки ✅/❌, рубрика без
незаполненных полей), виза/резидентство/языки/уровни, `init`/`check`.

Проверка скилла настройки (15.11): два выдуманных друга (frontend с паспортом ЕС и DOCX-резюме; data из
Казахстана, только переезд, резюме только в PDF), отдельный агент на Opus в свежем клоне по `SKILL.md`, ответы за
друга. Оба дошли до первого прогона (922 и 477 вакансий), переключатели совпали с заранее записанными ответами.
Найденное тогда исправлено: метка зарплаты на отдельной строке, минимум по коллективному договору, часовой пояс как
«требование жить», пометки про IND у гражданина ЕС, устаревшие заголовки после `reanalyze`, PATH бота под cron.

Регрессия при правке правил: снимок базы (`sqlite3 'file:jobs.db?mode=ro' '.backup …'`), `reanalyze` старым и
новым кодом на двух копиях, сравнение `verdict/track/score/llm_fit/reasons` построчно. Так проверялось обобщение
07.11.2026: на 31 019 вакансиях отличались 19, все — исправленные языковые альтернативы.

## Что не делать

- Не возвращать потолок 80 карточек LinkedIn (терял до 85% remote-выдачи) и не снимать ограничения EU-локации в
  быстром режиме (24 запроса × 1000 карточек = 50 минут). Deep для этого есть.
- Не возвращать долгие паузы после 429 и не считать поиск покрытым, если LinkedIn оборвал выдачу.
- Не убирать `stdin=DEVNULL` у CLI-бэкенда: `claude -p` приклеивает stdin к промпту.
- Не запускать два `run`/`assess` параллельно: одна SQLite.
- После правок `filters.py` или профиля: `pytest -q tests`, затем `reanalyze`.
- Не зашивать в код ничего про конкретную роль или страну: роль — `presets/roles/`, страна — `presets/countries.yaml`.
- Indeed/Glassdoor/StepStone/Nationale Vacaturebank/JOIN/Monster (антибот), XING (robots.txt), EURES (почти нет
  английских), поиск SmartRecruiters (игнорирует локацию) не подключать.
- Отдельные LinkedIn-запросы под узкую технологию не добавлять: гостевой поиск нестрогий и отдаёт обычную выдачу
  роли; узкие темы поднимает `role.focus`.
- Пустой дайджест — норма: в Нидерландах из ~270 QA-вакансий в неделю две трети на нидерландском, живых у
  спонсора 10–15.
