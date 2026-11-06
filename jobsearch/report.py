import html
from datetime import datetime
from pathlib import Path

TRACK_RU = {"eu": "🇪🇺 Другие страны ЕС (on-site / hybrid)",
            "remote_nl": "🇳🇱🌍 Remote EU у компаний с NL-юрлицом в реестре IND",
            "remote": "🌍 Remote EU", "other": "Прочее"}
TRACK_ORDER = {"eu": 1, "remote_nl": 2, "remote": 3, "other": 4, "": 4, None: 4}
PRIMARY = ""               # track code of the primary country
SPONSOR_CHECK = False      # IND register is consulted (a Dutch target and the candidate needs a visa)


def configure(profile):
    """Track names and order from the profile: primary country first, then the extra countries, EU, remote."""
    global PRIMARY, SPONSOR_CHECK
    t = profile.get("target", {})
    primary = t.get("primary")
    SPONSOR_CHECK = (profile.get("candidate") or {}).get("needs_visa", True) and any(
        c.get("sponsor_register") == "ind" for c in ([primary] if primary else []) + list(t.get("countries") or []))
    PRIMARY = primary["code"] if primary else ""
    if primary:
        TRACK_RU[PRIMARY] = t.get("track_label") or primary.get("label") or primary["name"]
        TRACK_ORDER[PRIMARY] = 0
    for key, name in (("remote_nl", "remote_entity_label"), ("remote", "remote_track_label")):
        if t.get(name):
            TRACK_RU[key] = t[name]
    if not primary:                                       # remote-only goal: remote first
        TRACK_ORDER.update({"remote": 0, "remote_nl": 0.5})
    for i, c in enumerate(t.get("countries") or []):
        TRACK_RU[c["code"]] = c.get("label", c.get("name", c["code"]))
        TRACK_ORDER[c["code"]] = 0.1 * (i + 1)          # after the primary country, before remote_nl


def run_summary(title, collected, new_jobs, fresh, assessed, notes=()):
    """First Telegram message of a run: what was collected and what happened per track; notes (throttling, a widened
    search window, a long run) go last."""
    from collections import Counter
    order = sorted(TRACK_RU, key=lambda k: TRACK_ORDER.get(k, 9))
    per = {}
    for j in new_jobs:
        d = per.setdefault(j.track or "other", Counter())
        d["new"] += 1
        d[j.verdict] += 1
        if j.llm_json:
            d["llm"] += 1
    fresh_ids = {r["id"] for r in fresh}
    for j in new_jobs:
        if j.id in fresh_ids:
            per[j.track or "other"]["sent"] += 1
    lines = [f"<b>{html.escape(title)}</b>", f"Собрано {collected}, новых {len(new_jobs)}, оценено моделью {assessed}, "
             f"в дайджест {len(fresh)}."]
    for k in order + [k for k in per if k not in order]:
        d = per.get(k)
        if not d:
            continue
        lines.append(f"{TRACK_RU.get(k, k)}: новых {d['new']}, отсеяно {d['skip'] + d['dup']}, "
                     f"на LLM {d['llm']}, в дайджест {d['sent']}")
    lines += [f"<i>{html.escape(n)}</i>" for n in notes]
    return "\n".join(lines)


def by_track(rows):
    return sorted(rows, key=lambda r: (TRACK_ORDER.get(r["track"], 2), -(r["score"] or 0)))


STATUS_RU = {"new": "новая", "applied": "откликнулся", "rejected": "отказ", "ignored": "скрыта",
             "interview": "интервью", "offer": "оффер", "later": "позже"}


def fmt_salary(r):
    return f"€{r['salary_month']:.0f}/мес" if r["salary_month"] else ""


def telegram_card(r):
    """Text of one posting for Telegram; buttons are attached by notify/bot, not here."""
    import json
    verdict_ru = {"apply": "откликаться", "maybe": "посмотреть", "skip": "мимо"}
    try:
        a = json.loads(r["llm_json"] or "{}")
    except ValueError:
        a = {}
    if r["sponsor_name"]:
        sp = f"✅ спонсор IND: {r['sponsor_name']}"
    elif r["track"] == "nl" and SPONSOR_CHECK:
        sp = "❔ не в реестре IND"
    elif r["track"] in ("remote", "remote_nl"):
        sp = "🌐 remote"
    else:
        sp = ""
    mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "офис"}.get(a.get("work_mode"), "")
    scope = a.get("remote_scope") or ""
    keys = r.keys()
    appl = r["applicants"] if "applicants" in keys else None
    appl_txt = f"👥 {appl} откликов" if appl is not None else ""
    bits = [b for b in [r["location"], mode + (f" ({scope})" if scope else ""), fmt_salary(r), sp, appl_txt] if b]
    fit = f"fit {r['llm_fit']}/10" if r["llm_fit"] is not None else "без LLM"
    verdict = verdict_ru.get(a.get("verdict"), "")
    lines = [f"<b>{TRACK_RU.get(r['track'], 'Прочее')}</b>",
             f"<b>{fit}</b>{' · ' + verdict if verdict else ''} · <a href=\"{html.escape(r['url'])}\">"
             f"{html.escape(r['title'])}</a> — {html.escape(r['company'])}",
             f"<i>{html.escape(' · '.join(bits))}</i>"]
    if r["llm_note"]:
        lines.append(html.escape(r["llm_note"]))
    flags = [x for x in (r["reasons"] or "").split(" | ") if x and not x.startswith(("LLM: слабое", "NL-юрлицо", "откликов на LinkedIn"))]
    if flags:
        lines.append("⚠️ " + html.escape(" · ".join(flags))[:300])
    return "\n".join(lines)


def telegram_digest(rows, title):
    """One card per posting: fit, verdict, where/how, sponsor, salary, the model's note, and flags worth knowing."""
    import json
    if not rows:
        return f"<b>{html.escape(title)}</b>\nНовых подходящих вакансий нет."
    lines = [f"<b>{html.escape(title)}</b>: {len(rows)} новых"]
    cur = None
    verdict_ru = {"apply": "откликаться", "maybe": "посмотреть", "skip": "мимо"}
    for r in by_track(rows):
        if r["track"] != cur:
            cur = r["track"]
            lines.append(f"\n<b>— {TRACK_RU.get(cur, 'Прочее')} —</b>")
        try:
            a = json.loads(r["llm_json"] or "{}")
        except ValueError:
            a = {}
        sp = f"✅ спонсор IND: {r['sponsor_name']}" if r["sponsor_name"] else ("🌐 remote" if r["remote"] else ("❔ не в реестре IND" if r["track"] == "nl" and SPONSOR_CHECK else ""))
        mode = {"remote": "remote", "hybrid": "hybrid", "onsite": "офис"}.get(a.get("work_mode"), "")
        scope = a.get("remote_scope") or ""
        bits = [b for b in [r["location"], mode + (f" ({scope})" if scope else ""), fmt_salary(r), sp] if b]
        fit = f"fit {r['llm_fit']}/10" if r["llm_fit"] is not None else "без LLM"
        verdict = verdict_ru.get(a.get("verdict"), "")
        lines.append(f"\n<b>{fit}</b>{' · ' + verdict if verdict else ''} · <a href=\"{html.escape(r['url'])}\">"
                     f"{html.escape(r['title'])}</a> — {html.escape(r['company'])}\n<i>{html.escape(' · '.join(bits))}</i>")
        if r["llm_note"]:
            lines.append(html.escape(r["llm_note"]))
        flags = [x for x in (r["reasons"] or "").split(" | ") if x and not x.startswith(("LLM: слабое", "NL-юрлицо", "откликов на LinkedIn"))]
        if flags:
            lines.append("⚠️ " + html.escape(" · ".join(flags))[:300])
        lines.append(f"<code>mark {r['id']} applied</code>")
    return "\n".join(lines)


def markdown(rows, title):
    out = [f"# {title}", "", f"_{_now():%Y-%m-%d %H:%M}_ · {len(rows)} вакансий", "",
           "| Score | Трек | Вакансия | Компания | Локация | Зарплата | Спонсор | Статус | Заметки |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in by_track(rows):
        sp = f"✅ {r['sponsor_name']} ({r['sponsor_kvk']})" if r["sponsor_name"] else ("remote" if r["remote"] else "—")
        llm = f" (LLM {r['llm_fit']})" if r["llm_fit"] is not None else ""
        notes = " · ".join(x for x in [r["reasons"], r["llm_note"]] if x)
        out.append(f"| {r['score']}{llm} | {r['track'] or ''} | [{_c(r['title'])}]({r['url']}) | {_c(r['company'])} | {_c(r['location'])} | "
                   f"{fmt_salary(r)} | {_c(sp)} | {STATUS_RU.get(r['status'], r['status'])} | {_c(notes)} |")
    return "\n".join(out) + "\n"


def html_report(rows, title):
    trs = []
    cur = None
    for r in by_track(rows):
        if r["track"] != cur:
            cur = r["track"]
            trs.append(f"<tr class=sec><td colspan=8>{TRACK_RU.get(cur, 'Прочее')}</td></tr>")
        sp = f"✅ {html.escape(r['sponsor_name'])}<br><small>KVK {r['sponsor_kvk']}</small>" if r["sponsor_name"] \
            else ("🌐 remote" if r["remote"] else "—")
        cls = "skip" if r["verdict"] == "skip" else ("other" if r["verdict"] == "other" else "")
        llm = f"<br><small>LLM {r['llm_fit']}/10</small>" if r["llm_fit"] is not None else "<br><small>без LLM</small>"
        notes = "<br>".join(html.escape(x) for x in [r["reasons"], r["llm_note"]] if x)
        trs.append(f"<tr class='{cls}'><td class=num>{r['score']}{llm}</td>"
                   f"<td><a href='{html.escape(r['url'])}' target=_blank>{html.escape(r['title'])}</a>"
                   f"<br><small>{r['source']} · {r['posted'] or r['first_seen'][:10]} · <code>{r['id']}</code></small></td>"
                   f"<td>{html.escape(r['company'])}</td><td>{html.escape(r['location'])}</td>"
                   f"<td>{fmt_salary(r)}</td><td>{sp}</td><td>{STATUS_RU.get(r['status'], r['status'])}</td>"
                   f"<td class=notes>{notes}</td></tr>")
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>
<style>body{{font:14px -apple-system,Segoe UI,sans-serif;margin:24px;color:#222;background:#fff}}a{{color:#0645ad}}table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}}th{{background:#f4f4f4;position:sticky;top:0}}
tr.skip{{opacity:.45}}tr.other td{{background:#fafafa}}.num{{font-weight:700;font-size:16px}}.notes{{max-width:380px;color:#7a4b00}}
small{{color:#777}}tr.sec td{{background:#e8eef7;font-weight:700;font-size:15px;padding:12px 8px}}code{{font-size:11px;color:#999}}</style>
<h1>{html.escape(title)}</h1><p>{_now():%Y-%m-%d %H:%M} · {len(rows)} вакансий. Отметить:
<code>.venv/bin/python -m jobsearch mark &lt;id&gt; applied</code></p>
<table><tr><th>Score</th><th>Вакансия</th><th>Компания</th><th>Локация</th><th>Зарплата</th><th>Спонсор</th><th>Статус</th><th>Заметки</th></tr>
{''.join(trs)}</table>"""


def _now():
    import os
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(os.environ.get("JOBSEARCH_TZ", "Europe/Amsterdam")))


def write_reports(rows, out_dir, title, stamp=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = stamp or _now().strftime("%Y-%m-%d")
    (out / f"{stamp}.md").write_text(markdown(rows, title))
    page = html_report(rows, title)
    (out / f"{stamp}.html").write_text(page)      # dated copy: history is kept
    (out / "latest.html").write_text(page)         # always the most recent report
    return out / f"{stamp}.md", out / f"{stamp}.html"


def _c(s):
    return (s or "").replace("|", "/").replace("\n", " ")
