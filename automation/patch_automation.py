import py_compile
import shutil
import sys
from pathlib import Path

# Put this file in C:\AssistantX or inside C:\AssistantX\automation, then run it.
HERE = Path(__file__).resolve().parent
ROOT = HERE
if not (ROOT / "core" / "assistant.py").exists():
    if (HERE.parent / "core" / "assistant.py").exists():
        ROOT = HERE.parent
ASSISTANT = ROOT / "core" / "assistant.py"
COMMANDS = ROOT / "automation" / "commands.py"
BACKUP = Path(str(ASSISTANT) + ".bak")

COMMANDS_CODE = r'''"""
automation/commands.py
======================

Connects the existing automation modules to JEROX's command router,
so that "open chrome" / "ক্রোম খোলো" really opens the app.

Added by patch_automation.py. If an app name is not recognised, the
request falls back to normal AI chat, so nothing else changes.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

_BANGLA = re.compile(r"[\u0980-\u09FF]")
_HINDI = re.compile(r"[\u0900-\u097F]")

# Words that are not part of an app name.
_NOISE = {
    "open", "launch", "start", "run", "please", "the", "app",
    "application", "program", "for", "me", "now", "jerox", "can",
    "you", "could", "will", "kindly", "a", "to",
    "খোলো", "খুলো", "খুলুন", "খুলে", "দাও", "দিন", "করো", "করুন",
    "কর", "চালু", "ওপেন", "লঞ্চ", "স্টার্ট", "প্লিজ", "অ্যাপ",
    "অ্যাপটা", "অ্যাপটি", "অ্যাপ্লিকেশন", "প্রোগ্রাম", "একটু",
    "আমার", "জন্য", "জেরক্স", "তুমি", "আমাকে",
    "खोलो", "खोलिए", "खोल", "दो", "करो", "ऐप", "कृपया",
}

# Bangla / Hindi spellings -> the English name used by automation.apps.
_ALIASES = {
    "ক্রোম": "chrome", "গুগল ক্রোম": "chrome", "क्रोम": "chrome",
    "নোটপ্যাড": "notepad", "नोटपैड": "notepad",
    "ক্যালকুলেটর": "calculator", "ক্যালকুলেটার": "calculator",
    "कैलकुलेटर": "calculator",
    "পেইন্ট": "paint", "পেন্ট": "paint",
    "ওয়ার্ড": "word", "এক্সেল": "excel", "পাওয়ারপয়েন্ট": "powerpoint",
    "এজ": "edge", "ফায়ারফক্স": "firefox",
    "ভিএস কোড": "vscode", "ভিএসকোড": "vscode",
    "স্পটিফাই": "spotify", "হোয়াটসঅ্যাপ": "whatsapp",
    "টেলিগ্রাম": "telegram", "ভিএলসি": "vlc",
    "ফাইল এক্সপ্লোরার": "explorer", "এক্সপ্লোরার": "explorer",
    "সেটিংস": "settings", "ক্যামেরা": "camera",
    "টার্মিনাল": "terminal", "কমান্ড প্রম্পট": "cmd",
    "ডিসকর্ড": "discord", "জুম": "zoom", "স্টিম": "steam",
    "টাস্ক ম্যানেজার": "task manager",
}

_MAX_TOKENS = 4


def _candidates(utterance: str) -> list[str]:
    """Possible app names found inside a short spoken command."""

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
    """Register the "open an app" command on the global router."""

    from config.constants import IntentCategory
    from core.command_router import CommandResult, register_command

    def handle_app_launch(utterance: str, slots: dict[str, Any]):
        text = str(utterance or "")

        try:
            from automation import apps
        except Exception as exc:
            print(f"[AUTO] automation.apps import failed: {exc}")
            logger.warning("automation.apps import failed: %s", exc)
            return chat_fallback(utterance, slots)

        for name in _candidates(text):
            try:
                available = bool(apps.is_app_available(name))
            except Exception:
                available = False

            print(f"[AUTO] try '{name}' -> available={available}")

            if not available:
                continue

            try:
                opened = bool(apps.open_app(name))
            except Exception as exc:
                print(f"[AUTO] open_app('{name}') failed: {exc}")
                opened = False

            if opened:
                return CommandResult.ok(
                    _say("ok", name, text),
                    intent=IntentCategory.APP_LAUNCH,
                )

            return CommandResult.fail(
                error=f"open_app failed for {name}",
                intent=IntentCategory.APP_LAUNCH,
                message=_say("fail", name, text),
            )

        # Not an app we know: let the AI answer normally.
        return chat_fallback(utterance, slots)

    register_command(
        IntentCategory.APP_LAUNCH,
        handle_app_launch,
        overwrite=True,
        description="Open desktop applications",
    )
    print("[AUTO] app-launch command registered")
'''

ANCHOR_1 = (
    "        command_router.set_fallback(\n"
    "            self._handle_general_chat\n"
    "        )\n"
)
NEW_1 = ANCHOR_1 + (
    "\n"
    "        try:\n"
    "            from automation.commands import register_automation_commands\n"
    "\n"
    "            register_automation_commands(self._handle_general_chat)\n"
    "        except Exception as exc:\n"
    "            logger.warning(\n"
    "                \"Automation commands unavailable: %s\",\n"
    "                exc,\n"
    "            )\n"
)

ANCHOR_2 = (
    "            config.constants.IntentCategory.APP_LAUNCH: (\n"
    "                \"open\",\n"
    "                \"launch\",\n"
    "                \"start\",\n"
    "            ),\n"
)
NEW_2 = (
    "            config.constants.IntentCategory.APP_LAUNCH: (\n"
    "                \"open\",\n"
    "                \"launch\",\n"
    "                \"start\",\n"
    "                \"খোলো\",\n"
    "                \"খুলো\",\n"
    "                \"খুলুন\",\n"
    "                \"খুলে দাও\",\n"
    "                \"ওপেন\",\n"
    "                \"লঞ্চ\",\n"
    "                \"खोलो\",\n"
    "            ),\n"
)

if not ASSISTANT.exists():
    print("ERROR: core\\assistant.py not found at:", ASSISTANT)
    sys.exit(1)

src = ASSISTANT.read_text(encoding="utf-8")
todo = []

if "automation.commands" not in src:
    if src.count(ANCHOR_1) != 1:
        print("ERROR: spot 1 not found exactly once. Nothing changed.")
        print("count:", src.count(ANCHOR_1))
        sys.exit(1)
    todo.append(1)

if "\"খোলো\"" not in src:
    if src.count(ANCHOR_2) != 1:
        print("ERROR: spot 2 not found exactly once. Nothing changed.")
        print("count:", src.count(ANCHOR_2))
        sys.exit(1)
    todo.append(2)

if not todo:
    print("Already patched. Nothing to do.")
else:
    shutil.copy(ASSISTANT, BACKUP)
    if 1 in todo:
        src = src.replace(ANCHOR_1, NEW_1, 1)
    if 2 in todo:
        src = src.replace(ANCHOR_2, NEW_2, 1)
    ASSISTANT.write_text(src, encoding="utf-8")

    try:
        py_compile.compile(str(ASSISTANT), doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy(BACKUP, ASSISTANT)
        print("ERROR: syntax problem, original restored.")
        print(exc)
        sys.exit(1)
    print("PATCHED core\\assistant.py  (backup: core\\assistant.py.bak)")

COMMANDS.parent.mkdir(parents=True, exist_ok=True)
COMMANDS.write_text(COMMANDS_CODE, encoding="utf-8")
try:
    py_compile.compile(str(COMMANDS), doraise=True)
except py_compile.PyCompileError as exc:
    print("ERROR in automation\\commands.py:", exc)
    sys.exit(1)
print("WROTE   automation\\commands.py")
print("DONE. Now run:  python main.py")


