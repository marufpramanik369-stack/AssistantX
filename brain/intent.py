"""
brain/intent.py
===============

Shared intent and entity schema for AssistantX.

This module contains only the data structures and small helpers required
to represent classified user intent.

Responsibilities
----------------
- Represent extracted entities.
- Represent classified intents.
- Validate and normalize intent data.
- Provide safe entity lookup helpers.
- Provide serialization/deserialization helpers.
- Provide common sub-intent constants.
- Provide factory helpers for UNKNOWN and GENERAL_CHAT intents.

Classification logic belongs in:
    brain/classifier.py

Decision logic belongs in:
    brain/decision_engine.py

Command execution belongs in:
    core/command_router.py
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from config.constants import IntentCategory

# ============================================================================ #
# Constants
# ============================================================================ #

DEFAULT_INTENT_CONFIDENCE = 0.0
DEFAULT_ENTITY_CONFIDENCE = 1.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.55

MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0


# ============================================================================ #
# Exceptions
# ============================================================================ #


class IntentError(Exception):
    """Base exception for intent-related errors."""


class IntentValidationError(IntentError):
    """Raised when intent data is invalid."""


class EntityValidationError(IntentError):
    """Raised when entity data is invalid."""


# ============================================================================ #
# Helpers
# ============================================================================ #


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    """
    Convert a confidence value to a safe float between 0.0 and 1.0.

    Invalid values fall back to ``default``.
    """

    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default

    if confidence < MIN_CONFIDENCE:
        return MIN_CONFIDENCE

    if confidence > MAX_CONFIDENCE:
        return MAX_CONFIDENCE

    return confidence


def _normalize_text(value: Any) -> str:
    """Normalize text while keeping the original semantic content."""

    if value is None:
        return ""

    return str(value).strip()


def _normalize_name(value: Any) -> str:
    """Normalize entity names and metadata keys."""

    return _normalize_text(value).lower().replace(" ", "_")


def _normalize_category(value: Any) -> IntentCategory:
    """
    Convert a value into ``IntentCategory``.

    Supports:
    - IntentCategory members
    - enum values
    - enum names
    """

    if isinstance(value, IntentCategory):
        return value

    if value is None:
        raise IntentValidationError("Intent category cannot be None.")

    text = str(value).strip()

    # Try enum value.
    for category in IntentCategory:
        if text == category.value:
            return category

    # Try enum name.
    try:
        return IntentCategory[text.upper()]
    except KeyError as exc:
        raise IntentValidationError(
            f"Unknown intent category: {value!r}"
        ) from exc


# ============================================================================ #
# Entity
# ============================================================================ #


@dataclass(slots=True)
class Entity:
    """
    Represents one extracted parameter from a user utterance.

    Example
    -------
    User:
        "open chrome"

    Entity:
        Entity(
            name="app_name",
            value="chrome"
        )
    """

    name: str
    value: Any

    start_index: int | None = None
    end_index: int | None = None

    confidence: float = DEFAULT_ENTITY_CONFIDENCE

    def __post_init__(self) -> None:
        """Validate and normalize entity fields."""

        self.name = _normalize_name(self.name)

        if not self.name:
            raise EntityValidationError(
                "Entity name cannot be empty."
            )

        self.confidence = _clamp_confidence(
            self.confidence,
            default=DEFAULT_ENTITY_CONFIDENCE,
        )

        self._validate_indexes()

    # --------------------------------------------------------------------- #
    # Validation
    # --------------------------------------------------------------------- #

    def _validate_indexes(self) -> None:
        """Validate optional text span indexes."""

        if self.start_index is not None:
            if not isinstance(self.start_index, int):
                raise EntityValidationError(
                    "start_index must be an integer or None."
                )

            if self.start_index < 0:
                raise EntityValidationError(
                    "start_index cannot be negative."
                )

        if self.end_index is not None:
            if not isinstance(self.end_index, int):
                raise EntityValidationError(
                    "end_index must be an integer or None."
                )

            if self.end_index < 0:
                raise EntityValidationError(
                    "end_index cannot be negative."
                )

        if (
            self.start_index is not None
            and self.end_index is not None
            and self.end_index < self.start_index
        ):
            raise EntityValidationError(
                "end_index cannot be smaller than start_index."
            )

    # --------------------------------------------------------------------- #
    # Properties
    # --------------------------------------------------------------------- #

    @property
    def span(self) -> tuple[int, int] | None:
        """Return the entity's text span if indexes are available."""

        if self.start_index is None or self.end_index is None:
            return None

        return self.start_index, self.end_index

    @property
    def is_confident(self) -> bool:
        """Whether this entity has a reasonably strong confidence."""

        return self.confidence >= DEFAULT_CONFIDENCE_THRESHOLD

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entity into a JSON-friendly dictionary."""

        return {
            "name": self.name,
            "value": self.value,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Entity:
        """Create an Entity from a dictionary."""

        if not isinstance(data, Mapping):
            raise EntityValidationError(
                "Entity data must be a mapping."
            )

        return cls(
            name=data.get("name", ""),
            value=data.get("value"),
            start_index=data.get("start_index"),
            end_index=data.get("end_index"),
            confidence=data.get(
                "confidence",
                DEFAULT_ENTITY_CONFIDENCE,
            ),
        )

    # --------------------------------------------------------------------- #
    # Representation
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:
        return (
            f"Entity("
            f"name={self.name!r}, "
            f"value={self.value!r}, "
            f"confidence={self.confidence:.2f}"
            f")"
        )


# ============================================================================ #
# Intent
# ============================================================================ #


@dataclass(slots=True)
class Intent:
    """
    Fully resolved understanding of one user utterance.

    Produced by:
        brain/classifier.py

    Consumed by:
        brain/decision_engine.py
        brain/response_generator.py
        core/command_router.py
    """

    category: IntentCategory
    raw_text: str

    confidence: float = DEFAULT_INTENT_CONFIDENCE

    entities: list[Entity] = field(default_factory=list)

    sub_intent: str | None = None

    requires_confirmation: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate the intent."""

        self.category = _normalize_category(self.category)

        self.raw_text = _normalize_text(self.raw_text)

        self.confidence = _clamp_confidence(
            self.confidence,
            default=DEFAULT_INTENT_CONFIDENCE,
        )

        self.sub_intent = (
            _normalize_name(self.sub_intent)
            if self.sub_intent
            else None
        )

        self.requires_confirmation = bool(
            self.requires_confirmation
        )

        if self.entities is None:
            self.entities = []

        self.entities = self._normalize_entities(
            self.entities
        )

        if self.metadata is None:
            self.metadata = {}

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _normalize_entities(
        entities: Iterable[Entity | Mapping[str, Any]],
    ) -> list[Entity]:
        """Normalize entity objects and dictionary representations."""

        normalized: list[Entity] = []

        for entity in entities:
            if isinstance(entity, Entity):
                normalized.append(entity)

            elif isinstance(entity, Mapping):
                normalized.append(
                    Entity.from_dict(entity)
                )

            else:
                raise EntityValidationError(
                    "Each entity must be an Entity or mapping."
                )

        return normalized

    # --------------------------------------------------------------------- #
    # Entity access
    # --------------------------------------------------------------------- #

    def get_entity(
        self,
        name: str,
    ) -> Entity | None:
        """
        Return the first entity matching ``name``.

        Returns:
            Entity | None
        """

        normalized_name = _normalize_name(name)

        for entity in self.entities:
            if entity.name == normalized_name:
                return entity

        return None

    def get_entities(
        self,
        name: str,
    ) -> list[Entity]:
        """Return all entities matching ``name``."""

        normalized_name = _normalize_name(name)

        return [
            entity
            for entity in self.entities
            if entity.name == normalized_name
        ]

    def get_entity_value(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """Return the value of the first matching entity."""

        entity = self.get_entity(name)

        if entity is None:
            return default

        return entity.value

    def has_entity(self, name: str) -> bool:
        """Return True when the intent contains the requested entity."""

        return self.get_entity(name) is not None

    # --------------------------------------------------------------------- #
    # Intent state
    # --------------------------------------------------------------------- #

    def is_confident(
        self,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> bool:
        """
        Check whether the intent confidence reaches the given threshold.
        """

        threshold = _clamp_confidence(threshold)

        return self.confidence >= threshold

    def is_unknown(self) -> bool:
        """Return True when classification failed."""

        return self.category == IntentCategory.UNKNOWN

    def is_general_chat(self) -> bool:
        """Return True when this is a normal AI conversation."""

        return self.category == IntentCategory.GENERAL_CHAT

    def is_actionable(self) -> bool:
        """
        Return True when this intent represents an actionable operation.
        """

        return self.category not in (
            IntentCategory.GENERAL_CHAT,
            IntentCategory.UNKNOWN,
        )

    def needs_confirmation(self) -> bool:
        """Return whether execution requires confirmation."""

        return self.requires_confirmation

    # --------------------------------------------------------------------- #
    # Metadata
    # --------------------------------------------------------------------- #

    def get_metadata(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """Safely retrieve intent metadata."""

        return self.metadata.get(key, default)

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> None:
        """Set one metadata value."""

        self.metadata[str(key)] = value

    # --------------------------------------------------------------------- #
    # Serialization
    # --------------------------------------------------------------------- #

    def to_dict(
        self,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """
        Convert intent into a JSON-friendly dictionary.

        ``metadata`` can be excluded when storing compact results.
        """

        data: dict[str, Any] = {
            "category": self.category.value,
            "raw_text": self.raw_text,
            "confidence": round(self.confidence, 4),
            "entities": [
                entity.to_dict()
                for entity in self.entities
            ],
            "sub_intent": self.sub_intent,
            "requires_confirmation": self.requires_confirmation,
        }

        if include_metadata:
            data["metadata"] = dict(self.metadata)

        return data

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> Intent:
        """Create an Intent from a serialized dictionary."""

        if not isinstance(data, Mapping):
            raise IntentValidationError(
                "Intent data must be a mapping."
            )

        raw_entities = data.get("entities", [])

        if raw_entities is None:
            raw_entities = []

        return cls(
            category=data.get(
                "category",
                IntentCategory.UNKNOWN.value,
            ),
            raw_text=data.get("raw_text", ""),
            confidence=data.get(
                "confidence",
                DEFAULT_INTENT_CONFIDENCE,
            ),
            entities=raw_entities,
            sub_intent=data.get("sub_intent"),
            requires_confirmation=data.get(
                "requires_confirmation",
                False,
            ),
            metadata=dict(
                data.get("metadata") or {}
            ),
        )

    # --------------------------------------------------------------------- #
    # Provider / debugging helpers
    # --------------------------------------------------------------------- #

    def summary(self) -> str:
        """Return a short human-readable intent summary."""

        category = self.category.value

        if self.sub_intent:
            category = f"{category}:{self.sub_intent}"

        return (
            f"{category} "
            f"(confidence={self.confidence:.2f}, "
            f"entities={len(self.entities)})"
        )

    def __repr__(self) -> str:
        return (
            f"Intent("
            f"category={self.category.value!r}, "
            f"sub_intent={self.sub_intent!r}, "
            f"confidence={self.confidence:.2f}, "
            f"entities={len(self.entities)}, "
            f"requires_confirmation="
            f"{self.requires_confirmation}"
            f")"
        )


# ============================================================================ #
# Sub Intent
# ============================================================================ #


class SubIntent:
    """
    Namespaced constants for common intent actions.

    Strings are intentionally used instead of an Enum so classifier rule
    tables remain simple and extensible.
    """

    # ------------------------------------------------------------------ #
    # SYSTEM CONTROL
    # ------------------------------------------------------------------ #

    SHUTDOWN = "shutdown"
    RESTART = "restart"
    SLEEP = "sleep"
    LOCK = "lock"

    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"

    BRIGHTNESS_UP = "brightness_up"
    BRIGHTNESS_DOWN = "brightness_down"

    # ------------------------------------------------------------------ #
    # APPLICATION
    # ------------------------------------------------------------------ #

    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"

    # ------------------------------------------------------------------ #
    # FILE / FOLDER
    # ------------------------------------------------------------------ #

    CREATE_FILE = "create_file"
    DELETE_FILE = "delete_file"
    RENAME_FILE = "rename_file"
    SEARCH_FILE = "search_file"
    OPEN_FOLDER = "open_folder"

    # ------------------------------------------------------------------ #
    # MUSIC
    # ------------------------------------------------------------------ #

    PLAY_MUSIC = "play_music"
    PAUSE_MUSIC = "pause_music"
    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"

    # ------------------------------------------------------------------ #
    # WEB
    # ------------------------------------------------------------------ #

    GENERAL_SEARCH = "general_search"
    OPEN_WEBSITE = "open_website"

    # ------------------------------------------------------------------ #
    # REMINDER
    # ------------------------------------------------------------------ #

    SET_REMINDER = "set_reminder"
    LIST_REMINDERS = "list_reminders"
    CANCEL_REMINDER = "cancel_reminder"

    # ------------------------------------------------------------------ #
    # CALCULATION
    # ------------------------------------------------------------------ #

    ARITHMETIC = "arithmetic"
    UNIT_CONVERSION = "unit_conversion"


# ============================================================================ #
# Factory Helpers
# ============================================================================ #


def unknown_intent(
    raw_text: str,
) -> Intent:
    """
    Create the canonical UNKNOWN intent.

    Used when the classifier cannot confidently determine what the
    user wants.
    """

    return Intent(
        category=IntentCategory.UNKNOWN,
        raw_text=raw_text,
        confidence=DEFAULT_INTENT_CONFIDENCE,
    )


def general_chat_intent(
    raw_text: str,
    confidence: float = 1.0,
) -> Intent:
    """
    Create a GENERAL_CHAT intent.

    This is normally routed to the configured AI provider.
    """

    return Intent(
        category=IntentCategory.GENERAL_CHAT,
        raw_text=raw_text,
        confidence=confidence,
    )


def create_intent(
    category: IntentCategory | str,
    raw_text: str,
    *,
    confidence: float = DEFAULT_INTENT_CONFIDENCE,
    entities: Iterable[Entity | Mapping[str, Any]] | None = None,
    sub_intent: str | None = None,
    requires_confirmation: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> Intent:
    """
    Generic convenience factory for creating Intent objects.

    Example
    -------
    intent = create_intent(
        IntentCategory.APP_LAUNCH,
        "open chrome",
        confidence=0.94,
        entities=[
            Entity(
                name="app_name",
                value="chrome",
            )
        ],
        sub_intent=SubIntent.OPEN_APP,
    )
    """

    return Intent(
        category=category,
        raw_text=raw_text,
        confidence=confidence,
        entities=list(entities or []),
        sub_intent=sub_intent,
        requires_confirmation=requires_confirmation,
        metadata=dict(metadata or {}),
    )


# ============================================================================ #
# Public API
# ============================================================================ #


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_ENTITY_CONFIDENCE",
    # Constants
    "DEFAULT_INTENT_CONFIDENCE",
    "MAX_CONFIDENCE",
    "MIN_CONFIDENCE",
    # Data structures
    "Entity",
    "EntityValidationError",
    "Intent",
    # Exceptions
    "IntentError",
    "IntentValidationError",
    # Sub-intents
    "SubIntent",
    "create_intent",
    "general_chat_intent",
    # Factories
    "unknown_intent",
]