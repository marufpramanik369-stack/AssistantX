"""
dashboard.input_box
===================

Professional chat input component for AssistantX.

Features
--------
- Multiline message input
- Enter -> send
- Shift+Enter -> new line
- Ctrl+Enter -> send
- Placeholder text
- Character counter
- Send button
- Clear / focus / enable / disable helpers
- Thread-safe callback dispatch
- Custom styling
- Validation
- Maximum character limit
- Read-only state support
- Diagnostics and state inspection
- Tkinter compatible
- CustomTkinter compatible where possible

Typical usage
-------------

    from dashboard.input_box import InputBox

    def on_send(message):
        print("User:", message)

    input_box = InputBox(
        parent,
        on_send=on_send,
    )

    input_box.pack(fill="x", padx=20, pady=20)
"""

from __future__ import annotations

import contextlib
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

# ============================================================================
# Exceptions
# ============================================================================


class InputBoxError(Exception):
    """Base exception for input box errors."""


class InputBoxConfigurationError(InputBoxError):
    """Raised when input box configuration is invalid."""


class InputBoxStateError(InputBoxError):
    """Raised when an operation is invalid for the current state."""


# ============================================================================
# Enums
# ============================================================================


class InputState(str, Enum):
    """Current state of the input box."""

    READY = "ready"
    DISABLED = "disabled"
    READONLY = "readonly"
    DESTROYED = "destroyed"


class SendMode(str, Enum):
    """Keyboard behavior for sending messages."""

    ENTER = "enter"
    CTRL_ENTER = "ctrl_enter"
    BUTTON_ONLY = "button_only"


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class InputBoxConfig:
    """Configuration for the input component."""

    placeholder: str = "Message AssistantX..."
    max_characters: int = 8000
    min_characters: int = 1

    height: int = 90
    width: int = 600

    send_mode: SendMode = SendMode.ENTER

    show_send_button: bool = True
    show_character_count: bool = True

    wrap: str = "word"

    font: tuple[str, int] = ("Segoe UI", 11)
    button_font: tuple[str, int] = ("Segoe UI Semibold", 10)

    background: str = "#1E1E1E"
    foreground: str = "#F5F5F5"
    border_color: str = "#3A3A3A"
    focus_border_color: str = "#5B8CFF"

    placeholder_color: str = "#777777"
    button_background: str = "#3B82F6"
    button_foreground: str = "#FFFFFF"

    disabled_background: str = "#171717"
    disabled_foreground: str = "#666666"

    character_warning_threshold: float = 0.90

    padx: int = 12
    pady: int = 10

    def __post_init__(self) -> None:
        if self.max_characters <= 0:
            raise InputBoxConfigurationError(
                "max_characters must be greater than 0."
            )

        if self.min_characters < 0:
            raise InputBoxConfigurationError(
                "min_characters cannot be negative."
            )

        if self.min_characters > self.max_characters:
            raise InputBoxConfigurationError(
                "min_characters cannot exceed max_characters."
            )

        if self.height <= 0:
            raise InputBoxConfigurationError(
                "height must be greater than 0."
            )

        if self.width <= 0:
            raise InputBoxConfigurationError(
                "width must be greater than 0."
            )

        if not 0.0 < self.character_warning_threshold <= 1.0:
            raise InputBoxConfigurationError(
                "character_warning_threshold must be between 0 and 1."
            )


@dataclass
class InputBoxStats:
    """Runtime statistics."""

    send_attempts: int = 0
    sent_messages: int = 0
    rejected_messages: int = 0
    cleared_messages: int = 0
    focus_events: int = 0
    key_events: int = 0

    @property
    def success_rate(self) -> float:
        if self.send_attempts == 0:
            return 0.0

        return self.sent_messages / self.send_attempts


# ============================================================================
# Helpers
# ============================================================================


def normalize_message(text: str) -> str:
    """
    Normalize user input without destroying intentional line breaks.
    """

    if not isinstance(text, str):
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove zero-width characters.
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")

    # Remove trailing spaces from individual lines.
    lines = [line.rstrip() for line in text.split("\n")]

    # Remove empty lines at beginning/end.
    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def is_blank(text: str) -> bool:
    """Return True when text contains no meaningful content."""

    return not isinstance(text, str) or not text.strip()


def clamp_text(text: str, maximum: int) -> str:
    """Safely limit text length."""

    if len(text) <= maximum:
        return text

    return text[:maximum]


# ============================================================================
# InputBox
# ============================================================================


class InputBox(tk.Frame):
    """
    Professional reusable chat input component.

    Parameters
    ----------
    parent:
        Parent Tkinter widget.

    on_send:
        Callback receiving the submitted message.

    config:
        Optional InputBoxConfig.

    **kwargs:
        Additional frame configuration.
    """

    def __init__(
        self,
        parent: tk.Misc,
        on_send: Callable[[str], Any] | None = None,
        config: InputBoxConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, **kwargs)

        self._lock = threading.RLock()

        self.config_data = config or InputBoxConfig()
        self._on_send = on_send

        self._state = InputState.READY
        self._destroyed = False
        self._placeholder_visible = False

        self._stats = InputBoxStats()

        self._build_variables()
        self._build_ui()
        self._bind_events()

        self._show_placeholder()
        self._update_counter()
        self._update_send_button()

    # ----------------------------------------------------------------------
    # Variables
    # ----------------------------------------------------------------------

    def _build_variables(self) -> None:
        self._character_var = tk.StringVar(value="0")
        self._status_var = tk.StringVar(value="")

    # ----------------------------------------------------------------------
    # UI
    # ----------------------------------------------------------------------

    def _build_ui(self) -> None:
        cfg = self.config_data

        self.configure(
            bg=cfg.background,
            highlightthickness=0,
            bd=0,
        )

        self._outer = tk.Frame(
            self,
            bg=cfg.background,
            bd=1,
            relief="solid",
            highlightthickness=0,
        )

        self._outer.pack(
            fill="both",
            expand=True,
        )

        self._text_frame = tk.Frame(
            self._outer,
            bg=cfg.background,
        )

        self._text_frame.pack(
            fill="both",
            expand=True,
            padx=1,
            pady=1,
        )

        self._text = tk.Text(
            self._text_frame,
            height=4,
            width=max(20, cfg.width // 8),
            wrap=cfg.wrap,
            font=cfg.font,
            bg=cfg.background,
            fg=cfg.foreground,
            insertbackground=cfg.foreground,
            selectbackground=cfg.focus_border_color,
            selectforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=cfg.padx,
            pady=cfg.pady,
            undo=True,
            maxundo=-1,
            highlightthickness=0,
        )

        self._text.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self._right = tk.Frame(
            self._outer,
            bg=cfg.background,
        )

        self._right.pack(
            side="right",
            fill="y",
            padx=8,
            pady=8,
        )

        self._counter = tk.Label(
            self._right,
            textvariable=self._character_var,
            font=("Segoe UI", 8),
            bg=cfg.background,
            fg=cfg.placeholder_color,
        )

        if cfg.show_character_count:
            self._counter.pack(
                pady=(2, 8),
            )

        if cfg.show_send_button:
            self._send_button = tk.Button(
                self._right,
                text="Send",
                font=cfg.button_font,
                bg=cfg.button_background,
                fg=cfg.button_foreground,
                activebackground=cfg.focus_border_color,
                activeforeground=cfg.button_foreground,
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=14,
                pady=7,
                command=self.send,
            )

            self._send_button.pack(
                side="bottom",
            )
        else:
            self._send_button = None

        self._text.tag_configure(
            "placeholder",
            foreground=cfg.placeholder_color,
        )

    # ----------------------------------------------------------------------
    # Events
    # ----------------------------------------------------------------------

    def _bind_events(self) -> None:
        self._text.bind(
            "<KeyPress>",
            self._on_key_press,
            add="+",
        )

        self._text.bind(
            "<KeyRelease>",
            self._on_key_release,
            add="+",
        )

        self._text.bind(
            "<FocusIn>",
            self._on_focus_in,
            add="+",
        )

        self._text.bind(
            "<FocusOut>",
            self._on_focus_out,
            add="+",
        )

        self._text.bind(
            "<Control-Return>",
            self._on_ctrl_enter,
            add="+",
        )

        self._text.bind(
            "<Escape>",
            self._on_escape,
            add="+",
        )

        self._text.bind(
            "<<Modified>>",
            self._on_modified,
            add="+",
        )

        self._text.edit_modified(False)

    # ----------------------------------------------------------------------
    # Event Handlers
    # ----------------------------------------------------------------------

    def _on_key_press(self, event: tk.Event) -> str | None:
        with self._lock:
            self._stats.key_events += 1

        if self._destroyed:
            return "break"

        if self._placeholder_visible:
            self._hide_placeholder()

        if event.keysym == "Return":
            # Shift+Enter always creates a new line.
            if event.state & 0x0001:
                return None

            if self.config_data.send_mode == SendMode.ENTER:
                self.send()
                return "break"

        if (
            event.keysym == "Return"
            and self.config_data.send_mode == SendMode.CTRL_ENTER
        ):
            return None

        return None

    def _on_ctrl_enter(self, _event: tk.Event) -> str:
        if self._destroyed:
            return "break"

        if self.config_data.send_mode == SendMode.CTRL_ENTER:
            self.send()

        return "break"

    def _on_key_release(self, _event: tk.Event) -> None:
        if self._destroyed:
            return

        self._enforce_max_length()
        self._update_counter()
        self._update_send_button()

    def _on_modified(self, _event: tk.Event) -> None:
        if self._destroyed:
            return

        self._enforce_max_length()
        self._update_counter()
        self._update_send_button()

        with contextlib.suppress(tk.TclError):
            self._text.edit_modified(False)

    def _on_focus_in(self, _event: tk.Event) -> None:
        with self._lock:
            self._stats.focus_events += 1

        if self._placeholder_visible:
            self._hide_placeholder()

        self._set_border_focused(True)

    def _on_focus_out(self, _event: tk.Event) -> None:
        if self._destroyed:
            return

        if self.is_empty():
            self._show_placeholder()

        self._set_border_focused(False)

    def _on_escape(self, _event: tk.Event) -> str:
        self.clear()
        return "break"

    # ----------------------------------------------------------------------
    # Placeholder
    # ----------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        if self._destroyed:
            return

        if not self.is_empty():
            return

        self._placeholder_visible = True

        self._text.configure(
            fg=self.config_data.placeholder_color,
        )

        self._text.insert(
            "1.0",
            self.config_data.placeholder,
        )

        self._text.tag_add(
            "placeholder",
            "1.0",
            "end",
        )

    def _hide_placeholder(self) -> None:
        if not self._placeholder_visible:
            return

        self._placeholder_visible = False

        try:
            self._text.delete("1.0", "end")
            self._text.configure(
                fg=self.config_data.foreground,
            )
        except tk.TclError:
            pass

    # ----------------------------------------------------------------------
    # Border
    # ----------------------------------------------------------------------

    def _set_border_focused(self, focused: bool) -> None:
        if self._destroyed:
            return

        color = (
            self.config_data.focus_border_color
            if focused
            else self.config_data.border_color
        )

        with contextlib.suppress(tk.TclError):
            self._outer.configure(
                highlightbackground=color,
                highlightcolor=color,
                highlightthickness=1,
            )

    # ----------------------------------------------------------------------
    # Text
    # ----------------------------------------------------------------------

    def get_text(self) -> str:
        """Return current user-entered text."""

        if self._destroyed:
            return ""

        if self._placeholder_visible:
            return ""

        try:
            return self._text.get("1.0", "end-1c")
        except tk.TclError:
            return ""

    def get_normalized_text(self) -> str:
        """Return normalized user text."""

        return normalize_message(self.get_text())

    def set_text(self, text: str) -> None:
        """Replace current input text."""

        if self._destroyed:
            raise InputBoxStateError(
                "Cannot modify a destroyed InputBox."
            )

        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        text = clamp_text(
            text,
            self.config_data.max_characters,
        )

        self._hide_placeholder()

        self._text.delete(
            "1.0",
            "end",
        )

        if text:
            self._text.insert(
                "1.0",
                text,
            )

        self._update_counter()
        self._update_send_button()

    def append_text(self, text: str) -> None:
        """Append text to the current message."""

        if self._destroyed:
            return

        if not isinstance(text, str):
            return

        self._hide_placeholder()

        current = self.get_text()

        separator = ""
        if current and not current.endswith((" ", "\n")):
            separator = " "

        combined = current + separator + text

        self.set_text(combined)

    def clear(self) -> None:
        """Clear input."""

        if self._destroyed:
            return

        self._hide_placeholder()

        try:
            self._text.delete("1.0", "end")
        except tk.TclError:
            return

        with self._lock:
            self._stats.cleared_messages += 1

        self._show_placeholder()
        self._update_counter()
        self._update_send_button()

    # ----------------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------------

    def is_empty(self) -> bool:
        """Return whether input is empty."""

        return is_blank(
            "" if self._placeholder_visible else self.get_text()
        )

    def validate(self, text: str | None = None) -> bool:
        """Validate message before sending."""

        value = (
            self.get_normalized_text()
            if text is None
            else normalize_message(text)
        )

        if not value:
            return False

        if len(value) < self.config_data.min_characters:
            return False

        return not len(value) > self.config_data.max_characters

    # ----------------------------------------------------------------------
    # Send
    # ----------------------------------------------------------------------

    def send(self) -> bool:
        """
        Submit the current message.

        Returns
        -------
        bool
            True if successfully submitted.
        """

        if self._destroyed:
            return False

        with self._lock:
            self._stats.send_attempts += 1

        if self._state != InputState.READY:
            with self._lock:
                self._stats.rejected_messages += 1
            return False

        message = self.get_normalized_text()

        if not self.validate(message):
            with self._lock:
                self._stats.rejected_messages += 1
            return False

        callback = self._on_send

        try:
            if callback is not None:
                callback(message)

            with self._lock:
                self._stats.sent_messages += 1

            self.clear()
            self.focus()

            return True

        except Exception:
            with self._lock:
                self._stats.rejected_messages += 1
            raise

    # ----------------------------------------------------------------------
    # Character Counter
    # ----------------------------------------------------------------------

    def _enforce_max_length(self) -> None:
        if self._placeholder_visible:
            return

        try:
            value = self._text.get(
                "1.0",
                "end-1c",
            )
        except tk.TclError:
            return

        maximum = self.config_data.max_characters

        if len(value) <= maximum:
            return

        trimmed = value[:maximum]

        try:
            self._text.delete(
                "1.0",
                "end",
            )

            self._text.insert(
                "1.0",
                trimmed,
            )
        except tk.TclError:
            pass

    def _update_counter(self) -> None:
        if self._destroyed:
            return

        length = len(self.get_text())
        maximum = self.config_data.max_characters

        try:
            self._character_var.set(
                f"{length:,} / {maximum:,}"
            )
        except tk.TclError:
            return

        if not hasattr(self, "_counter"):
            return

        ratio = length / maximum if maximum else 1.0

        if ratio >= 1.0:
            fg = "#EF4444"
        elif ratio >= self.config_data.character_warning_threshold:
            fg = "#F59E0B"
        else:
            fg = self.config_data.placeholder_color

        with contextlib.suppress(tk.TclError):
            self._counter.configure(
                fg=fg,
            )

    # ----------------------------------------------------------------------
    # Button
    # ----------------------------------------------------------------------

    def _update_send_button(self) -> None:
        if self._send_button is None:
            return

        enabled = (
            self._state == InputState.READY
            and self.validate()
        )

        with contextlib.suppress(tk.TclError):
            self._send_button.configure(
                state="normal" if enabled else "disabled"
            )

    # ----------------------------------------------------------------------
    # State
    # ----------------------------------------------------------------------

    def enable(self) -> None:
        """Enable input."""

        if self._destroyed:
            return

        self._state = InputState.READY

        with contextlib.suppress(tk.TclError):
            self._text.configure(
                state="normal",
                bg=self.config_data.background,
                fg=self.config_data.foreground,
            )

        self._update_send_button()

    def disable(self) -> None:
        """Disable input."""

        if self._destroyed:
            return

        self._state = InputState.DISABLED

        try:
            self._text.configure(
                state="disabled",
                bg=self.config_data.disabled_background,
                fg=self.config_data.disabled_foreground,
            )

            if self._send_button is not None:
                self._send_button.configure(
                    state="disabled"
                )
        except tk.TclError:
            pass

    def set_readonly(self, readonly: bool = True) -> None:
        """Set or clear readonly mode."""

        if self._destroyed:
            return

        if readonly:
            self._state = InputState.READONLY

            with contextlib.suppress(tk.TclError):
                self._text.configure(
                    state="disabled"
                )
        else:
            self.enable()

        self._update_send_button()

    def is_enabled(self) -> bool:
        """Return whether input is enabled."""

        return self._state == InputState.READY

    # ----------------------------------------------------------------------
    # Focus
    # ----------------------------------------------------------------------

    def focus(self) -> None:
        """Focus the text input."""

        if self._destroyed:
            return

        try:
            self._text.focus_set()

            with self._lock:
                self._stats.focus_events += 1
        except tk.TclError:
            pass

    def focus_force(self) -> None:
        """Force focus onto the input."""

        if self._destroyed:
            return

        with contextlib.suppress(tk.TclError):
            self._text.focus_force()

    # ----------------------------------------------------------------------
    # Callback
    # ----------------------------------------------------------------------

    def set_on_send(
        self,
        callback: Callable[[str], Any] | None,
    ) -> None:
        """Change send callback."""

        if callback is not None and not callable(callback):
            raise TypeError(
                "callback must be callable or None."
            )

        self._on_send = callback

    # ----------------------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------------------

    def set_placeholder(self, text: str) -> None:
        """Change placeholder text."""

        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        self.config_data = InputBoxConfig(
            **{
                **self.config_data.__dict__,
                "placeholder": text,
            }
        )

        if self.is_empty():
            self._show_placeholder()

    def set_max_characters(self, maximum: int) -> None:
        """Update maximum character limit."""

        if maximum <= 0:
            raise ValueError(
                "maximum must be greater than zero."
            )

        current = self.config_data

        self.config_data = InputBoxConfig(
            **{
                **current.__dict__,
                "max_characters": maximum,
                "min_characters": min(
                    current.min_characters,
                    maximum,
                ),
            }
        )

        self._enforce_max_length()
        self._update_counter()
        self._update_send_button()

    # ----------------------------------------------------------------------
    # State Queries
    # ----------------------------------------------------------------------

    @property
    def state(self) -> InputState:
        """Current input state."""

        return self._state

    @property
    def character_count(self) -> int:
        """Current character count."""

        return len(self.get_text())

    @property
    def max_characters(self) -> int:
        """Return the configured maximum number of input characters."""

        return self.config_data.max_characters

    @property
    def remaining_characters(self) -> int:
        """Number of remaining characters."""

        return max(
            0,
            self.config_data.max_characters
            - self.character_count,
        )

    # ----------------------------------------------------------------------
    # Stats / Diagnostics
    # ----------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return runtime statistics."""

        with self._lock:
            return {
                "send_attempts": self._stats.send_attempts,
                "sent_messages": self._stats.sent_messages,
                "rejected_messages": self._stats.rejected_messages,
                "cleared_messages": self._stats.cleared_messages,
                "focus_events": self._stats.focus_events,
                "key_events": self._stats.key_events,
                "success_rate": round(
                    self._stats.success_rate,
                    4,
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return component diagnostics."""

        return {
            "component": "InputBox",
            "state": self._state.value,
            "destroyed": self._destroyed,
            "placeholder_visible": self._placeholder_visible,
            "character_count": self.character_count,
            "remaining_characters": self.remaining_characters,
            "max_characters": self.config_data.max_characters,
            "send_mode": self.config_data.send_mode.value,
            "has_send_callback": self._on_send is not None,
            "has_send_button": self._send_button is not None,
            "stats": self.stats(),
        }

    # ----------------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------------

    def select_all(self) -> None:
        """Select all text."""

        if self._destroyed or self._placeholder_visible:
            return

        with contextlib.suppress(tk.TclError):
            self._text.tag_add(
                "sel",
                "1.0",
                "end-1c",
            )

    def insert_at_cursor(self, text: str) -> None:
        """Insert text at the current cursor position."""

        if self._destroyed:
            return

        if not isinstance(text, str):
            return

        self._hide_placeholder()

        try:
            self._text.insert(
                "insert",
                text,
            )
        except tk.TclError:
            return

        self._enforce_max_length()
        self._update_counter()
        self._update_send_button()

    # ----------------------------------------------------------------------
    # Destroy
    # ----------------------------------------------------------------------

    def destroy(self) -> None:
        """Safely destroy the component."""

        if self._destroyed:
            return

        self._destroyed = True
        self._state = InputState.DESTROYED

        self._on_send = None

        with contextlib.suppress(tk.TclError):
            super().destroy()


# ============================================================================
# Factory
# ============================================================================


def create_input_box(
    parent: tk.Misc,
    on_send: Callable[[str], Any] | None = None,
    **kwargs: Any,
) -> InputBox:
    """
    Convenience factory.

    Example
    -------
        input_box = create_input_box(
            parent,
            on_send=handle_message,
        )
    """

    return InputBox(
        parent,
        on_send=on_send,
        **kwargs,
    )


# ============================================================================
# Module Exports
# ============================================================================


__all__ = [
    "InputBox",
    "InputBoxConfig",
    "InputBoxConfigurationError",
    "InputBoxError",
    "InputBoxStateError",
    "InputBoxStats",
    "InputState",
    "SendMode",
    "clamp_text",
    "create_input_box",
    "is_blank",
    "normalize_message",
]
