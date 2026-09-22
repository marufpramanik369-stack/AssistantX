"""
apps.py
=======
Professional cross-platform application automation for AssistantX.

Features
--------
- Launch applications by friendly name
- Close running applications
- Exact + fuzzy app-name matching
- Platform-aware application commands
- Runtime app alias registration
- Application availability checks
- Known-app discovery
- Safe wrappers for command_router / assistant usage
- Structured diagnostics
- Windows / macOS / Linux support

Notes
-----
This module intentionally avoids heavyweight automation frameworks.
Application launching/closing is performed through native OS facilities
and subprocess commands.

Closing an application is best-effort and may force-terminate processes
on some platforms. Callers should obtain user confirmation before using
destructive/force-close operations when appropriate.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_FUZZY_CUTOFF = 0.72
STRICT_FUZZY_CUTOFF = 0.85

PROCESS_TIMEOUT_SECONDS = 10

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"


# ============================================================================
# Exceptions
# ============================================================================


class AppAutomationError(RuntimeError):
    """Base exception for application automation."""


class AppLaunchError(AppAutomationError):
    """Raised when an application cannot be launched."""


class AppCloseError(AppAutomationError):
    """Raised when an application cannot be closed."""


class AppValidationError(AppAutomationError):
    """Raised when application input is invalid."""


class AppNotFoundError(AppAutomationError):
    """Raised when an application cannot be resolved."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class AppAlias:
    """
    Application alias definition.

    names:
        Friendly names / spoken variants.

    windows_cmd:
        Windows executable, command, or URI.

    mac_cmd:
        macOS application name used with `open -a`.

    linux_cmd:
        Linux executable/command.
    """

    names: tuple[str, ...]
    windows_cmd: str | None = None
    mac_cmd: str | None = None
    linux_cmd: str | None = None

    def __post_init__(self) -> None:
        if not self.names:
            raise AppValidationError(
                "AppAlias must contain at least one name."
            )

        normalized = tuple(
            name.strip().casefold()
            for name in self.names
            if isinstance(name, str) and name.strip()
        )

        if not normalized:
            raise AppValidationError(
                "AppAlias contains no valid names."
            )

        object.__setattr__(self, "names", normalized)


@dataclass(frozen=True)
class AppResolution:
    """Result of resolving a user-facing application name."""

    requested_name: str
    matched_name: str | None
    target: str
    fuzzy_match: bool
    alias: AppAlias | None


@dataclass(frozen=True)
class AppInfo:
    """Basic information about an AssistantX-known application."""

    name: str
    aliases: tuple[str, ...]
    target: str | None
    available: bool


@dataclass(frozen=True)
class AppCommandResult:
    """Result information from a native process command."""

    success: bool
    return_code: int
    stdout: str = ""
    stderr: str = ""


# ============================================================================
# Application Alias Table
# ============================================================================

_APP_ALIASES: list[AppAlias] = [
    AppAlias(
        ("chrome", "google chrome"),
        windows_cmd="chrome",
        mac_cmd="Google Chrome",
        linux_cmd="google-chrome",
    ),
    AppAlias(
        ("firefox", "mozilla firefox"),
        windows_cmd="firefox",
        mac_cmd="Firefox",
        linux_cmd="firefox",
    ),
    AppAlias(
        ("edge", "microsoft edge"),
        windows_cmd="msedge",
        mac_cmd="Microsoft Edge",
        linux_cmd="microsoft-edge",
    ),
    AppAlias(
        ("notepad",),
        windows_cmd="notepad",
        mac_cmd="TextEdit",
        linux_cmd="gedit",
    ),
    AppAlias(
        ("calculator", "calc"),
        windows_cmd="calc",
        mac_cmd="Calculator",
        linux_cmd="gnome-calculator",
    ),
    AppAlias(
        ("word", "microsoft word", "ms word"),
        windows_cmd="winword",
        mac_cmd="Microsoft Word",
    ),
    AppAlias(
        ("excel", "microsoft excel", "ms excel"),
        windows_cmd="excel",
        mac_cmd="Microsoft Excel",
    ),
    AppAlias(
        ("powerpoint", "microsoft powerpoint", "ms powerpoint"),
        windows_cmd="powerpnt",
        mac_cmd="Microsoft PowerPoint",
    ),
    AppAlias(
        ("spotify",),
        windows_cmd="spotify",
        mac_cmd="Spotify",
        linux_cmd="spotify",
    ),
    AppAlias(
        (
            "vscode",
            "visual studio code",
            "vs code",
            "code",
        ),
        windows_cmd="code",
        mac_cmd="Visual Studio Code",
        linux_cmd="code",
    ),
    AppAlias(
        (
            "terminal",
            "command prompt",
            "cmd",
        ),
        windows_cmd="cmd",
        mac_cmd="Terminal",
        linux_cmd="gnome-terminal",
    ),
    AppAlias(
        (
            "powershell",
            "power shell",
        ),
        windows_cmd="powershell",
        mac_cmd="Terminal",
        linux_cmd="gnome-terminal",
    ),
    AppAlias(
        (
            "file explorer",
            "explorer",
            "files",
        ),
        windows_cmd="explorer",
        mac_cmd="Finder",
        linux_cmd="nautilus",
    ),
    AppAlias(
        ("settings", "system settings"),
        windows_cmd="ms-settings:",
        mac_cmd="System Settings",
        linux_cmd="gnome-control-center",
    ),
    AppAlias(
        ("paint", "ms paint"),
        windows_cmd="mspaint",
    ),
    AppAlias(
        ("task manager",),
        windows_cmd="taskmgr",
    ),
    AppAlias(
        (
            "outlook",
            "microsoft outlook",
        ),
        windows_cmd="outlook",
        mac_cmd="Microsoft Outlook",
    ),
    AppAlias(
        ("slack",),
        windows_cmd="slack",
        mac_cmd="Slack",
        linux_cmd="slack",
    ),
    AppAlias(
        ("discord",),
        windows_cmd="discord",
        mac_cmd="Discord",
        linux_cmd="discord",
    ),
    AppAlias(
        ("zoom", "zoom meetings"),
        windows_cmd="zoom",
        mac_cmd="zoom.us",
        linux_cmd="zoom",
    ),
    AppAlias(
        (
            "teams",
            "microsoft teams",
        ),
        windows_cmd="teams",
        mac_cmd="Microsoft Teams",
        linux_cmd="teams",
    ),
    AppAlias(
        ("vlc", "vlc media player"),
        windows_cmd="vlc",
        mac_cmd="VLC",
        linux_cmd="vlc",
    ),
    AppAlias(
        ("steam",),
        windows_cmd="steam",
        mac_cmd="Steam",
        linux_cmd="steam",
    ),
]


# ============================================================================
# Internal Index
# ============================================================================


def _build_alias_index() -> dict[str, AppAlias]:
    """Build a fast normalized-name -> alias mapping."""
    index: dict[str, AppAlias] = {}

    for alias in _APP_ALIASES:
        for name in alias.names:
            index[name.casefold()] = alias

    return index


_ALIAS_INDEX = _build_alias_index()


def _refresh_alias_index() -> None:
    """Refresh the internal alias index after runtime registration."""
    global _ALIAS_INDEX
    _ALIAS_INDEX = _build_alias_index()


def _all_names() -> list[str]:
    """Return all known friendly application names."""
    return sorted(_ALIAS_INDEX.keys())


# ============================================================================
# Validation
# ============================================================================


def _validate_app_name(app_name: str) -> str:
    """Validate and normalize an application name."""
    if not isinstance(app_name, str):
        raise AppValidationError(
            "Application name must be a string."
        )

    normalized = app_name.strip()

    if not normalized:
        raise AppValidationError(
            "Application name cannot be empty."
        )

    if len(normalized) > 255:
        raise AppValidationError(
            "Application name is too long."
        )

    return normalized


# ============================================================================
# Platform Helpers
# ============================================================================


def get_platform_name() -> str:
    """Return AssistantX's normalized platform name."""
    if IS_WINDOWS:
        return WINDOWS

    if IS_MAC:
        return MACOS

    if IS_LINUX:
        return LINUX

    return "unknown"


def _platform_target(alias: AppAlias) -> str | None:
    """Return the launch target appropriate for the current platform."""
    if IS_WINDOWS:
        return alias.windows_cmd

    if IS_MAC:
        return alias.mac_cmd

    if IS_LINUX:
        return alias.linux_cmd

    return None


# ============================================================================
# Alias Matching
# ============================================================================


def _find_alias(app_name: str) -> AppAlias | None:
    """Find an exact case-insensitive application alias."""
    normalized = app_name.strip().casefold()

    return _ALIAS_INDEX.get(normalized)


def _fuzzy_find_alias(
    app_name: str,
    cutoff: float = DEFAULT_FUZZY_CUTOFF,
) -> AppAlias | None:
    """
    Fuzzy-match an application name.

    Useful for voice recognition mistakes such as:
        crome -> chrome
        fire fox -> firefox
        vs code -> vscode
    """
    normalized = app_name.strip().casefold()

    if not normalized:
        return None

    matches = difflib.get_close_matches(
        normalized,
        _all_names(),
        n=1,
        cutoff=cutoff,
    )

    if not matches:
        return None

    return _find_alias(matches[0])


def resolve_app(
    app_name: str,
    *,
    fuzzy: bool = True,
    cutoff: float = DEFAULT_FUZZY_CUTOFF,
) -> AppResolution:
    """
    Resolve a user-facing app name into a platform-specific target.

    If no alias is found, the original application name is returned as
    the target so the OS/PATH can attempt to resolve it.
    """
    app_name = _validate_app_name(app_name)

    exact_alias = _find_alias(app_name)

    if exact_alias is not None:
        target = _platform_target(exact_alias)

        if target:
            return AppResolution(
                requested_name=app_name,
                matched_name=exact_alias.names[0],
                target=target,
                fuzzy_match=False,
                alias=exact_alias,
            )

        logger.debug(
            "Alias '%s' has no target for platform '%s'.",
            app_name,
            get_platform_name(),
        )

    if fuzzy:
        fuzzy_alias = _fuzzy_find_alias(
            app_name,
            cutoff=cutoff,
        )

        if fuzzy_alias is not None:
            target = _platform_target(fuzzy_alias)

            if target:
                logger.debug(
                    "Fuzzy matched '%s' -> '%s'.",
                    app_name,
                    fuzzy_alias.names[0],
                )

                return AppResolution(
                    requested_name=app_name,
                    matched_name=fuzzy_alias.names[0],
                    target=target,
                    fuzzy_match=True,
                    alias=fuzzy_alias,
                )

    # Raw fallback.
    return AppResolution(
        requested_name=app_name,
        matched_name=None,
        target=app_name,
        fuzzy_match=False,
        alias=None,
    )


def resolve_app_command(
    app_name: str,
    *,
    fuzzy: bool = True,
) -> str:
    """
    Backward-compatible helper.

    Returns the platform-specific launch target.
    """
    resolution = resolve_app(
        app_name,
        fuzzy=fuzzy,
    )

    logger.debug(
        "Resolved app '%s' -> '%s'.",
        resolution.requested_name,
        resolution.target,
    )

    return resolution.target


# ============================================================================
# Application Availability
# ============================================================================


def _windows_target_available(target: str) -> bool:
    """
    Check whether a Windows target appears launchable.

    URI schemes such as ms-settings: are considered available because
    Windows handles them through ShellExecute.
    """
    if target.endswith(":"):
        return True

    if os.path.isfile(target):
        return True

    if shutil.which(target):
        return True

    return False


def _mac_target_available(target: str) -> bool:
    """Check whether an application exists on macOS."""
    if shutil.which("open") is None:
        return False

    try:
        result = subprocess.run(
            ["open", "-Ra", target],
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        return result.returncode == 0

    except (OSError, subprocess.SubprocessError):
        return False


def _linux_target_available(target: str) -> bool:
    """Check whether a Linux command is available."""
    return shutil.which(target) is not None


def is_app_available(app_name: str) -> bool:
    """
    Check whether an application appears available on the current system.

    This is a best-effort check and does not guarantee successful launch.
    """
    resolution = resolve_app(app_name)

    target = resolution.target

    if IS_WINDOWS:
        return _windows_target_available(target)

    if IS_MAC:
        return _mac_target_available(target)

    if IS_LINUX:
        return _linux_target_available(target)

    return False


# ============================================================================
# Launch
# ============================================================================


def _launch_windows(target: str) -> None:
    """Launch an application on Windows."""
    os.startfile(target)  # type: ignore[attr-defined]


def _launch_mac(target: str) -> None:
    """Launch an application on macOS."""
    subprocess.Popen(
        ["open", "-a", target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _launch_linux(target: str) -> None:
    """Launch an application on Linux."""
    if shutil.which(target) is None:
        raise AppNotFoundError(
            f"'{target}' was not found on PATH."
        )

    subprocess.Popen(
        [target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_app(app_name: str) -> bool:
    """
    Launch an application by friendly name or executable name.

    Returns
    -------
    bool
        True when the launch request was dispatched.

    Raises
    ------
    AppLaunchError
        If launching fails.
    """
    resolution = resolve_app(app_name)

    logger.info(
        "Opening app '%s' -> '%s'%s",
        resolution.requested_name,
        resolution.target,
        " [fuzzy]" if resolution.fuzzy_match else "",
    )

    try:
        if IS_WINDOWS:
            _launch_windows(resolution.target)

        elif IS_MAC:
            _launch_mac(resolution.target)

        elif IS_LINUX:
            _launch_linux(resolution.target)

        else:
            raise AppLaunchError(
                "Unsupported platform for application launching."
            )

        return True

    except AppAutomationError:
        raise

    except FileNotFoundError as exc:
        raise AppLaunchError(
            f"Could not find application "
            f"'{resolution.requested_name}' "
            f"(target: '{resolution.target}')."
        ) from exc

    except PermissionError as exc:
        raise AppLaunchError(
            f"Permission denied while launching "
            f"'{resolution.requested_name}'."
        ) from exc

    except OSError as exc:
        raise AppLaunchError(
            f"Failed to launch "
            f"'{resolution.requested_name}': {exc}"
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected error while launching '%s'.",
            resolution.requested_name,
        )

        raise AppLaunchError(
            f"Unexpected launch error: {exc}"
        ) from exc


# ============================================================================
# Closing
# ============================================================================


def _close_windows(target: str) -> AppCommandResult:
    """Close/terminate a Windows application."""
    executable = target

    if not executable.lower().endswith(".exe"):
        executable = f"{executable}.exe"

    try:
        result = subprocess.run(
            [
                "taskkill",
                "/IM",
                executable,
                "/F",
            ],
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        return AppCommandResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )

    except (OSError, subprocess.SubprocessError) as exc:
        logger.error(
            "Windows close command failed: %s",
            exc,
        )

        return AppCommandResult(
            success=False,
            return_code=-1,
            stderr=str(exc),
        )


def _close_mac(target: str) -> AppCommandResult:
    """Request graceful application termination on macOS."""
    escaped_target = target.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'tell application "{escaped_target}" to quit'
    )

    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        return AppCommandResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )

    except (OSError, subprocess.SubprocessError) as exc:
        logger.error(
            "macOS close command failed: %s",
            exc,
        )

        return AppCommandResult(
            success=False,
            return_code=-1,
            stderr=str(exc),
        )


def _close_linux(target: str) -> AppCommandResult:
    """Request application termination on Linux."""
    try:
        result = subprocess.run(
            [
                "pkill",
                "-f",
                target,
            ],
            capture_output=True,
            text=True,
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        return AppCommandResult(
            success=result.returncode == 0,
            return_code=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )

    except (OSError, subprocess.SubprocessError) as exc:
        logger.error(
            "Linux close command failed: %s",
            exc,
        )

        return AppCommandResult(
            success=False,
            return_code=-1,
            stderr=str(exc),
        )


def close_app(
    app_name: str,
    *,
    raise_on_failure: bool = False,
) -> bool:
    """
    Attempt to close an application.

    Windows:
        Uses taskkill /F.

    macOS:
        Sends a graceful quit request through AppleScript.

    Linux:
        Uses pkill -f.

    Returns True when the OS command reports success.

    Note:
        Closing arbitrary applications is inherently best-effort.
        Some applications may prompt to save data or ignore termination.
    """
    resolution = resolve_app(app_name)

    logger.info(
        "Closing app '%s' -> '%s'.",
        resolution.requested_name,
        resolution.target,
    )

    try:
        if IS_WINDOWS:
            result = _close_windows(resolution.target)

        elif IS_MAC:
            result = _close_mac(resolution.target)

        elif IS_LINUX:
            result = _close_linux(resolution.target)

        else:
            if raise_on_failure:
                raise AppCloseError(
                    "Unsupported platform for application closing."
                )

            return False

    except Exception as exc:
        logger.error(
            "Failed to close '%s': %s",
            app_name,
            exc,
        )

        if raise_on_failure:
            raise AppCloseError(
                f"Failed to close '{app_name}': {exc}"
            ) from exc

        return False

    if result.success:
        return True

    logger.warning(
        "Application close command failed for '%s'. "
        "return_code=%s stderr=%s",
        app_name,
        result.return_code,
        result.stderr,
    )

    if raise_on_failure:
        raise AppCloseError(
            f"Could not close application '{app_name}'. "
            f"{result.stderr}".strip()
        )

    return False


# ============================================================================
# Alias Registration
# ============================================================================


def register_app(
    names: Sequence[str],
    *,
    windows_cmd: str | None = None,
    mac_cmd: str | None = None,
    linux_cmd: str | None = None,
    replace: bool = False,
) -> AppAlias:
    """
    Register a custom application alias.

    Example
    -------
    register_app(
        ("my app", "myapp"),
        windows_cmd="MyApp.exe",
        mac_cmd="My App",
        linux_cmd="myapp",
    )
    """
    normalized_names = tuple(
        name.strip().casefold()
        for name in names
        if isinstance(name, str) and name.strip()
    )

    if not normalized_names:
        raise AppValidationError(
            "At least one valid application alias is required."
        )

    if not any(
        (
            windows_cmd,
            mac_cmd,
            linux_cmd,
        )
    ):
        raise AppValidationError(
            "At least one platform launch target is required."
        )

    existing_names = [
        name
        for name in normalized_names
        if name in _ALIAS_INDEX
    ]

    if existing_names and not replace:
        raise AppValidationError(
            "Application alias already exists: "
            + ", ".join(existing_names)
        )

    if replace:
        global _APP_ALIASES

        _APP_ALIASES[:] = [
            alias
            for alias in _APP_ALIASES
            if not any(
                name in normalized_names
                for name in alias.names
            )
        ]

    alias = AppAlias(
        names=normalized_names,
        windows_cmd=windows_cmd,
        mac_cmd=mac_cmd,
        linux_cmd=linux_cmd,
    )

    _APP_ALIASES.append(alias)

    _refresh_alias_index()

    logger.info(
        "Registered application alias: %s",
        ", ".join(alias.names),
    )

    return alias


def unregister_app(name: str) -> bool:
    """Remove an application alias by any known friendly name."""
    normalized = _validate_app_name(name).casefold()

    alias = _ALIAS_INDEX.get(normalized)

    if alias is None:
        return False

    _APP_ALIASES[:] = [
        item
        for item in _APP_ALIASES
        if item is not alias
    ]

    _refresh_alias_index()

    logger.info(
        "Unregistered application alias '%s'.",
        normalized,
    )

    return True


# ============================================================================
# Discovery
# ============================================================================


def list_known_apps() -> list[str]:
    """
    Return all friendly application names recognized by AssistantX.
    """
    return _all_names()


def get_app_info(app_name: str) -> AppInfo:
    """Return structured information about a known application."""
    app_name = _validate_app_name(app_name)

    resolution = resolve_app(app_name)

    if resolution.alias is None:
        return AppInfo(
            name=app_name,
            aliases=(),
            target=resolution.target,
            available=is_app_available(app_name),
        )

    return AppInfo(
        name=resolution.alias.names[0],
        aliases=resolution.alias.names,
        target=_platform_target(resolution.alias),
        available=is_app_available(app_name),
    )


def find_apps(
    query: str,
    *,
    limit: int = 10,
    cutoff: float = DEFAULT_FUZZY_CUTOFF,
) -> list[str]:
    """
    Find application aliases matching a query.

    Useful for dashboard search and voice-command assistance.
    """
    query = _validate_app_name(query)

    if limit < 1:
        raise AppValidationError(
            "limit must be greater than zero."
        )

    names = _all_names()

    matches = difflib.get_close_matches(
        query.casefold(),
        names,
        n=limit,
        cutoff=cutoff,
    )

    return matches


# ============================================================================
# Safe Wrappers
# ============================================================================


def safe_open_app(app_name: str) -> bool:
    """
    Safe version of open_app().

    Returns False instead of raising AppAutomationError.
    """
    try:
        return open_app(app_name)

    except AppAutomationError as exc:
        logger.warning(
            "safe_open_app failed: %s",
            exc,
        )
        return False


def safe_close_app(app_name: str) -> bool:
    """
    Safe version of close_app().

    Returns False instead of raising AppAutomationError.
    """
    try:
        return close_app(app_name)

    except AppAutomationError as exc:
        logger.warning(
            "safe_close_app failed: %s",
            exc,
        )
        return False


# ============================================================================
# Diagnostics
# ============================================================================


def diagnostics() -> dict[str, object]:
    """
    Return module diagnostics for AssistantX health checks.
    """
    platform = get_platform_name()

    available_apps = 0

    for name in list_known_apps():
        try:
            if is_app_available(name):
                available_apps += 1
        except Exception:
            continue

    return {
        "platform": platform,
        "supported_platform": platform in {
            WINDOWS,
            MACOS,
            LINUX,
        },
        "known_alias_count": len(_APP_ALIASES),
        "known_name_count": len(_ALIAS_INDEX),
        "available_known_apps": available_apps,
        "fuzzy_cutoff": DEFAULT_FUZZY_CUTOFF,
        "strict_fuzzy_cutoff": STRICT_FUZZY_CUTOFF,
    }


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Exceptions
    "AppAutomationError",
    "AppLaunchError",
    "AppCloseError",
    "AppValidationError",
    "AppNotFoundError",

    # Data models
    "AppAlias",
    "AppResolution",
    "AppInfo",
    "AppCommandResult",

    # Constants
    "DEFAULT_FUZZY_CUTOFF",
    "STRICT_FUZZY_CUTOFF",
    "WINDOWS",
    "MACOS",
    "LINUX",

    # Resolution
    "resolve_app",
    "resolve_app_command",

    # Launch / close
    "open_app",
    "close_app",

    # Availability
    "is_app_available",

    # Discovery
    "list_known_apps",
    "get_app_info",
    "find_apps",

    # Runtime registration
    "register_app",
    "unregister_app",

    # Platform
    "get_platform_name",

    # Safe wrappers
    "safe_open_app",
    "safe_close_app",

    # Diagnostics
    "diagnostics",
]
