"""Резервный транспорт hiringcafe: настоящий headful Google Chrome под Xvfb на VPS.

HiringCafe под Cloudflare «managed challenge» для датацентровых IP: HTML и /api GET отвечают 403
(cf-mitigated: challenge), keyless Jina только пересылает challenge обратно, headless-браузеры
замирают на загрузке, а cf_clearance, выполненный через CDP, не принимается. Работает headful
настоящий google-chrome 157 (apt, dl.google.com) под Xvfb, причём БЕЗ CDP-автоматизации — челлендж
решается кликом по чекбоксу Turnstile, координаты которого ищутся по пикселям оранжевого облака
(scrot + pillow), а клик — «человеческим» движением xdotool. После одного решения все навигации
этой сессии проходят без челленджа (cf_clearance живёт ~30 мин, дольше дневного батча; истёк —
снова виден по заголовку окна «Just a moment» и решается заново).

SSR-страницы (/classic?searchState=...) сохраняются Ctrl+S через GTK-диалог (там есть
__NEXT_DATA__.pageProps.ssrHits — парсер тот же, что у Jina). JSON /api/job-description нельзя
сохранить («File wasn't available on site», 04.11) и view-source: из командной строки Chrome
молча отбрасывает (вместо исходника открыта вкладка Google) — открываем URL как обычную
страницу и Ctrl+A/Ctrl+C через xclip. До первого рендера 15–25 с пустых кадров (замер: JSON
дал пиксели на 21-й, SSR на 15-й), до рендера Ctrl+S не открывает диалог и Ctrl+A ловит
пустоту — ждём тёмные пиксели в области страницы. Диалог Ctrl+S подтверждаем по
синей рамке поля Name (единственная синяя полоса кадра сверху; клики координатами без
диалога прожимают страницу — 04.11). Если два полных цикла не дают ничего — профиль
уносим в aside (<профиль>.broken-* в data/hc-chrome/) и начинаем новый. Любая ошибка
любого шага → None, наверх уходит прежняя цепочка.

Включение: HC_CHROME=on|off|auto (по умолчанию auto — транспорт активен, когда на месте есть
google-chrome, xvfb, xdotool, scrot, xclip и pillow; ноутбук из-за этого остаётся на MCP→Jina→ChatGPT).
Без ключей и внешних аккаунтов. Скорость ограничена самой механикой (10–25 с на страницу), а объём —
тем, что транспорт включается только после отказа основного MCP.

Геометрия снята 04.11.2026 на VPS (окно 1360x900): чекбокс ~(253,422), поле «Name» GTK-диалога
сохранения ~(558,25), кнопка «Save» ~(1062,799); Return диалог не активирует, поэтому Save — кликом.
Хвосты прошлых запусков (singleton-папки /tmp/com.google.Chrome.*, старые сохранения HiringCafe
в Downloads) убираются при холодном старте Chrome; моложе часа — не трогаем.
"""
import fcntl
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..config import DATA as _DATA

SETTINGS = {}             # chrome_display / chrome_profile from the hiringcafe config section (aggregators.configure)
_LOGDIR = _DATA / "logs" / "hc-chrome"
_WINDOW = (1360, 900)

# цвет оранжевого облака Cloudflare на кадре scrot: r > 215, 90 < g < 170, b < 70; чекбокс стоит
# левее левого края облачка на снятый по кадру 04.11 сдвиг; на случай, если поиск по пикселям не
# сработал (помешал баннер), — координаты-запас из опыта
_CLOUD_RGB = (215, 90, 170, 70)
_CLOUD_TO_BOX_DX = -245
_DEFAULT_BOX = (253, 422)
_SAVE_NAME = (558, 25)     # поле «Name» GTK-диалога Ctrl+S
_SAVE_BTN = (1062, 799)    # кнопка «Save» (Return диалог не закрывает — проверено 04.11)
_XTOOLS = ("google-chrome", "xdotool", "scrot", "xclip", "Xvfb")

_SESSION = None


def _log(msg):
    from datetime import datetime
    print(f"[{datetime.now():%H:%M:%S}] hc-chrome: {msg}", flush=True)


def _missing():
    out = [b for b in _XTOOLS if not shutil.which(b)]
    try:
        import PIL  # noqa: F401
    except ImportError:
        out.append("pillow")
    return out


def enabled():
    """HC_CHROME=off|on|auto (по умолчанию auto): в auto транспорт включён, когда есть все утилиты.
    В тестах всегда выключен: настоящие клики в pytest не место."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return _active()


def _active():
    """Тот же выбор без pytest-охраны — для тестов и doctor-проверок."""
    mode = os.environ.get("HC_CHROME", "auto").strip().lower()
    if mode == "off":
        return False
    missing = _missing()
    if missing:
        if mode == "on":
            _log(f"HC_CHROME=on, но нет {', '.join(missing)} — транспорт выключен")
        return False
    if mode not in ("on", "auto"):
        _log(f"HC_CHROME={mode} не понят (on|off|auto), считаю auto")
    return True


def _settings():
    """chrome_display / chrome_profile из секции hiringcafe config.yaml (секции может не быть).
    Профиль в data/: живёт дольше перезапусков, в нём cf_clearance, доступен jobsearch-пользователю."""
    display, profile_path = "99", _DATA / "hc-chrome" / "profile"
    if SETTINGS.get("chrome_display"):
        display = str(SETTINGS["chrome_display"])
    if SETTINGS.get("chrome_profile"):
        profile_path = Path(str(SETTINGS["chrome_profile"]))
    return display, profile_path


def _pids(pattern):
    """PID по cmdline (pgrep -f). Паттерн начинается с «--user-data-…», поэтому после -f обязателен
    `--`: pgrep иначе ловит его за собственную опцию и тихо возвращает пусто (по этой ошибке 04.11
    пережили убийство несколько Chrome и копились окна, пока _title() читал самое старое)."""
    try:
        r = subprocess.run(["pgrep", "-f", "--", pattern], capture_output=True, text=True, timeout=10)
        return [int(x) for x in r.stdout.split()] if r.stdout.strip() else []
    except Exception:
        return []


class _Session:
    IDLE_QUIT = 600  # chrome с решённым челленджем не держим навсегда: 10 мин простоя — убить до следующего вызова

    def __init__(self):
        display, profile = _settings()
        self.display = display
        self.profile = profile           # --user-data-dir
        self.env = dict(os.environ, DISPLAY=f":{display}")
        self.downloads = Path.home() / "Downloads"
        self.chrome = None               # Popen
        self.lock = None                 # файловый lock: Chrome держит один процесс
        self.last_use = 0.0
        self.blank_starts = 0            # два пустых запуска подряд — уносим профиль в aside

    # ------------------------------------------------------------ запуск/остановка
    def _acquire_lock(self):
        if self.lock:
            return True
        try:
            handle = open(_DATA / ".hc-chrome.lock", "w")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _log("другой процесс уже управляет Chrome, транспорт пропущен")
                handle.close()
                return False
            self.lock = handle
            return True
        except OSError as e:
            _log(f"файловый lock: {e}")
            return False

    def _ensure_display(self):
        """Xvfb поднимается лениво и живёт между вызовами; бесполезен без lock-файла от прошлого владельца."""
        if _pids(f"Xvfb :{self.display} "):
            return
        stale = Path(f"/tmp/.X{self.display}-lock")
        try:
            if stale.exists():
                stale.unlink()
        except OSError as e:
            raise RuntimeError(f"не убрать {stale} ({e}) — возможно, создан другим пользователем") from e
        subprocess.Popen(["Xvfb", f":{self.display}", "-screen", "0",
                          f"{_WINDOW[0]}x{_WINDOW[1]}x24", "-nolisten", "tcp"],
                         env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(16):
            time.sleep(0.5)
            if _pids(f"Xvfb :{self.display} "):
                return
        raise RuntimeError("Xvfb не поднялся за 8 с")

    def _profile_pids(self):
        return _pids("--user-data-dir=" + str(self.profile))

    def _kill_pids(self, pids):
        """SIGTERM и ожидание выхода до 6 с, сироты — KILL. Жёсткий KILL остаётся последним
        шагом: запись профиля посреди такого убийства — риск для следующего запуска."""
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        live = list(pids)
        deadline = time.time() + 6
        while time.time() < deadline and live:
            live = [pid for pid in live if self._pid_alive(pid)]
            if live:
                time.sleep(0.4)
        for pid in live:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    @staticmethod
    def _pid_alive(pid):
        try:
            os.kill(pid, 0)          # PermissionError значит «жив» — ESRCH был бы уже мёртв
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    def _kill_stale(self):
        """Chrome на том же профиле конкурирует за singleton: прибить — обычно от прошлого простоя."""
        pids = self._profile_pids()
        if not pids:
            return
        _log(f"убиваю чужой Chrome на моём профиле: {pids}")
        self._kill_pids(pids)
        time.sleep(1)

    def _kill_chrome(self):
        self._kill_stale()
        self.chrome = None
        self.last_use = 0.0
        # blank_starts не трогаем: счетчик переживает рестарты, сброс — только успех и восстановление

    def _sweep_residue(self, max_age=3600, tmpdir=None):
        """Хвосты прошлых запусков: singleton-папки Chrome в /tmp (копились) и забытые сохранения
        Ctrl+S в Downloads (уходят, когда _absorb не доехал после падения цикла). Вызывается только
        перед стартом нового Chrome — папку и следы живого экземпляра не заденем. Свежее, моложе
        часа, не трогаем: возможно, это работа ещё живого процесса."""
        tmpdir = tmpdir or Path("/tmp")

        def _old(p):
            try:
                return time.time() - p.stat().st_mtime > max_age
            except OSError:
                return False

        gone = 0
        try:
            for p in tmpdir.glob("com.google.Chrome.*"):
                if _old(p) and p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    if not p.exists():
                        gone += 1
        except OSError as e:
            _log(f"чистка /tmp: {e}")
        try:
            self.downloads.mkdir(parents=True, exist_ok=True)
            for p in sorted(self.downloads.iterdir()):
                n = p.name
                ours = (" _ HiringCafe" in n or n.startswith("Just a moment")) \
                    and n.endswith((".html", "_files", ".crdownload"))
                if not ours or not _old(p):
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    if p.exists():
                        continue
                else:
                    p.unlink(missing_ok=True)
                gone += 1
        except OSError as e:
            _log(f"чистка Downloads: {e}")
        if gone:
            _log(f"чистка хвостов: убрано {gone}, старше {max_age // 60} мин")

    def _heal_profile(self):
        """Бывают запуски, когда страница вообще не рисует: первый рендер на свежем Chrome
        медленный, SSR-поток иногда зависает. Виновность профиля не доказана — тот же профиль
        позже работал как ни в чём не бывало. Лечим не причину, а частоту потерь: два полных
        цикла подряд без файла, диалога и челленджа — профиль в aside, начинаем новый.
        Челлендж нового профиля решится сам, цена ошибки — пара минут, а не ночная выдача."""
        if self.blank_starts < 2:
            return
        bak = self.profile.with_name(self.profile.name + f".broken-{time.strftime('%d-%H%M%S')}")
        try:
            self.profile.rename(bak)
            _log(f"профиль дал два пустых запуска подряд — убран в {bak.name}, начинаю новый")
            self.blank_starts = 0
        except OSError as e:
            _log(f"не унести профиль в aside ({e}) — транспорт продолжит на нём")

    def _focus(self):
        """Без оконного менеджера никто не ведёт стек и фокус: сами поднимаем и фокусируем окно.
        Иначе клавиши уходят в мёртвое окно прошлого запуска, а клики попадают не в тот Chrome."""
        if not (self.chrome and self.chrome.poll() is None):
            return
        try:
            ids = (self._x(["search", "--pid", str(self.chrome.pid)]).stdout or "").split()
            if not ids:
                return
            self._x(["windowraise", ids[0]], timeout=10)
            self._x(["windowfocus", "--sync", ids[0]], timeout=15)
        except Exception:
            pass

    def _start_chrome(self):
        cmd = ["google-chrome", f"--user-data-dir={self.profile}", "--no-first-run",
               "--no-default-browser-check", "--disable-crashpad", "--disable-component-update",
               "--disable-session-crashed-bubble", f"--window-size={_WINDOW[0]},{_WINDOW[1]}",
               "--lang=en-US", "about:blank"]
        self.chrome = subprocess.Popen(cmd, env=self.env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 25
        while time.time() < deadline:
            time.sleep(0.8)
            if self._title():
                time.sleep(1.5)          # хвост запуска: вкладка должна отработать ввод
                self._focus()
                return True
            if self.chrome.poll() is not None:
                break
        return False

    def ensure(self):
        now = time.time()
        if self.chrome and self.chrome.poll() is None and self.last_use and now - self.last_use > self.IDLE_QUIT:
            _log("простой 10+ минут — убиваю Chrome (профиль с cf_clearance сохранится)")
            self._kill_chrome()
        if not self._acquire_lock():
            return False
        try:
            self._ensure_display()
            if self.chrome and self.chrome.poll() is None:
                pass                                  # наш живой Chrome — переиспользуем, только обработаем простой
            else:
                self._sweep_residue()                 # хвосты прошлых запусков: до старта нового Chrome
                self._kill_stale()
                if not self._start_chrome():
                    raise RuntimeError("окно Chrome не появилось за 25 с")
            self.downloads.mkdir(parents=True, exist_ok=True)
            self.last_use = now
            return True
        except Exception as e:
            _log(f"Chrome не готов: {e}")
            self._kill_chrome()
            return False

    # ------------------------------------------------------------ xdotool / буфер / скрин
    def _x(self, args, timeout=20):
        return subprocess.run(["xdotool", *args], env=self.env, capture_output=True, text=True,
                              timeout=timeout)

    def _title(self):
        """Заголовок активного окна. Без оконного менеджера getactivewindow не работает
        (_NET_ACTIVE_WINDOW нет, проверка 04.11) — поэтому окно ищем по PID главного процесса
        Chrome; фолбэк по всем видимым окнам — только если PID-путь не дал ничего."""
        try:
            t = (self._x(["getactivewindow", "getwindowname"]).stdout or "").strip()
            if t:
                return t
        except Exception:
            pass
        try:
            ids = []
            if self.chrome and self.chrome.poll() is None:
                ids = (self._x(["search", "--pid", str(self.chrome.pid)]).stdout or "").split()
            if not ids:
                ids = (self._x(["search", "--onlyvisible", "."]).stdout or "").split()
            for wid in ids:
                t = (self._x(["getwindowname", wid]).stdout or "").strip()
                if t:
                    return t
        except Exception:
            pass
        return ""

    def _challenge(self):
        t = self._title().lower()
        return "just a moment" in t or "attention required" in t or "checking your browser" in t

    def _key(self, keys, pause=0.4):
        self._x(["key", "--delay", "60", keys])
        time.sleep(pause)

    def _pointer(self):
        m = re.search(r"x:(\d+) y:(\d+)", self._x(["getmouselocation"]).stdout or "")
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def _clipboard(self, text):
        subprocess.run(["xclip", "-selection", "clipboard", "-in"], env=self.env,
                       input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)

    def _clipboard_text(self, timeout=12):
        r = subprocess.run(["xclip", "-selection", "clipboard", "-out"], env=self.env,
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""

    def _screenshot(self):
        try:
            _LOGDIR.mkdir(parents=True, exist_ok=True)
            path = _LOGDIR / f"screen-{time.strftime('%d-%H%M%S')}.png"
            subprocess.run(["scrot", "-o", str(path)], env=self.env, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not path.exists():
                return None
            self._prune()
            return path
        except Exception as e:
            _log(f"scrot: {e}")
            return None

    def _prune(self, keep=20):
        """Диагностика без архива: скрины и сохранённые страницы старше 20 штук — в мусор."""
        try:
            files = sorted(_LOGDIR.glob("*"), key=lambda p: p.stat().st_mtime)
            for old in files[:-keep]:
                old.unlink()
        except OSError:
            pass

    def _human_click(self, x, y):
        """3–5 шагов движения с джиттером и пауза «подумал» перед кликом — иначе Turnstile молчит."""
        x = max(5, min(_WINDOW[0] - 5, x + random.randint(-3, 3)))
        y = max(5, min(_WINDOW[1] - 5, y + random.randint(-3, 3)))
        x0, y0 = self._pointer()
        n = random.randint(3, 5)
        for i in range(1, n + 1):
            px = x0 + round((x - x0) * i / n) + random.randint(-2, 2)
            py = y0 + round((y - y0) * i / n) + random.randint(-2, 2)
            self._x(["mousemove", "--sync", str(px), str(py)], timeout=10)
            time.sleep(random.uniform(0.06, 0.22))
        time.sleep(random.uniform(0.25, 0.7))
        self._x(["click", "1"], timeout=10)
        time.sleep(0.3)

    # ------------------------------------------------------------ челлендж и загрузка
    def _solve(self, attempts=3):
        """Клики по виджету, который ищем на живом скрине: титул под challenge не меняется, а F5
        после клика откатывал решение — страница проходит «Verification successful. Waiting for
        …» с тем же титулом «Just a moment…» (свежий профиль, 04.11), перезагрузка снова подставляла
        виджет. Успех — виджет исчез с экрана; после этого даём странице дозагрузиться."""
        for attempt in range(1, attempts + 1):
            time.sleep(random.uniform(1.2, 2.4))
            png = self._screenshot()
            pos = _find_checkbox(png) if png else None
            if not pos:
                if "just a moment" not in self._title().lower():
                    return True             # виджета нет и титул не челлендж: уже прошло само
                pos = _DEFAULT_BOX          # титул челленджа, а пикселей не видно — координаты из опыта
            _log(f"челлендж: клик по чекбоксу {pos} (попытка {attempt})")
            self._human_click(*pos)
            for _ in range(9):              # ~36 с на решение и подгрузку содержимого
                time.sleep(4)
                png = self._screenshot()
                if png and not _find_checkbox(png):
                    time.sleep(4)           # хвост «Waiting for hiringcafe.com to respond»
                    return True
        return False

    def navigate(self, url):
        """URL передаётся запущенному экземпляру (открывается новый таб и становится активным).
        Набивание омнибокса клавишами ненадёжно: после рестарта Chrome дважды молчало, а титул
        окна под challenge оставался «google-chrome» (04.11) — поэтому решение и загрузка не
        определим по титулу: виджет ищем на скрине, а содержимое проверяем по сохранённому файлу."""
        self._focus()
        subprocess.Popen(["google-chrome", f"--user-data-dir={self.profile}", url], env=self.env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(2.5)

    def _challenge_seen(self):
        """Челлендж — по заголовку окна и по виджету на скрине: без WM титул может не обновиться."""
        t = self._title().lower()
        if "just a moment" in t or "attention required" in t:
            return True
        png = self._screenshot()
        return bool(png and _find_checkbox(png))

    def _challenge_text(self, html):
        """Сохранили страницу-заглушку Cloudflare: метки в служебных блоках разметки."""
        head = html[:20000]
        return "Performing security verification" in head or "Just a moment" in head

    def _click_body(self):
        """Клик в пустое место страницы до выделения: свежий Chrome открывает таб с фокусом в
        омнибоксе, и Ctrl+A/Ctrl+C копировал адрес классической страницы вместо исходника
        (04.11, verify_prod). После клика выделение идёт по документу."""
        self._human_click(680, 700)

    def _grab_selection(self):
        self._click_body()
        self._key("ctrl+a", pause=0.4)
        self._key("ctrl+c", pause=0.8)
        return self._clipboard_text().strip()

    # ------------------------------------------------------------ сохранение и чтение
    def _save_dialog_open(self):
        """Диалог Ctrl+S подтверждаем по синей рамке поля Name — единственной синей полосе кадра
        сверху (GTK-кнопка Save в этой теме серая, цвета у неё нет). Страница в загрузке диалог
        вообще не открывает (04.11, «Loading…»), а клики по _SAVE_NAME/_SAVE_BTN без диалога
        прожимают страницу под этими координатами и уводят вкладку в другое место."""
        png = self._screenshot()
        if not png:
            return False
        try:
            from PIL import Image
            img = Image.open(png).convert("RGB")
            px = img.load()
            hits = 0
            for yy in range(10, 54, 2):
                for xx in range(60, 1120, 2):
                    r, g, b = px[xx, yy]
                    if r < 80 and 60 < g < 160 and b > 190 and b - g > 70:
                        hits += 1
            return hits >= 25
        except Exception as e:
            _log(f"поиск диалога: {e}")
            return False

    def _save_page(self, since):
        """Ctrl+S → диалог подтверждаем по синей рамке поля Name → клик «Name», клик «Save»,
        забрать новейший *.html из Downloads. Диалог не открылся (страница ещё грузится) —
        без кликов: Escape и Ctrl+S заново, до 4 раундов. Клик жмёт страницу только когда
        диалог реально виден."""
        for _ in range(4):
            self._key("ctrl+s", pause=2.0)
            if self._save_dialog_open():
                self._human_click(*_SAVE_NAME)
                time.sleep(0.5)
                self._human_click(*_SAVE_BTN)
                path = self._newest_download(".html", since, wait=22)
                if not path:
                    self._human_click(*_SAVE_BTN)   # диалог открыт — повтор кнопки безвреден
                    path = self._newest_download(".html", since, wait=12)
                if path:
                    html = path.read_text(encoding="utf-8", errors="replace")
                    self._absorb(path)
                    return html
            else:
                _log("диалог Ctrl+S не открыт — страница ещё грузится, Escape и Ctrl+S заново")
            self._key("escape", pause=0.8)
        raise RuntimeError("Ctrl+S не открыл диалог и файла нет")

    def _newest_download(self, ext, since, wait):
        deadline = time.time() + wait
        newest, newest_at = None, 0.0
        while time.time() < deadline:
            for p in list(self.downloads.iterdir()):
                if not p.name.endswith(ext):
                    continue
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m >= since - 1 and m > newest_at:
                    newest, newest_at = p, m
            if newest:
                return newest
            time.sleep(1)
        return None

    def _absorb(self, path):
        """Сохранённую страницу переносим в data/logs/hc-chrome (диагностика), хвост в мусор."""
        try:
            _LOGDIR.mkdir(parents=True, exist_ok=True)
            dst = _LOGDIR / f"ssr-{time.strftime('%d-%H%M%S')}.html"
            shutil.move(str(path), dst)
            assets = path.parent / (path.name[:-len(".html")] + "_files")
            shutil.rmtree(assets, ignore_errors=True)
            self._prune()
        except OSError as e:
            _log(f"не перенести сохранённую страницу: {e}")

    def page_html(self, url):
        """HTML SSR-страницы. Загрузку проверяем по факту: решаем виджет, сохраняем Ctrl+S, текст
        сохранёнки не должен быть заглушкой (титул окна без WM ненадёжен, DOM без CDP не достать;
        сохранение самой заглушки даёт файл в 4 байта, 04.11). Ошибки сохранения — признак «ещё не
        готово», цикл продолжается; удачная попытка закрывается Ctrl+W, чтобы табы не копились."""
        started = time.time()
        self.navigate(url)
        saw_challenge = saw_file = False
        for attempt in range(6):
            if self._challenge_seen():
                saw_challenge = True
                if not self._solve():
                    raise RuntimeError("челлендж не решён, страница не загрузилась")
            self._wait_render()          # Ctrl+S до рендера не открывает диалог (замер 04.11)
            html = None
            try:
                html = self._save_page(started)
                saw_file = True
            except Exception as e:
                _log(f"сохранение не дало файл ({e}); жду содержимого и повторяю")
            if html and not self._challenge_text(html) and len(html) >= 2000:
                self._key("ctrl+w", pause=0.5)
                self.blank_starts = 0
                return html
            html = None
        # ни файла, ни диалога, ни челленджа за всё время — страница не рисовалась;
        # это пустой запуск для heal
        if not (saw_challenge or saw_file):
            self._kill_chrome()      # восстановлению нужен мёртвый Chrome
            self.blank_starts += 1
            _log(f"пустой запуск #{self.blank_starts}: ни файла, ни диалога, ни челленджа за весь цикл")
            self._heal_profile()
        raise RuntimeError("страница не сохранилась без челленджа")

    def json_text(self, url):
        """Тело JSON-ответа. view-source: из командной строки Chrome молча отбрасывает
        (04.11: вместо исходника открывалась вкладка «Ask Google» новой страницы) — открываем
        сам URL и Ctrl+A/Ctrl+C через _grab_selection. Свежий Chrome на Xvfb рендерит
        15–25 с (замер: JSON-endpoint впервые дал пиксели на 21-й), до рендера Ctrl+A ловит
        пустоту — ждём тёмные пиксели между попытками."""
        self.navigate(url)
        body = ""
        for attempt in range(3):
            if self._challenge_seen() and not self._solve():
                raise RuntimeError("челлендж не решён (json)")
            self._wait_render()
            body = self._grab_selection()
            if body.startswith(("{", "[")):
                self._key("ctrl+w", pause=0.5)
                self.blank_starts = 0
                return body
            self.navigate(url)
        self._key("ctrl+w", pause=0.5)
        raise RuntimeError(f"в буфере не JSON ({(body or 'пусто')[:60]!r})")

    def _wait_render(self, total=45, step=5):
        """До первого рендера любой страницы на свежем Chrome/Xvfb 15–25 с пустого кадра
        (замер 04.11); Ctrl+S и Ctrl+A до рендера бесполезны — диалог не открывается."""
        deadline = time.time() + total
        while time.time() <= deadline:
            png = self._screenshot()
            if png and _frame_has_text(png):
                return True
            time.sleep(step)
        return False


def _frame_has_text(png):
    """Есть ли вообще текст на кадре: тёмные пиксели в области страницы (обойдены рамка окна и
    панель Chrome). Первый рендер на свежем Chrome/Xvfb занимает 15–25 с (замер 04.11:
    JSON-endpoint впервые дал тёмные пиксели на 21-й), до рендера Ctrl+A и Ctrl+S бесполезны.
    Порог по живым кадрам: у страницы JSON 3935, у пустого «Loading…» 0."""
    try:
        from PIL import Image
        img = Image.open(png).convert("RGB")
        px = img.load()
        dark = 0
        for yy in range(120, 800, 4):
            for xx in range(60, 1300, 4):
                r, g, b = px[xx, yy]
                if r < 110 and g < 110 and b < 110:
                    dark += 1
        return dark >= 300
    except Exception:
        return False


def _find_checkbox(png):
    """Узкой рамки у виджета нет — ищем пиксели оранжевого облака; левый край кластера минус сдвиг,
    y — середина кластера. Ниже облака всегда чёрное слово CLOUDFLARE: в полосе 48 px под кластером
    должно быть ≥ 25 тёмных пикселей — на живых кадрах 04.11 у виджета 45, и это отличает его от
    постороннего оранжевого в загруженном контенте (логотип Ennaturiijk: 111 px, 38×26, полоса дала
    14 — без ограды искали клик (10,607) и три раза тыкали уже решённую страницу пустыми кликами).
    Ни одного пикселя или рассыпанный цвет от баннера — None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(png).convert("RGB")
        r_lo, g_lo, g_hi, b_hi = _CLOUD_RGB
        xs, ys = [], []
        px = img.load()
        w, h = img.size
        for yy in range(0, h, 2):
            for xx in range(0, w, 2):
                r, g, b = px[xx, yy]
                if r > r_lo and g_lo < g < g_hi and b < b_hi:
                    xs.append(xx)
                    ys.append(yy)
        if not xs or max(ys) - min(ys) > 300:
            return None
        x0, x1, y1 = min(xs), max(xs), max(ys)
        below = 0                        # слово CLOUDFLARE стоит прямо под облаком виджета
        for yy in range(y1 + 2, min(h, y1 + 48), 2):
            for xx in range(max(0, x0 - 40), min(w, x1 + 40), 2):
                r, g, b = px[xx, yy]
                if r < 90 and g < 90 and b < 90:
                    below += 1
        if below < 25:
            return None
        return max(10, x0 + _CLOUD_TO_BOX_DX), (min(ys) + y1) // 2
    except Exception as e:
        _log(f"поиск чекбокса: {e}")
        return None


def _session():
    global _SESSION
    if _SESSION is None:
        _SESSION = _Session()
    return _SESSION


def _run(source, url):
    try:
        s = _session()
        if not s.ensure():
            return None
        try:
            return getattr(s, source)(url)
        except Exception as e:
            _log(f"{source} {url[:80]}…: {e} — Chrome убит до следующего вызова")
            s._kill_chrome()
            return None
        finally:
            s.last_use = time.time()
    except Exception as e:
        _log(f"{source}: {e}")
        return None


def page_html(url):
    """HTML SSR-страницы через настоящий Chrome (Ctrl+S). None → наверх идёт Jina."""
    return _run("page_html", url)


def json_text(url):
    """Тело JSON: открываем URL как обычную страницу и Ctrl+A/Ctrl+C через буфер. None → наверх идёт Jina."""
    return _run("json_text", url)
