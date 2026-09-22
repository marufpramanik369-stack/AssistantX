"""
AssistantX - Keyboard Automation
=================================

Professional keyboard automation module for Windows/Desktop.

Features
--------
- Type text
- Press individual keys
- Press hotkeys
- Hold keys safely
- Common Windows shortcuts
- Browser shortcuts
- Text editing shortcuts
- Application shortcuts
- Natural-language command execution
- Async-friendly API
- Thread-safe controller
- Optional PyAutoGUI backend
- Runtime availability checking
- Diagnostics
- Structured exceptions
- Logging integration

Dependency
----------
PyAutoGUI is optional.

Install:
    pip install pyautogui

The module does not import PyAutoGUI at module-import time. This keeps
AssistantX functional even when keyboard automation is unavailable.

Author: AssistantX Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any

try:
    import pyautogui
except ImportError:
    pyautogui = None

from core.logger import get_logger

# ============================================================================
# LOGGER
# ============================================================================

logger = get_logger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class KeyboardAutomationError(RuntimeError):
    """
    Base exception for keyboard automation failures.
    """


class KeyboardBackendError(KeyboardAutomationError):
    """
    Raised when the keyboard backend is unavailable.
    """


class InvalidKeyError(KeyboardAutomationError):
    """
    Raised when an invalid keyboard key is supplied.
    """


class InvalidTextError(KeyboardAutomationError):
    """
    Raised when invalid text is supplied.
    """


class InvalidDurationError(KeyboardAutomationError):
    """
    Raised when an invalid duration is supplied.
    """


class HotkeyError(KeyboardAutomationError):
    """
    Raised when a hotkey combination is invalid.
    """


class KeyboardCommandError(KeyboardAutomationError):
    """
    Raised when a keyboard command cannot be resolved.
    """


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class KeyboardConfig:
    """
    Configuration for KeyboardController.

    Attributes
    ----------
    typing_interval:
        Default delay between typed characters.

    key_hold_duration:
        Default duration used by hold_key().

    command_delay:
        Small delay between automation commands.

    failsafe:
        Enable PyAutoGUI failsafe.

    pause:
        PyAutoGUI global pause between actions.

    strict_validation:
        Enable input validation.
    """

    typing_interval: float = 0.02
    key_hold_duration: float = 0.1
    command_delay: float = 0.02

    failsafe: bool = True
    pause: float = 0.01

    strict_validation: bool = True

    def __post_init__(self) -> None:
        if self.typing_interval < 0:
            raise ValueError(
                "typing_interval cannot be negative."
            )

        if self.key_hold_duration <= 0:
            raise ValueError(
                "key_hold_duration must be greater than zero."
            )

        if self.command_delay < 0:
            raise ValueError(
                "command_delay cannot be negative."
            )

        if self.pause < 0:
            raise ValueError(
                "pause cannot be negative."
            )


# ============================================================================
# RESULT OBJECT
# ============================================================================

@dataclass
class KeyboardCommandResult:
    """
    Structured result for keyboard commands.
    """

    success: bool
    action: str
    message: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert result to dictionary.
        """

        return {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            "data": self.data or {},
        }


# ============================================================================
# KEY DEFINITIONS
# ============================================================================

SUPPORTED_KEYS = {
    # Basic
    "enter",
    "return",
    "esc",
    "escape",
    "tab",
    "space",
    "backspace",
    "delete",
    "insert",

    # Navigation
    "home",
    "end",
    "pageup",
    "pagedown",

    "up",
    "down",
    "left",
    "right",

    # Modifiers
    "shift",
    "ctrl",
    "control",
    "alt",
    "win",
    "windows",
    "command",

    # Function keys
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",

    # Lock keys
    "capslock",
    "numlock",
    "scrolllock",

    # Special
    "printscreen",
    "pause",
    "break",
}


# ============================================================================
# KEY ALIASES
# ============================================================================

KEY_ALIASES: dict[str, str] = {
    "return": "enter",
    "escape": "esc",
    "control": "ctrl",
    "windows": "win",
    "command": "win",

    "pgup": "pageup",
    "pgdn": "pagedown",

    "del": "delete",
    "ins": "insert",

    "spacebar": "space",

    "caps": "capslock",
    "num": "numlock",

    "up arrow": "up",
    "down arrow": "down",
    "left arrow": "left",
    "right arrow": "right",
}


# ============================================================================
# COMMAND ALIASES
# ============================================================================

COMMAND_ALIASES: dict[str, str] = {
    "copy": "copy",
    "copy text": "copy",

    "paste": "paste",
    "paste text": "paste",

    "cut": "cut",

    "undo": "undo",
    "redo": "redo",

    "select all": "select_all",

    "save": "save",
    "save file": "save",

    "find": "find",
    "search": "find",

    "refresh": "refresh",
    "reload": "refresh",

    "new tab": "new_tab",
    "open new tab": "new_tab",

    "close tab": "close_tab",

    "close window": "close_window",

    "switch window": "switch_window",
    "change window": "switch_window",

    "go back": "browser_back",
    "browser back": "browser_back",

    "go forward": "browser_forward",
    "browser forward": "browser_forward",

    "new window": "new_window",

    "fullscreen": "fullscreen",

    "escape": "escape",
    "press escape": "escape",

    "enter": "enter",
    "press enter": "enter",
}


# ============================================================================
# BACKEND
# ============================================================================

def _get_backend():
    """Return the PyAutoGUI backend or raise a clear error."""

    if pyautogui is None:
        raise KeyboardAutomationError(
            "Keyboard automation requires 'pyautogui'. "
            "Install it with: pip install pyautogui"
        )

    try:
        pyautogui.FAILSAFE = True
        return pyautogui
    except Exception as exc:
        raise KeyboardAutomationError(
            f"Could not initialize keyboard backend: {exc}"
        ) from exc
    

# ============================================================================
# AVAILABILITY                                                                               UPDATED     =========================================================================
# ============================================================================


import logging

logger = logging.getLogger(__name__)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None


class KeyboardAutomationError(Exception):
    """Custom exception raised for KeyboardController execution failures."""


class KeyboardController:
    """Class to handle OS-level keyboard events and text interaction."""

    def __init__(self, pause_interval: float = 0.1) -> None:
        self.backend = pyautogui
        self.pause_interval = pause_interval
        if self.backend:
            self.backend.PAUSE = pause_interval

    def is_available(self) -> bool:
        return self.backend is not None

    def _ensure_backend(self) -> None:
        if not self.is_available():
            logger.error("Keyboard automation backend (pyautogui) is unavailable.")
            raise KeyboardAutomationError("Keyboard backend is not installed or available.")

    def press(self, key: str) -> None:
        self._ensure_backend()
        if not key or not isinstance(key, str):
            raise ValueError("Key must be a non-empty string.")
        try:
            self.backend.press(key.lower())
        except Exception as exc:
            logger.exception("Failed to initialize keyboard")
            raise KeyboardAutomationError(f"Error executing key press: {key}") from exc

    def write_text(self, text: str, interval: float = 0.0) -> None:
        self._ensure_backend()
        if text is None or not isinstance(text, str):
            raise ValueError("Text must be a valid string.")
        try:
            self.backend.write(text, interval=interval)
        except Exception as exc:
            logger.exception("Failed to initialize keyboard")
            raise KeyboardAutomationError("Error executing text writing.") from exc

    def hotkey(self, *keys: str) -> None:
        self._ensure_backend()
        if not keys or any(not isinstance(k, str) for k in keys):
            raise ValueError("Hotkey sequence must contain valid string keys.")
        try:
            self.backend.hotkey(*[k.lower() for k in keys])
        except Exception as exc:
            logger.exception("Failed to initialize keyboard")
            raise KeyboardAutomationError(f"Error executing hotkey: {keys}") from exc


# Module-level convenience instance
_default_controller = KeyboardController()

def is_available() -> bool:
    return _default_controller.is_available()

def press(key: str) -> None:
    _default_controller.press(key)

def write_text(text: str, interval: float = 0.0) -> None:
    _default_controller.write_text(text, interval)

def hotkey(*keys: str) -> None:
    _default_controller.hotkey(*keys)



# ============================================================================
# KEYBOARD CONTROLLER
# ============================================================================

class KeyboardController:
    """
    Main AssistantX keyboard automation controller.

    Example
    -------
    controller = KeyboardController()

    controller.type_text("Hello AssistantX")
    controller.press_key("enter")
    controller.press_hotkey("ctrl", "c")
    """

    def __init__(
        self,
        config: KeyboardConfig | None = None,
    ) -> None:

        self.config = config or KeyboardConfig()

        self._lock = threading.RLock()

        self._commands_executed = 0
        self._last_action: str | None = None

        logger.info(
            "KeyboardController initialized."
        )

    # ------------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------------

    def _backend(self):
        """
        Return configured keyboard backend.
        """

        backend = _get_backend()

        backend.FAILSAFE = self.config.failsafe
        backend.PAUSE = self.config.pause

        return backend

    @staticmethod
    def _normalize_key(key: str) -> str:
        """
        Normalize a key name.
        """

        if not isinstance(key, str):
            raise InvalidKeyError(
                "Key must be a string."
            )

        normalized = (
            key
            .strip()
            .lower()
        )

        if not normalized:
            raise InvalidKeyError(
                "Key cannot be empty."
            )

        return KEY_ALIASES.get(
            normalized,
            normalized,
        )

    def _validate_key(self, key: str) -> str:
        """
        Validate and normalize a keyboard key.
        """

        normalized = self._normalize_key(key)

        # PyAutoGUI supports many more keys than this list.
        # Therefore this is a soft validation layer rather than
        # an absolute restriction.
        if (
            self.config.strict_validation
            and len(normalized) > 1
            and normalized not in SUPPORTED_KEYS
        ):
            backend = self._backend()

            valid_keys = getattr(
                backend,
                "KEYBOARD_KEYS",
                [],
            )

            if normalized not in valid_keys:
                raise InvalidKeyError(
                    f"Unsupported keyboard key: {key}"
                )

        return normalized

    @staticmethod
    def _validate_text(text: str) -> None:
        """
        Validate text input.
        """

        if not isinstance(text, str):
            raise InvalidTextError(
                "Text must be a string."
            )

        if not text:
            raise InvalidTextError(
                "Text cannot be empty."
            )

    @staticmethod
    def _validate_duration(
        duration_seconds: float,
    ) -> float:
        """
        Validate duration.
        """

        try:
            duration = float(
                duration_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidDurationError(
                "Duration must be a number."
            ) from exc

        if duration <= 0:
            raise InvalidDurationError(
                "Duration must be greater than zero."
            )

        return duration

    def _record_action(
        self,
        action: str,
    ) -> None:
        """
        Record internal action statistics.
        """

        self._commands_executed += 1
        self._last_action = action

        logger.info(
            "Keyboard action executed: %s",
            action,
        )

    # ------------------------------------------------------------------------
    # BASIC INPUT
    # ------------------------------------------------------------------------

    def type_text(
        self,
        text: str,
        interval_seconds: float | None = None,
    ) -> bool:
        """
        Type text at the current keyboard focus.
        """

        self._validate_text(text)

        if interval_seconds is None:
            interval_seconds = (
                self.config.typing_interval
            )

        if interval_seconds < 0:
            raise InvalidDurationError(
                "Typing interval cannot be negative."
            )

        backend = self._backend()

        logger.info(
            "Typing text (%d characters).",
            len(text),
        )

        try:
            with self._lock:
                backend.write(
                    text,
                    interval=interval_seconds,
                )

                self._record_action(
                    "type_text"
                )

            return True

        except Exception as exc:
            raise KeyboardAutomationError(
                f"Failed to type text: {exc}"
            ) from exc

    def press_key(
        self,
        key: str,
    ) -> bool:
        """
        Press and release a single key.
        """

        normalized = self._validate_key(key)

        backend = self._backend()

        try:
            with self._lock:
                backend.press(normalized)

                self._record_action(
                    f"press_key:{normalized}"
                )

            return True

        except Exception as exc:
            raise KeyboardAutomationError(
                f"Failed to press key "
                f"'{normalized}': {exc}"
            ) from exc

    def key_down(
        self,
        key: str,
    ) -> bool:
        """
        Press a key down without releasing it.

        Use key_up() afterward.
        """

        normalized = self._validate_key(key)

        backend = self._backend()

        try:
            with self._lock:
                backend.keyDown(normalized)

                self._record_action(
                    f"key_down:{normalized}"
                )

            return True

        except Exception as exc:
            raise KeyboardAutomationError(
                f"Failed to press key down "
                f"'{normalized}': {exc}"
            ) from exc

    def key_up(
        self,
        key: str,
    ) -> bool:
        """
        Release a previously held key.
        """

        normalized = self._validate_key(key)

        backend = self._backend()

        try:
            with self._lock:
                backend.keyUp(normalized)

                self._record_action(
                    f"key_up:{normalized}"
                )

            return True

        except Exception as exc:
            raise KeyboardAutomationError(
                f"Failed to release key "
                f"'{normalized}': {exc}"
            ) from exc

    def hold_key(
        self,
        key: str,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Hold a key for a specified duration.

        The key is released in a finally block so an exception does not
        leave the key physically stuck down.
        """

        normalized = self._validate_key(key)

        if duration_seconds is None:
            duration_seconds = (
                self.config.key_hold_duration
            )

        duration = self._validate_duration(
            duration_seconds
        )

        backend = self._backend()

        try:
            with self._lock:
                backend.keyDown(normalized)

                try:
                    time.sleep(duration)

                finally:
                    backend.keyUp(normalized)

                self._record_action(
                    f"hold_key:{normalized}"
                )

            return True

        except KeyboardAutomationError:
            raise

        except Exception as exc:
            raise KeyboardAutomationError(
                f"Failed to hold key "
                f"'{normalized}': {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # HOTKEYS
    # ------------------------------------------------------------------------

    def press_hotkey(
        self,
        *keys: str,
    ) -> bool:
        """
        Press multiple keys as a hotkey combination.

        Example:
            controller.press_hotkey("ctrl", "c")
        """

        if not keys:
            raise HotkeyError(
                "At least two keys are required."
            )

        if len(keys) < 2:
            raise HotkeyError(
                "A hotkey requires at least two keys."
            )

        normalized_keys = tuple(
            self._validate_key(key)
            for key in keys
        )

        backend = self._backend()

        try:
            with self._lock:
                backend.hotkey(
                    *normalized_keys
                )

                self._record_action(
                    "hotkey:"
                    + "+".join(normalized_keys)
                )

            return True

        except Exception as exc:
            raise HotkeyError(
                f"Failed to press hotkey "
                f"{normalized_keys}: {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # TEXT EDITING
    # ------------------------------------------------------------------------

    def copy(self) -> bool:
        """Ctrl+C."""

        return self.press_hotkey(
            "ctrl",
            "c",
        )

    def paste(self) -> bool:
        """Ctrl+V."""

        return self.press_hotkey(
            "ctrl",
            "v",
        )

    def cut(self) -> bool:
        """Ctrl+X."""

        return self.press_hotkey(
            "ctrl",
            "x",
        )

    def undo(self) -> bool:
        """Ctrl+Z."""

        return self.press_hotkey(
            "ctrl",
            "z",
        )

    def redo(self) -> bool:
        """Ctrl+Y."""

        return self.press_hotkey(
            "ctrl",
            "y",
        )

    def select_all(self) -> bool:
        """Ctrl+A."""

        return self.press_hotkey(
            "ctrl",
            "a",
        )

    def save(self) -> bool:
        """Ctrl+S."""

        return self.press_hotkey(
            "ctrl",
            "s",
        )

    def save_as(self) -> bool:
        """Ctrl+Shift+S."""

        return self.press_hotkey(
            "ctrl",
            "shift",
            "s",
        )

    def find(self) -> bool:
        """Ctrl+F."""

        return self.press_hotkey(
            "ctrl",
            "f",
        )

    def replace(self) -> bool:
        """Ctrl+H."""

        return self.press_hotkey(
            "ctrl",
            "h",
        )

    def select_line(self) -> bool:
        """
        Select current line using Home/Shift+End.
        """

        self.press_key("home")

        return self.press_hotkey(
            "shift",
            "end",
        )

    # ------------------------------------------------------------------------
    # WINDOWS SHORTCUTS
    # ------------------------------------------------------------------------

    def switch_window(self) -> bool:
        """Alt+Tab."""

        return self.press_hotkey(
            "alt",
            "tab",
        )

    def close_window(self) -> bool:
        """Alt+F4."""

        return self.press_hotkey(
            "alt",
            "f4",
        )

    def minimize_window(self) -> bool:
        """Windows+D."""

        return self.press_hotkey(
            "win",
            "d",
        )

    def show_desktop(self) -> bool:
        """Windows+D."""

        return self.press_hotkey(
            "win",
            "d",
        )

    def open_task_manager(self) -> bool:
        """Ctrl+Shift+Esc."""

        return self.press_hotkey(
            "ctrl",
            "shift",
            "esc",
        )

    def lock_screen(self) -> bool:
        """Windows+L."""

        return self.press_hotkey(
            "win",
            "l",
        )

    def open_run(self) -> bool:
        """Windows+R."""

        return self.press_hotkey(
            "win",
            "r",
        )

    def open_file_explorer(self) -> bool:
        """Windows+E."""

        return self.press_hotkey(
            "win",
            "e",
        )

    def open_settings(self) -> bool:
        """Windows+I."""

        return self.press_hotkey(
            "win",
            "i",
        )

    # ------------------------------------------------------------------------
    # BROWSER SHORTCUTS
    # ------------------------------------------------------------------------

    def new_tab(self) -> bool:
        """Ctrl+T."""

        return self.press_hotkey(
            "ctrl",
            "t",
        )

    def close_tab(self) -> bool:
        """Ctrl+W."""

        return self.press_hotkey(
            "ctrl",
            "w",
        )

    def reopen_closed_tab(self) -> bool:
        """Ctrl+Shift+T."""

        return self.press_hotkey(
            "ctrl",
            "shift",
            "t",
        )

    def refresh(self) -> bool:
        """F5."""

        return self.press_key("f5")

    def hard_refresh(self) -> bool:
        """Ctrl+F5."""

        return self.press_hotkey(
            "ctrl",
            "f5",
        )

    def browser_back(self) -> bool:
        """Alt+Left."""

        return self.press_hotkey(
            "alt",
            "left",
        )

    def browser_forward(self) -> bool:
        """Alt+Right."""

        return self.press_hotkey(
            "alt",
            "right",
        )

    def new_window(self) -> bool:
        """Ctrl+N."""

        return self.press_hotkey(
            "ctrl",
            "n",
        )

    def open_private_window(self) -> bool:
        """
        Ctrl+Shift+N.

        Supported by Chromium-based browsers.
        """

        return self.press_hotkey(
            "ctrl",
            "shift",
            "n",
        )

    def focus_address_bar(self) -> bool:
        """Ctrl+L."""

        return self.press_hotkey(
            "ctrl",
            "l",
        )

    # ------------------------------------------------------------------------
    # APPLICATION SHORTCUTS
    # ------------------------------------------------------------------------

    def fullscreen(self) -> bool:
        """F11."""

        return self.press_key("f11")

    def escape(self) -> bool:
        """Escape."""

        return self.press_key("esc")

    def enter(self) -> bool:
        """Enter."""

        return self.press_key("enter")

    def tab(self) -> bool:
        """Tab."""

        return self.press_key("tab")

    def backspace(self) -> bool:
        """Backspace."""

        return self.press_key("backspace")

    def delete(self) -> bool:
        """Delete."""

        return self.press_key("delete")

    # ------------------------------------------------------------------------
    # NAVIGATION
    # ------------------------------------------------------------------------

    def move_up(self) -> bool:
        """Press Up."""

        return self.press_key("up")

    def move_down(self) -> bool:
        """Press Down."""

        return self.press_key("down")

    def move_left(self) -> bool:
        """Press Left."""

        return self.press_key("left")

    def move_right(self) -> bool:
        """Press Right."""

        return self.press_key("right")

    def go_home(self) -> bool:
        """Press Home."""

        return self.press_key("home")

    def go_end(self) -> bool:
        """Press End."""

        return self.press_key("end")

    def page_up(self) -> bool:
        """Page Up."""

        return self.press_key("pageup")

    def page_down(self) -> bool:
        """Page Down."""

        return self.press_key("pagedown")

    # ------------------------------------------------------------------------
    # FUNCTION KEYS
    # ------------------------------------------------------------------------

    def press_function_key(
        self,
        number: int,
    ) -> bool:
        """
        Press F1-F12.
        """

        if not isinstance(number, int):
            raise InvalidKeyError(
                "Function key number must be an integer."
            )

        if not 1 <= number <= 12:
            raise InvalidKeyError(
                "Function key must be between F1 and F12."
            )

        return self.press_key(
            f"f{number}"
        )

    # ------------------------------------------------------------------------
    # SPECIAL COMBINATIONS
    # ------------------------------------------------------------------------

    def ctrl_enter(self) -> bool:
        return self.press_hotkey(
            "ctrl",
            "enter",
        )

    def alt_enter(self) -> bool:
        return self.press_hotkey(
            "alt",
            "enter",
        )

    def shift_enter(self) -> bool:
        return self.press_hotkey(
            "shift",
            "enter",
        )

    def ctrl_shift_esc(self) -> bool:
        return self.press_hotkey(
            "ctrl",
            "shift",
            "esc",
        )

    def alt_f4(self) -> bool:
        return self.press_hotkey(
            "alt",
            "f4",
        )

    # ------------------------------------------------------------------------
    # COMMAND PARSER
    # ------------------------------------------------------------------------

    @staticmethod
    def normalize_command(
        command: str,
    ) -> str:
        """
        Normalize natural-language keyboard command.
        """

        if not isinstance(command, str):
            raise KeyboardCommandError(
                "Command must be a string."
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
    ) -> KeyboardCommandResult:
        """
        Execute a natural-language keyboard command.

        Examples
        --------
        execute_command("copy")
        execute_command("paste")
        execute_command("save")
        execute_command("new tab")
        execute_command("close window")
        execute_command("switch window")
        """

        normalized = self.normalize_command(
            command
        )

        if not normalized:
            return KeyboardCommandResult(
                success=False,
                action="unknown",
                message="Keyboard command is empty.",
            )

        action = COMMAND_ALIASES.get(
            normalized
        )

        try:
            if action == "copy":
                self.copy()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Copied.",
                )

            if action == "paste":
                self.paste()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Pasted.",
                )

            if action == "cut":
                self.cut()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Cut.",
                )

            if action == "undo":
                self.undo()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Undo completed.",
                )

            if action == "redo":
                self.redo()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Redo completed.",
                )

            if action == "select_all":
                self.select_all()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Selected all.",
                )

            if action == "save":
                self.save()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Saved.",
                )

            if action == "find":
                self.find()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Find opened.",
                )

            if action == "refresh":
                self.refresh()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Page refreshed.",
                )

            if action == "new_tab":
                self.new_tab()

                return KeyboardCommandResult(
                    True,
                    action,
                    "New tab opened.",
                )

            if action == "close_tab":
                self.close_tab()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Tab closed.",
                )

            if action == "close_window":
                self.close_window()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Window closed.",
                )

            if action == "switch_window":
                self.switch_window()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Window switched.",
                )

            if action == "browser_back":
                self.browser_back()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Navigated back.",
                )

            if action == "browser_forward":
                self.browser_forward()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Navigated forward.",
                )

            if action == "new_window":
                self.new_window()

                return KeyboardCommandResult(
                    True,
                    action,
                    "New window opened.",
                )

            if action == "fullscreen":
                self.fullscreen()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Fullscreen toggled.",
                )

            if action == "escape":
                self.escape()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Escape pressed.",
                )

            if action == "enter":
                self.enter()

                return KeyboardCommandResult(
                    True,
                    action,
                    "Enter pressed.",
                )

            # --------------------------------------------------------------
            # Dynamic press command
            # --------------------------------------------------------------

            if normalized.startswith(
                "press "
            ):
                key = normalized[6:].strip()

                self.press_key(key)

                return KeyboardCommandResult(
                    True,
                    "press_key",
                    f"Pressed {key}.",
                    {
                        "key": key
                    },
                )

            # --------------------------------------------------------------
            # Dynamic type command
            # --------------------------------------------------------------

            if normalized.startswith(
                "type "
            ):
                text = command.strip()[5:]

                self.type_text(text)

                return KeyboardCommandResult(
                    True,
                    "type_text",
                    "Text typed successfully.",
                    {
                        "length": len(text)
                    },
                )

            return KeyboardCommandResult(
                success=False,
                action="unknown",
                message=(
                    f"Unknown keyboard command: "
                    f"{command}"
                ),
            )

        except KeyboardAutomationError as exc:

            logger.warning(
                "Keyboard command failed: %s",
                exc,
            )

            return KeyboardCommandResult(
                success=False,
                action=action or "error",
                message=str(exc),
            )

        except Exception as exc:

            logger.exception(
                "Unexpected keyboard command error."
            )

            return KeyboardCommandResult(
                success=False,
                action=action or "error",
                message=str(exc),
            )

    # ------------------------------------------------------------------------
    # ASYNC API
    # ------------------------------------------------------------------------

    async def async_type_text(
        self,
        text: str,
        interval_seconds: float | None = None,
    ) -> bool:
        """
        Async text typing.
        """

        return await asyncio.to_thread(
            self.type_text,
            text,
            interval_seconds,
        )

    async def async_press_key(
        self,
        key: str,
    ) -> bool:
        """
        Async key press.
        """

        return await asyncio.to_thread(
            self.press_key,
            key,
        )

    async def async_press_hotkey(
        self,
        *keys: str,
    ) -> bool:
        """
        Async hotkey.
        """

        return await asyncio.to_thread(
            self.press_hotkey,
            *keys,
        )

    async def async_copy(self) -> bool:
        """Async copy."""

        return await asyncio.to_thread(
            self.copy
        )

    async def async_paste(self) -> bool:
        """Async paste."""

        return await asyncio.to_thread(
            self.paste
        )

    async def async_execute_command(
        self,
        command: str,
    ) -> KeyboardCommandResult:
        """
        Async command execution.
        """

        return await asyncio.to_thread(
            self.execute_command,
            command,
        )

    # ------------------------------------------------------------------------
    # DIAGNOSTICS
    # ------------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return controller diagnostics.
        """

        backend_available = is_available()

        return {
            "platform": os.name,
            "backend": "pyautogui",
            "available": backend_available,
            "failsafe": self.config.failsafe,
            "pause": self.config.pause,
            "typing_interval": (
                self.config.typing_interval
            ),
            "commands_executed": (
                self._commands_executed
            ),
            "last_action": (
                self._last_action
            ),
        }

    # ------------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------------

    def reset_statistics(self) -> None:
        """
        Reset internal execution statistics.
        """

        with self._lock:
            self._commands_executed = 0
            self._last_action = None

        logger.info(
            "Keyboard statistics reset."
        )

    # ------------------------------------------------------------------------
    # CONTEXT MANAGER
    # ------------------------------------------------------------------------

    from typing import Self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc: type[BaseException] | None,
        val: BaseException | None,
        tb: TracebackType | None,
) -> bool:
        
        logger.debug("KeyboardController context closed.")

        return False

    # ------------------------------------------------------------------------
    # REPRESENTATION
    # ------------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "<KeyboardController "
            f"available={is_available()} "
            f"commands={self._commands_executed}>"
        )


# ============================================================================
# SINGLETON
# ============================================================================

_default_controller: KeyboardController | None = None

_controller_lock = threading.Lock()


def get_keyboard_controller() -> KeyboardController:
    """
    Return the shared KeyboardController.
    """

    global _default_controller

    with _controller_lock:

        if _default_controller is None:
            _default_controller = (
                KeyboardController()
            )

        return _default_controller


# ============================================================================
# BACKWARD-COMPATIBLE FUNCTIONS
# ============================================================================

def type_text(
    text: str,
    interval_seconds: float = 0.02,
) -> bool:
    """
    Type text.
    """

    return get_keyboard_controller().type_text(
        text,
        interval_seconds,
    )


def press_key(
    key: str,
) -> bool:
    """
    Press one key.
    """

    return get_keyboard_controller().press_key(
        key
    )


def press_hotkey(
    *keys: str,
) -> bool:
    """
    Press a hotkey combination.
    """

    return get_keyboard_controller().press_hotkey(
        *keys
    )


def hold_key(
    key: str,
    duration_seconds: float,
) -> bool:
    """
    Hold a key.
    """

    return get_keyboard_controller().hold_key(
        key,
        duration_seconds,
    )


def key_down(
    key: str,
) -> bool:
    """
    Key down.
    """

    return get_keyboard_controller().key_down(
        key
    )


def key_up(
    key: str,
) -> bool:
    """
    Key up.
    """

    return get_keyboard_controller().key_up(
        key
    )


# ============================================================================
# COMMON SHORTCUT FUNCTIONS
# ============================================================================

def copy() -> bool:
    return get_keyboard_controller().copy()


def paste() -> bool:
    return get_keyboard_controller().paste()


def cut() -> bool:
    return get_keyboard_controller().cut()


def undo() -> bool:
    return get_keyboard_controller().undo()


def redo() -> bool:
    return get_keyboard_controller().redo()


def select_all() -> bool:
    return get_keyboard_controller().select_all()


def save() -> bool:
    return get_keyboard_controller().save()


def save_as() -> bool:
    return get_keyboard_controller().save_as()


def find() -> bool:
    return get_keyboard_controller().find()


def replace() -> bool:
    return get_keyboard_controller().replace()


# ============================================================================
# WINDOWS SHORTCUT FUNCTIONS
# ============================================================================

def switch_window() -> bool:
    return get_keyboard_controller().switch_window()


def close_window() -> bool:
    return get_keyboard_controller().close_window()


def minimize_window() -> bool:
    return get_keyboard_controller().minimize_window()


def show_desktop() -> bool:
    return get_keyboard_controller().show_desktop()


def open_task_manager() -> bool:
    return get_keyboard_controller().open_task_manager()


def lock_screen() -> bool:
    return get_keyboard_controller().lock_screen()


def open_run() -> bool:
    return get_keyboard_controller().open_run()


def open_file_explorer() -> bool:
    return get_keyboard_controller().open_file_explorer()


def open_settings() -> bool:
    return get_keyboard_controller().open_settings()


# ============================================================================
# BROWSER FUNCTIONS
# ============================================================================

def new_tab() -> bool:
    return get_keyboard_controller().new_tab()


def close_tab() -> bool:
    return get_keyboard_controller().close_tab()


def reopen_closed_tab() -> bool:
    return get_keyboard_controller().reopen_closed_tab()


def refresh() -> bool:
    return get_keyboard_controller().refresh()


def hard_refresh() -> bool:
    return get_keyboard_controller().hard_refresh()


def browser_back() -> bool:
    return get_keyboard_controller().browser_back()


def browser_forward() -> bool:
    return get_keyboard_controller().browser_forward()


def new_window() -> bool:
    return get_keyboard_controller().new_window()


def open_private_window() -> bool:
    return get_keyboard_controller().open_private_window()


def focus_address_bar() -> bool:
    return get_keyboard_controller().focus_address_bar()


# ============================================================================
# SIMPLE KEY FUNCTIONS
# ============================================================================

def enter() -> bool:
    return get_keyboard_controller().enter()


def escape() -> bool:
    return get_keyboard_controller().escape()


def tab() -> bool:
    return get_keyboard_controller().tab()


def backspace() -> bool:
    return get_keyboard_controller().backspace()


def delete() -> bool:
    return get_keyboard_controller().delete()


def fullscreen() -> bool:
    return get_keyboard_controller().fullscreen()


# ============================================================================
# NAVIGATION FUNCTIONS
# ============================================================================

def move_up() -> bool:
    return get_keyboard_controller().move_up()


def move_down() -> bool:
    return get_keyboard_controller().move_down()


def move_left() -> bool:
    return get_keyboard_controller().move_left()


def move_right() -> bool:
    return get_keyboard_controller().move_right()


def go_home() -> bool:
    return get_keyboard_controller().go_home()


def go_end() -> bool:
    return get_keyboard_controller().go_end()


def page_up() -> bool:
    return get_keyboard_controller().page_up()


def page_down() -> bool:
    return get_keyboard_controller().page_down()


# ============================================================================
# COMMAND API
# ============================================================================

def execute_command(
    command: str,
) -> KeyboardCommandResult:
    """
    Execute a natural-language keyboard command.
    """

    return get_keyboard_controller().execute_command(
        command
    )


# ============================================================================
# DIAGNOSTICS API
# ============================================================================

def diagnostics() -> dict[str, Any]:
    """
    Get keyboard automation diagnostics.
    """

    return get_keyboard_controller().diagnostics()

# UPDATE

class KeyboardValidationError(Exception):
    """Raised when keyboard input validation fails."""

# ============================================================================
# MODULE METADATA
# ============================================================================

__title__ = "AssistantX Keyboard Automation"
__version__ = "1.0.0"
__author__ = "AssistantX Team"


__all__ = [
    # Exceptions (A-Z sorted)
    "HotkeyError",
    "InvalidDurationError",
    "InvalidKeyError",
    "InvalidTextError",
    "KeyboardAutomationError",
    "KeyboardBackendError",
    "KeyboardCommandError",
    
    # Configuration & Result
    "KeyboardCommandResult",
    "KeyboardConfig",
    
    # Controller
    "KeyboardController",
    
    # All functions and constants - Complete A-Z list
    "browser_back",
    "browser_forward",
    "close_tab",
    "close_window",
    "copy",
    "cut",
    "delete",
    "diagnostics",
    "enter",
    "escape",
    "execute_command",
    "find",
    "focus_address_bar",
    "fullscreen",
    "get_keyboard_controller",
    "go_end",
    "go_home",
    "hard_refresh",
    "hold_key",
    "hotkey",
    "is_available",
    "key_down",
    "key_up",
    "lock_screen",
    "minimize_window",
    "move_down",
    "move_left",
    "move_right",
    "move_up",
    "new_tab",
    "new_window",
    "open_file_explorer",
    "open_private_window",
    "open_run",
    "open_settings",
    "open_task_manager",
    "page_down",
    "page_up",
    "paste",
    "press",
    "press_hotkey",
    "press_key",
    "pyautogui",
    "redo",
    "refresh",
    "reopen_closed_tab",
    "replace",
    "save",
    "save_as",
    "select_all",
    "show_desktop",
    "switch_window",
    "tab",
    "type_text",
    "undo",
    "write_text",
]


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("AssistantX Keyboard Automation")
    print("=" * 70)

    print(
        "PyAutoGUI available:",
        is_available(),
    )

    controller = KeyboardController()

    print(
        "Diagnostics:"
    )

    for key, value in (
        controller.diagnostics()
        .items()
    ):
        print(
            f"  {key}: {value}"
        )

    print("=" * 70)
    print(
        "Keyboard controller initialized."
    )
    print(
        "No keyboard action was executed."
    )
    print("=" * 70)
    