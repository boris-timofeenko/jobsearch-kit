"""«CV под вакансию» end to end for every CV format, with a stand-in for the model."""
import shutil

import pytest

from jobsearch import config, cvgen

from test_cv_docx import BANK, make_docx
from test_cvgen import TEX

JOB = {"id": "linkedin:1", "company": "Acme Pay", "title": "Senior Backend Engineer", "location": "Berlin, Germany",
       "track": "de", "description": "We need Python, FastAPI and gRPC for payment services. " * 10}


class FakeModel:
    name = "api"

    def __init__(self):
        self.calls = 0

    def ask(self, system, prompt, out_cls, model=None):
        self.calls += 1
        assert "[r1.b1]" in prompt and "ВАКАНСИЯ" in prompt
        return cvgen.CvPlan(headline="Senior Python Engineer", summary=[], skills=[],
                            roles=[cvgen.RolePlan(role="r1", bullets=[cvgen.Piece(id="r1.b2"), cvgen.Piece(id="r1.b1")])],
                            vacancy_keywords=["Python", "gRPC"], comment="порядок под платёжный бэкенд")


def cfg_for(tmp_path, cv_name):
    import yaml
    (tmp_path / "cv_bank.yaml").write_text(yaml.safe_dump(BANK, allow_unicode=True))
    return {"profile": {"_cv": str(tmp_path / cv_name), "candidate": {"name": "Anna Example"},
                        "target": {"primary": {"code": "de", "name": "Germany"}, "countries": []}},
            "cv": {"bank": str(tmp_path / "cv_bank.yaml"), "max_pages": 2}}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")


def test_docx_end_to_end_and_cache(tmp_path):
    make_docx(tmp_path / "cv.docx")
    cfg, model = cfg_for(tmp_path, "cv.docx"), FakeModel()
    res = cvgen.build_for_job(JOB, cfg, backend=model, log=lambda *a: None)
    files = [res.pdf] + [f for f, _ in res.extra]
    assert all(f.exists() for f in files) and any(f.suffix == ".docx" for f in files)
    assert res.filename.startswith("Anna_Example_CV_Acme_Pay")
    assert "Relocating to Germany" in res.caption or "Germany" in res.caption
    again = cvgen.build_for_job(JOB, cfg, backend=model, log=lambda *a: None)
    assert again.cached and model.calls == 1


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="no pdflatex")
def test_markdown_and_latex_end_to_end(tmp_path):
    from pathlib import Path
    shutil.copy(Path(__file__).parent.parent / "presets" / "cv" / "example.md", tmp_path / "cv.md")
    res = cvgen.build_for_job(JOB, cfg_for(tmp_path, "cv.md"), backend=FakeModel(), log=lambda *a: None)
    assert res.pdf.suffix == ".pdf" and res.pdf.exists() and res.extra == []
    (tmp_path / "cv.tex").write_text(TEX)
    res = cvgen.build_for_job(JOB, cfg_for(tmp_path, "cv.tex"), backend=FakeModel(), log=lambda *a: None)
    assert res.pdf.exists() and "Ключевые слова вакансии в CV" in res.caption


def test_pdf_cv_explains_what_to_do(tmp_path):
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4")
    with pytest.raises(RuntimeError, match="DOCX"):
        cvgen.build_for_job(JOB, cfg_for(tmp_path, "cv.pdf"), backend=FakeModel(), log=lambda *a: None)
