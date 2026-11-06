import shutil

import pytest

from jobsearch import cvgen as c

# made-up CV with the same hooks as the real one (the real tex is personal and not in git)
TEX = r"""\documentclass{article}
\newcommand{\cvheadline}{Senior SDET / Test Automation Engineer}
\newcommand{\cvlocation}{Located in Belgrade, Serbia. Open to relocation.}
\newcommand{\cvworkauth}{Non-EU national.}
\newcommand{\cvkeywords}{SDET, Playwright,
   Python}
\newcommand{\cvsection}[1]{\section*{#1}}
\newcommand{\skillrow}[2]{\textbf{#1} #2\par}
\newcommand{\role}[3]{\textbf{#1} #2 #3\par}
\newcommand{\ca}{\ensuremath{\approx}}
\newenvironment{duties}{\begin{itemize}}{\end{itemize}}
\begin{document}
{\large \cvheadline}\par
\cvlocation\par \cvworkauth
\cvsection{SUMMARY}
% comment line
Senior SDET with 8 years in QA. Currently QA Tech Lead serving \ca{}100k users. Previously, I worked 4 years in travel.

\cvsection{SKILLS}
\skillrow{Test Automation}{Playwright (TypeScript/JavaScript), REST API testing, PyTest}
\skillrow{Engineering}{Python, Docker}
\cvsection{EXPERIENCE}
\role{QA Tech Lead}{SOLmate}{2025 -- Present}
\begin{duties}
  \item Developed end-to-end automation from 0 to \ca{}450 scenarios. This covers 65\% of regression plan.  % cv:pin
  \item Organized test plans into Kiwi TCMS.
  \item Cut the flaky rate from 20\% to 5\%.
  \item Ran release sign-off for the mobile app.
\end{duties}
\role{Engineer}{Typeable}{2021 -- 2025}
\begin{duties}
  \item Grew coverage from 80 to 550 cases in Selenium/PyTest and Playwright.  % cv:pin
  \item Built a suite in Playwright and JavaScript.
\end{duties}
\end{document}
"""

BANK = {
    "headlines": ["Senior SDET / Test Automation Engineer", "Senior QA Automation Engineer", "QA Lead / Senior SDET"],
    "skills": {"extra": {"Test Automation": ["WireMock"], "Engineering": ["CI/CD"]},
               "aliases": {"REST API testing": ["API testing"]}},
    "synonyms": [["end-to-end", "E2E"], ["cut", "reduced"]],
    "relocation": {
        "default": {"location": "Located in Belgrade.", "workauth": "Non-EU national."},
        "nl": {"location": "Ready to relocate to the Netherlands.", "workauth": "Eligible for HSM."},
        "eu": {"location": "Ready to relocate {to_country}.", "workauth": "Eligible for the EU Blue Card."},
        "countries": {"Ireland": {"workauth": "Eligible for the Critical Skills Employment Permit."}},
    },
}


def plan(**kw):
    base = dict(headline="Senior SDET / Test Automation Engineer", summary=[], skills=[], roles=[])
    return c.CvPlan(**{**base, **kw})


def test_parse():
    cv = c.parse(TEX)
    assert cv.macro("cvheadline") == "Senior SDET / Test Automation Engineer"
    assert "Python" in cv.macro("cvkeywords")
    assert len(cv.sentences) == 3 and cv.sentences[1].startswith("Currently")
    assert [r.label for r in cv.skills] == ["Test Automation", "Engineering"]
    assert cv.skills[0].items == ["Playwright (TypeScript/JavaScript)", "REST API testing", "PyTest"]
    assert [r.company for r in cv.roles] == ["SOLmate", "Typeable"]
    assert [b.pinned for b in cv.roles[0].bullets] == [True, False, False, False]
    assert "cv:pin" not in cv.roles[0].bullets[0].tex and r"65\%" in cv.roles[0].bullets[0].tex


def test_empty_plan_keeps_everything():
    cv = c.parse(TEX)
    out = c.render(cv, c.apply_plan(cv, BANK, plan()))
    for s in cv.sentences:
        assert s in out
    for b in cv.roles[0].bullets + cv.roles[1].bullets:
        assert b.tex in out
    assert out.index("Currently") < out.index("Previously")


def test_plain_tex_roundtrip():
    tex = r"from 0 to \ca{}450 scenarios, 65\% of plan, bdd\_widget\_test, 5--10"
    assert c.to_tex(c.to_plain(tex)) == tex
    with pytest.raises(ValueError):
        c.to_tex(r"\input{/etc/passwd}")


def test_small_edits():
    orig = "Grew coverage from ≈80 to ≈550 cases in Selenium/PyTest and Playwright."
    assert c.check_edit(orig, "Grew coverage from ≈80 to ≈550 cases in Playwright and Selenium/PyTest.") == ""
    assert "цифры" in c.check_edit(orig, "Grew coverage from ≈80 to ≈600 cases in Selenium/PyTest and Playwright.")
    assert "новые слова" in c.check_edit(orig, "Grew coverage from ≈80 to ≈550 cases in Cypress and Playwright.")
    assert "новые слова" in c.check_edit(orig, "Spearheaded coverage from ≈80 to ≈550 cases in Selenium/PyTest and Playwright.")
    e2e = "Developed end-to-end automation for the app."
    assert "новые слова" in c.check_edit(e2e, "Developed E2E automation for the app.", synonyms=[["cut", "reduced"]])
    assert c.check_edit(e2e, "Developed E2E automation for the app.", synonyms=[["end-to-end", "E2E"]]) == ""
    assert c.check_edit("Built a suite in Playwright and JavaScript for the new product.",
                        "Playwright.") != ""


def test_edit_budget_and_rejections():
    cv = c.parse(TEX)
    p = plan(roles=[c.RolePlan(role="r2", bullets=[
        c.Piece(id="r2.b1", text="Grew coverage from 80 to 550 cases in Playwright and Selenium/PyTest."),
        c.Piece(id="r2.b2", text="Built a suite in Cypress and JavaScript.")])])
    t = c.apply_plan(cv, BANK, p, max_edits=5)
    out = c.render(cv, t)
    assert "in Playwright and Selenium/PyTest." in out and "Cypress" not in out
    assert len(t.edits) == 1 and len(t.rejected) == 1
    t0 = c.apply_plan(cv, BANK, p, max_edits=0)
    assert not t0.edits and "лимит" in t0.rejected[0][1]


def test_skills():
    cv = c.parse(TEX)
    p = plan(skills=[c.SkillsRowPlan(row="Engineering", items=["Docker", "CI/CD", "Kubernetes"]),
                     c.SkillsRowPlan(row="Test Automation", items=["API testing", "PyTest"])])
    t = c.apply_plan(cv, BANK, p)
    rows = [(r.label, items) for r, items in t.skills]
    assert rows[0] == ("Engineering", ["Docker", "CI/CD", "Python"])          # extra added, original kept
    assert rows[1] == ("Test Automation", ["API testing", "PyTest", "Playwright (TypeScript/JavaScript)"])
    assert t.added_skills == ["CI/CD"] and t.renamed_skills == [("REST API testing", "API testing")]
    assert any("Kubernetes" in why for _, why in t.rejected)                  # not in the CV, not in the bank
    out = c.render(cv, t)
    assert out.index(r"\skillrow{Engineering}") < out.index(r"\skillrow{Test Automation}")


def test_bullets_hiding_rules():
    cv = c.parse(TEX)
    p = plan(roles=[c.RolePlan(role="r1", bullets=[c.Piece(id="r1.b4")]),   # hides b1 (pinned), b2, b3
                    c.RolePlan(role="r2", bullets=[]),
                    c.RolePlan(role="r9", bullets=[c.Piece(id="r1.b2")])])
    t = c.apply_plan(cv, BANK, p)
    ids = [b.id for b in t.roles["r1"]]
    assert ids[0] == "r1.b4" and "r1.b1" in ids                              # pinned comes back
    assert len([h for h in t.hidden if h[0] == "SOLmate"]) == 2                # at most two hidden per role
    assert [b.id for b in t.roles["r2"]] == ["r2.b1", "r2.b2"]                 # empty list = as is
    assert c.trim_one(cv, t) and len(t.trimmed) == 1
    assert all(b.pinned or b.id != t.trimmed[0] for b in t.roles["r1"])


def test_summary_order():
    cv = c.parse(TEX)
    t = c.apply_plan(cv, BANK, plan(summary=[c.Piece(id="s3"), c.Piece(id="s1")]))
    assert t.sentences[0].startswith("Senior SDET") and t.sentences[1].startswith("Previously")
    assert t.dropped_sentences == [c.to_plain(cv.sentences[1])]


def test_headline_choice():
    opts = BANK["headlines"]
    assert c.choose_headline("Senior QA Automation Engineer", opts, "x") == "Senior QA Automation Engineer"
    assert c.choose_headline("senior qa automation engineer ", opts, "x") == "Senior QA Automation Engineer"
    assert c.choose_headline("Head of Quality", opts, "Senior SDET / Test Automation Engineer") == \
        "Senior SDET / Test Automation Engineer"


def test_keywords():
    text = "Playwright (TypeScript/JavaScript), GitHub Actions, CI/CD pipelines"
    assert c.has_keyword("CI/CD", text) and c.has_keyword("typescript", text)
    assert not c.has_keyword("Java", text) and not c.has_keyword("Script", text)
    assert c.has_keyword("JavaScript/TypeScript", text) and not c.has_keyword("Java/Kotlin", text)


def test_extras_only_when_the_vacancy_asks():
    vw = set(c.words("We manage test cases in TestRail and work in Scrum teams; CI pipelines."))
    assert c.mentioned("Test case management (Kiwi TCMS)", vw)
    assert c.mentioned("Agile/Scrum", vw)
    assert not c.mentioned("WireMock", vw) and not c.mentioned("GCP", vw)
    cv = c.parse(TEX)
    p = plan(skills=[c.SkillsRowPlan(row="Test Automation", items=["WireMock"]),
                     c.SkillsRowPlan(row="Engineering", items=["CI/CD"])])
    t = c.apply_plan(cv, BANK, p, vacancy_text="Build CI/CD pipelines in GitHub Actions")
    assert t.added_skills == ["CI/CD"] and any("не упоминает" in why for _, why in t.rejected)


def test_country_and_relocation():
    assert c.country_of("Konin, Wielkopolskie, Poland") == "Poland"
    assert c.country_of("Łódź, Łódzkie, Poland") == "Poland"
    assert c.country_of("Gdansk Metropolitan Area") == "Poland"
    assert c.country_of("Greater Aarhus Area") == "Denmark"
    assert c.country_of("Remote: Czechia") == "Czechia"
    assert c.country_of("Werken op afstand") is None
    assert c.relocation_lines(BANK, "nl", "Amsterdam", "Netherlands")[:2] == \
        ("Ready to relocate to the Netherlands.", "Eligible for HSM.")
    loc, auth, _ = c.relocation_lines(BANK, "eu", "Madrid, Community of Madrid, Spain")
    assert loc == "Ready to relocate to Spain." and auth == "Eligible for the EU Blue Card."
    assert c.relocation_lines(BANK, "eu", "Dublin, County Dublin, Ireland")[1].startswith("Eligible for the Critical")
    assert c.relocation_lines(BANK, "eu", "Europe")[0] == "Ready to relocate within the EU."
    assert c.relocation_lines(BANK, "other", "New York")[:2] == ("Located in Belgrade.", "Non-EU national.")


def test_report_diff():
    d = c.diff_html("in Selenium/PyTest and Playwright.", "in Playwright and Selenium/PyTest.")
    assert "<s>" in d and "<b>" in d


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="no pdflatex")
def test_compile(tmp_path):
    cv = c.parse(TEX)
    t = c.apply_plan(cv, BANK, plan(headline="Senior QA Automation Engineer"))
    pdf, pages = c.compile_pdf(c.render(cv, t, "Ready to relocate to Spain.", "Eligible.", "SDET, Kiwi TCMS"), tmp_path)
    assert pdf.exists() and pages == 1
