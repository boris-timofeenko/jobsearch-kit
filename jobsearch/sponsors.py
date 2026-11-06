"""IND Public Register of Recognised Sponsors (Regular Labour and Highly Skilled Migrants)."""
import difflib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

IND_URL = ("https://ind.nl/en/public-register-recognised-sponsors/"
           "public-register-regular-labour-and-highly-skilled-migrants")

LEGAL = {"bv", "nv", "cv", "vof", "cooperatie", "coöperatie", "ua", "inc", "ltd", "llc", "gmbh", "sa",
         "se", "plc", "limited", "corp", "corporation", "co", "company", "holding", "holdings", "group",
         "netherlands", "nederland", "the", "europe", "european", "eu", "emea", "international", "intl",
         "global", "benelux", "amsterdam", "rotterdam", "utrecht", "eindhoven", "den", "haag", "hague",
         "nl", "com", "io", "ai", "app", "and", "en", "van", "de", "het"}


def normalize(name):
    n = name.lower().replace("&", " and ")
    n = re.sub(r"(?<=\w)\.(?=\w|\s|$)", "", n)      # "N.V." -> "nv", "Booking.com" -> "bookingcom"
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    toks = [t for t in n.split() if t not in LEGAL]
    return "".join(toks)


class Sponsors:
    def __init__(self, cache_path, http, max_age_days=30):
        self.path = Path(cache_path)
        self.http = http
        self.max_age = timedelta(days=max_age_days)
        self.entries = []          # [(name, kvk)]
        self.by_core = {}          # normalized -> [(name, kvk)]
        self._load()

    # ---------- loading ----------
    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text())
            fetched = datetime.fromisoformat(data["fetched"])
            if datetime.now() - fetched < self.max_age:
                self._index(data["entries"])
                return
        try:
            self.refresh()
        except Exception as e:  # keep stale cache if refresh fails
            if self.path.exists():
                self._index(json.loads(self.path.read_text())["entries"])
            else:
                print(f"[sponsors] could not load IND register: {e}")

    def refresh(self):
        r = self.http.get(IND_URL)
        if not r or r.status_code != 200:
            raise RuntimeError(f"IND fetch failed: {r and r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        entries = []
        for tr in soup.select("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td and re.fullmatch(r"\d{8}", td.get_text(strip=True)):
                entries.append((th.get_text(" ", strip=True), td.get_text(strip=True)))
        if len(entries) < 1000:
            raise RuntimeError(f"IND register parse looks wrong: {len(entries)} entries")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"fetched": datetime.now().isoformat(), "entries": entries},
                                        ensure_ascii=False))
        self._index(entries)

    def _index(self, entries):
        self.entries = [tuple(e) for e in entries]
        self.by_core = {}
        for name, kvk in self.entries:
            core = normalize(name)
            if core:
                self.by_core.setdefault(core, []).append((name, kvk))

    # ---------- matching ----------
    def match(self, company):
        """Return list of (name, kvk) sponsor entries plausibly equal to `company`.
        Approximate (prefix / fuzzy) hits are returned with the name prefixed by '≈ '."""
        if not company or not self.by_core:
            return []
        core = normalize(company)
        if not core:
            return []
        if core in self.by_core:
            return self.by_core[core]
        hits = []
        if len(core) >= 6:
            ext = 12 if len(core) >= 8 else 6      # "vanderlande" -> "vanderlandeindustries"
            for k, v in self.by_core.items():
                if (k.startswith(core) and len(k) - len(core) <= ext) or \
                        (core.startswith(k) and len(k) >= 6 and len(core) - len(k) <= ext):
                    hits.extend(v)
        if not hits:
            cands = [k for k in self.by_core if k[:3] == core[:3] and abs(len(k) - len(core)) <= 2]
            for k in difflib.get_close_matches(core, cands, n=3, cutoff=0.92):
                hits.extend(self.by_core[k])
        return [("≈ " + n, k) for n, k in hits[:5]]

    def tech_like(self):
        """Sponsor names that look like software/tech companies (for ATS discovery)."""
        pat = re.compile(r"(software|tech|digital|data|labs?|cloud|\bai\b|fintech|pay|online|apps?|systems|"
                         r"solutions|analytics|robotics|cyber|networks?|platform|\.com|\.io|\.nl|studio|games)",
                         re.I)
        return [n for n, _ in self.entries if pat.search(n)]
