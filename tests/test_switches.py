"""The switches block at the top of my/profile.yaml: each short answer changes what is cut, flagged or ranked."""
from pathlib import Path

import pytest
import yaml

from jobsearch import config, filters as f, llm, report
from jobsearch.models import Job

ROOT = Path(__file__).resolve().parent.parent
RATES = config.read_yaml(ROOT / "config.yaml")["currency_rates"]


@pytest.fixture(autouse=True)
def restore_fixture_profile():
    yield
    from jobsearch.cli import load_cfg
    load_cfg()


def use(**switches):
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "backend.yaml").read_text()))
    p["switches"] = {**(p.get("switches") or {}), **switches}
    config.normalize_profile(p, RATES)
    f.configure(p)
    llm.configure(p)
    report.configure(p)
    return p


def job(**kw):
    base = dict(id="s:1", source="t", company="Acme", title="Senior Backend Engineer", url="u",
                location="Berlin, Germany", description="We build APIs in Python and FastAPI. English is our language. " * 6)
    base.update(kw)
    return Job(**base)


def test_example_profile_switches_are_valid():
    p = use()
    assert p["_problems"] == [] and p["prefs"]["other_language"] == "skip"
    assert config.problems({"profile": p, "company_files": []}) == []


def test_goal_and_countries():
    p = use(goal="relocate", countries=["de", "es"])
    assert p["target"]["primary"]["code"] == "de" and [c["code"] for c in p["target"]["countries"]] == ["es"]
    assert not p["prefs"]["remote"]
    assert [l["name"] for l in config.default_linkedin_locations(p)] == ["Germany", "Spain"]
    j = f.analyze(job(location="Remote - Europe", remote=True), None, {})
    assert j.verdict == "other" and "remote, а цель — только переезд" in j.reasons
    p = use(goal="remote", countries=["de"])
    assert p["target"]["primary"] is None and p["target"]["countries"] == []
    assert any("countries не используется" in n for n in p["_notes"])


def test_relocation_goal_drops_remote_only_boards(tmp_path):
    (tmp_path / "profile.yaml").write_text((ROOT / "presets" / "profile.example.yaml").read_text().replace(
        "  goal: both", "  goal: relocate").replace("# ROLE: сюда вставляется пресет роли\n",
                                                     (ROOT / "presets" / "roles" / "qa.yaml").read_text()))
    cfg = config.load(tmp_path)
    assert "remotive" not in cfg["aggregators"] and "arbeitnow" in cfg["aggregators"]


def test_offices_off_and_the_old_eu_offices_switch():
    def madrid_office(**switches):
        use(**switches)
        j = f.analyze(job(location="Madrid, Spain"), None, {})
        return j.track, j.verdict
    for off in (dict(offices="none"), dict(offices=[]), dict(offices=None, eu_offices=False)):
        assert madrid_office(**off) == ("other", "other"), off
    for on in (dict(offices=["eu"]), dict(offices=None, eu_offices=True)):
        assert madrid_office(**on) == ("region", "live"), on


def test_other_language_modes():
    text = "Python and FastAPI. Fluent German is required for this role. " * 6
    use(other_language="skip")
    assert f.analyze(job(description=text), None, {}).verdict == "skip"
    use(other_language="flag")
    j = f.analyze(job(description=text), None, {})
    assert j.verdict == "live" and any(r.startswith("язык: нужен другой язык") for r in j.reasons)
    llm.apply_assessment(j, llm.Assessment(fit=7, language_requirement="German C1"))
    assert j.verdict == "live" and any(r.startswith("LLM: язык — нужен german") for r in j.reasons)
    dutch = "Wij zoeken een ontwikkelaar voor ons team. Je werkt met Python en je hebt ervaring met API's en de cloud. " * 4
    assert f.analyze(job(description=dutch, location="Utrecht, Netherlands"), None, {}).verdict == "skip"
    use(other_language="any")
    assert f.analyze(job(description=dutch, location="Utrecht, Netherlands"), None, {}).verdict == "live"


def test_salary_min_modes():
    low = "Python, FastAPI. Salary €3,000 per month. " * 6
    use(salary_min="visa", visa="needed")                       # Germany's Blue Card floor 3828
    assert f.analyze(job(description=low), None, {}).verdict == "skip"
    assert f.analyze(job(description=low, location="Remote - Europe", remote=True), None, {}).verdict == "live"
    use(salary_min=5000)
    j = f.analyze(job(description=low, location="Remote - Europe", remote=True), None, {})
    assert j.verdict == "skip" and any("свой минимум" in r for r in j.reasons)
    use(salary_min=0)
    assert f.analyze(job(description=low), None, {}).verdict == "live"
    p = use(salary_min="visa", visa="not_needed")               # no visa: the visa floor means nothing
    assert p["prefs"]["salary_min"] == 0 and f.analyze(job(description=low), None, {}).verdict == "live"


def test_contract_modes():
    hourly = "Python backend, freelance B2B. Rate €60 per hour. " * 6
    use(contract="penalize")
    assert f.analyze(job(description=hourly), None, {}).verdict == "skip"
    use(contract="ok")
    j = f.analyze(job(description=hourly), None, {})
    assert j.verdict == "live", j.reasons
    llm.apply_assessment(j, llm.Assessment(fit=7, employment="contractor", pay_basis="hourly"))
    assert j.verdict == "live" and not any("контракт, не найм" in r for r in j.reasons)
    use(contract="skip")
    j = f.analyze(job(description="Python and FastAPI, 12-month contract. " * 6, location="Remote - EU", remote=True),
                  None, {})
    assert j.verdict == "skip" and j.reasons[0].startswith(f.SETTING)


def test_outsourcing_and_agencies():
    use(outsourcing="skip", agencies="ok")
    j = job(track="de", verdict="live", score=60, reasons=[])
    llm.apply_assessment(j, llm.Assessment(fit=8, employer_type="consultancy"))
    assert j.verdict == "skip" and "отсев по настройке: аутсорс/аутстафф" in j.reasons
    j = job(track="de", verdict="live", score=60, reasons=[])
    llm.apply_assessment(j, llm.Assessment(fit=8, employer_type="recruiter", is_agency=True))
    assert j.verdict == "live" and not any("рекрутер" in r for r in j.reasons if r.startswith("fit:"))
    use(agencies="skip")
    j = f.analyze(job(description="We are recruiting on behalf of our client, a fintech. Python. " * 6), None, {})
    assert j.verdict == "skip" and "отсев по настройке: агентство/рекрутер" in j.reasons


def test_public_sector_and_ai():
    text = "Python backend for the Ministry of Defence, security clearance required. " * 6
    use(public_sector="skip")
    assert f.analyze(job(description=text), None, {}).verdict == "skip"
    use(public_sector="ok")
    assert f.analyze(job(description=text), None, {}).verdict == "live"
    use(ai="prefer")
    j = job(track="de", verdict="live", score=60, reasons=[])
    llm.apply_assessment(j, llm.Assessment(fit=7, ai_role="product"))
    assert any("+2 AI в продукте" in r for r in j.reasons), j.reasons


def test_bad_values_and_clashes_are_reported():
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "backend.yaml").read_text()))
    p["switches"]["contract"] = "maybe"
    p["candidate"]["languages"] = ["English"]
    config.normalize_profile(p)
    assert any("switches.contract" in x for x in p["_problems"])
    assert any("switches.languages перекрывает languages" in n for n in p["_notes"])


def test_cv_formats(tmp_path):
    for name, fmt in (("cv.tex", "latex"), ("cv.docx", "docx"), ("cv.md", "markdown"), ("cv.pdf", "text"),
                      ("cv.odt", "unknown")):
        assert config.cv_source({"profile": {"_cv": str(tmp_path / name)}})[1] == fmt
    assert config.cv_source({"profile": {"_cv": "none"}}) == (None, "none")
    assert config.cv_source({"profile": {}, "cv": {"tex": "my/cv.tex"}})[1] == "latex"     # older configs
    old = config.cv_source({"profile": {}, "cv": {"source": "my/cv.tex", "tex": "my/resume.tex"}})[0]
    assert old.name == "resume.tex"                     # a hand-set cv.tex beats the shared default source


def test_init_wizard_writes_answers_into_switches(tmp_path, monkeypatch):
    from jobsearch import cli
    cv = tmp_path / "Anna CV.docx"
    cv.write_bytes(b"PK fake docx")
    answers = iter(["data", "relocate", "de, es", "none", "not_needed", "Spain", "English, Spanish, German", "flag", "",
                    "", "4500", "", "ok", "", "skip", "", "prefer", str(cv)])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(config, "MY", tmp_path / "my")
    env = ROOT / ".env"
    had_env = env.exists()
    try:
        cli.main(["init", "--ask"])
    finally:
        if not had_env and env.exists():
            env.unlink()
    text = (tmp_path / "my" / "profile.yaml").read_text()
    p = yaml.safe_load(text)
    sw = p["switches"]
    assert (sw["goal"], sw["countries"], sw["offices"], sw["visa"]) == ("relocate", ["de", "es"], [], "not_needed")
    assert (sw["languages"], sw["other_language"], sw["level"], sw["salary_min"]) == (
        ["English", "Spanish", "German"], "flag", "senior", 4500)
    assert (sw["contract"], sw["agencies"], sw["ai"], sw["cv"]) == ("ok", "skip", "prefer", "my/cv.docx")
    assert (tmp_path / "my" / "cv.docx").read_bytes() == b"PK fake docx"
    assert "# relocate — только переезд" in text                       # comments survive
    assert p["role"]["name"].startswith("Data Engineer")
    config.normalize_profile(p)
    assert p["_problems"] == [] and p["prefs"]["salary_min"] == 4500 and not p["prefs"]["remote"]


def test_country_with_own_floor_inside_switches():
    p = use(countries=[{"code": "de", "salary_floor_month": 4225}, "nl"])
    assert p["target"]["primary"]["salary_floor_month"] == 4225 and p["target"]["countries"][0]["code"] == "nl"


def test_eu_citizen_gets_no_ind_register_flags():
    use(visa="not_needed", countries=["nl"])
    assert not any(c["sponsor"] for c in f.COUNTRIES)
    j = f.analyze(job(location="Amsterdam, Netherlands"), None, {})
    assert not any("реестре IND" in r for r in j.reasons)


def test_time_zone_is_not_an_address():
    use(based_in="Poland")
    text = "Remote role, React and TypeScript. Candidates must be located in or able to work within CEST time zone. " * 4
    j = f.analyze(job(location="Remote - Europe", remote=True, description=text), None, {})
    assert j.verdict == "live" and any(r.startswith("просят работать в часовом поясе") for r in j.reasons)
    use(visa="not_needed", based_in="Poland")
    j = f.analyze(job(location="Remote - Europe", remote=True,
                      description="Remote role, React. Candidates must be based in Portugal for tax reasons. " * 4), None, {})
    assert j.verdict == "skip" and j.reasons[0].startswith("только для живущих в другой стране")


def test_remote_search_in_the_home_country():
    p = use(goal="both", based_in="Poland")
    locs = config.default_linkedin_locations(p)
    assert locs[-1] == {"name": "Poland", "remote": True, "max_pages": 30, "queries": p["role"]["queries"][:4]}
    assert "Poland" not in [l["name"] for l in config.default_linkedin_locations(use(goal="relocate", based_in="Poland"))]
    assert [l["name"] for l in config.default_linkedin_locations(use(goal="both", based_in="Georgia"))][-1] == "European Union"


def test_remote_only_goal_hides_offices_everywhere():
    p = use(goal="remote", offices=["eu"])
    assert p["prefs"]["offices"] == [] and any("offices не используется" in n for n in p["_notes"])
    assert f.analyze(job(location="Madrid, Spain"), None, {}).verdict == "other"


def test_residency_wording_for_where_the_candidate_lives():
    use(based_in="Poland")
    for text in ("Only for candidates residing in Poland.", "You must currently live in Poland.",
                 "Open to residents of Poland only."):
        j = f.analyze(job(location="Remote - Europe", remote=True, description=("Python, FastAPI. " + text + " ") * 5),
                      None, {})
        assert j.verdict == "live", (text, j.reasons)
        assert any(r.startswith("ты живёшь в Poland") for r in j.reasons)
    j = f.analyze(job(location="Remote - Europe", remote=True,
                      description="Python. Only for candidates residing in Portugal. " * 5), None, {})
    assert j.verdict == "skip"


def test_eu_citizen_and_an_eu_only_quote_from_the_model():
    use(visa="not_needed", based_in="Spain")
    j = job(track="remote", verdict="live", score=60, reasons=[], location="Remote - EU")
    llm.apply_assessment(j, llm.Assessment(fit=7, residency_restriction="EU citizens only"))
    assert j.verdict == "live", j.reasons
    j = job(track="remote", verdict="live", score=60, reasons=[], location="Remote - EU")
    llm.apply_assessment(j, llm.Assessment(fit=7, residency_restriction="Candidates must be based in Germany"))
    assert j.verdict == "skip"


def test_hand_set_numbers_win_over_the_ai_switch_and_penalties_always_apply():
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "backend.yaml").read_text()))
    p["switches"]["ai"] = "neutral"
    p["target"]["fit_adjustments"]["ai_first"] = 3
    config.normalize_profile(p)
    llm.configure(p)
    assert llm.FIT_ADJ["ai_first"] == 3
    use(ai="avoid")
    j = job(track="de", verdict="live", score=60, reasons=[])
    llm.apply_assessment(j, llm.Assessment(fit=4, ai_role="ai_first"))       # weak match, still penalised
    assert any("-2 AI-first" in r for r in j.reasons), j.reasons


def test_empty_title_lists_mean_empty():
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "devops.yaml").read_text()))
    p["role"]["title_exclude"] = []
    p["role"]["stack"] = {}
    config.normalize_profile(p)
    f.configure(p)
    assert f.is_relevant_title("Senior DevOps Engineer")        # the QA exclusions (devops, sre…) are gone
    assert f.STACK == []


def test_clashes_with_goal_and_offices_are_noted():
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "backend.yaml").read_text()))
    p["switches"].update(goal="relocate", offices="none")
    p["target"].update(remote=True, eu_offices=True)
    config.normalize_profile(p)
    assert any("switches.goal перекрывает remote" in n for n in p["_notes"])
    assert any("switches.offices перекрывает offices: ['eu'] → []" in n for n in p["_notes"])


def test_companies_example_takes_appended_lines(tmp_path):
    f_ = tmp_path / "companies.yaml"
    f_.write_text((ROOT / "presets" / "companies.example.yaml").read_text()
                  + '- {name: "Mollie", ats: ashby, slug: mollie}   # 48 jobs\n')
    assert config.load_companies([str(f_)]) == [{"name": "Mollie", "ats": "ashby", "slug": "mollie"}]


# ------------------------------------------------------------------ countries outside the EU
RUSSIAN_POSTING = "Ищем Python-разработчика в команду платежей: сервисы на FastAPI, PostgreSQL и Kafka. " * 4


def test_friend_moving_within_russia_reads_russian_postings_in_roubles():
    p = use(countries=["ru"], visa="not_needed", based_in="Russia", languages=["Russian", "English"],
            salary_currency="RUB", salary_min=200000, offices=None)
    moscow = f.analyze(job(title="Python-разработчик", location="Москва, Россия", description=RUSSIAN_POSTING,
                           salary_text="от 250 000 до 300 000 ₽"), None, {})
    kazan = f.analyze(job(title="Python-разработчик", location="Казань, Россия", description=RUSSIAN_POSTING,
                          salary_text="до 150 000 ₽"), None, {})
    assert (moscow.track, moscow.verdict, moscow.lang) == ("ru", "live", "ru"), moscow.reasons
    assert kazan.reasons[0] == "зарплата ~150 000 ₽/мес < порога 200 000 ₽ (свой минимум)"
    assert f.analyze(job(location="Madrid, Spain"), None, {}).track == "other"    # by default no EU offices for Russia
    assert config.country_aggregators(p) == ["habr"]
    assert "Рабочая виза в целевых странах кандидату не нужна" in llm.SYSTEM and "ЕС" not in llm.GOAL


def test_russian_text_is_unreadable_without_russian():
    use(languages=["English"])
    j = f.analyze(job(title="Python-разработчик", description=RUSSIAN_POSTING), None, {})
    assert j.verdict == "skip" and "текст на русском" in j.reasons


def test_offices_in_other_regions_and_countries():
    use(countries=["rs"], offices=["cis", "ae"])
    track = lambda loc: f.analyze(job(location=loc), None, {}).track
    assert [track(x) for x in ("Белград", "Tbilisi, Georgia", "Dubai, United Arab Emirates", "Berlin, Germany")] \
        == ["rs", "region", "region", "other"]
    assert report.TRACK_RU["region"] == "🌍 Офис или гибрид: СНГ и Кавказ, ОАЭ"


def test_remote_postings_follow_where_the_candidate_lives():
    remote = lambda loc: f.analyze(job(location=loc, remote=True), None, {}).track
    p = use(goal="remote", based_in="United States")
    assert (remote("Remote - US"), remote("Remote - Europe")) == ("remote", "other")
    assert [x["name"] for x in config.default_linkedin_locations(p)] == ["United States"]
    use(goal="remote", based_in="Georgia")
    assert (remote("Remote - US"), remote("Remote, EMEA"), remote("Remote, Москва")) == ("other", "remote", "remote")


def test_living_in_the_job_city_outside_the_eu_is_not_a_blocker():
    use(countries=["ae"])
    assert not f.residency_blocks("Candidates must be based in Dubai", "ae", "Dubai, United Arab Emirates")
    assert f.residency_blocks("Candidates must be based in India", "ae", "Dubai, United Arab Emirates")
