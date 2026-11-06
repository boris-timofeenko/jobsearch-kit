"""Cheap triage before the model: language, level, sponsorship, salary, location track, score. Nothing is deleted;
every skip carries a reason. Everything about the person and the role comes from my/profile.yaml via configure()."""
import re

I = re.I

RELEVANT_TITLE = re.compile(
    r"\b(qa|sdet|test(s|ing|er)?|tests?\b|quality (assurance|engineer|automation|analyst)|software quality|"
    r"test automation|automation (test|qa|engineer)|engineer in test|kwaliteit|testautomati|testengineer|"
    r"testanalist|testconsultant|quality engineering|softwaretester|\w+tester)\b", I)
NOT_RELEVANT_TITLE = re.compile(
    r"\b(a/?b test|penetration|pentest|quality manager|product manager|account|sales|marketing|"
    r"recruiter|copywriter|designer|nurse|clinical|laborator|lab technician|food|chemist|welder|electrical|"
    r"mechanical|civil|hvac|devops|network|infrastructure|sre|site reliability|risk|compliance|rpa|"
    r"process automation|workflow automation|marketing automation|cloud automation|data engineer|"
    r"data analyst|business analyst|financial analyst|"
    r"release manager|devsecops|functioneel|tijdelijk|qaqc|mb testing|board testing|ict beheer|audit|"
    r"technician|seal testing|test bench|testsysteme|canoe|security testing|dast)\b", I)
GERMAN_TITLE = re.compile(r"\b(testautomatisierer\w*|testingenieur|softwareentwickler|testmanager\w*|"
                          r"mit karriere\w*|für|und|qualitätssicherung|prüf\w*)\b", I)
NON_EU_REMOTE = re.compile(r"\b(us|usa|u\.s\.|united states|us-remote|north america|americas|canada|india|"
                           r"latam|apac|australia|singapore|philippines|brazil|mexico|argentina|colombia|"
                           r"pakistan|vietnam|indonesia|africa|south africa|nigeria|egypt|uae|dubai|israel)\b", I)
EU_LOC = re.compile(
    r"\b(austria|österreich|belgium|bulgaria|croatia|cyprus|czechia|czech republic|denmark|estonia|finland|france|germany|"
    r"greece|hungary|ireland|italy|italia|latvia|lithuania|luxembourg|malta|netherlands|poland|polska|portugal|romania|"
    r"slovakia|slovenia|spain|españa|sweden|norway|switzerland|iceland|liechtenstein|"
    r"warsaw|warszawa|krak[oó]w|wroc[lł]aw|gda[nń]sk|pozna[nń]|[lł][oó]d[zź]|katowice|madrid|barcelona|valencia|m[aá]laga|"
    r"lisbon|lisboa|porto|milan|milano|rome|roma|turin|torino|vienna|wien|prague|praha|brno|budapest|bucharest|bucure[sș]ti|"
    r"cluj|ia[sș]i|timi[sș]oara|sofia|plovdiv|athens|thessaloniki|dublin|cork|galway|stockholm|gothenburg|malm[oö]|"
    r"copenhagen|k[oø]benhavn|aarhus|helsinki|oslo|zurich|z[uü]rich|geneva|basel|tallinn|riga|vilnius|ljubljana|zagreb|"
    r"bratislava|nicosia|limassol|valletta|european union|europe|eu)\b", I)
EU_HINT = re.compile(r"\b(europe|european|eu|emea|netherlands|nl|amsterdam|germany|berlin|spain|portugal|lisbon|"
                     r"poland|cyprus|serbia|belgrade|remote - eu|cet|eet)\b", I)

SENIOR = re.compile(r"\b(senior|sr\.?|lead|staff|principal|head of|architect|manager|tech lead|team lead)\b", I)
JUNIOR_TITLE = re.compile(r"\b(junior|jr\.?|intern(ship)?|trainee|graduate|entry[- ]level|werkstudent|"
                          r"stagiair|stage|student|apprentice|starter)\b", I)
MEDIOR = re.compile(r"\b(medior|mid[- ]level|associate)\b", I)

CLEARANCE = re.compile(r"\b(security clearance|clearance|nato|aivd|mivd|veiligheidsonderzoek|vgb|"
                       r"ministry of defen[cs]e|ministerie van defensie|defensie|top secret|secret level|"
                       r"dutch nationality|nederlandse nationaliteit)\b", I)
NON_EN_TITLE = re.compile(r"[ěščřžůňťďłąęśźżńćųėįčšž]|\b(tester/?ka|testerka|testovac\w*|inžinier|inzynier|"
                          r"specialistas|zleceniobiorca|ingénieur|ingeniero|ingegnere|collaudatore|testeur|"
                          r"analista de pruebas|pruebas|probador|tesztel\w*|testaus\w*|testare)\b", re.I)
DUTCH_TITLE = re.compile(r"\b(kwaliteits\w*|ingenieur|medewerker|functioneel|testcoördinator|testcoordinator|"
                         r"tester gezocht|softwaretester|testspecialist|testautomatiseerder|adviseur|"
                         r"zoekt|gezocht|vacature)\b", I)
FREELANCE = re.compile(r"\b(freelance|freelancer|zzp|interim|contractor|contract role|b2b contract|"
                       r"opdracht|inhuur|detachering)\b", I)
NO_SPONSOR = re.compile(
    r"\b(eea|eu|european) (nationals?|citizens?|passport( holders?)?|residents?)( only)?\b|"
    r"\b(only|exclusively) (for )?(candidates )?(with|holding|who (have|hold)) (a |an )?(valid )?"
    r"(eu|eea|dutch|nl|netherlands) (work(ing)? permit|right to work|citizenship|residen)|"
    r"\bmust (already )?(have|hold|possess) (a |an )?(valid )?(eu|eea|dutch|nl|netherlands|existing) "
    r"(work(ing)? permit|right to work|residen|citizenship)|"
    r"\b(no|without) (visa )?sponsorship\b|"
    r"\b(do not|don'?t|cannot|can'?t|are unable to|are not able to|will not|won'?t) (offer|provide|support|"
    r"sponsor) (a |any )?(visa|work permit|relocation|sponsorship)|"
    r"\bnot able to sponsor\b|\bsponsorship (is )?not (available|possible|offered)\b|"
    r"\balready (based|located|living|residing) in (the )?(netherlands|nl|eu|europe)\b|"
    r"\b(must|should|need to|required to|have to) already be (based|located|living|residing|resident) in\b|"
    r"\bcurrently (live|living|based|located|reside|residing) in\b|"
    r"\b(only|exclusively) (for )?(candidates|applicants|people|those) (residing|based|located|living|who live|who reside) in\b|"
    r"\blocal candidates only\b|\bresidents? of [A-Z][a-z]+ only\b|\bno relocation\b|"
    r"\b(right|eligib\w+|authori[sz]\w+|permit) to work in (the )?(uk|united kingdom|us|usa|poland|germany|spain|portugal|"
    r"italy|france|ireland|romania|bulgaria|hungary|czech\w*|greece|lithuania|latvia|estonia|sweden|denmark|finland|"
    r"austria|belgium|switzerland|serbia|cyprus)\b|"
    r"\bwork permit (is )?(required|mandatory|needed)\b|\bvalid (work|working) (permit|visa|authori[sz]ation) (for|in)\b", I)
# "Must be based in X": for a job in a target country or on-site/hybrid elsewhere in the EU that is where the candidate
# would move, so only a flag; for remote jobs it still closes the door (decided in analyze once the track is known).
LOCAL_ONLY = re.compile(
    r"\b((must|should|need to|required to|have to) (be )?(based|located|living|residing|reside|live|resident) in|"
    r"(candidates|applicants) (must|should) (be )?(residents?|based|located|living) (of|in))\b[^.;\n]{0,40}", I)
# A "must live in …" requirement (heuristic match or the model's residency quote) closes a relocation-track job only
# when it is about who may apply rather than where the job is: "only" next to candidates/residents, citizenship or an
# existing permit (several languages, quotes are copied from postings), "EU residency", "outside … won't be considered",
# a fully remote job for residents of one EU country, or a country other than the job's own. Checked 24.09 on 291
# residency skips: "has to be in Portugal, hybrid", "strictly on-site in Sofia", "remote-first within Germany" open up;
# "candidates based in Portugal or UK" for a Milan office, "work from Slovenia" for a French posting stay closed.
RESIDENCY_HARD = re.compile(
    r"\b(candidates|applicants|residents|people|those)\b[^.;]{0,30}\bonly\b|"
    r"\b(only|exclusively)\b[^.;]{0,20}\b(candidates|applicants|residents|people|those)\b|"
    r"\b(currently|already|existing|local (candidates|applicants|hiring|hires|talent)|hire locally|citizen\w*|nationalit\w*|nationals?|passport|right to work|"
    r"work(ing)? permit|permit to work|residence permit|authori[sz]\w*|eligib\w*|visas?|sponsor\w*|relocat\w*|eu|eea|"
    r"european union|outside|not be considered|won'?t be considered|cittadinanza|nationalité|staatsangehörigkeit|"
    r"staatsbürger\w*|nationaliteit|obywatel\w*|ciudadan\w*|cidadania|partita iva)\b", I)
# The same for a candidate who needs no visa (EU/EEA citizen): citizenship, permits and sponsorship stop mattering,
# "already living there" and "local hiring" still close the job.
RESIDENCY_HARD_NO_VISA = re.compile(
    r"\b(candidates|applicants|residents|people|those)\b[^.;]{0,30}\bonly\b|"
    r"\b(only|exclusively)\b[^.;]{0,20}\b(candidates|applicants|residents|people|those)\b|"
    r"\b(currently|already|existing|local (candidates|applicants|hiring|hires|talent)|hire locally|outside|"
    r"not be considered|won'?t be considered)\b", I)
REMOTE_JOB = re.compile(r"\b(fully|100 ?%) remote\b|\bremote[- ]only\b|\bremote (role|position|job)\b", I)
NON_EU_PLACE = re.compile(r"\b(usa|u\.s\.|united states|north america|canada|india|bengaluru|bangalore|hyderabad|pune|"
                          r"chennai|uk|united kingdom|london|australia|singapore|brazil|mexico|israel|uae|dubai|turkey|"
                          r"istanbul)\b", I)
AGENCY = re.compile(r"\b(our client|for a client|one of our clients|on behalf of (our|a) client|onze opdrachtgever|"
                    r"voor onze klant|our customer is looking|staffing|recruitment agency|detacheer|"
                    r"we are recruiting on behalf)\b", I)
# Intermediaries that hide the employer (Jobgether: "listed on behalf of a partner company") reuse generic titles for
# different clients, so company + title is not enough to call two postings the same (see same_posting)
PARTNER_LISTING = re.compile(r"\bon behalf of (a|our|one of our) (partner|client)", I)
REMOTE = re.compile(r"\b(remote|emea|europe|european union|eu|anywhere|worldwide|work from home|wfh|hybrid)\b", I)
NL_LOC = re.compile(r"\b(netherlands|nederland|holland|amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|"
                    r"groningen|leiden|delft|haarlem|amstelveen|hilversum|nijmegen|tilburg|breda|arnhem|"
                    r"zwolle|enschede|maastricht|almere|apeldoorn|hoofddorp|schiphol|veldhoven|'s-hertogenbosch|"
                    r"den bosch|amersfoort|zeist|\bnl\b)", I)

STACK = [(re.compile(p, I), w) for p, w in [
    (r"playwright", 4), (r"typescript", 3), (r"javascript|node\.?js", 2), (r"appium|patrol|mobile", 3),
    (r"flutter|dart", 3), (r"python|pytest", 2), (r"cucumber|gherkin|bdd", 2), (r"wiremock|api test", 2),
    (r"k6|jmeter|performance test", 1), (r"github actions|gitlab ci|ci/cd|jenkins", 1),
    (r"kubernetes|docker|gcp", 1), (r"fintech|payments?|banking|psd2", 3), (r"travel|booking", 1),
    (r"\bllm|ai[- ]agent|generative|genai|machine learning", 3), (r"cypress|selenium|webdriver", 1),
    (r"relocation|visa sponsorship|highly skilled migrant|kennismigrant|30% ruling", 6),
]]

NL_WORDS = {"de", "het", "een", "en", "van", "je", "jij", "jouw", "wij", "onze", "voor", "met", "niet", "bij",
            "als", "zijn", "ons", "werken", "ervaring", "functie", "kennis", "worden", "wordt", "ook", "naar",
            "dat", "deze", "dit", "over", "wat", "kun", "kunt", "goed", "uur", "week", "salaris", "sollicit"}
EN_WORDS = {"the", "and", "you", "our", "with", "for", "will", "are", "that", "this", "team", "experience",
            "work", "have", "your", "role", "about", "skills", "years", "we", "is", "in", "to", "of", "a"}


DE_WORDS = {"und", "der", "die", "das", "mit", "für", "wir", "sie", "du", "dich", "dein", "deine", "ist", "sind",
            "nicht", "auch", "bei", "uns", "unser", "unsere", "werden", "wird", "sowie", "oder", "erfahrung", "kenntnisse",
            "aufgaben", "profil", "bieten", "bewerbung", "arbeiten", "einen", "eine", "im", "zu", "auf", "von"}


KNOWN_LANGS = {"english", "russian"}
FOCUS = []                 # profile role.focus: [{name, regex, score, fit}] — topics the candidate is strongest in
PENALTIES = []             # profile role.penalties: [{name, regex, unless, score}] — flags that lower the score
TITLE_BOOST = []           # profile role.title_boost: [(regex, points)] — title words that mark the core of the role
OFF_DOMAIN = None          # profile role.off_domain: {name, title, desc} — a rescuable skip, the model may lift it
OFF_DOMAIN_REASON = ""
LEVEL = 2                  # candidate.seniority: 0 junior, 1 mid, 2 senior, 3 lead
NEEDS_VISA = True          # candidate.needs_visa: false for EU/EEA citizens — sponsorship wording stops mattering
BASED_IN = ""              # candidate.based_in: where a remote job may require the candidate to live
LANG_NAME_RU = {"nl": "нидерландском", "de": "немецком", "fr": "французском"}
LANG_KEY = {"nl": "dutch", "de": "german", "fr": "french"}
# target countries: primary first. Each: code, name, regex, floor (salary), sponsor (bool)
COUNTRIES = [{"code": "nl", "name": "Netherlands", "regex": NL_LOC, "floor": None, "sponsor": True}]
COUNTRY_CODES = {"nl"}
PRIMARY = "nl"             # track code of the primary country ("" when the goal is remote only)


def configure(profile):
    """Rebuild role/target-specific rules from the normalized profile (config.load). Called by cli.load_cfg."""
    global RELEVANT_TITLE, NOT_RELEVANT_TITLE, STACK, NL_LOC, KNOWN_LANGS, COUNTRIES, COUNTRY_CODES, FOCUS, PRIMARY
    global PENALTIES, TITLE_BOOST, OFF_DOMAIN, OFF_DOMAIN_REASON, LEVEL, NEEDS_VISA, BASED_IN
    role, target, cand = profile.get("role", {}), profile.get("target", {}), profile.get("candidate", {})
    countries = ([target["primary"]] if target.get("primary") else []) + list(target.get("countries") or [])
    COUNTRIES = [{"code": c["code"], "name": c["name"], "regex": re.compile(c["location_regex"], I),
                  "floor": c.get("salary_floor_month", target.get("salary_floor_month")),
                  "sponsor": c.get("sponsor_register", "none") == "ind"} for c in countries]
    COUNTRY_CODES = {c["code"] for c in COUNTRIES}
    PRIMARY = target["primary"]["code"] if target.get("primary") else ""
    # in_search_area keeps board postings in any target country; with no primary country nothing extra is needed
    NL_LOC = COUNTRIES[0]["regex"] if COUNTRIES else re.compile(r"(?!x)x")
    if role.get("title_include"):
        RELEVANT_TITLE = re.compile("|".join(f"(?:{x})" for x in role["title_include"]), I)
    if role.get("title_exclude"):
        NOT_RELEVANT_TITLE = re.compile("|".join(f"(?:{x})" for x in role["title_exclude"]), I)
    if role.get("stack"):
        STACK = [(re.compile(k, I), int(v)) for k, v in role["stack"].items()]
    TITLE_BOOST = [(re.compile(k, I), int(v)) for k, v in (role.get("title_boost") or {}).items()]
    FOCUS = [{"name": f["name"], "regex": re.compile(f["regex"], I), "score": int(f.get("score", 0)),
              "fit": int(f.get("fit", 0))} for f in role.get("focus") or []]
    PENALTIES = [{"name": f["name"], "regex": re.compile(f["regex"], I),
                  "unless": re.compile(f["unless"], I) if f.get("unless") else None,
                  "score": abs(int(f.get("score", 10)))} for f in role.get("penalties") or []]
    od = role.get("off_domain") or {}
    OFF_DOMAIN = ({"title": re.compile(od["title"], I) if od.get("title") else None,
                   "desc": re.compile(od["desc"], I) if od.get("desc") else None}
                  if od.get("title") or od.get("desc") else None)
    OFF_DOMAIN_REASON = od.get("name") or "не тот домен" if OFF_DOMAIN else ""
    if cand.get("languages"):
        KNOWN_LANGS = {x.lower() for x in cand["languages"]}
    LEVEL = {"junior": 0, "mid": 1, "senior": 2, "lead": 3}.get(str(cand.get("seniority") or "senior").lower(), 2)
    NEEDS_VISA = bool(cand.get("needs_visa", True))
    BASED_IN = str(cand.get("based_in") or "")


FR_WORDS = {"le", "la", "les", "des", "une", "un", "et", "vous", "nous", "pour", "avec", "dans", "sur", "est", "sont",
            "votre", "vos", "notre", "nos", "être", "au", "aux", "du", "poste", "équipe", "expérience", "compétences",
            "mission", "missions", "profil", "recherchons", "chez", "afin", "ainsi", "également", "qui", "que"}


def detect_lang(text):
    toks = re.findall(r"[a-zàâäèéêëîïôöûüçß']+", text.lower())
    if len(toks) < 15:
        return "unknown"
    en = sum(t in EN_WORDS for t in toks)
    scores = {"nl": sum(t in NL_WORDS for t in toks), "de": sum(t in DE_WORDS for t in toks),
              "fr": sum(t in FR_WORDS for t in toks)}
    lang, n = max(scores.items(), key=lambda kv: kv[1])
    if n > en * 0.9 and n >= 8:
        # bilingual posting (local intro + English requirements): don't treat as purely local
        return f"mixed:{lang}" if en >= 8 and en >= 0.5 * n else lang
    return "en"


OTHER_LANG = re.compile(
    r"\b(fluent|fluency|native|proficien\w+|c1|c2|b2|business level|professional|excellent|very good|good command)\b"
    r"[^.\n]{0,40}\b(german|french|spanish|italian|polish|portuguese|czech|hungarian|romanian|bulgarian|greek|swedish|"
    r"danish|finnish|norwegian|lithuanian|latvian|estonian|slovak|croatian|serbian|turkish|hebrew|arabic|japanese|"
    r"mandarin|chinese|korean)\b|"
    r"\b(german|french|spanish|italian|polish|portuguese|czech|hungarian|romanian|bulgarian|greek|swedish|danish|"
    r"finnish|norwegian|lithuanian|latvian|estonian|slovak|croatian|turkish)\b[^.\n]{0,30}\b(is |are )?(required|"
    r"mandatory|a must|essential|native|fluent|speaker|speaking)\b", I)
HOURLY = re.compile(r"(€|eur|\$|£|zł|pln|chf)\s?\d{2,4}\s?(?:-\s?\d{2,4}\s?)?(?:/|per|an|na)\s?(h\b|hr\b|hour|uur|godz|stunde|day|dag|tag)|"
                    r"\b(hourly rate|day rate|daily rate|uurtarief|dagtarief|b2b contract|b2b only|umowa b2b|contract role|"
                    r"contract position|\d+[- ]month contract|freelance basis|zzp)\b", I)
# Certain hourly/daily pay: an amount per hour/day that is a pay rate, not an allowance (meal, home office, travel),
# with no salaried alternative in the same posting (UoP/CDI/permanent, a monthly or annual amount). Anything less
# certain stays a soft flag via HOURLY. Calibrated 24.09 on 11k postings: allowances like "€2,45 per dag" were the
# main false positive of a bare "amount per day" rule.
_CUR = r"(?:€|eur(?:os?)?\b|\$|usd\b|£|gbp\b|zł|zl\b|pln\b|chf\b|ron\b|lei\b|czk\b|kč|huf\b|sek\b|dkk\b|nok\b)"
_NUM = r"\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_DAY = r"(?:day|dag|tag|jour|dzie[nń]|md|mandays?)"
PAY_RATE = re.compile(
    rf"(?:{_CUR}\s?(?P<a1>{_NUM})(?:\s?(?:-|–|to|à)\s?{_CUR}?\s?(?:{_NUM}))?\s?{_CUR}?"
    rf"|(?P<a2>{_NUM})(?:\s?(?:-|–|à)\s?(?:{_NUM}))?\s?{_CUR})"
    rf"\s?(?:\(?(?:net\w*|gross|brutto|netto)\)?\s?)?(?:\+\s?vat\s?)?(?:/|per|an|na|a|p\.?)\s?"
    rf"(?P<u>h|hr|hrs|hour|uur|godz\w*|stunde|std|heure|ora|{_DAY})\b"
    rf"|\b(?P<rt>hourly|daily|day)\s+rate\s*[:\-]?\s*(?:up to\s*|max\.?\s*)?(?:{_CUR}\s?)?(?P<a3>{_NUM})", I)
ALLOWANCE = re.compile(r"(allowance|vergoeding|meal|lunch|food|carte|ch[eè]que|ticket|swile|thuiswerk|home ?office|"
                       r"internet|travel|reis|per diem|diet|expense|subsid|stipend|budget for)", I)
SALARY_ALT = re.compile(
    rf"\b(uop|umow\w* o prac\w*|employment contract|contract of employment|permanent (contract|position|role)|cdi|"
    rf"vast (contract|dienstverband)|festanstellung)\b|"
    rf"(?:{_CUR}\s?(?:{_NUM})\s?k?|(?:{_NUM})\s?k?\s?{_CUR})[^.\n]{{0,25}}?(?:/|per|a|na|p\.?|par)\s?"
    rf"(?:year|yr|annum|month|mo|mies\w*|miesi\w*|rok\w*|an|mois)\b", I)


def _amount(s):
    s = s.replace(" ", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def pay_rate(text):
    """The quoted rate when pay is certainly per hour or per day, else ''."""
    for m in PAY_RATE.finditer(text):
        amount = _amount(m.group("a1") or m.group("a2") or m.group("a3") or "")
        daily = bool(re.fullmatch(_DAY, m.group("u") or "", I)) or (m.group("rt") or "").lower() in ("daily", "day")
        if amount is None or amount < (100 if daily else 10):
            continue
        if ALLOWANCE.search(text[max(0, m.start() - 60):m.start()]):
            continue
        if SALARY_ALT.search(text) or parse_salary(text):
            return ""
        return re.sub(r"\s+", " ", m.group(0)).strip()[:60]
    return ""


HYBRID = re.compile(r"\b(hybrid|on[- ]?site|in[- ]office|in the office|from (our|the) office|days? (per|a) week in)\b", I)
FULLY_REMOTE = re.compile(r"\b(fully remote|100 ?% remote|remote[- ]first|work from anywhere|anywhere in (the )?(eu|europe))\b", I)


SOFTENERS = re.compile(r"\b(plus|bonus|nice|advantage|prefer\w*|appreciated|not required|not (a )?must|optional|pre\b|"
                       r"beneficial|welcome|helpful|would be|desirable|ideally|good to have|wenselijk|pluspunt)\b", I)


def sentences(text):
    return re.split(r"(?<=[.!?;])\s+|\n+|\s+[•·\-–]\s+", text)


def other_language_required(text):
    """First non-softened sentence demanding a language the candidate does not have."""
    for sent in sentences(text):
        if SOFTENERS.search(sent):
            continue
        for m in OTHER_LANG.finditer(sent):
            lang = (m.group(2) or m.group(3) or "").lower()
            if lang not in KNOWN_LANGS:
                return m.group(0)[:80]
    return ""


def dutch_required(text):
    for sent in sentences(text):
        if not re.search(r"\b(dutch|nederlands(e)?|dutch[- ]speaking)\b", sent, I):
            continue
        if SOFTENERS.search(sent):
            continue
        if re.search(r"\b(required|mandatory|must|fluent|fluency|native|essential|excellent|proficien|"
                     r"c1|c2|b2|professional|speaking|speaker|verplicht|vereist|uitstekend)\b", sent, I):
            return sent.strip()[:160]
    return ""


SAL = re.compile(
    r"(?:€|eur\b|euro\b)\s?(\d{1,3}(?:[.,]\d{3})+|\d{4,6}|\d{2,3}(?=\s?k\b))\s?(k)?"          # lo (+k)
    r"(?:\s?(?:-|–|to|tot|en|and)\s?(?:€|eur)?\s?(\d{1,3}(?:[.,]\d{3})+|\d{4,6}|\d{2,3}(?=\s?k\b))\s?(k)?)?"  # hi (+k)
    r"[^.\n]{0,60}?(per (?:month|maand|year|jaar|annum)|p/?m\b|monthly|annual|yearly|a year|jaarlijks|maandelijks)?",
    re.I)


# Amounts that are not pay: benefits and budgets just before the number, company figures in millions right after it.
# Audit 25.09 of 300 salary-floor skips: "annual development budget of €1,500" (ZEAL Network), "Relocation support: up
# to €2,500" (Helsing), "jaaromzet van €1.267,4 miljoen" (Corbion) were read as monthly salaries and cut the posting.
NOT_PAY_BEFORE = re.compile(r"(budget|allowance|bonus|relocation|learning|development|education|training|equipment|"
                            r"stipend|voucher|gym|vergoeding|toelage|tegoed|omzet|turnover|revenue|umsatz|funding|raised|"
                            r"invest\w*|prime|indemnit\w*|chèque|ticket|meal)[^.\n]{0,40}$", I)
NOT_PAY_AFTER = re.compile(r"^[\s,.]*(\d+\s*)?(miljoen|million|mln|mio|bn|billion|mld|milliard)", I)


def parse_salary(text):
    """Return best-guess monthly gross (EUR) from free text, or None."""
    best = None
    for m in SAL.finditer(text):
        if NOT_PAY_BEFORE.search(text[max(0, m.start() - 60):m.start()]) or NOT_PAY_AFTER.search(text[m.end():m.end() + 15]):
            continue
        try:
            lo = float(re.sub(r"[.,]", "", m.group(1))) * (1000 if m.group(2) else 1)
            hi = float(re.sub(r"[.,]", "", m.group(3))) * (1000 if m.group(4) else 1) if m.group(3) else lo
        except (TypeError, ValueError):
            continue
        hi = max(lo, hi)
        period = (m.group(5) or "").lower()
        if any(k in period for k in ("year", "jaar", "annum", "annual")) or (not period and hi > 20000):
            hi /= 12
        if 1000 <= hi <= 30000:
            best = max(best or 0, hi)
    return best


def in_search_area(job):
    """A board posting worth keeping: no location, remote, a target country (by its own regex: Personio offices and
    Teamtailor cities are often just "Berlin" or "Paris", which EU_LOC lacks) or anywhere else in the EU."""
    loc = job.location
    return (not loc or job.remote or bool(NL_LOC.search(loc) or REMOTE.search(loc) or EU_LOC.search(loc))
            or any(c["regex"].search(loc) for c in COUNTRIES if c["regex"]))


def is_relevant_title(title):
    return bool(RELEVANT_TITLE.search(title)) and not NOT_RELEVANT_TITLE.search(title)


def analyze(job, sponsors, cfg):
    """Fill lang, salary, sponsor, score, verdict, reasons on the job in place."""
    text = f"{job.title}\n{job.description}"
    loc = f"{job.location} {job.title}"
    reasons = []
    skip = []

    job.lang = detect_lang(job.description) if job.description else detect_lang(job.title)
    knows_nl, knows_de = "dutch" in KNOWN_LANGS, "german" in KNOWN_LANGS
    if job.lang in LANG_KEY and LANG_KEY[job.lang] not in KNOWN_LANGS:
        skip.append(f"текст на {LANG_NAME_RU[job.lang]}")
    elif job.lang.startswith("mixed:") and LANG_KEY.get(job.lang[6:]) not in KNOWN_LANGS \
            and not (DUTCH_TITLE.search(job.title) or GERMAN_TITLE.search(job.title)):
        reasons.append(f"объявление двуязычное ({LANG_NAME_RU[job.lang[6:]]} + английский): язык решает LLM")
    elif DUTCH_TITLE.search(job.title) and not knows_nl:
        skip.append("заголовок на нидерландском")
    elif GERMAN_TITLE.search(job.title) and not knows_de:
        skip.append("заголовок на немецком")
    elif NON_EN_TITLE.search(job.title) and not (KNOWN_LANGS - {"english", "russian", "ukrainian", "belarusian"}):
        skip.append("заголовок не на английском")      # with another European language the model decides
    dr = dutch_required(text) if not knows_nl else ""
    if dr:
        skip.append(f"нужен нидерландский: «{dr}»")
    ol = other_language_required(job.description)
    if ol:
        skip.append(f"нужен другой язык: «{ol}»")
    junior = bool(JUNIOR_TITLE.search(job.title))
    if junior and LEVEL >= 2:
        skip.append("junior/intern уровень")
    if CLEARANCE.search(text):
        skip.append("clearance / Defensie / гос")
    if OFF_DOMAIN and ((OFF_DOMAIN["title"] and OFF_DOMAIN["title"].search(job.title))
                       or (OFF_DOMAIN["desc"] and OFF_DOMAIN["desc"].search(job.description))):
        skip.append(OFF_DOMAIN_REASON)
    m = NO_SPONSOR.search(text) if NEEDS_VISA else None
    if m:
        skip.append(f"без спонсорства: «{m.group(0)[:60]}»")

    country = None
    for c in COUNTRIES:
        rx = c["regex"] or NL_LOC
        if rx.search(job.location) or (not job.location and job.extra.get("country", "").lower() == c["code"]):
            country = c
            break
    in_nl = country is not None          # "in a target country" (name kept for the diff below)
    remote = job.remote or bool(REMOTE.search(job.location)) or bool(
        re.search(r"\b(fully remote|100% remote|remote[- ]first|work from anywhere)\b", text, I))
    job.remote = remote
    score_pen = 0
    for p in PENALTIES:             # role-specific red flags in the posting text, e.g. "manual testing only" for QA
        d = job.description
        if d and p["regex"].search(d) and not (p["unless"] and p["unless"].search(d)):
            reasons.append(p["name"])
            score_pen += p["score"]
    if FREELANCE.search(job.title) or (FREELANCE.search(job.description) and not re.search(
            r"\b(permanent|full[- ]time employment|employee|vast contract|dienstverband)\b", job.description, I)):
        if not remote:
            skip.append("freelance/contract on-site")
        else:
            reasons.append("похоже на контракт (remote)")

    job.salary_month = parse_salary(job.salary_text + "\n" + job.description)
    floor = (country or {}).get("floor") or cfg.get("salary_floor_month") or 0
    if job.salary_month and in_nl and job.salary_month < floor * 0.9:
        skip.append(f"зарплата ~€{job.salary_month:.0f}/мес < порога €{floor} ({country['name']})")
    elif job.salary_month and in_nl and job.salary_month < floor:
        reasons.append(f"зарплата ~€{job.salary_month:.0f}/мес на грани порога €{floor}: торговаться / индексация")

    if AGENCY.search(job.description):
        reasons.append("агентство: конечный клиент не назван")
    emp = (job.extra.get("employment_type") or "")
    rate = pay_rate(f"{job.salary_text}\n{job.description}")
    if rate:
        skip.append(f"оплата за час/день: «{rate}»")
    elif HOURLY.search(text) or re.search(r"contract|temporary|interim", emp, I):
        reasons.append("почасовая/дневная ставка или контракт: релокации обычно не подразумевает")
    if job.applicants is not None:
        reasons.append(f"откликов на LinkedIn: {job.applicants}")

    aliases = {normalize_simple(k): v for k, v in (cfg.get("sponsor_aliases") or {}).items()}
    lookup = aliases.get(normalize_simple(job.company), job.company)
    hits = sponsors.match(lookup) if sponsors else []
    eu_remote = remote and not in_nl and not (NON_EU_REMOTE.search(job.location) and not EU_HINT.search(job.location))
    sponsor_bonus, nl_entity = 0, False
    if hits and in_nl and country["sponsor"]:
        job.sponsor_name, job.sponsor_kvk = hits[0]
        sponsor_bonus = 8 if hits[0][0].startswith("≈") else 15
    elif hits and in_nl:
        reasons.append(f"юрлицо в реестре IND есть ({hits[0][0]}), но вакансия в {country['name']}")
    elif hits and eu_remote:
        nl_entity = True
        reasons.append(f"NL-юрлицо в реестре IND: {hits[0][0]} — заход через remote-найм")
    elif hits:
        reasons.append(f"юрлицо в реестре IND есть ({hits[0][0]}), но вакансия вне NL")
    elif in_nl and country["sponsor"]:
        reasons.append("компания не найдена в реестре IND")
    agencies = cfg.get("agency_companies", [])
    if any(normalize_simple(n) in normalize_simple(job.company) for n in agencies):
        reasons.append("агентство/рекрутер")

    # ---------- score ----------
    score = 40
    senior = bool(SENIOR.search(job.title))
    if senior:
        score += {3: 12, 2: 12, 1: 6, 0: -15}[LEVEL]              # a junior candidate: above the level
        if LEVEL == 0:
            reasons.append("уровень выше: senior/lead")
    if junior and LEVEL == 0:
        score += 12
    elif junior and LEVEL == 1:
        score -= 10
        reasons.append("junior в заголовке")
    for rx, pts in TITLE_BOOST:      # words marking the core of the role, e.g. "SDET" / "automation" for QA
        if rx.search(job.title):
            score += pts
            break
    if MEDIOR.search(job.title) and LEVEL >= 2:
        score -= 10
        reasons.append("medior")
    score += sponsor_bonus          # employer can sponsor HSM: a fact about viability, not a geography preference
    # no bonus for the country itself: location enters the final fit once, as a penalty in llm.apply_assessment
    if job.salary_month:
        target = cfg.get("salary_target_month") or floor or 5000
        score += 10 if job.salary_month >= target else (4 if job.salary_month >= floor else -20)
    stack = sum(w for p, w in STACK if p.search(text))
    score += min(stack, 20) - score_pen
    for f in FOCUS:                 # outside the stack cap: a focus topic should lift a posting over the LLM floor
        if f["regex"].search(text):
            reasons.append(f"фокус: {f['name']}")
            score += f["score"]
    if "агентство" in " ".join(reasons):
        score -= 15
    if job.lang == "unknown" and not job.description:
        reasons.append("описание не загружено")
        score -= 5

    known = cfg.get("known_companies", {})
    for status, names in known.items():
        if any(normalize_simple(n) in normalize_simple(job.company) for n in names):
            reasons.append(f"уже в воронке: {status}")
            score -= 30 if status in ("applied", "rejected") else 10
    if excluded_company(job.company, cfg):
        skip.append("компания в exclude_companies")

    non_eu_remote = remote and not in_nl and NON_EU_REMOTE.search(job.location) and not EU_HINT.search(job.location)
    if non_eu_remote:
        reasons.append("remote вне Европы")
    if remote and not in_nl and job.description and HYBRID.search(job.description) and not FULLY_REMOTE.search(text):
        reasons.append("в тексте есть hybrid/office: проверить режим")   # flag only; the LLM decides work_mode

    in_eu = bool(EU_LOC.search(job.location))
    if in_nl:
        job.track = country["code"]
    elif remote and not non_eu_remote:
        job.track = "remote_nl" if nl_entity else "remote"
    elif in_eu:
        job.track = "eu"                       # on-site / hybrid elsewhere in the EU: relocation there is acceptable
    else:
        job.track = "other"
    lm = None if m else LOCAL_ONLY.search(text)
    if lm and not residency_blocks(lm.group(0), job.track, job.location):
        reasons.append(f"просят жить в стране вакансии: «{lm.group(0).strip()[:60]}» — при переезде не помеха")
    elif lm:
        skip.append(f"без спонсорства: «{lm.group(0).strip()[:60]}»")
    job.reasons = skip + reasons
    job.score = max(0, min(100, score if not skip else min(score, 25)))
    if skip:
        job.verdict = "skip"
    elif job.track != "other":
        job.verdict = "live"
    else:
        job.verdict = "other"
    return job


def relocation_track(track):
    """Tracks where the candidate would move to the job's country: target countries and on-site/hybrid EU."""
    return track in COUNTRY_CODES or track == "eu"


def residency_blocks(quote, track, location):
    """Does a "must live in …" requirement close the job for someone who would relocate? See RESIDENCY_HARD.
    A requirement to live where the candidate already lives (candidate.based_in) is no obstacle on any track."""
    if BASED_IN and re.search(rf"\b{re.escape(BASED_IN)}\b", quote, I) and not re.search(
            r"citizen|nationalit|passport", quote, I):
        return False
    if not relocation_track(track):
        return True
    hard = RESIDENCY_HARD if NEEDS_VISA else RESIDENCY_HARD_NO_VISA
    if hard.search(quote) or NON_EU_PLACE.search(quote) or (track == "eu" and REMOTE_JOB.search(quote)):
        return True
    from .cvgen import country_of
    named = country_of(quote)
    own = country_of(location) if track == "eu" else next((c["name"] for c in COUNTRIES if c["code"] == track), None)
    return bool(named and own and named != own)


def normalize_simple(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def excluded_company(company, cfg):
    return any(normalize_simple(n) in normalize_simple(company) for n in cfg.get("exclude_companies", []))


def same_posting(text_a, text_b, threshold=0.85):
    """Do two postings that share company + title also share the text? Only asked for intermediaries
    (PARTNER_LISTING): the same partner role posted per country differs in a word or two, another client's role with
    the same generic title ("Senior QA Engineer") differs throughout."""
    from difflib import SequenceMatcher
    words = lambda t: re.findall(r"\w+", (t or "").lower())[:400]
    a, b = words(text_a), words(text_b)
    if not a or not b:
        return True       # nothing to compare: keep the plain company + title rule
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= threshold
