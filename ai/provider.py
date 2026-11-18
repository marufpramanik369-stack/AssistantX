"""
ai/provider.py
==============
Provider-agnostic AI abstraction layer for AssistantX.

This module defines:

- ChatMessage: Standard conversation message format
- CompletionResult: Normalized completion result
- ProviderError hierarchy: Exception classes
- AIProviderBase: Abstract base class for all providers
- Provider factory: Dynamic provider instantiation
- Fallback provider chain: Graceful failover support
- Provider availability helpers: Discovery and health checks

The rest of AssistantX does not need to know whether the active
backend is Gemini, Ollama, or Local AI. This module abstracts all
provider-specific behavior.

Architecture:

    core/assistant.py
            │
            ▼
        AI Provider API
            │
      ┌─────┼─────┐
      ▼     ▼     ▼
   Gemini Ollama Local AI

Design goals:
- Provider-independent API surface
- Strong validation of inputs
- Graceful error handling and normalization
- Automatic retry with exponential backoff
- Timeout propagation to providers
- Safe fallback chain with priority ordering
- Streaming support (native or simulated)
- Easy future provider/plugin integration
- Full logging for debugging

Thread Safety
-------------
This module is thread-safe. Provider instances can be used from
multiple threads. The factory functions use lazy module imports
to avoid circular dependencies.

Logging
-------
Debug logging includes:
- Provider initialization and configuration
- Message normalization and validation
- Retry attempts and backoff delays
- API call details and timing

Info logging includes:
- Successful generation operations
- Provider selection from fallback chain
- Generation completion with provider name

Error logging includes:
- API call failures with context
- Retry exhaustion with attempt counts
- Provider initialization failures
- Invalid configuration or input
"""



from __future__ import annotations

import abc
import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional



from config.constants import (

    DEFAULT_TEMPERATURE,
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    AIProvider,

)


logger = logging.getLogger(__name__)


# ============================================================================
# Built-in Provider References (Lazy Loading)
# ============================================================================
#
# Providers are loaded lazily to avoid circular imports and speed up
# module initialization. The concrete provider classes remain in their
# own modules while ai.provider exposes stable references for the factory.


GeminiProvider: Optional[type] = None
OllamaProvider: Optional[type] = None
LocalAIProvider: Optional[type] = None



def _load_gemini_provider() -> type:
    """Load and cache the Gemini provider class."""
    global GeminiProvider


    if GeminiProvider is None:
        logger.debug("Lazy-loading Gemini provider")
        from ai.gemini import GeminiProvider as _GeminiProvider


        GeminiProvider = _GeminiProvider


    return GeminiProvider


def _load_ollama_provider() -> type:
    """Load and cache the Ollama provider class."""
    global OllamaProvider


    if OllamaProvider is None:
        logger.debug("Lazy-loading Ollama provider")
        from ai.ollama import OllamaProvider as _OllamaProvider


        OllamaProvider = _OllamaProvider


    return OllamaProvider


def _load_local_provider() -> type:
    """Load and cache the Local AI provider class."""
    global LocalAIProvider


    if LocalAIProvider is None:
        logger.debug("Lazy-loading Local AI provider")
        from ai.local_ai import LocalAIProvider as _LocalAIProvider


        LocalAIProvider = _LocalAIProvider


    return LocalAIProvider


# ============================================================================
# Constants
# ============================================================================


MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0


MIN_RETRIES = 1
MAX_ALLOWED_RETRIES = 10


DEFAULT_MAX_TOKENS: Optional[int] = None


BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 8.0


MAX_MESSAGE_LENGTH = 100_000


PROVIDER_GEMINI = AIProvider.GEMINI.value
PROVIDER_OLLAMA = AIProvider.OLLAMA.value
PROVIDER_LOCAL = AIProvider.LOCAL.value


SUPPORTED_PROVIDERS = (

    PROVIDER_GEMINI,
    PROVIDER_OLLAMA,
    PROVIDER_LOCAL,

)



# ============================================================================
# Exceptions
# ============================================================================


class ProviderError(RuntimeError):
    """Base exception for AI provider errors."""



class ProviderValidationError(ProviderError):
    """Raised when provider input/configuration is invalid."""



class ProviderUnavailableError(ProviderError):
    """Raised when a provider is currently unavailable."""



class ProviderConfigurationError(ProviderError):
    """Raised when provider configuration is missing or invalid."""



class ProviderRequestError(ProviderError):
    """Raised when a provider request fails."""



class ProviderFactoryError(ProviderError):
    """Raised when a provider cannot be created."""



class ProviderStreamingError(ProviderError):
    """Raised when streaming fails."""



# ============================================================================
# Roles
# ============================================================================


class Role(str, Enum):


    """
    Standard LLM conversation roles.

    Values
    ------
    SYSTEM : "system"
        System/instruction message
    USER : "user"
        User message
    ASSISTANT : "assistant"
        Model response
    """



    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


    @classmethod
    def from_value(cls, value: str | Role) -> Role:


        """
        Convert a string/value to Role.

        Parameters
        ----------
        value : str or Role
            Role value to convert

        Returns
        -------
        Role
            Normalized role enum value

        Raises
        ------
        ProviderValidationError
            If value is not a valid role

        Examples
        --------
            role = Role.from_value("user")
            # Returns Role.USER

            role = Role.from_value(Role.ASSISTANT)
            # Returns Role.ASSISTANT
        """


        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower()


        try:
            return cls(normalized)
        except ValueError as exc:
            valid_roles = ", ".join(role.value for role in cls)
            raise ProviderValidationError(
                f"Invalid message role: {value!r}. "
                f"Valid roles: {valid_roles}"
            ) from exc



# ============================================================================
# Data Structures
# ============================================================================



@dataclass(slots=True)
class ChatMessage:


    """
    A single message in an AI conversation.

    Parameters
    ----------
    role : Role
        Message role (system, user, or assistant)
    content : str
        Message text content
    timestamp : float, optional
        Unix timestamp of message (default: current time)
    """



    role: Role | str
    content: str
    timestamp: float = field(default_factory=time.time)


    def __post_init__(self) -> None:
        """Normalize role to Role enum."""
        if isinstance(self.role, str):
            self.role = Role.from_value(self.role)


    def to_dict(self) -> dict[str, str]:

        """
        Serialize message to dictionary.

        Returns
        -------
        dict[str, str]
            Dictionary with 'role' and 'content' keys
        """

        return {
            "role": self.role.value if isinstance(self.role, Role) else str(self.role),
            "content": str(self.content),
        }

    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:

        """
        Create ChatMessage from dictionary.

        Parameters
        ----------
        data : dict
            Dictionary with 'role' and 'content' keys

        Returns
        -------
        ChatMessage
            Parsed message object

        Raises
        ------
        ProviderValidationError
            If required keys are missing or invalid

        Examples
        --------
            msg = ChatMessage.from_dict({
                "role": "user",
                "content": "Hello"
            })
        """

        if not isinstance(data, dict):
            raise ProviderValidationError(
                f"Message must be a dict, got {type(data).__name__}."
            )
        

        if "role" not in data:
            raise ProviderValidationError(
                "Message dict must have 'role' key."
            )
        

        if "content" not in data:
            raise ProviderValidationError(
                "Message dict must have 'content' key."
            )
        

        role = Role.from_value(data["role"])
        content = str(data["content"])


        timestamp = data.get("timestamp", time.time())


        return cls(

            role=role,
            content=content,
            timestamp=timestamp,

        )



@dataclass(slots=True)
class CompletionResult:

    """
    Normalized AI completion result.

    Every provider returns this standardized structure so the rest
    of AssistantX remains provider-independent.

    Parameters
    ----------
    text : str, optional
        Generated response text
    provider : str, optional
        Provider name (e.g., 'gemini', 'ollama')
    model : str, optional
        Model name used
    latency_seconds : float, optional
        Request duration in seconds
    tokens_used : int, optional
        Total tokens used (prompt + completion)
    prompt_tokens : int, optional
        Tokens in prompt
    completion_tokens : int, optional
        Tokens in completion
    finish_reason : str, optional
        Why generation stopped (e.g., 'stop', 'length')
    raw : dict, optional
        Raw provider response for debugging
    error : str, optional
        Error message if request failed
    success : bool, optional
        Whether request succeeded
    request_id : str, optional
        Provider-specific request ID
    created_at : float, optional
        Unix timestamp of creation
    """


    text: str = ""
    provider: str = ""
    model: str = ""
    latency_seconds: float = 0.0
    tokens_used: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    raw: Any = None
    error: Optional[str] = None
    success: bool = True
    request_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)



    def __post_init__(self) -> None:
        """Normalize error state."""
        if self.error is not None:
            self.success = False


    @property
    def ok(self) -> bool:
        """Return True when completion succeeded."""
        return self.success and self.error is None


    @property
    def failed(self) -> bool:
        """Return True when completion failed."""
        return not self.ok


    @property
    def has_text(self) -> bool:
        """Return True when non-empty response was produced."""
        return bool(self.text.strip())


    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:

        """
        Serialize result to dictionary.

        Parameters
        ----------
        include_raw : bool, optional
            Whether to include raw provider response

        Returns
        -------
        dict[str, Any]
            Serialized result
        """

        data: dict[str, Any] = {

            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "latency_seconds": self.latency_seconds,
            "tokens_used": self.tokens_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finish_reason": self.finish_reason,
            "error": self.error,
            "success": self.success,
            "request_id": self.request_id,
            "created_at": self.created_at,

        }


        if include_raw and self.raw is not None:
            data["raw"] = self.raw

        return data


    @classmethod
    def failure(
        cls,
        provider: str,
        model: str,
        error: str,
        latency_seconds: float = 0.0,
        **kwargs: Any,
    ) -> CompletionResult:

        
        """
        Create a standardized failure result.

        Parameters
        ----------
        provider : str
            Provider name
        model : str
            Model name
        error : str
            Error message
        latency_seconds : float, optional
            Request duration
        **kwargs : Any
            Additional fields

        Returns
        -------
        CompletionResult
            Failure result object
        """

        return cls(

            text="",
            provider=provider,
            model=model,
            latency_seconds=latency_seconds,
            error=error,
            success=False,
            **kwargs,

        )


# ============================================================================
# Provider Metadata
# ============================================================================


@dataclass(frozen=True, slots=True)
class ProviderInfo:


    """
    Information about an AI provider.

    Parameters
    ----------
    name : str
        Provider name (e.g., 'gemini', 'ollama')
    model : str
        Current/default model
    available : bool
        Whether provider is currently available
    description : str, optional
        Provider description from docstring
    """


    name: str
    model: str
    available: bool
    description: str = ""




# ============================================================================
# Validation Utilities
# ============================================================================




def normalize_provider_name(name: str | AIProvider) -> str:

    """
    Normalize a provider name string.

    Parameters
    ----------
    name : str or AIProvider
        Provider name to normalize

    Returns
    -------
    str
        Normalized provider name (lowercase)

    Examples
    --------
        normalize_provider_name(" Gemini ")
        # Returns "gemini"

        normalize_provider_name(AIProvider.OLLAMA)
        # Returns "ollama"

        normalize_provider_name("google-gemini")
        # Returns "gemini" (via alias)
    """

    if isinstance(name, AIProvider):
        return name.value.lower()
    

    normalized = str(name).strip().lower()


    # Common aliases


    aliases = {


        "google": PROVIDER_GEMINI,
        "google-gemini": PROVIDER_GEMINI,
        "gemini-ai": PROVIDER_GEMINI,
        "ollama-local": PROVIDER_OLLAMA,
        "localai": PROVIDER_LOCAL,
        "local-ai": PROVIDER_LOCAL,


    }

    return aliases.get(normalized, normalized)



def validate_provider_name(name: str | AIProvider) -> str:


    """
    Validate and normalize a provider name.

    Parameters
    ----------
    name : str or AIProvider
        Provider name to validate

    Returns
    -------
    str
        Validated provider name

    Raises
    ------
    ProviderValidationError
        If provider is unknown

    Examples
    --------
        validate_provider_name("ollama")
        # Returns "ollama"

        validate_provider_name("unknown")
        # Raises ProviderValidationError
    """


    normalized = normalize_provider_name(name)


    if normalized not in SUPPORTED_PROVIDERS:
        valid = ", ".join(SUPPORTED_PROVIDERS)
        raise ProviderValidationError(

            f"Unknown AI provider: {name!r}. "
            f"Supported providers: {valid}"

        )
    


    logger.debug("Provider name validated: %s", normalized)
    return normalized


def validate_temperature(temperature: float) -> float:

    """
    Validate model temperature parameter.

    Parameters
    ----------
    temperature : float
        Sampling temperature (0.0 = deterministic, 2.0 = maximum randomness)

    Returns
    -------
    float
        Validated temperature value

    Raises
    ------
    ProviderValidationError
        If temperature is not numeric or out of range

    Examples
    --------
        validate_temperature(0.7)
        # Returns 0.7

        validate_temperature(3.0)
        # Raises ProviderValidationError
    """

    try:
        value = float(temperature)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            f"Invalid temperature: {temperature!r}. Must be numeric."
        ) from exc


    if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        raise ProviderValidationError(
            f"Temperature must be between {MIN_TEMPERATURE} and "
            f"{MAX_TEMPERATURE} (got {value})."

        )


    return value


def validate_retries(max_retries: int) -> int:

    """
    Validate retry count.

    Parameters
    ----------
    max_retries : int
        Maximum number of retry attempts

    Returns
    -------
    int
        Validated retry count

    Raises
    ------
    ProviderValidationError
        If retries is not an int or out of range

    Examples
    --------
        validate_retries(3)
        # Returns 3

        validate_retries(20)
        # Raises ProviderValidationError
    """

    try:
        retries = int(max_retries)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            f"Invalid retry count: {max_retries!r}. Must be an integer."
        ) from exc


    if not MIN_RETRIES <= retries <= MAX_ALLOWED_RETRIES:
        raise ProviderValidationError(

            f"max_retries must be between {MIN_RETRIES} and "
            f"{MAX_ALLOWED_RETRIES} (got {retries})."

        )


    return retries


def normalize_messages(
        
    messages: Sequence[ChatMessage | Mapping[str, Any]],
) -> list[ChatMessage]:
    
    """
    Normalize a sequence of message objects or dicts.

    Parameters
    ----------
    messages : Sequence[ChatMessage or Mapping]
        Messages to normalize

    Returns
    -------
    list[ChatMessage]
        Normalized message list

    Raises
    ------
    ProviderValidationError
        If messages is None, empty, or contains invalid types

    Examples
    --------
        msgs = normalize_messages([
            ChatMessage(Role.USER, "Hello"),
            {"role": "assistant", "content": "Hi!"}
        ])
    """

    if messages is None:
        raise ProviderValidationError("messages cannot be None.")
    


    normalized: list[ChatMessage] = []

    for idx, message in enumerate(messages):
        try:

            if isinstance(message, ChatMessage):
                normalized.append(message)

            elif isinstance(message, Mapping):
                normalized.append(ChatMessage.from_dict(dict(message)))

            else:
                raise ProviderValidationError(

                    f"Message[{idx}] is not a ChatMessage or Mapping, "
                    f"got {type(message).__name__}."

                )
            
        except ProviderValidationError as exc:
            logger.error("Failed to normalize message at index %d: %s", idx, exc)
            raise


    if not normalized:
        raise ProviderValidationError(

            "At least one chat message is required."

        )


    logger.debug("Normalized %d messages", len(normalized))
    return normalized



# ============================================================================
# Base Provider
# ============================================================================


class AIProviderBase(abc.ABC):

    """
    Abstract base class for all AssistantX AI providers.

    Subclasses must implement:
    - `_call_api()`: Synchronous API request
    - `is_available()`: Provider availability check

    The base class provides:
    - Input validation
    - Automatic retry with exponential backoff
    - Request timing and logging
    - Error normalization
    - Fallback streaming implementation

    Parameters
    ----------
    model : str, optional
        Model name (defaults to provider's default_model)
    temperature : float, optional
        Sampling temperature (default: 0.7, range: 0.0-2.0)
    timeout : float, optional
        Request timeout in seconds (default: 30.0)

    Raises
    ------
    ProviderValidationError
        If configuration is invalid

    Examples
    --------
        # Implemented by subclasses
        provider = CustomProvider(model="custom-model")
        result = provider.generate([
            ChatMessage(Role.USER, "Hello")
        ])
        if result.ok:
            print(result.text)
    """


    name: str = "base"
    default_model: str = ""


    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        
        """
        Initialize base provider.

        Parameters
        ----------
        model : str, optional
            Model name
        temperature : float, optional
            Temperature (0.0-2.0)
        timeout : float, optional
            Timeout in seconds
        """

        self.model = str(model or self.default_model).strip()
        self.temperature = validate_temperature(temperature)


        try:
            self.timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError(

                f"Invalid timeout: {timeout!r}. Must be numeric."
            ) from exc


        if self.timeout <= 0:
            raise ProviderValidationError(

                f"timeout must be greater than zero (got {self.timeout})."
            )


        if not self.model:
            logger.warning(

                "[%s] Provider initialized without a model name.",
                self.name,
            )


        logger.debug(

            "[%s] Initialized: model=%s temperature=%.1f timeout=%.1f",
            self.name,
            self.model,
            self.temperature,
            self.timeout,

        )

    # ------------------
    # ------------------------------------------------
    # Abstract API (subclasses must implement)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _call_api(

        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        
        """
        Execute API call to provider.

        Subclasses implement this to call their specific provider API.
        Handles authentication, request formatting, response parsing,
        and timeout/error handling for that provider.

        Parameters
        ----------
        messages : list[ChatMessage]
            Normalized conversation messages
        **kwargs : Any
            Provider-specific generation options

        Returns
        -------
        CompletionResult
            Normalized completion result

        Raises
        ------
        ProviderError
            Provider-specific error (connection, timeout, validation, etc.)
        """


        raise NotImplementedError(

            f"{self.__class__.__name__} must implement _call_api()."

        )

    @abc.abstractmethod
    def is_available(self) -> bool:

        """
        Check whether provider is currently available.

        Subclasses override this to perform dependency, configuration,
        authentication, or service availability checks.

        Returns
        -------
        bool
            True if provider is available and ready to use
        """

        raise NotImplementedError(

            f"{self.__class__.__name__} must implement is_available()."

        )

    # ------------------------------------------------------------------
    # Synchronous Generation
    # ------------------------------------------------------------------

    def generate(
            
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        max_retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> CompletionResult:
        
        """
        Generate an AI response with automatic retry and fallback.

        Failures are normalized into CompletionResult instead of
        crashing the caller. Retries use exponential backoff.

        Parameters
        ----------
        messages : Sequence[ChatMessage or Mapping]
            Conversation messages
        max_retries : int, optional
            Maximum retry attempts (default: 3, max: 10)
        **kwargs : Any
            Provider-specific generation options (temperature, etc.)

        Returns
        -------
        CompletionResult
            Result object with text, metadata, and error info

        Examples
        --------
            result = provider.generate([
                ChatMessage(Role.USER, "Hello")
            ])
            if result.ok:
                print(result.text)
            else:
                print(f"Error: {result.error}")

            # With custom options
            result = provider.generate(
                [ChatMessage(Role.USER, "Write code")],
                temperature=0.8,
                max_retries=5
            )
        """

        # Allow empty message list: return an empty CompletionResult instead of raising
        if not messages:
            return CompletionResult.failure(
                provider=self.name,
                model=self.model,
                error="No messages provided.",
            )
        normalized_messages = normalize_messages(messages)
        retries = validate_retries(max_retries)

        logger.debug(

            "[%s] Starting generation: messages=%d retries=%d",
            self.name,
            len(normalized_messages),
            retries,

        )

        start = time.monotonic()
        last_error: Optional[Exception] = None


        for attempt in range(1, retries + 1):

            try:
                logger.debug(

                    "[%s] Generation attempt %d/%d",
                    self.name,
                    attempt,
                    retries,

                )

                result = self._call_api(

                    normalized_messages,
                    **kwargs,

                )

                if result.ok:
                    elapsed = time.monotonic() - start
                    logger.info(

                        "[%s] Generation succeeded: model=%s latency=%.2fs",
                        self.name,
                        result.model,
                        elapsed,

                    )

                    return result



                last_error = ProviderRequestError(

                    result.error or "Provider request failed."

                )

                logger.warning(

                    "[%s] Attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    last_error,

                )

            except Exception as exc:
                last_error = exc

                logger.warning(

                    "[%s] Attempt %d/%d raised exception: %s",
                    self.name,
                    attempt,
                    retries,
                    exc,

                )

            if attempt < retries:
                delay = self._get_backoff_delay(attempt)
                logger.debug(

                    "[%s] Retrying in %.2f seconds...",
                    self.name,
                    delay,

                )
                time.sleep(delay)

        elapsed = time.monotonic() - start
        error_msg = str(last_error or "Unknown provider error")

        logger.error(

            "[%s] Generation failed after %d attempts (%.2fs): %s",
            self.name,
            retries,
            elapsed,
            error_msg,

        )

        return CompletionResult.failure(

            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            error=error_msg,

        )

    # ------------------------------------------------------------------
    # Asynchronous Generation
    # ------------------------------------------------------------------

    async def _call_api_async(
            
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        
        """
        Async API call (default: uses sync version).

        Providers with native async APIs should override this.

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs : Any
            Generation options

        Returns
        -------
        CompletionResult
            Generation result
        """

        return self._call_api(messages, **kwargs)

    async def generate_async(
            
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        max_retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> CompletionResult:
        
        """
        Async generation with retry support.

        Parameters
        ----------
        messages : Sequence[ChatMessage or Mapping]
            Conversation messages
        max_retries : int, optional
            Maximum retry attempts
        **kwargs : Any
            Generation options

        Returns
        -------
        CompletionResult
            Generation result
        """

        # Allow empty message list: return an empty CompletionResult instead of raising
        if not messages:
            return CompletionResult.failure(
                provider=self.name,
                model=self.model,
                error="No messages provided.",
            )
        normalized_messages = normalize_messages(messages)
        retries = validate_retries(max_retries)

        logger.debug(

            "[%s] Starting async generation: messages=%d retries=%d",
            self.name,
            len(normalized_messages),
            retries,
            
        )

        start = time.monotonic()
        last_error: Optional[Exception] = None


        for attempt in range(1, retries + 1):
            try:
                logger.debug(

                    "[%s] Async attempt %d/%d",
                    self.name,
                    attempt,
                    retries,

                )

                result = await self._call_api_async(

                    normalized_messages,
                    **kwargs,

                )

                if result.ok:
                    elapsed = time.monotonic() - start
                    logger.info(

                        "[%s] Async generation succeeded: latency=%.2fs",
                        self.name,
                        elapsed,

                    )

                    return result

                last_error = ProviderRequestError(

                    result.error or "Async request failed."

                )

                logger.warning(

                    "[%s] Async attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    last_error,

                )

            except Exception as exc:
                last_error = exc
                logger.warning(

                    "[%s] Async attempt %d/%d raised exception: %s",
                    self.name,
                    attempt,
                    retries,
                    exc,

                )

            if attempt < retries:
                delay = self._get_backoff_delay(attempt)
                logger.debug(

                    "[%s] Async retrying in %.2f seconds...",
                    self.name,
                    delay,

                )
                await asyncio.sleep(delay)

        elapsed = time.monotonic() - start
        error_msg = str(last_error or "Unknown provider error")

        logger.error(

            "[%s] Async generation failed after %d attempts (%.2fs): %s",
            self.name,
            retries,
            elapsed,
            error_msg,

        )

        return CompletionResult.failure(

            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            error=error_msg,

        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
            
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> Iterator[str]:
        
        """
        Stream response chunks.

        Providers with native streaming should override this method.
        Default implementation uses generate() and yields full text.

        Parameters
        ----------
        messages : Sequence[ChatMessage or Mapping]
            Conversation messages
        **kwargs : Any
            Generation options

        Yields
        ------
        str
            Response text chunks

        Examples
        --------
            for chunk in provider.stream([
                ChatMessage(Role.USER, "Write a story")
            ]):
                print(chunk, end="", flush=True)
            print()  # newline
        """

        logger.debug("[%s] Starting streaming generation", self.name)

        result = self.generate(messages, **kwargs)

        if result.ok and result.has_text:
            logger.debug("[%s] Streaming complete", self.name)
            yield result

    async def stream_async(
            
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        
        """
        Async streaming with fallback.

        Parameters
        ----------
        messages : Sequence[ChatMessage or Mapping]
            Conversation messages
        **kwargs : Any
            Generation options

        Yields
        ------
        str
            Response text chunks
        """

        logger.debug("[%s] Starting async streaming", self.name)

        result = await self.generate_async(messages, **kwargs)

        if result.ok and result.has_text:
            logger.debug("[%s] Async streaming complete", self.name)
            yield result.text

    # ------------------------------------------------------------------
    # Retry Support
    # ------------------------------------------------------------------



    @staticmethod
    def _get_backoff_delay(attempt: int) -> float:

        """
        Calculate exponential backoff delay.

        Parameters
        ----------
        attempt : int
            Attempt number (1-based)

        Returns
        -------
        float
            Delay in seconds

        Examples
        --------
            _get_backoff_delay(1)  # 1.0 second
            _get_backoff_delay(2)  # 2.0 seconds
            _get_backoff_delay(3)  # 4.0 seconds
            _get_backoff_delay(4)  # 8.0 seconds (capped)
        """

        delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
        return min(delay, BACKOFF_MAX_SECONDS)

    # ------------------------------------------------------------------
    # Metadata & Diagnostics
    # ------------------------------------------------------------------

    def get_info(self) -> ProviderInfo:
        """

        Return provider metadata.

        Returns
        -------
        ProviderInfo
            Provider information object
        """

        return ProviderInfo(

            name=self.name,
            model=self.model,
            available=self.is_available(),
            description=self.__class__.__doc__ or "",
            
        )

    def health_check(self) -> bool:

        """
        Safe availability check (never raises).

        Returns
        -------
        bool
            True if provider is available
        """

        try:
            available = self.is_available()
            logger.debug("[%s] Health check: %s", self.name, available)
            return available
        except Exception as exc:
            logger.debug(

                "[%s] Health check failed: %s",
                self.name,
                exc,

            )

            return False
        

    def diagnostics(self) -> dict[str, Any]:
        """
        Return provider diagnostic information.

        Returns
        -------
        dict[str, Any]
            Diagnostic data (to be enhanced by subclasses)
        """
        return {

            "provider": self.name,
            "model": self.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "available": self.health_check(),

        }

    def __repr__(self) -> str:
        """Return string representation."""

        return (

            f"<{self.__class__.__name__} "
            f"name={self.name!r} "
            f"model={self.model!r}>"
            
        )


# ============================================================================
# Provider Factory
# ============================================================================


def get_provider(
    provider_name: Optional[str | AIProvider] = None,
) -> AIProviderBase:
    
    """
    Create and return an initialized AI provider.

    Provider selection priority:

    1. Explicit ``provider_name`` argument
    2. ``ai.provider`` from AssistantX settings
    3. Gemini as the default provider

    Parameters
    ----------
    provider_name : str or AIProvider, optional
        Specific provider to load

    Returns
    -------
    AIProviderBase
        Initialized provider instance

    Raises
    ------
    ProviderFactoryError
        If settings, provider, or initialization fails

    Examples
    --------
        provider = get_provider("ollama")
        # Returns OllamaProvider

        provider = get_provider()
        # Returns default provider from settings
    """

    logger.debug("Factory: loading provider %r", provider_name)

    # Load settings

    try:
        from config.settings import settings_manager
    except Exception as exc:
        logger.error("Failed to load settings: %s", exc)
        raise ProviderFactoryError(
            "Unable to load AssistantX settings."
        ) from exc


    # Resolve provider name

    configured_provider = settings_manager.get(
        "ai.provider",
        PROVIDER_GEMINI,

    )

    selected_provider = (

        provider_name if provider_name is not None else configured_provider

    )

    name = normalize_provider_name(selected_provider)

    try:
        validate_provider_name(name)
    except ProviderValidationError:
        raise  # let ProviderValidationError propagate directly

    # Initialize provider

    try:

        if name == PROVIDER_GEMINI:
            provider_class = GeminiProvider or _load_gemini_provider()
            model = settings_manager.get("ai.gemini_model")
            instance = provider_class(model=model) if model else provider_class()


        elif name == PROVIDER_OLLAMA:
            provider_class = OllamaProvider or _load_ollama_provider()
            model = settings_manager.get("ai.ollama_model")
            instance = provider_class(model=model) if model else provider_class()


        elif name == PROVIDER_LOCAL:
            provider_class = LocalAIProvider or _load_local_provider()
            model = settings_manager.get("ai.local_model")
            instance = provider_class(model=model) if model else provider_class()


        else:
            raise ProviderFactoryError(f"Unsupported provider: {name}")


        logger.info("Factory: initialized %s provider", name)
        return instance


    except ImportError as exc:
        logger.error("Failed to import provider %s: %s", name, exc)
        raise ProviderFactoryError(
            f"Provider '{name}' is unavailable."
        ) from exc


    except Exception as exc:
        logger.error("Failed to initialize provider %s: %s", name, exc)
        raise ProviderFactoryError(
            f"Failed to initialize provider '{name}': {exc}"
        ) from exc



def try_get_provider(
    provider_name: Optional[str | AIProvider] = None,
) -> Optional[AIProviderBase]:
    
    """
    Safe provider factory (returns None on failure).

    Parameters
    ----------
    provider_name : str or AIProvider, optional
        Provider to load

    Returns
    -------
    AIProviderBase or None
        Initialized provider or None if creation fails
    """

    try:
        return get_provider(provider_name)
    except Exception as exc:
        logger.warning(
            "Could not initialize provider '%s': %s",
            provider_name,
            exc,
        )
        return None


# ============================================================================
# Fallback Chain
# ============================================================================


def get_fallback_chain(
    preferred: Optional[str | AIProvider] = None,
    *,
    available_only: bool = False,
) -> list[AIProviderBase]:
    
    """
    Build an ordered provider fallback chain.

    Default order:

    1. Preferred provider (if specified)
    2. Gemini
    3. Ollama
    4. Local AI

    Parameters
    ----------
    preferred : str or AIProvider, optional
        Preferred provider to try first
    available_only : bool, optional
        Only include currently available providers

    Returns
    -------
    list[AIProviderBase]
        Ordered list of provider instances (duplicates removed)

    Examples
    --------
        chain = get_fallback_chain(preferred="ollama")
        # [OllamaProvider, GeminiProvider, LocalAIProvider]

        chain = get_fallback_chain(available_only=True)
        # Only healthy providers
    """

    order: list[str] = []

    if preferred is not None:
        try:
            preferred_name = validate_provider_name(preferred)
            order.append(preferred_name)
            logger.debug("Fallback chain: preferred=%s", preferred_name)
        except ProviderError as exc:
            logger.warning("Invalid preferred provider '%s': %s", preferred, exc)

    for candidate in SUPPORTED_PROVIDERS:
        if candidate not in order:
            order.append(candidate)

    chain: list[AIProviderBase] = []

    for name in order:
        provider = try_get_provider(name)


        if provider is None:
            continue


        if available_only and not provider.health_check():
            logger.info("Provider '%s' unavailable; skipping.", name)
            continue


        chain.append(provider)


    logger.debug(
        "Fallback chain built: %s",
        [p.name for p in chain],

    )

    return chain


# ============================================================================
# Provider Discovery
# ============================================================================


def list_provider_names() -> tuple[str, ...]:

    """
    Return all registered built-in provider names.

    Returns
    -------
    tuple[str, ...]
        Provider name tuple
    """

    return SUPPORTED_PROVIDERS


def list_providers(
    *,
    available_only: bool = False,
) -> list[ProviderInfo]:
    
    """
    Return information about all built-in providers.

    Parameters
    ----------
    available_only : bool, optional
        Only include available providers

    Returns
    -------
    list[ProviderInfo]
        Provider information objects
    """

    providers: list[ProviderInfo] = []

    for name in SUPPORTED_PROVIDERS:
        provider = try_get_provider(name)

        if provider is None:
            continue

        info = provider.get_info()

        if available_only and not info.available:
            continue

        providers.append(info)

    return providers


def get_available_provider_names() -> list[str]:

    """
    Return names of currently available providers.

    Returns
    -------
    list[str]
        Available provider names
    """

    return [info.name for info in list_providers(available_only=True)]


def get_best_available_provider(
    preferred: Optional[str | AIProvider] = None,
) -> Optional[AIProviderBase]:
    
    """
    Return the first healthy provider from fallback chain.

    Parameters
    ----------
    preferred : str or AIProvider, optional
        Preferred provider

    Returns
    -------
    AIProviderBase or None
        First available provider or None
    """

    chain = get_fallback_chain(preferred=preferred, available_only=True)
    return chain[0] if chain else None


# ============================================================================
# High-Level Generate With Fallback
# ============================================================================


def generate_with_fallback(
    messages: Sequence[ChatMessage | Mapping[str, Any]],
    *,
    preferred: Optional[str | AIProvider] = None,
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> CompletionResult:
    
    """
    Generate a response using the fallback provider chain.

    Tries providers in order (preferred first) until one succeeds.

    Parameters
    ----------
    messages : Sequence[ChatMessage or Mapping]
        Conversation messages
    preferred : str or AIProvider, optional
        Preferred provider to try first
    max_retries : int, optional
        Retries per provider
    **kwargs : Any
        Generation options

    Returns
    -------
    CompletionResult
        Result from first successful provider

    Examples
    --------
        result = generate_with_fallback([
            ChatMessage(Role.USER, "Hello")
        ])
        # Tries fallback chain, returns first success

        result = generate_with_fallback(
            [ChatMessage(Role.USER, "Code")],
            preferred="ollama"
        )
        # Tries Ollama first, then fallback chain
    """

    chain = get_fallback_chain(preferred)


    if not chain:
        logger.error("No AI providers available")
        return CompletionResult.failure(
            provider="none",
            model="",
            error="No AI providers could be initialized.",
        )


    last_result: Optional[CompletionResult] = None


    for provider in chain:

        logger.info(

            "Fallback: trying %s (%s)",
            provider.name,
            provider.model,

        )

        result = provider.generate(

            messages,
            max_retries=max_retries,
            **kwargs,

        )


        last_result = result

        if result.ok:
            logger.info(
                "Fallback: success with %s",
                provider.name,
            )
            return result

        logger.warning(
            "Fallback: %s failed: %s",
            provider.name,
            result.error,
        )

    return last_result or CompletionResult.failure(

        provider="none",
        model="",
        error="All AI providers failed.",

    )


# ============================================================================
# Diagnostics
# ============================================================================


def provider_diagnostics() -> dict[str, Any]:

    """
    Return diagnostic information for debugging.

    Returns
    -------
    dict[str, Any]
        Diagnostic data including all providers and availability
    """

    diagnostics: dict[str, Any] = {

        "supported_providers": list(SUPPORTED_PROVIDERS),
        "providers": [],

    }


    for name in SUPPORTED_PROVIDERS:
        provider = try_get_provider(name)

        if provider is None:
            diagnostics["providers"].append(
                {
                    "name": name,
                    "initialized": False,
                    "available": False,
                }
            )
            continue



        diagnostics["providers"].append(
            {
                "name": provider.name,
                "model": provider.model,
                "initialized": True,
                "available": provider.health_check(),
            }
        )

    diagnostics["available_providers"] = get_available_provider_names()

    return diagnostics


# ============================================================================
# Public API
# ============================================================================


__all__ = [


    # Constants

    "MIN_TEMPERATURE",
    "MAX_TEMPERATURE",
    "MIN_RETRIES",
    "MAX_ALLOWED_RETRIES",
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_MAX_SECONDS",
    "MAX_MESSAGE_LENGTH",
    "PROVIDER_GEMINI",
    "PROVIDER_OLLAMA",
    "PROVIDER_LOCAL",
    "SUPPORTED_PROVIDERS",


    # Enums

    "Role",


    # Data classes
    
    "ChatMessage",
    "CompletionResult",
    "ProviderInfo",


    # Exceptions

    "ProviderError",
    "ProviderValidationError",
    "ProviderUnavailableError",
    "ProviderConfigurationError",
    "ProviderRequestError",
    "ProviderFactoryError",
    "ProviderStreamingError",


    # Base provider

    "AIProviderBase",

    # Utilities

    "normalize_provider_name",
    "validate_provider_name",
    "validate_temperature",
    "validate_retries",
    "normalize_messages",


    # Factory

    "get_provider",
    "try_get_provider",


    # Discovery

    "list_provider_names",
    "list_providers",
    "get_available_provider_names",
    "get_best_available_provider",


    # Fallback

    "get_fallback_chain",
    "generate_with_fallback",


    # Diagnostics

    "provider_diagnostics",


]


