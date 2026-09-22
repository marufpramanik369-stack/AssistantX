"""
database.sqlite.models
======================

Typed, lightweight data models for AssistantX's SQLite database.

This module intentionally does NOT implement ORM behavior. Database
queries, transactions, migrations, and persistence remain the
responsibility of ``database.sqlite.db_manager``.

Responsibilities
----------------
- Convert ``sqlite3.Row`` / mapping-like query results into typed models.
- Safely deserialize JSON-backed database fields.
- Provide convenient datetime properties.
- Provide lightweight serialization helpers.
- Keep database-facing code explicit, predictable, and dependency-free.

Example
-------
    row = db_manager.fetchone(...)
    conversation = Conversation.from_row(row)

    print(conversation.title)
    print(conversation.created_at_dt)

These models are plain Python dataclasses and contain no lazy loading,
session tracking, or hidden database queries.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import (
    Any,
    ClassVar,
    Literal,
    TypeAlias,
    TypeVar,
)

# =============================================================================
# Types
# =============================================================================

RowMapping: TypeAlias = Mapping[str, Any]

TaskStatus: TypeAlias = Literal[
    "pending",
    "in_progress",
    "completed",
    "cancelled",
]

MessageRole: TypeAlias = Literal[
    "system",
    "user",
    "assistant",
    "tool",
]


T = TypeVar("T", bound="DatabaseModel")


# =============================================================================
# Exceptions
# =============================================================================


class ModelError(Exception):
    """Base exception for database model errors."""


class ModelConversionError(ModelError):
    """Raised when a database row cannot be converted into a model."""


# =============================================================================
# Internal helpers
# =============================================================================

_MISSING = object()


def _row_value(
    row: RowMapping,
    key: str,
    default: Any = _MISSING,
) -> Any:
    """
    Safely retrieve a value from a database row.

    Supports:
    - sqlite3.Row
    - dict
    - Mapping-like objects
    """
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        if default is not _MISSING:
            return default

        raise ModelConversionError(
            f"Required database column is missing: {key!r}"
        ) from None


def _as_str(
    value: Any,
    default: str = "",
) -> str:
    """Convert a value to string while safely handling None."""
    if value is None:
        return default

    if isinstance(value, str):
        return value

    return str(value)


def _as_optional_str(value: Any) -> str | None:
    """Convert a value to optional string."""
    if value is None:
        return None

    text = str(value).strip()
    return text if text else None


def _as_int(
    value: Any,
    default: int = 0,
) -> int:
    """Safely convert a value to integer."""
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(
    value: Any,
    default: bool = False,
) -> bool:
    """
    Convert common SQLite / JSON boolean representations to bool.
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }:
            return True

        if normalized in {
            "0",
            "false",
            "no",
            "off",
            "disabled",
            "",
        }:
            return False

    return default


def _decode_json(
    value: Any,
    *,
    default: Any = None,
) -> Any:
    """
    Safely deserialize a JSON database value.

    If ``value`` is already a Python object it is returned unchanged.
    Invalid JSON does not crash model creation; the original string is
    preserved instead.
    """
    if value is None:
        return default

    if not isinstance(value, str):
        return value

    text = value.strip()

    if not text:
        return default

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def _parse_iso(value: str | None) -> datetime | None:
    """
    Parse an ISO-8601 datetime string.

    Supports regular ``datetime.isoformat()`` output and UTC timestamps
    ending in ``Z``.

    Invalid values return None.
    """
    if not value:
        return None

    text = str(value).strip()

    if not text:
        return None

    # Python's datetime parser understands +00:00 more consistently
    # across versions than a trailing Z.
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _now_for_datetime(reference: datetime) -> datetime:
    """
    Return a current datetime compatible with ``reference``.

    Prevents comparing a timezone-aware datetime against a naive one.
    """
    if reference.tzinfo is None:
        return datetime.now(tz=reference.tzinfo)

    return datetime.now(reference.tzinfo)


# =============================================================================
# Base model
# =============================================================================


@dataclass(slots=True)
class DatabaseModel:
    """
    Base class shared by AssistantX database models.

    It only provides serialization conveniences and has no ORM behavior.
    """

    TABLE_NAME: ClassVar[str] = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the model as a plain dictionary."""
        return asdict(self)

    def copy_dict(self) -> dict[str, Any]:
        """Backward-friendly alias for ``to_dict``."""
        return self.to_dict()


# =============================================================================
# Conversation
# =============================================================================


@dataclass(slots=True)
class Conversation(DatabaseModel):
    """A conversation/chat session stored in the database."""

    TABLE_NAME: ClassVar[str] = "conversations"

    id: int
    title: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: RowMapping) -> Conversation:
        """Create a Conversation from a SQLite row."""
        return cls(
            id=_as_int(_row_value(row, "id")),
            title=_as_str(
                _row_value(row, "title", ""),
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
            updated_at=_as_str(
                _row_value(row, "updated_at", ""),
            ),
        )

    @property
    def created_at_dt(self) -> datetime | None:
        """Creation time as a datetime object."""
        return _parse_iso(self.created_at)

    @property
    def updated_at_dt(self) -> datetime | None:
        """Last update time as a datetime object."""
        return _parse_iso(self.updated_at)


# =============================================================================
# Message
# =============================================================================


@dataclass(slots=True)
class Message(DatabaseModel):
    """A single message belonging to a conversation."""

    TABLE_NAME: ClassVar[str] = "messages"

    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str

    @classmethod
    def from_row(cls, row: RowMapping) -> Message:
        """Create a Message from a SQLite row."""
        return cls(
            id=_as_int(
                _row_value(row, "id"),
            ),
            conversation_id=_as_int(
                _row_value(row, "conversation_id"),
            ),
            role=_as_str(
                _row_value(row, "role", "user"),
                "user",
            ),
            content=_as_str(
                _row_value(row, "content", ""),
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
        )

    @property
    def created_at_dt(self) -> datetime | None:
        """Creation time as datetime."""
        return _parse_iso(self.created_at)

    def to_provider_dict(self) -> dict[str, str]:
        """
        Convert the model into the simple message format expected by
        AI provider layers.
        """
        return {
            "role": self.role,
            "content": self.content,
        }


# =============================================================================
# Memory
# =============================================================================


@dataclass(slots=True)
class MemoryRecord(DatabaseModel):
    """A persistent AssistantX memory record."""

    TABLE_NAME: ClassVar[str] = "memories"

    id: int
    memory_key: str
    memory_value: Any
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: RowMapping) -> MemoryRecord:
        """Create a MemoryRecord from a SQLite row."""
        return cls(
            id=_as_int(
                _row_value(row, "id"),
            ),
            memory_key=_as_str(
                _row_value(row, "memory_key", ""),
            ),
            memory_value=_decode_json(
                _row_value(
                    row,
                    "memory_value",
                    None,
                )
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
            updated_at=_as_str(
                _row_value(row, "updated_at", ""),
            ),
        )

    @property
    def created_at_dt(self) -> datetime | None:
        return _parse_iso(self.created_at)

    @property
    def updated_at_dt(self) -> datetime | None:
        return _parse_iso(self.updated_at)


# =============================================================================
# Task
# =============================================================================


@dataclass(slots=True)
class Task(DatabaseModel):
    """A scheduled or user-created AssistantX task."""

    TABLE_NAME: ClassVar[str] = "tasks"

    id: int
    title: str
    description: str
    status: TaskStatus
    priority: int
    due_at: str | None
    created_at: str
    updated_at: str

    VALID_STATUSES: ClassVar[frozenset[str]] = frozenset(
        {
            "pending",
            "in_progress",
            "completed",
            "cancelled",
        }
    )

    @classmethod
    def from_row(cls, row: RowMapping) -> Task:
        """Create a Task from a SQLite row."""
        raw_status = _as_str(
            _row_value(row, "status", "pending"),
            "pending",
        ).strip().lower()

        if raw_status not in cls.VALID_STATUSES:
            raw_status = "pending"

        return cls(
            id=_as_int(
                _row_value(row, "id"),
            ),
            title=_as_str(
                _row_value(row, "title", ""),
            ),
            description=_as_str(
                _row_value(row, "description", ""),
            ),
            status=raw_status,  # type: ignore[arg-type]
            priority=_as_int(
                _row_value(row, "priority", 0),
            ),
            due_at=_as_optional_str(
                _row_value(row, "due_at", None),
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
            updated_at=_as_str(
                _row_value(row, "updated_at", ""),
            ),
        )

    @property
    def due_at_dt(self) -> datetime | None:
        """Task deadline as datetime."""
        return _parse_iso(self.due_at)

    @property
    def created_at_dt(self) -> datetime | None:
        return _parse_iso(self.created_at)

    @property
    def updated_at_dt(self) -> datetime | None:
        return _parse_iso(self.updated_at)

    @property
    def is_finished(self) -> bool:
        """Whether this task can no longer be considered active."""
        return self.status in {
            "completed",
            "cancelled",
        }

    @property
    def is_overdue(self) -> bool:
        """
        Return True when the task deadline has passed and the task has
        not been completed/cancelled.
        """
        due = self.due_at_dt

        if due is None or self.is_finished:
            return False

        return _now_for_datetime(due) >= due


# =============================================================================
# Command
# =============================================================================


@dataclass(slots=True)
class CommandRecord(DatabaseModel):
    """A persisted AssistantX command definition."""

    TABLE_NAME: ClassVar[str] = "commands"

    name: str
    command: str
    description: str
    enabled: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: RowMapping) -> CommandRecord:
        """Create a CommandRecord from a SQLite row."""
        return cls(
            name=_as_str(
                _row_value(row, "name", ""),
            ),
            command=_as_str(
                _row_value(row, "command", ""),
            ),
            description=_as_str(
                _row_value(row, "description", ""),
            ),
            enabled=_as_bool(
                _row_value(row, "enabled", True),
                True,
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
            updated_at=_as_str(
                _row_value(row, "updated_at", ""),
            ),
        )

    @property
    def created_at_dt(self) -> datetime | None:
        return _parse_iso(self.created_at)

    @property
    def updated_at_dt(self) -> datetime | None:
        return _parse_iso(self.updated_at)


# =============================================================================
# Profile
# =============================================================================


@dataclass(slots=True)
class Profile(DatabaseModel):
    """AssistantX user profile persisted in SQLite."""

    TABLE_NAME: ClassVar[str] = "profiles"

    id: int
    name: str
    email: str
    language: str
    theme: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: RowMapping) -> Profile:
        """Create a Profile from a SQLite row."""
        return cls(
            id=_as_int(
                _row_value(row, "id"),
            ),
            name=_as_str(
                _row_value(row, "name", "User"),
                "User",
            ),
            email=_as_str(
                _row_value(row, "email", ""),
            ),
            language=_as_str(
                _row_value(row, "language", "en"),
                "en",
            ),
            theme=_as_str(
                _row_value(row, "theme", "dark"),
                "dark",
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
            updated_at=_as_str(
                _row_value(row, "updated_at", ""),
            ),
        )

    @property
    def created_at_dt(self) -> datetime | None:
        return _parse_iso(self.created_at)

    @property
    def updated_at_dt(self) -> datetime | None:
        return _parse_iso(self.updated_at)


# =============================================================================
# Cache
# =============================================================================


@dataclass(slots=True)
class CacheRecord(DatabaseModel):
    """A temporary database-backed cache entry."""

    TABLE_NAME: ClassVar[str] = "cache"

    cache_key: str
    cache_value: Any
    expires_at: str | None
    created_at: str

    @property
    def key(self) -> str:
        """Alias for cache_key."""
        return self.cache_key

    @property
    def value(self) -> Any:
        """Alias for cache_value."""
        return self.cache_value


    @classmethod
    def from_row(cls, row: RowMapping) -> CacheRecord:
        """Create a CacheRecord from a SQLite row."""
        return cls(
            cache_key=_as_str(
                _row_value(row, "cache_key", ""),
            ),
            cache_value=_decode_json(
                _row_value(
                    row,
                    "cache_value",
                    None,
                )
            ),
            expires_at=_as_optional_str(
                _row_value(row, "expires_at", None),
            ),
            created_at=_as_str(
                _row_value(row, "created_at", ""),
            ),
        )

    @property
    def expires_at_dt(self) -> datetime | None:
        """Expiration timestamp as datetime."""
        return _parse_iso(self.expires_at)

    @property
    def created_at_dt(self) -> datetime | None:
        return _parse_iso(self.created_at)

    @property
    def is_expired(self) -> bool:
        """Return True when the cache entry has expired."""
        expiry = self.expires_at_dt

        if expiry is None:
            return False

        return _now_for_datetime(expiry) >= expiry


# =============================================================================
# Public exports
# =============================================================================

__all__ = [
    "CacheRecord",
    "CommandRecord",
    "Conversation",
    "DatabaseModel",
    "MemoryRecord",
    "Message",
    "MessageRole",
    "ModelConversionError",
    "ModelError",
    "Profile",
    "RowMapping",
    "Task",
    "TaskStatus",
]
