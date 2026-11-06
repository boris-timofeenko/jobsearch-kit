"""LinkedIn public (guest) job search. No login, HTML endpoints used by the logged-out jobs page."""
import html
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..models import Job

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


def search(http, keywords, location, time_filter="r604800", remote=False, max_pages=3, relevant=None,
           idle_pages=5):
    """Paginate the guest search. LinkedIn pads the tail with loosely related roles, so when `relevant(title)`
    is given we stop after `idle_pages` consecutive pages without a single relevant title.
    Returns (jobs, complete): complete is False when LinkedIn stopped answering mid-way, so the caller must not treat
    the time window as covered. The guest API ignores sortBy=DD (checked 27.10), so there is no "stop at known"."""
    jobs = {}
    start = 0
    idle = 0
    for _ in range(max_pages):
        params = {"keywords": keywords, "location": location, "f_TPR": time_filter, "start": start}
        if remote:
            params["f_WT"] = "2"
        r = http.get(f"{SEARCH}?{urlencode(params)}")
        if not r or r.status_code != 200:
            return list(jobs.values()), False
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.base-search-card, li")
        found = 0
        hit = 0
        for c in cards:
            urn = c.get("data-entity-urn") or (c.find(attrs={"data-entity-urn": True}) or {}).get("data-entity-urn")
            if not urn:
                continue
            jid = urn.rsplit(":", 1)[-1]
            if jid in jobs:
                continue
            title = _txt(c.select_one(".base-search-card__title"))
            company = _txt(c.select_one(".base-search-card__subtitle"))
            loc = _txt(c.select_one(".job-search-card__location"))
            t = c.find("time")
            posted = t.get("datetime", "") if t else ""
            link = c.select_one("a.base-card__full-link")
            url = (link.get("href", "").split("?")[0]) if link else f"https://www.linkedin.com/jobs/view/{jid}"
            jobs[jid] = Job(id=f"linkedin:{jid}", source="linkedin", company=company, title=title, url=url,
                            location=loc, posted=posted[:10], remote=remote,
                            extra={"query": keywords, "search_location": location})
            found += 1
            if relevant and relevant(title):
                hit += 1
        if found == 0:
            break
        idle = idle + 1 if (relevant and hit == 0) else 0
        if idle >= idle_pages:
            break
        start += found
        http.sleep()
    return list(jobs.values()), True


def detail(http, job_id):
    """Return dict(description, criteria, location, company) or None."""
    r = http.get(DETAIL.format(id=job_id))
    if not r or r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    d = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    desc = d.get_text("\n", strip=True) if d else ""
    crit = [html.unescape(x.get_text(strip=True)) for x in soup.select(".description__job-criteria-text")]
    salary = _txt(soup.select_one(".salary, .compensation__salary"))
    cap = _txt(soup.select_one(".num-applicants__caption"))
    applicants = None
    m = re.search(r"(\d[\d,]*)\s*applicants?", cap, re.I)
    if m:
        applicants = int(m.group(1).replace(",", ""))     # "Over 200 applicants" -> 200, "first 25" -> 25
    return {"description": desc, "criteria": crit, "salary": salary, "applicants": applicants, "applicants_text": cap,
            "company": _txt(soup.select_one(".topcard__org-name-link")),
            "location": _txt(soup.select_one(".topcard__flavor--bullet"))}


def _txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""
