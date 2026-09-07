"""
provider.py
===========
Defines the abstract contract every AI backend (Gemini, Ollama, local
models) must implement, plus shared data structures (ChatMessage,
CompletionResult) and a factory function that resolves the active
provider based on user settings.

Keeping this abstraction thin and provider-agnostic means brain/ and
core/assistant.py never need to know whether a response came from
Gemini's cloud API or a local Ollama model — they just call
`provider.generate(...)`.
"""

from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Iterable, Optional

from config.constants import AIProvider, DEFAULT_TEMPERATURE, MAX_RETRIES, REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class Role(str, Enum):
    """Chat message roles, mirroring the common LLM chat format."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ChatMessage:
    """A single turn in a conversation."""

    role: Role
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"role": self.role.value, "content": self.content}


@dataclass
class CompletionResult:
    """Normalized response returned by every provider's generate() call."""

    text: str
    provider: str
    model: str
    latency_seconds: float
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None
    raw: Optional[dict] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class ProviderError(RuntimeError):
    """Raised when a provider fails to produce a completion after retries."""


class AIProviderBase(abc.ABC):
    """
    Abstract base class for all AI backends.

    Concrete subclasses (GeminiProvider, OllamaProvider, LocalAIProvider)
    must implement `_call_api`. This base class handles cross-cutting
    concerns: retries, timing, logging, and error normalization, so
    subclasses stay focused purely on their API's wire format.
    """

    name: str = "base"
    default_model: str = ""

    def __init__(self, model: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> None:
        self.model = model or self.default_model
        self.temperature = temperature

    @abc.abstractmethod
    def _call_api(self, messages: list[ChatMessage], **kwargs) -> CompletionResult:
        """Provider-specific implementation. Must return a CompletionResult."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Quick, cheap check for whether this provider is usable right now
        (API key present, local server reachable, etc.)."""
        raise NotImplementedError

    def generate(
        self,
        messages: list[ChatMessage],
        max_retries: int = MAX_RETRIES,
        **kwargs,
    ) -> CompletionResult:
        """
        Generate a completion with automatic retry-with-backoff on
        transient failures. Always returns a CompletionResult — on total
        failure, `result.error` is populated instead of raising, so
        callers (brain/response_generator.py) can degrade gracefully.
        """
        last_error: Optional[Exception] = None
        start = time.monotonic()

        for attempt in range(1, max_retries + 1):
            try:
                result = self._call_api(messages, **kwargs)
                if result.ok:
                    return result
                last_error = RuntimeError(result.error)
            except Exception as exc:  # noqa: BLE001 - normalize all provider errors
                last_error = exc
                logger.warning(
                    "[%s] generate() attempt %d/%d failed: %s",
                    self.name,
                    attempt,
                    max_retries,
                    exc,
                )
                backoff = min(2 ** (attempt - 1), 8)
                if attempt < max_retries:
                    time.sleep(backoff)

        elapsed = time.monotonic() - start
        logger.error("[%s] generate() failed after %d attempts (%.2fs).", self.name, max_retries, elapsed)
        return CompletionResult(
            text="",
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            error=str(last_error) if last_error else "Unknown provider error",
        )

    def stream(self, messages: list[ChatMessage], **kwargs) -> Iterable[str]:
        """
        Default streaming implementation: yields the full response as a
        single chunk. Providers that support true token-by-token
        streaming (Gemini, Ollama) should override this method.
        """
        result = self.generate(messages, **kwargs)
        if result.ok:
            yield result.text

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{self.__class__.__name__} model={self.model!r}>"


def get_provider(provider_name: Optional[str] = None) -> AIProviderBase:
    """
    Factory that resolves and instantiates the requested AI provider.

    Args:
        provider_name: One of AIProvider values ('gemini', 'ollama',
            'local'). Defaults to the user's configured provider in
            settings if not specified.

    Returns:
        An instantiated, ready-to-use AIProviderBase subclass.

    Raises:
        ValueError: If the provider name is not recognized.
    """
    from config.settings import settings_manager

    name = (provider_name or settings_manager.get("ai.provider", AIProvider.GEMINI.value)).lower()

    if name == AIProvider.GEMINI.value:
        from ai.gemini import GeminiProvider

        return GeminiProvider(model=settings_manager.get("ai.gemini_model"))
    elif name == AIProvider.OLLAMA.value:
        from ai.ollama import OllamaProvider

        return OllamaProvider(model=settings_manager.get("ai.ollama_model"))
    elif name == AIProvider.LOCAL.value:
        from ai.local_ai import LocalAIProvider

        return LocalAIProvider()
    else:
        raise ValueError(f"Unknown AI provider: '{name}'. Valid options: gemini, ollama, local.")


def get_fallback_chain(preferred: Optional[str] = None) -> list[AIProviderBase]:
    """
    Build an ordered list of providers to try in sequence, so if the
    user's preferred provider is unavailable (no API key, server down),
    AssistantX can transparently fall back to another one rather than
    failing outright.
    """
    order = [preferred] if preferred else []
    for candidate in (AIProvider.GEMINI.value, AIProvider.OLLAMA.value, AIProvider.LOCAL.value):
        if candidate not in order:
            order.append(candidate)

    chain: list[AIProviderBase] = []
    for name in order:
        try:
            provider = get_provider(name)
            chain.append(provider)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping provider '%s' during fallback chain build: %s", name, exc)

    return chain
    