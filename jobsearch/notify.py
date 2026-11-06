import os
import requests


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def quiet(spec, now):
    """Is `now` (local time) inside quiet hours like "00:00-08:00"? Messages then arrive without a sound."""
    if not spec:
        return False
    a, b = (int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in spec.split("-"))
    m = now.hour * 60 + now.minute
    return a <= m < b if a <= b else (m >= a or m < b)


def telegram(text, silent=False):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    ok = True
    for chunk in _chunks(text, 3900):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                                "disable_web_page_preview": True, "disable_notification": silent}, timeout=30)
        ok = ok and r.status_code == 200
    return ok


def _chunks(text, n):
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > n:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        out.append(cur)
    return out


def telegram_cards(title, rows, db, silent=False):
    """Header message, then one message per job with status buttons (needs the bot service to handle clicks)."""
    from . import report
    from .bot import send_card, send_text
    if not rows:
        return True
    ok = bool(send_text(f"<b>{title}</b>: {len(rows)} новых", silent=silent).get("ok")) if title else True
    for r in rows:
        rowid = db.c.execute("SELECT rowid FROM jobs WHERE id=?", (r["id"],)).fetchone()[0]
        res = send_card(report.telegram_card(r), rowid, r["status"] or "new", silent=silent)
        ok = ok and bool(res.get("ok"))
    return ok
