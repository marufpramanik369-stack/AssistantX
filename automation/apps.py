"""
apps.py
=======
Cross-platform application launching, closing, and discovery.

Since there's no universal API for "open an app by name" across
Windows/macOS/Linux, this module maintains a small alias table for
common applications (mapped to their platform-specific launch command)
plus a fuzzy-matching fallback that tries the raw name directly via the
OS shell — so "open chrome" works out of the box, and less common app
names still have a reasonable shot at working.
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

logger = get_logger(__name__)


class AppLaunchError(RuntimeError):
    """Raised when an application could not be launched or found."""


@dataclass
class AppAlias:
    """Maps a friendly spoken name to platform-specific launch commands."""

    names: tuple[str, ...]  # all the ways a user might refer to this app
    windows_cmd: Optional[str] = None
    mac_cmd: Optional[str] = None   # macOS 'open -a <name>' target
    linux_cmd: Optional[str] = None


# --------------------------------------------------------------------------- #
# Common application alias table. Extend freely — this is intentionally a
# simple data table so users/plugins can add entries without touching logic.
# --------------------------------------------------------------------------- #

_APP_ALIASES: list[AppAlias] = [
    AppAlias(("chrome", "google chrome"), windows_cmd="chrome", mac_cmd="Google Chrome", linux_cmd="google-chrome"),
    AppAlias(("firefox", "mozilla firefox"), windows_cmd="firefox", mac_cmd="Firefox", linux_cmd="firefox"),
    AppAlias(("edge", "microsoft edge"), windows_cmd="msedge", mac_cmd="Microsoft Edge", linux_cmd="microsoft-edge"),
    AppAlias(("notepad",), windows_cmd="notepad", mac_cmd="TextEdit", linux_cmd="gedit"),
    AppAlias(("calculator",), windows_cmd="calc", mac_cmd="Calculator", linux_cmd="gnome-calculator"),
    AppAlias(("word", "microsoft word", "ms word"), windows_cmd="winword", mac_cmd="Microsoft Word"),
    AppAlias(("excel", "microsoft excel", "ms excel"), windows_cmd="excel", mac_cmd="Microsoft Excel"),
    AppAlias(("powerpoint", "microsoft powerpoint", "ms powerpoint"), windows_cmd="powerpnt", mac_cmd="Microsoft PowerPoint"),
    AppAlias(("spotify",), windows_cmd="spotify", mac_cmd="Spotify", linux_cmd="spotify"),
    AppAlias(("vscode", "visual studio code", "vs code", "code"), windows_cmd="code", mac_cmd="Visual Studio Code", linux_cmd="code"),
    AppAlias(("terminal", "command prompt", "cmd"), windows_cmd="cmd", mac_cmd="Terminal", linux_cmd="gnome-terminal"),
    AppAlias(("file explorer", "explorer", "files"), windows_cmd="explorer", mac_cmd="Finder", linux_cmd="nautilus"),
    AppAlias(("settings",), windows_cmd="ms-settings:", mac_cmd="System Settings"),
    AppAlias(("paint", "ms paint"), windows_cmd="mspaint"),
    AppAlias(("task manager",), windows_cmd="taskmgr"),
    AppAlias(("outlook", "microsoft outlook"), windows_cmd="outlook", mac_cmd="Microsoft Outlook"),
    AppAlias(("slack",), windows_cmd="slack", mac_cmd="Slack", linux_cmd="slack"),
    AppAlias(("discord",), windows_cmd="discord", mac_cmd="Discord", linux_cmd="discord"),
    AppAlias(("zoom",), windows_cmd="zoom", mac_cmd="zoom.us", linux_cmd="zoom"),
    AppAlias(("teams", "microsoft teams"), windows_cmd="teams", mac_cmd="Microsoft Teams"),
]

_ALL_NAMES: list[str] = [name for alias in _APP_ALIASES for name in alias.names]


def _find_alias(app_name: str) -> Optional[AppAlias]:
    """Exact (case-insensitive) match against the alias table."""
    lowered = app_name.strip().lower()
    for alias in _APP_ALIASES:
        if lowered in alias.names:
            return alias
    return None


def _fuzzy_find_alias(app_name: str, cutoff: float = 0.72) -> Optional[AppAlias]:
    """Fuzzy match, to tolerate STT mis-transcriptions like 'crome' -> 'chrome'."""
    lowered = app_name.strip().lower()
    matches = difflib.get_close_matches(lowered, _ALL_NAMES, n=1, cutoff=cutoff)
    if not matches:
        return None
    return _find_alias(matches[0])


def resolve_app_command(app_name: str) -> str:
    """
    Resolve a friendly app name into the actual command/target to launch
    on the current platform. Falls back to the raw name itself if no
    alias matches, letting the OS attempt to resolve it directly (works
    for many apps already on PATH).
    """
    alias = _find_alias(app_name) or _fuzzy_find_alias(app_name)

    if alias is None:
        logger.debug("No alias found for '%s'; using raw name as launch target.", app_name)
        return app_name.strip()

    if IS_WINDOWS and alias.windows_cmd:
        return alias.windows_cmd
    if IS_MAC and alias.mac_cmd:
        return alias.mac_cmd
    if IS_LINUX and alias.linux_cmd:
        return alias.linux_cmd

    return app_name.strip()


def open_app(app_name: str) -> bool:
    """
    Launch an application by its friendly name.

    Returns:
        True if a launch command was successfully dispatched (does NOT
        guarantee the app's GUI fully opened — just that the OS accepted
        the launch request without raising).

    Raises:
        AppLaunchError: if the platform is unsupported or the launch
            command fails outright (e.g. binary not found).
    """
    target = resolve_app_command(app_name)
    logger.info("Attempting to open app '%s' (resolved target: '%s')", app_name, target)

    try:
        if IS_WINDOWS:
            # os.startfile handles both real .exe names and registered
            # URI schemes like 'ms-settings:'.
            import os

            os.startfile(target)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", "-a", target])
        elif IS_LINUX:
            if shutil.which(target) is None:
                raise AppLaunchError(f"'{target}' was not found on PATH.")
            subprocess.Popen([target])
        else:
            raise AppLaunchError("Unsupported platform for app launching.")
        return True

    except FileNotFoundError as exc:
        raise AppLaunchError(f"Could not find application '{app_name}' (target: '{target}').") from exc
    except OSError as exc:
        raise AppLaunchError(f"Failed to launch '{app_name}': {exc}") from exc


def close_app(app_name: str) -> bool:
    """
    Attempt to close a running application by name. Uses `taskkill` on
    Windows, `pkill`/`osascript` on macOS, and `pkill` on Linux — a
    best-effort approach since gracefully closing arbitrary GUI apps
    without their cooperation is inherently platform-limited.

    Returns:
        True if a close command was issued (not a guarantee the app
        actually terminated, e.g. if it prompts to save unsaved work).
    """
    target = resolve_app_command(app_name)
    logger.info("Attempting to close app '%s' (target: '%s')", app_name, target)

    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/IM", f"{target}.exe", "/F"],
                capture_output=True,
                check=False,
            )
        elif IS_MAC:
            subprocess.run(
                ["osascript", "-e", f'quit app "{target}"'],
                capture_output=True,
                check=False,
            )
        elif IS_LINUX:
            subprocess.run(["pkill", "-f", target], capture_output=True, check=False)
        else:
            return False
        return True
    except OSError as exc:
        logger.error("Failed to close '%s': %s", app_name, exc)
        return False


def list_known_apps() -> list[str]:
    """Return all friendly app names AssistantX recognizes out of the box,
    useful for a dashboard 'quick launch' panel or help text."""
    return sorted(set(_ALL_NAMES))
    