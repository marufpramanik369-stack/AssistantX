"""
context_manager.py
===================
Tracks short-term conversational context that spans multiple turns —
things a single Intent object can't capture alone, such as:

    - Pending confirmations ("Are you sure you want to delete X?" -> yes/no)
    - Pending clarifications ("Which Chrome window?" -> "the second one")
    - Anaphora resolution ("open it" -> resolves 'it' to the last-mentioned
      entity, e.g. a file or app name from 2 turns ago)
    - The currently active "topic" (e.g. still talking about reminders)

This sits between brain/classifier.py (per-utterance understanding) and
brain/decision_engine.py (action selection) — decision_engine consults
ContextManager to resolve ambiguous or dependent utterances before
deciding on a final action.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from brain.intent import Entity, Intent
from config.constants import CONFIRMATION_KEYWORDS, NEGATION_KEYWORDS
from core.logger import get_logger

logger = get_logger(__name__)

_CONTEXT_TTL_SECONDS = 120  # pending state expires after 2 minutes of silence on it


@dataclass
class PendingAction:
    """
    Represents an action awaiting user confirmation, e.g. after the
    classifier flags `requires_confirmation=True` on a destructive intent.
    """

    intent: Intent
    prompt_shown: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl: float = _CONTEXT_TTL_SECONDS) -> bool:
        return (time.time() - self.created_at) > ttl


@dataclass
class PendingClarification:
    """
    Represents an outstanding question the assistant asked the user,
    along with what field of the original intent the answer should fill.
    """

    original_intent: Intent
    missing_entity_name: str
    question: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl: float = _CONTEXT_TTL_SECONDS) -> bool:
        return (time.time() - self.created_at) > ttl


@dataclass
class ContextSnapshot:
    """A point-in-time view of conversational context, useful for logging/debugging."""

    last_intent: Optional[Intent]
    last_entities: dict[str, Any]
    pending_action: Optional[PendingAction]
    pending_clarification: Optional[PendingClarification]
    active_topic: Optional[str]


class ContextManager:
    """
    Holds mutable, short-lived conversational state for the current
    session. One instance typically lives for the lifetime of the
    Assistant object (core/assistant.py owns it).
    """

    def __init__(self) -> None:
        self._last_intent: Optional[Intent] = None
        self._last_entities: dict[str, Any] = {}  # accumulated across recent turns
        self._pending_action: Optional[PendingAction] = None
        self._pending_clarification: Optional[PendingClarification] = None
        self._active_topic: Optional[str] = None
        self._turn_count: int = 0

    # -- recording -------------------------------------------------------- #

    def record_intent(self, intent: Intent) -> None:
        """Update context after a new intent has been classified/handled."""
        self._turn_count += 1
        self._last_intent = intent
        self._active_topic = intent.category.value

        for entity in intent.entities:
            self._last_entities[entity.name] = entity.value

        logger.debug("Context updated: topic=%s, turn=%d", self._active_topic, self._turn_count)

    def set_pending_action(self, intent: Intent, prompt_shown: str) -> None:
        self._pending_action = PendingAction(intent=intent, prompt_shown=prompt_shown)
        logger.debug("Pending action set for confirmation: %s", intent.category.value)

    def set_pending_clarification(self, original_intent: Intent, missing_entity_name: str, question: str) -> None:
        self._pending_clarification = PendingClarification(
            original_intent=original_intent,
            missing_entity_name=missing_entity_name,
            question=question,
        )
        logger.debug("Pending clarification set for entity '%s'.", missing_entity_name)

    def clear_pending(self) -> None:
        self._pending_action = None
        self._pending_clarification = None

    # -- resolution --------------------------------------------------------- #

    def try_resolve_confirmation(self, text: str) -> Optional[bool]:
        """
        If there's a pending action awaiting yes/no confirmation, check
        whether `text` answers it. Returns True/False if resolved, or
        None if there's no pending confirmation or the reply was unclear.
        """
        if self._pending_action is None:
            return None
        if self._pending_action.is_expired():
            logger.debug("Pending action expired before confirmation.")
            self._pending_action = None
            return None

        lowered = text.strip().lower()
        if any(word in lowered for word in CONFIRMATION_KEYWORDS):
            return True
        if any(word in lowered for word in NEGATION_KEYWORDS):
            return False
        return None  # unclear reply; caller should re-prompt

    def try_resolve_clarification(self, text: str) -> Optional[Intent]:
        """
        If there's a pending clarification, treat `text` as the answer
        and return an updated Intent with the missing entity filled in.
        Returns None if there's nothing pending (or it expired).
        """
        pending = self._pending_clarification
        if pending is None:
            return None
        if pending.is_expired():
            logger.debug("Pending clarification expired before being answered.")
            self._pending_clarification = None
            return None

        updated_intent = pending.original_intent
        updated_intent.entities.append(
            Entity(name=pending.missing_entity_name, value=text.strip(), confidence=0.8)
        )
        self._pending_clarification = None
        logger.debug("Clarification resolved: %s=%r", pending.missing_entity_name, text.strip())
        return updated_intent

    def resolve_anaphora(self, intent: Intent, pronoun_entity_names: tuple[str, ...] = ("it", "that", "this")) -> Intent:
        """
        Best-effort resolution of pronoun references ("open it", "delete
        that") by substituting the most recent relevant entity value from
        context, when the current intent's own entities don't already
        supply one.
        """
        raw_lower = intent.raw_text.lower()
        if not any(f" {p} " in f" {raw_lower} " or raw_lower.endswith(f" {p}") for p in pronoun_entity_names):
            return intent

        if intent.entities:
            return intent  # already has its own entity, no need to resolve

        # Try to find a plausible antecedent from the last few remembered entities.
        for name, value in reversed(list(self._last_entities.items())):
            intent.entities.append(Entity(name=name, value=value, confidence=0.5))
            logger.debug("Anaphora resolved: '%s' -> %s=%r", intent.raw_text, name, value)
            break

        return intent

    # -- accessors ------------------------------------------------------------ #

    @property
    def has_pending_action(self) -> bool:
        return self._pending_action is not None and not self._pending_action.is_expired()

    @property
    def has_pending_clarification(self) -> bool:
        return self._pending_clarification is not None and not self._pending_clarification.is_expired()

    @property
    def pending_action(self) -> Optional[PendingAction]:
        return self._pending_action

    @property
    def active_topic(self) -> Optional[str]:
        return self._active_topic

    @property
    def last_intent(self) -> Optional[Intent]:
        return self._last_intent

    def get_remembered_entity(self, name: str, default: Any = None) -> Any:
        return self._last_entities.get(name, default)

    def snapshot(self) -> ContextSnapshot:
        return ContextSnapshot(
            last_intent=self._last_intent,
            last_entities=dict(self._last_entities),
            pending_action=self._pending_action,
            pending_clarification=self._pending_clarification,
            active_topic=self._active_topic,
        )

    def reset(self) -> None:
        """Fully reset conversational context (e.g. on 'new chat')."""
        self.__init__()  # noqa: PLC2801 - deliberate full re-init
        logger.info("Conversation context reset.")


# Module-level singleton — a single active conversation context per app
# instance. If multi-session support is added later, this can become a
# per-session registry mirroring ai.conversation.ConversationManager.
context_manager: ContextManager = ContextManager()
