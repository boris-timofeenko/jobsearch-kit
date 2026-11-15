"""The switches block at the top of my/profile.yaml: each short answer changes what is cut, flagged or ranked."""
from pathlib import Path

import pytest
import yaml

from jobsearch import config, filters as f, llm
from jobsearch.models import Job

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def restore_fixture_profile():
    yield
    from jobsearch.cli import load_cfg
    load_cfg()


def use(**switches):
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / "backend.yaml").read_text()))
    p["switches"] = {**(p.get("switches") or {}), **switches}
    config.normalize_profile(p)
    f.configure(p)
    llm.configure(p)
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


def test_eu_offices_off():
    use(eu_offices=False)
    j = f.analyze(job(location="Madrid, Spain"), None, {})
    assert j.track == "eu" and j.verdict == "other"
    use(eu_offices=True)
    assert f.analyze(job(location="Madrid, Spain"), None, {}).verdict == "live"


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
    answers = iter(["data", "relocate", "de, es", "n", "not_needed", "Spain", "English, Spanish, German", "flag", "",
                    "4500", "", "ok", "", "skip", "", "prefer", str(cv)])
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
    assert (sw["goal"], sw["countries"], sw["eu_offices"], sw["visa"]) == ("relocate", ["de", "es"], False, "not_needed")
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
