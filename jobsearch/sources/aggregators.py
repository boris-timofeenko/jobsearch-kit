"""Public job APIs and job-board searches for the target-country and remote-EU tracks.

What to search for comes from the profile (configure): role.queries (job titles), role.keywords (short words),
role.categories (the board's own category names where a board is browsed by category)."""
from datetime import datetime

from ..models import Job
from .ats import strip_html

ROLE = {"queries": ["QA Engineer", "Test Automation Engineer", "SDET"], "keywords": ["QA", "test", "SDET"],
        "categories": {}}
SEARCH_COUNTRIES = ("Netherlands", "Belgium", "Germany", "France")   # target countries by name (configure)
PRIMARY = {"code": "nl", "name": "Netherlands", "city": "Amsterdam"}
HC_CONFIG = {}            # merged hiringcafe section of config.yaml + my/config.yaml
ADZUNA = {"at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "gb", "in", "it", "mx", "nl", "nz", "pl", "sg", "us", "za"}


def configure(cfg):
    """Search terms and countries from the loaded config (config.load): called by cli.load_cfg."""
    global SEARCH_COUNTRIES, PRIMARY, HC_CONFIG
    p = cfg.get("profile") or {}
    role, t = p.get("role") or {}, p.get("target") or {}
    ROLE["queries"] = list(role.get("queries") or ROLE["queries"])
    ROLE["keywords"] = list(role.get("keywords") or ROLE["keywords"])
    ROLE["categories"] = dict(role.get("categories") or {})
    countries = ([t["primary"]] if t.get("primary") else []) + list(t.get("countries") or [])
    SEARCH_COUNTRIES = tuple(c["name"] for c in countries)
    PRIMARY = t.get("primary") or {}
    HC_CONFIG = dict(cfg.get("hiringcafe") or {})
    from ..config import catalog
    for c in list(catalog().values()) + countries:
        if c.get("geo") and c.get("name") not in _GEO:
            _GEO[c["name"]] = (c["name"], str(c.get("code", c["name"][:2])).upper(), c["geo"][0], c["geo"][1])
    from . import hc_chrome
    hc_chrome.SETTINGS.update({k: HC_CONFIG[k] for k in ("chrome_display", "chrome_profile") if HC_CONFIG.get(k)})


def category(name, default=None):
    return ROLE["categories"].get(name, default)


def arbeitnow(http, pages=3):
    out = []
    url = "https://www.arbeitnow.com/api/job-board-api"
    for _ in range(pages):
        r = http.get(url)
        if not r or r.status_code != 200:
            break
        data = r.json()
        for j in data.get("data", []):
            ts = j.get("created_at")
            out.append(Job(id=f"arbeitnow:{j['slug']}", source="arbeitnow", company=j.get("company_name", ""),
                           title=j.get("title", ""), url=j.get("url", ""), location=j.get("location", ""),
                           posted=datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "",
                           remote=bool(j.get("remote")), description=strip_html(j.get("description", "")),
                           extra={"visa_sponsorship": j.get("visa_sponsorship")}))
        url = (data.get("links") or {}).get("next")
        if not url:
            break
        http.sleep()
    return out


def landingjobs(http, pages=3):
    out = []
    for p in range(pages):
        r = http.get(f"https://landing.jobs/api/v1/jobs?limit=100&offset={p * 100}")
        if not r or r.status_code != 200:
            break
        rows = r.json()
        if not rows:
            break
        for j in rows:
            loc = ", ".join(x for x in [j.get("city"), j.get("country_code")] if x)
            sal = ""
            if j.get("gross_salary_low"):
                sal = f"€{j['gross_salary_low']}-{j.get('gross_salary_high')} per year"
            out.append(Job(id=f"landingjobs:{j['id']}", source="landingjobs",
                           company=j.get("company_name") or f"company#{j.get('company_id')}",
                           title=j.get("title", ""), url=j.get("url", ""), location=loc,
                           posted=(j.get("published_at") or "")[:10], remote=bool(j.get("remote")),
                           description=strip_html((j.get("role_description") or "") + "\n" +
                                                  (j.get("main_requirements") or "")),
                           salary_text=sal, extra={"relocation": j.get("relocation_paid")}))
        http.sleep()
    return out


def himalayas(http, pages=2):
    out, cursor = [], None
    for _ in range(pages):
        url = "https://himalayas.app/jobs/api?limit=100" + (f"&cursor={cursor}" if cursor else "")
        r = http.get(url)
        if not r or r.status_code != 200:
            break
        data = r.json()
        for j in data.get("jobs", []):
            ts = j.get("pubDate")
            out.append(Job(id=f"himalayas:{j.get('guid') or j.get('applicationLink')}", source="himalayas",
                           company=j.get("companyName", ""), title=j.get("title", ""),
                           url=j.get("applicationLink", ""),
                           location="Remote: " + ", ".join(j.get("locationRestrictions") or ["worldwide"]),
                           posted=datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "",
                           remote=True, description=strip_html(j.get("description", "")),
                           salary_text=f"{j.get('minSalary') or ''}-{j.get('maxSalary') or ''} {j.get('currency') or ''}"))
        cursor = data.get("nextCursor")
        if not cursor:
            break
        http.sleep()
    return out


def remotive(http):
    """By category when the profile names one (role.categories.remotive: qa, software-dev, data, devops, design,
    product…), else a text search per keyword."""
    cat = category("remotive")
    urls = ([f"https://remotive.com/api/remote-jobs?category={quote(cat)}&limit=100"] if cat else
            [f"https://remotive.com/api/remote-jobs?search={quote(k)}&limit=100" for k in ROLE["keywords"][:4]])
    out, seen = [], set()
    for url in urls:
        r = http.get(url)
        if not r or r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            out.append(Job(id=f"remotive:{j['id']}", source="remotive", company=j.get("company_name", ""),
                       title=j.get("title", ""), url=j.get("url", ""),
                       location="Remote: " + (j.get("candidate_required_location") or ""),
                       posted=(j.get("publication_date") or "")[:10], remote=True,
                       description=strip_html(j.get("description", "")), salary_text=j.get("salary") or ""))
        http.sleep()
    return out


def remoteok(http):
    r = http.get("https://remoteok.com/api")
    if not r or r.status_code != 200:
        return []
    out = []
    for j in r.json():
        if not isinstance(j, dict) or "id" not in j:
            continue
        tags = " ".join(j.get("tags") or []).lower()
        if not any(t.lower() in tags for t in category("remoteok") or ROLE["keywords"]):
            continue
        sal = f"${j['salary_min']}-{j['salary_max']} per year" if j.get("salary_min") else ""
        out.append(Job(id=f"remoteok:{j['id']}", source="remoteok", company=j.get("company", ""),
                       title=j.get("position", ""), url=j.get("url", ""),
                       location="Remote: " + (j.get("location") or "worldwide"), posted=(j.get("date") or "")[:10],
                       remote=True, description=strip_html(j.get("description", "")), salary_text=sal))
    return out


from .expat_boards import EXPAT_BOARDS  # noqa: E402

AGGREGATORS = {"arbeitnow": arbeitnow, "landingjobs": landingjobs, "himalayas": himalayas,
               "remotive": remotive, "remoteok": remoteok, **EXPAT_BOARDS}


# ------------------------------------------------------------------ added 2026-09-07
import html as _html  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from urllib.parse import quote  # noqa: E402

from .. import filters as _filters  # noqa: E402


def workingnomads(http):
    r = http.get("https://www.workingnomads.com/api/exposed_jobs/")
    if not r or r.status_code != 200:
        return []
    out = []
    for j in r.json():
        out.append(Job(id=f"workingnomads:{j['url'].rstrip('/').rsplit('/', 1)[-1]}", source="workingnomads",
                       company=j.get("company_name", ""), title=j.get("title", ""), url=j.get("url", ""),
                       location="Remote: " + (j.get("location") or "worldwide"), posted=(j.get("pub_date") or "")[:10],
                       remote=True, description=strip_html(j.get("description", ""))))
    return out


def weworkremotely(http):
    out = []
    for cat in category("weworkremotely") or ("remote-programming-jobs", "remote-devops-sysadmin-jobs"):
        r = http.get(f"https://weworkremotely.com/categories/{cat}.rss")
        if not r or r.status_code != 200:
            continue
        for item in r.text.split("<item>")[1:]:
            def tag(name):
                m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
                return _html.unescape(m.group(1).strip()) if m else ""
            title = re.sub(r"^<!\[CDATA\[|\]\]>$", "", tag("title"))
            company, _, role = title.partition(": ")
            link = tag("link")
            out.append(Job(id=f"wwr:{link.rstrip('/').rsplit('/', 1)[-1]}", source="weworkremotely",
                           company=company, title=role or title, url=link,
                           location="Remote: " + (tag("region") or "worldwide"), posted=tag("pubDate")[:16],
                           remote=True, description=strip_html(tag("description"))))
    return out


def themuse(http, pages=3):
    out = []
    city = f"{PRIMARY['city']}, {PRIMARY['name']}" if PRIMARY.get("city") else None
    for loc in [x for x in (city, "Flexible / Remote") if x]:
        for page in range(1, pages + 1):
            r = http.get(f"https://www.themuse.com/api/public/jobs?category={quote(category('themuse', 'Software Engineering'))}"
                         f"&location={quote(loc)}&page={page}")
            if not r or r.status_code != 200:
                break
            data = r.json()
            for j in data.get("results", []):
                locs = [l["name"] for l in j.get("locations", [])]
                out.append(Job(id=f"themuse:{j['id']}", source="themuse", company=j.get("company", {}).get("name", ""),
                               title=j.get("name", ""), url=j.get("refs", {}).get("landing_page", ""),
                               location=" / ".join(locs)[:200], posted=(j.get("publication_date") or "")[:10],
                               remote=any("remote" in l.lower() for l in locs),
                               description=strip_html(j.get("contents", ""))))
            if page >= data.get("page_count", 1):
                break
            http.sleep()
    return out


def jobicy(http):
    out = []
    tag = category("jobicy") or ROLE["keywords"][0].lower()
    for q in (f"count=50&tag={quote(tag)}", "count=50&industry=engineering&geo=europe"):
        r = http.get(f"https://jobicy.com/api/v2/remote-jobs?{q}")
        if not r or r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            sal = ""
            if j.get("annualSalaryMin"):
                sal = f"{j.get('salaryCurrency', '')} {j['annualSalaryMin']}-{j.get('annualSalaryMax')} per year"
            out.append(Job(id=f"jobicy:{j['id']}", source="jobicy", company=j.get("companyName", ""),
                           title=j.get("jobTitle", ""), url=j.get("url", ""),
                           location="Remote: " + (j.get("jobGeo") or "worldwide"), posted=(j.get("pubDate") or "")[:10],
                           remote=True, description=strip_html(j.get("jobDescription", "")), salary_text=sal))
    return out


def adzuna(http):
    """Aggregator over the primary country's job boards (Indeed-like coverage). Needs free keys:
    https://developer.adzuna.com/ ; works for the countries Adzuna covers (ADZUNA)."""
    app_id, key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    cc = str(PRIMARY.get("code") or "")
    if not app_id or not key or cc not in ADZUNA:
        return []
    out = []
    for what in ROLE["queries"][:5]:
        r = http.get(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1?app_id={app_id}&app_key={key}"
                     f"&results_per_page=50&what={quote(what)}&max_days_old=3&content-type=application/json")
        if not r or r.status_code != 200:
            continue
        for j in r.json().get("results", []):
            sal = f"€{j['salary_min']:.0f}-{j.get('salary_max', 0):.0f} per year" if j.get("salary_min") else ""
            out.append(Job(id=f"adzuna:{j['id']}", source="adzuna", company=(j.get("company") or {}).get("display_name", ""),
                           title=j.get("title", ""), url=j.get("redirect_url", ""),
                           location=(j.get("location") or {}).get("display_name", "") + f", {PRIMARY.get('name', '')}",
                           posted=(j.get("created") or "")[:10], description=j.get("description", ""), salary_text=sal))
        http.sleep()
    return out


AGGREGATORS.update({"workingnomads": workingnomads, "weworkremotely": weworkremotely, "themuse": themuse,
                    "jobicy": jobicy, "adzuna": adzuna})


# ------------------------------------------------------------------ added 2026-10-30
import base64  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

from . import ats as _ats  # noqa: E402

def workable_search(http, days=7):
    """Cross-company search on jobs.workable.com: companies on Workable that we have no board for. Measured 30.10 over
    30 days: 37 QA titles in NL/BE/DE/FR, 12 not in the DB, 2-3 worth a look."""
    out, seen = [], set()
    for country in SEARCH_COUNTRIES:
        for q in category("workable") or ROLE["keywords"]:
            params = {"query": q, "location": country, "day_range": days}
            for _ in range(5):
                r = http.get("https://jobs.workable.com/api/v1/jobs?" + urlencode(params))
                if not r or r.status_code != 200:
                    break
                data = r.json()
                for j in data.get("jobs", []):
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    loc = j.get("location") or {}
                    out.append(Job(id=f"workablesearch:{j['id']}", source="workablesearch",
                                   company=(j.get("company") or {}).get("title", ""), title=j.get("title", ""),
                                   url=j.get("url", ""), posted=(j.get("created") or "")[:10],
                                   location=", ".join(x for x in (loc.get("city"), loc.get("countryName")) if x),
                                   remote=j.get("workplace") == "remote",
                                   description=strip_html("\n".join(j.get(k) or "" for k in (
                                       "description", "requirementsSection", "benefitsSection"))),
                                   extra={"employment_type": j.get("employmentType") or ""}))
                if not data.get("nextPageToken"):
                    break
                params["pageToken"] = data["nextPageToken"]
                http.sleep()
            http.sleep()
    return out


BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
BA_KEY = {"X-API-Key": "jobboerse-jobsuche"}       # the public key of the Jobsuche web app


def arbeitsagentur(http, days=1):
    """Bundesagentur für Arbeit Jobsuche: every German employer posts there. Measured 30.10: 74 QA titles a week,
    4 of them in English, none a fit; kept because it costs ~10 requests a run and German texts stop at the language
    rule before the LLM. Texts come from the detail endpoint, for new postings only (DETAIL_FETCHERS)."""
    out, seen = [], set()
    for q in ROLE["queries"] + list(category("arbeitsagentur") or []):    # + German titles of the role
        r = http.get(f"{BA}/v6/jobs?" + urlencode({"was": q, "size": 100, "page": 1, "veroeffentlichtseit": days,
                                                   "angebotsart": 1}), headers=BA_KEY)
        if not r or r.status_code != 200:
            continue
        for i in r.json().get("ergebnisliste") or []:
            ref = i["referenznummer"]
            if ref in seen:
                continue
            seen.add(ref)
            adr = ((i.get("stellenlokationen") or [{}])[0]).get("adresse") or {}
            sal = ""
            if i.get("gehaltsspanneVon") and i.get("verguetungsangabe") == "JAHRESGEHALT":
                sal = f"€{i['gehaltsspanneVon']:.0f}-{i.get('gehaltsspanneBis') or i['gehaltsspanneVon']:.0f} per year"
            out.append(Job(id=f"arbeitsagentur:{ref}", source="arbeitsagentur", company=i.get("firma", ""),
                           title=i.get("stellenangebotsTitel", ""), url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                           location=", ".join(x for x in (adr.get("ort"), "Germany") if x),
                           posted=i.get("datumErsteVeroeffentlichung", ""), salary_text=sal))
        http.sleep()
    return out


def detail_arbeitsagentur(http, job):
    ref = job.id.split(":", 1)[1]
    r = http.get(f"{BA}/v4/jobdetails/" + base64.b64encode(ref.encode()).decode(), headers=BA_KEY)
    if not r or r.status_code != 200:
        return ""
    try:
        return r.json().get("stellenangebotsBeschreibung", "")
    except ValueError:
        return ""


AGGREGATORS.update({"workable_search": workable_search, "arbeitsagentur": arbeitsagentur})
_ats.DETAIL_FETCHERS["arbeitsagentur"] = detail_arbeitsagentur


# ------------------------------------------------------------------ added 2026-11-03: hiringcafe
import collections
import json as _json
import time as _time
from datetime import datetime as _datetime, timedelta as _timedelta
from urllib.parse import quote as _quote, unquote as _unquote, urlparse as _urlparse

HC_DEFAULTS = {
    "countries": [],        # по умолчанию — целевые страны профиля (config.load), иначе hiringcafe.countries
    "queries": [],          # по умолчанию — первые два role.queries, иначе hiringcafe.queries
    "fresh_days": 21,       # и MCP-фильтр, и cutoff для SSR-hit'ов из Jina
    "limit": 25,            # официальный MCP отдаёт до 25 вакансий на поиск, без пагинации
    "max_per_company": 5,   # верхний предел MCP; по умолчанию у него 1, что теряет роли одной компании
    "max_calls": 60,        # потолок запросов MCP на один поиск (страницы + пачки работодателей + разбиение);
                            # qa в NL за 21 день 05.11 — 9 запросов
    "pages": 3,             # потолок SSR-страниц только для Jina fallback (страница — до ~70 hit'ов)
    "jina_delay": 3.5,      # keyless Jina: 20 запросов/мин; держим не больше ~17 RPM
}

_GEO = {"Netherlands": ("Netherlands", "NL", 52.1326, 5.2913), "Belgium": ("Belgium", "BE", 50.5039, 4.4699),
        "Germany": ("Germany", "DE", 51.1657, 10.4515), "France": ("France", "FR", 46.6034, 1.8883)}

_HC_MCP = "https://hiringcafe.com/api/mcp"
_HC_CHATGPT_MCP = "https://hiringcafe.com/api/chatgpt/mcp"
_HC_MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _hc_log(msg):
    from datetime import datetime
    print(f"[{datetime.now():%H:%M:%S}] hiringcafe: {msg}", flush=True)


def _hc_settings():
    """Секция hiringcafe из config.yaml + my/config.yaml (configure); чего там нет — HC_DEFAULTS."""
    cfg = HC_DEFAULTS.copy()
    cfg.update({k: v for k, v in HC_CONFIG.items() if v is not None})
    return cfg


def _hc_mcp(http, tool, arguments, endpoint=_HC_MCP, structured=False):
    """Официальный read-only MCP HiringCafe. В отличие от HTML/API GET, на VPS этот endpoint не попадает под
    Cloudflare challenge (проверка 04.11). Аккаунт и initialize handshake не нужны: tools/call работает одним POST."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    r = http.post(endpoint, json=body, headers=_HC_MCP_HEADERS)
    if r is None:
        raise RuntimeError("MCP: нет ответа после повторов")
    if r.status_code != 200:
        raise RuntimeError(f"MCP: HTTP {r.status_code}")
    try:
        payload = r.json()
        result = payload["result"]
        if payload.get("error") or result.get("isError"):
            raise ValueError("tool error")
        if structured:
            return result
        texts = [c["text"] for c in result["content"] if c.get("type") == "text" and c.get("text")]
        if not texts:
            raise ValueError("no text content")
        return "\n".join(texts)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"MCP: битый ответ ({e})") from e


def _hc_jina_get(http, url, hc):
    """Jina fallback для SSR-страницы или JSON описания. HTTP 200 с Cloudflare challenge внутри — не пустой ответ,
    а ошибка транспорта. Jina API key необязателен; JINA_API_KEY / HC_JINA_KEY включает более высокий лимит и proxy."""
    api = "/api/" in url
    headers = {"X-Respond-With": "text" if api else "html", "X-No-Cache": "true"}
    key = os.environ.get("JINA_API_KEY") or os.environ.get("HC_JINA_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    r = http.get("https://r.jina.ai/" + url, headers=headers)
    if r is None:
        raise RuntimeError("Jina: нет ответа после повторов")
    if r.status_code != 200:
        raise RuntimeError(f"Jina: HTTP {r.status_code}: {r.text[:120]}")
    if "Just a moment" in r.text or "Performing security verification" in r.text:
        raise RuntimeError("Jina: HiringCafe вернул Cloudflare challenge")
    _time.sleep(hc["jina_delay"])
    return r


def _hc_fields(block):
    """Поля вида `- **Location:** ...` в Markdown-ответе MCP; обратные кавычки вокруг ID необязательны."""
    out = {}
    for line in block.splitlines():
        m = re.match(r"^- \*\*([^:*]+):\*\*\s*(.*)$", line.strip())
        if m:
            out[m.group(1).strip().lower()] = m.group(2).strip().strip("`").strip()
    return out


_HC_CARD = re.compile(r"^### \[((?:\\.|[^\]\\])*)\]\((https://hiringcafe\.com/job/[^)\s]+)\)\s*$")
_HC_COMPANY = re.compile(r"(?m)^\*\*((?:\\.|[^*\n\\])+)\*\*\s*$")


def _hc_unescape(s):
    """Markdown-экранирование MCP: «\\[5-9 years\\]» → «[5-9 years]»."""
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", s).strip()


def _hc_mcp_jobs(text, cutoff):
    """Markdown search_jobs → Job. Карточки режутся по строкам «### », а не по удачно разобранным заголовкам: заголовок
    со скобками («Member of Technical staff 3 \\[5-9 years\\]- SDET …», 04.11) не совпадал с прежней регуляркой,
    карточка приклеивалась к предыдущей, и та получала её Job ID и дату. Неразобранная карточка теряется одна, с
    записью в лог; ответ, где не разобралась ни одна, — битый и включает fallback, а не честные «0 вакансий»."""
    if text.startswith("No jobs matched that search on HiringCafe."):
        return []
    blocks = re.split(r"(?m)^(?=### )", text)[1:]
    if not blocks:
        raise ValueError("MCP: в search_jobs нет карточек")
    jobs, broken = [], []
    for block in blocks:
        head, company = _HC_CARD.match(block.split("\n", 1)[0]), _HC_COMPANY.search(block)
        f = _hc_fields(block)
        jid, posted = f.get("job id", ""), f.get("posted", "")[:10]
        if not head or not company or not jid:
            broken.append(block.split("\n", 1)[0][:120])
            continue
        if posted and posted < cutoff:
            continue
        workplace = f.get("workplace", "")
        jobs.append(Job(id=f"hiringcafe:{jid}", source="hiringcafe", company=_hc_unescape(company.group(1)),
                        title=_hc_unescape(head.group(1)), url=head.group(2), location=f.get("location", "")[:200],
                        posted=posted, remote=workplace.lower() == "remote", salary_text=f.get("compensation", ""),
                        extra={"hc_worktype": workplace, "employment_type": f.get("employment type", ""),
                               "hc_transport": "mcp"}))
    if len(broken) == len(blocks):
        raise ValueError(f"MCP: ни одна карточка не разобрана ({broken[0]})")
    for b in broken:
        _hc_log(f"карточка MCP не разобрана, пропущена: {b}")
    return jobs


def _hc_counts(text, cards):
    """«showing X of Y matches» из заголовка ответа; заголовка нет — показано всё, что совпало."""
    m = re.search(r"showing (\d+) of (\d+) matches", text.split("\n", 1)[0])
    return (int(m.group(1)), int(m.group(2))) if m else (cards, cards)


_HC_SPLITS = (("workplace_types", (["Onsite"], ["Hybrid"], ["Remote"])),
              ("seniority_levels", (["No Prior Experience Required"], ["Entry Level"], ["Mid Level"], ["Senior Level"])),
              ("employment_types", (["Full Time"], ["Part Time"], ["Contract"], ["Internship"], ["Temporary"],
                                    ["Seasonal"], ["Volunteer"])))


class _HcSearch:
    """Все разные вакансии одного поиска search_jobs. Пагинации у MCP нет: карточек не больше `limit` (25) и не больше
    `max_per_company` (5) от работодателя, остальное молча обрезается («showing 25 of 83 matches», qa в NL за 21 день,
    05.11). Обрезку листаем фильтрами самого API:
    - страница упёрлась в лимит → следующая без её работодателей (`exclude_company_names`), а сами они перечитываются
      пачкой (`company_names`): иначе их роли ниже 25-го места выпали бы вместе с ними; пачка в лимите делится пополам;
    - у работодателя 5 карточек и совпадений больше → его поиск режется по режиму работы, уровню, типу найма.
    Остаток «of Y» после этого — копии одного объявления, которые MCP сворачивает в одну карточку (05.11:
    FrieslandCampina разместила «QA Specialist NPD» 21 раз; скрытые копии Adyen и Allseas не отличаются ни одним
    фильтром). Найденное копится в `found` и переживает сбой на середине."""

    def __init__(self, http, hc, base, label):
        self.http, self.hc, self.base, self.label = http, hc, base, label
        self.found, self.calls, self.first = {}, 0, None

    def run(self):
        excluded = []
        while True:
            cards, shown, total = self.page({"exclude_company_names": excluded} if excluded else {})
            self.first = self.first or (shown, total)
            new = list(dict.fromkeys(c.company for c in cards if c.company not in excluded))
            if not cards or shown >= total:
                return
            if not new:
                _hc_log(f"{self.label}: исключение работодателей не сработало, совпадения за ними не видны")
                return
            if shown >= self.hc["limit"]:
                self.employers(new)
            else:
                for name in self.saturated(cards):
                    self.split({"company_names": [name]})
            excluded += new

    def employers(self, names):
        """Все роли этих работодателей в поиске; пачка, упёршаяся в лимит, делится пополам."""
        cards, shown, total = self.page({"company_names": names})
        if shown >= self.hc["limit"] and shown < total and len(names) > 1:
            half = len(names) // 2
            self.employers(names[:half])
            self.employers(names[half:])
            return
        unknown = set(names) - {c.company for c in cards}
        if unknown:
            _hc_log(f"{self.label}: фильтр company_names не узнал {sorted(unknown)}, их роли ниже 25-го места не видны")
        if shown < total:
            for name in self.saturated(cards):
                self.split({"company_names": [name]})

    def split(self, args, depth=0):
        """Работодатель с `max_per_company` карточками и совпадениями сверх них: поиск делится по следующему фильтру."""
        if depth == len(_HC_SPLITS):
            _hc_log(f"{self.label}: {args['company_names'][0]} — больше {self.hc['max_per_company']} ролей в одной "
                    f"ячейке фильтров {args}, часть не видна")
            return
        key, values = _HC_SPLITS[depth]
        for value in values:
            cards, shown, total = self.page({**args, key: value})
            if shown >= self.hc["max_per_company"] and shown < total:
                self.split({**args, key: value}, depth + 1)

    def saturated(self, cards):
        per = collections.Counter(c.company for c in cards)
        return [name for name, n in per.items() if n >= self.hc["max_per_company"]]

    def page(self, args):
        if self.calls >= self.hc["max_calls"]:
            raise RuntimeError(f"потолок {self.hc['max_calls']} запросов на поиск")
        self.calls += 1
        try:
            text = _hc_mcp(self.http, "search_jobs", {**self.base, **args})
        finally:
            self.http.sleep()
        cards = _hc_mcp_jobs(text, "")
        for c in cards:
            self.found.setdefault(c.id, c)
        return (cards, *_hc_counts(text, len(cards)))


def _hc_mcp_description(text, jid):
    """get_job_details → полный текст. ID сверяем, чтобы не присвоить вакансии чужое описание."""
    f = _hc_fields(text.split("## Full description", 1)[0])
    if f.get("job id") != jid:
        raise ValueError("MCP: Job ID в описании не совпадает с запрошенным")
    parts = text.split("## Full description", 1)
    if len(parts) != 2 or not parts[1].strip():
        raise ValueError("MCP: нет Full description")
    return parts[1].strip()


def _hc_structured_salary(c):
    """Compensation из ChatGPT MCP → текст для прежних зарплатных эвристик."""
    if not c:
        return ""
    cur, freq = c.get("currency") or "", (c.get("frequency") or "").lower()
    period = {"yearly": "per year", "monthly": "per month", "weekly": "per week", "hourly": "per hour",
              "daily": "per day"}.get(freq)
    lo, hi = c.get("minimum"), c.get("maximum")
    if not cur or not period or not (lo or hi):
        return ""
    if lo and hi:
        return f"{cur} {lo:g}-{hi:g} {period}"
    return f"{cur} from {lo or hi:g} {period}"


def _hc_chatgpt_jobs(result, cutoff):
    """structuredContent.search_hiringcafe_jobs → Job. Это второй официальный MCP, не зеркало и не прокси."""
    try:
        rows = result["structuredContent"]["jobs"]
        assert isinstance(rows, list)
    except (KeyError, TypeError, AssertionError) as e:
        raise ValueError(f"ChatGPT MCP: нет structuredContent.jobs ({e})") from e
    jobs = []
    for h in rows:
        jid, posted = h.get("id") or "", (h.get("datePosted") or "")[:10]
        if not jid:
            raise ValueError("ChatGPT MCP: у карточки нет ID")
        if posted and posted < cutoff:
            continue
        workplace = h.get("workplaceType") or ""
        jobs.append(Job(id=f"hiringcafe:{jid}", source="hiringcafe", company=h.get("company") or "",
                        title=h.get("title") or "", url=h.get("applyUrl") or f"https://hiringcafe.com/job/{jid}",
                        location=(h.get("location") or "")[:200], posted=posted, remote=workplace.lower() == "remote",
                        salary_text=_hc_structured_salary(h.get("compensation")),
                        extra={"hc_worktype": workplace, "employment_type": ", ".join(h.get("employmentTypes") or []),
                               "hc_transport": "chatgpt_mcp"}))
    return jobs


def _hc_search(http, query, country, hc, fetch=None):
    """Резервные транспорты после MCP: настоящий Chrome (fetch(url) → HTML, см. hc_chrome) затем
    keyless Jina: SSR /classic?searchState=... → __NEXT_DATA__.pageProps.ssrHits. Возвращает
    (hits, complete); сбой теряет только текущий поиск, уже прочитанные страницы сохраняются."""
    name, cc, lat, lon = country
    state = {"searchQuery": query,
             "locations": [{"formatted_address": name, "types": ["country"],
                            "geometry": {"location": {"lat": str(lat), "lon": str(lon)}}, "id": cc.lower(),
                            "address_components": [{"long_name": name, "short_name": cc, "types": ["country"]}]}],
             "workplaceTypes": ["Onsite", "Remote", "Hybrid"], "sortBy": "default"}
    out, complete = [], True
    for page in range(hc["pages"]):
        url = f"https://hiringcafe.com/classic?searchState={_quote(_json.dumps(state))}&page={page}"
        try:
            text = fetch(url) if fetch else None       # chrome решает челлендж сам; None — идём к Jina
            if text is None:
                text = _hc_jina_get(http, url, hc).text
        except Exception as e:
            _hc_log(f"{name} {query!r}, страница {page}: {e}")
            complete = False
            break
        pp = _hc_page_props(text)
        if pp is None:
            if "Just a moment" in text:
                _hc_log(f"{name} {query!r}: в тексте страницы живёт челлендж")
            else:
                _hc_log(f"{name} {query!r}: в тексте нет __NEXT_DATA__ → pageProps.ssrHits — разметка поменялась?")
            complete = False
            break
        if pp.get("ssrError"):
            _hc_log(f"{name} {query!r}: ssrError {str(pp['ssrError'])[:150]}")
            complete = False
            break
        out += [h for h in pp["ssrHits"] or [] if not h.get("is_expired")]
        if pp.get("ssrIsLastPage", True):
            break
    return out, complete


def _hc_page_props(html):
    """pageProps из __NEXT_DATA__ SSR-страницы или None, если разметка не та: нет скрипта, битый JSON, нет ssrHits."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        pp = _json.loads(m.group(1))["props"]["pageProps"]
    except (AttributeError, ValueError, KeyError, TypeError):
        return None
    return pp if isinstance(pp, dict) and "ssrHits" in pp else None


def _hc_company(hit):
    """HiringCafe приписывает каждое объявление доски организации; имя в attributed_org / enriched_company_data
    (проверка 03.11 на 46 hit'ов: есть всегда). Фолбэк: слаг компании из board_token, затем домен из apply_url."""
    for src in ("attributed_org", "enriched_company_data"):
        name = (hit.get(src) or {}).get("name")
        if name:
            return name
    token = _unquote(str(hit.get("board_token") or "")).split("/")[0]
    m = re.match(r"[A-Za-z0-9\-_.]+", token)
    if m and m.group(0):
        return m.group(0).replace("-", " ").replace("_", " ").title()
    host = re.sub(r"^(www|jobs?|careers?|boards?)\.", "", _urlparse(hit.get("apply_url") or "").netloc or "", flags=re.I)
    return (host or "(hiringcafe)").replace("-", " ")


def _hc_salary(v5):
    """Прозрачная ставка — [min..max] одной из частот; например «EUR 80000-105000 per year» (слова eur/year
    parse_salary берёт). Часовые/дневные остаются явными: эвристика pay_rate работает по ним так же, как по
    объявлениям с текстом."""
    cur = (v5.get("listed_compensation_currency") or "").strip()
    tail = {"Yearly": ("yearly", "per year"), "Monthly": ("monthly", "per month"), "Weekly": ("weekly", "per week"),
            "Hourly": ("hourly", "per hour"), "Daily": ("daily", "per day"),
            "Bi-weekly": ("bi-weekly", "per 2 weeks")}.get(v5.get("listed_compensation_frequency"))
    if not cur or len(cur) != 3 or not tail:
        return ""
    low, high = v5.get(tail[0] + "_min_compensation"), v5.get(tail[0] + "_max_compensation")
    if not low and not high:
        return ""
    low, high = (low or 0), (high or 0)
    if low and high:
        return f"{cur} {low:g}-{high:g} {tail[1]}"
    return f"{cur} from {max(low, high):g} {tail[1]}"


_CC = {"nl": "Netherlands", "be": "Belgium", "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy",
       "pt": "Portugal", "pl": "Poland", "ro": "Romania", "cz": "Czechia", "gr": "Greece", "at": "Austria",
       "se": "Sweden", "dk": "Denmark", "fi": "Finland", "ie": "Ireland", "lu": "Luxembourg", "no": "Norway",
       "ch": "Switzerland", "gb": "United Kingdom", "rs": "Serbia", "ua": "Ukraine", "tr": "Turkey", "il": "Israel"}


def _hc_location(v5):
    """formatted_workplace_location часто перечисляет только города («Mechelen or Puurs or Antwerpen»), а трек и
    in_search_area в фильтрах работают с текстом локации: добавляем названия стран из workplace_countries."""
    parts = [(v5.get("formatted_workplace_location") or "").strip()]
    for cc in (v5.get("workplace_countries") or []):
        name = _CC.get(str(cc).lower())
        if name and not re.search(rf"\b{re.escape(name)}\b", parts[0], re.I):
            parts.append(name)
    out = ""
    for p in parts:
        out = (out + ", " + p) if out else p
    return out[:200]


def _hc_job(hit, cutoff):
    """Hit → Job; вакансия старше cutoff (по estimated_publish_date) теряется. Дату сайт берёт из ATS, и в индексе
    встречаются годы наперёд старые (2011) — поэтому cutoff свежести обязателен."""
    v5, ji = hit.get("v5_processed_job_data") or {}, hit.get("job_information") or {}
    jid = _unquote(str(hit.get("id") or ""))
    posted = (v5.get("estimated_publish_date") or "")[:10]
    if not jid or (posted and posted < cutoff):
        return None
    wtype = v5.get("workplace_type") or ""
    return Job(id=f"hiringcafe:{jid}", source="hiringcafe",
               company=_hc_company(hit), title=ji.get("title") or v5.get("core_job_title") or "",
               url=hit.get("apply_url") or f"https://hiringcafe.com/job/{jid}",
               location=_hc_location(v5), posted=posted, remote=wtype == "Remote",
               salary_text=_hc_salary(v5),
               extra={"hc_ats": hit.get("source") or "", "hc_worktype": wtype})


def hiringcafe(http):
    """Официальный MCP search_jobs (04.11 с VPS: 200, тогда как HTML и Jina получают Cloudflare challenge), каждый
    запрос+страна за `fresh_days` читается целиком (`_HcSearch`: у MCP нет пагинации, её заменяют фильтры по
    работодателям). Поиск, не давший ничего (ошибка или пусто), уходит в SSR-страницы через настоящий Chrome (если
    он на месте), затем keyless Jina, затем ChatGPT MCP. Дедуп по id здесь, по компании+заголовку — в конвейере."""
    hc = _hc_settings()
    cutoff = (_datetime.utcnow() - _timedelta(days=hc["fresh_days"])).strftime("%Y-%m-%d")
    chrome = _hc_chrome_fetcher()
    flat, seen = [], set()
    for query in hc["queries"]:
        for cname in hc["countries"]:
            country = _GEO.get(cname)
            if not country:
                _hc_log(f"unknown country {cname!r} (нет в presets/countries.yaml), skipped")
                continue
            search = _HcSearch(http, hc, {"search": query, "location": cname,
                                          "workplace_types": ["Onsite", "Remote", "Hybrid"],
                                          "posted_within_days": hc["fresh_days"], "limit": hc["limit"],
                                          "max_per_company": hc["max_per_company"]}, f"{cname} {query!r}")
            try:
                search.run()
            except Exception as e:
                _hc_log(f"{cname} {query!r}: MCP {e}; найдено до сбоя: {len(search.found)}")
            jobs = [j for j in search.found.values() if not (j.posted and j.posted < cutoff)]
            if search.calls > 1 and search.first:
                _hc_log(f"{cname} {query!r}: первая страница — {search.first[0]} из {search.first[1]}, всего разных "
                        f"{len(search.found)} за {search.calls} запросов (остаток — копии одного объявления)")
            if not jobs:
                _hc_log(f"{cname} {query!r}: MCP ничего не дал, пробую chrome/Jina")
                hits, complete = _hc_search(http, query, country, hc, fetch=chrome)
                if not complete:
                    _hc_log(f"{cname} {query!r}: резервные транспорты не дочитали выдачу, остальное в следующем прогоне")
                jobs = [j for h in hits if (j := _hc_job(h, cutoff)) is not None]
            if not jobs:
                try:
                    prompt = (f"{query} jobs in {cname}, remote hybrid or onsite, "
                              f"posted within the last {hc['fresh_days']} days")
                    result = _hc_mcp(http, "search_hiringcafe_jobs", {"prompt": prompt, "limit": hc["limit"]},
                                     endpoint=_HC_CHATGPT_MCP, structured=True)
                    jobs = _hc_chatgpt_jobs(result, cutoff)
                    if jobs:
                        _hc_log(f"{cname} {query!r}: получено через ChatGPT MCP fallback")
                except Exception as e:
                    _hc_log(f"{cname} {query!r}: ChatGPT MCP fallback failed: {e}")
                    jobs = []
            for j in jobs:
                if j.id not in seen:
                    seen.add(j.id)
                    flat.append(j)
    return flat


def _hc_json_description(r):
    """Ответ с описанием (HTTP-ответ Jina или строка JSON от Chrome через view-source) → текст.
    Ответ читаем json(), если есть: Jina при успехе отдаёт сам JSON; терпим и HTML <pre>, и Reader-обёртку."""
    payload = None
    if not isinstance(r, str):
        try:
            payload = r.json()
        except (ValueError, AttributeError):
            pass
        if payload is None:
            r = r.text
    if payload is None:
        try:
            payload = _json.loads(r)
        except ValueError:
            body = _html.unescape(strip_html(r))
            start = body.find("{")
            if start < 0:
                raise ValueError("в ответе описания нет JSON")
            payload = _json.loads(body[start:])
    return strip_html(((payload.get("job") or {}).get("job_information") or {}).get("description") or "")


def _hc_chrome_fetcher():
    """fetch(url) → HTML страницы или JSON-тело через настоящий Chrome (sources/hc_chrome.py); None —
    транспорт недоступен или сбой: наверх идёт Jina. Chrome решает челлендж сам, поэтому Jina, через
    которую датацентровый IP под challenge только читает заглушку, живёт после него."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        from . import hc_chrome
        if not hc_chrome.enabled():
            return None

        def fetch(url):
            body = hc_chrome.json_text(url) if "/api/" in url else hc_chrome.page_html(url)
            if body:
                _hc_log(f"chrome: получено {len(body)} байт")
                return body
            _hc_log("chrome: текста нет, продолжаю по цепочке")
            return None

        return fetch
    except Exception as e:
        _hc_log(f"chrome недоступен: {e}")
        return None


def detail_hiringcafe(http, job):
    """Полное описание: Claude MCP → Chrome JSON → Jina JSON → ChatGPT MCP. Если все пути не ответили,
    исключение оставляет description пустым: backfill следующего прогона повторит,
    «(no description)» закрыло бы вакансии путь к LLM."""
    jid = _unquote(job.id.split(":", 1)[1])
    errors = []                       # имя из `except … as e` Python удаляет после блока: копим текст ошибок сами
    try:
        return _hc_mcp_description(_hc_mcp(http, "get_job_details", {"job_id": jid}), jid)
    except Exception as e:
        errors.append(f"MCP: {e}")
        _hc_log(f"{jid}: описание MCP не загружено ({e}); пробую chrome")
    fetch = _hc_chrome_fetcher()
    if fetch:
        try:
            body = fetch("https://hiringcafe.com/api/job-description?id=" + _quote(jid))
            if not body:
                raise ValueError("chrome не вернул текст")
            description = _hc_json_description(body)
            if not description:
                raise ValueError("chrome: пустое описание")
            return description
        except Exception as e:
            errors.append(f"chrome: {e}")
            _hc_log(f"{jid}: chrome не загрузил описание ({e}); пробую Jina")
    try:
        r = _hc_jina_get(http, "https://hiringcafe.com/api/job-description?id=" + _quote(jid), _hc_settings())
        description = _hc_json_description(r)
        if not description:
            raise ValueError("Jina: пустое описание")
        return description
    except Exception as e:
        errors.append(f"Jina: {e}")
        _hc_log(f"{jid}: Jina не загрузила описание ({e}); пробую ChatGPT MCP")
    try:
        text = _hc_mcp(http, "get_hiringcafe_job_details", {"job_id": jid}, endpoint=_HC_CHATGPT_MCP)
        return _hc_mcp_description(text, jid)
    except Exception as e:
        errors.append(f"ChatGPT MCP: {e}")
    raise RuntimeError("описание не загружено; " + "; ".join(errors))


AGGREGATORS["hiringcafe"] = hiringcafe
_ats.DETAIL_FETCHERS["hiringcafe"] = detail_hiringcafe
