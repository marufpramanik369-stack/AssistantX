"""
AssistantX - Mouse Automation
=============================

Professional mouse automation module for AssistantX.

Features
--------
- Get current mouse position
- Get screen resolution
- Move cursor
- Relative cursor movement
- Left / right / middle click
- Double / triple click
- Mouse button down / up
- Drag to position
- Relative drag
- Vertical scrolling
- Horizontal scrolling
- Move to screen center
- Move to screen corners
- Natural-language command execution
- Async-friendly API
- Thread-safe operations
- PyAutoGUI lazy backend
- Runtime availability checking
- Diagnostics
- Structured exceptions
- Logging integration

Dependency
----------
PyAutoGUI is optional.

Install:
    pip install pyautogui

The module does not import PyAutoGUI during module import. This allows
the rest of AssistantX to continue working when mouse automation is
not installed.

Author: AssistantX Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger

# ============================================================================
# LOGGER
# ============================================================================

logger = get_logger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================

class MouseAutomationError(RuntimeError):
    """
    Base exception for mouse automation."""

class MouseValidationError(MouseAutomationError):
    """Raised when mouse automation input is invalid."""


class MouseBackendError(MouseAutomationError):
    """
    Raised when PyAutoGUI is unavailable."""


class InvalidCoordinateError(MouseAutomationError):
    """
    Raised when a mouse coordinate is invalid."""


class InvalidButtonError(MouseAutomationError):
    """Raised when an unsupported mouse button is supplied."""


class InvalidDurationError(MouseAutomationError):
    """
    Raised when a duration is invalid.
    """


class InvalidScrollError(MouseAutomationError):
    """
    Raised when a scroll value is invalid.
    """


class MouseCommandError(MouseAutomationError):
    """
    Raised when a natural-language mouse command cannot be resolved.
    """


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass(frozen=True)
class Point:
    """
    Represents a screen coordinate.

    Attributes
    ----------
    x:
        Horizontal coordinate.

    y:
        Vertical coordinate.
    """

    x: int
    y: int

    def as_tuple(self) -> tuple[int, int]:
        """
        Return coordinate as tuple.
        """

        return self.x, self.y

    def to_dict(self) -> dict[str, int]:
        """
        Return coordinate as dictionary.
        """

        return {
            "x": self.x,
            "y": self.y,
        }


@dataclass
class MouseConfig:
    """
    Configuration for MouseController.

    Attributes
    ----------
    move_duration:
        Default cursor movement duration.

    click_pause:
        Pause after click operations.

    drag_duration:
        Default drag duration.

    failsafe:
        Enable PyAutoGUI failsafe.

    pause:
        Global PyAutoGUI pause.

    strict_validation:
        Enable input validation.
    """

    move_duration: float = 0.2
    click_pause: float = 0.05
    drag_duration: float = 0.4

    failsafe: bool = True
    pause: float = 0.01

    strict_validation: bool = True

    def __post_init__(self) -> None:

        if self.move_duration < 0:
            raise ValueError(
                "move_duration cannot be negative."
            )

        if self.click_pause < 0:
            raise ValueError(
                "click_pause cannot be negative."
            )

        if self.drag_duration < 0:
            raise ValueError(
                "drag_duration cannot be negative."
            )

        if self.pause < 0:
            raise ValueError(
                "pause cannot be negative."
            )


@dataclass
class MouseCommandResult:
    """
    Structured result returned by execute_command().
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
# CONSTANTS
# ============================================================================

SUPPORTED_BUTTONS = {
    "left",
    "right",
    "middle",
}


BUTTON_ALIASES: dict[str, str] = {
    "primary": "left",
    "secondary": "right",
    "main": "left",
    "context": "right",
    "center": "middle",
}


COMMAND_ALIASES: dict[str, str] = {
    "click": "click",
    "left click": "click",
    "click left": "click",

    "right click": "right_click",
    "click right": "right_click",

    "middle click": "middle_click",
    "click middle": "middle_click",

    "double click": "double_click",
    "double-click": "double_click",

    "triple click": "triple_click",

    "scroll up": "scroll_up",
    "scroll down": "scroll_down",

    "move center": "center",

    "mouse position": "position",
    "cursor position": "position",

    "screen size": "screen_size",
    "screen resolution": "screen_size",
}


# ============================================================================
# BACKEND
# ============================================================================

def _get_backend():
    """
    Lazily import PyAutoGUI.

    PyAutoGUI is intentionally not imported when this module loads.
    """

    try:
        import pyautogui  # type: ignore

    except ImportError as exc:
        raise MouseBackendError(
            "Mouse automation requires the 'pyautogui' package. "
            "Install it with: pip install pyautogui"
        ) from exc

    return pyautogui


# ============================================================================
# AVAILABILITY
# ============================================================================

def is_available() -> bool:
    """
    Return True when PyAutoGUI is available.
    """

    try:
        _get_backend()
        return True

    except MouseAutomationError:
        return False


# ============================================================================
# MOUSE CONTROLLER
# ============================================================================

class MouseController:
    """
    Main AssistantX mouse automation controller.

    Example
    -------
    mouse = MouseController()

    mouse.move_to(500, 300)
    mouse.click()
    mouse.double_click()
    mouse.scroll(5)
    """

    def __init__(
        self,
        config: MouseConfig | None = None,
    ) -> None:

        self.config = config or MouseConfig()

        self._lock = threading.RLock()

        self._actions_executed = 0
        self._last_action: str | None = None

        logger.info(
            "MouseController initialized."
        )

    # ------------------------------------------------------------------------
    # INTERNAL BACKEND
    # ------------------------------------------------------------------------

    def _backend(self):
        """
        Return configured PyAutoGUI backend.
        """

        backend = _get_backend()

        backend.FAILSAFE = (
            self.config.failsafe
        )

        backend.PAUSE = (
            self.config.pause
        )

        return backend

    # ------------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------------

    @staticmethod
    def _validate_coordinate(
        value: Any,
        name: str,
    ) -> int:
        """
        Validate one coordinate.
        """

        if isinstance(value, bool):
            raise InvalidCoordinateError(
                f"{name} must be an integer."
            )

        try:
            converted = int(value)

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise InvalidCoordinateError(
                f"{name} must be an integer."
            ) from exc

        return converted

    def _validate_coordinates(
        self,
        x: int,
        y: int,
    ) -> tuple[int, int]:
        """
        Validate X/Y coordinates.
        """

        x_value = self._validate_coordinate(
            x,
            "x",
        )

        y_value = self._validate_coordinate(
            y,
            "y",
        )

        if self.config.strict_validation:

            size = self.get_screen_size()

            if not (
                0 <= x_value < size.x
                and
                0 <= y_value < size.y
            ):
                raise InvalidCoordinateError(
                    f"Coordinates ({x_value}, {y_value}) "
                    f"are outside the primary screen "
                    f"({size.x}x{size.y})."
                )

        return x_value, y_value

    @staticmethod
    def _validate_button(
        button: str,
    ) -> str:
        """
        Normalize and validate mouse button.
        """

        if not isinstance(button, str):
            raise InvalidButtonError(
                "Mouse button must be a string."
            )

        normalized = (
            button
            .strip()
            .lower()
        )

        normalized = BUTTON_ALIASES.get(
            normalized,
            normalized,
        )

        if normalized not in SUPPORTED_BUTTONS:
            raise InvalidButtonError(
                f"Unsupported mouse button: {button}. "
                f"Supported buttons: "
                f"{', '.join(sorted(SUPPORTED_BUTTONS))}"
            )

        return normalized

    @staticmethod
    def _validate_duration(
        duration: float,
        name: str = "duration",
    ) -> float:
        """
        Validate duration.
        """

        try:
            value = float(duration)

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise InvalidDurationError(
                f"{name} must be a number."
            ) from exc

        if value < 0:
            raise InvalidDurationError(
                f"{name} cannot be negative."
            )

        return value

    @staticmethod
    def _validate_scroll(
        amount: int,
    ) -> int:
        """
        Validate scroll amount.
        """

        if isinstance(amount, bool):
            raise InvalidScrollError(
                "Scroll amount must be an integer."
            )

        try:
            value = int(amount)

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise InvalidScrollError(
                "Scroll amount must be an integer."
            ) from exc

        if value == 0:
            raise InvalidScrollError(
                "Scroll amount cannot be zero."
            )

        return value

    # ------------------------------------------------------------------------
    # INTERNAL STATISTICS
    # ------------------------------------------------------------------------

    def _record_action(
        self,
        action: str,
    ) -> None:
        """
        Record action statistics.
        """

        self._actions_executed += 1
        self._last_action = action

        logger.info(
            "Mouse action executed: %s",
            action,
        )

    # ------------------------------------------------------------------------
    # POSITION
    # ------------------------------------------------------------------------

    def get_position(self) -> Point:
        """
        Return current cursor position.
        """

        backend = self._backend()

        try:
            position = backend.position()

            return Point(
                x=int(position.x),
                y=int(position.y),
            )

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to get mouse position: {exc}"
            ) from exc

    def get_screen_size(self) -> Point:
        """
        Return primary screen resolution.

        Example:
            Point(x=1920, y=1080)
        """

        backend = self._backend()

        try:
            size = backend.size()

            return Point(
                x=int(size.width),
                y=int(size.height),
            )

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to get screen size: {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # MOVEMENT
    # ------------------------------------------------------------------------

    def move_to(
        self,
        x: int,
        y: int,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to an absolute screen position.
        """

        x_value, y_value = (
            self._validate_coordinates(
                x,
                y,
            )
        )

        if duration_seconds is None:
            duration_seconds = (
                self.config.move_duration
            )

        duration = self._validate_duration(
            duration_seconds,
            "move duration",
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.moveTo(
                    x_value,
                    y_value,
                    duration=duration,
                )

                self._record_action(
                    f"move_to:{x_value},{y_value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to move mouse to "
                f"({x_value}, {y_value}): {exc}"
            ) from exc

    def move_relative(
        self,
        dx: int,
        dy: int,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor relative to current position.
        """

        dx_value = self._validate_coordinate(
            dx,
            "dx",
        )

        dy_value = self._validate_coordinate(
            dy,
            "dy",
        )

        if duration_seconds is None:
            duration_seconds = (
                self.config.move_duration
            )

        duration = self._validate_duration(
            duration_seconds,
            "move duration",
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.moveRel(
                    dx_value,
                    dy_value,
                    duration=duration,
                )

                self._record_action(
                    f"move_relative:{dx_value},{dy_value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to move mouse by "
                f"({dx_value}, {dy_value}): {exc}"
            ) from exc

    def move_center(
        self,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to the center of the primary screen.
        """

        size = self.get_screen_size()

        center_x = size.x // 2
        center_y = size.y // 2

        return self.move_to(
            center_x,
            center_y,
            duration_seconds,
        )

    def move_top_left(
        self,
        padding: int = 5,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to top-left screen corner.
        """

        padding = max(0, int(padding))

        return self.move_to(
            padding,
            padding,
            duration_seconds,
        )

    def move_top_right(
        self,
        padding: int = 5,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to top-right screen corner.
        """

        size = self.get_screen_size()

        padding = max(0, int(padding))

        return self.move_to(
            size.x - 1 - padding,
            padding,
            duration_seconds,
        )

    def move_bottom_left(
        self,
        padding: int = 5,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to bottom-left screen corner.
        """

        size = self.get_screen_size()

        padding = max(0, int(padding))

        return self.move_to(
            padding,
            size.y - 1 - padding,
            duration_seconds,
        )

    def move_bottom_right(
        self,
        padding: int = 5,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Move cursor to bottom-right screen corner.
        """

        size = self.get_screen_size()

        padding = max(0, int(padding))

        return self.move_to(
            size.x - 1 - padding,
            size.y - 1 - padding,
            duration_seconds,
        )

    # ------------------------------------------------------------------------
    # CLICKING
    # ------------------------------------------------------------------------

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
        interval_seconds: float = 0.1,
    ) -> bool:
        """
        Click at an optional position.

        If x/y are omitted, the current cursor position is used.
        """

        normalized_button = (
            self._validate_button(
                button
            )
        )

        if not isinstance(clicks, int):
            raise ValueError(
                "clicks must be an integer."
            )

        if clicks <= 0:
            raise ValueError(
                "clicks must be greater than zero."
            )

        interval = self._validate_duration(
            interval_seconds,
            "click interval",
        )

        if (
            x is not None
            and y is not None
        ):
            x_value, y_value = (
                self._validate_coordinates(
                    x,
                    y,
                )
            )

        elif (
            x is None
            and y is None
        ):
            x_value = None
            y_value = None

        else:
            raise InvalidCoordinateError(
                "Both x and y must be supplied together."
            )

        backend = self._backend()

        try:

            with self._lock:

                backend.click(
                    x=x_value,
                    y=y_value,
                    button=normalized_button,
                    clicks=clicks,
                    interval=interval,
                )

                self._record_action(
                    f"click:{normalized_button}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to click: {exc}"
            ) from exc

    def left_click(
        self,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        """
        Perform a left click.
        """

        return self.click(
            x=x,
            y=y,
            button="left",
        )

    def right_click(
        self,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        """
        Perform a right click.
        """

        return self.click(
            x=x,
            y=y,
            button="right",
        )

    def middle_click(
        self,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        """
        Perform a middle click.
        """

        return self.click(
            x=x,
            y=y,
            button="middle",
        )

    def double_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
    ) -> bool:
        """
        Perform a double click.
        """

        return self.click(
            x=x,
            y=y,
            button=button,
            clicks=2,
            interval_seconds=0.1,
        )

    def triple_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
    ) -> bool:
        """
        Perform a triple click.
        """

        return self.click(
            x=x,
            y=y,
            button=button,
            clicks=3,
            interval_seconds=0.1,
        )

    # ------------------------------------------------------------------------
    # MOUSE BUTTON STATE
    # ------------------------------------------------------------------------

    def button_down(
        self,
        button: str = "left",
    ) -> bool:
        """
        Press a mouse button down without releasing it.

        Always call button_up() afterward.
        """

        normalized_button = (
            self._validate_button(
                button
            )
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.mouseDown(
                    button=normalized_button
                )

                self._record_action(
                    f"button_down:{normalized_button}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to press mouse button "
                f"'{normalized_button}': {exc}"
            ) from exc

    def button_up(
        self,
        button: str = "left",
    ) -> bool:
        """
        Release a mouse button.
        """

        normalized_button = (
            self._validate_button(
                button
            )
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.mouseUp(
                    button=normalized_button
                )

                self._record_action(
                    f"button_up:{normalized_button}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to release mouse button "
                f"'{normalized_button}': {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # DRAGGING
    # ------------------------------------------------------------------------

    def drag_to(
        self,
        x: int,
        y: int,
        duration_seconds: float | None = None,
        button: str = "left",
    ) -> bool:
        """
        Drag from current cursor position to x/y.
        """

        x_value, y_value = (
            self._validate_coordinates(
                x,
                y,
            )
        )

        normalized_button = (
            self._validate_button(
                button
            )
        )

        if duration_seconds is None:
            duration_seconds = (
                self.config.drag_duration
            )

        duration = self._validate_duration(
            duration_seconds,
            "drag duration",
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.dragTo(
                    x_value,
                    y_value,
                    duration=duration,
                    button=normalized_button,
                )

                self._record_action(
                    f"drag_to:{x_value},{y_value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to drag to "
                f"({x_value}, {y_value}): {exc}"
            ) from exc

    def drag_relative(
        self,
        dx: int,
        dy: int,
        duration_seconds: float | None = None,
        button: str = "left",
    ) -> bool:
        """
        Drag relative to current cursor position.
        """

        dx_value = self._validate_coordinate(
            dx,
            "dx",
        )

        dy_value = self._validate_coordinate(
            dy,
            "dy",
        )

        normalized_button = (
            self._validate_button(
                button
            )
        )

        if duration_seconds is None:
            duration_seconds = (
                self.config.drag_duration
            )

        duration = self._validate_duration(
            duration_seconds,
            "drag duration",
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.dragRel(
                    dx_value,
                    dy_value,
                    duration=duration,
                    button=normalized_button,
                )

                self._record_action(
                    f"drag_relative:{dx_value},{dy_value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to drag by "
                f"({dx_value}, {dy_value}): {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # SCROLLING
    # ------------------------------------------------------------------------

    def scroll(
        self,
        amount: int,
    ) -> bool:
        """
        Scroll vertically.

        Positive = up.
        Negative = down.
        """

        value = self._validate_scroll(
            amount
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.scroll(value)

                self._record_action(
                    f"scroll:{value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to scroll: {exc}"
            ) from exc

    def scroll_up(
        self,
        amount: int = 5,
    ) -> bool:
        """
        Scroll up.
        """

        amount = abs(int(amount))

        return self.scroll(
            amount
        )

    def scroll_down(
        self,
        amount: int = 5,
    ) -> bool:
        """
        Scroll down.
        """

        amount = abs(int(amount))

        return self.scroll(
            -amount
        )

    def scroll_horizontal(
        self,
        amount: int,
    ) -> bool:
        """
        Horizontal scrolling.

        Positive = right.
        Negative = left.
        """

        value = self._validate_scroll(
            amount
        )

        backend = self._backend()

        try:

            with self._lock:

                backend.hscroll(value)

                self._record_action(
                    f"hscroll:{value}"
                )

            return True

        except Exception as exc:

            raise MouseAutomationError(
                f"Failed to horizontal-scroll: {exc}"
            ) from exc

    def scroll_left(
        self,
        amount: int = 5,
    ) -> bool:
        """
        Scroll horizontally left.
        """

        amount = abs(int(amount))

        return self.scroll_horizontal(
            -amount
        )

    def scroll_right(
        self,
        amount: int = 5,
    ) -> bool:
        """
        Scroll horizontally right.
        """

        amount = abs(int(amount))

        return self.scroll_horizontal(
            amount
        )

    # ------------------------------------------------------------------------
    # COMMAND PARSER
    # ------------------------------------------------------------------------

    @staticmethod
    def normalize_command(
        command: str,
    ) -> str:
        """
        Normalize a natural-language command.
        """

        if not isinstance(command, str):
            raise MouseCommandError(
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
    ) -> MouseCommandResult:
        """
        Execute a natural-language mouse command.

        Examples
        --------
        execute_command("click")
        execute_command("right click")
        execute_command("double click")
        execute_command("scroll up")
        execute_command("scroll down")
        execute_command("move center")
        execute_command("mouse position")
        """

        normalized = self.normalize_command(
            command
        )

        if not normalized:
            return MouseCommandResult(
                success=False,
                action="unknown",
                message="Mouse command is empty.",
            )

        action = COMMAND_ALIASES.get(
            normalized
        )

        try:

            if action == "click":

                self.left_click()

                return MouseCommandResult(
                    True,
                    "click",
                    "Left click completed.",
                )

            if action == "right_click":

                self.right_click()

                return MouseCommandResult(
                    True,
                    "right_click",
                    "Right click completed.",
                )

            if action == "middle_click":

                self.middle_click()

                return MouseCommandResult(
                    True,
                    "middle_click",
                    "Middle click completed.",
                )

            if action == "double_click":

                self.double_click()

                return MouseCommandResult(
                    True,
                    "double_click",
                    "Double click completed.",
                )

            if action == "triple_click":

                self.triple_click()

                return MouseCommandResult(
                    True,
                    "triple_click",
                    "Triple click completed.",
                )

            if action == "scroll_up":

                self.scroll_up()

                return MouseCommandResult(
                    True,
                    "scroll_up",
                    "Scrolled up.",
                )

            if action == "scroll_down":

                self.scroll_down()

                return MouseCommandResult(
                    True,
                    "scroll_down",
                    "Scrolled down.",
                )

            if action == "center":

                self.move_center()

                position = (
                    self.get_position()
                )

                return MouseCommandResult(
                    True,
                    "center",
                    "Cursor moved to screen center.",
                    position.to_dict(),
                )

            if action == "position":

                position = (
                    self.get_position()
                )

                return MouseCommandResult(
                    True,
                    "position",
                    "Current mouse position retrieved.",
                    position.to_dict(),
                )

            if action == "screen_size":

                size = (
                    self.get_screen_size()
                )

                return MouseCommandResult(
                    True,
                    "screen_size",
                    "Screen size retrieved.",
                    size.to_dict(),
                )

            # --------------------------------------------------------------
            # Dynamic move command
            #
            # Example:
            #   move 500 300
            # --------------------------------------------------------------

            if normalized.startswith(
                "move "
            ):

                parts = normalized.split()

                if len(parts) != 3:
                    return MouseCommandResult(
                        False,
                        "move",
                        "Use: move X Y",
                    )

                x = int(parts[1])
                y = int(parts[2])

                self.move_to(
                    x,
                    y,
                )

                return MouseCommandResult(
                    True,
                    "move",
                    f"Cursor moved to ({x}, {y}).",
                    {
                        "x": x,
                        "y": y,
                    },
                )

            # --------------------------------------------------------------
            # Dynamic relative move
            #
            # Example:
            #   move relative 100 -50
            # --------------------------------------------------------------

            if normalized.startswith(
                "move relative "
            ):

                parts = normalized.split()

                if len(parts) != 4:
                    return MouseCommandResult(
                        False,
                        "move_relative",
                        "Use: move relative DX DY",
                    )

                dx = int(parts[2])
                dy = int(parts[3])

                self.move_relative(
                    dx,
                    dy,
                )

                return MouseCommandResult(
                    True,
                    "move_relative",
                    f"Cursor moved by ({dx}, {dy}).",
                    {
                        "dx": dx,
                        "dy": dy,
                    },
                )

            return MouseCommandResult(
                success=False,
                action="unknown",
                message=(
                    f"Unknown mouse command: "
                    f"{command}"
                ),
            )

        except MouseAutomationError as exc:

            logger.warning(
                "Mouse command failed: %s",
                exc,
            )

            return MouseCommandResult(
                success=False,
                action=action or "error",
                message=str(exc),
            )

        except (
            ValueError,
            TypeError,
        ) as exc:

            logger.warning(
                "Invalid mouse command: %s",
                exc,
            )

            return MouseCommandResult(
                success=False,
                action=action or "error",
                message=str(exc),
            )

        except Exception as exc:

            logger.exception(
                "Unexpected mouse command error."
            )

            return MouseCommandResult(
                success=False,
                action=action or "error",
                message=str(exc),
            )

    # ------------------------------------------------------------------------
    # ASYNC API
    # ------------------------------------------------------------------------

    async def async_move_to(
        self,
        x: int,
        y: int,
        duration_seconds: float | None = None,
    ) -> bool:
        """
        Async move.
        """

        return await asyncio.to_thread(
            self.move_to,
            x,
            y,
            duration_seconds,
        )

    async def async_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> bool:
        """
        Async click.
        """

        return await asyncio.to_thread(
            self.click,
            x,
            y,
            button,
            clicks,
        )

    async def async_double_click(
        self,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        """
        Async double click.
        """

        return await asyncio.to_thread(
            self.double_click,
            x,
            y,
        )

    async def async_right_click(
        self,
        x: int | None = None,
        y: int | None = None,
    ) -> bool:
        """
        Async right click.
        """

        return await asyncio.to_thread(
            self.right_click,
            x,
            y,
        )

    async def async_scroll(
        self,
        amount: int,
    ) -> bool:
        """
        Async scroll.
        """

        return await asyncio.to_thread(
            self.scroll,
            amount,
        )

    async def async_drag_to(
        self,
        x: int,
        y: int,
        duration_seconds: float | None = None,
        button: str = "left",
    ) -> bool:
        """
        Async drag.
        """

        return await asyncio.to_thread(
            self.drag_to,
            x,
            y,
            duration_seconds,
            button,
        )

    async def async_execute_command(
        self,
        command: str,
    ) -> MouseCommandResult:
        """
        Async natural-language command.
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
        Return mouse automation diagnostics.
        """

        position: dict[str, int] | None = None
        screen: dict[str, int] | None = None

        available = is_available()

        if available:

            try:
                position = (
                    self.get_position()
                    .to_dict()
                )
            except Exception:
                position = None

            try:
                screen = (
                    self.get_screen_size()
                    .to_dict()
                )
            except Exception:
                screen = None

        return {
            "platform": os.name,
            "backend": "pyautogui",
            "available": available,
            "failsafe": (
                self.config.failsafe
            ),
            "pause": (
                self.config.pause
            ),
            "move_duration": (
                self.config.move_duration
            ),
            "drag_duration": (
                self.config.drag_duration
            ),
            "actions_executed": (
                self._actions_executed
            ),
            "last_action": (
                self._last_action
            ),
            "position": position,
            "screen_size": screen,
        }

    # ------------------------------------------------------------------------
    # RESET
    # ------------------------------------------------------------------------

    def reset_statistics(self) -> None:
        """
        Reset action statistics.
        """

        with self._lock:

            self._actions_executed = 0
            self._last_action = None

        logger.info(
            "Mouse statistics reset."
        )

    # ------------------------------------------------------------------------
    # CONTEXT MANAGER
    # ------------------------------------------------------------------------

    def __enter__(
        self,
    ) -> MouseController:

        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:

        logger.debug(
            "MouseController context closed."
        )

    # ------------------------------------------------------------------------
    # REPRESENTATION
    # ------------------------------------------------------------------------

    def __repr__(self) -> str:

        return (
            "<MouseController "
            f"available={is_available()} "
            f"actions={self._actions_executed}>"
        )


# ============================================================================
# SINGLETON
# ============================================================================

_default_controller: MouseController | None = None

_controller_lock = threading.Lock()


def get_mouse_controller() -> MouseController:
    """
    Return the shared AssistantX MouseController.
    """

    global _default_controller

    with _controller_lock:

        if _default_controller is None:

            _default_controller = (
                MouseController()
            )

        return _default_controller


# ============================================================================
# BACKWARD-COMPATIBLE FUNCTIONS
# ============================================================================

def get_position() -> Point:
    """
    Get current cursor position.
    """

    return (
        get_mouse_controller()
        .get_position()
    )


def get_screen_size() -> Point:
    """
    Get primary screen size.
    """

    return (
        get_mouse_controller()
        .get_screen_size()
    )


def move_to(
    x: int,
    y: int,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move cursor.
    """

    return (
        get_mouse_controller()
        .move_to(
            x,
            y,
            duration_seconds,
        )
    )

# UPDATE 

def safe_move_to(
    x: int,
    y: int,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Safely move cursor to a position.

    Returns:
        True if successful, otherwise False.
    """

    try:
        return move_to(
            x=x,
            y=y,
            duration_seconds=duration_seconds,
        )

    except MouseAutomationError as exc:
        logger.warning(
            "safe_move_to failed: %s",
            exc,
        )
        return False


def move_relative(
    dx: int,
    dy: int,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move cursor relative to current position.
    """

    return (
        get_mouse_controller()
        .move_relative(
            dx,
            dy,
            duration_seconds,
        )
    )


def click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> bool:
    """
    Click mouse.
    """

    return (
        get_mouse_controller()
        .click(
            x=x,
            y=y,
            button=button,
            clicks=clicks,
        )
    )


# UPDATE 


def safe_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
) -> bool:
    """
    Safely perform a mouse click.

    Returns:
        True if the click succeeds.
        False if the operation fails.
    """

    try:
        return click(
            x=x,
            y=y,
            button=button,
            clicks=clicks,
        )

    except MouseAutomationError as exc:
        logger.warning(
            "safe_click failed: %s",
            exc,
        )
        return False



def left_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Left click.
    """

    return (
        get_mouse_controller()
        .left_click(
            x,
            y,
        )
    )


def right_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Right click.
    """

    return (
        get_mouse_controller()
        .right_click(
            x,
            y,
        )
    )


def safe_right_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Safely perform a right mouse click.

    Returns:
        True if successful, otherwise False.
    """
    try:
        return right_click(
            x=x,
            y=y,
        )
    except MouseAutomationError as exc:
        logger.warning(
            "safe_right_click failed: %s",
            exc,
        )
        return False


def safe_middle_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Safely perform a middle mouse click.

    Returns:
        True if successful, otherwise False.
    """
    try:
        return middle_click(
            x=x,
            y=y,
        )
    except MouseAutomationError as exc:
        logger.warning(
            "safe_middle_click failed: %s",
            exc,
        )
        return False


def middle_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Middle click.
    """

    return (
        get_mouse_controller()
        .middle_click(
            x,
            y,
        )
    )


def double_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Double click.
    """

    return (
        get_mouse_controller()
        .double_click(
            x,
            y,
        )
    )

# UPDATE

def safe_double_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Safely perform a double mouse click.

    Returns:
        True if the operation succeeds.
        False if the operation fails.
    """

    try:
        return double_click(
            x=x,
            y=y,
        )

    except MouseAutomationError as exc:
        logger.warning(
            "safe_double_click failed: %s",
            exc,
        )
        return False


def triple_click(
    x: int | None = None,
    y: int | None = None,
) -> bool:
    """
    Triple click.
    """

    return (
        get_mouse_controller()
        .triple_click(
            x,
            y,
        )
    )


def button_down(
    button: str = "left",
) -> bool:
    """
    Press mouse button down.
    """

    return (
        get_mouse_controller()
        .button_down(
            button
        )
    )


def button_up(
    button: str = "left",
) -> bool:
    """
    Release mouse button.
    """

    return (
        get_mouse_controller()
        .button_up(
            button
        )
    )


# ============================================================================
# DRAG FUNCTIONS
# ============================================================================

def drag_to(
    x: int,
    y: int,
    duration_seconds: float = 0.4,
    button: str = "left",
) -> bool:
    """
    Drag cursor to target.
    """

    return (
        get_mouse_controller()
        .drag_to(
            x,
            y,
            duration_seconds,
            button,
        )
    )


def drag_relative(
    dx: int,
    dy: int,
    duration_seconds: float = 0.4,
    button: str = "left",
) -> bool:
    """
    Drag cursor relative to current position.
    """

    return (
        get_mouse_controller()
        .drag_relative(
            dx,
            dy,
            duration_seconds,
            button,
        )
    )


# ============================================================================
# SCROLL FUNCTIONS
# ============================================================================

def scroll(
    amount: int,
) -> bool:
    """
    Vertical scroll.
    """

    return (
        get_mouse_controller()
        .scroll(amount)
    )

# UPDATE 

def safe_scroll(
    amount: int,
) -> bool:
    """
    Safely scroll vertically.

    Returns:
        True if successful, otherwise False.
    """
    try:
        return scroll(
            amount=amount,
        )
    except MouseAutomationError as exc:
        logger.warning(
            "safe_scroll failed: %s",
            exc,
        )
        return False

def scroll_up(
    amount: int = 5,
) -> bool:
    """
    Scroll up.
    """

    return (
        get_mouse_controller()
        .scroll_up(amount)
    )


def scroll_down(
    amount: int = 5,
) -> bool:
    """
    Scroll down.
    """

    return (
        get_mouse_controller()
        .scroll_down(amount)
    )


def scroll_horizontal(
    amount: int,
) -> bool:
    """
    Horizontal scroll.
    """

    return (
        get_mouse_controller()
        .scroll_horizontal(amount)
    )


def scroll_left(
    amount: int = 5,
) -> bool:
    """
    Scroll left.
    """

    return (
        get_mouse_controller()
        .scroll_left(amount)
    )


def scroll_right(
    amount: int = 5,
) -> bool:
    """
    Scroll right.
    """

    return (
        get_mouse_controller()
        .scroll_right(amount)
    )


# ============================================================================
# POSITION HELPERS
# ============================================================================

def move_center(
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move to screen center.
    """

    return (
        get_mouse_controller()
        .move_center(
            duration_seconds
        )
    )


def move_top_left(
    padding: int = 5,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move to top-left.
    """

    return (
        get_mouse_controller()
        .move_top_left(
            padding,
            duration_seconds,
        )
    )


def move_top_right(
    padding: int = 5,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move to top-right.
    """

    return (
        get_mouse_controller()
        .move_top_right(
            padding,
            duration_seconds,
        )
    )


def move_bottom_left(
    padding: int = 5,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move to bottom-left.
    """

    return (
        get_mouse_controller()
        .move_bottom_left(
            padding,
            duration_seconds,
        )
    )


def move_bottom_right(
    padding: int = 5,
    duration_seconds: float = 0.2,
) -> bool:
    """
    Move to bottom-right.
    """

    return (
        get_mouse_controller()
        .move_bottom_right(
            padding,
            duration_seconds,
        )
    )


# ============================================================================
# COMMAND API
# ============================================================================

def execute_command(
    command: str,
) -> MouseCommandResult:
    """
    Execute natural-language mouse command.
    """

    return (
        get_mouse_controller()
        .execute_command(
            command
        )
    )


# ============================================================================
# DIAGNOSTICS API
# ============================================================================

def diagnostics() -> dict[str, Any]:
    """
    Return mouse automation diagnostics.
    """

    return (
        get_mouse_controller()
        .diagnostics()
    )


# ============================================================================
# MODULE METADATA
# ============================================================================

__title__ = "AssistantX Mouse Automation"
__version__ = "1.0.0"
__author__ = "AssistantX Team"


__all__ = [
    # Exceptions
    "MouseAutomationError",
    "MouseBackendError",
    "InvalidCoordinateError",
    "InvalidButtonError",
    "InvalidDurationError",
    "InvalidScrollError",
    "MouseCommandError",

    # Data
    "Point",
    "MouseConfig",
    "MouseCommandResult",

    # Controller
    "MouseController",
    "get_mouse_controller",

    # Availability
    "is_available",

    # Position
    "get_position",
    "get_screen_size",

    # Movement
    "move_to",
    "safe_move_to",
    "move_relative",
    "move_center",
    "move_top_left",
    "move_top_right",
    "move_bottom_left",
    "move_bottom_right",

    # Clicking
    "click",
    "safe_click",
    "safe_right_click",
    "left_click",
    "right_click",
    "middle_click",
    "safe_middle_click",
    "double_click",
    "safe_double_click",
    "triple_click",

    # Button
    "button_down",
    "button_up",

    # Drag
    "drag_to",
    "drag_relative",
    
    # Scroll
    "scroll",
    "safe_scroll",
    "scroll_up",
    "scroll_down",
    "scroll_horizontal",
    "scroll_left",
    "scroll_right",

    # Command
    "execute_command",

    # Diagnostics
    "diagnostics",
]


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("AssistantX Mouse Automation")
    print("=" * 70)

    print(
        "PyAutoGUI available:",
        is_available(),
    )

    controller = MouseController()

    print(
        "Diagnostics:"
    )

    for key, value in (
        controller
        .diagnostics()
        .items()
    ):
        print(
            f"  {key}: {value}"
        )

    print("=" * 70)
    print(
        "Mouse controller initialized."
    )

    print(
        "No mouse action was executed."
    )

    print("=" * 70)
    