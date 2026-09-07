"""
keyboard.py
===========
Simulated keyboard input: typing text, pressing individual keys, and
common key combinations (copy/paste/undo/alt-tab, etc). Built on the
optional `pyautogui` package — if it's not installed, every function
here raises a clear KeyboardAutomationError rather than crashing at
import time, so the rest of AssistantX keeps working without this
optional capability.
"""

from __future__ import annotations

import time
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)


class KeyboardAutomationError(RuntimeError):
    """Raised when keyboard automation is unavailable or a simulated action fails."""


def _get_backend():
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True  # moving mouse to a screen corner aborts — safety net
        return pyautogui
    except ImportError as exc:
        raise KeyboardAutomationError(
            "Keyboard automation requires the 'pyautogui' package. Run: pip install pyautogui"
        ) from exc


def is_available() -> bool:
    try:
        _get_backend()
        return True
    except KeyboardAutomationError:
        return False


def type_text(text: str, interval_seconds: float = 0.02) -> bool:
    """
    Simulate typing `text` at the current cursor/focus location.

    Args:
        text: The text to type.
        interval_seconds: Delay between keystrokes — a small nonzero
            value (default) makes typing land reliably in most GUI
            fields; 0 types instantly but can drop characters in some apps.
    """
    pyautogui = _get_backend()
    logger.info("Typing text (%d chars).", len(text))
    try:
        pyautogui.write(text, interval=interval_seconds)
        return True
    except Exception as exc:  # noqa: BLE001
        raise KeyboardAutomationError(f"Failed to type text: {exc}") from exc


def press_key(key: str) -> bool:
    """Press and release a single key, e.g. 'enter', 'esc', 'tab', 'f5'."""
    pyautogui = _get_backend()
    try:
        pyautogui.press(key)
        return True
    except Exception as exc:  # noqa: BLE001
        raise KeyboardAutomationError(f"Failed to press key '{key}': {exc}") from exc


def press_hotkey(*keys: str) -> bool:
    """
    Press a combination of keys simultaneously, e.g.
    press_hotkey('ctrl', 'c') for copy.
    """
    pyautogui = _get_backend()
    try:
        pyautogui.hotkey(*keys)
        return True
    except Exception as exc:  # noqa: BLE001
        raise KeyboardAutomationError(f"Failed to press hotkey {keys}: {exc}") from exc


def hold_key(key: str, duration_seconds: float) -> bool:
    """Hold a key down for a specific duration, then release it."""
    pyautogui = _get_backend()
    try:
        pyautogui.keyDown(key)
        time.sleep(duration_seconds)
        pyautogui.keyUp(key)
        return True
    except Exception as exc:  # noqa: BLE001
        raise KeyboardAutomationError(f"Failed to hold key '{key}': {exc}") from exc


# --------------------------------------------------------------------------- #
# Common shortcut convenience wrappers
# --------------------------------------------------------------------------- #

def copy() -> bool:
    return press_hotkey("ctrl", "c")


def paste() -> bool:
    return press_hotkey("ctrl", "v")


def cut() -> bool:
    return press_hotkey("ctrl", "x")


def undo() -> bool:
    return press_hotkey("ctrl", "z")


def redo() -> bool:
    return press_hotkey("ctrl", "y")


def select_all() -> bool:
    return press_hotkey("ctrl", "a")


def save() -> bool:
    return press_hotkey("ctrl", "s")


def find() -> bool:
    return press_hotkey("ctrl", "f")


def switch_window() -> bool:
    """Alt+Tab to switch to the next window."""
    return press_hotkey("alt", "tab")


def close_window() -> bool:
    return press_hotkey("alt", "f4")


def new_tab() -> bool:
    return press_hotkey("ctrl", "t")


def close_tab() -> bool:
    return press_hotkey("ctrl", "w")


def refresh() -> bool:
    return press_key("f5")


def enter() -> bool:
    return press_key("enter")


def escape() -> bool:
    return press_key("esc")
    