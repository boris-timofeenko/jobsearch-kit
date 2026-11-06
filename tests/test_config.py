"""Setup for other people: profile normalization, presets, the visa-free and remote-only goals, levels, init/check."""
import os
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
    load_cfg()                     # other test files rely on the QA fixture profile being active


def profile(role="backend", **cand_target):
    """The example profile with a role preset, overrides as candidate__x / target__x keyword arguments."""
    p = yaml.safe_load((ROOT / "presets" / "profile.example.yaml").read_text())
    p.update(yaml.safe_load((ROOT / "presets" / "roles" / f"{role}.yaml").read_text()))
    for k, v in cand_target.items():
        sect, key = k.split("__")
        p[sect][key] = v
    p["target"] = config.normalize_target(p)
    return p


def use(p):
    f.configure(p)
    llm.configure(p)
    return p


def job(**kw):
    base = dict(id="t:1", source="t", company="Acme", title="Senior Backend Engineer", url="u",
                location="Berlin, Germany", description="We build APIs in Python and FastAPI. English is our language. " * 6)
    base.update(kw)
    return Job(**base)


# ------------------------------------------------------------------ countries
def test_country_codes_expand_from_the_catalog():
    t = config.normalize_target({"target": {"country": "de", "countries": ["nl", "es", "de"]}})
    assert t["primary"]["code"] == "de" and t["primary"]["name"] == "Germany" and t["primary"]["city"] == "Berlin"
    assert [c["code"] for c in t["countries"]] == ["nl", "es"]          # the primary is not repeated
    assert t["countries"][0]["sponsor_register"] == "ind" and t["countries"][1]["sponsor_register"] == "none"
    assert t["salary_floor_month"] == t["primary"]["salary_floor_month"]


def test_profile_fields_override_the_catalog_and_age_picks_the_floor():
    t = config.normalize_target({"target": {"country": {"code": "de", "salary_floor_month": 4225, "city": "Munich"}}})
    assert (t["primary"]["salary_floor_month"], t["primary"]["city"]) == (4225, "Munich")
    young = config.normalize_target({"candidate": {"birth_year": 2000}, "target": {"country": "nl"}})
    older = config.normalize_target({"candidate": {"birth_year": 1980}, "target": {"country": "nl"}})
    assert young["primary"]["salary_floor_month"] == 4357 and older["primary"]["salary_floor_month"] == 5942


def test_flat_netherlands_profile_still_reads():
    """The single-owner format: the primary country's fields right in target."""
    t = config.normalize_target({"target": {"country": "Netherlands", "location_regex": r"\b(amsterdam)\b",
                                            "track_label": "NL (HSM)", "salary_floor_month": 4357,
                                            "local_language": "nl"}})
    assert t["primary"]["code"] == "nl" and t["primary"]["label"] == "NL (HSM)"
    assert t["primary"]["location_regex"] == r"\b(amsterdam)\b" and t["primary"]["local_languages"] == ["dutch"]
    assert t["salary_floor_month"] == 4357


def test_unknown_country_is_a_clear_error():
    with pytest.raises(config.ConfigError, match="не найдена"):
        config.normalize_target({"target": {"country": "atlantis"}})


def test_remote_only_goal():
    p = profile(target__country="none", target__countries=[])
    assert p["target"]["primary"] is None
    pen = config.default_location_penalty(p["target"])
    assert pen["remote"] == 0 and pen["eu"] > 0
    assert config.default_linkedin_locations(p) == [
        {"name": "European Union", "remote": True, "max_pages": 50, "queries": p["role"]["queries"][:4]}]
    use(p)
    j = f.analyze(job(location="Remote - Europe", remote=True), None, {})
    assert j.track == "remote" and j.verdict == "live"


def test_default_linkedin_locations_follow_the_target():
    p = profile(target__country="de", target__countries=["nl"])
    locs = config.default_linkedin_locations(p)
    assert [l["name"] for l in locs] == ["Germany", "Netherlands", "European Union"]
    assert "queries" not in locs[0] and locs[1]["queries"] == p["role"]["queries"][:4]


def test_deep_merge_replaces_lists():
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 2}
    assert config.deep_merge(base, {"a": {"y": [3]}}) == {"a": {"x": 1, "y": [3]}, "b": 2}


# ------------------------------------------------------------------ presets
ROLES = sorted(p.stem for p in (ROOT / "presets" / "roles").glob("*.yaml"))
TITLES = {
    "qa": (["Senior QA Automation Engineer", "SDET", "Test Automation Engineer"], ["Backend Engineer", "Quality Manager"]),
    "backend": (["Senior Backend Engineer", "Python Developer", "Software Engineer", "Go Developer (Payments)",
                 "Backend-Entwickler (m/w/d)"],
                ["Frontend Engineer", "QA Automation Engineer", "DevOps Engineer", "Sales Engineer"]),
    "frontend": (["Senior Frontend Engineer", "React Developer", "Full Stack Engineer", "Webentwickler (m/w/d)"],
                 ["iOS Developer", "QA Engineer", "Backend Engineer"]),
    "mobile": (["iOS Developer", "Senior Android Engineer", "Flutter Developer", "App-Entwickler iOS (m/w/d)"], ["Mobile QA Engineer", "Unity Developer"]),
    "devops": (["DevOps Engineer", "Site Reliability Engineer", "Senior Platform Engineer"],
               ["IT Support Specialist", "Helpdesk Engineer", "Data Engineer"]),
    "data": (["Senior Data Engineer", "Data Scientist", "Analytics Engineer", "Machine Learning Engineer"],
             ["Data Entry Clerk", "Financial Analyst", "Business Analyst"]),
    "product": (["Senior Product Manager", "Product Owner", "Head of Product"],
                ["Product Designer", "Product Marketing Manager", "Project Manager"]),
}


@pytest.mark.parametrize("role", ROLES)
def test_every_preset_is_complete(role):
    p = profile(role)
    cfg = {"profile": p, "company_files": []}
    assert config.problems(cfg) == []
    use(p)
    good, bad = TITLES[role]
    assert [t for t in good if not f.is_relevant_title(t)] == []
    assert [t for t in bad if f.is_relevant_title(t)] == []
    assert "{" not in llm.SYSTEM.split("Цели кандидата")[0]          # the rubric template is fully filled
    assert p["role"]["name"] in llm.SYSTEM


def test_off_domain_is_the_rescuable_skip_of_the_profile():
    use(profile("backend"))
    assert f.OFF_DOMAIN_REASON == ""
    j = f.analyze(job(title="Senior Backend Engineer, Embedded Platform"), None, {})
    assert not any("железо" in r for r in j.reasons)
    use(profile("qa"))
    j = f.analyze(job(title="QA Engineer Embedded"), None, {})
    assert f.OFF_DOMAIN_REASON in j.reasons and llm.rescuable(j)


# ------------------------------------------------------------------ visa, residence, languages, level
def test_eu_citizen_is_not_stopped_by_sponsorship_wording():
    text = "EU citizens only. We do not offer visa sponsorship. Python and FastAPI. " * 5
    use(profile(candidate__needs_visa=True))
    assert f.analyze(job(description=text), None, {}).verdict == "skip"
    use(profile(candidate__needs_visa=False))
    j = f.analyze(job(description=text), None, {})
    assert j.verdict == "live", j.reasons
    llm.apply_assessment(j, llm.Assessment(fit=7, sponsorship="no", residency_restriction="EU citizens only"))
    assert j.verdict == "live", j.reasons
    assert "Виза в ЕС кандидату не нужна" in llm.SYSTEM


def test_remote_job_for_residents_of_where_the_candidate_lives():
    use(profile(candidate__based_in="Serbia"))
    assert not f.residency_blocks("Candidates must be based in Serbia", "remote", "Remote")
    assert f.residency_blocks("Candidates must be based in Poland", "remote", "Remote")
    assert f.residency_blocks("Serbian citizens based in Serbia only", "remote", "Remote")


def test_known_languages_are_not_a_skip():
    use(profile(candidate__languages=["English", "German"]))
    assert f.other_language_required("Fluent German is required.") == ""
    assert f.other_language_required("Fluent French is required.")
    j = f.analyze(job(title="Senior Backend Entwickler (m/w/d)", description="Python. Fluent German required. " * 8), None, {})
    assert not any(r.startswith(("нужен другой язык", "заголовок")) for r in j.reasons), j.reasons


def test_language_alternatives():
    use(profile(candidate__languages=["English", "Russian"]))
    assert llm.language_gap("fluency in Ukrainian or Russian") == ""
    assert llm.language_gap("Good level of Latvian and English") == "latvian"
    assert llm.language_gap("German / Dutch") == "dutch, german"
    assert llm.language_gap("Fluent in French or English") == ""
    assert llm.language_gap("German (B1, or English)") == ""
    assert llm.language_gap("Strong English and/or German language skills") == ""
    assert llm.language_gap("English and Dutch and/or French") == "dutch, french"
    assert llm.language_gap("German and English, ideally B2 level or above") == "german"
    assert llm.language_gap("Spanish (implied, posting fully in Spanish), B2/C1 English") == "spanish"
    assert llm.language_gap("Dutch or French (native) plus Dutch/French intermediate and English") == "dutch, french"


def test_levels_follow_the_candidate():
    use(profile(candidate__seniority="junior"))
    j = f.analyze(job(title="Junior Backend Developer"), None, {})
    assert j.verdict == "live" and "junior/intern уровень" not in j.reasons
    s = f.analyze(job(title="Senior Backend Engineer"), None, {})
    assert "уровень выше: senior/lead" in s.reasons and s.score < j.score
    use(profile(candidate__seniority="mid"))
    j = f.analyze(job(title="Junior Backend Developer"), None, {})
    assert j.verdict == "live" and "junior в заголовке" in j.reasons
    llm.apply_assessment(j, llm.Assessment(fit=6, seniority="junior"))
    assert j.verdict == "live" and "LLM: junior-level" in j.reasons
    use(profile(candidate__seniority="senior"))
    assert f.analyze(job(title="Junior Backend Developer"), None, {}).verdict == "skip"


def test_assessments_stored_by_the_qa_only_version_still_apply():
    a = llm.Assessment.model_validate_json('{"is_software_qa": false, "ai_qa": "product", "automation_level": "manual", "fit": 3}')
    assert (a.is_target_role, a.ai_role) == (False, "product")
    use(profile("qa"))
    j = job(track="nl", verdict="live", score=60)
    llm.apply_assessment(j, a)
    assert j.verdict == "skip" and "LLM: не та роль" in j.reasons


def test_ai_bonus_only_when_the_profile_asks_for_it():
    use(profile())                                  # example profile: ai_* = 0
    j = job(track="de", verdict="live", score=60)
    llm.apply_assessment(j, llm.Assessment(fit=8, ai_role="ai_first"))
    assert not any("AI-first" in r for r in j.reasons)
    p = profile()
    p["target"]["fit_adjustments"]["ai_first"] = 2
    use(p)
    j = job(track="de", verdict="live", score=60)
    llm.apply_assessment(j, llm.Assessment(fit=8, ai_role="ai_first"))
    assert any("+2 AI-first" in r for r in j.reasons), j.reasons


# ------------------------------------------------------------------ commands
def test_init_and_check(tmp_path, monkeypatch, capsys):
    from jobsearch import cli
    monkeypatch.setattr(config, "MY", tmp_path / "my")
    env = ROOT / ".env"
    had_env = env.exists()
    cli.main(["init", "--role", "data"])
    try:
        prof = yaml.safe_load((tmp_path / "my" / "profile.yaml").read_text())
        assert prof["role"]["name"].startswith("Data Engineer") and prof["candidate"]["name"]
        assert (tmp_path / "my" / "config.yaml").exists() and (tmp_path / "my" / "companies.yaml").exists()
        with pytest.raises(SystemExit):
            cli.main(["init", "--role", "data"])                # never overwrites my/ silently
        monkeypatch.setattr(config, "load", lambda my=None, _l=config.load: _l(tmp_path / "my"))
        cli.main(["check", "--fast"])
        out = capsys.readouterr().out
        assert "Data Engineer" in out and "Netherlands" in out and out.rstrip().endswith("ok")
        cli.main(["check", "--title", "Senior Data Engineer", "Data Entry Clerk"])
        out = capsys.readouterr().out
        assert "✅ Senior Data Engineer" in out and "❌ Data Entry Clerk" in out
    finally:
        if not had_env and env.exists():
            env.unlink()
