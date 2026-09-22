"""
brain/context_manager.py
========================

Short-term conversational context manager for AssistantX.

Responsibilities
----------------
- Track the last resolved intent.
- Remember recently extracted entities.
- Handle pending confirmations.
- Handle pending clarifications.
- Resolve simple anaphora such as:
      "open it"
      "delete that"
      "play this"
- Track the current conversation topic.
- Provide immutable-ish snapshots for debugging/UI.
- Handle TTL expiration safely.
- Support reset/new-chat behavior.

This module does NOT:
- classify user input
- execute commands
- call AI providers

Classification:
    brain/classifier.py

Decision making:
    brain/decision_engine.py

Command execution:
    core/command_router.py
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from brain.intent import Entity, Intent
from config.constants import (
    CONFIRMATION_KEYWORDS,
    NEGATION_KEYWORDS,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================ #
# Constants
# ============================================================================ #

DEFAULT_CONTEXT_TTL_SECONDS = 120.0

DEFAULT_ENTITY_CONFIDENCE = 0.50

DEFAULT_CLARIFICATION_CONFIDENCE = 0.80

MAX_REMEMBERED_ENTITIES = 50

MAX_ACTIVE_TOPIC_LENGTH = 200

DEFAULT_PRONOUNS = (
    "it",
    "that",
    "this",
    "them",
    "those",
)

# Entity names that are generally useful as antecedents.
_PREFERRED_ENTITY_NAMES = (
    "app_name",
    "filename",
    "folder_path",
    "file_path",
    "query",
    "song_or_query",
    "song",
    "url",
    "website",
    "reminder_text",
    "expression",
)


# ============================================================================ #
# Exceptions
# ============================================================================ #


class ContextManagerError(Exception):
    """Base exception for conversational context errors."""


class ContextValidationError(ContextManagerError):
    """Raised when invalid context data is supplied."""


# ============================================================================ #
# Utility Functions
# ============================================================================ #


def _normalize_text(value: Any) -> str:
    """Convert a value into normalized text."""

    if value is None:
        return ""

    return str(value).strip()


def _normalize_entity_name(name: Any) -> str:
    """Normalize entity names to a predictable format."""

    return (
        _normalize_text(name)
        .lower()
        .replace(" ", "_")
    )


def _keyword_matches(
    text: str,
    keywords: Iterable[str],
) -> bool:
    """
    Check whether any keyword/phrase is present in text.

    Unlike a naive ``substring in text`` check, this tries to avoid
    accidental matches such as:

        "yes" inside "yesterday"
    """

    normalized = _normalize_text(text).lower()

    if not normalized:
        return False

    for keyword in keywords:
        keyword = _normalize_text(keyword).lower()

        if not keyword:
            continue

        # Phrase / multi-word keyword.
        if " " in keyword:
            if keyword in normalized:
                return True
            continue

        # Word boundary match.
        if re.search(
            rf"\b{re.escape(keyword)}\b",
            normalized,
        ):
            return True

    return False


# ============================================================================ #
# Pending Action
# ============================================================================ #


@dataclass(slots=True)
class PendingAction:
    """
    Represents an action waiting for explicit user confirmation.

    Example
    -------
    Assistant:
        "Are you sure you want to delete 'test.txt'?"

    PendingAction:
        intent = DELETE_FILE
        prompt_shown = confirmation prompt
    """

    intent: Intent
    prompt_shown: str

    created_at: float = field(
        default_factory=time.time
    )

    def is_expired(
        self,
        ttl: float = DEFAULT_CONTEXT_TTL_SECONDS,
    ) -> bool:
        """Return True when the pending action exceeded its TTL."""

        return (
            time.time() - self.created_at
        ) > ttl

    @property
    def age_seconds(self) -> float:
        """Return current age in seconds."""

        return max(
            0.0,
            time.time() - self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize pending action."""

        return {
            "intent": self.intent.to_dict(),
            "prompt_shown": self.prompt_shown,
            "created_at": self.created_at,
            "age_seconds": round(
                self.age_seconds,
                3,
            ),
        }


# ============================================================================ #
# Pending Clarification
# ============================================================================ #


@dataclass(slots=True)
class PendingClarification:
    """
    Represents an outstanding clarification request.

    Example
    -------
    User:
        "Open the app"

    Assistant:
        "Which application?"

    PendingClarification:
        missing_entity_name = "app_name"
    """

    original_intent: Intent
    missing_entity_name: str
    question: str

    created_at: float = field(
        default_factory=time.time
    )

    def __post_init__(self) -> None:
        self.missing_entity_name = (
            _normalize_entity_name(
                self.missing_entity_name
            )
        )

        self.question = _normalize_text(
            self.question
        )

    def is_expired(
        self,
        ttl: float = DEFAULT_CONTEXT_TTL_SECONDS,
    ) -> bool:
        """Return True when clarification exceeded its TTL."""

        return (
            time.time() - self.created_at
        ) > ttl

    @property
    def age_seconds(self) -> float:
        """Return current age in seconds."""

        return max(
            0.0,
            time.time() - self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize pending clarification."""

        return {
            "original_intent": self.original_intent.to_dict(),
            "missing_entity_name": self.missing_entity_name,
            "question": self.question,
            "created_at": self.created_at,
            "age_seconds": round(
                self.age_seconds,
                3,
            ),
        }


# ============================================================================ #
# Context Snapshot
# ============================================================================ #


@dataclass(slots=True)
class ContextSnapshot:
    """
    Point-in-time representation of current conversational context.

    Primarily useful for:
    - debugging
    - dashboard
    - logging
    - diagnostics
    """

    last_intent: Intent | None

    last_entities: dict[str, Any]

    pending_action: PendingAction | None

    pending_clarification: PendingClarification | None

    active_topic: str | None

    turn_count: int = 0

    created_at: float = field(
        default_factory=time.time
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot."""

        return {
            "last_intent": (
                self.last_intent.to_dict()
                if self.last_intent
                else None
            ),
            "last_entities": deepcopy(
                self.last_entities
            ),
            "pending_action": (
                self.pending_action.to_dict()
                if self.pending_action
                else None
            ),
            "pending_clarification": (
                self.pending_clarification.to_dict()
                if self.pending_clarification
                else None
            ),
            "active_topic": self.active_topic,
            "turn_count": self.turn_count,
            "created_at": self.created_at,
        }


# ============================================================================ #
# Context Manager
# ============================================================================ #


class ContextManager:
    """
    Thread-safe short-term conversational context manager.

    Normally one instance is used for one active Assistant session.

    State includes:
        - last intent
        - recent entities
        - pending confirmation
        - pending clarification
        - active topic
        - turn count
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CONTEXT_TTL_SECONDS,
        max_remembered_entities: int = MAX_REMEMBERED_ENTITIES,
    ) -> None:

        self._lock = RLock()

        self._ttl_seconds = self._validate_ttl(
            ttl_seconds
        )

        self._max_remembered_entities = (
            self._validate_entity_limit(
                max_remembered_entities
            )
        )

        self._last_intent: Intent | None = None

        self._last_entities: dict[
            str,
            Any,
        ] = {}

        self._pending_action: PendingAction | None = None

        self._pending_clarification: PendingClarification | None = None

        self._active_topic: str | None = None

        self._turn_count = 0

        self._created_at = time.time()

    # ==================================================================== #
    # Recording
    # ==================================================================== #

    def record_intent(
        self,
        intent: Intent,
    ) -> None:
        """
        Record a newly classified/resolved intent.

        Extracted entities are remembered for future contextual
        resolution.
        """

        if not isinstance(intent, Intent):
            raise ContextValidationError(
                "intent must be an Intent instance."
            )

        with self._lock:
            self._cleanup_expired()

            self._turn_count += 1

            self._last_intent = intent

            self._active_topic = (
                intent.category.value
                if intent.category
                else None
            )

            for entity in intent.entities:
                self._remember_entity(
                    entity
                )

            logger.debug(
                "Context updated: topic=%s turn=%d entities=%d",
                self._active_topic,
                self._turn_count,
                len(self._last_entities),
            )

    def _remember_entity(
        self,
        entity: Entity,
    ) -> None:
        """Store one entity while respecting the memory limit."""

        name = _normalize_entity_name(
            entity.name
        )

        if not name:
            return

        self._last_entities[name] = entity.value

        # Keep insertion order useful for "most recent" resolution.
        self._last_entities.move_to_end(
            name
        ) if hasattr(
            self._last_entities,
            "move_to_end",
        ) else None

        while (
            len(self._last_entities)
            > self._max_remembered_entities
        ):
            oldest = next(
                iter(self._last_entities)
            )

            del self._last_entities[
                oldest
            ]

    # ==================================================================== #
    # Pending Action
    # ==================================================================== #

    def set_pending_action(
        self,
        intent: Intent,
        prompt_shown: str,
    ) -> None:
        """Store an intent waiting for confirmation."""

        if not isinstance(intent, Intent):
            raise ContextValidationError(
                "intent must be an Intent instance."
            )

        prompt_shown = _normalize_text(
            prompt_shown
        )

        if not prompt_shown:
            raise ContextValidationError(
                "prompt_shown cannot be empty."
            )

        with self._lock:
            self._pending_action = PendingAction(
                intent=intent,
                prompt_shown=prompt_shown,
            )

            # A new confirmation should replace an old clarification.
            self._pending_clarification = None

            logger.debug(
                "Pending action set: category=%s sub_intent=%s",
                intent.category.value,
                intent.sub_intent,
            )

    def set_pending_clarification(
        self,
        original_intent: Intent,
        missing_entity_name: str,
        question: str,
    ) -> None:
        """Store an intent waiting for a missing entity."""

        if not isinstance(
            original_intent,
            Intent,
        ):
            raise ContextValidationError(
                "original_intent must be an Intent instance."
            )

        missing_entity_name = (
            _normalize_entity_name(
                missing_entity_name
            )
        )

        question = _normalize_text(
            question
        )

        if not missing_entity_name:
            raise ContextValidationError(
                "missing_entity_name cannot be empty."
            )

        if not question:
            raise ContextValidationError(
                "question cannot be empty."
            )

        with self._lock:
            self._pending_clarification = (
                PendingClarification(
                    original_intent=original_intent,
                    missing_entity_name=(
                        missing_entity_name
                    ),
                    question=question,
                )
            )

            # A clarification supersedes confirmation state.
            self._pending_action = None

            logger.debug(
                "Pending clarification set: entity=%s",
                missing_entity_name,
            )

    def clear_pending(self) -> None:
        """Clear both confirmation and clarification state."""

        with self._lock:
            self._pending_action = None
            self._pending_clarification = None

    def clear_pending_action(self) -> None:
        """Clear only pending confirmation."""

        with self._lock:
            self._pending_action = None

    def clear_pending_clarification(self) -> None:
        """Clear only pending clarification."""

        with self._lock:
            self._pending_clarification = None

    # ==================================================================== #
    # Confirmation Resolution
    # ==================================================================== #

    def try_resolve_confirmation(
        self,
        text: str,
    ) -> bool | None:
        """
        Try to resolve the current confirmation.

        Returns:
            True  -> confirmed
            False -> rejected
            None  -> ambiguous/no pending confirmation
        """

        with self._lock:
            if self._pending_action is None:
                return None

            pending = self._pending_action

            if pending.is_expired(
                self._ttl_seconds
            ):
                logger.debug(
                    "Pending confirmation expired."
                )

                self._pending_action = None

                return None

            normalized = _normalize_text(
                text
            )

            if not normalized:
                return None

            confirmed = _keyword_matches(
                normalized,
                CONFIRMATION_KEYWORDS,
            )

            rejected = _keyword_matches(
                normalized,
                NEGATION_KEYWORDS,
            )

            # If both appear, do not guess.
            if confirmed and rejected:
                logger.warning(
                    "Ambiguous confirmation: "
                    "both positive and negative keywords found."
                )

                return None

            if confirmed:
                return True

            if rejected:
                return False

            return None

    # ==================================================================== #
    # Clarification Resolution
    # ==================================================================== #

    def try_resolve_clarification(
        self,
        text: str,
    ) -> Intent | None:
        """
        Resolve a pending clarification by filling its missing entity.

        The original Intent is copied instead of mutating the original
        object directly. This prevents accidental shared-state bugs.
        """

        with self._lock:
            pending = (
                self._pending_clarification
            )

            if pending is None:
                return None

            if pending.is_expired(
                self._ttl_seconds
            ):
                logger.debug(
                    "Pending clarification expired."
                )

                self._pending_clarification = None

                return None

            answer = _normalize_text(
                text
            )

            if not answer:
                return None

            # ---------------------------------------------------------- #
            # Clone the original intent.
            # ---------------------------------------------------------- #

            updated_intent = Intent.from_dict(
                pending.original_intent.to_dict()
            )

            # ---------------------------------------------------------- #
            # Replace existing entity if present.
            # ---------------------------------------------------------- #

            entity_replaced = False

            for index, entity in enumerate(
                updated_intent.entities
            ):
                if (
                    entity.name
                    == pending.missing_entity_name
                ):
                    updated_intent.entities[
                        index
                    ] = Entity(
                        name=(
                            pending.missing_entity_name
                        ),
                        value=answer,
                        confidence=(
                            DEFAULT_CLARIFICATION_CONFIDENCE
                        ),
                    )

                    entity_replaced = True
                    break

            if not entity_replaced:
                updated_intent.entities.append(
                    Entity(
                        name=(
                            pending.missing_entity_name
                        ),
                        value=answer,
                        confidence=(
                            DEFAULT_CLARIFICATION_CONFIDENCE
                        ),
                    )
                )

            # ---------------------------------------------------------- #
            # Update metadata.
            # ---------------------------------------------------------- #

            updated_intent.metadata[
                "clarification_resolved"
            ] = True

            updated_intent.metadata[
                "clarification_entity"
            ] = pending.missing_entity_name

            self._pending_clarification = None

            # Remember the newly supplied entity.
            self._last_entities[
                pending.missing_entity_name
            ] = answer

            logger.debug(
                "Clarification resolved: %s=%r",
                pending.missing_entity_name,
                answer,
            )

            return updated_intent

    # ==================================================================== #
    # Anaphora Resolution
    # ==================================================================== #

    def resolve_anaphora(
        self,
        intent: Intent,
        pronoun_entity_names: tuple[
            str,
            ...,
        ] = DEFAULT_PRONOUNS,
    ) -> Intent:
        """
        Best-effort contextual resolution for pronouns.

        Examples:
            "open chrome"
            "close it"

        The second intent can inherit:
            app_name = chrome

        Important:
            This intentionally uses conservative heuristics.
            It does not attempt full NLP coreference resolution.
        """

        if not isinstance(intent, Intent):
            raise ContextValidationError(
                "intent must be an Intent instance."
            )

        if not intent.raw_text:
            return intent

        with self._lock:
            self._cleanup_expired()

            # If the classifier already extracted useful entities,
            # do not overwrite them.
            if intent.entities:
                return intent

            if not self._contains_pronoun(
                intent.raw_text,
                pronoun_entity_names,
            ):
                return intent

            antecedent = (
                self._find_best_antecedent()
            )

            if antecedent is None:
                logger.debug(
                    "No antecedent found for: %r",
                    intent.raw_text,
                )

                return intent

            entity_name, value = antecedent

            resolved_entity = Entity(
                name=entity_name,
                value=value,
                confidence=(
                    DEFAULT_ENTITY_CONFIDENCE
                ),
            )

            intent.entities.append(
                resolved_entity
            )

            intent.metadata[
                "anaphora_resolved"
            ] = True

            intent.metadata[
                "anaphora_source"
            ] = entity_name

            logger.debug(
                "Anaphora resolved: %r -> %s=%r",
                intent.raw_text,
                entity_name,
                value,
            )

            return intent

    @staticmethod
    def _contains_pronoun(
        text: str,
        pronouns: Iterable[str],
    ) -> bool:
        """Return True if text contains one of the target pronouns."""

        normalized = _normalize_text(
            text
        ).lower()

        if not normalized:
            return False

        for pronoun in pronouns:
            pronoun = _normalize_text(
                pronoun
            ).lower()

            if not pronoun:
                continue

            if re.search(
                rf"\b{re.escape(pronoun)}\b",
                normalized,
            ):
                return True

        return False

    def _find_best_antecedent(
        self,
    ) -> tuple[str, Any] | None:
        """
        Find the most useful remembered entity.

        Preferred entity types are checked first.
        """

        # First try preferred entity names.
        for name in reversed(
            self._last_entities.keys()
        ):
            if name in _PREFERRED_ENTITY_NAMES:
                value = self._last_entities[name]

                if self._valid_antecedent_value(
                    value
                ):
                    return name, value

        # Fallback to any recent entity.
        for name in reversed(
            self._last_entities.keys()
        ):
            value = self._last_entities[name]

            if self._valid_antecedent_value(
                value
            ):
                return name, value

        return None

    @staticmethod
    def _valid_antecedent_value(
        value: Any,
    ) -> bool:
        """Check whether a remembered value is usable."""

        if value is None:
            return False

        if isinstance(value, str):
            return bool(value.strip())

        return True

    # ==================================================================== #
    # Accessors
    # ==================================================================== #

    @property
    def has_pending_action(self) -> bool:
        """Whether a non-expired confirmation exists."""

        with self._lock:
            if self._pending_action is None:
                return False

            if self._pending_action.is_expired(
                self._ttl_seconds
            ):
                self._pending_action = None
                return False

            return True

    @property
    def has_pending_clarification(self) -> bool:
        """Whether a non-expired clarification exists."""

        with self._lock:
            if (
                self._pending_clarification
                is None
            ):
                return False

            if self._pending_clarification.is_expired(
                self._ttl_seconds
            ):
                self._pending_clarification = None
                return False

            return True

    @property
    def pending_action(
        self,
    ) -> PendingAction | None:
        """Return current pending action."""

        with self._lock:
            if not self.has_pending_action:
                return None

            return self._pending_action

    @property
    def pending_clarification(
        self,
    ) -> PendingClarification | None:
        """Return current pending clarification."""

        with self._lock:
            if not self.has_pending_clarification:
                return None

            return self._pending_clarification

    @property
    def active_topic(self) -> str | None:
        """Return current active topic."""

        with self._lock:
            return self._active_topic

    @property
    def last_intent(self) -> Intent | None:
        """Return the most recently recorded intent."""

        with self._lock:
            return self._last_intent

    @property
    def turn_count(self) -> int:
        """Return number of recorded turns."""

        with self._lock:
            return self._turn_count

    @property
    def ttl_seconds(self) -> float:
        """Return configured context TTL."""

        return self._ttl_seconds

    # ==================================================================== #
    # Entity Memory
    # ==================================================================== #

    def get_remembered_entity(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """Retrieve a remembered entity value."""

        name = _normalize_entity_name(
            name
        )

        with self._lock:
            return self._last_entities.get(
                name,
                default,
            )

    def remembered_entities(
        self,
    ) -> dict[str, Any]:
        """Return a copy of all remembered entities."""

        with self._lock:
            return dict(
                self._last_entities
            )

    def forget_entity(
        self,
        name: str,
    ) -> bool:
        """Forget one remembered entity."""

        name = _normalize_entity_name(
            name
        )

        with self._lock:
            if name not in self._last_entities:
                return False

            del self._last_entities[name]

            return True

    def clear_entities(self) -> None:
        """Clear remembered entities."""

        with self._lock:
            self._last_entities.clear()

    # ==================================================================== #
    # Snapshot
    # ==================================================================== #

    def snapshot(
        self,
    ) -> ContextSnapshot:
        """
        Return a point-in-time context snapshot.

        Nested structures are copied so callers cannot accidentally
        mutate manager state.
        """

        with self._lock:
            self._cleanup_expired()

            return ContextSnapshot(
                last_intent=(
                    Intent.from_dict(
                        self._last_intent.to_dict()
                    )
                    if self._last_intent
                    else None
                ),
                last_entities=deepcopy(
                    self._last_entities
                ),
                pending_action=(
                    PendingAction(
                        intent=Intent.from_dict(
                            self._pending_action.intent.to_dict()
                        ),
                        prompt_shown=(
                            self._pending_action.prompt_shown
                        ),
                        created_at=(
                            self._pending_action.created_at
                        ),
                    )
                    if self._pending_action
                    else None
                ),
                pending_clarification=(
                    PendingClarification(
                        original_intent=Intent.from_dict(
                            self._pending_clarification
                            .original_intent
                            .to_dict()
                        ),
                        missing_entity_name=(
                            self._pending_clarification
                            .missing_entity_name
                        ),
                        question=(
                            self._pending_clarification
                            .question
                        ),
                        created_at=(
                            self._pending_clarification
                            .created_at
                        ),
                    )
                    if self._pending_clarification
                    else None
                ),
                active_topic=self._active_topic,
                turn_count=self._turn_count,
            )

    # ==================================================================== #
    # Lifecycle
    # ==================================================================== #

    def reset(self) -> None:
        """
        Fully reset conversational context.

        Intended for:
            - New Chat
            - logout/session switch
            - application reset
        """

        with self._lock:
            self._last_intent = None
            self._last_entities.clear()
            self._pending_action = None
            self._pending_clarification = None
            self._active_topic = None
            self._turn_count = 0
            self._created_at = time.time()

        logger.info(
            "Conversation context reset."
        )

    def cleanup_expired(self) -> None:
        """Public method for removing expired pending state."""

        with self._lock:
            self._cleanup_expired()

    def _cleanup_expired(self) -> None:
        """Remove expired pending state."""

        if (
            self._pending_action is not None
            and self._pending_action.is_expired(
                self._ttl_seconds
            )
        ):
            logger.debug(
                "Expired pending action removed."
            )

            self._pending_action = None

        if (
            self._pending_clarification
            is not None
            and self._pending_clarification.is_expired(
                self._ttl_seconds
            )
        ):
            logger.debug(
                "Expired pending clarification removed."
            )

            self._pending_clarification = None

    # ==================================================================== #
    # Configuration
    # ==================================================================== #

    def set_ttl(
        self,
        ttl_seconds: float,
    ) -> None:
        """Change the context TTL."""

        self._ttl_seconds = self._validate_ttl(
            ttl_seconds
        )

    # ==================================================================== #
    # Statistics / Diagnostics
    # ==================================================================== #

    def stats(self) -> dict[str, Any]:
        """Return lightweight context statistics."""

        with self._lock:
            self._cleanup_expired()

            return {
                "turn_count": self._turn_count,
                "remembered_entities": len(
                    self._last_entities
                ),
                "active_topic": self._active_topic,
                "has_pending_action": (
                    self._pending_action
                    is not None
                ),
                "has_pending_clarification": (
                    self._pending_clarification
                    is not None
                ),
                "ttl_seconds": self._ttl_seconds,
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed diagnostic information."""

        snapshot = self.snapshot()

        return {
            "component": "ContextManager",
            "status": "ready",
            "ttl_seconds": self._ttl_seconds,
            "turn_count": self._turn_count,
            "active_topic": self._active_topic,
            "remembered_entities": (
                len(self._last_entities)
            ),
            "pending_action": (
                snapshot.pending_action.to_dict()
                if snapshot.pending_action
                else None
            ),
            "pending_clarification": (
                snapshot.pending_clarification.to_dict()
                if snapshot.pending_clarification
                else None
            ),
            "last_intent": (
                snapshot.last_intent.to_dict()
                if snapshot.last_intent
                else None
            ),
        }

    def __repr__(self) -> str:
        return (
            "ContextManager("
            f"turn_count={self._turn_count}, "
            f"active_topic={self._active_topic!r}, "
            f"remembered_entities="
            f"{len(self._last_entities)}, "
            f"pending_action="
            f"{self._pending_action is not None}, "
            f"pending_clarification="
            f"{self._pending_clarification is not None}"
            ")"
        )

    # ==================================================================== #
    # Validation
    # ==================================================================== #

    @staticmethod
    def _validate_ttl(
        ttl_seconds: float,
    ) -> float:
        """Validate context TTL."""

        try:
            ttl_seconds = float(
                ttl_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ContextValidationError(
                "ttl_seconds must be numeric."
            ) from exc

        if ttl_seconds <= 0:
            raise ContextValidationError(
                "ttl_seconds must be greater than 0."
            )

        return ttl_seconds

    @staticmethod
    def _validate_entity_limit(
        limit: int,
    ) -> int:
        """Validate remembered entity limit."""

        if not isinstance(
            limit,
            int,
        ):
            raise ContextValidationError(
                "max_remembered_entities "
                "must be an integer."
            )

        if limit <= 0:
            raise ContextValidationError(
                "max_remembered_entities "
                "must be greater than 0."
            )

        return limit


# ============================================================================ #
# Global Singleton
# ============================================================================ #

context_manager = ContextManager()


# ============================================================================ #
# Convenience API
# ============================================================================ #


def get_context_snapshot() -> ContextSnapshot:
    """Return a snapshot from the global context manager."""

    return context_manager.snapshot()


def reset_context() -> None:
    """Reset the global conversational context."""

    context_manager.reset()


def context_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global context manager."""

    return context_manager.diagnostics()


# ============================================================================ #
# Public API
# ============================================================================ #

__all__ = [
    "DEFAULT_CLARIFICATION_CONFIDENCE",
    # Constants
    "DEFAULT_CONTEXT_TTL_SECONDS",
    "DEFAULT_ENTITY_CONFIDENCE",
    "DEFAULT_PRONOUNS",
    "MAX_REMEMBERED_ENTITIES",
    # Manager
    "ContextManager",
    # Exceptions
    "ContextManagerError",
    "ContextSnapshot",
    "ContextValidationError",
    # Data structures
    "PendingAction",
    "PendingClarification",
    "context_diagnostics",
    "context_manager",
    # Convenience
    "get_context_snapshot",
    "reset_context",
]
