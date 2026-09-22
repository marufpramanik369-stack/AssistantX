"""
dashboard.widgets
=================

Reusable UI widgets for AssistantX.

This module provides lightweight, professional Tkinter widgets that can
be reused across the dashboard without creating dependencies on the
application/business logic.

Included
--------
- AXCard
- AXLabel
- AXButton
- AXIconButton
- AXEntry
- AXSearchEntry
- AXTextBox
- AXSwitch
- AXProgressBar
- AXBadge
- AXStatusDot
- AXSeparator
- AXScrollableFrame
- AXSectionHeader
- AXEmptyState
- AXLoadingDots

Design goals
------------
- Standard Tkinter only
- Theme-friendly
- Safe lifecycle handling
- Callback-based
- Reusable
- Small public API
- Compatible with AssistantX dashboard architecture
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

logger = logging.getLogger(__name__)

# ============================================================================
# Exceptions
# ============================================================================


class WidgetError(Exception):
    """Base exception for dashboard widgets."""


class WidgetConfigurationError(WidgetError):
    """Raised when widget configuration is invalid."""


class WidgetStateError(WidgetError):
    """Raised when an operation is invalid for the current widget state."""


# ============================================================================
# Helpers
# ============================================================================


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_callback(
    callback: Callable | None,
    *args,
    **kwargs,
) -> None:
    if callback is None:
        return

    try:
        callback(*args, **kwargs)
    except (tk.TclError, RuntimeError, TypeError, ValueError):
        # UI callbacks should never crash the dashboard, but failures should
        # remain visible for diagnosis.
        logger.exception("Dashboard widget callback failed")


def _widget_exists(widget: tk.Misc) -> bool:
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


# ============================================================================
# Enums
# ============================================================================


class ButtonStyle(str, Enum):
    """Button visual styles."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    GHOST = "ghost"
    DANGER = "danger"


class StatusType(str, Enum):
    """Common status types."""

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


# ============================================================================
# Theme
# ============================================================================


@dataclass(frozen=True, slots=True)
class WidgetTheme:
    """Default theme used by reusable widgets."""

    background: str = "#111827"
    surface: str = "#182235"
    surface_hover: str = "#202C42"

    foreground: str = "#F3F4F6"
    secondary_text: str = "#9CA3AF"
    muted_text: str = "#6B7280"

    border: str = "#293548"

    primary: str = "#3B82F6"
    primary_hover: str = "#2563EB"

    danger: str = "#EF4444"
    danger_hover: str = "#DC2626"

    success: str = "#22C55E"
    warning: str = "#F59E0B"
    info: str = "#60A5FA"

    input_background: str = "#0F172A"

    disabled_background: str = "#1B2433"
    disabled_text: str = "#5F6B7A"


DEFAULT_WIDGET_THEME = WidgetTheme()


# ============================================================================
# Base Widget
# ============================================================================


class AXWidgetMixin:
    """Shared functionality for AssistantX widgets."""

    def _safe_configure(self, **kwargs) -> None:
        with contextlib.suppress(tk.TclError):
            self.configure(**kwargs)

    def _safe_bind(self, sequence: str, callback) -> None:
        with contextlib.suppress(tk.TclError):
            self.bind(sequence, callback, add="+")


# ============================================================================
# AXCard
# ============================================================================


class AXCard(tk.Frame, AXWidgetMixin):
    """
    Reusable dashboard card/container.

    Example
    -------
        card = AXCard(parent)
        card.pack(fill="x", padx=10, pady=10)

        tk.Label(
            card.content,
            text="AssistantX",
        ).pack()
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        padding: int = 14,
        border_width: int = 1,
        radius: int = 0,
        hover: bool = False,
        on_click: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        del radius  # Tkinter Frame has no native corner radius.

        self.theme = theme
        self.padding = padding
        self.hover_enabled = hover
        self.on_click = on_click

        super().__init__(
            master,
            bg=theme.surface,
            bd=border_width,
            relief="solid" if border_width else "flat",
            highlightthickness=0,
            **kwargs,
        )

        self.content = tk.Frame(
            self,
            bg=theme.surface,
            bd=0,
            highlightthickness=0,
        )

        self.content.pack(
            fill="both",
            expand=True,
            padx=padding,
            pady=padding,
        )

        if hover:
            self._bind_hover()

        if on_click:
            self._bind_click()

    def _bind_hover(self) -> None:
        self.bind("<Enter>", self._hover_enter, add="+")
        self.bind("<Leave>", self._hover_leave, add="+")
        self.content.bind("<Enter>", self._hover_enter, add="+")
        self.content.bind("<Leave>", self._hover_leave, add="+")

    def _hover_enter(self, _event=None) -> None:
        self._set_surface(self.theme.surface_hover)

    def _hover_leave(self, _event=None) -> None:
        self._set_surface(self.theme.surface)

    def _set_surface(self, color: str) -> None:
        try:
            self.configure(bg=color)

            for child in self.winfo_children():
                child.configure(bg=color)

            self.content.configure(bg=color)

        except tk.TclError:
            pass

    def _bind_click(self) -> None:
        self.bind("<Button-1>", self._click, add="+")
        self.content.bind("<Button-1>", self._click, add="+")

    def _click(self, _event=None) -> None:
        _safe_callback(self.on_click)


# ============================================================================
# AXLabel
# ============================================================================


class AXLabel(tk.Label, AXWidgetMixin):
    """Theme-aware reusable label."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "",
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        size: int = 10,
        weight: str = "normal",
        color: str | None = None,
        align: str = "left",
        **kwargs,
    ) -> None:
        self.theme = theme

        super().__init__(
            master,
            text=text,
            bg=theme.background,
            fg=color or theme.foreground,
            font=("Segoe UI", size, weight),
            anchor=align,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

    def set_text(self, text: str) -> None:
        self.configure(text=str(text))

    def set_color(self, color: str) -> None:
        self.configure(fg=color)


# ============================================================================
# AXButton
# ============================================================================


class AXButton(tk.Button, AXWidgetMixin):
    """Professional button with AssistantX theme support."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "",
        command: Callable[[], None] | None = None,
        style: ButtonStyle | str = ButtonStyle.PRIMARY,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        width: int = 0,
        height: int = 1,
        **kwargs,
    ) -> None:
        self.theme = theme
        self._command = command

        try:
            button_style = ButtonStyle(style)
        except ValueError:
            button_style = ButtonStyle.PRIMARY

        self.button_style = button_style

        bg, hover, fg = self._colors(button_style)

        super().__init__(
            master,
            text=text,
            command=self._invoke,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=theme.disabled_text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            width=width,
            height=height,
            padx=12,
            pady=7,
            **kwargs,
        )

        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    def _colors(self, style: ButtonStyle):
        if style == ButtonStyle.PRIMARY:
            return (
                self.theme.primary,
                self.theme.primary_hover,
                "#FFFFFF",
            )

        if style == ButtonStyle.DANGER:
            return (
                self.theme.danger,
                self.theme.danger_hover,
                "#FFFFFF",
            )

        if style == ButtonStyle.SECONDARY:
            return (
                self.theme.surface,
                self.theme.surface_hover,
                self.theme.foreground,
            )

        return (
            self.theme.background,
            self.theme.surface_hover,
            self.theme.foreground,
        )

    def _invoke(self) -> None:
        _safe_callback(self._command)

    def _on_enter(self, _event=None) -> None:
        try:
            _, hover, _ = self._colors(self.button_style)
            self.configure(bg=hover)
        except tk.TclError:
            pass

    def _on_leave(self, _event=None) -> None:
        try:
            bg, _, _ = self._colors(self.button_style)
            self.configure(bg=bg)
        except tk.TclError:
            pass

    def set_command(self, command: Callable[[], None] | None) -> None:
        self._command = command

    def set_text(self, text: str) -> None:
        self.configure(text=str(text))


# ============================================================================
# AXIconButton
# ============================================================================


class AXIconButton(AXButton):
    """Compact button intended for icons."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        icon: str = "",
        command: Callable[[], None] | None = None,
        size: int = 32,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            text=icon,
            command=command,
            style=ButtonStyle.GHOST,
            theme=theme,
            width=2,
            height=1,
            font=("Segoe UI Symbol", 11),
            padx=0,
            pady=0,
            **kwargs,
        )

        self.configure(
            width=2,
            height=1,
        )

        self._button_size = size

    def set_icon(self, icon: str) -> None:
        self.configure(text=str(icon))


# ============================================================================
# AXEntry
# ============================================================================


class AXEntry(tk.Entry, AXWidgetMixin):
    """Theme-aware single-line input field."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        placeholder: str = "",
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        show: str = "",
        **kwargs,
    ) -> None:
        self.theme = theme
        self.placeholder = placeholder
        self._placeholder_active = False
        self._show = show

        super().__init__(
            master,
            bg=theme.input_background,
            fg=theme.foreground,
            insertbackground=theme.foreground,
            selectbackground=theme.primary,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.border,
            highlightcolor=theme.primary,
            font=("Segoe UI", 10),
            show=show,
            **kwargs,
        )

        if placeholder:
            self._set_placeholder()

            self.bind(
                "<FocusIn>",
                self._on_focus_in,
                add="+",
            )

            self.bind(
                "<FocusOut>",
                self._on_focus_out,
                add="+",
            )

    def _set_placeholder(self) -> None:
        if self.get():
            return

        self._placeholder_active = True

        self.configure(
            fg=self.theme.muted_text,
            show="",
        )

        self.insert(0, self.placeholder)

    def _clear_placeholder(self) -> None:
        if not self._placeholder_active:
            return

        self.delete(0, "end")
        self._placeholder_active = False

        self.configure(
            fg=self.theme.foreground,
            show=self._show,
        )

    def _on_focus_in(self, _event=None) -> None:
        self._clear_placeholder()

    def _on_focus_out(self, _event=None) -> None:
        if not self.get():
            self._set_placeholder()

    def get_value(self) -> str:
        if self._placeholder_active:
            return ""

        return self.get()

    def set_value(self, value: str) -> None:
        self._clear_placeholder()

        self.delete(0, "end")
        self.insert(0, str(value))

    def clear(self) -> None:
        self._clear_placeholder()
        self.delete(0, "end")

        if self.placeholder:
            self._set_placeholder()


# ============================================================================
# AXSearchEntry
# ============================================================================


class AXSearchEntry(tk.Frame, AXWidgetMixin):
    """Search field with icon and callback."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        placeholder: str = "Search...",
        command: Callable[[str], None] | None = None,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme
        self.command = command

        super().__init__(
            master,
            bg=theme.input_background,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.border,
            highlightcolor=theme.primary,
            **kwargs,
        )

        self.icon = tk.Label(
            self,
            text="⌕",
            bg=theme.input_background,
            fg=theme.muted_text,
            font=("Segoe UI Symbol", 13),
        )

        self.icon.pack(
            side="left",
            padx=(10, 3),
        )

        self.entry = AXEntry(
            self,
            placeholder=placeholder,
            theme=theme,
            relief="flat",
            highlightthickness=0,
        )

        self.entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 8),
            pady=7,
        )

        self.entry.bind(
            "<Return>",
            self._submit,
            add="+",
        )

        self.entry.bind(
            "<KeyRelease>",
            self._on_key_release,
            add="+",
        )

    def _on_key_release(self, _event=None) -> None:
        if self.command:
            _safe_callback(
                self.command,
                self.get(),
            )

    def _submit(self, _event=None) -> None:
        if self.command:
            _safe_callback(
                self.command,
                self.get(),
            )

    def get(self) -> str:
        return self.entry.get_value()

    def set(self, value: str) -> None:
        self.entry.set_value(value)

    def clear(self) -> None:
        self.entry.clear()


# ============================================================================
# AXTextBox
# ============================================================================


class AXTextBox(tk.Text, AXWidgetMixin):
    """Theme-aware multiline text box."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        height: int = 5,
        **kwargs,
    ) -> None:
        self.theme = theme

        super().__init__(
            master,
            bg=theme.input_background,
            fg=theme.foreground,
            insertbackground=theme.foreground,
            selectbackground=theme.primary,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.border,
            highlightcolor=theme.primary,
            font=("Segoe UI", 10),
            height=height,
            wrap="word",
            padx=10,
            pady=8,
            undo=True,
            **kwargs,
        )

    def get_value(self) -> str:
        return self.get("1.0", "end-1c")

    def set_value(self, value: str) -> None:
        self.delete("1.0", "end")
        self.insert("1.0", str(value))

    def clear(self) -> None:
        self.delete("1.0", "end")


# ============================================================================
# AXSwitch
# ============================================================================


class AXSwitch(tk.Frame, AXWidgetMixin):
    """Compact animated-style boolean switch."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        value: bool = False,
        command: Callable[[bool], None] | None = None,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        width: int = 42,
        height: int = 22,
        **kwargs,
    ) -> None:
        self.theme = theme
        self._value = bool(value)
        self._command = command
        self._width = width
        self._height = height

        super().__init__(
            master,
            width=width,
            height=height,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.pack_propagate(False)

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=theme.background,
            highlightthickness=0,
            bd=0,
        )

        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind(
            "<Button-1>",
            self._toggle,
            add="+",
        )

        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("all")

        w = self._width
        h = self._height

        track_color = (
            self.theme.primary
            if self._value
            else self.theme.border
        )

        self.canvas.create_rounded_rectangle = (
            getattr(
                self.canvas,
                "create_rounded_rectangle",
                None,
            )
        )

        # Tkinter Canvas does not have a native rounded rectangle.
        # Use a regular rectangle + circles for a clean pill shape.

        radius = h // 2

        self.canvas.create_rectangle(
            radius,
            2,
            w - radius,
            h - 2,
            fill=track_color,
            outline=track_color,
        )

        self.canvas.create_oval(
            2,
            2,
            h - 2,
            h - 2,
            fill=track_color,
            outline=track_color,
        )

        self.canvas.create_oval(
            w - h + 2,
            2,
            w - 2,
            h - 2,
            fill=track_color,
            outline=track_color,
        )

        knob_size = h - 6

        x = w - h // 2 if self._value else h // 2

        self.canvas.create_oval(
            x - knob_size // 2,
            h // 2 - knob_size // 2,
            x + knob_size // 2,
            h // 2 + knob_size // 2,
            fill="#FFFFFF",
            outline="#FFFFFF",
        )

    def _toggle(self, _event=None) -> None:
        self.set(not self._value)

    def get(self) -> bool:
        return self._value

    def set(
        self,
        value: bool,
        *,
        notify: bool = True,
    ) -> None:
        value = bool(value)

        if value == self._value:
            return

        self._value = value
        self._draw()

        if notify:
            _safe_callback(
                self._command,
                self._value,
            )

    def toggle(self) -> None:
        self.set(not self._value)


# ============================================================================
# AXProgressBar
# ============================================================================


class AXProgressBar(tk.Frame, AXWidgetMixin):
    """Lightweight progress bar."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        value: float = 0.0,
        maximum: float = 100.0,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        height: int = 6,
        **kwargs,
    ) -> None:
        self.theme = theme
        self.maximum = max(1.0, float(maximum))
        self._value = _clamp(
            float(value),
            0.0,
            self.maximum,
        )
        self._height = max(2, height)

        super().__init__(
            master,
            bg=theme.border,
            height=self._height,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.pack_propagate(False)

        self.bar = tk.Frame(
            self,
            bg=theme.primary,
            height=self._height,
            bd=0,
        )

        self._render()

    def _render(self) -> None:
        try:
            width = self.winfo_width()

            if width <= 1:
                self.after_idle(self._render)
                return

            ratio = self._value / self.maximum
            bar_width = max(
                0,
                int(width * ratio),
            )

            self.bar.place(
                x=0,
                y=0,
                width=bar_width,
                height=self._height,
            )

        except tk.TclError:
            pass

    def set(self, value: float) -> None:
        self._value = _clamp(
            float(value),
            0.0,
            self.maximum,
        )
        self._render()

    def get(self) -> float:
        return self._value

    def set_maximum(self, maximum: float) -> None:
        self.maximum = max(
            1.0,
            float(maximum),
        )

        self._value = min(
            self._value,
            self.maximum,
        )

        self._render()


# ============================================================================
# AXBadge
# ============================================================================


class AXBadge(tk.Label, AXWidgetMixin):
    """Small status/category badge."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "",
        color: str | None = None,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme
        self._color = color or theme.primary

        super().__init__(
            master,
            text=text,
            bg=self._color,
            fg="#FFFFFF",
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=2,
            bd=0,
            **kwargs,
        )

    def set_text(self, text: str) -> None:
        self.configure(text=str(text))

    def set_color(self, color: str) -> None:
        self._color = color
        self.configure(bg=color)


# ============================================================================
# AXStatusDot
# ============================================================================


class AXStatusDot(tk.Frame, AXWidgetMixin):
    """Small circular status indicator."""

    STATUS_COLORS: ClassVar[dict[StatusType, str]] = {
        StatusType.ONLINE: "#22C55E",
        StatusType.OFFLINE: "#6B7280",
        StatusType.BUSY: "#F59E0B",
        StatusType.WARNING: "#F59E0B",
        StatusType.ERROR: "#EF4444",
        StatusType.INFO: "#60A5FA",
    }

    def __init__(
        self,
        master: tk.Misc,
        *,
        status: StatusType | str = StatusType.OFFLINE,
        size: int = 9,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme
        self._size = max(4, int(size))

        super().__init__(
            master,
            width=self._size,
            height=self._size,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.pack_propagate(False)

        self.dot = tk.Canvas(
            self,
            width=self._size,
            height=self._size,
            bg=theme.background,
            highlightthickness=0,
            bd=0,
        )

        self.dot.pack(
            fill="both",
            expand=True,
        )

        self.set_status(status)

    def set_status(
        self,
        status: StatusType | str,
    ) -> None:
        try:
            status = StatusType(status)
        except ValueError:
            status = StatusType.OFFLINE

        color = self.STATUS_COLORS.get(
            status,
            self.theme.muted_text,
        )

        self.dot.delete("all")

        self.dot.create_oval(
            1,
            1,
            self._size - 1,
            self._size - 1,
            fill=color,
            outline=color,
        )

        self._status = status

    def get_status(self) -> StatusType:
        return self._status


# ============================================================================
# AXSeparator
# ============================================================================


class AXSeparator(tk.Frame, AXWidgetMixin):
    """Horizontal or vertical separator."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        vertical: bool = False,
        color: str | None = None,
        thickness: int = 1,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.vertical = vertical
        self.theme = theme

        color = color or theme.border

        if vertical:
            super().__init__(
                master,
                width=thickness,
                bg=color,
                bd=0,
                highlightthickness=0,
                **kwargs,
            )
        else:
            super().__init__(
                master,
                height=thickness,
                bg=color,
                bd=0,
                highlightthickness=0,
                **kwargs,
            )


# ============================================================================
# AXScrollableFrame
# ============================================================================


class AXScrollableFrame(tk.Frame, AXWidgetMixin):
    """
    Scrollable frame based on Canvas + Frame.

    Use:

        scroll = AXScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)

        tk.Label(
            scroll.content,
            text="Hello",
        ).pack()
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        scrollbar: bool = True,
        **kwargs,
    ) -> None:
        self.theme = theme

        super().__init__(
            master,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.canvas = tk.Canvas(
            self,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
        )

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.scrollbar: tk.Scrollbar | None = None

        if scrollbar:
            self.scrollbar = tk.Scrollbar(
                self,
                orient="vertical",
                command=self.canvas.yview,
            )

            self.scrollbar.pack(
                side="right",
                fill="y",
            )

            self.canvas.configure(
                yscrollcommand=self.scrollbar.set,
            )

        self.content = tk.Frame(
            self.canvas,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
        )

        self._window_id = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )

        self.content.bind(
            "<Configure>",
            self._on_content_configure,
            add="+",
        )

        self.canvas.bind(
            "<Configure>",
            self._on_canvas_configure,
            add="+",
        )

        self.canvas.bind(
            "<Enter>",
            self._bind_mousewheel,
            add="+",
        )

        self.canvas.bind(
            "<Leave>",
            self._unbind_mousewheel,
            add="+",
        )

    def _on_content_configure(self, _event=None) -> None:
        with contextlib.suppress(tk.TclError):
            self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )

    def _on_canvas_configure(self, event) -> None:
        with contextlib.suppress(tk.TclError):
            self.canvas.itemconfigure(
                self._window_id,
                width=event.width,
            )

    def _bind_mousewheel(self, _event=None) -> None:
        self.canvas.bind_all(
            "<MouseWheel>",
            self._on_mousewheel,
            add="+",
        )

    def _unbind_mousewheel(self, _event=None) -> None:
        with contextlib.suppress(tk.TclError):
            self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        with contextlib.suppress(tk.TclError):
            self.canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units",
            )

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)

    def scroll_to_bottom(self) -> None:
        self.canvas.yview_moveto(1)


# ============================================================================
# AXSectionHeader
# ============================================================================


class AXSectionHeader(tk.Frame, AXWidgetMixin):
    """Section title with optional action button."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        subtitle: str = "",
        action_text: str = "",
        action: Callable[[], None] | None = None,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme

        super().__init__(
            master,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        text_frame = tk.Frame(
            self,
            bg=theme.background,
        )

        text_frame.pack(
            side="left",
            fill="x",
            expand=True,
        )

        self.title_label = tk.Label(
            text_frame,
            text=title,
            bg=theme.background,
            fg=theme.foreground,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )

        self.title_label.pack(
            anchor="w",
        )

        if subtitle:
            self.subtitle_label = tk.Label(
                text_frame,
                text=subtitle,
                bg=theme.background,
                fg=theme.secondary_text,
                font=("Segoe UI", 8),
                anchor="w",
            )

            self.subtitle_label.pack(
                anchor="w",
                pady=(2, 0),
            )
        else:
            self.subtitle_label = None

        if action_text:
            self.action_button = AXButton(
                self,
                text=action_text,
                command=action,
                style=ButtonStyle.GHOST,
                theme=theme,
            )

            self.action_button.pack(
                side="right",
            )
        else:
            self.action_button = None

    def set_title(self, title: str) -> None:
        self.title_label.configure(
            text=str(title)
        )

    def set_subtitle(self, subtitle: str) -> None:
        if self.subtitle_label is None:
            return

        self.subtitle_label.configure(
            text=str(subtitle)
        )


# ============================================================================
# AXEmptyState
# ============================================================================


class AXEmptyState(tk.Frame, AXWidgetMixin):
    """Reusable empty-state component."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        icon: str = "○",
        title: str = "Nothing here",
        message: str = "",
        action_text: str = "",
        action: Callable[[], None] | None = None,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme

        super().__init__(
            master,
            bg=theme.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.icon_label = tk.Label(
            self,
            text=icon,
            bg=theme.background,
            fg=theme.muted_text,
            font=("Segoe UI Symbol", 28),
        )

        self.icon_label.pack(
            pady=(20, 8),
        )

        self.title_label = tk.Label(
            self,
            text=title,
            bg=theme.background,
            fg=theme.foreground,
            font=("Segoe UI", 12, "bold"),
        )

        self.title_label.pack()

        if message:
            self.message_label = tk.Label(
                self,
                text=message,
                bg=theme.background,
                fg=theme.secondary_text,
                font=("Segoe UI", 9),
                wraplength=360,
                justify="center",
            )

            self.message_label.pack(
                pady=(5, 12),
            )
        else:
            self.message_label = None

        if action_text:
            self.action_button = AXButton(
                self,
                text=action_text,
                command=action,
                style=ButtonStyle.PRIMARY,
                theme=theme,
            )

            self.action_button.pack(
                pady=(0, 20),
            )
        else:
            self.action_button = None

    def set_title(self, title: str) -> None:
        self.title_label.configure(
            text=str(title)
        )

    def set_message(self, message: str) -> None:
        if self.message_label is not None:
            self.message_label.configure(
                text=str(message)
            )


# ============================================================================
# AXLoadingDots
# ============================================================================


class AXLoadingDots(tk.Label, AXWidgetMixin):
    """Small text-based loading animation."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "Loading",
        interval: int = 350,
        theme: WidgetTheme = DEFAULT_WIDGET_THEME,
        **kwargs,
    ) -> None:
        self.theme = theme
        self.base_text = text
        self.interval = max(
            80,
            _safe_int(interval, 350),
        )

        self._running = False
        self._after_id: str | None = None
        self._step = 0

        super().__init__(
            master,
            text=text,
            bg=theme.background,
            fg=theme.secondary_text,
            font=("Segoe UI", 9),
            bd=0,
            **kwargs,
        )

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._step = 0
        self._animate()

    def stop(self) -> None:
        self._running = False

        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._after_id)

            self._after_id = None

        with contextlib.suppress(tk.TclError):
            self.configure(
                text=self.base_text
            )

    def _animate(self) -> None:
        if not self._running:
            return

        dots = "." * (self._step % 4)

        try:
            self.configure(
                text=f"{self.base_text}{dots}"
            )

            self._step += 1

            self._after_id = self.after(
                self.interval,
                self._animate,
            )

        except tk.TclError:
            self._running = False
            self._after_id = None

    @property
    def running(self) -> bool:
        return self._running


# ============================================================================
# Factory helpers
# ============================================================================


def create_card(
    parent: tk.Misc,
    **kwargs,
) -> AXCard:
    return AXCard(parent, **kwargs)


def create_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    **kwargs,
) -> AXButton:
    return AXButton(
        parent,
        text=text,
        command=command,
        **kwargs,
    )


def create_entry(
    parent: tk.Misc,
    **kwargs,
) -> AXEntry:
    return AXEntry(parent, **kwargs)


def create_search(
    parent: tk.Misc,
    **kwargs,
) -> AXSearchEntry:
    return AXSearchEntry(parent, **kwargs)


def create_switch(
    parent: tk.Misc,
    **kwargs,
) -> AXSwitch:
    return AXSwitch(parent, **kwargs)


def create_progress(
    parent: tk.Misc,
    **kwargs,
) -> AXProgressBar:
    return AXProgressBar(parent, **kwargs)


def create_badge(
    parent: tk.Misc,
    text: str,
    **kwargs,
) -> AXBadge:
    return AXBadge(
        parent,
        text=text,
        **kwargs,
    )


def create_status_dot(
    parent: tk.Misc,
    **kwargs,
) -> AXStatusDot:
    return AXStatusDot(parent, **kwargs)


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "DEFAULT_WIDGET_THEME",
    "AXBadge",
    "AXButton",
    # Widgets
    "AXCard",
    "AXEmptyState",
    "AXEntry",
    "AXIconButton",
    "AXLabel",
    "AXLoadingDots",
    "AXProgressBar",
    "AXScrollableFrame",
    "AXSearchEntry",
    "AXSectionHeader",
    "AXSeparator",
    "AXStatusDot",
    "AXSwitch",
    "AXTextBox",
    # Enums
    "ButtonStyle",
    "StatusType",
    "WidgetConfigurationError",
    # Exceptions
    "WidgetError",
    "WidgetStateError",
    # Theme
    "WidgetTheme",
    "create_badge",
    "create_button",
    # Factories
    "create_card",
    "create_entry",
    "create_progress",
    "create_search",
    "create_status_dot",
    "create_switch",
]
