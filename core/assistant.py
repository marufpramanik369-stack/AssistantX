"""
core/assistant.py
================

AssistantX core orchestration layer.

The Assistant class coordinates one complete user interaction:

    Raw Input
        ↓
    Validation / Normalization
        ↓
    Exit Detection
        ↓
    Intent Classification
        ↓
    Command Router
        ↓
    Handler / AI Provider
        ↓
    History / Memory
        ↓
    TurnResult
        ↓
    Dashboard / Voice / EventBus

Design goals
------------
- Keep classification separate from execution.
- Keep AI providers pluggable.
- Avoid hard dependencies on optional services.
- Keep one conversation turn atomic.
- Protect the application from provider/classifier failures.
- Emit useful lifecycle events.
- Maintain compatibility with the existing AssistantX modules.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from config.constants import (
    DATE_DISPLAY_FORMAT,
    EXIT_KEYWORDS,
    IntentCategory,
)
from config.prompts import PromptContext, build_system_prompt
from config.settings import settings_manager
from core.command_router import (
    CommandResult,
    command_router,
)
from core.event_bus import Events, event_bus
from core.history import history_manager
from core.logger import get_logger
from core.memory import memory_manager
from core.utils import contains_any, normalize_text

logger = get_logger(__name__)


# ============================================================================
# Protocols / Types
# ============================================================================


class AIProviderProtocol(Protocol):
    """
    Structural interface required by AssistantX AI providers.

    Any provider implementing:

        generate(messages=..., system_prompt=...)

    can be injected into Assistant without inheritance.
    """

    def generate(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> str:
        ...


ClassifierFunc = Callable[
    [str],
    tuple[IntentCategory, dict[str, Any]],
]


# ============================================================================
# Result Models
# ============================================================================


@dataclass
class TurnResult:
    """
    Complete result of one AssistantX conversation turn.

    Attributes:
        utterance:
            Original normalized user input.

        intent:
            Classified intent.

        response_text:
            Human-readable response for UI/voice.

        success:
            Whether processing completed successfully.

        should_exit:
            Whether the application should terminate.

        data:
            Structured result data.

        turn_id:
            Unique ID for this turn.

        duration_ms:
            Total processing time.

        metadata:
            Additional diagnostic information.
    """

    utterance: str

    intent: IntentCategory

    response_text: str

    success: bool = True

    should_exit: bool = False

    data: dict[str, Any] = field(
        default_factory=dict
    )

    turn_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    duration_ms: float | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "utterance": self.utterance,
            "intent": (
                self.intent.value
                if isinstance(
                    self.intent,
                    IntentCategory,
                )
                else str(self.intent)
            ),
            "response_text": self.response_text,
            "success": self.success,
            "should_exit": self.should_exit,
            "data": dict(self.data),
            "turn_id": self.turn_id,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
        }

    def __bool__(self) -> bool:
        return self.success


# ============================================================================
# Assistant
# ============================================================================


class Assistant:
    """
    High-level AssistantX conversation orchestrator.

    The class itself serializes conversation turns so dashboard and voice
    input cannot modify one conversation simultaneously.

    AI provider and classifier are dependency-injected to keep this class
    independent from Gemini, Ollama, local AI, or any specific classifier.
    """

    def __init__(
        self,
        ai_provider: AIProviderProtocol | None = None,
        classifier: ClassifierFunc | None = None,
        user_name: str | None = None,
    ) -> None:

        self.ai_provider = ai_provider
        self.classifier = classifier

        remembered_name = memory_manager.recall(
            "user_name"
        )

        self.user_name = (
            user_name
            or remembered_name
            or None
        )

        # One turn at a time.
        self._turn_lock = threading.RLock()

        self._initialized_at = datetime.now(
            timezone.utc
        ).isoformat()

        self._total_turns = 0
        self._successful_turns = 0
        self._failed_turns = 0

        self._last_turn: TurnResult | None = None

        self._register_builtin_handlers()

        logger.info(
            "Assistant initialized. AI provider=%s, classifier=%s",
            self._provider_name(),
            self._classifier_name(),
        )

    # ------------------------------------------------------------------
    # Provider / Classifier information
    # ------------------------------------------------------------------

    def _provider_name(self) -> str | None:
        """Return a readable provider name."""

        if self.ai_provider is None:
            return None

        return self.ai_provider.__class__.__name__

    def _classifier_name(self) -> str | None:
        """Return a readable classifier name."""

        if self.classifier is None:
            return None

        return getattr(
            self.classifier,
            "__name__",
            self.classifier.__class__.__name__,
        )

    # ------------------------------------------------------------------
    # Built-in handlers
    # ------------------------------------------------------------------

    def _register_builtin_handlers(self) -> None:
        """
        Configure Assistant's general-chat fallback.

        Domain handlers such as weather, browser, music, apps, etc.
        should be registered by their owning modules.
        """

        command_router.set_fallback(
            self._handle_general_chat
        )

    def _handle_general_chat(
        self,
        _utterance: str,
        _slots: dict[str, Any],
    ) -> CommandResult:
        """
        Handle open-ended conversation through the injected AI provider.
        """

        if self.ai_provider is None:
            return CommandResult.fail(
                error="No AI provider configured.",
                intent=IntentCategory.GENERAL_CHAT,
                message=(
                    "I don't have a language model "
                    "connected right now."
                ),
            )

        try:
            system_prompt = (
                self._build_system_prompt()
            )

            max_history = self._get_max_history()

            messages = (
                history_manager.as_provider_messages(
                    limit=max_history
                )
            )

            reply = self.ai_provider.generate(
                messages=messages,
                system_prompt=system_prompt,
            )

            reply = self._normalize_response(
                reply
            )

            if not reply:
                return CommandResult.fail(
                    error="AI provider returned an empty response.",
                    intent=IntentCategory.GENERAL_CHAT,
                    message=(
                        "I couldn't generate a response "
                        "right now."
                    ),
                )

            self._emit_event_safe(
                Events.AI_RESPONSE_COMPLETE,
                {
                    "text": reply,
                    "provider": self._provider_name(),
                },
            )

            return CommandResult.ok(
                reply,
                intent=IntentCategory.GENERAL_CHAT,
            )

        except Exception as exc:
            logger.exception(
                "AI provider failed during general chat."
            )

            self._emit_event_safe(
                Events.AI_ERROR,
                {
                    "error": str(exc),
                    "provider": self._provider_name(),
                },
            )

            return CommandResult.fail(
                error=str(exc),
                intent=IntentCategory.GENERAL_CHAT,
                message=(
                    "Sorry, I ran into a problem "
                    "while thinking that through."
                ),
            )

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the current AI system prompt."""

        context = PromptContext(
            user_name=self.user_name,
            persona=settings_manager.get(
                "ai.system_persona",
                "default",
            ),
            language=settings_manager.get(
                "voice.language",
                "en-US",
            ),
            current_datetime=datetime.now(tz=timezone.utc).strftime(
                DATE_DISPLAY_FORMAT
            ),
            recent_memory=(
                memory_manager.as_context_string(
                    limit=8
                )
            ),
        )

        return build_system_prompt(
            context
        )

    def _get_max_history(self) -> int:
        """Read and sanitize maximum AI history size."""

        value = settings_manager.get(
            "ai.max_history_messages",
            50,
        )

        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 50

        return max(
            1,
            min(value, 500),
        )

    # ------------------------------------------------------------------
    # Main text entry point
    # ------------------------------------------------------------------

    def handle_text_input(
        self,
        utterance: str,
    ) -> TurnResult:
        """
        Process one complete text interaction.

        Steps:
            1. Validate input
            2. Save user message
            3. Detect exit command
            4. Classify intent
            5. Emit intent event
            6. Dispatch command
            7. Save assistant response
            8. Return TurnResult
        """

        started = time.perf_counter()

        with self._turn_lock:

            turn_id = uuid.uuid4().hex

            utterance = self._normalize_utterance(
                utterance
            )

            # ----------------------------------------------------------
            # Empty input
            # ----------------------------------------------------------

            if not utterance:
                result = TurnResult(
                    utterance="",
                    intent=IntentCategory.UNKNOWN,
                    response_text="",
                    success=False,
                    turn_id=turn_id,
                    metadata={
                        "reason": "empty_input",
                    },
                )

                result.duration_ms = self._duration_ms(
                    started
                )

                return result

            logger.debug(
                "Processing turn %s: %s",
                turn_id,
                utterance,
            )

            # ----------------------------------------------------------
            # History: user message
            # ----------------------------------------------------------

            self._save_user_message(
                utterance
            )

            # ----------------------------------------------------------
            # Exit command
            # ----------------------------------------------------------

            if self._is_exit_command(
                utterance
            ):
                result = self._handle_exit(
                    utterance,
                    turn_id,
                    started,
                )

                self._finalize_turn(
                    result
                )

                return result

            # ----------------------------------------------------------
            # Classification
            # ----------------------------------------------------------

            try:
                intent, slots = self._classify(
                    utterance
                )
            except Exception as exc:
                logger.exception(
                    "Intent classification failed."
                )

                intent = IntentCategory.GENERAL_CHAT
                slots = {}

                self._emit_event_safe(
                    Events.AI_ERROR,
                    {
                        "stage": "classification",
                        "error": str(exc),
                    },
                )

            slots = self._normalize_slots(
                slots
            )

            self._emit_event_safe(
                Events.INTENT_CLASSIFIED,
                {
                    "turn_id": turn_id,
                    "intent": intent.value,
                    "slots": slots,
                },
            )

            # ----------------------------------------------------------
            # Command routing
            # ----------------------------------------------------------

            try:
                command_result = (
                    command_router.dispatch(
                        intent,
                        utterance,
                        slots,
                    )
                )

            except Exception as exc:
                logger.exception(
                    "CommandRouter failed for intent '%s'.",
                    intent.value,
                )

                command_result = CommandResult.fail(
                    error=str(exc),
                    intent=intent,
                    message=(
                        "Sorry, I couldn't "
                        "process that command."
                    ),
                )

            # ----------------------------------------------------------
            # Save assistant response
            # ----------------------------------------------------------

            self._save_assistant_message(
                command_result
            )

            # ----------------------------------------------------------
            # Build final result
            # ----------------------------------------------------------

            result = TurnResult(
                utterance=utterance,
                intent=intent,
                response_text=(
                    command_result.message
                ),
                success=command_result.success,
                should_exit=False,
                data=dict(
                    command_result.data
                ),
                turn_id=turn_id,
                duration_ms=self._duration_ms(
                    started
                ),
                metadata={
                    "command_id": (
                        command_result.command_id
                    ),
                    "handler": (
                        command_result.metadata.get(
                            "handler"
                        )
                    ),
                    "used_fallback": (
                        command_result.metadata.get(
                            "used_fallback",
                            False,
                        )
                    ),
                    "error": command_result.error,
                },
            )

            self._finalize_turn(
                result
            )

            return result

    # ------------------------------------------------------------------
    # Voice entry point
    # ------------------------------------------------------------------

    def handle_voice_input(
        self,
        transcribed_text: str,
        confidence: float = 1.0,
    ) -> TurnResult:
        """
        Process recognized voice text.

        Confidence is used for diagnostics but does not alter
        command execution automatically.
        """

        try:
            confidence = float(
                confidence
            )
        except (TypeError, ValueError):
            confidence = 1.0

        confidence = max(
            0.0,
            min(1.0, confidence),
        )

        logger.debug(
            "Voice input received "
            "(confidence=%.2f): %s",
            confidence,
            transcribed_text,
        )

        result = self.handle_text_input(
            transcribed_text
        )

        result.metadata[
            "voice_confidence"
        ] = confidence

        return result

    # ------------------------------------------------------------------
    # Exit handling
    # ------------------------------------------------------------------

    def _handle_exit(
        self,
        utterance: str,
        turn_id: str,
        started: float,
    ) -> TurnResult:

        farewell = "Goodbye! Talk soon."

        self._save_assistant_message_text(
            farewell,
            IntentCategory.SYSTEM_CONTROL,
        )

        self._emit_event_safe(
            Events.APP_SHUTTING_DOWN,
            {
                "reason": "user_exit_command",
                "utterance": utterance,
                "turn_id": turn_id,
            },
        )

        return TurnResult(
            utterance=utterance,
            intent=IntentCategory.SYSTEM_CONTROL,
            response_text=farewell,
            success=True,
            should_exit=True,
            turn_id=turn_id,
            duration_ms=self._duration_ms(
                started
            ),
            metadata={
                "reason": "exit_command",
            },
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(
        self,
        utterance: str,
    ) -> tuple[
        IntentCategory,
        dict[str, Any],
    ]:
        """
        Classify user input.

        Uses injected brain.classifier when available.
        Otherwise uses a minimal keyword fallback.
        """

        if self.classifier is not None:
            try:
                result = self.classifier(
                    utterance
                )

                return self._normalize_classification(
                    result
                )

            except Exception:
                logger.exception(
                    "Injected classifier failed; "
                    "using naive classifier."
                )

        return self._naive_classify(
            utterance
        )

    @staticmethod
    def _normalize_classification(
        result: Any,
    ) -> tuple[
        IntentCategory,
        dict[str, Any],
    ]:
        """Normalize classifier output."""

        if not isinstance(
            result,
            tuple,
        ) or len(result) != 2:
            raise TypeError(
                "Classifier must return "
                "(IntentCategory, dict)."
            )

        intent, slots = result

        if not isinstance(
            intent,
            IntentCategory,
        ):
            raise TypeError(
                "Classifier returned an invalid IntentCategory."
            )

        if slots is None:
            slots = {}

        if not isinstance(
            slots,
            dict,
        ):
            raise TypeError(
                "Classifier slots must be a dictionary."
            )

        return intent, dict(slots)

    @staticmethod
    def _naive_classify(
        utterance: str,
    ) -> tuple[
        IntentCategory,
        dict[str, Any],
    ]:
        """
        Minimal emergency classifier.

        This is intentionally simple and exists only when brain/
        classification is unavailable.
        """

        text = normalize_text(
            utterance
        )

        keyword_map = {
            IntentCategory.WEATHER: (
                "weather",
                "temperature",
                "forecast",
                "rain",
                "weather today",
            ),

            IntentCategory.NEWS: (
                "news",
                "headline",
                "headlines",
                "latest news",
            ),

            IntentCategory.MUSIC: (
                "play music",
                "play song",
                "music",
                "song",
            ),

            IntentCategory.CALCULATION: (
                "calculate",
                "calculator",
                "plus",
                "minus",
                "times",
                "divided",
            ),

            IntentCategory.APP_LAUNCH: (
                "open",
                "launch",
                "start",
            ),

            IntentCategory.WEB_SEARCH: (
                "search",
                "google",
                "look up",
                "find online",
            ),
        }

        for intent, keywords in keyword_map.items():
            if contains_any(
                text,
                keywords,
            ):
                return intent, {}

        return (
            IntentCategory.GENERAL_CHAT,
            {},
        )

    # ------------------------------------------------------------------
    # Input normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_utterance(
        utterance: Any,
    ) -> str:
        if utterance is None:
            return ""

        return str(
            utterance
        ).strip()

    @staticmethod
    def _normalize_slots(
        slots: Any,
    ) -> dict[str, Any]:
        if slots is None:
            return {}

        if not isinstance(
            slots,
            dict,
        ):
            logger.warning(
                "Invalid classifier slots; "
                "using empty slots."
            )
            return {}

        return dict(slots)

    @staticmethod
    def _normalize_response(
        response: Any,
    ) -> str:
        if response is None:
            return ""

        return str(
            response
        ).strip()

    # ------------------------------------------------------------------
    # Exit detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_exit_command(
        utterance: str,
    ) -> bool:
        return contains_any(
            utterance,
            EXIT_KEYWORDS,
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    @staticmethod
    def _save_user_message(
        utterance: str,
    ) -> None:
        """Persist user message safely."""

        try:
            history_manager.add_user_message(
                utterance
            )
        except Exception:
            logger.exception(
                "Failed to save user message to history."
            )

    @staticmethod
    def _save_assistant_message(
        result: CommandResult,
    ) -> None:
        """Persist assistant response safely."""

        if not result.message:
            return

        try:
            history_manager.add_assistant_message(
                result.message,
                intent=(
                    result.intent.value
                    if isinstance(
                        result.intent,
                        IntentCategory,
                    )
                    else None
                ),
            )
        except Exception:
            logger.exception(
                "Failed to save assistant response to history."
            )

    @staticmethod
    def _save_assistant_message_text(
        message: str,
        intent: IntentCategory,
    ) -> None:
        """Persist a plain assistant message."""

        try:
            history_manager.add_assistant_message(
                message,
                intent=intent.value,
            )
        except Exception:
            logger.exception(
                "Failed to save assistant message."
            )

    # ------------------------------------------------------------------
    # User identity
    # ------------------------------------------------------------------

    def set_user_name(
        self,
        name: str,
    ) -> None:
        """
        Update the current user's name and persist it in long-term memory.
        """

        name = str(
            name or ""
        ).strip()

        if not name:
            raise ValueError(
                "User name cannot be empty."
            )

        if len(name) > 100:
            raise ValueError(
                "User name is too long."
            )

        with self._turn_lock:
            self.user_name = name

            try:
                memory_manager.remember(
                    "user_name",
                    name,
                    importance=5,
                    source="user_provided",
                )
            except Exception:
                logger.exception(
                    "Failed to save user name to memory."
                )
                raise

        logger.info(
            "User name updated to '%s'.",
            name,
        )

    def get_user_name(
        self,
    ) -> str | None:
        """Return current user name."""

        return self.user_name

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    def set_ai_provider(
        self,
        provider: AIProviderProtocol | None,
    ) -> None:
        """Replace the active AI provider at runtime."""

        self.ai_provider = provider

        logger.info(
            "AI provider changed to '%s'.",
            self._provider_name()
            or "None",
        )

    def set_classifier(
        self,
        classifier: ClassifierFunc | None,
    ) -> None:
        """Replace the classifier at runtime."""

        if (
            classifier is not None
            and not callable(classifier)
        ):
            raise TypeError(
                "classifier must be callable or None."
            )

        self.classifier = classifier

        logger.info(
            "Classifier changed to '%s'.",
            self._classifier_name()
            or "None",
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_event_safe(
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Emit EventBus event without allowing EventBus failure to break
        the Assistant.
        """

        try:
            event_bus.emit(
                event_name,
                payload,
            )
        except Exception:
            logger.exception(
                "Failed to emit event '%s'.",
                event_name,
            )

    # ------------------------------------------------------------------
    # Turn bookkeeping
    # ------------------------------------------------------------------

    def _finalize_turn(
        self,
        result: TurnResult,
    ) -> None:
        with self._turn_lock:
            self._total_turns += 1

            if result.success:
                self._successful_turns += 1
            else:
                self._failed_turns += 1

            self._last_turn = result

            logger.debug(
                "Turn %s completed: success=%s, "
                "intent=%s, duration=%.2fms",
                result.turn_id,
                result.success,
                result.intent.value,
                result.duration_ms or 0.0,
            )

    @staticmethod
    def _duration_ms(
        started: float,
    ) -> float:
        return round(
            (
                time.perf_counter()
                - started
            )
            * 1000.0,
            3,
        )

    # ------------------------------------------------------------------
    # Runtime information
    # ------------------------------------------------------------------

    @property
    def total_turns(self) -> int:
        return self._total_turns

    @property
    def successful_turns(self) -> int:
        return self._successful_turns

    @property
    def failed_turns(self) -> int:
        return self._failed_turns

    @property
    def last_turn(self) -> TurnResult | None:
        return self._last_turn

    def stats(self) -> dict[str, Any]:
        """Return Assistant runtime statistics."""

        with self._turn_lock:
            return {
                "total_turns": self._total_turns,
                "successful_turns": (
                    self._successful_turns
                ),
                "failed_turns": (
                    self._failed_turns
                ),
                "success_rate": round(
                    (
                        self._successful_turns
                        / self._total_turns
                        * 100
                    )
                    if self._total_turns
                    else 0.0,
                    2,
                ),
                "ai_provider": self._provider_name(),
                "classifier": self._classifier_name(),
                "user_name": self.user_name,
                "initialized_at": (
                    self._initialized_at
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed Assistant diagnostics."""

        with self._turn_lock:
            last_turn = self._last_turn

            return {
                "module": __name__,
                "class": self.__class__.__name__,
                "ai_provider": self._provider_name(),
                "classifier": self._classifier_name(),
                "user_name_configured": (
                    self.user_name is not None
                ),
                "initialized_at": (
                    self._initialized_at
                ),
                "stats": self.stats(),
                "last_turn": (
                    last_turn.to_dict()
                    if last_turn
                    else None
                ),
            }

    # ------------------------------------------------------------------
    # Reset statistics
    # ------------------------------------------------------------------

    def reset_stats(self) -> None:
        """Reset runtime turn statistics."""

        with self._turn_lock:
            self._total_turns = 0
            self._successful_turns = 0
            self._failed_turns = 0
            self._last_turn = None

        logger.debug(
            "Assistant statistics reset."
        )

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self._provider_name()!r}, "
            f"classifier={self._classifier_name()!r}, "
            f"turns={self._total_turns}"
            f")"
        )


# ============================================================================
# Factory
# ============================================================================


def create_default_assistant() -> Assistant:
    """
    Create an Assistant using currently available application components.

    Imports are intentionally lazy to avoid circular imports:

        core → ai
        core → brain

    The factory gracefully falls back when optional components are not ready.
    """

    ai_provider: AIProviderProtocol | None = None

    classifier: ClassifierFunc | None = None

    # ------------------------------------------------------------------
    # AI Provider
    # ------------------------------------------------------------------

    try:
        from ai.provider import (
            get_active_provider,
        )

        ai_provider = (
            get_active_provider()
        )

        if ai_provider is not None:
            logger.info(
                "Default Assistant using AI provider: %s",
                ai_provider.__class__.__name__,
            )

    except Exception:  # noqa: BLE001
        logger.warning(
            "No active AI provider available. "
            "General chat will be unavailable."
        )

    # ------------------------------------------------------------------
    # Brain classifier
    # ------------------------------------------------------------------

    try:
        from brain.classifier import (
            classify_intent,
        )

        classifier = classify_intent

        logger.info(
            "Brain classifier loaded successfully."
        )

    except Exception:  # noqa: BLE001
        logger.warning(
            "brain.classifier unavailable; "
            "Assistant will use naive classification."
        )

    return Assistant(
        ai_provider=ai_provider,
        classifier=classifier,
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "AIProviderProtocol",
    "Assistant",
    "ClassifierFunc",
    "TurnResult",
    "create_default_assistant",
]
