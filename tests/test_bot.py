import sqlite3

import pytest

from jobsearch import bot
from jobsearch.db import DB

OWNER = 42


@pytest.fixture
def answers(monkeypatch):
    """Texts the bot showed in reply to clicks (answerCallbackQuery), in order."""
    shown = []
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(OWNER))
    monkeypatch.setattr(bot, "api", lambda method, **kw: shown.append(kw.get("text")) or {"ok": True})
    return shown


@pytest.fixture
def db(tmp_path):
    db = DB(tmp_path / "jobs.db")
    db.c.execute("PRAGMA busy_timeout=50")   # fail fast instead of the 30 s production timeout
    return db


def add_posting(conn, job_id):
    rowid = conn.execute("INSERT INTO jobs (id, company, title) VALUES (?, 'Acme', 'Senior QA Engineer')",
                         (job_id,)).lastrowid
    conn.commit()
    return rowid


def click(status, rowid):
    return {"update_id": rowid, "callback_query": {"id": f"cq{rowid}", "from": {"id": OWNER},
                                                   "data": f"m:{status}:{rowid}"}}


def test_clicks_failed_on_lock_do_not_hide_postings_from_later_runs(db, answers, tmp_path):
    old = add_posting(db.c, "linkedin:1")
    run = sqlite3.connect(tmp_path / "jobs.db")
    run.execute("BEGIN IMMEDIATE")            # a collector run holding the write lock

    bot.handle_update(db, click("applied", old))
    bot.handle_update(db, click("applied", old))   # the repeat click took a snapshot inside the unfinished transaction
    fresh = add_posting(run, "linkedin:2")         # the run commits and sends a card for its new posting
    bot.handle_update(db, click("applied", fresh))

    assert answers[-1].startswith("✅ Откликнулся")
    assert db.get("linkedin:2")["status"] == "applied"
