"""
dashboard.message_bubble
========================

Professional message bubble component for AssistantX.

Supports
--------
- User / Assistant / System messages
- Left/right alignment
- Multiline text
- Timestamp
- Copy action
- Optional action buttons
- Message status
- Hover effects
- Selection-friendly text
- Markdown-like plain text display
- Theme/config friendly styling
- Safe update/destroy lifecycle
- Diagnostics

Typical usage
-------------

    from dashboard.message_bubble import (
        MessageBubble,
        MessageRole,
    )

    bubble = MessageBubble(
        parent,
        text="Hello! How can I help you?",
        role=MessageRole.ASSISTANT,
    )

    bubble.pack(fill="x", padx=20, pady=8)
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

# ============================================================================
# Exceptions
# ============================================================================


class MessageBubbleError(Exception):
    """Base exception for message bubble errors."""


class MessageBubbleConfigurationError(MessageBubbleError):
    """Raised when message bubble configuration is invalid."""


class MessageBubbleStateError(MessageBubbleError):
    """Raised when an operation is invalid for the current state."""


# ============================================================================
# Enums
# ============================================================================


class MessageRole(str, Enum):
    """Supported message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"


class MessageStatus(str, Enum):
    """Message delivery/display status."""

    NONE = "none"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    ERROR = "error"


class BubbleState(str, Enum):
    """Runtime state of a bubble."""

    READY = "ready"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


# ============================================================================
# Configuration
# ============================================================================


@dataclass(frozen=True)
class MessageBubbleConfig:
    """Visual and behavioral configuration."""

    user_background: str = "#2563EB"
    user_foreground: str = "#FFFFFF"

    assistant_background: str = "#2A2A2A"
    assistant_foreground: str = "#F5F5F5"

    system_background: str = "#242424"
    system_foreground: str = "#D0D0D0"

    error_background: str = "#3A2020"
    error_foreground: str = "#FFB4B4"

    timestamp_color: str = "#8A8A8A"
    secondary_color: str = "#9CA3AF"

    border_color: str = "#3A3A3A"
    hover_border_color: str = "#5B8CFF"

    action_background: str = "#333333"
    action_foreground: str = "#DADADA"
    action_hover_background: str = "#444444"

    font: tuple[str, int] = ("Segoe UI", 10)
    timestamp_font: tuple[str, int] = ("Segoe UI", 8)
    action_font: tuple[str, int] = ("Segoe UI", 8)

    max_width: int = 720

    corner_radius: int = 12
    horizontal_padding: int = 14
    vertical_padding: int = 10

    show_timestamp: bool = True
    show_copy_button: bool = True
    show_status: bool = True

    enable_hover_actions: bool = True

    def __post_init__(self) -> None:
        if self.max_width <= 0:
            raise MessageBubbleConfigurationError(
                "max_width must be greater than zero."
            )

        if self.horizontal_padding < 0:
            raise MessageBubbleConfigurationError(
                "horizontal_padding cannot be negative."
            )

        if self.vertical_padding < 0:
            raise MessageBubbleConfigurationError(
                "vertical_padding cannot be negative."
            )


# ============================================================================
# Statistics
# ============================================================================


@dataclass
class MessageBubbleStats:
    """Runtime statistics."""

    copy_count: int = 0
    hover_count: int = 0
    update_count: int = 0
    status_updates: int = 0


# ============================================================================
# Helper Functions
# ============================================================================


def normalize_message(text: str) -> str:
    """Normalize message text while preserving intentional line breaks."""

    if not isinstance(text, str):
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove zero-width artifacts.
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")

    lines = [
        line.rstrip()
        for line in text.split("\n")
    ]

    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def role_from_value(
    role: MessageRole | str,
) -> MessageRole:
    """Convert a role value into MessageRole."""

    if isinstance(role, MessageRole):
        return role

    try:
        return MessageRole(str(role).lower().strip())
    except ValueError as exc:
        raise MessageBubbleConfigurationError(
            f"Unsupported message role: {role!r}"
        ) from exc


# ============================================================================
# Message Bubble
# ============================================================================


class MessageBubble(tk.Frame):
    """
    Reusable AssistantX message bubble.

    Parameters
    ----------
    parent:
        Parent Tkinter widget.

    text:
        Message content.

    role:
        USER / ASSISTANT / SYSTEM / ERROR.

    timestamp:
        Optional timestamp text.

    status:
        Optional message status.

    config:
        Optional MessageBubbleConfig.

    on_copy:
        Optional callback invoked after copying.

    on_action:
        Optional callback receiving an action name.
    """

    def __init__(
        self,
        parent: tk.Misc,
        text: str = "",
        role: MessageRole | str = MessageRole.ASSISTANT,
        timestamp: str | None = None,
        status: MessageStatus | str = MessageStatus.NONE,
        config: MessageBubbleConfig | None = None,
        on_copy: Callable[[str], Any] | None = None,
        on_action: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._config = config or MessageBubbleConfig()

        super().__init__(
            parent,
            bg=self._config.assistant_background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self._lock = __import__("threading").RLock()

        self._text_value = normalize_message(text)
        self._role = role_from_value(role)
        self._timestamp = timestamp or ""
        self._status = self._normalize_status(status)

        self._on_copy = on_copy
        self._on_action = on_action

        self._state = BubbleState.READY
        self._destroyed = False
        self._hovered = False

        self._stats = MessageBubbleStats()

        self._build_ui()
        self._bind_events()
        self._refresh_visuals()

    # ----------------------------------------------------------------------
    # Status
    # ----------------------------------------------------------------------

    @staticmethod
    def _normalize_status(
        status: MessageStatus | str,
    ) -> MessageStatus:
        if isinstance(status, MessageStatus):
            return status

        try:
            return MessageStatus(
                str(status).lower().strip()
            )
        except ValueError:
            return MessageStatus.NONE

    # ----------------------------------------------------------------------
    # UI Construction
    # ----------------------------------------------------------------------

    def _build_ui(self) -> None:
        cfg = self._config

        self._bubble = tk.Frame(
            self,
            bd=1,
            relief="solid",
            highlightthickness=0,
            padx=cfg.horizontal_padding,
            pady=cfg.vertical_padding,
        )

        self._bubble.pack(
            side="right"
            if self._role == MessageRole.USER
            else "left",
            anchor=(
                "e"
                if self._role == MessageRole.USER
                else "w"
            ),
        )

        self._content_frame = tk.Frame(
            self._bubble,
        )

        self._content_frame.pack(
            fill="both",
            expand=True,
        )

        self._header = tk.Frame(
            self._content_frame,
        )

        self._header.pack(
            fill="x",
            pady=(0, 4),
        )

        self._role_label = tk.Label(
            self._header,
            font=("Segoe UI Semibold", 8),
            anchor="w",
        )

        self._role_label.pack(
            side="left",
        )

        self._timestamp_label = tk.Label(
            self._header,
            font=cfg.timestamp_font,
            anchor="e",
        )

        if cfg.show_timestamp and self._timestamp:
            self._timestamp_label.pack(
                side="right",
                padx=(12, 0),
            )

        self._message = tk.Text(
            self._content_frame,
            wrap="word",
            font=cfg.font,
            height=1,
            width=1,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            cursor="arrow",
        )

        self._message.pack(
            fill="both",
            expand=True,
        )

        self._message.insert(
            "1.0",
            self._text_value,
        )

        self._message.configure(
            state="disabled",
        )

        self._footer = tk.Frame(
            self._content_frame,
        )

        self._footer.pack(
            fill="x",
            pady=(6, 0),
        )

        self._status_label = tk.Label(
            self._footer,
            font=cfg.timestamp_font,
            anchor="w",
        )

        if cfg.show_status:
            self._status_label.pack(
                side="left",
            )

        self._actions = tk.Frame(
            self._footer,
        )

        if cfg.show_copy_button:
            self._copy_button = self._create_action_button(
                "Copy",
                self.copy,
            )

            self._copy_button.pack(
                side="right",
            )
        else:
            self._copy_button = None

        self._update_text_height()

    def _create_action_button(
        self,
        text: str,
        command: Callable[[], Any],
    ) -> tk.Button:
        cfg = self._config

        return tk.Button(
            self._actions,
            text=text,
            command=command,
            font=cfg.action_font,
            bg=cfg.action_background,
            fg=cfg.action_foreground,
            activebackground=cfg.action_hover_background,
            activeforeground=cfg.action_foreground,
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
        )

    # ----------------------------------------------------------------------
    # Events
    # ----------------------------------------------------------------------

    def _bind_events(self) -> None:
        widgets = (
            self,
            self._bubble,
            self._content_frame,
            self._header,
            self._role_label,
            self._timestamp_label,
            self._message,
            self._footer,
            self._status_label,
        )

        for widget in widgets:
            try:
                widget.bind(
                    "<Enter>",
                    self._on_enter,
                    add="+",
                )
                widget.bind(
                    "<Leave>",
                    self._on_leave,
                    add="+",
                )
            except tk.TclError:
                pass

    def _on_enter(self, _event: tk.Event) -> None:
        if self._destroyed:
            return

        with self._lock:
            self._hovered = True
            self._stats.hover_count += 1

        self._refresh_border(True)

    def _on_leave(self, _event: tk.Event) -> None:
        if self._destroyed:
            return

        with self._lock:
            self._hovered = False

        self._refresh_border(False)

    # ----------------------------------------------------------------------
    # Visuals
    # ----------------------------------------------------------------------

    def _colors(self) -> tuple[str, str]:
        cfg = self._config

        if self._role == MessageRole.USER:
            return (
                cfg.user_background,
                cfg.user_foreground,
            )

        if self._role == MessageRole.SYSTEM:
            return (
                cfg.system_background,
                cfg.system_foreground,
            )

        if self._role == MessageRole.ERROR:
            return (
                cfg.error_background,
                cfg.error_foreground,
            )

        return (
            cfg.assistant_background,
            cfg.assistant_foreground,
        )

    def _refresh_visuals(self) -> None:
        if self._destroyed:
            return

        background, foreground = self._colors()
        cfg = self._config

        try:
            self.configure(
                bg=background,
            )

            self._bubble.configure(
                bg=background,
                highlightbackground=cfg.border_color,
                highlightcolor=cfg.border_color,
            )

            self._content_frame.configure(
                bg=background,
            )

            self._header.configure(
                bg=background,
            )

            self._footer.configure(
                bg=background,
            )

            self._actions.configure(
                bg=background,
            )

            self._role_label.configure(
                bg=background,
                fg=foreground,
                text=self._role_display_name(),
            )

            self._timestamp_label.configure(
                bg=background,
                fg=cfg.timestamp_color,
            )

            self._message.configure(
                bg=background,
                fg=foreground,
                insertbackground=foreground,
                selectbackground=cfg.hover_border_color,
                selectforeground="#FFFFFF",
            )

            self._status_label.configure(
                bg=background,
                fg=self._status_color(),
                text=self._status_text(),
            )

        except tk.TclError:
            pass

        self._refresh_border(self._hovered)

    def _refresh_border(self, hovered: bool) -> None:
        if self._destroyed:
            return

        color = (
            self._config.hover_border_color
            if hovered and self._config.enable_hover_actions
            else self._config.border_color
        )

        with contextlib.suppress(tk.TclError):
            self._bubble.configure(
                highlightbackground=color,
                highlightcolor=color,
                highlightthickness=1,
            )

    def _role_display_name(self) -> str:
        return {
            MessageRole.USER: "You",
            MessageRole.ASSISTANT: "AssistantX",
            MessageRole.SYSTEM: "System",
            MessageRole.ERROR: "Error",
        }[self._role]

    def _status_text(self) -> str:
        return {
            MessageStatus.NONE: "",
            MessageStatus.SENDING: "Sending...",
            MessageStatus.SENT: "Sent",
            MessageStatus.DELIVERED: "Delivered",
            MessageStatus.ERROR: "Failed",
        }[self._status]

    def _status_color(self) -> str:
        return {
            MessageStatus.NONE: self._config.secondary_color,
            MessageStatus.SENDING: "#F59E0B",
            MessageStatus.SENT: "#9CA3AF",
            MessageStatus.DELIVERED: "#22C55E",
            MessageStatus.ERROR: "#EF4444",
        }[self._status]

    # ----------------------------------------------------------------------
    # Text Height
    # ----------------------------------------------------------------------

    def _update_text_height(self) -> None:
        if self._destroyed:
            return

        lines = max(
            1,
            self._text_value.count("\n") + 1,
        )

        # Estimate wrapped lines.
        estimated_chars_per_line = 72

        for line in self._text_value.split("\n"):
            lines += max(
                0,
                len(line) // estimated_chars_per_line,
            )

        height = min(
            max(1, lines),
            18,
        )

        with contextlib.suppress(tk.TclError):
            self._message.configure(
                height=height,
            )

    # ----------------------------------------------------------------------
    # Getters
    # ----------------------------------------------------------------------

    def get_text(self) -> str:
        """Return message text."""

        return self._text_value

    @property
    def text(self) -> str:
        return self._text_value

    @property
    def role(self) -> MessageRole:
        return self._role

    @property
    def status(self) -> MessageStatus:
        return self._status

    # ----------------------------------------------------------------------
    # Update
    # ----------------------------------------------------------------------

    def update_message(
        self,
        text: str,
    ) -> None:
        """Replace message text."""

        if self._destroyed:
            raise MessageBubbleStateError(
                "Cannot update a destroyed MessageBubble."
            )

        normalized = normalize_message(text)

        self._text_value = normalized

        try:
            self._message.configure(
                state="normal",
            )

            self._message.delete(
                "1.0",
                "end",
            )

            self._message.insert(
                "1.0",
                normalized,
            )

            self._message.configure(
                state="disabled",
            )
        except tk.TclError:
            return

        with self._lock:
            self._stats.update_count += 1

        self._update_text_height()

    def update_timestamp(
        self,
        timestamp: str | None,
    ) -> None:
        """Update timestamp."""

        if self._destroyed:
            return

        self._timestamp = timestamp or ""

        try:
            self._timestamp_label.configure(
                text=self._timestamp,
            )

            if (
                self._config.show_timestamp
                and self._timestamp
            ):
                self._timestamp_label.pack(
                    side="right",
                    padx=(12, 0),
                )
            else:
                self._timestamp_label.pack_forget()
        except tk.TclError:
            pass

    def update_status(
        self,
        status: MessageStatus | str,
    ) -> None:
        """Update message status."""

        if self._destroyed:
            return

        self._status = self._normalize_status(status)

        with self._lock:
            self._stats.status_updates += 1

        with contextlib.suppress(tk.TclError):
            self._status_label.configure(
                text=self._status_text(),
                fg=self._status_color(),
            )

    def set_role(
        self,
        role: MessageRole | str,
    ) -> None:
        """Change message role."""

        if self._destroyed:
            return

        self._role = role_from_value(role)

        self._refresh_visuals()

    # ----------------------------------------------------------------------
    # Copy
    # ----------------------------------------------------------------------

    def copy(self) -> bool:
        """Copy message text to clipboard."""

        if self._destroyed:
            return False

        if not self._text_value:
            return False

        try:
            self.clipboard_clear()
            self.clipboard_append(
                self._text_value,
            )
            self.update()

            with self._lock:
                self._stats.copy_count += 1

            if self._on_copy is not None:
                self._on_copy(self._text_value)

            self._show_copy_feedback()

            return True

        except tk.TclError:
            return False

    def _show_copy_feedback(self) -> None:
        if self._copy_button is None:
            return

        try:
            original = self._copy_button.cget("text")

            self._copy_button.configure(
                text="Copied",
            )

            self.after(
                1200,
                lambda: self._restore_copy_button(
                    original
                ),
            )
        except tk.TclError:
            pass

    def _restore_copy_button(
        self,
        original: str,
    ) -> None:
        if self._destroyed:
            return

        if self._copy_button is None:
            return

        with contextlib.suppress(tk.TclError):
            self._copy_button.configure(
                text=original,
            )

    # ----------------------------------------------------------------------
    # Actions
    # ----------------------------------------------------------------------

    def trigger_action(
        self,
        action: str,
    ) -> Any:
        """Trigger a named external action."""

        if self._destroyed:
            return None

        if not isinstance(action, str):
            return None

        if self._on_action is not None:
            return self._on_action(action)

        return None

    # ----------------------------------------------------------------------
    # State
    # ----------------------------------------------------------------------

    def enable(self) -> None:
        if self._destroyed:
            return

        self._state = BubbleState.READY
        self._refresh_visuals()

    def disable(self) -> None:
        if self._destroyed:
            return

        self._state = BubbleState.DISABLED

        try:
            if self._copy_button is not None:
                self._copy_button.configure(
                    state="disabled"
                )
        except tk.TclError:
            pass

    # ----------------------------------------------------------------------
    # Callbacks
    # ----------------------------------------------------------------------

    def set_on_copy(
        self,
        callback: Callable[[str], Any] | None,
    ) -> None:
        """Set copy callback."""

        if callback is not None and not callable(callback):
            raise TypeError(
                "callback must be callable or None."
            )

        self._on_copy = callback

    def set_on_action(
        self,
        callback: Callable[[str], Any] | None,
    ) -> None:
        """Set action callback."""

        if callback is not None and not callable(callback):
            raise TypeError(
                "callback must be callable or None."
            )

        self._on_action = callback

    # ----------------------------------------------------------------------
    # Diagnostics
    # ----------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return runtime statistics."""

        with self._lock:
            return {
                "copy_count": self._stats.copy_count,
                "hover_count": self._stats.hover_count,
                "update_count": self._stats.update_count,
                "status_updates": self._stats.status_updates,
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return component diagnostics."""

        return {
            "component": "MessageBubble",
            "state": self._state.value,
            "destroyed": self._destroyed,
            "role": self._role.value,
            "status": self._status.value,
            "text_length": len(self._text_value),
            "has_timestamp": bool(self._timestamp),
            "has_copy_callback": self._on_copy is not None,
            "has_action_callback": self._on_action is not None,
            "stats": self.stats(),
        }

    # ----------------------------------------------------------------------
    # Destroy
    # ----------------------------------------------------------------------

    def destroy(self) -> None:
        """Safely destroy the message bubble."""

        if self._destroyed:
            return

        self._destroyed = True
        self._state = BubbleState.DESTROYED

        self._on_copy = None
        self._on_action = None

        with contextlib.suppress(tk.TclError):
            super().destroy()


# ============================================================================
# Factory Helpers
# ============================================================================


def create_message_bubble(
    parent: tk.Misc,
    text: str,
    role: MessageRole | str = MessageRole.ASSISTANT,
    **kwargs: Any,
) -> MessageBubble:
    """Create a MessageBubble using a simple factory."""

    return MessageBubble(
        parent,
        text=text,
        role=role,
        **kwargs,
    )


def create_user_bubble(
    parent: tk.Misc,
    text: str,
    **kwargs: Any,
) -> MessageBubble:
    """Create a user message bubble."""

    return MessageBubble(
        parent,
        text=text,
        role=MessageRole.USER,
        **kwargs,
    )


def create_assistant_bubble(
    parent: tk.Misc,
    text: str,
    **kwargs: Any,
) -> MessageBubble:
    """Create an AssistantX message bubble."""

    return MessageBubble(
        parent,
        text=text,
        role=MessageRole.ASSISTANT,
        **kwargs,
    )


def create_system_bubble(
    parent: tk.Misc,
    text: str,
    **kwargs: Any,
) -> MessageBubble:
    """Create a system message bubble."""

    return MessageBubble(
        parent,
        text=text,
        role=MessageRole.SYSTEM,
        **kwargs,
    )


def create_error_bubble(
    parent: tk.Misc,
    text: str,
    **kwargs: Any,
) -> MessageBubble:
    """Create an error message bubble."""

    return MessageBubble(
        parent,
        text=text,
        role=MessageRole.ERROR,
        **kwargs,
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "BubbleState",
    "MessageBubble",
    "MessageBubbleConfig",
    "MessageBubbleConfigurationError",
    "MessageBubbleError",
    "MessageBubbleStateError",
    "MessageBubbleStats",
    "MessageRole",
    "MessageStatus",
    "create_assistant_bubble",
    "create_error_bubble",
    "create_message_bubble",
    "create_system_bubble",
    "create_user_bubble",
    "normalize_message",
    "role_from_value",
]
