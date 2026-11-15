"""`python -m jobsearch init` in a terminal: the switches as questions, one at a time, answers written into the
switches block of my/profile.yaml with its comments kept. Enter keeps the value shown in brackets."""
import re
import shutil
from pathlib import Path

from . import config

QUESTIONS = [
    ("goal", "Что ищешь? relocate — переезд, remote — удалёнка, both — и то и другое", "choice"),
    ("countries", "Страны переезда через запятую, первая — основная ({codes})", "countries"),
    ("offices", "Офис в других странах, куда тоже готов переехать: eu, europe, cis (СНГ и Кавказ), middle_east, "
                "americas, asia, world, коды стран через запятую или none", "offices"),
    ("visa", "Нужна рабочая виза в этих странах? needed — да, not_needed — есть гражданство или ВНЖ", "choice"),
    ("based_in", "Где живёшь сейчас (страна по-английски)", "text"),
    ("languages", "На каких языках можешь работать, через запятую (по-английски)", "list"),
    ("other_language", "Вакансия требует язык не из списка: skip — отсеять, flag — показать с пометкой, any — не смотреть",
     "choice"),
    ("level", "Твой уровень: junior, mid, senior, lead", "choice"),
    ("salary_currency", "Валюта сумм зарплаты: EUR, RUB, USD, GBP…", "currency"),
    ("salary_min", "Минимум зарплаты: visa — порог визы страны, число — свой минимум в месяц, 0 — не отсекать",
     "salary"),
    ("salary_target", "Желаемая зарплата в месяц", "int"),
    ("contract", "B2B, фриланс, почасовая ставка: skip — отсеять, penalize — ниже в списке, ok", "choice"),
    ("outsourcing", "Аутсорс и аутстафф: skip, penalize, ok", "choice"),
    ("agencies", "Рекрутеры без названия работодателя: skip, penalize, ok", "choice"),
    ("public_sector", "Госсектор и оборонка: skip, ok", "choice"),
    ("ai", "Роли про AI/LLM: prefer — выше, neutral, avoid — ниже", "choice"),
    ("cv", "Путь к резюме (.docx, .tex, .md, .pdf, .txt) или none", "cv"),
]


def current(text, key):
    m = re.search(rf"^  {key}:\s*(.*?)(?:\s{{2,}}#.*)?$", block(text), re.M)
    return m.group(1).strip() if m else ""


def block(text):
    """The switches block: from `switches:` to the first line that is not indented or a comment inside it."""
    m = re.search(r"^switches:\n((?:[ \t]+.*\n|\s*\n)*)", text, re.M)
    return m.group(0) if m else ""


def set_switch(text, key, value):
    """Replace one value in the switches block, keeping its comment."""
    old = block(text)
    pat = re.compile(rf"^(  {key}:\s*)(.*?)(\s{{2,}}#.*)?$", re.M)
    if not pat.search(old):
        return text
    new = pat.sub(lambda m: m.group(1) + value + (m.group(3) or ""), old, count=1)
    return text.replace(old, new, 1)


def fmt(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(value) + "]"
    return str(value)


def parse(kind, raw, key, cat):
    """(value, '') or (None, why)."""
    raw = raw.strip()
    if kind == "choice":
        v = raw.lower()
        return (v, "") if v in config.SWITCH_VALUES[key] else (None, "одно из: " + ", ".join(config.SWITCH_VALUES[key]))
    if kind == "bool":
        v = raw.lower()
        if v in ("y", "yes", "д", "да", "true"):
            return True, ""
        if v in ("n", "no", "н", "нет", "false"):
            return False, ""
        return None, "y или n"
    if kind == "countries":
        codes = [x.strip().lower() for x in re.split(r"[,\s]+", raw.strip("[]")) if x.strip()]
        bad = [c for c in codes if c not in cat]
        return (codes, "") if codes and not bad else (None, f"неизвестно: {', '.join(bad) or 'пусто'}")
    if kind == "offices":
        items = [x.strip().lower() for x in re.split(r"[,\s]+", raw.strip("[]")) if x.strip()]
        items = [] if items in ([], ["none"]) else items
        bad = [x for x in items if x not in config.REGIONS and x not in cat]
        return (items, "") if not bad else (None, f"неизвестно: {', '.join(bad)}")
    if kind == "currency":
        v = raw.upper()
        return (v, "") if re.fullmatch(r"[A-Z]{3}", v) else (None, "трёхбуквенный код: EUR, RUB, USD")
    if kind == "list":
        items = [x.strip() for x in raw.strip("[]").split(",") if x.strip()]
        return (items, "") if items else (None, "хотя бы один")
    if kind in ("int", "salary"):
        if kind == "salary" and raw.lower() == "visa":
            return "visa", ""
        return (int(raw), "") if raw.isdigit() else (None, "число" + (" или visa" if kind == "salary" else ""))
    if kind == "cv":
        if raw.lower() == "none":
            return "none", ""
        p = Path(raw).expanduser()
        if p.suffix.lower() not in config.CV_FORMATS:
            return None, "формат .docx, .tex, .md, .pdf или .txt"
        return str(p), ""
    return raw, ""


def run(text, my, ask=None, say=print):
    """Ask every switch; returns the profile text with the answers in. A CV outside my/ is copied into it."""
    ask = ask or input
    cat = config.catalog()
    say("Отвечай коротко; Enter — оставить значение в скобках.\n")
    goal = None
    for key, question, kind in QUESTIONS:
        if key == "countries" and goal == "remote":
            continue
        if key == "offices" and goal == "remote":
            continue
        default = current(text, key)
        while True:
            raw = ask(f"{question.format(codes=' '.join(cat))} [{default}]: ") or default
            value, why = parse(kind, raw, key, cat)
            if why:
                say(f"  не понял: {why}")
                continue
            break
        if key == "goal":
            goal = value
        if key == "cv" and value != "none":
            src = Path(value)
            if not src.is_absolute() and not src.exists():
                src = config.ROOT / value
            inside = src.resolve().is_relative_to(my.resolve()) if src.exists() else value.startswith("my/")
            if src.exists() and not inside:
                dst = my / f"cv{src.suffix.lower()}"
                shutil.copyfile(src, dst)
                say(f"  резюме скопировано в {dst}")
                value = f"my/{dst.name}"
            elif not src.exists():
                say(f"  файла {value} пока нет — положи его туда до первого «CV под вакансию»")
        text = set_switch(text, key, fmt(value))
    return text
