"""Where one person's files live and how the configuration is put together.

Code and shared defaults are in git; everything about the person is in my/ (not in git):
  my/profile.yaml    candidate, role, target countries, company lists. Required.
  my/config.yaml     overrides of config.yaml: deep merge, a list replaces the default list. Optional.
  my/companies.yaml  the person's own company boards. Optional.
  my/cv.tex, my/cv_bank.yaml  tailored CVs from the bot. Optional.
Secrets are in .env, the database and reports in data/. JOBSEARCH_MY and JOBSEARCH_DATA move both elsewhere
(tests, two people on one machine).
"""
import copy
import os
import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MY = Path(os.environ.get("JOBSEARCH_MY") or ROOT / "my")
DATA = Path(os.environ.get("JOBSEARCH_DATA") or ROOT / "data")
CATALOG = ROOT / "presets" / "countries.yaml"
SENIORITY = ("junior", "mid", "senior", "lead")


class ConfigError(Exception):
    pass


def read_yaml(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: YAML не разбирается — {e}")


def deep_merge(base, over):
    """Dicts merge key by key, anything else (lists included) is replaced by the override."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if k in out and isinstance(out[k], dict) and isinstance(v, dict) else copy.deepcopy(v)
    return out


def path_in_project(p):
    """Paths in configs are relative to the project root; my/… follows JOBSEARCH_MY."""
    p = str(p)
    if p.startswith("my/"):
        return MY / p[3:]
    return Path(p) if Path(p).is_absolute() else ROOT / p


# ------------------------------------------------------------------ countries
def catalog():
    return read_yaml(CATALOG) or {}


def _country(spec, cat, birth_year=None):
    """A country from the catalog by code or name, with the profile's own fields on top."""
    if isinstance(spec, str):
        spec = {"code": spec}
    spec = dict(spec or {})
    key = str(spec.get("code") or "").lower()
    if key not in cat and spec.get("name"):
        key = next((k for k, v in cat.items() if v["name"].lower() == str(spec["name"]).lower()), key)
    if key not in cat and spec.get("code") and len(str(spec["code"])) > 3:      # "Germany" written as the code
        key = next((k for k, v in cat.items() if v["name"].lower() == str(spec["code"]).lower()), key)
        spec.pop("code")
    base = dict(cat.get(key) or {})
    if not base and not spec.get("location_regex"):
        raise ConfigError(f"страна «{spec.get('code') or spec.get('name')}» не найдена в presets/countries.yaml — "
                          f"укажи код из каталога или опиши её целиком (code, name, location_regex)")
    out = {**base, **{k: v for k, v in spec.items() if v is not None}}
    out["code"] = key or re.sub(r"\W+", "", str(out.get("name", "")).lower())
    if not out.get("name"):
        raise ConfigError(f"у страны {spec} нет name")
    if birth_year and out.get("salary_floor_under_30") and date.today().year - int(birth_year) < 30 \
            and "salary_floor_month" not in spec:
        out["salary_floor_month"] = out["salary_floor_under_30"]
    out.setdefault("label", out["name"])
    out.setdefault("local_languages", [])
    out.setdefault("sponsor_register", "none")
    return out


def normalize_target(profile, cat=None):
    """target.primary (or None for remote-only) and target.countries as full dicts.

    Accepts the short form (`country: de`, `countries: [nl, at]`) and the long flat form where the primary country's
    fields sit right in `target` (country: Netherlands, location_regex, visa_scheme, track_label, sponsor_register)."""
    cat = catalog() if cat is None else cat
    t = dict(profile.get("target") or {})
    birth = (profile.get("candidate") or {}).get("birth_year")
    spec = t.get("country")
    if spec in (None, "", "none", False):
        primary = None
    else:
        if isinstance(spec, str):
            spec = {"code": spec} if spec.lower() in cat or len(spec) <= 3 else {"name": spec}
        spec = dict(spec)
        for flat, key in (("location_regex", "location_regex"), ("visa_scheme", "visa_scheme"),
                          ("track_label", "label"), ("sponsor_register", "sponsor_register"), ("city", "city"),
                          ("salary_floor_month", "salary_floor_month"), ("code", "code")):
            if t.get(flat) is not None and key not in spec:
                spec[key] = t[flat]
        if "name" in spec and "code" not in spec and str(spec["name"]).lower() == "netherlands":
            spec["code"] = "nl"
        primary = _country(spec, cat, birth)
        if "local_language" in t and "local_languages" not in spec:   # old single-language key: nl | de | none
            lang = {"nl": "dutch", "de": "german", "fr": "french"}.get(str(t["local_language"]))
            primary["local_languages"] = [lang] if lang else []
    extra = [_country(c, cat, birth) for c in t.get("countries") or []]
    if primary:
        extra = [c for c in extra if c["code"] != primary["code"]]
    t["primary"], t["countries"] = primary, extra
    if primary and t.get("salary_floor_month") is None:
        t["salary_floor_month"] = primary.get("salary_floor_month")
    t.setdefault("remote", True)
    return t


def track_codes(target):
    return ([target["primary"]["code"]] if target.get("primary") else []) + [c["code"] for c in target["countries"]]


def default_location_penalty(target):
    """Final-fit correction per track (negative = bonus). Relocation goal: the primary country is a bonus, other
    countries a small penalty, the rest of the EU more, remote most (no visa path). Remote-only goal: the reverse."""
    out = {"eu": 2, "remote_nl": 2, "remote": 3, "other": 3}
    if not target.get("primary"):
        out.update({"remote": 0, "remote_nl": 0, "eu": 2})
    else:
        out[target["primary"]["code"]] = -1
    for c in target["countries"]:
        out[c["code"]] = 1
    return out


# ------------------------------------------------------------------ switches
# Short answers at the top of my/profile.yaml. apply_switches() turns them into the detailed fields the code reads;
# a profile without `switches` keeps working as before. Values: what each switch accepts, the first is the default.
SWITCH_VALUES = {
    "goal": ("both", "relocate", "remote"),
    "visa": ("needed", "not_needed"),
    "other_language": ("skip", "flag", "any"),
    "level": ("senior", "junior", "mid", "lead"),
    "contract": ("penalize", "skip", "ok"),
    "outsourcing": ("penalize", "skip", "ok"),
    "agencies": ("penalize", "skip", "ok"),
    "public_sector": ("skip", "ok"),
    "ai": ("neutral", "prefer", "avoid"),
}
# What the code does without a switch: the behaviour the rules were calibrated with
DEFAULT_PREFS = {"other_language": "skip", "contract": "penalize", "outsourcing": "penalize", "agencies": "penalize",
                 "public_sector": "skip", "eu_offices": True, "remote": True, "salary_min": None}
PENALTY_KEYS = {"contract": ("contractor", -2), "outsourcing": ("consultancy", -1), "agencies": ("agency", -1)}
AI_BONUS = {"prefer": {"ai_first": 2, "ai_product": 2, "ai_tooling": 1},
            "neutral": {"ai_first": 0, "ai_product": 0, "ai_tooling": 0},
            "avoid": {"ai_first": -2, "ai_product": -1, "ai_tooling": 0}}
# remote-only job boards: no use for a relocation-only goal
REMOTE_ONLY_AGGREGATORS = {"remotive", "remoteok", "workingnomads", "weworkremotely", "jobicy", "himalayas"}
CV_FORMATS = {".tex": "latex", ".docx": "docx", ".md": "markdown", ".markdown": "markdown", ".pdf": "text",
              ".txt": "text"}


def _choice(sw, name, problems):
    v = sw.get(name)
    if v is None:
        return None
    v = str(v).strip().lower() if not isinstance(v, bool) else v
    if v not in SWITCH_VALUES[name]:
        problems.append(f"switches.{name}: {sw[name]!r}, нужно одно из: {', '.join(SWITCH_VALUES[name])}")
        return None
    return v


def apply_switches(profile):
    """Write the switches into candidate / target / prefs. A switch wins over the same field set elsewhere in the
    profile (the clash is listed in profile['_notes'] for `check`); fit_adjustments numbers set by hand still decide
    how big a penalty is, the switch decides whether there is one."""
    sw = dict(profile.get("switches") or {})
    cand = profile.setdefault("candidate", {}) or {}
    t = profile.setdefault("target", {}) or {}
    profile["candidate"], profile["target"] = cand, t
    notes, bad = profile.setdefault("_notes", []), profile.setdefault("_problems", [])
    prefs = dict(DEFAULT_PREFS)

    def put(where, key, value, label):
        old = where.get(key)
        if old is not None and old != value:
            notes.append(f"switches.{label} перекрывает {key}: {old!r} → {value!r}")
        where[key] = value

    goal = _choice(sw, "goal", bad)
    countries = sw.get("countries")
    if countries is not None and not isinstance(countries, list):
        countries = [countries]
    if goal == "remote":
        if countries:
            notes.append("switches.goal: remote — список countries не используется")
        if sw.get("eu_offices"):
            notes.append("switches.goal: remote — eu_offices не используется, офисы не показываются")
        put(t, "country", "none", "goal")
        t["countries"] = []
        put(t, "remote", True, "goal")
        t["eu_offices"] = False                  # remote only: an office anywhere is not what is wanted
    else:
        if countries:
            put(t, "country", countries[0], "countries")
            t["countries"] = list(countries[1:])
        if goal == "relocate":
            put(t, "remote", False, "goal")
        elif goal == "both":
            put(t, "remote", True, "goal")
        if "eu_offices" in sw:
            put(t, "eu_offices", bool(sw["eu_offices"]), "eu_offices")
    visa = _choice(sw, "visa", bad)
    if visa:
        put(cand, "needs_visa", visa == "needed", "visa")
    if sw.get("based_in"):
        put(cand, "based_in", str(sw["based_in"]), "based_in")
    if sw.get("languages"):
        langs = sw["languages"] if isinstance(sw["languages"], list) else [sw["languages"]]
        put(cand, "languages", [str(x) for x in langs], "languages")
    level = _choice(sw, "level", bad)
    if level:
        put(cand, "seniority", level, "level")
    for name in ("other_language", "contract", "outsourcing", "agencies", "public_sector"):
        v = _choice(sw, name, bad)
        if v:
            prefs[name] = v
    adj = t.setdefault("fit_adjustments", {}) or {}
    t["fit_adjustments"] = adj
    for name, (key, size) in PENALTY_KEYS.items():
        if name not in sw:
            continue
        if prefs[name] == "ok":                       # no penalty, whatever number is written below
            if adj.get(key):
                notes.append(f"switches.{name}: ok обнуляет fit_adjustments.{key}: {adj[key]}")
            adj[key] = 0
        else:
            adj.setdefault(key, size)                 # a number written by hand still sets the size
    ai = _choice(sw, "ai", bad)
    if ai:
        for k, v in AI_BONUS[ai].items():       # a number written by hand in fit_adjustments wins, as for penalties
            adj.setdefault(k, v)
    if "salary_min" in sw:
        v = sw["salary_min"]
        if isinstance(v, str) and v.strip().lower() == "visa":
            prefs["salary_min"] = None if cand.get("needs_visa", True) else 0
        else:
            try:
                prefs["salary_min"] = max(0, int(v or 0))
            except (TypeError, ValueError):
                bad.append(f"switches.salary_min: {v!r}, нужно visa, число €/мес или 0")
    if sw.get("salary_target"):
        put(t, "salary_target_month", int(sw["salary_target"]), "salary_target")
    if sw.get("cv"):
        profile["_cv"] = str(sw["cv"])
    prefs["eu_offices"] = bool(t.get("eu_offices", True))
    profile["prefs"] = prefs
    return profile


def normalize_profile(profile):
    """Switches first, then the target countries; afterwards the profile has the shape every module reads."""
    apply_switches(profile)
    explicit_floor = profile["target"].get("salary_floor_month")       # set by hand, before the catalog fills it
    profile["target"] = normalize_target(profile)
    prefs = profile["prefs"]
    prefs["remote"] = bool(profile["target"].get("remote", True))
    if prefs["salary_min"] is None and not profile["candidate"].get("needs_visa", True):
        prefs["salary_min"] = int(explicit_floor or 0)    # visa thresholds mean nothing without a visa
    if prefs["salary_min"] is not None:             # an own minimum replaces the visa floors everywhere
        profile["target"]["salary_floor_month"] = prefs["salary_min"] or None
    return profile


def cv_source(cfg):
    """(path, format) of the CV: switches.cv, else cv.source / cv.tex in the config. Format by extension."""
    p = cfg.get("profile") or {}
    c = cfg.get("cv") or {}
    raw = p.get("_cv") or c.get("tex") or c.get("source") or "my/cv.tex"    # an old my/config `cv.tex` still counts
    if str(raw).lower() in ("none", "no", "off"):
        return None, "none"
    path = path_in_project(raw)
    return path, CV_FORMATS.get(path.suffix.lower(), "unknown")


# ------------------------------------------------------------------ sources derived from the profile
def default_linkedin_locations(profile):
    """Primary country with every query and up to 100 pages; each extra country and the remote EU search with the
    first four queries and 50 pages (their result lists are long and repeat between queries); remote in the country
    the candidate lives in (candidate.based_in) with the same four and 30 pages."""
    t, queries = profile["target"], (profile.get("role") or {}).get("queries") or []
    short = queries[:4]
    out = []
    if t.get("primary"):
        out.append({"name": t["primary"]["name"], "remote": False})
    for c in t["countries"]:
        out.append({"name": c["name"], "remote": False, "max_pages": 50, "queries": short})
    if t.get("remote", True):
        out.append({"name": "European Union", "remote": True, "max_pages": 50, "queries": short})
        # the EU-wide search stops at 1000 cards and loses remote jobs open to residents of one country; the one
        # where the candidate lives gets its own search (a test setup for Warsaw, 15.11: 46 live postings from it)
        from .filters import EU_LOC
        home = str((profile.get("candidate") or {}).get("based_in") or "").strip()
        # EU/EEA only: "Georgia" on LinkedIn is the US state, Serbia or Kazakhstan give local jobs, not remote ones
        if home and EU_LOC.fullmatch(home) and home.lower() not in {l["name"].lower() for l in out}:
            out.append({"name": home, "remote": True, "max_pages": 30, "queries": short})
    return out


def load(my=None):
    """config.yaml + my/config.yaml + my/profile.yaml (normalized) + company boards → one dict."""
    my = Path(my) if my else MY
    base = read_yaml(ROOT / "config.yaml") or {}
    over = read_yaml(my / "config.yaml") or {}
    cfg = deep_merge(base, over)
    profile = read_yaml(my / "profile.yaml")
    if profile is None:
        raise ConfigError(f"нет {my / 'profile.yaml'}: настрой профиль (скилл /jobsearch-setup в Claude Code "
                          f"или `python -m jobsearch init --role <роль>`, см. docs/SETUP.md)")
    normalize_profile(profile)
    cfg["profile"] = profile
    role, t = profile.get("role") or {}, profile["target"]
    if not profile["prefs"]["remote"] and "aggregators" not in over:     # relocation only: remote boards are noise
        cfg["aggregators"] = [a for a in cfg.get("aggregators") or [] if a not in REMOTE_ONLY_AGGREGATORS]
    li = cfg.setdefault("linkedin", {})
    if not li.get("queries"):
        li["queries"] = list(role.get("queries") or [])
    if not li.get("locations"):
        li["locations"] = default_linkedin_locations(profile)
    hc = cfg.setdefault("hiringcafe", {})
    if not hc.get("queries"):
        hc["queries"] = list(role.get("hiringcafe_queries") or (role.get("queries") or [])[:2])
    if not hc.get("countries"):
        hc["countries"] = [c["name"] for c in ([t["primary"]] if t.get("primary") else []) + t["countries"]]
    for k in ("salary_floor_month", "salary_target_month"):
        if t.get(k) is not None:
            cfg[k] = t[k]
    for k in ("known_companies", "exclude_companies", "sponsor_aliases", "agency_companies"):
        if profile.get(k) is not None:
            cfg[k] = profile[k]
    cfg["companies"] = load_companies(cfg.get("company_files") or [])
    return cfg


def load_companies(files):
    """Boards from every file, first mention wins: own and hand-picked lists first, then the mass-discovered ones."""
    out, seen = [], set()
    for f in files:
        data = read_yaml(path_in_project(f))
        for c in data or []:
            key = (c["ats"], str(c["slug"]).lower())
            if key not in seen:
                seen.add(key)
                out.append(c)
    return out


# ------------------------------------------------------------------ checks
def problems(cfg):
    """What would make runs useless or crash, in words the owner can act on. Empty list = fine."""
    p = cfg["profile"]
    out = list(p.get("_problems") or [])
    cand, role, t = p.get("candidate") or {}, p.get("role") or {}, p["target"]
    path, fmt = cv_source(cfg)
    if fmt == "unknown":
        out.append(f"резюме {path.name}: формат не поддерживается — .tex, .docx, .md, .pdf или .txt")
    if not (cand.get("summary") or "").strip():
        out.append("candidate.summary пуст: модели не с чем сравнивать вакансии")
    if not cand.get("languages"):
        out.append("candidate.languages пуст: вакансии на любом языке, кроме английского, отсекутся")
    if cand.get("seniority") and cand["seniority"] not in SENIORITY:
        out.append(f"candidate.seniority: {cand['seniority']!r}, нужно одно из {', '.join(SENIORITY)}")
    for k in ("name", "definition", "not_this_role"):
        if not (role.get(k) or "").strip():
            out.append(f"role.{k} пуст: это текст для модели, без него рубрика не знает, что считать ролью")
    if not role.get("title_include"):
        out.append("role.title_include пуст: ни один заголовок не пройдёт")
    if not role.get("queries"):
        out.append("role.queries пуст: LinkedIn и агрегаторам нечего искать")
    if not role.get("keywords"):
        out.append("role.keywords пуст: корпоративные сайты (Workday, SuccessFactors…) искать нечем")
    for where, pats in (("role.title_include", role.get("title_include") or []),
                        ("role.title_exclude", role.get("title_exclude") or []),
                        ("role.stack", list((role.get("stack") or {}).keys())),
                        ("role.title_boost", list((role.get("title_boost") or {}).keys())),
                        ("role.focus", [f.get("regex", "") for f in role.get("focus") or []]),
                        ("role.penalties", [f.get("regex", "") for f in role.get("penalties") or []]
                         + [f.get("unless", "") for f in role.get("penalties") or [] if f.get("unless")]),
                        ("role.off_domain", [x for x in ((role.get("off_domain") or {}).get("title"),
                                                         (role.get("off_domain") or {}).get("desc")) if x]),
                        ("target", [c["location_regex"] for c in ([t["primary"]] if t.get("primary") else [])
                                    + t["countries"]])):
        for pat in pats:
            try:
                re.compile(pat)
            except re.error as e:
                out.append(f"{where}: регэксп {pat[:60]!r} не компилируется — {e}")
    if not t.get("primary") and not t["countries"] and not t.get("remote", True):
        out.append("target: нет ни страны, ни remote — искать негде")
    for f in cfg.get("company_files") or []:
        if not str(f).startswith("my/") and not path_in_project(f).exists():      # own lists are optional
            out.append(f"company_files: файла {f} нет")
    return out
