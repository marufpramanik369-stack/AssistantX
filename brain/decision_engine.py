"""
decision_engine.py
===================
The orchestration layer between "we understood what the user said"
(brain/classifier.py + brain/context_manager.py) and "here is the
concrete action to execute" (core/command_router.py, which dispatches
into automation/ and services/).

Responsibilities:
    1. Resolve pending confirmations/clarifications from prior turns.
    2. Run anaphora resolution ("open it") via ContextManager.
    3. Decide whether an intent has enough information to act on
       immediately, needs a clarifying question first, or needs an
       explicit yes/no confirmation before proceeding (destructive
       actions).
    4. Package the final decision into a Decision object that
       core/assistant.py can act on uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from brain.classifier import classifier
from brain.context_manager import context_manager
from brain.intent import Intent, SubIntent
from config.constants import IntentCategory
from core.logger import get_logger

logger = get_logger(__name__)


class DecisionAction(str, Enum):
    """What core/assistant.py should do with this turn."""

    EXECUTE = "execute"                  # Run the command now via command_router
    ASK_CLARIFICATION = "ask_clarification"  # Need more info before executing
    ASK_CONFIRMATION = "ask_confirmation"    # Need explicit yes/no before executing
    CHAT = "chat"                        # Route to the AI provider for conversation
    CONFIRMED_EXECUTE = "confirmed_execute"  # User just confirmed a pending action
    CANCELLED = "cancelled"              # User declined a pending action


@dataclass
class Decision:
    """The final, actionable outcome of processing one user utterance."""

    action: DecisionAction
    intent: Optional[Intent] = None
    message: Optional[str] = None  # e.g. the clarifying question or cancellation notice

    @property
    def should_execute(self) -> bool:
        return self.action in (DecisionAction.EXECUTE, DecisionAction.CONFIRMED_EXECUTE)


# Entities considered "required" for a sub_intent to be actionable
# without asking a clarifying question. Extend as new sub-intents are added.
_REQUIRED_ENTITIES: dict[str, tuple[str, ...]] = {
    SubIntent.OPEN_APP: ("app_name",),
    SubIntent.CLOSE_APP: ("app_name",),
    SubIntent.PLAY_MUSIC: ("song_or_query",),
    SubIntent.SET_REMINDER: ("reminder_text",),
    SubIntent.CREATE_FILE: ("filename",),
    SubIntent.DELETE_FILE: ("filename",),
    SubIntent.SEARCH_FILE: ("filename",),
    SubIntent.OPEN_FOLDER: ("folder_path",),
    SubIntent.ARITHMETIC: ("expression",),
    SubIntent.GENERAL_SEARCH: ("query",),
}

_CLARIFICATION_QUESTIONS: dict[str, str] = {
    "app_name": "Which application would you like me to open?",
    "song_or_query": "What would you like me to play?",
    "reminder_text": "What should I remind you about?",
    "filename": "What's the file name?",
    "folder_path": "Which folder?",
    "expression": "What would you like me to calculate?",
    "query": "What would you like me to search for?",
}


class DecisionEngine:
    """
    Stateless coordinator that ties classifier + context_manager output
    into a single Decision. Holds no per-call mutable state of its own —
    all state lives in the shared ContextManager instance.
    """

    def process(self, text: str) -> Decision:
        """
        Main entry point: given raw user text for this turn, produce the
        Decision describing what should happen next.
        """
        text = text.strip()
        if not text:
            return Decision(action=DecisionAction.CHAT, message="")

        # 1. Check if this turn answers a pending confirmation.
        if context_manager.has_pending_action:
            confirmed = context_manager.try_resolve_confirmation(text)
            if confirmed is True:
                pending = context_manager.pending_action
                context_manager.clear_pending()
                logger.info("User confirmed pending action: %s", pending.intent.category.value)
                return Decision(action=DecisionAction.CONFIRMED_EXECUTE, intent=pending.intent)
            elif confirmed is False:
                context_manager.clear_pending()
                return Decision(
                    action=DecisionAction.CANCELLED,
                    message="Okay, I won't do that.",
                )
            # Ambiguous reply -> re-ask rather than silently dropping the pending action.
            return Decision(
                action=DecisionAction.ASK_CONFIRMATION,
                intent=context_manager.pending_action.intent,
                message=context_manager.pending_action.prompt_shown,
            )

        # 2. Check if this turn answers a pending clarification.
        if context_manager.has_pending_clarification:
            resolved_intent = context_manager.try_resolve_clarification(text)
            if resolved_intent is not None:
                return self._finalize(resolved_intent)

        # 3. Fresh utterance -> classify from scratch.
        intent = classifier.classify(text)
        intent = context_manager.resolve_anaphora(intent)
        return self._finalize(intent)

    def _finalize(self, intent: Intent) -> Decision:
        """Given a freshly classified (or clarification-resolved) intent,
        decide whether to execute, clarify, confirm, or fall through to chat."""
        context_manager.record_intent(intent)

        if not intent.is_actionable():
            return Decision(action=DecisionAction.CHAT, intent=intent)

        if not intent.is_confident():
            logger.debug("Low-confidence intent (%.2f) routed to chat as a safe default.", intent.confidence)
            return Decision(action=DecisionAction.CHAT, intent=intent)

        missing_entity = self._find_missing_required_entity(intent)
        if missing_entity is not None:
            question = _CLARIFICATION_QUESTIONS.get(missing_entity, f"Could you clarify {missing_entity}?")
            context_manager.set_pending_clarification(intent, missing_entity, question)
            return Decision(action=DecisionAction.ASK_CLARIFICATION, intent=intent, message=question)

        if intent.requires_confirmation:
            prompt = self._build_confirmation_prompt(intent)
            context_manager.set_pending_action(intent, prompt)
            return Decision(action=DecisionAction.ASK_CONFIRMATION, intent=intent, message=prompt)

        return Decision(action=DecisionAction.EXECUTE, intent=intent)

    def _find_missing_required_entity(self, intent: Intent) -> Optional[str]:
        required = _REQUIRED_ENTITIES.get(intent.sub_intent or "", ())
        for entity_name in required:
            if not intent.has_entity(entity_name):
                return entity_name
        return None

    def _build_confirmation_prompt(self, intent: Intent) -> str:
        """Construct a human-readable yes/no prompt for a destructive action."""
        if intent.sub_intent == SubIntent.DELETE_FILE:
            filename = intent.get_entity_value("filename", "that file")
            return f"Are you sure you want to delete '{filename}'? This can't be undone."
        if intent.sub_intent == SubIntent.SHUTDOWN:
            return "Are you sure you want to shut down the computer?"
        if intent.sub_intent == SubIntent.RESTART:
            return "Are you sure you want to restart the computer?"
        return f"Are you sure you want to proceed with {intent.category.value.replace('_', ' ')}?"


# Module-level singleton.
decision_engine: DecisionEngine = DecisionEngine()
