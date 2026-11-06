"""Find which ATS a company uses by probing public endpoints with slug guesses."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from .http import UA

PROBES = {
    "greenhouse": lambda s: ("GET", f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs", "jobs"),
    "lever": lambda s: ("GET", f"https://api.lever.co/v0/postings/{s}?mode=json", None),
    "ashby": lambda s: ("GET", f"https://api.ashbyhq.com/posting-api/job-board/{s}", "jobs"),
    "recruitee": lambda s: ("GET", f"https://{s}.recruitee.com/api/offers/", "offers"),
    "workable": lambda s: ("GET", f"https://apply.workable.com/api/v1/widget/accounts/{s}", "jobs"),
    "smartrecruiters": lambda s: ("GET", f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1", "content"),
    "teamtailor": lambda s: ("GET", f"https://{s}.teamtailor.com/jobs.rss", None),
    "personio": lambda s: ("GET", f"https://{s}.jobs.personio.de/xml", None),     # unknown slugs answer 404
}


def slug_candidates(name, first_word=True):
    n = name.lower()
    n = re.sub(r"\b(b\.?v\.?|n\.?v\.?|holding|netherlands|nederland|europe|international|group|inc|ltd)\b", " ", n)
    n = n.replace("&", "and")
    words = re.findall(r"[a-z0-9]+", n)
    if not words:
        return []
    joined = "".join(words)
    cands = [joined, "-".join(words)]
    if first_word and words[0] != joined and len(words[0]) >= 4:
        cands.append(words[0])
    if len(words) > 1:
        cands.append("".join(words[:2]))
    out, seen = [], set()
    for c in cands:
        if c and c not in seen and len(c) >= 3:
            seen.add(c)
            out.append(c)
    return out


def probe(ats, slug, timeout=12):
    method, url, key = PROBES[ats](slug)
    if len(slug) > 40:
        return None
    try:
        r = requests.request(method, url, timeout=timeout, headers={"User-Agent": UA})
    except Exception:  # DNS label errors, SSL errors, timeouts: treat as "not this ATS"
        return None
    if r.status_code != 200:
        return None
    if ats == "teamtailor":
        return {"count": r.text.count("<item>")} if "teamtailor.com/locations" in r.text else None
    if ats == "personio":
        return {"count": r.text.count("<position>")} if "<workzag-jobs" in r.text else None
    try:
        data = r.json()
    except ValueError:
        return None
    if ats == "lever":
        return {"count": len(data)} if isinstance(data, list) else None
    if isinstance(data, dict) and key in data:
        val = data[key]
        return {"count": len(val) if isinstance(val, list) else -1}
    return None


def discover(names, ats_list=None, workers=12):
    ats_list = ats_list or list(PROBES)
    tasks = [(name, ats, slug) for name in names for slug in slug_candidates(name) for ats in ats_list]

    def run(t):
        name, ats, slug = t
        try:
            res = probe(ats, slug)
        except Exception:
            return None
        return (name, ats, slug, res) if res else None

    found = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for hit in ex.map(run, tasks):
            if hit:
                name, ats, slug, res = hit
                if ats == "smartrecruiters" and res["count"] == 0:
                    continue  # SmartRecruiters answers 200 + empty list for unknown slugs
                found.setdefault(name, []).append({"ats": ats, "slug": slug, "count": res["count"]})
    return found


# ------------------------------------------------------------------ mass discovery with an identity check
def discover_boards(names, area_re, known=(), ats_list=None, workers=48, log=print):
    """Probe every name of a long list (the whole IND register, a list of large German employers) and keep only
    boards that list at least one job inside `area_re`. Thousands of names give many slug collisions ("bright",
    "nova", "atlas" are a dozen unrelated companies each); a board with jobs in the country the name came from is
    almost always the right company, and a board without them would not feed the pipeline anyway.
    The first-word slug variant is not tried: on a long list it mostly finds other companies.
    Returns [{name, ats, slug, jobs, in_area}]; `known` = {(ats, slug)} already in companies.yaml."""
    from .http import Http
    from .sources import ats as ats_mod

    ats_list = ats_list or list(PROBES)
    by_slug = {}
    for name in names:
        for slug in slug_candidates(name, first_word=False):
            by_slug.setdefault(slug, name)
    tasks = [(a, s) for s in by_slug for a in ats_list if (a, s) not in known]
    log(f"{len(names)} names -> {len(by_slug)} slugs -> {len(tasks)} probes")

    def run(t):
        try:
            return t, probe(*t)
        except Exception:
            return t, None

    hits, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (a, s), res in ex.map(run, tasks):
            done += 1
            if res and res["count"] != 0:
                hits.append((a, s))
            if done % 5000 == 0:
                log(f"  probed {done}/{len(tasks)}, boards with jobs so far {len(hits)}")
    log(f"{len(hits)} boards with jobs; checking locations")

    local = threading.local()

    def check(hit):
        a, s = hit
        if not hasattr(local, "http"):
            local.http = Http(delay=(0, 0))
        try:
            jobs = ats_mod.FETCHERS[a](local.http, by_slug[s], s) or []
        except Exception:
            jobs = []
        return {"name": by_slug[s], "ats": a, "slug": s, "jobs": len(jobs),
                "in_area": sum(1 for j in jobs if j.location and area_re.search(j.location))}

    with ThreadPoolExecutor(max_workers=min(workers, 12)) as ex:
        boards = [b for b in ex.map(check, hits) if b["in_area"]]
    best = {}                      # one board per company name: the ATS with most local jobs
    for b in boards:
        if b["name"] not in best or b["in_area"] > best[b["name"]]["in_area"]:
            best[b["name"]] = b
    return sorted(best.values(), key=lambda b: b["name"].lower())
