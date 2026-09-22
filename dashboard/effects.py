"""
AssistantX Dashboard - Visual Effects
=====================================

Reusable visual-effect utilities for AssistantX dashboard widgets.

Responsibilities
----------------
    • Hover effects
    • Focus-ring effects
    • Glow-like border effects
    • Emphasis / pulse hooks
    • Fade-in / fade-out helpers
    • Disabled / active states
    • Safe widget styling
    • Animation-engine integration

Design goals
------------
    • Dependency-light
    • Tkinter-compatible
    • Reusable across dashboard widgets
    • Theme-friendly
    • Safe failure behavior
    • No business logic
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
)

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================

class EffectError(Exception):
    """Base exception for dashboard visual effects."""


class EffectConfigurationError(EffectError):
    """Raised when effect configuration is invalid."""


class EffectStateError(EffectError):
    """Raised when an effect is used in an invalid state."""


# ============================================================================
# Enums
# ============================================================================

class EffectState(str, Enum):
    """Generic effect state."""

    NORMAL = "normal"
    HOVER = "hover"
    ACTIVE = "active"
    FOCUSED = "focused"
    DISABLED = "disabled"


class EffectType(str, Enum):
    """Supported visual effect types."""

    HOVER = "hover"
    FOCUS = "focus"
    GLOW = "glow"
    FADE = "fade"
    PULSE = "pulse"
    EMPHASIS = "emphasis"
    DISABLED = "disabled"


# ============================================================================
# Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class EffectConfig:
    """Global visual-effects configuration."""

    enabled: bool = True
    reduced_motion: bool = False

    hover_duration: int = 120
    focus_duration: int = 140
    fade_duration: int = 220
    pulse_duration: int = 650

    border_width: int = 1
    focus_border_width: int = 2

    normal_border: str = "#2A2F3A"
    hover_border: str = "#3A4350"
    focus_border: str = "#4F8CFF"

    disabled_alpha: float = 0.55

    target_fps: int = 60

    def __post_init__(self) -> None:

        if self.hover_duration < 0:
            raise EffectConfigurationError(
                "hover_duration cannot be negative."
            )

        if self.focus_duration < 0:
            raise EffectConfigurationError(
                "focus_duration cannot be negative."
            )

        if self.fade_duration < 0:
            raise EffectConfigurationError(
                "fade_duration cannot be negative."
            )

        if self.pulse_duration < 0:
            raise EffectConfigurationError(
                "pulse_duration cannot be negative."
            )

        if self.border_width < 0:
            raise EffectConfigurationError(
                "border_width cannot be negative."
            )

        if self.focus_border_width < 0:
            raise EffectConfigurationError(
                "focus_border_width cannot be negative."
            )

        if not 0.0 <= self.disabled_alpha <= 1.0:
            raise EffectConfigurationError(
                "disabled_alpha must be between 0.0 and 1.0."
            )

        if self.target_fps <= 0:
            raise EffectConfigurationError(
                "target_fps must be greater than zero."
            )


# ============================================================================
# Effect Statistics
# ============================================================================

@dataclass(slots=True)
class EffectStats:
    """Runtime effect statistics."""

    hover_bindings: int = 0
    focus_bindings: int = 0
    glow_effects: int = 0
    fades: int = 0
    pulses: int = 0
    emphasis_effects: int = 0
    disabled_updates: int = 0

    completed: int = 0
    cancelled: int = 0
    failed: int = 0


# ============================================================================
# Color Helpers
# ============================================================================

def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(minimum, min(maximum, value))


def _normalize_hex(color: str) -> str:
    """
    Normalize #RGB / #RRGGBB hex colors to #RRGGBB.
    """

    value = str(color).strip()

    if not value.startswith("#"):
        raise EffectConfigurationError(
            f"Unsupported color format: {color}"
        )

    value = value[1:]

    if len(value) == 3:
        value = "".join(
            character * 2
            for character in value
        )

    if len(value) != 6:

        raise EffectConfigurationError(
            f"Invalid hex color: {color}"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise EffectConfigurationError(
            f"Invalid hex color: {color}"
        ) from exc

    return f"#{value.upper()}"


def hex_to_rgb(
    color: str,
) -> tuple[int, int, int]:
    """Convert #RRGGBB into RGB."""

    value = _normalize_hex(color)[1:]

    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


def rgb_to_hex(
    red: int,
    green: int,
    blue: int,
) -> str:
    """Convert RGB values to #RRGGBB."""

    red = max(0, min(255, int(red)))
    green = max(0, min(255, int(green)))
    blue = max(0, min(255, int(blue)))

    return f"#{red:02X}{green:02X}{blue:02X}"


def blend_colors(
    start: str,
    end: str,
    progress: float,
) -> str:
    """
    Blend two hex colors.

    progress:
        0.0 -> start
        1.0 -> end
    """

    progress = _clamp(progress)

    sr, sg, sb = hex_to_rgb(start)
    er, eg, eb = hex_to_rgb(end)

    red = round(
        sr + ((er - sr) * progress)
    )

    green = round(
        sg + ((eg - sg) * progress)
    )

    blue = round(
        sb + ((eb - sb) * progress)
    )

    return rgb_to_hex(
        red,
        green,
        blue,
    )


def lighten(
    color: str,
    amount: float = 0.15,
) -> str:
    """Lighten a color."""

    return blend_colors(
        color,
        "#FFFFFF",
        _clamp(amount),
    )


def darken(
    color: str,
    amount: float = 0.15,
) -> str:
    """Darken a color."""

    return blend_colors(
        color,
        "#000000",
        _clamp(amount),
    )


# ============================================================================
# Safe Widget Helpers
# ============================================================================

def safe_configure(
    widget: tk.Misc,
    **kwargs: Any,
) -> bool:
    """
    Configure a widget safely.

    Returns True when configuration succeeds.
    """

    if widget is None:
        return False

    try:
        widget.configure(
            **kwargs
        )
        return True

    except (tk.TclError, AttributeError, TypeError):
        return False


def widget_exists(
    widget: tk.Misc | None,
) -> bool:
    """Return True when a Tk widget still exists."""

    if widget is None:
        return False

    try:
        return bool(
            widget.winfo_exists()
        )

    except tk.TclError:
        return False


# ============================================================================
# Hover Effect
# ============================================================================

class HoverEffect:
    """
    Reusable hover-state controller.

    It can alter:
        • background
        • foreground
        • border color
        • cursor
    """

    def __init__(
        self,
        widget: tk.Misc,
        *,
        normal_background: str | None = None,
        hover_background: str | None = None,
        normal_foreground: str | None = None,
        hover_foreground: str | None = None,
        normal_border: str | None = None,
        hover_border: str | None = None,
        cursor: str | None = "hand2",
        enabled: bool = True,
    ) -> None:

        if widget is None:
            raise EffectConfigurationError(
                "HoverEffect requires a widget."
            )

        self.widget = widget

        self.normal_background = normal_background
        self.hover_background = hover_background

        self.normal_foreground = normal_foreground
        self.hover_foreground = hover_foreground

        self.normal_border = normal_border
        self.hover_border = hover_border

        self.cursor = cursor

        self.enabled = enabled

        self._lock = RLock()

        self._bound = False

    def bind(self) -> None:
        """Bind hover events."""

        with self._lock:

            if self._bound:
                return

            self.widget.bind(
                "<Enter>",
                self._on_enter,
                add="+",
            )

            self.widget.bind(
                "<Leave>",
                self._on_leave,
                add="+",
            )

            self._bound = True

    def _on_enter(
        self,
        _event: tk.Event,
    ) -> None:

        if not self.enabled:
            return

        kwargs: dict[str, Any] = {}

        if self.hover_background is not None:
            kwargs["bg"] = self.hover_background

        if self.hover_foreground is not None:
            kwargs["fg"] = self.hover_foreground

        if self.hover_border is not None:
            kwargs["highlightbackground"] = self.hover_border

        if self.cursor:
            kwargs["cursor"] = self.cursor

        safe_configure(
            self.widget,
            **kwargs,
        )

    def _on_leave(
        self,
        _event: tk.Event,
    ) -> None:

        if not self.enabled:
            return

        kwargs: dict[str, Any] = {}

        if self.normal_background is not None:
            kwargs["bg"] = self.normal_background

        if self.normal_foreground is not None:
            kwargs["fg"] = self.normal_foreground

        if self.normal_border is not None:
            kwargs["highlightbackground"] = self.normal_border

        safe_configure(
            self.widget,
            **kwargs,
        )

    def set_enabled(
        self,
        enabled: bool,
    ) -> None:
        self.enabled = bool(enabled)


# ============================================================================
# Focus Ring Effect
# ============================================================================

class FocusRingEffect:
    """
    Adds a border-focus effect to input widgets.
    """

    def __init__(
        self,
        widget: tk.Misc,
        *,
        normal_color: str = "#2A2F3A",
        focus_color: str = "#4F8CFF",
        normal_width: int = 1,
        focus_width: int = 2,
    ) -> None:

        if widget is None:
            raise EffectConfigurationError(
                "FocusRingEffect requires a widget."
            )

        self.widget = widget

        self.normal_color = normal_color
        self.focus_color = focus_color

        self.normal_width = max(
            0,
            int(normal_width),
        )

        self.focus_width = max(
            0,
            int(focus_width),
        )

        self._bound = False

    def bind(self) -> None:

        if self._bound:
            return

        self.widget.bind(
            "<FocusIn>",
            self._focus_in,
            add="+",
        )

        self.widget.bind(
            "<FocusOut>",
            self._focus_out,
            add="+",
        )

        self._bound = True

    def _focus_in(
        self,
        _event: tk.Event,
    ) -> None:

        safe_configure(
            self.widget,
            highlightthickness=self.focus_width,
            highlightbackground=self.focus_color,
            highlightcolor=self.focus_color,
        )

    def _focus_out(
        self,
        _event: tk.Event,
    ) -> None:

        safe_configure(
            self.widget,
            highlightthickness=self.normal_width,
            highlightbackground=self.normal_color,
            highlightcolor=self.normal_color,
        )


# ============================================================================
# Effects Manager
# ============================================================================

class EffectsManager:
    """
    High-level visual-effect manager for AssistantX.

    Recommended usage:

        effects = EffectsManager(root)

        effects.bind_hover(...)
        effects.bind_focus(...)
        effects.fade_window(...)
        effects.pulse(...)
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        config: EffectConfig | None = None,
        animation_engine: AnimationEngine | None = None,
    ) -> None:

        if root is None:
            raise EffectConfigurationError(
                "EffectsManager requires a root widget."
            )

        self.root = root

        self.config = (
            config
            or EffectConfig()
        )

        self._lock = RLock()

        self._engine = (
            animation_engine
            or AnimationEngine(
                root,
                enabled=(
                    self.config.enabled
                    and not self.config.reduced_motion
                ),
                target_fps=self.config.target_fps,
            )
        )

        self._handles: set[
            AnimationHandle
        ] = set()

        self._hover_effects: list[
            HoverEffect
        ] = []

        self._focus_effects: list[
            FocusRingEffect
        ] = []

        self._stats = EffectStats()

    # ========================================================================
    # Hover
    # ========================================================================

    def bind_hover(
        self,
        widget: tk.Misc,
        *,
        normal_background: str | None = None,
        hover_background: str | None = None,
        normal_foreground: str | None = None,
        hover_foreground: str | None = None,
        normal_border: str | None = None,
        hover_border: str | None = None,
        cursor: str | None = "hand2",
    ) -> HoverEffect:
        """Attach a hover effect to a widget."""

        effect = HoverEffect(
            widget,
            normal_background=normal_background,
            hover_background=hover_background,
            normal_foreground=normal_foreground,
            hover_foreground=hover_foreground,
            normal_border=normal_border,
            hover_border=hover_border,
            cursor=cursor,
            enabled=self.config.enabled,
        )

        effect.bind()

        with self._lock:

            self._hover_effects.append(
                effect
            )

            self._stats.hover_bindings += 1

        return effect

    # ========================================================================
    # Focus
    # ========================================================================

    def bind_focus(
        self,
        widget: tk.Misc,
        *,
        normal_color: str | None = None,
        focus_color: str | None = None,
        normal_width: int | None = None,
        focus_width: int | None = None,
    ) -> FocusRingEffect:
        """Attach a focus-ring effect."""

        effect = FocusRingEffect(
            widget,
            normal_color=(
                normal_color
                or self.config.normal_border
            ),
            focus_color=(
                focus_color
                or self.config.focus_border
            ),
            normal_width=(
                self.config.border_width
                if normal_width is None
                else normal_width
            ),
            focus_width=(
                self.config.focus_border_width
                if focus_width is None
                else focus_width
            ),
        )

        effect.bind()

        with self._lock:

            self._focus_effects.append(
                effect
            )

            self._stats.focus_bindings += 1

        return effect

    # ========================================================================
    # Glow
    # ========================================================================

    def glow(
        self,
        widget: tk.Misc,
        *,
        start_color: str,
        glow_color: str,
        duration: int | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> AnimationHandle:
        """
        Animate a glow-like border.

        Tkinter does not provide real CSS box-shadow/glow,
        so this safely animates the highlight border instead.
        """

        if widget is None:
            raise EffectConfigurationError(
                "Glow effect requires a widget."
            )

        self._stats.glow_effects += 1

        if not self._motion_allowed():

            safe_configure(
                widget,
                highlightbackground=glow_color,
                highlightcolor=glow_color,
            )

            return self._completed_handle()

        def update(
            progress: float,
        ) -> None:

            if progress <= 0.5:

                local = progress * 2.0

                color = blend_colors(
                    start_color,
                    glow_color,
                    local,
                )

            else:

                local = (
                    progress - 0.5
                ) * 2.0

                color = blend_colors(
                    glow_color,
                    start_color,
                    local,
                )

            safe_configure(
                widget,
                highlightbackground=color,
                highlightcolor=color,
            )

        return self._track(
            self._engine.animate(
                update,
                config=AnimationConfig(
                    duration=(
                        duration
                        if duration is not None
                        else self.config.pulse_duration
                    ),
                    easing=Easing.SMOOTH,
                ),
                on_complete=on_complete,
            )
        )

    # ========================================================================
    # Pulse
    # ========================================================================

    def pulse(
        self,
        widget: tk.Misc,
        *,
        normal_color: str,
        pulse_color: str,
        duration: int | None = None,
        cycles: int = 1,
        property_name: str = "highlightbackground",
    ) -> AnimationHandle:
        """
        Pulse between two colors.

        Good for:
            • recording indicator
            • active AI state
            • notification highlight
        """

        if widget is None:
            raise EffectConfigurationError(
                "Pulse effect requires a widget."
            )

        cycles = max(
            1,
            int(cycles),
        )

        self._stats.pulses += 1

        if not self._motion_allowed():

            safe_configure(
                widget,
                **{
                    property_name: pulse_color
                },
            )

            return self._completed_handle()

        total_duration = (
            duration
            if duration is not None
            else self.config.pulse_duration
        ) * cycles

        def update(
            progress: float,
        ) -> None:

            cycle_progress = (
                progress * cycles
            ) % 1.0

            if cycle_progress <= 0.5:

                amount = (
                    cycle_progress * 2.0
                )

            else:

                amount = (
                    1.0
                    - (
                        cycle_progress - 0.5
                    ) * 2.0
                )

            color = blend_colors(
                normal_color,
                pulse_color,
                amount,
            )

            safe_configure(
                widget,
                **{
                    property_name: color
                },
            )

        return self._track(
            self._engine.animate(
                update,
                config=AnimationConfig(
                    duration=max(
                        1,
                        total_duration,
                    ),
                    easing=Easing.LINEAR,
                ),
            )
        )

    # ========================================================================
    # Emphasis
    # ========================================================================

    def emphasize(
        self,
        widget: tk.Misc,
        *,
        normal_background: str,
        emphasis_background: str,
        duration: int = 450,
    ) -> AnimationHandle:
        """
        Temporarily emphasize a widget background.
        """

        if widget is None:
            raise EffectConfigurationError(
                "Emphasis effect requires a widget."
            )

        self._stats.emphasis_effects += 1

        if not self._motion_allowed():

            safe_configure(
                widget,
                bg=emphasis_background,
            )

            return self._completed_handle()

        def update(
            progress: float,
        ) -> None:

            if progress <= 0.5:

                local = progress * 2.0

                color = blend_colors(
                    normal_background,
                    emphasis_background,
                    local,
                )

            else:

                local = (
                    progress - 0.5
                ) * 2.0

                color = blend_colors(
                    emphasis_background,
                    normal_background,
                    local,
                )

            safe_configure(
                widget,
                bg=color,
            )

        return self._track(
            self._engine.animate(
                update,
                config=AnimationConfig(
                    duration=max(
                        0,
                        int(duration),
                    ),
                    easing=Easing.SMOOTH,
                ),
            )
        )

    # ========================================================================
    # Window Fade
    # ========================================================================

    def fade_window(
        self,
        window: tk.Toplevel | tk.Tk,
        *,
        start: float = 0.0,
        end: float = 1.0,
        duration: int | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> AnimationHandle:
        """
        Fade a Tk/Toplevel window using the -alpha attribute.

        Note:
            Alpha support depends on the operating system/window manager.
        """

        if window is None:
            raise EffectConfigurationError(
                "fade_window requires a window."
            )

        start = _clamp(start)
        end = _clamp(end)

        self._stats.fades += 1

        if not self._motion_allowed():

            with contextlib.suppress(tk.TclError):
                window.attributes(
                    "-alpha",
                    end,
                )

            if on_complete:
                on_complete()

            return self._completed_handle()

        delta = (
            end - start
        )

        def update(
            progress: float,
        ) -> None:

            alpha = (
                start
                + delta * progress
            )

            try:

                if widget_exists(window):

                    window.attributes(
                        "-alpha",
                        _clamp(alpha),
                    )

            except tk.TclError:
                pass

        return self._track(
            self._engine.animate(
                update,
                config=AnimationConfig(
                    duration=(
                        duration
                        if duration is not None
                        else self.config.fade_duration
                    ),
                    easing=Easing.SMOOTH,
                ),
                on_complete=on_complete,
            )
        )

    def fade_in(
        self,
        window: tk.Toplevel | tk.Tk,
        *,
        duration: int | None = None,
    ) -> AnimationHandle:
        """Fade a window in."""

        return self.fade_window(
            window,
            start=0.0,
            end=1.0,
            duration=duration,
        )

    def fade_out(
        self,
        window: tk.Toplevel | tk.Tk,
        *,
        duration: int | None = None,
        destroy_on_complete: bool = False,
    ) -> AnimationHandle:
        """Fade a window out."""

        def completed() -> None:

            if destroy_on_complete:

                try:

                    if widget_exists(window):
                        window.destroy()

                except tk.TclError:
                    pass

        return self.fade_window(
            window,
            start=1.0,
            end=0.0,
            duration=duration,
            on_complete=completed,
        )

    # ========================================================================
    # Disabled State
    # ========================================================================

    def set_disabled(
        self,
        widget: tk.Misc,
        disabled: bool = True,
        *,
        disabled_background: str | None = None,
        disabled_foreground: str | None = None,
        normal_background: str | None = None,
        normal_foreground: str | None = None,
    ) -> None:
        """
        Apply a visual + logical disabled state.

        Works with widgets that support `state`.
        """

        self._stats.disabled_updates += 1

        if disabled:

            safe_configure(
                widget,
                state="disabled",
            )

            kwargs: dict[str, Any] = {}

            if disabled_background:
                kwargs["bg"] = (
                    disabled_background
                )

            if disabled_foreground:
                kwargs["fg"] = (
                    disabled_foreground
                )

            if kwargs:
                safe_configure(
                    widget,
                    **kwargs,
                )

        else:

            safe_configure(
                widget,
                state="normal",
            )

            kwargs = {}

            if normal_background:
                kwargs["bg"] = (
                    normal_background
                )

            if normal_foreground:
                kwargs["fg"] = (
                    normal_foreground
                )

            if kwargs:
                safe_configure(
                    widget,
                    **kwargs,
                )

    # ========================================================================
    # Animation Tracking
    # ========================================================================

    def _track(
        self,
        handle: AnimationHandle,
    ) -> AnimationHandle:

        with self._lock:
            self._handles.add(handle)

        return handle

    def cancel(
        self,
        handle: AnimationHandle | None,
    ) -> None:
        """Cancel a running effect animation."""

        if handle is None:
            return

        try:

            self._engine.cancel(
                handle
            )

        finally:

            with self._lock:
                self._handles.discard(
                    handle
                )

                self._stats.cancelled += 1

    def cancel_all(self) -> None:
        """Cancel all running visual effects."""

        with self._lock:

            handles = list(
                self._handles
            )

        for handle in handles:

            try:
                self.cancel(handle)
            except Exception:
                logger.exception(
                    "Failed to cancel effect."
                )

        with self._lock:
            self._handles.clear()

    # ========================================================================
    # Configuration
    # ========================================================================

    def set_enabled(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable effects."""

        enabled = bool(enabled)

        self.config = EffectConfig(
            enabled=enabled,
            reduced_motion=self.config.reduced_motion,
            hover_duration=self.config.hover_duration,
            focus_duration=self.config.focus_duration,
            fade_duration=self.config.fade_duration,
            pulse_duration=self.config.pulse_duration,
            border_width=self.config.border_width,
            focus_border_width=self.config.focus_border_width,
            normal_border=self.config.normal_border,
            hover_border=self.config.hover_border,
            focus_border=self.config.focus_border,
            disabled_alpha=self.config.disabled_alpha,
            target_fps=self.config.target_fps,
        )

        self._engine.set_enabled(
            enabled
            and not self.config.reduced_motion
        )

        with self._lock:

            for effect in self._hover_effects:
                effect.set_enabled(
                    enabled
                )

    def set_reduced_motion(
        self,
        enabled: bool,
    ) -> None:
        """Enable/disable reduced-motion mode."""

        self.config = EffectConfig(
            enabled=self.config.enabled,
            reduced_motion=bool(enabled),
            hover_duration=self.config.hover_duration,
            focus_duration=self.config.focus_duration,
            fade_duration=self.config.fade_duration,
            pulse_duration=self.config.pulse_duration,
            border_width=self.config.border_width,
            focus_border_width=self.config.focus_border_width,
            normal_border=self.config.normal_border,
            hover_border=self.config.hover_border,
            focus_border=self.config.focus_border,
            disabled_alpha=self.config.disabled_alpha,
            target_fps=self.config.target_fps,
        )

        self._engine.set_enabled(
            self.config.enabled
            and not self.config.reduced_motion
        )

    def _motion_allowed(
        self,
    ) -> bool:

        return (
            self.config.enabled
            and not self.config.reduced_motion
        )

    # ========================================================================
    # Completed Handle
    # ========================================================================

    @staticmethod
    def _completed_handle() -> AnimationHandle:

        from dashboard.animations import (
            AnimationState,
        )

        handle = AnimationHandle()

        handle._set_state(
            AnimationState.COMPLETED
        )

        return handle

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(
        self,
    ) -> dict[str, Any]:
        """Return safe effect diagnostics."""

        with self._lock:

            return {
                "enabled":
                    self.config.enabled,

                "reduced_motion":
                    self.config.reduced_motion,

                "active_animations":
                    len(self._handles),

                "hover_bindings":
                    self._stats.hover_bindings,

                "focus_bindings":
                    self._stats.focus_bindings,

                "glow_effects":
                    self._stats.glow_effects,

                "fades":
                    self._stats.fades,

                "pulses":
                    self._stats.pulses,

                "emphasis_effects":
                    self._stats.emphasis_effects,

                "disabled_updates":
                    self._stats.disabled_updates,

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
        """Stop all effects and release resources."""

        self.cancel_all()

        self._engine.shutdown()

        with self._lock:

            self._hover_effects.clear()
            self._focus_effects.clear()


# ============================================================================
# Convenience Helpers
# ============================================================================

def add_hover_effect(
    widget: tk.Misc,
    *,
    normal_background: str | None = None,
    hover_background: str | None = None,
    normal_foreground: str | None = None,
    hover_foreground: str | None = None,
    normal_border: str | None = None,
    hover_border: str | None = None,
    cursor: str | None = "hand2",
) -> HoverEffect:
    """Attach a standalone hover effect."""

    effect = HoverEffect(
        widget,
        normal_background=normal_background,
        hover_background=hover_background,
        normal_foreground=normal_foreground,
        hover_foreground=hover_foreground,
        normal_border=normal_border,
        hover_border=hover_border,
        cursor=cursor,
    )

    effect.bind()

    return effect


def add_focus_ring(
    widget: tk.Misc,
    *,
    normal_color: str = "#2A2F3A",
    focus_color: str = "#4F8CFF",
    normal_width: int = 1,
    focus_width: int = 2,
) -> FocusRingEffect:
    """Attach a standalone focus-ring effect."""

    effect = FocusRingEffect(
        widget,
        normal_color=normal_color,
        focus_color=focus_color,
        normal_width=normal_width,
        focus_width=focus_width,
    )

    effect.bind()

    return effect


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Models
    "EffectConfig",
    "EffectConfigurationError",
    # Exceptions
    "EffectError",
    # Enums
    "EffectState",
    "EffectStateError",
    "EffectStats",
    "EffectType",
    # Manager
    "EffectsManager",
    "FocusRingEffect",
    # Effects
    "HoverEffect",
    "add_focus_ring",
    # Convenience
    "add_hover_effect",
    "blend_colors",
    "darken",
    # Color utilities
    "hex_to_rgb",
    "lighten",
    "rgb_to_hex",
    # Widget helpers
    "safe_configure",
    "widget_exists",
]
