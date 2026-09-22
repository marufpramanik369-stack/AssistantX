"""
AssistantX Dashboard - Animation Engine
=======================================

Centralized animation utilities for the AssistantX dashboard.

Responsibilities:
    - Generic value interpolation
    - Easing functions
    - Tkinter-compatible animation scheduling
    - Fade / slide / progress animations
    - Animation lifecycle management

This module contains no business logic.
"""

from __future__ import annotations

import contextlib
import math
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock

# ============================================================================
# Types
# ============================================================================

Number = int | float
AnimationCallback = Callable[[float], None]
CompletionCallback = Callable[[], None]


# ============================================================================
# Exceptions
# ============================================================================

class AnimationError(Exception):
    """Base exception for dashboard animation errors."""


class AnimationConfigurationError(AnimationError):
    """Raised when animation configuration is invalid."""


class AnimationStateError(AnimationError):
    """Raised when an animation is used in an invalid state."""


# ============================================================================
# Easing
# ============================================================================

class Easing(str, Enum):
    """Supported easing functions."""

    LINEAR = "linear"

    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"

    QUAD_IN = "quad_in"
    QUAD_OUT = "quad_out"
    QUAD_IN_OUT = "quad_in_out"

    CUBIC_IN = "cubic_in"
    CUBIC_OUT = "cubic_out"
    CUBIC_IN_OUT = "cubic_in_out"

    SMOOTH = "smooth"
    SPRING = "spring"


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a numeric value."""

    return max(minimum, min(maximum, value))


def ease_linear(t: float) -> float:
    return _clamp(t)


def ease_in(t: float) -> float:
    t = _clamp(t)
    return t * t


def ease_out(t: float) -> float:
    t = _clamp(t)
    return 1.0 - ((1.0 - t) ** 2)


def ease_in_out(t: float) -> float:
    t = _clamp(t)

    if t < 0.5:
        return 2.0 * t * t

    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def quad_in(t: float) -> float:
    return _clamp(t) ** 2


def quad_out(t: float) -> float:
    t = _clamp(t)
    return 1.0 - (1.0 - t) ** 2


def quad_in_out(t: float) -> float:
    t = _clamp(t)

    if t < 0.5:
        return 2.0 * t * t

    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def cubic_in(t: float) -> float:
    return _clamp(t) ** 3


def cubic_out(t: float) -> float:
    t = _clamp(t)

    return 1.0 - (1.0 - t) ** 3


def cubic_in_out(t: float) -> float:
    t = _clamp(t)

    if t < 0.5:
        return 4.0 * t ** 3

    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def smooth_step(t: float) -> float:
    """Smooth Hermite interpolation."""

    t = _clamp(t)

    return t * t * (3.0 - 2.0 * t)


def spring(t: float) -> float:
    """
    Lightweight spring-style easing.

    Produces a subtle overshoot without requiring
    external animation libraries.
    """

    t = _clamp(t)

    if t <= 0.0:
        return 0.0

    if t >= 1.0:
        return 1.0

    return (
        1.0
        - math.exp(-8.0 * t)
        * math.cos(12.0 * t)
    )


def apply_easing(
    progress: float,
    easing: Easing | str = Easing.SMOOTH,
) -> float:
    """Apply an easing function to normalized progress."""

    if isinstance(easing, str):
        try:
            easing = Easing(easing.lower())
        except ValueError:
            easing = Easing.SMOOTH

    functions = {
        Easing.LINEAR: ease_linear,
        Easing.EASE_IN: ease_in,
        Easing.EASE_OUT: ease_out,
        Easing.EASE_IN_OUT: ease_in_out,
        Easing.QUAD_IN: quad_in,
        Easing.QUAD_OUT: quad_out,
        Easing.QUAD_IN_OUT: quad_in_out,
        Easing.CUBIC_IN: cubic_in,
        Easing.CUBIC_OUT: cubic_out,
        Easing.CUBIC_IN_OUT: cubic_in_out,
        Easing.SMOOTH: smooth_step,
        Easing.SPRING: spring,
    }

    return functions[easing](_clamp(progress))


# ============================================================================
# Animation Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class AnimationConfig:
    """Configuration for a single animation."""

    duration: int = 250
    fps: int = 60

    easing: Easing = Easing.SMOOTH

    enabled: bool = True

    delay: int = 0

    def __post_init__(self) -> None:
        if self.duration < 0:
            raise AnimationConfigurationError(
                "Animation duration cannot be negative."
            )

        if self.fps <= 0:
            raise AnimationConfigurationError(
                "Animation FPS must be greater than zero."
            )

        if self.delay < 0:
            raise AnimationConfigurationError(
                "Animation delay cannot be negative."
            )


# ============================================================================
# Animation State
# ============================================================================

class AnimationState(str, Enum):
    """Lifecycle state of an animation."""

    IDLE = "idle"
    DELAYED = "delayed"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class AnimationStats:
    """Runtime animation statistics."""

    started: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0


# ============================================================================
# Animation Handle
# ============================================================================

class AnimationHandle:
    """
    Controls a running animation.

    The handle can be used to:
        - cancel
        - pause
        - resume
        - inspect state
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = AnimationState.IDLE
        self._after_id: str | None = None

    @property
    def state(self) -> AnimationState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        return self.state == AnimationState.RUNNING

    @property
    def completed(self) -> bool:
        return self.state == AnimationState.COMPLETED

    @property
    def cancelled(self) -> bool:
        return self.state == AnimationState.CANCELLED

    def cancel(self) -> None:
        """Cancel the animation."""

        with self._lock:
            if self._state in (
                AnimationState.COMPLETED,
                AnimationState.CANCELLED,
            ):
                return

            self._state = AnimationState.CANCELLED

    def pause(self) -> None:
        """Pause a running animation."""

        with self._lock:
            if self._state == AnimationState.RUNNING:
                self._state = AnimationState.PAUSED

    def resume(self) -> None:
        """Resume a paused animation."""

        with self._lock:
            if self._state == AnimationState.PAUSED:
                self._state = AnimationState.RUNNING

    def _set_state(self, state: AnimationState) -> None:
        with self._lock:
            self._state = state

    def _set_after_id(self, after_id: str | None) -> None:
        with self._lock:
            self._after_id = after_id

    def _get_after_id(self) -> str | None:
        with self._lock:
            return self._after_id


# ============================================================================
# Animation Engine
# ============================================================================

class AnimationEngine:
    """
    Tkinter animation engine.

    All UI callbacks execute through Tkinter's main thread using
    `after()`. No background UI thread is created.
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        enabled: bool = True,
        target_fps: int = 60,
    ) -> None:

        if root is None:
            raise AnimationConfigurationError(
                "AnimationEngine requires a Tkinter root."
            )

        if target_fps <= 0:
            raise AnimationConfigurationError(
                "target_fps must be greater than zero."
            )

        self._root = root
        self._enabled = enabled
        self._target_fps = target_fps

        self._lock = RLock()
        self._animations: set[AnimationHandle] = set()

        self._stats = AnimationStats()

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def target_fps(self) -> int:
        return self._target_fps

    # ------------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable animations."""

        with self._lock:
            self._enabled = bool(enabled)

    # ------------------------------------------------------------------------
    # Core Animation
    # ------------------------------------------------------------------------

    def animate(
        self,
        callback: AnimationCallback,
        *,
        config: AnimationConfig | None = None,
        on_complete: CompletionCallback | None = None,
    ) -> AnimationHandle:
        """
        Run a normalized animation from 0.0 to 1.0.

        callback(progress) receives eased progress.
        """

        if not callable(callback):
            raise AnimationConfigurationError(
                "Animation callback must be callable."
            )

        config = config or AnimationConfig(
            fps=self._target_fps,
            enabled=self._enabled,
        )

        handle = AnimationHandle()

        with self._lock:
            self._animations.add(handle)
            self._stats.started += 1

        if not self._enabled or not config.enabled:
            try:
                callback(1.0)

                handle._set_state(AnimationState.COMPLETED)

                with self._lock:
                    self._stats.completed += 1

                if on_complete:
                    on_complete()

            except (TypeError, ValueError, RuntimeError):
                handle._set_state(AnimationState.CANCELLED)

                with self._lock:
                    self._stats.failed += 1

            finally:
                self._remove_handle(handle)

            return handle

        if config.delay > 0:
            handle._set_state(AnimationState.DELAYED)

            self._schedule(
                lambda: self._start_animation(
                    handle,
                    callback,
                    config,
                    on_complete,
                ),
                config.delay,
                handle,
            )
        else:
            self._start_animation(
                handle,
                callback,
                config,
                on_complete,
            )

        return handle

    def _start_animation(
        self,
        handle: AnimationHandle,
        callback: AnimationCallback,
        config: AnimationConfig,
        on_complete: CompletionCallback | None,
    ) -> None:

        if handle.cancelled:
            self._finish_cancelled(handle)
            return

        handle._set_state(AnimationState.RUNNING)

        start_time = time.perf_counter()

        interval = max(
            1,
            int(1000 / config.fps),
        )

        def tick() -> None:
            if handle.cancelled:
                self._finish_cancelled(handle)
                return

            if handle.state == AnimationState.PAUSED:
                self._schedule(tick, interval, handle)
                return

            elapsed = time.perf_counter() - start_time

            if config.duration <= 0:
                raw_progress = 1.0
            else:
                raw_progress = min(
                    1.0,
                    elapsed / (config.duration / 1000.0),
                )

            progress = apply_easing(
                raw_progress,
                config.easing,
            )

            try:
                callback(progress)
            except (RuntimeError, ValueError, TypeError):
                handle._set_state(AnimationState.CANCELLED)

                with self._lock:
                    self._stats.failed += 1

                self._remove_handle(handle)
                return

            if raw_progress >= 1.0:
                handle._set_state(AnimationState.COMPLETED)

                with self._lock:
                    self._stats.completed += 1

                self._remove_handle(handle)

                if on_complete:
                    try:
                        on_complete()
                    except (RuntimeError, ValueError, TypeError):
                        with self._lock:
                            self._stats.failed += 1

                return

            self._schedule(tick, interval, handle)

        tick()

    # ------------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------------

    def _schedule(
        self,
        callback: Callable[[], None],
        delay: int,
        handle: AnimationHandle,
    ) -> None:

        if handle.cancelled:
            return

        try:
            after_id = self._root.after(
                max(1, int(delay)),
                callback,
            )

            handle._set_after_id(after_id)

        except tk.TclError:
            handle._set_state(AnimationState.CANCELLED)

            with self._lock:
                self._stats.cancelled += 1

            self._remove_handle(handle)

    # ------------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------------

    def cancel(self, handle: AnimationHandle) -> None:
        """Cancel an animation handle."""

        if handle is None:
            return

        handle.cancel()

        after_id = handle._get_after_id()

        if after_id:
            with contextlib.suppress(tk.TclError):
                self._root.after_cancel(after_id)

        self._finish_cancelled(handle)

    def cancel_all(self) -> None:
        """Cancel every active animation."""

        with self._lock:
            handles = list(self._animations)

        for handle in handles:
            self.cancel(handle)

    def _finish_cancelled(
        self,
        handle: AnimationHandle,
    ) -> None:

        with self._lock:
            self._stats.cancelled += 1

        self._remove_handle(handle)

    def _remove_handle(
        self,
        handle: AnimationHandle,
    ) -> None:

        with self._lock:
            self._animations.discard(handle)

    # ------------------------------------------------------------------------
    # Utility Animations
    # ------------------------------------------------------------------------

    def animate_value(
        self,
        start: Number,
        end: Number,
        callback: Callable[[Number], None],
        *,
        config: AnimationConfig | None = None,
        on_complete: CompletionCallback | None = None,
    ) -> AnimationHandle:
        """Animate a numeric value."""

        if not callable(callback):
            raise AnimationConfigurationError(
                "callback must be callable."
            )

        delta = end - start

        def update(progress: float) -> None:
            value = start + (delta * progress)
            callback(value)

        return self.animate(
            update,
            config=config,
            on_complete=on_complete,
        )

    def fade(
        self,
        _widget: tk.Misc,
        start: float,
        end: float,
        *,
        callback: Callable[[float], None] | None = None,
        duration: int = 250,
        easing: Easing = Easing.SMOOTH,
    ) -> AnimationHandle:
        """
        Generic fade helper.

        The caller controls how opacity is applied because Tkinter
        widgets differ in how transparency is supported.
        """

        def update(value: Number) -> None:
            opacity = float(value)

            if callback:
                callback(opacity)

        return self.animate_value(
            start,
            end,
            update,
            config=AnimationConfig(
                duration=duration,
                fps=self._target_fps,
                easing=easing,
                enabled=self._enabled,
            ),
        )

    # ------------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------------

    def stats(self) -> dict[str, int | bool]:
        """Return animation statistics."""

        with self._lock:
            return {
                "enabled": self._enabled,
                "target_fps": self._target_fps,
                "active": len(self._animations),
                "started": self._stats.started,
                "completed": self._stats.completed,
                "cancelled": self._stats.cancelled,
                "failed": self._stats.failed,
            }

    def shutdown(self) -> None:
        """Cancel all animations and release references."""

        self.cancel_all()

        with self._lock:
            self._animations.clear()


# ============================================================================
# Convenience Functions
# ============================================================================

def interpolate(
    start: Number,
    end: Number,
    progress: float,
    easing: Easing | str = Easing.SMOOTH,
) -> Number:
    """Interpolate between two numeric values."""

    eased = apply_easing(progress, easing)

    return start + ((end - start) * eased)


def lerp(
    start: Number,
    end: Number,
    progress: float,
) -> Number:
    """Linear interpolation."""

    return start + ((end - start) * _clamp(progress))


def percentage(
    progress: float,
) -> int:
    """Convert normalized progress to percentage."""

    return round(_clamp(progress) * 100)


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "AnimationCallback",
    # Configuration / State
    "AnimationConfig",
    "AnimationConfigurationError",
    # Engine
    "AnimationEngine",
    # Exceptions
    "AnimationError",
    "AnimationHandle",
    "AnimationState",
    "AnimationStateError",
    "AnimationStats",
    "CompletionCallback",
    # Easing
    "Easing",
    # Types
    "Number",
    "apply_easing",
    "cubic_in",
    "cubic_in_out",
    "cubic_out",
    "ease_in",
    "ease_in_out",
    "ease_linear",
    "ease_out",
    # Helpers
    "interpolate",
    "lerp",
    "percentage",
    "quad_in",
    "quad_in_out",
    "quad_out",
    "smooth_step",
    "spring",
]
