"""
system.py
=========
OS-level system control: shutdown/restart/sleep/lock, and volume /
brightness adjustment. Uses platform-native commands where possible
(shutdown.exe, osascript, systemctl) and falls back to the optional
`pycaw` (Windows volume) / `screen-brightness-control` packages for
finer-grained control when installed.

All destructive operations (shutdown, restart) are expected to already
have been gated behind a user confirmation upstream in
brain/decision_engine.py — this module executes unconditionally once
called, by design, so it stays simple and testable.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

logger = get_logger(__name__)


class SystemControlError(RuntimeError):
    """Raised when a system-level action fails or is unsupported on this platform."""


# --------------------------------------------------------------------------- #
# Power control
# --------------------------------------------------------------------------- #

def shutdown(delay_seconds: int = 5) -> bool:
    """Shut down the computer after an optional delay (gives the user a
    brief window to notice and cancel if this was triggered in error)."""
    logger.warning("System shutdown requested (delay=%ds).", delay_seconds)
    try:
        if IS_WINDOWS:
            subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], check=True)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", "tell app \"System Events\" to shut down"], check=True)
        elif IS_LINUX:
            subprocess.run(["shutdown", "-h", f"+{max(1, delay_seconds // 60)}"], check=True)
        else:
            raise SystemControlError("Unsupported platform for shutdown.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Shutdown command failed: {exc}") from exc


def cancel_shutdown() -> bool:
    """Cancel a previously scheduled shutdown, if the platform supports it."""
    try:
        if IS_WINDOWS:
            subprocess.run(["shutdown", "/a"], check=True)
        elif IS_LINUX:
            subprocess.run(["shutdown", "-c"], check=True)
        else:
            logger.warning("Shutdown cancellation not supported on this platform.")
            return False
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Could not cancel shutdown: {exc}") from exc


def restart(delay_seconds: int = 5) -> bool:
    """Restart the computer after an optional delay."""
    logger.warning("System restart requested (delay=%ds).", delay_seconds)
    try:
        if IS_WINDOWS:
            subprocess.run(["shutdown", "/r", "/t", str(delay_seconds)], check=True)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", "tell app \"System Events\" to restart"], check=True)
        elif IS_LINUX:
            subprocess.run(["shutdown", "-r", f"+{max(1, delay_seconds // 60)}"], check=True)
        else:
            raise SystemControlError("Unsupported platform for restart.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Restart command failed: {exc}") from exc


def sleep() -> bool:
    """Put the computer to sleep."""
    logger.info("System sleep requested.")
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True
            )
        elif IS_MAC:
            subprocess.run(["pmset", "sleepnow"], check=True)
        elif IS_LINUX:
            subprocess.run(["systemctl", "suspend"], check=True)
        else:
            raise SystemControlError("Unsupported platform for sleep.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Sleep command failed: {exc}") from exc


def lock_screen() -> bool:
    """Lock the current user session."""
    logger.info("Screen lock requested.")
    try:
        if IS_WINDOWS:
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
        elif IS_MAC:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
                check=True,
            )
        elif IS_LINUX:
            # Try common Linux lock commands in order of availability.
            for cmd in (["loginctl", "lock-session"], ["xdg-screensaver", "lock"]):
                try:
                    subprocess.run(cmd, check=True)
                    return True
                except (OSError, subprocess.CalledProcessError):
                    continue
            raise SystemControlError("No supported screen-lock command found.")
        else:
            raise SystemControlError("Unsupported platform for screen lock.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Lock screen command failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# Volume control
# --------------------------------------------------------------------------- #

def _get_pycaw_volume_interface():  # pragma: no cover - requires Windows + pycaw
    from ctypes import cast, POINTER

    from comtypes import CLSCTX_ALL  # type: ignore
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(level_percent: int) -> bool:
    """
    Set system volume to an absolute level (0-100). Uses `pycaw` on
    Windows if installed (precise control), `osascript` on macOS, and
    `amixer`/`pactl` on Linux (whichever is available).
    """
    level_percent = max(0, min(100, level_percent))
    logger.info("Setting system volume to %d%%.", level_percent)

    try:
        if IS_WINDOWS:
            try:
                volume_interface = _get_pycaw_volume_interface()
                volume_interface.SetMasterVolumeLevelScalar(level_percent / 100.0, None)
            except ImportError:
                raise SystemControlError(
                    "Precise volume control requires 'pycaw' and 'comtypes'. "
                    "Run: pip install pycaw comtypes"
                )
        elif IS_MAC:
            subprocess.run(["osascript", "-e", f"set volume output volume {level_percent}"], check=True)
        elif IS_LINUX:
            _linux_set_volume(level_percent)
        else:
            raise SystemControlError("Unsupported platform for volume control.")
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemControlError(f"Failed to set volume: {exc}") from exc


def _linux_set_volume(level_percent: int) -> None:
    """Try pactl first (PulseAudio/PipeWire), fall back to amixer (ALSA)."""
    try:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level_percent}%"], check=True)
    except (OSError, subprocess.CalledProcessError):
        subprocess.run(["amixer", "set", "Master", f"{level_percent}%"], check=True)


def adjust_volume(delta_percent: int) -> bool:
    """Nudge volume up/down by a relative amount (e.g. -10 or +10)."""
    logger.info("Adjusting volume by %+d%%.", delta_percent)
    try:
        if IS_MAC:
            direction = "output volume (output volume of (get volume settings) + (" + str(delta_percent) + "))"
            subprocess.run(["osascript", "-e", f"set volume {direction}"], check=True)
            return True
        elif IS_LINUX:
            sign = "+" if delta_percent >= 0 else "-"
            magnitude = abs(delta_percent)
            try:
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{magnitude}%"], check=True
                )
            except (OSError, subprocess.CalledProcessError):
                subprocess.run(["amixer", "set", "Master", f"{magnitude}%{sign}"], check=True)
            return True
        else:
            # Windows lacks a simple relative-adjust shell one-liner without
            # pycaw; read current level via pycaw and compute the new absolute value.
            volume_interface = _get_pycaw_volume_interface()
            current = volume_interface.GetMasterVolumeLevelScalar() * 100
            return set_volume(int(current) + delta_percent)
    except (OSError, subprocess.CalledProcessError, ImportError) as exc:
        raise SystemControlError(f"Failed to adjust volume: {exc}") from exc


def mute() -> bool:
    """Mute system audio."""
    try:
        if IS_WINDOWS:
            volume_interface = _get_pycaw_volume_interface()
            volume_interface.SetMute(1, None)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", "set volume output muted true"], check=True)
        elif IS_LINUX:
            try:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=True)
            except (OSError, subprocess.CalledProcessError):
                subprocess.run(["amixer", "set", "Master", "mute"], check=True)
        else:
            raise SystemControlError("Unsupported platform for mute.")
        return True
    except (OSError, subprocess.CalledProcessError, ImportError) as exc:
        raise SystemControlError(f"Failed to mute: {exc}") from exc


def unmute() -> bool:
    """Unmute system audio."""
    try:
        if IS_WINDOWS:
            volume_interface = _get_pycaw_volume_interface()
            volume_interface.SetMute(0, None)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", "set volume output muted false"], check=True)
        elif IS_LINUX:
            try:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True)
            except (OSError, subprocess.CalledProcessError):
                subprocess.run(["amixer", "set", "Master", "unmute"], check=True)
        else:
            raise SystemControlError("Unsupported platform for unmute.")
        return True
    except (OSError, subprocess.CalledProcessError, ImportError) as exc:
        raise SystemControlError(f"Failed to unmute: {exc}") from exc


# --------------------------------------------------------------------------- #
# Brightness control
# --------------------------------------------------------------------------- #

def set_brightness(level_percent: int) -> bool:
    """
    Set screen brightness (0-100). Uses the optional
    `screen-brightness-control` package if installed (cross-platform);
    otherwise falls back to platform-specific commands where available
    (mainly Linux via `xrandr`/`brightnessctl`, macOS has no reliable
    unauthenticated CLI so this may require the optional package there).
    """
    level_percent = max(0, min(100, level_percent))
    try:
        import screen_brightness_control as sbc  # type: ignore

        sbc.set_brightness(level_percent)
        return True
    except ImportError:
        pass  # fall through to platform-specific attempts below
    except Exception as exc:  # noqa: BLE001
        logger.warning("screen_brightness_control failed (%s); trying platform fallback.", exc)

    if IS_LINUX:
        try:
            subprocess.run(["brightnessctl", "set", f"{level_percent}%"], check=True)
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemControlError(f"Failed to set brightness via brightnessctl: {exc}") from exc

    raise SystemControlError(
        "Brightness control requires the 'screen-brightness-control' package on this platform. "
        "Run: pip install screen-brightness-control"
    )


def adjust_brightness(delta_percent: int) -> bool:
    """Nudge brightness up/down by a relative amount."""
    try:
        import screen_brightness_control as sbc  # type: ignore

        current = sbc.get_brightness(display=0)
        current_value = current[0] if isinstance(current, list) else current
        return set_brightness(int(current_value) + delta_percent)
    except ImportError:
        raise SystemControlError(
            "Brightness control requires the 'screen-brightness-control' package. "
            "Run: pip install screen-brightness-control"
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemControlError(f"Failed to adjust brightness: {exc}") from exc
        