"""
screenshot.py
=============

Professional screenshot automation module for AssistantX.

Features
--------
- Full-screen screenshot
- Region screenshot
- Active-window screenshot
- In-memory screenshot capture
- Automatic screenshot directory
- Custom save path / filename
- Timestamp-based filenames
- Screenshot listing
- Screenshot deletion
- Region validation
- Backend availability detection
- Diagnostics
- Graceful fallback between PyAutoGUI and Pillow

Primary backends
----------------
1. PyAutoGUI
2. Pillow ImageGrab

Optional dependency
-------------------
pygetwindow -> active-window detection

Install:
    pip install pyautogui Pillow pygetwindow
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger(__name__)

@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_SCREENSHOT_DIR_NAME = "AssistantX Screenshots"
DEFAULT_FILENAME_PREFIX = "screenshot"
DEFAULT_REGION_PREFIX = "region"
DEFAULT_ACTIVE_WINDOW_PREFIX = "window"

PNG_EXTENSION = ".png"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class ScreenshotError(RuntimeError):
    """Base exception for screenshot-related errors."""


class ScreenshotBackendError(ScreenshotError):
    """Raised when no screenshot backend is available."""


class ScreenshotValidationError(ScreenshotError):
    """Raised when screenshot parameters are invalid."""


class ScreenshotSaveError(ScreenshotError):
    """Raised when a screenshot cannot be saved."""


# ============================================================================
# DATA MODELS
# ============================================================================


class ScreenshotValidationError(ValueError):
    """Raised when screenshot region validation fails."""


@dataclass(frozen=True, slots=True)
class Region:
    """Rectangular screen region representation.

    Attributes:
        left: X-coordinate of top-left corner.
        top: Y-coordinate of top-left corner.
        width: Width of the region (must be > 0).
        height: Height of the region (must be > 0).
    """

    left: int
    top: int
    width: int
    height: int

    def __init__(
        self,
        left: int | None = None,
        top: int | None = None,
        width: int = 0,
        height: int = 0,
        *,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        """Support initialization via both `left/top` and `x/y` keyword arguments."""
        final_left = left if left is not None else x
        final_top = top if top is not None else y

        if final_left is None or final_top is None:
            raise ScreenshotValidationError(
                "Region requires both X and Y coordinates (e.g., left/top or x/y)."
            )

        object.__setattr__(self, "left", int(final_left))
        object.__setattr__(self, "top", int(final_top))
        object.__setattr__(self, "width", int(width))
        object.__setattr__(self, "height", int(height))

        self._validate()

    def _validate(self) -> None:
        """Validate region dimensions."""
        if self.width <= 0:
            raise ScreenshotValidationError(
                f"Region width must be strictly positive (> 0). Got: {self.width}"
            )
        if self.height <= 0:
            raise ScreenshotValidationError(
                f"Region height must be strictly positive (> 0). Got: {self.height}"
            )

    @property
    def x(self) -> int:
        """Alias for `left` coordinate."""
        return self.left

    @property
    def y(self) -> int:
        """Alias for `top` coordinate."""
        return self.top

    @classmethod
    def from_tuple(cls, bounds: tuple[int, int, int, int]) -> Region:
        """Create Region instance from a 4-element tuple (left, top, width, height)."""
        if len(bounds) != 4:
            raise ScreenshotValidationError(
                f"Tuple bounds must contain exactly 4 integers. Got {len(bounds)} elements."
            )
        return cls(left=bounds[0], top=bounds[1], width=bounds[2], height=bounds[3])

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Return region in PyAutoGUI format: (left, top, width, height)."""
        return (self.left, self.top, self.width, self.height)

    def as_bbox(self) -> tuple[int, int, int, int]:
        """Return region in Pillow/ImageGrab bbox format: (left, top, right, bottom)."""
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def to_dict(self) -> dict[str, int]:
        """Return region dictionary representation."""
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class ScreenshotInfo:
    """Metadata describing a saved screenshot file.

    Attributes:
        path: Saved screenshot absolute file path.
        created_at: Creation timestamp.
        size_bytes: File size in bytes.
    """

    path: Path
    created_at: datetime
    size_bytes: int

    def __post_init__(self) -> None:
        """Ensure path is resolved as Path object and validation checks pass."""
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))

        if self.size_bytes < 0:
            raise ScreenshotValidationError(
                f"File size cannot be negative. Got: {self.size_bytes}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return metadata as a JSON-serializable dictionary."""
        return {
            "path": str(self.path),
            "created_at": self.created_at.isoformat(),
            "size_bytes": self.size_bytes,
        }


# ============================================================================
# DIRECTORY / FILE HELPERS
# ============================================================================


def get_screenshot_directory() -> Path:
    """
    Return AssistantX's default screenshot directory.

    Example:
        ~/Pictures/AssistantX Screenshots/
    """
    directory = (
        Path.home()
        / "Pictures"
        / DEFAULT_SCREENSHOT_DIR_NAME
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory


def _sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for Windows/Linux/macOS compatibility.
    """
    filename = filename.strip()

    if not filename:
        raise ScreenshotValidationError(
            "Screenshot filename cannot be empty."
        )

    invalid_chars = '<>:"/\\|?*'

    for char in invalid_chars:
        filename = filename.replace(char, "_")

    return filename


def _generate_filename(
    prefix: str = DEFAULT_FILENAME_PREFIX,
    extension: str = PNG_EXTENSION,
) -> str:
    """
    Generate a timestamp-based screenshot filename.

    Example:
        screenshot_20260907_221530_123456.png
    """
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    prefix = _sanitize_filename(prefix)

    if not extension.startswith("."):
        extension = f".{extension}"

    return f"{prefix}_{timestamp}{extension}"


def _resolve_save_path(
    save_path: str | Path | None,
    prefix: str,
) -> Path:
    """
    Resolve final screenshot destination.
    """
    if save_path:
        destination = Path(save_path)

        if destination.suffix == "":
            destination = destination.with_suffix(
                PNG_EXTENSION
            )
    else:
        destination = (
            get_screenshot_directory()
            / _generate_filename(prefix)
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    return destination


# ============================================================================
# BACKEND HELPERS
# ============================================================================


def _get_pyautogui() -> Any:
    """
    Lazily import PyAutoGUI.

    Returns:
        pyautogui module

    Raises:
        ScreenshotBackendError
    """
    try:
        import pyautogui  # type: ignore

        return pyautogui

    except ImportError as exc:
        raise ScreenshotBackendError(
            "PyAutoGUI is not installed. "
            "Install it with: pip install pyautogui"
        ) from exc


def _get_imagegrab() -> Any:
    """
    Lazily import Pillow ImageGrab.

    Returns:
        ImageGrab module

    Raises:
        ScreenshotBackendError
    """
    try:
        from PIL import ImageGrab

        return ImageGrab

    except ImportError as exc:
        raise ScreenshotBackendError(
            "Pillow is not installed. "
            "Install it with: pip install Pillow"
        ) from exc


def is_pyautogui_available() -> bool:
    """Return True if PyAutoGUI is installed."""
    try:
        _get_pyautogui()
        return True
    except ScreenshotBackendError:
        return False


def is_pillow_available() -> bool:
    """Return True if Pillow is installed."""
    try:
        _get_imagegrab()
        return True
    except ScreenshotBackendError:
        return False


def is_available() -> bool:
    """
    Return True if at least one screenshot backend is available.
    """
    return (
        is_pyautogui_available()
        or is_pillow_available()
    )


def get_backend() -> str:
    """
    Return the preferred available screenshot backend.

    Returns:
        "pyautogui"
        "pillow"
        "none"
    """
    if is_pyautogui_available():
        return "pyautogui"

    if is_pillow_available():
        return "pillow"

    return "none"


# ============================================================================
# CAPTURE INTERNALS
# ============================================================================


def _capture_fullscreen_image() -> Any:
    """
    Capture the entire screen and return the image object.
    """
    if is_pyautogui_available():
        try:
            pyautogui = _get_pyautogui()
            return pyautogui.screenshot()

        except Exception as exc:
            logger.warning(
                "PyAutoGUI fullscreen capture failed: %s",
                exc,
            )

    if is_pillow_available():
        try:
            imagegrab = _get_imagegrab()
            return imagegrab.grab()

        except Exception as exc:
            raise ScreenshotError(
                f"Pillow fullscreen capture failed: {exc}"
            ) from exc

    raise ScreenshotBackendError(
        "No screenshot backend available. "
        "Install PyAutoGUI or Pillow."
    )


def _capture_region_image(region: Region) -> Any:
    """
    Capture a specific region and return the image object.
    """
    if is_pyautogui_available():
        try:
            pyautogui = _get_pyautogui()

            return pyautogui.screenshot(
                region=region.as_tuple()
            )

        except Exception as exc:
            logger.warning(
                "PyAutoGUI region capture failed: %s",
                exc,
            )

    if is_pillow_available():
        try:
            imagegrab = _get_imagegrab()

            return imagegrab.grab(
                bbox=region.as_bbox()
            )

        except Exception as exc:
            raise ScreenshotError(
                f"Pillow region capture failed: {exc}"
            ) from exc

    raise ScreenshotBackendError(
        "No screenshot backend available."
    )


def _save_image(
    image: Any,
    destination: Path,
) -> Path:
    """
    Save an image safely to disk.
    """
    try:
        image.save(str(destination))

    except (OSError, ValueError) as exc:
        raise ScreenshotSaveError(
            f"Failed to save screenshot to "
            f"'{destination}': {exc}"
        ) from exc

    logger.info(
        "Screenshot saved: %s",
        destination,
    )

    return destination


# ============================================================================
# FULLSCREEN CAPTURE
# ============================================================================


def capture_fullscreen(
    save_path: str | Path | None = None,
) -> Path:
    """
    Capture the entire screen and save it to disk.

    Args:
        save_path:
            Optional destination path.

    Returns:
        Path to saved screenshot.
    """
    destination = _resolve_save_path(
        save_path,
        DEFAULT_FILENAME_PREFIX,
    )

    image = _capture_fullscreen_image()

    return _save_image(
        image,
        destination,
    )


def capture_fullscreen_image() -> Any:
    """
    Capture the entire screen and return the image
    without saving it.

    Useful for:
        - Vision AI
        - OCR
        - Image processing
        - Preview
    """
    return _capture_fullscreen_image()


# ============================================================================
# REGION CAPTURE
# ============================================================================


def capture_region(
    region: Region,
    save_path: str | Path | None = None,
) -> Path:
    """
    Capture a specific screen region.

    Example:
        region = Region(100, 100, 800, 600)
        path = capture_region(region)
    """
    if not isinstance(region, Region):
        raise ScreenshotValidationError(
            "region must be a Region instance."
        )

    destination = _resolve_save_path(
        save_path,
        DEFAULT_REGION_PREFIX,
    )

    image = _capture_region_image(region)

    return _save_image(
        image,
        destination,
    )


def capture_region_image(
    region: Region,
) -> Any:
    """
    Capture a region and return it in memory.
    """
    if not isinstance(region, Region):
        raise ScreenshotValidationError(
            "region must be a Region instance."
        )

    return _capture_region_image(region)


# ============================================================================
# ACTIVE WINDOW
# ============================================================================


def _get_active_window() -> Any:
    """
    Return the currently active window.

    Requires:
        pygetwindow
    """
    try:
        import pygetwindow as gw  # type: ignore

    except ImportError as exc:
        raise ScreenshotBackendError(
            "Active-window capture requires "
            "'pygetwindow'. "
            "Install with: pip install pygetwindow"
        ) from exc

    try:
        window = gw.getActiveWindow()

    except Exception as exc:
        raise ScreenshotError(
            f"Could not detect active window: {exc}"
        ) from exc

    return window


def get_active_window_region() -> Region | None:
    """
    Get the active window's screen region.

    Returns:
        Region or None if no active window exists.
    """
    window = _get_active_window()

    if window is None:
        logger.warning(
            "No active window detected."
        )
        return None

    try:
        left = int(window.left)
        top = int(window.top)
        width = int(window.width)
        height = int(window.height)

    except (AttributeError, TypeError, ValueError) as exc:
        raise ScreenshotError(
            "Active window returned invalid bounds."
        ) from exc

    if width <= 0 or height <= 0:
        logger.warning(
            "Active window has invalid dimensions: "
            "%sx%s",
            width,
            height,
        )
        return None

    return Region(
        left=left,
        top=top,
        width=width,
        height=height,
    )


def capture_active_window(
    save_path: str | Path | None = None,
) -> Path:
    """
    Capture the currently active window.

    If active-window detection is unavailable,
    falls back to fullscreen capture.
    """
    try:
        region = get_active_window_region()

    except ScreenshotBackendError:
        logger.warning(
            "pygetwindow unavailable. "
            "Falling back to fullscreen screenshot."
        )

        destination = _resolve_save_path(
            save_path,
            DEFAULT_ACTIVE_WINDOW_PREFIX,
        )

        return capture_fullscreen(
            destination
        )

    if region is None:
        logger.warning(
            "Active window unavailable. "
            "Falling back to fullscreen."
        )

        destination = _resolve_save_path(
            save_path,
            DEFAULT_ACTIVE_WINDOW_PREFIX,
        )

        return capture_fullscreen(
            destination
        )

    destination = _resolve_save_path(
        save_path,
        DEFAULT_ACTIVE_WINDOW_PREFIX,
    )

    return capture_region(
        region,
        destination,
    )


# ============================================================================
# QUICK SCREENSHOT FUNCTIONS
# ============================================================================


def screenshot(
    save_path: str | Path | None = None,
) -> Path:
    """
    Shortcut for capture_fullscreen().
    """
    return capture_fullscreen(save_path)


def screenshot_region(
    left: int,
    top: int,
    width: int,
    height: int,
    save_path: str | Path | None = None,
) -> Path:
    """
    Capture a region using direct coordinates.
    """
    region = Region(
        left=left,
        top=top,
        width=width,
        height=height,
    )

    return capture_region(
        region,
        save_path,
    )


def screenshot_active_window(
    save_path: str | Path | None = None,
) -> Path:
    """
    Shortcut for capture_active_window().
    """
    return capture_active_window(
        save_path
    )

    # UPDATED 


def safe_capture_active_window(
    save_path: str | Path | None = None,
) -> Path | None:
    """Safely capture the currently active window without raising exceptions.

    Falls back to fullscreen capture if active window detection fails.

    Args:
        save_path: Optional path where the screenshot should be saved.

    Returns:
        Optional[Path]: Path to saved screenshot, or None if capture fails completely.
    """
    try:
        return capture_active_window(save_path=save_path)
    except Exception as exc:
        logger.warning(
            "Failed to capture active window: %s. Attempting fallback to fullscreen.",
            exc,
        )
        try:
            return capture_fullscreen(save_path=save_path)
        except Exception as fallback_exc:
            logger.error("Fullscreen fallback capture also failed: %s", fallback_exc)
            return None

# UPDATED 

def safe_capture_fullscreen(
    save_path: str | Path | None = None,
) -> Path | None:
    """Safely capture the entire screen without raising exceptions.

    Args:
        save_path: Optional destination file path.

    Returns:
        Optional[Path]: Path to saved screenshot if successful, None otherwise.
    """
    try:
        return capture_fullscreen(save_path=save_path)
    except Exception as exc:
        logger.error("Failed to capture fullscreen screenshot: %s", exc, exc_info=True)
        return None


def safe_capture_region(
    region: Region,
    save_path: str | Path | None = None,
) -> Path | None:
    """Safely capture a specific screen region without raising exceptions.

    Args:
        region: Region instance specifying coordinates and dimensions.
        save_path: Optional destination file path.

    Returns:
        Optional[Path]: Path to saved screenshot if successful, None otherwise.
    """
    try:
        return capture_region(region=region, save_path=save_path)
    except Exception as exc:
        logger.error("Failed to capture region screenshot: %s", exc, exc_info=True)
        return None

# ============================================================================
# SCREENSHOT MANAGEMENT
# ============================================================================


def list_saved_screenshots(
    limit: int = 20,
) -> list[Path]:
    """
    Return recently saved screenshots.

    Args:
        limit:
            Maximum number of results.
    """
    if limit <= 0:
        return []

    directory = get_screenshot_directory()

    files = sorted(
        directory.glob("*.png"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    return files[:limit]

# UPDATED 


def list_screenshots(
    limit: int | None = 20,
) -> list[Path]:
    """Safely list recently saved screenshots sorted by creation time.

    Serves as a resilient public wrapper around `list_saved_screenshots`.
    Handles invalid limits gracefully and catches filesystem execution errors.

    Args:
        limit: Maximum number of recent screenshots to retrieve. Pass None or 0 
               to retrieve all. Defaults to 20.

    Returns:
        list[Path]: List of Path objects pointing to existing screenshot files.
    """
    if limit is not None and limit < 0:
        logger.warning("Invalid limit passed to list_screenshots: %s. Defaulting to 20.", limit)
        limit = 20

    try:
        if limit is None or limit == 0:
            return list_saved_screenshots(limit=999_999)
        return list_saved_screenshots(limit=limit)
    except Exception as exc:
        logger.error("Failed to list screenshots: %s", exc, exc_info=True)
        return []


def get_screenshot_info(
    path: str | Path,
) -> ScreenshotInfo:
    """
    Return metadata for a saved screenshot.
    """
    screenshot_path = Path(path)

    if not screenshot_path.exists():
        raise ScreenshotError(
            f"Screenshot does not exist: {screenshot_path}"
        )

    if not screenshot_path.is_file():
        raise ScreenshotError(
            f"Path is not a file: {screenshot_path}"
        )

    stat = screenshot_path.stat()

    return ScreenshotInfo(
        path=screenshot_path,
        created_at=datetime.fromtimestamp(
            stat.st_mtime
        ),
        size_bytes=stat.st_size,
    )


def delete_screenshot(
    path: str | Path,
) -> bool:
    """
    Delete a screenshot from disk.

    Returns:
        True if deleted successfully.
    """
    screenshot_path = Path(path)

    if not screenshot_path.exists():
        logger.warning(
            "Screenshot not found: %s",
            screenshot_path,
        )
        return False

    try:
        screenshot_path.unlink()

    except OSError as exc:
        raise ScreenshotError(
            f"Failed to delete screenshot "
            f"'{screenshot_path}': {exc}"
        ) from exc

    logger.info(
        "Screenshot deleted: %s",
        screenshot_path,
    )

    return True


def clear_saved_screenshots() -> int:
    """
    Delete all PNG screenshots from the default
    AssistantX screenshot directory.

    Returns:
        Number of deleted screenshots.
    """
    directory = get_screenshot_directory()

    count = 0

    for screenshot_file in directory.glob("*.png"):
        try:
            screenshot_file.unlink()
            count += 1

        except OSError as exc:
            logger.warning(
                "Could not delete %s: %s",
                screenshot_file,
                exc,
            )

    logger.info(
        "Cleared %d screenshots.",
        count,
    )

    return count


# ============================================================================
# SCREEN INFORMATION
# ============================================================================


def get_screen_size() -> tuple[int, int]:
    """
    Return primary screen size.

    Returns:
        (width, height)
    """
    if is_pyautogui_available():
        try:
            pyautogui = _get_pyautogui()

            width, height = pyautogui.size()

            return int(width), int(height)

        except Exception as exc:
            logger.warning(
                "Could not get screen size via PyAutoGUI: %s",
                exc,
            )

    if is_pillow_available():
        try:
            image = _capture_fullscreen_image()

            return image.size

        except Exception as exc:
            raise ScreenshotError(
                f"Could not determine screen size: {exc}"
            ) from exc

    raise ScreenshotBackendError(
        "No screenshot backend available."
    )


# ============================================================================
# DIAGNOSTICS
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return screenshot subsystem diagnostics.
    """
    pygetwindow_available = False

    try:
        import pygetwindow  # noqa: F401

        pygetwindow_available = True

    except ImportError:
        pass

    return {
        "available": is_available(),
        "backend": get_backend(),
        "pyautogui": is_pyautogui_available(),
        "pillow": is_pillow_available(),
        "pygetwindow": pygetwindow_available,
        "screenshot_directory": str(
            get_screenshot_directory()
        ),
    }


# ============================================================================
# PUBLIC API
# ============================================================================


__all__ = [
    # Exceptions
    "ScreenshotError",
    "ScreenshotBackendError",
    "ScreenshotValidationError",
    "ScreenshotSaveError",

    # Data models
    "Region",
    "ScreenshotInfo",
    "CacheRecord",

    # Availability
    "is_available",
    "is_pyautogui_available",
    "is_pillow_available",
    "get_backend",

    # Direct capture
    "capture_fullscreen",
    "capture_fullscreen_image",
    "capture_region",
    "capture_region_image",
    "capture_active_window",

    # Shortcuts
    "screenshot",
    "screenshot_region",
    "screenshot_active_window",
    "safe_capture_active_window",
    "safe_capture_fullscreen",
    "safe_capture_region",

    # Active window
    "get_active_window_region",

    # Screen info
    "get_screen_size",

    # File management
    "get_screenshot_directory",
    "list_saved_screenshots",
    "list_screenshots",
    "get_screenshot_info",
    "delete_screenshot",
    "clear_saved_screenshots",

    # Diagnostics
    "diagnostics",
]

