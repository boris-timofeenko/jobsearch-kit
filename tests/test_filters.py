from jobsearch import filters as f
from jobsearch.models import Job


def test_salary():
    assert round(f.parse_salary("Salary €4.500 - €5.500 per month")) == 5500
    assert round(f.parse_salary("€60,000 - €75,000 per year")) == 6250
    assert round(f.parse_salary("Salary: EUR 70k-85k")) == 7083
    assert round(f.parse_salary("Salaris €3.800 bruto per maand")) == 3800
    assert f.parse_salary("Budget of €500 for equipment") is None


def test_lang_and_dutch():
    nl = "Als Test Automation Engineer speel je een cruciale rol in het waarborgen van de kwaliteit van onze integraties tussen systemen en werk je samen met het team."
    assert f.detect_lang(nl) == "nl"
    assert f.dutch_required("Fluent in Dutch and English is required.")
    assert not f.dutch_required("Dutch is a plus, but not required.")


def test_no_sponsor_and_junior():
    assert f.NO_SPONSOR.search("We cannot offer visa sponsorship for this role")
    assert f.NO_SPONSOR.search("Candidates must already have a valid EU work permit")
    assert f.JUNIOR_TITLE.search("Junior QA Engineer")
    assert not f.JUNIOR_TITLE.search("Senior QA Engineer")


def test_analyze_live():
    j = Job(id="x:1", source="x", company="Adyen", title="Senior QA Automation Engineer", url="u",
            location="Amsterdam, North Holland, Netherlands",
            description="We are looking for a senior engineer. Playwright, TypeScript, payments. English is our working language. Salary €5,000 - €6,000 per month.")

    class SP:
        def match(self, c):
            return [("Adyen N.V.", "34259528")]
    f.analyze(j, SP(), {"salary_floor_month": 4357, "salary_target_month": 5000})
    assert j.verdict == "live" and j.sponsor_kvk == "34259528" and j.score >= 65, (j.verdict, j.score, j.reasons)


def test_analyze_skip_dutch():
    j = Job(id="x:2", source="x", company="X", title="Test Engineer", url="u", location="Utrecht, Netherlands",
            description="Je gaat werken met een team van ontwikkelaars en testers. Wij zoeken iemand met ervaring in testautomatisering en kennis van het vak. Deze functie is bij ons in Utrecht.")
    f.analyze(j, None, {})
    assert j.verdict == "skip" and "нидерландском" in j.reasons[0]


def test_fingerprint_collapses_city_variants():
    a = Job(id="l:1", source="linkedin", company="Jobster", title="Team Lead QA Automation (m/w/d) - Jobbird.com", url="u", location="Berlin")
    b = Job(id="l:2", source="linkedin", company="jobster", title="Team Lead QA Automation (m/w/d) - Jobbird.com", url="u", location="Heidelberg")
    c = Job(id="l:3", source="linkedin", company="Jobster", title="Senior QA Automation Engineer", url="u", location="Berlin")
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()
    d = Job(id="l:4", source="lever", company="Binance", title="Binance Accelerator Program - QA (Cloud)", url="u")
    e = Job(id="l:5", source="lever", company="Binance", title="Binance Accelerator Program - QA", url="u")
    assert d.fingerprint() != e.fingerprint()


def test_residency_and_language():
    assert f.NO_SPONSOR.search("Candidates must be based in Poland and have the right to work in Poland")
    assert f.NO_SPONSOR.search("Local candidates only, no relocation")
    assert f.other_language_required("Fluent German is required for this role.")
    assert not f.other_language_required("German is a plus.")
    assert not f.other_language_required("You communicate in English with the team.")


def test_hybrid_outside_nl_is_not_remote():
    j = Job(id="x:3", source="linkedin", company="Acme", title="Senior QA Automation Engineer", url="u",
            location="Cluj-Napoca, Romania", remote=True,
            description="Hybrid role: 3 days per week in our Cluj office. Playwright, TypeScript. We are a product company.")
    f.analyze(j, None, {})
    assert j.verdict == "live" and any("hybrid" in r for r in j.reasons), (j.verdict, j.reasons)


def test_dutch_preferably_is_not_required():
    text = "Hands-on experience with test automation\nA good command of English, and preferably Dutch language\nOur organization"
    assert not f.dutch_required(text)
    assert f.dutch_required("Requirements:\nFluent in Dutch (C1)\nExperience with Selenium")


def test_language_gap_respects_candidate_languages():
    from jobsearch import llm
    llm.configure({"candidate": {"languages": ["English", "Russian"], "summary": "QA"}, "role": {}, "target": {}})
    assert llm.language_gap("Fluent Russian and good English are both required") == ""
    assert llm.language_gap("Fluent Dutch required") == "dutch"
    assert llm.language_gap("German and Russian required") == "german"
    assert llm.language_gap(None) == ""


def test_extract_json_salvages_truncated_output():
    from jobsearch import llm
    good = '```json\n{"is_software_qa": true, "fit": 7, "note": "ok"}\n```'
    assert llm.extract_json(good)["fit"] == 7
    truncated = '{"is_software_qa": false, "seniority": "lead", "fit": 3, "note": "обрезано на полус'
    assert llm.extract_json(truncated)["fit"] == 3


def test_unsure_yes_no_field_takes_the_default():
    from jobsearch import llm
    a = llm.Assessment.model_validate({"fit": 5, "is_agency": "unknown", "relocation": None, "is_software_qa": "unclear"})
    assert (a.is_agency, a.relocation, a.is_target_role) == (False, False, True)
    assert llm.Assessment.model_validate({"fit": 5, "is_agency": "yes"}).is_agency is True


def test_country_and_eu_tracks():
    from jobsearch.cli import load_cfg
    load_cfg()
    base = dict(source="linkedin", url="u", description="Senior QA automation, Playwright, TypeScript, CI/CD. English-speaking team.")
    be = Job(id="t:be", company="Acme", title="Senior QA Engineer", location="Brussels, Brussels Region, Belgium", **base)
    de = Job(id="t:de", company="Acme", title="Senior QA Engineer", location="Berlin, Germany", **base)
    eu = Job(id="t:eu", company="Acme", title="Senior QA Engineer", location="Warsaw, Mazowieckie, Poland", **base)
    us = Job(id="t:us", company="Acme", title="Senior QA Engineer", location="Austin, Texas, United States", **base)
    both = Job(id="t:both", company="Acme", title="Senior QA Engineer", location="Berlin, Germany / Netherlands", **base)
    for j in (be, de, eu, us, both):
        f.analyze(j, None, {})
    assert (be.track, be.verdict) == ("be", "live")
    assert (de.track, de.verdict) == ("de", "live")
    assert (eu.track, eu.verdict) == ("eu", "live"), (eu.track, eu.reasons)
    assert (us.track, us.verdict) == ("other", "other")
    assert both.track == "nl"                   # a copy merged in from the Netherlands makes the posting an NL one


def test_french_text_is_detected():
    fr = "Nous recherchons un ingénieur QA pour rejoindre notre équipe. Vous serez responsable des tests et de la qualité des livraisons avec une expérience en automatisation."
    assert f.detect_lang(fr) == "fr"


def test_bilingual_posting_is_flagged_not_skipped():
    from jobsearch.cli import load_cfg
    load_cfg()
    text = ("Wij zoeken een Senior Test Automation Engineer voor ons team in Utrecht. Je gaat werken met een internationaal team "
            "en je bent verantwoordelijk voor de kwaliteit van onze releases. Je werkt samen met de ontwikkelaars en de product "
            "owner aan een stabiele testautomatisering. Wat wij bieden: een goed salaris en veel ruimte voor ontwikkeling. "
            "Requirements: 5+ years of experience with test automation. Strong skills in Playwright and TypeScript. "
            "You have experience with CI/CD pipelines and API testing. We work in English.")
    assert f.detect_lang(text).startswith("mixed:")
    j = Job(id="x:bi", source="linkedin", company="Acme", title="Senior Test Automation Engineer", url="u",
            location="Utrecht, Netherlands", description=text)
    f.analyze(j, None, {})
    assert j.verdict == "live" and any("двуязычное" in r for r in j.reasons), (j.verdict, j.reasons)


def test_salary_near_floor_is_flag_not_skip():
    from jobsearch.cli import load_cfg
    load_cfg()
    j = Job(id="x:sal", source="linkedin", company="Acme", title="Senior QA Engineer", url="u",
            location="Amsterdam, Netherlands", description="Salary €4,100 - €4,300 per month. Playwright, TypeScript. English team.")
    f.analyze(j, None, {"salary_floor_month": 4357})
    assert j.verdict == "live" and any("на грани" in r for r in j.reasons), (j.verdict, j.reasons)


def test_country_and_eu_tracks_are_llm_candidates():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    mk = lambda i, track, score: Job(id=f"c:{i}", source="x", company="Acme", title="Senior QA", url="u", description="x" * 400,
                                     track=track, verdict="live", score=score)
    cands = llm.select_candidates([mk(1, "be", 30), mk(2, "de", 30), mk(3, "eu", 60), mk(4, "eu", 40), mk(5, "remote", 60), mk(6, "other", 90)], {})
    assert [c.track for c in cands] == ["be", "de", "eu", "remote"]


def test_location_penalty_applied_once_after_llm():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    base = dict(source="x", company="Acme", title="Senior QA", url="u", description="x" * 400, verdict="live", score=60)
    a = llm.Assessment(is_software_qa=True, fit=8, verdict="apply", seniority="senior", automation_level="automation",
                       work_mode="hybrid", sponsorship="unknown", is_agency=False)
    nl, de, eu = Job(id="p:1", track="nl", **base), Job(id="p:2", track="de", **base), Job(id="p:3", track="eu", **base)
    for j in (nl, de, eu):
        llm.apply_assessment(j, a)
    assert (nl.llm_fit, de.llm_fit, eu.llm_fit) == (9, 7, 6)                    # NL +1, BE/FR/DE −1, EU −2
    weak = Job(id="p:4", track="nl", **base)
    llm.apply_assessment(weak, llm.Assessment(fit=4))
    assert weak.llm_fit == 4, weak.reasons                                       # NL bonus needs a decent role match


def test_spanish_de_is_not_germany():
    from jobsearch.cli import load_cfg
    load_cfg()
    base = dict(source="linkedin", url="u", company="Acme", title="Senior QA Engineer", description="Playwright, TypeScript. English team. " * 10)
    j = Job(id="t:es", location="Cornellà de Llobregat, Catalonia, Spain", **base)
    k = Job(id="t:pt", location="Vila Nova de Gaia, Porto, Portugal", **base)
    for x in (j, k):
        f.analyze(x, None, {})
    assert j.track == "eu" and k.track == "eu", (j.track, k.track)


def test_fit_adjustments_and_rescue_prefixes():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    a = llm.Assessment(is_software_qa=True, fit=7, verdict="maybe", seniority="senior", automation_level="automation",
                       work_mode="onsite", sponsorship="yes", is_agency=False)
    j = Job(id="f:1", source="linkedin", company="Acme", title="Senior QA", url="u", description="x" * 400,
            track="nl", verdict="live", score=60, applicants=12)
    llm.apply_assessment(j, a)
    assert j.llm_fit == 9, j.reasons                       # 7 +1 NL +1 low competition; no visa words in the text
    k = Job(id="f:2", source="linkedin", company="Acme", title="Senior QA", url="u", description="x" * 400,
            track="eu", verdict="live", score=60, applicants=300, reasons=["агентство/рекрутер", "почасовая/дневная ставка или контракт: релокации обычно не подразумевает"])
    llm.apply_assessment(k, llm.Assessment(fit=8, is_agency=True))
    assert k.llm_fit == 2, k.reasons                       # 8 -2 location -1 agency -2 contract -1 competition
    # rescue: only the hardware rule counts as a skip reason; soft flags must not block it
    h = Job(id="f:3", source="linkedin", company="Acme", title="Test Engineer", url="u", description="x" * 400,
            track="nl", verdict="skip", score=20, reasons=[f.OFF_DOMAIN_REASON, "объявление двуязычное (нидерландском + английский): язык решает LLM", "локация −0"])
    assert llm.rescuable(h)
    # sponsorship "no" for on-site elsewhere in the EU is a skip
    e = Job(id="f:4", source="linkedin", company="Acme", title="Senior QA", url="u", description="x" * 400, track="eu", verdict="live", score=60)
    llm.apply_assessment(e, llm.Assessment(fit=8, sponsorship="no"))
    assert e.verdict == "skip"


def test_hourly_contract_flag():
    from jobsearch.cli import load_cfg
    load_cfg()
    mk = lambda d: Job(id="h:1", source="linkedin", company="Acme", title="Senior QA Automation Engineer", url="u",
                       location="Poland", remote=True, description=d * 5)
    certain = mk("B2B contract, rate 120 zł/h, Playwright, TypeScript. Fully remote within Poland. ")
    f.analyze(certain, None, {})
    assert certain.verdict == "skip" and certain.reasons[0].startswith("оплата за час/день"), certain.reasons
    soft = mk("B2B contract, Playwright, TypeScript. Fully remote within Poland. ")    # no rate named: flag only
    f.analyze(soft, None, {})
    assert soft.verdict == "live" and any(r.startswith("почасовая") for r in soft.reasons), soft.reasons
    either = mk("B2B: 140-160 zł/h netto or UoP: 18 000 - 22 000 zł brutto, Playwright, TypeScript, remote. ")
    f.analyze(either, None, {})
    assert either.verdict == "live", either.reasons                               # salaried option: not certain


def test_certain_pay_rate_vs_allowances():
    rates = ["Rate: €250-€350 per day", "Wynagrodzenie 170-230 zł/h + VAT na B2B", "Payout: $25 - $80/hour",
             "Hourly Rate:\nup to 35 EUR (Gross)", "Budget: 40 EUR / h max", "1000 - 1100 PLN/day on B2B",
             "€280–€320/day + VAT", "Pay rate: 30 USD/hr"]
    not_rates = ["Een thuiswerkvergoeding van € 2,45 per dag", "Meal allowance — €10/day.",
                 "Carte Swile de 11 € / jour travaillé", "Our salary or hourly rate ranges reward associates",
                 "Stundensatz: nach Vereinbarung", "40 000€ à 50 000€ brut / an fixe, ou freelance 300€ à 400€/ jour",
                 "working 7h45 per day", "Salary €4.500 - €5.500 per month, travel €0,31/km"]
    assert all(f.pay_rate(t) for t in rates), [t for t in rates if not f.pay_rate(t)]
    assert not any(f.pay_rate(t) for t in not_rates), [t for t in not_rates if f.pay_rate(t)]


def test_focus_topics_from_profile():
    from jobsearch.cli import load_cfg
    load_cfg()
    names = lambda t: [x["name"] for x in f.FOCUS if x["regex"].search(t)]
    assert names("Mobile QA: Flutter app, Patrol tests") == ["Flutter/Patrol"]
    assert names("tools such as WebdriverIO, Patrol, Selenium") == ["Flutter/Patrol"]
    assert names("first article inspections, patrol inspections and sampling") == []   # manufacturing, not the tool
    assert names("Build LLM evals and RAG pipelines") == ["LLM/AI-агенты в тексте"]
    assert names("Playwright with TypeScript, CI in GitHub Actions") == ["Playwright TS/JS"]
    assert names("Playwright tests in Java") == []
    assert names("Openness to using AI tools like Copilot") == []
    j = Job(id="fl:1", source="linkedin", company="Acme", title="Senior QA Engineer (Flutter)", url="u",
            location="Amsterdam, Netherlands", description="Automate our Flutter app with Patrol and Appium. " * 10)
    base = Job(id="fl:2", source="linkedin", company="Acme", title="Senior QA Engineer", url="u",
               location="Amsterdam, Netherlands", description="Automate our app with Appium. " * 10)
    f.analyze(j, None, {})
    f.analyze(base, None, {})
    assert "фокус: Flutter/Patrol" in j.reasons and j.score >= base.score + 8, (j.score, base.score)


def test_new_bonuses_and_pay_skip():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    mk = lambda i, **kw: Job(id=f"b:{i}", source="linkedin", company="Acme", title="Senior QA", url="u",
                             description="We offer visa sponsorship and a relocation package. " * 8, track="nl",
                             verdict="live", score=60, **kw)
    visa, reloc, ai, tool, flutter, weak = mk(1), mk(2), mk(3), mk(4), mk(5, reasons=["фокус: Flutter/Patrol"]), mk(6)
    first, pw = mk(10), mk(11, reasons=["фокус: Playwright TS/JS"])
    llm.apply_assessment(first, llm.Assessment(fit=6, ai_qa="ai_first"))
    llm.apply_assessment(pw, llm.Assessment(fit=6))
    assert (first.llm_fit, pw.llm_fit) == (10, 8), (first.reasons, pw.reasons)   # 6 +1 NL +3 AI-first; 6 +1 +1
    llm.apply_assessment(visa, llm.Assessment(fit=6, sponsorship="yes", relocation=True))
    llm.apply_assessment(reloc, llm.Assessment(fit=6, relocation=True))
    llm.apply_assessment(ai, llm.Assessment(fit=6, ai_qa="product"))
    llm.apply_assessment(tool, llm.Assessment(fit=6, ai_qa="tooling"))
    llm.apply_assessment(flutter, llm.Assessment(fit=6))
    llm.apply_assessment(weak, llm.Assessment(fit=4, ai_qa="product", sponsorship="yes"))
    assert (visa.llm_fit, reloc.llm_fit, ai.llm_fit, tool.llm_fit, flutter.llm_fit) == (9, 8, 9, 8, 9)   # all +1 NL
    assert weak.llm_fit == 4, weak.reasons                          # bonuses never lift a weak role match
    hourly = mk(7)
    llm.apply_assessment(hourly, llm.Assessment(fit=8, pay_basis="hourly"))
    assert hourly.verdict == "skip" and "LLM: оплата почасовая" in hourly.reasons
    silent = Job(id="b:9", source="linkedin", company="Acme", title="Senior QA", url="u", description="x" * 400,
                 track="nl", verdict="live", score=60, sponsor_name="Acme B.V.")
    llm.apply_assessment(silent, llm.Assessment(fit=6, sponsorship="yes", relocation=True))
    assert silent.llm_fit == 7, silent.reasons                      # only +1 NL: a register entry is not a promise
    old = mk(8)                                                     # stored assessments without the new fields
    llm.apply_assessment(old, llm.Assessment.model_validate({"fit": 7, "sponsorship": "unknown"}))
    assert old.verdict == "live" and old.llm_fit == 8              # 7 +1 NL


def test_rubric_rates_fit_as_if_in_target_country():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    s = llm.SYSTEM
    assert "вакансия находится в Amsterdam" in s and "ai_role" in s and "pay_basis" in s
    assert s.index("fit 0-10") < s.index("Цели кандидата") < s.index("Ты оцениваешь")   # goals after the rules
    assert "«QA / SDET (автоматизация тестирования)»" in s and "Сильнейшие стороны кандидата — AI в QA" in s
    assert "{" not in s.split("Цели кандидата")[0]               # every template field was filled


def test_bonuses_do_not_rescue_weak_role_match():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    weak = Job(id="w:1", source="linkedin", company="Acme", title="Support Champion", url="u", description="x" * 400,
               track="nl", verdict="live", score=50, applicants=10)
    llm.apply_assessment(weak, llm.Assessment(fit=3, sponsorship="yes"))
    assert weak.llm_fit == 3, weak.reasons                      # 3: no NL bonus, no visa bonus


def test_product_company_ranks_above_outstaff_recruiter_and_contract():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    mk = lambda i, desc="x" * 400, track="eu": Job(id=f"e:{i}", source="linkedin", company="Acme", title="Senior QA",
                                                     url="u", description=desc, track=track, verdict="live", score=60)
    prod, cons, rec, outc, visa_c, bairesdev = mk(1), mk(2), mk(3), mk(4), mk(5, "We sponsor your visa. " * 20), mk(6, track="remote")
    llm.apply_assessment(prod, llm.Assessment(fit=6, employer_type="direct", employment="employee"))
    llm.apply_assessment(cons, llm.Assessment(fit=6, is_agency=True, employer_type="consultancy", employment="employee"))
    llm.apply_assessment(rec, llm.Assessment(fit=6, is_agency=True, employer_type="recruiter"))
    llm.apply_assessment(outc, llm.Assessment(fit=6, is_agency=True, employer_type="consultancy", employment="contractor"))
    llm.apply_assessment(visa_c, llm.Assessment(fit=6, employer_type="direct", employment="contractor", sponsorship="yes"))
    llm.apply_assessment(bairesdev, llm.Assessment(fit=8, is_agency=True, employer_type="consultancy", employment="contractor"))
    assert (prod.llm_fit, cons.llm_fit, rec.llm_fit, outc.llm_fit) == (4, 3, 3, 1), (prod.reasons, outc.reasons)
    assert visa_c.llm_fit == 6 and "контракт, но виза обещана явно: без штрафа" in visa_c.reasons, visa_c.reasons
    assert bairesdev.llm_fit == 2, bairesdev.reasons            # remote −3, outstaff −1, contract −2 (was 6 before 25.09)
    legacy = mk(7)                                              # heuristic "remote contract" wording counts as contract too
    legacy.reasons = ["похоже на контракт (remote)"]
    llm.apply_assessment(legacy, llm.Assessment(fit=6))
    assert legacy.llm_fit == 2, legacy.reasons

def test_cli_helpers_import_cleanly():
    from jobsearch import cli
    assert cli.now_local().tzinfo is not None
    assert "Прогон" in cli.report.run_summary("Прогон", 10, [], [], 0)


def test_living_in_the_job_country_is_not_a_blocker_when_relocating():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    mk = lambda i, loc, **kw: Job(id=f"r:{i}", source="linkedin", company="Acme", title="Senior QA Automation Engineer",
                                  url="u", location=loc, description="Playwright and TypeScript. Candidates must be based in the country. " * 8, **kw)
    de, remote = mk(1, "Berlin, Germany"), mk(2, "Poland", remote=True)
    f.analyze(de, None, {})
    f.analyze(remote, None, {})
    assert de.verdict == "live" and any(r.startswith("просят жить") for r in de.reasons), de.reasons
    assert remote.verdict == "skip" and remote.reasons[0].startswith("без спонсорства"), remote.reasons
    job = lambda i, track, **kw: Job(id=f"q:{i}", source="linkedin", company="Acme", title="Senior QA", url="u",
                                     description="x" * 400, track=track, verdict="live", score=60, **kw)
    soft, hard, rem, it, res = job(1, "de"), job(2, "eu"), job(3, "remote"), job(4, "eu"), job(5, "fr")
    llm.apply_assessment(res, llm.Assessment(fit=7, residency_restriction="Open only to residents of France", work_mode="onsite"))
    assert res.verdict == "skip", res.reasons
    llm.apply_assessment(soft, llm.Assessment(fit=7, residency_restriction="remote only within Germany", work_mode="remote"))
    llm.apply_assessment(hard, llm.Assessment(fit=7, residency_restriction="Bulgaria-based candidates only", work_mode="hybrid"))
    llm.apply_assessment(rem, llm.Assessment(fit=7, residency_restriction="must be based in Poland", work_mode="remote"))
    llm.apply_assessment(it, llm.Assessment(fit=7, residency_restriction="Cittadinanza italiana; full on-site a Bari", work_mode="onsite"))
    assert soft.verdict == "live" and any(r.startswith("LLM: просят жить") for r in soft.reasons), soft.reasons
    assert (hard.verdict, rem.verdict, it.verdict) == ("skip", "skip", "skip")
    blocks = lambda q, track, loc: f.residency_blocks(q, track, loc)
    assert not blocks("The candidate has to be in Portugal and open to a hybrid position.", "eu", "Lisbon, Portugal")
    assert not blocks("We live remote-first within Germany", "de", "Berlin, Germany")
    assert blocks("This is a fully remote role for candidates based in Poland or Portugal.", "eu", "Warsaw, Poland")
    assert blocks("EU residency", "eu", "Warsaw, Poland")
    assert blocks("If the applicant is permanently present outside of Portugal, Veeam reserves the right", "eu", "Lisbon, Portugal")
    assert blocks("role associated with Milan office; open to candidates based in Portugal or the UK", "eu", "Milan, Italy")
    assert blocks("Fully remote, full-time work from Slovenia.", "fr", "Paris, France")
    assert blocks("based in Bengaluru in a hybrid work model", "eu", "Kraków, Poland")


def test_fit_has_no_ceiling():
    from jobsearch import llm
    from jobsearch.cli import load_cfg
    load_cfg()
    j = Job(id="c:1", source="linkedin", company="Acme", title="Senior QA", url="u", track="nl", verdict="live",
            score=80, applicants=10, reasons=["фокус: Flutter/Patrol", "фокус: Playwright TS/JS"],
            description="We offer visa sponsorship. " * 20)
    llm.apply_assessment(j, llm.Assessment(fit=9, ai_qa="ai_first", sponsorship="yes"))
    assert j.llm_fit == 19 and j.score > 100, (j.llm_fit, j.score, j.reasons)    # 9 +1 +2 +3 +2 +1 +1


def test_per_company_cap_keeps_best_cards():
    from jobsearch import cli
    rows = [{"company": "BairesDev", "score": s, "id": f"b{s}"} for s in (60, 70, 50, 65)] + [{"company": "Acme", "score": 40, "id": "a"}]
    assert [r["id"] for r in cli.per_company(rows, 2)] == ["b70", "b65", "a"]


def test_salary_ignores_budgets_relocation_and_company_figures():
    assert f.parse_salary("Ongoing personal growth, supported by an annual development budget of €1,500 to invest") is None
    assert f.parse_salary("Relocation support: up to €2,500 and 4 weeks temporary accommodation") is None
    assert f.parse_salary("In 2024 realiseerde Corbion een jaaromzet van € €1.267,4 miljoen en had") is None
    assert round(f.parse_salary("Naast een salaris vanaf €3.016 (afhankelijk van kennis en ervaring)")) == 3016
    assert round(f.parse_salary("Een salaris tussen €2.700,- en €3.473,- per maand. Relocation budget €5,000")) == 3473
    assert round(f.parse_salary("€40,000.00/yr - €45,000.00/yr Groupe international")) == 3750


def test_fingerprint_ignores_legal_form_and_country_of_the_entity():
    fp = lambda company, title="Platform QA Chapter Lead (all genders)": Job(id="x", source="s", company=company,
                                                                             title=title, url="u").fingerprint()
    assert fp("JustPlay GmbH") == fp("JustPlay")
    assert fp("ZEAL Network SE") == fp("Zeal Network")
    assert fp("Luxoft Romania") == fp("Luxoft")
    assert fp("Sii Sp. z o.o.") == fp("Sii Poland") == fp("Sii")
    assert fp("Booking.com B.V.") == fp("Booking.com")
    assert fp("Bank of Ireland") != fp("Bank of Cyprus")            # the country is part of the name here
    assert fp("JustPlay") != fp("JustPlay", "Senior QA Test Automation Engineer (all genders)")
    assert fp("SE") == fp("SE")                                     # a name made only of a tail word stays itself


def test_hardware_skip_copies_are_deduplicated_too():
    from jobsearch import cli, llm
    live = Job(id="d:1", source="s", company="Acme", title="QA", url="u", verdict="live")
    hw = Job(id="d:2", source="s", company="Acme", title="QA", url="u", verdict="skip", reasons=[f.OFF_DOMAIN_REASON])
    lang = Job(id="d:3", source="s", company="Acme", title="QA", url="u", verdict="skip", reasons=["текст на немецком"])
    assert cli.dedup_eligible(live) and cli.dedup_eligible(hw) and not cli.dedup_eligible(lang)
