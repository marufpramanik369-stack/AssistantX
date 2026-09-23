"""
ai/conversation.py
==================
Provider-agnostic conversation/session manager for AssistantX.

Responsibilities
----------------
- Maintain in-memory conversation messages
- Build system + conversation payloads
- Connect AI providers with fallback support
- Persist user/assistant messages through core.history
- Support streaming responses
- Manage conversation/session lifecycle
- Estimate context/token usage
- Provide diagnostics and safe helpers

Architecture
------------
dashboard / core.assistant
            |
            v
     Conversation
            |
            +---- PromptContext / build_system_prompt
            |
            +---- HistoryManager
            |
            +---- AIProviderBase
                       |
                       +---- Gemini
                       +---- Ollama
                       +---- Local AI
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    get_fallback_chain,
    get_provider,
)
from config.constants import MAX_HISTORY_MESSAGES
from config.prompts import PromptContext, build_system_prompt
from config.settings import settings_manager
from core.history import history_manager

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_SESSION_ID = "default"
DEFAULT_PERSONA = "default"

MIN_MAX_MESSAGES = 2
MAX_ALLOWED_MESSAGES = 5000

DEFAULT_LANGUAGE = "en-US"

# Rough character/token ratio.
# This is intentionally approximate and provider-independent.
CHARS_PER_TOKEN = 4

MAX_INPUT_LENGTH = 50_000

FALLBACK_ERROR_MESSAGE = (
    "I'm sorry, I couldn't reach any AI provider right now. "
    "Please check your internet connection or local Ollama server."
)


# ============================================================================
# Exceptions
# ============================================================================


class ConversationError(RuntimeError):
    """Base exception for conversation errors."""


class ConversationValidationError(ConversationError):
    """Raised when conversation input/configuration is invalid."""


class ConversationProviderError(ConversationError):
    """Raised when conversation provider handling fails."""


class ConversationStreamError(ConversationError):
    """Raised when streaming fails."""


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class ConversationStats:
    """Snapshot of conversation statistics."""

    session_id: str
    message_count: int
    user_messages: int
    assistant_messages: int
    system_messages: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ConversationInfo:
    """Diagnostic information about an active conversation."""

    session_id: str
    persona: str
    provider: str
    model: str
    message_count: int
    max_messages: int
    estimated_tokens: int


# ============================================================================
# Validation helpers
# ============================================================================


def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str):
        raise ConversationValidationError(
            "session_id must be a string."
        )

    session_id = session_id.strip()

    if not session_id:
        raise ConversationValidationError(
            "session_id cannot be empty."
        )

    if len(session_id) > 200:
        raise ConversationValidationError(
            "session_id is too long."
        )

    return session_id


def _validate_message_limit(value: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ConversationValidationError(
            "max_messages must be an integer."
        ) from exc

    if value < MIN_MAX_MESSAGES:
        raise ConversationValidationError(
            f"max_messages must be at least {MIN_MAX_MESSAGES}."
        )

    if value > MAX_ALLOWED_MESSAGES:
        raise ConversationValidationError(
            f"max_messages cannot exceed {MAX_ALLOWED_MESSAGES}."
        )

    return value


def _validate_user_text(text: str) -> str:
    if not isinstance(text, str):
        raise ConversationValidationError(
            "User message must be a string."
        )

    text = text.strip()

    if not text:
        raise ConversationValidationError(
            "User message cannot be empty."
        )

    if len(text) > MAX_INPUT_LENGTH:
        raise ConversationValidationError(
            f"User message is too long. "
            f"Maximum: {MAX_INPUT_LENGTH} characters."
        )

    return text


def _validate_optional_memory(memory: str | None) -> str | None:
    if memory is None:
        return None

    if not isinstance(memory, str):
        raise ConversationValidationError(
            "extra_memory must be a string or None."
        )

    memory = memory.strip()

    if not memory:
        return None

    return memory


# ============================================================================
# Conversation
# ============================================================================


@dataclass
class Conversation:
    """
    Represents one active AssistantX conversation.

    A Conversation is provider-agnostic. The active provider can be
    changed at runtime and fallback providers can automatically be used
    when the current provider fails.
    """

    session_id: str = DEFAULT_SESSION_ID
    messages: list[ChatMessage] = field(default_factory=list)
    max_messages: int = MAX_HISTORY_MESSAGES
    persona: str = DEFAULT_PERSONA

    _provider: AIProviderBase | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
        compare=False,
    )

    _created_at: datetime = field(
        default_factory=datetime.now,
        init=False,
        repr=False,
        compare=False,
    )

    _last_activity: datetime | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        self.session_id = _validate_session_id(
            self.session_id
        )

        self.max_messages = _validate_message_limit(
            self.max_messages
        )

        configured_persona = settings_manager.get(
            "ai.system_persona",
            self.persona or DEFAULT_PERSONA,
        )

        if isinstance(configured_persona, str) and configured_persona.strip():
            self.persona = configured_persona.strip()
        else:
            self.persona = DEFAULT_PERSONA

        self._load_persisted_history()

    # ------------------------------------------------------------------
    # History hydration
    # ------------------------------------------------------------------

    def _load_persisted_history(self) -> None:
        """
        Load persisted history for the default session.

        core.history currently provides a shared rolling transcript,
        so only the default session hydrates directly from it.
        """

        if self.session_id != DEFAULT_SESSION_ID:
            return

        try:
            stored = history_manager.as_provider_messages(
                limit=self.max_messages
            )
        except Exception as exc:
            logger.exception(
                "Failed to load conversation history: %s",
                exc,
            )
            return

        loaded: list[ChatMessage] = []

        for entry in stored:
            try:
                role = entry.get("role")
                content = entry.get("content", "")

                if not role or not content:
                    continue

                message_role = self._parse_role(role)

                loaded.append(
                    ChatMessage(
                        role=message_role,
                        content=str(content).strip(),
                    )
                )

            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Skipping invalid history entry: %s",
                    exc,
                )

        self.messages = loaded[-self.max_messages:]

        if self.messages:
            logger.debug(
                "Conversation '%s' hydrated with %d message(s).",
                self.session_id,
                len(self.messages),
            )

    @staticmethod
    def _parse_role(role: object):
        """
        Convert persisted role into ai.provider.Role.

        Supports both enum values and string values.
        """

        from ai.provider import Role

        if isinstance(role, Role):
            return role

        try:
            return Role(str(role))
        except ValueError:
            normalized = str(role).strip().lower()

            for candidate in Role:
                if candidate.value.lower() == normalized:
                    return candidate

        raise ConversationValidationError(
            f"Unsupported message role: {role!r}"
        )

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------

    @property
    def provider(self) -> AIProviderBase:
        """
        Return the active provider.

        Provider creation is lazy.
        """

        with self._lock:
            if self._provider is None:
                try:
                    self._provider = get_provider()
                except Exception as exc:
                    logger.exception(
                        "Failed to create AI provider: %s",
                        exc,
                    )
                    raise ConversationProviderError(
                        f"Failed to initialize AI provider: {exc}"
                    ) from exc

            return self._provider

    @property
    def provider_name(self) -> str:
        return getattr(
            self.provider,
            "name",
            "unknown",
        )

    @property
    def model_name(self) -> str:
        return getattr(
            self.provider,
            "model",
            "unknown",
        )

    def set_provider(
        self,
        provider: AIProviderBase,
    ) -> None:
        """
        Set the active AI provider.

        Example:
            conversation.set_provider(OllamaProvider())
        """

        if not isinstance(provider, AIProviderBase):
            raise ConversationValidationError(
                "provider must be an AIProviderBase instance."
            )

        with self._lock:
            self._provider = provider

        logger.info(
            "Conversation '%s' switched to provider '%s'.",
            self.session_id,
            provider.name,
        )

    def reset_provider(self) -> None:
        """Forget the currently selected provider."""

        with self._lock:
            self._provider = None

        logger.debug(
            "Conversation '%s' provider reset.",
            self.session_id,
        )

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def add_user_message(
        self,
        content: str,
    ) -> ChatMessage:

        content = _validate_user_text(content)

        message = ChatMessage(
            role=self._role_user(),
            content=content,
        )

        self._append(message)

        return message

    def add_assistant_message(
        self,
        content: str,
    ) -> ChatMessage:

        if not isinstance(content, str):
            raise ConversationValidationError(
                "Assistant message must be a string."
            )

        content = content.strip()

        if not content:
            raise ConversationValidationError(
                "Assistant message cannot be empty."
            )

        message = ChatMessage(
            role=self._role_assistant(),
            content=content,
        )

        self._append(message)

        return message

    @staticmethod
    def _role_user():
        from ai.provider import Role

        return Role.USER

    @staticmethod
    def _role_assistant():
        from ai.provider import Role

        return Role.ASSISTANT

    def _append(
        self,
        message: ChatMessage,
        *,
        persist: bool = True,
    ) -> None:

        with self._lock:
            self.messages.append(message)

            self._trim()

            self._last_activity = datetime.now()

        if not persist:
            return

        try:
            if message.role == self._role_user():
                history_manager.add_user_message(
                    message.content
                )

            elif message.role == self._role_assistant():
                history_manager.add_assistant_message(
                    message.content
                )

        except Exception as exc:
            # Persistence failure should not destroy the active
            # in-memory conversation.
            logger.exception(
                "Failed to persist conversation message: %s",
                exc,
            )

    def _trim(self) -> None:
        """
        Keep only the newest max_messages.
        """

        if len(self.messages) <= self.max_messages:
            return

        overflow = len(self.messages) - self.max_messages

        del self.messages[:overflow]

    # ------------------------------------------------------------------
    # Message inspection
    # ------------------------------------------------------------------

    def get_messages(self) -> list[ChatMessage]:
        """Return a shallow copy of current messages."""

        with self._lock:
            return list(self.messages)

    def message_count(self) -> int:
        with self._lock:
            return len(self.messages)

    def last_message(
        self,
    ) -> ChatMessage | None:

        with self._lock:
            if not self.messages:
                return None

            return self.messages[-1]

    # ------------------------------------------------------------------
    # Clear / reset
    # ------------------------------------------------------------------

    def clear(
        self,
        *,
        clear_persisted: bool = True,
    ) -> None:
        """
        Clear the current conversation.

        Parameters
        ----------
        clear_persisted:
            If True and this is the default session, clear persisted
            history as well.
        """

        with self._lock:
            self.messages.clear()
            self._last_activity = datetime.now()

        if (
            clear_persisted
            and self.session_id == DEFAULT_SESSION_ID
        ):
            try:
                history_manager.clear()
            except Exception as exc:
                logger.exception(
                    "Failed to clear persisted history: %s",
                    exc,
                )

        logger.info(
            "Conversation '%s' cleared.",
            self.session_id,
        )

    def new_chat(self) -> None:
        """
        Start a fresh chat while keeping the same Conversation object.
        """

        self.clear(clear_persisted=True)
        self.reset_provider()

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        extra_memory: str | None = None,
    ) -> list[ChatMessage]:
        """
        Build the provider payload.

        Structure:
            SYSTEM
            USER
            ASSISTANT
            USER
            ASSISTANT
            ...
        """

        extra_memory = _validate_optional_memory(
            extra_memory
        )

        language = settings_manager.get(
            "voice.language",
            DEFAULT_LANGUAGE,
        )

        if not isinstance(language, str) or not language.strip():
            language = DEFAULT_LANGUAGE

        context = PromptContext(
            persona=self.persona,
            language=language,
            current_datetime=datetime.now().strftime(
                "%A, %d %B %Y %I:%M %p"
            ),
            recent_memory=extra_memory,
        )

        system_text = build_system_prompt(context)

        if not isinstance(system_text, str):
            system_text = str(system_text)

        system_text = system_text.strip()

        system_message = ChatMessage(
            role=self._role_system(),
            content=system_text,
        )

        with self._lock:
            current_messages = list(self.messages)

        return [
            system_message,
            *current_messages,
        ]

    @staticmethod
    def _role_system():
        from ai.provider import Role

        return Role.SYSTEM

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def _provider_candidates(
        self,
        *,
        use_fallback: bool,
    ) -> Iterable[AIProviderBase]:

        active = self.provider

        if not use_fallback:
            return [active]

        try:
            candidates = list(
                get_fallback_chain(
                    preferred=active.name
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to build fallback chain: %s",
                exc,
            )
            return [active]

        # Make sure the active provider is present first.
        ordered: list[AIProviderBase] = []

        seen: set[str] = set()

        for candidate in [active, *candidates]:

            name = getattr(
                candidate,
                "name",
                repr(candidate),
            )

            if name in seen:
                continue

            seen.add(name)
            ordered.append(candidate)

        return ordered

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(
        self,
        user_text: str,
        extra_memory: str | None = None,
        use_fallback: bool = True,
    ) -> CompletionResult:
        """
        Send a user message and generate an assistant response.

        Provider flow:
            Active provider
                  ↓
            fallback provider(s)
                  ↓
            Local AI
        """

        user_text = _validate_user_text(user_text)

        extra_memory = _validate_optional_memory(
            extra_memory
        )

        self.add_user_message(user_text)

        payload = self._build_payload(
            extra_memory=extra_memory
        )

        result: CompletionResult | None = None

        candidates = self._provider_candidates(
            use_fallback=use_fallback
        )

        for candidate in candidates:

            try:
                if not candidate.is_available():
                    logger.debug(
                        "Provider '%s' unavailable; skipping.",
                        candidate.name,
                    )
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Availability check failed for '%s': %s",
                    getattr(candidate, "name", "unknown"),
                    exc,
                )
                continue

            logger.info(
                "Generating response using provider '%s'.",
                candidate.name,
            )

            try:
                result = candidate.generate(
                    payload
                )
            except Exception as exc:
                logger.exception(
                    "Provider '%s' raised an exception: %s",
                    candidate.name,
                    exc,
                )
                continue

            if result and result.ok:
                with self._lock:
                    self._provider = candidate

                break

            logger.warning(
                "Provider '%s' returned failure: %s",
                candidate.name,
                getattr(result, "error", None),
            )

        # ------------------------------------------------------------------
        # Total failure
        # ------------------------------------------------------------------

        if result is None or not result.ok:

            error_result = CompletionResult(
                text=FALLBACK_ERROR_MESSAGE,
                provider="none",
                model="none",
                latency_seconds=0.0,
                error="all_providers_failed",
            )

            self.add_assistant_message(
                FALLBACK_ERROR_MESSAGE
            )

            return error_result

        # ------------------------------------------------------------------
        # Success
        # ------------------------------------------------------------------

        response_text = (
            getattr(result, "text", "") or ""
        ).strip()

        if response_text:
            self.add_assistant_message(
                response_text
            )

        return result

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
        self,
        user_text: str,
        extra_memory: str | None = None,
        use_fallback: bool = True,
    ) -> Iterator[str]:
        """
        Stream an assistant response.

        If the active provider fails before producing output,
        fallback providers are attempted.

        The complete streamed response is persisted only after
        successful generation.
        """

        user_text = _validate_user_text(user_text)

        extra_memory = _validate_optional_memory(
            extra_memory
        )

        self.add_user_message(user_text)

        payload = self._build_payload(
            extra_memory=extra_memory
        )

        candidates = self._provider_candidates(
            use_fallback=use_fallback
        )

        last_error: Exception | None = None

        for candidate in candidates:

            try:
                if not candidate.is_available():
                    logger.debug(
                        "Streaming provider '%s' unavailable.",
                        candidate.name,
                    )
                    continue
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

            chunks: list[str] = []
            started = False

            logger.info(
                "Starting stream with provider '%s'.",
                candidate.name,
            )

            try:
                for chunk in candidate.stream(
                    payload
                ):

                    if chunk is None:
                        continue

                    chunk = str(chunk)

                    if not chunk:
                        continue

                    started = True
                    chunks.append(chunk)

                    yield chunk

                full_text = "".join(chunks).strip()

                if full_text:
                    with self._lock:
                        self._provider = candidate

                    self.add_assistant_message(
                        full_text
                    )

                    return

                # Provider returned no content.
                if started:
                    return

                logger.warning(
                    "Provider '%s' produced an empty stream.",
                    candidate.name,
                )

            except Exception as exc:
                last_error = exc

                logger.exception(
                    "Streaming failed for provider '%s': %s",
                    candidate.name,
                    exc,
                )

                # If partial output was already yielded, do not attempt
                # another provider because the caller has already received
                # an incomplete response.
                if chunks:
                    raise ConversationStreamError(
                        f"Provider '{candidate.name}' streaming failed "
                        "after partial output."
                    ) from exc

                continue

        logger.error(
            "All streaming providers failed. Last error: %s",
            last_error,
        )

        raise ConversationStreamError(
            "All AI providers failed during streaming."
        ) from last_error

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def token_estimate(self) -> int:
        """
        Return a rough token estimate for current messages.

        This is NOT provider-specific tokenizer output.
        It is intended only for context-budget decisions.
        """

        with self._lock:
            total_chars = sum(
                len(message.content)
                for message in self.messages
            )

        if total_chars <= 0:
            return 0

        return max(
            1,
            (total_chars + CHARS_PER_TOKEN - 1)
            // CHARS_PER_TOKEN,
        )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> ConversationStats:
        with self._lock:
            messages = list(self.messages)

        user_count = 0
        assistant_count = 0
        system_count = 0

        for message in messages:

            if message.role == self._role_user():
                user_count += 1

            elif message.role == self._role_assistant():
                assistant_count += 1

            elif message.role == self._role_system():
                system_count += 1

        return ConversationStats(
            session_id=self.session_id,
            message_count=len(messages),
            user_messages=user_count,
            assistant_messages=assistant_count,
            system_messages=system_count,
            estimated_tokens=self.token_estimate(),
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict:
        """
        Return JSON-friendly conversation diagnostics.
        """

        stats = self.stats()

        return {
            "session_id": stats.session_id,
            "persona": self.persona,
            "provider": self.provider_name,
            "model": self.model_name,
            "message_count": stats.message_count,
            "user_messages": stats.user_messages,
            "assistant_messages": stats.assistant_messages,
            "system_messages": stats.system_messages,
            "estimated_tokens": stats.estimated_tokens,
            "max_messages": self.max_messages,
            "created_at": self._created_at.isoformat(),
            "last_activity": (
                self._last_activity.isoformat()
                if self._last_activity
                else None
            ),
        }

    def info(self) -> ConversationInfo:
        """Return typed conversation information."""

        return ConversationInfo(
            session_id=self.session_id,
            persona=self.persona,
            provider=self.provider_name,
            model=self.model_name,
            message_count=self.message_count(),
            max_messages=self.max_messages,
            estimated_tokens=self.token_estimate(),
        )

    # ------------------------------------------------------------------
    # Persona
    # ------------------------------------------------------------------

    def set_persona(
        self,
        persona: str,
    ) -> None:

        if not isinstance(persona, str):
            raise ConversationValidationError(
                "persona must be a string."
            )

        persona = persona.strip()

        if not persona:
            raise ConversationValidationError(
                "persona cannot be empty."
            )

        if len(persona) > 500:
            raise ConversationValidationError(
                "persona is too long."
            )

        self.persona = persona

        logger.debug(
            "Conversation '%s' persona changed to '%s'.",
            self.session_id,
            persona,
        )

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "Conversation("
            f"session_id={self.session_id!r}, "
            f"messages={len(self.messages)}, "
            f"provider={self.provider_name!r}, "
            f"model={self.model_name!r}"
            ")"
        )


# ============================================================================
# Conversation Manager
# ============================================================================


class ConversationManager:
    """
    Thread-safe registry of active Conversation objects.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Conversation] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Session creation
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        session_id: str = DEFAULT_SESSION_ID,
        *,
        max_messages: int = MAX_HISTORY_MESSAGES,
        persona: str = DEFAULT_PERSONA,
    ) -> Conversation:

        session_id = _validate_session_id(
            session_id
        )

        with self._lock:

            conversation = self._sessions.get(
                session_id
            )

            if conversation is None:

                conversation = Conversation(
                    session_id=session_id,
                    max_messages=max_messages,
                    persona=persona,
                )

                self._sessions[session_id] = conversation

                logger.info(
                    "Created conversation session '%s'.",
                    session_id,
                )

            return conversation

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(
        self,
        session_id: str,
    ) -> Conversation | None:

        session_id = _validate_session_id(
            session_id
        )

        with self._lock:
            return self._sessions.get(
                session_id
            )

    def exists(
        self,
        session_id: str,
    ) -> bool:

        session_id = _validate_session_id(
            session_id
        )

        with self._lock:
            return session_id in self._sessions

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def end_session(
        self,
        session_id: str,
    ) -> None:

        session_id = _validate_session_id(
            session_id
        )

        with self._lock:
            removed = self._sessions.pop(
                session_id,
                None,
            )

        if removed is not None:
            logger.info(
                "Ended conversation session '%s'.",
                session_id,
            )

    def clear_session(
        self,
        session_id: str,
        *,
        clear_persisted: bool = True,
    ) -> bool:

        conversation = self.get(
            session_id
        )

        if conversation is None:
            return False

        conversation.clear(
            clear_persisted=clear_persisted
        )

        return True

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    def all_session_ids(self) -> list[str]:

        with self._lock:
            return list(
                self._sessions.keys()
            )

    def all_sessions(self) -> list[Conversation]:

        with self._lock:
            return list(
                self._sessions.values()
            )

    def count(self) -> int:

        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Manager diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict:

        sessions = self.all_sessions()

        return {
            "session_count": len(sessions),
            "sessions": [
                session.diagnostics()
                for session in sessions
            ],
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clear_all(
        self,
        *,
        clear_persisted: bool = False,
    ) -> None:

        sessions = self.all_sessions()

        for session in sessions:
            session.clear(
                clear_persisted=clear_persisted
            )

        with self._lock:
            self._sessions.clear()

        logger.info(
            "All conversation sessions cleared."
        )


# ============================================================================
# Global Conversation Manager
# ============================================================================


conversation_manager = ConversationManager()


# ============================================================================
# Convenience helpers
# ============================================================================


def get_conversation(
    session_id: str = DEFAULT_SESSION_ID,
) -> Conversation:
    """
    Get or create a conversation session.
    """

    return conversation_manager.get_or_create(
        session_id
    )


def reset_conversation(
    session_id: str = DEFAULT_SESSION_ID,
) -> None:
    """
    Reset an existing conversation session.
    """

    conversation = conversation_manager.get(
        session_id
    )

    if conversation is not None:
        conversation.new_chat()


def conversation_diagnostics() -> dict:
    """
    Return diagnostics for all active conversations.
    """

    return conversation_manager.diagnostics()


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Main classes
    "Conversation",
    "ConversationManager",

    # Dataclasses
    "ConversationStats",
    "ConversationInfo",

    # Exceptions
    "ConversationError",
    "ConversationValidationError",
    "ConversationProviderError",
    "ConversationStreamError",

    # Global manager
    "conversation_manager",

    # Helpers
    "get_conversation",
    "reset_conversation",
    "conversation_diagnostics",
]
