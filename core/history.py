"""
history.py
==========
Manages the rolling conversation transcript (user + assistant turns)
that gets fed to the AI provider as context and displayed in the chat UI.

Distinct from memory.py: history is the raw, chronological turn log
(potentially trimmed for context-window reasons), while memory.py holds
distilled, durable facts extracted FROM that history.

Persistence: JSON file at data/history.json (see config.constants).
Also inserts rows into the SQLite database via database/db_manager.py
when available, for querying/searching older conversations — but never
hard-fails if the DB layer isn't ready yet, since JSON is the source of
truth for "recent context" during a session.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from config.constants import HISTORY_JSON, MAX_HISTORY_MESSAGES
from core.event_bus import Events, event_bus
from core.logger import get_logger
from core.utils import now_iso, read_json, write_json

logger = get_logger(__name__)


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """A single conversation turn."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: Role = Role.USER
    content: str = ""
    timestamp: str = field(default_factory=now_iso)
    intent: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["role"] = self.role.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            role=Role(data.get("role", Role.USER.value)),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", now_iso()),
            intent=data.get("intent"),
            metadata=data.get("metadata", {}),
        )

    def to_provider_format(self) -> dict:
        """Format expected by most LLM chat completion APIs (role/content only)."""
        role = "assistant" if self.role == Role.ASSISTANT else self.role.value
        return {"role": role, "content": self.content}


class HistoryManager:
    """
    Thread-safe manager for the active conversation transcript.

    A single HistoryManager instance typically represents "the current
    session", but sessions can be saved/archived and a new one started
    (e.g. when the user clicks "New Chat" in the dashboard).
    """

    def __init__(self, path: Path = HISTORY_JSON, max_messages: int = MAX_HISTORY_MESSAGES) -> None:
        self._path = path
        self._max_messages = max_messages
        self._lock = threading.RLock()
        self._messages: list[Message] = []
        self.session_id: str = str(uuid.uuid4())
        self.load()

    # -- mutation ---------------------------------------------------------- #

    def add(self, role: Role, content: str, intent: Optional[str] = None, **metadata) -> Message:
        """Append a new message to the transcript, trim if needed, and persist."""
        message = Message(role=role, content=content, intent=intent, metadata=metadata)
        with self._lock:
            self._messages.append(message)
            self._trim()
            self.save()

        event_bus.emit(Events.HISTORY_APPENDED, message.to_dict())
        logger.debug("History += [%s] %s", role.value, content[:80])
        return message

    def add_user_message(self, content: str, **metadata) -> Message:
        return self.add(Role.USER, content, **metadata)

    def add_assistant_message(self, content: str, intent: Optional[str] = None, **metadata) -> Message:
        return self.add(Role.ASSISTANT, content, intent=intent, **metadata)

    def _trim(self) -> None:
        """Keep only the most recent `max_messages` turns in active memory."""
        if len(self._messages) > self._max_messages:
            overflow = len(self._messages) - self._max_messages
            self._messages = self._messages[overflow:]
            logger.debug("Trimmed %d old message(s) from active history.", overflow)

    def clear(self, start_new_session: bool = True) -> None:
        """Wipe the current transcript (e.g. user clicked 'New Chat')."""
        with self._lock:
            self._messages.clear()
            if start_new_session:
                self.session_id = str(uuid.uuid4())
            self.save()
        event_bus.emit(Events.HISTORY_CLEARED, {"session_id": self.session_id})
        logger.info("Conversation history cleared.")

    # -- access ------------------------------------------------------------ #

    def all(self) -> list[Message]:
        with self._lock:
            return list(self._messages)

    def last(self, n: int = 1) -> list[Message]:
        with self._lock:
            return self._messages[-n:]

    def last_user_message(self) -> Optional[Message]:
        with self._lock:
            for msg in reversed(self._messages):
                if msg.role == Role.USER:
                    return msg
        return None

    def as_provider_messages(self, limit: Optional[int] = None) -> list[dict]:
        """
        Return the transcript formatted for an LLM chat-completion call,
        optionally limited to the most recent `limit` turns.
        """
        with self._lock:
            msgs = self._messages[-limit:] if limit else list(self._messages)
        return [m.to_provider_format() for m in msgs]

    def search(self, query: str) -> list[Message]:
        """Naive substring search over message content (case-insensitive)."""
        query_lower = query.lower()
        with self._lock:
            return [m for m in self._messages if query_lower in m.content.lower()]

    def count(self) -> int:
        with self._lock:
            return len(self._messages)

    # -- persistence ------------------------------------------------------- #

    def load(self) -> None:
        """Load the transcript from disk, if present."""
        raw = read_json(self._path, default={"session_id": self.session_id, "messages": []})
        with self._lock:
            self.session_id = raw.get("session_id", self.session_id)
            self._messages = [Message.from_dict(m) for m in raw.get("messages", [])]
        logger.info("Loaded %d historical message(s) from %s.", len(self._messages), self._path)

    def save(self) -> None:
        """Persist the transcript to disk as JSON."""
        with self._lock:
            payload = {
                "session_id": self.session_id,
                "updated_at": now_iso(),
                "messages": [m.to_dict() for m in self._messages],
            }
        success = write_json(self._path, payload)
        if not success:
            logger.error("Failed to persist conversation history to %s.", self._path)

    def export_transcript(self, path: Path) -> None:
        """Export the current session as a plain-text transcript file."""
        lines = []
        for msg in self.all():
            speaker = "You" if msg.role == Role.USER else "AssistantX"
            lines.append(f"[{msg.timestamp}] {speaker}: {msg.content}")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Transcript exported to %s.", path)


# Module-level singleton representing "the current active session".
history_manager: HistoryManager = HistoryManager()
