"""CV tailoring for a .docx in its own design (Word, Google Docs → File → Download → .docx).

The document is read into the same structure as the LaTeX CV (cvgen.Cv: headline, summary sentences, skill rows,
roles with bullets), so the model gets the same prompt and cvgen.apply_plan applies the same checks. Then only what
changed is written back into the document: bullets are moved or removed as whole paragraphs (formatting and
numbering stay), a changed text goes into the paragraph's own run. A paragraph whose text is split into runs with
different formatting (a bold word inside a bullet) or holds a link is not rewritten: the edit is reported as
declined. Paragraphs nobody touched are not rewritten at all.

Structure is found by section headings (a Heading style, or a short line in bold or capitals): Summary / Profile /
About, Skills, Experience. Skill rows are lines "Label: a, b, c"; a role is a run of list paragraphs (bullets) after
its header lines. Other names can be given in cv_bank.yaml → docx: {summary: regex, skills: regex, experience: regex}.
The headline is the paragraph equal to one of cv_bank headlines; location and work authorisation lines are the
paragraphs equal to relocation.default.location / workauth of the bank. `python -m jobsearch cv --inspect` prints
what was found.

PDF: LibreOffice (`soffice`) converts the result when installed; then the page limit is checked too. Without it the
tailored CV is sent as .docx (most application forms take it)."""
import copy
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from . import cvgen

SECTIONS = {
    "summary": r"(professional |career )?(summary|profile|overview)|about( me)?|о себе|профиль|кратко",
    "skills": r"((technical|core|key|hard) )?skills( (&|and) tools)?|tech(nical)? stack|stack|tools|competencies|навыки|стек",
    "experience": r"((work|professional|relevant) )?experience|employment( history)?|work history|career( history)?|опыт( работы)?",
}
# headings that end a section without being one we tailor
OTHER = (r"education|languages?|projects?|certifications?|certificates|courses|training|awards|achievements|"
         r"interests|hobbies|publications|references|volunteering|contacts?|personal( details| information)?|"
         r"образование|языки|проекты|сертификаты|курсы|награды|интересы|контакты")
BULLET_CHARS = "•●▪◦‣-–*·"
W_T, W_R = qn("w:t"), qn("w:r")


# ------------------------------------------------------------------ reading
def paragraphs(doc):
    """Every paragraph in reading order: body, tables, text boxes. The VML fallback copy of a text box is skipped."""
    out = []
    for p in doc.element.body.iter(qn("w:p")):
        anc, skip = p.getparent(), False
        while anc is not None:
            if anc.tag.endswith("}Fallback"):
                skip = True
                break
            anc = anc.getparent()
        if not skip:
            out.append(p)
    return out


def text_of(p):
    parts = []
    for el in p.iter():
        if el.tag == W_T:
            parts.append(el.text or "")
        elif el.tag == qn("w:tab"):
            parts.append("\t")
    return "".join(parts)


def style_of(p, doc):
    sid = p.find(qn("w:pPr") + "/" + qn("w:pStyle"))
    if sid is None:
        return ""
    try:
        return doc.styles.get_by_id(sid.get(qn("w:val")), 1).name or ""   # 1 = WD_STYLE_TYPE.PARAGRAPH
    except Exception:
        return sid.get(qn("w:val")) or ""


def is_list(p, doc):
    if p.find(qn("w:pPr") + "/" + qn("w:numPr")) is not None:
        return True
    if "list" in style_of(p, doc).lower():
        return True
    return bool(re.match(rf"^\s*[{re.escape(BULLET_CHARS)}]\s+", text_of(p)))


def is_heading(p, doc):
    t = text_of(p).strip()
    if not t or len(t) > 45 or is_list(p, doc):
        return False
    st = style_of(p, doc).lower()
    if st.startswith(("heading", "title")) or "заголовок" in st:
        return True
    if t.endswith((".", ",", ";")):
        return False
    letters = [c for c in t if c.isalpha()]
    caps = letters and all(c.isupper() for c in letters)
    runs = [r for r in p.iter(W_R) if (text_of(r) or "").strip()]
    bold = runs and all(_bold(r) for r in runs)
    return bool(caps or bold)


def heading_level(p, doc):
    m = re.search(r"(\d+)$", style_of(p, doc))
    return int(m.group(1)) if m and style_of(p, doc).lower().startswith(("heading", "заголовок")) else None


def _bold(r):
    b = r.find(qn("w:rPr") + "/" + qn("w:b"))
    return b is not None and b.get(qn("w:val")) not in ("0", "false")


def bullet_prefix(text):
    m = re.match(rf"^\s*[{re.escape(BULLET_CHARS)}]\s+", text)
    return m.group(0) if m else ""


@dataclass
class DocxCv(cvgen.Cv):
    """cvgen.Cv plus where each piece sits: paragraph indexes into paragraphs(doc)."""
    headline: str = ""
    headline_idx: object = None
    summary_idx: object = None
    skill_slots: dict = field(default_factory=dict)      # norm(label) -> (paragraph index, offset where items start, sep)
    bullet_idx: dict = field(default_factory=dict)       # bullet id -> paragraph index
    location_idx: object = None
    workauth_idx: object = None
    full_text: str = ""

    def macro(self, name):
        return self.headline if name == "cvheadline" else ""


def parse(path, bank=None):
    bank = bank or {}
    doc = Document(str(path))
    ps = paragraphs(doc)
    texts = [text_of(p) for p in ps]
    hints = bank.get("docx") or {}
    rx = {k: re.compile(rf"^\W*({v}" + (f"|{hints[k]}" if hints.get(k) else "") + r")\W*$", re.I)
          for k, v in SECTIONS.items()}                  # own names are added to the usual ones
    other = re.compile(rf"^\W*({OTHER})\W*$", re.I)
    headlines = {cvgen.norm(h): h for h in bank.get("headlines") or []}
    rel = ((bank.get("relocation") or {}).get("default") or {})
    cv = DocxCv(text="", macros={}, sentences=[], summary_span=None, skills=[], roles=[],
                full_text="\n".join(texts))

    section, level, role, header = None, None, None, []
    for i, (p, t) in enumerate(zip(ps, texts)):
        s = t.strip()
        if not s:
            continue
        if cv.headline_idx is None and cvgen.norm(s) in headlines:
            cv.headline, cv.headline_idx = s, i
            continue
        if rel.get("location") and cvgen.norm(s) == cvgen.norm(rel["location"]):
            cv.location_idx = i
            continue
        if rel.get("workauth") and cvgen.norm(s) == cvgen.norm(rel["workauth"]):
            cv.workauth_idx = i
            continue
        if is_heading(p, doc):
            hit = next((k for k, r in rx.items() if r.match(s)), None)
            lv = heading_level(p, doc)
            # a section ends at a known section name or a heading style of its own level; a bold role title
            # inside Experience is a role header, not a new section
            if hit or other.match(s) or (lv is not None and level is not None and lv <= level):
                section, level, role, header = hit, lv, None, []
                continue
        if section == "summary" and cv.summary_idx is None and not is_list(p, doc):
            cv.summary_idx = i
            cv.sentences = cvgen.split_sentences(s)
        elif section == "skills":
            body = s[len(bullet_prefix(s)):]
            m = re.match(r"^([^:]{1,40}):\s*(.+)$", body)
            if m:
                label, items = m.group(1).strip(), m.group(2)
                sep = "; " if ";" in items and "," not in items else ", "
                parts = [x.strip() for x in items.split(";")] if sep == "; " else cvgen._split_items(items)
                cv.skills.append(cvgen.SkillRow(label, parts, None))
                cv.skill_slots[cvgen.norm(label)] = (i, t.index(m.group(2), len(bullet_prefix(t))), sep)
        elif section == "experience":
            if is_list(p, doc):
                if role is None:
                    rid = f"r{len(cv.roles) + 1}"
                    title = header[0] if header else f"роль {len(cv.roles) + 1}"
                    role = cvgen.Role(rid, title, title, " · ".join(header[1:]), [], None)   # reports name it by title
                    cv.roles.append(role)
                bid = f"{role.id}.b{len(role.bullets) + 1}"
                pinned = any(x.lower() in s.lower() for x in (bank.get("pin") or []))
                role.bullets.append(cvgen.Bullet(bid, s[len(bullet_prefix(s)):], pinned))
                cv.bullet_idx[bid] = i
            else:
                if role is not None:
                    role, header = None, []
                header.append(s)
    return cv


# ------------------------------------------------------------------ writing
def _sig(r):
    rpr = r.find(qn("w:rPr"))
    return b"" if rpr is None else _xml(rpr)


def _xml(el):
    from lxml import etree
    return etree.tostring(el)


def replace_from(p, k, new_tail):
    """Text of paragraph `p` from character k on becomes `new_tail`, in the formatting of the run where k falls.
    False (nothing changed) when that part spans runs with different formatting, a link or a field."""
    if p.find(".//" + qn("w:hyperlink")) is not None or p.find(".//" + qn("w:fldChar")) is not None:
        return False
    runs = [r for r in p.iter(W_R) if r.find(W_T) is not None]
    if not runs:
        return False
    texts = [text_of(r) for r in runs]
    pos, i = 0, None
    for n, t in enumerate(texts):
        if pos + len(t) > k:
            i = n
            break
        pos += len(t)
    if i is None:                                   # k at the very end: append to the last run
        i, pos = len(runs) - 1, sum(len(t) for t in texts[:-1])
    if len({_sig(r) for r, t in zip(runs[i:], texts[i:]) if t.strip()}) > 1:
        return False
    head = texts[i][:k - pos]
    _set_run(runs[i], head + new_tail)
    for r in runs[i + 1:]:
        _set_run(r, "")
    return True


def _set_run(r, text):
    ts = r.findall(W_T)
    for extra in ts[1:]:
        r.remove(extra)
    for tab in r.findall(qn("w:tab")):
        r.remove(tab)
    ts[0].text = text
    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


FROM_TEX = [(r"$\rightarrow$", "→"), (r"\ca{}", "≈"), ("---", "—"), ("--", "–"), ("``", "“"), ("''", "”"),
            (r"\%", "%"), (r"\_", "_"), (r"\&", "&"), (r"\#", "#")]


def from_tex(s):
    """Model or bank text came through cvgen.to_tex: back to plain text for Word (longest sequences first)."""
    for a, b in FROM_TEX:
        s = s.replace(a, b)
    return s


@dataclass
class Rendered:
    doc: object
    declined: list = field(default_factory=list)     # (where, why) edits the document could not take


def render(path, cv, t, location=None, workauth=None, keywords=None):
    doc = Document(str(path))
    ps = paragraphs(doc)
    out = Rendered(doc)

    def put(idx, text, where, start=None):
        p = ps[idx]
        orig = text_of(p)
        k = len(bullet_prefix(orig)) if start is None else start
        if not replace_from(p, k, text):
            out.declined.append((where, "в абзаце разное форматирование или ссылка — Word-текст не тронут"))

    originals = set(cv.sentences)
    if cv.headline_idx is not None and t.headline and cvgen.norm(t.headline) != cvgen.norm(cv.headline):
        put(cv.headline_idx, from_tex(t.headline), "заголовок")
    if cv.summary_idx is not None and t.sentences and t.sentences != cv.sentences:
        put(cv.summary_idx, " ".join(s if s in originals else from_tex(s) for s in t.sentences), "summary")
    for row, items in t.skills:
        slot = cv.skill_slots.get(cvgen.norm(row.label))
        if slot and items != row.items:
            idx, start, sep = slot
            orig = set(row.items)
            put(idx, sep.join(x if x in orig else from_tex(x) for x in items), f"skills «{row.label}»", start)
    for line, idx, where in ((location, cv.location_idx, "локация"), (workauth, cv.workauth_idx, "разрешение на работу")):
        if line and idx is not None and cvgen.norm(line) != cvgen.norm(text_of(ps[idx]).strip()):
            put(idx, line, where)

    for role in cv.roles:
        shown = t.roles.get(role.id, role.bullets)
        orig_by_id = {b.id: b for b in role.bullets}
        els = [ps[cv.bullet_idx[b.id]] for b in role.bullets]
        for b in shown:                                 # text edits first, while indexes still hold
            if b.tex != orig_by_id[b.id].tex:
                put(cv.bullet_idx[b.id], from_tex(b.tex), f"{role.title}, буллет {b.id.split('.b')[-1]}")
        keep = [ps[cv.bullet_idx[b.id]] for b in shown]
        parent = els[0].getparent()
        contiguous = all(e.getparent() is parent for e in els) and all(
            els[n].getnext() is els[n + 1] for n in range(len(els) - 1))
        if contiguous:
            anchor = els[0].getprevious()
            index = parent.index(els[0])
            for e in els:
                parent.remove(e)
            for n, e in enumerate(keep):
                if anchor is not None:
                    anchor.addnext(e)
                    anchor = e
                else:
                    parent.insert(index + n, e)
        else:                                           # bullets spread over cells: hide only, keep the order
            for e in els:
                if e not in keep:
                    e.getparent().remove(e)
            if [b.id for b in shown] != [b.id for b in role.bullets if b in shown]:
                out.declined.append((role.title, "буллеты не подряд — порядок не менялся"))
    if keywords:
        doc.core_properties.keywords = keywords[:255]
    return out


# ------------------------------------------------------------------ PDF via LibreOffice
def soffice():
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            return shutil.which(name)
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac) if mac.exists() else None


def to_pdf(docx_path, workdir):
    """(pdf path, pages) or (None, None) without LibreOffice. Its own profile dir: two conversions at once would
    otherwise fight over the user's profile lock."""
    exe = soffice()
    if not exe:
        return None, None
    profile = Path(workdir) / "lo-profile"
    p = subprocess.run([exe, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(workdir), str(docx_path)], capture_output=True, text=True, timeout=180,
                       stdin=subprocess.DEVNULL)
    pdf = Path(workdir) / (Path(docx_path).stem + ".pdf")
    if p.returncode != 0 or not pdf.exists():
        raise RuntimeError("LibreOffice не сконвертировал DOCX в PDF: " + (p.stderr or p.stdout)[-300:])
    from pypdf import PdfReader
    return pdf, len(PdfReader(str(pdf)).pages)


def plain(doc_or_cv):
    if isinstance(doc_or_cv, DocxCv):
        return doc_or_cv.full_text
    return "\n".join(text_of(p) for p in paragraphs(doc_or_cv))


def inspect(cv):
    """What was found in the document, for `jobsearch cv --inspect`."""
    lines = [f"заголовок: {cv.headline or '— (нет абзаца, равного одному из cv_bank headlines)'}",
             f"summary: {len(cv.sentences)} предл." if cv.sentences else "summary: не найден (раздел Summary/Profile/About)"]
    lines.append(f"skills: {len(cv.skills)} строк" + (": " + ", ".join(r.label for r in cv.skills) if cv.skills else
                                                     " (строки вида «Название: a, b, c» в разделе Skills)"))
    if not cv.roles:
        lines.append("опыт: роли не найдены (раздел Experience, буллеты списком после строк с должностью)")
    for r in cv.roles:
        lines.append(f"роль {r.id}: {r.title}" + (f" ({r.dates})" if r.dates else "") + f", буллетов {len(r.bullets)}")
    lines.append(f"строка локации: {'есть' if cv.location_idx is not None else 'нет'}, "
                 f"разрешения на работу: {'есть' if cv.workauth_idx is not None else 'нет'} "
                 f"(абзацы, равные relocation.default в cv_bank)")
    return "\n".join(lines)
