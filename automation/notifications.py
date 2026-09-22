"""
notifications.py
================

Cross-platform native desktop notification system for AssistantX.

Features
--------
- Windows notifications
- macOS notifications
- Linux notifications
- Plyer backend
- Platform-native fallbacks
- NotificationRequest dataclass
- Custom icons
- Timeout validation
- Safe text handling
- Backend detection
- Diagnostics
- Reminder/error/success/info helpers
- Non-blocking notification support

Backends
--------
Primary:
    plyer

Windows fallback:
    win10toast

macOS fallback:
    osascript

Linux fallback:
    notify-send

Used by:
    core/scheduler.py
    core/assistant.py
    dashboard/
    services/
    automation/
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.constants import (
    APP_NAME,
    ICONS_DIR,
    IS_LINUX,
    IS_MAC,
    IS_WINDOWS,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_TIMEOUT_SECONDS = 8
REMINDER_TIMEOUT_SECONDS = 15
ERROR_TIMEOUT_SECONDS = 10
SUCCESS_TIMEOUT_SECONDS = 6
INFO_TIMEOUT_SECONDS = 6
WARNING_TIMEOUT_SECONDS = 8

DEFAULT_ICON_PATH = ICONS_DIR / "app.ico"

MAX_TITLE_LENGTH = 256
MAX_MESSAGE_LENGTH = 2048

SUPPORTED_PLATFORMS = (
    "windows",
    "macos",
    "linux",
)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class NotificationError(RuntimeError):
    """Base exception for notification failures."""


class NotificationValidationError(NotificationError):
    """Raised when notification input is invalid."""


class NotificationBackendError(NotificationError):
    """Raised when no notification backend is available."""


# ============================================================================
# DATA MODELS
# ============================================================================


@dataclass(frozen=True)
class NotificationRequest:
    """
    Immutable notification request.

    Attributes:
        title:
            Notification title.

        message:
            Notification body.

        timeout_seconds:
            How long the notification should remain visible.

        icon_path:
            Optional path to an icon.
    """

    title: str
    message: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    icon_path: str | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        message = self.message.strip()

        if not title:
            raise NotificationValidationError(
                "Notification title cannot be empty."
            )

        if not message:
            raise NotificationValidationError(
                "Notification message cannot be empty."
            )

        if len(title) > MAX_TITLE_LENGTH:
            raise NotificationValidationError(
                f"Notification title is too long. "
                f"Maximum: {MAX_TITLE_LENGTH} characters."
            )

        if len(message) > MAX_MESSAGE_LENGTH:
            raise NotificationValidationError(
                f"Notification message is too long. "
                f"Maximum: {MAX_MESSAGE_LENGTH} characters."
            )

        if self.timeout_seconds <= 0:
            raise NotificationValidationError(
                "timeout_seconds must be greater than 0."
            )


# ============================================================================
# TEXT / PATH HELPERS
# ============================================================================


def _clean_text(value: str) -> str:
    """Normalize notification text."""
    return " ".join(str(value).strip().split())


def _resolve_icon_path(
    icon_path: str | None,
) -> str | None:
    """
    Resolve the icon path.

    Priority:
        1. Explicit icon path
        2. AssistantX default icon
        3. None
    """
    if icon_path:
        path = Path(icon_path).expanduser()

        if path.exists() and path.is_file():
            return str(path)

        logger.debug(
            "Notification icon does not exist: %s",
            path,
        )

    if DEFAULT_ICON_PATH.exists():
        return str(DEFAULT_ICON_PATH)

    return None


def _prepare_request(
    title: str,
    message: str,
    timeout_seconds: int,
    icon_path: str | None,
) -> NotificationRequest:
    """Create a validated notification request."""
    return NotificationRequest(
        title=_clean_text(title),
        message=_clean_text(message),
        timeout_seconds=int(timeout_seconds),
        icon_path=_resolve_icon_path(icon_path),
    )


# ============================================================================
# PLYER BACKEND
# ============================================================================


def _try_plyer(
    request: NotificationRequest,
) -> bool:
    """
    Try showing notification using Plyer.
    """
    try:
        from plyer import notification  # type: ignore

    except ImportError:
        logger.debug(
            "Plyer is not installed."
        )
        return False

    try:
        notification.notify(
            title=request.title,
            message=request.message,
            app_name=APP_NAME,
            timeout=request.timeout_seconds,
            app_icon=request.icon_path or "",
        )

        logger.debug(
            "Notification displayed through Plyer."
        )

        return True

    except Exception as exc:
        logger.debug(
            "Plyer notification failed: %s",
            exc,
        )

        return False


# ============================================================================
# WINDOWS BACKEND
# ============================================================================


def _try_windows_native(
    request: NotificationRequest,
) -> bool:
    """
    Try Windows notification using win10toast.
    """
    if not IS_WINDOWS:
        return False

    try:
        from win10toast import ToastNotifier  # type: ignore

    except ImportError:
        logger.debug(
            "win10toast is not installed."
        )
        return False

    try:
        toaster = ToastNotifier()

        toaster.show_toast(
            title=request.title,
            msg=request.message,
            duration=request.timeout_seconds,
            threaded=True,
            icon_path=request.icon_path,
        )

        logger.debug(
            "Notification displayed through win10toast."
        )

        return True

    except Exception as exc:
        logger.debug(
            "Windows native notification failed: %s",
            exc,
        )

        return False


# ============================================================================
# MACOS BACKEND
# ============================================================================


def _escape_applescript_text(
    value: str,
) -> str:
    """
    Escape text for AppleScript string literals.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def _try_mac_native(
    request: NotificationRequest,
) -> bool:
    """
    Try macOS Notification Center using osascript.
    """
    if not IS_MAC:
        return False

    title = _escape_applescript_text(
        request.title
    )

    message = _escape_applescript_text(
        request.message
    )

    script = (
        f'display notification "{message}" '
        f'with title "{title}"'
    )

    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                script,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        logger.debug(
            "Notification displayed through macOS osascript."
        )

        return True

    except (
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        logger.debug(
            "macOS notification failed: %s",
            exc,
        )

        return False


# ============================================================================
# LINUX BACKEND
# ============================================================================


def _try_linux_native(
    request: NotificationRequest,
) -> bool:
    """
    Try Linux notification using notify-send.
    """
    if not IS_LINUX:
        return False

    if shutil.which("notify-send") is None:
        logger.debug(
            "Linux 'notify-send' command is unavailable."
        )

        return False

    command = [
        "notify-send",
        request.title,
        request.message,
        "-t",
        str(request.timeout_seconds * 1000),
    ]

    if request.icon_path:
        command.extend(
            [
                "-i",
                request.icon_path,
            ]
        )

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )

        logger.debug(
            "Notification displayed through notify-send."
        )

        return True

    except (
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        logger.debug(
            "Linux notification failed: %s",
            exc,
        )

        return False


# ============================================================================
# BACKEND AVAILABILITY
# ============================================================================


def is_plyer_available() -> bool:
    """Return True if Plyer can be imported."""
    try:
        from plyer import notification  # noqa: F401

        return True

    except ImportError:
        return False


def is_win10toast_available() -> bool:
    """Return True if win10toast can be imported."""
    if not IS_WINDOWS:
        return False

    try:
        from win10toast import ToastNotifier  # noqa: F401

        return True

    except ImportError:
        return False


def is_macos_available() -> bool:
    """Return True if macOS osascript is available."""
    return (
        IS_MAC
        and shutil.which("osascript") is not None
    )


def is_linux_available() -> bool:
    """Return True if Linux notify-send is available."""
    return (
        IS_LINUX
        and shutil.which("notify-send") is not None
    )


def get_available_backends() -> list[str]:
    """
    Return all currently available notification backends.
    """
    backends: list[str] = []

    if is_plyer_available():
        backends.append("plyer")

    if is_win10toast_available():
        backends.append("win10toast")

    if is_macos_available():
        backends.append("osascript")

    if is_linux_available():
        backends.append("notify-send")

    return backends


def is_available() -> bool:
    """
    Return True if at least one notification backend exists.
    """
    return bool(
        get_available_backends()
    )


# ============================================================================
# PLATFORM INFO
# ============================================================================


def get_platform_name() -> str:
    """
    Return normalized operating-system name.
    """
    if IS_WINDOWS:
        return "windows"

    if IS_MAC:
        return "macos"

    if IS_LINUX:
        return "linux"

    return platform.system().lower()


# ============================================================================
# CORE NOTIFICATION
# ============================================================================


def notify(
    title: str,
    message: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    icon_path: str | None = None,
) -> bool:
    """
    Display a desktop notification.

    Backend order:
        1. Plyer
        2. Windows -> win10toast
        3. macOS -> osascript
        4. Linux -> notify-send

    Returns:
        True when a notification was successfully displayed.

    Raises:
        NotificationValidationError:
            Invalid notification data.

        NotificationBackendError:
            No backend could display the notification.
    """
    request = _prepare_request(
        title=title,
        message=message,
        timeout_seconds=timeout_seconds,
        icon_path=icon_path,
    )

    logger.debug(
        "Sending notification: title=%r",
        request.title,
    )

    # ------------------------------------------------------------------
    # Primary cross-platform backend
    # ------------------------------------------------------------------

    if _try_plyer(request):
        logger.info(
            "Notification shown via plyer: %s",
            request.title,
        )

        return True

    # ------------------------------------------------------------------
    # Platform fallback
    # ------------------------------------------------------------------

    if IS_WINDOWS:
        if _try_windows_native(request):
            logger.info(
                "Notification shown via win10toast: %s",
                request.title,
            )

            return True

    elif IS_MAC:
        if _try_mac_native(request):
            logger.info(
                "Notification shown via osascript: %s",
                request.title,
            )

            return True

    elif IS_LINUX:
        if _try_linux_native(request):
            logger.info(
                "Notification shown via notify-send: %s",
                request.title,
            )

            return True

    raise NotificationBackendError(
        f"Could not display notification "
        f"'{request.title}'. "
        f"Available backends: "
        f"{', '.join(get_available_backends()) or 'none'}"
    )


# ============================================================================
# SAFE NOTIFICATION
# ============================================================================


def safe_notify(
    title: str,
    message: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    icon_path: str | None = None,
) -> bool:
    """
    Non-raising notification wrapper.

    Useful for:
        - scheduler
        - background tasks
        - automation
        - startup processes

    Returns:
        True on success, False on failure.
    """
    try:
        return notify(
            title=title,
            message=message,
            timeout_seconds=timeout_seconds,
            icon_path=icon_path,
        )

    except NotificationError as exc:
        logger.warning(
            "Notification failed: %s",
            exc,
        )

        return False

    except Exception as exc:
        logger.exception(
            "Unexpected notification error: %s",
            exc,
        )

        return False


# ============================================================================
# NOTIFICATION TYPES
# ============================================================================


def notify_info(
    message: str,
    title: str | None = None,
) -> bool:
    """
    Show an informational notification.
    """
    return notify(
        title=title or f"{APP_NAME} — Info",
        message=message,
        timeout_seconds=INFO_TIMEOUT_SECONDS,
    )


def notify_success(
    message: str,
    title: str | None = None,
) -> bool:
    """
    Show a success notification.
    """
    return notify(
        title=title or f"{APP_NAME} — Success",
        message=message,
        timeout_seconds=SUCCESS_TIMEOUT_SECONDS,
    )


def notify_warning(
    message: str,
    title: str | None = None,
) -> bool:
    """
    Show a warning notification.
    """
    return notify(
        title=title or f"{APP_NAME} — Warning",
        message=message,
        timeout_seconds=WARNING_TIMEOUT_SECONDS,
    )


def notify_error(
    error_summary: str,
    title: str | None = None,
) -> bool:
    """
    Show a non-blocking error notification.
    """
    return notify(
        title=title or f"{APP_NAME} — Something went wrong",
        message=error_summary,
        timeout_seconds=ERROR_TIMEOUT_SECONDS,
    )


def notify_reminder(
    reminder_text: str,
) -> bool:
    """
    Show a reminder notification.

    Intended for:
        core/scheduler.py
    """
    return notify(
        title=f"{APP_NAME} Reminder",
        message=reminder_text,
        timeout_seconds=REMINDER_TIMEOUT_SECONDS,
    )


# ============================================================================
# ASSISTANTX-SPECIFIC HELPERS
# ============================================================================


def notify_task_completed(
    task_name: str,
) -> bool:
    """
    Notify that an AssistantX task has completed.
    """
    return notify_success(
        f"Task completed: {task_name}"
    )


def notify_download_completed(
    filename: str,
) -> bool:
    """
    Notify that a download has completed.
    """
    return notify_success(
        f"Download completed: {filename}",
        title=f"{APP_NAME} — Download Complete",
    )


def notify_update_available(
    version: str,
) -> bool:
    """
    Notify that a new AssistantX version is available.
    """
    return notify_info(
        f"A new AssistantX version is available: {version}",
        title=f"{APP_NAME} — Update Available",
    )


def notify_system_event(
    event_message: str,
) -> bool:
    """
    Show a general system event notification.
    """
    return notify_info(
        event_message,
        title=f"{APP_NAME} — System",
    )


# ============================================================================
# DIAGNOSTICS
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return notification subsystem diagnostics.
    """
    return {
        "available": is_available(),
        "platform": get_platform_name(),
        "python_platform": platform.platform(),
        "backends": get_available_backends(),
        "plyer": is_plyer_available(),
        "win10toast": is_win10toast_available(),
        "osascript": is_macos_available(),
        "notify_send": is_linux_available(),
        "default_icon": str(DEFAULT_ICON_PATH),
        "default_icon_exists": DEFAULT_ICON_PATH.exists(),
    }


# ============================================================================
# PUBLIC API
# ============================================================================


__all__ = [
    # Constants
    "DEFAULT_TIMEOUT_SECONDS",
    "REMINDER_TIMEOUT_SECONDS",
    "ERROR_TIMEOUT_SECONDS",
    "SUCCESS_TIMEOUT_SECONDS",
    "INFO_TIMEOUT_SECONDS",
    "WARNING_TIMEOUT_SECONDS",

    # Exceptions
    "NotificationError",
    "NotificationValidationError",
    "NotificationBackendError",

    # Models
    "NotificationRequest",

    # Core
    "notify",
    "safe_notify",

    # Notification types
    "notify_info",
    "notify_success",
    "notify_warning",
    "notify_error",
    "notify_reminder",

    # AssistantX helpers
    "notify_task_completed",
    "notify_download_completed",
    "notify_update_available",
    "notify_system_event",

    # Backend
    "is_available",
    "is_plyer_available",
    "is_win10toast_available",
    "is_macos_available",
    "is_linux_available",
    "get_available_backends",
    "get_platform_name",

    # Diagnostics
    "diagnostics",
]
