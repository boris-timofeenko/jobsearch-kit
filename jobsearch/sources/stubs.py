"""Job boards that cannot be read today, kept as named placeholders.

Each stub sits in aggregators.AGGREGATORS under the board's name like a real source, so a config or the country
catalog can list it already: a run logs why nothing comes from it, `check` marks it, and the day access appears a real
fetcher replaces the stub under the same name — no profile changes. Checked 15.11.2026.
"""

BLOCKED = {
    "hh": "hh.ru: с апреля 2026 поиск вакансий в API только с токеном приложения, а токен дают подтверждённым "
          "работодателям после модерации; сайт закрыт DDoS-Guard с капчей",
    "superjob": "SuperJob: API требует ключ приложения (регистрация на api.superjob.ru), источник не написан",
    "getmatch": "GetMatch: вакансии приходят только из /api/, а его закрывает robots.txt; их Telegram-канал можно "
                "добавить в tg_channels",
    "geekjob": "Geekjob: вакансии приходят только из /json/ и /rest/, а их закрывает robots.txt; их Telegram-канал "
               "можно добавить в tg_channels",
}


def stub(name):
    """A source that returns nothing; `blocked` says why (collect logs it, check shows it)."""
    def fetch(http):
        return []
    fetch.__name__ = name
    fetch.blocked = BLOCKED[name]
    return fetch


STUBS = {name: stub(name) for name in BLOCKED}
