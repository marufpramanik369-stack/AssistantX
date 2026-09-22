"""
ai/provider.py
==============
Provider-agnostic AI abstraction layer for AssistantX.

This module defines:

- ChatMessage
- CompletionResult
- ProviderError hierarchy
- AIProviderBase
- Provider factory
- Fallback provider chain
- Provider availability helpers

The rest of AssistantX does not need to know whether the active
backend is Gemini, Ollama, or Local AI.

Architecture:

    core/assistant.py
            │
            ▼
        AI Provider
            │
      ┌─────┼─────┐
      ▼     ▼     ▼
   Gemini Ollama Local AI

Design goals:
- Provider-independent API
- Strong validation
- Graceful failures
- Retry support
- Exponential backoff
- Timeout forwarding
- Safe fallback support
- Streaming compatibility
- Easy future provider/plugin integration
"""

from __future__ import annotations

import abc
import logging
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config.constants import (
    DEFAULT_TEMPERATURE,
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    AIProvider,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Built-in Provider References
# ============================================================================
#
# Providers are loaded lazily to avoid circular imports.
# The concrete provider classes remain in their own modules while
# ai.provider exposes stable references for the factory and tests.

GeminiProvider = None
OllamaProvider = None
LocalAIProvider = None

#            UPDATED                                    ===============================================================================

@dataclass(slots=True)
class ChatMessage:
    """A single message in an AI conversation."""

    role: Any
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str]:
        return {
            "role": str(self.role),
            "content": self.content,
        }


def _load_gemini_provider():
    """Load and cache the Gemini provider class."""
    global GeminiProvider

    if GeminiProvider is None:
        from ai.gemini import GeminiProvider as _GeminiProvider

        GeminiProvider = _GeminiProvider

    return GeminiProvider


def _load_ollama_provider():
    """Load and cache the Ollama provider class."""
    global OllamaProvider

    if OllamaProvider is None:
        from ai.ollama import OllamaProvider as _OllamaProvider

        OllamaProvider = _OllamaProvider

    return OllamaProvider


def _load_local_provider():
    """Load and cache the Local AI provider class."""
    global LocalAIProvider

    if LocalAIProvider is None:
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

DEFAULT_MAX_TOKENS: int | None = None

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
    """Standard LLM conversation roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

    @classmethod
    def from_value(cls, value: str | Role) -> Role:
        """Convert a string/value to Role."""
        if isinstance(value, cls):
            return value

        normalized = str(value).strip().lower()

        try:
            return cls(normalized)
        except ValueError as exc:
            raise ProviderValidationError(
                f"Invalid message role: {value!r}. "
                f"Valid roles: {', '.join(role.value for role in cls)}"
            ) from exc


# ============================================================================
# Data Structures
# ============================================================================

@dataclass(slots=True)
class CompletionResult:
    """
    Normalized AI completion result.

    Every provider should return this structure so the rest of AssistantX
    remains provider-independent.
    """

    text: str = ""
    provider: str = ""
    model: str = ""
    latency_seconds: float = 0.0

    tokens_used: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    finish_reason: str | None = None

    raw: Any | None = None
    error: str | None = None
    error_message: str | None = None
    success: bool = True

    request_id: str | None = None

    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        # Normalize error messages between error and error_message attributes
        if self.error_message and not self.error:
            self.error = self.error_message
        elif self.error and not self.error_message:
            self.error_message = self.error

        if self.error is not None:
            self.success = False

    @property
    def ok(self) -> bool:
        """Return True when the completion succeeded."""
        return self.success and self.error is None

    @property
    def failed(self) -> bool:
        """Return True when the completion failed."""
        return not self.ok

    @property
    def has_text(self) -> bool:
        """Return True when a non-empty response was produced."""
        return bool(self.text.strip())

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        """Serialize the result."""
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
            "error_message": self.error_message,
            "success": self.success,
            "request_id": self.request_id,
            "created_at": self.created_at,
        }

        if include_raw:
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
        """Create a standardized failure result."""
        return cls(
            text="",
            provider=provider,
            model=model,
            latency_seconds=latency_seconds,
            error=error,
            error_message=error,
            success=False,
            **kwargs,
        )



# ============================================================================
# Provider Metadata
# ============================================================================


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Describes an AI provider."""

    name: str
    model: str
    available: bool
    description: str = ""


# ============================================================================
# Utility Functions
# ============================================================================


def normalize_provider_name(name: str | AIProvider) -> str:
    """
    Normalize a provider name.

    Examples:
        " Gemini " -> "gemini"
        AIProvider.OLLAMA -> "ollama"
    """
    if isinstance(name, AIProvider):
        return name.value.lower()

    normalized = str(name).strip().lower()

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
    """Validate and normalize a provider name."""
    normalized = normalize_provider_name(name)

    if normalized not in SUPPORTED_PROVIDERS:
        raise ProviderValidationError(
            f"Unknown AI provider: {name!r}. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    return normalized


def validate_temperature(temperature: float) -> float:
    """Validate model temperature."""
    try:
        value = float(temperature)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            f"Invalid temperature: {temperature!r}"
        ) from exc

    if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        raise ProviderValidationError(
            f"Temperature must be between "
            f"{MIN_TEMPERATURE} and {MAX_TEMPERATURE}."
        )

    return value


def validate_retries(max_retries: int) -> int:
    """Validate retry count."""
    try:
        retries = int(max_retries)
    except (TypeError, ValueError) as exc:
        raise ProviderValidationError(
            f"Invalid retry count: {max_retries!r}"
        ) from exc

    if not MIN_RETRIES <= retries <= MAX_ALLOWED_RETRIES:
        raise ProviderValidationError(
            f"max_retries must be between "
            f"{MIN_RETRIES} and {MAX_ALLOWED_RETRIES}."
        )

    return retries


def normalize_messages(
    messages: Sequence[ChatMessage | Mapping[str, Any]],
) -> list[ChatMessage]:
    """
    Normalize a sequence of ChatMessage objects/dictionaries.
    """
    if messages is None:
        raise ProviderValidationError("messages cannot be None.")

    normalized: list[ChatMessage] = []

    for message in messages:
        if isinstance(message, ChatMessage):
            normalized.append(message)
        elif isinstance(message, Mapping):
            normalized.append(ChatMessage.from_dict(message))
        else:
            raise ProviderValidationError(
                "Each message must be ChatMessage or mapping."
            )

    if not normalized:
        raise ProviderValidationError(
            "At least one chat message is required."
        )

    return normalized


# ============================================================================
# Base Provider
# ============================================================================


class AIProviderBase(abc.ABC):
    """
    Abstract base class for all AssistantX AI providers.

    Concrete providers implement:

        _call_api()
        is_available()

    This class handles:

        - validation
        - retries
        - timing
        - logging
        - error normalization
        - basic streaming fallback
    """

    name: str = "base"
    default_model: str = ""

    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.model = str(model or self.default_model).strip()
        self.temperature = validate_temperature(temperature)

        try:
            self.timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ProviderValidationError(
                f"Invalid timeout: {timeout!r}"
            ) from exc

        if self.timeout <= 0:
            raise ProviderValidationError(
                "timeout must be greater than zero."
            )

        if not self.model:
            logger.warning(
                "[%s] Provider initialized without a model.",
                self.name,
            )

    # Updated                                                                              =======================================================================================


    def generate(self, prompt: Any, **kwargs: Any) -> CompletionResult:
        """
        Generate a response using the provider's API wrapper.
        """
        if not prompt and not isinstance(prompt, (list, dict)):
            raise ProviderValidationError("Prompt or messages cannot be empty.")

        start_time = time.perf_counter()
        try:
            result = self._call_api(prompt, **kwargs)
            if isinstance(result, CompletionResult):
                return result
            
            # If _call_api returned a string or raw response, wrap it
            return CompletionResult(
                text=str(result),
                provider=getattr(self, "provider_name", self.name),
                model=self.model,
                latency_seconds=time.perf_counter() - start_time,
                finish_reason="stop",
            )
        except Exception as exc:
            logger.error("[%s] API call failed: %s", self.name, exc)
            return CompletionResult(
                text="",
                provider=getattr(self, "provider_name", self.name),
                model=self.model,
                success=False,
                error_message=str(exc),
                latency_seconds=time.perf_counter() - start_time,
            )

    def stream(self, prompt: Any, **kwargs: Any):
        """
        Stream response yields completion results or chunks.
        """
        result = self.generate(prompt, **kwargs)
        yield result


    # ------------------------------------------------------------------
    # Abstract API
    # ------------------------------------------------------------------

# UPDATED 


def _generate(
    self,
    messages: list[ChatMessage],
    **kwargs: Any,
) -> CompletionResult:
    """
    Provider-specific generation hook.

    Lightweight providers and test doubles can override this method
    instead of implementing the lower-level ``_call_api`` method.

    Args:
        messages:
            Normalized chat messages.

        **kwargs:
            Additional provider-specific generation options.

    Returns:
        CompletionResult:
            Provider completion result.

    Raises:
        NotImplementedError:
            If neither ``_generate`` nor ``_call_api`` is implemented.
    """
    raise NotImplementedError(
        f"{self.__class__.__name__} must implement "
        "_generate() or _call_api()."
    )


def _call_api(
    self,
    messages: list[ChatMessage],
    **kwargs: Any,
) -> CompletionResult:
    """
    Provider API compatibility hook.

    Concrete production providers may override this method directly.
    Lightweight providers and test doubles may instead override
    ``_generate()``.

    Args:
        messages:
            Normalized chat messages.

        **kwargs:
            Additional provider-specific options.

    Returns:
        CompletionResult:
            Result returned by the provider implementation.
    """
    return self._generate(
        messages,
        **kwargs,
    )


    # UPDATED 


    def is_available(self) -> bool:
        """
        Check whether the AI provider is currently available.

        The base implementation assumes that the provider is available.
        Concrete provider implementations may override this method to
        perform dependency, configuration, authentication, or service
        availability checks.

        Returns:
            bool:
                ``True`` when the provider is available; otherwise,
                ``False``.
        """
        return True


    # ------------------------------------------------------------------
    # Optional async API
    # ------------------------------------------------------------------

    async def _call_api_async(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Default async implementation.

        Providers can override this when they have a native async API.
        """
        return self._call_api(messages, **kwargs)

    async def generate_async(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        max_retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Async version of generate().
        """
        normalized_messages = normalize_messages(messages)
        retries = validate_retries(max_retries)

        start = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                result = await self._call_api_async(
                    normalized_messages,
                    **kwargs,
                )

                if result.ok:
                    return result

                last_error = ProviderRequestError(
                    result.error or "Provider request failed."
                )

                logger.warning(
                    "[%s] async attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    last_error,
                )

            except Exception as exc:  # noqa: BLE001
                last_error = exc

                logger.warning(
                    "[%s] async attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    exc,
                )

            if attempt < retries:
                delay = self._get_backoff_delay(attempt)
                await self._async_sleep(delay)

        elapsed = time.monotonic() - start

        logger.error(
            "[%s] Async generation failed after %d attempts (%.2fs).",
            self.name,
            retries,
            elapsed,
        )

        return CompletionResult.failure(
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            error=str(last_error or "Unknown provider error"),
        )

    @staticmethod
    async def _async_sleep(seconds: float) -> None:
        """Async sleep helper kept import-light."""
        import asyncio

        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Synchronous generation
    # ------------------------------------------------------------------

def generate(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        max_retries: int = MAX_RETRIES,
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate an AI response.

        Failures are normalized into CompletionResult instead of being
        allowed to crash the caller.
        """
        normalized_messages = normalize_messages(messages)
        retries = validate_retries(max_retries)

        start = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                result = self._call_api(
                    normalized_messages,
                    **kwargs,
                )

                if result.ok:
                    return result

                last_error = ProviderRequestError(
                    getattr(result, "error", None) or getattr(result, "error_message", None) or "Provider request failed."
                )

                logger.warning(
                    "[%s] attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    last_error,
                )

            except Exception as exc:  # noqa: BLE001
                last_error = exc

                logger.warning(
                    "[%s] attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    retries,
                    exc,
                )

            if attempt < retries:
                delay = self._get_backoff_delay(attempt) if hasattr(self, "_get_backoff_delay") else 0.5

                logger.debug(
                    "[%s] retrying in %.2fs...",
                    self.name,
                    delay,
                )

                time.sleep(delay)

        elapsed = time.monotonic() - start

        error_message = str(
            last_error or "Unknown provider error"
        )

        logger.error(
            "[%s] generation failed after %d attempts (%.2fs): %s",
            self.name,
            retries,
            elapsed,
            error_message,
        )

        if hasattr(CompletionResult, "failure"):
            return CompletionResult.failure(
                provider=self.name,
                model=self.model,
                latency_seconds=elapsed,
                error=error_message,
            )

        return CompletionResult(
            text="",
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------



   # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

def stream(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream response generator with fallback handling.

        Yields completion chunks or full text as string tokens.
        Providers with native streaming capabilities should override this method.
        """
        result = self.generate(messages, **kwargs)

        # Ensure response was successful and contains text before yielding
        is_successful = getattr(result, "ok", True) and not getattr(
            result, "error_message", None
        )
        if is_successful and getattr(result, "text", None):
            yield str(result.text)

async def stream_async(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Default async streaming implementation.
        """
        result = await self.generate_async(messages, **kwargs)

        if getattr(result, "ok", True) and result.text:
            yield result.text

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------


def _get_backoff_delay(attempt: int) -> float:
        """
        Calculate exponential backoff.

        Attempt 1 -> 1 sec
        Attempt 2 -> 2 sec
        Attempt 3 -> 4 sec
        Attempt 4+ -> max 8 sec
        """
        return min(
            BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            BACKOFF_MAX_SECONDS,
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

def get_info(self) -> ProviderInfo:
        """Return provider metadata."""
        return ProviderInfo(
            name=self.name,
            model=self.model,
            available=self.is_available(),
            description=self.__class__.__doc__ or "",
        )

def health_check(self) -> bool:
        """
        Safe availability check.

        Unlike is_available(), this method never propagates exceptions.
        """
        try:
            return bool(self.is_available())
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "[%s] health check failed: %s",
                self.name,
                exc,
            )
            return False

def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"name={self.name!r} "
            f"model={self.model!r}>"
        )


# ============================================================================
# Provider Factory                                                              ========================================================================================
# ============================================================================


def get_provider(
    provider_name: str | AIProvider | None = None,
) -> AIProviderBase:
    """
    Create and return an initialized AI provider.

    Provider selection priority:

    1. Explicit ``provider_name`` argument.
    2. ``ai.provider`` from AssistantX settings.
    3. Gemini as the default provider.

    Supported providers:

        - Gemini
        - Ollama
        - Local AI

    The provider classes are exposed at module level intentionally.
    This allows dependency injection and normal ``unittest.mock.patch``
    usage while still keeping real provider imports lazy.

    Args:
        provider_name:
            Optional provider name or ``AIProvider`` enum value.

    Returns:
        AIProviderBase:
            Initialized provider instance.

    Raises:
        ProviderFactoryError:
            If settings cannot be loaded, the provider is invalid,
            the provider implementation cannot be imported, or
            initialization fails.
    """

    # ------------------------------------------------------------------
    # Load settings
    # ------------------------------------------------------------------
    try:
        from config.settings import settings_manager
    except Exception as exc:
        raise ProviderFactoryError(
            "Unable to load AssistantX settings."
        ) from exc

    # ------------------------------------------------------------------
    # Resolve provider name
    # ------------------------------------------------------------------
    configured_provider = settings_manager.get(
        "ai.provider",
        PROVIDER_GEMINI,
    )

    selected_provider = (
        provider_name
        if provider_name is not None
        else configured_provider
    )

    name = normalize_provider_name(
        selected_provider
    )

    validate_provider_name(name)

    # ------------------------------------------------------------------
    # Initialize selected provider
    # ------------------------------------------------------------------
    try:

        # ==============================================================
        # Gemini
        # ==============================================================
        if name == PROVIDER_GEMINI:

            provider_class = GeminiProvider

            # The module-level reference may be None when the real
            # provider has not yet been imported. Load it lazily.
            if provider_class is None:
                provider_class = _load_gemini_provider()

            model = settings_manager.get(
                "ai.gemini_model"
            )

            if model:
                return provider_class(
                    model=model,
                )

            return provider_class()

        # ==============================================================
        # Ollama
        # ==============================================================
        if name == PROVIDER_OLLAMA:

            provider_class = OllamaProvider

            if provider_class is None:
                provider_class = _load_ollama_provider()

            model = settings_manager.get(
                "ai.ollama_model"
            )

            if model:
                return provider_class(
                    model=model,
                )

            return provider_class()

        # ==============================================================
        # Local AI
        # ==============================================================
        if name == PROVIDER_LOCAL:

            provider_class = LocalAIProvider

            if provider_class is None:
                provider_class = _load_local_provider()

            model = settings_manager.get(
                "ai.local_model"
            )

            if model:
                return provider_class(
                    model=model,
                )

            return provider_class()

    except ImportError as exc:
        logger.exception(
            "Unable to import AI provider '%s'.",
            name,
        )

        raise ProviderFactoryError(
            f"AI provider '{name}' is unavailable."
        ) from exc

    except Exception as exc:
        logger.exception(
            "Failed to initialize AI provider '%s'.",
            name,
        )

        raise ProviderFactoryError(
            f"Failed to initialize AI provider "
            f"'{name}': {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # Defensive fallback
    # ------------------------------------------------------------------
    raise ProviderFactoryError(
        f"Unsupported AI provider: {name}"
    )
    


# ============================================================================
# Safe Factory
# ============================================================================


def try_get_provider(
    provider_name: str | AIProvider | None = None,
) -> AIProviderBase | None:
    """
    Safe provider factory.

    Returns None instead of raising when provider creation fails.
    """
    try:
        return get_provider(provider_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not initialize provider '%s': %s",
            provider_name,
            exc,
        )
        return None

#                                 ===================================================================================================================================================
# ============================================================================
# Fallback Chain
# ============================================================================


def get_fallback_chain(
    preferred: str | AIProvider | None = None,
    *,
    available_only: bool = False,
) -> list[AIProviderBase]:
    """
    Build an ordered provider fallback chain.

    Default order:

        preferred
        Gemini
        Ollama
        Local AI

    Duplicate providers are removed.

    Args:
        preferred:
            Preferred provider.
        available_only:
            If True, unavailable providers are excluded.
    """
    order: list[str] = []

    if preferred is not None:
        try:
            preferred_name = validate_provider_name(preferred)
            order.append(preferred_name)
        except ProviderError as exc:
            logger.warning(
                "Invalid preferred provider '%s': %s",
                preferred,
                exc,
            )

    for candidate in SUPPORTED_PROVIDERS:
        if candidate not in order:
            order.append(candidate)

    chain: list[AIProviderBase] = []

    for name in order:
        provider = try_get_provider(name)

        if provider is None:
            continue

        if available_only and not provider.health_check():
            logger.info(
                "Provider '%s' is unavailable; skipping.",
                name,
            )
            continue

        chain.append(provider)

    logger.debug(
        "Fallback chain: %s",
        [provider.name for provider in chain],
    )

    return chain


# ============================================================================
# Provider Discovery
# ============================================================================


def list_provider_names() -> tuple[str, ...]:
    """Return all registered built-in provider names."""
    return SUPPORTED_PROVIDERS


def list_providers(
    *,
    available_only: bool = False,
) -> list[ProviderInfo]:
    """
    Return information about all built-in providers.
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
    """Return names of providers currently available."""
    return [
        info.name
        for info in list_providers(available_only=True)
    ]


def get_best_available_provider(
    preferred: str | AIProvider | None = None,
) -> AIProviderBase | None:
    """
    Return the first healthy provider from the fallback chain.
    """
    chain = get_fallback_chain(
        preferred=preferred,
        available_only=True,
    )

    return chain[0] if chain else None


# ============================================================================
# High-Level Generate With Fallback
# ============================================================================


def generate_with_fallback(
    messages: Sequence[ChatMessage | Mapping[str, Any]],
    *,
    preferred: str | AIProvider | None = None,
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> CompletionResult:
    """
    Generate a response using the fallback provider chain.

    Example:

        result = generate_with_fallback(
            [
                ChatMessage(
                    Role.USER,
                    "Hello AssistantX"
                )
            ]
        )

    If Gemini fails, Ollama is attempted, followed by Local AI.
    """
    chain = get_fallback_chain(preferred)

    if not chain:
        return CompletionResult.failure(
            provider="none",
            model="",
            error="No AI providers could be initialized.",
        )

    last_result: CompletionResult | None = None

    for provider in chain:
        logger.info(
            "Trying AI provider: %s (%s)",
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
                "AI response generated successfully using %s.",
                provider.name,
            )
            return result

        logger.warning(
            "Provider '%s' failed: %s",
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
    Return diagnostic information useful for debugging AssistantX AI.
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

    diagnostics["available_providers"] = (
        get_available_provider_names()
    )

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


