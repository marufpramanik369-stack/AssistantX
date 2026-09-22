"""
core/history.py
===============

AssistantX Conversation History Manager.

Responsibilities
----------------
- Store the active conversation transcript.
- Persist recent conversation history to JSON.
- Keep the active history within a configurable limit.
- Provide LLM/provider-ready message formatting.
- Search recent conversation messages.
- Manage conversation sessions.
- Export transcripts.
- Integrate with the AssistantX event bus.
- Remain thread-safe and resilient to invalid persisted data.

History vs Memory
-----------------
History:
    Raw chronological conversation messages.

Memory:
    Distilled long-term facts/preferences extracted from conversations.

JSON is the source of truth for active/recent conversation context.
The database layer may optionally be used elsewhere for long-term
conversation querying/archiving.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from config.constants import HISTORY_JSON, MAX_HISTORY_MESSAGES
from core.event_bus import Events, event_bus
from core.logger import get_logger
from core.utils import (
    iso_timestamp,
    normalize_text,
    read_json,
    write_json,
)

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

HISTORY_SCHEMA_VERSION = 1

DEFAULT_MAX_MESSAGES = MAX_HISTORY_MESSAGES

DEFAULT_SEARCH_LIMIT = 50

MAX_MESSAGE_LENGTH = 100_000


# ============================================================================
# Exceptions
# ============================================================================


class HistoryError(Exception):
    """Base exception for conversation history errors."""


class HistoryValidationError(HistoryError):
    """Raised when history input is invalid."""


class MessageNotFoundError(HistoryError):
    """Raised when a requested message does not exist."""


# ============================================================================
# Message Roles
# ============================================================================


class Role(str, Enum):
    """Supported conversation roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ============================================================================
# Message Model
# ============================================================================


@dataclass
class Message:
    """
    Represents a single conversation message.
    """

    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    role: Role = Role.USER

    content: str = ""

    timestamp: str = field(
        default_factory=iso_timestamp
    )

    # Optional classified intent.
    intent: str | None = None

    # Additional metadata such as:
    # {
    #     "model": "gemini",
    #     "source": "voice",
    #     "latency_ms": 1200
    # }
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Convert message into a JSON-compatible dictionary."""

        data = asdict(self)

        data["role"] = self.role.value

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> Message:
        """
        Restore a Message from persisted JSON data.

        Invalid records raise HistoryValidationError so the caller
        can safely skip the corrupted record.
        """

        if not isinstance(data, dict):
            raise HistoryValidationError(
                "Message data must be a dictionary."
            )

        try:
            role = Role(
                str(
                    data.get(
                        "role",
                        Role.USER.value,
                    )
                ).lower()
            )
        except ValueError as exc:
            raise HistoryValidationError(
                f"Invalid message role: "
                f"{data.get('role')!r}"
            ) from exc

        content = str(
            data.get(
                "content",
                "",
            )
        ).strip()

        if not content:
            raise HistoryValidationError(
                "Message content cannot be empty."
            )

        metadata = data.get(
            "metadata",
            {},
        )

        if not isinstance(metadata, dict):
            metadata = {}

        return cls(
            id=str(
                data.get("id")
                or uuid.uuid4()
            ),
            role=role,
            content=content,
            timestamp=str(
                data.get("timestamp")
                or iso_timestamp()
            ),
            intent=(
                str(data["intent"]).strip()
                if data.get("intent") is not None
                else None
            ),
            metadata=metadata,
        )

    # --------------------------------------------------------------------- #
    # Provider Formatting
    # --------------------------------------------------------------------- #

    def to_provider_format(
        self,
    ) -> dict[str, str]:
        """
        Return the standard role/content structure expected by most
        LLM chat APIs.
        """

        return {
            "role": self.role.value,
            "content": self.content,
        }


# ============================================================================
# Validation Helpers
# ============================================================================


def _normalize_role(
    role: Role | str,
) -> Role:
    """Normalize and validate message role."""

    if isinstance(role, Role):
        return role

    try:
        return Role(
            str(role).strip().lower()
        )
    except ValueError as exc:
        raise HistoryValidationError(
            f"Invalid message role: {role!r}. "
            f"Valid roles: "
            f"{', '.join(role.value for role in Role)}"
        ) from exc


def _validate_content(
    content: str,
) -> str:
    """Validate message content."""

    content = str(content).strip()

    if not content:
        raise HistoryValidationError(
            "Message content cannot be empty."
        )

    if len(content) > MAX_MESSAGE_LENGTH:
        raise HistoryValidationError(
            f"Message is too long. "
            f"Maximum length is {MAX_MESSAGE_LENGTH:,} characters."
        )

    return content


def _normalize_intent(
    intent: str | None,
) -> str | None:
    """Normalize optional intent."""

    if intent is None:
        return None

    intent = str(intent).strip()

    return intent or None


# ============================================================================
# History Manager
# ============================================================================


class HistoryManager:
    """
    Thread-safe manager for the active AssistantX conversation.

    A HistoryManager instance represents one active conversation session.
    """

    def __init__(
        self,
        path: Path = HISTORY_JSON,
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:

        self._path = Path(path)

        try:
            max_messages = int(max_messages)
        except (TypeError, ValueError) as exc:
            raise HistoryValidationError(
                "max_messages must be an integer."
            ) from exc

        if max_messages <= 0:
            raise HistoryValidationError(
                "max_messages must be greater than zero."
            )

        self._max_messages = max_messages

        self._lock = threading.RLock()

        self._messages: list[Message] = []

        self.session_id: str = self._new_session_id()

        self._loaded = False

        self.load()

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    @staticmethod
    def _new_session_id() -> str:
        """Generate a new conversation session ID."""

        return str(uuid.uuid4())

    def _emit(
        self,
        event: str,
        payload: Any,
    ) -> None:
        """Safely emit an event without breaking history operations."""

        try:
            event_bus.emit(
                event,
                payload,
            )
        except Exception:
            logger.exception(
                "Failed to emit history event: %s",
                event,
            )

    def _trim(self) -> int:
        """
        Trim old messages from active history.

        Returns:
            Number of removed messages.
        """

        if len(self._messages) <= self._max_messages:
            return 0

        overflow = (
            len(self._messages)
            - self._max_messages
        )

        del self._messages[:overflow]

        return overflow

    # ========================================================================
    # Add Messages
    # ========================================================================

    def add(
        self,
        role: Role | str,
        content: str,
        intent: str | None = None,
        **metadata: Any,
    ) -> Message:
        """
        Append a message to the active transcript.

        The message is persisted immediately and the HISTORY_APPENDED
        event is emitted after successful persistence.
        """

        normalized_role = _normalize_role(role)

        normalized_content = _validate_content(
            content
        )

        normalized_intent = _normalize_intent(
            intent
        )

        message = Message(
            role=normalized_role,
            content=normalized_content,
            intent=normalized_intent,
            metadata=dict(metadata),
        )

        with self._lock:

            self._messages.append(
                message
            )

            removed = self._trim()

            if removed:
                logger.debug(
                    "Trimmed %d old message(s) "
                    "from active history.",
                    removed,
                )

            if not self.save():
                logger.warning(
                    "Message added to memory but "
                    "history persistence failed."
                )

        self._emit(
            Events.HISTORY_APPENDED,
            message.to_dict(),
        )

        logger.debug(
            "History += [%s] %s",
            normalized_role.value,
            normalized_content[:120],
        )

        return message

    def add_user_message(
        self,
        content: str,
        **metadata: Any,
    ) -> Message:
        """Add a user message."""

        return self.add(
            Role.USER,
            content,
            **metadata,
        )

    def add_assistant_message(
        self,
        content: str,
        intent: str | None = None,
        **metadata: Any,
    ) -> Message:
        """Add an AssistantX response."""

        return self.add(
            Role.ASSISTANT,
            content,
            intent=intent,
            **metadata,
        )

    def add_system_message(
        self,
        content: str,
        **metadata: Any,
    ) -> Message:
        """Add a system message."""

        return self.add(
            Role.SYSTEM,
            content,
            **metadata,
        )

    # ========================================================================
    # Remove / Clear
    # ========================================================================

    def remove(
        self,
        message_id: str,
    ) -> bool:
        """
        Remove a single message by ID.

        Returns:
            True if removed, otherwise False.
        """

        message_id = str(
            message_id
        ).strip()

        if not message_id:
            return False

        with self._lock:

            for index, message in enumerate(
                self._messages
            ):

                if message.id == message_id:

                    removed = self._messages.pop(
                        index
                    )

                    self.save()

                    logger.debug(
                        "Removed history message: %s",
                        removed.id,
                    )

                    return True

        return False

    def clear(
        self,
        start_new_session: bool = True,
    ) -> None:
        """
        Clear the active conversation.

        Args:
            start_new_session:
                Generate a fresh session ID after clearing.
        """

        with self._lock:

            old_session_id = self.session_id

            self._messages.clear()

            if start_new_session:
                self.session_id = (
                    self._new_session_id()
                )

            self.save()

            payload = {
                "session_id": self.session_id,
                "previous_session_id": old_session_id,
            }

        self._emit(
            Events.HISTORY_CLEARED,
            payload,
        )

        logger.info(
            "Conversation history cleared "
            "(session=%s).",
            self.session_id,
        )

    # ========================================================================
    # Session Management
    # ========================================================================

    def new_session(
        self,
        *,
        clear_history: bool = True,
    ) -> str:
        """
        Start a new conversation session.

        Returns:
            New session ID.
        """

        with self._lock:

            old_session_id = self.session_id

            self.session_id = (
                self._new_session_id()
            )

            if clear_history:
                self._messages.clear()

            self.save()

            new_session_id = self.session_id

        logger.info(
            "New conversation session created: "
            "%s -> %s",
            old_session_id,
            new_session_id,
        )

        if clear_history:

            self._emit(
                Events.HISTORY_CLEARED,
                {
                    "session_id": new_session_id,
                    "previous_session_id": old_session_id,
                },
            )

        return new_session_id

    # ========================================================================
    # Access
    # ========================================================================

    def all(self) -> list[Message]:
        """Return a snapshot of all active messages."""

        with self._lock:
            return list(self._messages)

    def get(
        self,
        message_id: str,
    ) -> Message | None:
        """Get one message by ID."""

        message_id = str(
            message_id
        ).strip()

        with self._lock:

            for message in self._messages:

                if message.id == message_id:
                    return message

        return None

    def last(
        self,
        n: int = 1,
    ) -> list[Message]:
        """
        Return the last N messages.

        Negative/zero values return an empty list.
        """

        try:
            n = int(n)
        except (TypeError, ValueError):
            return []

        if n <= 0:
            return []

        with self._lock:
            return list(
                self._messages[-n:]
            )

    def last_user_message(
        self,
    ) -> Message | None:
        """Return the most recent user message."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if message.role == Role.USER:
                    return message

        return None

    def last_assistant_message(
        self,
    ) -> Message | None:
        """Return the most recent AssistantX response."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if (
                    message.role
                    == Role.ASSISTANT
                ):
                    return message

        return None

    # ========================================================================
    # Provider Context
    # ========================================================================

    def as_provider_messages(
        self,
        limit: int | None = None,
        *,
        include_system: bool = True,
    ) -> list[dict[str, str]]:
        """
        Return history in LLM provider format.

        Args:
            limit:
                Maximum number of recent messages.

            include_system:
                Whether system messages should be included.
        """

        with self._lock:

            if limit is None:
                messages = list(
                    self._messages
                )

            else:

                try:
                    limit = int(limit)
                except (TypeError, ValueError):
                    limit = len(
                        self._messages
                    )

                if limit <= 0:
                    return []

                messages = list(
                    self._messages[-limit:]
                )

        if not include_system:

            messages = [
                message
                for message in messages
                if message.role
                != Role.SYSTEM
            ]

        return [
            message.to_provider_format()
            for message in messages
        ]

    def context_text(
        self,
        limit: int | None = None,
    ) -> str:
        """
        Return a human-readable conversation context.

        Useful for local AI or debugging.
        """

        messages = self.last(
            limit
            if limit is not None
            else self._max_messages
        )

        lines: list[str] = []

        for message in messages:

            if message.role == Role.USER:
                speaker = "User"

            elif message.role == Role.ASSISTANT:
                speaker = "AssistantX"

            else:
                speaker = "System"

            lines.append(
                f"{speaker}: {message.content}"
            )

        return "\n".join(lines)

    # ========================================================================
    # Search
    # ========================================================================

    def search(
        self,
        query: str,
        *,
        role: Role | str | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        """
        Search active history.

        Search is case-insensitive and whitespace normalized.
        """

        query_normalized = normalize_text(
            query
        )

        if not query_normalized:
            return []

        normalized_role = (
            _normalize_role(role)
            if role is not None
            else None
        )

        with self._lock:

            results = []

            for message in self._messages:

                if (
                    normalized_role is not None
                    and message.role
                    != normalized_role
                ):
                    continue

                content = normalize_text(
                    message.content
                )

                if query_normalized in content:
                    results.append(message)

        if limit is not None:

            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = DEFAULT_SEARCH_LIMIT

            if limit <= 0:
                return []

            results = results[:limit]

        return results

    # ========================================================================
    # Counts / Statistics
    # ========================================================================

    def count(
        self,
        role: Role | str | None = None,
    ) -> int:
        """Return message count, optionally filtered by role."""

        if role is None:

            with self._lock:
                return len(
                    self._messages
                )

        normalized_role = _normalize_role(
            role
        )

        with self._lock:

            return sum(
                1
                for message in self._messages
                if message.role
                == normalized_role
            )

    def is_empty(self) -> bool:
        """Return True when the current transcript is empty."""

        return self.count() == 0

    def stats(self) -> dict[str, Any]:
        """Return conversation statistics."""

        with self._lock:

            messages = list(
                self._messages
            )

            return {
                "session_id": self.session_id,
                "total": len(messages),
                "user": sum(
                    1
                    for m in messages
                    if m.role == Role.USER
                ),
                "assistant": sum(
                    1
                    for m in messages
                    if m.role == Role.ASSISTANT
                ),
                "system": sum(
                    1
                    for m in messages
                    if m.role == Role.SYSTEM
                ),
                "max_messages": self._max_messages,
                "loaded": self._loaded,
                "path": str(self._path),
                "schema_version": HISTORY_SCHEMA_VERSION,
            }

    # ========================================================================
    # Persistence
    # ========================================================================

    def load(self) -> None:
        """
        Load active history from JSON.

        Invalid messages are skipped rather than crashing AssistantX.
        """

        try:

            raw = read_json(
                self._path,
                default={
                    "schema_version": HISTORY_SCHEMA_VERSION,
                    "session_id": self.session_id,
                    "messages": [],
                },
            )

            if not isinstance(raw, dict):

                logger.warning(
                    "History file contains invalid root data."
                )

                raw = {}

            session_id = str(
                raw.get(
                    "session_id",
                    self.session_id,
                )
            ).strip()

            loaded_session_id = session_id or self.session_id

            raw_messages = raw.get(
                "messages",
                [],
            )

            if not isinstance(
                raw_messages,
                list,
            ):

                logger.warning(
                    "History 'messages' field "
                    "is not a list."
                )

                raw_messages = []

            messages: list[Message] = []

            for item in raw_messages:

                try:

                    message = Message.from_dict(
                        item
                    )

                    messages.append(
                        message
                    )

                except HistoryValidationError as exc:

                    logger.warning(
                        "Skipping invalid history "
                        "message: %s",
                        exc,
                    )

            with self._lock:

                self.session_id = (
                    loaded_session_id
                )

                self._messages = messages

                removed = self._trim()

                self._loaded = True

            if removed:

                logger.debug(
                    "Trimmed %d old message(s) "
                    "after history load.",
                    removed,
                )

            logger.info(
                "Loaded %d historical "
                "message(s) from %s.",
                len(messages),
                self._path,
            )

        except Exception:

            logger.exception(
                "Failed to load conversation "
                "history from %s.",
                self._path,
            )

            with self._lock:

                self._messages = []

                self._loaded = True

    def save(self) -> bool:
        """
        Persist the active transcript to JSON.

        Returns:
            True on success, False on failure.
        """

        with self._lock:

            payload = {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "session_id": self.session_id,
                "updated_at": iso_timestamp(),
                "messages": [
                    message.to_dict()
                    for message in self._messages
                ],
            }

            try:

                result = write_json(
                    self._path,
                    payload,
                )

                if result is False:

                    logger.error(
                        "Failed to persist "
                        "conversation history to %s.",
                        self._path,
                    )

                    return False

                return True

            except Exception:

                logger.exception(
                    "Failed to persist "
                    "conversation history to %s.",
                    self._path,
                )

                return False

    def reload(self) -> None:
        """Reload history from disk."""

        self.load()

    # ========================================================================
    # Export
    # ========================================================================

    def export_transcript(
        self,
        path: Path,
        *,
        include_metadata: bool = False,
    ) -> bool:
        """
        Export the current session as plain text.

        Returns:
            True on success, False on failure.
        """

        path = Path(path)

        messages = self.all()

        lines: list[str] = []

        for message in messages:

            if message.role == Role.USER:
                speaker = "You"

            elif message.role == Role.ASSISTANT:
                speaker = "AssistantX"

            else:
                speaker = "System"

            lines.append(
                f"[{message.timestamp}] "
                f"{speaker}: "
                f"{message.content}"
            )

            if (
                include_metadata
                and message.metadata
            ):

                lines.append(
                    f"    Metadata: "
                    f"{message.metadata}"
                )

        try:

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            path.write_text(
                "\n".join(lines),
                encoding="utf-8",
            )

            logger.info(
                "Transcript exported to %s.",
                path,
            )

            return True

        except OSError:

            logger.exception(
                "Failed to export transcript "
                "to %s.",
                path,
            )

            return False

    # ========================================================================
    # Configuration
    # ========================================================================

    @property
    def max_messages(self) -> int:
        """Return maximum active history size."""

        return self._max_messages

    def set_max_messages(
        self,
        max_messages: int,
    ) -> None:
        """
        Change the active history limit.

        Existing history is immediately trimmed if necessary.
        """

        try:
            max_messages = int(
                max_messages
            )
        except (TypeError, ValueError) as exc:

            raise HistoryValidationError(
                "max_messages must be an integer."
            ) from exc

        if max_messages <= 0:
            raise HistoryValidationError(
                "max_messages must be greater than zero."
            )

        with self._lock:

            self._max_messages = max_messages

            removed = self._trim()

            if removed:
                self.save()

        logger.info(
            "Maximum active history changed "
            "to %d.",
            max_messages,
        )

    @property
    def path(self) -> Path:
        """Return history persistence path."""

        return self._path

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information."""

        with self._lock:

            return {
                "module": "core.history",
                "status": "ok",
                "loaded": self._loaded,
                "session_id": self.session_id,
                "message_count": len(
                    self._messages
                ),
                "max_messages": self._max_messages,
                "path": str(self._path),
                "file_exists": self._path.exists(),
                "schema_version": HISTORY_SCHEMA_VERSION,
            }


# ============================================================================
# Global History Manager
# ============================================================================


history_manager = HistoryManager()


# ============================================================================
# Convenience Functions
# ============================================================================


def add_user_message(
    content: str,
    **metadata: Any,
) -> Message:
    """Global helper for adding a user message."""

    return history_manager.add_user_message(
        content,
        **metadata,
    )


def add_assistant_message(
    content: str,
    intent: str | None = None,
    **metadata: Any,
) -> Message:
    """Global helper for adding an AssistantX response."""

    return history_manager.add_assistant_message(
        content,
        intent=intent,
        **metadata,
    )


def add_system_message(
    content: str,
    **metadata: Any,
) -> Message:
    """Global helper for adding a system message."""

    return history_manager.add_system_message(
        content,
        **metadata,
    )


def get_history(
    limit: int | None = None,
) -> list[Message]:
    """Return recent conversation messages."""

    if limit is None:
        return history_manager.all()

    return history_manager.last(limit)


def get_provider_history(
    limit: int | None = None,
) -> list[dict[str, str]]:
    """Return history formatted for an AI provider."""

    return history_manager.as_provider_messages(
        limit
    )


def search_history(
    query: str,
    limit: int | None = None,
) -> list[Message]:
    """Search active conversation history."""

    return history_manager.search(
        query,
        limit=limit,
    )


def clear_history(
    start_new_session: bool = True,
) -> None:
    """Clear the active conversation."""

    history_manager.clear(
        start_new_session=start_new_session
    )


def new_session() -> str:
    """Start a fresh conversation session."""

    return history_manager.new_session()


def history_count() -> int:
    """Return active message count."""

    return history_manager.count()


def history_diagnostics() -> dict[str, Any]:
    """Return global history diagnostics."""

    return history_manager.diagnostics()


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "DEFAULT_MAX_MESSAGES",
    "DEFAULT_SEARCH_LIMIT",
    # Constants
    "HISTORY_SCHEMA_VERSION",
    "MAX_MESSAGE_LENGTH",
    # Exceptions
    "HistoryError",
    # Manager
    "HistoryManager",
    "HistoryValidationError",
    "Message",
    "MessageNotFoundError",
    # Models
    "Role",
    "add_assistant_message",
    "add_system_message",
    # Helpers
    "add_user_message",
    "clear_history",
    "get_history",
    "get_provider_history",
    "history_count",
    "history_diagnostics",
    "history_manager",
    "new_session",
    "search_history",
]
