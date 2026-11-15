"""Markdown CV (my/cv.md) → LaTeX with presets/cv/template.tex, so tailoring (cvgen) and autofill work on it as on
a hand-written tex. The format is small on purpose (presets/cv/example.md):

    # Name
    Headline
    Located in City, Country. Open to relocation.        <- free lines before the contacts: location, then work auth
    Kazakhstan national, need a work permit.
    +995 555 123 456 · name@example.com · linkedin.com/in/name · github.com/name

    ## Summary                                           <- one paragraph
    ## Skills                                            <- "- Label: a, b, c"
    ## Experience
    ### Title | Company | Jan 2022 – Present
    City, Country (remote). One line of context.
    - bullet <!-- pin -->                                <- pinned: never hidden by tailoring
    ## Education
    ### Degree, Field | School, City | 2015 – 2019
    ## Languages
    English: C1 · Russian: Native

Any other `##` section is printed as is (paragraphs and bullets)."""
import re
from pathlib import Path

from .config import ROOT

TEMPLATE = ROOT / "presets" / "cv" / "template.tex"
SUMMARY = re.compile(r"^(summary|profile|professional summary|about( me)?|overview|о себе|профиль)$", re.I)
CONTACT = re.compile(r"@|https?://|linkedin\.com|github\.com|t\.me/|^\+?\d[\d\s()-]{6,}$")
SPECIAL = [("\\", r"\textbackslash{}"), ("{", r"\{"), ("}", r"\}"), ("$", r"\$"), ("^", r"\^{}"), ("~", r"\~{}"),
           ("%", r"\%"), ("_", r"\_"), ("&", r"\&"), ("#", r"\#"), ("—", "---"), ("–", "--"), ("“", "``"),
           ("”", "''"), ("’", "'"), ("≈", r"\ca{}"), ("→", r"$\rightarrow$")]


def esc(s):
    """Plain text → tex; **bold** and *italic* become \\textbf / \\textit."""
    s = s.strip()
    out = []
    for i, part in enumerate(re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", s)):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(r"\textbf{" + esc(part[2:-2]) + "}")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append(r"\textit{" + esc(part[1:-1]) + "}")
        else:
            for a, b in SPECIAL:
                part = part.replace(a, b) if a != "\\" else part.replace("\\", "\x00")
            out.append(part.replace("\x00", r"\textbackslash{}"))
    return "".join(out)


def contact(item):
    item = item.strip()
    if "@" in item and " " not in item:
        return rf"\href{{mailto:{item}}}{{{esc(item)}}}"
    if re.fullmatch(r"\+?\d[\d\s()-]{6,}", item):
        digits, shown = re.sub(r"[^0-9+]", "", item), esc(item)
        return rf"\href{{tel:{digits}}}{{{shown}}}"
    if re.match(r"(https?://)?([\w-]+\.)+\w+(/\S*)?$", item):
        url = item if item.startswith("http") else "https://" + item
        shown = esc(re.sub(r"^https?://(www\.)?", "", item))
        return rf"\href{{{url}}}{{{shown}}}"
    return esc(item)


def _sections(lines):
    """[(title, [lines])] for every `## ` section, in order."""
    out, cur = [], None
    for ln in lines:
        if ln.startswith("## "):
            cur = (ln[3:].strip(), [])
            out.append(cur)
        elif cur:
            cur[1].append(ln)
    return out


def _bullet(ln):
    m = re.match(r"^\s*[-*+]\s+(.*)$", ln)
    if not m:
        return None
    text = m.group(1)
    pin = bool(re.search(r"<!--\s*pin\s*-->", text))
    return esc(re.sub(r"\s*<!--.*?-->\s*", " ", text)) + ("  % cv:pin" if pin else "")


def convert(md):
    """Markdown text → full tex document."""
    lines = [ln.rstrip() for ln in md.replace("\r\n", "\n").split("\n")]
    first = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
    if first is None:
        raise ValueError("в резюме нет строки «# Имя»")
    name = lines[first][2:].strip()
    head = []
    for ln in lines[first + 1:]:
        if ln.startswith("## "):
            break
        if ln.strip():
            head.append(ln.strip())
    headline = head[0] if head else ""
    free, contacts = [], []
    for ln in head[1:]:
        parts = [p for p in re.split(r"\s+[·|•]\s+", ln) if p.strip()]
        if any(CONTACT.search(p.strip()) for p in parts):
            contacts.append(parts)
        else:
            free.append(ln)
    location, workauth = (free + ["", ""])[:2]

    defs = "\n".join([rf"\newcommand{{\cvheadline}}{{{esc(headline)}}}", rf"\newcommand{{\cvlocation}}{{{esc(location)}}}",
                      rf"\newcommand{{\cvworkauth}}{{{esc(workauth)}}}", r"\newcommand{\cvkeywords}{}"])
    body = [rf"{{\LARGE\bfseries\color{{inkc}} {esc(name)}}}\par\vspace{{3pt}}", r"{\large \cvheadline}\par\vspace{2pt}",
            r"{\raggedright"]
    if location:
        body.append(r"\cvlocation\par")
    if workauth:
        body.append(r"\cvworkauth\par")
    for parts in contacts:
        body.append(r"\quad ".join(contact(p) for p in parts) + r"\par")
    body.append("}")

    for title, sec in _sections(lines[first + 1:]):
        kind = "SUMMARY" if SUMMARY.match(title) else title.upper()
        body += ["", rf"\cvsection{{{esc(kind)}}}"]
        if kind == "SUMMARY":
            body.append(esc(" ".join(ln.strip() for ln in sec if ln.strip())))
        elif re.match(r"^(SKILLS|TECHNICAL SKILLS|CORE SKILLS|KEY SKILLS|НАВЫКИ)$", kind):
            for ln in sec:
                b = re.match(r"^\s*[-*+]\s+([^:]+):\s*(.+)$", ln)
                if b:
                    body.append(rf"\skillrow{{{esc(b.group(1))}}}{{{esc(b.group(2))}}}")
        elif re.match(r"^(EXPERIENCE|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EMPLOYMENT|ОПЫТ|ОПЫТ РАБОТЫ)$", kind):
            body += _experience(sec)
        elif re.match(r"^(EDUCATION|ОБРАЗОВАНИЕ)$", kind):
            rows = [ln[4:].strip() for ln in sec if ln.startswith("### ")]
            for i, row in enumerate(rows):
                deg, school, dates = ([p.strip() for p in row.split("|")] + ["", ""])[:3]
                body.append(rf"\textcolor{{inkc}}{{\bfseries {esc(deg)}}}\sep{{}}{esc(school)}\hfill\dt{{{esc(dates)}}}"
                            + (r"\par" if i < len(rows) - 1 else ""))
        elif re.match(r"^(LANGUAGES|ЯЗЫКИ)$", kind):
            text = " ".join(ln.strip() for ln in sec if ln.strip())
            body.append(r" \sep{} ".join(esc(p) for p in re.split(r"\s+[·|•]\s+|;\s*", text) if p.strip()))
        else:
            body += _plain(sec)
    tpl = TEMPLATE.read_text(encoding="utf-8")
    return tpl.replace("%%HEAD%%", defs).replace("%%BODY%%", "\n".join(body))


def _experience(sec):
    out, inside, first = [], False, True
    for ln in sec + ["### "]:
        if ln.startswith("### "):
            if inside:
                out.append(r"\end{duties}")
                inside = False
            row = ln[4:].strip()
            if not row:
                continue
            title, company, dates = ([p.strip() for p in row.split("|")] + ["", ""])[:3]
            if not first:
                out.append(r"\nextrole")
            first = False
            out.append(rf"\role{{{esc(title)}}}{{{esc(company)}}}{{{esc(dates)}}}")
            continue
        b = _bullet(ln)
        if b is not None:
            if not inside:
                out.append(r"\begin{duties}")
                inside = True
            out.append(f"  \\item {b}")
        elif ln.strip() and not inside:
            out.append(rf"\ctx{{{esc(ln)}}}")
    return out


def _plain(sec):
    out, inside = [], False
    for ln in sec + [""]:
        b = _bullet(ln)
        if b is not None:
            if not inside:
                out.append(r"\begin{itemize}[leftmargin=1.2em,itemsep=1pt,topsep=2pt]")
                inside = True
            out.append(f"  \\item {b.replace('  % cv:pin', '')}")
            continue
        if inside:
            out.append(r"\end{itemize}")
            inside = False
        if ln.strip():
            out.append(esc(ln) + r"\par")
    return out


def load(path):
    return convert(Path(path).read_text(encoding="utf-8"))
