"""
ai/conversation.py (IMPROVED VERSION)
=====================================
Provider-agnostic conversation/session manager for AssistantX.

Responsibilities
----------------
- Maintain in-memory conversation messages with thread safety
- Build system + conversation payloads with validation
- Connect AI providers with fallback support and error recovery
- Persist user/assistant messages through core.history
- Support streaming responses with proper error handling
- Manage conversation/session lifecycle
- Estimate context/token usage (approximate)
- Provide comprehensive diagnostics and safe helpers

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
            +---- AIProviderBase (with fallback chain)
                       |
                       +---- Gemini
                       +---- Ollama
                       +---- Local AI

Thread Safety
-------------
All mutable operations use RLock to ensure thread-safe access.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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

# Message limit constraints
MIN_MAX_MESSAGES = 2
MAX_ALLOWED_MESSAGES = 5000

# Language/localization
DEFAULT_LANGUAGE = "en-US"

# Token estimation (approximate, provider-independent)
CHARS_PER_TOKEN = 4

# Input validation
MAX_INPUT_LENGTH = 50_000
MAX_SESSION_ID_LENGTH = 200
MAX_PERSONA_LENGTH = 500

# Fallback message when all providers fail
FALLBACK_ERROR_MESSAGE = (
    "I'm sorry, I couldn't reach any AI provider right now. "
    "Please check your internet connection or local Ollama server."
)


# ============================================================================
# Exceptions
# ============================================================================


class ConversationError(RuntimeError):
    """Base exception for conversation-related errors."""



class ConversationValidationError(ConversationError):
    """Raised when conversation input or configuration is invalid."""


class ConversationProviderError(ConversationError):
    """Raised when conversation provider handling fails."""




class ConversationStreamError(ConversationError):
    """Raised when streaming response fails."""




class ConversationOperationError(ConversationError):
    """Raised when a conversation operation fails unexpectedly."""




# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class ConversationStats:
    """
    Snapshot of conversation statistics.

    Attributes
    ----------
    session_id : str
        Session identifier
    message_count : int
        Total number of messages
    user_messages : int
        Count of user messages
    assistant_messages : int
        Count of assistant messages
    system_messages : int
        Count of system messages
    estimated_tokens : int
        Approximate token count (for context budgeting only)
    """

    session_id: str
    message_count: int
    user_messages: int
    assistant_messages: int
    system_messages: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ConversationInfo:
    """
    Diagnostic information about an active conversation.

    Attributes
    ----------
    session_id : str
        Session identifier
    persona : str
        Current conversation persona
    provider : str
        Active AI provider name
    model : str
        Active model name
    message_count : int
        Current message count
    max_messages : int
        Maximum messages allowed
    estimated_tokens : int
        Approximate token count
    """

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
    """
    Validate and normalize a session ID.

    Parameters
    ----------
    session_id : str
        Session ID to validate

    Returns
    -------
    str
        Normalized session ID

    Raises
    ------
    ConversationValidationError
        If session_id is invalid
    """

    if not isinstance(session_id, str):
        raise ConversationValidationError(
            f"session_id must be a string, got {type(session_id).__name__}."
        )

    session_id = session_id.strip()

    if not session_id:
        raise ConversationValidationError(
            "session_id cannot be empty or whitespace-only."
        )

    if len(session_id) > MAX_SESSION_ID_LENGTH:
        raise ConversationValidationError(
            f"session_id exceeds maximum length of {MAX_SESSION_ID_LENGTH} characters."
        )

    return session_id


def _validate_message_limit(value: int) -> int:
    """
    Validate maximum message count.

    Parameters
    ----------
    value : int
        Maximum messages value

    Returns
    -------
    int
        Validated value

    Raises
    ------
    ConversationValidationError
        If value is invalid
    """

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ConversationValidationError(
            f"max_messages must be an integer, got {type(value).__name__}."
        ) from exc

    if value < MIN_MAX_MESSAGES:
        raise ConversationValidationError(
            f"max_messages must be at least {MIN_MAX_MESSAGES}, got {value}."
        )

    if value > MAX_ALLOWED_MESSAGES:
        raise ConversationValidationError(
            f"max_messages cannot exceed {MAX_ALLOWED_MESSAGES}, got {value}."
        )

    return value


def _validate_user_text(text: str) -> str:
    """
    Validate user message text.

    Parameters
    ----------
    text : str
        User message

    Returns
    -------
    str
        Validated and normalized message

    Raises
    ------
    ConversationValidationError
        If text is invalid
    """

    if not isinstance(text, str):
        raise ConversationValidationError(
            f"User message must be a string, got {type(text).__name__}."
        )

    text = text.strip()

    if not text:
        raise ConversationValidationError(
            "User message cannot be empty or whitespace-only."
        )

    if len(text) > MAX_INPUT_LENGTH:
        raise ConversationValidationError(
            f"User message exceeds maximum length of {MAX_INPUT_LENGTH} characters."
        )

    return text


def _validate_optional_memory(memory: Optional[str]) -> Optional[str]:
    """
    Validate optional memory/context text.

    Parameters
    ----------
    memory : str or None
        Memory text to validate

    Returns
    -------
    str or None
        Validated memory or None

    Raises
    ------
    ConversationValidationError
        If memory is invalid
    """

    if memory is None:
        return None

    if not isinstance(memory, str):
        raise ConversationValidationError(
            f"extra_memory must be a string or None, got {type(memory).__name__}."
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

    Thread Safety
    -------------
    All mutable operations are protected by an RLock.

    Attributes
    ----------
    session_id : str
        Unique conversation session identifier
    messages : list[ChatMessage]
        Current conversation messages
    max_messages : int
        Maximum messages to retain
    persona : str
        Conversation persona/personality
    """

    session_id: str = DEFAULT_SESSION_ID
    messages: list[ChatMessage] = field(default_factory=list)
    max_messages: int = MAX_HISTORY_MESSAGES
    persona: str = DEFAULT_PERSONA

    _provider: Optional[AIProviderBase] = field(
        default=None,
        repr=False,
        compare=False,
        init=False,
    )

    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
        compare=False,
        init=False,
    )

    _created_at: datetime = field(
        default_factory=datetime.now,
        init=False,
        repr=False,
        compare=False,
    )

    _last_activity: Optional[datetime] = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Initialize and validate conversation parameters."""

        # Validate session ID
        self.session_id = _validate_session_id(self.session_id)

        # Validate message limit
        self.max_messages = _validate_message_limit(self.max_messages)

        # Load and normalize persona
        configured_persona = settings_manager.get(
            "ai.system_persona",
            self.persona or DEFAULT_PERSONA,
        )

        if isinstance(configured_persona, str) and configured_persona.strip():
            self.persona = configured_persona.strip()
        else:
            self.persona = DEFAULT_PERSONA

        # Initialize lock
        object.__setattr__(self, "_lock", threading.RLock())

        # Load persisted history
        self._load_persisted_history()

        logger.info(
            "Conversation initialized: session_id=%r, persona=%r",
            self.session_id,
            self.persona,
        )

    # ------------------------------------------------------------------
    # History hydration
    # ------------------------------------------------------------------

    def _load_persisted_history(self) -> None:
        """
        Load persisted conversation history from storage.

        Only the default session loads from persisted history.
        Other sessions start fresh.
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

        for idx, entry in enumerate(stored):
            try:
                role = entry.get("role")
                content = entry.get("content", "")

                if not role or not content:
                    logger.debug(
                        "Skipping history entry %d: missing role or content",
                        idx,
                    )
                    continue

                message_role = self._parse_role(role)

                loaded.append(
                    ChatMessage(
                        role=message_role,
                        content=str(content).strip(),
                    )
                )

            except Exception as exc:
                logger.debug(
                    "Skipping invalid history entry %d: %s",
                    idx,
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
    def _parse_role(role: object) -> object:
        """
        Convert persisted role into ai.provider.Role.

        Supports both enum values and string values with fallback handling.

        Parameters
        ----------
        role : object
            Role value to parse

        Returns
        -------
        Role
            Parsed Role enum value

        Raises
        ------
        ConversationValidationError
            If role cannot be parsed
        """

        from ai.provider import Role

        # Already a Role enum
        if isinstance(role, Role):
            return role

        # Try direct value conversion
        try:
            return Role(str(role))
        except ValueError:
            pass

        # Try case-insensitive matching
        normalized = str(role).strip().lower()

        for candidate in Role:
            if candidate.value.lower() == normalized:
                return candidate

        raise ConversationValidationError(
            f"Unsupported message role: {role!r}"
        )

    # ------------------------------------------------------------------
    # Provider management
    # ------------------------------------------------------------------

    @property
    def provider(self) -> AIProviderBase:
        """
        Get the active AI provider.

        Provider initialization is lazy - created on first access.

        Returns
        -------
        AIProviderBase
            Active AI provider instance

        Raises
        ------
        ConversationProviderError
            If provider initialization fails
        """

        with self._lock:
            if self._provider is None:
                try:
                    self._provider = get_provider()
                    logger.info(
                        "Initialized AI provider: %s",
                        getattr(self._provider, "name", "unknown"),
                    )
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
        """Get the name of the active provider."""

        try:
            return getattr(self.provider, "name", "unknown")
        except ConversationProviderError:
            return "unavailable"

    @property
    def model_name(self) -> str:
        """Get the model name of the active provider."""

        try:
            return getattr(self.provider, "model", "unknown")
        except ConversationProviderError:
            return "unavailable"

    def set_provider(self, provider: AIProviderBase) -> None:
        """
        Set the active AI provider at runtime.

        Parameters
        ----------
        provider : AIProviderBase
            New provider instance

        Raises
        ------
        ConversationValidationError
            If provider is invalid

        Example
        -------
        >>> conversation.set_provider(OllamaProvider())
        """

        if not isinstance(provider, AIProviderBase):
            raise ConversationValidationError(
                f"provider must be an AIProviderBase instance, "
                f"got {type(provider).__name__}."
            )

        with self._lock:
            self._provider = provider

        logger.info(
            "Conversation '%s' switched to provider '%s'.",
            self.session_id,
            getattr(provider, "name", "unknown"),
        )

    def reset_provider(self) -> None:
        """
        Reset the provider, forcing lazy re-initialization on next use.
        """

        with self._lock:
            old_provider = self._provider
            self._provider = None

        if old_provider:
            logger.debug(
                "Conversation '%s' provider reset (was: %s).",
                self.session_id,
                getattr(old_provider, "name", "unknown"),
            )

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def add_user_message(self, content: str) -> ChatMessage:
        """
        Add a user message to the conversation.

        Parameters
        ----------
        content : str
            User message text

        Returns
        -------
        ChatMessage
            Created message object

        Raises
        ------
        ConversationValidationError
            If content is invalid
        """

        content = _validate_user_text(content)

        message = ChatMessage(
            role=self._role_user(),
            content=content,
        )

        self._append(message)

        return message

    def add_assistant_message(self, content: str) -> ChatMessage:
        """
        Add an assistant message to the conversation.

        Parameters
        ----------
        content : str
            Assistant response text

        Returns
        -------
        ChatMessage
            Created message object

        Raises
        ------
        ConversationValidationError
            If content is invalid
        """

        if not isinstance(content, str):
            raise ConversationValidationError(
                f"Assistant message must be a string, got {type(content).__name__}."
            )

        content = content.strip()

        if not content:
            raise ConversationValidationError(
                "Assistant message cannot be empty or whitespace-only."
            )

        message = ChatMessage(
            role=self._role_assistant(),
            content=content,
        )

        self._append(message)

        return message

    @staticmethod
    def _role_user() -> object:
        """Get the user role."""

        from ai.provider import Role

        return Role.USER

    @staticmethod
    def _role_assistant() -> object:
        """Get the assistant role."""

        from ai.provider import Role

        return Role.ASSISTANT

    def _append(
        self,
        message: ChatMessage,
        *,
        persist: bool = True,
    ) -> None:
        """
        Append a message to conversation and optionally persist it.

        Parameters
        ----------
        message : ChatMessage
            Message to add
        persist : bool, optional
            Whether to persist to history (default: True)
        """

        with self._lock:
            self.messages.append(message)
            self._trim()
            self._last_activity = datetime.now()

        if not persist:
            return

        try:
            if message.role == self._role_user():
                history_manager.add_user_message(message.content)
            elif message.role == self._role_assistant():
                history_manager.add_assistant_message(message.content)

        except Exception as exc:
            # Persistence failure should not break active conversation
            logger.exception(
                "Failed to persist message (session=%r): %s",
                self.session_id,
                exc,
            )

    def _trim(self) -> None:
        """
        Keep only the newest max_messages in memory.

        Should only be called with lock held.
        """

        if len(self.messages) <= self.max_messages:
            return

        overflow = len(self.messages) - self.max_messages
        removed = self.messages[:overflow]

        del self.messages[:overflow]

        logger.debug(
            "Trimmed %d message(s) from conversation '%s'.",
            len(removed),
            self.session_id,
        )

    # ------------------------------------------------------------------
    # Message inspection
    # ------------------------------------------------------------------

    def get_messages(self) -> list[ChatMessage]:
        """
        Get a snapshot of current conversation messages.

        Returns
        -------
        list[ChatMessage]
            Copy of current messages
        """

        with self._lock:
            return list(self.messages)

    def message_count(self) -> int:
        """Return the number of messages in the conversation."""

        with self._lock:
            return len(self.messages)

    def last_message(self) -> Optional[ChatMessage]:
        """
        Get the most recent message.

        Returns
        -------
        ChatMessage or None
            Last message, or None if conversation is empty
        """

        with self._lock:
            if not self.messages:
                return None
            return self.messages[-1]

    def has_messages(self) -> bool:
        """Check if conversation has any messages."""

        with self._lock:
            return len(self.messages) > 0

    # ------------------------------------------------------------------
    # Clear / reset
    # ------------------------------------------------------------------

    def clear(self, *, clear_persisted: bool = True) -> None:
        """
        Clear the current conversation.

        Parameters
        ----------
        clear_persisted : bool, optional
            If True and this is the default session, clear persisted
            history as well (default: True)
        """

        with self._lock:
            message_count = len(self.messages)
            self.messages.clear()
            self._last_activity = datetime.now()

        if clear_persisted and self.session_id == DEFAULT_SESSION_ID:
            try:
                history_manager.clear()
                logger.info(
                    "Cleared persisted history for session '%s'.",
                    self.session_id,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to clear persisted history: %s",
                    exc,
                )

        logger.info(
            "Conversation '%s' cleared (%d message(s) removed).",
            self.session_id,
            message_count,
        )

    def new_chat(self) -> None:
        """
        Start a fresh chat while keeping the same Conversation object.

        Clears messages, persisted history, and resets provider.
        """

        self.clear(clear_persisted=True)
        self.reset_provider()

        logger.info(
            "Started new chat for session '%s'.",
            self.session_id,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        extra_memory: Optional[str] = None,
    ) -> list[ChatMessage]:
        """
        Build the provider payload with system prompt and messages.

        Structure:
            [SYSTEM, USER, ASSISTANT, USER, ASSISTANT, ...]

        Parameters
        ----------
        extra_memory : str or None
            Additional context/memory to include in system prompt

        Returns
        -------
        list[ChatMessage]
            Complete message payload for provider
        """

        extra_memory = _validate_optional_memory(extra_memory)

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

        return [system_message, *current_messages]

    @staticmethod
    def _role_system() -> object:
        """Get the system role."""

        from ai.provider import Role

        return Role.SYSTEM

    # ------------------------------------------------------------------
    # Provider selection and fallback
    # ------------------------------------------------------------------

    def _provider_candidates(
        self,
        *,
        use_fallback: bool,
    ) -> Iterable[AIProviderBase]:
        """
        Get ordered list of providers to attempt.

        If fallback is enabled, returns active provider + fallback chain.

        Parameters
        ----------
        use_fallback : bool
            Whether to include fallback providers

        Returns
        -------
        Iterable[AIProviderBase]
            Providers in order of preference
        """

        active = self.provider

        if not use_fallback:
            return [active]

        try:
            candidates = list(get_fallback_chain(preferred=active.name))
        except Exception as exc:
            logger.warning(
                "Failed to build fallback chain: %s",
                exc,
            )
            return [active]

        # Ensure active provider is tried first
        ordered: list[AIProviderBase] = []
        seen: set[str] = set()

        for candidate in [active, *candidates]:
            name = getattr(candidate, "name", repr(candidate))

            if name in seen:
                continue

            seen.add(name)
            ordered.append(candidate)

        return ordered

    # ------------------------------------------------------------------
    # Send (non-streaming)
    # ------------------------------------------------------------------

    def send(
        self,
        user_text: str,
        extra_memory: Optional[str] = None,
        use_fallback: bool = True,
    ) -> CompletionResult:
        """
        Send a user message and generate a complete assistant response.

        Provider fallback chain:
            Active provider → Fallback providers → Error

        Parameters
        ----------
        user_text : str
            User message
        extra_memory : str or None
            Optional context to include
        use_fallback : bool
            Use fallback providers on failure (default: True)

        Returns
        -------
        CompletionResult
            Provider response or error result

        Raises
        ------
        ConversationValidationError
            If input validation fails
        """

        user_text = _validate_user_text(user_text)
        extra_memory = _validate_optional_memory(extra_memory)

        self.add_user_message(user_text)

        payload = self._build_payload(extra_memory=extra_memory)

        result: Optional[CompletionResult] = None
        candidates = self._provider_candidates(use_fallback=use_fallback)

        for candidate in candidates:
            try:
                if not candidate.is_available():
                    logger.debug(
                        "Provider '%s' unavailable; skipping.",
                        getattr(candidate, "name", "unknown"),
                    )
                    continue
            except Exception as exc:
                logger.warning(
                    "Availability check failed for provider: %s",
                    exc,
                )
                continue

            provider_name = getattr(candidate, "name", "unknown")
            logger.info(
                "Generating response using provider '%s'.",
                provider_name,
            )

            try:
                result = candidate.generate(payload)
            except Exception as exc:
                logger.exception(
                    "Provider '%s' raised exception during generation: %s",
                    provider_name,
                    exc,
                )
                continue

            if result and result.ok:
                with self._lock:
                    self._provider = candidate

                logger.debug(
                    "Provider '%s' succeeded.",
                    provider_name,
                )
                break

            error_msg = getattr(result, "error", "unknown error")
            logger.warning(
                "Provider '%s' failed: %s",
                provider_name,
                error_msg,
            )

        # ------------------------------------------------------------------
        # Handle total failure
        # ------------------------------------------------------------------

        if result is None or not result.ok:
            logger.error(
                "All providers failed for session '%s'.",
                self.session_id,
            )

            error_result = CompletionResult(
                text=FALLBACK_ERROR_MESSAGE,
                provider="none",
                model="none",
                latency_seconds=0.0,
                error="all_providers_failed",
            )

            self.add_assistant_message(FALLBACK_ERROR_MESSAGE)

            return error_result

        # ------------------------------------------------------------------
        # Success: persist and return
        # ------------------------------------------------------------------

        response_text = (getattr(result, "text", "") or "").strip()

        if response_text:
            self.add_assistant_message(response_text)

        logger.info(
            "Successfully completed request for session '%s' using '%s'.",
            self.session_id,
            getattr(result, "provider", "unknown"),
        )

        return result

    # ------------------------------------------------------------------
    # Stream
    # ------------------------------------------------------------------

    def stream(
        self,
        user_text: str,
        extra_memory: Optional[str] = None,
        use_fallback: bool = True,
    ) -> Iterator[str]:
        """
        Stream an assistant response chunk by chunk.

        If the active provider fails before producing output,
        fallback providers are attempted. Once streaming starts,
        no fallback occurs.

        Parameters
        ----------
        user_text : str
            User message
        extra_memory : str or None
            Optional context to include
        use_fallback : bool
            Use fallback providers (default: True)

        Yields
        ------
        str
            Response chunks as they arrive

        Raises
        ------
        ConversationStreamError
            If streaming fails
        ConversationValidationError
            If input validation fails
        """

        user_text = _validate_user_text(user_text)
        extra_memory = _validate_optional_memory(extra_memory)

        self.add_user_message(user_text)

        payload = self._build_payload(extra_memory=extra_memory)

        candidates = self._provider_candidates(use_fallback=use_fallback)

        last_error: Optional[Exception] = None

        for candidate in candidates:
            try:
                if not candidate.is_available():
                    logger.debug(
                        "Stream provider '%s' unavailable.",
                        getattr(candidate, "name", "unknown"),
                    )
                    continue
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Availability check failed: %s",
                    exc,
                )
                continue

            chunks: list[str] = []
            started = False

            provider_name = getattr(candidate, "name", "unknown")
            logger.info(
                "Starting stream with provider '%s'.",
                provider_name,
            )

            try:
                for chunk in candidate.stream(payload):
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

                    self.add_assistant_message(full_text)

                    logger.info(
                        "Stream completed with '%s' (%d chunk(s)).",
                        provider_name,
                        len(chunks),
                    )

                    return

                # Provider returned no content
                if started:
                    logger.warning(
                        "Provider '%s' produced empty stream.",
                        provider_name,
                    )
                    return

                logger.warning(
                    "Provider '%s' produced no output.",
                    provider_name,
                )

            except Exception as exc:
                last_error = exc

                logger.exception(
                    "Streaming failed for provider '%s': %s",
                    provider_name,
                    exc,
                )

                # If partial output already yielded, don't try fallback
                if chunks:
                    raise ConversationStreamError(
                        f"Provider '{provider_name}' failed after partial output."
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
    # Token estimation (approximate)
    # ------------------------------------------------------------------

    def token_estimate(self) -> int:
        """
        Estimate token count for current messages.

        NOTE: This is an APPROXIMATE estimate and is provider-independent.
        Use only for context budgeting decisions, not for precise accounting.

        Returns
        -------
        int
            Approximate token count
        """

        with self._lock:
            total_chars = sum(
                len(message.content) for message in self.messages
            )

        if total_chars <= 0:
            return 0

        # Simple approximation: 1 token ≈ 4 characters
        return max(1, (total_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> ConversationStats:
        """
        Get conversation statistics snapshot.

        Returns
        -------
        ConversationStats
            Statistics including message counts and token estimate
        """

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
        Get JSON-friendly conversation diagnostics.

        Returns
        -------
        dict
            Complete diagnostic information
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
        """
        Get typed conversation information.

        Returns
        -------
        ConversationInfo
            Structured conversation information
        """

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
    # Persona management
    # ------------------------------------------------------------------

    def set_persona(self, persona: str) -> None:
        """
        Change the conversation persona.

        Parameters
        ----------
        persona : str
            New persona name/description

        Raises
        ------
        ConversationValidationError
            If persona is invalid
        """

        if not isinstance(persona, str):
            raise ConversationValidationError(
                f"persona must be a string, got {type(persona).__name__}."
            )

        persona = persona.strip()

        if not persona:
            raise ConversationValidationError(
                "persona cannot be empty or whitespace-only."
            )

        if len(persona) > MAX_PERSONA_LENGTH:
            raise ConversationValidationError(
                f"persona exceeds maximum length of {MAX_PERSONA_LENGTH} characters."
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
        """Return string representation of conversation."""

        return (
            f"Conversation("
            f"session_id={self.session_id!r}, "
            f"messages={len(self.messages)}, "
            f"provider={self.provider_name!r}, "
            f"model={self.model_name!r}"
            ")"
        )


# ============================================================================
# Conversation Manager (Thread-safe registry)
# ============================================================================


class ConversationManager:
    """
    Thread-safe registry of active Conversation objects.

    Manages session lifecycle including creation, lookup, and cleanup.
    """

    def __init__(self) -> None:
        """Initialize the conversation manager."""

        self._sessions: dict[str, Conversation] = {}
        self._lock = threading.RLock()

        logger.debug("ConversationManager initialized.")

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
        """
        Get existing conversation or create a new one.

        Parameters
        ----------
        session_id : str
            Session identifier
        max_messages : int
            Maximum messages for new session
        persona : str
            Persona for new session

        Returns
        -------
        Conversation
            Conversation object (existing or newly created)
        """

        session_id = _validate_session_id(session_id)

        with self._lock:
            conversation = self._sessions.get(session_id)

            if conversation is None:
                conversation = Conversation(
                    session_id=session_id,
                    max_messages=max_messages,
                    persona=persona,
                )

                self._sessions[session_id] = conversation

                logger.info(
                    "Created new conversation session: %r",
                    session_id,
                )

            return conversation

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, session_id: str) -> Optional[Conversation]:
        """
        Get conversation by session ID.

        Parameters
        ----------
        session_id : str
            Session identifier

        Returns
        -------
        Conversation or None
            Conversation if found, None otherwise
        """

        session_id = _validate_session_id(session_id)

        with self._lock:
            return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        """
        Check if a session exists.

        Parameters
        ----------
        session_id : str
            Session identifier

        Returns
        -------
        bool
            True if session exists
        """

        session_id = _validate_session_id(session_id)

        with self._lock:
            return session_id in self._sessions

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def end_session(self, session_id: str) -> None:
        """
        End and remove a session.

        Parameters
        ----------
        session_id : str
            Session identifier to end
        """

        session_id = _validate_session_id(session_id)

        with self._lock:
            removed = self._sessions.pop(session_id, None)

        if removed is not None:
            logger.info(
                "Ended conversation session: %r",
                session_id,
            )

    def clear_session(
        self,
        session_id: str,
        *,
        clear_persisted: bool = True,
    ) -> bool:
        """
        Clear messages from a session.

        Parameters
        ----------
        session_id : str
            Session identifier
        clear_persisted : bool
            Also clear persisted history (default: True)

        Returns
        -------
        bool
            True if session existed and was cleared
        """

        conversation = self.get(session_id)

        if conversation is None:
            return False

        conversation.clear(clear_persisted=clear_persisted)

        return True

    # ------------------------------------------------------------------
    # Session listing
    # ------------------------------------------------------------------

    def all_session_ids(self) -> list[str]:
        """
        Get all active session IDs.

        Returns
        -------
        list[str]
            List of session identifiers
        """

        with self._lock:
            return list(self._sessions.keys())

    def all_sessions(self) -> list[Conversation]:
        """
        Get all active conversations.

        Returns
        -------
        list[Conversation]
            List of conversation objects
        """

        with self._lock:
            return list(self._sessions.values())

    def count(self) -> int:
        """
        Get count of active sessions.

        Returns
        -------
        int
            Number of active sessions
        """

        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Manager diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict:
        """
        Get diagnostics for all sessions.

        Returns
        -------
        dict
            Diagnostic information for manager and all sessions
        """

        sessions = self.all_sessions()

        return {
            "session_count": len(sessions),
            "sessions": [session.diagnostics() for session in sessions],
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clear_all(self, *, clear_persisted: bool = False) -> None:
        """
        Clear all active sessions.

        Parameters
        ----------
        clear_persisted : bool
            Also clear persisted history (default: False)
        """

        sessions = self.all_sessions()

        for session in sessions:
            session.clear(clear_persisted=clear_persisted)

        with self._lock:
            self._sessions.clear()

        logger.info(
            "Cleared all %d conversation session(s).",
            len(sessions),
        )


# ============================================================================
# Global Conversation Manager
# ============================================================================

conversation_manager = ConversationManager()


# ============================================================================
# Convenience Helpers
# ============================================================================


def get_conversation(
    session_id: str = DEFAULT_SESSION_ID,
) -> Conversation:
    """
    Get or create a conversation session.

    Parameters
    ----------
    session_id : str
        Session identifier (default: 'default')

    Returns
    -------
    Conversation
        Conversation object
    """

    return conversation_manager.get_or_create(session_id)


def reset_conversation(
    session_id: str = DEFAULT_SESSION_ID,
) -> None:
    """
    Reset a conversation session (clear messages and provider).

    Parameters
    ----------
    session_id : str
        Session identifier (default: 'default')
    """

    conversation = conversation_manager.get(session_id)

    if conversation is not None:
        conversation.new_chat()


def conversation_diagnostics() -> dict:
    """
    Get diagnostics for all active conversations.

    Returns
    -------
    dict
        Diagnostic information
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
    "ConversationOperationError",

    # Global manager
    "conversation_manager",

    # Helpers
    "get_conversation",
    "reset_conversation",
    "conversation_diagnostics",
]
