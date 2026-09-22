"""
core/memory.py
==============

AssistantX Long-Term Memory System.

Responsible for storing durable user memories such as:
    - Identity
    - Preferences
    - Facts
    - Commitments / reminders
    - Relationships

Features
--------
- Thread-safe memory management
- JSON persistence
- CRUD operations
- Category-based memory
- Importance / priority
- Search
- Context generation for AI prompts
- Duplicate key protection
- Input validation
- Safe loading from corrupted/invalid data
- Memory statistics
- Event-bus integration
- Global singleton + helper functions

This module is intentionally independent from the UI so it can be used by:
    - brain/context_manager.py
    - AI providers
    - voice commands
    - automation
    - dashboard
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from config.constants import MEMORY_JSON
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

MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 5

DEFAULT_IMPORTANCE = 1
DEFAULT_SOURCE = "conversation"

DEFAULT_CONTEXT_LIMIT = 10
DEFAULT_MIN_IMPORTANCE = 1

MEMORY_SCHEMA_VERSION = 1


# ============================================================================
# Exceptions
# ============================================================================


class MemoryError(Exception):
    """Base exception for the memory system."""


class MemoryValidationError(MemoryError):
    """Raised when memory input is invalid."""


class MemoryNotFoundError(MemoryError):
    """Raised when a requested memory does not exist."""


# ============================================================================
# Categories
# ============================================================================


class MemoryCategory(str, Enum):
    """Supported long-term memory categories."""

    IDENTITY = "identity"
    PREFERENCE = "preference"
    FACT = "fact"
    COMMITMENT = "commitment"
    RELATIONSHIP = "relationship"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return all category values."""
        return tuple(category.value for category in cls)


# ============================================================================
# Memory Entry
# ============================================================================


@dataclass
class MemoryEntry:
    """
    Represents one durable memory record.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    category: MemoryCategory = MemoryCategory.FACT

    # Short machine-friendly identifier.
    # Example: "user_name"
    key: str = ""

    # Actual remembered information.
    value: str = ""

    created_at: str = field(default_factory=iso_timestamp)
    updated_at: str = field(default_factory=iso_timestamp)

    # 1 = low importance
    # 5 = very important
    importance: int = DEFAULT_IMPORTANCE

    # Where the memory originated.
    source: str = DEFAULT_SOURCE

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Convert memory entry to a JSON-compatible dictionary."""

        data = asdict(self)

        data["category"] = self.category.value

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """
        Create a MemoryEntry from persisted data.

        Invalid optional fields are replaced with safe defaults.
        """

        if not isinstance(data, dict):
            raise MemoryValidationError("Memory entry must be a dictionary.")

        try:
            category = MemoryCategory(
                data.get(
                    "category",
                    MemoryCategory.FACT.value,
                )
            )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid memory category '%s'. Falling back to FACT.",
                data.get("category"),
            )
            category = MemoryCategory.FACT

        importance = _normalize_importance(
            data.get("importance", DEFAULT_IMPORTANCE)
        )

        key = _normalize_key(str(data.get("key", "")))

        value = str(data.get("value", "")).strip()

        if not key:
            raise MemoryValidationError(
                "Memory entry contains an empty key."
            )

        if not value:
            raise MemoryValidationError(
                f"Memory entry '{key}' contains an empty value."
            )

        now = iso_timestamp()

        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            category=category,
            key=key,
            value=value,
            created_at=str(data.get("created_at") or now),
            updated_at=str(data.get("updated_at") or now),
            importance=importance,
            source=str(
                data.get("source") or DEFAULT_SOURCE
            ).strip(),
        )


# ============================================================================
# Validation Helpers
# ============================================================================


def _normalize_key(key: str) -> str:
    """
    Normalize a memory key.

    Example:
        " User Name " -> "user_name"
        "favorite music" -> "favorite_music"
    """

# UPDATED

def _normalize_key(key: str) -> str:
    """
    Normalize a memory key.

    Example:
        " User Name " -> "user_name"
        "favorite music" -> "favorite_music"
    """

    normalized = normalize_text(str(key))
    normalized = normalized.replace(" ", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")

def _normalize_importance(value: Any) -> int:
    """Clamp importance to the supported 1-5 range."""

    try:
        importance = int(value)
    except (TypeError, ValueError):
        importance = DEFAULT_IMPORTANCE

    return max(
        MIN_IMPORTANCE,
        min(MAX_IMPORTANCE, importance),
    )


def _normalize_category(
    category: MemoryCategory | str,
) -> MemoryCategory:
    """Convert a category string into MemoryCategory."""

    if isinstance(category, MemoryCategory):
        return category

    try:
        return MemoryCategory(str(category).strip().lower())
    except ValueError as exc:
        raise MemoryValidationError(
            f"Invalid memory category: {category!r}. "
            f"Valid categories: {', '.join(MemoryCategory.values())}"
        ) from exc


def _validate_value(value: str) -> str:
    """Validate and normalize memory value."""

    value = str(value).strip()

    if not value:
        raise MemoryValidationError(
            "Memory value cannot be empty."
        )

    return value


def _validate_source(source: str) -> str:
    """Validate memory source."""

    source = str(source).strip()

    return source or DEFAULT_SOURCE


# ============================================================================
# Memory Manager
# ============================================================================


class MemoryManager:
    """
    Thread-safe CRUD manager for AssistantX long-term memory.

    All disk operations are protected through the manager lock to avoid
    concurrent state corruption.
    """

    def __init__(
        self,
        path: Path = MEMORY_JSON,
    ) -> None:

        self._path = Path(path)

        self._lock = threading.RLock()

        self._entries: dict[str, MemoryEntry] = {}

        self._loaded = False

        self.load()

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _find_by_key(
        self,
        normalized_key: str,
    ) -> MemoryEntry | None:
        """Find an entry by normalized key."""

        for entry in self._entries.values():
            if entry.key == normalized_key:
                return entry

        return None

    def _find_by_id(
        self,
        entry_id: str,
    ) -> MemoryEntry | None:
        """Find an entry by ID."""

        return self._entries.get(entry_id)

    def _emit_memory_event(
        self,
        entry: MemoryEntry,
    ) -> None:
        """Emit memory update event safely."""

        try:
            event_bus.emit(
                Events.MEMORY_UPDATED,
                entry.to_dict(),
            )
        except Exception:
            logger.exception(
                "Failed to emit MEMORY_UPDATED event."
            )

    # ========================================================================
    # Create / Update
    # ========================================================================


    def remember(
        self,
        key: str,
        value: str,
        category: MemoryCategory | str = MemoryCategory.FACT,
        importance: int = DEFAULT_IMPORTANCE,
        source: str = DEFAULT_SOURCE,
    ) -> MemoryEntry:
        """Store or update a memory entry thread-safely.

        If the key already exists, updates the record and sets new timestamps.
        Raises MemoryValidationError if input validation fails.
        """
        if key is None or not isinstance(key, str):
            raise MemoryValidationError("Memory key must be a non-empty string.")

        try:
            normalized_key = _normalize_key(key)
        except Exception as exc:
            raise MemoryValidationError(f"Invalid key format: {exc}") from exc

        if not normalized_key:
            raise MemoryValidationError("Memory key cannot be empty.")

        #if value is None:
          #  raise MemoryValidationError("Memory value cannot be None.")

        normalized_value = _validate_value(value)
        normalized_category = _normalize_category(category)
        normalized_importance = _normalize_importance(importance)
        normalized_source = _validate_source(source)

        with self._lock:
            existing = self._find_by_key(normalized_key)

            if existing:
                existing.value = normalized_value
                existing.category = normalized_category
                existing.importance = max(
                    existing.importance,
                    normalized_importance,
                )
                existing.source = normalized_source
                existing.updated_at = iso_timestamp()
                entry = existing
                logger.debug("Memory updated: %s", normalized_key)
            else:
                entry = MemoryEntry(
                    key=normalized_key,
                    value=normalized_value,
                    category=normalized_category,
                    importance=normalized_importance,
                    source=normalized_source,
                )
                self._entries[entry.id] = entry
                logger.debug("Memory created: %s", normalized_key)

            self.save()

        self._emit_memory_event(entry)
        return entry


    # ========================================================================
    # Delete
    # ========================================================================

    def forget(
        self,
        key: str,
    ) -> bool:
        """
        Delete one memory by key.

        Returns:
            True if deleted, otherwise False.
        """

        normalized_key = _normalize_key(key)

        if not normalized_key:
            return False

        with self._lock:

            entry = self._find_by_key(normalized_key)

            if not entry:
                return False

            del self._entries[entry.id]

            self.save()

        logger.info(
            "Memory forgotten: %s",
            normalized_key,
        )

        return True

    def forget_by_id(
        self,
        entry_id: str,
    ) -> bool:
        """Delete one memory by its unique ID."""

        entry_id = str(entry_id).strip()

        if not entry_id:
            return False

        with self._lock:

            if entry_id not in self._entries:
                return False

            del self._entries[entry_id]

            self.save()

        logger.info(
            "Memory forgotten by ID: %s",
            entry_id,
        )

        return True

    def forget_all(
        self,
        category: MemoryCategory | str | None = None,
    ) -> int:
        """
        Delete all memories.

        Optionally restrict deletion to a category.

        Returns:
            Number of deleted entries.
        """

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        with self._lock:

            if normalized_category is None:

                count = len(self._entries)

                self._entries.clear()

            else:

                to_remove = [
                    entry_id
                    for entry_id, entry in self._entries.items()
                    if entry.category == normalized_category
                ]

                for entry_id in to_remove:
                    del self._entries[entry_id]

                count = len(to_remove)

            if count:
                self.save()

        logger.info(
            "Forgot %d memory entr(y/ies). Category=%s",
            count,
            normalized_category,
        )

        return count

    # ========================================================================
    # Recall
    # ========================================================================

    def recall(
        self,
        key: str,
    ) -> str | None:
        """
        Return a memory value by key.

        Returns:
            Memory value or None.
        """

        normalized_key = _normalize_key(key)

        if not normalized_key:
            return None

        with self._lock:

            entry = self._find_by_key(normalized_key)

            return entry.value if entry else None

    def get(
        self,
        key: str,
    ) -> MemoryEntry | None:
        """Return the complete memory entry by key."""

        normalized_key = _normalize_key(key)

        if not normalized_key:
            return None

        with self._lock:
            return self._find_by_key(normalized_key)

    def get_by_id(
        self,
        entry_id: str,
    ) -> MemoryEntry | None:
        """Return a memory entry by ID."""

        with self._lock:

            return self._find_by_id(
                str(entry_id).strip()
            )

    # ========================================================================
    # Listing
    # ========================================================================

    def all_entries(
        self,
        category: MemoryCategory | str | None = None,
    ) -> list[MemoryEntry]:
        """
        Return all memories sorted by importance.

        Highest importance comes first.
        """

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        with self._lock:

            entries = list(
                self._entries.values()
            )

        if normalized_category is not None:

            entries = [
                entry
                for entry in entries
                if entry.category == normalized_category
            ]

        return sorted(
            entries,
            key=lambda entry: (
                entry.importance,
                entry.updated_at,
            ),
            reverse=True,
        )

    def recent(
        self,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Return recently updated memories."""

        limit = max(1, int(limit))

        with self._lock:

            entries = list(
                self._entries.values()
            )

        return sorted(
            entries,
            key=lambda entry: entry.updated_at,
            reverse=True,
        )[:limit]

    # ========================================================================
    # Search
    # ========================================================================

    def search(
        self,
        query: str,
        category: MemoryCategory | str | None = None,
        min_importance: int = MIN_IMPORTANCE,
        limit: int | None = None,
    ) -> list[MemoryEntry]:
        """
        Search memory keys and values.

        Search is case-insensitive and whitespace normalized.
        """

        query_norm = normalize_text(query)

        if not query_norm:
            return []

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        min_importance = _normalize_importance(
            min_importance
        )

        with self._lock:

            results = []

            for entry in self._entries.values():

                if entry.importance < min_importance:
                    continue

                if (
                    normalized_category is not None
                    and entry.category != normalized_category
                ):
                    continue

                key_match = (
                    query_norm
                    in normalize_text(entry.key)
                )

                value_match = (
                    query_norm
                    in normalize_text(entry.value)
                )

                if key_match or value_match:
                    results.append(entry)

        results.sort(
            key=lambda entry: (
                entry.importance,
                entry.updated_at,
            ),
            reverse=True,
        )

        if limit is not None:

            limit = max(1, int(limit))

            results = results[:limit]

        return results

    # ========================================================================
    # Context
    # ========================================================================

    def as_context_string(
        self,
        limit: int = DEFAULT_CONTEXT_LIMIT,
        min_importance: int = DEFAULT_MIN_IMPORTANCE,
        category: MemoryCategory | str | None = None,
    ) -> str:
        """
        Build a compact memory context for AI prompts.

        Example:

            - User prefers Bangla.
            - User's name is Rahim.
            - User likes lo-fi music.
        """

        limit = max(1, int(limit))

        min_importance = _normalize_importance(
            min_importance
        )

        entries = [
            entry
            for entry in self.all_entries(category)
            if entry.importance >= min_importance
        ][:limit]

        if not entries:
            return ""

        return "\n".join(
            f"- {entry.value}"
            for entry in entries
        )

    def as_context_entries(
        self,
        limit: int = DEFAULT_CONTEXT_LIMIT,
        min_importance: int = DEFAULT_MIN_IMPORTANCE,
    ) -> list[dict[str, Any]]:
        """
        Return structured memory context.

        Useful for context_manager.py or AI providers that prefer
        structured data over plain text.
        """

        entries = [
            entry
            for entry in self.all_entries()
            if entry.importance >= min_importance
        ][: max(1, int(limit))]

        return [
            {
                "key": entry.key,
                "value": entry.value,
                "category": entry.category.value,
                "importance": entry.importance,
                "source": entry.source,
            }
            for entry in entries
        ]

    # ========================================================================
    # Update
    # ========================================================================

    def update_importance(
        self,
        key: str,
        importance: int,
    ) -> MemoryEntry | None:
        """Update only the importance of an existing memory."""

        normalized_key = _normalize_key(key)

        normalized_importance = _normalize_importance(
            importance
        )

        with self._lock:

            entry = self._find_by_key(normalized_key)

            if not entry:
                return None

            entry.importance = normalized_importance
            entry.updated_at = iso_timestamp()

            self.save()

        self._emit_memory_event(entry)

        return entry

    def update_category(
        self,
        key: str,
        category: MemoryCategory | str,
    ) -> MemoryEntry | None:
        """Move an existing memory into another category."""

        normalized_key = _normalize_key(key)

        normalized_category = _normalize_category(
            category
        )

        with self._lock:

            entry = self._find_by_key(normalized_key)

            if not entry:
                return None

            entry.category = normalized_category
            entry.updated_at = iso_timestamp()

            self.save()

        self._emit_memory_event(entry)

        return entry

    # ========================================================================
    # Persistence
    # ========================================================================

    def load(self) -> None:
        """
        Load memories from disk.

        Invalid individual entries are skipped instead of crashing the
        entire AssistantX startup process.
        """

        try:

            raw = read_json(
                self._path,
                default={
                    "schema_version": MEMORY_SCHEMA_VERSION,
                    "entries": [],
                },
            )

            if not isinstance(raw, dict):

                logger.warning(
                    "Memory file contains invalid root data."
                )

                raw = {"entries": []}

            raw_entries = raw.get(
                "entries",
                [],
            )

            if not isinstance(raw_entries, list):

                logger.warning(
                    "Memory 'entries' is not a list."
                )

                raw_entries = []

            loaded: dict[str, MemoryEntry] = {}

            for item in raw_entries:

                try:

                    entry = MemoryEntry.from_dict(item)

                    loaded[entry.id] = entry

                except MemoryValidationError as exc:

                    logger.warning(
                        "Skipping invalid memory entry: %s",
                        exc,
                    )

            with self._lock:

                self._entries = loaded

                self._loaded = True

            logger.info(
                "Loaded %d memory entr(y/ies) from %s.",
                len(loaded),
                self._path,
            )

        except MemoryValidationError:

            logger.exception(
                "Failed to load memory from %s.",
                self._path,
            )

            with self._lock:

                self._entries = {}

                self._loaded = True

    def save(self) -> bool:
        """
        Persist current memory state to disk.

        Returns:
            True on success, False on failure.
        """

        with self._lock:

            payload = {
                "schema_version": MEMORY_SCHEMA_VERSION,
                "updated_at": iso_timestamp(),
                "entries": [
                    entry.to_dict()
                    for entry in self._entries.values()
                ],
            }

            try:

                result = write_json(
                    self._path,
                    payload,
                )

                if result is False:

                    logger.error(
                        "Failed to persist memory to %s.",
                        self._path,
                    )

                    return False

                return True

            except Exception:

                logger.exception(
                    "Failed to persist memory to %s.",
                    self._path,
                )

                return False

    # ========================================================================
    # Utility
    # ========================================================================

    def count(
        self,
        category: MemoryCategory | str | None = None,
    ) -> int:
        """Return total memory count, optionally by category."""

        if category is None:

            with self._lock:
                return len(self._entries)

        return len(
            self.all_entries(category)
        )

    def exists(
        self,
        key: str,
    ) -> bool:
        """Check whether a memory key exists."""

        return self.get(key) is not None

    def clear(self) -> int:
        """
        Clear every memory entry.

        Alias-friendly method for UI or command handlers.
        """

        return self.forget_all()

    def reload(self) -> None:
        """Reload memories from disk."""

        self.load()

    def path(self) -> Path:
        """Return the current memory file path."""

        return self._path

    def stats(self) -> dict[str, Any]:
        """Return useful memory statistics."""

        with self._lock:

            entries = list(
                self._entries.values()
            )

        by_category = {
            category.value: 0
            for category in MemoryCategory
        }

        for entry in entries:
            by_category[entry.category.value] += 1

        importance = {
            str(level): 0
            for level in range(
                MIN_IMPORTANCE,
                MAX_IMPORTANCE + 1,
            )
        }

        for entry in entries:
            importance[str(entry.importance)] += 1

        return {
            "total": len(entries),
            "loaded": self._loaded,
            "path": str(self._path),
            "schema_version": MEMORY_SCHEMA_VERSION,
            "categories": by_category,
            "importance": importance,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information."""

        return {
            "module": "core.memory",
            "status": "ok",
            "loaded": self._loaded,
            "memory_count": self.count(),
            "path": str(self._path),
            "file_exists": self._path.exists(),
            "schema_version": MEMORY_SCHEMA_VERSION,
        }


# ============================================================================
# Global Memory Manager
# ============================================================================

memory_manager = MemoryManager()


# ============================================================================
# Convenience Functions
# ============================================================================


def remember(
    key: str,
    value: str,
    category: MemoryCategory | str = MemoryCategory.FACT,
    importance: int = DEFAULT_IMPORTANCE,
    source: str = DEFAULT_SOURCE,
) -> MemoryEntry:
    """Global helper for remembering information."""

    return memory_manager.remember(
        key=key,
        value=value,
        category=category,
        importance=importance,
        source=source,
    )


def recall(
    key: str,
) -> str | None:
    """Global helper for recalling a memory."""

    return memory_manager.recall(key)


def forget(
    key: str,
) -> bool:
    """Global helper for forgetting a memory."""

    return memory_manager.forget(key)


def search_memory(
    query: str,
    limit: int | None = None,
) -> list[MemoryEntry]:
    """Global helper for searching memories."""

    return memory_manager.search(
        query=query,
        limit=limit,
    )


def memory_context(
    limit: int = DEFAULT_CONTEXT_LIMIT,
    min_importance: int = DEFAULT_MIN_IMPORTANCE,
) -> str:
    """Global helper for generating AI memory context."""

    return memory_manager.as_context_string(
        limit=limit,
        min_importance=min_importance,
    )


def memory_count() -> int:
    """Return total stored memories."""

    return memory_manager.count()


# ============================================================================
# Diagnostics
# ============================================================================


def memory_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global memory manager."""

    return memory_manager.diagnostics()


get = get_memory = memory_manager.get


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "DEFAULT_IMPORTANCE",
    "DEFAULT_SOURCE",
    "MAX_IMPORTANCE",
    "MEMORY_SCHEMA_VERSION",
    "MIN_IMPORTANCE",
    "MemoryCategory",
    "MemoryEntry",
    "MemoryError",
    "MemoryManager",
    "MemoryNotFoundError",
    "MemoryValidationError",
    "forget",
    "get",
    "memory_context",
    "memory_count",
    "memory_diagnostics",
    "memory_manager",
    "recall",
    "remember",
    "search_memory",
]
