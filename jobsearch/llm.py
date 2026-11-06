"""LLM assessment of each posting by its full description.

Backends (config `llm.backend`, default `auto`):
  api  - Anthropic SDK, structured output via messages.parse (needs ANTHROPIC_API_KEY in env or .env)
  cli  - local `claude -p` (needs the CLI to be logged in: run `claude` in a terminal, then /login)
"""
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import company_key

PROFILE = "Кандидат: профиль не настроен (my/profile.yaml)."

# The rubric is a template: configure() fills the role, the candidate's level and the target from my/profile.yaml.
# Its core (fit measures the role match only, everything about place, visa, employer and contract is priced in by
# code) was calibrated on a QA profile in September-October 2026; see AGENTS.md "LLM-стадия".
RULES_TEMPLATE = """Оцени вакансию строго по тексту. Правила:
- fit 0-10 измеряет ТОЛЬКО совпадение роли с кандидатом: стек, уровень, тип работы, домен. Оценивай так, будто
  вакансия находится в {city}, {visa_assume}зарплата и режим работы подходят: страна, город, офис или remote, виза,
  зарплата, тип работодателя (продукт, аутстафф, рекрутер) и тип найма (штат или контракт) на fit НЕ влияют — для них
  есть отдельные поля, их учитывает код. Если у роли есть основной язык программирования или ключевая технология,
  определи её первой: если её нет в профиле кандидата, это не мелкий пробел, а чужой стек. Шкала: 9-10 — стек,
  уровень и домен совпадают почти полностью; 7-8 — сильное совпадение с 1-2 мелкими пробелами ({small_gap});
  5-6 — частичное (основной язык роли чужой при похожем типе работы, или половина стека чужая, или уровень
  ниже/выше); 3-4 — слабое; 0-2 — не та роль.{strengths}
- is_target_role=true, если это роль «{role_name}»: {role_definition}. Не та роль (false): {not_this_role}.
- residency_restriction: процитируй, если вакансия закрыта для того, кто переезжает: гражданство, уже имеющееся право
  на работу или разрешение, отказ в спонсорстве или релокации, проживание с «only», «currently», «already», «local
  candidates» ("EU citizens only", "no visa sponsorship", "right to work in the UK", "Poland-based candidates only").
  Для вакансии в целевой стране и для офисной или гибридной вакансии в ЕС простое «based in <страна или город
  вакансии>» или «remote within <эта страна>» — не ограничение: кандидат переезжает туда; упомяни это в note. Для
  remote-вакансии, открытой только жителям одной страны, — ограничение. Общие фразы про "eligible to work" без
  страны — null.
- language_requirement: обязательный язык кроме английского (Dutch, German, French, Polish...). "Nice to have" — null.
- work_mode: remote / hybrid / onsite по тексту; remote_scope — откуда можно работать ("EU", "Poland only", "worldwide").
  onsite только если текст явно требует присутствия в офисе. Если упомянуты remote или hybrid как опция, или режим не
  указан для вакансии с пометкой remote — remote/unknown.
- sponsorship: yes — явно обещана помощь с визой или разрешением на работу (visa sponsorship, work permit, Blue Card,
  HSM/kennismigrant); no — явно отказано; иначе unknown. relocation: true — явно обещана помощь с переездом
  (relocation package, support или bonus), даже без слова «виза». Оба поля — только по тексту вакансии: {sponsor_hint}
  то, что компания крупная, обещанием не считается.
- pay_basis: hourly или daily — только если в тексте прямо названа оплата за час или за день (€/час, zł/h, day rate);
  если рядом есть оклад на выбор (UoP, employment, permanent) — salary; контракт, B2B или фриланс без названной
  ставки — unknown. Компенсации за день (питание, работа из дома) — не оплата.
- ai_role: ai_first — работа в этой роли строится вокруг AI, и текст говорит это прямо: AI-first / AI-native /
  agentic подход, AI-агенты как основной способ работы («direct AI agents daily», «from script-first to AI-native»).
  Общие слова — «passionate about leveraging AI», «explore how AI can help», «drive the use of AI tools» — это
  tooling, не ai_first; «AI» в названии продукта (AI Gateway, AI platform) без AI в самой работе роли — none или
  product; product — роль сама делает, тестирует или исследует AI/LLM-функции продукта (LLM, агенты, RAG, модели,
  evals, безопасность промптов); tooling — от роли прямо ждут применения AI-инструментов как обязанность или
  требование, но это не основа роли; none — иначе, в том числе «компания делает AI-продукт» без AI-задач в этой роли
  и дежурное «используем Copilot / AI tools». Если подходят несколько — бери первый по списку.
- seniority по требованиям (годы опыта, лидерство), не только по заголовку. Уровень кандидата — {level}; вакансия
  ниже его уровня — понижение fit.
- is_agency: вакансия не от конечного работодателя. employer_type уточняет: direct — продуктовая компания или in-house
  команда: нанимает к себе и работает над своим продуктом или сервисом (банк, ритейлер, SaaS — тоже direct);
  consultancy — IT-сервисы, аутсорс, аутстафф, nearshore, body leasing: ставят на проекты клиентов (EPAM, Luxoft, Sii,
  BairesDev, Capgemini, Sogeti, Exadel), даже если оформляют в штат; recruiter — кадровое агентство, маркетплейс или
  посредник ищет для клиента, сам не нанимает (Hays, Harnham, Jobgether, Mission.dev, Toptal, «our client», «on behalf
  of»); unknown — не понять.
- employment: employee — трудовой договор с работодателем или его юрлицом (permanent или fixed-term; через employer of
  record — тоже employee); contractor — B2B, фриланс, independent contractor, «contract role» на срок через агентство
  или аутстафф; unknown — не сказано. Выбирай contractor только по прямым словам текста.
- verdict: apply (стоит откликаться), maybe, skip. skip ТОЛЬКО по причинам: не та роль, {skip_reasons}обязательный
  язык, уровень сильно ниже кандидата, локация вне ЕС без remote.
- note: одна-две фразы по-русски: суть роли и главный риск/что проверить. Без общих слов. Страну упоминай, только если
  с ней связан риск для визы или remote.{note_scheme}"""
RULES = ""

TAIL = ("Ты оцениваешь вакансии для этого кандидата. Не рассуждай вслух и не пиши ничего до или после ответа: "
        "сразу один JSON-объект без markdown.")
GOAL = ""
SYSTEM = PROFILE + "\n\n" + TAIL


KNOWN_LANGS = {"english", "russian"}
LOCATION_PENALTY = {"nl": -1, "eu": 2, "remote_nl": 2, "remote": 3, "other": 3}
# AI bonuses are 0 unless the profile sets them (target.fit_adjustments): how much AI in the role matters is personal
FIT_ADJ = {"sponsorship_yes": 2, "relocation_yes": 1, "ai_first": 0, "ai_product": 0, "ai_tooling": 0, "agency": -1,
           "consultancy": -1, "contractor": -2, "low_competition": 1, "low_competition_max": 25, "high_competition": -1,
           "high_competition_min": 150}
LEGACY_FIT_KEYS = {"ai_qa_first": "ai_first", "ai_qa_product": "ai_product", "ai_qa_tooling": "ai_tooling",
                   "hourly_contract": "contractor"}
CONTRACT_FLAGS = ("почасовая", "похоже на контракт")   # heuristic reasons from filters: contract/B2B/freelance wording
FOCUS_FIT = {}             # profile role.focus: name -> fit bonus for postings flagged "фокус: <name>" by filters
NEEDS_VISA = True          # candidate.needs_visa
SPONSOR_REGISTER = False   # some target country has a public sponsor register (IND): the prompt shows the match
# The visa/relocation bonus needs these words in the posting itself: models read "Спонсор IND по реестру" in the
# prompt as a promise (CGI, Creative Clicks, Lemonade got sponsorship=yes with no such words, A/B 24.09).
VISA_TEXT = re.compile(r"\b(visas?|sponsor\w*|work permits?|permit to work|blue card|kennismigrant|highly skilled migrant|"
                       r"relocat\w*|verhuiz\w*|umzug|déménagement|immigration)\b", re.I)
GOAL_NOTE = ""
LEVEL_RU = {"junior": "junior", "mid": "middle", "senior": "senior", "lead": "lead / senior"}
LANG_ALIASES = {"english": ["english", "англ"], "russian": ["russian", "рус"], "dutch": ["dutch", "nederlands", "нидерланд", "голланд"],
                "german": ["german", "deutsch", "немец"], "french": ["french", "français", "француз"],
                "spanish": ["spanish", "español", "испан"], "italian": ["italian", "итальян"], "polish": ["polish", "поль"],
                "portuguese": ["portuguese", "португал"], "serbian": ["serbian", "серб"], "greek": ["greek", "греч"],
                "czech": ["czech", "чеш"], "hungarian": ["hungarian", "венгер"], "romanian": ["romanian", "румын"],
                "swedish": ["swedish", "швед"], "danish": ["danish", "дан"], "finnish": ["finnish", "финс"],
                "lithuanian": ["lithuanian", "литов"], "hebrew": ["hebrew", "иврит"], "turkish": ["turkish", "турец"],
                "ukrainian": ["ukrainian", "украин"], "norwegian": ["norwegian", "норв"], "estonian": ["estonian", "эстон"],
                "latvian": ["latvian", "латыш"]}


# Two languages next to each other joined only by "or", "/", "and/or" (a level in brackets may sit between):
# "Ukrainian or Russian", "German (B1, or English)", "Dutch/French". "German and English, ideally B2 or above" and
# "B2/C1 English" are not alternatives.
ALT_JOIN = re.compile(r"^[\s,(]*(?:[abc][12]\+?[\s,]*)?(?:and/or|or|/|или|либо)[\s(]*$")


def language_gap(requirement):
    """The model reports required languages as free text. Skip only for a language the candidate lacks:
    a posting asking for Russian is a match, not a blocker, when Russian is in the profile; one known language of
    an alternative ("Ukrainian or Russian") is enough."""
    if not requirement:
        return ""
    low = requirement.lower()
    hits = sorted({(m.start(), m.end(), lang) for lang, words in LANG_ALIASES.items() for w in words
                   for m in re.finditer(re.escape(w), low)})
    mentioned = {lang for _, _, lang in hits}
    if not mentioned:
        return requirement             # unrecognised wording: keep the old cautious behaviour
    if not mentioned - KNOWN_LANGS:
        return ""                      # every language named is one the candidate has
    groups = [{hits[0][2]}]
    for (_, end, _), (start, _, lang) in zip(hits, hits[1:]):
        if ALT_JOIN.match(low[end:start]) or lang in groups[-1]:
            groups[-1].add(lang)
        else:
            groups.append({lang})
    missing = set().union(*(g for g in groups if not g & KNOWN_LANGS)) - KNOWN_LANGS
    return ", ".join(sorted(missing))


def _goal(c, t):
    """Candidate's goals for the rubric: context for sponsorship, residency and note, never for fit."""
    primary, extra = t.get("primary"), t.get("countries") or []
    needs_visa = c.get("needs_visa", True)
    lines = ["Цели кандидата — контекст для sponsorship, residency_restriction и note; на fit они не влияют."]
    floor = t.get("salary_floor_month")
    money = (f", зарплата не ниже €{floor}/мес гросс" if floor else "") + \
            (f" (цель €{t['salary_target_month']}+)" if t.get("salary_target_month") else "")
    if primary:
        how = (f" по схеме {primary['visa_scheme']}" if needs_visa and primary.get("visa_scheme") else "")
        sponsor = (", работодатель должен быть признанным спонсором"
                   if needs_visa and primary.get("sponsor_register", "none") != "none" else "")
        lines.append(f"Основная цель: работа в {primary['name']}{how}{sponsor}{money}.")
    if extra:
        lines.append("Дополнительные страны (отдельные треки, тоже переезд): " + ", ".join(
            f"{x['name']}" + (f" ({x.get('visa_scheme', '')}, порог ~€{x.get('salary_floor_month', '?')}/мес)"
                               if needs_visa else "") for x in extra) + ".")
    base = t.get("remote_base") or c.get("based_in") or "текущая страна проживания"
    if t.get("remote", True):
        lines.append(f"{'Запасной трек' if primary or extra else 'Основная цель'}: remote, база — {base}."
                     + ("" if primary or extra else money))
    if not needs_visa:
        lines.append("Виза в ЕС кандидату не нужна (гражданство ЕС/ЕЭЗ): sponsorship и relocation — только информация, "
                     "требование гражданства ЕС или права на работу в ЕС — не ограничение.")
    if GOAL_NOTE:
        lines.append(GOAL_NOTE)
    return " ".join(lines[:1]) + "\n" + " ".join(lines[1:])


def configure(profile):
    """Build the candidate profile and the rubric from the normalized profile (config.load)."""
    global PROFILE, RULES, SYSTEM, KNOWN_LANGS, LOCATION_PENALTY, FIT_ADJ, GOAL_NOTE, GOAL, FOCUS_FIT, NEEDS_VISA
    global SPONSOR_REGISTER
    from .config import default_location_penalty
    c, r, t = profile.get("candidate", {}), profile.get("role", {}), profile.get("target", {})
    if "primary" in t:
        LOCATION_PENALTY = {**default_location_penalty(t), **{k: int(v) for k, v in (t.get("location_penalty") or {}).items()}}
    adj = {LEGACY_FIT_KEYS.get(k, k): int(v) for k, v in (t.get("fit_adjustments") or {}).items()}
    FIT_ADJ = {**FIT_ADJ, **adj}
    GOAL_NOTE = (t.get("goal_note") or "").strip()
    FOCUS_FIT = {f["name"]: int(f.get("fit", 0)) for f in r.get("focus") or []}
    if c.get("languages"):
        KNOWN_LANGS = {x.lower() for x in c["languages"]}
    NEEDS_VISA = bool(c.get("needs_visa", True))
    countries = ([t["primary"]] if t.get("primary") else []) + list(t.get("countries") or [])
    SPONSOR_REGISTER = NEEDS_VISA and any(x.get("sponsor_register", "none") == "ind" for x in countries)
    if not c.get("summary"):
        return
    based = f" Живёт: {c['based_in']}." if c.get("based_in") else ""
    PROFILE = (f"Кандидат: {c['summary'].strip()}\nЯзыки: {', '.join(c.get('languages', []))}; других языков нет. "
               f"{c.get('citizenship_note', '')}{based}").strip()
    primary = t.get("primary")
    city = (primary or {}).get("city") or (primary or {}).get("name") or "удобном для кандидата месте ЕС"
    strengths = (r.get("strengths") or "").strip()
    RULES = RULES_TEMPLATE.format(
        city=city,
        visa_assume="работодатель спонсирует визу, а " if NEEDS_VISA else "",
        small_gap=(r.get("small_gap") or "другой инструмент того же типа; другой домен").strip(),
        strengths=(f" Сильнейшие стороны кандидата — {strengths.rstrip('.')}: если вакансия их просит, это весомое "
                   f"совпадение." if strengths else ""),
        role_name=(r.get("name") or "целевая роль").strip(),
        role_definition=(r.get("definition") or "работа, описанная в профиле кандидата").strip().rstrip("."),
        not_this_role=(r.get("not_this_role") or "другие профессии").strip().rstrip("."),
        sponsor_hint="строка «Спонсор IND по реестру» и" if SPONSOR_REGISTER else "",
        level=LEVEL_RU.get(str(c.get("seniority") or "senior").lower(), "senior"),
        skip_reasons=("резидентство/право на работу без спонсорства, явный отказ в визовой поддержке для on-site "
                      "вакансии, " if NEEDS_VISA else "требование жить в другой стране для remote, "),
        note_scheme=(f" Визовую схему {primary['visa_scheme']} упоминай только для вакансий в {primary['name']}."
                     if primary and NEEDS_VISA and primary.get("visa_scheme") else ""),
    )
    GOAL = _goal(c, t)
    SYSTEM = PROFILE + "\n\n" + RULES + "\n\n" + GOAL + "\n\n" + TAIL


PROMPT = """Вакансия:
Компания: {company}
Заголовок: {title}
Локация: {location}
Источник: {source}
{sponsor_line}Текст вакансии:
{desc}
"""


class Assessment(BaseModel):
    is_target_role: bool = True
    seniority: Literal["junior", "mid", "senior", "lead", "unknown"] = "unknown"
    residency_restriction: Optional[str] = None
    language_requirement: Optional[str] = None
    work_mode: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    remote_scope: Optional[str] = None
    sponsorship: Literal["yes", "no", "unknown"] = "unknown"     # visa / work permit
    employment: Literal["employee", "contractor", "unknown"] = "unknown"
    relocation: bool = False                                      # help with moving, visa not necessarily named
    pay_basis: Literal["salary", "hourly", "daily", "unknown"] = "unknown"
    ai_role: Literal["ai_first", "product", "tooling", "none"] = "none"
    salary_month_eur: Optional[float] = None
    is_agency: bool = False
    employer_type: Literal["direct", "consultancy", "recruiter", "unknown"] = "unknown"
    fit: int = Field(ge=0, le=10)
    verdict: Optional[Literal["apply", "maybe", "skip"]] = None   # models sometimes drop it; derived from fit
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def legacy_fields(cls, data):
        """Assessments stored by the QA-only version: is_software_qa and ai_qa were renamed, automation_level dropped."""
        if isinstance(data, dict):
            data = dict(data)
            if "is_software_qa" in data and "is_target_role" not in data:
                data["is_target_role"] = data["is_software_qa"]
            if "ai_qa" in data and "ai_role" not in data:
                data["ai_role"] = data["ai_qa"]
            for k in ("is_software_qa", "ai_qa", "automation_level"):
                data.pop(k, None)
        return data

    @field_validator("is_target_role", "relocation", "is_agency", mode="before")
    @classmethod
    def unsure_is_default(cls, v, info):
        """"unknown" or null in a yes/no field means the default. The CLI model answered is_agency "unknown" for 4 postings
        in October, twice in a row each, and those postings never got an assessment (ALLPS, 28.10)."""
        if v is None or isinstance(v, str) and v.strip().lower() not in ("true", "false", "yes", "no", "1", "0"):
            return cls.model_fields[info.field_name].default
        return v

    def model_post_init(self, __context):
        if self.verdict is None:
            self.verdict = "apply" if self.fit >= 7 else ("maybe" if self.fit >= 4 else "skip")


SCHEMA_HINT = ("Ответь ТОЛЬКО одним JSON-объектом без markdown с полями: is_target_role (bool), "
               "seniority (junior|mid|senior|lead|unknown), residency_restriction "
               "(string|null), language_requirement (string|null), work_mode (remote|hybrid|onsite|unknown), "
               "remote_scope (string|null), sponsorship (yes|no|unknown), relocation (bool), "
               "pay_basis (salary|hourly|daily|unknown), ai_role (ai_first|product|tooling|none), salary_month_eur (number|null), "
               "is_agency (bool), employer_type (direct|consultancy|recruiter|unknown), employment (employee|contractor|unknown), fit (0-10), "
               "verdict (apply|maybe|skip), note (string).")


DESC_CAP = 6000   # the requirements block sits in the first ~6k chars; the tail is usually benefits/legal boilerplate


def build_prompt(job):
    sponsor = f"Спонсор IND по реестру: {job.sponsor_name or 'не найден'}\n" if SPONSOR_REGISTER else ""
    return PROMPT.format(company=job.company, title=job.title, location=job.location, source=job.source,
                         sponsor_line=sponsor, desc=job.description[:DESC_CAP])


def _country_codes():
    from . import filters as _f
    return _f.COUNTRY_CODES


def select_candidates(jobs, cfg):
    """Which jobs deserve an LLM call. Cheap cuts first: only live (or hardware-rescuable) postings with real text;
    remote track only above a score floor and never for agency postings without a named client."""
    floor = cfg.get("min_score_remote", 50)
    out = []
    for j in jobs:
        if not j.description or j.description == "(no description)" or len(j.description) < 300:
            continue
        if j.verdict == "skip" and not rescuable(j):
            continue
        if j.verdict == "other" or (j.track not in ("remote_nl", "remote", "eu") and j.track not in _country_codes()):
            continue
        if j.track in ("remote", "eu") and j.score < floor:
            continue
        out.append(j)
    out.sort(key=lambda j: (0 if j.track in _country_codes() else {"eu": 1, "remote_nl": 2}.get(j.track, 3), -j.score))
    return out[:cfg.get("max_per_run", 300)]


def low_yield_companies(stats, cfg, min_assessed):
    """company_key -> number of assessments for companies whose postings never reached the digest bar: at least
    min_assessed LLM calls, best final fit below 4, the owner never touched one, not in known_companies.
    27.10: Looper Engineering (53 calls), Atos, Archer Recruitment, Baxter, ABB, Vertiv, Airbus Defence and Space.
    0 turns the cut off."""
    if not min_assessed:
        return {}
    known = {company_key(n) for names in (cfg.get("known_companies") or {}).values() for n in names}
    out = {}
    for name, (n, best, touched) in stats.items():
        k = company_key(name)
        if k not in known and not touched:
            prev = out.get(k, (0, -1))
            out[k] = (prev[0] + n, max(prev[1], best if best is not None else -1))
    return {k: n for k, (n, best) in out.items() if n >= min_assessed and best < 4}


def skip_low_yield(jobs, low):
    for j in jobs:
        n = low.get(company_key(j.company))
        if n and j.verdict == "live":
            j.verdict = "skip"
            j.reasons.append(f"компания без fit ≥ 4 за {n} оценок моделью")


# ------------------------------------------------------------------ backends
class ApiBackend:
    name = "api"

    def __init__(self, model, model_country=None):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=3, timeout=120.0)
        self.model = model
        self.model_country = model_country or model

    def model_for(self, job):
        return self.model_country if job.track in _country_codes() else self.model

    @staticmethod
    def available():
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def assess(self, job):
        return self._parse(model=self.model_for(job), max_tokens=2048,
                           output_config={"effort": "medium"},
                           system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                           messages=[{"role": "user", "content": build_prompt(job)}],
                           output_format=Assessment)

    def ask(self, system, prompt, out_cls, model=None):
        """One structured call outside the vacancy rubric (CV tailoring); returns a validated `out_cls`."""
        return self._parse(model=model or self.model, max_tokens=16000, system=system,
                           messages=[{"role": "user", "content": prompt}], output_format=out_cls, timeout=300)

    def _parse(self, timeout=None, **kw):
        a = self.anthropic
        client = self.client.with_options(timeout=timeout) if timeout else self.client
        try:
            resp = client.messages.parse(**kw)
        except a.RateLimitError as e:
            raise RuntimeError(f"rate limited: {e.message}")
        except a.AuthenticationError:
            raise RuntimeError("invalid ANTHROPIC_API_KEY")
        except a.APIStatusError as e:
            raise RuntimeError(f"api error {e.status_code}: {e.message}")
        except a.APIConnectionError:
            raise RuntimeError("network error")
        if resp.stop_reason == "refusal":
            raise RuntimeError("model refused")
        return resp.parsed_output


class CliBackend:
    name = "cli"

    def __init__(self, model, model_country=None):
        self.model = model
        self.model_country = model_country or model
        self.last_usage = {}

    def model_for(self, job):
        return self.model_country if job.track in _country_codes() else self.model

    @staticmethod
    def available():
        if not shutil.which("claude"):
            return False
        try:
            p = subprocess.run(["claude", "-p", "ok", "--output-format", "json", "--model", "haiku",
                                "--system-prompt", "Answer: ok", "--tools", "", "--no-session-persistence"],
                               capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            return "Not logged in" not in p.stdout and p.returncode == 0
        except Exception:
            return False

    def assess(self, job, _attempt=0):
        prompt = build_prompt(job) + "\n" + SCHEMA_HINT
        # --system-prompt replaces Claude Code's own ~30k-token agent prompt, --tools "" drops tool schemas:
        # ~135k tokens per call -> ~3-4k. Measured 2026-09-07.
        # stdin=DEVNULL: the CLI appends anything it finds on stdin to the prompt (bit us when called from a heredoc script)
        p = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--model", self.model_for(job),
                            "--system-prompt", SYSTEM, "--tools", "", "--no-session-persistence"],
                           capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        raw = p.stdout
        try:
            self.last_usage = json.loads(raw).get("usage", {}) | {"cost_usd": json.loads(raw).get("total_cost_usd")}
        except ValueError:
            self.last_usage = {}
        try:
            raw = json.loads(raw).get("result", raw)
        except ValueError:
            pass
        if "Not logged in" in raw:
            raise RuntimeError("claude CLI not logged in")
        try:
            return Assessment.model_validate(extract_json(raw))
        except Exception:
            if _attempt == 0:      # truncated or malformed output happens a few times per hundred calls
                return self.assess(job, _attempt=1)
            raise

    def ask(self, system, prompt, out_cls, model=None, timeout=400):
        """One structured call outside the vacancy rubric (CV tailoring). --json-schema makes the CLI validate the
        answer and return it in `structured_output`; the text result is only a fallback."""
        p = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--model", model or self.model,
                            "--system-prompt", system, "--tools", "", "--no-session-persistence",
                            "--json-schema", json.dumps(out_cls.model_json_schema())],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError(f"claude CLI: {(p.stdout or p.stderr)[:200]}")
        self.last_usage = out.get("usage", {}) | {"cost_usd": out.get("total_cost_usd")}
        if out.get("is_error"):
            raise RuntimeError(f"claude CLI: {str(out.get('result'))[:200]}")
        obj = out.get("structured_output")
        return out_cls.model_validate(obj if obj is not None else extract_json(out.get("result") or "", key=None))


def extract_json(raw, key="fit"):
    """First JSON object in `raw` that parses and has `key` (any object when key is None); models sometimes add
    prose or fences. Also salvages output cut off mid-object: closing the braces recovers the fields that did arrive."""
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", raw):
        try:
            obj, _ = dec.raw_decode(raw[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and (key is None or key in obj):
            return obj
    start = raw.find("{")
    if start >= 0:
        frag = raw[start:]
        for cut in (frag.rfind(","), frag.rfind("}")):
            if cut <= 0:
                continue
            try:
                obj = json.loads(frag[:cut] + "}")
            except ValueError:
                continue
            if isinstance(obj, dict) and (key is None or key in obj):
                return obj
    raise RuntimeError(f"no JSON in model output: {raw[:120]!r}")


def pick_backend(cfg):
    mode = cfg.get("backend", "auto")
    if mode == "off" or not cfg.get("enabled", True):
        return None, "выключено в config.yaml"
    if mode in ("auto", "api") and ApiBackend.available():
        return ApiBackend(cfg.get("model_api", "claude-sonnet-5"), cfg.get("model_api_country")), ""
    if mode in ("auto", "cli") and CliBackend.available():
        return CliBackend(cfg.get("model_cli", "sonnet"), cfg.get("model_cli_country")), ""
    return None, ("нет ANTHROPIC_API_KEY в .env и `claude` CLI не залогинен "
                  "(открой терминал, запусти `claude`, затем /login)")


# ------------------------------------------------------------------ pipeline glue
SKIP_PREFIXES = ("текст на", "заголовок", "нужен", "junior/intern", "clearance", "без спонсорства",
                 "freelance/contract on-site", "компания в exclude", "LLM: не та роль", "LLM: ограничение",
                 "LLM: нужен язык", "LLM: junior", "LLM: спонсорство явно", "оплата за час/день", "LLM: оплата",
                 "компания без fit")


def is_skip_reason(r):
    from . import filters as _f
    return (r.startswith(SKIP_PREFIXES) or (bool(_f.OFF_DOMAIN_REASON) and r == _f.OFF_DOMAIN_REASON)
            or (r.startswith("зарплата") and "< порога" in r))


def rescuable(job):
    """Skipped only by the off-domain heuristic (role.off_domain, e.g. hardware/industrial QA) - the most
    false-positive-prone rule, so the model gets to say whether it is the role after all."""
    from . import filters as _f
    return bool(_f.OFF_DOMAIN_REASON) and [r for r in job.reasons if is_skip_reason(r)] == [_f.OFF_DOMAIN_REASON]


LEVELS = {"junior": 0, "mid": 1, "senior": 2, "lead": 3}


def apply_assessment(job, a: Assessment):
    """Fold the structured assessment into verdict / reasons / score."""
    from . import filters as _f
    if job.verdict == "skip" and rescuable(job) and a.is_target_role:
        job.reasons = [r for r in job.reasons if r != _f.OFF_DOMAIN_REASON] + [
            f"LLM: роль подходит, эвристика «{_f.OFF_DOMAIN_REASON}» снята"]
        job.verdict = "live" if (job.track in ("remote", "remote_nl", "eu") or job.track in _country_codes()) else "other"
        job.score = max(job.score, 50)
    job.llm_fit = a.fit
    job.llm_note = a.note[:400]
    job.llm_json = a.model_dump_json()
    skip = []
    if not a.is_target_role:
        skip.append("LLM: не та роль")
    track_after = ("eu" if job.track in ("remote", "remote_nl") and a.work_mode in ("hybrid", "onsite")
                   and _f.EU_LOC.search(job.location or "") else job.track)          # the switch below, computed early
    soft_residency = []
    if a.residency_restriction and not _f.residency_blocks(a.residency_restriction, track_after, job.location):
        soft_residency = [f"LLM: просят жить в стране вакансии — «{a.residency_restriction[:90]}»: при переезде не помеха"]
    elif a.residency_restriction:
        skip.append(f"LLM: ограничение по резидентству — «{a.residency_restriction[:90]}»")
    gap = language_gap(a.language_requirement)
    flags = []
    if gap:
        skip.append(f"LLM: нужен язык — {gap[:60]}")
    elif a.language_requirement:
        flags.append(f"LLM: язык есть у кандидата — {a.language_requirement[:60]}")
    flags += soft_residency
    level, own = LEVELS.get(a.seniority), min(_f.LEVEL, 2)         # a lead candidate takes senior roles too
    if level == 0 and own >= 2:
        skip.append("LLM: junior")
    elif level is not None and level < own:
        flags.append(f"LLM: {a.seniority}-level")
    if a.pay_basis in ("hourly", "daily"):
        skip.append("LLM: оплата " + ("почасовая" if a.pay_basis == "hourly" else "подневная"))
    if NEEDS_VISA and a.sponsorship == "no" and (job.track in _f.COUNTRY_CODES or job.track == "eu"):
        skip.append("LLM: спонсорство явно не предлагается")   # on-site in the EU without a visa is not reachable
    if a.verdict == "skip" and not skip:
        flags_extra = [f"LLM: слабое соответствие (fit {a.fit}) — {a.note[:100]}"]   # ranking, not exclusion
    else:
        flags_extra = []
    if a.is_agency and a.employer_type != "consultancy":
        flags.append("LLM: агентство")
    in_text = bool(VISA_TEXT.search(job.description or ""))
    visa, moving = NEEDS_VISA and a.sponsorship == "yes" and in_text, a.relocation and in_text
    if visa:
        flags.append("LLM: визовая поддержка явно ✅")
    elif moving:
        flags.append("LLM: помощь с переездом ✅")
    if job.track in ("remote", "remote_nl") and a.work_mode in ("hybrid", "onsite"):
        if _f.EU_LOC.search(job.location or ""):
            job.track = "eu"                  # not remote after all, but relocation within the EU is fine
            flags.append(f"LLM: {a.work_mode}, трек EU")
        else:
            job.track = "other"
            flags.append(f"LLM: {a.work_mode} вне ЕС — не remote")
    if a.salary_month_eur and not job.salary_month:
        job.salary_month = a.salary_month_eur
    # final fit = model fit (role match only) + what the model must not price in: location, visa or relocation offer,
    # employer type, contract, competition, focus topics. Each adjustment is visible in the flags.
    adj = []
    strong_role = a.fit >= 5      # bonuses may promote a decent role match, never rescue a weak one
    penalty = LOCATION_PENALTY.get(job.track, 2)
    if penalty > 0:
        adj.append((-penalty, "локация"))
    elif penalty < 0 and strong_role:               # the primary country is a bonus, not just "no penalty"
        name = next((c["name"] for c in _f.COUNTRIES if c["code"] == job.track), "страна")
        adj.append((-penalty, name))
    if visa and FIT_ADJ["sponsorship_yes"] and strong_role:
        adj.append((FIT_ADJ["sponsorship_yes"], "виза явно"))
    elif moving and FIT_ADJ["relocation_yes"] and strong_role:
        adj.append((FIT_ADJ["relocation_yes"], "переезд явно"))
    ai = {"ai_first": FIT_ADJ["ai_first"], "product": FIT_ADJ["ai_product"],
          "tooling": FIT_ADJ["ai_tooling"]}.get(a.ai_role, 0)
    if ai and strong_role:
        adj.append((ai, {"ai_first": "AI-first", "product": "AI в продукте"}.get(a.ai_role, "AI-инструменты")))
    for name, bonus in FOCUS_FIT.items():
        if bonus and strong_role and f"фокус: {name}" in job.reasons:
            adj.append((bonus, name))
    # who employs and how: a product company hiring to staff is the default target; outsourcing/outstaffing even with
    # a staff contract, recruiters and contracts rank lower (calibrated 25.09 on a QA owner's clicks: BairesDev
    # "remote, outstaff, contractor" got fit 7). A contract is fine when the posting itself promises a visa.
    heuristic_recruiter = any(r.startswith("агентство") for r in job.reasons)   # "our client", agency_companies list
    etype = a.employer_type
    if etype == "unknown" and a.is_agency:
        etype = "recruiter" if heuristic_recruiter else "consultancy"          # legacy assessments without the field
    if (etype == "recruiter" or (etype == "unknown" and heuristic_recruiter)) and FIT_ADJ["agency"]:
        adj.append((FIT_ADJ["agency"], "рекрутер/посредник"))
    elif etype == "consultancy" and FIT_ADJ["consultancy"]:
        adj.append((FIT_ADJ["consultancy"], "аутсорс/аутстафф"))
    contract = a.employment == "contractor" or any(r.startswith(CONTRACT_FLAGS) for r in job.reasons)
    if contract and visa:
        flags.append("контракт, но виза обещана явно: без штрафа")
    elif contract and FIT_ADJ["contractor"]:
        adj.append((FIT_ADJ["contractor"], "контракт, не найм"))
    if job.applicants is not None:
        if job.applicants <= FIT_ADJ["low_competition_max"] and FIT_ADJ["low_competition"] and strong_role:
            adj.append((FIT_ADJ["low_competition"], f"мало откликов ({job.applicants})"))
        elif job.applicants >= FIT_ADJ["high_competition_min"] and FIT_ADJ["high_competition"]:
            adj.append((FIT_ADJ["high_competition"], f"много откликов ({job.applicants})"))
    job.llm_fit = max(0, a.fit + sum(d for d, _ in adj))      # no ceiling: strong postings with bonuses go above 10
    if adj:
        flags.append("fit: модель " + str(a.fit) + " " + " ".join(f"{d:+d} {why}" for d, why in adj) + f" = {job.llm_fit}")
    job.reasons = skip + job.reasons + flags + flags_extra
    if skip:
        job.verdict = "skip"
        job.score = min(job.score, 25)
    elif job.track == "other":
        job.verdict = "other"
    else:
        job.score = max(0, round(0.4 * job.score + 6 * job.llm_fit))   # uncapped too, so the order at the top holds
    return job


def assess_many(jobs, backend, workers=4, log=print, on_done=None):
    """Assess in parallel; `on_done(job)` is called after each job so callers can persist incrementally."""
    import threading
    lock = threading.Lock()
    cost = [0.0]

    def one(j):
        try:
            a = backend.assess(j)
            apply_assessment(j, a)
            ok = True
        except Exception as e:
            j.llm_note = f"LLM error: {e}"[:200]
            ok = False
        with lock:
            cost[0] += (getattr(backend, "last_usage", {}) or {}).get("cost_usd") or 0
            if on_done:
                on_done(j)
        return ok
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, jobs))
    ok = sum(results)
    log(f"LLM ({backend.name}): assessed {ok}/{len(jobs)}" + (f", ~${cost[0]:.2f} API-equivalent" if cost[0] else ""))
    return ok
