"""
notifications.py
=================
Native OS desktop notifications (toast on Windows, Notification Center
on macOS, libnotify on Linux), built on the `plyer` package for
cross-platform coverage with a per-platform native fallback so this
still works even without plyer installed.

Used by core/scheduler.py (reminder due notifications) and anywhere
else AssistantX needs to surface a message even when the dashboard
window isn't focused or is minimized to the tray.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.constants import APP_NAME, ICONS_DIR, IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_ICON_PATH = ICONS_DIR / "app.ico"


class NotificationError(RuntimeError):
    """Raised when a notification could not be shown through any available backend."""


@dataclass
class NotificationRequest:
    title: str
    message: str
    timeout_seconds: int = 8
    icon_path: Optional[str] = None


def _try_plyer(request: NotificationRequest) -> bool:
    try:
        from plyer import notification  # type: ignore
    except ImportError:
        return False

    try:
        notification.notify(
            title=request.title,
            message=request.message,
            app_name=APP_NAME,
            timeout=request.timeout_seconds,
            app_icon=request.icon_path or (str(_DEFAULT_ICON_PATH) if _DEFAULT_ICON_PATH.exists() else ""),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("plyer notification failed (%s); trying platform-native fallback.", exc)
        return False


def _try_windows_native(request: NotificationRequest) -> bool:
    try:
        from win10toast import ToastNotifier  # type: ignore

        toaster = ToastNotifier()
        toaster.show_toast(
            request.title,
            request.message,
            duration=request.timeout_seconds,
            threaded=True,
            icon_path=request.icon_path or (str(_DEFAULT_ICON_PATH) if _DEFAULT_ICON_PATH.exists() else None),
        )
        return True
    except ImportError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug("win10toast fallback failed: %s", exc)
        return False


def _try_mac_native(request: NotificationRequest) -> bool:
    try:
        # osascript's display notification doesn't support custom icons,
        # but is available on every macOS install with zero dependencies.
        safe_title = request.title.replace('"', '\\"')
        safe_message = request.message.replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_message}" with title "{safe_title}"'],
            check=True,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.debug("macOS osascript notification failed: %s", exc)
        return False


def _try_linux_native(request: NotificationRequest) -> bool:
    try:
        cmd = ["notify-send", request.title, request.message, "-t", str(request.timeout_seconds * 1000)]
        if request.icon_path:
            cmd.extend(["-i", request.icon_path])
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.debug("Linux notify-send fallback failed: %s", exc)
        return False


def notify(
    title: str,
    message: str,
    timeout_seconds: int = 8,
    icon_path: Optional[str] = None,
) -> bool:
    """
    Show a desktop notification, trying `plyer` first (best
    cross-platform coverage), then falling back to platform-native
    mechanisms in order.

    Returns:
        True if any backend successfully displayed the notification.

    Raises:
        NotificationError: if every available backend failed (or none
            are installed/supported on this platform).
    """
    request = NotificationRequest(
        title=title, message=message, timeout_seconds=timeout_seconds, icon_path=icon_path
    )

    if _try_plyer(request):
        logger.debug("Notification shown via plyer: %s", title)
        return True

    if IS_WINDOWS and _try_windows_native(request):
        logger.debug("Notification shown via win10toast: %s", title)
        return True
    if IS_MAC and _try_mac_native(request):
        logger.debug("Notification shown via osascript: %s", title)
        return True
    if IS_LINUX and _try_linux_native(request):
        logger.debug("Notification shown via notify-send: %s", title)
        return True

    raise NotificationError(
        f"Could not display notification '{title}' — no working backend found. "
        f"Try: pip install plyer"
    )


def notify_reminder(reminder_text: str) -> bool:
    """Convenience wrapper for core/scheduler.py's due-reminder notifications."""
    return notify(title=f"{APP_NAME} Reminder", message=reminder_text, timeout_seconds=15)


def notify_error(error_summary: str) -> bool:
    """Convenience wrapper for surfacing a non-blocking error to the user."""
    return notify(title=f"{APP_NAME} — Something went wrong", message=error_summary, timeout_seconds=10)
    