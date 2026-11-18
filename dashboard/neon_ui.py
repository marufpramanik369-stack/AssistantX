"""AssistantX - JEROX | Neon HUD Dashboard (complete file)

Place at: C:\\AssistantX\\dashboard\\neon_ui.py
Assets used: assets/images (avatar_girl.png, logo.png, splash.jpg),
             assets/icons (mic.png, send.png, settings.png),
             assets/sounds (startup.mp3, listening.mp3, notify.mp3)
"""
import asyncio
import importlib
import inspect
import math
import os
import queue
import re
import json
import random
import shutil
import subprocess  # nosec B404 - explicit, no-shell process launches only
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser

try:
    import psutil
except ImportError:
    psutil = None
try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk
except ImportError:
    Image = None
try:
    from playsound import playsound
except Exception:
    playsound = None

# ---------- paths ----------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

IMG = os.path.join(ROOT, "assets", "images")
ICON = os.path.join(ROOT, "assets", "icons")
SND = os.path.join(ROOT, "assets", "sounds")
AVATAR = os.path.join(IMG, "avatar_girl.png")

# ---------- theme ----------
BG, PANEL, BORDER = "#010806", "#03110e", "#0c5f47"
GREEN, DIM, TEXT, TRACK = "#19f0a0", "#0e9b73", "#b9ecdc", "#0a2a22"
FONT = "Consolas"
ASSISTANT_NAME = "JEROX"

VOICE_LANG = "bn"   # microphone language: "bn" Bangla, "en" English, "hi" Hindi
AUTO_LISTEN = True  # start hands-free listening as soon as the dashboard opens

# Wake words: () = no wake word. If a spoken sentence contains one, the word is removed
# before the command is sent ("জেরক্স Chrome খোলো" -> "Chrome খোলো").

VOICE_WAKE_WORDS = ("jerox", "জেরক্স")

VOICE_WAKE_WORD_REQUIRED = True   # True = sentences WITHOUT a wake word are ignored

# How long a silence ends your sentence (seconds). Higher = it waits longer, so a short
# pause inside a sentence ("হ্যালো জেরক্স ... তুমি কেমন আছো") no longer splits it in two.

VOICE_PAUSE_SECONDS = 1.9

# Show a note in the terminal when speech was heard but could not be understood.

VOICE_SHOW_UNCLEAR = False

# Spoken reply: the first sentence is spoken as soon as it is ready (so JEROX starts
# talking sooner) and very long replies are shortened for speech only (the terminal shows all).

SPEAK_SPLIT = False

SPEAK_MAX_CHARS = 9000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000


# Words in Latin letters inside brackets, e.g. "জেরক্স (JEROX)": a Bangla voice would read
# the name twice (once in Bangla, once in English), so they are removed from the SPOKEN text only.
_LATIN_BRACKET = re.compile(r"\s*[\(\[]\s*[A-Za-z][A-Za-z0-9 .,'\-_/]{0,40}[\)\]]")
_BANGLA = re.compile(r"[\u0980-\u09FF]")


def speech_text(text):
    """Text as it will be spoken (the terminal still shows the full reply)."""
    text = str(text)
    if VOICE_LANG == "bn" and _BANGLA.search(text):
        text = _LATIN_BRACKET.sub("", text)
    return text.strip()


def split_for_speech(text):
    """[first sentence, rest] (or one piece), shortened to SPEAK_MAX_CHARS for speech."""
    text = speech_text(text)
    if len(text) > SPEAK_MAX_CHARS:
        cut = max(text.rfind(m, 0, SPEAK_MAX_CHARS) for m in ("।", ". ", "! ", "? "))
        text = text[:cut + 1] if cut > 60 else text[:SPEAK_MAX_CHARS]
    if SPEAK_SPLIT:
        m = re.search(r"[।.!?]\s", text)
        if m and m.end() < len(text):
            return [text[:m.end()].strip(), text[m.end():].strip()]
    return [text]


def play_sound(name):
    path = os.path.join(SND, name)
    if playsound is None or not os.path.exists(path):
        return

    def run():
        try:
            playsound(path)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def load_icon(path, size):
    if Image is None or not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _urlopen_https(url, timeout=5):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme or 'missing'}")
    request = urllib.request.Request(url, headers={"User-Agent": "AssistantX/1.0"})
    return urllib.request.urlopen(request, timeout=timeout)  # nosec B310 - HTTPS/HTTP only


# ---------- bridge to the real assistant (core/assistant.py) ----------
_assistant = None
_assistant_lock = threading.Lock()


def get_assistant():
    """Create the project's Assistant once (same factory the app uses)."""
    global _assistant
    with _assistant_lock:
        if _assistant is None:
            mod = importlib.import_module("core.assistant")
            _assistant = mod.create_default_assistant()
            try:   # automatic online (Gemini) / offline (Ollama) selection
                from ai.auto_provider import AutoProvider
                _assistant.set_ai_provider(AutoProvider())
            except Exception:
                pass   # keep the normal provider if auto_provider.py is missing
        return _assistant


def provider_info(asst):
    """(provider class name, model name or None)."""
    prov = getattr(asst, "ai_provider", None)
    if prov is None:
        return "None", None
    used = getattr(prov, "last_used", None)
    if used:
        name, model = used
        return f"{name.capitalize()} ({'online' if name == 'gemini' else 'local'})", model
    if prov.__class__.__name__ == "AutoProvider":
        return "Auto", None
    for attr in ("model", "model_name", "_model", "_model_name", "MODEL"):
        val = getattr(prov, attr, None)
        if isinstance(val, str) and val:
            return prov.__class__.__name__, val
    return prov.__class__.__name__, None


DATA = os.path.join(ROOT, "data")
LAT, LON = 24.0064, 89.2372   # weather location (Pabna) - change if needed

_WCODE = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog",
          48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 61: "Light rain",
          63: "Rain", 65: "Heavy rain", 80: "Showers", 81: "Showers", 82: "Heavy showers",
          95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}


def fetch_weather():
    """Free Open-Meteo API (no key needed). Returns (temp, cond, humidity, wind)."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current="
           "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code" % (LAT, LON))
    if not url.startswith("https://api.open-meteo.com/"):
        raise ValueError("Unexpected weather API URL")
    req = urllib.request.Request(url, headers={"User-Agent": "AssistantX/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:  # nosec B310 - trusted public HTTPS API
        c = json.load(r)["current"]
    return (round(c["temperature_2m"]), _WCODE.get(c["weather_code"], "Unknown"),
            round(c["relative_humidity_2m"]), round(c["wind_speed_10m"]))


def detect_model():
    """Look for a *MODEL* string setting in the project's config / gemini modules."""
    best = None
    for modname in ("config.settings", "config.config", "config.constants", "ai.gemini"):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(mod):
            val = getattr(mod, name, None)
            if "MODEL" in name.upper() and isinstance(val, str) and 0 < len(val) < 60:
                if "gemini" in val.lower():
                    return val
                best = best or val
    return best or os.environ.get("GEMINI_MODEL", "Unknown")


def scheduled_jobs_count():
    try:
        mod = importlib.import_module("core.scheduler")
    except Exception:
        return 0
    for n in ("get_jobs", "list_jobs", "get_scheduled_jobs", "jobs"):
        obj = getattr(mod, n, None)
        try:
            if callable(obj):
                obj = obj()
            if obj is not None:
                return len(obj)
        except Exception:
            continue
    return 0


def dir_stats(path):
    total = n = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
                n += 1
            except OSError:
                pass
    return total, n


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title(f"AssistantX — {ASSISTANT_NAME}")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(bg=BG)
        self.t0 = time.time()
        self.angle = 0
        self.photo = None
        self._psize = 0
        self.bars, self.labels = {}, {}
        self.q = queue.Queue()
        self._reminders = None
        self._start_reminders()
        self.on_send = None            # optional custom handler: fn(text) -> reply str
        self.stats = {"in_tokens": 0, "out_tokens": 0, "running": 0,
                      "completed": 0, "failed": 0}
        self.history = []
        self._model = detect_model()
        self._ltm = (0, 0)
        self._ltm_tick = 0
        self._gpu = None
        self._voice_busy = False
        self.speak_on = True
        self.auto_listen = AUTO_LISTEN
        self._closing = False
        self._quiet_until = 0.0
        self._voice_thread = None
        self._stt_secs = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._disk = 0
        self._cores = (f"{psutil.cpu_count(logical=False) or '?'}/{psutil.cpu_count() or '?'}"
                       if psutil else "?")

        self.icons = {k: load_icon(os.path.join(ICON, f), 22)
                      for k, f in [("mic", "mic.png"), ("send", "send.png"),
                                   ("settings", "settings.png")]}
        self.icons["logo"] = load_icon(os.path.join(IMG, "logo.png"), 42)
        if self.icons["logo"]:
            self.iconphoto(True, self.icons["logo"])

        self.columnconfigure(0, weight=0, minsize=290)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0, minsize=340)
        self.rowconfigure(1, weight=1)

        self._topbar()
        self._left()
        self._center()
        self._right()
        self._footer()
        self.after(100, self._tick)
        self.after(100, self._animate)
        self.after(100, self._pump)
        self.after(300, self._refresh_weather)
        self.after(500, self._refresh_status)
        self.after(800, self._poll_gpu)
        self.after(4000, self._start_auto_voice)
        self.after(1500, self._warm_up)
        if not self._splash():
            self.deiconify()

    # ---------- helpers ----------
    def panel(self, parent, title, **grid):
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        outer.grid(**grid)
        head = tk.Frame(outer, bg=PANEL)
        head.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(head, text=title, bg=PANEL, fg=GREEN, font=(FONT, 10, "bold")).pack(side="left")
        tk.Label(head, text="···", bg=PANEL, fg=DIM, font=(FONT, 10)).pack(side="right")
        body = tk.Frame(outer, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return body

    def bar(self, parent, key, name):
        f = tk.Frame(parent, bg=PANEL)
        f.pack(fill="x", pady=2)
        f.columnconfigure(0, weight=1)
        tk.Label(f, text=name, bg=PANEL, fg=TEXT, font=(FONT, 9)).grid(row=0, column=0, sticky="w")
        v = tk.Label(f, text="0%", bg=PANEL, fg=GREEN, font=(FONT, 9, "bold"))
        v.grid(row=0, column=1, sticky="e")
        c = tk.Canvas(f, height=4, bg=TRACK, highlightthickness=0)
        c.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.bars[key] = (c, v)

    def set_bar(self, key, pct, text=None):
        pct = max(0, min(100, pct or 0))
        c, v = self.bars[key]
        c.delete("all")
        c.create_rectangle(0, 0, c.winfo_width() * pct / 100, 4, fill=GREEN, width=0)
        v.config(text=text if text else f"{pct:.0f}%")

    def kv(self, parent, key, name, value=""):
        f = tk.Frame(parent, bg=PANEL)
        f.pack(fill="x", pady=1)
        tk.Label(f, text=name, bg=PANEL, fg=DIM, font=(FONT, 8)).pack(side="left")
        lb = tk.Label(f, text=value, bg=PANEL, fg=TEXT, font=(FONT, 9, "bold"))
        lb.pack(side="right")
        self.labels[key] = lb

    # ---------- top bar ----------
    def _topbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 4))
        logo = tk.Frame(bar, bg=BG)
        logo.pack(side="left")
        if self.icons.get("logo"):
            tk.Label(logo, image=self.icons["logo"], bg=BG).pack(side="left", padx=(0, 8))
        txt = tk.Frame(logo, bg=BG)
        txt.pack(side="left")
        tk.Label(txt, text="ASSISTANT", bg=BG, fg=GREEN, font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(txt, text="● ONLINE", bg=BG, fg=GREEN, font=(FONT, 8)).pack(anchor="w")

        nav = tk.Frame(bar, bg=BG)
        nav.pack(side="left", expand=True)
        for i, n in enumerate(["⌂ HOME", "⚙ SYSTEM", "✦ NETWORK", "▤ DATABASE", "▭ TERMINAL"]):
            tk.Label(nav, text=n, bg=BG, fg=GREEN if i == 0 else TEXT,
                     font=(FONT, 10, "bold"), padx=14).pack(side="left")

        clock = tk.Frame(bar, bg=BG)
        clock.pack(side="right")
        self.clock = tk.Label(clock, text="", bg=BG, fg=GREEN, font=(FONT, 14, "bold"))
        self.clock.pack(anchor="e")
        self.date = tk.Label(clock, text="", bg=BG, fg=DIM, font=(FONT, 8))
        self.date.pack(anchor="e")
        if self.icons.get("settings"):
            tk.Button(bar, image=self.icons["settings"], bg=BG, activebackground=BORDER, bd=0,
                      command=lambda: self.log_feed("Settings opened")).pack(side="right", padx=14)

    # ---------- left ----------
    def _left(self):
        col = tk.Frame(self, bg=BG)
        col.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
        col.columnconfigure(0, weight=1)
        for r in range(5):
            col.rowconfigure(r, weight=1)
        b = self.panel(col, "SYSTEM STATUS", row=0, column=0, sticky="nsew", pady=3)
        for k, n in [("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("net", "NET")]:
            self.bar(b, k, n)
        b = self.panel(col, "AI CORE STATUS", row=1, column=0, sticky="nsew", pady=3)
        self.kv(b, "model", "AI MODEL", "Unknown")
        self.kv(b, "provider", "PROVIDER", "Gemini")
        self.kv(b, "mode", "MODE", "ACTIVE")
        self.kv(b, "tokens", "TOKENS", "0 / 128000")
        b = self.panel(col, "MEMORY BANK", row=2, column=0, sticky="nsew", pady=3)
        self.kv(b, "ctx", "ACTIVE CONTEXT", "0 KB")
        self.kv(b, "ltm", "LONG TERM MEMORY", "0 KB")
        self.kv(b, "stm", "SHORT TERM MEMORY", "0 KB")
        b = self.panel(col, "NETWORK STATUS", row=3, column=0, sticky="nsew", pady=3)
        self.kv(b, "up", "UPLOAD", "0.0 Mbps")
        self.kv(b, "down", "DOWNLOAD", "0.0 Mbps")
        self.kv(b, "conn", "CONNECTIONS", "0")
        b = self.panel(col, "LIVE FEED", row=4, column=0, sticky="nsew", pady=3)
        self.feed = tk.Text(b, height=4, bg=PANEL, fg=TEXT, font=(FONT, 8), bd=0,
                            highlightthickness=0, state="disabled", wrap="word")
        self.feed.pack(fill="both", expand=True)
        self.log_feed("Dashboard initialized")

    # ---------- center ----------
    def _center(self):
        col = tk.Frame(self, bg=BG)
        col.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        col.rowconfigure(0, weight=1)
        col.columnconfigure(0, weight=1)
        self.cv = tk.Canvas(col, bg=BG, highlightthickness=0)
        self.cv.grid(row=0, column=0, sticky="nsew")

        voice = tk.Frame(col, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        voice.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        tk.Label(voice, text="What shall we build today?", bg=PANEL, fg=GREEN,
                 font=(FONT, 13)).pack(pady=(10, 0))
        self.vstat = tk.Label(voice, text="… STARTING MIC", bg=PANEL, fg=DIM,
                              font=(FONT, 9, "bold"))
        self.vstat.pack()
        self.wave = tk.Canvas(voice, height=30, bg=PANEL, highlightthickness=0)
        self.wave.pack(fill="x", padx=20)

        box = tk.Frame(voice, bg=PANEL)
        box.pack(fill="x", padx=20, pady=(0, 6))
        self.entry = tk.Entry(box, bg="#052019", fg=TEXT, insertbackground=GREEN,
                              relief="flat", font=(FONT, 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.send())
        sb = tk.Button(box, bg="#052019", activebackground=BORDER, bd=0, command=self.send)
        if self.icons.get("send"):
            sb.config(image=self.icons["send"])
        else:
            sb.config(text="SEND", fg=GREEN, font=(FONT, 9, "bold"))
        sb.pack(side="left", padx=(6, 0))
        mic = tk.Button(box, bg="#052019", activebackground=BORDER, bd=0, command=self.on_mic)
        if self.icons.get("mic"):
            mic.config(image=self.icons["mic"])
        else:
            mic.config(text="MIC", fg=GREEN, font=(FONT, 9, "bold"))
        mic.pack(side="left", padx=(6, 0))
        self.spk_btn = tk.Button(box, text="SPK ON", bg="#052019", fg=GREEN,
                                 activebackground=BORDER, bd=0, font=(FONT, 8, "bold"),
                                 command=self._toggle_speak)
        self.spk_btn.pack(side="left", padx=(6, 0))

        row = tk.Frame(voice, bg=PANEL)
        row.pack(fill="x", padx=20, pady=(0, 10))
        for t in ["Analyze Code", "Diagnostics", "Terminal", "Search Web"]:
            tk.Button(row, text=t, bg=PANEL, fg=TEXT, activebackground=BORDER,
                      activeforeground=GREEN, font=(FONT, 8), bd=1, relief="solid",
                      command=lambda x=t: self.run_chip(x)
                      ).pack(side="left", expand=True, fill="x", padx=3)

    def _load_photo(self, size):
        if Image is None or not os.path.exists(AVATAR):
            return None
        try:
            img = Image.open(AVATAR).convert("RGBA")
            img = ImageOps.fit(img, (size, size), centering=(0.5, 0.25))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
            img.putalpha(mask)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _animate(self):
        cv = self.cv
        w, h = cv.winfo_width(), cv.winfo_height()
        if w > 50:
            cv.delete("all")
            cx, cy = w / 2, h / 2 - 5
            R = min(w, h) * 0.40
            for k, wd in [(1.0, 1), (0.88, 2), (0.70, 1)]:
                r = R * k
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=BORDER, width=wd)
            for i in range(60):
                a = math.radians(i * 6)
                r1, r2 = R * 1.02, R * (1.07 if i % 5 == 0 else 1.04)
                cv.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                               cx + r2 * math.cos(a), cy + r2 * math.sin(a), fill=DIM)
            r = R * 0.92
            for i in range(3):
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=self.angle + i * 120,
                              extent=55, style="arc", outline=GREEN, width=6)
            r = R * 0.76
            for i in range(4):
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=-self.angle * 1.5 + i * 90,
                              extent=30, style="arc", outline=DIM, width=3)
            size = int(R * 1.38)
            if self.photo is None or self._psize != size:
                self._psize = size
                self.photo = self._load_photo(size)
            if self.photo:
                cv.create_image(cx, cy, image=self.photo)
            else:
                cv.create_text(cx, cy, text=ASSISTANT_NAME, fill=GREEN, font=(FONT, int(R / 5), "bold"))
            cv.create_text(cx - R * 1.25, cy - R * 0.5, text=f"PROCESSOR\nCORE {self._cores}",
                           fill=TEXT, font=(FONT, 8), anchor="w")
            cv.create_text(cx + R * 1.25, cy - R * 0.5, text=f"POWER LEVEL\n{self._power_text()}", fill=TEXT,
                           font=(FONT, 8), anchor="e", justify="right")
            cv.create_text(cx - R * 1.25, cy + R * 0.5, text="NEURAL PATHWAYS\nACTIVE",
                           fill=TEXT, font=(FONT, 8), anchor="w")
            cv.create_text(cx + R * 1.25, cy + R * 0.5, text=f"DISK\n{self._disk}%", fill=GREEN,
                           font=(FONT, 9, "bold"), anchor="e", justify="right")
            cv.create_text(cx, cy + R * 1.18, text="● SYSTEMS OPERATIONAL", fill=GREEN,
                           font=(FONT, 9, "bold"))
            self.angle = (self.angle + 3) % 360
            ww = self.wave.winfo_width()
            self.wave.delete("all")
            for x in range(0, ww, 6):
                hh = random.randint(2, 12)
                self.wave.create_line(x, 15 - hh, x, 15 + hh, fill=DIM)
        self.after(50, self._animate)

    # ---------- right ----------
    def _right(self):
        col = tk.Frame(self, bg=BG)
        col.grid(row=1, column=2, sticky="nsew", padx=(5, 10), pady=5)
        col.columnconfigure(0, weight=1)
        for r, wt in enumerate([3, 2, 3, 3, 4]):
            col.rowconfigure(r, weight=wt)
        b = self.panel(col, "WEATHER REPORT", row=0, column=0, sticky="nsew", pady=3)
        top = tk.Frame(b, bg=PANEL)
        top.pack(fill="x")
        self.w_temp = tk.Label(top, text="☁ --°C", bg=PANEL, fg=TEXT, font=(FONT, 24, "bold"))
        self.w_temp.pack(side="left")
        side = tk.Frame(top, bg=PANEL)
        side.pack(side="right")
        self.w_cond = tk.Label(side, text="Unknown", bg=PANEL, fg=GREEN, font=(FONT, 9, "bold"))
        self.w_cond.pack(anchor="e")
        self.w_hum = tk.Label(side, text="Humidity 0%", bg=PANEL, fg=DIM, font=(FONT, 8))
        self.w_hum.pack(anchor="e")
        self.w_wind = tk.Label(side, text="Wind 0 km/h", bg=PANEL, fg=DIM, font=(FONT, 8))
        self.w_wind.pack(anchor="e")

        b = self.panel(col, "CROWN JOBS", row=1, column=0, sticky="nsew", pady=3)
        r = tk.Frame(b, bg=PANEL)
        r.pack(fill="x")
        self.jobs = {}
        for n in ["RUNNING", "SCHEDULED", "COMPLETED", "FAILED"]:
            c = tk.Frame(r, bg=PANEL)
            c.pack(side="left", expand=True)
            v = tk.Label(c, text="0", bg=PANEL, fg=TEXT, font=(FONT, 18, "bold"))
            v.pack()
            tk.Label(c, text=n, bg=PANEL, fg=DIM, font=(FONT, 7)).pack()
            self.jobs[n] = v

        b = self.panel(col, "QUICK ACTIONS", row=2, column=0, sticky="nsew", pady=3)
        self._icon_row(b, ["VOICE", "SHOT", "CAMERA", "FILES", "AI"])
        b = self.panel(col, "SYSTEM SHORTCUTS", row=3, column=0, sticky="nsew", pady=3)
        self._icon_row(b, ["TERM", "DB", "NET", "APPS", "SET"])
        b = self.panel(col, "TERMINAL", row=4, column=0, sticky="nsew", pady=3)
        self.term = tk.Text(b, height=6, bg=PANEL, fg=GREEN, font=(FONT, 8), bd=0,
                            highlightthickness=0, state="disabled", wrap="word")
        self.term.pack(fill="both", expand=True)
        for line in ["AssistantX Terminal v1.0.0", "Type your message below and press Enter.",
                     "> Initializing AI Core...          [OK]", "> Ready for your command..."]:
            self.terminal_write(line)

    def _icon_row(self, parent, items):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="both", expand=True)
        for t in items:
            tk.Button(r, text=t, bg="#052019", fg=GREEN, activebackground=BORDER,
                      activeforeground=TEXT, font=(FONT, 8, "bold"), bd=1, relief="solid",
                      command=lambda x=t: self.run_action(x)
                      ).pack(side="left", expand=True, fill="both", padx=2, pady=2)

    # ---------- footer ----------
    def _footer(self):
        f = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        f.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 8))
        tk.Label(f, text=ASSISTANT_NAME, bg=PANEL, fg=GREEN, font=(FONT, 16, "bold")).pack(
            side="left", padx=14, pady=6)
        self.foot = {}
        for k in ["UPTIME", "POWER", "AI LOAD", "DISK", "PROCESSES"]:
            c = tk.Frame(f, bg=PANEL)
            c.pack(side="left", expand=True)
            tk.Label(c, text=k, bg=PANEL, fg=DIM, font=(FONT, 8)).pack()
            v = tk.Label(c, text="--", bg=PANEL, fg=GREEN, font=(FONT, 10, "bold"))
            v.pack()
            self.foot[k] = v

    # ---------- actions ----------
    # ---------- hands-free voice: always listening in the background ----------
    def _set_vstatus(self, text):
        color = GREEN if "LISTENING" in text else ("#e0b040" if "⚠" in text else DIM)
        self.vstat.config(text=text, fg=color)

    def _start_auto_voice(self):
        if self.auto_listen:
            self._ensure_voice_thread()

    def _ensure_voice_thread(self):
        t = self._voice_thread
        if t is None or not t.is_alive():
            self._voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
            self._voice_thread.start()

    def on_mic(self):
        """Mic button / VOICE action: switch hands-free listening on or off."""
        self.auto_listen = not self.auto_listen
        if self.auto_listen:
            play_sound("listening.mp3")
            self._set_vstatus("… STARTING MIC")
            self._ensure_voice_thread()
        else:
            self._set_vstatus("○ MIC OFF")
        self.log_feed("Hands-free voice " + ("ON" if self.auto_listen else "OFF"))

    def _busy_reason(self):
        """Why the mic should pause (so JEROX never hears herself), or None."""
        if self.stats["running"] > 0:
            return "… THINKING"
        try:
            sp = sys.modules.get("voice.speaker")
            if sp is not None and sp.speaker.is_speaking:
                self._quiet_until = time.time() + 1.2
        except Exception:
            pass
        if time.time() < self._quiet_until:
            return "◌ SPEAKING"
        return None

    def _voice_loop(self):
        """Runs in a background thread: listen -> text -> send, forever."""
        rec = None
        calibrated = False
        shown = None
        last_err = 0.0

        def show(text):
            nonlocal shown
            if text != shown:
                shown = text
                self.q.put(("vstatus", text))

        while not self._closing:
            try:
                if not self.auto_listen:
                    show("○ MIC OFF")
                    time.sleep(0.4)
                    continue
                if rec is None:
                    show("… STARTING MIC")
                    rec = importlib.import_module("voice.recognizer").recognizer
                    if not rec.is_available():
                        self.q.put(("term", "[VOICE] Microphone / SpeechRecognition not available."))
                        self.q.put(("mic_off", ""))
                        rec = None
                        time.sleep(1.0)
                        continue
                    if VOICE_LANG:
                        rec.set_language(VOICE_LANG)
                    inner = getattr(rec, "_recognizer", None)    # the SpeechRecognition engine
                    if inner is not None:
                        inner.pause_threshold = max(1.2, VOICE_PAUSE_SECONDS)
                        inner.non_speaking_duration = 0.6
                if not calibrated:
                    show("… CALIBRATING")
                    rec.calibrate_ambient_noise(1.0)
                    calibrated = True
                    _in = getattr(rec, '_recognizer', None)
                    if _in is not None:
                        _in.dynamic_energy_threshold = True
                        if _in.energy_threshold < 300:
                            _in.energy_threshold = 300
                        print(f'[NOISE] calibrated energy_threshold={_in.energy_threshold:.1f}', flush=True)
                reason = self._busy_reason()
                if reason:
                    show(reason)
                    if time.time() < getattr(self, "_awake_until", 0):
                        self._awake_until = time.time() + 15
                    time.sleep(0.3)
                    continue
                show("◉ LISTENING")
                result = rec.listen_and_transcribe()
                text = (result.text or "").strip()
                print("[RAW] " + repr(result.text), flush=True)
                if not text:
                    continue
                if VOICE_WAKE_WORDS:
                    low = text.lower()
                    hit = next((w for w in VOICE_WAKE_WORDS if w.lower() in low), None)
                    if hit is not None:
                        self._awake_until = time.time() + 15
                        text = re.sub(re.escape(hit), "", text, count=1,
                                      flags=re.IGNORECASE).strip(" ,.!?।")
                        if not text:
                            text = "হ্যালো"
                    elif VOICE_WAKE_WORD_REQUIRED and time.time() >= getattr(self, "_awake_until", 0):
                        continue
                self._stt_secs = getattr(result, "duration", None)
                self.q.put(("voice_text", text))
                time.sleep(0.3)
            except Exception as exc:
                msg = str(exc)
                low = msg.lower()
                if exc.__class__.__name__ == "RecognitionTimeoutError":
                    continue          # silence: just keep listening

                if "understand" in low or "empty text" in low:
                    print("[RAW] <not understood by Google>", flush=True)
                    if VOICE_SHOW_UNCLEAR:
                        self.q.put(("term", "… (heard something but could not understand it)"))
                        time.sleep(0.9)
                    continue

                if any(k in low for k in ("service", "connection", "network", "resolve")):
                    show("⚠ VOICE NEEDS INTERNET")
                    time.sleep(3.0)
                    continue

                now = time.time()
                if now - last_err > 30:
                    last_err = now
                    self.q.put(("term", f"[VOICE] {exc.__class__.__name__}: {msg}"))
                time.sleep(1.0)

    def _on_close(self):
        self._closing = True
        self.auto_listen = False
        self._stop_speech()
        self.destroy()

    # ---------- timed reminders (core/reminders.py) ----------
    def _start_reminders(self):
        try:
            from core.reminders import ReminderScheduler
            self._reminders = ReminderScheduler(self._fire_reminder)
            self._reminders.start()
        except Exception as exc:
            self.q.put(("term", f"[REMINDER] could not start: {exc}"))

    def _fire_reminder(self, r):
        from core.reminders import ai_prompt, fallback_text
        self.stats["running"] += 1

        def run():
            try:
                res = get_assistant().handle_text_input(ai_prompt(r))
                if res.success and res.response_text:
                    self.q.put(("reply", res.response_text))
                    return
            except Exception:
                pass
            self.q.put(("reply", fallback_text(r)))

        threading.Thread(target=run, daemon=True).start()

    def _game_note(self, text):
        """Detects game-mode phrases; adds a hidden note so the AI replies suitably."""
        r = getattr(self, "_reminders", None)
        t = str(text).lower()
        if r is None:
            return text
        game = "\u0997\u09c7\u09ae"
        off = (game + " \u09b6\u09c7\u09b7", "\u0996\u09c7\u09b2\u09be \u09b6\u09c7\u09b7",
               "game mode off", "game over", "finished playing")
        on = (game + " \u0996\u09c7\u09b2\u099b\u09bf", game + " \u0996\u09c7\u09b2\u09ac",
              "game mode on", "i am playing")
        if "reminder test" in t:
            import datetime as _dt
            from core.reminders import Reminder
            self._fire_reminder(Reminder("test", "prayer", "Asr", _dt.datetime.now(), "16:10"))
            return text + " [System note: reply with one very short Bangla sentence saying OK.]"
        if any(k in t for k in off):
            r.set_game_mode(False)
            return text + " [System note: game mode is now OFF. Reply with one short Bangla sentence welcoming him back.]"
        if any(k in t for k in on):
            r.set_game_mode(True)
            return text + " [System note: game mode is now ON. Reply with one short Bangla sentence saying you will stay quiet and only prayer reminders will come.]"
        return text

    def send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.terminal_write(f"> {text}")
        self.log_feed(f"Command: {text}")
        self._stop_speech()
        self.stats["running"] += 1
        self.stats["in_tokens"] += max(1, len(text) // 4)
        self.history.append(("user", text))
        self.labels["mode"].config(text="THINKING")
        stt, self._stt_secs = self._stt_secs, None
        threading.Thread(target=self._worker, args=(text, stt), daemon=True).start()

    def _worker(self, text, stt=None):
        """Runs in a background thread so the window never freezes."""
        try:
            if self.on_send:
                self.q.put(("reply", self.on_send(text) or "(empty reply)"))
                return
            try:
                from automation.smart_commands import try_handle as _smart
                _sr = _smart(text)
            except Exception as _exc:
                _sr = None
                self.q.put(("term", f"[SMART] {_exc}"))
            if _sr:
                self.q.put(("reply", _sr))
                return
            asst = get_assistant()
            self.q.put(("ai_info", provider_info(asst)))
            t0 = time.time()
            res = asst.handle_text_input(self._game_note(text))
            ai_s = (res.duration_ms or (time.time() - t0) * 1000) / 1000
            parts = ([f"STT {stt:.1f}s"] if stt else []) + [f"AI {ai_s:.1f}s"]
            self.q.put(("term", "⏱ " + " · ".join(parts)))
            self.q.put(("ai_info", provider_info(asst)))
            if res.should_exit:
                self.q.put(("reply", res.response_text or "Goodbye!"))
                self.q.put(("exit", ""))
            elif res.success and res.response_text:
                self.q.put(("reply", res.response_text))
            else:
                err = (res.metadata or {}).get("error") or "no response"
                self.q.put(("error", f"{res.response_text or 'Assistant failed'} [{err}]"))
        except Exception as exc:
            self.q.put(("error", f"{exc.__class__.__name__}: {exc}"))

    def _pump(self):
        try:
            while True:
                kind, msg = self.q.get_nowait()
                if kind == "weather":
                    self.set_weather(*msg)
                    continue
                if kind == "weather_err":
                    self.w_cond.config(text="Offline")
                    continue
                if kind == "gpu":
                    self._gpu = msg
                    continue
                if kind == "ai_info":
                    name, model = msg
                    self.labels["provider"].config(text=name)
                    if model:
                        self._model = model
                    continue
                if kind == "exit":
                    self.log_feed("Exit command - closing")
                    self.after(1500, self.destroy)
                    continue
                if kind == "term":
                    self.terminal_write(msg)
                    continue
                if kind == "voice_text":
                    self.entry.delete(0, "end")
                    self.entry.insert(0, msg)
                    self.send()
                    continue
                if kind == "vstatus":
                    self._set_vstatus(msg)
                    continue
                if kind == "mic_off":
                    self.auto_listen = False
                    self._set_vstatus("○ MIC OFF")
                    continue
                if kind == "voice_done":
                    self._voice_busy = False
                    if self.stats["running"] == 0:
                        self.labels["mode"].config(text="ACTIVE")
                    continue
                self.stats["running"] = max(0, self.stats["running"] - 1)
                if kind == "reply":
                    self.stats["completed"] += 1
                    self.stats["out_tokens"] += max(1, len(msg) // 4)
                    self.history.append(("bot", msg))
                    self.terminal_write(f"{ASSISTANT_NAME}: {msg}")
                    if self.speak_on:
                        self._quiet_until = time.time() + 3.0
                        self._speak(msg)
                    self.log_feed("Reply received")
                    play_sound("notify.mp3")
                else:
                    self.stats["failed"] += 1
                    self.terminal_write(f"[ERROR] {msg}")
                    self.log_feed("Assistant error")
                self.labels["mode"].config(text="ACTIVE")
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _splash(self):
        path = os.path.join(IMG, "splash.jpg")
        if Image is None or not os.path.exists(path):
            return False
        try:
            sp = tk.Toplevel(self)
            sp.overrideredirect(True)
            img = Image.open(path)
            img.thumbnail((760, 440))
            self._splash_img = ImageTk.PhotoImage(img)
            w, h = img.size
            sp.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}"
                        f"+{(self.winfo_screenheight() - h) // 2}")
            tk.Label(sp, image=self._splash_img, bd=0).pack()
            play_sound("startup.mp3")

            def close():
                sp.destroy()
                self.deiconify()
            self.after(2500, close)
            return True
        except Exception:
            return False

    # ---------- quick actions / shortcuts ----------
    def run_action(self, name):
        try:
            if name == "VOICE":
                self.on_mic()
            elif name == "SHOT":
                self._screenshot()
            elif name == "CAMERA":
                os.startfile("microsoft.windows.camera:")
            elif name == "FILES":
                os.startfile(ROOT)
            elif name == "AI":
                self.entry.focus_set()
                self.log_feed("AI ready - type a message")
            elif name == "TERM":
                subprocess.Popen(["cmd.exe"], cwd=ROOT,
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            elif name == "DB":
                os.makedirs(DATA, exist_ok=True)
                os.startfile(DATA)
            elif name == "NET":
                os.startfile("ms-settings:network")
            elif name == "APPS":
                os.startfile("ms-settings:appsfeatures")
            elif name == "SET":
                os.startfile("ms-settings:")
            self.log_feed(f"{name} opened")
        except Exception as exc:
            self.log_feed(f"{name} failed: {exc.__class__.__name__}")
            self.terminal_write(f"[ERROR] {name}: {exc}")

    def _screenshot(self):
        from PIL import ImageGrab
        folder = os.path.join(os.path.expanduser("~"), "Pictures")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("AssistantX_%Y%m%d_%H%M%S.png"))
        self.withdraw()
        self.update()
        time.sleep(0.4)
        try:
            ImageGrab.grab().save(path)
        finally:
            self.deiconify()
        self.log_feed("Screenshot saved")
        self.terminal_write(f"Screenshot: {path}")

    # ---------- spoken replies (voice/speaker.py) ----------
    def _speak(self, text):
        def run():
            try:
                sp = importlib.import_module("voice.speaker").speaker
                if not sp.is_available():
                    self.q.put(("term", "[SPEAK] speaker unavailable "
                                        "(python -m pip install edge-tts pyttsx3)"))
                    return
                
                from voice.languages import detect_voice_language
                sp.set_language(detect_voice_language(text).split("-")[0])


                for i, chunk in enumerate(split_for_speech(text)):
                    if sp.speak(chunk, interrupt=(i == 0)) is None:
                        self.q.put(("term", "[SPEAK] could not queue the speech"))
                        break

            except Exception as exc:
                self.q.put(("term", f"[SPEAK] {exc.__class__.__name__}: {exc}"))

        threading.Thread(target=run, daemon=True).start()

    def _stop_speech(self):
        def run():
            try:
                importlib.import_module("voice.speaker").speaker.stop()
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _toggle_speak(self):
        self.speak_on = not self.speak_on
        self.spk_btn.config(text="SPK ON" if self.speak_on else "SPK OFF")
        if not self.speak_on:
            self._stop_speech()
        self.log_feed("Spoken replies " + ("ON" if self.speak_on else "OFF"))

    # ---------- bottom buttons ----------
    def run_chip(self, name):
        self.terminal_write(f"> {name}")
        if name == "Terminal":
            self.run_action("TERM")
        elif name == "Search Web":
            q = self.entry.get().strip()
            if not q:
                self.terminal_write("Type what to search in the box, then press Search Web.")
                self.entry.focus_set()
                return
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))
            self.entry.delete(0, "end")
            self.log_feed(f"Web search: {q}")
        elif name == "Analyze Code":
            threading.Thread(target=self._analyze_code, daemon=True).start()
        elif name == "Diagnostics":
            threading.Thread(target=self._diagnostics, daemon=True).start()

    def _analyze_code(self):
        skip = {".venv", "build", "__pycache__", ".git", "node_modules", "dist"}
        files = lines = 0
        per = {}
        for dp, dns, fns in os.walk(ROOT):
            dns[:] = [d for d in dns if d not in skip]
            for f in fns:
                if not f.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dp, f), encoding="utf-8", errors="ignore") as fh:
                        n = sum(1 for _ in fh)
                except OSError:
                    continue
                files += 1
                lines += n
                top = os.path.relpath(dp, ROOT).split(os.sep)[0]
                per[top] = per.get(top, 0) + n
        self.q.put(("term", f"Code: {files} .py files, {lines} lines"))
        for k, v in sorted(per.items(), key=lambda kv: -kv[1])[:6]:
            self.q.put(("term", f"  {'(root)' if k == '.' else k}: {v} lines"))

    def _diagnostics(self):
        out = [f"Python {sys.version.split()[0]}"]
        if psutil:
            out.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f}% | "
                       f"RAM {psutil.virtual_memory().percent:.0f}%")
        for label, path in [("avatar", AVATAR), ("icons", ICON), ("sounds", SND)]:
            out.append(f"{label}: {'OK' if os.path.exists(path) else 'MISSING'}")
        try:
            _urlopen_https("https://www.google.com", timeout=5)
            out.append("Internet: OK")
        except Exception:
            out.append("Internet: FAILED")
        out.append(f"Model: {self._model}")
        for line in out:
            self.q.put(("term", line))
        self.q.put(("term", "Diagnostics complete"))

    # ---------- real hardware values ----------
    def _power_text(self):
        try:
            b = psutil.sensors_battery()
            if b is not None:
                return f"{b.percent:.0f}%" + (" (AC)" if b.power_plugged else "")
        except Exception:
            pass
        return "AC"

    def _poll_gpu(self):
        def work():
            val = None
            exe = shutil.which("nvidia-smi")
            if exe:
                try:
                    res = subprocess.run(
                        [exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=3,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    lines = res.stdout.strip().splitlines()
                    val = float(lines[0]) if lines else None
                except Exception:
                    val = None
            self.q.put(("gpu", val))
        threading.Thread(target=work, daemon=True).start()
        self.after(5000, self._poll_gpu)

    # ---------- AI warm-up (so the first message and every online/local switch is fast) ----------
    def _warm_up(self):
        def run():
            try:
                asst = get_assistant()                     # build everything now, not on message 1
                prov = getattr(asst, "ai_provider", None)
                if hasattr(prov, "start_watcher"):
                    prov.start_watcher()                   # track internet / Ollama in background
                try:
                    importlib.import_module("voice.speaker")   # load the voice engine now
                except Exception:
                    pass
                self.q.put(("ai_info", provider_info(asst)))
            except Exception as exc:
                self.q.put(("term", f"[AI] warm-up failed: {exc.__class__.__name__}: {exc}"))
        threading.Thread(target=run, daemon=True).start()

    # ---------- live data ----------
    def _refresh_weather(self):
        def work():
            try:
                self.q.put(("weather", fetch_weather()))
            except Exception:
                self.q.put(("weather_err", ""))
        threading.Thread(target=work, daemon=True).start()
        self.after(15 * 60 * 1000, self._refresh_weather)

    def _refresh_status(self):
        s = self.stats
        used = s["in_tokens"] + s["out_tokens"]
        self.labels["model"].config(text=self._model)
        self.labels["tokens"].config(text=f"{used} / 128000")
        stm = sum(len(m) for _, m in self.history)
        self._ltm_tick += 1
        if self._ltm_tick % 5 == 1:
            self._ltm = dir_stats(DATA)
        self.labels["ctx"].config(text=f"{used * 4 / 1024:.1f} KB")
        self.labels["stm"].config(text=f"{stm / 1024:.1f} KB · {len(self.history)} msgs")
        self.labels["ltm"].config(text=f"{self._ltm[0] / 1024:.1f} KB · {self._ltm[1]} files")
        self.set_jobs(running=s["running"], scheduled=scheduled_jobs_count(),
                      completed=s["completed"], failed=s["failed"])
        self.after(3000, self._refresh_status)

    # ---------- public API ----------
    def log_feed(self, msg):
        self.feed.config(state="normal")
        self.feed.insert("end", f"● {time.strftime('%I:%M %p')}  {msg}\n")
        self.feed.see("end")
        self.feed.config(state="disabled")

    def terminal_write(self, msg):
        self.term.config(state="normal")
        self.term.insert("end", msg + "\n")
        self.term.see("end")
        self.term.config(state="disabled")

    def set_ai(self, model, provider, tokens=0, limit=128000):
        self.labels["model"].config(text=model)
        self.labels["provider"].config(text=provider)
        self.labels["tokens"].config(text=f"{tokens} / {limit}")

    def set_weather(self, temp, cond, humidity, wind):
        self.w_temp.config(text=f"☁ {temp}°C")
        self.w_cond.config(text=cond)
        self.w_hum.config(text=f"Humidity {humidity}%")
        self.w_wind.config(text=f"Wind {wind} km/h")

    def set_jobs(self, running=0, scheduled=0, completed=0, failed=0):
        for k, v in zip(["RUNNING", "SCHEDULED", "COMPLETED", "FAILED"],
                        [running, scheduled, completed, failed]):
            self.jobs[k].config(text=str(v))

    # ---------- periodic ----------
    def _tick(self):
        self.clock.config(text=time.strftime("%I:%M:%S %p"))
        self.date.config(text=time.strftime("%b %d, %Y").upper())
        if psutil:
            cpu = psutil.cpu_percent()
            self.set_bar("cpu", cpu)
            self.set_bar("ram", psutil.virtual_memory().percent)
            self.set_bar("gpu", self._gpu, "N/A" if self._gpu is None else None)
            n = psutil.net_io_counters()
            now = time.time()
            if hasattr(self, "_last"):
                dt = max(now - self._last[0], 0.1)
                up = (n.bytes_sent - self._last[1]) * 8 / dt / 1e6
                dn = (n.bytes_recv - self._last[2]) * 8 / dt / 1e6
                self.labels["up"].config(text=f"{up:.2f} Mbps")
                self.labels["down"].config(text=f"{dn:.2f} Mbps")
                self.set_bar("net", min(100, (up + dn) * 10))
            self._last = (now, n.bytes_sent, n.bytes_recv)
            try:
                self.labels["conn"].config(
                    text=str(len(psutil.net_connections(kind="inet"))))
            except Exception:
                pass
            self.foot["AI LOAD"].config(text=f"{cpu:.0f}%")
        s = int(time.time() - self.t0)
        self.foot["UPTIME"].config(text=f"{s // 3600}h {s % 3600 // 60}m {s % 60}s")
        self.foot["POWER"].config(text=self._power_text())
        if psutil:
            try:
                self._disk = round(psutil.disk_usage(os.path.abspath(os.sep)).percent)
                self.foot["DISK"].config(text=f"{self._disk}%")
                self.foot["PROCESSES"].config(text=str(len(psutil.pids())))
            except Exception:
                pass
        self.after(1000, self._tick)


def main() -> int:
    """Entry point used by dashboard/app.py (and therefore main.py)."""
    Dashboard().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

