"""
core/history.py — Production-Grade Conversation History Manager
================================================================

Thread-safe, JSON-persisted conversation history for AssistantX / JEROX.

Responsibilities
----------------
    • Persist chronological conversation history
    • Track sessions and turns
    • Support text, voice, and UI input sources
    • Preserve voice recognition metadata
    • Provide provider-ready message formatting
    • Search and filter conversation history
    • Emit history events through the central EventBus
    • Provide diagnostics and export functionality
    • Remain independent from the voice package

Architecture
------------

    voice/
        recognizer.py
        wake_word.py
        voice_commands.py
             │
             │ recognized transcript + metadata
             ▼
    core/history.py
             │
             ├── JSON persistence
             ├── EventBus
             ├── Assistant
             └── future memory.py

Important
---------
History does NOT import voice modules.

Voice integration happens through explicit metadata:

    history_manager.add_voice_user_message(
        "open calculator",
        confidence=0.94,
        language="en",
        engine="speech_recognition",
        wake_word="jerox",
        turn_id="...",
    )

This avoids circular imports while keeping the complete voice context
available for memory, analytics, debugging, and future learning systems.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

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

HISTORY_SCHEMA_VERSION = 2

DEFAULT_MAX_MESSAGES = MAX_HISTORY_MESSAGES
DEFAULT_SEARCH_LIMIT = 50

MAX_MESSAGE_LENGTH = 100_000

MIN_MAX_MESSAGES = 1
MAX_MAX_MESSAGES = 100_000

SUPPORTED_INPUT_SOURCES = (
    "text",
    "voice",
    "ui",
    "system",
    "automation",
    "api",
)

SUPPORTED_VOICE_LANGUAGES = (
    "bn",
    "en",
    "hi",
)


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
# Roles
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
    Represents one conversation message.

    Voice example
    -------------
    Message(
        role=Role.USER,
        content="open calculator",
        metadata={
            "source": "voice",
            "input_mode": "voice",
            "confidence": 0.94,
            "language": "en",
            "engine": "speech_recognition",
            "wake_word": "jerox",
        },
    )
    """

    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    role: Role = Role.USER

    content: str = ""

    timestamp: str = field(
        default_factory=iso_timestamp
    )

    intent: Optional[str] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        data = asdict(self)

        data["role"] = self.role.value

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "Message":
        """
        Restore a Message from persisted data.

        Invalid records raise HistoryValidationError.
        """

        if not isinstance(data, dict):
            raise HistoryValidationError(
                f"Message must be dict, got {type(data).__name__}"
            )

        raw_role = data.get(
            "role",
            Role.USER.value,
        )

        try:
            role = Role(
                str(raw_role).strip().lower()
            )
        except ValueError as exc:
            raise HistoryValidationError(
                f"Invalid message role: {raw_role!r}"
            ) from exc

        content = str(
            data.get("content", "")
        ).strip()

        if not content:
            raise HistoryValidationError(
                "Message content cannot be empty"
            )

        if len(content) > MAX_MESSAGE_LENGTH:
            raise HistoryValidationError(
                f"Message exceeds {MAX_MESSAGE_LENGTH:,} characters"
            )

        message_id = str(
            data.get("id") or uuid.uuid4()
        ).strip()

        if not message_id:
            message_id = str(uuid.uuid4())

        timestamp = str(
            data.get("timestamp") or iso_timestamp()
        ).strip()

        intent = data.get("intent")

        if intent is not None:
            intent = str(intent).strip() or None

        metadata = data.get(
            "metadata",
            {},
        )

        if not isinstance(metadata, dict):
            metadata = {}

        # Make a shallow copy so callers cannot mutate the source object.
        metadata = dict(metadata)

        return cls(
            id=message_id,
            role=role,
            content=content,
            timestamp=timestamp,
            intent=intent,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Provider formatting
    # ------------------------------------------------------------------

    def to_provider_format(
        self,
    ) -> dict[str, str]:
        """Return standard LLM provider role/content format."""

        return {
            "role": self.role.value,
            "content": self.content,
        }

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def source(self) -> Optional[str]:
        """Return message source."""

        value = self.metadata.get("source")

        if value is None:
            return None

        return str(value)

    @property
    def input_mode(self) -> Optional[str]:
        """Return input mode, such as text or voice."""

        value = self.metadata.get("input_mode")

        if value is None:
            return None

        return str(value)

    @property
    def is_voice(self) -> bool:
        """Return True when this message originated from voice."""

        return (
            self.source == "voice"
            or self.input_mode == "voice"
        )

    @property
    def confidence(self) -> Optional[float]:
        """Return speech recognition confidence when available."""

        value = self.metadata.get("confidence")

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None


# ============================================================================
# Validation Helpers
# ============================================================================


def _normalize_role(
    role: Role | str,
) -> Role:
    """Normalize and validate a message role."""

    if isinstance(role, Role):
        return role

    try:
        return Role(
            str(role).strip().lower()
        )
    except ValueError as exc:
        valid = ", ".join(
            item.value
            for item in Role
        )

        raise HistoryValidationError(
            f"Invalid message role: {role!r}; "
            f"expected one of: {valid}"
        ) from exc


def _validate_content(
    content: str,
) -> str:
    """Validate and normalize message content."""

    if content is None:
        raise HistoryValidationError(
            "Message content cannot be None"
        )

    content = str(content).strip()

    if not content:
        raise HistoryValidationError(
            "Message content cannot be empty"
        )

    if len(content) > MAX_MESSAGE_LENGTH:
        raise HistoryValidationError(
            f"Message exceeds maximum length "
            f"({len(content):,} > {MAX_MESSAGE_LENGTH:,})"
        )

    return content


def _normalize_intent(
    intent: Optional[str],
) -> Optional[str]:
    """Normalize an optional intent value."""

    if intent is None:
        return None

    value = str(intent).strip()

    return value or None


def _normalize_source(
    source: Optional[str],
) -> Optional[str]:
    """Normalize message source."""

    if source is None:
        return None

    value = str(source).strip().lower()

    return value or None


def _normalize_language(
    language: Optional[str],
) -> Optional[str]:
    """
    Normalize voice language.

    Supported canonical values:
        bn
        en
        hi

    Aliases:
        bn-BD → bn
        en-US → en
        en-GB → en
        hi-IN → hi
    """

    if language is None:
        return None

    value = str(language).strip().lower()

    if not value:
        return None

    if value.startswith("bn"):
        return "bn"

    if value.startswith("en"):
        return "en"

    if value.startswith("hi"):
        return "hi"

    return value


def _safe_confidence(
    confidence: Any,
) -> Optional[float]:
    """Normalize speech confidence into 0.0–1.0."""

    if confidence is None:
        return None

    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return None

    return max(
        0.0,
        min(1.0, value),
    )


def _safe_non_negative_float(
    value: Any,
) -> Optional[float]:
    """Normalize optional non-negative numeric metadata."""

    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number < 0:
        return 0.0

    return number


# ============================================================================
# History Manager
# ============================================================================


class HistoryManager:
    """
    Thread-safe conversation history manager.

    The manager is deliberately independent from the voice package.

    Voice systems provide recognized text and metadata; HistoryManager stores
    those values without importing recognizer/speaker/wake-word modules.
    """

    def __init__(
        self,
        path: Path = HISTORY_JSON,
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:

        self._path = Path(path)

        self._max_messages = self._validate_max_messages(
            max_messages
        )

        self._lock = threading.RLock()

        self._messages: list[Message] = []

        self.session_id = self._new_session_id()

        self._loaded = False

        self._save_count = 0
        self._load_count = 0
        self._write_failures = 0
        self._skipped_messages = 0

        self.load()

    # ========================================================================
    # Internal
    # ========================================================================

    @staticmethod
    def _new_session_id() -> str:
        """Generate a new UUID4 session ID."""

        return str(uuid.uuid4())

    @staticmethod
    def _validate_max_messages(
        max_messages: int,
    ) -> int:

        try:
            value = int(max_messages)
        except (TypeError, ValueError) as exc:
            raise HistoryValidationError(
                "max_messages must be an integer"
            ) from exc

        if value < MIN_MAX_MESSAGES:
            raise HistoryValidationError(
                f"max_messages must be >= {MIN_MAX_MESSAGES}"
            )

        if value > MAX_MAX_MESSAGES:
            logger.warning(
                "max_messages clamped from %d to %d",
                value,
                MAX_MAX_MESSAGES,
            )

            value = MAX_MAX_MESSAGES

        return value

    def _emit(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        """Safely emit a history event."""

        try:
            event_bus.emit(
                event,
                payload,
            )

        except Exception as exc:
            # Event failures must never break history persistence.
            logger.warning(
                "History event emission failed: %s (%s)",
                event,
                type(exc).__name__,
                exc_info=exc,
            )

    def _trim(self) -> int:
        """Trim oldest messages above configured limit."""

        overflow = (
            len(self._messages)
            - self._max_messages
        )

        if overflow <= 0:
            return 0

        del self._messages[:overflow]

        return overflow

    @staticmethod
    def _message_event_payload(
        message: Message,
        *,
        persisted: bool,
    ) -> dict[str, Any]:
        """Build a stable HISTORY_APPENDED payload."""

        return {
            "message": message.to_dict(),
            "message_id": message.id,
            "role": message.role.value,
            "content": message.content,
            "session_id": None,
            "source": message.source,
            "input_mode": message.input_mode,
            "is_voice": message.is_voice,
            "confidence": message.confidence,
            "intent": message.intent,
            "persisted": persisted,
        }

    # ========================================================================
    # Add
    # ========================================================================

    def add(
        self,
        role: Role | str,
        content: str,
        intent: Optional[str] = None,
        **metadata: Any,
    ) -> Message:
        """
        Add a message to history.

        Persistence happens before HISTORY_APPENDED is emitted.
        """

        normalized_role = _normalize_role(role)

        normalized_content = _validate_content(
            content
        )

        normalized_intent = _normalize_intent(
            intent
        )

        clean_metadata = dict(metadata)

        # Normalize known metadata fields.
        if "source" in clean_metadata:
            clean_metadata["source"] = _normalize_source(
                clean_metadata.get("source")
            )

        if "input_mode" in clean_metadata:
            clean_metadata["input_mode"] = _normalize_source(
                clean_metadata.get("input_mode")
            )

        if "confidence" in clean_metadata:
            confidence = _safe_confidence(
                clean_metadata.get("confidence")
            )

            if confidence is not None:
                clean_metadata["confidence"] = confidence
            else:
                clean_metadata.pop(
                    "confidence",
                    None,
                )

        message = Message(
            role=normalized_role,
            content=normalized_content,
            intent=normalized_intent,
            metadata=clean_metadata,
        )

        with self._lock:

            self._messages.append(message)

            removed = self._trim()

            persisted = self.save()

            session_id = self.session_id

        if not persisted:
            logger.warning(
                "History message %s exists in memory but was not persisted",
                message.id[:8],
            )

        payload = self._message_event_payload(
            message,
            persisted=persisted,
        )

        payload["session_id"] = session_id

        self._emit(
            Events.HISTORY_APPENDED,
            payload,
        )

        logger.debug(
            "History message added: id=%s role=%s source=%s trimmed=%d persisted=%s",
            message.id[:8],
            message.role.value,
            message.source,
            removed,
            persisted,
        )

        return message

    # ========================================================================
    # Text Messages
    # ========================================================================

    def add_user_message(
        self,
        content: str,
        **metadata: Any,
    ) -> Message:
        """Add a normal user message."""

        metadata.setdefault(
            "source",
            "text",
        )

        metadata.setdefault(
            "input_mode",
            "text",
        )

        return self.add(
            Role.USER,
            content,
            **metadata,
        )

    def add_assistant_message(
        self,
        content: str,
        intent: Optional[str] = None,
        **metadata: Any,
    ) -> Message:
        """Add an AssistantX response."""

        metadata.setdefault(
            "source",
            "assistant",
        )

        metadata.setdefault(
            "input_mode",
            "text",
        )

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

        metadata.setdefault(
            "source",
            "system",
        )

        metadata.setdefault(
            "input_mode",
            "system",
        )

        return self.add(
            Role.SYSTEM,
            content,
            **metadata,
        )

    # ========================================================================
    # Voice Integration
    # ========================================================================

    def add_voice_user_message(
        self,
        content: str,
        *,
        confidence: Optional[float] = None,
        language: Optional[str] = None,
        engine: Optional[str] = None,
        wake_word: Optional[str] = None,
        intent: Optional[str] = None,
        turn_id: Optional[str] = None,
        recognition_duration_ms: Optional[float] = None,
        **metadata: Any,
    ) -> Message:
        """
        Add a user message recognized by JEROX's voice pipeline.

        This is the main bridge between voice recognition and history.

        No voice module is imported here.

        Example
        -------

            history_manager.add_voice_user_message(
                "open calculator",
                confidence=0.96,
                language="en",
                engine="speech_recognition",
                wake_word="jerox",
                turn_id="abc123",
            )
        """

        metadata["source"] = "voice"
        metadata["input_mode"] = "voice"

        normalized_confidence = _safe_confidence(
            confidence
        )

        if normalized_confidence is not None:
            metadata["confidence"] = normalized_confidence

        normalized_language = _normalize_language(
            language
        )

        if normalized_language is not None:
            metadata["language"] = normalized_language

        if engine is not None:
            engine_value = str(engine).strip()

            if engine_value:
                metadata["engine"] = engine_value

        # JEROX is fixed. We preserve the received wake word only when
        # it is explicitly supplied, while normalizing the stored identity.
        if wake_word is not None:
            wake_value = str(wake_word).strip().lower()

            if wake_value:
                metadata["wake_word"] = "jerox"

        if turn_id is not None:
            turn_value = str(turn_id).strip()

            if turn_value:
                metadata["turn_id"] = turn_value

        recognition_time = _safe_non_negative_float(
            recognition_duration_ms
        )

        if recognition_time is not None:
            metadata[
                "recognition_duration_ms"
            ] = recognition_time

        return self.add(
            Role.USER,
            content,
            intent=intent,
            **metadata,
        )

    def add_voice_assistant_message(
        self,
        content: str,
        *,
        intent: Optional[str] = None,
        turn_id: Optional[str] = None,
        language: Optional[str] = None,
        model: Optional[str] = None,
        response_duration_ms: Optional[float] = None,
        **metadata: Any,
    ) -> Message:
        """
        Add an AssistantX/JEROX response belonging to a voice turn.

        This lets one complete voice turn be represented as:

            USER voice message
                    ↓
            ASSISTANT voice response
        """

        metadata["source"] = "voice"
        metadata["input_mode"] = "voice"

        if turn_id is not None:
            turn_value = str(turn_id).strip()

            if turn_value:
                metadata["turn_id"] = turn_value

        normalized_language = _normalize_language(
            language
        )

        if normalized_language is not None:
            metadata["language"] = normalized_language

        if model is not None:
            model_value = str(model).strip()

            if model_value:
                metadata["model"] = model_value

        response_time = _safe_non_negative_float(
            response_duration_ms
        )

        if response_time is not None:
            metadata[
                "response_duration_ms"
            ] = response_time

        return self.add(
            Role.ASSISTANT,
            content,
            intent=intent,
            **metadata,
        )

    # ========================================================================
    # Generic Voice Turn
    # ========================================================================

    def add_voice_turn(
        self,
        user_content: str,
        assistant_content: Optional[str] = None,
        *,
        confidence: Optional[float] = None,
        language: Optional[str] = None,
        engine: Optional[str] = None,
        wake_word: str = "jerox",
        intent: Optional[str] = None,
        turn_id: Optional[str] = None,
        recognition_duration_ms: Optional[float] = None,
        response_duration_ms: Optional[float] = None,
        model: Optional[str] = None,
        **metadata: Any,
    ) -> tuple[Message, Optional[Message]]:
        """
        Store a complete JEROX voice turn.

        Returns
        -------
        tuple
            (user_message, assistant_message_or_none)

        This method is useful when the voice pipeline already has the
        complete interaction before persistence.
        """

        if turn_id is None:
            turn_id = str(uuid.uuid4())

        user_message = self.add_voice_user_message(
            user_content,
            confidence=confidence,
            language=language,
            engine=engine,
            wake_word=wake_word,
            intent=intent,
            turn_id=turn_id,
            recognition_duration_ms=recognition_duration_ms,
            **metadata,
        )

        assistant_message: Optional[Message] = None

        if assistant_content is not None:
            assistant_message = self.add_voice_assistant_message(
                assistant_content,
                intent=intent,
                turn_id=turn_id,
                language=language,
                model=model,
                response_duration_ms=response_duration_ms,
                **metadata,
            )

        return (
            user_message,
            assistant_message,
        )

    # ========================================================================
    # Remove / Clear
    # ========================================================================

    def remove(
        self,
        message_id: str,
    ) -> bool:
        """Remove one message by ID."""

        message_id = str(
            message_id
        ).strip()

        if not message_id:
            return False

        removed_message: Optional[Message] = None

        with self._lock:

            for index, message in enumerate(
                self._messages
            ):

                if message.id == message_id:
                    removed_message = self._messages.pop(
                        index
                    )

                    persisted = self.save()

                    break
            else:
                persisted = False

        if removed_message is None:
            return False

        self._emit(
            Events.HISTORY_APPENDED,
            {
                "action": "removed",
                "message": removed_message.to_dict(),
                "message_id": removed_message.id,
                "session_id": self.session_id,
                "persisted": persisted,
            },
        )

        return True

    def clear(
        self,
        start_new_session: bool = True,
    ) -> None:
        """Clear active history and optionally create a new session."""

        with self._lock:

            previous_session_id = self.session_id

            removed_count = len(
                self._messages
            )

            self._messages.clear()

            if start_new_session:
                self.session_id = (
                    self._new_session_id()
                )

            new_session_id = self.session_id

            persisted = self.save()

        self._emit(
            Events.HISTORY_CLEARED,
            {
                "session_id": new_session_id,
                "previous_session_id": previous_session_id,
                "removed_count": removed_count,
                "persisted": persisted,
            },
        )

        logger.info(
            "History cleared: removed=%d session=%s",
            removed_count,
            new_session_id[:8],
        )

    # ========================================================================
    # Session Management
    # ========================================================================

    def new_session(
        self,
        *,
        clear_history: bool = True,
    ) -> str:
        """Create a new conversation session."""

        with self._lock:

            previous_session_id = self.session_id

            self.session_id = (
                self._new_session_id()
            )

            removed_count = 0

            if clear_history:
                removed_count = len(
                    self._messages
                )

                self._messages.clear()

            new_session_id = self.session_id

            persisted = self.save()

        if clear_history:

            self._emit(
                Events.HISTORY_CLEARED,
                {
                    "session_id": new_session_id,
                    "previous_session_id": previous_session_id,
                    "removed_count": removed_count,
                    "persisted": persisted,
                },
            )

        logger.info(
            "New history session: %s → %s",
            previous_session_id[:8],
            new_session_id[:8],
        )

        return new_session_id

    # ========================================================================
    # Access
    # ========================================================================

    def all(self) -> list[Message]:
        """Return a snapshot of all messages."""

        with self._lock:
            return list(self._messages)

    def get(
        self,
        message_id: str,
    ) -> Optional[Message]:
        """Return a message by ID."""

        message_id = str(
            message_id
        ).strip()

        if not message_id:
            return None

        with self._lock:

            for message in self._messages:

                if message.id == message_id:
                    return message

        return None

    def last(
        self,
        n: int = 1,
    ) -> list[Message]:
        """Return the last N messages, oldest first."""

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
    ) -> Optional[Message]:
        """Return the latest user message."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if message.role == Role.USER:
                    return message

        return None

    def last_assistant_message(
        self,
    ) -> Optional[Message]:
        """Return the latest assistant message."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if message.role == Role.ASSISTANT:
                    return message

        return None

    def last_voice_message(
        self,
    ) -> Optional[Message]:
        """Return the latest voice-originated message."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if message.is_voice:
                    return message

        return None

    def last_voice_user_message(
        self,
    ) -> Optional[Message]:
        """Return the latest voice user message."""

        with self._lock:

            for message in reversed(
                self._messages
            ):

                if (
                    message.role == Role.USER
                    and message.is_voice
                ):
                    return message

        return None

    # ========================================================================
    # Provider Context
    # ========================================================================

    def as_provider_messages(
        self,
        limit: Optional[int] = None,
        *,
        include_system: bool = True,
    ) -> list[dict[str, str]]:
        """
        Return provider-ready messages.

        Metadata is intentionally excluded from provider payloads.
        """

        with self._lock:

            if limit is None:
                messages = list(
                    self._messages
                )
            else:
                try:
                    normalized_limit = int(limit)
                except (TypeError, ValueError):
                    normalized_limit = len(
                        self._messages
                    )

                if normalized_limit <= 0:
                    return []

                messages = list(
                    self._messages[
                        -normalized_limit:
                    ]
                )

        if not include_system:

            messages = [
                message
                for message in messages
                if message.role != Role.SYSTEM
            ]

        return [
            message.to_provider_format()
            for message in messages
        ]

    def context_text(
        self,
        limit: Optional[int] = None,
    ) -> str:
        """Return human-readable conversation context."""

        if limit is None:
            limit = self._max_messages

        messages = self.last(limit)

        lines: list[str] = []

        for message in messages:

            if message.role == Role.USER:
                speaker = "User"

            elif message.role == Role.ASSISTANT:
                speaker = "JEROX"

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
        role: Optional[Role | str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Message]:
        """
        Search history.

        Supports role and source filters.

        Examples
        --------
            search("weather")

            search(
                "weather",
                role=Role.USER,
            )

            search(
                "calculator",
                source="voice",
            )
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

        normalized_source = (
            _normalize_source(source)
            if source is not None
            else None
        )

        with self._lock:

            results: list[Message] = []

            for message in self._messages:

                if (
                    normalized_role is not None
                    and message.role
                    != normalized_role
                ):
                    continue

                if (
                    normalized_source is not None
                    and message.source
                    != normalized_source
                ):
                    continue

                if query_normalized in normalize_text(
                    message.content
                ):
                    results.append(message)

        results.reverse()

        if limit is not None:

            try:
                normalized_limit = int(limit)
            except (TypeError, ValueError):
                normalized_limit = DEFAULT_SEARCH_LIMIT

            if normalized_limit <= 0:
                return []

            results = results[
                :normalized_limit
            ]

        return results

    # ========================================================================
    # Counts / Statistics
    # ========================================================================

    def count(
        self,
        role: Optional[Role | str] = None,
    ) -> int:
        """Return total or role-specific message count."""

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

    def voice_count(self) -> int:
        """Return number of voice-originated messages."""

        with self._lock:
            return sum(
                1
                for message in self._messages
                if message.is_voice
            )

    def count_by_source(
        self,
    ) -> dict[str, int]:
        """Return message counts grouped by source."""

        counts: dict[str, int] = {}

        with self._lock:

            for message in self._messages:

                source = (
                    message.source
                    or "unknown"
                )

                counts[source] = (
                    counts.get(source, 0)
                    + 1
                )

        return counts

    def is_empty(self) -> bool:
        """Return True if no messages exist."""

        return self.count() == 0

    def stats(self) -> dict[str, Any]:
        """Return detailed history statistics."""

        with self._lock:

            messages = list(
                self._messages
            )

            return {
                "session_id": self.session_id,
                "total": len(messages),
                "user": sum(
                    m.role == Role.USER
                    for m in messages
                ),
                "assistant": sum(
                    m.role == Role.ASSISTANT
                    for m in messages
                ),
                "system": sum(
                    m.role == Role.SYSTEM
                    for m in messages
                ),
                "voice": sum(
                    m.is_voice
                    for m in messages
                ),
                "text": sum(
                    1
                    for m in messages
                    if not m.is_voice
                    and m.role != Role.SYSTEM
                ),
                "sources": self.count_by_source(),
                "max_messages": self._max_messages,
                "loaded": self._loaded,
                "path": str(self._path),
                "schema_version": HISTORY_SCHEMA_VERSION,
                "save_count": self._save_count,
                "load_count": self._load_count,
                "write_failures": self._write_failures,
                "skipped_messages": self._skipped_messages,
            }

    # ========================================================================
    # Persistence
    # ========================================================================

    def load(self) -> None:
        """
        Load history from disk.

        Invalid individual records are skipped.
        """

        try:

            raw = read_json(
                self._path,
                default=None,
            )

            if raw is None:
                raw = {}

            if not isinstance(raw, dict):
                logger.warning(
                    "History root is not a dictionary; starting empty"
                )

                raw = {}

            raw_session_id = str(
                raw.get(
                    "session_id",
                    "",
                )
            ).strip()

            session_id = (
                raw_session_id
                or self.session_id
            )

            raw_messages = raw.get(
                "messages",
                [],
            )

            if not isinstance(
                raw_messages,
                list,
            ):
                logger.warning(
                    "History messages field is not a list"
                )

                raw_messages = []

            loaded_messages: list[Message] = []

            skipped = 0

            for index, item in enumerate(
                raw_messages
            ):

                try:

                    message = Message.from_dict(
                        item
                    )

                    loaded_messages.append(
                        message
                    )

                except HistoryValidationError as exc:

                    skipped += 1

                    logger.warning(
                        "Skipping invalid history message #%d: %s",
                        index,
                        exc,
                    )

            with self._lock:

                self.session_id = session_id

                self._messages = (
                    loaded_messages
                )

                self._skipped_messages += skipped

                removed = self._trim()

                self._loaded = True

                self._load_count += 1

            if removed:
                logger.info(
                    "Trimmed %d old messages after load",
                    removed,
                )

            logger.info(
                "History loaded: %d messages, voice=%d, session=%s",
                len(loaded_messages),
                sum(
                    message.is_voice
                    for message in loaded_messages
                ),
                session_id[:8],
            )

        except Exception as exc:

            logger.exception(
                "History load failed: %s",
                exc,
            )

            with self._lock:

                self._messages = []

                self._loaded = True

                self._load_count += 1

    def save(self) -> bool:
        """
        Persist history atomically through core.utils.write_json().
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
                    self._write_failures += 1

                    logger.error(
                        "History write_json returned False: %s",
                        self._path,
                    )

                    return False

                self._save_count += 1

                return True

            except Exception as exc:

                self._write_failures += 1

                logger.error(
                    "History save failed: %s",
                    exc,
                    exc_info=True,
                )

                return False

    def reload(self) -> None:
        """Discard current in-memory state and reload from disk."""

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
        """Export current history to a readable text transcript."""

        destination = Path(path)

        messages = self.all()

        lines: list[str] = []

        for message in messages:

            if message.role == Role.USER:
                speaker = "You"

            elif message.role == Role.ASSISTANT:
                speaker = "JEROX"

            else:
                speaker = "System"

            source = message.source

            source_label = (
                f" [{source}]"
                if source
                else ""
            )

            lines.append(
                f"[{message.timestamp}] "
                f"{speaker}{source_label}: "
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

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_text(
                "\n".join(lines),
                encoding="utf-8",
            )

            logger.info(
                "Transcript exported: %d messages → %s",
                len(messages),
                destination,
            )

            return True

        except OSError as exc:

            logger.error(
                "Transcript export failed: %s",
                exc,
                exc_info=True,
            )

            return False

    # ========================================================================
    # Configuration
    # ========================================================================

    @property
    def max_messages(self) -> int:
        """Return configured history limit."""

        with self._lock:
            return self._max_messages

    def set_max_messages(
        self,
        max_messages: int,
    ) -> None:
        """Change maximum active history size."""

        new_limit = self._validate_max_messages(
            max_messages
        )

        with self._lock:

            self._max_messages = new_limit

            removed = self._trim()

            if removed:
                self.save()

        logger.info(
            "History max_messages changed to %d; trimmed=%d",
            new_limit,
            removed,
        )

    @property
    def path(self) -> Path:
        """Return history JSON path."""

        return self._path

    @property
    def loaded(self) -> bool:
        """Return whether initial loading has completed."""

        with self._lock:
            return self._loaded

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """Return production diagnostics."""

        with self._lock:

            return {
                "module": "core.history",
                "status": "ok",
                "loaded": self._loaded,
                "session_id": self.session_id,
                "message_count": len(
                    self._messages
                ),
                "voice_message_count": sum(
                    message.is_voice
                    for message in self._messages
                ),
                "max_messages": self._max_messages,
                "path": str(self._path),
                "file_exists": self._path.exists(),
                "schema_version": HISTORY_SCHEMA_VERSION,
                "save_count": self._save_count,
                "load_count": self._load_count,
                "write_failures": self._write_failures,
                "skipped_messages": self._skipped_messages,
                "sources": self.count_by_source(),
            }


# ============================================================================
# Global History Manager
# ============================================================================


history_manager = HistoryManager()


logger.info(
    "Global history_manager initialized: session=%s path=%s",
    history_manager.session_id[:8],
    history_manager.path,
)


# ============================================================================
# Global Convenience Functions
# ============================================================================


def add_user_message(
    content: str,
    **metadata: Any,
) -> Message:
    """Add a normal text/UI user message."""

    return history_manager.add_user_message(
        content,
        **metadata,
    )


def add_voice_user_message(
    content: str,
    *,
    confidence: Optional[float] = None,
    language: Optional[str] = None,
    engine: Optional[str] = None,
    wake_word: Optional[str] = None,
    intent: Optional[str] = None,
    turn_id: Optional[str] = None,
    recognition_duration_ms: Optional[float] = None,
    **metadata: Any,
) -> Message:
    """Add a JEROX voice-recognized user message."""

    return history_manager.add_voice_user_message(
        content,
        confidence=confidence,
        language=language,
        engine=engine,
        wake_word=wake_word,
        intent=intent,
        turn_id=turn_id,
        recognition_duration_ms=recognition_duration_ms,
        **metadata,
    )


def add_assistant_message(
    content: str,
    intent: Optional[str] = None,
    **metadata: Any,
) -> Message:
    """Add an AssistantX/JEROX assistant response."""

    return history_manager.add_assistant_message(
        content,
        intent=intent,
        **metadata,
    )


def add_voice_assistant_message(
    content: str,
    *,
    intent: Optional[str] = None,
    turn_id: Optional[str] = None,
    language: Optional[str] = None,
    model: Optional[str] = None,
    response_duration_ms: Optional[float] = None,
    **metadata: Any,
) -> Message:
    """Add a voice-mode JEROX response."""

    return history_manager.add_voice_assistant_message(
        content,
        intent=intent,
        turn_id=turn_id,
        language=language,
        model=model,
        response_duration_ms=response_duration_ms,
        **metadata,
    )


def add_system_message(
    content: str,
    **metadata: Any,
) -> Message:
    """Add a system message."""

    return history_manager.add_system_message(
        content,
        **metadata,
    )


def get_history(
    limit: Optional[int] = None,
) -> list[Message]:
    """Return recent history."""

    if limit is None:
        return history_manager.all()

    return history_manager.last(
        limit
    )


def get_provider_history(
    limit: Optional[int] = None,
    *,
    include_system: bool = True,
) -> list[dict[str, str]]:
    """Return provider-ready conversation history."""

    return history_manager.as_provider_messages(
        limit,
        include_system=include_system,
    )


def search_history(
    query: str,
    limit: Optional[int] = None,
    *,
    role: Optional[Role | str] = None,
    source: Optional[str] = None,
) -> list[Message]:
    """Search history."""

    return history_manager.search(
        query,
        role=role,
        source=source,
        limit=limit,
    )


def clear_history(
    start_new_session: bool = True,
) -> None:
    """Clear current history."""

    history_manager.clear(
        start_new_session=start_new_session
    )


def new_session(
    *,
    clear_history: bool = True,
) -> str:
    """Create a new conversation session."""

    return history_manager.new_session(
        clear_history=clear_history
    )


def history_count() -> int:
    """Return total active message count."""

    return history_manager.count()


def history_diagnostics() -> dict[str, Any]:
    """Return global history diagnostics."""

    return history_manager.diagnostics()


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Constants
    "DEFAULT_MAX_MESSAGES",
    "DEFAULT_SEARCH_LIMIT",
    "HISTORY_SCHEMA_VERSION",
    "MAX_MESSAGE_LENGTH",
    "SUPPORTED_INPUT_SOURCES",
    "SUPPORTED_VOICE_LANGUAGES",

    # Enum
    "Role",

    # Data model
    "Message",

    # Exceptions
    "HistoryError",
    "HistoryValidationError",
    "MessageNotFoundError",

    # Manager
    "HistoryManager",
    "history_manager",

    # User messages
    "add_user_message",
    "add_voice_user_message",

    # Assistant messages
    "add_assistant_message",
    "add_voice_assistant_message",

    # System
    "add_system_message",

    # History access
    "get_history",
    "get_provider_history",
    "search_history",

    # Session/history control
    "clear_history",
    "new_session",
    "history_count",
    "history_diagnostics",
]
