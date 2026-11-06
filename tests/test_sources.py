import collections
import json
from types import SimpleNamespace

import pytest

from jobsearch import cli, filters
from jobsearch.cli import load_cfg
from jobsearch.http import Http
from jobsearch.models import Job
from jobsearch.sources import aggregators, ats

TEAMTAILOR_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations"><channel><title>Fortaegis Technologies</title>
<item>
  <title>QA/Test Automation Engineer</title>
  <description>&lt;h3&gt;Job description&lt;/h3&gt;&lt;p&gt;Playwright and Python.&lt;/p&gt;</description>
  <pubDate>Mon, 17 Aug 2026 10:00:00 +0200</pubDate>
  <link>https://fortaegis.teamtailor.com/jobs/6291234-qa-test-automation-engineer</link>
  <remoteStatus>none</remoteStatus>
  <tt:locations><tt:location><tt:name>Amsterdam office</tt:name><tt:city>Amsterdam</tt:city>
    <tt:country>Netherlands</tt:country></tt:location></tt:locations>
</item>
</channel></rss>"""

PERSONIO_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs><position>
  <id>2765735</id><office>Berlin</office><additionalOffices><additionalOffice>Hamburg</additionalOffice></additionalOffices>
  <name>Senior QA Engineer (m/f/d)</name>
  <jobDescriptions><jobDescription><name>Your profile</name><value>&lt;p&gt;Five years of test automation.&lt;/p&gt;</value>
  </jobDescription></jobDescriptions>
  <employmentType>freelance</employmentType><createdAt>2026-10-19T09:00:00+00:00</createdAt>
</position></workzag-jobs>"""


class Board:
    """Http stand-in that answers each request with the next canned body and records the URLs."""
    def __init__(self, *bodies):
        self.bodies, self.urls = list(bodies), []

    def get(self, url, **kw):
        self.urls.append(url)
        body = self.bodies.pop(0)
        return SimpleNamespace(status_code=200, content=body, json=lambda: body)

    def sleep(self):
        pass


def test_teamtailor_job_has_a_clean_title_and_its_city():
    [job] = ats.teamtailor(Board(TEAMTAILOR_RSS), "Fortaegis", "fortaegis")
    assert job.id == "teamtailor:fortaegis:6291234"
    assert (job.title, job.location, job.remote) == ("QA/Test Automation Engineer", "Amsterdam, Netherlands", False)
    assert job.posted == "2026-08-17" and "Playwright and Python." in job.description


def test_personio_job_lists_every_office_and_flags_freelance():
    [job] = ats.personio(Board(PERSONIO_XML), "MILES Mobility", "miles-mobility")
    assert job.id == "personio:miles-mobility:2765735"
    assert job.location == "Berlin / Hamburg"
    assert "Five years of test automation." in job.description
    assert job.extra["employment_type"] == "Contract"


def test_smartrecruiters_board_is_read_past_the_first_hundred():
    page = lambda n, total: {"totalFound": total, "content": [{"id": f"{n}-{i}", "name": "QA Engineer"} for i in range(n)]}
    board = Board(page(100, 110), page(10, 110))
    assert len(ats.smartrecruiters(board, "Lely", "lely1")) == 110
    assert board.urls[1].endswith("offset=100")


def test_smartrecruiters_big_board_is_searched_by_keyword():
    page = lambda total, *ids: {"totalFound": total, "content": [{"id": i, "name": "QA Engineer"} for i in ids]}
    board = Board(page(4000, "x"), page(1, "t1"), page(2, "t1", "q1"), page(0))
    jobs = ats.smartrecruiters(board, "Bosch", "BoschGroup", queries=("test", "QA", "SDET"))
    assert [j.id for j in jobs] == ["smartrecruiters:BoschGroup:t1", "smartrecruiters:BoschGroup:q1"]
    assert [u.rsplit("&", 1)[-1] for u in board.urls[1:]] == ["q=test", "q=QA", "q=SDET"]


def test_board_posting_with_only_a_city_of_a_target_country_is_kept():
    load_cfg()
    at = lambda location: Job(id="x:1", source="personio", company="Acme", title="QA Engineer", url="u", location=location)
    assert filters.in_search_area(at("Berlin"))
    assert filters.in_search_area(at("Paris"))
    assert not filters.in_search_area(at("Austin, Texas, United States"))


# ------------------------------------------------------------------ hiringcafe (added 2026-11-03)
HC_HIT = {
    "id": "grnhse___sportygroup___4951687101", "source": "grnhse",
    "board_token": "sportygroup%2F4951687101", "apply_url": "https://job-boards.eu.greenhouse.io/sportygroup/jobs/1",
    "attributed_org": {"name": "Sporty Group"},
    "job_information": {"title": "Lead Hybrid QA Engineer"},
    "v5_processed_job_data": {"core_job_title": "QA Engineer", "estimated_publish_date": "2026-11-01T12:00:00.",
                              "workplace_type": "Hybrid", "workplace_countries": ["BE", "NL"],
                              "formatted_workplace_location": "Mechelen or Antwerpen",
                              "listed_compensation_currency": "EUR", "listed_compensation_frequency": "Yearly",
                              "yearly_min_compensation": 60000, "yearly_max_compensation": 75000},
}


def test_hiringcafe_hit_becomes_a_job_with_uncoded_id_and_enriched_location():
    load_cfg()                                    # filters are configured: NL_LOC / EU_LOC matter to the track
    job = aggregators._hc_job(HC_HIT, "2026-01-01")
    assert job.id == "hiringcafe:grnhse___sportygroup___4951687101"
    assert (job.company, job.title, job.posted) == ("Sporty Group", "Lead Hybrid QA Engineer", "2026-11-01")
    assert job.location == "Mechelen or Antwerpen, Belgium, Netherlands"
    assert job.salary_text == "EUR 60000-75000 per year"
    assert not job.remote and not job.description


def test_hiringcafe_drops_the_stale_and_rejects_nameless_locations_dedup():
    job = aggregators._hc_job(HC_HIT, "2026-11-02")   # older than the window — too old
    assert job is None


def test_hiringcafe_salary_hourly_is_explicit_for_the_rate_heuristic():
    v5 = {"listed_compensation_currency": "EUR", "listed_compensation_frequency": "Hourly",
          "hourly_min_compensation": 45, "hourly_max_compensation": None}
    assert aggregators._hc_salary(v5) == "EUR from 45 per hour"
    v5["listed_compensation_frequency"] = "Unknown"
    assert aggregators._hc_salary(v5) == ""


MCP_SEARCH = """## HiringCafe job results (showing 1 of 1 matches)

### [QA Engineer](https://hiringcafe.com/job/qa-engineer-acme-amsterdam-mcp123?utm_source=claude)
**Acme**
- **Location:** Amsterdam, North Holland, Netherlands
- **Workplace:** Hybrid
- **Compensation:** €60,000 – €84,000/yr
- **Employment type:** Full Time
- **Posted:** 2026-11-03
- **Job ID:** mcp123
"""
MCP_DETAIL = """# [QA Engineer](https://hiringcafe.com/job/qa-engineer-acme-amsterdam-mcp123)
**Acme**
- **Job ID:** mcp123
- **View & apply:** https://hiringcafe.com/job/qa-engineer-acme-amsterdam-mcp123

## Requirements summary
Playwright and Python.
## Full description
Build and maintain automated tests with Playwright.
"""
CHATGPT_RESULT = {"content": [{"type": "text", "text": "Found 1 matching job"}], "structuredContent": {"jobs": [{
    "id": "chat123", "title": "Senior QA Engineer", "company": "Fallback BV", "location": "Utrecht, Netherlands",
    "workplaceType": "Remote", "employmentTypes": ["Full Time"], "datePosted": "2026-11-03T12:00:00Z",
    "compensation": {"currency": "EUR", "frequency": "Yearly", "minimum": 70000, "maximum": 90000},
    "applyUrl": "https://hiringcafe.com/job/senior-qa-engineer-fallback-bv-chat123",
}]}}


@pytest.fixture
def hc_site(monkeypatch):
    """HiringCafe without the network: MCP POST and Jina GET are scripted independently."""
    site = SimpleNamespace(mcp=None, jina=None, calls=[], slept=0.0)

    def answer(which, url, **kw):
        site.calls.append((which, url, kw))
        value = getattr(site, which)
        if callable(value):
            value = value(url, **kw)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(Http, "post", lambda self, url, **kw: answer("mcp", url, **kw))
    monkeypatch.setattr(Http, "get", lambda self, url, **kw: answer("jina", url, **kw))
    monkeypatch.setattr(Http, "sleep", lambda self: None)
    monkeypatch.setattr(aggregators, "_time", SimpleNamespace(sleep=lambda seconds: setattr(site, "slept", site.slept + seconds)))
    monkeypatch.setattr(aggregators, "_hc_settings", lambda: dict(aggregators.HC_DEFAULTS, queries=["qa"],
                                                                  countries=["Netherlands"], pages=2,
                                                                  jina_delay=0))
    return site


def hc_answer(status=200, text="", js=None):
    return SimpleNamespace(status_code=status, text=text, json=lambda: js)


def hc_mcp(text="", result=None):
    result = result or {"content": [{"type": "text", "text": text}]}
    return hc_answer(js={"jsonrpc": "2.0", "id": 1, "result": result})


def hc_search_page(page_props):
    data = json.dumps({"props": {"pageProps": page_props}})
    return hc_answer(text=f'<script id="__NEXT_DATA__" type="application/json">{data}</script>')


def hc_job(jid="mcp123"):
    return Job(id=f"hiringcafe:{jid}", source="hiringcafe", company="P", title="QA", url="u")


def mcp_card(jid, title, company="Acme", workplace="Onsite"):
    return (f"### [{title}](https://hiringcafe.com/job/{jid}?utm_source=claude)\n**{company}**\n"
            f"- **Location:** Amsterdam, Netherlands\n- **Workplace:** {workplace}\n- **Posted:** 2026-11-03\n"
            f"- **Job ID:** {jid}\n\n")


def posting(jid, company, workplace="Onsite"):
    return SimpleNamespace(jid=jid, company=company, workplace=workplace)


class HiringCafeIndex:
    """search_jobs as the official MCP answers it: postings in rank order, filtered by employer and workplace,
    at most max_per_company per employer and limit in all, «showing X of Y matches» when something is cut."""

    def __init__(self, postings):
        self.postings = postings

    def __call__(self, url, **kw):
        args = kw["json"]["params"]["arguments"]
        hits = [p for p in self.postings if self.matches(p, args)]
        shown = self.cut(hits, args["limit"], args["max_per_company"])
        head = f"(showing {len(shown)} of {len(hits)} matches)" if len(shown) < len(hits) else ""
        cards = "".join(mcp_card(p.jid, "QA Engineer", p.company, p.workplace) for p in shown)
        return hc_mcp(f"## HiringCafe job results {head}\n\n{cards}" if hits else "No jobs matched that search on HiringCafe.")

    @staticmethod
    def matches(p, args):
        return (p.company in args.get("company_names", [p.company])
                and p.company not in args.get("exclude_company_names", [])
                and p.workplace in args["workplace_types"])

    @staticmethod
    def cut(hits, limit, per_company):
        shown, per = [], collections.Counter()
        for p in hits:
            per[p.company] += 1
            if per[p.company] <= per_company:
                shown.append(p)
        return shown[:limit]


def found_ids():
    return sorted(j.id for j in aggregators.hiringcafe(Http()))


def ids(postings):
    return sorted(f"hiringcafe:{p.jid}" for p in postings)


def test_hiringcafe_mcp_card_preserves_metadata_for_the_pipeline():
    [job] = aggregators._hc_mcp_jobs(MCP_SEARCH, "2026-11-01")
    assert (job.id, job.company, job.location, job.posted) == (
        "hiringcafe:mcp123", "Acme", "Amsterdam, North Holland, Netherlands", "2026-11-03")
    assert job.salary_text == "€60,000 – €84,000/yr" and not job.remote
    assert job.extra["employment_type"] == "Full Time"
    assert aggregators._hc_mcp_jobs("No jobs matched that search on HiringCafe. Try again.", "2026-11-01") == []
    with pytest.raises(ValueError):
        aggregators._hc_mcp_jobs("unexpected response", "2026-11-01")


def test_hiringcafe_title_with_brackets_keeps_each_card_its_own_id():
    text = "## HiringCafe job results\n\n" + mcp_card("a1", "QA Engineer") + mcp_card(
        "b2", r"Member of Technical staff 3 \[5-9 years\]- SDET Python Automation")
    jobs = aggregators._hc_mcp_jobs(text, "2026-11-01")
    assert [(j.id, j.title) for j in jobs] == [
        ("hiringcafe:a1", "QA Engineer"),
        ("hiringcafe:b2", "Member of Technical staff 3 [5-9 years]- SDET Python Automation")]


def test_hiringcafe_search_cut_at_the_limit_is_read_to_the_end(hc_site):
    first_page = [posting(f"a{i}", f"Employer {i}") for i in range(25)]
    second_page = [posting(f"b{i}", f"Other {i}") for i in range(5)]
    ranked_below_its_employer = [posting("a0-second", "Employer 0")]
    postings = first_page + second_page + ranked_below_its_employer
    hc_site.mcp = HiringCafeIndex(postings)
    assert found_ids() == ids(postings)


def test_hiringcafe_employer_with_more_roles_than_the_per_company_cap_is_read_to_the_end(hc_site):
    postings = ([posting(f"onsite{i}", "Big Corp") for i in range(4)]
                + [posting(f"hybrid{i}", "Big Corp", "Hybrid") for i in range(3)] + [posting("x", "Small BV")])
    hc_site.mcp = HiringCafeIndex(postings)
    assert found_ids() == ids(postings)


def test_hiringcafe_description_failure_names_every_path(hc_site):
    hc_site.mcp, hc_site.jina = hc_answer(403, "Just a moment"), hc_answer(403, "Just a moment")
    with pytest.raises(RuntimeError, match="MCP: .*Jina: .*ChatGPT MCP: "):
        aggregators.detail_hiringcafe(Http(), hc_job())


def test_hiringcafe_mcp_is_the_primary_transport(hc_site):
    hc_site.mcp = hc_mcp(MCP_SEARCH)
    hc_site.jina = AssertionError("Jina must not be called after a non-empty MCP answer")
    [job] = aggregators.hiringcafe(Http())
    assert job.id == "hiringcafe:mcp123"
    assert [c[0] for c in hc_site.calls] == ["mcp"]


def test_hiringcafe_empty_mcp_falls_back_to_jina(hc_site):
    hc_site.mcp = hc_mcp("No jobs matched that search on HiringCafe. Try broadening the search.")
    hc_site.jina = hc_search_page({"ssrHits": [HC_HIT], "ssrIsLastPage": True})
    [job] = aggregators.hiringcafe(Http())
    assert job.id == "hiringcafe:grnhse___sportygroup___4951687101"
    assert [c[0] for c in hc_site.calls] == ["mcp", "jina"]


def test_hiringcafe_failed_jina_falls_back_to_official_chatgpt_mcp(hc_site):
    def mcp(url, **kw):
        return hc_mcp(result=CHATGPT_RESULT) if "chatgpt" in url else hc_answer(403, "Just a moment")
    hc_site.mcp, hc_site.jina = mcp, hc_answer(200, "Just a moment")
    [job] = aggregators.hiringcafe(Http())
    assert (job.id, job.company, job.salary_text) == (
        "hiringcafe:chat123", "Fallback BV", "EUR 70000-90000 per year")
    assert job.remote and job.extra["hc_transport"] == "chatgpt_mcp"
    assert [c[0] for c in hc_site.calls] == ["mcp", "jina", "mcp"]


def test_hiringcafe_mcp_detail_is_the_full_description(hc_site):
    hc_site.mcp = hc_mcp(MCP_DETAIL)
    assert "automated tests with Playwright" in aggregators.detail_hiringcafe(Http(), hc_job())


def test_hiringcafe_jina_detail_is_used_after_an_mcp_error(hc_site):
    hc_site.mcp = hc_answer(403, "Just a moment")
    hc_site.jina = hc_answer(js={"job": {"job_information": {
        "description": "<h2>Job description</h2><p>Automate with Playwright.</p>"}}})
    assert aggregators.detail_hiringcafe(Http(), hc_job()) == "Job description\nAutomate with Playwright."


def test_hiringcafe_chatgpt_detail_is_the_last_fallback(hc_site):
    def mcp(url, **kw):
        return hc_mcp(MCP_DETAIL) if "chatgpt" in url else hc_answer(403, "Just a moment")
    hc_site.mcp, hc_site.jina = mcp, hc_answer(200, "Just a moment")
    assert "automated tests with Playwright" in aggregators.detail_hiringcafe(Http(), hc_job())
    assert [c[0] for c in hc_site.calls] == ["mcp", "jina", "mcp"]


def test_hiringcafe_refused_descriptions_wait_for_the_backfill(hc_site):
    hc_site.mcp, hc_site.jina = hc_answer(403, "Just a moment"), hc_answer(403, "Just a moment")
    jobs = [hc_job("a"), hc_job("b")]
    cli.fetch_descriptions(Http(), jobs, 10)
    assert [j.description for j in jobs] == ["", ""]     # not "(no description)": the next run's backfill retries
    assert hc_site.slept == 0                            # no four-minute Cloudflare cooldown inside the detail budget


def test_hiringcafe_page_with_changed_markup_is_incomplete(hc_site):
    hc_site.jina = hc_search_page({"hits": [HC_HIT]})
    assert aggregators._hc_search(Http(), "qa", aggregators._GEO["Netherlands"], aggregators.HC_DEFAULTS) == ([], False)


def test_hiringcafe_network_error_keeps_the_pages_already_read(hc_site):
    def answer(url, **kw):
        if url.endswith("page=1"):
            raise ConnectionError("timed out")
        return hc_search_page({"ssrHits": [HC_HIT], "ssrIsLastPage": False})
    hc_site.jina = answer
    assert aggregators._hc_search(Http(), "qa", aggregators._GEO["Netherlands"], aggregators.HC_DEFAULTS) == ([HC_HIT], False)


def test_hiringcafe_jina_challenge_is_an_error_not_an_empty_page(hc_site):
    hc_site.jina = hc_answer(200, "<title>Just a moment...</title>")
    with pytest.raises(RuntimeError, match="Cloudflare challenge"):
        aggregators._hc_jina_get(Http(), "https://hiringcafe.com/classic", aggregators.HC_DEFAULTS)


def test_hiringcafe_is_registered_in_collect_and_detail_maps():
    assert callable(aggregators.AGGREGATORS.get("hiringcafe")) and "hiringcafe" in ats.DETAIL_FETCHERS


# ------------------------------------------------------------------ hc_chrome transport (added 2026-11-05)
def test_hc_chrome_never_runs_inside_tests():
    """Настоящие клики в pytest не место: охрана выключает и сам модуль, и фабрику в aggregators."""
    from jobsearch.sources import hc_chrome
    assert not hc_chrome.enabled() and aggregators._hc_chrome_fetcher() is None


def test_hc_chrome_switch_honours_missing_utilities_and_off(monkeypatch):
    from jobsearch.sources import hc_chrome
    monkeypatch.delenv("HC_CHROME", raising=False)
    monkeypatch.setattr(hc_chrome, "_missing", lambda: ["xdotool", "xclip"])
    assert not hc_chrome._active()          # auto без утилит — нет
    monkeypatch.setenv("HC_CHROME", "on")
    assert not hc_chrome._active()          # и явный on не спасает: их всё равно нет
    monkeypatch.setattr(hc_chrome, "_missing", lambda: [])
    assert hc_chrome._active()              # всё на месте — включён
    monkeypatch.setenv("HC_CHROME", "off")
    assert not hc_chrome._active()          # off сильнее наличия утилит


def _hc_frame(path, orange=None, wordmark=None, specks=None):
    """Синтетический кадр scrot: белая страница, оранжевый кластер, под ним тёмный CLOUDFLARE,
    в полосе — отдельные тёмные точки (число «мимо») — как у логотипа в контенте."""
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1360, 900), "white")
    d = ImageDraw.Draw(img)
    if orange:
        d.rectangle(orange, fill=(232, 129, 41))     # оранжевое облако CF / логотип компании
    if wordmark:
        d.rectangle(wordmark, fill=(30, 30, 30))     # слово CLOUDFLARE под облаком
    for (x, y) in (specks or []):
        d.point((x, y), fill=(60, 60, 60))
    img.save(path)


def test_hc_chrome_finds_widget_with_cloudflare_wordmark(tmp_path):
    """Виджет Cloudflare (кадры 04.11: кластер 498–524 × 414–428): клик (253,421) в чекбокс."""
    from jobsearch.sources import hc_chrome
    p = tmp_path / "widget.png"
    _hc_frame(p, orange=(498, 414, 526, 428), wordmark=(460, 434, 534, 446))
    assert hc_chrome._find_checkbox(p) == (253, 421)


def test_hc_chrome_orange_logo_without_wordmark_is_rejected(tmp_path):
    """Оранжевый логотип в уже загруженном контенте (Ennaturiijk: 111 px, 38×26, y~607) — не виджет,
    и горстка тёмных точек ниже его не спасает: 5 < порога 25 в полосе под кластером."""
    from jobsearch.sources import hc_chrome
    p = tmp_path / "logo.png"
    _hc_frame(p, orange=(150, 594, 190, 622), specks=[(160, 640), (180, 650), (170, 660),
                                                      (200, 645), (210, 655)])
    assert hc_chrome._find_checkbox(p) is None


def test_hc_chrome_frame_without_any_orange_is_rejected(tmp_path):
    from jobsearch.sources import hc_chrome
    p = tmp_path / "blank.png"
    _hc_frame(p, wordmark=(460, 434, 534, 446))     # даже тёмная надпись без оранжевого — ничего
    assert hc_chrome._find_checkbox(p) is None


def _dialog_frame(path, dialog=True):
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1360, 900), "white")
    d = ImageDraw.Draw(img)
    if dialog:
        # GTK-диалог Ctrl+S: синяя рамка фокуса у поля Name — единственная синяя полоса кадра
        d.rectangle((64, 15, 1110, 41), outline=(26, 115, 232), width=2)
    else:
        # страница в загрузке: спиннер вкладки тоже синий, но точек в нём мало (замер 04.11: ≤13)
        for x in range(310, 322):
            d.point((x, 39), fill=(26, 115, 232))
        for y in range(34, 45):
            d.point((315, y), fill=(26, 115, 232))
    img.save(path)


def _bare_session(monkeypatch, png):
    from jobsearch.sources import hc_chrome
    s = hc_chrome._Session.__new__(hc_chrome._Session)
    monkeypatch.setattr(hc_chrome._Session, "_screenshot", lambda self: png)
    return s


def test_hc_chrome_save_dialog_is_confirmed_by_name_field_ring(tmp_path, monkeypatch):
    s = _bare_session(monkeypatch, tmp_path / "dialog.png")
    _dialog_frame(tmp_path / "dialog.png", dialog=True)
    assert s._save_dialog_open()


def test_hc_chrome_save_dialog_missing_while_tab_spins_alone(tmp_path, monkeypatch):
    """Страница в загрузке: спиннер вкладки синий, но рамки поля нет — диалога нет, кликов нет."""
    s = _bare_session(monkeypatch, tmp_path / "spin.png")
    _dialog_frame(tmp_path / "spin.png", dialog=False)
    assert not s._save_dialog_open()


def test_hc_chrome_profile_heal_after_two_blank_starts(tmp_path, monkeypatch):
    """Две пустые загрузки подряд — профиль в aside, начинаем новый (виновность профиля не
    доказана, но потери — пара минут против сломанной ночи)."""
    from jobsearch.sources import hc_chrome
    prof = tmp_path / "profile"
    prof.mkdir()
    s = hc_chrome._Session.__new__(hc_chrome._Session)
    s.profile = prof
    s.blank_starts = 1
    s._heal_profile()
    assert prof.is_dir()                     # один пустой запуск — профиль ещё живёт
    s.blank_starts = 2
    s._heal_profile()
    assert not prof.is_dir()                 # два — aside, начинаем новый
    rest = list(tmp_path.glob("profile.broken-*"))
    assert len(rest) == 1 and s.blank_starts == 0


def test_hc_chrome_residue_sweeper_takes_only_our_old_files(tmp_path):
    """Хвосты прошлых запусков: singleton-папки /tmp/com.google.Chrome.* и сохранения Ctrl+S в
    Downloads убираются, если старше часа; чужие имена и свежие файлы не трогаются."""
    import os
    import time as _time
    from jobsearch.sources import hc_chrome

    stale_at = _time.time() - 7200
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    stale_dir = tmpdir / "com.google.Chrome.deadbeef"
    stale_dir.mkdir()
    fresh_dir = tmpdir / "com.google.Chrome.now"
    fresh_dir.mkdir()
    os.utime(stale_dir, (stale_at, stale_at))          # fresh_dir — без utime, только что создан

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    old_html = downloads / "Qa Jobs _ HiringCafe.html"
    old_html.write_text("<html></html>")
    fresh_html = downloads / "Qa Jobs _ HiringCafe (1).html"
    fresh_html.write_text("<html></html>")
    other_html = downloads / "manual notes.html"
    other_html.write_text("keep me")
    stub_old = downloads / "Just a moment….html"
    stub_old.write_bytes(b"Just a moment")
    assets_old = downloads / "Qa Jobs _ HiringCafe_files"
    assets_old.mkdir()
    for p in (old_html, stub_old, assets_old):
        os.utime(p, (stale_at, stale_at))              # fresh_html и other_html — свежие, как есть

    s = hc_chrome._Session.__new__(hc_chrome._Session)
    s.downloads = downloads
    s._sweep_residue(tmpdir=tmpdir)

    assert not stale_dir.exists() and not old_html.exists()
    assert not stub_old.exists() and not assets_old.exists()
    assert fresh_dir.exists() and fresh_html.exists() and other_html.exists()


def test_hc_chrome_pid_alive():
    import os
    from jobsearch.sources import hc_chrome
    assert hc_chrome._Session._pid_alive(os.getpid())
    assert not hc_chrome._Session._pid_alive(99999999)


def test_hc_chrome_frame_has_text(tmp_path):
    """Первый рендер на свежем Chrome идёт 15–25 с пустых кадров — Ctrl+A до него бесполезен."""
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    from jobsearch.sources import hc_chrome

    blank = tmp_path / "blank.png"
    Image.new("RGB", (1360, 900), "white").save(blank)
    assert not hc_chrome._frame_has_text(blank)

    text = tmp_path / "text.png"
    img = Image.new("RGB", (1360, 900), "white")
    ImageDraw.Draw(img).rectangle((200, 300, 400, 700), fill=(30, 30, 30))
    img.save(text)
    assert hc_chrome._frame_has_text(text)


def test_hc_json_description_accepts_response_object_or_string():
    js = {"job": {"job_information": {"description": "<p>Automate with Playwright.</p>"}}}
    assert aggregators._hc_json_description(hc_answer(js=js)) == "Automate with Playwright."
    assert aggregators._hc_json_description(json.dumps(js)) == "Automate with Playwright."
    with pytest.raises(ValueError):
        aggregators._hc_json_description("<html>challenge page</html>")


def test_hiringcafe_search_takes_the_chrome_page_before_jina(hc_site):
    html = hc_search_page({"ssrHits": [HC_HIT], "ssrIsLastPage": True}).text
    hc_site.jina = AssertionError("Jina must not be called when Chrome produced a page")
    hits, complete = aggregators._hc_search(Http(), "qa", aggregators._GEO["Netherlands"],
                                            aggregators.HC_DEFAULTS, fetch=lambda url: html)
    assert complete and hits
    assert hc_site.calls == []              # ни MCP, ни Jina не тронуты


def test_hiringcafe_search_falls_back_from_chrome_to_jina(hc_site):
    hc_site.jina = hc_search_page({"ssrHits": [HC_HIT], "ssrIsLastPage": True})
    hits, complete = aggregators._hc_search(Http(), "qa", aggregators._GEO["Netherlands"],
                                            aggregators.HC_DEFAULTS, fetch=lambda url: None)
    assert complete and hits
    assert [c[0] for c in hc_site.calls] == ["jina"]


def test_hiringcafe_chrome_challenge_text_is_not_a_result(hc_site):
    hits, complete = aggregators._hc_search(Http(), "qa", aggregators._GEO["Netherlands"],
                                            aggregators.HC_DEFAULTS,
                                            fetch=lambda url: "<title>Just a moment...</title>")
    assert (hits, complete) == ([], False)  # в дайджест не попали, наверх — Jina в конце цепочки
    assert hc_site.calls == []


def test_hiringcafe_chrome_detail_sits_between_mcp_and_jina(hc_site, monkeypatch):
    hc_site.mcp = hc_answer(403, "Just a moment")
    hc_site.jina = AssertionError("Jina must not be called when Chrome returned the JSON")
    body = json.dumps({"job": {"job_information": {"description": "<p>Automate with Playwright.</p>"}}})
    monkeypatch.setattr(aggregators, "_hc_chrome_fetcher", lambda: (lambda url: body))
    assert aggregators.detail_hiringcafe(Http(), hc_job()) == "Automate with Playwright."
    assert [c[0] for c in hc_site.calls] == ["mcp"]


def test_hiringcafe_chrome_detail_failure_is_named_in_the_chain_error(hc_site, monkeypatch):
    monkeypatch.setattr(aggregators, "_hc_chrome_fetcher", lambda: (lambda url: None))
    hc_site.mcp, hc_site.jina = hc_answer(403, "Just a moment"), hc_answer(403, "Just a moment")
    with pytest.raises(RuntimeError, match="MCP: .*chrome: .*Jina: .*ChatGPT MCP: "):
        aggregators.detail_hiringcafe(Http(), hc_job())


# ---------------------------------------------------------------- corporate career sites
RMK_PAGE = """<table aria-label="Search results for test. Page 1 of 1, Results 1 to 2 of 2"><tbody>
<tr class="data-row"><td><a class="jobTitle-link" href="/job/Herzogenaurach-QA-Engineer-BY/1428326333/">QA Engineer</a>
  <span class="jobLocation">Herzogenaurach, BY, DE</span><span class="jobDate">Oct 17, 2026</span></td></tr>
<tr class="data-row"><td><a class="jobTitle-link" href="/job/Portland-Apparel-Developer-OR/1415117033/">Apparel Developer</a>
  <span class="jobLocation">Portland, OR, US</span></td></tr></tbody></table>"""


class Site(Board):
    """Board for HTML pages and POST endpoints."""
    def get(self, url, **kw):
        self.urls.append(url)
        body = self.bodies.pop(0)
        return SimpleNamespace(status_code=200, text=body, json=lambda: body)

    post = get


def test_successfactors_location_gets_the_country_behind_its_code():
    jobs = ats.rmk(Site(RMK_PAGE), "adidas", "jobs.adidas-group.com", queries=("test",))
    assert [(j.id, j.location, j.posted) for j in jobs] == [
        ("rmk:jobs.adidas-group.com:1428326333", "Herzogenaurach, BY, DE, Germany", "2026-10-17"),
        ("rmk:jobs.adidas-group.com:1415117033", "Portland, OR, US", "")]
    assert jobs[0].url == "https://jobs.adidas-group.com/job/Herzogenaurach-QA-Engineer-BY/1428326333/"


def test_beesite_job_lists_all_its_cities():
    page = {"SearchResult": {"SearchResultCountAll": 1, "SearchResultItems": [{"MatchedObjectId": "62330",
            "MatchedObjectDescriptor": {"PositionTitle": "Test Automation Engineer",
                                        "PositionURI": "https://jobs.commerzbank.com/index.php?ac=jobad&id=62330",
                                        "PositionLocation": [{"CityName": "Lodz", "CountryName": "Poland"},
                                                             {"CityName": "Frankfurt", "CountryName": "Germany"}],
                                        "PublicationStartDate": "2026-08-25"}}]}}
    [job] = ats.beesite(Site(page), "Commerzbank", "coba-beesite-production-gjb.app.beesite.de", queries=("QA",))
    assert (job.id, job.location) == ("beesite:coba-beesite-production-gjb.app.beesite.de:62330",
                                      "Lodz, Poland / Frankfurt, Germany")


def test_phenom_job_links_to_the_site_and_leaves_the_text_to_the_job_page():
    page = {"refineSearch": {"totalHits": 1, "data": {"jobs": [{"jobId": "R1", "title": "Senior Test Engineer",
            "multi_location": ["Utrecht, Utrecht, Netherlands"], "postedDate": "2026-10-02T14:51:48.000+0000",
            "descriptionTeaser": "Playwright"}]}}}
    [job] = ats.phenom(Site(page), "DHL", "careers.dhl.com", queries=("test",))
    assert (job.url, job.location, job.posted, job.description) == (
        "https://careers.dhl.com/global/en/job/R1", "Utrecht, Utrecht, Netherlands", "2026-10-02", "")


def test_workday_reads_past_the_first_page_and_asks_where_a_multi_city_posting_is():
    posting = lambda n, where: {"title": f"QA Engineer {n}", "externalPath": f"/job/x_{n}", "locationsText": where}
    site = Site({"total": 21, "jobPostings": [posting(i, "Hamburg") for i in range(20)]},
                {"total": 0, "jobPostings": [posting(20, "2 Locations")]},
                {"jobPostingInfo": {"location": "Amsterdam", "additionalLocations": ["Berlin"]}})
    jobs = ats.workday(site, "Airbus", "ag/wd3/Airbus", queries=("QA",))
    assert len(jobs) == 21 and jobs[-1].location == "Amsterdam / Berlin"


# ---------------------------------------------------------------- boards are read in parallel
def test_board_that_fails_does_not_stop_the_others(monkeypatch):
    def board(http, company, slug):
        if slug == "down":
            raise ConnectionError("timeout")
        return [Job(id=f"greenhouse:{slug}:1", source="greenhouse", company=company, title="QA Engineer",
                    url="u", location="Amsterdam")]
    monkeypatch.setitem(ats.FETCHERS, "greenhouse", board)
    companies = [{"name": n, "ats": "greenhouse", "slug": n.lower()} for n in ("Adyen", "Down", "Mollie")]
    assert [j.company for j in cli.collect_boards(companies, workers=3)] == ["Adyen", "Mollie"]
