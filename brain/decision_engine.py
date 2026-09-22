"""
brain/decision_engine.py
========================

Decision/orchestration layer for AssistantX.

The DecisionEngine sits between:

    User Input
        ↓
    brain.classifier
        ↓
    brain.context_manager
        ↓
    DecisionEngine
        ↓
    core.command_router / AI provider

Responsibilities
----------------
1. Resolve pending confirmations.
2. Resolve pending clarifications.
3. Resolve contextual/anaphoric references such as "open it".
4. Validate intent confidence.
5. Check required entities.
6. Decide whether confirmation is required.
7. Produce a consistent Decision object.

This module does NOT execute commands.

Command execution belongs to:
    core.command_router.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Any

from brain.classifier import classifier
from brain.context_manager import context_manager
from brain.intent import Intent, SubIntent
from config.constants import IntentCategory
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================ #
# Constants
# ============================================================================ #

DEFAULT_CONFIDENCE_THRESHOLD = 0.55
MAX_MESSAGE_LENGTH = 10_000


# ============================================================================ #
# Exceptions
# ============================================================================ #


class DecisionEngineError(Exception):
    """Base exception for DecisionEngine."""


class DecisionValidationError(DecisionEngineError):
    """Raised when invalid decision data is supplied."""


class DecisionProcessingError(DecisionEngineError):
    """Raised when decision processing fails."""


# ============================================================================ #
# Decision Action
# ============================================================================ #


class DecisionAction(str, Enum):
    """
    Describes what AssistantX should do after processing an intent.
    """

    EXECUTE = "execute"

    ASK_CLARIFICATION = "ask_clarification"

    ASK_CONFIRMATION = "ask_confirmation"

    CHAT = "chat"

    CONFIRMED_EXECUTE = "confirmed_execute"

    CANCELLED = "cancelled"


# ============================================================================ #
# Decision
# ============================================================================ #


@dataclass(slots=True)
class Decision:
    """
    Final outcome produced by the DecisionEngine.

    Attributes
    ----------
    action:
        The next operation AssistantX should perform.

    intent:
        The classified intent associated with this decision.

    message:
        Optional user-facing message.

    metadata:
        Additional information useful for logging/debugging/UI.

    duration_ms:
        Processing time for this decision.
    """

    action: DecisionAction

    intent: Intent | None = None

    message: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    duration_ms: float = 0.0

    @property
    def should_execute(self) -> bool:
        """Return True when the command should be executed."""

        return self.action in (
            DecisionAction.EXECUTE,
            DecisionAction.CONFIRMED_EXECUTE,
        )

    @property
    def is_chat(self) -> bool:
        """Return True when the turn should be handled by AI chat."""

        return self.action == DecisionAction.CHAT

    @property
    def needs_clarification(self) -> bool:
        """Return True when more information is required."""

        return self.action == DecisionAction.ASK_CLARIFICATION

    @property
    def needs_confirmation(self) -> bool:
        """Return True when explicit user confirmation is required."""

        return self.action == DecisionAction.ASK_CONFIRMATION

    @property
    def is_cancelled(self) -> bool:
        """Return True when a pending action was cancelled."""

        return self.action == DecisionAction.CANCELLED

    @property
    def is_confirmed_execution(self) -> bool:
        """Return True when the user confirmed a pending action."""

        return self.action == DecisionAction.CONFIRMED_EXECUTE

    @property
    def success(self) -> bool:
        """
        Whether the decision itself was successfully resolved.

        Note:
            This does NOT mean the underlying command succeeded.
            Command execution happens later.
        """

        return True

    def to_dict(
        self,
        include_intent: bool = True,
    ) -> dict[str, Any]:
        """Serialize the decision for logging, UI or debugging."""

        data: dict[str, Any] = {
            "action": self.action.value,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 3),
            "metadata": dict(self.metadata),
        }

        if include_intent:
            data["intent"] = (
                self.intent.to_dict()
                if self.intent is not None
                else None
            )

        return data

    def __bool__(self) -> bool:
        return True


# ============================================================================ #
# Required Entity Rules
# ============================================================================ #

_REQUIRED_ENTITIES: dict[str, tuple[str, ...]] = {
    # Applications
    SubIntent.OPEN_APP: ("app_name",),
    SubIntent.CLOSE_APP: ("app_name",),

    # Music
    SubIntent.PLAY_MUSIC: ("song_or_query",),

    # Reminders
    SubIntent.SET_REMINDER: ("reminder_text",),

    # Files
    SubIntent.CREATE_FILE: ("filename",),
    SubIntent.DELETE_FILE: ("filename",),
    SubIntent.SEARCH_FILE: ("filename",),
    SubIntent.OPEN_FOLDER: ("folder_path",),

    # Calculator
    SubIntent.ARITHMETIC: ("expression",),

    # Web
    SubIntent.GENERAL_SEARCH: ("query",),
}


# ============================================================================ #
# Clarification Questions
# ============================================================================ #

_CLARIFICATION_QUESTIONS: dict[str, str] = {
    "app_name": "Which application would you like me to open?",

    "song_or_query": "What would you like me to play?",

    "reminder_text": "What should I remind you about?",

    "filename": "What's the file name?",

    "folder_path": "Which folder would you like me to open?",

    "expression": "What would you like me to calculate?",

    "query": "What would you like me to search for?",
}


# ============================================================================ #
# Decision Engine
# ============================================================================ #


class DecisionEngine:
    """
    Coordinates classifier + context manager into a final Decision.

    The engine itself does not execute automation commands.
    """

    def __init__(
        self,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.confidence_threshold = self._validate_threshold(
            confidence_threshold
        )

        self._processed_count = 0
        self._last_decision: Decision | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def process(
        self,
        text: str,
    ) -> Decision:
        """
        Process one user utterance.

        Processing order:

            1. Pending confirmation
            2. Pending clarification
            3. Fresh classification
            4. Anaphora/context resolution
            5. Final decision
        """

        started = perf_counter()

        normalized_text = self._normalize_input(text)

        if not normalized_text:
            decision = Decision(
                action=DecisionAction.CHAT,
                message="",
            )

            return self._complete_decision(
                decision,
                started,
            )

        try:
            # ---------------------------------------------------------- #
            # 1. Pending confirmation
            # ---------------------------------------------------------- #

            confirmation_decision = (
                self._resolve_pending_confirmation(
                    normalized_text
                )
            )

            if confirmation_decision is not None:
                return self._complete_decision(
                    confirmation_decision,
                    started,
                )

            # ---------------------------------------------------------- #
            # 2. Pending clarification
            # ---------------------------------------------------------- #

            clarification_decision = (
                self._resolve_pending_clarification(
                    normalized_text
                )
            )

            if clarification_decision is not None:
                return self._complete_decision(
                    clarification_decision,
                    started,
                )

            # ---------------------------------------------------------- #
            # 3. Fresh classification
            # ---------------------------------------------------------- #

            intent = classifier.classify(
                normalized_text
            )

            if intent is None:
                logger.warning(
                    "Classifier returned no intent for input."
                )

                intent = self._unknown_intent(
                    normalized_text
                )

            # ---------------------------------------------------------- #
            # 4. Context / anaphora resolution
            # ---------------------------------------------------------- #

            intent = context_manager.resolve_anaphora(
                intent
            )

            # ---------------------------------------------------------- #
            # 5. Finalize
            # ---------------------------------------------------------- #

            decision = self._finalize(intent)

            return self._complete_decision(
                decision,
                started,
            )

        except Exception as exc:
            logger.exception(
                "Decision processing failed: %s",
            )


            decision = Decision(
                action=DecisionAction.CHAT,
                message=(
                    "I couldn't determine the best action "
                    "for that request."
                ),
                metadata={
                    "error": str(exc),
                },
            )

            return self._complete_decision(
                decision,
                started,
            )

    # ------------------------------------------------------------------ #
    # Pending confirmation
    # ------------------------------------------------------------------ #

    def _resolve_pending_confirmation(
        self,
        text: str,
    ) -> Decision | None:
        """
        Resolve a pending yes/no confirmation.

        Returns:
            Decision | None

        None means there is no pending confirmation.
        """

        if not context_manager.has_pending_action:
            return None

        pending = context_manager.pending_action

        if pending is None:
            logger.warning(
                "ContextManager reported pending action "
                "but returned no action."
            )
            return None

        result = context_manager.try_resolve_confirmation(
            text
        )

        # -------------------------------------------------------------- #
        # Confirmed
        # -------------------------------------------------------------- #

        if result is True:
            intent = pending.intent

            context_manager.clear_pending()

            logger.info(
                "Pending action confirmed: category=%s sub_intent=%s",
                intent.category.value,
                intent.sub_intent,
            )

            return Decision(
                action=DecisionAction.CONFIRMED_EXECUTE,
                intent=intent,
                metadata={
                    "confirmation": "confirmed",
                },
            )

        # -------------------------------------------------------------- #
        # Cancelled
        # -------------------------------------------------------------- #

        if result is False:
            context_manager.clear_pending()

            logger.info(
                "Pending action cancelled by user."
            )

            return Decision(
                action=DecisionAction.CANCELLED,
                message="Okay, I won't do that.",
                metadata={
                    "confirmation": "cancelled",
                },
            )

        # -------------------------------------------------------------- #
        # Ambiguous
        # -------------------------------------------------------------- #

        logger.debug(
            "Ambiguous confirmation response; asking again."
        )

        return Decision(
            action=DecisionAction.ASK_CONFIRMATION,
            intent=pending.intent,
            message=pending.prompt_shown,
            metadata={
                "confirmation": "ambiguous",
            },
        )

    # ------------------------------------------------------------------ #
    # Pending clarification
    # ------------------------------------------------------------------ #

    def _resolve_pending_clarification(
        self,
        text: str,
    ) -> Decision | None:
        """
        Try to use the current text to resolve a pending clarification.
        """

        if not context_manager.has_pending_clarification:
            return None

        resolved_intent = (
            context_manager.try_resolve_clarification(
                text
            )
        )

        if resolved_intent is None:
            logger.debug(
                "Pending clarification could not be resolved."
            )

            return Decision(
                action=DecisionAction.ASK_CLARIFICATION,
                message=(
                    "Could you provide a little more information?"
                ),
            )

        logger.debug(
            "Pending clarification successfully resolved."
        )

        return self._finalize(
            resolved_intent
        )

    # ------------------------------------------------------------------ #
    # Finalization
    # ------------------------------------------------------------------ #

    def _finalize(
        self,
        intent: Intent,
    ) -> Decision:
        """
        Convert an Intent into a final Decision.

        Decision priority:

            UNKNOWN / GENERAL_CHAT
                ↓
            CHAT

            Low confidence
                ↓
            CHAT

            Missing required entity
                ↓
            ASK_CLARIFICATION

            Confirmation required
                ↓
            ASK_CONFIRMATION

            Otherwise
                ↓
            EXECUTE
        """

        if intent is None:
            return Decision(
                action=DecisionAction.CHAT,
                message="",
            )

        # -------------------------------------------------------------- #
        # Record intent in context
        # -------------------------------------------------------------- #

        try:
            context_manager.record_intent(
                intent
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            logger.warning(
                "Failed to record intent in context: %s"
            )


        # -------------------------------------------------------------- #
        # Non-actionable intent
        # -------------------------------------------------------------- #

        if not intent.is_actionable():
            return Decision(
                action=DecisionAction.CHAT,
                intent=intent,
                metadata={
                    "reason": "non_actionable_intent",
                },
            )

        # -------------------------------------------------------------- #
        # Confidence check
        # -------------------------------------------------------------- #

        if not intent.is_confident(
            self.confidence_threshold
        ):
            logger.debug(
                "Low-confidence intent routed to chat: "
                "%.2f < %.2f",
                intent.confidence,
                self.confidence_threshold,
            )

            return Decision(
                action=DecisionAction.CHAT,
                intent=intent,
                metadata={
                    "reason": "low_confidence",
                    "confidence": intent.confidence,
                    "threshold": self.confidence_threshold,
                },
            )

        # -------------------------------------------------------------- #
        # Required entity check
        # -------------------------------------------------------------- #

        missing_entity = (
            self._find_missing_required_entity(
                intent
            )
        )

        if missing_entity is not None:
            question = self._build_clarification_question(
                missing_entity
            )

            try:
                context_manager.set_pending_clarification(
                    intent,
                    missing_entity,
                    question,
                )
            except (ValueError, RuntimeError, AssertionError):
                logger.warning(
                    "Failed to save pending clarification: %s"
                )


            return Decision(
                action=DecisionAction.ASK_CLARIFICATION,
                intent=intent,
                message=question,
                metadata={
                    "missing_entity": missing_entity,
                },
            )

        # -------------------------------------------------------------- #
        # Confirmation check
        # -------------------------------------------------------------- #

        if intent.requires_confirmation:
            prompt = self._build_confirmation_prompt(
                intent
            )

            try:
                context_manager.set_pending_action(
                    intent,
                    prompt,
                )
            except (RuntimeError, ValueError, TypeError):
                logger.warning(
                    "Failed to save pending action: %s",

                )
                

            return Decision(
                action=DecisionAction.ASK_CONFIRMATION,
                intent=intent,
                message=prompt,
                metadata={
                    "reason": "confirmation_required",
                },
            )

        # -------------------------------------------------------------- #
        # Ready for execution
        # -------------------------------------------------------------- #

        return Decision(
            action=DecisionAction.EXECUTE,
            intent=intent,
            metadata={
                "reason": "ready_for_execution",
            },
        )

    # ------------------------------------------------------------------ #
    # Required entities
    # ------------------------------------------------------------------ #

    def _find_missing_required_entity(
        self,
        intent: Intent,
    ) -> str | None:
        """
        Return the first missing entity required by an intent.
        """

        if not intent.sub_intent:
            return None

        required_entities = _REQUIRED_ENTITIES.get(
            intent.sub_intent,
            (),
        )

        for entity_name in required_entities:
            entity = intent.get_entity(
                entity_name
            )

            if entity is None:
                return entity_name

            # Empty values should also count as missing.
            if entity.value is None:
                return entity_name

            if isinstance(entity.value, str) and not entity.value.strip():
                return entity_name

        return None

    

    # ------------------------------------------------------------------ #
    # Clarification
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_clarification_question(
        entity_name: str,
    ) -> str:
        """Build a user-friendly clarification question."""

        return _CLARIFICATION_QUESTIONS.get(
            entity_name,
            f"Could you clarify the {entity_name.replace('_', ' ')}?",
        )

    # ------------------------------------------------------------------ #
    # Confirmation
    # ------------------------------------------------------------------ #

    def _build_confirmation_prompt(
        self,
        intent: Intent,
    ) -> str:
        """
        Build a safe yes/no confirmation prompt.

        Destructive or system-level actions receive explicit wording.
        """

        sub_intent = intent.sub_intent

        # -------------------------------------------------------------- #
        # File deletion
        # -------------------------------------------------------------- #

        if sub_intent == SubIntent.DELETE_FILE:
            filename = intent.get_entity_value(
                "filename",
                "that file",
            )

            return (
                f"Are you sure you want to delete "
                f"'{filename}'? This can't be undone."
            )

        # -------------------------------------------------------------- #
        # System actions
        # -------------------------------------------------------------- #

        if sub_intent == SubIntent.SHUTDOWN:
            return (
                "Are you sure you want to shut down "
                "the computer?"
            )

        if sub_intent == SubIntent.RESTART:
            return (
                "Are you sure you want to restart "
                "the computer?"
            )

        if sub_intent == SubIntent.SLEEP:
            return (
                "Are you sure you want to put "
                "the computer to sleep?"
            )

        # -------------------------------------------------------------- #
        # Folder deletion / destructive operations
        # -------------------------------------------------------------- #

        if sub_intent == SubIntent.DELETE_FILE:
            return (
                "Are you sure you want to delete "
                "that file?"
            )

        # -------------------------------------------------------------- #
        # Generic fallback
        # -------------------------------------------------------------- #

        category = (
            intent.category.value
            .replace("_", " ")
        )

        if sub_intent:
            action_name = (
                sub_intent
                .replace("_", " ")
            )

            return (
                f"Are you sure you want to "
                f"{action_name}?"
            )

        return (
            f"Are you sure you want to proceed "
            f"with {category}?"
        )

    # ------------------------------------------------------------------ #
    # Input validation
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_input(
        text: str,
    ) -> str:
        """Normalize raw user input."""

        if text is None:
            return ""

        if not isinstance(text, str):
            text = str(text)

        text = text.strip()

        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH]

            logger.warning(
                "Input exceeded maximum length and was truncated."
            )

        return text

    @staticmethod
    def _validate_threshold(
        threshold: float,
    ) -> float:
        """Validate confidence threshold."""

        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise DecisionValidationError(
                "confidence_threshold must be numeric."
            ) from exc

        if not 0.0 <= threshold <= 1.0:
            raise DecisionValidationError(
                "confidence_threshold must be between 0.0 and 1.0."
            )

        return threshold

    @staticmethod
    def _unknown_intent(
        text: str,
    ) -> Intent:
        """
        Create UNKNOWN intent without importing another factory.

        Kept isolated so the engine remains resilient if classifier
        temporarily returns None.
        """

        return Intent(
            category=IntentCategory.UNKNOWN,
            raw_text=text,
            confidence=0.0,
        )

    # ------------------------------------------------------------------ #
    # Decision completion / metrics
    # ------------------------------------------------------------------ #

    def _complete_decision(
        self,
        decision: Decision,
        started: float,
    ) -> Decision:
        """Attach timing information and update engine statistics."""

        decision.duration_ms = (
            perf_counter() - started
        ) * 1000

        self._processed_count += 1
        self._last_decision = decision

        logger.debug(
            "Decision completed: action=%s duration=%.2fms",
            decision.action.value,
            decision.duration_ms,
        )

        return decision

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    @property
    def processed_count(self) -> int:
        """Number of processed turns."""

        return self._processed_count

    @property
    def last_decision(self) -> Decision | None:
        """Return the most recent decision."""

        return self._last_decision

    def stats(self) -> dict[str, Any]:
        """Return runtime statistics."""

        return {
            "processed_count": self._processed_count,
            "confidence_threshold": self.confidence_threshold,
            "last_action": (
                self._last_decision.action.value
                if self._last_decision
                else None
            ),
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information."""

        return {
            "component": "DecisionEngine",
            "status": "ready",
            "confidence_threshold": self.confidence_threshold,
            "processed_count": self._processed_count,
            "pending_action": bool(
                context_manager.has_pending_action
            ),
            "pending_clarification": bool(
                context_manager.has_pending_clarification
            ),
            "last_decision": (
                self._last_decision.to_dict()
                if self._last_decision
                else None
            ),
        }

    def reset_stats(self) -> None:
        """Reset runtime statistics."""

        self._processed_count = 0
        self._last_decision = None

    def __repr__(self) -> str:
        return (
            f"DecisionEngine("
            f"confidence_threshold="
            f"{self.confidence_threshold:.2f}, "
            f"processed_count="
            f"{self._processed_count}"
            f")"
        )


# ============================================================================ #
# Global Singleton
# ============================================================================ #


decision_engine = DecisionEngine()


# ============================================================================ #
# Convenience API
# ============================================================================ #


def process_decision(
    text: str,
) -> Decision:
    """Process text using the global DecisionEngine."""

    return decision_engine.process(text)


def decision_engine_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global DecisionEngine."""

    return decision_engine.diagnostics()


# ============================================================================ #
# Public API
# ============================================================================ #


__all__ = [
    "Decision",
    # Core types
    "DecisionAction",
    # Engine
    "DecisionEngine",
    # Exceptions
    "DecisionEngineError",
    "DecisionProcessingError",
    "DecisionValidationError",
    "decision_engine",
    "decision_engine_diagnostics",
    # Convenience
    "process_decision",
]
