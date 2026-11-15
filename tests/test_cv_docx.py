"""CV tailoring on a .docx: structure found by headings, edits written back without touching anything else."""
import pytest
from docx import Document

from jobsearch import cv_docx, cvgen

BANK = {"headlines": ["Senior Backend Engineer", "Senior Python Engineer"],
        "relocation": {"default": {"location": "Located in Tbilisi, Georgia.", "workauth": "Need a work permit."},
                       "de": {"location": "Relocating to Germany.", "workauth": "Eligible for the EU Blue Card."}},
        "skills": {"extra": {"Backend": ["gRPC"]}},
        "pin": ["payout service"]}


def make_docx(path):
    d = Document()
    d.add_paragraph("Anna Example", style="Title")
    d.add_paragraph("Senior Backend Engineer")
    d.add_paragraph("Located in Tbilisi, Georgia.")
    d.add_paragraph("Need a work permit.")
    d.add_paragraph("anna@example.com · linkedin.com/in/anna")
    d.add_heading("Summary", level=1)
    d.add_paragraph("Backend engineer with 6 years in fintech. Build Python services on FastAPI and Kafka. "
                    "Lead a team of two developers.")
    d.add_heading("Skills", level=1)
    for label, items in (("Languages", "Python, SQL, Bash"), ("Backend", "FastAPI, Django, Celery, REST")):
        p = d.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        p.add_run(items)
    d.add_heading("Experience", level=1)
    p = d.add_paragraph()
    p.add_run("Senior Backend Engineer — Acme Payments").bold = True
    d.add_paragraph("Jan 2022 – Present")
    d.add_paragraph("Rebuilt the payout service on FastAPI and Kafka, p99 from 900 to 120 ms.", style="List Bullet")
    d.add_paragraph("Lead two backend developers: reviews, planning, onboarding.", style="List Bullet")
    d.add_paragraph("Moved CI from Jenkins to GitHub Actions, builds from 25 to 8 minutes.", style="List Bullet")
    p = d.add_paragraph()
    p.add_run("Backend Developer — Travel Soft").bold = True
    p = d.add_paragraph(style="List Bullet")
    p.add_run("Integrated 12 airline APIs through a ")
    p.add_run("common").bold = True
    p.add_run(" adapter layer.")
    d.add_paragraph("Wrote the billing reconciliation job.", style="List Bullet")
    d.add_heading("Education", level=1)
    d.add_paragraph("BSc Computer Science, Al-Farabi University, 2015 – 2019")
    d.save(path)
    return path


@pytest.fixture
def docx_cv(tmp_path):
    path = make_docx(tmp_path / "cv.docx")
    return path, cv_docx.parse(path, BANK)


def test_structure_is_found(docx_cv):
    _, cv = docx_cv
    assert cv.headline == "Senior Backend Engineer" and cv.location_idx is not None and cv.workauth_idx is not None
    assert len(cv.sentences) == 3 and cv.sentences[0].startswith("Backend engineer")
    assert [(r.label, r.items) for r in cv.skills] == [("Languages", ["Python", "SQL", "Bash"]),
                                                       ("Backend", ["FastAPI", "Django", "Celery", "REST"])]
    assert [(r.title, len(r.bullets)) for r in cv.roles] == [("Senior Backend Engineer — Acme Payments", 3),
                                                             ("Backend Developer — Travel Soft", 2)]
    assert cv.roles[0].bullets[0].pinned and not cv.roles[0].bullets[1].pinned
    assert "Education" not in " ".join(b.tex for r in cv.roles for b in r.bullets)       # the section ended
    assert "роль r1: Senior Backend Engineer — Acme Payments (Jan 2022 – Present), буллетов 3" in cv_docx.inspect(cv)


def test_plan_is_written_back_and_formatting_kept(docx_cv, tmp_path):
    path, cv = docx_cv
    P = cvgen.Piece
    plan = cvgen.CvPlan(
        headline="Senior Python Engineer",
        summary=[P(id="s1"), P(id="s2", text="Build Python services on FastAPI and Kafka.")],     # s3 dropped
        skills=[cvgen.SkillsRowPlan(row="Backend", items=["REST", "gRPC", "FastAPI"]),
                cvgen.SkillsRowPlan(row="Languages", items=["SQL", "Python"])],
        roles=[cvgen.RolePlan(role="r1", bullets=[P(id="r1.b3"), P(id="r1.b1")]),                  # b2 hidden
               cvgen.RolePlan(role="r2", bullets=[P(id="r2.b1", text="Integrated 12 airline APIs via a common adapter "
                                                                     "layer.")])])
    t = cvgen.apply_plan(cv, BANK, plan, vacancy_text="gRPC REST FastAPI Python services")
    out = cv_docx.render(path, cv, t, "Relocating to Germany.", "Eligible for the EU Blue Card.", "Python, gRPC")
    res = tmp_path / "out.docx"
    out.doc.save(res)
    text = [p.text for p in Document(res).paragraphs]
    assert "Senior Python Engineer" in text and "Relocating to Germany." in text
    assert "Backend engineer with 6 years in fintech. Build Python services on FastAPI and Kafka." in text
    assert "Languages: SQL, Python, Bash" in text and "Backend: REST, gRPC, FastAPI, Django, Celery" in text
    i = text.index("Jan 2022 – Present")
    assert text[i + 1].startswith("Moved CI") and text[i + 2].startswith("Rebuilt the payout")
    assert not any(x.startswith("Lead two backend") for x in text)
    # the bullet with a bold word inside keeps its text: edit declined, reported
    assert "Integrated 12 airline APIs through a common adapter layer." in text
    assert any("разное форматирование" in why for _, why in out.declined)
    # the label run stays bold, the items are one plain run after it
    row = next(p for p in Document(res).paragraphs if p.text.startswith("Backend:"))
    assert row.runs[0].bold and row.runs[0].text == "Backend: " and not row.runs[1].bold
    assert Document(res).core_properties.keywords == "Python, gRPC"
    # list style survives the move
    moved = next(p for p in Document(res).paragraphs if p.text.startswith("Moved CI"))
    assert moved.style.name == "List Bullet"


def test_untouched_plan_changes_nothing(docx_cv, tmp_path):
    path, cv = docx_cv
    plan = cvgen.CvPlan(headline="Senior Backend Engineer", summary=[], skills=[], roles=[])
    t = cvgen.apply_plan(cv, BANK, plan)
    out = cv_docx.render(path, cv, t)
    res = tmp_path / "same.docx"
    out.doc.save(res)
    assert [p.text for p in Document(res).paragraphs] == [p.text for p in Document(path).paragraphs]
    assert out.declined == []


def test_manual_bullets_and_hints(tmp_path):
    d = Document()
    d.add_paragraph("PROFILE")
    d.add_paragraph("QA engineer. Seven years in payments.")
    d.add_paragraph("WHAT I DO")
    d.add_paragraph("Acme · 2020 – now")
    d.add_paragraph("• Built the test framework.")
    d.add_paragraph("• Run release sign-off.")
    path = tmp_path / "plain.docx"
    d.save(path)
    cv = cv_docx.parse(path, {"docx": {"experience": "what i do"}})
    assert len(cv.sentences) == 2 and len(cv.roles) == 1 and cv.roles[0].bullets[0].tex == "Built the test framework."
    plan = cvgen.CvPlan(headline="", summary=[], skills=[],
                        roles=[cvgen.RolePlan(role="r1", bullets=[cvgen.Piece(id="r1.b2"), cvgen.Piece(id="r1.b1")])])
    out = cv_docx.render(path, cv, cvgen.apply_plan(cv, {}, plan))
    out.doc.save(tmp_path / "o.docx")
    assert [p.text for p in Document(tmp_path / "o.docx").paragraphs][-2:] == ["• Run release sign-off.",
                                                                               "• Built the test framework."]


def test_autofill_from_docx(docx_cv):
    from jobsearch import autofill
    path, _ = docx_cv
    p = autofill.parse_docx(path, BANK)
    assert (p["name"], p["email"], p["linkedin"]) == ("Anna Example", "anna@example.com", "https://www.linkedin.com/in/anna")
    assert p["location"] == "Tbilisi, Georgia" and p["headline"] == "Senior Backend Engineer"
    assert [(e["title"], e["company"]) for e in p["experience"]] == [("Senior Backend Engineer", "Acme Payments"),
                                                                     ("Backend Developer", "Travel Soft")]
    assert p["experience"][0]["start"] == {"year": 2022, "month": 1} and p["experience"][0]["current"]
    prof = autofill.build("", BANK, "", parsed=p)
    assert prof["person"]["first_name"] == "Anna" and "FastAPI" in prof["skills"]
