"""
core/assistant.py
=================

AssistantX Core Conversation Orchestration Engine.

This module provides the high-level ``Assistant`` class responsible for
coordinating a complete user interaction from input to final response.

Processing Pipeline
-------------------

    Raw Input
        ↓
    Validation / Normalization
        ↓
    Exit Command Detection
        ↓
    Intent Classification
        ↓
    CommandRouter Dispatch
        ↓
    Handler / AI Provider
        ↓
    Response Normalization
        ↓
    History Persistence
        ↓
    TurnResult
        ↓
    EventBus / Dashboard / Voice

Architecture
------------

The Assistant layer intentionally acts as an orchestration layer.

It does NOT own:

- speech recognition
- text-to-speech
- wake-word detection
- noise filtering
- AI provider implementation
- domain-specific command implementation
- long-term memory implementation
- UI implementation

Those responsibilities belong to their respective modules.

The Assistant coordinates them.

Design principles
-----------------

- Separation of concerns
- Dependency injection
- Provider independence
- Graceful degradation
- Thread-safe turn processing
- Event-driven integration
- Safe prompt construction
- History persistence
- Runtime diagnostics
- Backward-compatible public API

Assistant identity
------------------

AssistantX's assistant identity is fixed as:

    Name       : JEROX
    Wake word  : JEROX
    Voice      : Female
    Languages  : Bengali, English, Hindi

The Assistant class does not allow conversation or prompt content to
change the assistant's fixed identity.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

import config.constants
import config.settings

from config.prompts import (
    ASSISTANT_IDENTITY,
    ASSISTANT_VOICE_GENDER,
    ASSISTANT_WAKE_WORD,
    PromptContext,
    build_system_prompt,
)

from core.command_router import (
    CommandResult,
    command_router,
)

from core.event_bus import (
    Events,
    event_bus,
)

from core.history import history_manager
from core.logger import get_logger
from core.memory import memory_manager
from core.utils import contains_any, normalize_text


logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_MAX_HISTORY: int = 50
MIN_MAX_HISTORY: int = 1
MAX_MAX_HISTORY: int = 500

MAX_USER_NAME_LENGTH: int = 100
MAX_UTTERANCE_LOG_LENGTH: int = 100

DEFAULT_PERSONA: str = "default"
DEFAULT_LANGUAGE: str = "en"

EXIT_FAREWELL: str = "Goodbye! Talk soon."

NO_PROVIDER_MESSAGE: str = (
    "I don't have a language model connected right now."
)

AI_ERROR_MESSAGE: str = (
    "Sorry, I ran into a problem while thinking that through."
)

ROUTER_ERROR_MESSAGE: str = (
    "Sorry, I couldn't process that command."
)

EMPTY_RESPONSE_MESSAGE: str = (
    "I couldn't generate a response right now."
)


# ============================================================================
# Protocols / Types
# ============================================================================


class AIProviderProtocol(Protocol):
    """
    Structural interface for AssistantX AI providers.

    Any provider implementing ``generate()`` with this interface can be
    injected into ``Assistant``.

    Parameters
    ----------
    messages:
        Conversation messages in provider-compatible format.

    system_prompt:
        System instruction for the provider.

    Returns
    -------
    str
        Generated response text.
    """

    def generate(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> str:
        """Generate an AI response."""
        ...


ClassifierFunc = Callable[
    [str],
    tuple[config.constants.IntentCategory, dict[str, Any]],
]


# ============================================================================
# Result Model
# ============================================================================


@dataclass
class TurnResult:
    """
    Standardized result of one Assistant conversation turn.

    Attributes
    ----------
    utterance:
        Normalized user input.

    intent:
        Classified intent.

    response_text:
        Final human-readable response.

    success:
        Whether the turn completed successfully.

    should_exit:
        Whether the application should terminate.

    data:
        Structured handler result data.

    turn_id:
        Unique identifier for the conversation turn.

    duration_ms:
        Processing duration in milliseconds.

    metadata:
        Diagnostic and execution metadata.
    """

    utterance: str

    intent: config.constants.IntentCategory

    response_text: str

    success: bool = True

    should_exit: bool = False

    data: dict[str, Any] = field(
        default_factory=dict
    )

    turn_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    duration_ms: Optional[float] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the result to a JSON-friendly dictionary.
        """

        intent = (
            self.intent.value
            if isinstance(
                self.intent,
                config.constants.IntentCategory,
            )
            else str(self.intent)
        )

        return {
            "utterance": self.utterance,
            "intent": intent,
            "response_text": self.response_text,
            "success": self.success,
            "should_exit": self.should_exit,
            "data": dict(self.data),
            "turn_id": self.turn_id,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
        }

    def __bool__(self) -> bool:
        """Return True when the turn succeeded."""

        return self.success


# ============================================================================
# Assistant
# ============================================================================


class Assistant:
    """
    High-level AssistantX conversation orchestrator.

    The Assistant coordinates:

        Input
        → Classification
        → CommandRouter
        → Handler / AI
        → History
        → Events
        → TurnResult

    Parameters
    ----------
    ai_provider:
        Optional AI provider.

    classifier:
        Optional intent-classification callable.

    user_name:
        Optional user display name.

    Notes
    -----

    Turn processing is serialized with an RLock so dashboard, voice,
    automation, and text inputs cannot corrupt shared conversation state.
    """

    def __init__(
        self,
        ai_provider: Optional[AIProviderProtocol] = None,
        classifier: Optional[ClassifierFunc] = None,
        user_name: Optional[str] = None,
    ) -> None:

        if classifier is not None and not callable(classifier):
            raise TypeError(
                "classifier must be callable or None, "
                f"got {type(classifier).__name__}."
            )

        self.ai_provider = ai_provider
        self.classifier = classifier

        # ------------------------------------------------------------
        # Threading
        # ------------------------------------------------------------

        self._turn_lock = threading.RLock()

        # ------------------------------------------------------------
        # User identity
        # ------------------------------------------------------------

        remembered_name = None

        try:
            remembered_name = memory_manager.recall(
                "user_name"
            )
        except Exception as exc:
            logger.warning(
                "Unable to recall user name from memory: %s",
                exc,
            )

        self.user_name = (
            self._sanitize_user_name(user_name)
            or self._sanitize_user_name(remembered_name)
            or None
        )

        # ------------------------------------------------------------
        # Runtime metadata
        # ------------------------------------------------------------

        self._initialized_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        # ------------------------------------------------------------
        # Statistics
        # ------------------------------------------------------------

        self._total_turns = 0
        self._successful_turns = 0
        self._failed_turns = 0
        self._last_turn: Optional[TurnResult] = None

        # ------------------------------------------------------------
        # Register fallback
        # ------------------------------------------------------------

        self._register_builtin_handlers()

        logger.info(
            "Assistant initialized: "
            "name=%s, wake_word=%s, voice_gender=%s, "
            "ai_provider=%s, classifier=%s, user_name=%r",
            ASSISTANT_IDENTITY,
            ASSISTANT_WAKE_WORD,
            ASSISTANT_VOICE_GENDER,
            self._provider_name(),
            self._classifier_name(),
            self.user_name,
        )

    # ========================================================================
    # Provider / Classifier Information
    # ========================================================================

    def _provider_name(self) -> Optional[str]:
        """
        Return the active provider class name.
        """

        provider = self.ai_provider

        if provider is None:
            return None

        return provider.__class__.__name__

    def _classifier_name(self) -> Optional[str]:
        """
        Return the active classifier name.
        """

        classifier = self.classifier

        if classifier is None:
            return None

        return getattr(
            classifier,
            "__name__",
            classifier.__class__.__name__,
        )

    # ========================================================================
    # Built-in Handlers
    # ========================================================================

    def _register_builtin_handlers(self) -> None:
        """
        Register the general-chat fallback handler.

        Domain-specific handlers should be registered by their owning
        modules.
        """

        logger.debug(
            "Registering built-in general chat fallback."
        )

        command_router.set_fallback(
            self._handle_general_chat
        )

        try:
            from automation.commands import register_automation_commands

            register_automation_commands(self._handle_general_chat)
        except Exception as exc:
            logger.warning(
                "Automation commands unavailable: %s",
                exc,
            )

    # ========================================================================
    # General AI Chat
    # ========================================================================

    def _generate_general_chat_response(self) -> str:
        """
        Generate a response using the active AI provider.
        """

        if self.ai_provider is None:
            return ""

        logger.debug(
            "Starting AI generation via %s",
            self._provider_name(),
        )

        system_prompt = self._build_system_prompt()

        max_history = self._get_max_history()

        messages = history_manager.as_provider_messages(
            limit=max_history
        )

        # provider.generate() আলাদা system_prompt নেয় না, তাই প্রথম মেসেজ হিসেবে দিচ্ছি
        messages = [
            {"role": "system", "content": system_prompt},
            *list(messages),
        ]

        logger.debug(
            "Calling AI provider with %d messages.",
            len(messages),
        )

        result = self.ai_provider.generate(messages)

        # generate() একটা CompletionResult ফেরত দেয়, সাধারণ লেখা নয়
        if hasattr(result, "ok"):
            if not result.ok:
                raise RuntimeError(result.error or "AI provider failed")
            reply = result.text
        else:
            reply = result

        return self._normalize_response(
            reply
        )

    def _handle_general_chat(
        self,
        _utterance: str,
        _slots: dict[str, Any],
    ) -> CommandResult:
        """
        Handle general conversation through the configured AI provider.
        """

        if self.ai_provider is None:

            logger.warning(
                "General chat requested without an AI provider."
            )

            return CommandResult.fail(
                error="No AI provider configured.",
                intent=(
                    config.constants.IntentCategory.GENERAL_CHAT
                ),
                message=NO_PROVIDER_MESSAGE,
            )

        try:

            reply = (
                self._generate_general_chat_response()
            )

            if not reply:

                logger.warning(
                    "AI provider returned an empty response."
                )

                return CommandResult.fail(
                    error=(
                        "AI provider returned an empty response."
                    ),
                    intent=(
                        config.constants.IntentCategory.GENERAL_CHAT
                    ),
                    message=EMPTY_RESPONSE_MESSAGE,
                )

            self._emit_event_safe(
                Events.AI_RESPONSE_COMPLETE,
                {
                    "text": reply,
                    "provider": self._provider_name(),
                    "length": len(reply),
                },
            )

            return CommandResult.ok(
                reply,
                intent=(
                    config.constants.IntentCategory.GENERAL_CHAT
                ),
            )

        except Exception as exc:

            logger.exception(
                "AI provider failed during general chat: %s",
                exc,
            )

            self._emit_event_safe(
                Events.AI_ERROR,
                {
                    "stage": "generation",
                    "error": str(exc),
                    "provider": self._provider_name(),
                    "error_type": type(exc).__name__,
                },
            )

            return CommandResult.fail(
                error=str(exc),
                intent=(
                    config.constants.IntentCategory.GENERAL_CHAT
                ),
                message=AI_ERROR_MESSAGE,
            )

    # ========================================================================
    # Prompt Building
    # ========================================================================

    def _get_setting(
        self,
        path: str,
        default: Any,
    ) -> Any:
        """
        Safely retrieve a setting.

        This protects the conversation engine from malformed or partially
        migrated configuration files.
        """

        try:

            manager = config.settings.settings_manager

            value = manager.get(
                path,
                default,
            )

            return (
                default
                if value is None
                else value
            )

        except Exception as exc:

            logger.warning(
                "Unable to read setting %r: %s",
                path,
                exc,
            )

            return default

    def _get_persona(self) -> str:
        """
        Return configured AI persona.
        """

        persona = self._get_setting(
            "ai.system_persona",
            DEFAULT_PERSONA,
        )

        if not isinstance(
            persona,
            str,
        ):
            return DEFAULT_PERSONA

        persona = persona.strip().lower()

        return (
            persona
            if persona
            else DEFAULT_PERSONA
        )

    def _get_language(self) -> str:
        """
        Return configured assistant language.

        Supports the new canonical:

            bn
            en
            hi

        while allowing legacy regional identifiers such as:

            bn-BD
            en-US
            hi-IN
        """

        language = self._get_setting(
            "voice.language",
            DEFAULT_LANGUAGE,
        )

        if not isinstance(
            language,
            str,
        ):
            return DEFAULT_LANGUAGE

        normalized = (
            language
            .strip()
            .lower()
            .replace("_", "-")
        )

        if (
            normalized == "bn"
            or normalized.startswith("bn-")
        ):
            return "bn"

        if (
            normalized == "en"
            or normalized.startswith("en-")
        ):
            return "en"

        if (
            normalized == "hi"
            or normalized.startswith("hi-")
        ):
            return "hi"

        logger.warning(
            "Unsupported assistant language %r; "
            "falling back to %s.",
            language,
            DEFAULT_LANGUAGE,
        )

        return DEFAULT_LANGUAGE

    def _build_system_prompt(self) -> str:
        """
        Build the complete system prompt for the current turn.
        """

        try:

            memory_context = ""

            try:
                memory_context = (
                    memory_manager.as_context_string(
                        limit=8
                    )
                    or ""
                )
            except Exception as exc:
                logger.warning(
                    "Unable to load memory context: %s",
                    exc,
                )

            current_datetime = (
                datetime.now(
                    tz=timezone.utc
                ).strftime(
                    config.constants.DATE_DISPLAY_FORMAT
                )
            )

            context = PromptContext(
                user_name=self.user_name,
                persona=self._get_persona(),
                language=self._get_language(),
                current_datetime=current_datetime,
                recent_memory=memory_context,
            )

            prompt = build_system_prompt(
                context
            )

            if not prompt.strip():
                raise ValueError(
                    "Prompt builder returned an empty system prompt."
                )

            logger.debug(
                "System prompt built successfully: %d chars.",
                len(prompt),
            )

            return prompt

        except Exception as exc:

            logger.exception(
                "Failed to build system prompt: %s",
                exc,
            )

            # Safe JEROX fallback.
            return (
                f"You are {ASSISTANT_IDENTITY}, "
                "a helpful personal AI assistant.\n"
                f"Your wake word is {ASSISTANT_WAKE_WORD}.\n"
                f"Your voice identity is fixed as "
                f"{ASSISTANT_VOICE_GENDER}.\n"
                "Respond helpfully and accurately.\n"
                "Do not invent actions, facts, or results."
            )

    # ========================================================================
    # History Configuration
    # ========================================================================

    def _get_max_history(self) -> int:
        """
        Return a sanitized maximum number of history messages.
        """

        value = self._get_setting(
            "ai.max_history_messages",
            DEFAULT_MAX_HISTORY,
        )

        try:
            value = int(value)

        except (
            TypeError,
            ValueError,
        ):

            logger.warning(
                "Invalid max_history_messages=%r; "
                "using default=%d.",
                value,
                DEFAULT_MAX_HISTORY,
            )

            value = DEFAULT_MAX_HISTORY

        clamped = max(
            MIN_MAX_HISTORY,
            min(
                value,
                MAX_MAX_HISTORY,
            ),
        )

        if clamped != value:

            logger.debug(
                "max_history_messages clamped: %d → %d",
                value,
                clamped,
            )

        return clamped

    # ========================================================================
    # Main Text Entry Point
    # ========================================================================

    def handle_text_input(
        self,
        utterance: str,
    ) -> TurnResult:
        """
        Process one complete text conversation turn.

        The turn is serialized through ``_turn_lock``.
        """

        started = time.perf_counter()

        with self._turn_lock:

            turn_id = uuid.uuid4().hex

            # --------------------------------------------------------
            # Normalize
            # --------------------------------------------------------

            normalized = (
                self._normalize_utterance(
                    utterance
                )
            )

            # --------------------------------------------------------
            # Empty input
            # --------------------------------------------------------

            if not normalized:

                logger.debug(
                    "Empty input received: turn=%s",
                    turn_id,
                )

                result = TurnResult(
                    utterance="",
                    intent=(
                        config.constants.IntentCategory.UNKNOWN
                    ),
                    response_text="",
                    success=False,
                    turn_id=turn_id,
                    metadata={
                        "reason": "empty_input",
                    },
                )

                result.duration_ms = (
                    self._duration_ms(
                        started
                    )
                )

                self._finalize_turn(
                    result
                )

                return result

            logger.debug(
                "Processing turn=%s utterance=%r",
                turn_id,
                normalized[
                    :MAX_UTTERANCE_LOG_LENGTH
                ],
            )

            # --------------------------------------------------------
            # Save user input
            # --------------------------------------------------------

            self._save_user_message(
                normalized
            )

            # --------------------------------------------------------
            # Exit detection
            # --------------------------------------------------------

            if self._is_exit_command(
                normalized
            ):

                logger.info(
                    "Exit command detected: turn=%s",
                    turn_id,
                )

                result = self._handle_exit(
                    normalized,
                    turn_id,
                    started,
                )

                self._finalize_turn(
                    result
                )

                return result

            # --------------------------------------------------------
            # Classification
            # --------------------------------------------------------

            classification_failed = False

            try:

                intent, slots = self._classify(
                    normalized
                )

            except Exception as exc:

                classification_failed = True

                logger.exception(
                    "Intent classification failed: "
                    "turn=%s error=%s",
                    turn_id,
                    exc,
                )

                intent = (
                    config.constants.IntentCategory.GENERAL_CHAT
                )

                slots = {}

                self._emit_event_safe(
                    Events.AI_ERROR,
                    {
                        "stage": "classification",
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "turn_id": turn_id,
                    },
                )

            slots = self._normalize_slots(
                slots
            )

            logger.debug(
                "Classification complete: turn=%s intent=%s",
                turn_id,
                intent.value,
            )

            # --------------------------------------------------------
            # Classification event
            # --------------------------------------------------------

            self._emit_event_safe(
                Events.INTENT_CLASSIFIED,
                {
                    "turn_id": turn_id,
                    "intent": intent.value,
                    "slots": dict(slots),
                    "utterance": normalized[
                        :MAX_UTTERANCE_LOG_LENGTH
                    ],
                },
            )

            # --------------------------------------------------------
            # Command routing
            # --------------------------------------------------------

            try:

                command_result = (
                    command_router.dispatch(
                        intent,
                        normalized,
                        slots,
                    )
                )

            except Exception as exc:

                logger.exception(
                    "CommandRouter failed: "
                    "intent=%r turn=%s error=%s",
                    intent.value,
                    turn_id,
                    exc,
                )

                command_result = (
                    CommandResult.fail(
                        error=str(exc),
                        intent=intent,
                        message=ROUTER_ERROR_MESSAGE,
                    )
                )

            # --------------------------------------------------------
            # Save response
            # --------------------------------------------------------

            self._save_assistant_message(
                command_result
            )

            # --------------------------------------------------------
            # Build result
            # --------------------------------------------------------

            result = TurnResult(
                utterance=normalized,
                intent=intent,
                response_text=(
                    self._normalize_response(
                        command_result.message
                    )
                ),
                success=bool(
                    command_result.success
                ),
                should_exit=False,
                data=dict(
                    command_result.data
                    or {}
                ),
                turn_id=turn_id,
                duration_ms=(
                    self._duration_ms(
                        started
                    )
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
                    "error": (
                        command_result.error
                    ),
                    "classification_failed": (
                        classification_failed
                    ),
                },
            )

            self._finalize_turn(
                result
            )

            logger.info(
                "Turn completed: "
                "turn=%s success=%s intent=%s duration=%.2fms",
                turn_id,
                result.success,
                result.intent.value,
                result.duration_ms or 0.0,
            )

            return result

    # ========================================================================
    # Voice Entry Point
    # ========================================================================

    def handle_voice_input(
        self,
        transcribed_text: str,
        confidence: float = 1.0,
    ) -> TurnResult:
        """
        Process speech-recognition output.

        The Assistant does not perform speech recognition itself.

        ``confidence`` is stored in result metadata and does not
        automatically block command execution.
        """

        try:
            confidence = float(
                confidence
            )
        except (
            TypeError,
            ValueError,
        ):
            confidence = 1.0

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        logger.debug(
            "Voice input received: confidence=%.3f text=%r",
            confidence,
            str(transcribed_text)[:MAX_UTTERANCE_LOG_LENGTH],
        )

        result = self.handle_text_input(
            transcribed_text
        )

        result.metadata[
            "voice_confidence"
        ] = confidence

        result.metadata[
            "input_mode"
        ] = "voice"

        return result

    # ========================================================================
    # Exit Handling
    # ========================================================================

    def _handle_exit(
        self,
        utterance: str,
        turn_id: str,
        started: float,
    ) -> TurnResult:
        """
        Handle a user exit command.
        """

        self._save_assistant_message_text(
            EXIT_FAREWELL,
            config.constants.IntentCategory.SYSTEM_CONTROL,
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
            intent=(
                config.constants.IntentCategory.SYSTEM_CONTROL
            ),
            response_text=EXIT_FAREWELL,
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

    # ========================================================================
    # Classification
    # ========================================================================

    def _classify(
        self,
        utterance: str,
    ) -> tuple[
        config.constants.IntentCategory,
        dict[str, Any],
    ]:
        """
        Classify an utterance.

        Uses the injected classifier when available. If the injected
        classifier fails, the lightweight fallback classifier is used.
        """

        if self.classifier is not None:

            try:

                logger.debug(
                    "Using injected classifier: %s",
                    self._classifier_name(),
                )

                result = self.classifier(
                    utterance
                )

                return (
                    self._normalize_classification(
                        result
                    )
                )

            except Exception as exc:

                logger.exception(
                    "Injected classifier failed; "
                    "falling back to naive classifier: %s",
                    exc,
                )

        logger.debug(
            "Using naive fallback classifier."
        )

        return self._naive_classify(
            utterance
        )


    @staticmethod
    def _normalize_classification(
        result: Any,
    ) -> tuple[
        config.constants.IntentCategory,
        dict[str, Any],
    ]:
        """
        Normalize classifier output.

        Supports both:

        1. Legacy AssistantX classifier format:
           (IntentCategory, dict)

        2. Brain Intent object:
           brain.intent.Intent

        This keeps the Assistant layer backward compatible while
        allowing the modern brain classifier to be used directly.
        """

        # ----------------------------------------------------------------
        # Modern brain.intent.Intent object
        # ----------------------------------------------------------------

        try:
            from brain.intent import Intent as BrainIntent
        except Exception:
            BrainIntent = None

        if (
            BrainIntent is not None
            and isinstance(result, BrainIntent)
        ):
            intent_category = result.category

            if not isinstance(
                intent_category,
                config.constants.IntentCategory,
            ):
                try:
                    intent_category = (
                        config.constants.IntentCategory(
                            intent_category
                        )
                    )
                except Exception as exc:
                    raise TypeError(
                        "Brain Intent category must be a valid "
                        "IntentCategory. "
                        f"Got {type(result.category).__name__}."
                    ) from exc

            entities: dict[str, Any] = {}

            raw_entities = getattr(
                result,
                "entities",
                None,
            )

            if isinstance(
                raw_entities,
                dict,
            ):
                entities = dict(raw_entities)

            elif raw_entities:
                try:
                    for entity in raw_entities:
                        name = getattr(
                            entity,
                            "name",
                            None,
                        )

                        value = getattr(
                            entity,
                            "value",
                            None,
                        )

                        if name and value is not None:
                            entities[str(name)] = value

                except Exception as exc:
                    logger.debug(
                        "Unable to normalize Intent entities: %s",
                        exc,
                    )

            # Preserve useful classifier metadata.
            metadata = {
                "confidence": getattr(
                    result,
                    "confidence",
                    None,
                ),
                "sub_intent": getattr(
                    result,
                    "sub_intent",
                    None,
                ),
                "requires_confirmation": getattr(
                    result,
                    "requires_confirmation",
                    False,
                ),
            }

            metadata = {
                key: value
                for key, value in metadata.items()
                if value is not None
            }

            entities["_classifier_metadata"] = metadata

            return (
                intent_category,
                entities,
            )

        # ----------------------------------------------------------------
        # Legacy classifier format:
        # (IntentCategory, dict)
        # ----------------------------------------------------------------

        if (
            not isinstance(
                result,
                tuple,
            )
            or len(result) != 2
        ):
            raise TypeError(
                "Classifier must return either an "
                "Intent object or "
                "(IntentCategory, dict). "
                f"Got {type(result).__name__}."
            )

        intent, slots = result

        if not isinstance(
            intent,
            config.constants.IntentCategory,
        ):
            raise TypeError(
                "Classifier intent must be "
                "IntentCategory. "
                f"Got {type(intent).__name__}."
            )

        if slots is None:
            slots = {}

        if not isinstance(
            slots,
            dict,
        ):
            raise TypeError(
                "Classifier slots must be a dict. "
                f"Got {type(slots).__name__}."
            )

        return (
            intent,
            dict(slots),
        )




    @staticmethod
    def _naive_classify(
        utterance: str,
    ) -> tuple[
        config.constants.IntentCategory,
        dict[str, Any],
    ]:
        """
        Lightweight keyword-based fallback classifier.

        This classifier intentionally remains simple. The primary
        classifier should live in ``brain/``.
        """

        text = normalize_text(
            utterance
        )

        keyword_map = {
            config.constants.IntentCategory.WEATHER: (
                "weather",
                "temperature",
                "forecast",
                "rain",
                "sunny",
            ),

            config.constants.IntentCategory.NEWS: (
                "news",
                "headline",
                "headlines",
                "latest news",
            ),

            config.constants.IntentCategory.MUSIC: (
                "play music",
                "play song",
                "music",
                "song",
            ),

            config.constants.IntentCategory.CALCULATION: (
                "calculate",
                "calculator",
                "plus",
                "minus",
                "times",
            ),

            config.constants.IntentCategory.APP_LAUNCH: (
                "open",
                "launch",
                "start",
                "খোলো",
                "খুলো",
                "খুলুন",
                "খুলে দাও",
                "ওপেন",
                "লঞ্চ",
                "खोलो",
                "close",
                "quit",
                "বন্ধ করো",
                "বন্ধ কর",
                "বন্ধ করুন",
                "বন্ধ করে দাও",
                "बंद करो",
                "screenshot",
                "screen shot",
                "স্ক্রিনশট",
                "স্ক্রীনশট",
                "स्क्रीनशॉट",
                "সার্চ",
                "খুঁজো",
                "খোঁজো",
                "खोजो",
            ),

            config.constants.IntentCategory.WEB_SEARCH: (
                "search",
                "google",
                "look up",
                "find",
            ),
        }

        for intent, keywords in keyword_map.items():

            if contains_any(
                text,
                keywords,
            ):
                return (
                    intent,
                    {},
                )

        return (
            config.constants.IntentCategory.GENERAL_CHAT,
            {},
        )

    # ========================================================================
    # Input Normalization
    # ========================================================================

    @staticmethod
    def _normalize_utterance(
        utterance: Any,
    ) -> str:
        """
        Normalize raw user input.
        """

        if utterance is None:
            return ""

        if not isinstance(
            utterance,
            str,
        ):
            logger.warning(
                "Expected string utterance; got %s.",
                type(utterance).__name__,
            )

        return str(
            utterance
        ).strip()

    @staticmethod
    def _normalize_slots(
        slots: Any,
    ) -> dict[str, Any]:
        """
        Normalize classifier slots.
        """

        if slots is None:
            return {}

        if not isinstance(
            slots,
            dict,
        ):
            logger.warning(
                "Expected dict slots; got %s.",
                type(slots).__name__,
            )

            return {}

        return dict(
            slots
        )

    @staticmethod
    def _normalize_response(
        response: Any,
    ) -> str:
        """
        Normalize an AI or handler response.
        """

        if response is None:
            return ""

        if not isinstance(
            response,
            str,
        ):
            logger.warning(
                "Expected string response; got %s.",
                type(response).__name__,
            )

        return str(
            response
        ).strip()

    # ========================================================================
    # Exit Detection
    # ========================================================================

    @staticmethod
    def _is_exit_command(
        utterance: str,
    ) -> bool:
        """
        Return True when the utterance matches an exit keyword.
        """

        return contains_any(
            utterance,
            config.constants.EXIT_KEYWORDS,
        )

    # ========================================================================
    # History
    # ========================================================================

    @staticmethod
    def _save_user_message(
        utterance: str,
    ) -> None:
        """
        Save a user message without allowing history failure to crash
        the conversation engine.
        """

        try:

            history_manager.add_user_message(
                utterance
            )

            logger.debug(
                "User message saved: %d chars.",
                len(utterance),
            )

        except Exception as exc:

            logger.exception(
                "Failed to save user message: %s",
                exc,
            )

    @staticmethod
    def _save_assistant_message(
        result: CommandResult,
    ) -> None:
        """
        Save a command result to history.
        """

        message = (
            getattr(
                result,
                "message",
                None,
            )
            or ""
        )

        if not message:
            return

        try:

            intent = getattr(
                result,
                "intent",
                None,
            )

            intent_value = (
                intent.value
                if isinstance(
                    intent,
                    config.constants.IntentCategory,
                )
                else None
            )

            history_manager.add_assistant_message(
                message,
                intent=intent_value,
            )

            logger.debug(
                "Assistant response saved: %d chars.",
                len(message),
            )

        except Exception as exc:

            logger.exception(
                "Failed to save assistant response: %s",
                exc,
            )

    @staticmethod
    def _save_assistant_message_text(
        message: str,
        intent: config.constants.IntentCategory,
    ) -> None:
        """
        Save a plain assistant response to history.
        """

        if not message:
            return

        try:

            history_manager.add_assistant_message(
                message,
                intent=intent.value,
            )

        except Exception as exc:

            logger.exception(
                "Failed to save assistant message: %s",
                exc,
            )

    # ========================================================================
    # User Identity
    # ========================================================================

    @staticmethod
    def _sanitize_user_name(
        name: Any,
    ) -> Optional[str]:
        """
        Sanitize a user name.
        """

        if name is None:
            return None

        value = str(
            name
        ).strip()

        if not value:
            return None

        return value[
            :MAX_USER_NAME_LENGTH
        ]

    def set_user_name(
        self,
        name: str,
    ) -> None:
        """
        Update the user's name and persist it to long-term memory.
        """

        clean_name = self._sanitize_user_name(
            name
        )

        if not clean_name:
            raise ValueError(
                "User name cannot be empty."
            )

        if len(clean_name) > MAX_USER_NAME_LENGTH:
            raise ValueError(
                "User name exceeds the maximum "
                f"length of {MAX_USER_NAME_LENGTH} characters."
            )

        with self._turn_lock:

            self.user_name = clean_name

            try:

                memory_manager.remember(
                    "user_name",
                    clean_name,
                    importance=5,
                    source="user_provided",
                )

                logger.info(
                    "User name updated."
                )

            except Exception as exc:

                logger.exception(
                    "Failed to persist user name: %s",
                    exc,
                )

                raise

    def get_user_name(
        self,
    ) -> Optional[str]:
        """
        Return the current user name.
        """

        with self._turn_lock:
            return self.user_name

    # ========================================================================
    # Provider Management
    # ========================================================================

    def set_ai_provider(
        self,
        provider: Optional[AIProviderProtocol],
    ) -> None:
        """
        Replace the active AI provider at runtime.
        """

        with self._turn_lock:

            self.ai_provider = provider

            logger.info(
                "AI provider changed to %s.",
                self._provider_name() or "None",
            )

    def set_classifier(
        self,
        classifier: Optional[ClassifierFunc],
    ) -> None:
        """
        Replace the active classifier at runtime.
        """

        if (
            classifier is not None
            and not callable(classifier)
        ):
            raise TypeError(
                "classifier must be callable or None, "
                f"got {type(classifier).__name__}."
            )

        with self._turn_lock:

            self.classifier = classifier

            logger.info(
                "Classifier changed to %s.",
                self._classifier_name() or "None",
            )

    # ========================================================================
    # Events
    # ========================================================================

    @staticmethod
    def _emit_event_safe(
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Emit an EventBus event without allowing EventBus errors to
        crash the Assistant.
        """

        try:

            event_bus.emit(
                event_name,
                payload,
            )

            logger.debug(
                "Event emitted: %s",
                event_name,
            )

        except Exception as exc:

            logger.exception(
                "Event emission failed: %r: %s",
                event_name,
                exc,
            )

    # ========================================================================
    # Statistics
    # ========================================================================

    def _finalize_turn(
        self,
        result: TurnResult,
    ) -> None:
        """
        Update turn statistics and last-turn state.
        """

        with self._turn_lock:

            self._total_turns += 1

            if result.success:
                self._successful_turns += 1
            else:
                self._failed_turns += 1

            self._last_turn = result

    @staticmethod
    def _duration_ms(
        started: float,
    ) -> float:
        """
        Return elapsed processing time in milliseconds.
        """

        return round(
            (
                time.perf_counter()
                - started
            )
            * 1000.0,
            3,
        )

    # ========================================================================
    # Runtime Properties
    # ========================================================================

    @property
    def total_turns(
        self,
    ) -> int:
        """Return total processed turns."""

        with self._turn_lock:
            return self._total_turns

    @property
    def successful_turns(
        self,
    ) -> int:
        """Return successful turn count."""

        with self._turn_lock:
            return self._successful_turns

    @property
    def failed_turns(
        self,
    ) -> int:
        """Return failed turn count."""

        with self._turn_lock:
            return self._failed_turns

    @property
    def last_turn(
        self,
    ) -> Optional[TurnResult]:
        """Return the latest turn result."""

        with self._turn_lock:
            return self._last_turn

    # ========================================================================
    # Statistics / Diagnostics
    # ========================================================================

    def stats(
        self,
    ) -> dict[str, Any]:
        """
        Return runtime statistics.
        """

        with self._turn_lock:

            total = self._total_turns

            success_rate = (
                (
                    self._successful_turns
                    / total
                    * 100.0
                )
                if total
                else 0.0
            )

            return {
                "total_turns": total,
                "successful_turns": (
                    self._successful_turns
                ),
                "failed_turns": (
                    self._failed_turns
                ),
                "success_rate": round(
                    success_rate,
                    2,
                ),
                "ai_provider": (
                    self._provider_name()
                ),
                "classifier": (
                    self._classifier_name()
                ),
                "user_name_configured": (
                    self.user_name is not None
                ),
                "initialized_at": (
                    self._initialized_at
                ),
            }

    def diagnostics(
        self,
    ) -> dict[str, Any]:
        """
        Return detailed Assistant diagnostics.

        User secrets and actual user-name values are intentionally
        excluded.
        """

        with self._turn_lock:

            last_turn = self._last_turn

            return {
                "module": __name__,
                "class": self.__class__.__name__,

                "identity": {
                    "assistant_name": (
                        ASSISTANT_IDENTITY
                    ),
                    "wake_word": (
                        ASSISTANT_WAKE_WORD
                    ),
                    "voice_gender": (
                        ASSISTANT_VOICE_GENDER
                    ),
                    "voice_gender_locked": True,
                },

                "ai_provider": (
                    self._provider_name()
                ),

                "classifier": (
                    self._classifier_name()
                ),

                "user_name_configured": (
                    self.user_name is not None
                ),

                "language": self._get_language(),

                "persona": self._get_persona(),

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

    def reset_stats(
        self,
    ) -> None:
        """
        Reset runtime statistics.
        """

        with self._turn_lock:

            self._total_turns = 0
            self._successful_turns = 0
            self._failed_turns = 0
            self._last_turn = None

        logger.info(
            "Assistant statistics reset."
        )

    # ========================================================================
    # Representation
    # ========================================================================

    def __repr__(
        self,
    ) -> str:
        """
        Return a concise debug representation.
        """

        return (
            f"{self.__class__.__name__}("
            f"name={ASSISTANT_IDENTITY!r}, "
            f"provider={self._provider_name()!r}, "
            f"classifier={self._classifier_name()!r}, "
            f"turns={self._total_turns})"
        )


# ============================================================================
# Factory
# ============================================================================


def create_default_assistant() -> Assistant:
    """
    Create an Assistant using currently available application components.

    AI provider and classifier imports are intentionally lazy to reduce
    circular-import risk during application startup.
    """

    ai_provider: Optional[
        AIProviderProtocol
    ] = None

    classifier: Optional[
        ClassifierFunc
    ] = None

    # ------------------------------------------------------------------------
    # AI Provider
    # ------------------------------------------------------------------------

    try:

        from ai.auto_provider import AutoProvider

        ai_provider = AutoProvider()
        ai_provider.start_watcher(interval=5.0)

        logger.info(
            "Default AI provider loaded: %s",
            ai_provider.__class__.__name__,
        )

    except Exception as exc:

        logger.warning(
            "No active AI provider available: %s",
            exc,
        )

    # ------------------------------------------------------------------------
    # Classifier
    # ------------------------------------------------------------------------

    try:

        from brain.classifier import (
            classify_intent,
        )

        classifier = classify_intent

        logger.info(
            "Brain classifier loaded successfully."
        )

    except Exception as exc:

        logger.warning(
            "brain.classifier unavailable: %s. "
            "Using naive fallback classifier.",
            exc,
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
