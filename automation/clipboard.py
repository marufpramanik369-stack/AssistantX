"""
automation/clipboard.py
=======================

Professional system clipboard automation for AssistantX.

Features:
    - Copy text to system clipboard
    - Read/paste text from clipboard
    - Clear clipboard
    - Check text availability
    - Multiple clipboard backends
    - pyperclip primary backend
    - tkinter fallback backend
    - Backend diagnostics
    - Safe wrappers
    - Input validation
    - Logging

The module is intentionally focused on plain-text clipboard operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyperclip

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_MAX_TEXT_LENGTH = 1_000_000

BACKEND_PYPERCLIP = "pyperclip"
BACKEND_TKINTER = "tkinter"

SUPPORTED_BACKENDS = (
    BACKEND_PYPERCLIP,
    BACKEND_TKINTER,
)


# ============================================================================
# Exceptions
# ============================================================================


class ClipboardError(RuntimeError):
    """Base exception for clipboard operations."""


class ClipboardValidationError(ClipboardError):
    """Raised when clipboard input is invalid."""


class ClipboardBackendError(ClipboardError):
    """Raised when a clipboard backend is unavailable or fails."""


class ClipboardReadError(ClipboardError):
    """Raised when clipboard content cannot be read."""


class ClipboardWriteError(ClipboardError):
    """Raised when clipboard content cannot be written."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class ClipboardInfo:
    """Information about the clipboard backend and current text."""

    available: bool
    backend: str | None
    has_text: bool
    text_length: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "backend": self.backend,
            "has_text": self.has_text,
            "text_length": self.text_length,
        }


# ============================================================================
# Backend Helpers
# ============================================================================


def _try_pyperclip():
    """
    Lazily import pyperclip.

    Returns:
        pyperclip module or None.
    """
    try:
        import pyperclip  # type: ignore

        return pyperclip
    except ImportError:
        return None


def _try_tkinter():
    """
    Lazily import tkinter.

    Returns:
        tkinter module or None.
    """
    try:
        import tkinter as tk

        return tk
    except ImportError:
        return None


def _pyperclip_available() -> bool:
    """Check whether pyperclip can be imported."""
    return _try_pyperclip() is not None


def _tkinter_available() -> bool:
    """Check whether tkinter can be imported."""
    return _try_tkinter() is not None


def get_available_backends() -> list[str]:
    """Return all clipboard backends that are importable."""
    backends: list[str] = []

    if _pyperclip_available():
        backends.append(BACKEND_PYPERCLIP)

    if _tkinter_available():
        backends.append(BACKEND_TKINTER)

    return backends


def is_available() -> bool:
    """
    Return True if at least one clipboard backend is available.
    """
    return bool(get_available_backends())


def get_backend_name() -> str | None:
    """
    Return the preferred available backend.

    pyperclip is preferred because it does not require creating
    a temporary GUI root.
    """
    if _pyperclip_available():
        return BACKEND_PYPERCLIP

    if _tkinter_available():
        return BACKEND_TKINTER

    return None


# ============================================================================
# Validation
# ============================================================================


def _validate_text(text: str) -> str:
    """Validate clipboard text."""
    if text is None:
        raise ClipboardValidationError(
            "Clipboard text cannot be None."
        )

    if not isinstance(text, str):
        raise ClipboardValidationError(
            "Clipboard content must be a string."
        )

    if len(text) > DEFAULT_MAX_TEXT_LENGTH:
        raise ClipboardValidationError(
            f"Clipboard text exceeds the maximum allowed length "
            f"of {DEFAULT_MAX_TEXT_LENGTH:,} characters."
        )

    return text


def _validate_max_length(max_length: int) -> int:
    """Validate a maximum text length."""
    if not isinstance(max_length, int) or isinstance(max_length, bool):
        raise ClipboardValidationError(
            "max_length must be an integer."
        )

    if max_length <= 0:
        raise ClipboardValidationError(
            "max_length must be greater than zero."
        )

    return max_length


# ============================================================================
# Tkinter Backend
# ============================================================================


def _tk_copy(text: str) -> bool:
    """Copy text using tkinter."""
    tk = _try_tkinter()

    if tk is None:
        raise ClipboardBackendError(
            "tkinter is not available."
        )

    root = None

    try:
        root = tk.Tk()
        root.withdraw()

        root.clipboard_clear()
        root.clipboard_append(text)

        # Keep clipboard data available after tkinter exits.
        root.update()

        logger.debug(
            "Copied %d characters using tkinter.",
            len(text),
        )

        return True

    except Exception as exc:
        raise ClipboardWriteError(
            f"tkinter clipboard write failed: {exc}"
        ) from exc

    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError as exc:                                      # UPDATED
                logger.debug("Failed to destroy tkinter root: %s", exc)


def _tk_paste() -> str:
    """Read clipboard text using tkinter."""
    tk = _try_tkinter()

    if tk is None:
        raise ClipboardBackendError(
            "tkinter is not available."
        )

    root = None

    try:
        root = tk.Tk()
        root.withdraw()

        try:
            content = root.clipboard_get()
        except tk.TclError:
            # Clipboard may be empty or contain non-text data.
            content = ""

        if not isinstance(content, str):
            content = str(content)

        return content

    except Exception as exc:
        raise ClipboardReadError(
            f"tkinter clipboard read failed: {exc}"
        ) from exc

    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001, S110
                pass


# ============================================================================
# Pyperclip Backend
# ============================================================================


def _pyperclip_copy(text: str) -> bool:
    """Copy text using pyperclip."""
    pyperclip = _try_pyperclip()

    if pyperclip is None:
        raise ClipboardBackendError(
            "pyperclip is not installed."
        )

    try:
        pyperclip.copy(text)

        logger.debug(
            "Copied %d characters using pyperclip.",
            len(text),
        )

        return True

    except Exception as exc:
        raise ClipboardWriteError(
            f"pyperclip clipboard write failed: {exc}"
        ) from exc


def _pyperclip_paste() -> str:
    """Read clipboard text using pyperclip."""
    pyperclip = _try_pyperclip()

    if pyperclip is None:
        raise ClipboardBackendError(
            "pyperclip is not installed."
        )

    try:
        content = pyperclip.paste()

        if content is None:
            return ""

        return str(content)

    except Exception as exc:
        raise ClipboardReadError(
            f"pyperclip clipboard read failed: {exc}"
        ) from exc


# ============================================================================
# Core Operations
# ============================================================================


def copy_text(
    text: str,
    *,
    backend: str | None = None,
) -> bool:
    """
    Copy text to the system clipboard.

    Args:
        text: Text to copy.
        backend: Optional backend name.

    Returns:
        True when successful.
    """
    text = _validate_text(text)

    selected_backend = backend or get_backend_name()

    if selected_backend not in SUPPORTED_BACKENDS:
        raise ClipboardBackendError(
            "No supported clipboard backend is available."
        )

    if selected_backend == BACKEND_PYPERCLIP:
        try:
            return _pyperclip_copy(text)
        except ClipboardError as exc:
            logger.warning(
                "pyperclip copy failed: %s; trying tkinter fallback.",
                exc,
            )

            if _tkinter_available():
                return _tk_copy(text)

            raise

    if selected_backend == BACKEND_TKINTER:
        return _tk_copy(text)

    raise ClipboardBackendError(
        f"Unsupported clipboard backend: {selected_backend}"
    )


def paste_text(
    *,
    backend: str | None = None,
    max_length: int | None = None,
) -> str:
    """
    Read text from the system clipboard.

    Args:
        backend: Optional backend name.
        max_length: Optional maximum number of returned characters.

    Returns:
        Clipboard text.
    """
    if max_length is not None:
        max_length = _validate_max_length(max_length)

    selected_backend = backend or get_backend_name()

    if selected_backend not in SUPPORTED_BACKENDS:
        raise ClipboardBackendError(
            "No supported clipboard backend is available."
        )

    content = ""

    if selected_backend == BACKEND_PYPERCLIP:
        try:
            content = _pyperclip_paste()

        except ClipboardError as exc:
            logger.warning(
                "pyperclip paste failed: %s; trying tkinter fallback.",
                exc,
            )

            if _tkinter_available():
                content = _tk_paste()
            else:
                raise

    elif selected_backend == BACKEND_TKINTER:
        content = _tk_paste()

    else:
        raise ClipboardBackendError(
            f"Unsupported clipboard backend: {selected_backend}"
        )

    if max_length is not None and len(content) > max_length:
        return (
            content[:max_length]
            + "\n...[truncated by AssistantX]"
        )

    return content


def clear_clipboard(
    *,
    backend: str | None = None,
) -> bool:
    """Clear the system clipboard."""
    return copy_text(
        "",
        backend=backend,
    )


def has_text(
    *,
    backend: str | None = None,
) -> bool:
    """
    Return True if clipboard contains non-empty text.
    """
    try:
        return bool(
            paste_text(backend=backend).strip()
        )
    except ClipboardError as exc:
        logger.debug(
            "Unable to determine clipboard text state: %s",
            exc,
        )
        return False


# ============================================================================
# Additional Convenience Operations
# ============================================================================


def get_text_length(
    *,
    backend: str | None = None,
) -> int:
    """Return the number of characters currently in the clipboard."""
    return len(
        paste_text(backend=backend)
    )


def get_preview(
    max_length: int = 200,
    *,
    backend: str | None = None,
) -> str:
    """
    Return a short clipboard preview.

    Useful for AssistantX UI/logging without dumping large clipboard
    contents.
    """
    max_length = _validate_max_length(max_length)

    text = paste_text(backend=backend)

    if len(text) <= max_length:
        return text

    return (
        text[:max_length]
        + "..."
    )


def get_clipboard_info(
    *,
    backend: str | None = None,
) -> ClipboardInfo:
    """Return structured information about the clipboard."""
    selected_backend = backend or get_backend_name()

    if selected_backend not in SUPPORTED_BACKENDS:
        return ClipboardInfo(
            available=False,
            backend=None,
            has_text=False,
            text_length=0,
        )

    try:
        text = paste_text(
            backend=selected_backend,
        )

        return ClipboardInfo(
            available=True,
            backend=selected_backend,
            has_text=bool(text.strip()),
            text_length=len(text),
        )

    except ClipboardError as exc:
        logger.debug(
            "Could not inspect clipboard: %s",
            exc,
        )

        return ClipboardInfo(
            available=True,
            backend=selected_backend,
            has_text=False,
            text_length=0,
        )


# ============================================================================
# Safe Wrappers
# ============================================================================


def safe_copy_text(
    text: str,
    *,
    backend: str | None = None,
) -> bool:
    """
    Copy text without propagating ClipboardError.
    """
    try:
        return copy_text(
            text,
            backend=backend,
        )
    except ClipboardError as exc:
        logger.warning(
            "safe_copy_text failed: %s",
            exc,
        )
        return False


def safe_paste_text(
    *,
    backend: str | None = None,
    max_length: int | None = None,
) -> str | None:
    """
    Read clipboard without propagating ClipboardError.
    """
    try:
        return paste_text(
            backend=backend,
            max_length=max_length,
        )
    except ClipboardError as exc:
        logger.warning(
            "safe_paste_text failed: %s",
            exc,
        )
        return None


def safe_clear_clipboard(
    *,
    backend: str | None = None,
) -> bool:
    """Clear clipboard without propagating ClipboardError."""
    try:
        return clear_clipboard(
            backend=backend,
        )
    except ClipboardError as exc:
        logger.warning(
            "safe_clear_clipboard failed: %s",
            exc,
        )
        return False


# ============================================================================
# Diagnostics
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return clipboard subsystem diagnostics.
    """
    available_backends = get_available_backends()

    info = get_clipboard_info()

    return {
        "module": "automation.clipboard",
        "available": bool(available_backends),
        "preferred_backend": get_backend_name(),
        "available_backends": available_backends,
        "supported_backends": list(SUPPORTED_BACKENDS),
        "clipboard": info.to_dict(),
        "max_text_length": DEFAULT_MAX_TEXT_LENGTH,
    }


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "BACKEND_PYPERCLIP",
    "BACKEND_TKINTER",
    "DEFAULT_MAX_TEXT_LENGTH",
    "SUPPORTED_BACKENDS",
    "ClipboardBackendError",
    "ClipboardError",
    "ClipboardInfo",
    "ClipboardReadError",
    "ClipboardValidationError",
    "ClipboardWriteError",
    "clear_clipboard",
    "copy_text",
    "diagnostics",
    "get_available_backends",
    "get_backend_name",
    "get_clipboard_info",
    "get_preview",
    "get_text_length",
    "has_text",
    "is_available",
    "paste_text",
    "pyperclip",
    "safe_clear_clipboard",
    "safe_copy_text",
    "safe_paste_text",
]
