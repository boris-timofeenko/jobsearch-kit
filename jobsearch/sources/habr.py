"""Хабр Карьера (career.habr.com): IT vacancies in Russia, Belarus, Kazakhstan and remote ones for Russian speakers.

Its search is fuzzy (q=QA brings Data Engineers and a power engineer), while the whole board is small: 1329 live
vacancies and 40-50 new a day on 15.11.2026. So the feed is read by date down to the start of the window and the
profile's title filter does the rest. The list is the site's frontend JSON (/api/frontend/vacancies, not closed by
robots.txt), the description is the schema.org JobPosting on the vacancy page (ats.detail_page). Cities come in
Russian and without a country: a city that names no part of the world (filters.parts_in) is taken as Russian.
"""
from datetime import datetime, timedelta, timezone

from ..models import Job

LIST = "https://career.habr.com/api/frontend/vacancies"
SETTINGS = {"days": 7, "max_pages": 60}       # config.yaml `habr`


def configure(cfg):
    SETTINGS.update(cfg.get("habr") or {})


def location(v):
    """«Белград» stays as is (Serbia knows it), «Шахты, Новошахтинск» and an empty location become Russian."""
    from .. import filters
    cities = [x.get("title", "") for x in v.get("locations") or []] or [(v.get("location") or {}).get("title", "")]
    loc = ", ".join(c for c in cities if c)
    if loc and filters.parts_in(loc):
        return loc
    return f"{loc}, Россия" if loc else "Россия"


def to_job(v):
    return Job(id=f"habr:{v['id']}", source="habr", company=(v.get("company") or {}).get("title", ""),
               title=(v.get("title") or "").strip(), url="https://career.habr.com" + (v.get("href") or f"/vacancies/{v['id']}"),
               location=location(v), posted=v["publishedDate"]["date"][:10], remote=bool(v.get("remoteWork")),
               salary_text=(v.get("salary") or {}).get("formatted") or "",
               extra={"employment_type": v.get("employment") or ""})


def published(v):
    return datetime.fromisoformat(v["publishedDate"]["date"])


def habr(http, days=None, max_pages=None):
    """Vacancies published in the last `days`, newest first. Highlighted ones sit on top out of date order, so the
    reading stops at the first page with nothing new on it rather than at the first old vacancy."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days or SETTINGS["days"])
    out = []
    for page in range(1, (max_pages or SETTINGS["max_pages"]) + 1):
        r = http.get(LIST, params={"sort": "date", "type": "all", "page": page})
        if not r or r.status_code != 200:
            break
        data = r.json()
        fresh = [v for v in data.get("list") or [] if published(v) >= cutoff]
        out += [to_job(v) for v in fresh if v.get("id") and v.get("publishedDate")]
        if not fresh or page >= (data.get("meta") or {}).get("totalPages", page):
            break
        http.sleep()
    return list({j.id: j for j in out}.values())
