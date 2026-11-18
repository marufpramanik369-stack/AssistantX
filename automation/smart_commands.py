"""automation/smart_commands.py - extra PC commands that are tried BEFORE the AI.

try_handle(text) returns a reply (str) when it handled the request,
or None so JEROX continues exactly as before.
Run  python -m automation.smart_commands  for a safe self-test (nothing is executed).
"""
from __future__ import annotations

import os
import re
import unicodedata
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

CONFIRM_SECONDS = 30      # how long a "yes" is accepted after the question
POWER_DELAY = 30          # shutdown / restart delay in seconds (can be cancelled)
READ_LIMIT = 900000000          # max characters read aloud from a text file
SEARCH_SECONDS = 3        # max time spent looking for a file
MOOD_SEARCHES = [
    "Shironamhin sad song", "Minar Rahman sad song",
    "James band sad song", "Ayub Bachchu sad song",
]
TEXT_EXTS = {".txt", ".md", ".py", ".csv", ".json", ".log", ".ini", ".xml", ".html", ".js"}
SKIP_DIRS = {"appdata", "node_modules", ".venv", ".git", "windows", "program files",
             "program files (x86)", "$recycle.bin", "__pycache__", "site-packages"}

DRY_RUN = False           # self-test switch: record actions instead of doing them
ACTIONS: list = []
ROOTS: Optional[list] = None   # override search folders (used by the self-test)

_pending = {"action": None, "until": 0.0}
_scheduled_until = [0.0]
_mood_index = [0]

_WORD = re.compile(r"[\w\u0980-\u09ff]+")
_YES = {"yes", "yeah", "yep", "ok", "okay", "confirm", "ha", "hya", "haa", "ji", "hay",
        "\u09b9\u09cd\u09af\u09be\u0981", "\u09b9\u09cd\u09af\u09be", "\u09b9\u09be\u0981", "\u099c\u09bf"}
_NO = {"No", "no", "nope", "Nope", "Na", "na", "Cancel", "cancel", "Nah", "nah", "Nahi", "nahi", "\u09a8\u09be", "\u09a8\u09be\u09b9", "\u09a5\u09be\u0995", "\u09ac\u09be\u09a4\u09bf\u09b2"}


def _norm(text) -> str:
    t = unicodedata.normalize("NFC", str(text or "")).lower().strip()
    return re.sub(r"\s+", " ", t)


def _words(t: str) -> set:
    return set(_WORD.findall(t))


def _has(t: str, *keys: str) -> bool:
    return any(k in t for k in keys)


def _do(kind: str, *args):
    """Run (or, in self-test, record) a real action."""
    if DRY_RUN:
        ACTIONS.append((kind,) + args)
        return True
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if kind == "run":
        subprocess.Popen(list(args), creationflags=flags)
        return True
    if kind == "startfile":
        getattr(os, "startfile")(args[0])
        return True
    return False


# ---------------------------------------------------------------- power
_PC = ("pc", "laptop", "computer", "system", "\u09aa\u09bf\u09b8\u09bf", "\u09b2\u09cd\u09af\u09be\u09aa\u099f\u09aa", "\u0995\u09ae\u09cd\u09aa\u09bf\u0989\u099f\u09be\u09b0", "\u09b8\u09bf\u09b8\u09cd\u099f\u09c7\u09ae")


def _power_kind(t: str) -> Optional[str]:
    w = _words(t)
    if _has(t, "Shutdown", "shutdown", "Shut Down", "shut down", "System Shutdown", "system shutdown", "\u09b6\u09be\u099f\u09a1\u09be\u0989\u09a8", "Power Off", "power off"):
        return "shutdown"
    if _has(t, "Restart", "restart", "Reboot", "reboot", "Syestem Restart", "system restart", "\u09b0\u09bf\u09b8\u09cd\u099f\u09be\u09b0\u09cd\u099f", "\u09b0\u09bf\u09ac\u09c1\u099f"):
        return "restart"
    if (w & {"pc", "laptop", "computer", "system"} or _has(t, *_PC[4:])) and \
            (_has(t, "\u09ac\u09a8\u09cd\u09a7") or w & {"off"}):
        return "shutdown"
    if "lock" in w or re.search(r"(?<![\u0980-\u09ff])\u09b2\u0995(?![\u0980-\u09ff])", t):
        return "lock"
    return None


def _handle_power(t: str) -> Optional[str]:
    now = time.time()
    w = _words(t)

    # waiting for a yes / no
    if _pending["action"] and now < _pending["until"]:
        action = _pending["action"]
        _pending["action"] = None
        if w & _YES and len(w) <= 3:
            if action == "restart":
                _do("run", "shutdown", "/r", "/t", str(POWER_DELAY))
                msg = f"\u09a0\u09bf\u0995 \u0986\u099b\u09c7, {POWER_DELAY} \u09b8\u09c7\u0995\u09c7\u09a8\u09cd\u09a1\u09c7\u09b0 \u09ae\u09a7\u09cd\u09af\u09c7 \u09b0\u09bf\u09b8\u09cd\u099f\u09be\u09b0\u09cd\u099f \u09b9\u09ac\u09c7\u0964 \u09a5\u09be\u09ae\u09be\u09a4\u09c7 \u2018\u09ac\u09be\u09a4\u09bf\u09b2\u2019 \u09ac\u09b2\u09cb\u0964"
            else:
                _do("run", "shutdown", "/s", "/t", str(POWER_DELAY))
                msg = f"\u09a0\u09bf\u0995 \u0986\u099b\u09c7, {POWER_DELAY} \u09b8\u09c7\u0995\u09c7\u09a8\u09cd\u09a1\u09c7\u09b0 \u09ae\u09a7\u09cd\u09af\u09c7 \u0995\u09ae\u09cd\u09aa\u09bf\u0989\u099f\u09be\u09b0 \u09ac\u09a8\u09cd\u09a7 \u09b9\u09ac\u09c7\u0964 \u09a5\u09be\u09ae\u09be\u09a4\u09c7 \u2018\u09ac\u09be\u09a4\u09bf\u09b2\u2019 \u09ac\u09b2\u09cb\u0964"
            _scheduled_until[0] = now + POWER_DELAY + 5
            return msg
        if w & _NO and len(w) <= 3:
            return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09b2\u09be\u09ae\u0964"
        # something unrelated was said: forget the question, continue normally
    elif _pending["action"]:
        _pending["action"] = None

    # cancel a running countdown
    if now < _scheduled_until[0] and (w & _NO or _has(t, "\u09ac\u09be\u09a4\u09bf\u09b2", "cancel", "\u09a5\u09be\u09ae\u09be\u0993", "abort")):
        _scheduled_until[0] = 0.0
        _do("run", "shutdown", "/a")
        return "\u09b6\u09be\u099f\u09a1\u09be\u0989\u09a8 \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09c7\u099b\u09bf\u0964"
    if _has(t, "cancel shutdown", "abort shutdown", "\u09b6\u09be\u099f\u09a1\u09be\u0989\u09a8 \u09ac\u09be\u09a4\u09bf\u09b2", "\u09b0\u09bf\u09b8\u09cd\u099f\u09be\u09b0\u09cd\u099f \u09ac\u09be\u09a4\u09bf\u09b2"):
        _do("run", "shutdown", "/a")
        return "\u09b6\u09be\u099f\u09a1\u09be\u0989\u09a8 \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09c7\u099b\u09bf\u0964 (\u0995\u09bf\u099b\u09c1 \u099a\u09b2\u099b\u09bf\u09b2 \u09a8\u09be \u09b9\u09b2\u09c7\u0993 \u09b8\u09ae\u09b8\u09cd\u09af\u09be \u09a8\u09c7\u0987\u0964)"

    kind = _power_kind(t)
    if kind == "lock":
        _do("run", "rundll32.exe", "user32.dll,LockWorkStation")
        return "\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8 \u09b2\u0995 \u0995\u09b0\u099b\u09bf\u0964"
    if kind in ("shutdown", "restart"):
        _pending["action"] = kind
        _pending["until"] = now + CONFIRM_SECONDS
        what = "\u09b0\u09bf\u09b8\u09cd\u099f\u09be\u09b0\u09cd\u099f" if kind == "restart" else "\u0995\u09ae\u09cd\u09aa\u09bf\u0989\u099f\u09be\u09b0 \u09ac\u09a8\u09cd\u09a7"
        return f"\u09b8\u09a4\u09cd\u09af\u09bf\u0987 {what} \u0995\u09b0\u09ac\u09cb? \u09a8\u09bf\u09b6\u09cd\u099a\u09bf\u09a4 \u0995\u09b0\u09a4\u09c7 \u2018\u09b9\u09cd\u09af\u09be\u0981\u2019 \u09ac\u09b2\u09cb\u0964"
    return None


# ---------------------------------------------------------------- music
_MOODS = ("mon kharap", "mon valo nai", "mon bhalo nei", "mon valo nei", "mon bhalo nai",
          "feeling sad", "i am sad", "i'm sad", "\u09ae\u09a8 \u0996\u09be\u09b0\u09be\u09aa", "\u09ae\u09a8 \u09ad\u09be\u09b2\u09cb \u09a8\u09c7\u0987", "\u09ae\u09a8 \u09ad\u09be\u09b2\u09cb \u09a8\u09be\u0987")
_PLAY_EN = re.compile(r"^(?:jerox[ ,]+)?(?:please\s+)?play\s+(?P<q>.+)$")
_PLAY_BN = re.compile(
    r"^(?:jerox[ ,]+)?(?:\u0987\u0989\u099f\u09bf\u0989\u09ac\u09c7\s*|youtube\s+)?(?P<q>.+?)\s*(?:\u0997\u09be\u09a8|song|gan)?\s*"
    r"(?:\u099a\u09be\u09b2\u09be\u0993|\u099a\u09be\u09b2\u09bf\u09af\u09bc\u09c7\s*\u09a6\u09be\u0993|\u09ac\u09be\u099c\u09be\u0993|\u09b6\u09cb\u09a8\u09be\u0993|\u09b6\u09c1\u09a8\u09be\u0993|\u099b\u09be\u09a1\u09bc\u09cb|chalao|bajao|sonao|shonao)\s*$")
_FILLER = re.compile(r"\b(?:on|in|from)\s+youtube\b|\u0987\u0989\u099f\u09bf\u0989\u09ac\u09c7|\byoutube\b", re.I)


def _play_on_youtube(query: str) -> bool:
    if DRY_RUN:
        ACTIONS.append(("youtube", query))
        return True
    try:
        from automation import youtube
        result = youtube.search_and_play(query)
        if result is not False:
            return True
    except Exception as exc:
        print(f"[SMART] youtube.search_and_play failed: {exc}")
    try:
        return bool(webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(query)))
    except Exception:
        return False


def _handle_music(t: str) -> Optional[str]:
    if _has(t, *_MOODS):
        query = MOOD_SEARCHES[_mood_index[0] % len(MOOD_SEARCHES)]
        _mood_index[0] += 1
        if _play_on_youtube(query):
            return "\u09ae\u09a8 \u0996\u09be\u09b0\u09be\u09aa \u09b6\u09c1\u09a8\u09c7 \u0996\u09be\u09b0\u09be\u09aa \u09b2\u09be\u0997\u09b2\u09cb, \u09ae\u09be\u09b0\u09c1\u09ab\u0964 \u09a4\u09cb\u09ae\u09be\u09b0 \u099c\u09a8\u09cd\u09af \u098f\u0995\u099f\u09be \u0997\u09be\u09a8 \u099a\u09be\u09b2\u09be\u099a\u09cd\u099b\u09bf\u0964"
        return "\u09ae\u09a8 \u0996\u09be\u09b0\u09be\u09aa \u09b6\u09c1\u09a8\u09c7 \u0996\u09be\u09b0\u09be\u09aa \u09b2\u09be\u0997\u09b2\u09cb, \u09ae\u09be\u09b0\u09c1\u09ab\u0964 \u0997\u09be\u09a8 \u099a\u09be\u09b2\u09be\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be, \u0987\u09a8\u09cd\u099f\u09be\u09b0\u09a8\u09c7\u099f\u099f\u09be \u09a6\u09c7\u0996\u09cb\u0964"
    m = _PLAY_EN.match(t)
    if not m:
        m = _PLAY_BN.match(t)
        if m and not _has(t, "\u0997\u09be\u09a8", "song", "gan", "\u0987\u0989\u099f\u09bf\u0989\u09ac", "youtube"):
            return None
    if not m:
        return None
    q = _FILLER.sub(" ", m.group("q"))
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    if not q or q in {"youtube", "\u0987\u0989\u099f\u09bf\u0989\u09ac", "music", "\u09ae\u09bf\u0989\u099c\u09bf\u0995"} and not _has(t, "song", "\u0997\u09be\u09a8", "gan"):
        return None
    if _play_on_youtube(q):
        return f"\u0987\u0989\u099f\u09bf\u0989\u09ac\u09c7 \u2018{q}\u2019 \u099a\u09be\u09b2\u09be\u099a\u09cd\u099b\u09bf\u0964"
    return "\u0997\u09be\u09a8 \u099a\u09be\u09b2\u09be\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be, \u0987\u09a8\u09cd\u099f\u09be\u09b0\u09a8\u09c7\u099f\u099f\u09be \u09a6\u09c7\u0996\u09cb\u0964"


# ---------------------------------------------------------------- files
_STOP = {"file", "the", "my", "a", "an", "please", "read", "open", "show", "display", "named",
         "called", "of", "to", "me", "jerox", "screen", "on", "and", "it", "this", "any", "network", "drive", "folder", "explorer", "file explorer",
         "\u0996\u09cb\u09b2\u09cb", "\u0996\u09c1\u09b2\u09c7", "\u09a6\u09c7\u0996\u09be\u0993", "\u09a6\u09c7\u0996\u09bf", "\u09aa\u09a1\u09bc\u09cb", "\u09aa\u09a1\u09bc\u09c7", "\u09b6\u09cb\u09a8\u09be\u0993", "\u09a6\u09be\u0993", "\u0995\u09b0\u09cb", "\u0986\u09ae\u09be\u09b0", "\u098f\u0995\u099f\u09be", "\u098f\u0987", "\u0993\u0987"}


def _search_roots() -> list:
    if ROOTS is not None:
        return [Path(r) for r in ROOTS]
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home / "OneDrive",
             home / "Pictures", home / "Videos", home / "Music", Path(r"C:\AssistantX")]
    return [r for r in roots if r.exists()]


def _find_file(name: str) -> Optional[Path]:
    key = name.lower().strip()
    end = time.time() + SEARCH_SECONDS
    exact, starts, contains = [], [], []
    for root in _search_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                low = fn.lower()
                stem = low.rsplit(".", 1)[0]
                if key == low or key == stem:
                    exact.append(Path(dirpath) / fn)
                elif stem.startswith(key):
                    starts.append(Path(dirpath) / fn)
                elif key in low:
                    contains.append(Path(dirpath) / fn)
            if time.time() > end:
                break
        if time.time() > end:
            break
    for group in (exact, starts, contains):
        if group:
            try:
                return max(group, key=lambda p: p.stat().st_mtime)
            except OSError:
                return group[0]
    return None


def _handle_files(t: str) -> Optional[str]:
    if not _has(t, "file", "\u09ab\u09be\u0987\u09b2"):
        return None
    if _has(t, "explorer", "\u098f\u0995\u09cd\u09b8\u09aa\u09cd\u09b2\u09cb\u09b0\u09be\u09b0", "folder", "\u09ab\u09cb\u09b2\u09cd\u09a1\u09be\u09b0"):
        return None
    reading = _has(t, "read", "\u09aa\u09a1\u09bc", "\u09b2\u09c7\u0996\u09be", "what is in", "what's in")
    opening = _has(t, "open", "show", "display", "\u0996\u09cb\u09b2", "\u0996\u09c1\u09b2", "\u09a6\u09c7\u0996")
    if not (reading or opening):
        return None
    quoted = re.search(r"[\"'\u201c\u2018](.+?)[\"'\u201d\u2019]", t)
    if quoted:
        name = quoted.group(1).strip()
    else:
        m = re.search(r"([\w\-. ]{1,60}\.\w{2,5})\b", t)
        if m:
            name = m.group(1).strip()
            name = " ".join(x for x in name.split() if x not in _STOP) or name
        else:
            toks = [x for x in _WORD.findall(t)
                    if x not in _STOP and not x.startswith("\u09ab\u09be\u0987\u09b2") and not x.startswith("\u09aa\u09a1\u09bc")
                    and not x.startswith("\u0996\u09c1\u09b2") and not x.startswith("\u09a6\u09c7\u0996")]
            name = " ".join(toks).strip()
    if not name:
        return "\u0995\u09cb\u09a8 \u09ab\u09be\u0987\u09b2? \u09a8\u09be\u09ae\u099f\u09be \u09ac\u09b2\u09cb\u0964"
    path = _find_file(name)
    if path is None:
        return f"\u2018{name}\u2019 \u09a8\u09be\u09ae\u09c7 \u0995\u09cb\u09a8\u09cb \u09ab\u09be\u0987\u09b2 \u09aa\u09c7\u09b2\u09be\u09ae \u09a8\u09be\u0964"
    if reading and path.suffix.lower() in TEXT_EXTS:
        try:
            body = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            return f"{path.name} \u09aa\u09a1\u09bc\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be ({exc.__class__.__name__})\u0964"
        if not body:
            return f"{path.name} \u09ab\u09be\u0987\u09b2\u099f\u09be \u09ab\u09be\u0981\u0995\u09be\u0964"
        cut = body[:READ_LIMIT] + ("\u2026" if len(body) > READ_LIMIT else "")
        if opening:
            _do("startfile", str(path))
        return f"{path.name} \u09ab\u09be\u0987\u09b2\u09c7\u09b0 \u09b2\u09c7\u0996\u09be: {cut}"
    _do("startfile", str(path))
    if reading:
        return f"{path.name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964 \u098f\u0987 \u09a7\u09b0\u09a8\u09c7\u09b0 \u09ab\u09be\u0987\u09b2 \u0986\u09ae\u09bf \u098f\u0996\u09a8\u09cb \u099c\u09cb\u09b0\u09c7 \u09aa\u09a1\u09bc\u09a4\u09c7 \u09aa\u09be\u09b0\u09bf \u09a8\u09be\u0964"
    return f"{path.name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"


# ---------------------------------------------------------------- apps, browsers, web search
START_DIRS: Optional[list] = None   # override Start Menu folders (self-test)

APPS = {
    "Chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "microsoft edge": "msedge",
    "Firefox": "firefox", "Notepad": "notepad", "Calculator": "calc", "Paint": "mspaint",
    "Cmd": "cmd", "Command Prompt": "cmd", "Powershell": "powershell",
    "Task Manager": "taskmgr", "File Explorer": "explorer", "Explorer": "explorer",
    "Settings": "ms-settings:", "Control Panel": "control", "Word": "winword",
    "Excel": "excel", "PowerPoint": "powerpnt", "VSCode": "code", "VS Code": "code",
    "Visual Studio Code": "code", "Spotify": "spotify", "VLC": "vlc", "vs code": "code", "Visual Studio": "devenv",
    "Camera": "microsoft.windows.camera:", "Settings": "ms-settings:", "Windows Settings": "ms-settings:", "Photos": "microsoft.photos:", "Calculator": "calc", "Paint": "mspaint", "Antigravity": "antigravity", "Microsoft Store": "ms-windows-store:", "Store": "ms-windows-store:", "CapCut": "capcut", "Claude": "claude", "GitHub Desktop": "githubdesktop", "Ollama": "ollama", "Phone Link": "microsoft.windowscommunicationsapps:",
    "\u0995\u09cd\u09b0\u09cb\u09ae": "chrome", "\u098f\u099c": "msedge", "\u09ab\u09be\u09af\u09bc\u09be\u09b0\u09ab\u0995\u09cd\u09b8": "firefox", "\u09a8\u09cb\u099f\u09aa\u09cd\u09af\u09be\u09a1": "notepad",
    "\u0995\u09cd\u09af\u09be\u09b2\u0995\u09c1\u09b2\u09c7\u099f\u09b0": "calc", "\u09aa\u09c7\u0987\u09a8\u09cd\u099f": "mspaint", "\u09b8\u09c7\u099f\u09bf\u0982\u09b8": "ms-settings:",
    "\u0993\u09af\u09bc\u09be\u09b0\u09cd\u09a1": "winword", "\u098f\u0995\u09cd\u09b8\u09c7\u09b2": "excel", "\u0995\u09cd\u09af\u09be\u09ae\u09c7\u09b0\u09be": "microsoft.windows.camera:",
    "\u09b8\u09cd\u09aa\u099f\u09bf\u09ab\u09be\u0987": "spotify", "\u09ab\u09be\u0987\u09b2 \u098f\u0995\u09cd\u09b8\u09aa\u09cd\u09b2\u09cb\u09b0\u09be\u09b0": "explorer",
}
PROCS = {
    "chrome": ("chrome.exe",), "msedge": ("msedge.exe",), "firefox": ("firefox.exe",),
    "notepad": ("notepad.exe",), "calc": ("CalculatorApp.exe", "calc.exe", "Calculator.exe"),
    "mspaint": ("mspaint.exe",), "taskmgr": ("Taskmgr.exe",), "winword": ("WINWORD.EXE",),
    "excel": ("EXCEL.EXE",), "powerpnt": ("POWERPNT.EXE",), "spotify": ("Spotify.exe",),
    "vlc": ("vlc.exe",), "ms-settings:": ("SystemSettings.exe",),
}
# never closed: closing these could kill JEROX itself or the desktop
PROTECTED = {"explorer.exe", "python.exe", "pythonw.exe", "powershell.exe", "pwsh.exe",
             "cmd.exe", "windowsterminal.exe", "conhost.exe", "code.exe", "system",
             "svchost.exe", "winlogon.exe", "csrss.exe", "wininit.exe", "lsass.exe",
             "services.exe"}
SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "facebook": "https://www.facebook.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "wikipedia": "https://www.wikipedia.org",
    "instagram": "https://www.instagram.com", "linkedin": "https://www.linkedin.com",
    "twitter": "https://x.com", "google maps": "https://maps.google.com",
    "\u0987\u0989\u099f\u09bf\u0989\u09ac": "https://www.youtube.com", "\u0997\u09c1\u0997\u09b2": "https://www.google.com",
    "\u09ab\u09c7\u09b8\u09ac\u09c1\u0995": "https://www.facebook.com", "\u099c\u09bf\u09ae\u09c7\u0987\u09b2": "https://mail.google.com",
    "\u0997\u09bf\u099f\u09b9\u09be\u09ac": "https://github.com", "\u0989\u0987\u0995\u09bf\u09aa\u09bf\u09a1\u09bf\u09af\u09bc\u09be": "https://www.wikipedia.org",
}
BROWSERS = {
    "google chrome": "chrome", "chrome": "chrome", "\u0995\u09cd\u09b0\u09cb\u09ae": "chrome",
    "microsoft edge": "msedge", "edge": "msedge", "\u098f\u099c": "msedge",
    "firefox": "firefox", "\u09ab\u09be\u09af\u09bc\u09be\u09b0\u09ab\u0995\u09cd\u09b8": "firefox",
}
ENGINES = {
    "youtube": "https://www.youtube.com/results?search_query=",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search=",
    "bing": "https://www.bing.com/search?q=",
    "google": "https://www.google.com/search?q=",
}
_ENGINE_WORDS = {"youtube": "youtube", "\u0987\u0989\u099f\u09bf\u0989\u09ac": "youtube", "wikipedia": "wikipedia",
                 "\u0989\u0987\u0995\u09bf\u09aa\u09bf\u09a1\u09bf\u09af\u09bc\u09be": "wikipedia", "bing": "bing", "google": "google", "\u0997\u09c1\u0997\u09b2": "google"}

_OPEN_EN = re.compile(r"^(?:open|launch|run)\s+(?P<n>.+)$")
_CLOSE_EN = re.compile(r"^(?:close|quit)\s+(?P<n>.+)$")
_OPEN_BN = re.compile(
    r"^(?P<n>.+?)\s+(?:\u0996\u09cb\u09b2\u09cb|\u0996\u09c1\u09b2\u09cb|\u0996\u09c1\u09b2\u09c7\s*\u09a6\u09be\u0993|\u0993\u09aa\u09c7\u09a8\s*\u0995\u09b0\u09cb|\u0993\u09aa\u09c7\u09a8\s*\u0995\u09b0|\u099a\u09be\u09b2\u09c1\s*\u0995\u09b0\u09cb|\u099a\u09be\u09b2\u09c1\s*\u0995\u09b0|"
    r"open\s*(?:koro|kor)|kholo|khulo)$")
_CLOSE_BN = re.compile(
    r"^(?P<n>.+?)\s+(?:\u09ac\u09a8\u09cd\u09a7\s*\u0995\u09b0\u09c7\s*\u09a6\u09be\u0993|\u09ac\u09a8\u09cd\u09a7\s*\u0995\u09b0\u09cb|\u09ac\u09a8\u09cd\u09a7\s*\u0995\u09b0|close\s*(?:koro|kor)|"
    r"bondho\s*(?:koro|kor)|bondho)$")
_NAME_STOP = {"the", "app", "application", "browser", "my", "please", "window", "\u0985\u09cd\u09af\u09be\u09aa",
              "\u09ac\u09cd\u09b0\u09be\u0989\u099c\u09be\u09b0", "\u0986\u09ae\u09be\u09b0", "\u098f\u0995\u099f\u09be", "\u0989\u0987\u09a8\u09cd\u09a1\u09cb", "\u098f\u09aa"}


def _strip_wake(t: str) -> str:
    return re.sub(r"^(?:(?:jerox|\u099c\u09c7\u09b0\u0995\u09cd\u09b8)[ ,]+)?(?:please\s+)?", "", t).strip()


_OPEN_PRE_BN = re.compile(r"^(?:\u0993\u09aa\u09c7\u09a8|\u0985\u09aa\u09c7\u09a8|\u09b2\u099e\u09cd\u099a|\u09b0\u09be\u09a8)\s+(?P<n>.+)$")
_CLOSE_PRE_BN = re.compile(r"^\u0995\u09cd\u09b2\u09cb\u099c\s+(?P<n>.+)$")


def _clean_name(raw: str) -> str:
    toks = [x for x in _WORD.findall(raw) if x not in _NAME_STOP]
    return " ".join(toks).strip()


def _resolve(table: dict, name: str) -> Optional[str]:
    for key in sorted(table, key=len, reverse=True):
        if key in name:
            return key
    return None


def _pick_browser(raw: str):
    """'... in chrome' / 'chrome \u098f ...' -> ('chrome', text without the browser part)."""
    for key in sorted(BROWSERS, key=len, reverse=True):
        k = re.escape(key)
        for pat in (r"\b(?:in|on|with|using|via)\s+" + k + r"\b",
                    k + r"(?:\u09c7|\s*\u098f|\s*\u09a6\u09bf\u09af\u09bc\u09c7)(?![\w\u0980-\u09ff])"):
            if re.search(pat, raw):
                return BROWSERS[key], re.sub(pat, " ", raw, count=1).strip()
    return None, raw


def _open_url(url: str, browser: Optional[str] = None) -> bool:
    if DRY_RUN:
        ACTIONS.append(("url", url, browser))
        return True
    if browser:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", browser, url],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError:
            pass
    return bool(webbrowser.open(url))


def _find_shortcut(name: str) -> Optional[Path]:
    key = re.sub(r"\s+", " ", name.lower()).strip()
    if not key:
        return None
    if START_DIRS is not None:
        dirs = [Path(d) for d in START_DIRS]
    else:
        dirs = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    exact, starts, contains = [], [], []
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.lnk"):
            stem = p.stem.lower()
            if "uninstall" in stem:
                continue
            if stem == key:
                exact.append(p)
            elif stem.startswith(key):
                starts.append(p)
            elif key in stem:
                contains.append(p)
    for group in (exact, starts, contains):
        if group:
            return sorted(group, key=lambda p: len(p.stem))[0]
    return None


def _open_app(raw: str) -> str:
    browser, rest = _pick_browser(raw)
    name = _clean_name(rest)
    if not name and browser:
        name = raw.strip()
        browser = None
    if not name:
        return "\u0995\u09cb\u09a8 \u0985\u09cd\u09af\u09be\u09aa \u0996\u09c1\u09b2\u09ac\u09cb? \u09a8\u09be\u09ae\u099f\u09be \u09ac\u09b2\u09cb\u0964"
    site = _resolve(SITES, name)
    if site and not _resolve(APPS, name):
        _open_url(SITES[site], browser)
        return f"{name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"
    if re.fullmatch(r"[\w-]+\.(?:com|net|org|io|bd|co|edu|gov)(?:/\S*)?", name):
        _open_url("https://" + name, browser)
        return f"{name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"
    key = _resolve(APPS, name)
    if key:
        try:
            _do("startfile", APPS[key])
            return f"{name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"
        except Exception as exc:
            print(f"[SMART] start {APPS[key]} failed: {exc}")
    lnk = _find_shortcut(key or name)
    if lnk is not None:
        try:
            _do("startfile", str(lnk))
            return f"{name} \u0996\u09c1\u09b2\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"
        except Exception as exc:
            print(f"[SMART] shortcut failed: {exc}")
            return f"{name} \u0996\u09c1\u09b2\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be\u0964"
    return f"\u2018{name}\u2019 \u09a8\u09be\u09ae\u09c7 \u0995\u09cb\u09a8\u09cb \u0985\u09cd\u09af\u09be\u09aa \u0996\u09c1\u0981\u099c\u09c7 \u09aa\u09c7\u09b2\u09be\u09ae \u09a8\u09be\u0964"


def _close_proc(image: str) -> int:
    if DRY_RUN:
        ACTIONS.append(("close", image))
        return 0
    r = subprocess.run(["taskkill", "/IM", image], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode


def _close_app(raw: str) -> str:
    name = _clean_name(raw)
    if not name:
        return "\u0995\u09cb\u09a8 \u0985\u09cd\u09af\u09be\u09aa \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09ac\u09cb? \u09a8\u09be\u09ae\u099f\u09be \u09ac\u09b2\u09cb\u0964"
    key = _resolve(APPS, name)
    if key:
        target = APPS[key]
        procs = PROCS.get(target) or (() if ":" in target else (target + ".exe",))
    else:
        flat = name.replace(" ", "")
        if not re.fullmatch(r"[a-z0-9_-]{3,30}", flat):
            return f"\u2018{name}\u2019 \u0995\u09cb\u09a8 \u0985\u09cd\u09af\u09be\u09aa \u09ac\u09c1\u099d\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be\u0964"
        procs = (flat + ".exe",)
    for image in procs:
        if image.lower() in PROTECTED:
            return "\u098f\u099f\u09be \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09b2\u09c7 \u0986\u09ae\u09bf\u0993 \u09ac\u09a8\u09cd\u09a7 \u09b9\u09af\u09bc\u09c7 \u09af\u09c7\u09a4\u09c7 \u09aa\u09be\u09b0\u09bf, \u09a4\u09be\u0987 \u098f\u099f\u09be \u09a8\u09bf\u099c\u09c7 \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09cb\u0964"
    for image in procs:
        if _close_proc(image) == 0:
            return f"{name} \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09c7 \u09a6\u09bf\u09b2\u09be\u09ae\u0964"
    return f"{name} \u098f\u0996\u09a8 \u099a\u09be\u09b2\u09c1 \u09a8\u09c7\u0987\u0964"


def _handle_apps(t: str) -> Optional[str]:
    t = _strip_wake(t)
    m = _CLOSE_EN.match(t) or _CLOSE_BN.match(t) or _CLOSE_PRE_BN.match(t)
    if m:
        return _close_app(m.group("n"))
    m = _OPEN_EN.match(t) or _OPEN_BN.match(t) or _OPEN_PRE_BN.match(t)
    if m:
        return _open_app(m.group("n"))
    return None


def _handle_search(t: str) -> Optional[str]:
    if _has(t, "file", "\u09ab\u09be\u0987\u09b2"):
        return None
    t = _strip_wake(t)
    m = re.match(r"^(?:search|google|look up)(?:\s+for)?\s+(?P<q>.+)$", t)
    if not m:
        m = re.match(r"^(?P<q>.+?)\s*(?:\u09b8\u09be\u09b0\u09cd\u099a|\u0996\u09c1\u0981\u099c\u09c7?|\u0996\u09cb\u0981\u099c\u09cb?)\s*(?:\u0995\u09b0\u09cb|\u0995\u09b0|\u09a6\u09be\u0993)?\s*$", t)
    if not m:
        return None
    browser, q = _pick_browser(m.group("q"))
    engine = "google"
    for word, eng in _ENGINE_WORDS.items():
        if re.search(r"(?<![\w\u0980-\u09ff])" + re.escape(word), q):
            engine = eng
            q = re.sub(r"(?:\b(?:on|in|at|from)\s+)?(?<![\w\u0980-\u09ff])" + re.escape(word)
                       + r"(?:\u09af\u09bc|\u09c7)?\b", " ", q, count=1)
            break
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    if not q:
        return None
    base = ENGINES[engine]
    if engine == "wikipedia" and re.search(r"[\u0980-\u09ff]", q):
        base = "https://bn.wikipedia.org/w/index.php?search="
    _open_url(base + quote_plus(q), browser)
    return f"{engine.capitalize()}-\u098f \u2018{q}\u2019 \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964"


# ---------------------------------------------------------------- screenshots
SHOT_DELAY = 1          # seconds to wait first, so you can bring another window to the front
_SHOT_WORDS = ("Screenshot naw", "screenshot", "screen shot", "\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f", "\u09b8\u09cd\u0995\u09cd\u09b0\u09c0\u09a8\u09b6\u099f", "\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8 \u09b6\u099f", "\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b8\u099f")
_QUESTION = ("how ", "what ", "why ", "where ", "\u0995\u09c0\u09ad\u09be\u09ac\u09c7", "\u0995\u09bf\u09ad\u09be\u09ac\u09c7", "\u0995\u09c7\u09a8", "\u0995\u09cb\u09a5\u09be\u09af\u09bc")


def _run_grab(mode: str) -> str:
    """Run automation/screen_grab.py in its own process; returns its last output line."""
    if DRY_RUN:
        ACTIONS.append(("grab", mode, SHOT_DELAY))
        return "C:/x/" + mode + "_test.png"
    script = Path(__file__).with_name("screen_grab.py")
    if not script.exists():
        return "ERROR: screen_grab.py is missing"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run([sys.executable, str(script), mode, str(SHOT_DELAY)],
                           capture_output=True, timeout=180, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "ERROR: timed out"
    lines = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    if lines:
        return lines[-1].strip()
    return "ERROR: " + (r.stderr or b"").decode("utf-8", "replace").strip()[-200:]


def _handle_screenshot(t: str) -> Optional[str]:
    if not _has(t, *_SHOT_WORDS) or _has(t, *_QUESTION) or len(_words(t)) > 12:
        return None
    if _has(t, "left", "\u09ac\u09be\u09ae"):
        mode = "left"
    elif _has(t, "right", "\u09a1\u09be\u09a8"):
        mode = "right"
    elif _has(t, "top", "upper", "\u0989\u09aa\u09b0", "\u0993\u09aa\u09b0"):
        mode = "top"
    elif _has(t, "bottom", "lower", "\u09a8\u09bf\u099a"):
        mode = "bottom"
    elif _has(t, "center", "centre", "middle", "\u09ae\u09be\u099d"):
        mode = "center"
    elif _has(t, "area", "region", "select", "choose", "portion", "part", "\u0985\u0982\u09b6", "\u098f\u09b0\u09bf\u09af\u09bc\u09be", "\u09ac\u09c7\u099b\u09c7", "\u09b8\u09bf\u09b2\u09c7\u0995\u09cd\u099f"):
        mode = "area"
    else:
        mode = "full"
    out = _run_grab(mode)
    if out.startswith("CANCELLED"):
        return "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09b2\u09be\u09ae\u0964"
    if out.startswith("ERROR"):
        return "\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09a8\u09bf\u09a4\u09c7 \u09aa\u09be\u09b0\u09b2\u09be\u09ae \u09a8\u09be: " + out[6:].strip()
    return f"\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09b8\u09c7\u09ad \u0995\u09b0\u09c7\u099b\u09bf: {Path(out).name}\u0964 \u09ab\u09cb\u09b2\u09cd\u09a1\u09be\u09b0: Pictures\\AssistantX Screenshots\u0964"


# ---------------------------------------------------------------- entry point
_CONNECT = r"\s+(?:\u0986\u09b0|\u098f\u09ac\u0982|\u09a4\u09be\u09b0\u09aa\u09b0|and|then)\s+"


def _run_handlers(t, allow_power):
    handlers = [_handle_music, _handle_files, _handle_screenshot, _handle_apps, _handle_search]
    if allow_power:
        handlers.insert(0, _handle_power)
    for handler in handlers:
        reply = handler(t)
        if reply:
            return reply
    return None


def try_handle(text) -> Optional[str]:
    t = _norm(text)
    if not t:
        return None
    try:
        reply = _run_handlers(t, True)
        if reply:
            return reply
        import re as _re
        parts = [x.strip(" ,.!?\u0964") for x in _re.split(_CONNECT, t, flags=_re.IGNORECASE)]
        parts = [x for x in parts if x]
        if len(parts) < 2:
            return None
        replies = []
        for part in parts:
            r = _run_handlers(_norm(part), False)
            if r:
                replies.append(r)
        return " ".join(replies) if replies else None
    except Exception as exc:
        print(f"[SMART] {exc.__class__.__name__}: {exc}")
    return None


def _selftest() -> None:
    import tempfile
    global DRY_RUN, ROOTS
    DRY_RUN = True
    tmp = Path(tempfile.mkdtemp())
    (tmp / "notes.txt").write_text("hello from notes", encoding="utf-8")
    (tmp / "cv.pdf").write_bytes(b"%PDF")
    ROOTS = [str(tmp)]
    bad = []

    def check(label, ok):
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            bad.append(label)

    def last():
        return ACTIONS[-1] if ACTIONS else None

    for text in ("hello jerox", "i like to play free fire", "who made you", "how are you",
                 "what is open source", "start a timer", "who is Hozrot Mohammad sallellaho alaihi-oa-sallam", "how to take a screenshot"):
        check(f"ignored: {text}", try_handle(text) is None)
    check("shutdown asks first", "\u09b9\u09cd\u09af\u09be\u0981" in (try_handle("shutdown the pc") or "") and not ACTIONS)
    try_handle("yes")
    check("yes -> shutdown /s", last() == ("run", "shutdown", "/s", "/t", str(POWER_DELAY)))
    try_handle("cancel")
    check("cancel -> shutdown /a", last() == ("run", "shutdown", "/a"))
    try_handle("\u09aa\u09bf\u09b8\u09bf \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09cb")
    check("no -> nothing", try_handle("\u09a8\u09be") == "\u09a0\u09bf\u0995 \u0986\u099b\u09c7, \u09ac\u09be\u09a4\u09bf\u09b2 \u0995\u09b0\u09b2\u09be\u09ae\u0964")
    try_handle("shutdown"); ACTIONS.clear()
    try_handle("chrome \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09cb ok")
    check("long unrelated reply does not confirm", not any(a[0] == "run" for a in ACTIONS))
    try_handle("restart"); try_handle("\u09b9\u09cd\u09af\u09be\u0981")
    check("restart confirmed", last() == ("run", "shutdown", "/r", "/t", str(POWER_DELAY)))
    try_handle("lock the screen")
    check("lock", last() == ("run", "rundll32.exe", "user32.dll,LockWorkStation"))
    ACTIONS.clear()
    try_handle("\u0986\u09ae\u09be\u09b0 \u09ae\u09a8 \u0996\u09be\u09b0\u09be\u09aa")
    check("mood -> song", last() and last()[0] == "youtube" and "sad song" in last()[1])
    try_handle("play Minar Rahman song")
    check("play english", last() == ("youtube", "minar rahman song"))
    try_handle("\u0986\u09ae\u09be\u09b0 \u09b8\u09cb\u09a8\u09be \u09ac\u09a8\u09cd\u09a7\u09c1 \u0997\u09be\u09a8 \u099a\u09be\u09b2\u09be\u0993")
    check("play bangla", last() and last()[0] == "youtube" and "\u0986\u09ae\u09be\u09b0 \u09b8\u09cb\u09a8\u09be \u09ac\u09a8\u09cd\u09a7\u09c1" in last()[1])
    check("read text file", "hello from notes" in (try_handle("read file notes") or ""))
    try_handle("open file cv")
    check("open pdf", last() and last()[0] == "startfile" and last()[1].endswith("cv.pdf"))
    check("missing file", "\u09aa\u09c7\u09b2\u09be\u09ae \u09a8\u09be" in (try_handle("open file nothing123") or ""))

    # apps / browsers / search
    import tempfile as _tf
    global START_DIRS
    sm = Path(_tf.mkdtemp())
    (sm / "My Cool App.lnk").write_bytes(b"x")
    START_DIRS = [str(sm)]
    ACTIONS.clear()
    try_handle("open chrome")
    check("open chrome", last() == ("startfile", "chrome"))
    try_handle("notepad \u0996\u09cb\u09b2\u09cb")
    check("open notepad (bangla verb)", last() == ("startfile", "notepad"))
    try_handle("\u0995\u09cd\u09b0\u09cb\u09ae \u0996\u09cb\u09b2\u09cb")
    check("open chrome (bangla name)", last() == ("startfile", "chrome"))
    try_handle("open file explorer")
    check("open file explorer", last() == ("startfile", "explorer"))
    try_handle("open my cool app")
    check("start menu shortcut", last() and last()[0] == "startfile" and last()[1].endswith("My Cool App.lnk"))
    try_handle("open youtube")
    check("open youtube", last() == ("url", "https://www.youtube.com", None))
    try_handle("open youtube in chrome")
    check("open youtube in chrome", last() == ("url", "https://www.youtube.com", "chrome"))
    try_handle("chrome \u098f \u0987\u0989\u099f\u09bf\u0989\u09ac \u0996\u09cb\u09b2\u09cb")
    check("bangla: youtube in chrome", last() == ("url", "https://www.youtube.com", "chrome"))
    try_handle("close chrome")
    check("close chrome", last() == ("close", "chrome.exe"))
    try_handle("chrome \u09ac\u09a8\u09cd\u09a7 \u0995\u09b0\u09cb")
    check("close chrome (bangla)", last() == ("close", "chrome.exe"))
    ACTIONS.clear()
    check("python protected", "\u0986\u09ae\u09bf\u0993" in (try_handle("close python") or "") and not ACTIONS)
    check("explorer protected", "\u0986\u09ae\u09bf\u0993" in (try_handle("close file explorer") or "") and not ACTIONS)
    try_handle("search messi on firefox")
    check("search in firefox", last() == ("url", "https://www.google.com/search?q=messi", "firefox"))
    try_handle("\u09ae\u09c7\u09b8\u09bf \u09b8\u09be\u09b0\u09cd\u099a \u0995\u09b0\u09cb")
    check("bangla search", last() and last()[1].startswith("https://www.google.com/search?q=%E0%A6"))
    try_handle("search cats on youtube")
    check("search on youtube", last() == ("url", "https://www.youtube.com/results?search_query=cats", None))
    ACTIONS.clear()
    try_handle("notepad \u099a\u09be\u09b2\u09be\u0993")
    check("'\u099a\u09be\u09b2\u09be\u0993' alone is not music", not any(a[0] == "youtube" for a in ACTIONS))
    check("precomposed \u09a1\u09bc reads file", "hello from notes" in (try_handle("notes \u09ab\u09be\u0987\u09b2 \u09aa\u09dc\u09cb") or ""))

    ACTIONS.clear()
    for phrase, mode in (("take a screenshot", "full"), ("screenshot left half", "left"),
                         ("take screenshot of the right side", "right"), ("screenshot top half", "top"),
                         ("screenshot bottom", "bottom"), ("screenshot center", "center"),
                         ("screenshot area", "area"), ("\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09a8\u09be\u0993", "full"),
                         ("\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09c7\u09b0 \u09a1\u09be\u09a8 \u0985\u0982\u09b6\u09c7\u09b0 \u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09a8\u09be\u0993", "right"),
                         ("\u098f\u0995\u099f\u09be \u0985\u0982\u09b6\u09c7\u09b0 \u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09a8\u09b6\u099f \u09a8\u09be\u0993", "area")):
        try_handle(phrase)
        check(f"screenshot {mode}: {phrase}", last() == ("grab", mode, SHOT_DELAY))
    print("SELFTEST PASSED" if not bad else "SELFTEST FAILED: " + ", ".join(bad))


if __name__ == "__main__":
    _selftest()
