"""Company job boards via public ATS APIs. Each fetcher returns a list of Job for one company."""
import html
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ..filters import is_relevant_title
from ..models import Job

TT = "{https://teamtailor.com/locations}"       # namespace of city/country in the Teamtailor RSS feed
KEYWORDS = ("test", "QA", "quality engineer", "SDET")   # site searches where a board is too big to read whole;
                                                        # replaced by role.keywords from the profile (configure)


def configure(profile):
    """Corporate career sites and huge SmartRecruiters boards are searched by the role's short keywords."""
    global KEYWORDS
    kw = (profile.get("role") or {}).get("keywords")
    if kw:
        KEYWORDS = tuple(kw)


def strip_html(s):
    if not s:
        return ""
    s = html.unescape(s)
    return re.sub(r"\s+\n", "\n", BeautifulSoup(s, "html.parser").get_text("\n", strip=True))


def greenhouse(http, company, slug):
    r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not r or r.status_code != 200:
        return None
    out = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job(id=f"greenhouse:{slug}:{j['id']}", source="greenhouse", company=company,
                       title=j["title"], url=j["absolute_url"], location=loc,
                       posted=(j.get("updated_at") or "")[:10], description=strip_html(j.get("content", ""))))
    return out


def lever(http, company, slug):
    r = http.get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not r or r.status_code != 200:
        return None
    out = []
    for j in r.json():
        cat = j.get("categories", {})
        loc = ", ".join(x for x in [cat.get("location"), cat.get("allLocations") and " / ".join(cat["allLocations"])] if x)
        desc = strip_html(j.get("descriptionPlain") or j.get("description", ""))
        desc += "\n" + "\n".join(strip_html(l.get("text", "")) for l in j.get("lists", []))
        ts = j.get("createdAt")
        posted = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
        out.append(Job(id=f"lever:{slug}:{j['id']}", source="lever", company=company, title=j["text"],
                       url=j["hostedUrl"], location=loc, posted=posted, description=desc,
                       remote=(j.get("workplaceType") == "remote")))
    return out


def ashby(http, company, slug):
    r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    if not r or r.status_code != 200:
        return None
    out = []
    for j in r.json().get("jobs", []):
        loc = j.get("location", "") or ""
        sec = j.get("secondaryLocations") or []
        if sec:
            loc += " / " + " / ".join(s.get("location", "") for s in sec)
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "") or ""
        out.append(Job(id=f"ashby:{slug}:{j['id']}", source="ashby", company=company, title=j["title"],
                       url=j.get("jobUrl") or j.get("applyUrl", ""), location=loc,
                       posted=(j.get("publishedAt") or "")[:10], remote=bool(j.get("isRemote")),
                       description=strip_html(j.get("descriptionHtml") or j.get("descriptionPlain", "")),
                       salary_text=comp))
    return out


def recruitee(http, company, slug):
    r = http.get(f"https://{slug}.recruitee.com/api/offers/")
    if not r or r.status_code != 200:
        return None
    out = []
    for j in r.json().get("offers", []):
        loc = j.get("location") or ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        desc = strip_html((j.get("description") or "") + "\n" + (j.get("requirements") or ""))
        sal = j.get("salary") or {}
        sal_txt = f"€{sal.get('min')}-{sal.get('max')} per {sal.get('period')}" if sal.get("min") else ""
        out.append(Job(id=f"recruitee:{slug}:{j['id']}", source="recruitee", company=company, title=j["title"],
                       url=j.get("careers_url", ""), location=loc, posted=(j.get("published_at") or "")[:10],
                       remote=bool(j.get("remote")), description=desc, salary_text=sal_txt))
    return out


def workable(http, company, slug):
    """The widget endpoint returns every job with its text in one request; the v3 jobs API used before gave 10 per page
    and only the first page was read (European Dynamics has 190 open jobs)."""
    r = http.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if not r or r.status_code != 200:
        return None
    out = []
    for j in r.json().get("jobs", []):
        locs = [", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in j.get("locations") or []]
        loc = " / ".join(x for x in locs if x) or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        out.append(Job(id=f"workable:{slug}:{j['shortcode']}", source="workable", company=company,
                       title=j["title"], url=f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
                       location=loc, posted=j.get("published_on") or "",
                       remote=str(j.get("telecommuting")).lower() == "true", description=strip_html(j.get("description")),
                       extra={"employment_type": j.get("employment_type") or ""}))
    return out


def smartrecruiters(http, company, slug, pages=5, queries=None):
    """Up to 500 postings are read in full (Lely lists 110). Bigger boards (Continental 559, Sixt and Auto1 over 500,
    Bosch thousands) are read by keyword instead: the API's `q` matches title and text ("test" on Continental: 39)."""
    queries = queries or KEYWORDS
    found = {}
    total = _smartrecruiters_read(http, company, slug, "", pages, found)
    if total is None:
        return None
    if total > pages * 100:
        found.clear()
        for q in queries:
            _smartrecruiters_read(http, company, slug, q, pages, found)
    return list(found.values())


def _smartrecruiters_read(http, company, slug, q, pages, found):
    """Pages of one search into `found` (id -> Job); returns totalFound, or None if the first page failed."""
    total = None
    for page in range(pages):
        r = http.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={page * 100}"
                     + (f"&q={q}" if q else ""))
        if not r or r.status_code != 200:
            return total
        data = r.json()
        total = data.get("totalFound", 0)
        if not q and total > pages * 100:
            return total
        for j in data.get("content", []):
            loc = j.get("location") or {}
            found[j["id"]] = Job(id=f"smartrecruiters:{slug}:{j['id']}", source="smartrecruiters", company=company,
                                 title=j["name"], url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                                 location=", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                                 posted=(j.get("releasedDate") or "")[:10], remote=bool(loc.get("remote")),
                                 extra={"country": (loc.get("country") or "").upper()})
        if (page + 1) * 100 >= total:
            break
        http.sleep()
    return total


def workday(http, company, slug, queries=None, pages=5):
    """slug = 'tenant/wd3/SiteName' e.g. 'maersk/wd3/Maersk_Careers'. 20 postings per page, up to `pages` per query
    (Airbus: 150 hits for "test" in Germany alone). A posting in several cities says only "3 Locations"; for QA titles
    the cities come from the posting itself, otherwise the location filter would drop it."""
    queries = queries or KEYWORDS
    tenant, wd, site = slug.split("/")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    seen, out = set(), []
    for q in queries:
        total = 0
        for page in range(pages):
            r = http.post(f"{base}/wday/cxs/{tenant}/{site}/jobs", json={"appliedFacets": {}, "limit": 20,
                          "offset": page * 20, "searchText": q}, headers={"Content-Type": "application/json"})
            if not r or r.status_code != 200:
                return out or None
            data = r.json()
            for j in data.get("jobPostings", []):
                path = j.get("externalPath", "")
                if path in seen:
                    continue
                seen.add(path)
                job = Job(id=f"workday:{tenant}:{path.rsplit('_', 1)[-1] or path}", source="workday",
                          company=company, title=j.get("title", ""), url=f"{base}/{site}{path}",
                          location=j.get("locationsText", ""), posted="")
                if re.fullmatch(r"\d+ Locations?", job.location) and is_relevant_title(job.title):
                    job.location = _workday_locations(http, base, tenant, site, path) or job.location
                out.append(job)
            http.sleep()
            total = data.get("total") or total     # only the first page carries the total
            if (page + 1) * 20 >= total:
                break
    return out


def _workday_locations(http, base, tenant, site, path):
    r = http.get(f"{base}/wday/cxs/{tenant}/{site}{path}")
    if not r or r.status_code != 200:
        return ""
    info = r.json().get("jobPostingInfo", {})
    return " / ".join([info.get("location", "")] + list(info.get("additionalLocations") or []))[:200]


def teamtailor(http, company, slug):
    """The RSS feed lists every open job with its cities and text. The /jobs page scraped before showed only the first
    20 and glued "Department · City · Mode" into the title with no location, so Fortaegis' QA role in Amsterdam sat in
    track "other" and never reached the LLM (06.09-30.10)."""
    r = http.get(f"https://{slug}.teamtailor.com/jobs.rss")
    if not r or r.status_code != 200:
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return None
    out = []
    for it in root.iter("item"):
        link = it.findtext("link") or ""
        m = re.search(r"/jobs/(\d+)", link)
        if not m:
            continue
        locs = []
        for loc in it.iter(f"{TT}location"):
            city, country = (loc.findtext(f"{TT}city") or "").strip(), (loc.findtext(f"{TT}country") or "").strip()
            locs.append(", ".join(x for x in (city, country) if x) or (loc.findtext(f"{TT}name") or "").strip())
        pub = it.findtext("pubDate")
        out.append(Job(id=f"teamtailor:{slug}:{m.group(1)}", source="teamtailor", company=company,
                       title=(it.findtext("title") or "").strip(), url=link, location=" / ".join(x for x in locs if x),
                       posted=parsedate_to_datetime(pub).strftime("%Y-%m-%d") if pub else "",
                       remote=(it.findtext("remoteStatus") == "fully"), description=strip_html(it.findtext("description"))))
    return out


def personio(http, company, slug):
    """German startups and mid-size companies mostly use Personio; its XML feed has every open position with text.
    Offices are company-named ("Salto CloudWorks Amsterdam"), so the location filter matches them by city."""
    r = http.get(f"https://{slug}.jobs.personio.de/xml?language=en")
    if not r or r.status_code != 200:
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return None
    out = []
    for p in root.iter("position"):
        pid = (p.findtext("id") or "").strip()
        offices = [p.findtext("office") or ""] + [o.text or "" for o in p.iter("additionalOffice")]
        text = "\n".join(f"{d.findtext('name') or ''}\n{d.findtext('value') or ''}" for d in p.iter("jobDescription"))
        out.append(Job(id=f"personio:{slug}:{pid}", source="personio", company=company,
                       title=(p.findtext("name") or "").strip(), url=f"https://{slug}.jobs.personio.de/job/{pid}",
                       location=" / ".join(o.strip() for o in offices if o.strip()),
                       posted=(p.findtext("createdAt") or "")[:10], description=strip_html(text),
                       extra={"employment_type": "Contract"} if p.findtext("employmentType") == "freelance" else {}))
    return out


# ------------------------------------------------------------------ corporate career sites (large German employers)
# These have no public board API with every posting, only a site search: they are read by KEYWORDS, and the later
# title and location filters keep what matters. Descriptions come from the job page (detail_page).
EU_CODES = {"DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "FR": "France", "AT": "Austria", "ES": "Spain",
            "PT": "Portugal", "IT": "Italy", "PL": "Poland", "CZ": "Czechia", "RO": "Romania", "HU": "Hungary",
            "IE": "Ireland", "DK": "Denmark", "SE": "Sweden", "FI": "Finland", "CH": "Switzerland", "LU": "Luxembourg"}


def with_country(location):
    """SuccessFactors writes "Herzogenaurach, BY, DE" or "Zaragoza, ES, Aragon": a city outside the country regexes
    and a bare ISO code. A last part that is a code outside the list ("Wilmington, DE, US") is the country."""
    parts = [p.strip() for p in (location or "").split(",")]
    if re.fullmatch(r"[A-Z]{2}", parts[-1]):
        code = parts[-1]
    else:
        code = next((p for p in parts[1:] if p in EU_CODES), "")
    return f"{location}, {EU_CODES[code]}" if code in EU_CODES else location


def rmk(http, company, host, queries=None, pages=4):
    """SAP SuccessFactors career sites (jobs.adidas-group.com, jobs.zf.com, jobs.gft.com...): server-rendered search,
    rows `tr.data-row` (classic) or `job-tile` blocks, the count in the table's aria-label."""
    queries = queries or KEYWORDS
    found = {}
    for q in queries:
        start = 0
        for _ in range(pages):
            r = http.get(f"https://{host}/search/?q={q}&startrow={start}")
            if not r or r.status_code != 200:
                return None if not found and q == queries[0] else list(found.values())
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("tr.data-row") or soup.select("li.job-tile, div.job-tile")
            for row in rows:
                a = row.select_one("a.jobTitle-link")
                if not a or not a.get("href"):
                    continue
                m = re.search(r"/(\d+)/?$", a["href"])
                jid = m.group(1) if m else a["href"]
                date = row.select_one(".jobDate")
                found.setdefault(jid, Job(
                    id=f"rmk:{host}:{jid}", source="rmk", company=company, title=a.get_text(" ", strip=True),
                    url=f"https://{host}{a['href']}", location=with_country(_rmk_location(row)),
                    posted=_rmk_date(date.get_text(strip=True) if date else "")))
            total = re.search(r"Results? \d+ (?:to|–|-) \d+ of ([\d,.]+)", r.text)
            start += len(rows)
            if not rows or not total or start >= int(re.sub(r"\D", "", total.group(1))):
                break
            http.sleep()
    return list(found.values())


def _rmk_location(row):
    """Classic rows have span.jobLocation; tiles have fields "job-N-desktop-section-<field>-value" (Hannover Re:
    city and country "DE" as separate fields, no location field)."""
    loc = row.select_one(".jobLocation")
    if loc:
        return loc.get_text(" ", strip=True)
    fields = {}
    for el in row.select("[id*=desktop-section-]"):
        m = re.search(r"desktop-section-(location|city|country)-value$", el.get("id", ""))
        if m:
            fields[m.group(1)] = el.get_text(" ", strip=True)
    return fields.get("location") or ", ".join(fields[k] for k in ("city", "country") if fields.get(k))


def _rmk_date(text):
    try:
        return datetime.strptime(text, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def beesite(http, company, base, queries=None, pages=3):
    """Milch & Zucker BeeSite "GJB" search API (Mercedes-Benz, Porsche, Deutsche Bank, Daimler Truck, Commerzbank).
    `base` is the API host. The keyword criterion is a fuzzy full-text match ("test" alone: 1447 of Mercedes' 2691
    jobs), there is no working country criterion; the location filter downstream does that."""
    queries = queries or KEYWORDS
    found, fields = {}, ["ID", "PositionTitle", "PositionURI", "PositionLocation.CountryName",
                         "PositionLocation.CityName", "PublicationStartDate"]
    for q in queries:
        for page in range(pages):
            data = {"LanguageCode": "EN", "SearchParameters": {"FirstItem": page * 100 + 1, "CountItem": 100,
                                                                "MatchedObjectDescriptor": fields},
                    "SearchCriteria": [{"CriterionName": "PositionFormattedDescription.Content", "CriterionValue": [q]}]}
            r = http.get(f"https://{base}/search/", params={"data": json.dumps(data)})
            if not r or r.status_code != 200:
                return None if not found and q == queries[0] else list(found.values())
            res = r.json().get("SearchResult", {})
            for it in res.get("SearchResultItems", []):
                m = {"ID": it.get("MatchedObjectId"), **it.get("MatchedObjectDescriptor", {})}
                locs = [", ".join(x for x in (l.get("CityName"), l.get("CountryName")) if x)
                        for l in m.get("PositionLocation") or []]
                found.setdefault(m["ID"], Job(id=f"beesite:{base}:{m['ID']}", source="beesite", company=company,
                                              title=m.get("PositionTitle", ""), url=m.get("PositionURI", ""),
                                              location=" / ".join(x for x in locs if x),
                                              posted=(m.get("PublicationStartDate") or "")[:10]))
            if (page + 1) * 100 >= res.get("SearchResultCountAll", 0):
                break
            http.sleep()
    return list(found.values())


def phenom(http, company, host, queries=None, pages=3, lang="en_global"):
    """Phenom People career sites (careers.allianz.com, careers.dhl.com, careers.siemens-healthineers.com,
    careers.merckgroup.com): the `refineSearch` widget call the site itself makes. A fuller body copied from the
    browser (refNum, pageId...) answered empty on three of the four sites. The `descriptionTeaser` is not kept: a
    non-empty description would stop the full text from loading (detail_page), and the teaser is too short for the LLM."""
    queries = queries or KEYWORDS
    found = {}
    for q in queries:
        for page in range(pages):
            body = {"lang": lang, "ddoKey": "refineSearch", "keywords": q, "from": page * 100, "size": 100,
                    "jobs": True, "counts": True, "all_fields": ["country"], "selected_fields": {}}
            r = http.post(f"https://{host}/widgets", json=body)
            if not r or r.status_code != 200:
                return None if not found and q == queries[0] else list(found.values())
            res = (r.json() or {}).get("refineSearch") or {}
            for j in (res.get("data") or {}).get("jobs") or []:
                locs = j.get("multi_location") or [j.get("location") or ""]
                found.setdefault(j["jobId"], Job(id=f"phenom:{host}:{j['jobId']}", source="phenom", company=company,
                                                 title=j.get("title", ""), url=f"https://{host}/global/en/job/{j['jobId']}",
                                                 location=" / ".join(x for x in locs if x)[:200],
                                                 posted=(j.get("postedDate") or "")[:10]))
            if (page + 1) * 100 >= res.get("totalHits", 0):
                break
            http.sleep()
    return list(found.values())


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "recruitee": recruitee,
            "workable": workable, "smartrecruiters": smartrecruiters, "workday": workday, "teamtailor": teamtailor,
            "personio": personio, "rmk": rmk, "beesite": beesite, "phenom": phenom}


# ------------------------------------------------------------------ description back-fill for boards without inline text
def detail_teamtailor(http, job):
    r = http.get(job.url)
    if not r or r.status_code != 200:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    node = soup.select_one("section.body, div.body, [class*='body'], main, article")
    return node.get_text("\n", strip=True) if node else ""


def detail_workday(http, job):
    # url = {base}/{site}{externalPath}; cxs endpoint mirrors the path
    m = re.match(r"(https://[^/]+)/([^/]+)(/job/.*)$", job.url)
    if not m:
        return ""
    base, site, path = m.groups()
    tenant = base.split("//")[1].split(".")[0]
    r = http.get(f"{base}/wday/cxs/{tenant}/{site}{path}")
    if not r or r.status_code != 200:
        return ""
    try:
        return strip_html(r.json().get("jobPostingInfo", {}).get("jobDescription", ""))
    except ValueError:
        return ""


def detail_smartrecruiters(http, job):
    _, slug, jid = job.id.split(":", 2)
    r = http.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
    if not r or r.status_code != 200:
        return ""
    try:
        secs = r.json().get("jobAd", {}).get("sections", {})
    except ValueError:
        return ""
    return "\n".join(strip_html(v.get("text", "")) for v in secs.values() if isinstance(v, dict))


def detail_page(http, job):
    """Career-site job page: schema.org JobPosting first (SuccessFactors, Phenom and BeeSite pages carry it), then
    the SuccessFactors description block, then the main text of the page."""
    r = http.get(job.url)
    if not r or r.status_code != 200:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("description"):
                return strip_html(item["description"])
    node = soup.select_one(".jobdescription, [itemprop=description], main, article")
    if node:
        return node.get_text("\n", strip=True)
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    return soup.get_text("\n", strip=True)[:8000]


DETAIL_FETCHERS = {"teamtailor": detail_teamtailor, "workday": detail_workday, "smartrecruiters": detail_smartrecruiters,
                   "rmk": detail_page, "beesite": detail_page, "phenom": detail_page}
