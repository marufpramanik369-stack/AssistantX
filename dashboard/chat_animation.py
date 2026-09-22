"""
AssistantX Dashboard - Chat Animation
=====================================

Professional animation helpers for the AssistantX chat interface.

Responsibilities
----------------
    • Message entrance animations
    • Message exit animations
    • Streaming text animation
    • Typing / cursor effects
    • Message highlight animation
    • Pulse animations
    • Smooth chat scrolling
    • Animation cancellation
    • Reduced-motion support

This module contains presentation logic only.
It does not contain AI, chat history, or business logic.
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

from dashboard.animations import (
    AnimationConfig,
    AnimationEngine,
    AnimationHandle,
    Easing,
    apply_easing,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_MESSAGE_DURATION = 220
DEFAULT_STREAM_INTERVAL = 25
DEFAULT_TYPING_INTERVAL = 450
DEFAULT_SCROLL_DURATION = 260

MIN_STREAM_INTERVAL = 5
MAX_STREAM_INTERVAL = 500

MIN_TYPING_INTERVAL = 100
MAX_TYPING_INTERVAL = 2000


# ============================================================================
# Exceptions
# ============================================================================

class ChatAnimationError(Exception):
    """Base exception for chat animation errors."""


class ChatAnimationConfigurationError(ChatAnimationError):
    """Raised when animation configuration is invalid."""


# ============================================================================
# Animation Types
# ============================================================================

class ChatAnimationType(str, Enum):
    """Supported chat animation types."""

    MESSAGE_ENTER = "message_enter"
    MESSAGE_EXIT = "message_exit"

    STREAM = "stream"
    TYPING = "typing"

    HIGHLIGHT = "highlight"
    PULSE = "pulse"

    SCROLL = "scroll"


# ============================================================================
# Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class ChatAnimationConfig:
    """Global chat animation configuration."""

    enabled: bool = True

    message_duration: int = DEFAULT_MESSAGE_DURATION

    stream_interval: int = DEFAULT_STREAM_INTERVAL

    typing_interval: int = DEFAULT_TYPING_INTERVAL

    scroll_duration: int = DEFAULT_SCROLL_DURATION

    typing_dots: int = 3

    cursor_character: str = "▌"

    enable_message_animation: bool = True

    enable_stream_animation: bool = True

    enable_typing_animation: bool = True

    enable_scroll_animation: bool = True

    reduced_motion: bool = False

    def __post_init__(self) -> None:

        if self.message_duration < 0:
            raise ChatAnimationConfigurationError(
                "message_duration cannot be negative."
            )

        if not (
            MIN_STREAM_INTERVAL
            <= self.stream_interval
            <= MAX_STREAM_INTERVAL
        ):
            raise ChatAnimationConfigurationError(
                "stream_interval is outside the supported range."
            )

        if not (
            MIN_TYPING_INTERVAL
            <= self.typing_interval
            <= MAX_TYPING_INTERVAL
        ):
            raise ChatAnimationConfigurationError(
                "typing_interval is outside the supported range."
            )

        if self.scroll_duration < 0:
            raise ChatAnimationConfigurationError(
                "scroll_duration cannot be negative."
            )

        if not 1 <= self.typing_dots <= 6:
            raise ChatAnimationConfigurationError(
                "typing_dots must be between 1 and 6."
            )

        if not self.cursor_character:
            raise ChatAnimationConfigurationError(
                "cursor_character cannot be empty."
            )


# ============================================================================
# Runtime Statistics
# ============================================================================

@dataclass(slots=True)
class ChatAnimationStats:
    """Runtime statistics."""

    message_animations: int = 0
    stream_animations: int = 0
    typing_animations: int = 0
    highlight_animations: int = 0
    pulse_animations: int = 0
    scroll_animations: int = 0

    completed: int = 0
    cancelled: int = 0
    failed: int = 0


# ============================================================================
# Streaming Controller
# ============================================================================

class StreamController:
    """
    Controls character-by-character chat streaming.

    The controller is Tkinter-main-thread safe because all callbacks
    are scheduled through `after()`.
    """

    def __init__(
        self,
        widget: tk.Misc,
        text: str,
        *,
        interval: int = DEFAULT_STREAM_INTERVAL,
        callback: Callable[[str], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:

        if widget is None:
            raise ChatAnimationConfigurationError(
                "widget is required."
            )

        interval = max(interval, MIN_STREAM_INTERVAL)

        interval = min(interval, MAX_STREAM_INTERVAL)

        self._widget = widget
        self._text = str(text)

        self._interval = interval

        self._callback = callback
        self._on_complete = on_complete

        self._index = 0
        self._after_id: str | None = None

        self._running = False
        self._paused = False

        self._lock = RLock()

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def completed(self) -> bool:
        with self._lock:
            return (
                not self._running
                and self._index >= len(self._text)
            )

    @property
    def progress(self) -> float:
        with self._lock:

            if not self._text:
                return 1.0

            return min(
                1.0,
                self._index / len(self._text),
            )

    # ------------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------------

    def start(self) -> None:
        """Start streaming."""

        with self._lock:

            if self._running:
                return

            self._running = True
            self._paused = False

        self._tick()

    def pause(self) -> None:
        """Pause streaming."""

        with self._lock:
            self._paused = True

    def resume(self) -> None:
        """Resume streaming."""

        with self._lock:
            self._paused = False

        if self.running:
            self._tick()

    def cancel(self) -> None:
        """Cancel streaming."""

        with self._lock:

            self._running = False
            self._paused = False

            after_id = self._after_id
            self._after_id = None

        if after_id:

            with contextlib.suppress(tk.TclError):
                self._widget.after_cancel(after_id)

    # ------------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------------

    def _tick(self) -> None:

        with self._lock:

            if not self._running:
                return

            if self._paused:
                return

            if self._index >= len(self._text):

                self._running = False

                callback = self._on_complete

                self._after_id = None

            else:

                self._index += 1

                current_text = self._text[:self._index]

                callback = self._callback

        if callback:

            try:

                if self._index <= len(self._text):
                    callback(current_text)

            except Exception:
                logger.exception(
                    "Chat stream callback failed."
                )

                self.cancel()
                return

        if self.completed:

            if self._on_complete:

                try:
                    self._on_complete()
                except Exception:
                    logger.exception(
                        "Stream completion callback failed."
                    )

            return

        try:

            after_id = self._widget.after(
                self._interval,
                self._tick,
            )

            with self._lock:
                self._after_id = after_id

        except tk.TclError:

            self.cancel()


# ============================================================================
# Chat Animation Manager
# ============================================================================

class ChatAnimationManager:
    """
    High-level animation manager for chat UI.

    A single instance can be shared by the entire chat interface.
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        engine: AnimationEngine | None = None,
        config: ChatAnimationConfig | None = None,
    ) -> None:

        if root is None:
            raise ChatAnimationConfigurationError(
                "root is required."
            )

        self._root = root

        self._config = config or ChatAnimationConfig()

        self._engine = engine or AnimationEngine(
            root,
            enabled=self._config.enabled,
        )

        self._lock = RLock()

        self._handles: set[AnimationHandle] = set()

        self._streams: set[StreamController] = set()

        self._stats = ChatAnimationStats()

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def config(self) -> ChatAnimationConfig:
        return self._config

    @property
    def engine(self) -> AnimationEngine:
        return self._engine

    # ========================================================================
    # Message Enter
    # ========================================================================

    def message_enter(
        self,
        widget: tk.Misc,
        *,
        duration: int | None = None,
        on_progress: Callable[[float], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> AnimationHandle:
        """
        Animate a new chat message.

        The progress value goes from 0.0 to 1.0.

        UI code decides how to translate progress into movement,
        opacity, scaling, or other effects.
        """

        if widget is None:
            raise ChatAnimationConfigurationError(
                "widget is required."
            )

        if not self._animations_allowed(
            self._config.enable_message_animation
        ):
            if on_progress:
                on_progress(1.0)

            if on_complete:
                on_complete()

            return self._completed_handle()

        self._stats.message_animations += 1

        return self._create_animation(
            duration=(
                duration
                if duration is not None
                else self._config.message_duration
            ),
            easing=Easing.EASE_OUT,
            callback=on_progress,
            on_complete=on_complete,
        )

    # ========================================================================
    # Message Exit
    # ========================================================================

    def message_exit(
        self,
        widget: tk.Misc,
        *,
        duration: int = 160,
        on_progress: Callable[[float], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> AnimationHandle:
        """Animate a chat message leaving the UI."""

        if widget is None:
            raise ChatAnimationConfigurationError(
                "widget is required."
            )

        self._stats.message_animations += 1

        return self._create_animation(
            duration=duration,
            easing=Easing.EASE_IN,
            callback=on_progress,
            on_complete=on_complete,
        )

    # ========================================================================
    # Streaming
    # ========================================================================

    def stream_text(
        self,
        widget: tk.Misc,
        text: str,
        *,
        interval: int | None = None,
        callback: Callable[[str], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> StreamController:
        """
        Stream text progressively into a chat message.
        """

        if widget is None:
            raise ChatAnimationConfigurationError(
                "widget is required."
            )

        text = str(text)

        controller = StreamController(
            widget,
            text,
            interval=(
                interval
                if interval is not None
                else self._config.stream_interval
            ),
            callback=callback,
            on_complete=on_complete,
        )

        if not self._animations_allowed(
            self._config.enable_stream_animation
        ):
            if callback:
                callback(text)

            if on_complete:
                on_complete()

            return controller

        with self._lock:
            self._streams.add(controller)
            self._stats.stream_animations += 1

        def cleanup() -> None:

            with self._lock:
                self._streams.discard(controller)
                self._stats.completed += 1

            if on_complete:
                try:
                    on_complete()
                except Exception:
                    logger.exception(
                        "Stream completion callback failed."
                    )

        # Replace completion callback with managed cleanup.
        controller._on_complete = cleanup

        controller.start()

        return controller

    # ========================================================================
    # Typing Indicator
    # ========================================================================

    def typing_indicator(
        self,
        widget: tk.Misc,
        *,
        callback: Callable[[str], None],
        interval: int | None = None,
        dots: int | None = None,
    ) -> AnimationHandle:
        """
        Animate a typing indicator.

        Example output:

            ""
            "."
            ".."
            "..."
        """

        if widget is None:
            raise ChatAnimationConfigurationError(
                "widget is required."
            )

        if not callable(callback):
            raise ChatAnimationConfigurationError(
                "callback must be callable."
            )

        if not self._animations_allowed(
            self._config.enable_typing_animation
        ):
            callback("." * (dots or self._config.typing_dots))
            return self._completed_handle()

        self._stats.typing_animations += 1

        max_dots = dots or self._config.typing_dots

        max_dots = max(
            1,
            min(6, max_dots),
        )

        delay = (
            interval
            if interval is not None
            else self._config.typing_interval
        )

        handle = AnimationHandle()

        with self._lock:
            self._handles.add(handle)

        handle._set_state(
            __import__(
                "dashboard.animations",
                fromlist=["AnimationState"],
            ).AnimationState.RUNNING
        )

        counter = 0

        def tick() -> None:

            nonlocal counter

            if handle.cancelled:
                self._cleanup_handle(handle)
                return

            if handle.state.name == "PAUSED":

                try:
                    after_id = self._root.after(
                        delay,
                        tick,
                    )

                    handle._set_after_id(after_id)

                except tk.TclError:
                    handle.cancel()

                return

            counter = (counter % max_dots) + 1

            try:
                callback("." * counter)

            except Exception:

                logger.exception(
                    "Typing indicator callback failed."
                )

                handle.cancel()
                self._cleanup_handle(handle)
                return

            try:

                after_id = self._root.after(
                    delay,
                    tick,
                )

                handle._set_after_id(after_id)

            except tk.TclError:

                handle.cancel()
                self._cleanup_handle(handle)

        tick()

        return handle

    # ========================================================================
    # Pulse
    # ========================================================================

    def pulse(
        self,
        *,
        callback: Callable[[float], None],
        duration: int = 700,
        cycles: int = 1,
    ) -> AnimationHandle:
        """
        Create a smooth pulse animation.

        callback receives values approximately between 0.0 and 1.0.
        """

        if not callable(callback):
            raise ChatAnimationConfigurationError(
                "callback must be callable."
            )

        if cycles <= 0:
            cycles = 1

        self._stats.pulse_animations += 1

        total_duration = max(
            1,
            duration,
        ) * cycles

        def update(progress: float) -> None:

            pulse = (
                0.5
                - 0.5
                * __import__("math").cos(
                    progress * cycles * 2 * __import__("math").pi
                )
            )

            callback(pulse)

        return self._create_animation(
            duration=total_duration,
            easing=Easing.LINEAR,
            callback=update,
        )

    # ========================================================================
    # Highlight
    # ========================================================================

    def highlight(
        self,
        *,
        callback: Callable[[float], None],
        duration: int = 500,
    ) -> AnimationHandle:
        """
        Animate a temporary message highlight.

        callback receives normalized highlight intensity.
        """

        if not callable(callback):
            raise ChatAnimationConfigurationError(
                "callback must be callable."
            )

        self._stats.highlight_animations += 1

        def update(progress: float) -> None:

            # Fade in then fade out.
            intensity = (
                progress * 2.0
                if progress < 0.5
                else (1.0 - progress) * 2.0
            )

            callback(
                apply_easing(
                    intensity,
                    Easing.SMOOTH,
                )
            )

        return self._create_animation(
            duration=duration,
            easing=Easing.LINEAR,
            callback=update,
        )

    # ========================================================================
    # Smooth Scroll
    # ========================================================================

    def smooth_scroll(
        self,
        *,
        start: float,
        end: float,
        duration: int | None = None,
        callback: Callable[[float], None] | None = None,
    ) -> AnimationHandle:
        """
        Smoothly animate a scroll position.

        The callback receives the interpolated position.
        """

        if not self._animations_allowed(
            self._config.enable_scroll_animation
        ):

            if callback:
                callback(end)

            return self._completed_handle()

        self._stats.scroll_animations += 1

        delta = end - start

        def update(progress: float) -> None:

            position = start + delta * progress

            if callback:
                callback(position)

        return self._create_animation(
            duration=(
                duration
                if duration is not None
                else self._config.scroll_duration
            ),
            easing=Easing.EASE_OUT,
            callback=update,
        )

    # ========================================================================
    # Generic Animation
    # ========================================================================

    def _create_animation(
        self,
        *,
        duration: int,
        easing: Easing,
        callback: Callable[[float], None] | None,
        on_complete: Callable[[], None] | None = None,
    ) -> AnimationHandle:

        if callback is None:
            def callback(_progress: float) -> None:
                return None

        try:

            handle = self._engine.animate(
                callback,
                config=AnimationConfig(
                    duration=max(0, duration),
                    easing=easing,
                    enabled=self._config.enabled,
                ),
                on_complete=on_complete,
            )

        except Exception:

            self._stats.failed += 1
            raise

        with self._lock:
            self._handles.add(handle)

        return handle

    # ========================================================================
    # Helpers
    # ========================================================================

    def _animations_allowed(self, component_enabled: bool) -> bool:
        return (
            self._config.enabled
            and component_enabled
            and not self._config.reduced_motion
        )

    @staticmethod
    def _completed_handle() -> AnimationHandle:

        from dashboard.animations import AnimationState

        handle = AnimationHandle()

        handle._set_state(
            AnimationState.COMPLETED
        )

        return handle

    def _cleanup_handle(
        self,
        handle: AnimationHandle,
    ) -> None:

        with self._lock:
            self._handles.discard(handle)

    # ========================================================================
    # Cancellation
    # ========================================================================

    def cancel(
        self,
        handle: AnimationHandle | None,
    ) -> None:
        """Cancel a specific animation."""

        if handle is None:
            return

        self._engine.cancel(handle)
        self._cleanup_handle(handle)

        self._stats.cancelled += 1

    def cancel_stream(
        self,
        controller: StreamController | None,
    ) -> None:
        """Cancel a text stream."""

        if controller is None:
            return

        controller.cancel()

        with self._lock:
            self._streams.discard(controller)

        self._stats.cancelled += 1

    def cancel_all(self) -> None:
        """Cancel all active chat animations."""

        with self._lock:

            handles = list(self._handles)
            streams = list(self._streams)

        for handle in handles:
            self.cancel(handle)

        for stream in streams:
            self.cancel_stream(stream)

    # ========================================================================
    # Configuration
    # ========================================================================

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable chat animations."""

        self._config = ChatAnimationConfig(
            enabled=bool(enabled),

            message_duration=self._config.message_duration,
            stream_interval=self._config.stream_interval,
            typing_interval=self._config.typing_interval,
            scroll_duration=self._config.scroll_duration,

            typing_dots=self._config.typing_dots,
            cursor_character=self._config.cursor_character,

            enable_message_animation=(
                self._config.enable_message_animation
            ),

            enable_stream_animation=(
                self._config.enable_stream_animation
            ),

            enable_typing_animation=(
                self._config.enable_typing_animation
            ),

            enable_scroll_animation=(
                self._config.enable_scroll_animation
            ),

            reduced_motion=self._config.reduced_motion,
        )

        self._engine.set_enabled(enabled)

    def set_reduced_motion(
        self,
        enabled: bool,
    ) -> None:
        """Enable reduced-motion mode."""

        self._config = ChatAnimationConfig(
            enabled=self._config.enabled,

            message_duration=self._config.message_duration,
            stream_interval=self._config.stream_interval,
            typing_interval=self._config.typing_interval,
            scroll_duration=self._config.scroll_duration,

            typing_dots=self._config.typing_dots,
            cursor_character=self._config.cursor_character,

            enable_message_animation=(
                self._config.enable_message_animation
            ),

            enable_stream_animation=(
                self._config.enable_stream_animation
            ),

            enable_typing_animation=(
                self._config.enable_typing_animation
            ),

            enable_scroll_animation=(
                self._config.enable_scroll_animation
            ),

            reduced_motion=bool(enabled),
        )

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def stats(self) -> dict[str, Any]:
        """Return safe runtime diagnostics."""

        with self._lock:

            return {
                "enabled": self._config.enabled,
                "reduced_motion": self._config.reduced_motion,

                "active_animations": len(
                    self._handles
                ),

                "active_streams": len(
                    self._streams
                ),

                "message_animations":
                    self._stats.message_animations,

                "stream_animations":
                    self._stats.stream_animations,

                "typing_animations":
                    self._stats.typing_animations,

                "highlight_animations":
                    self._stats.highlight_animations,

                "pulse_animations":
                    self._stats.pulse_animations,

                "scroll_animations":
                    self._stats.scroll_animations,

                "completed":
                    self._stats.completed,

                "cancelled":
                    self._stats.cancelled,

                "failed":
                    self._stats.failed,
            }

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(self) -> None:
        """Stop all chat animations and release resources."""

        self.cancel_all()

        self._engine.shutdown()

        with self._lock:
            self._handles.clear()
            self._streams.clear()


# ============================================================================
# Factory
# ============================================================================

def create_chat_animation_manager(
    root: tk.Misc,
    *,
    config: ChatAnimationConfig | None = None,
) -> ChatAnimationManager:
    """Create a configured chat animation manager."""

    return ChatAnimationManager(
        root,
        config=config,
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Configuration
    "ChatAnimationConfig",
    "ChatAnimationConfigurationError",
    # Exceptions
    "ChatAnimationError",
    # Manager
    "ChatAnimationManager",
    # Statistics
    "ChatAnimationStats",
    # Enums
    "ChatAnimationType",
    # Streaming
    "StreamController",
    # Factory
    "create_chat_animation_manager",
]
