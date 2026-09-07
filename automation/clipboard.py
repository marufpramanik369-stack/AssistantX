"""
clipboard.py
============
System clipboard read/write access, built on the `pyperclip` package
(lightweight, cross-platform, no GUI-automation dependency needed just
for clipboard text). Falls back to `tkinter`'s clipboard access if
pyperclip isn't installed, since tkinter ships with most Python
installations and can serve as a zero-extra-dependency fallback for
plain text clipboard operations.
"""

from __future__ import annotations

from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)


class ClipboardError(RuntimeError):
    """Raised when clipboard access fails or is unavailable."""


def _try_pyperclip():
    try:
        import pyperclip  # type: ignore

        return pyperclip
    except ImportError:
        return None


def is_available() -> bool:
    """Check whether at least one clipboard backend can be used."""
    if _try_pyperclip() is not None:
        return True
    try:
        import tkinter  # noqa: F401

        return True
    except ImportError:
        return False


def copy_text(text: str) -> bool:
    """Copy `text` to the system clipboard."""
    pyperclip = _try_pyperclip()
    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            logger.debug("Copied %d chars to clipboard via pyperclip.", len(text))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("pyperclip.copy failed (%s); trying tkinter fallback.", exc)

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # required on some platforms to flush the clipboard write
        root.destroy()
        logger.debug("Copied %d chars to clipboard via tkinter fallback.", len(text))
        return True
    except Exception as exc:  # noqa: BLE001
        raise ClipboardError(f"Failed to copy text to clipboard: {exc}") from exc


def paste_text() -> str:
    """Read and return the current text content of the system clipboard."""
    pyperclip = _try_pyperclip()
    if pyperclip is not None:
        try:
            return pyperclip.paste()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pyperclip.paste failed (%s); trying tkinter fallback.", exc)

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            content = root.clipboard_get()
        except tk.TclError:
            content = ""  # clipboard empty or contains non-text data
        root.destroy()
        return content
    except Exception as exc:  # noqa: BLE001
        raise ClipboardError(f"Failed to read clipboard: {exc}") from exc


def clear_clipboard() -> bool:
    """Clear the clipboard contents."""
    return copy_text("")


def has_text() -> bool:
    """Check whether the clipboard currently contains non-empty text."""
    try:
        return bool(paste_text().strip())
    except ClipboardError:
        return False