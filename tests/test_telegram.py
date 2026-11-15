import json
from types import SimpleNamespace

import pytest

from jobsearch import cli, filters, llm
from jobsearch.cli import load_cfg
from jobsearch.db import DB
from jobsearch.sources import telegram
from jobsearch.sources.telegram import Post, Vacancy


def preview_page(*posts):
    """t.me/s/<channel> markup for (id, date, inner html) posts, as the preview renders them."""
    items = "".join(
        f'<div class="tgme_widget_message" data-post="forallqa/{msg_id}"><div class="tgme_widget_message_bubble">'
        f'<div class="tgme_widget_message_text js-message_text">{html}</div>'
        f'<a class="tgme_widget_message_date"><time datetime="{date}"></time></a></div></div>'
        for msg_id, date, html in posts)
    return f"<html><body>{items}</body></html>"


class Preview:
    """Http stand-in: each GET answers with the next page (or a redirect) and records the URL."""
    def __init__(self, *pages):
        self.pages, self.urls = list(pages), []

    def get(self, url, **kw):
        self.urls.append(url)
        page = self.pages.pop(0)
        if page == "redirect":
            return SimpleNamespace(status_code=302, text="")
        return SimpleNamespace(status_code=200, text=page)

    def sleep(self):
        pass


class Extractor:
    """LLM backend stand-in: answers every post with the same vacancies and counts the calls."""
    def __init__(self, *vacancies):
        self.vacancies, self.calls = list(vacancies), 0

    def ask(self, system, prompt, out_cls, model=None):
        self.calls += 1
        return out_cls(vacancies=self.vacancies)


@pytest.fixture(autouse=True)
def qa_profile():
    load_cfg()          # filters.is_relevant_title follows the role from profile.yaml


def test_preview_post_keeps_line_breaks_and_links_but_not_the_quoted_reply():
    html = ('<div class="tgme_widget_message" data-post="forallqa/7">'
            '<div class="tgme_widget_message_reply"><div class="tgme_widget_message_text">quoted</div></div>'
            '<div class="tgme_widget_message_text js-message_text">Senior QA Engineer<br/>в '
            '<a href="https://example.com/job">Example</a></div>'
            '<a class="tgme_widget_message_date"><time datetime="2026-11-13T18:51:58+01:00"></time></a></div>')

    [post] = telegram.parse_preview(html, "forallqa")

    assert (post.id, post.date, post.text) == (7, "2026-11-13T17:51:58Z", "Senior QA Engineer\nв Example")
    assert post.links == ["https://example.com/job"]


def test_reading_goes_back_page_by_page_to_the_last_stored_post():
    http = Preview(preview_page((21, "2026-11-14T10:00:00+00:00", "QA Lead"), (22, "2026-11-15T10:00:00+00:00", "SDET")),
                   preview_page((19, "2026-11-12T10:00:00+00:00", "old"), (20, "2026-11-13T10:00:00+00:00", "QA")))

    posts = telegram.web_posts(http, "forallqa", after_id=19, since="2026-10-01")

    assert [p.id for p in posts] == [20, 21, 22]
    assert http.urls == ["https://t.me/s/forallqa", "https://t.me/s/forallqa?before=21"]


def test_first_read_stops_at_the_date_limit():
    http = Preview(preview_page((5, "2026-09-01T10:00:00+00:00", "too old"), (6, "2026-11-01T10:00:00+00:00", "QA")))

    posts = telegram.web_posts(http, "forallqa", after_id=0, since="2026-10-15")

    assert [p.id for p in posts] == [6]
    assert len(http.urls) == 1


def test_group_without_web_preview_needs_the_account():
    with pytest.raises(telegram.NoPreview):
        telegram.web_posts(Preview("redirect"), "qa_jobs")


def test_channel_is_named_by_link_handle_or_name():
    assert {telegram.channel_name(s) for s in ("https://t.me/QA_Work", "@qa_work", "t.me/s/qa_work/", "qa_work")} \
        == {"qa_work"}


def test_only_short_lines_with_a_qa_title_send_a_post_to_the_model():
    text = "🔥 Senior QA Automation Engineer | Remote\nWe need 5+ years of experience in test automation with Playwright " \
           "and a strong background in API testing and CI pipelines for a product team.\nProduct Manager"

    assert telegram.title_lines(text, filters.is_relevant_title) == ["Senior QA Automation Engineer | Remote"]


def test_digest_post_gives_a_job_per_qa_vacancy_with_its_own_fragment():
    post = Post("af_job_board", 191, "2026-11-04T07:03:19Z", "digest of three roles")
    vacancies = [Vacancy(title="QA Automation Engineer", company="Acme", location="Berlin, Germany",
                         work_mode="hybrid", fragment="QA Automation Engineer at Acme, Berlin, hybrid. " * 3),
                 Vacancy(title="Product Designer", company="Acme", fragment="Product Designer at Acme. " * 5),
                 Vacancy(title="SDET", company="Beta", location="Remote (Europe)", work_mode="remote",
                         fragment="SDET at Beta, remote in Europe, Python and pytest. " * 2)]

    jobs = telegram.to_jobs(post, vacancies, filters.is_relevant_title)

    assert [(j.id, j.company, j.location, j.remote) for j in jobs] == [
        ("telegram:af_job_board/191/1", "Acme", "Berlin, Germany", False),
        ("telegram:af_job_board/191/2", "Beta", "Remote (Europe)", True)]
    assert jobs[0].description.startswith("QA Automation Engineer at Acme")
    assert {j.url for j in jobs} == {"https://t.me/af_job_board/191"}


def test_single_vacancy_post_keeps_the_whole_text():
    post = Post("qa_chillout_jobs", 1436, "2026-11-14T06:46:22Z", "Middle QA Automation Engineer | Paphos, Cyprus\n…")

    [job] = telegram.to_jobs(post, [Vacancy(title="Middle QA Automation Engineer", location="Paphos, Cyprus",
                                            work_mode="onsite", fragment="ignored for a single vacancy")],
                             filters.is_relevant_title)

    assert (job.id, job.description, job.posted) == ("telegram:qa_chillout_jobs/1436", post.text, "2026-11-14")


def test_each_post_goes_to_the_model_once_and_its_jobs_come_back_every_run(tmp_path, monkeypatch):
    post = Post("forallqa", 6165, telegram.since_iso(1), "Senior QA Engineer в Example\n" + "Playwright, API. " * 30)
    monkeypatch.setattr(telegram, "web_posts", lambda http, ch, after, since, max_pages: [post] if after < post.id else [])
    extractor = Extractor(Vacancy(title="Senior QA Engineer", company="Example", location="Remote (Europe)",
                                  work_mode="remote"))
    monkeypatch.setattr(llm, "pick_backend", lambda cfg: (extractor, ""))
    cfg = {"tg_channels": {"channels": ["https://t.me/forallqa"]}, "llm": {"workers": 1}}
    db, run = DB(tmp_path / "jobs.db"), SimpleNamespace(no_llm=False)

    first = cli.collect_telegram(cfg, Preview(), db, run, known=set())
    second = cli.collect_telegram(cfg, Preview(), db, run, known={j.id for j in first})

    assert extractor.calls == 1
    assert [j.id for j in first] == [j.id for j in second] == ["telegram:forallqa/6165"]
    assert json.loads(db.tg_parsed(telegram.since_iso(30))[0]["extracted"])[0]["company"] == "Example"


def test_post_stays_pending_while_the_model_is_unavailable(tmp_path, monkeypatch):
    post = Post("forallqa", 6166, telegram.since_iso(1), "QA Lead в Example")
    monkeypatch.setattr(telegram, "web_posts", lambda http, ch, after, since, max_pages: [post] if after < post.id else [])
    monkeypatch.setattr(llm, "pick_backend", lambda cfg: (None, "claude не залогинен"))
    db = DB(tmp_path / "jobs.db")

    jobs = cli.collect_telegram({"tg_channels": {"channels": ["forallqa"]}}, Preview(), db,
                                SimpleNamespace(no_llm=False), known=set())

    assert jobs == []
    assert [r["msg_id"] for r in db.tg_pending(telegram.since_iso(30), 10)] == [6166]


def test_short_post_is_parsed_together_with_the_job_page_it_links(tmp_path, monkeypatch):
    post = Post("forallqa", 6173, telegram.since_iso(1), "Senior Fullstack QA Engineer\nв inDrive. Описание вакансии.",
                ["https://indrive.pinpointhq.com/en/postings/83854790"])
    monkeypatch.setattr(telegram, "web_posts", lambda http, ch, after, since, max_pages: [post] if after < post.id else [])
    monkeypatch.setattr(cli, "job_page_text", lambda http, url: "Location: Cyprus. Playwright, API, 5+ years.")
    prompts = []

    class PageReader(Extractor):
        def ask(self, system, prompt, out_cls, model=None):
            prompts.append(prompt)
            return super().ask(system, prompt, out_cls, model)
    monkeypatch.setattr(llm, "pick_backend", lambda cfg: (PageReader(
        Vacancy(title="Senior Fullstack QA Engineer", company="inDrive", location="Cyprus", work_mode="onsite")), ""))

    [job] = cli.collect_telegram({"tg_channels": {"channels": ["forallqa"]}, "llm": {"workers": 1}}, Preview(),
                                 DB(tmp_path / "jobs.db"), SimpleNamespace(no_llm=False), known=set())

    assert "Location: Cyprus" in prompts[0]
    assert job.location == "Cyprus" and job.description.endswith("Location: Cyprus. Playwright, API, 5+ years.")
