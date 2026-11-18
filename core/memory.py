"""
core/memory.py — AssistantX Production Long-Term Memory
========================================================

Persistent, thread-safe, migration-ready memory system for AssistantX.

Design goals
------------
- Durable JSON-backed long-term memory.
- Thread-safe CRUD operations.
- Stable public API for the rest of AssistantX.
- Voice/JEROX-aware memory metadata without importing voice modules.
- Category + importance based retrieval.
- Search and AI-context generation.
- Corruption-tolerant loading.
- Schema migration readiness.
- Atomic-ish persistence through the existing JSON utility layer.
- EventBus integration without allowing event failures to break memory.
- Backward-compatible convenience functions.

Memory identity
---------------
Assistant application : AssistantX
Assistant identity    : JEROX
Voice identity        : Female / fixed
Supported languages   : bn / en / hi

The memory layer intentionally does NOT import the voice package.  Voice
metadata is represented as plain strings so that core -> voice circular
dependencies are avoided.

Public compatibility
--------------------
The following existing APIs are preserved:

    MemoryCategory
    MemoryEntry
    MemoryManager
    remember()
    recall()
    forget()
    search_memory()
    memory_context()
    memory_count()
    memory_diagnostics()
    get
    get_memory
    memory_manager
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from config.constants import MEMORY_JSON
from core.event_bus import Events, event_bus
from core.logger import get_logger
from core.utils import iso_timestamp, normalize_text, read_json, write_json


logger = get_logger(__name__)


# ============================================================================
# Identity
# ============================================================================

ASSISTANT_NAME = "JEROX"
FIXED_VOICE_GENDER = "female"

SUPPORTED_LANGUAGES = ("bn", "en", "hi")
SUPPORTED_SOURCES = (
    "conversation",
    "voice",
    "text",
    "ui",
    "system",
    "automation",
    "api",
)


# ============================================================================
# Constants
# ============================================================================

MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 5

DEFAULT_IMPORTANCE = 1
DEFAULT_SOURCE = "conversation"

DEFAULT_CONTEXT_LIMIT = 10
DEFAULT_MIN_IMPORTANCE = 1
DEFAULT_SEARCH_LIMIT = 50

MEMORY_SCHEMA_VERSION = 2

MAX_KEY_LENGTH = 100
MAX_VALUE_LENGTH = 5000
MAX_SOURCE_LENGTH = 100
MAX_LANGUAGE_LENGTH = 20
MAX_CONTEXT_VALUE_LENGTH = 1000


# ============================================================================
# Exceptions
# ============================================================================


class MemoryError(Exception):
    """Base exception for AssistantX memory operations."""


class MemoryValidationError(MemoryError):
    """Raised when memory input is invalid."""


class MemoryNotFoundError(MemoryError):
    """Raised when a requested memory cannot be found."""


# ============================================================================
# Categories
# ============================================================================


class MemoryCategory(str, Enum):
    """
    Supported durable-memory categories.
    """

    IDENTITY = "identity"
    PREFERENCE = "preference"
    FACT = "fact"
    COMMITMENT = "commitment"
    RELATIONSHIP = "relationship"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return all supported category values."""
        return tuple(item.value for item in cls)


# ============================================================================
# Language helpers
# ============================================================================


_LANGUAGE_ALIASES: dict[str, str] = {
    "bn": "bn",
    "bn-bd": "bn",
    "bangla": "bn",
    "bengali": "bn",
    "বাংলা": "bn",

    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",

    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
    "हिन्दी": "hi",
}


def _normalize_language(language: Any) -> str:
    """
    Normalize a language identifier to bn/en/hi.

    Unknown values are preserved in a compact normalized form so that
    future languages do not break old memory records.
    """

    if language is None:
        return ""

    value = str(language).strip().lower()

    if not value:
        return ""

    return _LANGUAGE_ALIASES.get(
        value,
        value[:MAX_LANGUAGE_LENGTH],
    )


# ============================================================================
# Validation helpers
# ============================================================================


def _normalize_key(key: Any) -> str:
    """
    Normalize a memory key.

    Example:
        " Favorite Music " -> "favorite_music"
    """

    if key is None:
        raise MemoryValidationError("Memory key cannot be None.")

    raw = str(key).strip()

    if not raw:
        raise MemoryValidationError("Memory key cannot be empty.")

    normalized = normalize_text(raw)
    normalized = normalized.replace(" ", "_")

    while "__" in normalized:
        normalized = normalized.replace("__", "_")

    normalized = normalized.strip("_")

    if not normalized:
        raise MemoryValidationError(
            f"Memory key becomes empty after normalization: {raw!r}"
        )

    return normalized[:MAX_KEY_LENGTH]


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
    """Normalize a category into MemoryCategory."""

    if isinstance(category, MemoryCategory):
        return category

    try:
        return MemoryCategory(
            str(category).strip().lower()
        )
    except ValueError as exc:
        valid = ", ".join(MemoryCategory.values())

        raise MemoryValidationError(
            f"Invalid memory category {category!r}. "
            f"Expected one of: {valid}"
        ) from exc


def _validate_value(value: Any) -> str:
    """Validate and normalize a memory value."""

    # None is a valid JSON value (null); store it as the string "null"
    if value is None:
        return "null"

    normalized = str(value).strip()

    if not normalized:
        raise MemoryValidationError("Memory value cannot be empty.")

    return normalized[:MAX_VALUE_LENGTH]


def _validate_source(source: Any) -> str:
    """Normalize memory source."""

    if source is None:
        return DEFAULT_SOURCE

    normalized = str(source).strip().lower()

    if not normalized:
        return DEFAULT_SOURCE

    return normalized[:MAX_SOURCE_LENGTH]


def _safe_text(value: Any, limit: int = 500) -> str:
    """Return bounded human-readable text."""

    if value is None:
        return ""

    return str(value).strip()[:limit]


def _safe_confidence(value: Any) -> Optional[float]:
    """Normalize optional speech-recognition confidence."""

    if value is None:
        return None

    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None

    return max(0.0, min(1.0, confidence))


# ============================================================================
# Memory Entry
# ============================================================================


@dataclass
class MemoryEntry:
    """
    One durable memory record.

    The additional voice/language fields are optional so existing memory.json
    files remain compatible.
    """

    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    category: MemoryCategory = MemoryCategory.FACT

    key: str = ""

    value: str = ""

    created_at: str = field(
        default_factory=iso_timestamp
    )

    updated_at: str = field(
        default_factory=iso_timestamp
    )

    importance: int = DEFAULT_IMPORTANCE

    source: str = DEFAULT_SOURCE

    language: str = ""

    input_mode: str = ""

    confidence: Optional[float] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this memory entry into JSON-safe data."""

        data = asdict(self)

        data["category"] = self.category.value

        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> MemoryEntry:
        """Safely construct an entry from persisted JSON data."""

        if not isinstance(data, dict):
            raise MemoryValidationError(
                "Memory entry must be a dictionary."
            )

        key = _normalize_key(
            data.get("key", "")
        )

        value = _validate_value(
            data.get("value", "")
        )

        category = _normalize_category(
            data.get(
                "category",
                MemoryCategory.FACT.value,
            )
        )

        importance = _normalize_importance(
            data.get(
                "importance",
                DEFAULT_IMPORTANCE,
            )
        )

        source = _validate_source(
            data.get(
                "source",
                DEFAULT_SOURCE,
            )
        )

        now = iso_timestamp()

        raw_metadata = data.get(
            "metadata",
            {},
        )

        metadata = (
            dict(raw_metadata)
            if isinstance(raw_metadata, dict)
            else {}
        )

        entry_id = str(
            data.get("id")
            or uuid.uuid4()
        ).strip()

        if not entry_id:
            entry_id = str(uuid.uuid4())

        return cls(
            id=entry_id,
            category=category,
            key=key,
            value=value,
            created_at=str(
                data.get("created_at")
                or now
            ),
            updated_at=str(
                data.get("updated_at")
                or now
            ),
            importance=importance,
            source=source,
            language=_normalize_language(
                data.get("language", "")
            ),
            input_mode=_safe_text(
                data.get("input_mode", ""),
                50,
            ),
            confidence=_safe_confidence(
                data.get("confidence")
            ),
            metadata=metadata,
        )

    @property
    def is_voice(self) -> bool:
        """Return True when memory originated from voice interaction."""

        return (
            self.source == "voice"
            or self.input_mode == "voice"
        )

    @property
    def age_key(self) -> str:
        """Return a stable key useful for debugging/UI."""

        return self.key

    def clone(self) -> MemoryEntry:
        """Return a detached copy of the entry."""

        return MemoryEntry.from_dict(
            self.to_dict()
        )


# ============================================================================
# Memory Manager
# ============================================================================


class MemoryManager:
    """
    Production-grade persistent memory manager.

    All multi-step state operations are protected by RLock.  The lock is
    intentionally explicit because read-modify-write sequences are not safe
    merely because individual dictionary operations may be atomic. :contentReference[oaicite:1]{index=1}
    """

    def __init__(
        self,
        path: Path = MEMORY_JSON,
    ) -> None:

        self._path = Path(path)

        self._lock = threading.RLock()

        self._entries: dict[str, MemoryEntry] = {}

        self._loaded = False

        self._load_count = 0
        self._save_count = 0
        self._save_failures = 0
        self._load_failures = 0
        self._skipped_entries = 0

        self._last_load_at: Optional[str] = None
        self._last_save_at: Optional[str] = None
        self._last_error: Optional[str] = None

        self.load()

    # ========================================================================
    # Internal lookup helpers
    # ========================================================================

    def _find_by_key(
        self,
        normalized_key: str,
    ) -> Optional[MemoryEntry]:

        for entry in self._entries.values():

            if entry.key == normalized_key:
                return entry

        return None

    def _find_by_id(
        self,
        entry_id: str,
    ) -> Optional[MemoryEntry]:

        return self._entries.get(entry_id)

    def _emit(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Emit EventBus event without breaking memory operations."""

        try:
            event_bus.emit(
                event_name,
                payload,
            )
        except Exception as exc:
            logger.warning(
                "Memory event emission failed: %s",
                type(exc).__name__,
            )

    def _emit_updated(
        self,
        entry: MemoryEntry,
        action: str,
    ) -> None:

        self._emit(
            Events.MEMORY_UPDATED,
            {
                "action": action,
                "entry": entry.to_dict(),
            },
        )

    def _emit_deleted(
        self,
        entry: MemoryEntry,
    ) -> None:

        # MEMORY_UPDATED is retained for compatibility with the existing
        # EventBus contract. Consumers can inspect action="deleted".
        self._emit(
            Events.MEMORY_UPDATED,
            {
                "action": "deleted",
                "entry": entry.to_dict(),
            },
        )

    # ========================================================================
    # Remember / Update
    # ========================================================================

    def remember(
        self,
        key: str,
        value: str,
        category: MemoryCategory | str = MemoryCategory.FACT,
        importance: int = DEFAULT_IMPORTANCE,
        source: str = DEFAULT_SOURCE,
        *,
        language: Optional[str] = None,
        input_mode: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
        replace_importance: bool = True,
    ) -> MemoryEntry:
        """
        Create or update a durable memory.

        Existing keys are updated in place so the logical memory identity
        remains stable.

        `replace_importance=True` means explicit updates can lower or raise
        importance. Set False when callers want monotonic importance growth.
        """

        normalized_key = _normalize_key(key)
        normalized_value = _validate_value(value)
        normalized_category = _normalize_category(category)
        normalized_importance = _normalize_importance(importance)
        normalized_source = _validate_source(source)

        normalized_language = _normalize_language(
            language
        )

        normalized_input_mode = _safe_text(
            input_mode,
            50,
        ).lower()

        normalized_confidence = _safe_confidence(
            confidence
        )

        safe_metadata = (
            dict(metadata)
            if isinstance(metadata, dict)
            else {}
        )

        with self._lock:

            existing = self._find_by_key(
                normalized_key
            )

            now = iso_timestamp()

            if existing is not None:

                existing.value = normalized_value
                existing.category = normalized_category
                existing.source = normalized_source
                existing.updated_at = now

                if replace_importance:
                    existing.importance = (
                        normalized_importance
                    )
                else:
                    existing.importance = max(
                        existing.importance,
                        normalized_importance,
                    )

                if normalized_language:
                    existing.language = (
                        normalized_language
                    )

                if normalized_input_mode:
                    existing.input_mode = (
                        normalized_input_mode
                    )

                if normalized_confidence is not None:
                    existing.confidence = (
                        normalized_confidence
                    )

                if safe_metadata:
                    existing.metadata.update(
                        safe_metadata
                    )

                entry = existing
                action = "updated"

            else:

                entry = MemoryEntry(
                    key=normalized_key,
                    value=normalized_value,
                    category=normalized_category,
                    importance=normalized_importance,
                    source=normalized_source,
                    language=normalized_language,
                    input_mode=normalized_input_mode,
                    confidence=normalized_confidence,
                    metadata=safe_metadata,
                )

                self._entries[entry.id] = entry

                action = "created"

            if not self.save():
                raise MemoryError(
                    f"Failed to persist memory: {normalized_key}"
                )

        self._emit_updated(
            entry,
            action,
        )

        logger.info(
            "Memory %s: %s",
            action,
            normalized_key,
        )

        return entry

    # ========================================================================
    # Voice-specific memory
    # ========================================================================

    def remember_voice(
        self,
        key: str,
        value: str,
        *,
        category: MemoryCategory | str = MemoryCategory.FACT,
        importance: int = DEFAULT_IMPORTANCE,
        language: str = "en",
        confidence: Optional[float] = None,
        turn_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryEntry:
        """
        Remember information learned through JEROX voice interaction.

        The wake identity itself is not user-configurable here.  The memory
        layer only records the source as voice and keeps JEROX as metadata.
        """

        combined_metadata = (
            dict(metadata)
            if isinstance(metadata, dict)
            else {}
        )

        combined_metadata.setdefault(
            "assistant_name",
            ASSISTANT_NAME,
        )

        combined_metadata.setdefault(
            "voice_gender",
            FIXED_VOICE_GENDER,
        )

        combined_metadata.setdefault(
            "wake_word",
            "jerox",
        )

        if turn_id:
            combined_metadata.setdefault(
                "turn_id",
                str(turn_id),
            )

        return self.remember(
            key=key,
            value=value,
            category=category,
            importance=importance,
            source="voice",
            language=language,
            input_mode="voice",
            confidence=confidence,
            metadata=combined_metadata,
        )

    # ========================================================================
    # Recall
    # ========================================================================

    def recall(
        self,
        key: str,
    ) -> Optional[str]:

        entry = self.get(key)

        if entry is None:
            return None

        return entry.value

    def get(
        self,
        key: str,
    ) -> Optional[MemoryEntry]:

        normalized_key = _normalize_key(key)

        with self._lock:

            entry = self._find_by_key(
                normalized_key
            )

            return (
                entry.clone()
                if entry is not None
                else None
            )

    def get_by_id(
        self,
        entry_id: str,
    ) -> Optional[MemoryEntry]:

        normalized_id = str(
            entry_id
        ).strip()

        if not normalized_id:
            return None

        with self._lock:

            entry = self._find_by_id(
                normalized_id
            )

            return (
                entry.clone()
                if entry is not None
                else None
            )

    # ========================================================================
    # Forget
    # ========================================================================

    def forget(
        self,
        key: str,
    ) -> bool:

        normalized_key = _normalize_key(key)

        with self._lock:

            entry = self._find_by_key(
                normalized_key
            )

            if entry is None:
                return False

            del self._entries[entry.id]

            if not self.save():
                # Restore in-memory state if persistence failed.
                self._entries[entry.id] = entry
                return False

        self._emit_deleted(entry)

        logger.info(
            "Memory forgotten: %s",
            normalized_key,
        )

        return True

    def forget_by_id(
        self,
        entry_id: str,
    ) -> bool:

        normalized_id = str(
            entry_id
        ).strip()

        if not normalized_id:
            return False

        with self._lock:

            entry = self._entries.get(
                normalized_id
            )

            if entry is None:
                return False

            del self._entries[normalized_id]

            if not self.save():
                self._entries[normalized_id] = entry
                return False

        self._emit_deleted(entry)

        return True

    def forget_all(
        self,
        category: Optional[
            MemoryCategory | str
        ] = None,
    ) -> int:

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        with self._lock:

            if normalized_category is None:

                removed = list(
                    self._entries.values()
                )

                self._entries.clear()

            else:

                removed = [
                    entry
                    for entry in self._entries.values()
                    if entry.category
                    == normalized_category
                ]

                for entry in removed:
                    self._entries.pop(
                        entry.id,
                        None,
                    )

            if not removed:
                return 0

            if not self.save():

                for entry in removed:
                    self._entries[
                        entry.id
                    ] = entry

                return 0

        for entry in removed:
            self._emit_deleted(entry)

        logger.info(
            "Forgot %d memories",
            len(removed),
        )

        return len(removed)

    # ========================================================================
    # Listing
    # ========================================================================

    def all_entries(
        self,
        category: Optional[
            MemoryCategory | str
        ] = None,
    ) -> list[MemoryEntry]:

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        with self._lock:

            entries = [
                entry.clone()
                for entry in self._entries.values()
                if (
                    normalized_category is None
                    or entry.category
                    == normalized_category
                )
            ]

        entries.sort(
            key=lambda item: (
                item.importance,
                item.updated_at,
            ),
            reverse=True,
        )

        return entries

    def recent(
        self,
        limit: int = 10,
    ) -> list[MemoryEntry]:

        limit = max(1, int(limit))

        entries = self.all_entries()

        entries.sort(
            key=lambda item: item.updated_at,
            reverse=True,
        )

        return entries[:limit]

    # ========================================================================
    # Search
    # ========================================================================

    def search(
        self,
        query: str,
        category: Optional[
            MemoryCategory | str
        ] = None,
        min_importance: int = MIN_IMPORTANCE,
        limit: Optional[int] = None,
        source: Optional[str] = None,
        language: Optional[str] = None,
    ) -> list[MemoryEntry]:

        query_norm = normalize_text(
            str(query or "").strip()
        )

        if not query_norm:
            return []

        normalized_category = (
            _normalize_category(category)
            if category is not None
            else None
        )

        normalized_source = (
            _validate_source(source)
            if source is not None
            else None
        )

        normalized_language = (
            _normalize_language(language)
            if language is not None
            else None
        )

        minimum = _normalize_importance(
            min_importance
        )

        with self._lock:

            results: list[MemoryEntry] = []

            for entry in self._entries.values():

                if entry.importance < minimum:
                    continue

                if (
                    normalized_category is not None
                    and entry.category
                    != normalized_category
                ):
                    continue

                if (
                    normalized_source is not None
                    and entry.source
                    != normalized_source
                ):
                    continue

                if (
                    normalized_language
                    and entry.language
                    != normalized_language
                ):
                    continue

                searchable = " ".join(
                    (
                        entry.key,
                        entry.value,
                        entry.category.value,
                        entry.source,
                        entry.language,
                    )
                )

                if (
                    query_norm
                    in normalize_text(searchable)
                ):
                    results.append(
                        entry.clone()
                    )

        results.sort(
            key=lambda item: (
                item.importance,
                item.updated_at,
            ),
            reverse=True,
        )

        if limit is not None:
            results = results[
                : max(1, int(limit))
            ]

        return results

    # ========================================================================
    # Context
    # ========================================================================

    def as_context_string(
        self,
        limit: int = DEFAULT_CONTEXT_LIMIT,
        min_importance: int = DEFAULT_MIN_IMPORTANCE,
        category: Optional[
            MemoryCategory | str
        ] = None,
    ) -> str:

        limit = max(1, int(limit))

        minimum = _normalize_importance(
            min_importance
        )

        entries = [
            entry
            for entry in self.all_entries(
                category
            )
            if entry.importance >= minimum
        ][:limit]

        if not entries:
            return ""

        lines: list[str] = []

        for entry in entries:

            value = _safe_text(
                entry.value,
                MAX_CONTEXT_VALUE_LENGTH,
            )

            if entry.category == MemoryCategory.IDENTITY:
                lines.append(
                    f"- {value}"
                )
            else:
                lines.append(
                    f"- {value}"
                )

        return "\n".join(lines)

    def as_context_entries(
        self,
        limit: int = DEFAULT_CONTEXT_LIMIT,
        min_importance: int = DEFAULT_MIN_IMPORTANCE,
        category: Optional[
            MemoryCategory | str
        ] = None,
    ) -> list[dict[str, Any]]:

        limit = max(1, int(limit))

        minimum = _normalize_importance(
            min_importance
        )

        entries = [
            entry
            for entry in self.all_entries(
                category
            )
            if entry.importance >= minimum
        ][:limit]

        return [
            {
                "id": entry.id,
                "key": entry.key,
                "value": entry.value,
                "category": entry.category.value,
                "importance": entry.importance,
                "source": entry.source,
                "language": entry.language,
                "input_mode": entry.input_mode,
                "confidence": entry.confidence,
            }
            for entry in entries
        ]

    # ========================================================================
    # Update helpers
    # ========================================================================

    def update_importance(
        self,
        key: str,
        importance: int,
    ) -> Optional[MemoryEntry]:

        normalized_key = _normalize_key(key)
        normalized_importance = _normalize_importance(
            importance
        )

        with self._lock:

            entry = self._find_by_key(
                normalized_key
            )

            if entry is None:
                return None

            entry.importance = (
                normalized_importance
            )
            entry.updated_at = iso_timestamp()

            if not self.save():
                return None

            snapshot = entry.clone()

        self._emit_updated(
            snapshot,
            "importance_updated",
        )

        return snapshot

    def update_category(
        self,
        key: str,
        category: MemoryCategory | str,
    ) -> Optional[MemoryEntry]:

        normalized_key = _normalize_key(key)
        normalized_category = _normalize_category(
            category
        )

        with self._lock:

            entry = self._find_by_key(
                normalized_key
            )

            if entry is None:
                return None

            entry.category = normalized_category
            entry.updated_at = iso_timestamp()

            if not self.save():
                return None

            snapshot = entry.clone()

        self._emit_updated(
            snapshot,
            "category_updated",
        )

        return snapshot

    def update_value(
        self,
        key: str,
        value: str,
    ) -> Optional[MemoryEntry]:

        normalized_key = _normalize_key(key)
        normalized_value = _validate_value(value)

        with self._lock:

            entry = self._find_by_key(
                normalized_key
            )

            if entry is None:
                return None

            entry.value = normalized_value
            entry.updated_at = iso_timestamp()

            if not self.save():
                return None

            snapshot = entry.clone()

        self._emit_updated(
            snapshot,
            "value_updated",
        )

        return snapshot

    # ========================================================================
    # Persistence
    # ========================================================================

    def _build_payload(self) -> dict[str, Any]:

        return {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "assistant_name": ASSISTANT_NAME,
            "voice_gender": FIXED_VOICE_GENDER,
            "updated_at": iso_timestamp(),
            "entries": [
                entry.to_dict()
                for entry in self._entries.values()
            ],
        }

    def load(self) -> None:
        """
        Load memory from disk.

        Invalid individual entries are skipped. A broken root payload does not
        prevent AssistantX from starting.
        """

        with self._lock:

            try:

                raw = read_json(
                    self._path,
                    default={
                        "schema_version": 1,
                        "entries": [],
                    },
                )

                if not isinstance(raw, dict):
                    raise MemoryValidationError(
                        "Memory root must be a dictionary."
                    )

                raw_entries = raw.get(
                    "entries",
                    [],
                )

                if not isinstance(
                    raw_entries,
                    list,
                ):
                    raw_entries = []

                loaded: dict[
                    str,
                    MemoryEntry,
                ] = {}

                skipped = 0

                for index, item in enumerate(
                    raw_entries
                ):

                    try:

                        entry = MemoryEntry.from_dict(
                            item
                        )

                        # Protect against duplicate IDs.
                        if entry.id in loaded:
                            entry.id = str(
                                uuid.uuid4()
                            )

                        loaded[
                            entry.id
                        ] = entry

                    except Exception as exc:

                        skipped += 1

                        logger.warning(
                            "Skipping invalid memory entry "
                            "at index %d: %s",
                            index,
                            exc,
                        )

                self._entries = loaded
                self._loaded = True
                self._load_count += 1
                self._skipped_entries += skipped
                self._last_load_at = iso_timestamp()
                self._last_error = None

                logger.info(
                    "Memory loaded: %d entries, skipped=%d, path=%s",
                    len(loaded),
                    skipped,
                    self._path,
                )

            except Exception as exc:

                self._entries = {}
                self._loaded = True
                self._load_failures += 1
                self._last_load_at = iso_timestamp()
                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                logger.error(
                    "Memory load failed: %s",
                    self._last_error,
                    exc_info=True,
                )

    def save(self) -> bool:
        """
        Persist memory state.

        Uses the project's existing write_json helper so all filesystem
        behavior remains centralized.
        """

        with self._lock:

            payload = self._build_payload()

            try:

                result = write_json(
                    self._path,
                    payload,
                )

                if result is False:
                    raise OSError(
                        "write_json returned False"
                    )

                self._save_count += 1
                self._last_save_at = iso_timestamp()
                self._last_error = None

                return True

            except Exception as exc:

                self._save_failures += 1
                self._last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                logger.error(
                    "Memory save failed: %s",
                    self._last_error,
                    exc_info=True,
                )

                return False

    def reload(self) -> None:
        """Reload memory from persistent storage."""

        self.load()

    # ========================================================================
    # Utility
    # ========================================================================

    def count(
        self,
        category: Optional[
            MemoryCategory | str
        ] = None,
    ) -> int:

        if category is None:

            with self._lock:
                return len(self._entries)

        normalized_category = _normalize_category(
            category
        )

        with self._lock:

            return sum(
                1
                for entry in self._entries.values()
                if entry.category
                == normalized_category
            )

    def exists(
        self,
        key: str,
    ) -> bool:

        return self.get(key) is not None

    def clear(self) -> int:
        """Clear all memories."""

        return self.forget_all()

    def path(self) -> Path:
        """Return configured memory file path."""

        return self._path

    # ========================================================================
    # Statistics
    # ========================================================================

    def stats(self) -> dict[str, Any]:

        with self._lock:

            entries = list(
                self._entries.values()
            )

            categories = {
                category.value: 0
                for category in MemoryCategory
            }

            importance = {
                str(level): 0
                for level in range(
                    MIN_IMPORTANCE,
                    MAX_IMPORTANCE + 1,
                )
            }

            sources: dict[str, int] = {}

            languages: dict[str, int] = {}

            voice_count = 0

            for entry in entries:

                categories[
                    entry.category.value
                ] += 1

                importance[
                    str(entry.importance)
                ] += 1

                sources[
                    entry.source
                ] = (
                    sources.get(
                        entry.source,
                        0,
                    )
                    + 1
                )

                if entry.language:

                    languages[
                        entry.language
                    ] = (
                        languages.get(
                            entry.language,
                            0,
                        )
                        + 1
                    )

                if entry.is_voice:
                    voice_count += 1

            return {
                "total": len(entries),
                "voice_memories": voice_count,
                "loaded": self._loaded,
                "path": str(self._path),
                "schema_version": MEMORY_SCHEMA_VERSION,
                "categories": categories,
                "importance": importance,
                "sources": sources,
                "languages": languages,
                "load_count": self._load_count,
                "save_count": self._save_count,
                "load_failures": self._load_failures,
                "save_failures": self._save_failures,
                "skipped_entries": self._skipped_entries,
                "last_load_at": self._last_load_at,
                "last_save_at": self._last_save_at,
                "last_error": self._last_error,
            }

    def diagnostics(self) -> dict[str, Any]:

        stats = self.stats()

        return {
            "module": "core.memory",
            "status": (
                "degraded"
                if stats["save_failures"]
                or stats["load_failures"]
                else "ok"
            ),
            "assistant_name": ASSISTANT_NAME,
            "voice_gender": FIXED_VOICE_GENDER,
            "supported_languages": list(
                SUPPORTED_LANGUAGES
            ),
            "loaded": stats["loaded"],
            "memory_count": stats["total"],
            "voice_memories": stats[
                "voice_memories"
            ],
            "path": str(self._path),
            "file_exists": self._path.exists(),
            "schema_version": MEMORY_SCHEMA_VERSION,
            "save_failures": stats[
                "save_failures"
            ],
            "load_failures": stats[
                "load_failures"
            ],
            "skipped_entries": stats[
                "skipped_entries"
            ],
            "last_error": stats[
                "last_error"
            ],
        }

    # ========================================================================
    # Representation
    # ========================================================================

    def __len__(self) -> int:
        return self.count()

    def __contains__(self, key: object) -> bool:

        try:
            return self.exists(str(key))
        except Exception:
            return False

    def __repr__(self) -> str:

        return (
            f"MemoryManager("
            f"path={str(self._path)!r}, "
            f"entries={self.count()}, "
            f"loaded={self._loaded}"
            f")"
        )


# ============================================================================
# Global Memory Manager
# ============================================================================

memory_manager = MemoryManager()


# ============================================================================
# Global Convenience API
# ============================================================================


def remember(
    key: str,
    value: str,
    category: MemoryCategory | str = MemoryCategory.FACT,
    importance: int = DEFAULT_IMPORTANCE,
    source: str = DEFAULT_SOURCE,
    **kwargs: Any,
) -> MemoryEntry:

    return memory_manager.remember(
        key=key,
        value=value,
        category=category,
        importance=importance,
        source=source,
        **kwargs,
    )


def remember_voice(
    key: str,
    value: str,
    *,
    category: MemoryCategory | str = MemoryCategory.FACT,
    importance: int = DEFAULT_IMPORTANCE,
    language: str = "en",
    confidence: Optional[float] = None,
    turn_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> MemoryEntry:

    return memory_manager.remember_voice(
        key=key,
        value=value,
        category=category,
        importance=importance,
        language=language,
        confidence=confidence,
        turn_id=turn_id,
        metadata=metadata,
    )


def recall(
    key: str,
) -> Optional[str]:

    return memory_manager.recall(key)


def forget(
    key: str,
) -> bool:

    return memory_manager.forget(key)


def search_memory(
    query: str,
    limit: Optional[int] = None,
    *,
    category: Optional[
        MemoryCategory | str
    ] = None,
    min_importance: int = MIN_IMPORTANCE,
    source: Optional[str] = None,
    language: Optional[str] = None,
) -> list[MemoryEntry]:

    return memory_manager.search(
        query=query,
        category=category,
        min_importance=min_importance,
        limit=limit,
        source=source,
        language=language,
    )


def memory_context(
    limit: int = DEFAULT_CONTEXT_LIMIT,
    min_importance: int = DEFAULT_MIN_IMPORTANCE,
    category: Optional[
        MemoryCategory | str
    ] = None,
) -> str:

    return memory_manager.as_context_string(
        limit=limit,
        min_importance=min_importance,
        category=category,
    )


def memory_context_entries(
    limit: int = DEFAULT_CONTEXT_LIMIT,
    min_importance: int = DEFAULT_MIN_IMPORTANCE,
    category: Optional[
        MemoryCategory | str
    ] = None,
) -> list[dict[str, Any]]:

    return memory_manager.as_context_entries(
        limit=limit,
        min_importance=min_importance,
        category=category,
    )


def memory_count() -> int:

    return memory_manager.count()


def memory_diagnostics() -> dict[str, Any]:

    return memory_manager.diagnostics()


# Backward-compatible aliases.
get = memory_manager.get
get_memory = memory_manager.get


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Identity
    "ASSISTANT_NAME",
    "FIXED_VOICE_GENDER",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_SOURCES",

    # Constants
    "DEFAULT_CONTEXT_LIMIT",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_MIN_IMPORTANCE",
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SOURCE",
    "MAX_IMPORTANCE",
    "MAX_KEY_LENGTH",
    "MAX_VALUE_LENGTH",
    "MEMORY_SCHEMA_VERSION",
    "MIN_IMPORTANCE",

    # Enums
    "MemoryCategory",

    # Classes
    "MemoryEntry",
    "MemoryManager",

    # Exceptions
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryValidationError",

    # Global manager
    "memory_manager",

    # Functions
    "forget",
    "get",
    "get_memory",
    "memory_context",
    "memory_context_entries",
    "memory_count",
    "memory_diagnostics",
    "recall",
    "remember",
    "remember_voice",
    "search_memory",
]
