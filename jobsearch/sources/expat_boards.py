"""English-language NL job boards for expats. Small volume, but every posting is by definition English-friendly."""
import re

from bs4 import BeautifulSoup

from ..models import Job

IAE_URLS = ["https://www.iamexpat.nl/career/jobs-netherlands/it-technology-positions"]
UND_URL = "https://undutchables.nl/vacancies"


def iamexpat(http):
    out = []
    for url in IAE_URLS:
        r = http.get(url)
        if not r or r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='/career/jobs-netherlands/']"):
            href = a.get("href", "")
            if href.count("/") < 5:
                continue
            parts = [t.strip() for t in a.get_text("|", strip=True).split("|") if t.strip()]
            if not parts:
                continue
            title = parts[0]
            # card text: Title | [Language] | [City] | IT & technology | City | Posted date ...
            cat = next((i for i, p in enumerate(parts) if "technology" in p.lower()), None)
            loc = parts[cat + 1] if cat is not None and cat + 1 < len(parts) and "Posted" not in parts[cat + 1] else "Netherlands"
            posted = ""
            m = re.search(r"Posted date (\w+ \d{1,2}, \d{4})", a.get_text(" ", strip=True))
            if m:
                try:
                    from datetime import datetime
                    posted = datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    pass
            jid = href.rstrip("/").rsplit("/", 1)[-1]
            out.append(Job(id=f"iamexpat:{jid}", source="iamexpat", company="(IamExpat: см. вакансию)", title=title,
                           url="https://www.iamexpat.nl" + href if href.startswith("/") else href,
                           location=loc + ", Netherlands" if "Netherlands" not in loc else loc, posted=posted,
                           remote="remote" in " ".join(parts).lower()))
    return out


def undutchables(http):
    r = http.get(UND_URL)
    if not r or r.status_code != 200:
        return []
    out = []
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.vacancy-item"):
        title = a.find("h4")
        loc = a.select_one(".location")
        href = a.get("href", "")
        if not title or not href:
            continue
        out.append(Job(id=f"undutchables:{href.rstrip('/').rsplit('/', 1)[-1]}", source="undutchables",
                       company="Undutchables (агентство, клиент в вакансии)", title=title.get_text(strip=True),
                       url=href, location=(loc.get_text(strip=True) if loc else "") + ", Netherlands"))
    return out


EXPAT_BOARDS = {"iamexpat": iamexpat, "undutchables": undutchables}
