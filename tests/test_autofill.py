from datetime import date

from jobsearch import autofill as a

# made-up CV with the same markup as the real one (the real tex is personal and not in git)
TEX = r"""\documentclass{article}
\newcommand{\cvheadline}{Senior SDET / Test Automation Engineer}
\newcommand{\cvlocation}{Located in Belgrade, Serbia. Open to relocation.}
\newcommand{\cvworkauth}{Non-EU national.}
\newcommand{\ca}{\ensuremath{\approx}}
\begin{document}
{\LARGE\bfseries\color{inkc}Alex Example}\par\vspace{3pt}
{\large \cvheadline}\par
{\raggedright
\cvlocation\par
\href{tel:+381601234567}{+381 60 123 4567}\quad
\href{mailto:alex@example.com}{alex@example.com}\par
\href{https://linkedin.com/in/alex-example}{linkedin.com/in/alex-example}\quad
\href{https://t.me/alex_example}{t.me/alex\_example}\quad
\href{https://github.com/alex-example}{github.com/alex-example}\par}

\cvsection{LANGUAGES}
% comment
English: C1 \sep{} Russian: Native

\cvsection{SUMMARY}
Senior SDET with 8 years in software. Serving \ca{}100k users.

\cvsection{SKILLS}
\skillrow{Test Automation}{Playwright (TypeScript/JavaScript), PyTest}
\skillrow{Engineering}{Python, Docker}

\cvsection{EXPERIENCE}
\role{QA Tech Lead}{Acme Pay}{Nov 2025 -- Present}
\ctx{Johannesburg, South Africa (remote). Fintech, \ca{}100k active users.}
\begin{duties}
  \item Built automation from 0 to \ca{}450 scenarios, 65\% of regression.  % cv:pin
  \item Lead a team of 3 QA engineers.
\end{duties}
\nextrole
\role{QA Engineer $\rightarrow$ Senior QA Engineer}{Travel Soft}{Sep 2021 -- Aug 2025}
\ctx{Remote (Montenegro). B2B travel-tech.}
\begin{duties}
  \item Grew coverage from 80 to 550 cases.
\end{duties}

\cvsection{EDUCATION}
\textcolor{inkc}{\bfseries MSc, Big Data and Machine Learning}\sep{}ITMO University, Saint Petersburg\hfill\dt{2020--2022}\par
\textcolor{inkc}{\bfseries BSc, Applied Mathematics}\sep{}Far Eastern Federal University, Vladivostok\hfill\dt{2016--2020}
\end{document}
"""

BANK = {
    "skills": {"extra": {"Test Automation": ["WireMock", "PyTest"]}},
    "autofill": {"address": "Example street 1", "postal_code": 11000, "notice_period": "1 month",
                 "salary": {"monthly": 5500, "annual": 66000, "text": "EUR 5,500 gross per month"}},
}


def test_contacts_and_links():
    p = a.build(TEX, BANK, today=date(2026, 9, 24))
    pe = p["person"]
    assert (pe["first_name"], pe["last_name"], pe["full_name"]) == ("Alex", "Example", "Alex Example")
    assert pe["email"] == "alex@example.com"
    assert pe["phone"] == {"e164": "+381601234567", "international": "+381 60 123 4567", "country_code": "+381",
                           "national": "60 123 4567"}
    assert pe["linkedin"] == "https://www.linkedin.com/in/alex-example"
    assert pe["github"] == "https://github.com/alex-example"
    assert pe["telegram"] == "https://t.me/alex_example"
    assert p["location"]["display"] == "Belgrade, Serbia"
    assert p["location"]["postal_code"] == "11000"
    assert p["headline"] == "Senior SDET / Test Automation Engineer"
    assert p["summary"] == "Senior SDET with 8 years in software. Serving ~100k users."
    assert p["cv_name"] == "Alex_Example_CV.pdf"


def test_experience_dates_and_locations():
    ex = a.build(TEX, BANK)["experience"]
    assert [e["company"] for e in ex] == ["Acme Pay", "Travel Soft"]
    assert ex[0]["start"] == {"year": 2025, "month": 11} and ex[0]["end"] is None and ex[0]["current"]
    assert ex[0]["location"] == "Johannesburg, South Africa" and ex[0]["remote"]
    assert ex[0]["description"].startswith("- Built automation from 0 to ~450 scenarios, 65% of regression.")
    assert "cv:pin" not in ex[0]["description"]
    assert ex[1]["title"] == "Senior QA Engineer"                     # the last step of "QA Engineer → Senior QA"
    assert ex[1]["title_history"] == ["QA Engineer", "Senior QA Engineer"]
    assert ex[1]["location"] == "Montenegro"
    assert ex[1]["end"] == {"year": 2025, "month": 8}


def test_education_languages_skills():
    p = a.build(TEX, BANK)
    ed = p["education"]
    assert ed[0] == {"degree": "MSc", "degree_full": "Master of Science", "field": "Big Data and Machine Learning",
                     "school": "ITMO University", "city": "Saint Petersburg", "start": {"year": 2020}, "end": {"year": 2022}}
    assert ed[1]["degree_full"] == "Bachelor of Science"
    assert p["languages"] == [{"name": "English", "level": "C1"}, {"name": "Russian", "level": "Native"}]
    assert p["skills"] == ["Playwright (TypeScript/JavaScript)", "PyTest", "Python", "Docker", "WireMock"]   # no duplicate PyTest


def test_answers_come_from_bank_with_defaults():
    ans = a.build(TEX, BANK)["answers"]
    assert ans["work_authorized"] is False
    assert ans["notice_period"] == "1 month"
    assert ans["heard_about"] == "LinkedIn"
    assert ans["salary"]["annual"] == 66000
    empty = a.build(TEX, {})
    assert empty["location"]["address"] == "" and empty["answers"]["salary"] == {}


def test_parse_date():
    assert a.parse_date("Present") is None
    assert a.parse_date("Sept. 2021") == {"year": 2021, "month": 9}
    assert a.parse_date("2019") == {"year": 2019}
