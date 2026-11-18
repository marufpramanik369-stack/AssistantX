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
automation/commands.py  (version 3)
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
    "কর", "চালু", "ওপেন", "লঞ্চ", "স্টার্ট", "প্লিজ", "অ্যাপ",
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
}

# Websites opened in the default browser.
_SITES = {
    "facebook": "https://www.facebook.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "wikipedia": "https://www.wikipedia.org",
    "messenger": "https://www.messenger.com",
    "whatsapp": "https://web.whatsapp.com",
}

# Browsers that Windows can start by name even when they are not on PATH.
_WIN_START = {
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox", "mozilla firefox": "firefox",
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

    def handle_app_launch(utterance: str, slots: dict[str, Any]):
        text = str(utterance or "")

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
                    return fail(name, text)

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
        description="Open desktop applications and websites",
    )
    print("[AUTO] app-launch command registered (v3)")
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

print("UPDATED automation\\commands.py  (old copy: automation\\commands.py.bak)")
print("DONE. Close the assistant and run:  python main.py")


