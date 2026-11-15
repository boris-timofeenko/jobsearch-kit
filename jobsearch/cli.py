import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from . import filters, llm, notify, report
from .db import DB
from .http import Http
from .models import company_key
from .sources import aggregators, ats, linkedin, telegram
from .sponsors import Sponsors
from . import config
from .config import DATA, ROOT


def load_cfg():
    """config.yaml + my/config.yaml + my/profile.yaml (see jobsearch/config.py), rules rebuilt from the profile."""
    try:
        cfg = config.load()
    except config.ConfigError as e:
        sys.exit(f"настройка: {e}")
    profile = cfg["profile"]
    filters.configure(profile)
    llm.configure(profile)
    report.configure(profile)
    ats.configure(profile)
    aggregators.configure(cfg)
    return cfg


def make_sponsors(cfg, http):
    """Recognised-sponsor register is a Netherlands feature (IND): on when a target country uses it and the candidate
    needs a visa at all."""
    p = cfg.get("profile", {})
    t = p.get("target", {})
    countries = ([t["primary"]] if t.get("primary") else []) + list(t.get("countries") or [])
    if (p.get("candidate") or {}).get("needs_visa", True) and any(c.get("sponsor_register") == "ind" for c in countries):
        return Sponsors(DATA / "sponsors.json", http)
    return None


def now_local():
    """Wall-clock time in the user's zone for everything the user reads (server runs in UTC)."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(os.environ.get("JOBSEARCH_TZ", "Europe/Amsterdam"))
    return datetime.now(tz)


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------------ run
def search_window(base, last, now, margin, cap):
    """Seconds for LinkedIn's f_TPR: at least the run's base window, and far enough back to reach the start of the
    previous complete search of the same query plus a margin for postings LinkedIn indexes late; at most cap."""
    if not last:
        return base
    since = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
    return int(min(max(base, since + margin), cap))


def collect_linkedin(cfg, http, a, coverage):
    """LinkedIn searches. Returns (jobs, done, notes): done maps (location, query, remote) to the start of each search
    that ran to the end; cmd_run stores it only after the run's postings are saved, so a crash or a kill widens the
    next window instead of leaving a gap. A run stops searching when its time budget is spent or LinkedIn fails three
    queries in a row; the skipped queries keep their old coverage and catch up next run."""
    li = cfg.get("linkedin", {})
    deep = getattr(a, "deep", False)   # --deep: all queries, full pagination, no early stop (nightly run)
    base = int((a.time_filter or li.get("time_filter", "r604800"))[1:])
    margin, cap = li.get("window_margin", 7200), li.get("window_max", 259200)
    budget = (li.get("search_budget_min") or {}).get("deep" if deep else "fast", 0) * 60
    only = {x.strip().lower() for x in (getattr(a, "locations", None) or "").split(",") if x.strip()}
    jobs_out, done, notes, postponed = [], {}, [], []
    started, failed_in_row, widest = time.monotonic(), 0, base
    for loc in li.get("locations", []):
        if only and loc["name"].lower() not in only:
            continue
        for q in (li.get("queries", []) if deep else (loc.get("queries") or li.get("queries", []))):
            key = (loc["name"], q, bool(loc.get("remote", False)))
            if postponed or failed_in_row >= 3 or (budget and time.monotonic() - started > budget):
                postponed.append(key)
                continue
            at = datetime.now(timezone.utc)
            window = search_window(base, coverage.get(key), at, margin, cap)
            widest = max(widest, window)
            jobs, complete = linkedin.search(http, q, loc["name"], f"r{window}", remote=loc.get("remote", False),
                                             max_pages=100 if deep else loc.get("max_pages", li.get("max_pages", 100)),
                                             relevant=None if deep else filters.is_relevant_title,
                                             idle_pages=li.get("idle_pages", 5))
            rel = [j for j in jobs if filters.is_relevant_title(j.title)]
            tail = f", окно {window / 3600:.0f} ч" if window > base + 1800 else ""
            log(f"linkedin '{q}' @ {loc['name']}: {len(jobs)} cards, {len(rel)} по роли{tail}"
                + ("" if complete else ", оборван: LinkedIn не ответил"))
            jobs_out += rel
            if complete:
                done[key] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
                failed_in_row = 0
            else:
                failed_in_row += 1
            http.sleep()
    if widest > base + 3600:
        notes.append(f"окно поиска LinkedIn расширено до {widest / 3600:.0f} ч, чтобы закрыть пропуск")
    if postponed:
        why = "LinkedIn не ответил на три запроса подряд" if failed_in_row >= 3 else f"бюджет {budget // 60} мин исчерпан"
        notes.append(f"LinkedIn: {why}, отложено запросов: {len(postponed)} — их окно расширится в следующем прогоне")
        log(notes[-1])
    return jobs_out, done, notes


def collect(cfg, http, a, coverage=None):
    """Gather Job objects from all enabled sources (relevance-filtered, not yet analyzed).
    Returns (jobs, LinkedIn coverage to store, notes for the run summary)."""
    collected, done, notes = [], {}, []
    li = cfg.get("linkedin", {})
    if li.get("enabled", True) and not a.no_linkedin:
        collected, done, notes = collect_linkedin(cfg, http, a, coverage or {})

    if not a.no_companies:
        collected += collect_boards(cfg["companies"], cfg.get("board_workers", 8))

    if not a.no_aggregators:
        # Discovery-heavy sources run in the nightly deep run only. HiringCafe's official MCP is fast, but one
        # nightly pass over its ATS index is enough for new postings and keeps us well below its rate limit.
        deep = cfg.get("aggregators_deep", []) if getattr(a, "deep", False) else []
        for name in cfg.get("aggregators", []) + deep:
            f = aggregators.AGGREGATORS.get(name)
            if not f:
                continue
            if getattr(f, "blocked", ""):
                log(f"{name}: заглушка, вакансий нет — {f.blocked}")
                continue
            try:
                jobs = f(http)
            except Exception as e:
                log(f"{name}: FAILED {e}")
                continue
            rel = [j for j in jobs if filters.is_relevant_title(j.title)]
            log(f"{name}: {len(jobs)} jobs, {len(rel)} по роли")
            collected += rel
    return collected, done, notes


def collect_boards(companies, workers=8):
    """All company boards, several at a time: with the mass-discovered lists there are over a thousand, one after
    another they took longer than the LinkedIn search. Each thread has its own session; the boards are on a handful
    of ATS hosts with public APIs, and the log keeps the board order."""
    local = threading.local()

    def fetch(c):
        f = ats.FETCHERS.get(c["ats"])
        if not f:
            return c, None, "unknown ats"
        if not hasattr(local, "http"):
            local.http = Http(delay=(0.2, 0.5))
        try:
            return c, f(local.http, c["name"], str(c["slug"])), None
        except Exception as e:
            return c, None, f"error {e}"

    out, failed = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, jobs, err in ex.map(fetch, companies):
            if jobs is None:
                failed += 1
                log(f"{c['name']} ({c['ats']}): FAILED" + (f" {err}" if err else ""))
                continue
            # target countries, remote, no location, or anywhere in the EU (the eu track is relocation too)
            rel = merge_duplicates([j for j in jobs if filters.is_relevant_title(j.title) and filters.in_search_area(j)])
            if rel:                      # over a thousand boards: only those that gave something
                log(f"{c['name']} ({c['ats']}): {len(jobs)} jobs, {len(rel)} по роли в зоне поиска")
            out += rel
    log(f"boards: {len(companies)}, failed {failed}, postings for the role {len(out)}")
    return out


def collect_telegram(cfg, http, db, a, known):
    """Telegram job channels (sources/telegram.py, `tg_channels` in my/config.yaml): new posts are stored, the model
    splits the ones with a title line of the role into vacancies, and the jobs are rebuilt from every post parsed within `days`:
    stored ids are only touched, so a run that died after parsing loses nothing."""
    tcfg = cfg.get("tg_channels") or {}
    channels = list(dict.fromkeys(telegram.channel_name(c) for c in tcfg.get("channels") or []))
    if not channels or getattr(a, "no_telegram", False):
        return []
    since = telegram.since_iso(tcfg.get("days", 30))
    last = db.tg_last_ids()
    relevant = lambda p: bool(telegram.title_lines(p.text, filters.is_relevant_title))
    no_preview = []
    for ch in channels:
        try:
            posts = telegram.web_posts(http, ch, last.get(ch, 0), since, tcfg.get("max_pages", 40))
        except telegram.NoPreview:
            no_preview.append(ch)
            continue
        except Exception as e:
            log(f"telegram {ch}: FAILED {e}")
            continue
        db.tg_save(posts, relevant)
        log(f"telegram {ch}: {len(posts)} new posts, {sum(map(relevant, posts))} по роли")
        http.sleep()
    if no_preview and telegram.account_ready(DATA):
        try:
            for ch, posts in telegram.account_posts(DATA, no_preview, last, since).items():
                db.tg_save(posts, relevant)
                log(f"telegram {ch} (account): {len(posts)} new posts, {sum(map(relevant, posts))} по роли")
        except Exception as e:
            log(f"telegram account: FAILED {e}")
    elif no_preview:
        log(f"telegram {', '.join(no_preview)}: no web preview (a group or the preview is off), "
            f"reading needs the account: `jobsearch tg-login`")
    db.commit()

    pending = db.tg_pending(since, tcfg.get("extract_per_run", 200))
    for r in pending:
        link = telegram.page_link(telegram.post_from_row(r))
        if link and r["page"] is None:
            db.tg_set_page(r["channel"], r["msg_id"], job_page_text(http, link)[:8000])
    pending = db.tg_pending(since, tcfg.get("extract_per_run", 200))
    if pending and not a.no_llm:
        backend, why = llm.pick_backend(cfg.get("llm", {}))
        if backend:
            parse_tg_posts(db, pending, backend, cfg.get("llm", {}).get("workers", 4))
        else:
            log(f"telegram: {len(pending)} posts wait for the model ({why})")
    db.commit()

    jobs, parsed = [], db.tg_parsed(since)
    for r in parsed:
        jobs += telegram.to_jobs(telegram.post_from_row(r), [telegram.Vacancy(**v) for v in json.loads(r["extracted"])],
                                 filters.is_relevant_title)
    for j in jobs:                          # a digest's role: its own page, if the post links one
        if j.id not in known and len(j.description) < 700 and "— страница вакансии —" not in j.description:
            page = job_page_text(http, j.extra.get("apply_url", ""))
            if page:
                j.description += "\n\n— страница вакансии —\n" + page[:6000]
    log(f"telegram: {len(jobs)} vacancies of the role in {len(parsed)} parsed posts")
    return jobs


def parse_tg_posts(db, rows, backend, workers):
    """The model splits each post into vacancies; a failed call leaves the post pending for the next run."""
    def one(r):
        post = telegram.post_from_row(r)
        lines = telegram.title_lines(post.text, filters.is_relevant_title)
        try:
            out = backend.ask(telegram.EXTRACT_SYSTEM, telegram.extract_prompt(post, lines), telegram.PostVacancies)
        except Exception as e:
            log(f"telegram parse {post.url}: {e}")
            return post, None
        return post, json.dumps([v.model_dump() for v in out.vacancies], ensure_ascii=False)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for post, vacancies in ex.map(one, rows):
            if vacancies is not None:
                db.tg_set_extracted(post.channel, post.id, vacancies)
                done += 1
    log(f"telegram: model parsed {done}/{len(rows)} posts")


LINKEDIN_VIEW = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{6,})")


def job_page_text(http, url):
    """Full text behind a short post's apply link: a LinkedIn posting, else schema.org JobPosting or the page's main
    text. Telegram links (a recruiter's handle, another channel) and failures give ""."""
    if not url.startswith("http") or re.search(r"//(t|telegram)\.me/", url):
        return ""
    try:
        m = LINKEDIN_VIEW.search(url)
        if m:
            d = linkedin.detail(http, m.group(1))
            return (d or {}).get("description") or ""
        return ats.detail_page(http, SimpleNamespace(url=url))
    except Exception:
        return ""


def merge_duplicates(jobs):
    """Same company + same title posted for many cities -> one job listing all locations."""
    out = {}
    for j in jobs:
        key = (j.company.lower(), filters.normalize_simple(j.title))
        if key in out:
            k = out[key]
            if j.location and j.location not in k.location:
                k.location = (k.location + " / " + j.location)[:200]
            k.remote = k.remote or j.remote
        else:
            out[key] = j
    return list(out.values())


def fetch_descriptions(http, jobs, limit, budget_s=0):
    """Load full text for every job that lacks it: LinkedIn detail pages plus Workday/Teamtailor/SmartRecruiters.
    NL-located postings go first when the per-run budget is limited. Whatever the time budget leaves is picked up by
    the backfill of a later run."""
    todo = [j for j in jobs if not j.description and (j.source == "linkedin" or j.source in ats.DETAIL_FETCHERS)]
    todo.sort(key=lambda j: (0 if filters.NL_LOC.search(j.location) else 1))
    n, started = 0, time.monotonic()
    for j in todo[:limit]:
        if budget_s and time.monotonic() - started > budget_s:
            log(f"descriptions: time budget spent, {len(todo[:limit]) - n} left for the backfill")
            break
        if j.source == "linkedin":
            d = linkedin.detail(http, j.id.split(":")[1])
            if d:
                j.description = d["description"] or "(no description)"
                j.salary_text = d["salary"]
                j.extra["criteria"] = d["criteria"]
                j.applicants = d.get("applicants")
                if len(d["criteria"]) >= 2:
                    j.extra["employment_type"] = d["criteria"][1]     # Full-time / Contract / Temporary / Internship
                if d["location"] and not j.location:
                    j.location = d["location"]
        else:
            try:
                j.description = ats.DETAIL_FETCHERS[j.source](http, j) or "(no description)"
            except Exception as e:
                log(f"detail failed {j.id}: {e}")
        n += 1
        http.sleep()
    return n


def row_to_job(r):
    from .models import Job
    keys = r.keys()
    return Job(id=r["id"], source=r["source"], company=r["company"], title=r["title"], url=r["url"],
               location=r["location"] or "", posted=r["posted"] or "", remote=bool(r["remote"]),
               description=r["description"] or "", salary_text=r["salary_text"] or "",
               applicants=r["applicants"] if "applicants" in keys else None)


def cmd_run(a):
    cfg = load_cfg()
    notify.load_env(ROOT / ".env")
    http = Http()
    db = DB(DATA / "jobs.db")
    sponsors = make_sponsors(cfg, http)
    log(f"IND register: {len(sponsors.entries)} sponsors" if sponsors else "sponsor register: disabled for this target")
    known = db.known_ids()
    li = cfg.get("linkedin", {})
    run_started = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()
    detail_budget = (li.get("detail_budget_min") or {}).get("deep" if getattr(a, "deep", False) else "fast", 0) * 60

    collected, covered, notes = collect(cfg, http, a, db.coverage())
    try:
        collected += collect_telegram(cfg, http, db, a, known)
    except Exception as e:                  # a broken channel source must not cost the rest of the run
        log(f"telegram: FAILED {e}")
    if http.summary():
        log(f"LinkedIn: {http.summary()}")
    seen, new_jobs = set(), []
    for j in collected:
        if j.id in seen:
            continue
        seen.add(j.id)
        if j.id in known:
            db.touch(j.id)
        else:
            new_jobs.append(j)
    db.commit()   # each write stage commits: the first touch used to hold the write lock through descriptions and
                  # LLM (5-12 min), and the bot's button clicks failed with "database is locked"
    log(f"collected {len(seen)} unique, {len(new_jobs)} new")

    # excluded companies are skipped anyway: no detail request for them (Jobster alone was 11% of all detail requests)
    for j in new_jobs:
        if not j.description and filters.excluded_company(j.company, cfg):
            j.description = NOT_FETCHED
    n = fetch_descriptions(http, new_jobs, li.get("detail_fetch_limit", 600), detail_budget)
    if n:
        log(f"descriptions fetched: {n}")

    for j in new_jobs:
        safe_analyze(j, sponsors, cfg)

    # cross-ID duplicates: same company + title already stored (other city / repost)
    for o in mark_duplicates(new_jobs, db):
        safe_analyze(o, sponsors, cfg)          # the track follows the added city
    db.commit()
    dups = sum(j.verdict == "dup" for j in new_jobs)
    if dups:
        log(f"cross-id duplicates: {dups}")

    # backfill: older LinkedIn rows still without description (budget-limited), then re-analyze them
    backfill = [row_to_job(r) for r in db.query("(description IS NULL OR description='') AND status='new' "
                                                "AND verdict != 'dup'", order="first_seen DESC",
                                                limit=li.get("backfill_limit", 200))]
    refreshed = []                   # backfilled rows that got their text now: they go to the LLM like new ones
    if backfill:
        n = fetch_descriptions(http, backfill, len(backfill), detail_budget)
        for j in backfill:
            if j.description:
                safe_analyze(j, sponsors, cfg)
                db.update_analysis(j)
                refreshed.append(j)
        db.commit()
        log(f"backfilled descriptions: {n}")

    lcfg = cfg.get("llm", {})
    assessed = 0
    low = llm.low_yield_companies(db.assessed_by_company(), cfg, lcfg.get("skip_low_yield_after", 0))
    llm.skip_low_yield(new_jobs + refreshed, low)
    if not a.no_llm:
        backend, why = llm.pick_backend(lcfg)
        if backend:
            cand = llm.select_candidates(new_jobs + refreshed, lcfg)
            log(f"LLM candidates: {len(cand)} of {len(new_jobs)} new + {len(refreshed)} backfilled")
            if cand:
                assessed = llm.assess_many(cand, backend, workers=lcfg.get("workers", 4), log=log)
        else:
            log(f"LLM assessment skipped: {why}")
    live = sorted([j for j in new_jobs if j.verdict == "live"], key=lambda j: -j.score)
    for j in new_jobs:
        db.insert(j)
        db.update_analysis(j)
    for j in refreshed:
        db.update_analysis(j)
    db.commit()
    db.set_coverage(covered)         # only now: the postings these searches found are stored
    db.commit()

    since = (datetime.utcnow() - timedelta(days=a.report_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.query("first_seen >= ? AND verdict = 'live' AND llm_json != '' AND llm_fit >= 4 AND status != 'ignored'", (since,), limit=1000)
    title = f"Вакансии · прошли LLM-проверку · {now_local():%d.%m.%Y}"
    md, htm = report.write_reports(rows, DATA / "reports", title)
    log(f"report: {htm}  ({len(rows)} rows)")

    # Telegram: only postings that passed the LLM check in THIS run, same bar as the report (fit >= min_fit)
    tcfg = cfg.get("telegram", {})
    new_ids = {j.id for j in new_jobs} | {j.id for j in refreshed if j.llm_json}
    # filter to this run's postings first, then cap: with LIMIT before the filter, older unsent rows (176 on 24.09)
    # took the 40 slots and new postings ranked below them were silently never sent
    fresh = [r for r in db.query("notified=0 AND verdict='live' AND llm_json != '' AND llm_fit >= ?",
                                 (tcfg.get("min_fit", 4),), limit=100000) if r["id"] in new_ids]
    fresh = per_company(fresh, tcfg.get("max_per_company", 2))[:40]
    if a.notify or tcfg.get("enabled"):
        if not fresh and tcfg.get("quiet_when_empty", False):
            log("telegram: nothing new worth sending")
        else:
            silent = notify.quiet(tcfg.get("quiet_hours", ""), now_local())    # the nightly deep run stays silent
            summary = report.run_summary(f"Прогон {now_local():%d.%m %H:%M %Z}", len(seen), new_jobs, fresh, assessed,
                                         notes + run_notes(http, time.monotonic() - t0))
            ok = notify.telegram(summary, silent) if tcfg.get("summary_always", True) or fresh else True
            if fresh and notify.telegram_cards(None, fresh, db, silent):
                db.mark_notified([r["id"] for r in fresh])
                log(f"telegram sent: {len(fresh)} cards")
            elif not ok:
                log("telegram not configured or failed (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env)")
    db.commit()

    st = http.stats.get("linkedin", {})
    with open(DATA / "runs.log", "a") as f:   # used by `list/report --last-run` (first field only)
        f.write(f"{run_started} new={len(new_jobs)} li_req={st.get('req', 0)} li_429={st.get('429', 0)} "
                f"li_no_answer={st.get('gave_up', 0)} min={(time.monotonic() - t0) / 60:.0f}\n")

    skip = [j for j in new_jobs if j.verdict == "skip"]
    other = [j for j in new_jobs if j.verdict == "other"]
    print(f"\nНОВЫЕ: live {len(live)} · other {len(other)} · skip {len(skip)}\n")
    print_jobs(live[:40])


NOT_FETCHED = "(не загружено: компания в exclude_companies)"


def run_notes(http, seconds):
    """Lines for the run summary when LinkedIn throttled or the run ran long; nothing on an ordinary run."""
    st = http.stats.get("linkedin", {})
    out = [f"LinkedIn: {http.summary()}"] if st.get("429") or st.get("gave_up") else []
    if seconds > 3600:
        out.append(f"прогон шёл {seconds // 3600:.0f} ч {seconds % 3600 // 60:.0f} мин")
    return out


def same_original(job, candidates, text_of):
    """Which stored posting (ids sharing the fingerprint) this one repeats, or None. For intermediaries that hide the
    employer the texts must match too: Jobgether lists different clients' roles as "Senior QA Engineer", and a fit-14
    role in NL was marked a duplicate of a fit-8 one (27.10)."""
    if not candidates:
        return None
    if not filters.PARTNER_LISTING.search(job.description or ""):
        return candidates[0]
    return next((c for c in candidates if filters.same_posting(job.description, text_of(c))), None)


def mark_duplicates(jobs, db):
    """Mark copies of stored postings, or of postings earlier in this batch, as "dup" and note the copy's city on the
    original. Returns this batch's originals whose location grew: they are not stored yet, so the city goes onto the
    Job, and the caller re-analyzes them. Before, the city was lost, and an NL copy of a German Jobgether posting
    found in the same deep run went out as a German card (30.10).
    A copy that passes the heuristics is not swallowed by an original they closed: Lely's LinkedIn posting was skipped
    for its Dutch text, its English copy from hiring.cafe got model fit 9 and was marked "dup" of it (04.11)."""
    fps = db.fingerprints()
    originals, widened = {}, {}

    def closed(i):
        if i in originals:
            return originals[i].verdict == "skip" and not llm.rescuable(originals[i])
        r = db.get(i)
        return bool(r) and r["verdict"] == "skip"
    for j in jobs:
        fp = j.fingerprint()
        candidates = [i for i in fps.get(fp, []) if j.verdict == "skip" or not closed(i)]
        orig = same_original(j, candidates,
                             lambda i: originals[i].description if i in originals else stored_description(db, i))
        if not orig or not dedup_eligible(j):
            fps.setdefault(fp, []).append(j.id)
            originals[j.id] = j
            continue
        if orig in originals:
            o = originals[orig]
            if j.location and j.location not in o.location:
                o.location = (f"{o.location} / {j.location}" if o.location else j.location)[:300]
                widened[orig] = o
        else:
            db.add_location(orig, j.location)
        j.verdict, j.reasons = "dup", [f"дубль {orig}"] + j.reasons
    return list(widened.values())


def stored_description(db, job_id):
    r = db.get(job_id)
    return (r["description"] or "") if r else ""


def dedup_eligible(j):
    """A copy of a stored posting becomes "dup" unless the heuristics already closed it for good. A hardware skip is
    not final: the LLM may rescue it, and each rescued copy then went out as its own card (eleQtron, 25.09)."""
    return j.verdict != "skip" or llm.rescuable(j)


def per_company(rows, n):
    """At most n cards per company per run, best score first: staffing firms post the same role under many titles
    (BairesDev sent four near-identical cards on 24.09); the rest stay in the report."""
    seen, out = {}, []
    for r in sorted(rows, key=lambda r: -(r["score"] or 0)):
        k = filters.normalize_simple(r["company"])
        if seen.get(k, 0) < n:
            seen[k] = seen.get(k, 0) + 1
            out.append(r)
    return out


def safe_analyze(j, sponsors, cfg):
    try:
        filters.analyze(j, sponsors, cfg)
    except Exception as e:  # never lose a run because of one odd posting
        j.verdict, j.reasons = "other", [f"analyze error: {e}"]
        log(f"analyze failed for {j.id}: {e}")


def print_jobs(jobs):
    for j in jobs:
        sp = f"IND: {j.sponsor_name}" if j.sponsor_name else ("remote" if j.remote else "")
        sal = f" · {filters.money(j.salary_month)}/мес" if j.salary_month else ""
        llmtxt = f" · LLM {j.llm_fit}" if j.llm_fit is not None else ""
        print(f"{j.score:3d}{llmtxt} | {j.title} — {j.company} | {j.location}{sal} | {sp}")
        if j.reasons or j.llm_note:
            print(f"      {' · '.join(j.reasons + ([j.llm_note] if j.llm_note else []))}")
        print(f"      {j.url}")


def cmd_assess(a):
    """LLM-assess stored jobs that have a description but no assessment yet (e.g. after enabling a backend).
    --again: assess once more what was assessed already, after the profile changed (summary, strengths, role);
    heuristics run afresh first so the old assessment's verdict does not decide who goes to the model."""
    cfg = load_cfg()
    notify.load_env(ROOT / ".env")
    if a.again and not (a.days or a.since):
        sys.exit("--again переоценивает уже оценённое и тратит модель: укажи период, --days N или --since ДАТА")
    backend, why = llm.pick_backend(cfg.get("llm", {}))
    if not backend:
        sys.exit(f"LLM недоступен: {why}")
    db = DB(DATA / "jobs.db")
    where = "verdict IN ('live','other','skip') AND description != ''"
    if not a.again:
        where += " AND (llm_json IS NULL OR llm_json='')"
    params = []
    if a.since:
        where += " AND first_seen >= ?"
        params = [a.since]
    elif a.days:
        where += " AND first_seen >= ?"
        params = [(datetime.utcnow() - timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M:%SZ")]
    # no SQL limit here: the cheap cuts in select_candidates decide, then a.limit caps the LLM calls
    rows = db.query(where, params + [filters.PRIMARY], order="CASE track WHEN ? THEN 0 ELSE 1 END, score DESC",
                    limit=100000)
    jobs = []
    sponsors = make_sponsors(cfg, Http()) if a.again else None
    for r in rows:
        j = row_to_job(r)
        if a.again:                              # fresh heuristics: the old assessment must not decide
            safe_analyze(j, sponsors, cfg)
        else:
            j.track, j.verdict, j.score, j.sponsor_name, j.sponsor_kvk = r["track"], r["verdict"], r["score"], r["sponsor_name"], r["sponsor_kvk"]
            j.reasons = [x for x in (r["reasons"] or "").split(" | ") if x]
            j.lang, j.salary_month = r["lang"], r["salary_month"]
        jobs.append(j)
    jobs = llm.select_candidates(jobs, cfg.get("llm", {}) | {"max_per_run": a.limit})
    log(f"assessing {len(jobs)} stored jobs via {backend.name} (after cheap cuts)")

    def persist(j):  # save each result immediately so an interrupted run keeps its work
        db.update_analysis(j)
        db.commit()
    llm.assess_many(jobs, backend, workers=cfg.get("llm", {}).get("workers", 4), log=log, on_done=persist)
    print_jobs(sorted([j for j in jobs if j.verdict == "live"], key=lambda j: -j.score)[:40])


def cmd_telegram_test(a):
    """Send a test message and, optionally, a digest of the last N LLM-checked jobs to see the card format."""
    cfg = load_cfg()
    notify.load_env(ROOT / ".env")
    import os
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        sys.exit("нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID в .env")
    ok = notify.telegram(f"✅ jobsearch на связи ({now_local():%d.%m %H:%M %Z}). Тестовое сообщение.")
    print("test message:", "sent" if ok else "FAILED")
    if a.sample and ok:
        db = DB(DATA / "jobs.db")
        rows = db.query("verdict='live' AND llm_json != '' AND llm_fit >= 4", order="first_seen DESC, llm_fit DESC",
                        limit=a.sample)
        ok = notify.telegram_cards("Пример дайджеста", rows, db)
        print(f"sample cards ({len(rows)}):", "sent" if ok else "FAILED")


def cmd_tg_login(a):
    notify.load_env(ROOT / ".env")
    print(f"вошли как {telegram.login(DATA)}; сессия {telegram.session_path(DATA)}.session")


def cmd_tg_check(a):
    """Read-only: what each channel gives over `--days`, nothing is stored."""
    cfg = load_cfg()
    notify.load_env(ROOT / ".env")
    names = [telegram.channel_name(c) for c in (a.channels or (cfg.get("tg_channels") or {}).get("channels") or [])]
    if not names:
        sys.exit("нет каналов: tg_channels.channels в my/config.yaml или имена аргументами")
    http, since = Http(delay=(1.0, 2.0)), telegram.since_iso(a.days)
    no_preview = []
    for ch in names:
        try:
            posts = telegram.web_posts(http, ch, 0, since)
        except telegram.NoPreview:
            no_preview.append(ch)
            continue
        except Exception as e:
            print(f"❌ {ch}: {e}")
            continue
        lines = [ln for p in posts for ln in telegram.title_lines(p.text, filters.is_relevant_title)[:1]]
        print(f"✅ {ch}: веб-просмотр, постов за {a.days} дн. {len(posts)}, с заголовком роли {len(lines)}"
              + (f" (например «{lines[-1][:60]}»)" if lines else ""))
    if no_preview and not telegram.account_ready(DATA):
        print(f"🔒 {', '.join(no_preview)}: веб-просмотра нет (группа или он выключен) — читать через аккаунт: "
              f"TG_API_ID/TG_API_HASH в .env и `python -m jobsearch tg-login`")
    elif no_preview:
        for ch, posts in telegram.account_posts(DATA, no_preview, {}, since).items():
            n = sum(bool(telegram.title_lines(p.text, filters.is_relevant_title)) for p in posts)
            print(f"✅ {ch}: через аккаунт, сообщений за {a.days} дн. {len(posts)}, с заголовком роли {n}")


def cmd_bot(a):
    """Long-polling Telegram bot: buttons under cards write statuses to the database."""
    from . import bot
    notify.load_env(ROOT / ".env")
    bot.run(DATA / "jobs.db", log=log, cfg=load_cfg())


def cmd_cv(a):
    """CV tailored to one stored posting (same as the bot button): PDF/DOCX into data/cv/, changes printed; --send
    posts it. --inspect only shows what was found in the CV: the pieces tailoring can move."""
    import html
    import re
    from . import cvgen
    cfg = load_cfg()
    if a.inspect:
        return inspect_cv(cfg)
    if not a.id:
        sys.exit("укажи id вакансии (или --inspect)")
    notify.load_env(ROOT / ".env")
    db = DB(DATA / "jobs.db")
    row = db.c.execute("SELECT rowid, * FROM jobs WHERE id=? OR rowid=?",
                       (a.id, a.id if a.id.isdigit() else -1)).fetchone()
    if not row:
        sys.exit(f"нет вакансии {a.id}")
    res = cvgen.build_for_job(dict(row), cfg, log=log)
    plain = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s))
    print("\n".join(str(f) for f in [res.pdf] + [p for p, _ in res.extra]) + ("  (из кэша)" if res.cached else "")
          + f"\n\n{plain(res.caption)}\n\n{plain(res.details)}")
    if a.send:
        from . import bot
        bot.send_document(res.pdf, res.filename, res.caption)
        for path, filename in res.extra:
            bot.send_document(path, filename)
        if res.details:
            bot.send_text(res.details)


def inspect_cv(cfg):
    """What tailoring sees in the CV: headline, summary, skill rows, roles and bullets."""
    import yaml as _yaml
    from . import cvgen
    path, fmt = config.cv_source(cfg)
    print(f"резюме: {path} ({fmt})")
    if fmt not in ("latex", "markdown", "docx") or not path.exists():
        sys.exit("«CV под вакансию» работает с существующим .docx, .tex или .md (switches.cv)")
    bank_path = config.path_in_project((cfg.get("cv") or {}).get("bank", "my/cv_bank.yaml"))
    bank = _yaml.safe_load(bank_path.read_text()) if bank_path.exists() else {}
    if fmt == "docx":
        from . import cv_docx
        print(cv_docx.inspect(cv_docx.parse(path, bank or {})))
        return
    from . import cv_markdown
    cv = cvgen.parse(cv_markdown.load(path) if fmt == "markdown" else path.read_text())
    print(f"заголовок: {cvgen.to_plain(cv.macro('cvheadline')) or '—'}")
    print(f"summary: {len(cv.sentences)} предл.; skills: {len(cv.skills)} строк; ролей: {len(cv.roles)}")
    for r in cv.roles:
        print(f"роль {r.id}: {cvgen.to_plain(r.title)} — {cvgen.to_plain(r.company)}, буллетов {len(r.bullets)}"
              + (f", закреплено {sum(b.pinned for b in r.bullets)}" if any(b.pinned for b in r.bullets) else ""))


def cmd_autofill(a):
    """Profile + CV PDF for the form-filling browser extension (extension/): profile.json and cv.pdf next to it."""
    import json
    import shutil
    import tempfile
    import yaml
    from . import autofill, cvgen
    cfg = load_cfg()
    ccfg = cfg.get("cv") or {}
    path, fmt = config.cv_source(cfg)
    bank_path = config.path_in_project(ccfg.get("bank", "my/cv_bank.yaml"))
    if fmt not in ("latex", "markdown", "docx"):
        sys.exit("автозаполнение читает резюме в .docx, .tex или .md (switches.cv в my/profile.yaml)")
    if not path.exists():
        sys.exit(f"нет файла резюме {path}")
    bank = yaml.safe_load(bank_path.read_text()) if bank_path.exists() else {}
    name = (cfg.get("profile") or {}).get("candidate", {}).get("name", "")
    text = None
    if fmt == "docx":
        prof = autofill.build("", bank, name, parsed=autofill.parse_docx(path, bank))
    else:
        if fmt == "markdown":
            from . import cv_markdown
            text = cv_markdown.load(path)
        else:
            text = path.read_text()
        prof = autofill.build(text, bank, name)
    out = Path(a.out) if Path(a.out).is_absolute() else ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(prof, ensure_ascii=False, indent=1) + "\n")
    print(f"{out / 'profile.json'}: {prof['person']['full_name']}, {len(prof['experience'])} мест работы, "
          f"{len(prof['education'])} образования, {len(prof['skills'])} навыков")
    empty = [k for k, v in {"адрес": prof["location"]["address"], "индекс": prof["location"]["postal_code"],
                            "срок уведомления": prof["answers"]["notice_period"]}.items() if not v]
    if empty:
        print("не задано в cv_bank.yaml → autofill: " + ", ".join(empty))
    if fmt == "docx" and not prof["education"]:
        print("образование из DOCX не переносится: эти поля формы заполнишь руками")
    if a.pdf:
        shutil.copyfile(a.pdf, out / "cv.pdf")
        print(f"{out / 'cv.pdf'}: копия {a.pdf}")
    elif not a.no_pdf:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                if fmt == "docx":
                    from . import cv_docx
                    pdf, pages = cv_docx.to_pdf(path, tmp)
                    if not pdf:
                        raise RuntimeError("нет LibreOffice")
                else:
                    pdf, pages = cvgen.compile_pdf(text, tmp)
            except RuntimeError as e:
                sys.exit(f"PDF не собран ({e}); укажи готовый через --pdf или --no-pdf")
            shutil.copyfile(pdf, out / "cv.pdf")
        print(f"{out / 'cv.pdf'}: собран из {path.name}, страниц {pages}")


def cmd_reanalyze(a):
    """Re-run the triage rules over everything already stored (after editing filters/config)."""
    cfg = load_cfg()
    db = DB(DATA / "jobs.db")
    sponsors = make_sponsors(cfg, Http())
    rows = db.query("1=1", order="first_seen ASC", limit=100000)
    drop, dups, fps, texts = 0, 0, {}, {}
    for n, r in enumerate(rows, 1):
        if n % 500 == 0:
            db.commit()      # short write transactions: the bot writes button clicks to the same SQLite
                             # (one 3-minute transaction on 24.09 made its clicks fail with "database is locked")
        j = row_to_job(r)
        off_role = not filters.is_relevant_title(j.title)     # title_include / title_exclude changed since
        if off_role and a.prune:
            db.c.execute("DELETE FROM jobs WHERE id=? AND status='new'", (j.id,))
            drop += 1
            continue
        safe_analyze(j, sponsors, cfg)
        if off_role and j.verdict == "live":
            j.verdict = "other"
            j.reasons.append("не по роли: заголовок больше не проходит title_include / title_exclude")
        fp = j.fingerprint()
        db.c.execute("UPDATE jobs SET fingerprint=? WHERE id=?", (fp, j.id))
        orig = same_original(j, fps.get(fp, []), lambda i: texts[i])
        if orig and dedup_eligible(j) and r["status"] == "new":
            db.add_location(orig, j.location)
            j.verdict, j.reasons = "dup", [f"дубль {orig}"] + j.reasons
            dups += 1
        else:
            fps.setdefault(fp, []).append(j.id)
            texts[j.id] = j.description
        j.llm_fit, j.llm_note, j.llm_json = r["llm_fit"], r["llm_note"] or "", r["llm_json"] or ""
        if j.llm_json:  # re-apply the stored assessment on top of the fresh heuristics
            try:
                llm.apply_assessment(j, llm.Assessment.model_validate_json(j.llm_json))
            except Exception:
                pass
        db.update_analysis(j)
    db.commit()
    print(f"reanalyzed {len(rows)} rows, pruned {drop} irrelevant titles, marked {dups} cross-id duplicates")


# ------------------------------------------------------------------ other commands
def recent_clause(hours):
    """Posted within the window (LinkedIn/ATS give a date) or, lacking a date, first seen within it."""
    since = datetime.utcnow() - timedelta(hours=hours)
    return ("((posted != '' AND posted >= ?) OR (posted = '' AND first_seen >= ?))",
            [since.strftime("%Y-%m-%d"), since.strftime("%Y-%m-%dT%H:%M:%SZ")])


def last_run_started():
    p = DATA / "runs.log"
    if not p.exists():
        sys.exit("нет data/runs.log — ещё не было прогона с этой версией")
    return p.read_text().strip().splitlines()[-1].split()[0]


def cmd_list(a):
    db = DB(DATA / "jobs.db")
    where, params = ["verdict NOT IN ('skip','dup')"], []
    if a.last_run:
        where.append("first_seen >= ?")
        params.append(last_run_started())
    if a.hours:
        cl, pr = recent_clause(a.hours)
        where.append(cl)
        params += pr
    if a.status:
        where.append("status=?")
        params.append(a.status)
    if a.min_score:
        where.append("score>=?")
        params.append(a.min_score)
    if a.days:
        where.append("first_seen>=?")
        params.append((datetime.utcnow() - timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if a.all:
        where = [w for w in where if not w.startswith("verdict")] + ["verdict != 'dup'"]
    rows = db.query(" AND ".join(where), params, limit=a.limit)
    cur = None
    for r in report.by_track(rows):
        if r["track"] != cur:
            cur = r["track"]
            print(f"\n=== {report.TRACK_RU.get(cur, 'Прочее')} ===")
        sp = f"IND: {r['sponsor_name']}" if r["sponsor_name"] else ("remote" if r["remote"] else "")
        sal = f" · {filters.money(r['salary_month'])}" if r["salary_month"] else ""
        print(f"{r['score']:3d} [{r['status']:7s}] {r['title']} — {r['company']} | {r['location']}{sal} | {sp} | {r['posted'] or r['first_seen'][:10]}")
        if r["reasons"]:
            print(f"      {r['reasons']}")
        print(f"      {r['id']}  {r['url']}")


def cmd_mark(a):
    db = DB(DATA / "jobs.db")
    if not db.get(a.id):
        sys.exit(f"нет такого id: {a.id}")
    db.mark(a.id, a.status, a.note)
    db.commit()
    print("ok")


def cmd_report(a):
    cfg = load_cfg()
    db = DB(DATA / "jobs.db")
    if a.last_run:
        where, params = "first_seen >= ?", [last_run_started()]
        label = "новые с последнего прогона"
    elif a.hours:
        where, params = recent_clause(a.hours)
        label = f"последние {a.hours} ч"
    else:
        where, params = "first_seen >= ?", [(datetime.utcnow() - timedelta(days=a.days)).strftime("%Y-%m-%dT%H:%M:%SZ")]
        label = f"последние {a.days} дн."
    if a.all:
        pass                                   # everything incl. skipped/dup
    elif a.unchecked:
        where += " AND verdict = 'live' AND status != 'ignored'"          # heuristics only, no LLM yet
    else:
        where += " AND verdict = 'live' AND llm_json != '' AND llm_fit >= 4 AND status != 'ignored'"   # passed LLM check
    rows = db.query(where, params, limit=1000)
    md, htm = report.write_reports(rows, DATA / "reports", f"Вакансии · {label}",
                                   stamp=f"{now_local():%Y-%m-%d-%H%M}-lastrun" if a.last_run else
                                   (f"{now_local():%Y-%m-%d}-{a.hours}h" if a.hours else None))
    print(md, htm, sep="\n")


def cmd_sponsors(a):
    http = Http()
    sp = Sponsors(DATA / "sponsors.json", http)
    if a.refresh:
        sp.refresh()
    print(f"{len(sp.entries)} sponsors in register")
    for name in a.check:
        hits = sp.match(name)
        print(f"{name!r}: " + (", ".join(f"{n} (KVK {k})" for n, k in hits) if hits else "НЕ НАЙДЕН"))


def cmd_discover(a):
    from .discover import discover
    names = list(a.names)
    if a.file:
        names += [l.strip() for l in open(a.file) if l.strip() and not l.startswith("#")]
    if a.from_ind:
        sp = Sponsors(DATA / "sponsors.json", Http())
        pool = [n for n, _ in sp.entries] if a.all else sp.tech_like()
        names += pool[a.offset:a.offset + a.limit] if a.limit else pool[a.offset:]
    if a.area:
        return discover_area(a, names)
    log(f"probing {len(names)} companies")
    found = discover(names)
    out = []
    for name, hits in found.items():
        for h in hits:
            print(f"- {{name: \"{name}\", ats: {h['ats']}, slug: {h['slug']}}}   # {h['count']} jobs")
            out.append({"name": name, "ats": h["ats"], "slug": h["slug"]})
    if a.out:
        Path(a.out).write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False))


def discover_area(a, names):
    """Mass discovery: keep boards with jobs in the area, write them as a companies file (see discover_boards)."""
    from .discover import discover_boards
    cfg = load_cfg()
    t = cfg["profile"].get("target", {})
    regexes = {c["code"]: c["location_regex"] for c in ([t["primary"]] if t.get("primary") else []) + t["countries"]}
    area_re = re.compile(regexes.get(a.area) or a.area, re.I)
    known = {(c["ats"], str(c["slug"])) for c in cfg["companies"]}
    boards = discover_boards(names, area_re, known=known, log=log)
    log(f"{len(boards)} boards with jobs in {a.area}")
    lines = [f"- {{name: {json.dumps(b['name'], ensure_ascii=False)}, ats: {b['ats']}, slug: {b['slug']}}}"
             f"   # {b['in_area']}/{b['jobs']} jobs in {a.area}" for b in boards]
    print("\n".join(lines))
    if a.out:
        Path(a.out).write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------ setup
def cmd_init(a):
    """my/profile.yaml from the example plus a role preset, my/config.yaml and .env from their examples. In a terminal
    (or with --ask) the switches are asked one by one. Never overwrites without --force: my/ is the person's own data."""
    from . import wizard
    roles = sorted(p.stem for p in (ROOT / "presets" / "roles").glob("*.yaml"))
    interactive = a.ask or (not a.role and sys.stdin.isatty())
    role = a.role
    if interactive and not role:
        while role not in roles:
            role = input(f"Роль, ближайшая к твоей ({', '.join(roles)}): ").strip().lower()
    if role not in roles:
        sys.exit(f"укажи --role: {', '.join(roles)} (близкую, потом подправишь role в my/profile.yaml)")
    my = config.MY
    my.mkdir(parents=True, exist_ok=True)
    prof = my / "profile.yaml"
    if prof.exists() and not a.force:
        sys.exit(f"{prof} уже есть; --force перезапишет")
    text = (ROOT / "presets" / "profile.example.yaml").read_text(encoding="utf-8")
    preset = (ROOT / "presets" / "roles" / f"{role}.yaml").read_text(encoding="utf-8")
    marker = "# ROLE: сюда вставляется пресет роли\n"
    text = text.replace(marker, preset.rstrip("\n") + "\n") if marker in text else text + "\n" + preset
    if interactive:
        text = wizard.run(text, my)
    prof.write_text(text, encoding="utf-8")
    print(f"{prof}: профиль, роль {role}" + (", переключатели по твоим ответам" if interactive else " (пример)"))
    for src, dst in ((ROOT / "presets" / "config.example.yaml", my / "config.yaml"),
                     (ROOT / "presets" / "companies.example.yaml", my / "companies.yaml"),
                     (ROOT / ".env.example", ROOT / ".env")):
        if not dst.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"{dst}: из {src.name}")
    print("дальше: в my/profile.yaml перепиши candidate.summary своим резюме, токены — в .env, "
          "потом `python -m jobsearch check`")


def cmd_check(a):
    """Is the setup usable: profile problems, what will be searched, which secrets are present, LLM backend."""
    if a.title:
        cfg = load_cfg()
        for t in a.title:
            ok = filters.is_relevant_title(t)
            why = "" if ok else (" (исключён title_exclude)" if filters.RELEVANT_TITLE.search(t) else
                                 " (не подходит под title_include)")
            print(f"{'✅' if ok else '❌'} {t}{why}")
        return
    cfg = load_cfg()
    notify.load_env(ROOT / ".env")
    p = cfg["profile"]
    t, role, cand = p["target"], p.get("role") or {}, p.get("candidate") or {}
    bad = config.problems(cfg)
    print(f"профиль: {config.MY / 'profile.yaml'}")
    print(f"роль: {role.get('name', '?')} · уровень {cand.get('seniority', 'senior')} · языки "
          f"{', '.join(cand.get('languages') or [])} · виза {'нужна' if cand.get('needs_visa', True) else 'не нужна'}")
    visa_floors = p["prefs"]["salary_min"] is None
    floor = (lambda c: f", порог €{c.get('salary_floor_month') or '—'}") if visa_floors else (lambda c: "")
    tracks = ([f"{t['primary']['name']} (основная{floor(t['primary'])})"] if t.get("primary") else []) + [
        f"{c['name']}" + (f" (€{c.get('salary_floor_month') or '—'})" if visa_floors else "") for c in t["countries"]]
    print("формат: " + ", ".join(config.WORK_MODE_RU[m] for m in t["work_modes"]))
    zones = {"europe": "Европа и СНГ", "middle_east": "Ближний Восток и Африка", "americas": "Америка", "asia": "Азия"}
    print("страны: " + (", ".join(tracks) or "нет (только remote)")
          + (" · офисы: " + config.offices_names(t) if t.get("offices") else " · офисы вне этих стран не показываются")
          + (" · remote: " + ", ".join(zones[z] for z in sorted(filters.REMOTE_ZONES)) if t.get("remote", True) else ""))
    pr = p["prefs"]
    salary = ("порог визы страны" if pr["salary_min"] is None else
              f"свой минимум {config.money(pr['salary_min'], pr['currency'], pr['rates'])}" if pr["salary_min"]
              else "не отсекается")
    word = {"skip": "отсеивать", "flag": "только пометка", "any": "не смотреть", "penalize": "ниже в списке",
            "ok": "как остальные"}
    print(f"зарплата: {salary} · чужой язык: {word[pr['other_language']]} · контракт: {word[pr['contract']]} · "
          f"аутсорс: {word[pr['outsourcing']]} · рекрутеры: {word[pr['agencies']]} · госсектор: {word[pr['public_sector']]}")
    cv_path, cv_fmt = config.cv_source(cfg)
    cv_what = {"latex": "CV под вакансию → PDF", "docx": "CV под вакансию → DOCX (и PDF, если есть LibreOffice)",
               "markdown": "CV под вакансию → PDF через встроенный шаблон", "text": "только текст, без CV под вакансию",
               "none": "не задано", "unknown": "формат не поддерживается"}[cv_fmt]
    print(f"резюме: {cv_path.relative_to(ROOT) if cv_path and cv_path.is_relative_to(ROOT) else cv_path or '—'} "
          f"({cv_what}{'' if not cv_path or cv_path.exists() else ', файла нет'})")
    for n in p.get("_notes") or []:
        print(f"  заметка: {n}")
    li = cfg.get("linkedin", {})
    print(f"LinkedIn: {'вкл' if li.get('enabled', True) else 'выкл'}, запросов {len(li.get('queries') or [])}, "
          f"локации: " + ", ".join(f"{l['name']}{' (remote)' if l.get('remote') else ''}" for l in li.get("locations") or []))
    print(f"доски компаний: {len(cfg['companies'])} из {', '.join(cfg.get('company_files') or []) or '—'}")
    stub = lambda a: f"{a} (заглушка)" if getattr(aggregators.AGGREGATORS.get(a), "blocked", "") else a
    print(f"агрегаторы: {', '.join(map(stub, cfg.get('aggregators') or [])) or '—'}; только в deep: "
          f"{', '.join(cfg.get('aggregators_deep') or []) or '—'}")
    env = {k: bool(os.environ.get(k)) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY",
                                                "CLAUDE_CODE_OAUTH_TOKEN")}
    print("Telegram: " + ("токен и chat id есть" if env["TELEGRAM_BOT_TOKEN"] and env["TELEGRAM_CHAT_ID"]
                          else "нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID в .env — карточки не придут"))
    if not a.fast:
        backend, why = llm.pick_backend(cfg.get("llm", {}))
        print(f"LLM: {backend.name} ({backend.model})" if backend else f"LLM: недоступен — {why}")
    if bad:
        print("\nисправить:")
        for x in bad:
            print(f"  - {x}")
        sys.exit(1)
    print("\nok")


def main(argv=None):
    p = argparse.ArgumentParser(prog="jobsearch")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="collect, triage, report, notify")
    r.add_argument("--no-linkedin", action="store_true")
    r.add_argument("--no-companies", action="store_true")
    r.add_argument("--no-aggregators", action="store_true")
    r.add_argument("--no-telegram", action="store_true", help="не читать Telegram-каналы (tg_channels)")
    r.add_argument("--time-filter", help="LinkedIn f_TPR, e.g. r86400 (day), r604800 (week), r2592000 (month)")
    r.add_argument("--no-llm", action="store_true", help="skip the LLM assessment stage")
    r.add_argument("--deep", action="store_true", help="LinkedIn: все запросы, полная пагинация, без раннего стопа (~40 мин)")
    r.add_argument("--locations", help="LinkedIn: только эти локации (linkedin.locations), через запятую (для отладки)")
    r.add_argument("--notify", action="store_true", help="send Telegram digest")
    r.add_argument("--report-days", type=int, default=14)
    r.set_defaults(fn=cmd_run)

    l = sub.add_parser("list")
    l.add_argument("--status")
    l.add_argument("--min-score", type=int)
    l.add_argument("--days", type=int)
    l.add_argument("--hours", type=int, help="опубликованы за последние N часов")
    l.add_argument("--last-run", action="store_true", help="только впервые найденные последним прогоном")
    l.add_argument("--all", action="store_true", help="include skipped")
    l.add_argument("--limit", type=int, default=100)
    l.set_defaults(fn=cmd_list)

    m = sub.add_parser("mark", help="mark <id> applied|rejected|ignored|interview|offer|later [note]")
    m.add_argument("id")
    m.add_argument("status", choices=["new", "applied", "rejected", "ignored", "interview", "offer", "later"])
    m.add_argument("note", nargs="?")
    m.set_defaults(fn=cmd_mark)

    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int, default=14)
    rp.add_argument("--hours", type=int, help="опубликованы за последние N часов")
    rp.add_argument("--last-run", action="store_true", help="только впервые найденные последним прогоном")
    rp.add_argument("--all", action="store_true", help="всё, включая отсеянные")
    rp.add_argument("--unchecked", action="store_true", help="включить live без LLM-проверки")
    rp.set_defaults(fn=cmd_report)

    asx = sub.add_parser("assess", help="LLM-assess stored jobs that have no assessment yet")
    asx.add_argument("--days", type=int)
    asx.add_argument("--since", help="ISO date, e.g. 2026-09-04")
    asx.add_argument("--limit", type=int, default=300)
    asx.add_argument("--again", action="store_true",
                     help="переоценить и уже оценённое (после правки профиля); нужен --days или --since")
    asx.set_defaults(fn=cmd_assess)

    tl = sub.add_parser("tg-login", help="вход в аккаунт Telegram для групп и каналов без веб-просмотра (один раз)")
    tl.set_defaults(fn=cmd_tg_login)

    tc = sub.add_parser("tg-check", help="каналы из tg_channels: открыт ли веб-просмотр, сколько постов и заголовков роли")
    tc.add_argument("channels", nargs="*", help="проверить эти вместо списка из my/config.yaml")
    tc.add_argument("--days", type=int, default=30)
    tc.set_defaults(fn=cmd_tg_check)

    bt = sub.add_parser("bot", help="Telegram-бот: кнопки статусов под карточками, /applied, /stats")
    bt.set_defaults(fn=cmd_bot)

    cvp = sub.add_parser("cv", help="CV под вакансию: PDF в data/cv/ и что изменено (как кнопка в боте)")
    cvp.add_argument("id", nargs="?", help="id вакансии или rowid")
    cvp.add_argument("--send", action="store_true", help="прислать результат в Telegram")
    cvp.add_argument("--inspect", action="store_true", help="показать, что найдено в резюме (без модели)")
    cvp.set_defaults(fn=cmd_cv)

    af = sub.add_parser("autofill", help="профиль и PDF для расширения автозаполнения откликов (extension/)")
    af.add_argument("--pdf", help="готовый PDF вместо сборки из tex, например CV под вакансию из data/cv/")
    af.add_argument("--no-pdf", action="store_true", help="только profile.json")
    af.add_argument("--out", default="extension", help="куда писать (по умолчанию extension/)")
    af.set_defaults(fn=cmd_autofill)

    tt = sub.add_parser("telegram-test", help="проверить бота: тестовое сообщение и пример дайджеста")
    tt.add_argument("--sample", type=int, default=0, help="прислать пример дайджеста из N последних проверенных вакансий")
    tt.set_defaults(fn=cmd_telegram_test)

    ra = sub.add_parser("reanalyze", help="re-run triage rules over stored jobs")
    ra.add_argument("--prune", action="store_true", help="delete stored rows whose title no longer matches role.title_include")
    ra.set_defaults(fn=cmd_reanalyze)

    s = sub.add_parser("sponsors", help="IND register: refresh / check company names")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("check", nargs="*")
    s.set_defaults(fn=cmd_sponsors)

    d = sub.add_parser("discover", help="detect ATS + slug for company names")
    d.add_argument("names", nargs="*")
    d.add_argument("--file")
    d.add_argument("--from-ind", action="store_true", help="probe tech-looking names from the IND register")
    d.add_argument("--offset", type=int, default=0)
    d.add_argument("--limit", type=int, default=300, help="0 = no limit")
    d.add_argument("--all", action="store_true", help="with --from-ind: every register name, not only tech-looking")
    d.add_argument("--area", help="keep only boards with jobs here: nl | be | fr | de | a regex (mass discovery)")
    d.add_argument("--out")
    d.set_defaults(fn=cmd_discover)

    it = sub.add_parser("init", help="создать my/profile.yaml из пресета роли, my/config.yaml и .env")
    it.add_argument("--role", help="пресет из presets/roles/")
    it.add_argument("--force", action="store_true", help="перезаписать существующий my/profile.yaml")
    it.add_argument("--ask", action="store_true", help="задать вопросы-переключатели (в терминале и так спрашивает)")
    it.set_defaults(fn=cmd_init)

    ck = sub.add_parser("check", help="проверить настройку: профиль, что будет искаться, токены, LLM")
    ck.add_argument("--title", nargs="+", help="проверить, пройдут ли эти заголовки фильтр роли")
    ck.add_argument("--fast", action="store_true", help="не проверять LLM (вызов claude занимает до минуты)")
    ck.set_defaults(fn=cmd_check)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
