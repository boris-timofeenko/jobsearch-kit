import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# Trailing words that do not tell two employers apart: legal forms and countries of a local entity. The same posting
# arrives as "JustPlay GmbH" on arbeitnow and "JustPlay" on LinkedIn, "Luxoft Romania" / "Luxoft", "ZEAL Network SE" /
# "Zeal Network" (24-25.09: the owner got both cards and had already applied to one).
COMPANY_TAIL = {"gmbh", "mbh", "ag", "se", "kg", "kgaa", "co", "bv", "nv", "ltd", "limited", "llc", "inc", "corp",
                "corporation", "plc", "sa", "sas", "srl", "sarl", "spa", "sl", "slu", "lda", "oy", "ab", "as", "aps", "kft",
                "zrt", "spzoo", "sro", "doo", "group", "holding", "holdings", "international", "europe", "emea",
                "nederland", "netherlands", "germany", "deutschland", "polska", "poland", "romania", "portugal", "spain",
                "espana", "france", "italia", "italy", "uk", "bulgaria", "czech", "republic", "hungary", "belgium",
                "ireland", "greece", "cyprus"}
NAME_LINK = {"of", "de", "du", "van", "von", "del", "di", "and"}      # "Bank of Ireland" keeps its country


def company_key(name):
    s = re.sub(r"\bsp\.?\s*z\s*o\.?\s*o\.?", " spzoo ", (name or "").lower())
    s = re.sub(r"\b([a-z])\.(?=[a-z]\.)", r"\1", s).replace("b.v.", "bv").replace("n.v.", "nv")
    toks = re.findall(r"[a-z0-9]+", s)
    while len(toks) > 1 and toks[-1] in COMPANY_TAIL and toks[-2] not in NAME_LINK:
        toks.pop()
    return "".join(toks)


@dataclass
class Job:
    id: str                      # "<source>:<external id>"
    source: str
    company: str
    title: str
    url: str
    location: str = ""
    posted: str = ""             # ISO date if known
    remote: bool = False
    description: str = ""
    salary_text: str = ""
    applicants: Optional[int] = None   # LinkedIn: number of applicants at fetch time (25 = "among the first 25")
    extra: dict = field(default_factory=dict)

    # filled by the pipeline
    lang: str = ""
    salary_month: Optional[float] = None
    sponsor_name: str = ""
    sponsor_kvk: str = ""
    score: int = 0
    verdict: str = ""            # live / other / skip
    track: str = ""              # nl / remote / other
    reasons: list = field(default_factory=list)
    llm_fit: Optional[int] = None
    llm_note: str = ""
    llm_json: str = ""

    def fingerprint(self):
        """Company + title, normalized; same posting in several cities / reposts / job sites shares it."""
        norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
        title = re.sub(r"\((m|w|f|d|x|h|all genders|k|/|\s)+\)|\b(m/w/d|f/m/x|f/m/d|m/f/d|k/m|all genders)\b", "",
                       self.title, flags=re.I)
        # drop site/agency/employment-type tails only: " - Jobbird.com", " | Vollzeit & Teilzeit", " - Warszawa ... K/M"
        title = re.sub(r"\s[-–|]\s(?:[\w.\- ]*\.(?:com|nl|de|io|pl|eu)\b.*|voll?zeit.*|teilzeit.*|remote.*|hybrid.*|"
                       r"[\w ]*\([\w ]+\),?\s*polska.*|\(?rif\.?.*|ref\d*.*|\(ref.*)$", "", title, flags=re.I)
        return f"{company_key(self.company)[:40]}|{norm(title)}"

    def as_row(self):
        d = asdict(self)
        d["remote"] = int(self.remote)
        d["reasons"] = " | ".join(self.reasons)
        d.pop("extra")
        return d
