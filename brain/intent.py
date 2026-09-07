"""
intent.py
=========
Defines the core data structures used throughout the brain/ package to
represent a classified user intent: what the user wants, which entities
(parameters) were extracted from their utterance, and how confident the
classifier is.

This module has NO classification logic itself (see classifier.py for
that) — it's purely the shared vocabulary/schema that classifier.py,
decision_engine.py, and core/command_router.py all speak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from config.constants import IntentCategory


@dataclass
class Entity:
    """
    A single extracted parameter from an utterance, e.g. for
    "open chrome", entity=Entity(name='app_name', value='chrome').
    """

    name: str
    value: Any
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    confidence: float = 1.0

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Entity({self.name}={self.value!r}, conf={self.confidence:.2f})"


@dataclass
class Intent:
    """
    The fully resolved understanding of a single user utterance.

    Produced by brain/classifier.py, consumed by
    brain/decision_engine.py and core/command_router.py to decide what
    action to take.
    """

    category: IntentCategory
    raw_text: str
    confidence: float = 0.0
    entities: list[Entity] = field(default_factory=list)
    sub_intent: Optional[str] = None  # e.g. category=APP_LAUNCH, sub_intent='open'
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_entity(self, name: str) -> Optional[Entity]:
        """Fetch the first entity matching `name`, or None if absent."""
        for entity in self.entities:
            if entity.name == name:
                return entity
        return None

    def get_entity_value(self, name: str, default: Any = None) -> Any:
        """Convenience shortcut to fetch just the value of a named entity."""
        entity = self.get_entity(name)
        return entity.value if entity is not None else default

    def has_entity(self, name: str) -> bool:
        return self.get_entity(name) is not None

    def is_confident(self, threshold: float = 0.55) -> bool:
        """Whether this intent was classified with sufficient confidence
        to act on directly without asking the user to clarify."""
        return self.confidence >= threshold

    def is_actionable(self) -> bool:
        """Whether this intent maps to a concrete automation/service action
        (as opposed to falling through to general conversation)."""
        return self.category not in (IntentCategory.GENERAL_CHAT, IntentCategory.UNKNOWN)

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "raw_text": self.raw_text,
            "confidence": round(self.confidence, 4),
            "entities": [
                {"name": e.name, "value": e.value, "confidence": round(e.confidence, 4)}
                for e in self.entities
            ],
            "sub_intent": self.sub_intent,
            "requires_confirmation": self.requires_confirmation,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"Intent(category={self.category.value}, sub_intent={self.sub_intent!r}, "
            f"confidence={self.confidence:.2f}, entities={len(self.entities)})"
        )


# --------------------------------------------------------------------------- #
# Well-known sub-intents, grouped by category. These are string constants
# (rather than a nested enum) so classifier.py's rule tables stay simple
# to read and extend.
# --------------------------------------------------------------------------- #

class SubIntent:
    """Namespaced string constants for common sub-intents within a category."""

    # SYSTEM_CONTROL
    SHUTDOWN = "shutdown"
    RESTART = "restart"
    SLEEP = "sleep"
    LOCK = "lock"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"

    # APP_LAUNCH
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"

    # FILE_OPERATION
    CREATE_FILE = "create_file"
    DELETE_FILE = "delete_file"
    RENAME_FILE = "rename_file"
    SEARCH_FILE = "search_file"
    OPEN_FOLDER = "open_folder"

    # MUSIC
    PLAY_MUSIC = "play_music"
    PAUSE_MUSIC = "pause_music"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"

    # WEB_SEARCH
    GENERAL_SEARCH = "general_search"
    OPEN_WEBSITE = "open_website"

    # REMINDER
    SET_REMINDER = "set_reminder"
    LIST_REMINDERS = "list_reminders"
    CANCEL_REMINDER = "cancel_reminder"

    # CALCULATION
    ARITHMETIC = "arithmetic"
    UNIT_CONVERSION = "unit_conversion"


def unknown_intent(raw_text: str) -> Intent:
    """Factory for the canonical 'could not classify' result."""
    return Intent(category=IntentCategory.UNKNOWN, raw_text=raw_text, confidence=0.0)


def general_chat_intent(raw_text: str, confidence: float = 1.0) -> Intent:
    """Factory for utterances that should just be routed to the AI chat provider."""
    return Intent(category=IntentCategory.GENERAL_CHAT, raw_text=raw_text, confidence=confidence)
    