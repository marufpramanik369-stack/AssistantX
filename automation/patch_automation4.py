import py_compile
import shutil
import sys
from pathlib import Path

# Put this file inside C:\AssistantX\automation (or C:\AssistantX) and run it.
HERE = Path(__file__).resolve().parent
ROOT = HERE
if not (ROOT / "core" / "assistant.py").exists():
    if (HERE.parent / "core" / "assistant.py").exists():
        ROOT = HERE.parent
COMMANDS = ROOT / "automation" / "commands.py"
BACKUP = Path(str(COMMANDS) + ".bak")

CODE = r'''"""
automation/commands.py  (version 4)
===================================

"open chrome" / "ক্রোম খোলো" opens apps, and "open facebook" /
"ফেসবুক খোলো" opens websites in the default browser.

If the name is not an app or a known website, the request falls back
to normal AI chat, so nothing else changes.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import webbrowser
from typing import Any, Callable

logger = logging.getLogger(__name__)

_BANGLA = re.compile(r"[\u0980-\u09FF]")
_HINDI = re.compile(r"[\u0900-\u097F]")

# Words that are not part of a name.
_NOISE = {
    "open", "launch", "start", "run", "please", "the", "app",
    "application", "program", "for", "me", "now", "jerox", "can",
    "you", "could", "will", "kindly", "a", "to", "website", "site",
    "web", "page", "go", "on",
    "খোলো", "খুলো", "খুলুন", "খুলে", "দাও", "দিন", "করো", "করুন",
    "কর", "করে", "চালু", "ওপেন", "লঞ্চ", "স্টার্ট", "প্লিজ", "অ্যাপ",
    "অ্যাপটা", "অ্যাপটি", "অ্যাপ্লিকেশন", "প্রোগ্রাম", "একটু",
    "আমার", "জন্য", "জেরক্স", "তুমি", "আমাকে", "ওয়েবসাইট",
    "সাইট", "ওয়েব", "পেজ", "গিয়ে", "এ", "তে",
    "खोलो", "खोलिए", "खोल", "दो", "करो", "ऐप", "कृपया",
}

# Bangla / Hindi spellings -> English names.
_ALIASES = {
    "ক্রোম": "chrome", "গুগল ক্রোম": "chrome", "क्रोम": "chrome",
    "নোটপ্যাড": "notepad", "नोटपैड": "notepad",
    "ক্যালকুলেটর": "calculator", "ক্যালকুলেটার": "calculator",
    "कैलकुलेटर": "calculator",
    "পেইন্ট": "paint", "পেন্ট": "paint",
    "ওয়ার্ড": "word", "এক্সেল": "excel", "পাওয়ারপয়েন্ট": "powerpoint",
    "এজ": "edge", "ফায়ারফক্স": "firefox",
    "ভিএস কোড": "vscode", "ভিএসকোড": "vscode",
    "স্পটিফাই": "spotify", "টেলিগ্রাম": "telegram", "ভিএলসি": "vlc",
    "ফাইল এক্সপ্লোরার": "explorer", "এক্সপ্লোরার": "explorer",
    "সেটিংস": "settings", "টার্মিনাল": "terminal",
    "কমান্ড প্রম্পট": "cmd", "ডিসকর্ড": "discord", "জুম": "zoom",
    "স্টিম": "steam", "টাস্ক ম্যানেজার": "task manager",
    "ফেসবুক": "facebook", "ফেসবুকে": "facebook", "फेसबुक": "facebook",
    "ইউটিউব": "youtube", "ইউটিউবে": "youtube", "यूट्यूब": "youtube",
    "গুগল": "google", "গুগলে": "google", "जीमेल": "gmail",
    "জিমেইল": "gmail", "গিটহাব": "github", "উইকিপিডিয়া": "wikipedia",
    "হোয়াটসঅ্যাপ": "whatsapp", "মেসেঞ্জার": "messenger",
    "পাইচার্ম": "pycharm", "অলামা": "ollama", "ক্লড": "claude",
    "fb": "facebook", "yt": "youtube",
    # --- extra browsers / apps ---
    "ব্রেভ": "brave", "অপেরা": "opera", "ভিভাল্ডি": "vivaldi",
    "ব্রাউজার": "chrome", "browser": "chrome",
    "ওয়ার্ডপ্যাড": "wordpad", "কন্ট্রোল প্যানেল": "control panel",
    "পাওয়ারশেল": "powershell", "স্নিপিং টুল": "snipping tool",
    "ক্যামেরা": "camera", "ঘড়ি": "clock", "আউটলুক": "outlook",
    "ওয়াননোট": "onenote", "টিমস": "teams", "স্কাইপ": "skype",
    "স্ল্যাক": "slack", "অবস": "obs", "ডকার": "docker",
    "পোস্টম্যান": "postman", "ফিগমা": "figma", "ইন্টেলিজ": "intellij",
    "সাবলাইম": "sublime", "অ্যান্ড্রয়েড স্টুডিও": "android studio",
    "ভিজ্যুয়াল স্টুডিও": "visual studio", "এনিডেস্ক": "anydesk",
    "টিমভিউয়ার": "teamviewer", "উইনরার": "winrar",
    "ডিভাইস ম্যানেজার": "device manager",
    # --- extra sites ---
    "ইনস্টাগ্রাম": "instagram", "ইন্সটাগ্রাম": "instagram",
    "টুইটার": "twitter", "এক্স": "twitter", "লিংকডইন": "linkedin",
    "রেডিট": "reddit", "টিকটক": "tiktok", "নেটফ্লিক্স": "netflix",
    "চ্যাটজিপিটি": "chatgpt", "চ্যাট জিপিটি": "chatgpt", "chat gpt": "chatgpt",
    "জেমিনি": "gemini web", "gemini": "gemini web", "ক্লড ওয়েব": "claude web",
    "গুগল ড্রাইভ": "google drive", "গুগল ম্যাপ": "google maps",
    "গুগল ম্যাপস": "google maps", "ম্যাপ": "google maps",
    "গুগল ট্রান্সলেট": "google translate", "অনুবাদ": "google translate",
    "স্ট্যাক ওভারফ্লো": "stackoverflow", "stack overflow": "stackoverflow",
    "লিটকোড": "leetcode", "কোডফোর্সেস": "codeforces",
    "কাগল": "kaggle", "মিডিয়াম": "medium", "dev to": "devto",
    "গিটল্যাব": "gitlab", "হাগিং ফেস": "huggingface",
    "hugging face": "huggingface", "পাইপাই": "pypi", "এনপিএম": "npm",
    "অ্যামাজন": "amazon", "আমাজন": "amazon", "দারাজ": "daraz",
    "প্রথম আলো": "prothom alo", "আবহাওয়া": "weather",
    "twitch tv": "twitch", "x com": "twitter",
    "py charm": "pycharm", "note pad": "notepad",
    "whats app": "whatsapp", "face book": "facebook", "you tube": "youtube",
    "ms word": "word", "ms excel": "excel", "ms paint": "paint",
    "ms powerpoint": "powerpoint", "windows terminal": "terminal",
    "chatgpt web": "chatgpt", "github web": "github",
    "whatsapp web": "whatsapp",
}

# Websites opened in the default browser.
_SITES = {
    # --- search / mail / google ---
    "google": "https://www.google.com", "bing": "https://www.bing.com",
    "duckduckgo": "https://duckduckgo.com", "yahoo": "https://www.yahoo.com",
    "gmail": "https://mail.google.com", "outlook web": "https://outlook.live.com",
    "google drive": "https://drive.google.com", "google maps": "https://maps.google.com",
    "google translate": "https://translate.google.com",
    "google docs": "https://docs.google.com", "google sheets": "https://sheets.google.com",
    "google slides": "https://slides.google.com", "google meet": "https://meet.google.com",
    "google calendar": "https://calendar.google.com", "google photos": "https://photos.google.com",
    "google colab": "https://colab.research.google.com",
    # --- social ---
    "facebook": "https://www.facebook.com", "messenger": "https://www.messenger.com",
    "instagram": "https://www.instagram.com", "twitter": "https://x.com",
    "linkedin": "https://www.linkedin.com", "reddit": "https://www.reddit.com",
    "pinterest": "https://www.pinterest.com", "tiktok": "https://www.tiktok.com",
    "whatsapp": "https://web.whatsapp.com", "telegram web": "https://web.telegram.org",
    "discord web": "https://discord.com/app", "quora": "https://www.quora.com",
    "snapchat": "https://www.snapchat.com",
    # --- video / music / fun ---
    "youtube": "https://www.youtube.com", "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv", "spotify web": "https://open.spotify.com",
    "imdb": "https://www.imdb.com", "soundcloud": "https://soundcloud.com",
    # --- AI ---
    "chatgpt": "https://chatgpt.com", "claude web": "https://claude.ai",
    "gemini web": "https://gemini.google.com", "perplexity": "https://www.perplexity.ai",
    "huggingface": "https://huggingface.co", "copilot": "https://copilot.microsoft.com",
    # --- programmer ---
    "github": "https://github.com", "gitlab": "https://gitlab.com",
    "bitbucket": "https://bitbucket.org", "stackoverflow": "https://stackoverflow.com",
    "leetcode": "https://leetcode.com", "hackerrank": "https://www.hackerrank.com",
    "codeforces": "https://codeforces.com", "geeksforgeeks": "https://www.geeksforgeeks.org",
    "w3schools": "https://www.w3schools.com", "mdn": "https://developer.mozilla.org",
    "pypi": "https://pypi.org", "npm": "https://www.npmjs.com",
    "docker hub": "https://hub.docker.com", "kaggle": "https://www.kaggle.com",
    "medium": "https://medium.com", "devto": "https://dev.to",
    "hacker news": "https://news.ycombinator.com", "replit": "https://replit.com",
    "codepen": "https://codepen.io", "jsfiddle": "https://jsfiddle.net",
    "figma web": "https://www.figma.com", "canva": "https://www.canva.com",
    "notion": "https://www.notion.so", "trello": "https://trello.com",
    "slack web": "https://app.slack.com", "postman web": "https://web.postman.co",
    "vercel": "https://vercel.com", "netlify": "https://www.netlify.com",
    "stackblitz": "https://stackblitz.com", "python docs": "https://docs.python.org",
    "aws": "https://aws.amazon.com", "azure": "https://portal.azure.com",
    "firebase": "https://console.firebase.google.com",
    "ollama web": "https://ollama.com",
    # --- shopping / info / news ---
    "amazon": "https://www.amazon.com", "daraz": "https://www.daraz.com.bd",
    "ebay": "https://www.ebay.com", "aliexpress": "https://www.aliexpress.com",
    "wikipedia": "https://www.wikipedia.org", "prothom alo": "https://www.prothomalo.com",
    "bdnews24": "https://bdnews24.com", "daily star": "https://www.thedailystar.net",
    "bbc": "https://www.bbc.com", "cnn": "https://www.cnn.com",
    "weather": "https://www.google.com/search?q=weather",
}

# Words that appear in the browser window title of a site (used to close it).
_SITE_TITLE = {
    "google drive": "Google Drive", "google maps": "Google Maps",
    "google translate": "Google Translate", "google docs": "Google Docs",
    "google sheets": "Google Sheets", "google slides": "Google Slides",
    "google meet": "Meet", "google calendar": "Google Calendar",
    "google photos": "Google Photos", "google colab": "Colab",
    "outlook web": "Outlook", "twitter": "X", "whatsapp": "WhatsApp",
    "telegram web": "Telegram", "discord web": "Discord",
    "spotify web": "Spotify", "claude web": "Claude", "gemini web": "Gemini",
    "huggingface": "Hugging Face", "stackoverflow": "Stack Overflow",
    "geeksforgeeks": "GeeksforGeeks", "mdn": "MDN", "docker hub": "Docker Hub",
    "devto": "DEV", "hacker news": "Hacker News", "figma web": "Figma",
    "slack web": "Slack", "postman web": "Postman", "python docs": "Python",
    "ollama web": "Ollama", "prothom alo": "Prothom Alo",
    "daily star": "Daily Star", "weather": "weather",
}

# Browsers that Windows can start by name even when they are not on PATH.
_WIN_START = {
    # --- browsers ---
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox", "mozilla firefox": "firefox",
    "brave": "brave", "vivaldi": "vivaldi", "opera": "opera",
    # --- Windows tools ---
    "notepad": "notepad", "calculator": "calc", "calc": "calc",
    "paint": "mspaint", "wordpad": "write", "explorer": "explorer",
    "file explorer": "explorer", "task manager": "taskmgr",
    "control panel": "control", "cmd": "cmd", "command prompt": "cmd",
    "powershell": "powershell", "terminal": "wt",
    "snipping tool": "snippingtool", "settings": "ms-settings:",
    "camera": "microsoft.windows.camera:", "clock": "ms-clock:",
    "device manager": "devmgmt.msc", "services": "services.msc",
    "disk management": "diskmgmt.msc", "system info": "msinfo32",
    # --- Office ---
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "outlook": "outlook", "onenote": "onenote", "access": "msaccess",
}

_MAX_TOKENS = 4


def _candidates(utterance: str) -> list[str]:
    """Possible names found inside a short spoken command."""

    text = re.sub(r"[,.!?।;:\"'()]", " ", str(utterance).lower())
    tokens = [t for t in text.split() if t not in _NOISE]

    # Real launch commands are short ("open chrome"). Long sentences
    # are normal conversation.
    if not tokens or len(tokens) > _MAX_TOKENS:
        return []

    out: list[str] = []
    n = len(tokens)
    for size in range(n, 0, -1):
        for i in range(0, n - size + 1):
            phrase = " ".join(tokens[i:i + size])
            mapped = _ALIASES.get(phrase, phrase)
            if mapped not in out:
                out.append(mapped)
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z\u0980-\u09FF\u0900-\u097F]", "", text.lower())


_SHORTCUTS: dict[str, str] | None = None


def _shortcuts() -> dict[str, str]:
    """Desktop + Start Menu shortcuts (and Desktop folders): name -> path."""

    global _SHORTCUTS
    if _SHORTCUTS is not None:
        return _SHORTCUTS
    found: dict[str, str] = {}
    from pathlib import Path

    roots = []
    for var, sub in (
        ("USERPROFILE", "Desktop"),
        ("PUBLIC", "Desktop"),
        ("OneDrive", "Desktop"),
        ("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
        ("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs"),
    ):
        base = os.environ.get(var)
        if base:
            roots.append((Path(base) / sub, var in ("USERPROFILE", "OneDrive")))
    for root, include_dirs in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".lnk", ".url", ".exe"):
                    found.setdefault(_norm(p.stem), str(p))
                elif include_dirs and p.is_dir() and p.parent == root:
                    found.setdefault(_norm(p.name), str(p))
        except Exception as exc:
            print(f"[AUTO] scan failed for {root}: {exc}")
    _SHORTCUTS = found
    print(f"[AUTO] found {len(found)} shortcuts")
    return found


def _find_shortcut(name: str) -> str | None:
    key = _norm(name)
    if not key:
        return None
    table = _shortcuts()
    if key in table:
        return table[key]
    if len(key) >= 4:
        for k, path in table.items():
            if key in k:
                return path
    return None


# ---- closing apps -------------------------------------------------------
_CLOSE_WORDS = {"close", "quit", "kill", "বন্ধ", "बंद", "बन्द"}

# Spoken name -> Windows process name.
_EXE = {
    # --- browsers ---
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe", "mozilla firefox": "firefox.exe",
    "brave": "brave.exe", "vivaldi": "vivaldi.exe", "opera": "opera.exe",
    "tor": "tor.exe",
    # --- Windows tools ---
    "notepad": "notepad.exe", "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe", "paint": "mspaint.exe",
    "wordpad": "wordpad.exe", "task manager": "Taskmgr.exe",
    "snipping tool": "SnippingTool.exe", "settings": "SystemSettings.exe",
    "camera": "WindowsCamera.exe", "control panel": "control.exe",
    # --- Office ---
    "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE", "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE", "access": "MSACCESS.EXE",
    # --- programmer tools ---
    "vscode": "Code.exe", "code": "Code.exe", "vs code": "Code.exe",
    "pycharm": "pycharm64.exe", "intellij": "idea64.exe",
    "android studio": "studio64.exe", "visual studio": "devenv.exe",
    "notepad++": "notepad++.exe", "sublime": "sublime_text.exe",
    "postman": "Postman.exe", "docker": "Docker Desktop.exe",
    "github desktop": "GitHubDesktop.exe", "figma": "Figma.exe",
    "git bash": "git-bash.exe", "ollama": "ollama app.exe",
    "claude": "claude.exe",
    # --- social / media / other apps ---
    "spotify": "Spotify.exe", "vlc": "vlc.exe", "telegram": "Telegram.exe",
    "whatsapp": "WhatsApp.exe", "discord": "Discord.exe", "zoom": "Zoom.exe",
    "skype": "Skype.exe", "teams": "ms-teams.exe", "slack": "slack.exe",
    "steam": "steam.exe", "obs": "obs64.exe", "anydesk": "AnyDesk.exe",
    "teamviewer": "TeamViewer.exe", "acrobat": "Acrobat.exe",
    "winrar": "WinRAR.exe", "7zip": "7zFM.exe",
}
_BROWSER_EXES = {"chrome.exe", "msedge.exe", "firefox.exe"}
# Never close these by voice.
# The terminal that runs JEROX must never be closed by voice.
_PROTECTED = {
    "python.exe", "pythonw.exe", "explorer.exe", "system", "cmd.exe",
    "powershell.exe", "pwsh.exe", "windowsterminal.exe", "conhost.exe",
}


def _split_close(utterance: str) -> tuple[bool, str]:
    text = re.sub(r"[,.!?।;:\"'()]", " ", str(utterance).lower())
    tokens = text.split()
    closing = any(t in _CLOSE_WORDS for t in tokens)
    rest = " ".join(t for t in tokens if t not in _CLOSE_WORDS)
    return closing, rest


def _is_running(exe: str) -> bool:
    import subprocess

    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
            capture_output=True, text=True, errors="replace",
        ).stdout
        return exe.lower() in out.lower()
    except Exception as exc:
        print(f"[AUTO] tasklist failed: {exc}")
        return False


def _close_exe(exe: str) -> str:
    """Returns 'closed', 'not_running', 'still_open' or 'error'."""
    import subprocess
    import time

    if exe.lower() in _PROTECTED:
        return "error"
    if not _is_running(exe):
        return "not_running"
    try:
        # Polite close first (lets apps ask about unsaved work).
        subprocess.run(
            ["taskkill", "/IM", exe, "/T"], capture_output=True,
            text=True, errors="replace",
        )
        for _ in range(6):
            time.sleep(0.5)
            if not _is_running(exe):
                return "closed"
        if exe.lower() in {e.lower() for e in _BROWSER_EXES}:
            subprocess.run(
                ["taskkill", "/IM", exe, "/F", "/T"], capture_output=True,
                text=True, errors="replace",
            )
            time.sleep(0.5)
            return "closed" if not _is_running(exe) else "error"
        return "still_open"
    except Exception as exc:
        print(f"[AUTO] close failed: {exc}")
        return "error"


_BROWSER_PROCS = "chrome,msedge,firefox,brave,opera,vivaldi"


def _close_site_window(keyword: str) -> str:
    """Closes browser windows whose title contains the site name."""
    import subprocess
    import time

    key = re.sub(r"[^0-9A-Za-z +-]", "", keyword)
    if not key:
        return "error"
    script = (
        f"$p = Get-Process -Name {_BROWSER_PROCS} -ErrorAction SilentlyContinue "
        f"| Where-Object {{ $_.MainWindowTitle -like '*{key}*' }}; "
        "if (-not $p) { exit 3 }; "
        "$p | ForEach-Object { [void]$_.CloseMainWindow() }"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, errors="replace",
        )
        print(f"[AUTO] close site window '{key}' rc={r.returncode}")
        if r.returncode == 3:
            return "not_running"
        time.sleep(0.5)
        return "closed" if r.returncode == 0 else "error"
    except Exception as exc:
        print(f"[AUTO] site close failed: {exc}")
        return "error"


def _say_close(kind: str, name: str, text: str) -> str:
    if _BANGLA.search(text):
        return {
            "closed": f"{name} বন্ধ করেছি।",
            "not_running": f"{name} তো চালু নেই।",
            "still_open": f"{name} এখনো খোলা, হয়তো সেভ করতে বলছে।",
            "site_missing": f"{name} কোনো ব্রাউজার উইন্ডোতে খোলা পাইনি।",
            "error": f"আমি {name} বন্ধ করতে পারিনি।",
        }[kind]
    if _HINDI.search(text):
        return {
            "closed": f"{name} बंद कर दिया।",
            "not_running": f"{name} चालू नहीं है।",
            "still_open": f"{name} अभी खुला है, शायद सेव पूछ रहा है।",
            "site_missing": f"{name} किसी ब्राउज़र विंडो में खुला नहीं मिला।",
            "error": f"मैं {name} बंद नहीं कर सका।",
        }[kind]
    return {
        "closed": f"Closed {name}.",
        "not_running": f"{name} is not running.",
        "still_open": f"{name} is still open, it may be asking to save.",
        "site_missing": f"I could not find {name} open in a browser window.",
        "error": f"I could not close {name}.",
    }[kind]


def _say(kind: str, name: str, text: str) -> str:
    if _BANGLA.search(text):
        return (
            f"ঠিক আছে, {name} খুলছি।"
            if kind == "ok"
            else f"আমি {name} খুলতে পারিনি।"
        )
    if _HINDI.search(text):
        return (
            f"ठीक है, {name} खोल रहा हूँ।"
            if kind == "ok"
            else f"मैं {name} नहीं खोल सका।"
        )
    return f"Opening {name}." if kind == "ok" else f"I could not open {name}."


def register_automation_commands(chat_fallback: Callable[..., Any]) -> None:
    """Register the "open an app / website" command on the global router."""

    from config.constants import IntentCategory
    from core.command_router import CommandResult, register_command

    def ok(name: str, text: str):
        return CommandResult.ok(
            _say("ok", name, text), intent=IntentCategory.APP_LAUNCH
        )

    def fail(name: str, text: str):
        return CommandResult.fail(
            error=f"could not open {name}",
            intent=IntentCategory.APP_LAUNCH,
            message=_say("fail", name, text),
        )

    def handle_close(rest: str, text: str):
        starter = getattr(os, "startfile", None)
        if starter is None or sys.platform != "win32":
            return chat_fallback(text, {})
        for name in _candidates(rest):
            if name in _SITES:
                result = _close_site_window(_SITE_TITLE.get(name, name))
                if result == "error":
                    return CommandResult.fail(
                        error=f"could not close {name}",
                        intent=IntentCategory.APP_LAUNCH,
                        message=_say_close("error", name, text),
                    )
                if result == "not_running":
                    msg = _say_close("site_missing", name, text)
                else:
                    msg = _say_close(result, name, text)
                return CommandResult.ok(msg, intent=IntentCategory.APP_LAUNCH)
            exe = _EXE.get(name)
            if exe is None and re.fullmatch(r"[a-z0-9 _-]{3,30}", name):
                exe = name.replace(" ", "") + ".exe"
            if not exe:
                continue
            result = _close_exe(exe)
            print(f"[AUTO] close {exe} -> {result}")
            if result == "error":
                return CommandResult.fail(
                    error=f"could not close {name}",
                    intent=IntentCategory.APP_LAUNCH,
                    message=_say_close("error", name, text),
                )
            return CommandResult.ok(
                _say_close(result, name, text),
                intent=IntentCategory.APP_LAUNCH,
            )
        return chat_fallback(text, {})

    def handle_app_launch(utterance: str, slots: dict[str, Any]):
        text = str(utterance or "")

        closing, rest = _split_close(text)
        if closing:
            return handle_close(rest, text)

        try:
            from automation import apps
        except Exception as exc:
            apps = None
            print(f"[AUTO] automation.apps import failed: {exc}")

        for name in _candidates(text):
            # 1) Websites
            if name in _SITES:
                print(f"[AUTO] website '{name}' -> {_SITES[name]}")
                try:
                    if webbrowser.open(_SITES[name]):
                        return ok(name, text)
                except Exception as exc:
                    print(f"[AUTO] webbrowser failed: {exc}")
                return fail(name, text)

            # 2) Apps known to automation.apps
            available = False
            if apps is not None:
                try:
                    available = bool(apps.is_app_available(name))
                except Exception:
                    available = False
            print(f"[AUTO] try '{name}' -> available={available}")

            if available:
                try:
                    if bool(apps.open_app(name)):
                        return ok(name, text)
                except Exception as exc:
                    print(f"[AUTO] open_app('{name}') failed: {exc}")
                return fail(name, text)

            # 3) Browsers that Windows can start by name
            exe = _WIN_START.get(name)
            starter = getattr(os, "startfile", None)
            if exe and starter is not None and sys.platform == "win32":
                try:
                    starter(exe)
                    print(f"[AUTO] started '{exe}' through Windows")
                    return ok(name, text)
                except Exception as exc:
                    print(f"[AUTO] could not start '{exe}': {exc}")

            # 4) Any Desktop / Start Menu shortcut or Desktop folder
            starter = getattr(os, "startfile", None)
            if starter is not None and sys.platform == "win32":
                path = _find_shortcut(name)
                if path:
                    try:
                        starter(path)
                        print(f"[AUTO] opened shortcut {path}")
                        return ok(name, text)
                    except Exception as exc:
                        print(f"[AUTO] shortcut failed: {exc}")
                        return fail(name, text)

        # Not an app or site we know: let the AI answer normally.
        return chat_fallback(utterance, slots)

    register_command(
        IntentCategory.APP_LAUNCH,
        handle_app_launch,
        overwrite=True,
        description="Open and close desktop applications and websites",
    )
    print("[AUTO] app-launch command registered (v4)")
'''

if not COMMANDS.parent.exists():
    print("ERROR: automation folder not found at:", COMMANDS.parent)
    sys.exit(1)

if COMMANDS.exists():
    shutil.copy(COMMANDS, BACKUP)

COMMANDS.write_text(CODE, encoding="utf-8")

try:
    py_compile.compile(str(COMMANDS), doraise=True)
except py_compile.PyCompileError as exc:
    if BACKUP.exists():
        shutil.copy(BACKUP, COMMANDS)
    print("ERROR: syntax problem, old file restored.")
    print(exc)
    sys.exit(1)


# ---- add "close" keywords so the router sends them to the same handler ----
ASSISTANT = ROOT / "core" / "assistant.py"
ABACKUP = Path(str(ASSISTANT) + ".bak2")
KW_ANCHOR = (
    "                \"खोलो\",\n"
    "            ),\n"
)
KW_NEW = (
    "                \"खोलो\",\n"
    "                \"close\",\n"
    "                \"quit\",\n"
    "                \"বন্ধ করো\",\n"
    "                \"বন্ধ কর\",\n"
    "                \"বন্ধ করুন\",\n"
    "                \"বন্ধ করে দাও\",\n"
    "                \"बंद करो\",\n"
    "            ),\n"
)
if ASSISTANT.exists():
    asrc = ASSISTANT.read_text(encoding="utf-8")
    if "\"বন্ধ করো\"" in asrc:
        print("assistant.py already has close keywords.")
    elif asrc.count(KW_ANCHOR) != 1:
        print("WARNING: close keywords NOT added (spot count:",
              asrc.count(KW_ANCHOR), "). Send me this message.")
    else:
        shutil.copy(ASSISTANT, ABACKUP)
        ASSISTANT.write_text(asrc.replace(KW_ANCHOR, KW_NEW, 1), encoding="utf-8")
        try:
            py_compile.compile(str(ASSISTANT), doraise=True)
            print("PATCHED core\\assistant.py (close keywords added)")
        except py_compile.PyCompileError as exc:
            shutil.copy(ABACKUP, ASSISTANT)
            print("ERROR: assistant.py restored.", exc)
else:
    print("WARNING: core\\assistant.py not found.")

print("UPDATED automation\\commands.py  (old copy: automation\\commands.py.bak)")
print("DONE. Close the assistant and run:  python main.py")
