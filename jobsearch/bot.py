"""Telegram bot: inline buttons under each job card write statuses into the server database.

Runs as a long-polling loop (systemd `jobsearch-bot.service`). Callback data is `m:<status>:<rowid>` — rowid keeps
it under Telegram's 64-byte limit for any source id; `cv:<rowid>` builds a CV tailored to the posting (cvgen.py) in a
background thread and replies with the PDF. Text commands: /applied, /later, /stats, /mark <id> <status>, /cv <id>.
"""
import html
import json
import os
import sqlite3
import threading
import time
from datetime import datetime

import requests
import urllib3.util.connection as _urllib3_conn

from .db import DB

_urllib3_conn.HAS_IPV6 = False   # Hetzner IPv6 -> api.telegram.org delivered long-poll updates 20-40 s late; IPv4 is prompt
SESSION = requests.Session()

STATUSES = {"applied": "✅ Откликнулся", "later": "⏳ Позже", "ignored": "🙈 Скрыть", "rejected": "❌ Отказ",
            "interview": "🎤 Интервью", "offer": "🏁 Оффер", "new": "новая"}
BUTTONS = [("✅ Откликнулся", "applied"), ("⏳ Позже", "later"), ("🙈 Скрыть", "ignored")]


LOG = print
CFG = {}                   # config.yaml + profile, passed by `jobsearch bot`; cvgen needs it
CV_LOCK = threading.Lock()  # one CV at a time: one pdflatex, one model call
CV_BUSY = set()             # rowids being built, so a double click does not start a second build


def api(method, **payload):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = SESSION.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=20)
    res = r.json()
    desc = res.get("description", "")
    if not res.get("ok") and method != "getUpdates" and "message is not modified" not in desc:
        LOG(f"telegram {method} failed: {desc}")
    return res


def keyboard(rowid, current="new"):
    """Buttons for a card; after a click the chosen status is shown and the others stay available."""
    row = []
    for label, status in BUTTONS:
        text = f"• {label}" if status == current else label
        row.append({"text": text, "callback_data": f"m:{status}:{rowid}"})
    return {"inline_keyboard": [row, [{"text": "📄 CV под вакансию", "callback_data": f"cv:{rowid}"}]]}


def send_card(text, rowid, current="new", silent=False):
    return api("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text, parse_mode="HTML",
               disable_web_page_preview=True, disable_notification=silent, reply_markup=keyboard(rowid, current))


def send_text(text, reply_to=None, silent=False):
    extra = {"reply_parameters": {"message_id": reply_to, "allow_sending_without_reply": True}} if reply_to else {}
    return api("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text, parse_mode="HTML",
               disable_web_page_preview=True, disable_notification=silent, **extra)


def send_document(path, filename, caption="", reply_to=None):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    data = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption, "parse_mode": "HTML"}
    if reply_to:
        data["reply_parameters"] = json.dumps({"message_id": reply_to, "allow_sending_without_reply": True})
    with open(path, "rb") as f:
        r = SESSION.post(f"https://api.telegram.org/bot{token}/sendDocument", data=data,
                         files={"document": (filename, f, "application/pdf")}, timeout=60)
    res = r.json()
    if not res.get("ok"):
        LOG(f"telegram sendDocument failed: {res.get('description', '')}")
    return res


# ------------------------------------------------------------------ CV tailored to a posting
def start_cv(row, reply_to=None):
    """Build in a thread so polling (and status buttons) keep working; the result arrives as a reply to the card."""
    rowid = row["rowid"]
    if rowid in CV_BUSY:
        return False
    CV_BUSY.add(rowid)
    threading.Thread(target=_cv_worker, args=(row, reply_to), daemon=True).start()
    return True


def _cv_worker(row, reply_to):
    from . import cvgen
    try:
        with CV_LOCK:
            res = cvgen.build_for_job(row, CFG, log=LOG)
        LOG(f"cv: {res.pdf.name}{' (cache)' if res.cached else ''} <- {row['id']}")
        send_document(res.pdf, res.filename, res.caption, reply_to)
        if res.details:
            send_text(res.details, reply_to)
    except Exception as e:
        LOG(f"cv failed for {row['id']}: {e}")
        send_text(f"❌ CV не собралось: {html.escape(str(e))[:500]}", reply_to)
    finally:
        CV_BUSY.discard(row["rowid"])


# ------------------------------------------------------------------ handlers
def handle_callback(db, cq):
    from . import report
    data = cq.get("data", "")
    parts = data.split(":")
    if len(parts) == 2 and parts[0] == "cv":
        row = db.c.execute("SELECT rowid, * FROM jobs WHERE rowid=?", (parts[1],)).fetchone()
        if not row:
            return api("answerCallbackQuery", callback_query_id=cq["id"], text="Вакансия не найдена в базе")
        started = start_cv(dict(row), (cq.get("message") or {}).get("message_id"))
        return api("answerCallbackQuery", callback_query_id=cq["id"],
                   text="Собираю CV, минута-две" if started else "Уже собираю это CV")
    if len(parts) != 3 or parts[0] != "m":
        return api("answerCallbackQuery", callback_query_id=cq["id"])
    _, status, rowid = parts
    row = db.c.execute("SELECT * FROM jobs WHERE rowid=?", (rowid,)).fetchone()
    if not row:
        return api("answerCallbackQuery", callback_query_id=cq["id"], text="Вакансия не найдена в базе")
    db.mark(row["id"], status)
    db.commit()
    LOG(f"callback: {status} <- {row['id']} ({row['company']})")
    api("answerCallbackQuery", callback_query_id=cq["id"], text=f"{STATUSES.get(status, status)}: {row['title'][:40]}")
    msg = cq.get("message") or {}
    if not msg:
        return None
    row = db.c.execute("SELECT * FROM jobs WHERE rowid=?", (rowid,)).fetchone()
    if status == "ignored":  # collapse the card to one line; "Вернуть" restores it
        text = (f"🙈 <s>{html.escape(row['title'][:60])}</s> — {html.escape(row['company'][:30])}")
        markup = {"inline_keyboard": [[{"text": "↩️ Вернуть", "callback_data": f"m:new:{rowid}"}]]}
    else:                    # full card with a visible status line; the chosen button is marked
        text = report.telegram_card(row)
        if status != "new":
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(os.environ.get("JOBSEARCH_TZ", "Europe/Amsterdam")))
            text += f"\n\n<b>Статус: {STATUSES.get(status, status)}</b> ({now:%d.%m %H:%M})"
        markup = keyboard(rowid, status)
    api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"], text=text, parse_mode="HTML",
        disable_web_page_preview=True, reply_markup=markup)


def handle_command(db, text):
    cmd, *args = text.strip().split()
    cmd = cmd.lower().split("@")[0]
    if cmd in ("/applied", "/later", "/interview"):
        status = cmd[1:]
        rows = db.query("status=?", (status,), order="first_seen DESC", limit=30)
        if not rows:
            return send_text(f"Со статусом «{STATUSES.get(status, status)}» пока ничего.")
        lines = [f"<b>{STATUSES.get(status, status)}</b> — {len(rows)}:"]
        for r in rows:
            lines.append(f"• <a href=\"{html.escape(r['url'])}\">{html.escape(r['title'][:60])}</a> — "
                         f"{html.escape(r['company'][:30])} <i>({r['first_seen'][:10]})</i>")
        return send_text("\n".join(lines))
    if cmd == "/stats":
        total = db.c.execute("SELECT count(*) FROM jobs").fetchone()[0]
        by = db.c.execute("SELECT status, count(*) FROM jobs WHERE status != 'new' GROUP BY status").fetchall()
        live = db.c.execute("SELECT count(*) FROM jobs WHERE verdict='live' AND llm_fit >= 4").fetchone()[0]
        last = db.c.execute("SELECT max(first_seen) FROM jobs").fetchone()[0]
        lines = [f"В базе {total} вакансий, прошедших LLM с fit≥4: {live}.", f"Последнее пополнение: {last}"]
        lines += [f"{STATUSES.get(s, s)}: {n}" for s, n in by]
        return send_text("\n".join(lines))
    if cmd == "/mark" and len(args) >= 2 and args[1] in STATUSES:
        if not db.get(args[0]):
            return send_text(f"Нет вакансии с id <code>{html.escape(args[0])}</code>")
        db.mark(args[0], args[1], " ".join(args[2:]) or None)
        db.commit()
        return send_text(f"{STATUSES[args[1]]}: <code>{html.escape(args[0])}</code>")
    if cmd == "/cv" and args:
        key = args[0]
        row = db.c.execute("SELECT rowid, * FROM jobs WHERE id=? OR rowid=?", (key, key if key.isdigit() else -1)).fetchone()
        if not row:
            return send_text(f"Нет вакансии <code>{html.escape(key)}</code>")
        if start_cv(dict(row)):
            return send_text(f"Собираю CV под «{html.escape(row['title'][:60])}» — {html.escape(row['company'][:30])}")
        return send_text("Уже собираю это CV")
    if cmd in ("/start", "/help"):
        return send_text("Кнопки под карточками ставят статус, «📄 CV под вакансию» присылает PDF резюме под неё. "
                         "Команды: /applied, /later, /interview, /stats, /cv &lt;id&gt;, "
                         "/mark &lt;id&gt; applied|later|ignored|rejected|interview|offer [заметка]")
    return None


def handle_update(db, u):
    """One update from getUpdates. Whatever happens, no transaction is left open: a click that failed on the lock left
    BEGIN behind, the next click's SELECT took a snapshot inside it, and from then on every read saw the database as
    of that moment: cards from later runs answered «не найдена» (14.10–19.10, until the bot restarted)."""
    try:
        if "callback_query" in u:
            cq = u["callback_query"]
            if str(cq["from"]["id"]) == str(os.environ["TELEGRAM_CHAT_ID"]):   # only the owner may mark
                try:
                    handle_callback(db, cq)
                except sqlite3.OperationalError as e:    # a long write elsewhere held the DB past the timeout
                    LOG(f"callback {cq.get('data')} failed: {e}")
                    api("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                        text="База занята другим процессом, статус не записан. Нажми ещё раз через минуту.")
            else:
                api("answerCallbackQuery", callback_query_id=cq["id"], text="Не твой бот")
        elif "message" in u:
            m = u["message"]
            if str(m["chat"]["id"]) == str(os.environ["TELEGRAM_CHAT_ID"]) and m.get("text", "").startswith("/"):
                handle_command(db, m["text"])
    except Exception as e:
        LOG(f"update {u.get('update_id')} failed: {e}")
    finally:
        if db.c.in_transaction:
            db.c.rollback()


def run(db_path, log=print, cfg=None):
    global LOG, CFG
    LOG = log
    CFG = cfg or {}
    db = DB(db_path)
    offset = None
    log(f"bot started, chat {os.environ.get('TELEGRAM_CHAT_ID')}")
    while True:
        try:
            res = api("getUpdates", timeout=5, offset=offset, allowed_updates=["message", "callback_query"])
        except requests.RequestException as e:
            log(f"getUpdates error: {e}")
            time.sleep(10)
            continue
        for u in res.get("result", []):
            offset = u["update_id"] + 1
            handle_update(db, u)
        if not res.get("ok"):
            log(f"telegram error: {json.dumps(res)[:200]}")
            time.sleep(10)
