"""
memory.py
=========
Long-term memory store: durable facts, preferences, and reminders about
the user that should persist far beyond a single conversation session
(unlike core/history.py, which is the raw recent transcript).

Examples of what belongs in memory:
    - "The user's name is Rahim."
    - "The user prefers Bangla for casual conversation."
    - "The user's favorite music genre is lo-fi."
    - "The user mentioned they have a dentist appointment on the 12th."

Memory entries are simple key/value-ish records with categories, so the
brain/context_manager.py can selectively recall only what's relevant to
the current conversation rather than dumping the entire memory store
into every prompt (which would waste context tokens).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from config.constants import MEMORY_JSON
from core.event_bus import Events, event_bus
from core.logger import get_logger
from core.utils import normalize_text, now_iso, read_json, write_json

logger = get_logger(__name__)


class MemoryCategory(str, Enum):
    IDENTITY = "identity"          # name, age, location, etc.
    PREFERENCE = "preference"      # likes/dislikes, favorite settings
    FACT = "fact"                  # arbitrary remembered facts
    COMMITMENT = "commitment"      # appointments, promises, deadlines
    RELATIONSHIP = "relationship"  # family/friends mentioned by the user


@dataclass
class MemoryEntry:
    """A single durable memory record."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    category: MemoryCategory = MemoryCategory.FACT
    key: str = ""             # short identifier, e.g. "user_name"
    value: str = ""           # the actual remembered content
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    importance: int = 1       # 1 (low) .. 5 (high) — affects recall priority
    source: str = "conversation"  # where this memory came from

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            category=MemoryCategory(data.get("category", MemoryCategory.FACT.value)),
            key=data.get("key", ""),
            value=data.get("value", ""),
            created_at=data.get("created_at", now_iso()),
            updated_at=data.get("updated_at", now_iso()),
            importance=data.get("importance", 1),
            source=data.get("source", "conversation"),
        )


class MemoryManager:
    """Thread-safe CRUD interface over the long-term memory store."""

    def __init__(self, path: Path = MEMORY_JSON) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self.load()

    # -- mutation ---------------------------------------------------------- #

    def remember(
        self,
        key: str,
        value: str,
        category: MemoryCategory = MemoryCategory.FACT,
        importance: int = 1,
        source: str = "conversation",
    ) -> MemoryEntry:
        """
        Store or update a memory entry. If an entry with the same `key`
        already exists, its value/importance/timestamp are updated
        in-place rather than creating a duplicate.
        """
        normalized_key = normalize_text(key).replace(" ", "_")
        with self._lock:
            existing = self._find_by_key(normalized_key)
            if existing:
                existing.value = value
                existing.importance = max(existing.importance, importance)
                existing.updated_at = now_iso()
                entry = existing
                logger.debug("Memory updated: %s = %s", normalized_key, value)
            else:
                entry = MemoryEntry(
                    key=normalized_key,
                    value=value,
                    category=category,
                    importance=importance,
                    source=source,
                )
                self._entries[entry.id] = entry
                logger.debug("Memory created: %s = %s", normalized_key, value)
            self.save()

        event_bus.emit(Events.MEMORY_UPDATED, entry.to_dict())
        return entry

    def forget(self, key: str) -> bool:
        """Remove a memory entry by key. Returns True if something was removed."""
        normalized_key = normalize_text(key).replace(" ", "_")
        with self._lock:
            entry = self._find_by_key(normalized_key)
            if entry:
                del self._entries[entry.id]
                self.save()
                logger.info("Memory forgotten: %s", normalized_key)
                return True
        return False

    def forget_all(self, category: Optional[MemoryCategory] = None) -> int:
        """Clear all memory, optionally scoped to one category. Returns count removed."""
        with self._lock:
            if category is None:
                count = len(self._entries)
                self._entries.clear()
            else:
                to_remove = [eid for eid, e in self._entries.items() if e.category == category]
                for eid in to_remove:
                    del self._entries[eid]
                count = len(to_remove)
            self.save()
        logger.info("Forgot %d memory entr(y/ies) (category=%s).", count, category)
        return count

    # -- access ------------------------------------------------------------ #

    def _find_by_key(self, normalized_key: str) -> Optional[MemoryEntry]:
        for entry in self._entries.values():
            if entry.key == normalized_key:
                return entry
        return None

    def recall(self, key: str) -> Optional[str]:
        """Fetch a single memory value by key, or None if not remembered."""
        normalized_key = normalize_text(key).replace(" ", "_")
        with self._lock:
            entry = self._find_by_key(normalized_key)
            return entry.value if entry else None

    def all_entries(self, category: Optional[MemoryCategory] = None) -> list[MemoryEntry]:
        with self._lock:
            entries = list(self._entries.values())
        if category:
            entries = [e for e in entries if e.category == category]
        return sorted(entries, key=lambda e: e.importance, reverse=True)

    def search(self, query: str) -> list[MemoryEntry]:
        """Naive substring search over memory keys and values."""
        query_norm = normalize_text(query)
        with self._lock:
            return [
                e for e in self._entries.values()
                if query_norm in normalize_text(e.key) or query_norm in normalize_text(e.value)
            ]

    def as_context_string(self, limit: int = 10, min_importance: int = 1) -> str:
        """
        Render the most important memory entries as a short bullet-point
        string suitable for injection into an AI system prompt (see
        config/prompts.py build_system_prompt()).
        """
        entries = [e for e in self.all_entries() if e.importance >= min_importance][:limit]
        if not entries:
            return ""
        return "\n".join(f"- {e.value}" for e in entries)

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    # -- persistence --------------------------------------------------------- #

    def load(self) -> None:
        raw = read_json(self._path, default={"entries": []})
        with self._lock:
            self._entries = {
                e["id"]: MemoryEntry.from_dict(e) for e in raw.get("entries", [])
            }
        logger.info("Loaded %d memory entr(y/ies) from %s.", len(self._entries), self._path)

    def save(self) -> None:
        with self._lock:
            payload = {
                "updated_at": now_iso(),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
        if not write_json(self._path, payload):
            logger.error("Failed to persist memory to %s.", self._path)


# Module-level singleton.
memory_manager: MemoryManager = MemoryManager()
