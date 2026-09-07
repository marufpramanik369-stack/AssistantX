"""
response_generator.py
======================
The final stage of the brain/ pipeline: given a Decision (from
decision_engine.py) and the outcome of executing it (if any), produce
the natural-language text that gets shown in the dashboard chat and
spoken aloud by voice/speaker.py.

This module deliberately centralizes ALL user-facing text generation
logic so core/assistant.py's main loop stays a thin coordinator: it
calls decision_engine.process(), optionally executes a command via
core/command_router.py, and then calls response_generator.generate()
to get back exactly what to display/speak — regardless of whether the
turn was a command, a clarification, a confirmation, an error, or plain
conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ai.conversation import Conversation
from brain.decision_engine import Decision, DecisionAction
from brain.intent import Intent
from brain.prompt_engine import prompt_engine
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExecutionOutcome:
    """
    Result of actually running a command via core/command_router.py,
    passed into response_generator so it can phrase success/failure
    appropriately. `None` fields mean "not applicable" (e.g. this was a
    chat turn, not a command).
    """

    success: bool = True
    error_message: Optional[str] = None
    result_data: Optional[Any] = None  # e.g. weather data, search results


@dataclass
class Response:
    """Final packaged reply for a single turn."""

    text: str
    should_speak: bool = True
    intent: Optional[Intent] = None
    is_error: bool = False
    is_clarification: bool = False
    is_confirmation_request: bool = False


class ResponseGenerator:
    """Stateless — converts (Decision, ExecutionOutcome) pairs into a Response."""

    def generate(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: Optional[ExecutionOutcome] = None,
    ) -> Response:
        """
        Main dispatch: route to the appropriate phrasing strategy based
        on the decision's action type.
        """
        handler = {
            DecisionAction.CHAT: self._handle_chat,
            DecisionAction.ASK_CLARIFICATION: self._handle_clarification,
            DecisionAction.ASK_CONFIRMATION: self._handle_confirmation,
            DecisionAction.CANCELLED: self._handle_cancelled,
            DecisionAction.EXECUTE: self._handle_execute,
            DecisionAction.CONFIRMED_EXECUTE: self._handle_execute,
        }.get(decision.action)

        if handler is None:
            logger.error("No response handler registered for action: %s", decision.action)
            return Response(text="Something went wrong processing that.", is_error=True)

        return handler(decision, conversation, outcome)

    # -- individual handlers ------------------------------------------------- #

    def _handle_chat(self, decision: Decision, conversation: Conversation, outcome: Optional[ExecutionOutcome]) -> Response:
        user_text = decision.intent.raw_text if decision.intent else (decision.message or "")
        if not user_text:
            return Response(text="I didn't catch that — could you say it again?", should_speak=True)

        reply_text = prompt_engine.generate_reply(conversation, user_text, intent=decision.intent)
        return Response(text=reply_text, intent=decision.intent)

    def _handle_clarification(self, decision: Decision, conversation: Conversation, outcome: Optional[ExecutionOutcome]) -> Response:
        question = decision.message or "Could you clarify that?"
        return Response(
            text=prompt_engine.phrase_clarification(question),
            intent=decision.intent,
            is_clarification=True,
        )

    def _handle_confirmation(self, decision: Decision, conversation: Conversation, outcome: Optional[ExecutionOutcome]) -> Response:
        prompt = decision.message or "Are you sure?"
        return Response(
            text=prompt_engine.phrase_confirmation_prompt(prompt),
            intent=decision.intent,
            is_confirmation_request=True,
        )

    def _handle_cancelled(self, decision: Decision, conversation: Conversation, outcome: Optional[ExecutionOutcome]) -> Response:
        return Response(text=prompt_engine.phrase_cancellation(), intent=decision.intent)

    def _handle_execute(self, decision: Decision, conversation: Conversation, outcome: Optional[ExecutionOutcome]) -> Response:
        if decision.intent is None:
            return Response(text="I couldn't determine what to do.", is_error=True)

        # If the caller hasn't actually executed the command yet (outcome
        # is None), core/assistant.py is expected to call command_router
        # first — this branch is a defensive fallback so the generator
        # never crashes even if wired up out of order during development.
        if outcome is None:
            logger.warning("_handle_execute called without an ExecutionOutcome; assuming success.")
            return Response(text=prompt_engine.phrase_action_success(decision.intent), intent=decision.intent)

        if outcome.success:
            return Response(text=prompt_engine.phrase_action_success(decision.intent), intent=decision.intent)

        action_description = (decision.intent.sub_intent or decision.intent.category.value).replace("_", " ")
        error_text = prompt_engine.phrase_error_apology(action_description)
        if outcome.error_message:
            logger.debug("Execution error detail (not shown to user): %s", outcome.error_message)

        return Response(text=error_text, intent=decision.intent, is_error=True)


# Module-level singleton.
response_generator: ResponseGenerator = ResponseGenerator()
