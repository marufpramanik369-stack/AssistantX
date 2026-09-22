"""
AssistantX Dashboard - Chat Interface
=====================================

Professional chat interface/controller for AssistantX.

Responsibilities
----------------
    • Chat message rendering
    • User / assistant message handling
    • Conversation state
    • Streaming response support
    • Typing indicator
    • Message history management
    • Auto-scroll
    • Chat animation integration
    • Assistant callback integration
    • Keyboard shortcuts
    • Safe UI updates

This module intentionally keeps AI/business logic outside the UI layer.

Architecture
------------

    User Input
        │
        ▼
    ChatView
        │
        ├── Input
        ├── Message Store
        ├── Message Renderer
        ├── Animation Manager
        │
        ▼
    on_message callback
        │
        ▼
    Assistant / Brain / AI
        │
        ▼
    response / stream
        │
        ▼
    ChatView.update_assistant_message()
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any

from dashboard.chat_animation import (
    ChatAnimationManager,
    StreamController,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_PLACEHOLDER = "Message AssistantX..."
MAX_MESSAGE_LENGTH = 20_000
MAX_HISTORY_MESSAGES = 500

CHAT_BG = "#0f1117"
CHAT_SURFACE = "#171a21"
CHAT_USER_BG = "#2563eb"
CHAT_ASSISTANT_BG = "#20242d"
CHAT_TEXT = "#f5f7fa"
CHAT_MUTED = "#9ca3af"
CHAT_BORDER = "#2a2f3a"

SEND_BUTTON_TEXT = "Send"

USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"
SYSTEM_ROLE = "system"


# ============================================================================
# Exceptions
# ============================================================================

class ChatError(Exception):
    """Base exception for chat UI errors."""


class ChatConfigurationError(ChatError):
    """Raised when chat configuration is invalid."""


class ChatStateError(ChatError):
    """Raised when chat is used in an invalid state."""


# ============================================================================
# Enums
# ============================================================================

class MessageRole(str, Enum):
    """Supported chat message roles."""

    USER = USER_ROLE
    ASSISTANT = ASSISTANT_ROLE
    SYSTEM = SYSTEM_ROLE


class ChatState(str, Enum):
    """Chat lifecycle states."""

    IDLE = "idle"
    SENDING = "sending"
    STREAMING = "streaming"
    ERROR = "error"
    STOPPED = "stopped"


# ============================================================================
# Message Model
# ============================================================================

@dataclass(slots=True)
class ChatMessage:
    """Represents one chat message."""

    role: MessageRole
    content: str

    message_id: str = ""

    timestamp: str = field(
        default_factory=lambda:
        datetime.now(timezone.utc).isoformat()
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:

        self.content = str(self.content).strip()

        if not self.message_id:
            self.message_id = (
                f"{self.role.value}-"
                f"{int(datetime.now(timezone.utc).timestamp() * 1000000)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert message to a serializable dictionary."""

        return {
            "message_id": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Chat Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class ChatConfig:
    """Configuration for the chat interface."""

    background: str = CHAT_BG
    surface: str = CHAT_SURFACE

    user_background: str = CHAT_USER_BG
    assistant_background: str = CHAT_ASSISTANT_BG

    text_color: str = CHAT_TEXT
    muted_color: str = CHAT_MUTED
    border_color: str = CHAT_BORDER

    placeholder: str = DEFAULT_PLACEHOLDER

    max_message_length: int = MAX_MESSAGE_LENGTH
    max_history_messages: int = MAX_HISTORY_MESSAGES

    show_timestamps: bool = False

    enable_animations: bool = True
    enable_streaming: bool = True
    enable_typing_indicator: bool = True

    auto_scroll: bool = True

    font_family: str = "Segoe UI"
    font_size: int = 11

    user_font_weight: str = "normal"
    assistant_font_weight: str = "normal"

    spacing: int = 10

    def __post_init__(self) -> None:

        if self.max_message_length <= 0:
            raise ChatConfigurationError(
                "max_message_length must be greater than zero."
            )

        if self.max_history_messages <= 0:
            raise ChatConfigurationError(
                "max_history_messages must be greater than zero."
            )

        if self.font_size <= 0:
            raise ChatConfigurationError(
                "font_size must be greater than zero."
            )


# ============================================================================
# Chat Statistics
# ============================================================================

@dataclass(slots=True)
class ChatStats:
    """Runtime chat statistics."""

    user_messages: int = 0
    assistant_messages: int = 0
    system_messages: int = 0

    messages_sent: int = 0
    streams_started: int = 0
    streams_completed: int = 0

    errors: int = 0

    characters_received: int = 0


# ============================================================================
# Message Bubble
# ============================================================================

class ChatMessageBubble(tk.Frame):
    """
    Lightweight built-in message bubble.

    This keeps chat.py functional even before message_bubble.py
    is integrated.

    Later, this class can be replaced by dashboard.message_bubble.MessageBubble.
    """

    def __init__(
        self,
        master: tk.Misc,
        message: ChatMessage,
        *,
        config: ChatConfig,
        on_copy: Callable[[ChatMessage], None] | None = None,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            master,
            bg=config.background,
            **kwargs,
        )

        self.message = message
        self.config_data = config
        self._on_copy = on_copy

        self._build()

    def _build(self) -> None:

        is_user = (
            self.message.role == MessageRole.USER
        )

        bubble_background = (
            self.config_data.user_background
            if is_user
            else self.config_data.assistant_background
        )

        anchor = "e" if is_user else "w"

        outer = tk.Frame(
            self,
            bg=self.config_data.background,
        )

        outer.pack(
            fill="x",
            padx=14,
            pady=5,
        )

        bubble = tk.Frame(
            outer,
            bg=bubble_background,
            highlightthickness=1,
            highlightbackground=self.config_data.border_color,
        )

        bubble.pack(
            anchor=anchor,
            padx=4,
        )

        # ---------------------------------------------------------------
        # Role label
        # ---------------------------------------------------------------

        role_name = (
            "You"
            if is_user
            else "AssistantX"
        )

        role_label = tk.Label(
            bubble,
            text=role_name,
            bg=bubble_background,
            fg=self.config_data.muted_color,
            font=(
                self.config_data.font_family,
                max(8, self.config_data.font_size - 2),
                "bold",
            ),
            anchor="w",
        )

        role_label.pack(
            fill="x",
            padx=12,
            pady=(8, 2),
        )

        # ---------------------------------------------------------------
        # Message text
        # ---------------------------------------------------------------

        self.text_label = tk.Label(
            bubble,
            text=self.message.content,
            bg=bubble_background,
            fg=self.config_data.text_color,
            font=(
                self.config_data.font_family,
                self.config_data.font_size,
            ),
            justify="left",
            anchor="w",
            wraplength=700,
        )

        self.text_label.pack(
            fill="x",
            padx=12,
            pady=(2, 8),
        )

        # ---------------------------------------------------------------
        # Timestamp
        # ---------------------------------------------------------------

        if self.config_data.show_timestamps:

            timestamp = self._format_timestamp(
                self.message.timestamp
            )

            timestamp_label = tk.Label(
                bubble,
                text=timestamp,
                bg=bubble_background,
                fg=self.config_data.muted_color,
                font=(
                    self.config_data.font_family,
                    8,
                ),
                anchor="e",
            )

            timestamp_label.pack(
                fill="x",
                padx=12,
                pady=(0, 7),
            )

    @staticmethod
    def _format_timestamp(value: str) -> str:

        try:
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            return dt.astimezone().strftime(
                "%H:%M"
            )

        except (TypeError, ValueError, OverflowError):
            return ""

    def update_text(
        self,
        text: str,
    ) -> None:
        """Update message bubble text."""

        self.message.content = str(text)

        if hasattr(self, "text_label"):

            self.text_label.configure(
                text=self.message.content
            )


# ============================================================================
# Chat View
# ============================================================================

class ChatView(tk.Frame):
    """
    Main AssistantX chat interface.

    This widget can be embedded inside dashboard.window or app.py.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        config: ChatConfig | None = None,
        on_message: Callable[[str], Any] | None = None,
        on_stop: Callable[[], Any] | None = None,
        **kwargs: Any,
    ) -> None:

        self.config_data = config or ChatConfig()

        super().__init__(
            master,
            bg=self.config_data.background,
            **kwargs,
        )

        self._lock = RLock()

        self._state = ChatState.IDLE

        self._messages: list[ChatMessage] = []

        self._message_widgets: dict[
            str,
            ChatMessageBubble,
        ] = {}

        self._current_stream: StreamController | None = None

        self._current_assistant_message: ChatMessage | None = None

        self._typing_active = False

        self._on_message = on_message
        self._on_stop = on_stop

        self._stats = ChatStats()

        self._animation_manager = (
            ChatAnimationManager(self)
            if self.config_data.enable_animations
            else None
        )

        self._build_ui()

        self._bind_events()

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def state(self) -> ChatState:
        """Return current chat state."""

        with self._lock:
            return self._state

    @property
    def messages(self) -> list[ChatMessage]:
        """Return a copy of the current messages."""

        with self._lock:
            return list(self._messages)

    @property
    def is_streaming(self) -> bool:
        return self.state == ChatState.STREAMING

    # ========================================================================
    # UI Construction
    # ========================================================================

    def _build_ui(self) -> None:

        self._build_header()
        self._build_message_area()
        self._build_input_area()

    # ------------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------------

    def _build_header(self) -> None:

        self.header = tk.Frame(
            self,
            bg=self.config_data.surface,
            height=58,
            highlightthickness=1,
            highlightbackground=self.config_data.border_color,
        )

        self.header.pack(
            fill="x",
        )

        self.header.pack_propagate(False)

        title = tk.Label(
            self.header,
            text="AssistantX",
            bg=self.config_data.surface,
            fg=self.config_data.text_color,
            font=(
                self.config_data.font_family,
                14,
                "bold",
            ),
        )

        title.pack(
            side="left",
            padx=18,
            pady=10,
        )

        self.status_label = tk.Label(
            self.header,
            text="Ready",
            bg=self.config_data.surface,
            fg=self.config_data.muted_color,
            font=(
                self.config_data.font_family,
                9,
            ),
        )

        self.status_label.pack(
            side="right",
            padx=18,
        )

    # ------------------------------------------------------------------------
    # Message Area
    # ------------------------------------------------------------------------

    def _build_message_area(self) -> None:

        container = tk.Frame(
            self,
            bg=self.config_data.background,
        )

        container.pack(
            fill="both",
            expand=True,
        )

        self.canvas = tk.Canvas(
            container,
            bg=self.config_data.background,
            highlightthickness=0,
            bd=0,
        )

        scrollbar = tk.Scrollbar(
            container,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        scrollbar.pack(
            side="right",
            fill="y",
        )

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.message_container = tk.Frame(
            self.canvas,
            bg=self.config_data.background,
        )

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.message_container,
            anchor="nw",
        )

        self.message_container.bind(
            "<Configure>",
            self._on_message_container_configure,
        )

        self.canvas.bind(
            "<Configure>",
            self._on_canvas_configure,
        )

        self._bind_mousewheel()

    # ------------------------------------------------------------------------
    # Input Area
    # ------------------------------------------------------------------------

    def _build_input_area(self) -> None:

        self.input_container = tk.Frame(
            self,
            bg=self.config_data.surface,
            highlightthickness=1,
            highlightbackground=self.config_data.border_color,
        )

        self.input_container.pack(
            fill="x",
            padx=12,
            pady=12,
        )

        self.input_text = tk.Text(
            self.input_container,
            height=3,
            wrap="word",
            undo=True,
            bg=self.config_data.surface,
            fg=self.config_data.text_color,
            insertbackground=self.config_data.text_color,
            relief="flat",
            borderwidth=0,
            font=(
                self.config_data.font_family,
                self.config_data.font_size,
            ),
            padx=10,
            pady=8,
        )

        self.input_text.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.input_text.insert(
            "1.0",
            self.config_data.placeholder,
        )

        self.input_text.configure(
            fg=self.config_data.muted_color,
        )

        self.send_button = tk.Button(
            self.input_container,
            text=SEND_BUTTON_TEXT,
            command=self.send_current_message,
            bg=self.config_data.user_background,
            fg="#ffffff",
            activebackground=self.config_data.user_background,
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=(
                self.config_data.font_family,
                10,
                "bold",
            ),
            padx=16,
            pady=10,
        )

        self.send_button.pack(
            side="right",
            padx=8,
            pady=8,
        )

    # ========================================================================
    # Events
    # ========================================================================

    def _bind_events(self) -> None:

        self.input_text.bind(
            "<FocusIn>",
            self._on_input_focus_in,
        )

        self.input_text.bind(
            "<FocusOut>",
            self._on_input_focus_out,
        )

        self.input_text.bind(
            "<Return>",
            self._on_enter_pressed,
        )

        self.input_text.bind(
            "<Shift-Return>",
            self._on_shift_enter,
        )

    def _on_input_focus_in(
        self,
        _event: tk.Event,
    ) -> None:

        current = self.input_text.get(
            "1.0",
            "end-1c",
        )

        if current == self.config_data.placeholder:

            self.input_text.delete(
                "1.0",
                "end",
            )

            self.input_text.configure(
                fg=self.config_data.text_color,
            )

    def _on_input_focus_out(
        self,
        _event: tk.Event,
    ) -> None:

        current = self.input_text.get(
            "1.0",
            "end-1c",
        ).strip()

        if not current:

            self.input_text.delete(
                "1.0",
                "end",
            )

            self.input_text.insert(
                "1.0",
                self.config_data.placeholder,
            )

            self.input_text.configure(
                fg=self.config_data.muted_color,
            )

    def _on_enter_pressed(
        self,
        _event: tk.Event,
    ) -> str:

        self.send_current_message()

        return "break"

    def _on_shift_enter(
        self,
        _event: tk.Event,
    ) -> None:

        self.input_text.insert(
            "insert",
            "\n",
        )

    # ========================================================================
    # Mouse Wheel
    # ========================================================================

    def _bind_mousewheel(self) -> None:

        self.canvas.bind_all(
            "<MouseWheel>",
            self._on_mousewheel,
            add="+",
        )

    def _on_mousewheel(
        self,
        event: tk.Event,
    ) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units",
            )

    # ========================================================================
    # Layout
    # ========================================================================

    def _on_message_container_configure(
        self,
        _event: tk.Event,
    ) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )

    def _on_canvas_configure(
        self,
        event: tk.Event,
    ) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.itemconfigure(
                self.canvas_window,
                width=event.width,
            )

    # ========================================================================
    # Sending
    # ========================================================================

    def send_current_message(self) -> None:
        """Read input box and send a user message."""

        text = self.input_text.get(
            "1.0",
            "end-1c",
        ).strip()

        if not text:
            return

        if text == self.config_data.placeholder:
            return

        if len(text) > self.config_data.max_message_length:

            self.set_status(
                "Message is too long."
            )

            return

        if self.is_streaming:

            self.stop_stream()

            return

        self.input_text.delete(
            "1.0",
            "end",
        )

        self._add_message(
            MessageRole.USER,
            text,
        )

        with self._lock:
            self._state = ChatState.SENDING
            self._stats.messages_sent += 1

        self.set_status("Thinking...")

        try:

            if self._on_message:

                result = self._on_message(text)

                # -------------------------------------------------------
                # Optional synchronous response.
                # -------------------------------------------------------

                if isinstance(result, str) and result.strip():

                    self.add_assistant_message(
                        result
                    )

                elif result is not None:

                    self._handle_callback_result(
                        result
                    )

            else:

                logger.debug(
                    "No chat callback configured."
                )

        except Exception as exc:

            logger.exception(
                "Chat message callback failed."
            )

            self._stats.errors += 1

            self.show_error(
                f"Sorry, something went wrong: {exc}"
            )

    def _handle_callback_result(
        self,
        result: Any,
    ) -> None:
        """
        Handle common assistant callback return types.

        Supported:
            str
            dict with response/text/content
            iterable stream
        """

        if isinstance(result, dict):

            response = (
                result.get("response")
                or result.get("text")
                or result.get("content")
            )

            if response:

                self.add_assistant_message(
                    str(response)
                )

            return

        if hasattr(result, "__iter__") and not isinstance(
            result,
            (str, bytes, dict),
        ):

            self.start_stream()

            for chunk in result:

                if chunk is None:
                    continue

                self.append_stream_text(
                    str(chunk)
                )

            self.finish_stream()

    # ========================================================================
    # Message Management
    # ========================================================================

    def _add_message(
        self,
        role: MessageRole,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        """Add and render a message."""

        content = str(content).strip()

        if not content:
            raise ChatConfigurationError(
                "Message content cannot be empty."
            )

        if len(content) > self.config_data.max_message_length:

            content = content[
                :self.config_data.max_message_length
            ]

        message = ChatMessage(
            role=role,
            content=content,
            metadata=metadata or {},
        )

        with self._lock:

            self._messages.append(message)

            self._trim_history()

            if role == MessageRole.USER:
                self._stats.user_messages += 1

            elif role == MessageRole.ASSISTANT:
                self._stats.assistant_messages += 1

            elif role == MessageRole.SYSTEM:
                self._stats.system_messages += 1

        self._render_message(message)

        return message

    def add_user_message(
        self,
        content: str,
    ) -> ChatMessage:
        """Public helper for adding a user message."""

        return self._add_message(
            MessageRole.USER,
            content,
        )

    def add_assistant_message(
        self,
        content: str,
    ) -> ChatMessage:
        """Public helper for adding an assistant message."""

        message = self._add_message(
            MessageRole.ASSISTANT,
            content,
        )

        with self._lock:
            self._state = ChatState.IDLE

        self.set_status("Ready")

        return message

    def add_system_message(
        self,
        content: str,
    ) -> ChatMessage:
        """Add a system message."""

        return self._add_message(
            MessageRole.SYSTEM,
            content,
        )

    # ========================================================================
    # Rendering
    # ========================================================================

    def _render_message(
        self,
        message: ChatMessage,
    ) -> ChatMessageBubble:
        """Render a message bubble."""

        bubble = ChatMessageBubble(
            self.message_container,
            message,
            config=self.config_data,
        )

        bubble.pack(
            fill="x",
            expand=True,
        )

        self._message_widgets[
            message.message_id
        ] = bubble

        self.update_idletasks()

        if (
            self.config_data.auto_scroll
            and self.winfo_exists()
        ):
            self.after_idle(
                self.scroll_to_bottom
            )

        # ---------------------------------------------------------------
        # Entrance animation
        # ---------------------------------------------------------------

        if self._animation_manager:

            self._animation_manager.message_enter(
                bubble,
            )

        return bubble

    # ========================================================================
    # Streaming
    # ========================================================================

    def start_stream(
        self,
        *,
        message_id: str | None = None,
    ) -> ChatMessage:
        """
        Start an assistant streaming response.

        If message_id is not provided, a new empty assistant message
        is created.
        """

        if self.is_streaming:

            raise ChatStateError(
                "A stream is already active."
            )

        if message_id:

            message = self._find_message(
                message_id
            )

            if message is None:
                raise ChatStateError(
                    f"Unknown message: {message_id}"
                )

            self._current_assistant_message = message

        else:

            message = self._add_message(
                MessageRole.ASSISTANT,
                "",
            )

            self._current_assistant_message = message

        with self._lock:

            self._state = ChatState.STREAMING

            self._stats.streams_started += 1

        self.set_status("AssistantX is typing...")

        return self._current_assistant_message

    def append_stream_text(
        self,
        text: str,
    ) -> None:
        """Append text to the current assistant response."""

        if not text:
            return

        if self._current_assistant_message is None:

            self.start_stream()

        message = self._current_assistant_message

        if message is None:
            return

        new_content = (
            message.content
            + str(text)
        )

        if len(new_content) > self.config_data.max_message_length:

            new_content = new_content[
                :self.config_data.max_message_length
            ]

        message.content = new_content

        self._stats.characters_received += len(
            str(text)
        )

        self._update_message_widget(
            message
        )

        if self.config_data.auto_scroll:

            self.after_idle(
                self.scroll_to_bottom
            )

    def update_stream_text(
        self,
        text: str,
    ) -> None:
        """Replace the current streamed assistant response."""

        if self._current_assistant_message is None:
            self.start_stream()

        message = self._current_assistant_message

        if message is None:
            return

        message.content = str(text)[
            :self.config_data.max_message_length
        ]

        self._update_message_widget(
            message
        )

        if self.config_data.auto_scroll:

            self.after_idle(
                self.scroll_to_bottom
            )

    def finish_stream(self) -> None:
        """Finish the active assistant stream."""

        if self._current_stream:

            self._current_stream.cancel()

            self._current_stream = None

        self._current_assistant_message = None

        with self._lock:

            self._state = ChatState.IDLE

            self._stats.streams_completed += 1

        self.set_status("Ready")

    def stop_stream(self) -> None:
        """Stop the current stream."""

        if self._current_stream:

            self._current_stream.cancel()

            self._current_stream = None

        self._current_assistant_message = None

        with self._lock:
            self._state = ChatState.IDLE

        self.set_status("Ready")

        if self._on_stop:

            try:
                self._on_stop()
            except Exception:
                logger.exception(
                    "Chat stop callback failed."
                )

    # ========================================================================
    # Animated Text Streaming
    # ========================================================================

    def animate_response(
        self,
        text: str,
        *,
        interval: int | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """
        Display an assistant response with character streaming animation.
        """

        message = self.start_stream()

        if not self._animation_manager:

            self.update_stream_text(text)
            self.finish_stream()

            if on_complete:
                on_complete()

            return

        bubble = self._message_widgets.get(
            message.message_id
        )

        if bubble is None:

            self.update_stream_text(text)
            self.finish_stream()

            return

        def update(value: str) -> None:

            self.update_stream_text(
                value
            )

        def completed() -> None:

            self.finish_stream()

            if on_complete:
                on_complete()

        self._current_stream = (
            self._animation_manager.stream_text(
                bubble,
                text,
                interval=interval,
                callback=update,
                on_complete=completed,
            )
        )

    # ========================================================================
    # Typing Indicator
    # ========================================================================

    def show_typing(
        self,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        """Show animated typing indicator in status bar."""

        if self._typing_active:
            return

        self._typing_active = True

        self.set_status(
            "AssistantX is typing..."
        )

        if not self._animation_manager:
            return

        def update(dots: str) -> None:

            if self._typing_active:

                self.set_status(
                    f"AssistantX is typing{dots}"
                )

                if callback:
                    callback(dots)

        self._typing_handle = (
            self._animation_manager.typing_indicator(
                self,
                callback=update,
            )
        )

    def hide_typing(self) -> None:
        """Hide typing indicator."""

        self._typing_active = False

        handle = getattr(
            self,
            "_typing_handle",
            None,
        )

        if handle and self._animation_manager:

            self._animation_manager.cancel(
                handle
            )

        self.set_status("Ready")

    # ========================================================================
    # Message Update
    # ========================================================================

    def _update_message_widget(
        self,
        message: ChatMessage,
    ) -> None:
        """Update an existing message bubble."""

        bubble = self._message_widgets.get(
            message.message_id
        )

        if bubble is None:
            return

        try:

            bubble.update_text(
                message.content
            )

        except tk.TclError:
            return

    # ========================================================================
    # Message Lookup
    # ========================================================================

    def _find_message(
        self,
        message_id: str,
    ) -> ChatMessage | None:

        with self._lock:

            for message in self._messages:

                if message.message_id == message_id:
                    return message

        return None

    # ========================================================================
    # History
    # ========================================================================

    def _trim_history(self) -> None:

        limit = self.config_data.max_history_messages

        if len(self._messages) <= limit:
            return

        removed = self._messages[
            :len(self._messages) - limit
        ]

        self._messages = self._messages[
            -limit:
        ]

        for message in removed:

            widget = self._message_widgets.pop(
                message.message_id,
                None,
            )

            if widget:

                with contextlib.suppress(tk.TclError):
                    widget.destroy()

    def get_history(
        self,
    ) -> list[dict[str, Any]]:
        """Return serializable chat history."""

        with self._lock:

            return [
                message.to_dict()
                for message in self._messages
            ]

    def load_history(
        self,
        messages: list[dict[str, Any]],
        *,
        clear_existing: bool = True,
    ) -> None:
        """Load chat history into the UI."""

        if not isinstance(messages, list):
            raise ChatConfigurationError(
                "messages must be a list."
            )

        if clear_existing:
            self.clear()

        for item in messages:

            if not isinstance(item, dict):
                continue

            role_value = item.get("role")
            content = item.get("content", "")

            try:
                role = MessageRole(
                    role_value
                )
            except ValueError:
                continue

            if not content:
                continue

            self._add_message(
                role,
                str(content),
                metadata=item.get(
                    "metadata",
                    {},
                ),
            )

    # ========================================================================
    # Clear
    # ========================================================================

    def clear(self) -> None:
        """Clear all messages."""

        self.stop_stream()
        self.hide_typing()

        with self._lock:
            messages = list(self._messages)
            self._messages.clear()

        for message in messages:

            widget = self._message_widgets.pop(
                message.message_id,
                None,
            )

            if widget:

                with contextlib.suppress(tk.TclError):
                    widget.destroy()

        self.set_status("Ready")

    # ========================================================================
    # Error
    # ========================================================================

    def show_error(
        self,
        message: str,
    ) -> None:
        """Display an error as a system-style assistant message."""

        with self._lock:
            self._state = ChatState.ERROR

        self._add_message(
            MessageRole.SYSTEM,
            message,
            metadata={
                "error": True,
            },
        )

        self.set_status(
            "Something went wrong."
        )

    # ========================================================================
    # Status
    # ========================================================================

    def set_status(
        self,
        text: str,
    ) -> None:
        """Update chat status safely."""

        with contextlib.suppress(tk.TclError):
            self.status_label.configure(
                text=str(text)
            )

    # ========================================================================
    # Scroll
    # ========================================================================

    def scroll_to_bottom(self) -> None:
        """Scroll chat to the newest message."""

        try:

            self.canvas.update_idletasks()

            self.canvas.yview_moveto(
                1.0
            )

        except tk.TclError:
            pass

    # ========================================================================
    # Export
    # ========================================================================

    def export_text(self) -> str:
        """Export the current conversation as plain text."""

        lines: list[str] = []

        with self._lock:
            messages = list(self._messages)

        for message in messages:

            if message.role == MessageRole.USER:
                name = "You"

            elif message.role == MessageRole.ASSISTANT:
                name = "AssistantX"

            else:
                name = "System"

            lines.append(
                f"{name}: {message.content}"
            )

        return "\n\n".join(lines)

    # ========================================================================
    # Statistics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """Return safe runtime diagnostics."""

        with self._lock:

            return {
                "state": self._state.value,
                "message_count": len(
                    self._messages
                ),
                "streaming": self.is_streaming,
                "typing_active": self._typing_active,

                "statistics": {
                    "user_messages":
                        self._stats.user_messages,

                    "assistant_messages":
                        self._stats.assistant_messages,

                    "system_messages":
                        self._stats.system_messages,

                    "messages_sent":
                        self._stats.messages_sent,

                    "streams_started":
                        self._stats.streams_started,

                    "streams_completed":
                        self._stats.streams_completed,

                    "errors":
                        self._stats.errors,

                    "characters_received":
                        self._stats.characters_received,
                },

                "configuration": {
                    "animations":
                        self.config_data.enable_animations,

                    "streaming":
                        self.config_data.enable_streaming,

                    "auto_scroll":
                        self.config_data.auto_scroll,

                    "history_limit":
                        self.config_data.max_history_messages,
                },
            }

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(self) -> None:
        """Release chat resources."""

        self.stop_stream()
        self.hide_typing()

        if self._animation_manager:

            self._animation_manager.shutdown()

        try:
            self.canvas.unbind_all(
                "<MouseWheel>"
            )
        except tk.TclError:
            logger.debug(
                "Unable to unbind the chat mouse-wheel handler.",
                exc_info=True,
            )

        with self._lock:
            self._state = ChatState.STOPPED

    # ========================================================================
    # Destructor Safety
    # ========================================================================

    def destroy(self) -> None:
        """Safely destroy the chat widget."""

        try:
            self.shutdown()
        except Exception:
            logger.exception(
                "Chat shutdown failed during destroy."
            )

        super().destroy()


# ============================================================================
# Factory
# ============================================================================

def create_chat(
    master: tk.Misc,
    *,
    config: ChatConfig | None = None,
    on_message: Callable[[str], Any] | None = None,
    on_stop: Callable[[], Any] | None = None,
) -> ChatView:
    """Create a configured AssistantX chat view."""

    return ChatView(
        master,
        config=config,
        on_message=on_message,
        on_stop=on_stop,
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "ChatConfig",
    "ChatConfigurationError",
    "ChatError",
    "ChatMessage",
    "ChatMessageBubble",
    "ChatState",
    "ChatStateError",
    "ChatStats",
    "ChatView",
    "MessageRole",
    "create_chat",
]
