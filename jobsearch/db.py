import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, url TEXT,
  location TEXT, posted TEXT, remote INTEGER, description TEXT, salary_text TEXT,
  lang TEXT, salary_month REAL, sponsor_name TEXT, sponsor_kvk TEXT,
  score INTEGER, verdict TEXT, track TEXT, reasons TEXT, llm_fit INTEGER, llm_note TEXT,
  status TEXT DEFAULT 'new', note TEXT DEFAULT '', fingerprint TEXT DEFAULT '', llm_json TEXT DEFAULT '', applicants INTEGER,
  first_seen TEXT, last_seen TEXT, notified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_verdict ON jobs(verdict, score);
-- when each LinkedIn search (query x location) last ran to the end: the next run widens its time window to reach back
-- here, so a skipped or cut-short run leaves no gap
CREATE TABLE IF NOT EXISTS coverage (
  location TEXT, query TEXT, remote INTEGER, searched_at TEXT,
  PRIMARY KEY (location, query, remote)
);
-- posts of Telegram job channels (sources/telegram.py): the newest stored id is where the next run starts reading;
-- candidate = a line passes the role's title filter; extracted = the model's vacancies as JSON, NULL = not parsed yet
CREATE TABLE IF NOT EXISTS tg_posts (
  channel TEXT, msg_id INTEGER, posted TEXT, text TEXT, links TEXT, candidate INTEGER, extracted TEXT, seen_at TEXT,
  page TEXT,                  -- job page a short post links to, loaded before parsing; NULL = not loaded yet
  PRIMARY KEY (channel, msg_id)
);
"""

COLS = ["id", "source", "company", "title", "url", "location", "posted", "remote", "description",
        "salary_text", "lang", "salary_month", "sponsor_name", "sponsor_kvk", "score", "verdict", "track",
        "reasons", "llm_fit", "llm_note"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path, check_same_thread=False, timeout=30)  # writes serialized by callers / busy timeout
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")       # bot and collector can read/write concurrently
        self.c.executescript(SCHEMA)
        cols = {r[1] for r in self.c.execute("PRAGMA table_info(jobs)")}
        if "track" not in cols:  # migration for early databases
            self.c.execute("ALTER TABLE jobs ADD COLUMN track TEXT DEFAULT ''")
        if "applicants" not in cols:
            self.c.execute("ALTER TABLE jobs ADD COLUMN applicants INTEGER")
        if "llm_json" not in cols:
            self.c.execute("ALTER TABLE jobs ADD COLUMN llm_json TEXT DEFAULT ''")
        if "fingerprint" not in cols:
            self.c.execute("ALTER TABLE jobs ADD COLUMN fingerprint TEXT DEFAULT ''")
            self.c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fp ON jobs(fingerprint)")

    def known_ids(self):
        return {r[0] for r in self.c.execute("SELECT id FROM jobs")}

    def get(self, job_id):
        return self.c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def touch(self, job_id):
        self.c.execute("UPDATE jobs SET last_seen=? WHERE id=?", (now(), job_id))

    def fingerprints(self):
        """fingerprint -> ids of the non-duplicate rows carrying it, earliest first (several only for intermediaries
        whose different postings share company + title)."""
        out = {}
        for fp, jid in self.c.execute("SELECT fingerprint, id FROM jobs WHERE fingerprint != '' AND verdict != 'dup' "
                                      "ORDER BY first_seen"):
            out.setdefault(fp, []).append(jid)
        return out

    def add_location(self, job_id, location):
        r = self.get(job_id)
        if r and location and location not in (r["location"] or ""):
            self.c.execute("UPDATE jobs SET location=? WHERE id=?", ((r["location"] + " / " + location)[:300], job_id))

    def insert(self, job):
        row = job.as_row()
        row["first_seen"] = row["last_seen"] = now()
        row["fingerprint"] = job.fingerprint()
        cols = COLS + ["first_seen", "last_seen", "fingerprint"]
        self.c.execute(
            f"INSERT OR IGNORE INTO jobs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols])

    def update_analysis(self, job):
        row = job.as_row()
        self.c.execute(
            "UPDATE jobs SET lang=?, salary_month=?, sponsor_name=?, sponsor_kvk=?, score=?, verdict=?, track=?, "
            "reasons=?, llm_fit=?, llm_note=?, llm_json=COALESCE(NULLIF(?, ''), llm_json), "
            "description=COALESCE(NULLIF(?, ''), description), salary_text=COALESCE(NULLIF(?, ''), salary_text), "
            "applicants=COALESCE(?, applicants) WHERE id=?",
            (row["lang"], row["salary_month"], row["sponsor_name"], row["sponsor_kvk"], row["score"],
             row["verdict"], row["track"], row["reasons"], row["llm_fit"], row["llm_note"], row["llm_json"],
             row["description"], row["salary_text"], row["applicants"], job.id))

    def mark(self, job_id, status, note=None):
        if note is None:
            self.c.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        else:
            self.c.execute("UPDATE jobs SET status=?, note=? WHERE id=?", (status, note, job_id))
        return self.c.total_changes

    def mark_notified(self, ids):
        self.c.executemany("UPDATE jobs SET notified=1 WHERE id=?", [(i,) for i in ids])

    def coverage(self):
        """(location, query, remote) -> ISO time the search last ran to the end."""
        return {(r[0], r[1], bool(r[2])): r[3] for r in
                self.c.execute("SELECT location, query, remote, searched_at FROM coverage")}

    def set_coverage(self, items):
        self.c.executemany("INSERT OR REPLACE INTO coverage (location, query, remote, searched_at) VALUES (?, ?, ?, ?)",
                           [(loc, q, int(remote), at) for (loc, q, remote), at in items.items()])

    def assessed_by_company(self):
        """Company name -> (LLM assessments, best final fit, owner touched it: any status but new)."""
        return {r[0]: (r[1], r[2], bool(r[3])) for r in self.c.execute(
            "SELECT company, count(*), max(llm_fit), sum(status != 'new') FROM jobs WHERE llm_json != '' GROUP BY company")}

    def tg_last_ids(self):
        return {r[0]: r[1] for r in self.c.execute("SELECT channel, max(msg_id) FROM tg_posts GROUP BY channel")}

    def tg_save(self, posts, candidate):
        self.c.executemany(
            "INSERT OR IGNORE INTO tg_posts (channel, msg_id, posted, text, links, candidate, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(p.channel, p.id, p.date, p.text, json.dumps(p.links), int(candidate(p)), now()) for p in posts])

    def tg_pending(self, since, limit):
        """Candidate posts the model has not parsed yet (a failed or skipped parse stays pending), oldest first."""
        return self.c.execute("SELECT * FROM tg_posts WHERE candidate=1 AND extracted IS NULL AND posted >= ? "
                              "ORDER BY posted LIMIT ?", (since, limit)).fetchall()

    def tg_set_page(self, channel, msg_id, text):
        self.c.execute("UPDATE tg_posts SET page=? WHERE channel=? AND msg_id=?", (text, channel, msg_id))

    def tg_set_extracted(self, channel, msg_id, vacancies_json):
        self.c.execute("UPDATE tg_posts SET extracted=? WHERE channel=? AND msg_id=?", (vacancies_json, channel, msg_id))

    def tg_parsed(self, since):
        return self.c.execute("SELECT * FROM tg_posts WHERE extracted IS NOT NULL AND extracted != '[]' "
                              "AND posted >= ? ORDER BY posted", (since,)).fetchall()

    def query(self, where="1=1", params=(), order="score DESC, first_seen DESC", limit=500):
        return self.c.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY {order} LIMIT {limit}", params).fetchall()

    def commit(self):
        self.c.commit()
