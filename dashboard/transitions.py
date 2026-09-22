"""
AssistantX Dashboard - Transitions
==================================

Professional transition and page-animation utilities for AssistantX.

Features:
    - Fade transitions
    - Slide transitions
    - Scale transitions
    - Cross-fade page switching
    - Reduced-motion support
    - Cancellation
    - Thread-safe state tracking
    - Tkinter.after based animation
    - No external dependencies
"""

from __future__ import annotations

import contextlib
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

# ============================================================================
# COLORS / DEFAULTS
# ============================================================================

DEFAULT_DURATION = 220
MIN_DURATION = 0
MAX_DURATION = 5000

DEFAULT_FPS = 60
MIN_FPS = 15
MAX_FPS = 120


# ============================================================================
# EXCEPTIONS
# ============================================================================

class TransitionError(Exception):
    """Base transition error."""


class TransitionConfigurationError(TransitionError):
    """Invalid transition configuration."""


class TransitionStateError(TransitionError):
    """Invalid transition state."""


# ============================================================================
# ENUMS
# ============================================================================

class TransitionType(str, Enum):
    """Supported transition types."""

    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    SCALE = "scale"
    CROSS_FADE = "cross_fade"


class TransitionState(str, Enum):
    """Transition lifecycle state."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Easing(str, Enum):
    """Built-in easing functions."""

    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    SMOOTH = "smooth"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass(frozen=True)
class TransitionConfig:
    """Transition configuration."""

    transition_type: TransitionType = TransitionType.FADE

    duration: int = DEFAULT_DURATION

    fps: int = DEFAULT_FPS

    easing: Easing = Easing.EASE_OUT

    enabled: bool = True

    reduced_motion: bool = False

    destroy_old: bool = False

    offset: int = 30

    def __post_init__(self) -> None:

        if not isinstance(
            self.transition_type,
            TransitionType,
        ):
            try:
                object.__setattr__(
                    self,
                    "transition_type",
                    TransitionType(
                        self.transition_type
                    ),
                )
            except ValueError as exc:
                raise TransitionConfigurationError(
                    "Invalid transition type."
                ) from exc

        if not isinstance(
            self.easing,
            Easing,
        ):
            try:
                object.__setattr__(
                    self,
                    "easing",
                    Easing(self.easing),
                )
            except ValueError as exc:
                raise TransitionConfigurationError(
                    "Invalid easing."
                ) from exc

        if not (
            MIN_DURATION
            <= self.duration
            <= MAX_DURATION
        ):
            raise TransitionConfigurationError(
                f"duration must be between "
                f"{MIN_DURATION} and {MAX_DURATION}."
            )

        if not (
            MIN_FPS
            <= self.fps
            <= MAX_FPS
        ):
            raise TransitionConfigurationError(
                f"fps must be between "
                f"{MIN_FPS} and {MAX_FPS}."
            )

        if self.offset < 0:
            raise TransitionConfigurationError(
                "offset cannot be negative."
            )


@dataclass
class TransitionStats:
    """Runtime transition statistics."""

    started: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0

    total_duration_ms: float = 0.0

    last_transition: str | None = None

    @property
    def average_duration_ms(self) -> float:

        if self.completed <= 0:
            return 0.0

        return (
            self.total_duration_ms
            / self.completed
        )


# ============================================================================
# TRANSITION HANDLE
# ============================================================================

class TransitionHandle:
    """
    Handle returned by a running transition.

    Allows:
        - cancel()
        - completed
        - cancelled
        - state
    """

    def __init__(
        self,
        manager: TransitionManager,
        transition_id: int,
    ) -> None:

        self._manager = manager
        self.transition_id = transition_id

    @property
    def state(self) -> TransitionState:
        return self._manager.get_state(
            self.transition_id
        )

    @property
    def completed(self) -> bool:
        return self.state == TransitionState.COMPLETED

    @property
    def cancelled(self) -> bool:
        return self.state == TransitionState.CANCELLED

    @property
    def running(self) -> bool:
        return self.state == TransitionState.RUNNING

    def cancel(self) -> bool:
        return self._manager.cancel(
            self.transition_id
        )


# ============================================================================
# EASING FUNCTIONS
# ============================================================================

def ease_linear(value: float) -> float:
    return value


def ease_in(value: float) -> float:
    return value * value


def ease_out(value: float) -> float:
    return 1.0 - (
        1.0 - value
    ) ** 2


def ease_in_out(value: float) -> float:

    if value < 0.5:
        return 2.0 * value * value

    return 1.0 - (
        (-2.0 * value + 2.0) ** 2
    ) / 2.0


def ease_smooth(value: float) -> float:
    """
    Smoothstep easing.
    """

    return (
        value
        * value
        * (3.0 - 2.0 * value)
    )


def apply_easing(
    value: float,
    easing: Easing,
) -> float:

    value = max(
        0.0,
        min(
            1.0,
            value,
        ),
    )

    if easing == Easing.LINEAR:
        return ease_linear(value)

    if easing == Easing.EASE_IN:
        return ease_in(value)

    if easing == Easing.EASE_OUT:
        return ease_out(value)

    if easing == Easing.EASE_IN_OUT:
        return ease_in_out(value)

    return ease_smooth(value)


# ============================================================================
# TRANSITION MANAGER
# ============================================================================

class TransitionManager:
    """
    Central transition manager.

    Recommended:
        manager = TransitionManager(root)

        manager.fade(
            old_frame,
            new_frame,
        )
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        enabled: bool = True,
        reduced_motion: bool = False,
    ) -> None:

        if root is None:
            raise TransitionConfigurationError(
                "root cannot be None."
            )

        self.root = root

        self._enabled = bool(enabled)
        self._reduced_motion = bool(
            reduced_motion
        )

        self._lock = RLock()

        self._next_id = 1

        self._states: dict[
            int,
            TransitionState,
        ] = {}

        self._jobs: dict[
            int,
            Any,
        ] = {}

        self._stats = TransitionStats()

        self._shutdown = False

    # ========================================================================
    # CORE ANIMATION
    # ========================================================================

    def animate(
        self,
        widget: tk.Misc,
        *,
        config: TransitionConfig | None = None,
        start: Callable[[], None] | None = None,
        update: Callable[[float], None] | None = None,
        complete: Callable[[], None] | None = None,
    ) -> TransitionHandle:

        if widget is None:
            raise TransitionConfigurationError(
                "widget cannot be None."
            )

        config = config or TransitionConfig()

        transition_id = self._create_transition(
            config.transition_type
        )

        handle = TransitionHandle(
            self,
            transition_id,
        )

        # Disabled / reduced motion
        if (
            not self._enabled
            or not config.enabled
            or self._reduced_motion
            or config.reduced_motion
            or config.transition_type
            == TransitionType.NONE
            or config.duration == 0
        ):

            self._start_transition(
                transition_id
            )

            try:

                if start:
                    start()

                if update:
                    update(1.0)

                if complete:
                    complete()

                self._complete_transition(
                    transition_id
                )

            except Exception:
                self._fail_transition(
                    transition_id
                )
                raise

            return handle

        self._start_transition(
            transition_id
        )

        try:

            if start:
                start()

            start_time = time.perf_counter()

            interval = max(
                1,
                int(
                    1000
                    / config.fps
                ),
            )

            def tick() -> None:

                if self._is_terminal(
                    transition_id
                ):
                    return

                try:

                    elapsed = (
                        time.perf_counter()
                        - start_time
                    )

                    progress = min(
                        1.0,
                        elapsed
                        / (
                            config.duration
                            / 1000.0
                        ),
                    )

                    eased = apply_easing(
                        progress,
                        config.easing,
                    )

                    if update:
                        update(eased)

                    if progress >= 1.0:

                        if complete:
                            complete()

                        self._complete_transition(
                            transition_id
                        )

                        return

                    job = self.root.after(
                        interval,
                        tick,
                    )

                    with self._lock:
                        self._jobs[
                            transition_id
                        ] = job

                except (
                    tk.TclError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    AttributeError,
                ):

                    self._fail_transition(
                        transition_id
                    )

            tick()

        except Exception:

            self._fail_transition(
                transition_id
            )
            raise

        return handle

    # ========================================================================
    # FADE
    # ========================================================================

    def fade(
        self,
        widget: tk.Misc,
        *,
        fade_in: bool = True,
        config: TransitionConfig | None = None,
        complete: Callable[[], None] | None = None,
    ) -> TransitionHandle:
        """
        Fade a window.

        Works best with Tk/Toplevel windows where
        wm_attributes('-alpha', value) is supported.
        """

        config = config or TransitionConfig(
            transition_type=TransitionType.FADE
        )

        def update(progress: float) -> None:

            alpha = (
                progress
                if fade_in
                else 1.0 - progress
            )

            self._set_alpha(
                widget,
                alpha,
            )

        if fade_in:
            self._set_alpha(
                widget,
                0.0,
            )

        return self.animate(
            widget,
            config=config,
            update=update,
            complete=complete,
        )

    # ========================================================================
    # SLIDE
    # ========================================================================

    def slide(
        self,
        widget: tk.Misc,
        *,
        direction: TransitionType = (
            TransitionType.SLIDE_LEFT
        ),
        config: TransitionConfig | None = None,
        complete: Callable[[], None] | None = None,
    ) -> TransitionHandle:
        """
        Slide a widget using place geometry.

        The widget should already be managed with place().
        """

        if direction not in (
            TransitionType.SLIDE_LEFT,
            TransitionType.SLIDE_RIGHT,
            TransitionType.SLIDE_UP,
            TransitionType.SLIDE_DOWN,
        ):
            raise TransitionConfigurationError(
                "Invalid slide direction."
            )

        config = config or TransitionConfig(
            transition_type=direction
        )

        try:

            self.root.update_idletasks()

            x = widget.winfo_x()
            y = widget.winfo_y()

        except tk.TclError:

            x = 0
            y = 0

        offset = config.offset

        if direction == TransitionType.SLIDE_LEFT:
            start_x = x + offset
            start_y = y

        elif direction == TransitionType.SLIDE_RIGHT:
            start_x = x - offset
            start_y = y

        elif direction == TransitionType.SLIDE_UP:
            start_x = x
            start_y = y + offset

        else:
            start_x = x
            start_y = y - offset

        def start() -> None:

            with contextlib.suppress(tk.TclError):
                widget.place(
                    x=start_x,
                    y=start_y,
                )

        def update(progress: float) -> None:

            current_x = (
                start_x
                + (x - start_x)
                * progress
            )

            current_y = (
                start_y
                + (y - start_y)
                * progress
            )

            with contextlib.suppress(tk.TclError):
                widget.place(
                    x=int(current_x),
                    y=int(current_y),
                )

        return self.animate(
            widget,
            config=config,
            start=start,
            update=update,
            complete=complete,
        )

    # ========================================================================
    # SCALE
    # ========================================================================

    def scale(
        self,
        widget: tk.Misc,
        *,
        config: TransitionConfig | None = None,
        complete: Callable[[], None] | None = None,
    ) -> TransitionHandle:
        """
        Lightweight scale-style transition.

        Tkinter widgets do not support native transform scaling,
        so this changes widget dimensions when possible.
        """

        config = config or TransitionConfig(
            transition_type=TransitionType.SCALE
        )

        try:

            self.root.update_idletasks()

            original_width = widget.winfo_width()
            original_height = widget.winfo_height()

        except tk.TclError:

            original_width = 1
            original_height = 1

        original_width = max(
            1,
            original_width,
        )

        original_height = max(
            1,
            original_height,
        )

        def update(progress: float) -> None:

            scale = 0.92 + (
                0.08 * progress
            )

            width = max(
                1,
                int(
                    original_width
                    * scale
                ),
            )

            height = max(
                1,
                int(
                    original_height
                    * scale
                ),
            )

            with contextlib.suppress(tk.TclError):
                widget.configure(
                    width=width,
                    height=height,
                )

        return self.animate(
            widget,
            config=config,
            update=update,
            complete=complete,
        )

    # ========================================================================
    # CROSS FADE
    # ========================================================================

    def cross_fade(
        self,
        old_widget: tk.Misc | None,
        new_widget: tk.Misc,
        *,
        duration: int = DEFAULT_DURATION,
        complete: Callable[[], None] | None = None,
        destroy_old: bool = False,
    ) -> TransitionHandle:
        """
        Perform a simple cross-fade style page transition.

        Tkinter cannot reliably alpha-blend individual Frames,
        so the transition uses visibility timing and optional
        Toplevel alpha support.
        """

        config = TransitionConfig(
            transition_type=(
                TransitionType.CROSS_FADE
            ),
            duration=duration,
            destroy_old=destroy_old,
        )

        if old_widget is not None:

            try:
                old_widget.pack_forget()
            except tk.TclError:
                with contextlib.suppress(tk.TclError):
                    old_widget.place_forget()

        try:
            new_widget.pack(
                fill="both",
                expand=True,
            )
        except tk.TclError:
            with contextlib.suppress(tk.TclError):
                new_widget.place(
                    relx=0,
                    rely=0,
                    relwidth=1,
                    relheight=1,
                )

        def finish() -> None:

            if (
                destroy_old
                and old_widget is not None
            ):
                with contextlib.suppress(tk.TclError):
                    old_widget.destroy()

            if complete:
                complete()

        return self.animate(
            new_widget,
            config=config,
            update=lambda _progress: None,
            complete=finish,
        )

    # ========================================================================
    # PAGE SWITCH
    # ========================================================================

    def switch_page(
        self,
        old_page: tk.Misc | None,
        new_page: tk.Misc,
        *,
        transition: TransitionType = (
            TransitionType.FADE
        ),
        duration: int = DEFAULT_DURATION,
        complete: Callable[[], None] | None = None,
    ) -> TransitionHandle:
        """
        Generic dashboard page switch.
        """

        if transition == TransitionType.NONE:

            if old_page is not None:
                self._hide_widget(old_page)

            self._show_widget(new_page)

            if complete:
                complete()

            return self._instant_handle()

        if transition == TransitionType.CROSS_FADE:

            return self.cross_fade(
                old_page,
                new_page,
                duration=duration,
                complete=complete,
            )

        if old_page is not None:
            self._hide_widget(old_page)

        self._show_widget(new_page)

        config = TransitionConfig(
            transition_type=transition,
            duration=duration,
        )

        if transition == TransitionType.FADE:

            return self.fade(
                new_page,
                fade_in=True,
                config=config,
                complete=complete,
            )

        if transition in (
            TransitionType.SLIDE_LEFT,
            TransitionType.SLIDE_RIGHT,
            TransitionType.SLIDE_UP,
            TransitionType.SLIDE_DOWN,
        ):

            return self.slide(
                new_page,
                direction=transition,
                config=config,
                complete=complete,
            )

        if transition == TransitionType.SCALE:

            return self.scale(
                new_page,
                config=config,
                complete=complete,
            )

        return self.animate(
            new_page,
            config=config,
            update=lambda _value: None,
            complete=complete,
        )

    # ========================================================================
    # VISIBILITY
    # ========================================================================

    @staticmethod
    def _show_widget(
        widget: tk.Misc,
    ) -> None:

        try:

            if widget.winfo_manager() == "pack":
                widget.pack(
                    fill="both",
                    expand=True,
                )

            elif widget.winfo_manager() == "place":
                widget.place(
                    relx=0,
                    rely=0,
                    relwidth=1,
                    relheight=1,
                )

            elif widget.winfo_manager() == "grid":
                widget.grid()

        except tk.TclError:
            pass

    @staticmethod
    def _hide_widget(
        widget: tk.Misc,
    ) -> None:

        try:
            manager = widget.winfo_manager()

            if manager == "pack":
                widget.pack_forget()

            elif manager == "place":
                widget.place_forget()

            elif manager == "grid":
                widget.grid_remove()

        except tk.TclError:
            pass

    # ========================================================================
    # WINDOW ALPHA
    # ========================================================================

    @staticmethod
    def _set_alpha(
        widget: tk.Misc,
        value: float,
    ) -> None:

        value = max(
            0.0,
            min(
                1.0,
                float(value),
            ),
        )

        with contextlib.suppress(
            tk.TclError,
            AttributeError,
        ):
            widget.wm_attributes(
                "-alpha",
                value,
            )

    # ========================================================================
    # STATE
    # ========================================================================

    def _create_transition(
        self,
        transition_type: TransitionType,
    ) -> int:

        with self._lock:

            transition_id = self._next_id

            self._next_id += 1

            self._states[
                transition_id
            ] = TransitionState.IDLE

            self._stats.started += 1

            self._stats.last_transition = (
                transition_type.value
            )

            return transition_id

    def _start_transition(
        self,
        transition_id: int,
    ) -> None:

        with self._lock:

            if transition_id not in self._states:
                return

            self._states[
                transition_id
            ] = TransitionState.RUNNING

    def _complete_transition(
        self,
        transition_id: int,
    ) -> None:

        with self._lock:

            current = self._states.get(
                transition_id
            )

            if current != TransitionState.RUNNING:
                return

            self._states[
                transition_id
            ] = TransitionState.COMPLETED

            self._stats.completed += 1

            self._cancel_job_locked(
                transition_id
            )

    def _fail_transition(
        self,
        transition_id: int,
    ) -> None:

        with self._lock:

            self._states[
                transition_id
            ] = TransitionState.FAILED

            self._stats.failed += 1

            self._cancel_job_locked(
                transition_id
            )

    def _is_terminal(
        self,
        transition_id: int,
    ) -> bool:

        with self._lock:

            state = self._states.get(
                transition_id
            )

            return state in (
                TransitionState.COMPLETED,
                TransitionState.CANCELLED,
                TransitionState.FAILED,
                None,
            )

    def get_state(
        self,
        transition_id: int,
    ) -> TransitionState:

        with self._lock:

            return self._states.get(
                transition_id,
                TransitionState.CANCELLED,
            )

    # ========================================================================
    # CANCEL
    # ========================================================================

    def cancel(
        self,
        transition_id: int,
    ) -> bool:

        with self._lock:

            state = self._states.get(
                transition_id
            )

            if state != TransitionState.RUNNING:
                return False

            self._states[
                transition_id
            ] = TransitionState.CANCELLED

            self._stats.cancelled += 1

            self._cancel_job_locked(
                transition_id
            )

            return True

    def _cancel_job_locked(
        self,
        transition_id: int,
    ) -> None:

        job = self._jobs.pop(
            transition_id,
            None,
        )

        if job is None:
            return

        with contextlib.suppress(tk.TclError):
            self.root.after_cancel(
                job
            )

    def cancel_all(self) -> int:
        """Cancel every running transition."""

        cancelled = 0

        with self._lock:

            ids = list(
                self._states.keys()
            )

        for transition_id in ids:

            if self.cancel(
                transition_id
            ):
                cancelled += 1

        return cancelled

    # ========================================================================
    # SETTINGS
    # ========================================================================

    def set_enabled(
        self,
        enabled: bool,
    ) -> None:

        with self._lock:
            self._enabled = bool(enabled)

    def set_reduced_motion(
        self,
        enabled: bool,
    ) -> None:

        with self._lock:
            self._reduced_motion = bool(
                enabled
            )

    @property
    def enabled(self) -> bool:

        with self._lock:
            return self._enabled

    @property
    def reduced_motion(self) -> bool:

        with self._lock:
            return self._reduced_motion

    # ========================================================================
    # INSTANT HANDLE
    # ========================================================================

    def _instant_handle(
        self,
    ) -> TransitionHandle:

        transition_id = self._create_transition(
            TransitionType.NONE
        )

        self._start_transition(
            transition_id
        )

        self._complete_transition(
            transition_id
        )

        return TransitionHandle(
            self,
            transition_id,
        )

    # ========================================================================
    # STATS
    # ========================================================================

    def stats(self) -> dict[str, Any]:

        with self._lock:

            return {
                "enabled": self._enabled,
                "reduced_motion": (
                    self._reduced_motion
                ),
                "active": sum(
                    state
                    == TransitionState.RUNNING
                    for state
                    in self._states.values()
                ),
                "started": self._stats.started,
                "completed": (
                    self._stats.completed
                ),
                "cancelled": (
                    self._stats.cancelled
                ),
                "failed": self._stats.failed,
                "average_duration_ms": (
                    self._stats.average_duration_ms
                ),
                "last_transition": (
                    self._stats.last_transition
                ),
            }

    def diagnostics(self) -> dict[str, Any]:

        with self._lock:

            return {
                "shutdown": self._shutdown,
                "enabled": self._enabled,
                "reduced_motion": (
                    self._reduced_motion
                ),
                "transition_count": len(
                    self._states
                ),
                "active_transitions": sum(
                    state
                    == TransitionState.RUNNING
                    for state
                    in self._states.values()
                ),
                "stats": self.stats(),
            }

    # ========================================================================
    # SHUTDOWN
    # ========================================================================

    def shutdown(self) -> None:

        if self._shutdown:
            return

        self.cancel_all()

        with self._lock:
            self._shutdown = True
            self._jobs.clear()


# ============================================================================
# GLOBAL MANAGER
# ============================================================================

transition_manager: TransitionManager | None = None


def initialize_transitions(
    root: tk.Misc,
    *,
    enabled: bool = True,
    reduced_motion: bool = False,
) -> TransitionManager:
    """
    Initialize the global transition manager.
    """

    global transition_manager

    if transition_manager is not None:

        try:
            transition_manager.shutdown()
        except tk.TclError:
            # A destroyed Tk root may prevent pending callbacks from being
            # cancelled; continue by replacing the unusable manager.
            transition_manager = None

    transition_manager = TransitionManager(
        root,
        enabled=enabled,
        reduced_motion=reduced_motion,
    )

    return transition_manager


def get_transition_manager() -> TransitionManager:
    """Return the initialized global manager."""

    if transition_manager is None:
        raise TransitionStateError(
            "Transition manager is not initialized. "
            "Call initialize_transitions(root) first."
        )

    return transition_manager


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def fade_in(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().fade(
        widget,
        fade_in=True,
        config=TransitionConfig(
            transition_type=TransitionType.FADE,
            duration=duration,
        ),
    )


def fade_out(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().fade(
        widget,
        fade_in=False,
        config=TransitionConfig(
            transition_type=TransitionType.FADE,
            duration=duration,
        ),
    )


def slide_left(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().slide(
        widget,
        direction=TransitionType.SLIDE_LEFT,
        config=TransitionConfig(
            transition_type=(
                TransitionType.SLIDE_LEFT
            ),
            duration=duration,
        ),
    )


def slide_right(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().slide(
        widget,
        direction=TransitionType.SLIDE_RIGHT,
        config=TransitionConfig(
            transition_type=(
                TransitionType.SLIDE_RIGHT
            ),
            duration=duration,
        ),
    )


def slide_up(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().slide(
        widget,
        direction=TransitionType.SLIDE_UP,
        config=TransitionConfig(
            transition_type=(
                TransitionType.SLIDE_UP
            ),
            duration=duration,
        ),
    )


def slide_down(
    widget: tk.Misc,
    *,
    duration: int = DEFAULT_DURATION,
) -> TransitionHandle:

    return get_transition_manager().slide(
        widget,
        direction=TransitionType.SLIDE_DOWN,
        config=TransitionConfig(
            transition_type=(
                TransitionType.SLIDE_DOWN
            ),
            duration=duration,
        ),
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "Easing",
    "TransitionConfig",
    "TransitionConfigurationError",
    "TransitionError",
    "TransitionHandle",
    "TransitionManager",
    "TransitionState",
    "TransitionStateError",
    "TransitionStats",
    "TransitionType",
    "apply_easing",
    "ease_in",
    "ease_in_out",
    "ease_linear",
    "ease_out",
    "ease_smooth",
    "fade_in",
    "fade_out",
    "get_transition_manager",
    "initialize_transitions",
    "slide_down",
    "slide_left",
    "slide_right",
    "slide_up",
    "transition_manager",
]
