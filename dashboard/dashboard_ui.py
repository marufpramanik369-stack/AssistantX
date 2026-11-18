"""AssistantX - JEROX  |  Neon HUD Dashboard (tkinter)

Run:  python dashboard_ui.py
Optional:  pip install psutil pillow
Center photo: put your picture at  assets/jerox.png  (next to this file).
"""
import math
import os
import random
import time
import tkinter as tk

try:
    import psutil
except ImportError:
    psutil = None
try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None

# ---------- theme ----------
BG = "#010806"
PANEL = "#03110e"
BORDER = "#0c5f47"
GREEN = "#19f0a0"
DIM = "#0e9b73"
TEXT = "#b9ecdc"
TRACK = "#0a2a22"
FONT = "Consolas"

HERE = os.path.dirname(os.path.abspath(__file__))


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AssistantX — JEROX")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(bg=BG)
        self.t0 = time.time()
        self.angle = 0
        self.photo = None
        self.bars = {}
        self.labels = {}

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

    # ---------- helpers ----------
    def panel(self, parent, title, **grid):
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1)
        outer.grid(**grid)
        head = tk.Frame(outer, bg=PANEL)
        head.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(head, text=title, bg=PANEL, fg=GREEN,
                 font=(FONT, 10, "bold")).pack(side="left")
        tk.Label(head, text="···", bg=PANEL, fg=DIM,
                 font=(FONT, 10)).pack(side="right")
        body = tk.Frame(outer, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return body

    def bar(self, parent, key, name):
        f = tk.Frame(parent, bg=PANEL)
        f.pack(fill="x", pady=2)
        f.columnconfigure(0, weight=1)
        tk.Label(f, text=name, bg=PANEL, fg=TEXT, font=(FONT, 9)).grid(row=0, column=0, sticky="w")
        val = tk.Label(f, text="0%", bg=PANEL, fg=GREEN, font=(FONT, 9, "bold"))
        val.grid(row=0, column=1, sticky="e")
        c = tk.Canvas(f, height=4, bg=TRACK, highlightthickness=0)
        c.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.bars[key] = (c, val)

    def set_bar(self, key, pct):
        c, val = self.bars[key]
        c.delete("all")
        c.create_rectangle(0, 0, c.winfo_width() * pct / 100, 4, fill=GREEN, width=0)
        val.config(text=f"{pct:.0f}%")

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
        tk.Label(logo, text="ASSISTANT ❦", bg=BG, fg=GREEN,
                 font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(logo, text="● ONLINE", bg=BG, fg=GREEN, font=(FONT, 8)).pack(anchor="w")

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

    # ---------- left column ----------
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
        self.feed = tk.Text(b, height=4, bg=PANEL, fg=TEXT, font=(FONT, 8),
                            bd=0, highlightthickness=0, state="disabled")
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
        self.wave = tk.Canvas(voice, height=36, bg=PANEL, highlightthickness=0)
        self.wave.pack(fill="x", padx=20)
        row = tk.Frame(voice, bg=PANEL)
        row.pack(pady=(0, 10))
        for t in ["Analyze Codebase", "Run Diagnostics"]:
            self._chip(row, t).pack(side="left", padx=6)
        tk.Button(row, text="🎙", bg=PANEL, fg=GREEN, activebackground=BORDER,
                  font=(FONT, 16), bd=1, relief="solid", width=3,
                  command=lambda: self.log_feed("Voice mode")).pack(side="left", padx=10)
        for t in ["Open Terminal", "Search The Web"]:
            self._chip(row, t).pack(side="left", padx=6)

    def _chip(self, parent, text):
        return tk.Button(parent, text=text, bg=PANEL, fg=TEXT, activebackground=BORDER,
                         activeforeground=GREEN, font=(FONT, 9), bd=1, relief="solid",
                         padx=10, command=lambda: self.terminal_write(f"> {text}"))

    def _load_photo(self, size):
        path = os.path.join(HERE, "assets", "jerox.png")
        if Image is None or not os.path.exists(path):
            return None
        img = Image.open(path).convert("RGBA").resize((size, size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        img.putalpha(mask)
        return ImageTk.PhotoImage(img)

    def _animate(self):
        cv = self.cv
        w, h = cv.winfo_width(), cv.winfo_height()
        if w > 50:
            cv.delete("all")
            cx, cy = w / 2, h / 2 - 5
            R = min(w, h) * 0.40
            # static rings
            for k, wd in [(1.0, 1), (0.88, 2), (0.70, 1)]:
                r = R * k
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=BORDER, width=wd)
            # tick marks
            for i in range(60):
                a = math.radians(i * 6)
                r1, r2 = R * 1.02, R * (1.07 if i % 5 == 0 else 1.04)
                cv.create_line(cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                               cx + r2 * math.cos(a), cy + r2 * math.sin(a), fill=DIM)
            # rotating arcs
            r = R * 0.92
            for i in range(3):
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=self.angle + i * 120,
                              extent=55, style="arc", outline=GREEN, width=6)
            r = R * 0.76
            for i in range(4):
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=-self.angle * 1.5 + i * 90,
                              extent=30, style="arc", outline=DIM, width=3)
            # crosshair
            cv.create_line(cx - R * 1.3, cy, cx - R * 1.08, cy, fill=BORDER)
            cv.create_line(cx + R * 1.08, cy, cx + R * 1.3, cy, fill=BORDER)
            # center photo / placeholder
            size = int(R * 1.3)
            if self.photo is None or getattr(self, "_psize", 0) != size:
                self._psize = size
                self.photo = self._load_photo(size)
            if self.photo:
                cv.create_image(cx, cy, image=self.photo)
            else:
                cv.create_text(cx, cy - 8, text="JEROX", fill=GREEN,
                               font=(FONT, int(R / 5), "bold"))
                cv.create_text(cx, cy + R * 0.18, text="assets/jerox.png",
                               fill=DIM, font=(FONT, 9))
            # side readouts
            cv.create_text(cx - R * 1.25, cy - R * 0.5, text="PROCESSOR\nCORE 8/16",
                           fill=TEXT, font=(FONT, 8), anchor="w")
            cv.create_text(cx + R * 1.25, cy - R * 0.5, text="POWER LEVEL\n93%",
                           fill=TEXT, font=(FONT, 8), anchor="e", justify="right")
            cv.create_text(cx - R * 1.25, cy + R * 0.5, text="NEURAL PATHWAYS\nACTIVE",
                           fill=TEXT, font=(FONT, 8), anchor="w")
            cv.create_text(cx + R * 1.25, cy + R * 0.5, text="TEMP\n42°C",
                           fill=GREEN, font=(FONT, 9, "bold"), anchor="e", justify="right")
            cv.create_text(cx, cy + R * 1.18, text="● SYSTEMS OPERATIONAL",
                           fill=GREEN, font=(FONT, 9, "bold"))
            self.angle = (self.angle + 3) % 360

            # voice wave
            ww = self.wave.winfo_width()
            self.wave.delete("all")
            for x in range(0, ww, 6):
                hh = random.randint(2, 16)
                self.wave.create_line(x, 18 - hh, x, 18 + hh, fill=DIM)
        self.after(50, self._animate)

    # ---------- right column ----------
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
        for i, n in enumerate(["RUNNING", "SCHEDULED", "COMPLETED", "FAILED"]):
            c = tk.Frame(r, bg=PANEL)
            c.pack(side="left", expand=True)
            v = tk.Label(c, text="0", bg=PANEL, fg=TEXT, font=(FONT, 18, "bold"))
            v.pack()
            tk.Label(c, text=n, bg=PANEL, fg=DIM, font=(FONT, 7)).pack()
            self.jobs[n] = v

        b = self.panel(col, "QUICK ACTIONS", row=2, column=0, sticky="nsew", pady=3)
        self._icon_row(b, ["🎙\nVOICE", "▣\nSHOT", "◉\nCAMERA", "▤\nFILES", "✦\nAI"])

        b = self.panel(col, "SYSTEM SHORTCUTS", row=3, column=0, sticky="nsew", pady=3)
        self._icon_row(b, ["▭\nTERM", "⛁\nDB", "✦\nNET", "❖\nAPPS", "⚙\nSET"])

        b = self.panel(col, "TERMINAL", row=4, column=0, sticky="nsew", pady=3)
        self.term = tk.Text(b, height=6, bg=PANEL, fg=GREEN, font=(FONT, 8), bd=0,
                            highlightthickness=0, state="disabled", wrap="word")
        self.term.pack(fill="both", expand=True)
        self.terminal_write("AssistantX Terminal v1.0.0")
        self.terminal_write("Type 'help' for available commands...")
        self.terminal_write("> Initializing AI Core...          [OK]")
        self.terminal_write("> Loading Memory Bank...           [OK]")
        self.terminal_write("> Ready for your command...")

    def _icon_row(self, parent, items):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="both", expand=True)
        for t in items:
            tk.Button(r, text=t, bg="#052019", fg=GREEN, activebackground=BORDER,
                      activeforeground=TEXT, font=(FONT, 8, "bold"), bd=1, relief="solid",
                      command=lambda x=t: self.log_feed(x.replace("\n", " "))
                      ).pack(side="left", expand=True, fill="both", padx=2, pady=2)

    # ---------- footer ----------
    def _footer(self):
        f = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        f.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 8))
        tk.Label(f, text="JEROX ❦", bg=PANEL, fg=GREEN,
                 font=(FONT, 16, "bold")).pack(side="left", padx=14, pady=6)
        self.foot = {}
        for k in ["UPTIME", "POWER", "AI LOAD", "TEMP", "FAN SPEED"]:
            c = tk.Frame(f, bg=PANEL)
            c.pack(side="left", expand=True)
            tk.Label(c, text=k, bg=PANEL, fg=DIM, font=(FONT, 8)).pack()
            v = tk.Label(c, text="--", bg=PANEL, fg=GREEN, font=(FONT, 10, "bold"))
            v.pack()
            self.foot[k] = v

    # ---------- public API (use these from your assistant code) ----------
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

    # ---------- periodic update ----------
    def _tick(self):
        self.clock.config(text=time.strftime("%I:%M:%S %p"))
        self.date.config(text=time.strftime("%b %d, %Y").upper())
        if psutil:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            self.set_bar_safe("cpu", cpu)
            self.set_bar_safe("ram", ram)
            self.set_bar_safe("gpu", 0)
            n = psutil.net_io_counters()
            now = time.time()
            if hasattr(self, "_last"):
                dt = max(now - self._last[0], 0.1)
                up = (n.bytes_sent - self._last[1]) * 8 / dt / 1e6
                dn = (n.bytes_recv - self._last[2]) * 8 / dt / 1e6
                self.labels["up"].config(text=f"{up:.2f} Mbps")
                self.labels["down"].config(text=f"{dn:.2f} Mbps")
                self.set_bar_safe("net", min(100, (up + dn) * 10))
            self._last = (now, n.bytes_sent, n.bytes_recv)
            try:
                self.labels["conn"].config(text=str(len(psutil.net_connections())))
            except Exception:
                pass
            self.foot["AI LOAD"].config(text=f"{cpu:.0f}%")
        up_s = int(time.time() - self.t0)
        self.foot["UPTIME"].config(text=f"{up_s // 3600}h {up_s % 3600 // 60}m {up_s % 60}s")
        self.foot["POWER"].config(text="93%")
        self.foot["TEMP"].config(text="42°C")
        self.foot["FAN SPEED"].config(text="1200 RPM")
        self.after(1000, self._tick)

    def set_bar_safe(self, key, pct):
        self.set_bar(key, max(0, min(100, pct)))


if __name__ == "__main__":
    Dashboard().mainloop()
    