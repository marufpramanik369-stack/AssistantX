"""
mouse.py
========
Simulated mouse input: moving the cursor, clicking, dragging, and
scrolling. Like keyboard.py, this is built on the optional `pyautogui`
package and degrades to a clear error (rather than an import crash) if
that package isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)


class MouseAutomationError(RuntimeError):
    """Raised when mouse automation is unavailable or a simulated action fails."""


@dataclass(frozen=True)
class Point:
    x: int
    y: int


def _get_backend():
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        return pyautogui
    except ImportError as exc:
        raise MouseAutomationError(
            "Mouse automation requires the 'pyautogui' package. Run: pip install pyautogui"
        ) from exc


def is_available() -> bool:
    try:
        _get_backend()
        return True
    except MouseAutomationError:
        return False


def get_position() -> Point:
    """Return the current mouse cursor position."""
    pyautogui = _get_backend()
    pos = pyautogui.position()
    return Point(x=pos.x, y=pos.y)


def get_screen_size() -> Point:
    """Return the primary screen's resolution (width, height)."""
    pyautogui = _get_backend()
    size = pyautogui.size()
    return Point(x=size.width, y=size.height)


def move_to(x: int, y: int, duration_seconds: float = 0.2) -> bool:
    """Move the cursor to an absolute screen position, with a brief
    animated glide (duration_seconds) so the motion is visible/natural
    rather than an instant teleport, which some apps mis-handle."""
    pyautogui = _get_backend()
    try:
        pyautogui.moveTo(x, y, duration=duration_seconds)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to move mouse to ({x}, {y}): {exc}") from exc


def move_relative(dx: int, dy: int, duration_seconds: float = 0.2) -> bool:
    """Move the cursor relative to its current position."""
    pyautogui = _get_backend()
    try:
        pyautogui.moveRel(dx, dy, duration=duration_seconds)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to move mouse by ({dx}, {dy}): {exc}") from exc


def click(x: Optional[int] = None, y: Optional[int] = None, button: str = "left", clicks: int = 1) -> bool:
    """
    Click at a position (or the current cursor location if x/y are
    omitted). `button` is one of 'left', 'right', 'middle'.
    """
    pyautogui = _get_backend()
    try:
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to click: {exc}") from exc


def double_click(x: Optional[int] = None, y: Optional[int] = None) -> bool:
    pyautogui = _get_backend()
    try:
        pyautogui.doubleClick(x=x, y=y)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to double-click: {exc}") from exc


def right_click(x: Optional[int] = None, y: Optional[int] = None) -> bool:
    return click(x=x, y=y, button="right")


def drag_to(x: int, y: int, duration_seconds: float = 0.4, button: str = "left") -> bool:
    """Click-and-drag from the current cursor position to (x, y)."""
    pyautogui = _get_backend()
    try:
        pyautogui.dragTo(x, y, duration=duration_seconds, button=button)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to drag to ({x}, {y}): {exc}") from exc


def scroll(amount: int) -> bool:
    """
    Scroll the mouse wheel. Positive values scroll up, negative scroll
    down (matching pyautogui's convention).
    """
    pyautogui = _get_backend()
    try:
        pyautogui.scroll(amount)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to scroll: {exc}") from exc


def scroll_horizontal(amount: int) -> bool:
    """Horizontal scroll where supported by the OS/app (less universally
    supported than vertical scroll)."""
    pyautogui = _get_backend()
    try:
        pyautogui.hscroll(amount)
        return True
    except Exception as exc:  # noqa: BLE001
        raise MouseAutomationError(f"Failed to horizontal-scroll: {exc}") from exc
        