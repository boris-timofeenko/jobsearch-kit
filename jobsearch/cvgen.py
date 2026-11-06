"""CV tailored to one vacancy without rewriting it: Telegram button «📄 CV под вакансию», `jobsearch cv <id>`.

Sources (personal, not in git; deploy/deploy.sh copies them to the server):
  config `cv.tex`   the CV itself. Tailoring hooks: \\newcommand{\\cvheadline|\\cvlocation|\\cvworkauth|\\cvkeywords}{...};
                    the SUMMARY paragraph; `\\skillrow{Label}{a, b, c}` lines; `\\item` lines inside `\\begin{duties}`.
                    "% cv:pin" at the end of an \\item line: never hidden.
  config `cv.bank`  cv_bank.yaml: headline variants, extra skills per row, alternative spellings, synonym groups for
                    small edits, visa / relocation lines per track and country.

The model sees the CV cut into numbered pieces and returns a plan (CvPlan): a headline from the list, the order of
summary sentences, skill rows and bullets, a few hidden bullets and at most `cv.max_edits` small wording edits. Code
applies the plan and discards whatever breaks the rules: an unknown id, a skill that is neither in the tex nor in the
bank, a pinned bullet hidden, an edit that changes a number, brings in a word from outside its own text (function
words and synonym groups excepted) or drifts too far from the original. Visa and relocation lines are picked by code
from the vacancy's track and country, never by the model. If the PDF grows past `cv.max_pages`, the least relevant
unpinned bullets go one by one.
"""
import difflib
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2"                 # part of the cache key: bump when the tailoring logic changes
MACROS = ("cvheadline", "cvlocation", "cvworkauth", "cvkeywords")
DESC_CAP = 6000
MAX_HIDE_PER_ROLE = 2
MAX_DROP_SENTENCES = 2
MIN_SIMILARITY = 0.75         # difflib ratio over words: a reorder of tools keeps ~0.9, a rewrite falls below 0.6

FUNCTION_WORDS = set("""a an the and or but nor of in on at to for with without by from as into onto via using across
including such like over under within between per plus also both each every all any our my its their this that these
those which who whom whose while where when than then so is are was were be been being has have had do does did i we it
they new more most other same own up out off only just""".split())


# ------------------------------------------------------------------ plan (model output)
class Piece(BaseModel):
    id: str
    text: Optional[str] = None      # small wording edit; null = keep as is


class SkillsRowPlan(BaseModel):
    row: str
    items: list[str]


class RolePlan(BaseModel):
    role: str
    bullets: list[Piece]            # shown bullets in order; a bullet left out is hidden


class CvPlan(BaseModel):
    headline: str
    summary: list[Piece]
    skills: list[SkillsRowPlan]
    roles: list[RolePlan]
    vacancy_keywords: list[str] = []
    comment: str = ""


SYSTEM = """Ты подгоняешь резюме кандидата под одну вакансию, чтобы оно лучше находилось поиском в ATS и читалось
рекрутером за первые секунды. Резюме не переписывается: ты выбираешь и переставляешь готовые куски и изредка делаешь
мелкие правки формулировок. Код проверит каждое поле и отбросит всё, что нарушает правила.

- headline: один вариант из списка, дословно; ближайший к названию и уровню вакансии.
- summary: s1 всегда первым. Остальные предложения упорядочи по важности для вакансии; можно убрать не больше двух
  нерелевантных.
- skills: все строки; внутри каждой нужное вакансии — первым. Пункты не удаляй. Добавлять можно только из «можно
  добавить» этой строки и только то, что вакансия прямо просит. Пункт можно заменить вариантом написания из списка,
  если вакансия пишет именно так.
- roles: все роли; буллеты по убыванию релевантности. Можно скрыть до двух нерелевантных буллетов роли, кроме
  закреплённых; скрытый буллет — тот, которого нет в списке.
- text у предложения summary или буллета — мелкая правка, не больше {max_edits} на всё резюме: переставить
  элементы внутри одного перечисления (инструменты, платформы), чтобы нужные вакансии шли первыми; заменить слово на
  другое из той же группы синонимов; поправить артикль или пунктуацию. Порядок частей предложения не меняй. Нельзя: добавлять инструменты, факты, цифры и достижения, которых нет
  в этом же тексте; менять цифры и смысл; писать рекламным языком (spearheaded, leveraged, robust, seamless,
  cutting-edge, passionate). Не уверен, что правка нужна, — text: null.
- vacancy_keywords: 10–15 главных hard skills, инструментов и методик из текста вакансии, дословно как в вакансии,
  включая те, которых у кандидата нет. Каждый — один короткий термин (Cypress, TestRail, CI/CD, test design), без
  скобок, пояснений и перечислений.
- comment: одна-две фразы по-русски: что подчёркнуто и чего под эту вакансию в резюме нет.
Ответ — один JSON-объект по схеме, без пояснений."""


# ------------------------------------------------------------------ tex <-> plain text
TEX2PLAIN = [(r"\ca{}", "≈"), (r"$\rightarrow$", "→"), (r"\%", "%"), (r"\_", "_"), (r"\&", "&"), (r"\#", "#"),
             ("---", "—"), ("--", "–")]
PLAIN2TEX = [("%", r"\%"), ("_", r"\_"), ("&", r"\&"), ("#", r"\#"), ("—", "---"), ("–", "--"), ("“", "``"),
             ("”", "''"), ("’", "'"), ("≈", r"\ca{}"), ("→", r"$\rightarrow$")]
MARKUP = re.compile(r"[\\{}$^~]")


def to_plain(tex):
    for a, b in TEX2PLAIN:
        tex = tex.replace(a, b)
    return tex


def to_tex(plain):
    """Model or bank text -> tex. Anything that looks like markup is refused rather than escaped."""
    if MARKUP.search(plain):
        raise ValueError("разметка в тексте")
    for a, b in PLAIN2TEX:
        plain = plain.replace(a, b)
    return plain


WORD = re.compile(r"[a-z0-9]+")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")     # "100k", "1.5", "65%" count; the 2 in "E2E" does not


def words(s):
    return WORD.findall(s.lower())


def numbers(s):
    return sorted(NUMBER.findall(s))


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# ------------------------------------------------------------------ parsing the CV
@dataclass
class Bullet:
    id: str
    tex: str
    pinned: bool = False


@dataclass
class Role:
    id: str
    title: str
    company: str
    dates: str
    bullets: list
    span: tuple                     # text between \begin{duties} and \end{duties}


@dataclass
class SkillRow:
    label: str
    items: list                     # tex
    span: tuple                     # the whole \skillrow{...}{...} line


@dataclass
class Cv:
    text: str
    macros: dict                    # name -> (start, end) of the value inside the braces
    sentences: list                 # tex
    summary_span: Optional[tuple]
    skills: list
    roles: list

    def macro(self, name):
        s = self.macros.get(name)
        return self.text[s[0]:s[1]] if s else ""


def _brace_end(text, i):
    """Index of the brace closing the one at text[i]; escaped braces are skipped."""
    depth, k = 0, i
    while k < len(text):
        c = text[k]
        if c == "\\":
            k += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    raise ValueError(f"unbalanced braces at {i}")


def _split_items(s):
    """Skill items: commas outside parentheses."""
    out, depth, cur = [], 0, ""
    for c in s:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def split_sentences(par):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", par.strip()) if s]


def parse(text):
    macros = {}
    for name in MACROS:
        m = re.search(r"\\newcommand\{\\%s\}\{" % name, text)
        if m:
            macros[name] = (m.end(), _brace_end(text, m.end() - 1))

    sentences, summary_span = [], None
    m = re.search(r"\\cvsection\{SUMMARY\}[^\n]*\n", text)
    if m:
        pos, start, end = m.end(), None, None
        for line in text[m.end():].split("\n"):
            s = line.strip()
            if start is None and (not s or s.startswith("%")):
                pos += len(line) + 1
                continue
            if start is not None and (not s or s.startswith("%") or s.startswith("\\cvsection")):
                break
            if start is None:
                start = pos
            pos += len(line) + 1
            end = pos - 1
        if start is not None:
            summary_span = (start, end)
            sentences = split_sentences(text[start:end])

    skills = [SkillRow(m.group(1), _split_items(m.group(2)), m.span())
              for m in re.finditer(r"^\\skillrow\{([^{}]*)\}\{(.*)\}[ \t]*$", text, re.M)]

    roles = []
    heads = list(re.finditer(r"\\role\{([^{}]*)\}\{([^{}]*)\}\{([^{}]*)\}", text))
    for i, h in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        b = text.find("\\begin{duties}", h.end(), stop)
        if b < 0:
            continue
        body_start = b + len("\\begin{duties}")
        body_end = text.find("\\end{duties}", body_start)
        rid = f"r{len(roles) + 1}"
        bullets = []
        for chunk in re.split(r"^[ \t]*\\item[ \t]+", text[body_start:body_end], flags=re.M)[1:]:
            pinned = bool(re.search(r"(?<!\\)%\s*cv:pin", chunk))
            tex = " ".join(re.sub(r"(?<!\\)%.*$", "", ln).strip() for ln in chunk.split("\n")).strip()
            bullets.append(Bullet(f"{rid}.b{len(bullets) + 1}", tex, pinned))
        roles.append(Role(rid, h.group(1), h.group(2), h.group(3), bullets, (body_start, body_end)))
    return Cv(text, macros, sentences, summary_span, skills, roles)


# ------------------------------------------------------------------ checking small edits
def synonym_words(orig_words, groups):
    """Words the edit may bring in by swapping within a synonym group present in the original."""
    have, out = set(orig_words), set()
    for g in groups or []:
        if any(set(words(ph)) <= have for ph in g):
            for ph in g:
                out |= set(words(ph))
    return out


def check_edit(orig, new, allowed=(), synonyms=()):
    """'' if `new` is a small edit of `orig` (both plain text), otherwise why not (Russian, goes into the report)."""
    if MARKUP.search(new):
        return "разметка в тексте"
    if numbers(orig) != numbers(new):
        return "изменены цифры"
    ow, nw = words(orig), words(new)
    if not nw:
        return "пустой текст"
    ok = set(ow) | FUNCTION_WORDS | set(allowed) | synonym_words(ow, synonyms)
    fresh = [w for w in dict.fromkeys(nw) if w not in ok]
    if fresh:
        return "новые слова: " + ", ".join(fresh[:5])
    co, cn = words(_canon(orig, synonyms)), words(_canon(new, synonyms))    # a synonym swap costs nothing below
    if not 0.8 <= len(cn) / max(1, len(co)) <= 1.3:
        return "сильно изменилась длина"
    if difflib.SequenceMatcher(None, co, cn, autojunk=False).ratio() < MIN_SIMILARITY:
        return "слишком далеко от исходного текста"
    return ""


def _canon(s, groups):
    """Every phrase of a synonym group replaced by the group's marker, so "end-to-end" and "E2E" compare equal."""
    s = f" {s.lower()} "
    for gi, g in enumerate(groups or []):
        for ph in sorted(g, key=len, reverse=True):
            s = re.sub(r"(?<![a-z0-9])" + re.escape(ph.lower()) + r"(?![a-z0-9])", f" syn{gi} ", s)
    return s


# ------------------------------------------------------------------ applying the plan
@dataclass
class Tailored:
    headline: str
    sentences: list                          # tex, in order
    skills: list                             # [(SkillRow, [tex items])] in order
    roles: dict                              # role id -> [Bullet] shown, in order
    edits: list = field(default_factory=list)          # (where, old plain, new plain)
    rejected: list = field(default_factory=list)       # (where, why)
    hidden: list = field(default_factory=list)         # (company, plain) hidden by the model
    trimmed: list = field(default_factory=list)        # (company, plain) dropped to fit the page limit
    dropped_sentences: list = field(default_factory=list)
    added_skills: list = field(default_factory=list)
    renamed_skills: list = field(default_factory=list)  # (from, to)


def choose_headline(wanted, options, default):
    options = [o for o in options or [] if o]
    if not options:
        return default
    by_norm = {norm(o): o for o in options}
    if norm(wanted or "") in by_norm:
        return by_norm[norm(wanted)]
    close = difflib.get_close_matches(norm(wanted or ""), list(by_norm), n=1, cutoff=0.8)
    return by_norm[close[0]] if close else (default or options[0])


def _edit(piece_text, orig_tex, where, t, budget, allowed, synonyms):
    """Returns the tex to use for one piece: the checked edit or the original."""
    if not piece_text or norm(piece_text) == norm(to_plain(orig_tex)):
        return orig_tex, False
    orig = to_plain(orig_tex)
    if MARKUP.search(orig):
        t.rejected.append((where, "в исходнике есть разметка, править нельзя"))
        return orig_tex, False
    if len(t.edits) >= budget:
        t.rejected.append((where, f"лимит правок ({budget})"))
        return orig_tex, False
    why = check_edit(orig, piece_text, allowed, synonyms)
    if why:
        t.rejected.append((where, why))
        return orig_tex, False
    t.edits.append((where, orig, piece_text.strip()))
    return to_tex(piece_text.strip()), True


def mentioned(item, vacancy_words):
    """Does the vacancy ask for a bank skill? Any of its "/" parts (parentheses ignored) with all significant words
    present, compared by a 5-letter stem ("case" ~ "cases", "management" ~ "manage")."""
    for part in re.split(r"[/,]", re.sub(r"\(.*?\)", "", item)):
        sig = [w for w in words(part) if w not in FUNCTION_WORDS and len(w) > 1]
        if sig and all(any(v.startswith(w[:5]) for v in vacancy_words) for w in sig):
            return True
    return False


def apply_plan(cv, bank, plan, max_edits=5, vacancy_text=""):
    vacancy_words = set(words(vacancy_text))
    synonyms = bank.get("synonyms") or []
    sk = bank.get("skills") or {}
    extras = {norm(k): v or [] for k, v in (sk.get("extra") or {}).items()}
    aliases = {norm(k): v or [] for k, v in (sk.get("aliases") or {}).items()}
    t = Tailored(choose_headline(plan.headline, bank.get("headlines"), to_plain(cv.macro("cvheadline"))), [], [], {})

    # summary: s1 first, the rest in the model's order, at most MAX_DROP_SENTENCES dropped
    skill_words = {w for r in cv.skills for it in r.items for w in words(to_plain(it))}
    skill_words |= {w for v in extras.values() for it in v for w in words(it)}
    skill_words |= {w for h in bank.get("headlines") or [] for w in words(h)}
    ids = {f"s{i + 1}": s for i, s in enumerate(cv.sentences)}
    chosen = []
    for p in plan.summary or [Piece(id=i) for i in ids]:      # no summary in the plan = keep it as is
        if p.id in ids and p.id not in [c.id for c in chosen]:
            chosen.append(p)
    if ids and "s1" not in [c.id for c in chosen]:
        chosen.insert(0, Piece(id="s1"))
    chosen.sort(key=lambda p: p.id != "s1")                 # stable: only moves s1 to the front
    dropped = [i for i in ids if i not in [c.id for c in chosen]]
    for i in dropped[MAX_DROP_SENTENCES:]:
        chosen.append(Piece(id=i))
    t.dropped_sentences = [to_plain(ids[i]) for i in dropped[:MAX_DROP_SENTENCES]]
    for p in chosen:
        tex, _ = _edit(p.text, ids[p.id], f"summary {p.id}", t, max_edits, skill_words, synonyms)
        t.sentences.append(tex)

    # skills: rows in the model's order, items from the row / its aliases / its extras; nothing original goes missing
    rows = {norm(r.label): r for r in cv.skills}
    planned = {norm(p.row): p.items for p in plan.skills if norm(p.row) in rows}
    order = [rows[k] for k in dict.fromkeys(norm(p.row) for p in plan.skills) if k in rows]
    order += [r for r in cv.skills if r not in order]
    for row in order:
        orig = {norm(to_plain(x)): x for x in row.items}
        alias_of = {norm(a): (k, a) for k in orig for a in aliases.get(k, [])}
        extra = {norm(x): x for x in extras.get(norm(row.label), [])}
        out, used = [], set()
        for it in planned.get(norm(row.label), []):
            k = norm(it)
            if k in orig:
                if k not in used:
                    out.append(orig[k])
                    used.add(k)
            elif k in alias_of:
                src, alt = alias_of[k]
                if src not in used:
                    out.append(to_tex(alt))
                    used.add(src)
                    t.renamed_skills.append((to_plain(orig[src]), alt))
            elif k in extra:
                if vacancy_words and not mentioned(extra[k], vacancy_words):
                    t.rejected.append((f"skills «{row.label}»", f"«{it}»: вакансия этого не упоминает"))
                elif k not in used:
                    out.append(to_tex(extra[k]))
                    used.add(k)
                    t.added_skills.append(extra[k])
            else:
                t.rejected.append((f"skills «{row.label}»", f"«{it}» нет ни в CV, ни в банке"))
        out += [x for k, x in orig.items() if k not in used]
        t.skills.append((row, out))

    # bullets: the model's order; pinned never hidden, at most MAX_HIDE_PER_ROLE hidden per role, at least one shown
    plans = {p.role: p for p in plan.roles}
    for role in cv.roles:
        by_id = {b.id: b for b in role.bullets}
        pieces = []
        for p in (plans[role.id].bullets if plans.get(role.id) and plans[role.id].bullets     # empty = as is
                  else [Piece(id=b.id) for b in role.bullets]):
            if p.id in by_id and p.id not in [x.id for x in pieces]:
                pieces.append(p)
        hidden = [b for b in role.bullets if b.id not in [x.id for x in pieces]]
        back = [b for b in hidden if b.pinned] + [b for b in hidden if not b.pinned][MAX_HIDE_PER_ROLE:]
        if not pieces and not back:
            back = hidden
        pieces += [Piece(id=b.id) for b in role.bullets if b in back]
        t.hidden += [(role.company, to_plain(b.tex)) for b in hidden if b not in back]
        shown = []
        for p in pieces:
            b = by_id[p.id]
            tex, _ = _edit(p.text, b.tex, f"{role.company}, буллет {p.id.split('.')[-1][1:]}", t, max_edits,
                           (), synonyms)
            shown.append(Bullet(b.id, tex, b.pinned))
        t.roles[role.id] = shown
    return t


def trim_one(cv, t):
    """Hide the least relevant unpinned bullet of the role that shows the most; False when nothing is left to cut."""
    best = None
    for role in cv.roles:
        shown = t.roles.get(role.id, [])
        cut = [b for b in shown if not b.pinned]
        if cut and len(shown) > 1 and (best is None or len(shown) >= len(t.roles[best.id])):
            best = role
    if best is None:
        return False
    victim = [b for b in t.roles[best.id] if not b.pinned][-1]
    t.roles[best.id].remove(victim)
    t.trimmed.append((best.company, to_plain(victim.tex)))
    return True


# ------------------------------------------------------------------ visa / relocation lines (code, not the model)
COUNTRIES = {
    "Austria": ["austria", "osterreich", "vienna", "wien"], "Belgium": ["belgium", "brussels", "antwerp"],
    "Bulgaria": ["bulgaria", "sofia", "plovdiv"], "Croatia": ["croatia", "zagreb"], "Cyprus": ["cyprus", "nicosia", "limassol"],
    "Czechia": ["czechia", "czech republic", "prague", "praha", "brno"], "Denmark": ["denmark", "copenhagen", "kobenhavn", "aarhus"],
    "Estonia": ["estonia", "tallinn"], "Finland": ["finland", "helsinki"], "France": ["france", "paris"],
    "Germany": ["germany", "deutschland", "berlin", "munich", "hamburg"], "Greece": ["greece", "athens", "thessaloniki"],
    "Hungary": ["hungary", "budapest"], "Ireland": ["ireland", "dublin", "cork", "galway"],
    "Italy": ["italy", "italia", "milan", "milano", "rome", "roma", "turin", "torino"], "Latvia": ["latvia", "riga"],
    "Lithuania": ["lithuania", "vilnius"], "Luxembourg": ["luxembourg"], "Malta": ["malta", "valletta"],
    "Netherlands": ["netherlands", "amsterdam", "rotterdam"],
    "Poland": ["poland", "polska", "warsaw", "warszawa", "krakow", "cracow", "wroclaw", "gdansk", "poznan", "lodz", "katowice"],
    "Portugal": ["portugal", "lisbon", "lisboa", "porto", "braga"],
    "Romania": ["romania", "bucharest", "bucuresti", "cluj", "iasi", "timisoara"], "Slovakia": ["slovakia", "bratislava"],
    "Slovenia": ["slovenia", "ljubljana"], "Spain": ["spain", "espana", "madrid", "barcelona", "valencia", "malaga"],
    "Sweden": ["sweden", "stockholm", "gothenburg", "malmo"], "Norway": ["norway", "oslo"],
    "Switzerland": ["switzerland", "zurich", "geneva", "basel"], "Iceland": ["iceland"], "Liechtenstein": ["liechtenstein"],
}


def _ascii(s):
    s = s.replace("ł", "l").replace("Ł", "L").replace("ø", "o")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def country_of(location):
    """Country from a free-form location; country names win over city names, the last comma part wins over the rest."""
    loc = _ascii(location or "")
    parts = [p.strip() for p in loc.split(",")][::-1]
    for names_first in (True, False):
        for part in parts:
            for country, names in COUNTRIES.items():
                cand = names[:1] if names_first else names
                if any(re.search(rf"\b{re.escape(n)}\b", part) for n in cand):
                    return country
    return None


def relocation_lines(bank, track, location, country_name=None):
    """(location line, work authorisation line, short note for the report) for the vacancy's track."""
    rel = bank.get("relocation") or {}
    base = rel.get("default") or {}
    country = country_name
    if track == "eu":
        country = country_of(location)
        entry = {**(rel.get("eu") or {}), **((rel.get("countries") or {}).get(country) or {})}
    else:
        entry = rel.get(track) or {}
    loc, auth = entry.get("location") or base.get("location"), entry.get("workauth") or base.get("workauth")
    to_country = f"to {country}" if country else "within the EU"
    fill = lambda s: s.replace("{to_country}", to_country).replace("{country}", country or "the EU") if s else s
    note = {"remote": "remote", "remote_nl": "remote + NL"}.get(track) or country or ("ЕС" if track == "eu" else "общая")
    return fill(loc), fill(auth), note


# ------------------------------------------------------------------ rendering and compiling
def render(cv, t, location=None, workauth=None, keywords=None):
    subs = []
    for name, value in (("cvheadline", t.headline), ("cvlocation", location), ("cvworkauth", workauth),
                        ("cvkeywords", keywords)):
        if value and name in cv.macros:
            subs.append((*cv.macros[name], to_tex(value)))
    if cv.summary_span and t.sentences:
        subs.append((*cv.summary_span, " ".join(t.sentences)))
    for slot, (row, items) in zip(cv.skills, t.skills):         # rows fill the original slots in the new order
        subs.append((*slot.span, f"\\skillrow{{{row.label}}}{{{', '.join(items)}}}"))
    for role in cv.roles:
        shown = t.roles.get(role.id, role.bullets)
        subs.append((*role.span, "\n" + "".join(f"  \\item {b.tex}\n" for b in shown)))
    text = cv.text
    for start, end, new in sorted(subs, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def compile_pdf(tex, workdir):
    """pdflatex in `workdir`; returns (pdf path, pages)."""
    if not shutil.which("pdflatex"):
        raise RuntimeError("pdflatex не установлен (на сервере: deploy/install-server.sh ставит TeX Live)")
    src = Path(workdir) / "cv.tex"
    src.write_text(tex)
    p = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "cv.tex"],
                       cwd=workdir, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    log = (Path(workdir) / "cv.log").read_text(errors="replace") if (Path(workdir) / "cv.log").exists() else p.stdout
    m = re.search(r"Output written on cv\.pdf \((\d+) pages?", log)
    if p.returncode != 0 or not m:
        errors = [ln for ln in log.splitlines() if ln.startswith("!")][:3]
        raise RuntimeError("pdflatex: " + ("; ".join(errors) or log[-300:]))
    return Path(workdir) / "cv.pdf", int(m.group(1))


def plain_text(tex, extra=""):
    """Rough text of the document body for keyword matching: macro values + body without commands and comments."""
    body = tex.split("\\begin{document}", 1)[-1]
    body = re.sub(r"(?<!\\)%.*", "", body)
    body = to_plain(body)
    body = re.sub(r"\\[a-zA-Z]+\*?", " ", body).replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", f"{extra} {body}")


def has_keyword(kw, text):
    """Literal, case-insensitive, on word boundaries ("Java" is not in "JavaScript"). "A/B" also counts when every part
    is there separately; "CI/CD" is matched as a whole first."""
    k, low = kw.strip().lower(), text.lower()
    hit = lambda x: re.search(r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])", low) is not None
    if not k:
        return False
    if hit(k):
        return True
    parts = [x.strip() for x in k.split("/") if x.strip()]
    return len(parts) > 1 and all(hit(x) for x in parts)


# ------------------------------------------------------------------ report (Telegram HTML)
def diff_html(old, new, ctx=4):
    """Word diff: removed words struck through, added in bold, long unchanged runs shortened."""
    a, b = old.split(), new.split()
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    out = []
    for n, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == "equal":
            seg = a[i1:i2]
            if len(seg) > 2 * ctx:
                head = [] if n == 0 else seg[:ctx]
                tail = [] if n == len(ops) - 1 else seg[-ctx:]
                seg = head + ["…"] + tail
            out.append(html.escape(" ".join(seg)))
            continue
        if i2 > i1:
            out.append(f"<s>{html.escape(' '.join(a[i1:i2]))}</s>")
        if j2 > j1:
            out.append(f"<b>{html.escape(' '.join(b[j1:j2]))}</b>")
    return " ".join(out)


def _short(s, n=90):
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def report_texts(job, t, plan, kws, before, after, note):
    esc = html.escape
    missing = [k for k in kws if not after.get(k)]
    head = [f"📄 <b>CV под вакансию</b>: {esc(job.get('title') or '')} — {esc(job.get('company') or '')}",
            f"Заголовок: {esc(t.headline)}"]
    if kws:
        head.append(f"Ключевые слова вакансии в CV: {sum(before.values())}/{len(kws)} → {sum(after.values())}/{len(kws)}")
    head.append(f"Виза/релокация: {esc(note)}")
    changed = [f"правок {len(t.edits)}"] if t.edits else []
    changed += [f"в Skills +{len(t.added_skills)}"] if t.added_skills else []
    changed += [f"скрыто буллетов {len(t.hidden) + len(t.trimmed)}"] if t.hidden or t.trimmed else []
    if changed:
        head.append("Изменения: " + ", ".join(changed))
    tail_missing = "Нет в CV: " + esc(", ".join(missing)) if missing else ""
    comment = f"<i>{esc(plan.comment)}</i>" if plan.comment else ""
    caption = "\n".join([*head, tail_missing, comment]).strip()
    if len(caption) > 1024:                              # Telegram caption limit; drop the comment first
        caption = "\n".join([*head, tail_missing]).strip()[:1024]

    d = []
    if t.edits:
        d.append("✏️ <b>Правки формулировок</b>")
        d += [f"• <i>{esc(w)}</i>: {diff_html(o, n)}" for w, o, n in t.edits]
    if t.renamed_skills:
        d.append("🔤 <b>Написание как в вакансии</b>: " + esc("; ".join(f"{a} → {b}" for a, b in t.renamed_skills)))
    if t.added_skills:
        d.append("➕ <b>Добавлено в Skills</b>: " + esc(", ".join(t.added_skills)))
    if t.dropped_sentences:
        d.append("➖ <b>Убрано из Summary</b>: " + esc(" · ".join(_short(s) for s in t.dropped_sentences)))
    if t.hidden:
        d.append("🙈 <b>Скрыто как нерелевантное</b>")
        d += [f"• {esc(c)}: «{esc(_short(s))}»" for c, s in t.hidden]
    if t.trimmed:
        d.append("✂️ <b>Убрано, чтобы уложиться в страницы</b>")
        d += [f"• {esc(c)}: «{esc(_short(s))}»" for c, s in t.trimmed]
    if t.rejected:
        d.append("🚫 <b>Отклонено проверкой</b>")
        d += [f"• {esc(w)}: {esc(why)}" for w, why in t.rejected]
    details = ""
    for line in d:                                       # Telegram message limit, cut on a line boundary
        if len(details) + len(line) + 1 > 3900:
            details += "\n…"
            break
        details += ("\n" if details else "") + line
    return caption, details


# ------------------------------------------------------------------ entry point
@dataclass
class Result:
    pdf: Path
    filename: str
    caption: str
    details: str
    plan: dict = field(default_factory=dict)
    cached: bool = False


def build_prompt(cv, bank, job):
    sk = bank.get("skills") or {}
    extras = {norm(k): v or [] for k, v in (sk.get("extra") or {}).items()}
    aliases = {norm(k): v or [] for k, v in (sk.get("aliases") or {}).items()}
    lines = ["ВАКАНСИЯ", f"Компания: {job.get('company')}", f"Заголовок: {job.get('title')}",
             f"Локация: {job.get('location')}", "Текст:", (job.get("description") or "")[:DESC_CAP], "",
             "РЕЗЮМЕ", "headline — варианты:"]
    lines += [f"- {h}" for h in bank.get("headlines") or [to_plain(cv.macro("cvheadline"))]]
    lines += ["", "summary:"] + [f"[s{i + 1}] {to_plain(s)}" for i, s in enumerate(cv.sentences)]
    lines += ["", "skills (строка: пункты через «; »):"]
    for row in cv.skills:
        lines.append(f"[{row.label}] " + "; ".join(to_plain(x) for x in row.items))
        if extras.get(norm(row.label)):
            lines.append("   можно добавить: " + "; ".join(extras[norm(row.label)]))
        alts = [f"{to_plain(x)} → {' | '.join(aliases[norm(to_plain(x))])}" for x in row.items
                if aliases.get(norm(to_plain(x)))]
        if alts:
            lines.append("   варианты написания: " + "; ".join(alts))
    lines += ["", "roles:"]
    for role in cv.roles:
        lines.append(f"[{role.id}] {to_plain(role.title)} — {to_plain(role.company)} ({to_plain(role.dates)})")
        lines += [f"  [{b.id}]{' (закреплён)' if b.pinned else ''} {to_plain(b.tex)}" for b in role.bullets]
    if bank.get("synonyms"):
        lines += ["", "группы синонимов для правок:"] + ["- " + " = ".join(g) for g in bank["synonyms"]]
    return "\n".join(lines)


def _slug(s, n=30):
    return re.sub(r"[^A-Za-z0-9]+", "_", _ascii(s or "")).strip("_").title()[:n] or "Company"


def build_for_job(job, cfg, backend=None, log=print):
    """Tailored PDF for one vacancy (`job` is a jobs row as a dict). Cached by CV, bank, vacancy text and model."""
    from . import llm
    ccfg = cfg.get("cv") or {}
    from .config import path_in_project
    tex_path, bank_path = path_in_project(ccfg.get("tex", "my/cv.tex")), path_in_project(ccfg.get("bank", "my/cv_bank.yaml"))
    if not tex_path.exists():
        raise RuntimeError(f"нет исходника CV {tex_path}: положи LaTeX-резюме в my/cv.tex (на сервер его копирует deploy/deploy.sh)")
    desc = job.get("description") or ""
    if len(desc) < 200:
        raise RuntimeError("у вакансии нет текста описания, подгонять не по чему")
    text = tex_path.read_text()
    bank_text = bank_path.read_text() if bank_path.exists() else ""
    bank = yaml.safe_load(bank_text) or {}
    if backend is None:
        backend, why = llm.pick_backend(cfg.get("llm", {}))
        if not backend:
            raise RuntimeError(f"LLM недоступен: {why}")
    model = ccfg.get("model_cli" if backend.name == "cli" else "model_api")
    key = hashlib.sha1("\0".join([VERSION, text, bank_text, job.get("id", ""), desc, str(model)]).encode()).hexdigest()[:10]
    name = (cfg.get("profile") or {}).get("candidate", {}).get("name") or "CV"
    filename = f"{_slug(name, 40)}_CV_{_slug(job.get('company'))}.pdf"
    from .config import DATA
    out_dir = DATA / "cv"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{_slug(job.get('company'))}-{key}"
    if base.with_suffix(".pdf").exists() and base.with_suffix(".json").exists():
        meta = json.loads(base.with_suffix(".json").read_text())
        return Result(base.with_suffix(".pdf"), filename, meta["caption"], meta["details"], meta.get("plan", {}), True)

    cv = parse(text)
    log(f"cv: asking {backend.name}/{model} for {job.get('company')} — {job.get('title')}")
    plan = backend.ask(SYSTEM.replace("{max_edits}", str(ccfg.get("max_edits", 5))), build_prompt(cv, bank, job),
                       CvPlan, model=model)
    t = apply_plan(cv, bank, plan, ccfg.get("max_edits", 5), vacancy_text=f"{job.get('title')} {desc}")

    track = job.get("track") or ""
    t = (cfg.get("profile") or {}).get("target", {})
    country = next((c["name"] for c in ([t["primary"]] if t.get("primary") else []) + list(t.get("countries") or [])
                    if c.get("code") == track), None)
    location, workauth, note = relocation_lines(bank, track, job.get("location"), country)

    kws = list(dict.fromkeys(k.strip() for k in plan.vacancy_keywords if k.strip()))[:20]
    original_plain = plain_text(text, " ".join(to_plain(cv.macro(m)) for m in MACROS[:3]))
    before = {k: has_keyword(k, original_plain) for k in kws}
    max_pages = int(ccfg.get("max_pages", 2))
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(12):
            draft = render(cv, t, location, workauth)
            body = plain_text(draft, f"{t.headline} {location or ''} {workauth or ''}")
            base_kw = [k.strip() for k in to_plain(cv.macro("cvkeywords")).split(",") if k.strip()]
            extra_kw = [k for k in kws if has_keyword(k, body) and norm(k) not in {norm(x) for x in base_kw}
                        and not MARKUP.search(k)]
            final = render(cv, t, location, workauth, ", ".join(base_kw + extra_kw) or None)
            pdf, pages = compile_pdf(final, tmp)
            if pages <= max_pages or not trim_one(cv, t):
                break
        after = {k: has_keyword(k, body) for k in kws}
        shutil.copy(pdf, base.with_suffix(".pdf"))
        base.with_suffix(".tex").write_text(final)
    caption, details = report_texts(job, t, plan, kws, before, after, note)
    base.with_suffix(".json").write_text(json.dumps({"caption": caption, "details": details, "pages": pages,
                                                     "plan": plan.model_dump()}, ensure_ascii=False, indent=1))
    return Result(base.with_suffix(".pdf"), filename, caption, details, plan.model_dump())
