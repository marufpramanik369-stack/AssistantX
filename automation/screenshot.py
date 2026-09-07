"""
screenshot.py
=============
Screen capture: full-screen, region, and active-window screenshots,
saved to disk (default: user's Pictures/AssistantX Screenshots folder)
or returned in-memory for further processing (e.g. handing to a vision
model in a future feature).

Built primarily on `pyautogui` (which itself uses Pillow under the
hood), with Pillow's ImageGrab used directly where it offers more
control (e.g. specific region capture).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SCREENSHOT_DIR_NAME = "AssistantX Screenshots"


class ScreenshotError(RuntimeError):
    """Raised when screenshot capture fails or required libraries are missing."""


@dataclass(frozen=True)
class Region:
    """A rectangular screen region: (left, top, width, height)."""

    left: int
    top: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)


def _default_screenshot_dir() -> Path:
    directory = Path.home() / "Pictures" / _DEFAULT_SCREENSHOT_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _generate_filename(prefix: str = "screenshot") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.png"


def is_available() -> bool:
    try:
        import pyautogui  # noqa: F401

        return True
    except ImportError:
        try:
            from PIL import ImageGrab  # noqa: F401

            return True
        except ImportError:
            return False


def capture_fullscreen(save_path: Optional[str] = None) -> Path:
    """
    Capture the entire primary screen and save it to disk.

    Args:
        save_path: Full destination path. If omitted, saves to
            ~/Pictures/AssistantX Screenshots/ with an auto-generated
            timestamped filename.

    Returns:
        The Path where the screenshot was saved.
    """
    destination = Path(save_path) if save_path else (_default_screenshot_dir() / _generate_filename())
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pyautogui  # type: ignore

        image = pyautogui.screenshot()
    except ImportError:
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab()
        except ImportError as exc:
            raise ScreenshotError(
                "Screenshot capture requires 'pyautogui' or 'Pillow'. "
                "Run: pip install pyautogui Pillow"
            ) from exc

    try:
        image.save(str(destination))
    except OSError as exc:
        raise ScreenshotError(f"Failed to save screenshot to '{destination}': {exc}") from exc

    logger.info("Screenshot saved: %s", destination)
    return destination


def capture_region(region: Region, save_path: Optional[str] = None) -> Path:
    """Capture a specific rectangular region of the screen."""
    destination = Path(save_path) if save_path else (_default_screenshot_dir() / _generate_filename("region"))
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pyautogui  # type: ignore

        image = pyautogui.screenshot(region=region.as_tuple())
    except ImportError:
        try:
            from PIL import ImageGrab

            left, top, width, height = region.as_tuple()
            bbox = (left, top, left + width, top + height)
            image = ImageGrab.grab(bbox=bbox)
        except ImportError as exc:
            raise ScreenshotError(
                "Screenshot capture requires 'pyautogui' or 'Pillow'. "
                "Run: pip install pyautogui Pillow"
            ) from exc

    try:
        image.save(str(destination))
    except OSError as exc:
        raise ScreenshotError(f"Failed to save region screenshot to '{destination}': {exc}") from exc

    logger.info("Region screenshot saved: %s (region=%s)", destination, region)
    return destination


def capture_active_window(save_path: Optional[str] = None) -> Path:
    """
    Capture only the currently focused/active window, where the
    platform supports identifying its bounds. Falls back to a
    full-screen capture with a logged warning if window-bounds
    detection isn't available (this varies significantly by platform
    and installed libraries).
    """
    try:
        import pygetwindow as gw  # type: ignore

        active = gw.getActiveWindow()
        if active is None:
            logger.warning("No active window detected; falling back to full-screen capture.")
            return capture_fullscreen(save_path)

        region = Region(left=active.left, top=active.top, width=active.width, height=active.height)
        return capture_region(region, save_path=save_path)

    except ImportError:
        logger.warning(
            "Active-window screenshot requires 'pygetwindow'. Falling back to full-screen capture. "
            "Run: pip install pygetwindow"
        )
        return capture_fullscreen(save_path)


def list_saved_screenshots(limit: int = 20) -> list[Path]:
    """Return the most recently saved screenshots from the default directory."""
    directory = _default_screenshot_dir()
    files = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]
    