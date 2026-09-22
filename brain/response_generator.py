"""
brain.response_generator
========================

Final response-generation layer of AssistantX.

Responsibilities
----------------
This module converts a ``Decision`` and optional command execution
result into a user-facing ``Response``.

The response may be:

- Normal AI conversation
- Clarification request
- Confirmation request
- Cancellation message
- Successful command response
- Command failure response
- Defensive/internal error response

Architecture
------------
The response generator intentionally does NOT execute commands.

Flow:

    User Input
        ↓
    Intent
        ↓
    Decision Engine
        ↓
    Command Router (if required)
        ↓
    ExecutionOutcome
        ↓
    ResponseGenerator
        ↓
    Response
        ↓
    Dashboard / Voice

Keeping execution separate from response generation makes this module
easy to test and keeps ``core/assistant.py`` thin.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter
from typing import Any

from ai.conversation import Conversation
from brain.decision_engine import Decision, DecisionAction
from brain.intent import Intent
from brain.prompt_engine import prompt_engine
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_EMPTY_INPUT_RESPONSE = (
    "I didn't catch that. Could you say it again?"
)

DEFAULT_CLARIFICATION_RESPONSE = (
    "Could you clarify what you'd like me to do?"
)

DEFAULT_CONFIRMATION_RESPONSE = "Are you sure?"

DEFAULT_CANCELLED_RESPONSE = "Okay, cancelled."

DEFAULT_UNKNOWN_ACTION_RESPONSE = (
    "Something went wrong while processing that request."
)

DEFAULT_EXECUTION_ERROR_RESPONSE = (
    "Sorry, I couldn't complete that action."
)

DEFAULT_UNDETERMINED_ACTION_RESPONSE = (
    "I couldn't determine what to do."
)

MAX_ERROR_DETAIL_LENGTH = 500


# ============================================================================
# Exceptions
# ============================================================================


class ResponseGeneratorError(Exception):
    """Base exception for response-generation errors."""


class InvalidDecisionError(ResponseGeneratorError):
    """Raised when an invalid or unusable Decision is supplied."""


class ResponseGenerationError(ResponseGeneratorError):
    """Raised when response generation fails unexpectedly."""


# ============================================================================
# Execution Outcome
# ============================================================================


@dataclass(slots=True)
class ExecutionOutcome:
    """
    Result of executing a command.

    Parameters
    ----------
    success:
        Whether the command completed successfully.
    error_message:
        Internal error detail, if execution failed.
        This should generally NOT be displayed directly to the user.
    result_data:
        Optional structured result returned by the command.
    metadata:
        Additional execution metadata such as command ID, duration,
        provider information, etc.
    """

    success: bool = True
    error_message: str | None = None
    result_data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.success = bool(self.success)

        if self.error_message is not None:
            self.error_message = str(self.error_message).strip() or None

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata or {})

    @classmethod
    def success_result(
        cls,
        result_data: Any = None,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionOutcome:
        """Create a successful execution outcome."""
        return cls(
            success=True,
            result_data=result_data,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failure(
        cls,
        error_message: str | None = None,
        *,
        result_data: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionOutcome:
        """Create a failed execution outcome."""
        return cls(
            success=False,
            error_message=error_message,
            result_data=result_data,
            metadata=dict(metadata or {}),
        )

    @property
    def failed(self) -> bool:
        """Return ``True`` when execution failed."""
        return not self.success

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""
        return {
            "success": self.success,
            "error_message": self.error_message,
            "result_data": self.result_data,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Response Status
# ============================================================================


class ResponseStatus(str, Enum):
    """Semantic status of a generated response."""

    SUCCESS = "success"
    EMPTY_INPUT = "empty_input"
    CLARIFICATION = "clarification"
    CONFIRMATION = "confirmation"
    CANCELLED = "cancelled"
    ERROR = "error"


# ============================================================================
# Response
# ============================================================================


@dataclass(slots=True)
class Response:
    """
    Final response returned by ``ResponseGenerator``.

    ``text`` is the primary user-facing content.

    The remaining fields provide metadata for the dashboard, voice
    system, logging layer and future analytics.
    """

    text: str
    should_speak: bool = True
    intent: Intent | None = None

    status: ResponseStatus = ResponseStatus.SUCCESS

    is_error: bool = False
    is_clarification: bool = False
    is_confirmation_request: bool = False

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = str(self.text or "").strip()

        if not self.text:
            self.text = DEFAULT_UNKNOWN_ACTION_RESPONSE

        self.should_speak = bool(self.should_speak)

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata or {})

        # Keep legacy boolean flags synchronized with status.
        if self.status == ResponseStatus.ERROR:
            self.is_error = True

        if self.status == ResponseStatus.CLARIFICATION:
            self.is_clarification = True

        if self.status == ResponseStatus.CONFIRMATION:
            self.is_confirmation_request = True

    @classmethod
    def success(
        cls,
        text: str,
        *,
        intent: Intent | None = None,
        should_speak: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> Response:
        """Create a successful response."""
        return cls(
            text=text,
            should_speak=should_speak,
            intent=intent,
            status=ResponseStatus.SUCCESS,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error(
        cls,
        text: str,
        *,
        intent: Intent | None = None,
        should_speak: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> Response:
        """Create an error response."""
        return cls(
            text=text,
            should_speak=should_speak,
            intent=intent,
            status=ResponseStatus.ERROR,
            is_error=True,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def clarification(
        cls,
        text: str,
        *,
        intent: Intent | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Response:
        """Create a clarification response."""
        return cls(
            text=text,
            intent=intent,
            status=ResponseStatus.CLARIFICATION,
            is_clarification=True,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def confirmation(
        cls,
        text: str,
        *,
        intent: Intent | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Response:
        """Create a confirmation request."""
        return cls(
            text=text,
            intent=intent,
            status=ResponseStatus.CONFIRMATION,
            is_confirmation_request=True,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable response dictionary."""
        return {
            "text": self.text,
            "should_speak": self.should_speak,
            "intent": (
                self.intent.category.value
                if self.intent is not None
                else None
            ),
            "status": self.status.value,
            "is_error": self.is_error,
            "is_clarification": self.is_clarification,
            "is_confirmation_request": self.is_confirmation_request,
            "metadata": dict(self.metadata),
        }

    def __bool__(self) -> bool:
        """Allow ``if response:`` style checks."""
        return bool(self.text)


# ============================================================================
# Handler Type
# ============================================================================


ResponseHandler = Callable[
    [
        Decision,
        Conversation,
        ExecutionOutcome | None,
    ],
    Response,
]


# ============================================================================
# Response Generator
# ============================================================================


class ResponseGenerator:
    """
    Generate final user-facing responses from decisions.

    The class is intentionally stateless. Custom handlers can be
    registered when plugins or future features need specialized
    response generation.
    """

    def __init__(self) -> None:
        self._handlers: dict[DecisionAction, ResponseHandler] = {}
        self._register_default_handlers()

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_default_handlers(self) -> None:
        """Register built-in decision handlers."""

        self._handlers = {
            DecisionAction.CHAT: self._handle_chat,
            DecisionAction.ASK_CLARIFICATION: self._handle_clarification,
            DecisionAction.ASK_CONFIRMATION: self._handle_confirmation,
            DecisionAction.CANCELLED: self._handle_cancelled,
            DecisionAction.EXECUTE: self._handle_execute,
            DecisionAction.CONFIRMED_EXECUTE: self._handle_execute,
        }

    def register_handler(
        self,
        action: DecisionAction,
        handler: ResponseHandler,
        *,
        overwrite: bool = False,
    ) -> None:
        """
        Register a custom response handler.

        Parameters
        ----------
        action:
            Decision action to handle.
        handler:
            Callable receiving ``decision``, ``conversation`` and
            ``outcome``.
        overwrite:
            Allow replacing an existing handler.
        """

        if not isinstance(action, DecisionAction):
            raise InvalidDecisionError(
                f"Invalid decision action: {action!r}"
            )

        if not callable(handler):
            raise TypeError("handler must be callable")

        if action in self._handlers and not overwrite:
            raise ResponseGeneratorError(
                f"Handler already registered for action: {action.value}"
            )

        self._handlers[action] = handler

        logger.debug(
            "Response handler registered: action=%s handler=%s",
            action.value,
            getattr(handler, "__name__", repr(handler)),
        )

    def unregister_handler(self, action: DecisionAction) -> bool:
        """Remove a custom response handler."""
        if action in self._handlers:
            del self._handlers[action]
            return True

        return False

    def has_handler(self, action: DecisionAction) -> bool:
        """Return whether a handler exists for an action."""
        return action in self._handlers

    def handler_count(self) -> int:
        """Return the number of registered handlers."""
        return len(self._handlers)

    # ------------------------------------------------------------------
    # Main generation API
    # ------------------------------------------------------------------

    def generate(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None = None,
    ) -> Response:
        """
        Generate the final response.

        This method never executes a command. Command execution must
        happen before calling this method when the decision requires it.
        """

        started = perf_counter()

        self._validate_inputs(decision, conversation)

        handler = self._handlers.get(decision.action)

        if handler is None:
            logger.error(
                "No response handler registered for action=%r",
                decision.action,
            )

            return Response.error(
                DEFAULT_UNKNOWN_ACTION_RESPONSE,
                intent=getattr(decision, "intent", None),
                metadata={
                    "reason": "unregistered_action",
                    "action": str(decision.action),
                },
            )

        try:
            response = handler(
                decision,
                conversation,
                outcome,
            )

            if not isinstance(response, Response):
                logger.error(
                    "Response handler returned invalid type: %s",
                    type(response).__name__,
                )

                return Response.error(
                    DEFAULT_UNKNOWN_ACTION_RESPONSE,
                    intent=getattr(decision, "intent", None),
                    metadata={
                        "reason": "invalid_handler_result",
                    },
                )

            elapsed_ms = round(
                (perf_counter() - started) * 1000,
                3,
            )

            response.metadata.setdefault(
                "generation_duration_ms",
                elapsed_ms,
            )

            response.metadata.setdefault(
                "action",
                getattr(decision.action, "value", str(decision.action)),
            )

            return response

        except Exception:
            elapsed_ms = round(
                (perf_counter() - started) * 1000,
                3,
            )

            logger.exception(
                "Response generation failed: %s",
            )
            

            return Response.error(
                DEFAULT_UNKNOWN_ACTION_RESPONSE,
                intent=getattr(decision, "intent", None),
                metadata={
                    "reason": "generation_exception",
                    "generation_duration_ms": elapsed_ms,
                },
            )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        decision: Decision,
        conversation: Conversation,
    ) -> None:
        """Validate required generation inputs."""

        if decision is None:
            raise InvalidDecisionError(
                "decision cannot be None"
            )

        if not isinstance(decision, Decision):
            raise InvalidDecisionError(
                f"Expected Decision, got {type(decision).__name__}"
            )

        if conversation is None:
            raise ResponseGeneratorError(
                "conversation cannot be None"
            )

    # ------------------------------------------------------------------
    # CHAT
    # ------------------------------------------------------------------

    def _handle_chat(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None,
    ) -> Response:
        """Generate a normal conversational response."""

        user_text = self._get_user_text(decision)

        if not user_text:
            return Response(
                text=DEFAULT_EMPTY_INPUT_RESPONSE,
                should_speak=True,
                intent=decision.intent,
                status=ResponseStatus.EMPTY_INPUT,
                metadata={
                    "reason": "empty_user_text",
                },
            )

        try:
            reply_text = prompt_engine.generate_reply(
                conversation,
                user_text,
                intent=decision.intent,
            )

        except Exception:
            logger.exception(
                "Chat response generation failed",
            )

            return Response.error(
                DEFAULT_UNKNOWN_ACTION_RESPONSE,
                intent=decision.intent,
                metadata={
                    "reason": "prompt_engine_failure",
                },
            )

        reply_text = self._clean_response_text(reply_text)

        if not reply_text:
            return Response.error(
                DEFAULT_UNKNOWN_ACTION_RESPONSE,
                intent=decision.intent,
                metadata={
                    "reason": "empty_generated_response",
                },
            )

        return Response.success(
            reply_text,
            intent=decision.intent,
        )

    # ------------------------------------------------------------------
    # CLARIFICATION
    # ------------------------------------------------------------------

    def _handle_clarification(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None,
    ) -> Response:
        """Generate a clarification request."""

        question = (
            self._clean_response_text(decision.message)
            or DEFAULT_CLARIFICATION_RESPONSE
        )

        try:
            text = prompt_engine.phrase_clarification(question)
        except Exception:
            logger.exception(
                "Clarification phrasing failed",
            )
            text = question

        return Response.clarification(
            text,
            intent=decision.intent,
        )

    # ------------------------------------------------------------------
    # CONFIRMATION
    # ------------------------------------------------------------------

    def _handle_confirmation(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None,
    ) -> Response:
        """Generate a confirmation request."""

        prompt = (
            self._clean_response_text(decision.message)
            or DEFAULT_CONFIRMATION_RESPONSE
        )

        try:
            text = prompt_engine.phrase_confirmation_prompt(prompt)
        except Exception:
            logger.exception(
                "Confirmation phrasing failed",
            )
            text: str = prompt

        return Response.confirmation(
            text,
            intent=decision.intent,
        )

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    def _handle_cancelled(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None,
    ) -> Response:
        """Generate a cancellation response."""

        try:
            text = prompt_engine.phrase_cancellation()
        except Exception:
            logger.exception(
                "Cancellation phrasing failed",
            )
            text: str = DEFAULT_CANCELLED_RESPONSE

        return Response.success(
            text,
            intent=decision.intent,
        )

    # ------------------------------------------------------------------
    # EXECUTE
    # ------------------------------------------------------------------

    def _handle_execute(
        self,
        decision: Decision,
        conversation: Conversation,
        outcome: ExecutionOutcome | None,
    ) -> Response:
        """Generate a response for command execution."""

        if decision.intent is None:
            logger.warning(
                "Execute action received without an intent."
            )

            return Response.error(
                DEFAULT_UNDETERMINED_ACTION_RESPONSE,
            )

        # Defensive fallback.
        #
        # Normally core/assistant.py should execute the command first
        # and pass the resulting ExecutionOutcome here.
        if outcome is None:
            logger.warning(
                "Execute response requested without ExecutionOutcome; "
                "assuming success."
            )

            return self._action_success_response(
                decision.intent,
                metadata={
                    "execution_outcome": "missing_assumed_success",
                },
            )

        if outcome.success:
            return self._action_success_response(
                decision.intent,
                result_data=outcome.result_data,
                metadata=outcome.metadata,
            )

        return self._action_failure_response(
            decision.intent,
            outcome,
        )

    # ------------------------------------------------------------------
    # Execution response helpers
    # ------------------------------------------------------------------

    def _action_success_response(
        self,
        intent: Intent,
        *,
        result_data: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Response:
        """Generate a successful action response."""

        try:
            text = prompt_engine.phrase_action_success(intent)
        except Exception:
            logger.exception(
                "Action-success phrasing failed",
            )
            text = "Done."

        response_metadata = dict(metadata or {})

        if result_data is not None:
            response_metadata.setdefault(
                "result_data",
                result_data,
            )

        return Response.success(
            text,
            intent=intent,
            metadata=response_metadata,
        )

    def _action_failure_response(
        self,
        intent: Intent,
        outcome: ExecutionOutcome,
    ) -> Response:
        """Generate a safe user-facing command failure response."""

        action_description = self._describe_action(intent)

        # Log internal error details but don't expose raw exceptions
        # to the user.
        if outcome.error_message:
            logger.debug(
                "Command execution failed: action=%s error=%s",
                action_description,
                self._truncate_error(outcome.error_message),
            )

        try:
            text = prompt_engine.phrase_error_apology(
                action_description
            )
            
        except Exception:
            logger.exception("Error-apology phrasing failed")
            text = DEFAULT_EXECUTION_ERROR_RESPONSE

        metadata = dict(outcome.metadata)

        metadata.setdefault(
            "action_description",
            action_description,
        )

        return Response.error(
            text,
            intent=intent,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_user_text(decision: Decision) -> str:
        """Safely extract the original user utterance."""

        intent = getattr(decision, "intent", None)

        if intent is not None:
            raw_text = getattr(intent, "raw_text", None)

            if raw_text:
                return str(raw_text).strip()

        message = getattr(decision, "message", None)

        if message:
            return str(message).strip()

        return ""

    @staticmethod
    def _describe_action(intent: Intent) -> str:
        """Convert an intent into a human-readable action description."""

        sub_intent = getattr(intent, "sub_intent", None)

        if sub_intent:
            description = str(sub_intent)
        else:
            category = getattr(intent, "category", None)

            if category is None:
                return "that action"

            description = getattr(
                category,
                "value",
                str(category),
            )

        description = description.replace("_", " ")
        description = " ".join(description.split())

        return description or "that action"

    @staticmethod
    def _clean_response_text(value: Any) -> str:
        """Normalize generated text without changing its meaning."""

        if value is None:
            return ""

        text = str(value).strip()

        if not text:
            return ""

        return text

    @staticmethod
    def _truncate_error(
        error_message: str,
        limit: int = MAX_ERROR_DETAIL_LENGTH,
    ) -> str:
        """Prevent huge internal error logs."""

        text = str(error_message)

        if len(text) <= limit:
            return text

        return text[:limit] + "..."

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def registered_actions(self) -> list[str]:
        """Return registered decision-action names."""

        return [
            getattr(action, "value", str(action))
            for action in self._handlers
        ]

    def diagnostics(self) -> dict[str, Any]:
        """Return response-generator diagnostics."""

        return {
            "handler_count": len(self._handlers),
            "registered_actions": self.registered_actions(),
            "generator": self.__class__.__name__,
        }

    def reset_handlers(self) -> None:
        """Restore all built-in response handlers."""

        self._register_default_handlers()

        logger.debug(
            "Response generator handlers reset to defaults."
        )

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"handlers={len(self._handlers)})"
        )


# ============================================================================
# Global Singleton
# ============================================================================

response_generator = ResponseGenerator()


# ============================================================================
# Convenience API
# ============================================================================


def generate_response(
    decision: Decision,
    conversation: Conversation,
    outcome: ExecutionOutcome | None = None,
) -> Response:
    """
    Generate a response using the global response generator.

    This is the recommended lightweight API for most callers.
    """
    return response_generator.generate(
        decision,
        conversation,
        outcome,
    )


def response_generator_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global response generator."""
    return response_generator.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "ExecutionOutcome",
    "InvalidDecisionError",
    "Response",
    "ResponseGenerationError",
    "ResponseGenerator",
    "ResponseGeneratorError",
    "ResponseStatus",
    "generate_response",
    "response_generator",
    "response_generator_diagnostics",
]

