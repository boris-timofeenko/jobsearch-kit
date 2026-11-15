"""Job channels in Telegram.

Open channels are read through the public web preview `t.me/s/<name>`: no account, so there is nothing to ban.
The preview lists the latest ~20 posts and pages back with `?before=<id>`; a run reads only posts newer than the last
one stored (table `tg_posts`), the first read of a channel goes `days` back. Every two hours that is one request per
channel, the same posts a subscription would deliver, without a client holding a connection.

Groups and channels with the preview turned off (`t.me/s/<name>` redirects to `t.me/<name>`) need a Telegram
account: `jobsearch tg-login` signs in once into a session of its own (data/tg.session), and the run connects for a
moment, reads the history of the public chat without joining it and disconnects. Joining is what Telegram counts as
spam when done in bulk, and a second client on another program's session breaks that program.

Posts are free text: one vacancy "Title в Company", digests of ten, long descriptions, ads. A post goes to the model
only when one of its lines passes the role's title filter; the model splits it into vacancies (title, company,
location, mode, apply link), and the code keeps those whose title passes the filter. The rest of the pipeline treats
them like any other source: dedup by company + title, heuristics, the fit model, cards.
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel

from ..models import Job

TME = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/?$")
TG_LINK = re.compile(r"//(?:t|telegram)\.me/")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def channel_name(s):
    """`zarubezhom_jobs`, `@zarubezhom_jobs`, `https://t.me/zarubezhom_jobs`, `t.me/s/…` → `zarubezhom_jobs`."""
    s = str(s).strip().lstrip("@")
    m = TME.match(s)
    return (m.group(1) if m else s).lower()


@dataclass
class Post:
    channel: str
    id: int
    date: str                    # ISO, UTC
    text: str
    links: list = field(default_factory=list)
    page: str = ""               # text of the job page a short post links to (page_link), loaded before parsing

    @property
    def url(self):
        return f"https://t.me/{self.channel}/{self.id}"


def post_from_row(r):
    return Post(r["channel"], r["msg_id"], r["posted"], r["text"], json.loads(r["links"] or "[]"), r["page"] or "")


class NoPreview(Exception):
    """t.me/s/<name> redirects: a group, a channel with the preview off, or no such name."""


# ─── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────

def parse_preview(html, channel):
    """Posts on one page of t.me/s/<channel>, oldest first. Text keeps line breaks; a quoted reply is not the post."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for node in soup.select("div.tgme_widget_message[data-post]"):
        try:
            msg_id = int(node["data-post"].rsplit("/", 1)[1])
        except (ValueError, IndexError):
            continue
        texts = [t for t in node.select(".tgme_widget_message_text") if not t.find_parent(class_="tgme_widget_message_reply")]
        when = node.select_one(".tgme_widget_message_date time[datetime]") or node.select_one("time[datetime]")
        if not texts or not when:
            continue
        body = texts[-1]
        for br in body.find_all("br"):
            br.replace_with("\n")
        links = [a["href"] for a in body.select("a[href]") if a["href"].startswith("http")]
        date = datetime.fromisoformat(when["datetime"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(Post(channel, msg_id, date, body.get_text().strip(), links))
    return out


def web_posts(http, channel, after_id=0, since="", max_pages=40):
    """Posts newer than `after_id` and not older than `since` (ISO), oldest first, paging back from the newest."""
    found, before = {}, None
    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        r = http.get(url, allow_redirects=False)
        if r is None:
            raise RuntimeError("t.me не ответил")
        if r.status_code in (301, 302, 303, 307, 308):
            raise NoPreview(channel)
        if r.status_code != 200:
            raise RuntimeError(f"t.me: HTTP {r.status_code}")
        page = parse_preview(r.text, channel)
        if not page:
            break
        for p in page:
            if p.id > after_id and p.date >= since:
                found[p.id] = p
        oldest = page[0]
        if oldest.id <= after_id + 1 or oldest.date < since or oldest.id <= 1:
            break
        before = oldest.id
        http.sleep()
    return [found[i] for i in sorted(found)]


def session_path(data_dir):
    return str(data_dir / "tg")      # Telethon adds .session


def account_ready(data_dir):
    return bool(os.environ.get("TG_API_ID") and os.environ.get("TG_API_HASH")) and \
        os.path.exists(session_path(data_dir) + ".session")


def _client(data_dir):
    from telethon.sync import TelegramClient
    # receive_updates=False: a reader, not a listener; nothing else of the account is touched
    return TelegramClient(session_path(data_dir), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"],
                          receive_updates=False, flood_sleep_threshold=120)


def login(data_dir):
    """Interactive sign-in into a session used only by jobsearch (phone, code from Telegram, 2FA password)."""
    from getpass import getpass
    if not (os.environ.get("TG_API_ID") and os.environ.get("TG_API_HASH")):
        raise SystemExit("нужны TG_API_ID и TG_API_HASH в .env (my.telegram.org → API development tools)")
    data_dir.mkdir(parents=True, exist_ok=True)
    client = _client(data_dir)
    client.start(phone=lambda: input("Номер аккаунта (+…): "), code_callback=lambda: input("Код из Telegram: "),
                 password=lambda: getpass("Пароль 2FA (если есть): "))
    me = client.get_me()
    client.disconnect()
    os.chmod(session_path(data_dir) + ".session", 0o600)    # the session file is full access to the account
    return f"{me.first_name or ''} (@{me.username or '—'})".strip()


def account_posts(data_dir, channels, after, since, limit=3000):
    """{channel: posts newer than after[channel] and not older than `since`} for public groups and channels read with
    the account, one short connection for all of them, without joining. Replies inside a discussion are skipped:
    vacancies are top-level messages. Telethon waits out a FloodWait of up to two minutes by itself."""
    from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl
    client = _client(data_dir)
    client.connect()
    out = {}
    try:
        if not client.is_user_authorized():
            raise RuntimeError("сессия Telegram не авторизована: python -m jobsearch tg-login")
        for ch in channels:
            posts = []
            for m in client.iter_messages(ch, min_id=after.get(ch, 0), limit=limit):
                date = m.date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if date < since:
                    break
                reply = m.reply_to
                if reply and not (getattr(reply, "forum_topic", False) and reply.reply_to_top_id is None):
                    continue
                if not m.message:
                    continue
                links = [e.url for e in m.entities or [] if isinstance(e, MessageEntityTextUrl)]
                links += [m.message[e.offset:e.offset + e.length] for e in m.entities or []
                          if isinstance(e, MessageEntityUrl)]
                posts.append(Post(ch, m.id, date, m.message, [u for u in links if u.startswith("http")]))
            out[ch] = posts[::-1]
    finally:
        client.disconnect()
    return out


# ─── posts → vacancies ────────────────────────────────────────────────────────────────────────────────────────────

def page_link(post):
    """The job page behind a short post («Senior QA в inDrive. Описание вакансии» with a link): the city and the
    requirements are often only there, and the model needs them to place the job. Long posts carry the text
    themselves; a digest links a page per role, those are loaded per vacancy after parsing."""
    ext = list(dict.fromkeys(u for u in post.links if not TG_LINK.search(u)))
    return ext[0] if ext and len(ext) <= 2 and len(post.text) < 1500 else ""


def title_lines(text, is_relevant):
    """Short lines of the post that pass the role's title filter: the cheap test before the model."""
    out = []
    for line in text.splitlines():
        line = EMOJI.sub(" ", line).strip(" -—–•|#*:")
        if 3 <= len(line) <= 100 and is_relevant(line):
            out.append(re.sub(r"\s+", " ", line))
    return out


class Vacancy(BaseModel):
    title: str
    company: str = ""
    location: str = ""
    work_mode: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    apply_url: str = ""
    fragment: str = ""


class PostVacancies(BaseModel):
    vacancies: list[Vacancy] = []


EXTRACT_SYSTEM = """Ты разбираешь пост из Telegram-канала с вакансиями. Верни JSON {"vacancies": [...]}, по объекту на
каждую вакансию из поста, у которой заголовок похож на один из заголовков, перечисленных в запросе; остальные
вакансии поста (другие роли) пропусти. Реклама, курсы, статьи, резюме соискателей, «ищу работу» — пустой список.

Поля вакансии:
- title — название должности как в посте, без эмодзи, уровня в скобках не добавляй;
- company — работодатель; если пост от агентства и клиент не назван — название агентства; не назван никто — "";
- location — где офис: «City, Country» по-английски; несколько — через « / »; remote — «Remote» и регион в скобках,
  если он указан («Remote (Europe)», «Remote (Russia)», «Remote (worldwide)»); при релокации в страну — эта страна;
  ничего не сказано — "";
- work_mode — remote / hybrid / onsite / unknown;
- apply_url — ссылка на вакансию или отклик из списка ссылок поста (не ссылка на другой канал), иначе "";
- fragment — только если в посте несколько вакансий: дословный кусок поста про эту вакансию; иначе "".
Если к посту приложен текст страницы вакансии, недостающее (город, страна, режим работы) бери оттуда.
Ничего не выдумывай: чего нет ни в посте, ни на странице, оставь пустым."""


def extract_prompt(post, lines):
    links = "\n".join(f"- {u}" for u in post.links[:30]) or "(нет)"
    return (f"Заголовки, похожие на нужную роль: {'; '.join(lines[:20])}\n\nСсылки поста:\n{links}\n\n"
            f"Пост {post.url} от {post.date[:10]}:\n{post.text[:6000]}"
            + (f"\n\nТекст страницы по ссылке из поста:\n{post.page[:4000]}" if post.page else ""))


def to_jobs(post, vacancies, is_relevant):
    """Job objects for the vacancies whose title passes the filter. The card links to the post: the apply route
    (a form, a recruiter's handle, a job page) is there. With several vacancies each gets its own id and fragment."""
    keep = [v for v in vacancies if v.title.strip() and is_relevant(v.title)]
    out = []
    for n, v in enumerate(keep, 1):
        text = v.fragment.strip() if len(keep) > 1 and len(v.fragment.strip()) > 80 else post.text
        if len(keep) == 1 and post.page:
            text += "\n\n— страница вакансии —\n" + post.page[:6000]
        loc = v.location.strip()
        remote = v.work_mode == "remote" or loc.lower().startswith("remote")
        if remote and not loc:
            loc = "Remote"
        j = Job(id=f"telegram:{post.channel}/{post.id}" + (f"/{n}" if len(keep) > 1 else ""), source="telegram",
                company=v.company.strip(), title=v.title.strip()[:200], url=post.url, location=loc[:200],
                posted=post.date[:10], remote=remote, description=text)
        j.extra["apply_url"] = v.apply_url.strip()
        j.extra["channel"] = post.channel
        if v.work_mode in ("hybrid", "onsite"):
            j.extra["work_mode"] = v.work_mode
        out.append(j)
    return out


def since_iso(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
