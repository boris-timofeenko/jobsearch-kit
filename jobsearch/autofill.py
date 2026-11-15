"""Profile for the browser extension (extension/): what a job application form asks, taken from the CV tex and the
`autofill:` section of cv_bank.yaml. `python -m jobsearch autofill` writes extension/profile.json and extension/cv.pdf;
both are personal and ignored by git and by the signed package (extension/web-ext-config.cjs).

The CV is the source of truth for name, contacts, experience, education, languages and skills; the bank holds what a CV
does not say (street address, notice period, salary, answers to yes/no questions)."""
import re
from datetime import date

from . import cvgen

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DEGREES = {"msc": "Master of Science", "ma": "Master of Arts", "mba": "Master of Business Administration",
           "bsc": "Bachelor of Science", "ba": "Bachelor of Arts", "phd": "Doctor of Philosophy"}


def plain(tex):
    """Tex fragment -> text a form accepts: commands and braces gone, ≈ as ~."""
    s = cvgen.to_plain(tex)
    s = re.sub(r"\\(?:textbf|textit|emph|textcolor\{[^}]*\})\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\{\})?", "", s).replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s.replace("≈", "~")).strip()


def parse_date(s):
    """'Nov 2025' -> {'year': 2025, 'month': 11}; 'Present' -> None; '2020' -> {'year': 2020}."""
    s = s.strip().lower()
    if not s or s.startswith(("present", "now", "current")):
        return None
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if m and m.group(1) in MONTHS:
        return {"year": int(m.group(2)), "month": MONTHS[m.group(1)]}
    m = re.search(r"\d{4}", s)
    return {"year": int(m.group())} if m else None


def split_dates(s):
    parts = re.split(r"\s*(?:--|–|—|-)\s*", plain(s), maxsplit=1)
    return parse_date(parts[0]), parse_date(parts[1]) if len(parts) > 1 else None


def role_location(ctx):
    """First sentence of the \\ctx line: 'Johannesburg, South Africa (remote)' / 'Remote (Montenegro)'."""
    first = re.split(r"(?<=[a-z)])\.\s", plain(ctx) + " ", maxsplit=1)[0].strip().rstrip(".")
    remote = bool(re.search(r"\bremote\b", first, re.I))
    m = re.fullmatch(r"remote\s*\(([^)]*)\)", first, re.I)
    loc = m.group(1) if m else re.sub(r"\s*\(remote\)", "", first, flags=re.I)
    return loc.strip(), remote


def parse_cv(text):
    cv = cvgen.parse(text)
    body = text.split("\\begin{document}", 1)[-1]
    out = {}

    m = re.search(r"\\LARGE\\bfseries(?:\\color\{[^}]*\})?\s*([^{}\\]+)\}", body)
    out["name"] = m.group(1).strip() if m else ""

    m = re.search(r"\\href\{tel:([^}]+)\}\{([^}]+)\}", body)
    if m:
        shown = plain(m.group(2))
        code = shown.split()[0] if shown.startswith("+") else ""
        out["phone"] = {"e164": re.sub(r"[^\d+]", "", m.group(1)), "international": shown, "country_code": code,
                        "national": shown[len(code):].strip()}
    m = re.search(r"\\href\{mailto:([^}]+)\}", body)
    out["email"] = m.group(1).strip() if m else ""

    links = re.findall(r"\\href\{(https?://[^}]+)\}", body)
    for url in links:
        host = re.sub(r"^https?://(www\.)?", "", url)
        if host.startswith("linkedin.com"):
            out["linkedin"] = "https://www." + host.rstrip("/")
        elif host.startswith("github.com"):
            out["github"] = "https://" + host.rstrip("/")
        elif host.startswith(("t.me", "telegram.me")):
            out["telegram"] = "https://" + host.rstrip("/")

    location = plain(cv.macro("cvlocation"))
    m = re.search(r"\bin\s+([^.]+)\.", location)
    out["location"] = m.group(1).strip() if m else ""
    out["headline"] = plain(cv.macro("cvheadline"))
    out["summary"] = " ".join(plain(s) for s in cv.sentences)

    m = re.search(r"\\cvsection\{LANGUAGES\}[^\n]*\n((?:\s*%[^\n]*\n)*)\s*([^\n]+)", text)
    langs = []
    if m:
        for part in re.split(r"\\sep\{\}|;", m.group(2)):
            name, _, level = plain(part).partition(":")
            if name.strip():
                langs.append({"name": name.strip(), "level": level.strip()})
    out["languages"] = langs

    out["skills"] = [plain(i) for row in cv.skills for i in row.items]

    heads = list(re.finditer(r"\\role\{([^{}]*)\}\{([^{}]*)\}\{([^{}]*)\}", text))
    exp = []
    for i, (h, role) in enumerate(zip(heads, cv.roles)):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        ctx = re.search(r"\\ctx\{(.*)\}\s*$", text[h.end():stop], re.M)
        loc, remote = role_location(ctx.group(1)) if ctx else ("", False)
        titles = [t.strip() for t in plain(role.title).split("→")]
        start, end = split_dates(role.dates)
        exp.append({"title": titles[-1], "title_history": titles, "company": plain(role.company), "location": loc,
                    "remote": remote, "start": start, "end": end, "current": end is None,
                    "description": "\n".join("- " + plain(b.tex) for b in role.bullets)})
    out["experience"] = exp

    edu = []
    for m in re.finditer(r"\\bfseries\s+([^{}]*)\}\\sep\{\}(.*?)\\hfill\\dt\{([^}]*)\}", body):
        degree, _, field = plain(m.group(1)).partition(",")
        school, _, city = plain(m.group(2)).partition(",")
        start, end = split_dates(m.group(3))
        edu.append({"degree": degree.strip(), "degree_full": DEGREES.get(degree.strip().lower().replace(".", ""), degree.strip()),
                    "field": field.strip(), "school": school.strip(), "city": city.strip(), "start": start, "end": end})
    out["education"] = edu
    return out


LINK = re.compile(r"(?:https?://)?(?:www\.)?((?:linkedin\.com|github\.com|t\.me|telegram\.me)/[\w./-]+)", re.I)
PHONE = re.compile(r"\+\d[\d\s()-]{7,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def parse_docx(path, bank=None):
    """The same fields as parse_cv from a .docx: contacts by pattern from the whole text, summary, skills and roles
    from cv_docx; a role header "Title — Company" or "Title | Company | Jan 2022 – Present" is split, dates parsed.
    Education stays empty: there is no common shape for it in Word CVs."""
    from . import cv_docx
    cv = cv_docx.parse(path, bank or {})
    lines = [x.strip() for x in cv.full_text.split("\n") if x.strip()]
    out = {"name": lines[0] if lines else "", "headline": cv.headline or (lines[1] if len(lines) > 1 else "")}
    m = PHONE.search(cv.full_text)
    if m:
        shown = re.sub(r"\s+", " ", m.group(0)).strip()
        code = shown.split()[0] if " " in shown else ""
        out["phone"] = {"e164": re.sub(r"[^\d+]", "", shown), "international": shown, "country_code": code,
                        "national": shown[len(code):].strip()}
    m = EMAIL.search(cv.full_text)
    out["email"] = m.group(0) if m else ""
    for host in LINK.findall(cv.full_text):
        host = host.rstrip("/.")
        key = "linkedin" if host.lower().startswith("linkedin") else "github" if host.lower().startswith("github") \
            else "telegram"
        out.setdefault(key, ("https://www." if key == "linkedin" else "https://") + host)
    m = re.search(r"\b(?:located|based|living)\s+in\s+([^.\n]+)", cv.full_text, re.I)
    out["location"] = m.group(1).strip() if m else ""
    out["summary"] = " ".join(cv.sentences)
    out["skills"] = [i for row in cv.skills for i in row.items]
    m = re.search(r"^\s*(?:languages|языки)\s*\n(.+)$", cv.full_text, re.I | re.M)
    langs = []
    for part in re.split(r"\s*[·|•;,]\s*", m.group(1)) if m else []:
        name, _, level = part.partition(":")
        if name.strip():
            langs.append({"name": name.strip(), "level": level.strip()})
    out["languages"] = langs
    exp = []
    for r in cv.roles:
        parts = [x.strip() for x in re.split(r"\s+[—–|@]\s+|\s+at\s+", r.title) if x.strip()]
        dates = r.dates or next((x for x in parts[2:] if re.search(r"\d{4}", x)), "")
        start, end = split_dates(dates) if dates else (None, None)
        exp.append({"title": parts[0] if parts else r.title, "title_history": parts[:1], "company": parts[1] if len(parts) > 1 else "",
                    "location": "", "remote": False, "start": start, "end": end, "current": bool(start) and end is None,
                    "description": "\n".join("- " + b.tex for b in r.bullets)})
    out["experience"] = exp
    out["education"] = []
    return out


def build(text, bank, candidate_name="", today=None, parsed=None):
    """profile.json content for the extension (schema: extension/profile.example.json). `parsed`: fields already
    read from a non-LaTeX CV (parse_docx) instead of the tex `text`."""
    cv = parsed if parsed is not None else parse_cv(text)
    af = (bank or {}).get("autofill") or {}
    extra = [s for items in ((bank or {}).get("skills") or {}).get("extra", {}).values() for s in items]
    name = cv["name"] or candidate_name
    first, _, last = name.partition(" ")
    city, _, country = (af.get("location") or cv["location"]).partition(",")
    city, country = city.strip(), (af.get("country") or country).strip()
    return {
        "version": 1,
        "generated": (today or date.today()).isoformat(),
        "person": {
            "full_name": name, "first_name": first, "last_name": last.strip(),
            "email": af.get("email") or cv["email"],
            "phone": cv.get("phone") or {"e164": "", "international": "", "country_code": "", "national": ""},
            "linkedin": cv.get("linkedin", ""), "github": cv.get("github", ""), "telegram": cv.get("telegram", ""),
            "website": af.get("website", ""),
            "nationality": af.get("nationality", ""), "citizenship_country": af.get("citizenship_country", ""),
            "date_of_birth": af.get("date_of_birth", ""),
        },
        "location": {
            "city": city, "country": country, "display": ", ".join(x for x in (city, country) if x),
            "country_aliases": af.get("country_aliases") or ([f"Republic of {country}"] if country else []),
            "address": af.get("address", ""), "postal_code": str(af.get("postal_code", "") or ""),
        },
        "headline": cv["headline"],
        "summary": cv["summary"],
        "experience": cv["experience"],
        "education": cv["education"],
        "languages": cv["languages"],
        "skills": cv["skills"] + [s for s in extra if s not in cv["skills"]],
        "years": af.get("years") or {},
        "answers": {
            "work_authorized": bool(af.get("work_authorized", False)),
            "notice_period": af.get("notice_period", ""),
            "available_from": str(af.get("available_from", "") or ""),
            "available_text": af.get("available_text", ""),
            "heard_about": af.get("heard_about", "LinkedIn"),
            "gender": af.get("gender", ""),
            "salary": af.get("salary") or {},
        },
        "cv_file": "cv.pdf",
        "cv_name": re.sub(r"\s+", "_", name) + "_CV.pdf" if name else "CV.pdf",
    }
