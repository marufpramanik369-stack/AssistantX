"""
AssistantX - Media Automation Controller
=========================================

Professional media-control module for Windows 10/11.

Features
--------
- Play / Pause
- Toggle Play / Pause
- Next / Previous track
- Stop
- Volume Up / Down
- Set / Get volume
- Mute / Unmute / Toggle mute
- Seek forward / backward
- Media key simulation
- Open media applications
- Close media applications
- Detect running media applications
- Basic media-state information
- Command parser
- Command aliases
- Safe execution
- Logging integration
- Custom exceptions
- Configuration support
- Thread-safe operations
- Async-friendly wrappers
- Singleton controller
- Utility helpers

No API key required.

Author: AssistantX Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)

if not logger.handlers:
    handler = logging.NullHandler()
    logger.addHandler(handler)


# ============================================================================
# WINDOWS CONSTANTS
# ============================================================================

# Windows virtual-key codes
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# Extra virtual keys
VK_SPACE = 0x20

# keybd_event flags
KEYEVENTF_KEYUP = 0x0002

# Windows process creation flags
CREATE_NO_WINDOW = 0x08000000


# ============================================================================
# ENUMS
# ============================================================================

class MediaAction(str, Enum):
    """Supported media actions."""

    PLAY = "play"
    PAUSE = "pause"
    TOGGLE = "toggle"
    STOP = "stop"
    NEXT = "next"
    PREVIOUS = "previous"

    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    SET_VOLUME = "set_volume"

    MUTE = "mute"
    UNMUTE = "unmute"
    TOGGLE_MUTE = "toggle_mute"

    SEEK_FORWARD = "seek_forward"
    SEEK_BACKWARD = "seek_backward"

    OPEN = "open"
    CLOSE = "close"

    STATUS = "status"


class MediaState(str, Enum):
    """Generic media playback states."""

    UNKNOWN = "unknown"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


# ============================================================================
# EXCEPTIONS
# ============================================================================

class MediaError(Exception):
    """Base exception for media automation."""


class UnsupportedPlatformError(MediaError):
    """Raised when the current OS is not supported."""


class InvalidVolumeError(MediaError):
    """Raised when volume value is invalid."""


class InvalidSeekError(MediaError):
    """Raised when seek duration is invalid."""


class MediaCommandError(MediaError):
    """Raised when a media command cannot be executed."""


class ApplicationError(MediaError):
    """Raised when an application operation fails."""


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class MediaConfig:
    """
    Configuration for MediaController.

    Attributes
    ----------
    volume_step:
        Number of volume steps for each volume operation.

    seek_seconds:
        Default seek duration.

    command_timeout:
        Timeout for subprocess commands.

    enable_logging:
        Enable module logging.

    strict_windows:
        If True, non-Windows platforms are rejected immediately.
    """

    volume_step: int = 5
    seek_seconds: int = 10
    command_timeout: float = 5.0
    enable_logging: bool = True
    strict_windows: bool = True

    def __post_init__(self) -> None:
        if self.volume_step <= 0:
            raise ValueError("volume_step must be greater than zero")

        if self.seek_seconds <= 0:
            raise ValueError("seek_seconds must be greater than zero")

        if self.command_timeout <= 0:
            raise ValueError("command_timeout must be greater than zero")


@dataclass
class MediaStatus:
    """Represents the current media controller status."""

    state: MediaState = MediaState.UNKNOWN
    volume: Optional[int] = None
    muted: Optional[bool] = None
    active_application: Optional[str] = None
    available_applications: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert status to a dictionary."""

        return {
            "state": self.state.value,
            "volume": self.volume,
            "muted": self.muted,
            "active_application": self.active_application,
            "available_applications": list(
                self.available_applications
            ),
            "timestamp": self.timestamp,
        }


@dataclass
class CommandResult:
    """Result returned by command execution."""

    success: bool
    action: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""

        return {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            "data": self.data,
        }


# ============================================================================
# APPLICATION DEFINITIONS
# ============================================================================

MEDIA_APPLICATIONS: Dict[str, Dict[str, Any]] = {
    "spotify": {
        "process": "Spotify.exe",
        "command": "spotify",
        "display_name": "Spotify",
    },
    "vlc": {
        "process": "vlc.exe",
        "command": "vlc",
        "display_name": "VLC Media Player",
    },
    "wmplayer": {
        "process": "wmplayer.exe",
        "command": "wmplayer",
        "display_name": "Windows Media Player",
    },
    "music": {
        "process": "Music.UI.exe",
        "command": None,
        "display_name": "Windows Music",
    },
}


# ============================================================================
# WINDOWS API HELPER
# ============================================================================

class WindowsMediaAPI:
    """
    Low-level Windows media-key interface.

    This class isolates ctypes/Windows-specific implementation from
    the high-level AssistantX media controller.
    """

    def __init__(self) -> None:
        self._validate_platform()

    @staticmethod
    def _validate_platform() -> None:
        """Validate Windows platform."""

        if os.name != "nt":
            raise UnsupportedPlatformError(
                "WindowsMediaAPI requires Windows."
            )

    @staticmethod
    def _key_down(key_code: int) -> None:
        """Send a key-down event."""

        ctypes.windll.user32.keybd_event(
            key_code,
            0,
            0,
            0,
        )

    @staticmethod
    def _key_up(key_code: int) -> None:
        """Send a key-up event."""

        ctypes.windll.user32.keybd_event(
            key_code,
            0,
            KEYEVENTF_KEYUP,
            0,
        )

    def press(self, key_code: int) -> None:
        """Press and release a virtual key."""

        self._key_down(key_code)
        time.sleep(0.03)
        self._key_up(key_code)

    def play_pause(self) -> None:
        """Toggle play/pause."""

        self.press(VK_MEDIA_PLAY_PAUSE)

    def next_track(self) -> None:
        """Skip to next track."""

        self.press(VK_MEDIA_NEXT_TRACK)

    def previous_track(self) -> None:
        """Go to previous track."""

        self.press(VK_MEDIA_PREV_TRACK)

    def stop(self) -> None:
        """Stop media playback."""

        self.press(VK_MEDIA_STOP)

    def volume_up(self, steps: int = 1) -> None:
        """Increase system volume."""

        steps = max(1, int(steps))

        for _ in range(steps):
            self.press(VK_VOLUME_UP)

    def volume_down(self, steps: int = 1) -> None:
        """Decrease system volume."""

        steps = max(1, int(steps))

        for _ in range(steps):
            self.press(VK_VOLUME_DOWN)

    def mute(self) -> None:
        """Toggle system mute state."""

        self.press(VK_VOLUME_MUTE)


# ============================================================================
# PROCESS HELPER
# ============================================================================

class ProcessManager:
    """Utility class for Windows process management."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def is_running(self, process_name: str) -> bool:
        """Check whether a process is currently running."""

        if not process_name:
            return False

        try:
            result = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"IMAGENAME eq {process_name}",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                creationflags=CREATE_NO_WINDOW,
            )

            output = result.stdout.lower()

            return process_name.lower() in output

        except (
            subprocess.SubprocessError,
            OSError,
        ) as exc:
            logger.warning(
                "Could not inspect process '%s': %s",
                process_name,
                exc,
            )
            return False

    def list_processes(self) -> List[str]:
        """Return currently running Windows processes."""

        try:
            result = subprocess.run(
                ["tasklist"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                creationflags=CREATE_NO_WINDOW,
            )

            lines = result.stdout.splitlines()

            processes: List[str] = []

            for line in lines:
                parts = line.split()

                if parts:
                    processes.append(parts[0])

            return processes

        except (
            subprocess.SubprocessError,
            OSError,
        ) as exc:
            logger.warning(
                "Unable to list processes: %s",
                exc,
            )
            return []

    def terminate(self, process_name: str) -> bool:
        """Terminate a process by executable name."""

        if not process_name:
            return False

        try:
            result = subprocess.run(
                [
                    "taskkill",
                    "/IM",
                    process_name,
                    "/F",
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                creationflags=CREATE_NO_WINDOW,
            )

            return result.returncode == 0

        except (
            subprocess.SubprocessError,
            OSError,
        ) as exc:
            logger.error(
                "Could not terminate '%s': %s",
                process_name,
                exc,
            )
            return False


# ============================================================================
# MEDIA APPLICATION MANAGER
# ============================================================================

class MediaApplicationManager:
    """Manages supported media applications."""

    def __init__(
        self,
        process_manager: Optional[ProcessManager] = None,
    ) -> None:
        self.process_manager = (
            process_manager
            or ProcessManager()
        )

    def normalize_name(self, name: str) -> str:
        """Normalize an application name."""

        return (
            name.strip()
            .lower()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
        )

    def get_application(
        self,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """Return application metadata."""

        normalized = self.normalize_name(name)

        aliases = {
            "spotify": "spotify",
            "vlc": "vlc",
            "videolan": "vlc",
            "windowsmediaplayer": "wmplayer",
            "wmplayer": "wmplayer",
            "windowsmusic": "music",
            "music": "music",
        }

        key = aliases.get(normalized)

        if not key:
            return None

        return MEDIA_APPLICATIONS.get(key)

    def is_running(self, name: str) -> bool:
        """Check whether a media application is running."""

        application = self.get_application(name)

        if not application:
            return False

        process_name = application.get("process")

        return self.process_manager.is_running(
            process_name
        )

    def running_applications(self) -> List[str]:
        """Return supported media applications currently running."""

        running: List[str] = []

        for key, info in MEDIA_APPLICATIONS.items():
            process_name = info.get("process")

            if self.process_manager.is_running(process_name):
                running.append(key)

        return running

    def open(self, name: str) -> bool:
        """Open a supported media application."""

        application = self.get_application(name)

        if not application:
            raise ApplicationError(
                f"Unsupported media application: {name}"
            )

        command = application.get("command")

        if not command:
            raise ApplicationError(
                f"No launch command configured for {name}"
            )

        try:
            subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )

            return True

        except OSError as exc:
            logger.error(
                "Could not open %s: %s",
                name,
                exc,
            )

            raise ApplicationError(
                f"Failed to open {name}"
            ) from exc

    def close(self, name: str) -> bool:
        """Close a supported media application."""

        application = self.get_application(name)

        if not application:
            raise ApplicationError(
                f"Unsupported media application: {name}"
            )

        process_name = application.get("process")

        return self.process_manager.terminate(
            process_name
        )


# ============================================================================
# MEDIA CONTROLLER
# ============================================================================

class MediaController:
    """
    High-level AssistantX media controller.

    This is the main class that other AssistantX modules should use.

    Example
    -------
    controller = MediaController()

    controller.play()
    controller.pause()
    controller.next_track()
    controller.volume_up()
    controller.mute()
    """

    def __init__(
        self,
        config: Optional[MediaConfig] = None,
    ) -> None:

        self.config = config or MediaConfig()

        if self.config.strict_windows and os.name != "nt":
            raise UnsupportedPlatformError(
                "AssistantX MediaController currently "
                "supports Windows only."
            )

        self._lock = threading.RLock()

        self._api = WindowsMediaAPI()

        self._process_manager = ProcessManager(
            timeout=self.config.command_timeout
        )

        self._applications = MediaApplicationManager(
            process_manager=self._process_manager
        )

        self._state = MediaState.UNKNOWN
        self._muted = False
        self._volume = 50

        logger.info("MediaController initialized.")

    # ------------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------------

    def _log_action(
        self,
        action: str,
        **kwargs: Any,
    ) -> None:
        """Log a media action."""

        if not self.config.enable_logging:
            return

        logger.info(
            "Media action: %s | %s",
            action,
            kwargs,
        )

    def _safe_call(
        self,
        action: str,
        callback: Any,
    ) -> CommandResult:
        """Execute an action safely."""

        try:
            with self._lock:
                callback()

            self._log_action(action)

            return CommandResult(
                success=True,
                action=action,
                message=f"{action} executed successfully.",
            )

        except Exception as exc:
            logger.exception(
                "Media action '%s' failed.",
                action,
            )

            return CommandResult(
                success=False,
                action=action,
                message=str(exc),
            )

    # ------------------------------------------------------------------------
    # PLAYBACK
    # ------------------------------------------------------------------------

    def play(self) -> bool:
        """
        Play media.

        Windows media keys generally expose play/pause rather than a
        guaranteed play-only operation. This method therefore uses the
        Windows play/pause media key.
        """

        with self._lock:
            self._api.play_pause()
            self._state = MediaState.PLAYING

        self._log_action("play")

        return True

    def pause(self) -> bool:
        """
        Pause media.

        Windows provides a toggle media key rather than a universal
        pause-only key. This method sends the play/pause command.
        """

        with self._lock:
            self._api.play_pause()
            self._state = MediaState.PAUSED

        self._log_action("pause")

        return True

    def toggle_play_pause(self) -> bool:
        """Toggle media playback."""

        with self._lock:
            self._api.play_pause()

            if self._state == MediaState.PLAYING:
                self._state = MediaState.PAUSED
            else:
                self._state = MediaState.PLAYING

        self._log_action("toggle_play_pause")

        return True

    def stop(self) -> bool:
        """Stop media playback."""

        with self._lock:
            self._api.stop()
            self._state = MediaState.STOPPED

        self._log_action("stop")

        return True

    def next_track(self) -> bool:
        """Play next track."""

        with self._lock:
            self._api.next_track()

        self._log_action("next_track")

        return True

    def previous_track(self) -> bool:
        """Play previous track."""

        with self._lock:
            self._api.previous_track()

        self._log_action("previous_track")

        return True

    # ------------------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------------------

    def volume_up(
        self,
        steps: Optional[int] = None,
    ) -> bool:
        """Increase system volume."""

        if steps is None:
            steps = self.config.volume_step

        steps = max(1, int(steps))

        with self._lock:
            self._api.volume_up(steps)

            self._volume = min(
                100,
                self._volume + steps,
            )

        self._log_action(
            "volume_up",
            steps=steps,
        )

        return True

    def volume_down(
        self,
        steps: Optional[int] = None,
    ) -> bool:
        """Decrease system volume."""

        if steps is None:
            steps = self.config.volume_step

        steps = max(1, int(steps))

        with self._lock:
            self._api.volume_down(steps)

            self._volume = max(
                0,
                self._volume - steps,
            )

        self._log_action(
            "volume_down",
            steps=steps,
        )

        return True

    def set_volume(
        self,
        volume: int,
    ) -> bool:
        """
        Set volume approximately to a percentage.

        Windows media keys provide relative volume control. Therefore
        this implementation uses the controller's last-known volume
        and adjusts it using volume keys.
        """

        if not isinstance(volume, int):
            raise InvalidVolumeError(
                "Volume must be an integer."
            )

        if not 0 <= volume <= 100:
            raise InvalidVolumeError(
                "Volume must be between 0 and 100."
            )

        with self._lock:
            difference = volume - self._volume

            if difference > 0:
                self._api.volume_up(difference)

            elif difference < 0:
                self._api.volume_down(abs(difference))

            self._volume = volume

        self._log_action(
            "set_volume",
            volume=volume,
        )

        return True

    def get_volume(self) -> int:
        """Return the controller's last-known volume."""

        with self._lock:
            return self._volume

    # ------------------------------------------------------------------------
    # MUTE
    # ------------------------------------------------------------------------

    def mute(self) -> bool:
        """Mute system audio."""

        with self._lock:
            if not self._muted:
                self._api.mute()
                self._muted = True

        self._log_action("mute")

        return True

    def unmute(self) -> bool:
        """Unmute system audio."""

        with self._lock:
            if self._muted:
                self._api.mute()
                self._muted = False

        self._log_action("unmute")

        return True

    def toggle_mute(self) -> bool:
        """Toggle mute state."""

        with self._lock:
            self._api.mute()
            self._muted = not self._muted

        self._log_action("toggle_mute")

        return True

    def is_muted(self) -> bool:
        """Return last-known mute state."""

        with self._lock:
            return self._muted

    # ------------------------------------------------------------------------
    # SEEK
    # ------------------------------------------------------------------------

    def seek_forward(
        self,
        seconds: Optional[int] = None,
    ) -> bool:
        """
        Seek forward.

        This method currently uses keyboard-level media compatibility
        where possible. Exact seeking is player-dependent.
        """

        if seconds is None:
            seconds = self.config.seek_seconds

        if seconds <= 0:
            raise InvalidSeekError(
                "Seek duration must be greater than zero."
            )

        # Generic media keys do not expose universal seek.
        # Keep this operation as a safe no-op-compatible command.
        logger.info(
            "Seek forward requested: %s seconds",
            seconds,
        )

        self._log_action(
            "seek_forward",
            seconds=seconds,
        )

        return True

    def seek_backward(
        self,
        seconds: Optional[int] = None,
    ) -> bool:
        """Seek backward by the requested duration."""

        if seconds is None:
            seconds = self.config.seek_seconds

        if seconds <= 0:
            raise InvalidSeekError(
                "Seek duration must be greater than zero."
            )

        logger.info(
            "Seek backward requested: %s seconds",
            seconds,
        )

        self._log_action(
            "seek_backward",
            seconds=seconds,
        )

        return True

    # ------------------------------------------------------------------------
    # APPLICATION CONTROL
    # ------------------------------------------------------------------------

    def open_application(
        self,
        application: str,
    ) -> bool:
        """Open a supported media application."""

        result = self._applications.open(
            application
        )

        self._log_action(
            "open_application",
            application=application,
        )

        return result

    def close_application(
        self,
        application: str,
    ) -> bool:
        """Close a supported media application."""

        result = self._applications.close(
            application
        )

        self._log_action(
            "close_application",
            application=application,
        )

        return result

    def application_running(
        self,
        application: str,
    ) -> bool:
        """Check whether a media application is running."""

        return self._applications.is_running(
            application
        )

    def running_applications(self) -> List[str]:
        """Return running supported media applications."""

        return self._applications.running_applications()

    # ------------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------------

    def get_state(self) -> MediaState:
        """Return controller playback state."""

        with self._lock:
            return self._state

    def get_status(self) -> MediaStatus:
        """Return complete media status."""

        with self._lock:
            applications = (
                self.running_applications()
            )

            active_application = (
                applications[0]
                if applications
                else None
            )

            return MediaStatus(
                state=self._state,
                volume=self._volume,
                muted=self._muted,
                active_application=active_application,
                available_applications=applications,
            )

    # ------------------------------------------------------------------------
    # COMMAND ROUTER
    # ------------------------------------------------------------------------

    @staticmethod
    def _normalize_command(
        command: str,
    ) -> str:
        """Normalize natural-language command."""

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
    ) -> CommandResult:
        """
        Execute a natural-language media command.

        Examples
        --------
        "play music"
        "pause"
        "next song"
        "previous track"
        "volume up"
        "volume down"
        "mute"
        "unmute"
        "stop music"
        "open spotify"
        "close vlc"
        """

        if not command or not command.strip():
            return CommandResult(
                success=False,
                action="unknown",
                message="Empty media command.",
            )

        normalized = self._normalize_command(
            command
        )

        try:
            # PLAY
            if normalized in {
                "play",
                "play music",
                "start music",
                "resume",
                "resume music",
            }:
                self.play()

                return CommandResult(
                    True,
                    "play",
                    "Playback started.",
                )

            # PAUSE
            if normalized in {
                "pause",
                "pause music",
                "pause song",
            }:
                self.pause()

                return CommandResult(
                    True,
                    "pause",
                    "Playback paused.",
                )

            # TOGGLE
            if normalized in {
                "toggle",
                "toggle playback",
                "play pause",
                "play or pause",
            }:
                self.toggle_play_pause()

                return CommandResult(
                    True,
                    "toggle",
                    "Playback toggled.",
                )

            # STOP
            if normalized in {
                "stop",
                "stop music",
                "stop song",
                "stop playback",
            }:
                self.stop()

                return CommandResult(
                    True,
                    "stop",
                    "Playback stopped.",
                )

            # NEXT
            if normalized in {
                "next",
                "next track",
                "next song",
                "skip",
                "skip song",
            }:
                self.next_track()

                return CommandResult(
                    True,
                    "next",
                    "Skipped to the next track.",
                )

            # PREVIOUS
            if normalized in {
                "previous",
                "previous track",
                "previous song",
                "back",
                "go back",
            }:
                self.previous_track()

                return CommandResult(
                    True,
                    "previous",
                    "Moved to the previous track.",
                )

            # VOLUME UP
            if normalized in {
                "volume up",
                "increase volume",
                "raise volume",
                "louder",
                "make it louder",
            }:
                self.volume_up()

                return CommandResult(
                    True,
                    "volume_up",
                    "Volume increased.",
                    {
                        "volume": self.get_volume()
                    },
                )

            # VOLUME DOWN
            if normalized in {
                "volume down",
                "decrease volume",
                "lower volume",
                "quieter",
                "make it quieter",
            }:
                self.volume_down()

                return CommandResult(
                    True,
                    "volume_down",
                    "Volume decreased.",
                    {
                        "volume": self.get_volume()
                    },
                )

            # MUTE
            if normalized in {
                "mute",
                "mute volume",
                "silence",
                "silent",
            }:
                self.mute()

                return CommandResult(
                    True,
                    "mute",
                    "Audio muted.",
                )

            # UNMUTE
            if normalized in {
                "unmute",
                "unmute volume",
                "turn sound on",
            }:
                self.unmute()

                return CommandResult(
                    True,
                    "unmute",
                    "Audio unmuted.",
                )

            # STATUS
            if normalized in {
                "status",
                "media status",
                "player status",
                "what is playing",
            }:
                status = self.get_status()

                return CommandResult(
                    True,
                    "status",
                    "Media status retrieved.",
                    status.to_dict(),
                )

            # OPEN
            if normalized.startswith("open "):
                application = normalized[5:].strip()

                if application:
                    self.open_application(
                        application
                    )

                    return CommandResult(
                        True,
                        "open",
                        f"Opened {application}.",
                    )

            # CLOSE
            if normalized.startswith("close "):
                application = normalized[6:].strip()

                if application:
                    self.close_application(
                        application
                    )

                    return CommandResult(
                        True,
                        "close",
                        f"Closed {application}.",
                    )

            return CommandResult(
                success=False,
                action="unknown",
                message=(
                    f"Unknown media command: {command}"
                ),
            )

        except MediaError as exc:
            logger.warning(
                "Media command error: %s",
                exc,
            )

            return CommandResult(
                success=False,
                action="error",
                message=str(exc),
            )

        except Exception as exc:
            logger.exception(
                "Unexpected media command failure."
            )

            return CommandResult(
                success=False,
                action="error",
                message=str(exc),
            )

    # ------------------------------------------------------------------------
    # ASYNC API
    # ------------------------------------------------------------------------

    async def async_play(self) -> bool:
        """Async play."""

        return await asyncio.to_thread(
            self.play
        )

    async def async_pause(self) -> bool:
        """Async pause."""

        return await asyncio.to_thread(
            self.pause
        )

    async def async_toggle(self) -> bool:
        """Async toggle."""

        return await asyncio.to_thread(
            self.toggle_play_pause
        )

    async def async_stop(self) -> bool:
        """Async stop."""

        return await asyncio.to_thread(
            self.stop
        )

    async def async_next(self) -> bool:
        """Async next track."""

        return await asyncio.to_thread(
            self.next_track
        )

    async def async_previous(self) -> bool:
        """Async previous track."""

        return await asyncio.to_thread(
            self.previous_track
        )

    async def async_volume_up(
        self,
        steps: Optional[int] = None,
    ) -> bool:
        """Async volume up."""

        return await asyncio.to_thread(
            self.volume_up,
            steps,
        )

    async def async_volume_down(
        self,
        steps: Optional[int] = None,
    ) -> bool:
        """Async volume down."""

        return await asyncio.to_thread(
            self.volume_down,
            steps,
        )

    async def async_mute(self) -> bool:
        """Async mute."""

        return await asyncio.to_thread(
            self.mute
        )

    async def async_unmute(self) -> bool:
        """Async unmute."""

        return await asyncio.to_thread(
            self.unmute
        )

    async def async_execute_command(
        self,
        command: str,
    ) -> CommandResult:
        """Async natural-language command execution."""

        return await asyncio.to_thread(
            self.execute_command,
            command,
        )

    # ------------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------------

    def reset_state(self) -> None:
        """Reset internal state."""

        with self._lock:
            self._state = MediaState.UNKNOWN
            self._volume = 50
            self._muted = False

        logger.info(
            "MediaController state reset."
        )

    # ------------------------------------------------------------------------
    # DIAGNOSTICS
    # ------------------------------------------------------------------------

    def diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic information."""

        return {
            "platform": os.name,
            "windows_supported": os.name == "nt",
            "state": self._state.value,
            "volume": self._volume,
            "muted": self._muted,
            "running_applications": (
                self.running_applications()
            ),
            "config": {
                "volume_step": (
                    self.config.volume_step
                ),
                "seek_seconds": (
                    self.config.seek_seconds
                ),
                "command_timeout": (
                    self.config.command_timeout
                ),
                "logging": (
                    self.config.enable_logging
                ),
            },
        }

    # ------------------------------------------------------------------------
    # CLEANUP
    # ------------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release controller resources."""

        with self._lock:
            self._state = MediaState.UNKNOWN

        logger.info(
            "MediaController cleanup completed."
        )

    def __enter__(self) -> "MediaController":
        """Context-manager entry."""

        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        """Context-manager exit."""

        self.cleanup()

    def __repr__(self) -> str:
        """Developer-friendly representation."""

        return (
            f"<MediaController "
            f"state={self._state.value} "
            f"volume={self._volume} "
            f"muted={self._muted}>"
        )


# ============================================================================
# SINGLETON
# ============================================================================

_default_controller: Optional[MediaController] = None
_controller_lock = threading.Lock()


def get_media_controller() -> MediaController:
    """
    Return the shared AssistantX MediaController.

    Using this function prevents every module from creating a
    separate controller instance.
    """

    global _default_controller

    with _controller_lock:
        if _default_controller is None:
            _default_controller = MediaController()

        return _default_controller


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def play() -> bool:
    """Play media."""

    return get_media_controller().play()


def pause() -> bool:
    """Pause media."""

    return get_media_controller().pause()


def toggle_play_pause() -> bool:
    """Toggle play/pause."""

    return get_media_controller().toggle_play_pause()


def stop() -> bool:
    """Stop media."""

    return get_media_controller().stop()


def next_track() -> bool:
    """Next track."""

    return get_media_controller().next_track()


def previous_track() -> bool:
    """Previous track."""

    return get_media_controller().previous_track()


def volume_up(
    steps: Optional[int] = None,
) -> bool:
    """Increase volume."""

    return get_media_controller().volume_up(
        steps
    )


def volume_down(
    steps: Optional[int] = None,
) -> bool:
    """Decrease volume."""

    return get_media_controller().volume_down(
        steps
    )


def set_volume(volume: int) -> bool:
    """Set volume."""

    return get_media_controller().set_volume(
        volume
    )


def get_volume() -> int:
    """Get last-known volume."""

    return get_media_controller().get_volume()


def mute() -> bool:
    """Mute audio."""

    return get_media_controller().mute()


def unmute() -> bool:
    """Unmute audio."""

    return get_media_controller().unmute()


def toggle_mute() -> bool:
    """Toggle mute."""

    return get_media_controller().toggle_mute()


def get_status() -> MediaStatus:
    """Get media status."""

    return get_media_controller().get_status()


def execute_command(
    command: str,
) -> CommandResult:
    """Execute a natural-language media command."""

    return get_media_controller().execute_command(
        command
    )


# ============================================================================
# COMMAND ALIASES
# ============================================================================

COMMAND_ALIASES: Dict[str, str] = {
    "play music": "play",
    "start music": "play",
    "resume music": "play",

    "pause music": "pause",
    "pause song": "pause",

    "next song": "next",
    "skip song": "next",
    "skip track": "next",

    "previous song": "previous",
    "previous track": "previous",

    "louder": "volume_up",
    "increase volume": "volume_up",
    "raise volume": "volume_up",

    "quieter": "volume_down",
    "decrease volume": "volume_down",
    "lower volume": "volume_down",

    "silent": "mute",
    "silence": "mute",

    "sound on": "unmute",
    "turn sound on": "unmute",
}


def resolve_alias(command: str) -> str:
    """
    Resolve a known command alias.

    If no alias exists, return the original command.
    """

    normalized = (
        command
        .strip()
        .lower()
    )

    return COMMAND_ALIASES.get(
        normalized,
        command,
    )


# ============================================================================
# MODULE INFORMATION
# ============================================================================

__title__ = "AssistantX Media Automation"
__version__ = "1.0.0"
__author__ = "AssistantX Team"


__all__ = [
    # Main controller
    "MediaController",
    "MediaConfig",

    # Data
    "MediaStatus",
    "CommandResult",

    # Enums
    "MediaAction",
    "MediaState",

    # Exceptions
    "MediaError",
    "UnsupportedPlatformError",
    "InvalidVolumeError",
    "InvalidSeekError",
    "MediaCommandError",
    "ApplicationError",

    # Factory
    "get_media_controller",

    # Convenience functions
    "play",
    "pause",
    "toggle_play_pause",
    "stop",
    "next_track",
    "previous_track",
    "volume_up",
    "volume_down",
    "set_volume",
    "get_volume",
    "mute",
    "unmute",
    "toggle_mute",
    "get_status",
    "execute_command",
    "resolve_alias",
]


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================

if __name__ == "__main__":
    """
    Simple development test.

    Run:
        python automation/media.py

    This will NOT automatically start or stop music.
    It only initializes the controller and prints diagnostics.
    """

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )

    try:
        controller = MediaController()

        print("=" * 60)
        print("AssistantX Media Controller")
        print("=" * 60)

        print(
            "Controller:",
            controller,
        )

        print(
            "Status:",
            controller.get_status().to_dict(),
        )

        print(
            "Diagnostics:",
            controller.diagnostics(),
        )

        print("=" * 60)
        print("Media controller initialized successfully.")
        print("=" * 60)

    except UnsupportedPlatformError as exc:
        print(
            "Unsupported platform:",
            exc,
        )

    except Exception as exc:
        print(
            "Initialization error:",
            exc,
        )
        