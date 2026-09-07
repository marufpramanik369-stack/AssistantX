"""
assistant.py
============
The centerpiece of core/: the `Assistant` class orchestrates a single
end-to-end turn of interaction — from raw user input (text or
transcribed voice) through intent classification, command routing or AI
generation, history/memory updates, and finally a response ready to be
spoken and/or displayed.

This module intentionally depends only on abstractions (command_router,
event_bus, history, memory) plus a pluggable `ai_provider` and
`classifier`, which are injected rather than hard-imported, so:
    - Tests can supply fake/mock providers.
    - Swapping AI backends (Gemini <-> Ollama <-> local model) requires
      zero changes here.
    - The brain/ package owns classification logic; this module just
      calls it.

Typical wiring (usually done once in launcher.py or main.py):

    from core.assistant import Assistant
    from ai.provider import get_active_provider
    from brain.classifier import classify_intent

    assistant = Assistant(ai_provider=get_active_provider(), classifier=classify_intent)
    reply = assistant.handle_text_input("what's the weather like today?")
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Protocol

from config.constants import DATE_DISPLAY_FORMAT, EXIT_KEYWORDS, IntentCategory
from config.prompts import PromptContext, build_system_prompt
from config.settings import settings_manager
from core.command_router import CommandResult, command_router
from core.event_bus import Events, event_bus
from core.history import Role, history_manager
from core.logger import get_logger
from core.memory import memory_manager
from core.utils import contains_any, normalize_text

logger = get_logger(__name__)


class AIProviderProtocol(Protocol):
    """
    Structural interface any AI backend (ai/gemini.py, ai/ollama.py,
    ai/local_ai.py) must satisfy to be usable by Assistant. Using a
    Protocol (rather than an ABC) avoids forcing providers to inherit
    from a specific base class.
    """

    def generate(self, messages: list[dict], system_prompt: str) -> str:
        ...


ClassifierFunc = Callable[[str], tuple[IntentCategory, dict]]


@dataclass
class TurnResult:
    """The full outcome of processing a single user turn."""

    utterance: str
    intent: IntentCategory
    response_text: str
    success: bool = True
    should_exit: bool = False
    data: dict = field(default_factory=dict)


class Assistant:
    """
    High-level façade coordinating a single conversational turn.

    Not itself thread-safe for concurrent calls to `handle_text_input`
    from multiple threads simultaneously (that would interleave a single
    conversation's turns nonsensically) — but internal state updates use
    the underlying thread-safe singletons (history_manager, memory_manager),
    so calling from the voice thread and the dashboard thread at
    *different* times is fine.
    """

    def __init__(
        self,
        ai_provider: Optional[AIProviderProtocol] = None,
        classifier: Optional[ClassifierFunc] = None,
        user_name: Optional[str] = None,
    ) -> None:
        self.ai_provider = ai_provider
        self.classifier = classifier
        self.user_name = user_name or memory_manager.recall("user_name")
        self._turn_lock = threading.Lock()
        self._register_builtin_handlers()

    # -- built-in intent handlers ------------------------------------------- #

    def _register_builtin_handlers(self) -> None:
        """
        Register the handful of intents Assistant itself is qualified to
        answer without delegating to services/automation (e.g. exit
        commands). Domain-specific handlers (weather, apps, browser,
        etc.) are registered by their owning modules during app startup,
        not here — this keeps assistant.py from depending on every
        service/automation module directly.
        """
        command_router.set_fallback(self._handle_general_chat)

    def _handle_general_chat(self, utterance: str, slots: dict) -> CommandResult:
        """Fallback handler: route to the AI provider for open-ended conversation."""
        if self.ai_provider is None:
            return CommandResult.fail(
                error="No AI provider configured",
                message="I don't have a language model connected right now.",
            )

        system_prompt = self._build_system_prompt()
        messages = history_manager.as_provider_messages(
            limit=settings_manager.get("ai.max_history_messages", 50)
        )

        try:
            reply = self.ai_provider.generate(messages=messages, system_prompt=system_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI provider failed to generate a response.")
            event_bus.emit(Events.AI_ERROR, {"error": str(exc)})
            return CommandResult.fail(error=str(exc), message="Sorry, I ran into a problem thinking that through.")

        event_bus.emit(Events.AI_RESPONSE_COMPLETE, {"text": reply})
        return CommandResult.ok(reply, intent=IntentCategory.GENERAL_CHAT)

    def _build_system_prompt(self) -> str:
        context = PromptContext(
            user_name=self.user_name,
            persona=settings_manager.get("ai.system_persona", "default"),
            language=settings_manager.get("voice.language", "en-US"),
            current_datetime=datetime.now().strftime(DATE_DISPLAY_FORMAT),
            recent_memory=memory_manager.as_context_string(limit=8),
        )
        return build_system_prompt(context)

    # -- main entry points --------------------------------------------------- #

    def handle_text_input(self, utterance: str) -> TurnResult:
        """
        Process a single piece of user text input end-to-end: classify
        intent, route to the right handler, update history, and return
        a TurnResult ready for the UI/voice layer to present.
        """
        with self._turn_lock:
            utterance = utterance.strip()
            if not utterance:
                return TurnResult(
                    utterance=utterance,
                    intent=IntentCategory.UNKNOWN,
                    response_text="",
                    success=False,
                )

            history_manager.add_user_message(utterance)

            if self._is_exit_command(utterance):
                farewell = "Goodbye! Talk soon."
                history_manager.add_assistant_message(farewell, intent=IntentCategory.SYSTEM_CONTROL.value)
                return TurnResult(
                    utterance=utterance,
                    intent=IntentCategory.SYSTEM_CONTROL,
                    response_text=farewell,
                    should_exit=True,
                )

            intent, slots = self._classify(utterance)
            event_bus.emit(Events.INTENT_CLASSIFIED, {"intent": intent.value, "slots": slots})

            result = command_router.dispatch(intent, utterance, slots)

            return TurnResult(
                utterance=utterance,
                intent=intent,
                response_text=result.message,
                success=result.success,
                data=result.data,
            )

    def handle_voice_input(self, transcribed_text: str, confidence: float = 1.0) -> TurnResult:
        """
        Entry point for voice/recognizer.py once speech has been
        transcribed to text. Thin wrapper around handle_text_input that
        also logs recognition confidence for debugging/tuning.
        """
        logger.debug("Voice input received (confidence=%.2f): %s", confidence, transcribed_text)
        return self.handle_text_input(transcribed_text)

    # -- helpers --------------------------------------------------------- #

    @staticmethod
    def _is_exit_command(utterance: str) -> bool:
        return contains_any(utterance, EXIT_KEYWORDS)

    def _classify(self, utterance: str) -> tuple[IntentCategory, dict]:
        """
        Delegate to the injected classifier if present; otherwise fall
        back to a minimal keyword-based guess so Assistant remains
        usable even before brain/classifier.py is wired in.
        """
        if self.classifier:
            try:
                return self.classifier(utterance)
            except Exception:  # noqa: BLE001
                logger.exception("Classifier raised; falling back to GENERAL_CHAT.")
                return IntentCategory.GENERAL_CHAT, {}
        return self._naive_classify(utterance)

    @staticmethod
    def _naive_classify(utterance: str) -> tuple[IntentCategory, dict]:
        """Minimal fallback classifier used only when brain/ isn't wired up yet."""
        text = normalize_text(utterance)
        keyword_map = {
            IntentCategory.WEATHER: ("weather", "temperature", "forecast", "rain"),
            IntentCategory.NEWS: ("news", "headline"),
            IntentCategory.MUSIC: ("play", "music", "song"),
            IntentCategory.CALCULATION: ("calculate", "plus", "minus", "times", "divided"),
            IntentCategory.APP_LAUNCH: ("open", "launch", "start"),
            IntentCategory.WEB_SEARCH: ("search", "google", "look up"),
        }
        for intent, keywords in keyword_map.items():
            if contains_any(text, keywords):
                return intent, {}
        return IntentCategory.GENERAL_CHAT, {}

    # -- user identity convenience --------------------------------------- #

    def set_user_name(self, name: str) -> None:
        """Remember the user's name both in-memory (this session) and long-term."""
        self.user_name = name
        memory_manager.remember("user_name", name, importance=5, source="user_provided")
        logger.info("User name set to '%s'.", name)


def create_default_assistant() -> Assistant:
    """
    Convenience factory that wires Assistant to the currently configured
    AI provider and classifier, resolved lazily to avoid import cycles
    (ai/ and brain/ both depend on core/, so core/ cannot import them at
    module load time).
    """
    ai_provider = None
    classifier = None

    try:
        from ai.provider import get_active_provider

        ai_provider = get_active_provider()
    except Exception:  # noqa: BLE001
        logger.warning("No AI provider available yet; general chat will be disabled until one is configured.")

    try:
        from brain.classifier import classify_intent

        classifier = classify_intent
    except Exception:  # noqa: BLE001
        logger.warning("brain.classifier not available yet; using naive fallback classifier.")

    return Assistant(ai_provider=ai_provider, classifier=classifier)
    