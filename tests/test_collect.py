from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jobsearch import cli, llm, notify
from jobsearch.db import DB
from jobsearch.http import Http
from jobsearch.models import Job
from jobsearch.sources import linkedin

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
HOUR = 3600


# ---------------------------------------------------------------- search window from coverage
def test_window_is_base_without_a_previous_search():
    assert cli.search_window(4 * HOUR, None, NOW, 2 * HOUR, 72 * HOUR) == 4 * HOUR


def test_window_is_base_when_previous_search_is_recent():
    assert cli.search_window(4 * HOUR, "2026-10-27T10:00:00Z", NOW, 2 * HOUR, 72 * HOUR) == 4 * HOUR


def test_window_reaches_back_past_a_skipped_run():
    assert cli.search_window(4 * HOUR, "2026-10-27T03:00:00Z", NOW, 2 * HOUR, 72 * HOUR) == 11 * HOUR


def test_window_stops_at_cap():
    assert cli.search_window(4 * HOUR, "2026-10-20T12:00:00Z", NOW, 2 * HOUR, 72 * HOUR) == 72 * HOUR


# ---------------------------------------------------------------- collection: coverage, failures
@pytest.fixture
def linkedin_cfg():
    return {"linkedin": {"window_margin": 2 * HOUR, "window_max": 72 * HOUR,
                         "locations": [{"name": "Netherlands", "queries": ["QA Engineer", "SDET"]}]}}


@pytest.fixture
def run_args():
    return SimpleNamespace(time_filter="r14400", deep=False, locations=None)


@pytest.fixture
def searches(monkeypatch):
    """Replaces LinkedIn search: answers come from `searches.complete[query]`, windows asked are recorded."""
    calls = SimpleNamespace(windows={}, complete={})

    def fake_search(http, q, location, time_filter, **kw):
        calls.windows[q] = int(time_filter[1:])
        return [], calls.complete.get(q, True)
    monkeypatch.setattr(cli.linkedin, "search", fake_search)
    monkeypatch.setattr(Http, "sleep", lambda self: None)
    return calls


def test_only_completed_searches_count_as_covered(linkedin_cfg, run_args, searches):
    searches.complete["SDET"] = False
    _, done, _ = cli.collect_linkedin(linkedin_cfg, Http(), run_args, {})
    assert [key[1] for key in done] == ["QA Engineer"]


def test_search_after_a_gap_widens_its_window(linkedin_cfg, run_args, searches):
    nine_hours_ago = datetime.now(timezone.utc) - timedelta(hours=9)
    coverage = {("Netherlands", "SDET", False): nine_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")}
    cli.collect_linkedin(linkedin_cfg, Http(), run_args, coverage)
    assert searches.windows["QA Engineer"] == 4 * HOUR
    assert round(searches.windows["SDET"] / HOUR) == 11      # 9 h since its last search + 2 h margin


def test_three_failed_searches_in_a_row_postpone_the_rest(linkedin_cfg, run_args, searches):
    linkedin_cfg["linkedin"]["locations"][0]["queries"] = ["A", "B", "C", "D"]
    searches.complete.update(A=False, B=False, C=False)
    _, done, notes = cli.collect_linkedin(linkedin_cfg, Http(), run_args, {})
    assert "D" not in searches.windows and not done
    assert "отложено запросов: 1" in notes[-1]


def test_deep_only_aggregator_runs_in_the_deep_run_only(monkeypatch):
    monkeypatch.setitem(cli.aggregators.AGGREGATORS, "slow", lambda http: [
        Job(id="slow:1", source="slow", company="C", title="QA Engineer", url="u")])
    cfg = {"aggregators": [], "aggregators_deep": ["slow"]}
    fast, deep = (SimpleNamespace(no_linkedin=True, no_companies=True, no_aggregators=False, deep=d) for d in (0, 1))
    assert cli.collect(cfg, Http(), fast)[0] == []
    assert [j.id for j in cli.collect(cfg, Http(), deep)[0]] == ["slow:1"]


# ---------------------------------------------------------------- LinkedIn search reports a cut-short pagination
CARD = ('<li><div class="base-search-card" data-entity-urn="urn:li:jobPosting:{id}">'
        '<h3 class="base-search-card__title">QA Engineer</h3></div></li>')


def test_search_that_loses_linkedin_midway_is_incomplete():
    pages = iter([SimpleNamespace(status_code=200, text=CARD.format(id=1)), None])
    http = SimpleNamespace(get=lambda url: next(pages), sleep=lambda: None)
    jobs, complete = linkedin.search(http, "QA Engineer", "Netherlands", "r14400")
    assert [j.id for j in jobs] == ["linkedin:1"] and not complete


def test_search_that_reaches_the_empty_page_is_complete():
    pages = iter([SimpleNamespace(status_code=200, text=CARD.format(id=1)), SimpleNamespace(status_code=200, text="")])
    http = SimpleNamespace(get=lambda url: next(pages), sleep=lambda: None)
    _, complete = linkedin.search(http, "QA Engineer", "Netherlands", "r14400")
    assert complete


# ---------------------------------------------------------------- 429 handling
@pytest.fixture
def linkedin_answers(monkeypatch):
    """Http whose session returns the given status codes in order; sleeps are recorded, not slept."""
    waits = []
    monkeypatch.setattr("jobsearch.http.time.sleep", waits.append)

    def make(*codes):
        http = Http()
        answers = iter(codes)
        http.s.request = lambda method, url, **kw: SimpleNamespace(status_code=next(answers))
        return http, waits
    return make


def test_429_is_retried_after_a_short_wait(linkedin_answers):
    http, waits = linkedin_answers(429, 429, 200)
    r = http.get("https://www.linkedin.com/jobs-guest/x")
    assert r.status_code == 200 and sum(waits) < 60
    assert http.stats["linkedin"]["429"] == 2 and http.stats["linkedin"]["ok"] == 1


def test_five_429_in_a_row_give_up(linkedin_answers):
    http, _ = linkedin_answers(*[429] * 5)
    assert http.get("https://www.linkedin.com/jobs-guest/x") is None
    assert http.stats["linkedin"]["gave_up"] == 1


# ---------------------------------------------------------------- duplicates of intermediaries
PARTNER = "This position is listed on behalf of a partner company. Our partner is looking for a Senior QA Engineer "


def jobgether(text):
    return Job(id="linkedin:9", source="linkedin", company="Jobgether", title="Senior QA Engineer", url="u",
               description=PARTNER + text)


def test_intermediary_copy_for_another_country_is_a_duplicate():
    stored = {"a": PARTNER + "based in France. Playwright, TypeScript, payments platform, CI pipelines, mentoring."}
    job = jobgether("based in Germany. Playwright, TypeScript, payments platform, CI pipelines, mentoring.")
    assert cli.same_original(job, ["a"], stored.get) == "a"


def test_intermediary_role_of_another_client_is_not_a_duplicate():
    stored = {"a": PARTNER + "based in France. Playwright, TypeScript, payments platform, CI pipelines, mentoring."}
    job = jobgether("in healthcare SaaS. Lead the testing strategy, build AI agents for test generation, LLM evals.")
    assert cli.same_original(job, ["a"], stored.get) is None


def test_ordinary_company_repost_is_a_duplicate_by_title_alone():
    job = Job(id="linkedin:5", source="linkedin", company="Adyen", title="QA Engineer", url="u", description="other text")
    assert cli.same_original(job, ["a"], {"a": "different text"}.get) == "a"


def acme(id, location, **kw):
    return Job(id=id, source="linkedin", company="Acme", title="QA Engineer", url="u", location=location, **kw)


def test_copy_in_the_same_run_adds_its_city_to_the_original(tmp_path):
    de, nl = acme("linkedin:1", "Germany"), acme("linkedin:2", "Netherlands")
    assert cli.mark_duplicates([de, nl], DB(tmp_path / "jobs.db")) == [de]
    assert nl.verdict == "dup" and de.location == "Germany / Netherlands"


def test_copy_of_a_stored_posting_adds_its_city_to_the_row(tmp_path):
    db = DB(tmp_path / "jobs.db")
    db.insert(acme("linkedin:1", "Germany", verdict="live"))
    nl = acme("linkedin:2", "Netherlands")
    assert cli.mark_duplicates([nl], db) == []
    assert nl.verdict == "dup" and db.get("linkedin:1")["location"] == "Germany / Netherlands"


def test_copy_that_passes_is_not_swallowed_by_a_skipped_original(tmp_path):
    db = DB(tmp_path / "jobs.db")
    db.insert(acme("linkedin:1", "Netherlands", verdict="skip"))   # e.g. the LinkedIn text was in Dutch
    copy = acme("hiringcafe:2", "Netherlands", verdict="live")
    cli.mark_duplicates([copy], db)
    assert copy.verdict == "live"


# ---------------------------------------------------------------- companies that never reach the digest
def test_low_yield_company_is_cut_unless_the_owner_touched_it():
    stats = {"Sii Poland": (113, 3, False), "Jobgether": (217, 14, False), "Looper Engineering": (53, 2, True)}
    assert llm.low_yield_companies(stats, {}, 20) == {"sii": 113}       # company_key drops the country


def test_low_yield_job_is_skipped_with_a_reason():
    job = Job(id="linkedin:7", source="linkedin", company="Sii Poland", title="QA Engineer", url="u", verdict="live")
    llm.skip_low_yield([job], {"sii": 113})
    assert job.verdict == "skip" and llm.is_skip_reason(job.reasons[-1])


# ---------------------------------------------------------------- quiet hours
def test_quiet_hours_cover_the_night_only():
    assert notify.quiet("00:00-08:00", datetime(2026, 10, 28, 0, 30))
    assert not notify.quiet("00:00-08:00", datetime(2026, 10, 28, 8, 15))
