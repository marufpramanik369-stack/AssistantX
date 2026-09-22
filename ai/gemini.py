"""
ai/gemini.py
============
Google Gemini AI provider for AssistantX.

Features
--------
- Optional Google Gemini SDK integration
- Lazy SDK import/configuration
- API-key based availability detection
- System instruction support
- Multi-turn conversation history
- Configurable temperature / top-p / max tokens
- Request timeout handling
- True streaming support
- Detailed Gemini-specific exceptions
- Health/diagnostic helpers
- Safe fallback-friendly behavior
- Compatible with ai.provider.AIProviderBase
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    ProviderError,
    ProviderRequestError,
    Role,
)
from config.constants import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_TEMPERATURE,
    REQUEST_TIMEOUT_SECONDS,
)
from config.secrets import secrets

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

PROVIDER_NAME = "gemini"

DEFAULT_MAX_TOKENS = 2048
DEFAULT_TOP_P = 0.9

MIN_TOP_P = 0.0
MAX_TOP_P = 1.0

MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 65536

MIN_MODEL_LENGTH = 1
MAX_MODEL_LENGTH = 200


# ============================================================================
# Exceptions
# ============================================================================


class GeminiError(ProviderError):
    """Base exception for Gemini provider errors."""


class GeminiValidationError(GeminiError):
    """Raised when Gemini input/configuration is invalid."""


class GeminiConfigurationError(GeminiError):
    """Raised when Gemini is not configured correctly."""


class GeminiConnectionError(GeminiError):
    """Raised when Gemini cannot be reached."""


class GeminiTimeoutError(GeminiConnectionError):
    """Raised when a Gemini request times out."""


class GeminiResponseError(GeminiError):
    """Raised when Gemini returns an invalid/unexpected response."""


class GeminiStreamingError(GeminiError):
    """Raised when Gemini streaming fails."""


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class GeminiServerInfo:
    """Diagnostic information about the Gemini provider."""

    provider: str
    model: str
    sdk_installed: bool
    api_key_configured: bool
    available: bool


# ============================================================================
# Validation helpers
# ============================================================================


def _validate_model(model: str) -> str:
    if not isinstance(model, str):
        raise GeminiValidationError("Gemini model must be a string.")

    model = model.strip()

    if not model:
        raise GeminiValidationError("Gemini model cannot be empty.")

    if len(model) > MAX_MODEL_LENGTH:
        raise GeminiValidationError(
            f"Gemini model name is too long. Maximum: {MAX_MODEL_LENGTH} characters."
        )

    return model


def _validate_top_p(value: Any) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError("top_p must be a number.") from exc

    if not MIN_TOP_P <= value <= MAX_TOP_P:
        raise GeminiValidationError(
            f"top_p must be between {MIN_TOP_P} and {MAX_TOP_P}."
        )

    return value


def _validate_max_tokens(value: Any) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError("max_tokens must be an integer.") from exc

    if not MIN_MAX_TOKENS <= value <= MAX_MAX_TOKENS:
        raise GeminiValidationError(
            f"max_tokens must be between "
            f"{MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}."
        )

    return value


def _validate_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError("timeout must be a number.") from exc

    if timeout <= 0:
        raise GeminiValidationError("timeout must be greater than zero.")

    return timeout


# ============================================================================
# SDK helpers
# ============================================================================


def _load_sdk():
    """
    Lazily import google-generativeai.

    Returns
    -------
    module
        The imported Gemini SDK module.

    Raises
    ------
    GeminiConfigurationError
        If the SDK is not installed.
    """

    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as exc:
        raise GeminiConfigurationError(
            "The 'google-generativeai' package is not installed. "
            "Install it with: pip install google-generativeai"
        ) from exc

    return genai


def _sdk_installed() -> bool:
    try:
        import google.generativeai  # noqa: F401
    except ImportError:
        return False

    return True


def _api_key_configured() -> bool:
    key = getattr(secrets, "gemini_api_key", None)
    return bool(key and str(key).strip())


# ============================================================================
# Message conversion
# ============================================================================


def _messages_to_gemini_format(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    """
    Convert AssistantX ChatMessage objects into Gemini chat format.

    Returns
    -------
    tuple
        (system_instruction, history)
    """

    system_instruction: str | None = None
    history: list[dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, ChatMessage):
            raise GeminiValidationError(
                "All messages must be ChatMessage instances."
            )

        content = message.content.strip()

        if not content:
            continue

        if message.role == Role.SYSTEM:
            if system_instruction is None:
                system_instruction = content
            else:
                system_instruction = (
                    f"{system_instruction}\n{content}"
                )

            continue

        if message.role == Role.ASSISTANT:
            gemini_role = "model"
        elif message.role == Role.USER:
            gemini_role = "user"
        else:
            raise GeminiValidationError(
                f"Unsupported message role: {message.role!r}"
            )

        history.append(
            {
                "role": gemini_role,
                "parts": [content],
            }
        )

    return system_instruction, history


# ============================================================================
# Response helpers
# ============================================================================


def _extract_finish_reason(response: Any) -> str | None:
    try:
        candidates = getattr(response, "candidates", None)

        if not candidates:
            return None

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)

        if finish_reason is None:
            return None

        return str(finish_reason)

    except (AttributeError, IndexError, TypeError):
        return None


def _extract_token_count(response: Any) -> int | None:
    try:
        metadata = getattr(response, "usage_metadata", None)

        if metadata is None:
            return None

        value = getattr(metadata, "total_token_count", None)

        if value is None:
            return None

        return int(value)

    except (AttributeError, TypeError, ValueError):
        return None


def _extract_response_text(response: Any) -> str:
    """
    Safely extract text from a Gemini response.
    """

    try:
        text = getattr(response, "text", None)

        if text:
            return str(text).strip()

    except Exception:  # noqa: BLE001
        pass

    return ""


# ============================================================================
# Gemini Provider
# ============================================================================


class GeminiProvider(AIProviderBase):
    """
    Google Gemini provider implementation.

    Gemini is optional. If the SDK or API key is unavailable,
    `is_available()` returns False so ai.provider can fall back
    to Ollama or Local AI.
    """

    name = PROVIDER_NAME
    default_model = DEFAULT_GEMINI_MODEL

    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:

        model = _validate_model(model or self.default_model)
        timeout = _validate_timeout(timeout)

        super().__init__(
            model=model,
            temperature=temperature,
            timeout=timeout,
        )

        self._client_module: Any = None
        self._model_instance: Any = None
        self._configured = False

    # ------------------------------------------------------------------
    # SDK / client
    # ------------------------------------------------------------------

    def _ensure_client(self):
        """
        Lazily load and configure the Gemini SDK.
        """

        if self._model_instance is not None:
            return self._model_instance

        if not _api_key_configured():
            raise GeminiConfigurationError(
                "GEMINI_API_KEY is not configured. "
                "Add your Gemini API key to the .env file."
            )

        genai = _load_sdk()

        try:
            genai.configure(
                api_key=str(secrets.gemini_api_key).strip()
            )
        except Exception as exc:
            logger.exception("Failed to configure Gemini SDK.")

            raise GeminiConfigurationError(
                f"Failed to configure Gemini SDK: {exc}"
            ) from exc

        self._client_module = genai
        self._configured = True

        try:
            self._model_instance = genai.GenerativeModel(
                self.model
            )
        except Exception as exc:
            logger.exception(
                "Failed to initialize Gemini model '%s'.",
                self.model,
            )

            raise GeminiConfigurationError(
                f"Failed to initialize Gemini model '{self.model}': {exc}"
            ) from exc

        return self._model_instance

    def _create_model(
        self,
        system_instruction: str | None = None,
    ):
        """
        Create a Gemini GenerativeModel.

        Gemini system instructions are attached at model level.
        """

        base_model = self._ensure_client()

        if not system_instruction:
            return base_model

        try:
            return self._client_module.GenerativeModel(
                self.model,
                system_instruction=system_instruction,
            )
        except Exception as exc:
            raise GeminiConfigurationError(
                f"Failed to create Gemini model with system instruction: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True when Gemini SDK and API key are available.
        """

        if not _api_key_configured():
            return False

        return _sdk_installed()

    def health_check(self) -> bool:
        """
        Perform a lightweight provider configuration check.

        This does not intentionally make a billable generation request.
        """

        return self.is_available()

    # ------------------------------------------------------------------
    # Generation config
    # ------------------------------------------------------------------

    def _build_generation_config(self, **kwargs) -> dict[str, Any]:
        temperature = kwargs.get(
            "temperature",
            self.temperature,
        )

        max_tokens = kwargs.get(
            "max_tokens",
            DEFAULT_MAX_TOKENS,
        )

        top_p = kwargs.get(
            "top_p",
            DEFAULT_TOP_P,
        )

        config = {
            "temperature": temperature,
            "max_output_tokens": _validate_max_tokens(max_tokens),
            "top_p": _validate_top_p(top_p),
        }

        # Optional Gemini generation settings.
        if "top_k" in kwargs and kwargs["top_k"] is not None:
            try:
                top_k = int(kwargs["top_k"])
            except (TypeError, ValueError) as exc:
                raise GeminiValidationError(
                    "top_k must be an integer."
                ) from exc

            if top_k < 1:
                raise GeminiValidationError(
                    "top_k must be greater than zero."
                )

            config["top_k"] = top_k

        if "candidate_count" in kwargs:
            try:
                candidate_count = int(kwargs["candidate_count"])
            except (TypeError, ValueError) as exc:
                raise GeminiValidationError(
                    "candidate_count must be an integer."
                ) from exc

            if candidate_count < 1:
                raise GeminiValidationError(
                    "candidate_count must be at least 1."
                )

            config["candidate_count"] = candidate_count

        return config

    # ------------------------------------------------------------------
    # API call
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[ChatMessage],
        **kwargs,
    ) -> CompletionResult:

        if not messages:
            raise GeminiValidationError(
                "At least one message is required."
            )

        system_instruction, history = _messages_to_gemini_format(
            messages
        )

        if not history:
            raise GeminiValidationError(
                "No user/assistant messages were provided to Gemini."
            )

        # The final message should normally be the current user turn.
        latest_turn = history[-1]

        if latest_turn["role"] != "user":
            raise GeminiValidationError(
                "The last Gemini message must be a user message."
            )

        chat_history = history[:-1]

        model = self._create_model(system_instruction)

        generation_config = self._build_generation_config(**kwargs)

        timeout = _validate_timeout(
            kwargs.get("timeout", self.timeout)
        )

        start = time.monotonic()

        try:
            chat_session = model.start_chat(
                history=chat_history
            )

            response = chat_session.send_message(
                latest_turn["parts"][0],
                generation_config=generation_config,
                request_options={
                    "timeout": timeout,
                },
            )

        except TimeoutError as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini request timed out after %.2fs.",
                elapsed,
            )

            raise GeminiTimeoutError(
                f"Gemini request timed out after {timeout:.1f} seconds."
            ) from exc

        except Exception as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini API request failed after %.2fs: %s",
                elapsed,
                exc,
            )

            raise ProviderRequestError(
                f"Gemini API request failed: {exc}"
            ) from exc

        elapsed = time.monotonic() - start

        text = _extract_response_text(response)

        if not text:
            logger.warning(
                "Gemini returned an empty response. finish_reason=%s",
                _extract_finish_reason(response),
            )

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            tokens_used=_extract_token_count(response),
            finish_reason=_extract_finish_reason(response),
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
        self,
        messages: list[ChatMessage],
        **kwargs,
    ) -> Iterable[str]:
        """
        Stream Gemini response chunks.

        Errors are logged and raised as GeminiStreamingError so callers
        can decide whether to fall back to another provider.
        """

        if not messages:
            raise GeminiValidationError(
                "At least one message is required."
            )

        system_instruction, history = _messages_to_gemini_format(
            messages
        )

        if not history:
            raise GeminiValidationError(
                "No user/assistant messages were provided to Gemini."
            )

        latest_turn = history[-1]

        if latest_turn["role"] != "user":
            raise GeminiValidationError(
                "The last Gemini message must be a user message."
            )

        chat_history = history[:-1]

        model = self._create_model(system_instruction)

        generation_config = self._build_generation_config(**kwargs)

        timeout = _validate_timeout(
            kwargs.get("timeout", self.timeout)
        )

        start = time.monotonic()

        try:
            chat_session = model.start_chat(
                history=chat_history
            )

            response_stream = chat_session.send_message(
                latest_turn["parts"][0],
                generation_config=generation_config,
                request_options={
                    "timeout": timeout,
                },
                stream=True,
            )

            for chunk in response_stream:
                text = _extract_response_text(chunk)

                if text:
                    yield text

        except TimeoutError as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini streaming timed out after %.2fs.",
                elapsed,
            )

            raise GeminiTimeoutError(
                f"Gemini streaming timed out after {timeout:.1f} seconds."
            ) from exc

        except Exception as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini streaming failed after %.2fs: %s",
                elapsed,
                exc,
            )

            raise GeminiStreamingError(
                f"Gemini streaming failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_server_info(self) -> GeminiServerInfo:
        """
        Return diagnostic information without making a generation call.
        """

        return GeminiServerInfo(
            provider=self.name,
            model=self.model,
            sdk_installed=_sdk_installed(),
            api_key_configured=_api_key_configured(),
            available=self.is_available(),
        )

    def diagnostics(self) -> dict[str, Any]:
        """
        Return JSON-friendly diagnostics.
        """

        info = self.get_server_info()

        return {
            "provider": info.provider,
            "model": info.model,
            "sdk_installed": info.sdk_installed,
            "api_key_configured": info.api_key_configured,
            "available": info.available,
            "configured": self._configured,
        }

    def __repr__(self) -> str:
        return (
            f"GeminiProvider("
            f"model={self.model!r}, "
            f"available={self.is_available()}"
            f")"
        )


# ============================================================================
# Module-level helpers
# ============================================================================


def gemini_available() -> bool:
    """Return whether Gemini can currently be used."""

    if not _api_key_configured():
        return False

    return _sdk_installed()


def create_gemini_provider(
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> GeminiProvider:
    """Create a configured Gemini provider."""

    return GeminiProvider(
        model=model,
        temperature=temperature,
        timeout=timeout,
    )


def gemini_diagnostics() -> dict[str, Any]:
    """Return Gemini provider diagnostics."""

    provider = GeminiProvider()

    return provider.diagnostics()


def get_gemini_model() -> str:
    """Return the configured/default Gemini model name."""

    return _validate_model(DEFAULT_GEMINI_MODEL)


# ============================================================================
# Backward-compatible aliases
# ============================================================================

is_gemini_available = gemini_available


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Provider
    "GeminiProvider",

    # Dataclasses
    "GeminiServerInfo",

    # Exceptions
    "GeminiError",
    "GeminiValidationError",
    "GeminiConfigurationError",
    "GeminiConnectionError",
    "GeminiTimeoutError",
    "GeminiResponseError",
    "GeminiStreamingError",

    # Helpers
    "gemini_available",
    "is_gemini_available",
    "create_gemini_provider",
    "gemini_diagnostics",
    "get_gemini_model",

    # Conversion helper
    "_messages_to_gemini_format",
]
