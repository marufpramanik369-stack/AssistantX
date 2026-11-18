"""
ai/gemini.py (IMPROVED VERSION)
===============================
Google Gemini AI provider for AssistantX.

Features
--------
- Optional Google Gemini SDK integration with lazy loading
- Automatic API-key based availability detection
- System instruction support at model level
- Multi-turn conversation history management
- Configurable temperature, top-p, max tokens
- Request timeout handling with proper error recovery
- True streaming support with chunk-by-chunk yielding
- Detailed Gemini-specific exceptions with context
- Health checks and diagnostic helpers
- Safe fallback-friendly behavior for graceful degradation
- Full compatibility with ai.provider.AIProviderBase

Thread Safety
-------------
SDK initialization is thread-safe through lazy loading pattern.

Architecture
------------
Gemini is optional. If SDK is not installed or API key is missing,
is_available() returns False, allowing the provider chain to fall back
to Ollama or Local AI seamlessly.
"""

from __future__ import annotations

import abc
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
    validate_temperature,
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

# Model parameters
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TOP_P = 0.9

# Parameter bounds
MIN_TOP_P = 0.0
MAX_TOP_P = 1.0
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 65536
MIN_TOP_K = 1
MIN_CANDIDATE_COUNT = 1

# Input validation
MIN_MODEL_LENGTH = 1
MAX_MODEL_LENGTH = 200


# ============================================================================
# Exceptions
# ============================================================================


class GeminiError(ProviderError):
    """Base exception for Gemini provider-specific errors."""


class GeminiValidationError(GeminiError):
    """Raised when Gemini input or configuration validation fails."""



class GeminiConfigurationError(GeminiError):
    """Raised when Gemini is not properly configured (SDK/API key missing)."""


class GeminiConnectionError(GeminiError):
    """Raised when Gemini API connection fails."""


class GeminiTimeoutError(GeminiConnectionError):
    """Raised when a Gemini API request times out."""



class GeminiResponseError(GeminiError):
    """Raised when Gemini returns an invalid or unexpected response."""



class GeminiStreamingError(GeminiError):
    """Raised when Gemini streaming operation fails."""



# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class GeminiServerInfo:
    """
    Diagnostic information about the Gemini provider.

    Attributes
    ----------
    provider : str
        Provider name (always "gemini")
    model : str
        Configured model name
    sdk_installed : bool
        Whether google-generativeai is installed
    api_key_configured : bool
        Whether GEMINI_API_KEY is set
    available : bool
        Whether provider is ready to use
    """

    provider: str
    model: str
    sdk_installed: bool
    api_key_configured: bool
    available: bool


# ============================================================================
# Validation Helpers
# ============================================================================


def _validate_model(model: str) -> str:
    """
    Validate Gemini model name.

    Parameters
    ----------
    model : str
        Model name/ID

    Returns
    -------
    str
        Validated model name

    Raises
    ------
    GeminiValidationError
        If model is invalid
    """

    if not isinstance(model, str):
        raise GeminiValidationError(
            f"Gemini model must be a string, got {type(model).__name__}."
        )

    model = model.strip()

    if not model:
        raise GeminiValidationError(
            "Gemini model cannot be empty or whitespace-only."
        )

    if len(model) > MAX_MODEL_LENGTH:
        raise GeminiValidationError(
            f"Gemini model name exceeds {MAX_MODEL_LENGTH} characters "
            f"(got {len(model)})."
        )

    return model


def _validate_top_p(value: Any) -> float:
    """
    Validate top-p sampling parameter.

    Parameters
    ----------
    value : Any
        Value to validate

    Returns
    -------
    float
        Validated top_p

    Raises
    ------
    GeminiValidationError
        If value is invalid
    """

    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError(
            f"top_p must be numeric, got {type(value).__name__}."
        ) from exc

    if not MIN_TOP_P <= value <= MAX_TOP_P:
        raise GeminiValidationError(
            f"top_p must be between {MIN_TOP_P} and {MAX_TOP_P}, got {value}."
        )

    return value


def _validate_max_tokens(value: Any) -> int:
    """
    Validate max output tokens.

    Parameters
    ----------
    value : Any
        Value to validate

    Returns
    -------
    int
        Validated max_tokens

    Raises
    ------
    GeminiValidationError
        If value is invalid
    """

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError(
            f"max_tokens must be an integer, got {type(value).__name__}."
        ) from exc

    if not MIN_MAX_TOKENS <= value <= MAX_MAX_TOKENS:
        raise GeminiValidationError(
            f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}, "
            f"got {value}."
        )

    return value


def _validate_top_k(value: Any) -> int:
    """
    Validate top-k parameter (optional for Gemini).

    Parameters
    ----------
    value : Any
        Value to validate

    Returns
    -------
    int
        Validated top_k

    Raises
    ------
    GeminiValidationError
        If value is invalid
    """

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError(
            f"top_k must be an integer, got {type(value).__name__}."
        ) from exc

    if value < MIN_TOP_K:
        raise GeminiValidationError(
            f"top_k must be >= {MIN_TOP_K}, got {value}."
        )

    return value


def _validate_candidate_count(value: Any) -> int:
    """
    Validate candidate count parameter.

    Parameters
    ----------
    value : Any
        Value to validate

    Returns
    -------
    int
        Validated candidate_count

    Raises
    ------
    GeminiValidationError
        If value is invalid
    """

    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError(
            f"candidate_count must be an integer, got {type(value).__name__}."
        ) from exc

    if value < MIN_CANDIDATE_COUNT:
        raise GeminiValidationError(
            f"candidate_count must be >= {MIN_CANDIDATE_COUNT}, got {value}."
        )

    return value


def _validate_timeout(value: Any) -> float:
    """
    Validate request timeout.

    Parameters
    ----------
    value : Any
        Value to validate

    Returns
    -------
    float
        Validated timeout

    Raises
    ------
    GeminiValidationError
        If value is invalid
    """

    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise GeminiValidationError(
            f"timeout must be numeric, got {type(value).__name__}."
        ) from exc

    if timeout <= 0:
        raise GeminiValidationError(
            f"timeout must be > 0, got {timeout}."
        )

    return timeout


# ============================================================================
# SDK Management
# ============================================================================


def _load_sdk() -> Any:
    """
    Lazily import google-generativeai SDK.

    Returns
    -------
    module
        Imported genai module

    Raises
    ------
    GeminiConfigurationError
        If SDK is not installed
    """

    try:
        from google import genai  # type: ignore

        logger.debug("Loaded google-genai SDK.")

        return genai

    except ImportError as exc:
        logger.error(
            "google-genai SDK not found. "
            "Install with: pip install google-genai"
        )

        raise GeminiConfigurationError(
            "The 'google-genai' package is not installed. "
            "Install it with: pip install google-genai"
        ) from exc


def _load_types() -> Any:
    """Lazily import google.genai.types."""

    try:
        from google.genai import types  # type: ignore

        return types

    except ImportError as exc:
        raise GeminiConfigurationError(
            "The 'google-genai' package is not installed. "
            "Install it with: pip install google-genai"
        ) from exc


def _history_to_contents(history: list[dict[str, Any]]) -> list[Any]:
    """Convert internal history dicts to google-genai Content objects."""

    types = _load_types()

    return [
        types.Content(
            role=item["role"],
            parts=[types.Part(text=str(part)) for part in item["parts"]],
        )
        for item in history
    ]


def _sdk_installed() -> bool:
    """
    Check if google-generativeai SDK is installed.

    Returns
    -------
    bool
        True if SDK is available
    """

    try:
        from importlib.util import find_spec

        return find_spec("google.genai") is not None
    except (ImportError, ValueError):
        return False


def _api_key_configured() -> bool:
    """
    Check if GEMINI_API_KEY is configured.

    Returns
    -------
    bool
        True if API key is present and non-empty
    """

    key = getattr(secrets, "gemini_api_key", None)

    is_configured = bool(key and str(key).strip())

    if not is_configured:
        logger.debug("GEMINI_API_KEY not configured.")

    return is_configured


# ============================================================================
# Message Conversion
# ============================================================================


def _messages_to_gemini_format(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    """
    Convert AssistantX ChatMessage objects to Gemini API format.

    Gemini uses:
    - system_instruction (at model level, not in history)
    - conversation history with 'user' and 'model' roles

    Parameters
    ----------
    messages : list[ChatMessage]
        Messages in AssistantX format

    Returns
    -------
    tuple[str or None, list[dict]]
        (system_instruction, conversation_history)

    Raises
    ------
    GeminiValidationError
        If messages are invalid
    """

    system_instruction: str | None = None
    history: list[dict[str, Any]] = []

    for idx, message in enumerate(messages):
        if not isinstance(message, ChatMessage):
            raise GeminiValidationError(
                f"Message {idx} is not a ChatMessage instance, "
                f"got {type(message).__name__}."
            )

        content = message.content.strip()

        if not content:
            logger.debug(
                "Skipping empty message at index %d.",
                idx,
            )

            continue

        # System messages go to system_instruction
        if message.role == Role.SYSTEM:
            if system_instruction is None:
                system_instruction = content
            else:
                # Combine multiple system messages
                system_instruction = f"{system_instruction}\n{content}"

            logger.debug(
                "Added system message (total length: %d).",
                len(system_instruction),
            )

            continue

        # Convert role to Gemini format
        if message.role == Role.ASSISTANT:
            gemini_role = "model"
        elif message.role == Role.USER:
            gemini_role = "user"
        else:
            raise GeminiValidationError(
                f"Unsupported message role: {message.role!r} (at index {idx})."
            )

        history.append(
            {
                "role": gemini_role,
                "parts": [content],
            }
        )

    logger.info(
        "Converted messages to Gemini format: "
        "%d history items, system_instruction=%s",
        len(history),
        "present" if system_instruction else "absent",
    )

    return system_instruction, history


# ============================================================================
# Response Extraction
# ============================================================================


def _extract_finish_reason(response: Any) -> str | None:
    """
    Extract finish_reason from Gemini response.

    Parameters
    ----------
    response : Any
        Gemini response object

    Returns
    -------
    str or None
        Finish reason or None if not available
    """

    try:
        candidates = getattr(response, "candidates", None)

        if not candidates:
            return None

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)

        if finish_reason is None:
            return None

        reason_str = str(finish_reason)

        logger.debug("Gemini finish_reason: %s", reason_str)

        return reason_str

    except (AttributeError, IndexError, TypeError) as exc:
        logger.debug("Could not extract finish_reason: %s", exc)

        return None


def _extract_token_count(response: Any) -> int | None:
    """
    Extract token count from Gemini response.

    Parameters
    ----------
    response : Any
        Gemini response object

    Returns
    -------
    int or None
        Total token count or None if not available
    """

    try:
        metadata = getattr(response, "usage_metadata", None)

        if metadata is None:
            return None

        value = getattr(metadata, "total_token_count", None)

        if value is None:
            return None

        count = int(value)

        logger.debug("Gemini token count: %d", count)

        return count

    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Could not extract token count: %s", exc)

        return None


def _extract_response_text(response: Any) -> str:
    """
    Safely extract response text from Gemini response object.

    Parameters
    ----------
    response : Any
        Gemini response object

    Returns
    -------
    str
        Extracted text or empty string if unavailable
    """

    try:
        if (text := getattr(response, "text", None)) and (
            extracted := str(text).strip()
        ):
            return extracted

    except Exception as exc:
        logger.debug("Error extracting response text: %s", exc)

    logger.warning("Gemini returned empty response text.")

    return ""


# ============================================================================
# Gemini Provider Implementation
# ============================================================================


class GeminiProvider(AIProviderBase):
    """
    Google Gemini AI provider with streaming and system instruction support.

    Gemini is optional. If SDK or API key is unavailable, is_available()
    returns False, allowing fallback to other providers.

    Attributes
    ----------
    name : str
        Provider name (always "gemini")
    model : str
        Gemini model ID
    temperature : float
        Generation temperature
    timeout : float
        Request timeout in seconds
    """

    name = PROVIDER_NAME
    default_model = DEFAULT_GEMINI_MODEL

    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initialize Gemini provider.

        Parameters
        ----------
        model : str or None
            Model ID (default: configured default)
        temperature : float
            Generation temperature (0.0-1.0, default: from config)
        timeout : float
            Request timeout in seconds (default: from config)
        """

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

        logger.info(
            "Initialized GeminiProvider: model=%r, timeout=%.1f",
            self.model,
            self.timeout,
        )

    # ------------------------------------------------------------------
    # SDK and Client Management
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        """
        Lazily load and configure the Gemini SDK.

        Returns
        -------
        object
            Configured Gemini GenerativeModel instance

        Raises
        ------
        GeminiConfigurationError
            If SDK or API key configuration fails
        """

        if self._model_instance is not None:
            logger.debug("Reusing existing Gemini model instance.")

            return self._model_instance

        if not _api_key_configured():
            raise GeminiConfigurationError(
                "GEMINI_API_KEY is not configured. "
                "Add your Gemini API key to the .env file or set the environment variable."
            )

        logger.info("Loading Gemini SDK...")

        genai = _load_sdk()

        self._client_module = genai

        # Create the google-genai client (this SDK has no global configure()).
        try:
            logger.info("Initializing Gemini client for model: %s", self.model)

            self._model_instance = genai.Client(
                api_key=str(secrets.gemini_api_key).strip(),
            )
            self._configured = True

            logger.info("Successfully initialized Gemini client.")

        except Exception as exc:
            logger.exception(
                "Failed to initialize Gemini model '%s': %s",
                self.model,
                exc,
            )

            raise GeminiConfigurationError(
                f"Failed to initialize Gemini model '{self.model}': {exc}"
            ) from exc

        return self._model_instance

    def _create_model(
        self,
        system_instruction: str | None = None,
    ) -> Any:
        """
        Create Gemini GenerativeModel with optional system instruction.

        In Gemini, system instructions are attached at model creation time,
        not in the conversation history.

        Parameters
        ----------
        system_instruction : str or None
            System prompt text

        Returns
        -------
        object
            Configured GenerativeModel

        Raises
        ------
        GeminiConfigurationError
            If model creation fails
        """

        # google-genai: the system instruction is sent with each request
        # (see _build_request_config), so we just return the shared client.
        return self._ensure_client()

    def _build_request_config(
        self,
        system_instruction: str | None,
        generation_config: dict[str, Any],
        timeout: float,
    ) -> Any:
        """Build a google-genai GenerateContentConfig."""

        types = _load_types()

        config: dict[str, Any] = dict(generation_config)

        if system_instruction:
            config["system_instruction"] = system_instruction

        config["http_options"] = types.HttpOptions(
            timeout=int(timeout * 1000),
        )

        return types.GenerateContentConfig(**config)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Check if Gemini can be used right now.

        Returns True when:
        - SDK is installed
        - API key is configured

        Returns
        -------
        bool
            True if provider is available
        """

        available = _sdk_installed() and _api_key_configured()

        if available:
            logger.debug("Gemini provider is available.")
        else:
            logger.debug(
                "Gemini provider is unavailable: sdk=%s, api_key=%s",
                _sdk_installed(),
                _api_key_configured(),
            )

        return available

    def health_check(self) -> bool:
        """
        Lightweight health check (configuration only).

        Does not make a billable API call.

        Returns
        -------
        bool
            True if provider is configured correctly
        """

        return self.is_available()

    # ------------------------------------------------------------------
    # Generation Configuration
    # ------------------------------------------------------------------

    def _build_generation_config(self, **kwargs) -> dict[str, Any]:
        """
        Build Gemini generation configuration.

        Parameters
        ----------
        **kwargs
            temperature, max_tokens, top_p, top_k, candidate_count

        Returns
        -------
        dict
            Gemini generation_config dict

        Raises
        ------
        GeminiValidationError
            If parameters are invalid
        """

        temperature = kwargs.get("temperature", self.temperature)

        max_tokens = kwargs.get("max_tokens", DEFAULT_MAX_TOKENS)
        max_tokens = _validate_max_tokens(max_tokens)

        top_p = kwargs.get("top_p", DEFAULT_TOP_P)
        top_p = _validate_top_p(top_p)

        config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "top_p": top_p,
        }

        # Optional Gemini-specific parameters
        if "top_k" in kwargs and kwargs["top_k"] is not None:
            top_k = _validate_top_k(kwargs["top_k"])
            config["top_k"] = top_k

            logger.debug("Added top_k=%d to generation config.", top_k)

        if "candidate_count" in kwargs and kwargs["candidate_count"] is not None:
            candidate_count = _validate_candidate_count(kwargs["candidate_count"])
            config["candidate_count"] = candidate_count

            logger.debug(
                "Added candidate_count=%d to generation config.",
                candidate_count,
            )

        logger.debug(
            "Built generation config: temp=%.1f, max_tokens=%d, top_p=%.2f",
            temperature,
            max_tokens,
            top_p,
        )

        return config

    # ------------------------------------------------------------------
    # API Calls
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[ChatMessage],
        **kwargs,
    ) -> CompletionResult:
        """
        Generate a completion from Gemini.

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs
            temperature, max_tokens, top_p, timeout, etc.

        Returns
        -------
        CompletionResult
            Generated response

        Raises
        ------
        GeminiValidationError
            If messages are invalid
        GeminiTimeoutError
            If request times out
        ProviderRequestError
            If API call fails
        """

        if not messages:
            raise GeminiValidationError(
                "At least one message is required."
            )

        logger.info(
            "Generating Gemini completion: %d message(s)",
            len(messages),
        )

        system_instruction, history = _messages_to_gemini_format(messages)

        if not history:
            raise GeminiValidationError(
                "No user/assistant messages provided to Gemini "
                "(all messages were system messages)."
            )

        # Gemini requires the last message to be from user
        latest_turn = history[-1]

        if latest_turn["role"] != "user":
            raise GeminiValidationError(
                f"Last message to Gemini must be from user, got '{latest_turn['role']}'."
            )

        client = self._create_model(system_instruction)

        generation_config = self._build_generation_config(**kwargs)

        timeout = _validate_timeout(kwargs.get("timeout", self.timeout))

        config = self._build_request_config(
            system_instruction,
            generation_config,
            timeout,
        )

        contents = _history_to_contents(history)

        start = time.monotonic()

        try:
            logger.debug(
                "Sending request to Gemini (timeout=%.1f)...",
                timeout,
            )

            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

        except TimeoutError as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini request timed out after %.2f seconds.",
                elapsed,
            )

            raise GeminiTimeoutError(
                f"Gemini request timed out after {timeout:.1f} seconds."
            ) from exc

        except Exception as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini API call failed after %.2f seconds: %s: %s",
                elapsed,
                type(exc).__name__,
                exc,
            )

            raise ProviderRequestError(
                f"Gemini API request failed: {exc}"
            ) from exc

        elapsed = time.monotonic() - start

        text = _extract_response_text(response)

        if not text:
            logger.warning(
                "Gemini returned empty response (finish_reason=%s).",
                _extract_finish_reason(response),
            )

        logger.info(
            "Gemini generation complete: %.2f seconds, %d chars",
            elapsed,
            len(text),
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

        Yields text chunks as they arrive from the API.

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs
            temperature, max_tokens, top_p, timeout, etc.

        Yields
        ------
        str
            Response chunks

        Raises
        ------
        GeminiValidationError
            If messages are invalid
        GeminiTimeoutError
            If streaming times out
        GeminiStreamingError
            If streaming fails
        """

        if not messages:
            raise GeminiValidationError(
                "At least one message is required."
            )

        logger.info(
            "Starting Gemini streaming: %d message(s)",
            len(messages),
        )

        system_instruction, history = _messages_to_gemini_format(messages)

        if not history:
            raise GeminiValidationError(
                "No user/assistant messages provided to Gemini."
            )

        latest_turn = history[-1]

        if latest_turn["role"] != "user":
            raise GeminiValidationError(
                f"Last message must be from user, got '{latest_turn['role']}'."
            )

        client = self._create_model(system_instruction)

        generation_config = self._build_generation_config(**kwargs)

        timeout = _validate_timeout(kwargs.get("timeout", self.timeout))

        config = self._build_request_config(
            system_instruction,
            generation_config,
            timeout,
        )

        contents = _history_to_contents(history)

        start = time.monotonic()
        chunk_count = 0

        try:
            logger.debug("Requesting stream from Gemini (timeout=%.1f)...", timeout)

            response_stream = client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            )

            for chunk in response_stream:
                # Keep raw chunk text: stripping here would remove the
                # spaces between chunks ("আমি " + "জেরক্স" -> "আমিজেরক্স").
                text = getattr(chunk, "text", None) or ""

                if text:
                    chunk_count += 1

                    yield text

            elapsed = time.monotonic() - start

            logger.info(
                "Gemini streaming complete: %.2f seconds, %d chunk(s)",
                elapsed,
                chunk_count,
            )

        except TimeoutError as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini streaming timed out after %.2f seconds (%d chunk(s)).",
                elapsed,
                chunk_count,
            )

            raise GeminiTimeoutError(
                f"Gemini streaming timed out after {timeout:.1f} seconds."
            ) from exc

        except Exception as exc:
            elapsed = time.monotonic() - start

            logger.error(
                "Gemini streaming failed after %.2f seconds (%d chunk(s)): %s: %s",
                elapsed,
                chunk_count,
                type(exc).__name__,
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
        Get provider diagnostic information (no API call).

        Returns
        -------
        GeminiServerInfo
            Provider status and configuration info
        """

        info = GeminiServerInfo(
            provider=self.name,
            model=self.model,
            sdk_installed=_sdk_installed(),
            api_key_configured=_api_key_configured(),
            available=self.is_available(),
        )

        logger.debug(
            "Gemini server info: available=%s, sdk=%s, key=%s",
            info.available,
            info.sdk_installed,
            info.api_key_configured,
        )

        return info

    def diagnostics(self) -> dict[str, Any]:
        """
        Get comprehensive provider diagnostics.

        Returns
        -------
        dict
            JSON-friendly diagnostics
        """

        info = self.get_server_info()

        diags = {
            "provider": info.provider,
            "model": info.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "sdk_installed": info.sdk_installed,
            "api_key_configured": info.api_key_configured,
            "available": info.available,
            "configured": self._configured,
        }

        logger.debug("Gemini diagnostics: %s", diags)

        return diags

    def __repr__(self) -> str:
        return (
            f"GeminiProvider("
            f"model={self.model!r}, "
            f"available={self.is_available()}"
            ")"
        )


# ============================================================================
# Module-Level Helpers
# ============================================================================


def gemini_available() -> bool:
    """
    Check if Gemini provider is currently available.

    Returns
    -------
    bool
        True if SDK is installed and API key is configured
    """

    available = _sdk_installed() and _api_key_configured()

    logger.debug("Gemini availability: %s", available)

    return available


def create_gemini_provider(
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> GeminiProvider:
    """
    Factory function to create a configured Gemini provider.

    Parameters
    ----------
    model : str or None
        Model ID (default: configured default)
    temperature : float
        Generation temperature
    timeout : float
        Request timeout

    Returns
    -------
    GeminiProvider
        Configured provider instance
    """

    return GeminiProvider(
        model=model,
        temperature=temperature,
        timeout=timeout,
    )


def gemini_diagnostics() -> dict[str, Any]:
    """
    Get Gemini provider diagnostics without requiring instantiation.

    Returns
    -------
    dict
        Provider diagnostics
    """

    provider = GeminiProvider()

    return provider.diagnostics()


def get_gemini_model() -> str:
    """
    Get the configured/default Gemini model name.

    Returns
    -------
    str
        Model name/ID
    """

    return _validate_model(DEFAULT_GEMINI_MODEL)


# ============================================================================
# Backward-Compatible Aliases
# ============================================================================

is_gemini_available = gemini_available


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Provider class
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

    # Helper functions
    "gemini_available",
    "is_gemini_available",  # Alias
    "create_gemini_provider",
    "gemini_diagnostics",
    "get_gemini_model",

    # Conversion helpers (internal but needed)
    "_messages_to_gemini_format",
]
