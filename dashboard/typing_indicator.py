"""
dashboard.typing_indicator
==========================

Professional animated typing indicator for AssistantX.

Features
--------
- Animated 3-dot typing indicator
- Configurable animation speed
- Optional status text
- Start / stop / pause / resume
- Compact mode
- Theme-aware colors
- Thread-safe public controls
- Safe widget lifecycle handling
- Diagnostics and statistics
- Zero external dependencies

Typical usage
-------------

    indicator = TypingIndicator(parent)
    indicator.pack()

    indicator.start()

    # When response is ready:
    indicator.stop()

"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TypingIndicatorError(Exception):
    """Base exception for typing indicator errors."""


class TypingIndicatorConfigurationError(TypingIndicatorError):
    """Raised when typing indicator configuration is invalid."""


class TypingIndicatorStateError(TypingIndicatorError):
    """Raised when an invalid state operation is requested."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TypingIndicatorState(str, Enum):
    """Lifecycle states of the typing indicator."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    DESTROYED = "destroyed"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypingIndicatorConfig:
    """Visual and animation configuration."""

    dot_count: int = 3
    dot_size: int = 7
    dot_spacing: int = 5

    animation_interval: int = 280
    active_duration: int = 180

    text: str = "AssistantX is typing"
    show_text: bool = True

    background: str = "#111827"
    foreground: str = "#9CA3AF"
    active_color: str = "#60A5FA"
    text_color: str = "#9CA3AF"

    font_family: str = "Segoe UI"
    font_size: int = 9

    padding_x: int = 10
    padding_y: int = 7

    compact: bool = False

    def __post_init__(self) -> None:
        if self.dot_count < 1 or self.dot_count > 8:
            raise TypingIndicatorConfigurationError(
                "dot_count must be between 1 and 8."
            )

        if self.dot_size < 2 or self.dot_size > 30:
            raise TypingIndicatorConfigurationError(
                "dot_size must be between 2 and 30."
            )

        if self.dot_spacing < 0 or self.dot_spacing > 50:
            raise TypingIndicatorConfigurationError(
                "dot_spacing must be between 0 and 50."
            )

        if self.animation_interval < 30:
            raise TypingIndicatorConfigurationError(
                "animation_interval must be at least 30ms."
            )

        if self.active_duration < 20:
            raise TypingIndicatorConfigurationError(
                "active_duration must be at least 20ms."
            )

        if self.font_size < 6 or self.font_size > 48:
            raise TypingIndicatorConfigurationError(
                "font_size must be between 6 and 48."
            )


@dataclass(slots=True)
class TypingIndicatorStats:
    """Runtime statistics."""

    starts: int = 0
    stops: int = 0
    pauses: int = 0
    resumes: int = 0
    animation_frames: int = 0
    skipped_frames: int = 0
    last_started_at: float | None = None
    last_stopped_at: float | None = None

    def snapshot(self) -> dict:
        return {
            "starts": self.starts,
            "stops": self.stops,
            "pauses": self.pauses,
            "resumes": self.resumes,
            "animation_frames": self.animation_frames,
            "skipped_frames": self.skipped_frames,
            "last_started_at": self.last_started_at,
            "last_stopped_at": self.last_stopped_at,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"1", "true", "yes", "on"}:
            return True

        if normalized in {"0", "false", "no", "off"}:
            return False

    return default


# ---------------------------------------------------------------------------
# Main Widget
# ---------------------------------------------------------------------------


class TypingIndicator(tk.Frame):
    """
    Animated AssistantX typing indicator.

    The widget itself is intentionally lightweight and does not depend on
    the AI/provider layer. Any chat screen can control it through:

        start()
        stop()
        pause()
        resume()
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        config: TypingIndicatorConfig | None = None,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_frame: Callable[[int], None] | None = None,
        **kwargs,
    ) -> None:
        self._config = config or TypingIndicatorConfig()

        self._validate_callbacks(
            on_start=on_start,
            on_stop=on_stop,
            on_frame=on_frame,
        )

        super().__init__(
            master,
            bg=self._config.background,
            **kwargs,
        )

        self._lock = threading.RLock()

        self._state = TypingIndicatorState.IDLE
        self._after_id: str | None = None
        self._destroyed = False
        self._animation_index = 0

        self._on_start = on_start
        self._on_stop = on_stop
        self._on_frame = on_frame

        self._stats = TypingIndicatorStats()

        self._dot_items: list[tk.Label] = []
        self._text_label: tk.Label | None = None

        self._build_ui()

        self.bind("<Destroy>", self._handle_destroy, add="+")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_callbacks(**callbacks: object) -> None:
        for name, callback in callbacks.items():
            if callback is not None and not callable(callback):
                raise TypingIndicatorConfigurationError(
                    f"{name} must be callable or None."
                )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        cfg = self._config

        self.configure(
            bg=cfg.background,
            bd=0,
            highlightthickness=0,
        )

        container = tk.Frame(
            self,
            bg=cfg.background,
            bd=0,
            highlightthickness=0,
        )

        container.pack(
            padx=cfg.padding_x,
            pady=cfg.padding_y,
        )

        dots_frame = tk.Frame(
            container,
            bg=cfg.background,
            bd=0,
            highlightthickness=0,
        )

        dots_frame.pack(side="left")

        for _index in range(cfg.dot_count):
            dot = tk.Label(
                dots_frame,
                text="●",
                bg=cfg.background,
                fg=cfg.foreground,
                font=(
                    cfg.font_family,
                    max(6, cfg.dot_size),
                    "bold",
                ),
                bd=0,
                padx=max(0, cfg.dot_spacing // 2),
                pady=0,
            )

            dot.pack(
                side="left",
            )

            self._dot_items.append(dot)

        if cfg.show_text and not cfg.compact:
            self._text_label = tk.Label(
                container,
                text=cfg.text,
                bg=cfg.background,
                fg=cfg.text_color,
                font=(
                    cfg.font_family,
                    cfg.font_size,
                ),
                bd=0,
                padx=7,
                pady=0,
            )

            self._text_label.pack(side="left")

        self._render_frame(0)

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def _render_frame(self, active_index: int) -> None:
        if self._destroyed:
            return

        cfg = self._config

        try:
            for index, dot in enumerate(self._dot_items):
                if not dot.winfo_exists():
                    continue

                if index == active_index:
                    dot.configure(
                        fg=cfg.active_color,
                    )
                else:
                    dot.configure(
                        fg=cfg.foreground,
                    )

            self._stats.animation_frames += 1

            callback = self._on_frame

            if callback is not None:
                try:
                    callback(active_index)
                except Exception:
                    # UI callbacks must never break the animation loop.
                    logger.exception("Typing indicator frame callback failed")

        except tk.TclError:
            self._stats.skipped_frames += 1

    def _schedule_next_frame(self) -> None:
        if self._destroyed:
            return

        try:
            self._after_id = self.after(
                self._config.animation_interval,
                self._animate,
            )
        except tk.TclError:
            self._after_id = None

    def _animate(self) -> None:
        with self._lock:
            if self._destroyed:
                return

            if self._state != TypingIndicatorState.RUNNING:
                self._after_id = None
                return

            self._animation_index = (
                self._animation_index + 1
            ) % self._config.dot_count

            self._render_frame(
                self._animation_index
            )

            self._after_id = None

            self._schedule_next_frame()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the typing animation."""

        with self._lock:
            self._ensure_alive()

            if self._state == TypingIndicatorState.RUNNING:
                return False

            if self._state == TypingIndicatorState.PAUSED:
                return self.resume()

            self._cancel_scheduled_callback()

            self._state = TypingIndicatorState.RUNNING
            self._animation_index = 0

            self._stats.starts += 1
            self._stats.last_started_at = time.time()

            self._render_frame(0)
            self._schedule_next_frame()

            callback = self._on_start

        if callback is not None:
            try:
                callback()
            except (RuntimeError, TypeError, ValueError):
                logger.exception("Typing indicator start callback failed")

        return True

    def stop(self) -> bool:
        """Stop the animation and return to idle state."""

        with self._lock:
            self._ensure_alive()

            if self._state in {
                TypingIndicatorState.IDLE,
                TypingIndicatorState.STOPPED,
            }:
                return False

            self._cancel_scheduled_callback()

            self._state = TypingIndicatorState.STOPPED
            self._stats.stops += 1
            self._stats.last_stopped_at = time.time()

            self._render_frame(-1)

            callback = self._on_stop

        if callback is not None:
            try:
                callback()
            except (RuntimeError, TypeError, ValueError):
                logger.exception("Typing indicator stop callback failed")

        return True

    def pause(self) -> bool:
        """Pause the animation without resetting its state."""

        with self._lock:
            self._ensure_alive()

            if self._state != TypingIndicatorState.RUNNING:
                return False

            self._cancel_scheduled_callback()

            self._state = TypingIndicatorState.PAUSED
            self._stats.pauses += 1

            return True

    def resume(self) -> bool:
        """Resume a paused animation."""

        with self._lock:
            self._ensure_alive()

            if self._state != TypingIndicatorState.PAUSED:
                return False

            self._state = TypingIndicatorState.RUNNING
            self._stats.resumes += 1

            self._schedule_next_frame()

            return True

    def restart(self) -> bool:
        """Restart the animation from the first dot."""

        self.stop()
        return self.start()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> TypingIndicatorState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        return self.state == TypingIndicatorState.RUNNING

    @property
    def paused(self) -> bool:
        return self.state == TypingIndicatorState.PAUSED

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def set_text(self, text: str) -> None:
        """Update the indicator text."""

        text = str(text).strip()

        with self._lock:
            self._ensure_alive()

            self._config = TypingIndicatorConfig(
                **{
                    **self._config.__dict__,
                    "text": text,
                }
            )

            if self._text_label is not None:
                with contextlib.suppress(tk.TclError):
                    self._text_label.configure(text=text)

    def get_text(self) -> str:
        return self._config.text

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_speed(self, milliseconds: int) -> None:
        """Change animation interval."""

        milliseconds = _safe_int(milliseconds, 280)

        milliseconds = max(milliseconds, 30)

        with self._lock:
            self._config = TypingIndicatorConfig(
                **{
                    **self._config.__dict__,
                    "animation_interval": milliseconds,
                }
            )

    def set_colors(
        self,
        *,
        foreground: str | None = None,
        active_color: str | None = None,
        text_color: str | None = None,
        background: str | None = None,
    ) -> None:
        """Update visual colors."""

        values = dict(self._config.__dict__)

        if foreground is not None:
            values["foreground"] = foreground

        if active_color is not None:
            values["active_color"] = active_color

        if text_color is not None:
            values["text_color"] = text_color

        if background is not None:
            values["background"] = background

        with self._lock:
            self._config = TypingIndicatorConfig(**values)

            try:
                self.configure(bg=self._config.background)

                for dot in self._dot_items:
                    dot.configure(
                        bg=self._config.background,
                        fg=self._config.foreground,
                    )

                if self._text_label is not None:
                    self._text_label.configure(
                        bg=self._config.background,
                        fg=self._config.text_color,
                    )

            except tk.TclError:
                pass

    def set_visible(self, visible: bool) -> None:
        """Show or hide the widget using pack/grid/place-independent state."""

        if visible:
            with contextlib.suppress(tk.TclError):
                self.tk.call(
                    "wm",
                    "attributes",
                    self.winfo_toplevel(),
                    "-alpha",
                    1.0,
                )
        else:
            # Do not unmanage the widget because the caller may use any
            # geometry manager. Use visual state instead.
            with contextlib.suppress(tk.TclError):
                self.configure(
                    width=1,
                    height=1,
                )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _cancel_scheduled_callback(self) -> None:
        if self._after_id is None:
            return

        try:
            self.after_cancel(self._after_id)
        except (tk.TclError, ValueError):
            pass
        finally:
            self._after_id = None

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _ensure_alive(self) -> None:
        if self._destroyed or self._state == TypingIndicatorState.DESTROYED:
            raise TypingIndicatorStateError(
                "TypingIndicator has already been destroyed."
            )

    def _handle_destroy(self, _event: tk.Event | None = None) -> None:
        with self._lock:
            if self._destroyed:
                return

            self._destroyed = True
            self._cancel_scheduled_callback()
            self._state = TypingIndicatorState.DESTROYED

    def destroy(self) -> None:
        with self._lock:
            if self._destroyed:
                return

            self._destroyed = True
            self._cancel_scheduled_callback()
            self._state = TypingIndicatorState.DESTROYED

        with contextlib.suppress(tk.TclError):
            super().destroy()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            return self._stats.snapshot()

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "component": "TypingIndicator",
                "state": self._state.value,
                "destroyed": self._destroyed,
                "running": self._state == TypingIndicatorState.RUNNING,
                "paused": self._state == TypingIndicatorState.PAUSED,
                "dot_count": self._config.dot_count,
                "dot_size": self._config.dot_size,
                "animation_interval": self._config.animation_interval,
                "text": self._config.text,
                "show_text": self._config.show_text,
                "compact": self._config.compact,
                "scheduled": self._after_id is not None,
                "stats": self._stats.snapshot(),
            }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_typing_indicator(
    parent: tk.Misc,
    *,
    text: str = "AssistantX is typing",
    compact: bool = False,
    **kwargs,
) -> TypingIndicator:
    """
    Create a configured typing indicator.

    Example
    -------
        indicator = create_typing_indicator(
            chat_frame,
            text="Thinking...",
        )
        indicator.pack(anchor="w")
    """

    config = TypingIndicatorConfig(
        text=text,
        compact=compact,
    )

    return TypingIndicator(
        parent,
        config=config,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def start_typing(indicator: TypingIndicator) -> bool:
    """Start an existing typing indicator."""
    return indicator.start()


def stop_typing(indicator: TypingIndicator) -> bool:
    """Stop an existing typing indicator."""
    return indicator.stop()


def is_typing(indicator: TypingIndicator) -> bool:
    """Return True when the indicator is actively animating."""
    return indicator.running


__all__ = [
    "TypingIndicator",
    "TypingIndicatorConfig",
    "TypingIndicatorConfigurationError",
    "TypingIndicatorError",
    "TypingIndicatorState",
    "TypingIndicatorStateError",
    "TypingIndicatorStats",
    "create_typing_indicator",
    "is_typing",
    "start_typing",
    "stop_typing",
]
