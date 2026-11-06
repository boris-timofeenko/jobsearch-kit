import random
import time
from collections import Counter
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class Http:
    """requests.Session with polite pacing and 429 handling.

    LinkedIn's guest API sheds ~20% of requests with 429 for a day or more at a time (episodes since 10.10, no
    Retry-After). The old backoff (penalty up to 8, retry after 2-6 minutes) turned that into 20-35 s per request and
    a 15-hour deep run; a 429 now costs a short jittered wait and the pacing at most doubles."""
    MAX_PENALTY = 4

    def __init__(self, delay=(0.6, 1.4), timeout=30):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,nl;q=0.5"})
        self.delay = delay
        self.timeout = timeout
        self.penalty = 0          # grows on 429s, slows every following request; decays on success
        self.stats = {}           # host group -> Counter(req, ok, 429, 5xx, other, error, gave_up, wait_s)

    def get(self, url, **kw):
        return self._req("GET", url, **kw)

    def post(self, url, **kw):
        return self._req("POST", url, **kw)

    def _req(self, method, url, retries=5, **kw):
        st = self.stats.setdefault(host_group(url), Counter())
        for i in range(retries):
            st["req"] += 1
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException:
                st["error"] += 1
                self._wait(st, 2 * (i + 1))
                continue
            if r.status_code == 429:
                st["429"] += 1
                self.penalty = min(self.penalty + 1, self.MAX_PENALTY)
                self._wait(st, random.uniform(8, 15) * (i + 1))
                continue
            if r.status_code >= 500:
                st["5xx"] += 1
                self._wait(st, 6 * (i + 1))
                continue
            st["ok" if r.status_code == 200 else "other"] += 1
            if self.penalty and r.status_code == 200 and random.random() < 0.25:
                self.penalty -= 1
            return r
        st["gave_up"] += 1
        return None

    def _wait(self, st, seconds):
        st["wait_s"] += seconds
        time.sleep(seconds)

    def sleep(self):
        time.sleep(random.uniform(*self.delay) * (1 + 0.25 * self.penalty))

    def summary(self, group="linkedin"):
        """One line for the run log and the Telegram summary; empty when the group was not contacted."""
        st = self.stats.get(group)
        if not st or not st["req"]:
            return ""
        share = 100 * st["429"] / st["req"]
        parts = [f"{st['req']} запросов", f"429: {st['429']} ({share:.0f}%)"]
        if st["5xx"] + st["other"] + st["error"]:
            parts.append(f"прочие ошибки {st['5xx'] + st['other'] + st['error']}")
        if st["gave_up"]:
            parts.append(f"без ответа {st['gave_up']}")
        if st["wait_s"] >= 60:
            parts.append(f"ожидание после ошибок {st['wait_s'] / 60:.0f} мин")
        return ", ".join(parts)


def host_group(url):
    host = urlparse(url).hostname or ""
    return "linkedin" if host == "linkedin.com" or host.endswith(".linkedin.com") else "other"
