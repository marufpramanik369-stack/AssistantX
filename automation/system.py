"""
AssistantX - System Automation
===============================

Professional cross-platform system-control module for AssistantX.

Supported operations
--------------------
Power:
    - shutdown
    - cancel_shutdown
    - restart
    - sleep
    - lock_screen

Volume:
    - set_volume
    - get_volume
    - increase_volume
    - decrease_volume
    - adjust_volume
    - mute
    - unmute
    - toggle_mute

Brightness:
    - set_brightness
    - get_brightness
    - increase_brightness
    - decrease_brightness
    - adjust_brightness

Utilities:
    - get_platform_info
    - is_available
    - diagnostics
    - execute_command

Design
------
- Cross-platform
- Windows-first optimization
- Lazy optional dependencies
- Structured exceptions
- Input validation
- Logging
- Thread-safe controller
- Singleton controller
- Natural-language command support
- Async wrappers
- Backward-compatible module functions

Important
---------
Destructive operations such as shutdown and restart should be confirmed
by AssistantX's decision layer before reaching this module.

This module executes an already-approved operation.

Optional dependencies
---------------------
Windows volume:
    pip install pycaw comtypes

Brightness:
    pip install screen-brightness-control

Author:
    AssistantX Team

Version:
    2.0.0
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

# ============================================================================
# LOGGER
# ============================================================================

logger = get_logger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class SystemControlError(RuntimeError):
    """Base exception for AssistantX system-control operations."""


class SystemOperationError(SystemControlError):
    """Raised when a system automation operation fails."""


class UnsupportedPlatformError(SystemControlError):
    """Raised when an operation is unavailable on the current platform."""


class DependencyError(SystemControlError):
    """Raised when an optional dependency is required but unavailable."""


class CommandExecutionError(SystemControlError):
    """Raised when an OS command fails."""


class ValidationError(SystemControlError):
    """Raised when user input is invalid."""


# Alias & specific exception for automation/__init__.py and tests
SystemValidationError = ValidationError


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass(frozen=True)
class PlatformInfo:
    """Basic information about the operating system."""

    system: str
    release: str
    version: str
    machine: str
    processor: str
    python_version: str
    is_windows: bool
    is_linux: bool
    is_mac: bool

    def to_dict(self) -> dict[str, Any]:
        """Return platform information as a dictionary."""

        return {
            "system": self.system,
            "release": self.release,
            "version": self.version,
            "machine": self.machine,
            "processor": self.processor,
            "python_version": self.python_version,
            "is_windows": self.is_windows,
            "is_linux": self.is_linux,
            "is_mac": self.is_mac,
        }


@dataclass
class SystemConfig:
    """
    Runtime configuration for SystemController.

    Attributes
    ----------
    default_shutdown_delay:
        Default shutdown delay in seconds.

    default_restart_delay:
        Default restart delay in seconds.

    volume_step:
        Default relative volume adjustment.

    brightness_step:
        Default relative brightness adjustment.

    command_timeout:
        Timeout for subprocess operations.

    strict_validation:
        Whether invalid ranges should raise exceptions.
    """

    default_shutdown_delay: int = 5
    default_restart_delay: int = 5

    volume_step: int = 10
    brightness_step: int = 10

    command_timeout: float = 10.0

    strict_validation: bool = True

    def __post_init__(self) -> None:

        if self.default_shutdown_delay < 0:
            raise ValueError(
                "default_shutdown_delay cannot be negative."
            )

        if self.default_restart_delay < 0:
            raise ValueError(
                "default_restart_delay cannot be negative."
            )

        if self.volume_step <= 0:
            raise ValueError(
                "volume_step must be greater than zero."
            )

        if self.brightness_step <= 0:
            raise ValueError(
                "brightness_step must be greater than zero."
            )

        if self.command_timeout <= 0:
            raise ValueError(
                "command_timeout must be greater than zero."
            )


@dataclass
class SystemCommandResult:
    """Structured result for natural-language commands."""

    success: bool
    action: str
    message: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""

        return {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            "data": self.data or {},
        }

#UPDATED                                                                       ======================================================================================


class SystemAutomationError(Exception):
    """Base exception for system automation failures."""

def lock() -> None:
    """Lock the workstation."""


# ============================================================================
# CONSTANTS
# ============================================================================


MIN_PERCENT = 0
MAX_PERCENT = 100

POWER_ACTIONS = {
    "shutdown",
    "restart",
    "sleep",
    "lock",
    "safe_sleep",
    "safe_unmute",
}

SUPPORTED_PLATFORMS = {
    "windows",
    "linux",
    "macos",
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _clamp_percent(value: int) -> int:
    """
    Clamp a percentage between 0 and 100.
    """

    return max(
        MIN_PERCENT,
        min(MAX_PERCENT, int(value)),
    )


def _validate_percent(
    value: int,
    name: str = "value",
) -> int:
    """
    Validate and clamp a percentage.
    """

    if isinstance(value, bool):
        raise ValidationError(
            f"{name} must be an integer."
        )

    try:
        numeric_value = int(value)

    except (TypeError, ValueError) as exc:

        raise ValidationError(
            f"{name} must be an integer."
        ) from exc

    if not 0 <= numeric_value <= 100:
        raise ValidationError(
            f"{name} must be between 0 and 100."
        )

    return numeric_value


def _validate_delta(
    value: int,
    name: str = "delta",
) -> int:
    """
    Validate a relative percentage adjustment.
    """

    if isinstance(value, bool):
        raise ValidationError(
            f"{name} must be an integer."
        )

    try:
        return int(value)

    except (TypeError, ValueError) as exc:

        raise ValidationError(
            f"{name} must be an integer."
        ) from exc


def _validate_delay(
    value: int,
    name: str = "delay",
) -> int:
    """
    Validate a delay in seconds.
    """

    if isinstance(value, bool):
        raise ValidationError(
            f"{name} must be an integer."
        )

    try:
        delay = int(value)

    except (TypeError, ValueError) as exc:

        raise ValidationError(
            f"{name} must be an integer."
        ) from exc

    if delay < 0:
        raise ValidationError(
            f"{name} cannot be negative."
        )

    return delay


# ============================================================================
# PLATFORM INFORMATION
# ============================================================================


def get_platform_info() -> PlatformInfo:
    """
    Return detailed platform information.
    """

    return PlatformInfo(
        system=platform.system(),
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        processor=platform.processor(),
        python_version=platform.python_version(),
        is_windows=IS_WINDOWS,
        is_linux=IS_LINUX,
        is_mac=IS_MAC,
    )


def get_platform_name() -> str:
    """
    Return normalized platform name.
    """

    if IS_WINDOWS:
        return "windows"

    if IS_LINUX:
        return "linux"

    if IS_MAC:
        return "macos"

    return "unknown"


# ============================================================================
# COMMAND RUNNER
# ============================================================================


class CommandRunner:
    """
    Safe wrapper around subprocess.run().
    """

    def __init__(
        self,
        timeout: float = 10.0,
    ) -> None:

        if timeout <= 0:
            raise ValueError(
                "timeout must be greater than zero."
            )

        self.timeout = timeout

    def run(
        self,
        command: Sequence[str],
        *,
        check: bool = True,
        timeout: float | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Execute an operating-system command.
        """

        if not command:
            raise CommandExecutionError(
                "Command cannot be empty."
            )

        effective_timeout = (
            timeout
            if timeout is not None
            else self.timeout
        )

        logger.debug(
            "Executing system command: %s",
            list(command),
        )

        try:

            result = subprocess.run(
                list(command),
                check=check,
                timeout=effective_timeout,
                capture_output=capture_output,
                text=True,
            )

            return result

        except subprocess.TimeoutExpired as exc:

            raise CommandExecutionError(
                f"Command timed out: {command}"
            ) from exc

        except FileNotFoundError as exc:

            raise CommandExecutionError(
                f"Command not found: {command[0]}"
            ) from exc

        except subprocess.CalledProcessError as exc:

            stderr = (
                exc.stderr.strip()
                if exc.stderr
                else ""
            )

            message = (
                f"Command failed: {command}"
            )

            if stderr:
                message += f" - {stderr}"

            raise CommandExecutionError(
                message
            ) from exc

        except OSError as exc:

            raise CommandExecutionError(
                f"OS command failed: {exc}"
            ) from exc


# ============================================================================
# SYSTEM CONTROLLER
# ============================================================================


class SystemController:
    """
    Main AssistantX system automation controller.

    Example
    -------
    system = SystemController()

    system.set_volume(50)
    system.increase_volume()
    system.set_brightness(70)
    system.lock_screen()
    """

    def __init__(
        self,
        config: SystemConfig | None = None,
    ) -> None:

        self.config = config or SystemConfig()

        self._lock = threading.RLock()

        self._runner = CommandRunner(
            timeout=self.config.command_timeout
        )

        self._actions_executed = 0
        self._last_action: str | None = None

        logger.info(
            "SystemController initialized on %s.",
            get_platform_name(),
        )

    # ========================================================================
    # INTERNAL
    # ========================================================================

    def _record_action(
        self,
        action: str,
    ) -> None:
        """
        Record executed action.
        """

        self._actions_executed += 1
        self._last_action = action

        logger.info(
            "System action executed: %s",
            action,
        )

    # ========================================================================
    # POWER - SHUTDOWN
    # ========================================================================

    def shutdown(
        self,
        delay_seconds: int | None = None,
    ) -> bool:
        """
        Schedule system shutdown.
        """

        if delay_seconds is None:
            delay_seconds = (
                self.config.default_shutdown_delay
            )

        delay = _validate_delay(
            delay_seconds,
            "shutdown delay",
        )

        logger.warning(
            "System shutdown requested "
            "(delay=%ds).",
            delay,
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    self._runner.run(
                        [
                            "shutdown",
                            "/s",
                            "/t",
                            str(delay),
                        ]
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            'tell app "System Events" to shut down',
                        ]
                    )

                elif IS_LINUX:

                    minutes = max(
                        1,
                        delay // 60,
                    )

                    self._runner.run(
                        [
                            "shutdown",
                            "-h",
                            f"+{minutes}",
                        ]
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Shutdown is unsupported on "
                        "this platform."
                    )

                self._record_action(
                    "shutdown"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Shutdown failed: {exc}"
            ) from exc

    # ========================================================================
    # CANCEL SHUTDOWN
    # ========================================================================

    def cancel_shutdown(self) -> bool:
        """
        Cancel a previously scheduled shutdown.
        """

        logger.info(
            "Shutdown cancellation requested."
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    self._runner.run(
                        [
                            "shutdown",
                            "/a",
                        ]
                    )

                elif IS_LINUX:

                    self._runner.run(
                        [
                            "shutdown",
                            "-c",
                        ]
                    )

                elif IS_MAC:

                    logger.warning(
                        "Shutdown cancellation is not "
                        "universally supported on macOS."
                    )

                    return False

                else:

                    raise UnsupportedPlatformError(
                        "Shutdown cancellation is "
                        "unsupported on this platform."
                    )

                self._record_action(
                    "cancel_shutdown"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Could not cancel shutdown: {exc}"
            ) from exc

    # ========================================================================
    # RESTART
    # ========================================================================

    def restart(
        self,
        delay_seconds: int | None = None,
    ) -> bool:
        """
        Schedule system restart.
        """

        if delay_seconds is None:
            delay_seconds = (
                self.config.default_restart_delay
            )

        delay = _validate_delay(
            delay_seconds,
            "restart delay",
        )

        logger.warning(
            "System restart requested "
            "(delay=%ds).",
            delay,
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    self._runner.run(
                        [
                            "shutdown",
                            "/r",
                            "/t",
                            str(delay),
                        ]
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            'tell app "System Events" to restart',
                        ]
                    )

                elif IS_LINUX:

                    minutes = max(
                        1,
                        delay // 60,
                    )

                    self._runner.run(
                        [
                            "shutdown",
                            "-r",
                            f"+{minutes}",
                        ]
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Restart is unsupported on "
                        "this platform."
                    )

                self._record_action(
                    "restart"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Restart failed: {exc}"
            ) from exc

    # ========================================================================
    # SLEEP
    # ========================================================================

    def sleep(self) -> bool:
        """
        Put the computer into sleep mode.
        """

        logger.info(
            "System sleep requested."
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    self._runner.run(
                        [
                            "rundll32.exe",
                            "powrprof.dll,SetSuspendState",
                            "0,1,0",
                        ]
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "pmset",
                            "sleepnow",
                        ]
                    )

                elif IS_LINUX:

                    self._runner.run(
                        [
                            "systemctl",
                            "suspend",
                        ]
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Sleep is unsupported on "
                        "this platform."
                    )

                self._record_action(
                    "sleep"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Sleep failed: {exc}"
            ) from exc

    # ========================================================================
    # LOCK SCREEN
    # ========================================================================

    def lock_screen(self) -> bool:
        """
        Lock the current user session.
        """

        logger.info(
            "Screen lock requested."
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    self._runner.run(
                        [
                            "rundll32.exe",
                            "user32.dll,LockWorkStation",
                        ]
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            (
                                'tell application "System Events" '
                                'to keystroke "q" '
                                'using {control down, command down}'
                            ),
                        ]
                    )

                elif IS_LINUX:

                    commands = [
                        [
                            "loginctl",
                            "lock-session",
                        ],
                        [
                            "xdg-screensaver",
                            "lock",
                        ],
                    ]

                    success = False

                    for command in commands:

                        try:

                            self._runner.run(
                                command
                            )

                            success = True
                            break

                        except SystemControlError:
                            continue

                    if not success:

                        raise UnsupportedPlatformError(
                            "No supported Linux "
                            "screen-lock command found."
                        )

                else:

                    raise UnsupportedPlatformError(
                        "Screen lock is unsupported "
                        "on this platform."
                    )

                self._record_action(
                    "lock_screen"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Screen lock failed: {exc}"
            ) from exc

    # ========================================================================
    # WINDOWS VOLUME BACKEND
    # ========================================================================

    @staticmethod
    def _get_pycaw_volume_interface():
        """
        Return Windows master-volume interface.

        Requires:
            pycaw
            comtypes
        """

        if not IS_WINDOWS:

            raise UnsupportedPlatformError(
                "pycaw volume interface is only "
                "available on Windows."
            )

        try:

            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import (
                AudioUtilities,
                IAudioEndpointVolume,
            )

        except ImportError as exc:

            raise DependencyError(
                "Windows volume control requires "
                "'pycaw' and 'comtypes'. "
                "Install with: "
                "pip install pycaw comtypes"
            ) from exc

        try:

            devices = AudioUtilities.GetSpeakers()

            interface = devices.Activate(
                IAudioEndpointVolume._iid_,
                CLSCTX_ALL,
                None,
            )

            return cast(
                interface,
                POINTER(
                    IAudioEndpointVolume
                ),
            )

        except Exception as exc:

            raise SystemControlError(
                f"Could not initialize Windows "
                f"audio interface: {exc}"
            ) from exc

    # ========================================================================
    # GET VOLUME
    # ========================================================================

    def get_volume(self) -> int:
        """
        Return current system volume percentage.
        """

        try:

            if IS_WINDOWS:

                interface = (
                    self._get_pycaw_volume_interface()
                )

                value = (
                    interface
                    .GetMasterVolumeLevelScalar()
                )

                return _clamp_percent(
                    round(value * 100)
                )

            if IS_MAC:

                result = self._runner.run(
                    [
                        "osascript",
                        "-e",
                        (
                            "output volume of "
                            "(get volume settings)"
                        ),
                    ],
                    capture_output=True,
                )

                return _clamp_percent(
                    int(result.stdout.strip())
                )

            if IS_LINUX:

                return self._linux_get_volume()

            raise UnsupportedPlatformError(
                "Volume control is unsupported "
                "on this platform."
            )

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to get volume: {exc}"
            ) from exc

    # ========================================================================
    # WINDOWS / LINUX / MAC VOLUME SET
    # ========================================================================

    def set_volume(
        self,
        level_percent: int,
    ) -> bool:
        """
        Set system volume to an absolute level.

        Range:
            0 - 100
        """

        level = _validate_percent(
            level_percent,
            "volume",
        )

        logger.info(
            "Setting system volume to %d%%.",
            level,
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    interface = (
                        self._get_pycaw_volume_interface()
                    )

                    interface.SetMasterVolumeLevelScalar(
                        level / 100.0,
                        None,
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            f"set volume output volume {level}",
                        ]
                    )

                elif IS_LINUX:

                    self._linux_set_volume(
                        level
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Volume control is unsupported "
                        "on this platform."
                    )

                self._record_action(
                    f"set_volume:{level}"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to set volume: {exc}"
            ) from exc

    # ========================================================================
    # LINUX GET VOLUME
    # ========================================================================

    def _linux_get_volume(self) -> int:
        """
        Read Linux volume using pactl or amixer.
        """

        if shutil.which("pactl"):

            result = self._runner.run(
                [
                    "pactl",
                    "get-sink-volume",
                    "@DEFAULT_SINK@",
                ],
                capture_output=True,
            )

            output = result.stdout

            import re

            match = re.search(
                r"(\d+)%"
                ,
                output,
            )

            if match:

                return _clamp_percent(
                    int(match.group(1))
                )

        if shutil.which("amixer"):

            result = self._runner.run(
                [
                    "amixer",
                    "get",
                    "Master",
                ],
                capture_output=True,
            )

            output = result.stdout

            import re

            match = re.search(
                r"\[(\d+)%\]",
                output,
            )

            if match:

                return _clamp_percent(
                    int(match.group(1))
                )

        raise DependencyError(
            "Could not read Linux volume. "
            "Install/configure pactl or amixer."
        )

    # ========================================================================
    # LINUX SET VOLUME
    # ========================================================================

    def _linux_set_volume(
        self,
        level_percent: int,
    ) -> None:
        """
        Set Linux volume using pactl or amixer.
        """

        if shutil.which("pactl"):

            self._runner.run(
                [
                    "pactl",
                    "set-sink-volume",
                    "@DEFAULT_SINK@",
                    f"{level_percent}%",
                ]
            )

            return

        if shutil.which("amixer"):

            self._runner.run(
                [
                    "amixer",
                    "set",
                    "Master",
                    f"{level_percent}%",
                ]
            )

            return

        raise DependencyError(
            "Linux volume control requires "
            "'pactl' or 'amixer'."
        )

    # ========================================================================
    # ADJUST VOLUME
    # ========================================================================

    def adjust_volume(
        self,
        delta_percent: int,
    ) -> bool:
        """
        Adjust volume relatively.

        Example:
            adjust_volume(+10)
            adjust_volume(-10)
        """

        delta = _validate_delta(
            delta_percent,
            "volume delta",
        )

        logger.info(
            "Adjusting volume by %+d%%.",
            delta,
        )

        if IS_WINDOWS:

            current = self.get_volume()

            return self.set_volume(
                current + delta
            )

        if IS_MAC:

            direction = (
                "output volume of "
                "(get volume settings)"
            )

            expression = (
                f"set volume {direction} "
                f"+ ({delta})"
            )

            try:

                self._runner.run(
                    [
                        "osascript",
                        "-e",
                        expression,
                    ]
                )

                self._record_action(
                    f"adjust_volume:{delta}"
                )

                return True

            except Exception as exc:

                raise SystemControlError(
                    f"Failed to adjust volume: {exc}"
                ) from exc

        if IS_LINUX:

            if shutil.which("pactl"):

                sign = (
                    "+"
                    if delta >= 0
                    else "-"
                )

                amount = abs(delta)

                self._runner.run(
                    [
                        "pactl",
                        "set-sink-volume",
                        "@DEFAULT_SINK@",
                        f"{sign}{amount}%",
                    ]
                )

                self._record_action(
                    f"adjust_volume:{delta}"
                )

                return True

            if shutil.which("amixer"):

                sign = (
                    "+"
                    if delta >= 0
                    else "-"
                )

                amount = abs(delta)

                self._runner.run(
                    [
                        "amixer",
                        "set",
                        "Master",
                        f"{amount}%{sign}",
                    ]
                )

                self._record_action(
                    f"adjust_volume:{delta}"
                )

                return True

        raise UnsupportedPlatformError(
            "Relative volume control is unsupported "
            "on this platform."
        )

    # ========================================================================
    # CONVENIENCE VOLUME
    # ========================================================================

    def increase_volume(
        self,
        amount: int | None = None,
    ) -> bool:
        """
        Increase volume.
        """

        if amount is None:
            amount = self.config.volume_step

        amount = abs(int(amount))

        return self.adjust_volume(
            amount
        )

    def decrease_volume(
        self,
        amount: int | None = None,
    ) -> bool:
        """
        Decrease volume.
        """

        if amount is None:
            amount = self.config.volume_step

        amount = abs(int(amount))

        return self.adjust_volume(
            -amount
        )

    # ========================================================================
    # MUTE
    # ========================================================================

    def mute(self) -> bool:
        """
        Mute system audio.
        """

        logger.info(
            "Muting system audio."
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    interface = (
                        self._get_pycaw_volume_interface()
                    )

                    interface.SetMute(
                        1,
                        None,
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            "set volume output muted true",
                        ]
                    )

                elif IS_LINUX:

                    self._linux_mute(
                        True
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Mute is unsupported on "
                        "this platform."
                    )

                self._record_action(
                    "mute"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to mute: {exc}"
            ) from exc

    # ========================================================================
    # UNMUTE
    # ========================================================================

    def unmute(self) -> bool:
        """
        Unmute system audio.
        """

        logger.info(
            "Unmuting system audio."
        )

        try:

            with self._lock:

                if IS_WINDOWS:

                    interface = (
                        self._get_pycaw_volume_interface()
                    )

                    interface.SetMute(
                        0,
                        None,
                    )

                elif IS_MAC:

                    self._runner.run(
                        [
                            "osascript",
                            "-e",
                            "set volume output muted false",
                        ]
                    )

                elif IS_LINUX:

                    self._linux_mute(
                        False
                    )

                else:

                    raise UnsupportedPlatformError(
                        "Unmute is unsupported on "
                        "this platform."
                    )

                self._record_action(
                    "unmute"
                )

            return True

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to unmute: {exc}"
            ) from exc

    # ========================================================================
    # LINUX MUTE
    # ========================================================================

    def _linux_mute(
        self,
        muted: bool,
    ) -> None:
        """
        Mute/unmute Linux audio.
        """

        state = (
            "1"
            if muted
            else "0"
        )

        if shutil.which("pactl"):

            self._runner.run(
                [
                    "pactl",
                    "set-sink-mute",
                    "@DEFAULT_SINK@",
                    state,
                ]
            )

            return

        if shutil.which("amixer"):

            action = (
                "mute"
                if muted
                else "unmute"
            )

            self._runner.run(
                [
                    "amixer",
                    "set",
                    "Master",
                    action,
                ]
            )

            return

        raise DependencyError(
            "Linux mute control requires "
            "'pactl' or 'amixer'."
        )

    # ========================================================================
    # TOGGLE MUTE
    # ========================================================================

    def toggle_mute(self) -> bool:
        """
        Toggle system mute state.
        """

        try:

            if IS_WINDOWS:

                interface = (
                    self._get_pycaw_volume_interface()
                )

                current = (
                    interface.GetMute()
                )

                interface.SetMute(
                    0 if current else 1,
                    None,
                )

                self._record_action(
                    "toggle_mute"
                )

                return True

            if IS_MAC:

                self._runner.run(
                    [
                        "osascript",
                        "-e",
                        (
                            "set currentMute to "
                            "(output muted of "
                            "(get volume settings))\n"
                            "set volume output muted "
                            "not currentMute"
                        ),
                    ]
                )

                self._record_action(
                    "toggle_mute"
                )

                return True

            if IS_LINUX:

                if shutil.which("pactl"):

                    self._runner.run(
                        [
                            "pactl",
                            "set-sink-mute",
                            "@DEFAULT_SINK@",
                            "toggle",
                        ]
                    )

                    self._record_action(
                        "toggle_mute"
                    )

                    return True

                raise DependencyError(
                    "Linux toggle mute requires pactl."
                )

            raise UnsupportedPlatformError(
                "Mute toggle is unsupported."
            )

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to toggle mute: {exc}"
            ) from exc

    # ========================================================================
    # BRIGHTNESS BACKEND
    # ========================================================================

    @staticmethod
    def _get_brightness_backend():
        """
        Lazily import screen-brightness-control.
        """

        try:

            import screen_brightness_control as sbc

            return sbc

        except ImportError as exc:

            raise DependencyError(
                "Brightness control requires "
                "'screen-brightness-control'. "
                "Install with: "
                "pip install screen-brightness-control"
            ) from exc

    # ========================================================================
    # GET BRIGHTNESS
    # ========================================================================

    def get_brightness(self) -> int:
        """
        Return current display brightness.
        """

        try:

            sbc = (
                self._get_brightness_backend()
            )

            current = sbc.get_brightness(
                display=0
            )

            if isinstance(
                current,
                list,
            ):

                if not current:

                    raise SystemControlError(
                        "Brightness backend returned "
                        "an empty result."
                    )

                current = current[0]

            return _clamp_percent(
                int(current)
            )

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to get brightness: {exc}"
            ) from exc

    # ========================================================================
    # SET BRIGHTNESS
    # ========================================================================

    def set_brightness(
        self,
        level_percent: int,
    ) -> bool:
        """
        Set screen brightness.

        Range:
            0 - 100
        """

        level = _validate_percent(
            level_percent,
            "brightness",
        )

        logger.info(
            "Setting brightness to %d%%.",
            level,
        )

        try:

            with self._lock:

                sbc = (
                    self._get_brightness_backend()
                )

                sbc.set_brightness(
                    level
                )

                self._record_action(
                    f"set_brightness:{level}"
                )

            return True

        except DependencyError:

            if IS_LINUX:

                if shutil.which(
                    "brightnessctl"
                ):

                    self._runner.run(
                        [
                            "brightnessctl",
                            "set",
                            f"{level}%",
                        ]
                    )

                    self._record_action(
                        f"set_brightness:{level}"
                    )

                    return True

            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to set brightness: {exc}"
            ) from exc

    # ========================================================================
    # ADJUST BRIGHTNESS
    # ========================================================================

    def adjust_brightness(
        self,
        delta_percent: int,
    ) -> bool:
        """
        Adjust brightness relatively.
        """

        delta = _validate_delta(
            delta_percent,
            "brightness delta",
        )

        logger.info(
            "Adjusting brightness by %+d%%.",
            delta,
        )

        try:

            current = (
                self.get_brightness()
            )

            target = _clamp_percent(
                current + delta
            )

            return self.set_brightness(
                target
            )

        except SystemControlError:
            raise

        except Exception as exc:

            raise SystemControlError(
                f"Failed to adjust brightness: {exc}"
            ) from exc

    # ========================================================================
    # BRIGHTNESS CONVENIENCE
    # ========================================================================

    def increase_brightness(
        self,
        amount: int | None = None,
    ) -> bool:
        """
        Increase brightness.
        """

        if amount is None:
            amount = (
                self.config.brightness_step
            )

        amount = abs(int(amount))

        return self.adjust_brightness(
            amount
        )

    def decrease_brightness(
        self,
        amount: int | None = None,
    ) -> bool:
        """
        Decrease brightness.
        """

        if amount is None:
            amount = (
                self.config.brightness_step
            )

        amount = abs(int(amount))

        return self.adjust_brightness(
            -amount
        )

    # ========================================================================
    # AVAILABILITY
    # ========================================================================

    def is_volume_available(self) -> bool:
        """
        Check whether volume control is available.
        """

        try:

            if IS_WINDOWS:

                self._get_pycaw_volume_interface()
                return True

            if IS_MAC:

                return shutil.which(
                    "osascript"
                ) is not None

            if IS_LINUX:

                return (
                    shutil.which("pactl")
                    is not None
                    or
                    shutil.which("amixer")
                    is not None
                )

            return False

        except Exception:

            return False

    def is_brightness_available(self) -> bool:
        """
        Check whether brightness control is available.
        """

        try:

            self._get_brightness_backend()

            return True

        except Exception:

            if IS_LINUX:

                return (
                    shutil.which(
                        "brightnessctl"
                    )
                    is not None
                )

            return False

    # ========================================================================
    # NATURAL LANGUAGE COMMAND
    # ========================================================================

    @staticmethod
    def normalize_command(
        command: str,
    ) -> str:
        """
        Normalize natural-language system command.
        """

        if not isinstance(command, str):

            raise ValidationError(
                "System command must be a string."
            )

        return (
            command
            .strip()
            .lower()
            .replace("_", " ")
            .replace("-", " ")
        )

    def execute_command(
        self,
        command: str,
    ) -> SystemCommandResult:
        """
        Execute a natural-language system command.

        Supported examples
        ------------------
        shutdown
        restart
        sleep
        lock screen

        volume up
        volume down
        volume 50
        mute
        unmute

        brightness up
        brightness down
        brightness 70

        get volume
        get brightness
        system info
        """

        normalized = self.normalize_command(
            command
        )

        if not normalized:

            return SystemCommandResult(
                False,
                "unknown",
                "System command is empty.",
            )

        try:

            # ---------------------------------------------------------------
            # POWER
            # ---------------------------------------------------------------

            if normalized in {
                "shutdown",
                "shut down",
                "power off",
            }:

                self.shutdown()

                return SystemCommandResult(
                    True,
                    "shutdown",
                    "Shutdown command executed.",
                )

            if normalized in {
                "cancel shutdown",
                "abort shutdown",
            }:

                success = (
                    self.cancel_shutdown()
                )

                return SystemCommandResult(
                    success,
                    "cancel_shutdown",
                    (
                        "Shutdown cancellation "
                        "executed."
                        if success
                        else
                        "Shutdown cancellation is "
                        "not supported."
                    ),
                )

            if normalized in {
                "restart",
                "reboot",
            }:

                self.restart()

                return SystemCommandResult(
                    True,
                    "restart",
                    "Restart command executed.",
                )

            if normalized in {
                "sleep",
                "sleep computer",
                "put computer to sleep",
            }:

                self.sleep()

                return SystemCommandResult(
                    True,
                    "sleep",
                    "Sleep command executed.",
                )

            if normalized in {
                "lock",
                "lock screen",
                "lock computer",
            }:

                self.lock_screen()

                return SystemCommandResult(
                    True,
                    "lock_screen",
                    "Screen locked.",
                )

            # ---------------------------------------------------------------
            # VOLUME
            # ---------------------------------------------------------------

            if normalized in {
                "volume up",
                "increase volume",
                "volume increase",
                "turn volume up",
            }:

                self.increase_volume()

                return SystemCommandResult(
                    True,
                    "increase_volume",
                    "Volume increased.",
                    {
                        "volume": self.get_volume()
                    },
                )

            if normalized in {
                "volume down",
                "decrease volume",
                "volume decrease",
                "turn volume down",
            }:

                self.decrease_volume()

                return SystemCommandResult(
                    True,
                    "decrease_volume",
                    "Volume decreased.",
                    {
                        "volume": self.get_volume()
                    },
                )

            if normalized in {
                "mute",
                "mute volume",
                "silent",
            }:

                self.mute()

                return SystemCommandResult(
                    True,
                    "mute",
                    "System audio muted.",
                )

            if normalized in {
                "unmute",
                "unmute volume",
                "sound on",
            }:

                self.unmute()

                return SystemCommandResult(
                    True,
                    "unmute",
                    "System audio unmuted.",
                )

            if normalized in {
                "toggle mute",
                "toggle volume mute",
            }:

                self.toggle_mute()

                return SystemCommandResult(
                    True,
                    "toggle_mute",
                    "Mute state toggled.",
                )

            if normalized in {
                "get volume",
                "volume",
                "current volume",
            }:

                volume = (
                    self.get_volume()
                )

                return SystemCommandResult(
                    True,
                    "get_volume",
                    f"Current volume is {volume}%.",
                    {
                        "volume": volume
                    },
                )

            # ---------------------------------------------------------------
            # BRIGHTNESS
            # ---------------------------------------------------------------

            if normalized in {
                "brightness up",
                "increase brightness",
                "brightness increase",
            }:

                self.increase_brightness()

                return SystemCommandResult(
                    True,
                    "increase_brightness",
                    "Brightness increased.",
                    {
                        "brightness":
                            self.get_brightness()
                    },
                )

            if normalized in {
                "brightness down",
                "decrease brightness",
                "brightness decrease",
            }:

                self.decrease_brightness()

                return SystemCommandResult(
                    True,
                    "decrease_brightness",
                    "Brightness decreased.",
                    {
                        "brightness":
                            self.get_brightness()
                    },
                )

            if normalized in {
                "get brightness",
                "brightness",
                "current brightness",
            }:

                brightness = (
                    self.get_brightness()
                )

                return SystemCommandResult(
                    True,
                    "get_brightness",
                    (
                        f"Current brightness is "
                        f"{brightness}%."
                    ),
                    {
                        "brightness": brightness
                    },
                )

            # ---------------------------------------------------------------
            # VOLUME NUMBER
            # ---------------------------------------------------------------

            if normalized.startswith(
                "volume "
            ):

                parts = normalized.split()

                if len(parts) == 2:

                    try:

                        level = int(
                            parts[1]
                        )

                        self.set_volume(
                            level
                        )

                        return SystemCommandResult(
                            True,
                            "set_volume",
                            (
                                f"Volume set to "
                                f"{level}%."
                            ),
                            {
                                "volume": level
                            },
                        )

                    except ValueError:
                        pass

            # ---------------------------------------------------------------
            # BRIGHTNESS NUMBER
            # ---------------------------------------------------------------

            if normalized.startswith(
                "brightness "
            ):

                parts = normalized.split()

                if len(parts) == 2:

                    try:

                        level = int(
                            parts[1]
                        )

                        self.set_brightness(
                            level
                        )

                        return SystemCommandResult(
                            True,
                            "set_brightness",
                            (
                                f"Brightness set "
                                f"to {level}%."
                            ),
                            {
                                "brightness": level
                            },
                        )

                    except ValueError:
                        pass

            # ---------------------------------------------------------------
            # SYSTEM INFO
            # ---------------------------------------------------------------

            if normalized in {
                "system info",
                "system information",
                "platform info",
                "computer info",
            }:

                info = (
                    get_platform_info()
                    .to_dict()
                )

                return SystemCommandResult(
                    True,
                    "system_info",
                    "System information retrieved.",
                    info,
                )

            return SystemCommandResult(
                False,
                "unknown",
                (
                    f"Unknown system command: "
                    f"{command}"
                ),
            )

        except SystemControlError as exc:

            logger.warning(
                "System command failed: %s",
                exc,
            )

            return SystemCommandResult(
                False,
                "error",
                str(exc),
            )

        except Exception as exc:

            logger.exception(
                "Unexpected system command error."
            )

            return SystemCommandResult(
                False,
                "error",
                str(exc),
            )

    # ========================================================================
    # ASYNC API
    # ========================================================================

    async def async_shutdown(
        self,
        delay_seconds: int | None = None,
    ) -> bool:

        return await asyncio.to_thread(
            self.shutdown,
            delay_seconds,
        )

    async def async_restart(
        self,
        delay_seconds: int | None = None,
    ) -> bool:

        return await asyncio.to_thread(
            self.restart,
            delay_seconds,
        )

    async def async_sleep(self) -> bool:

        return await asyncio.to_thread(
            self.sleep
        )

    async def async_lock_screen(self) -> bool:

        return await asyncio.to_thread(
            self.lock_screen
        )

    async def async_set_volume(
        self,
        level_percent: int,
    ) -> bool:

        return await asyncio.to_thread(
            self.set_volume,
            level_percent,
        )

    async def async_adjust_volume(
        self,
        delta_percent: int,
    ) -> bool:

        return await asyncio.to_thread(
            self.adjust_volume,
            delta_percent,
        )

    async def async_set_brightness(
        self,
        level_percent: int,
    ) -> bool:

        return await asyncio.to_thread(
            self.set_brightness,
            level_percent,
        )

    async def async_adjust_brightness(
        self,
        delta_percent: int,
    ) -> bool:

        return await asyncio.to_thread(
            self.adjust_brightness,
            delta_percent,
        )

    async def async_execute_command(
        self,
        command: str,
    ) -> SystemCommandResult:

        return await asyncio.to_thread(
            self.execute_command,
            command,
        )

    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """
        Return system-controller diagnostics.
        """

        info = (
            get_platform_info()
            .to_dict()
        )

        return {
            "platform": info,
            "volume_available":
                self.is_volume_available(),
            "brightness_available":
                self.is_brightness_available(),
            "actions_executed":
                self._actions_executed,
            "last_action":
                self._last_action,
            "config": {
                "shutdown_delay":
                    self.config.default_shutdown_delay,
                "restart_delay":
                    self.config.default_restart_delay,
                "volume_step":
                    self.config.volume_step,
                "brightness_step":
                    self.config.brightness_step,
                "command_timeout":
                    self.config.command_timeout,
            },
        }

    # ========================================================================
    # RESET STATISTICS
    # ========================================================================

    def reset_statistics(self) -> None:
        """
        Reset action statistics.
        """

        with self._lock:

            self._actions_executed = 0
            self._last_action = None

        logger.info(
            "System controller statistics reset."
        )

    # ========================================================================
    # CONTEXT MANAGER
    # ========================================================================

    def __enter__(
        self,
    ) -> SystemController:

        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:

        logger.debug(
            "SystemController context closed."
        )

    # ========================================================================
    # REPRESENTATION
    # ========================================================================

    def __repr__(self) -> str:

        return (
            "<SystemController "
            f"platform={get_platform_name()} "
            f"actions={self._actions_executed}>"
        )


# ============================================================================
# SINGLETON
# ============================================================================


_default_controller: SystemController | None = None

_controller_lock = threading.Lock()


def get_system_controller() -> SystemController:
    """
    Return shared AssistantX SystemController.
    """

    global _default_controller

    with _controller_lock:

        if _default_controller is None:

            _default_controller = (
                SystemController()
            )

        return _default_controller


# ============================================================================
# BACKWARD-COMPATIBLE MODULE FUNCTIONS
# ============================================================================


def shutdown(
    delay_seconds: int = 5,
) -> bool:
    """Schedule system shutdown."""

    return (
        get_system_controller()
        .shutdown(delay_seconds)
    )

#UPDATED 


def safe_shutdown() -> bool:
    """
    Safely shut down the system.

    This function wraps :func:`shutdown` and prevents expected
    system automation errors from propagating to higher-level callers.

    Returns:
        bool:
            ``True`` if the shutdown operation is initiated successfully;
            otherwise ``False``.
    """
    try:
        success = shutdown()

        if not success:
            logger.warning(
                "System shutdown operation returned unsuccessful status."
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to shut down the system safely: %s",
            exc,
        )
        return False


def cancel_shutdown() -> bool:
    """Cancel scheduled shutdown."""

    return (
        get_system_controller()
        .cancel_shutdown()
    )


def restart(
    delay_seconds: int = 5,
) -> bool:
    """Schedule system restart."""

    return (
        get_system_controller()
        .restart(delay_seconds)
    )

#UPDATED 

def safe_restart() -> bool:
    """
    Safely restart the system.

    This function wraps :func:`restart` and prevents expected
    system automation errors from propagating to higher-level callers.

    Returns:
        bool:
            ``True`` if the restart operation is initiated successfully;
            otherwise ``False``.
    """
    try:
        success = restart()

        if not success:
            logger.warning(
                "System restart operation returned unsuccessful status."
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to restart the system safely: %s",
            exc,
        )
        return False


def sleep() -> bool:
    """Put computer to sleep."""

    return (
        get_system_controller()
        .sleep()
    )

#UPDATED 


def safe_sleep(seconds: float) -> bool:
    """
    Safely put the system into sleep mode.

    Args:
        seconds: Duration to wait before returning, in seconds.

    Returns:
        True if the sleep operation succeeds; otherwise False.
    """
    try:
        success = sleep(seconds)

        if not success:
            logger.warning(
                "System sleep operation returned unsuccessful status "
                "for duration=%s seconds.",
                seconds,
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to execute system sleep safely "
            "(duration=%s seconds): %s",
            seconds,
            exc,
        )
        return False


def lock_screen() -> bool:
    """Lock current user session."""

    return (
        get_system_controller()
        .lock_screen()
    )

def lock_system() -> bool:
    """
    Compatibility alias for :func:`lock`.
    """
    return lock()

# UPDATED 

def safe_lock_screen() -> bool:
    """
    Safely lock the current user's screen.

    This is a defensive wrapper around :func:`lock_screen`.
    Any expected system automation failure is caught and logged
    instead of propagating to the caller.

    Returns:
        bool:
            ``True`` when the screen was locked successfully;
            otherwise ``False``.
    """
    try:
        success = lock_screen()

        if not success:
            logger.warning(
                "Screen lock operation returned unsuccessful status."
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to lock screen safely: %s",
            exc,
        )
        return False


# ============================================================================
# VOLUME FUNCTIONS
# ============================================================================


def get_volume() -> int:
    """Get current volume."""

    return (
        get_system_controller()
        .get_volume()
    )


def set_volume(
    level_percent: int,
) -> bool:
    """Set system volume."""

    return (
        get_system_controller()
        .set_volume(level_percent)
    )

# UPDATED 


def safe_set_volume(level: int) -> bool:
    """
    Safely set the system volume level.

    Args:
        level: Desired system volume level, typically from 0 to 100.

    Returns:
        True if the volume was changed successfully;
        otherwise False.
    """
    try:
        success = set_volume(level)

        if not success:
            logger.warning(
                "System volume operation returned unsuccessful status "
                "for level=%s.",
                level,
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to set system volume safely "
            "(level=%s): %s",
            level,
            exc,
        )
        return False


def adjust_volume(
    delta_percent: int,
) -> bool:
    """Adjust system volume."""

    return (
        get_system_controller()
        .adjust_volume(delta_percent)
    )


def increase_volume(
    amount: int = 10,
) -> bool:
    """Increase volume."""

    return (
        get_system_controller()
        .increase_volume(amount)
    )


def decrease_volume(
    amount: int = 10,
) -> bool:
    """Decrease volume."""

    return (
        get_system_controller()
        .decrease_volume(amount)
    )


def mute() -> bool:
    """Mute system audio."""

    return (
        get_system_controller()
        .mute()
    )

#UPDATED

def safe_mute() -> bool:
    """
    Safely mute the system audio.

    This function wraps :func:`mute` and prevents expected system
    automation errors from propagating to higher-level callers.

    Returns:
        bool:
            ``True`` if the mute operation succeeds;
            otherwise ``False``.
    """
    try:
        success = mute()

        if not success:
            logger.warning(
                "System mute operation returned unsuccessful status."
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to mute system audio safely: %s",
            exc,
        )
        return False


def unmute() -> bool:
    """Unmute system audio."""

    return (
        get_system_controller()
        .unmute()
    )

#UPDATED 


def safe_unmute() -> bool:
    """
    Safely unmute the system audio.

    This function wraps :func:`unmute` and prevents expected
    system automation errors from propagating to higher-level callers.

    Returns:
        bool:
            ``True`` if the unmute operation succeeds;
            otherwise ``False``.
    """
    try:
        success = unmute()

        if not success:
            logger.warning(
                "System unmute operation returned unsuccessful status."
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to unmute system audio safely: %s",
            exc,
        )
        return False


def toggle_mute() -> bool:
    """Toggle mute."""

    return (
        get_system_controller()
        .toggle_mute()
    )

# updated


def safe_adjust_volume(delta_percent: int) -> bool:
    """Safely adjust system volume by a relative percentage without raising exceptions.

    Args:
        delta_percent: Relative volume change percentage (positive or negative).

    Returns:
        bool: True if volume was adjusted successfully, False otherwise.
    """
    try:
        if "adjust_volume" in globals():
            return bool(globals()["adjust_volume"](delta_percent))
        return False
    except Exception as exc:
        logger.warning("Safe volume adjustment failed: %s", exc)
        return False



# ============================================================================
# BRIGHTNESS FUNCTIONS
# ============================================================================


def get_brightness() -> int:
    """Get current brightness."""

    return (
        get_system_controller()
        .get_brightness()
    )


def set_brightness(
    level_percent: int,
) -> bool:
    """Set screen brightness."""

    return (
        get_system_controller()
        .set_brightness(
            level_percent
        )
    )

# UPDATED 

def safe_set_brightness(level: int) -> bool:
    """
    Safely set the system display brightness.

    This function wraps :func:`set_brightness` and prevents expected
    system automation errors from propagating to higher-level callers.

    Args:
        level: Desired brightness level, typically from 0 to 100.

    Returns:
        True if the brightness was changed successfully,
        otherwise False.
    """
    try:
        success = set_brightness(level)

        if not success:
            logger.warning(
                "System brightness operation returned unsuccessful status "
                "for level=%s.",
                level,
            )

        return bool(success)

    except SystemAutomationError as exc:
        logger.warning(
            "Unable to set system brightness safely "
            "(level=%s): %s",
            level,
            exc,
        )
        return False


def adjust_brightness(
    delta_percent: int,
) -> bool:
    """Adjust brightness."""

    return (
        get_system_controller()
        .adjust_brightness(
            delta_percent
        )
    )


def increase_brightness(
    amount: int = 10,
) -> bool:
    """Increase brightness."""

    return (
        get_system_controller()
        .increase_brightness(amount)
    )


def decrease_brightness(
    amount: int = 10,
) -> bool:
    """Decrease brightness."""

    return (
        get_system_controller()
        .decrease_brightness(amount)
    )

# UPDATED 

def safe_adjust_brightness(level: int) -> bool:
    """Safely adjust display brightness level without raising exceptions.

    Args:
        level (int): Target brightness percentage (0-100).

    Returns:
        bool: True if brightness was successfully adjusted, False otherwise.
    """
    try:
        # If adjust_brightness or set_brightness function exists in system.py
        if "adjust_brightness" in globals():
            return bool(globals()["adjust_brightness"](level))
        elif "set_brightness" in globals():
            return bool(globals()["set_brightness"](level))
        return False
    except Exception as exc:
        logger.warning("Failed to adjust brightness to %s%%: %s", level, exc)
        return False



# ============================================================================
# COMMAND API
# ============================================================================


def execute_command(
    command: str,
) -> SystemCommandResult:
    """
    Execute natural-language system command.
    """

    return (
        get_system_controller()
        .execute_command(command)
    )


# ============================================================================
# DIAGNOSTICS API
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return system diagnostics.
    """

    return (
        get_system_controller()
        .diagnostics()
    )


def is_available() -> bool:
    """
    Return whether basic system automation is available.
    """

    return (
        IS_WINDOWS
        or IS_LINUX
        or IS_MAC
    )


# ============================================================================
# MODULE METADATA
# ============================================================================


__title__ = "AssistantX System Automation"
__version__ = "2.0.0"
__author__ = "AssistantX Team"


__all__ = [
    # Exceptions
    "SystemControlError",
    "SystemOperationError",
    "UnsupportedPlatformError",
    "DependencyError",
    "CommandExecutionError",
    "ValidationError",
    "SystemValidationError",

    # Data classes
    "PlatformInfo",
    "SystemConfig",
    "SystemCommandResult",

    # Controller
    "SystemController",
    "get_system_controller",

    # Platform
    "get_platform_info",
    "get_platform_name",

    # Availability
    "is_available",

    # Power
    "shutdown",
    "safe_shutdown",
    "cancel_shutdown",
    "restart",
    "safe_restart",
    "sleep",
    "safe_sleep",
    "lock_screen",
    "lock_system",
    "safe_lock_screen",

    # Volume
    "get_volume",
    "set_volume",
    "safe_set_volume",
    "adjust_volume",
    "increase_volume",
    "decrease_volume",
    "mute",
    "safe_mute",
    "unmute",
    "safe_unmute",
    "toggle_mute",
    "safe_adjust_volume",

    # Brightness
    "get_brightness",
    "set_brightness",
    "safe_set_brightness",
    "adjust_brightness",
    "increase_brightness",
    "decrease_brightness",
    "safe_adjust_brightness",

    # Command
    "execute_command",

    # Diagnostics
    "diagnostics",
]


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================


if __name__ == "__main__":

    print("=" * 72)
    print("AssistantX System Automation")
    print("=" * 72)

    print(
        "Platform:",
        get_platform_name(),
    )

    print(
        "System automation available:",
        is_available(),
    )

    controller = SystemController()

    print()
    print("Diagnostics")
    print("-" * 72)

    diagnostics_data = (
        controller.diagnostics()
    )

    for key, value in diagnostics_data.items():

        print(
            f"{key}: {value}"
        )

    print()
    print("-" * 72)
    print(
        "SystemController initialized successfully."
    )
    print(
        "No destructive action was executed."
    )
    print("=" * 72)
    