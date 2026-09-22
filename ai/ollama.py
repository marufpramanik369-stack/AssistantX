"""
ai/ollama.py
============
Ollama AI provider for AssistantX.

This module communicates directly with a locally running Ollama server
through its REST API. No Ollama Python SDK is required.

Features
--------
- Local/private AI inference
- /api/chat completion
- True NDJSON streaming
- Ollama health checking
- Installed model discovery
- Model pulling
- Configurable generation parameters
- Robust timeout/error handling
- ProviderBase compatibility
- Safe helper functions
- Diagnostics

Architecture
------------
    core/assistant.py
            │
            ▼
        AIProviderBase
            │
            ▼
      OllamaProvider
            │
            ▼
       Ollama REST API

Typical server:
    http://127.0.0.1:11434

Start Ollama:
    ollama serve
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests

from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    ProviderError,
    ProviderRequestError,
    ProviderValidationError,
    normalize_messages,
    validate_temperature,
)
from config.constants import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_TEMPERATURE,
    REQUEST_TIMEOUT_SECONDS,
)
from config.secrets import secrets

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

PROVIDER_NAME = "ollama"

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"

DEFAULT_TOP_P = 0.9
DEFAULT_TOP_K = 40
DEFAULT_REPEAT_PENALTY = 1.1

DEFAULT_KEEP_ALIVE = "5m"

HEALTH_TIMEOUT_SECONDS = 2.0
MODEL_LIST_TIMEOUT_SECONDS = 5.0

MIN_TIMEOUT_SECONDS = 0.1
MAX_TIMEOUT_SECONDS = 600.0

MAX_MODEL_NAME_LENGTH = 200
MAX_HOST_LENGTH = 500

OLLAMA_CHAT_ENDPOINT = "/api/chat"
OLLAMA_TAGS_ENDPOINT = "/api/tags"
OLLAMA_PULL_ENDPOINT = "/api/pull"
OLLAMA_VERSION_ENDPOINT = "/api/version"


# ============================================================================
# Exceptions
# ============================================================================


class OllamaError(ProviderError):
    """Base exception for Ollama-specific errors."""


class OllamaValidationError(
    OllamaError,
    ProviderValidationError,
):
    """Invalid Ollama configuration or request."""


class OllamaConnectionError(
    OllamaError,
    ProviderRequestError,
):
    """Unable to connect to the Ollama server."""


class OllamaTimeoutError(
    OllamaError,
    ProviderRequestError,
):
    """Ollama request timed out."""


class OllamaHTTPError(
    OllamaError,
    ProviderRequestError,
):
    """Ollama returned an HTTP error response."""


class OllamaResponseError(
    OllamaError,
    ProviderRequestError,
):
    """Ollama returned an invalid or unexpected response."""


class OllamaModelError(
    OllamaError,
    ProviderRequestError,
):
    """Requested Ollama model is unavailable."""


# ============================================================================
# Data Structures
# ============================================================================


@dataclass(frozen=True, slots=True)
class OllamaModel:
    """Information about an installed Ollama model."""

    name: str
    size_bytes: int | None = None
    digest: str | None = None
    modified_at: str | None = None

    @property
    def size_gb(self) -> float | None:
        """Return model size in GB."""
        if self.size_bytes is None:
            return None

        return self.size_bytes / (1024**3)


@dataclass(frozen=True, slots=True)
class OllamaServerInfo:
    """Basic information about the Ollama server."""

    host: str
    available: bool
    version: str | None = None
    latency_seconds: float | None = None


# ============================================================================
# Validation Helpers
# ============================================================================


def _validate_host(host: str) -> str:
    """Validate and normalize Ollama server URL."""
    if not isinstance(host, str):
        raise OllamaValidationError(
            "Ollama host must be a string."
        )

    value = host.strip().rstrip("/")

    if not value:
        raise OllamaValidationError(
            "Ollama host cannot be empty."
        )

    if len(value) > MAX_HOST_LENGTH:
        raise OllamaValidationError(
            "Ollama host is too long."
        )

    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"

    return value


def _validate_model_name(model: str) -> str:
    """Validate Ollama model name."""
    if not isinstance(model, str):
        raise OllamaValidationError(
            "Ollama model name must be a string."
        )

    value = model.strip()

    if not value:
        raise OllamaValidationError(
            "Ollama model name cannot be empty."
        )

    if len(value) > MAX_MODEL_NAME_LENGTH:
        raise OllamaValidationError(
            "Ollama model name is too long."
        )

    if any(char in value for char in ("\n", "\r", "\t")):
        raise OllamaValidationError(
            "Ollama model name contains invalid whitespace."
        )

    return value


def _validate_timeout(timeout: float) -> float:
    """Validate request timeout."""
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid timeout: {timeout!r}"
        ) from exc

    if not MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS:
        raise OllamaValidationError(
            f"Timeout must be between "
            f"{MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS} seconds."
        )

    return value


def _validate_probability(value: float, name: str) -> float:
    """Validate probability-like Ollama option."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid {name}: {value!r}"
        ) from exc

    if not 0.0 <= number <= 1.0:
        raise OllamaValidationError(
            f"{name} must be between 0.0 and 1.0."
        )

    return number


def _validate_positive_number(value: float, name: str) -> float:
    """Validate a positive numeric option."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid {name}: {value!r}"
        ) from exc

    if not math.isfinite(number) or number <= 0:
        raise OllamaValidationError(
            f"{name} must be a positive finite number."
        )

    return number


# ============================================================================
# Message Conversion
# ============================================================================


def _messages_to_ollama_format(
    messages: list[ChatMessage],
) -> list[dict[str, str]]:
    """
    Convert AssistantX ChatMessages into Ollama's chat format.
    """
    return [
        {
            "role": message.role.value,
            "content": message.content,
        }
        for message in messages
    ]


# ============================================================================
# Ollama Provider
# ============================================================================


class OllamaProvider(AIProviderBase):
    """
    AssistantX provider backed by a local Ollama server.

    Example
    -------
        provider = OllamaProvider(
            model="llama3.2"
        )

        result = provider.generate(
            [
                ChatMessage(
                    Role.USER,
                    "Hello"
                )
            ]
        )

        print(result.text)
    """

    name = PROVIDER_NAME
    default_model = DEFAULT_OLLAMA_MODEL

    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        host: str | None = None,
    ) -> None:
        """
        Initialize Ollama provider.
        """
        super().__init__(
            model=model,
            temperature=temperature,
            timeout=timeout,
        )

        configured_host = (
            host
            or getattr(secrets, "ollama_host", None)
            or DEFAULT_OLLAMA_HOST
        )

        self.host = _validate_host(configured_host)

        logger.debug(
            "OllamaProvider initialized: host=%s model=%s",
            self.host,
            self.model,
        )

    # ------------------------------------------------------------------
    # URLs
    # ------------------------------------------------------------------

    def _chat_url(self) -> str:
        """Return Ollama chat endpoint."""
        return f"{self.host}{OLLAMA_CHAT_ENDPOINT}"

    def _tags_url(self) -> str:
        """Return Ollama model-tags endpoint."""
        return f"{self.host}{OLLAMA_TAGS_ENDPOINT}"

    def _pull_url(self) -> str:
        """Return Ollama model-pull endpoint."""
        return f"{self.host}{OLLAMA_PULL_ENDPOINT}"

    def _version_url(self) -> str:
        """Return Ollama version endpoint."""
        return f"{self.host}{OLLAMA_VERSION_ENDPOINT}"

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Check whether Ollama server is reachable.

        This method is intentionally lightweight and never raises.
        """
        try:
            response = requests.get(
                self._tags_url(),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )

            return response.status_code == 200

        except requests.RequestException:
            return False

    def health_check(self) -> bool:
        """Explicit health check alias."""
        return self.is_available()

    # ------------------------------------------------------------------
    # Server Info
    # ------------------------------------------------------------------

    def get_server_info(self) -> OllamaServerInfo:
        """
        Retrieve Ollama server availability and version.
        """
        start = time.monotonic()

        try:
            response = requests.get(
                self._version_url(),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            data = response.json()

            return OllamaServerInfo(
                host=self.host,
                available=True,
                version=data.get("version"),
                latency_seconds=time.monotonic() - start,
            )

        except requests.RequestException as exc:
            logger.debug(
                "Ollama server info request failed: %s",
                exc,
            )

            return OllamaServerInfo(
                host=self.host,
                available=False,
                latency_seconds=time.monotonic() - start,
            )

        except (ValueError, TypeError) as exc:
            logger.debug(
                "Invalid Ollama version response: %s",
                exc,
            )

            return OllamaServerInfo(
                host=self.host,
                available=False,
                latency_seconds=time.monotonic() - start,
            )

    # ------------------------------------------------------------------
    # Model Management
    # ------------------------------------------------------------------

    def list_installed_models(
        self,
    ) -> list[str]:
        """
        Return names of models currently installed in Ollama.
        """
        try:
            response = requests.get(
                self._tags_url(),
                timeout=MODEL_LIST_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            data = response.json()

            models = data.get("models", [])

            if not isinstance(models, list):
                return []

            result: list[str] = []

            for item in models:
                if not isinstance(item, dict):
                    continue

                name = item.get("name")

                if isinstance(name, str) and name.strip():
                    result.append(name.strip())

            return result

        except requests.RequestException as exc:
            logger.warning(
                "Could not list Ollama models: %s",
                exc,
            )
            return []

        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid Ollama model list response: %s",
                exc,
            )
            return []

    def list_models(self) -> list[OllamaModel]:
        """
        Return detailed information about installed models.
        """
        try:
            response = requests.get(
                self._tags_url(),
                timeout=MODEL_LIST_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            data = response.json()

            models = data.get("models", [])

            if not isinstance(models, list):
                return []

            result: list[OllamaModel] = []

            for item in models:
                if not isinstance(item, dict):
                    continue

                name = item.get("name")

                if not isinstance(name, str) or not name.strip():
                    continue

                result.append(
                    OllamaModel(
                        name=name.strip(),
                        size_bytes=item.get("size"),
                        digest=item.get("digest"),
                        modified_at=item.get("modified_at"),
                    )
                )

            return result

        except requests.RequestException as exc:
            logger.warning(
                "Failed to retrieve detailed Ollama models: %s",
                exc,
            )
            return []

        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid Ollama model metadata: %s",
                exc,
            )
            return []

    def model_installed(
        self,
        model_name: str | None = None,
    ) -> bool:
        """
        Check whether a model is installed locally.
        """
        target = _validate_model_name(
            model_name or self.model
        )

        installed = self.list_installed_models()

        return target in installed

    def pull_model(
        self,
        model_name: str | None = None,
        *,
        timeout: float | None = None,
    ) -> bool:
        """
        Pull an Ollama model through the REST API.

        The method blocks until the pull finishes.
        """
        target = _validate_model_name(
            model_name or self.model
        )

        request_timeout = (
            None
            if timeout is None
            else _validate_timeout(timeout)
        )

        logger.info(
            "Pulling Ollama model '%s'...",
            target,
        )

        try:
            with requests.post(
                self._pull_url(),
                json={
                    "name": target,
                    "stream": True,
                },
                stream=True,
                timeout=request_timeout,
            ) as response:

                response.raise_for_status()

                for line in response.iter_lines(
                    decode_unicode=True
                ):
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Ignoring invalid Ollama pull chunk."
                        )
                        continue

                    status = data.get("status")

                    if status:
                        logger.info(
                            "[ollama pull:%s] %s",
                            target,
                            status,
                        )

                    if data.get("error"):
                        logger.error(
                            "Ollama pull error: %s",
                            data["error"],
                        )
                        return False

            logger.info(
                "Ollama model '%s' pulled successfully.",
                target,
            )

            return True

        except requests.ConnectionError as exc:
            logger.error(
                "Could not connect to Ollama while pulling '%s': %s",
                target,
                exc,
            )
            return False

        except requests.Timeout as exc:
            logger.error(
                "Ollama model pull timed out for '%s': %s",
                target,
                exc,
            )
            return False

        except requests.HTTPError as exc:
            logger.error(
                "Ollama returned HTTP error while pulling '%s': %s",
                target,
                exc,
            )
            return False

        except requests.RequestException as exc:
            logger.error(
                "Failed to pull Ollama model '%s': %s",
                target,
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Generation Options
    # ------------------------------------------------------------------

    def _build_options(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Build Ollama generation options.

        Supported options:
            temperature
            top_p
            top_k
            repeat_penalty
            num_ctx
            num_predict
            seed
        """
        temperature = validate_temperature(
            kwargs.get(
                "temperature",
                self.temperature,
            )
        )

        top_p = _validate_probability(
            kwargs.get("top_p", DEFAULT_TOP_P),
            "top_p",
        )

        try:
            top_k = int(
                kwargs.get(
                    "top_k",
                    DEFAULT_TOP_K,
                )
            )
        except (TypeError, ValueError) as exc:
            raise OllamaValidationError(
                "top_k must be an integer."
            ) from exc

        if top_k < 0:
            raise OllamaValidationError(
                "top_k cannot be negative."
            )

        try:
            repeat_penalty = float(
                kwargs.get(
                    "repeat_penalty",
                    DEFAULT_REPEAT_PENALTY,
                )
            )
        except (TypeError, ValueError) as exc:
            raise OllamaValidationError(
                "repeat_penalty must be numeric."
            ) from exc

        if repeat_penalty <= 0:
            raise OllamaValidationError(
                "repeat_penalty must be greater than zero."
            )

        options: dict[str, Any] = {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repeat_penalty": repeat_penalty,
        }

        optional_integer_options = (
            "num_ctx",
            "num_predict",
            "seed",
        )

        for key in optional_integer_options:
            if key not in kwargs:
                continue

            try:
                value = int(kwargs[key])
            except (TypeError, ValueError) as exc:
                raise OllamaValidationError(
                    f"{key} must be an integer."
                ) from exc

            if key != "seed" and value <= 0:
                raise OllamaValidationError(
                    f"{key} must be greater than zero."
                )

            options[key] = value

        return options

    # ------------------------------------------------------------------
    # API Request
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Perform a synchronous /api/chat request.
        """
        normalized_messages = normalize_messages(messages)

        target_model = _validate_model_name(
            kwargs.get("model", self.model)
        )

        timeout = _validate_timeout(
            kwargs.get("timeout", self.timeout)
        )

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": _messages_to_ollama_format(
                normalized_messages
            ),
            "stream": False,
            "options": self._build_options(**kwargs),
        }

        if "keep_alive" in kwargs:
            payload["keep_alive"] = kwargs["keep_alive"]

        start = time.monotonic()

        try:
            response = requests.post(
                self._chat_url(),
                json=payload,
                timeout=timeout,
            )

            response.raise_for_status()

        except requests.ConnectionError as exc:
            raise OllamaConnectionError(
                f"Could not reach Ollama server at {self.host}. "
                f"Make sure Ollama is running "
                f"(for example: 'ollama serve')."
            ) from exc

        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                f"Ollama request timed out after "
                f"{timeout:.1f} seconds."
            ) from exc

        except requests.HTTPError as exc:
            detail = self._extract_http_error(response)

            raise OllamaHTTPError(
                f"Ollama returned HTTP {response.status_code}: "
                f"{detail}"
            ) from exc

        except requests.RequestException as exc:
            raise OllamaConnectionError(
                f"Ollama request failed: {exc}"
            ) from exc

        elapsed = time.monotonic() - start

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaResponseError(
                "Ollama returned invalid JSON."
            ) from exc

        if not isinstance(data, dict):
            raise OllamaResponseError(
                "Ollama response must be a JSON object."
            )

        if data.get("error"):
            raise OllamaModelError(
                str(data["error"])
            )

        message = data.get("message")

        if not isinstance(message, dict):
            raise OllamaResponseError(
                "Ollama response does not contain a valid message."
            )

        text = message.get("content", "")

        if not isinstance(text, str):
            text = str(text)

        text = text.strip()

        tokens_used = self._calculate_tokens_used(data)

        return CompletionResult(
            text=text,
            provider=self.name,
            model=target_model,
            latency_seconds=elapsed,
            tokens_used=tokens_used,
            prompt_tokens=self._safe_int(
                data.get("prompt_eval_count")
            ),
            completion_tokens=self._safe_int(
                data.get("eval_count")
            ),
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> Iterator[str]:
        """
        Stream response chunks from Ollama.

        Ollama returns newline-delimited JSON (NDJSON).
        """
        normalized_messages = normalize_messages(messages)

        target_model = _validate_model_name(
            kwargs.get("model", self.model)
        )

        timeout = _validate_timeout(
            kwargs.get("timeout", self.timeout)
        )

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": _messages_to_ollama_format(
                normalized_messages
            ),
            "stream": True,
            "options": self._build_options(**kwargs),
        }

        if "keep_alive" in kwargs:
            payload["keep_alive"] = kwargs["keep_alive"]

        logger.debug(
            "Starting Ollama streaming request: model=%s",
            target_model,
        )

        try:
            with requests.post(
                self._chat_url(),
                json=payload,
                stream=True,
                timeout=timeout,
            ) as response:

                try:
                    response.raise_for_status()
                except requests.HTTPError as exc:
                    detail = self._extract_http_error(response)

                    raise OllamaHTTPError(
                        f"Ollama returned HTTP "
                        f"{response.status_code}: {detail}"
                    ) from exc

                for line in response.iter_lines(
                    decode_unicode=True
                ):
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Ignoring invalid Ollama stream chunk."
                        )
                        continue

                    if not isinstance(chunk, dict):
                        continue

                    if chunk.get("error"):
                        raise OllamaResponseError(
                            str(chunk["error"])
                        )

                    message = chunk.get(
                        "message",
                        {},
                    )

                    if not isinstance(message, dict):
                        continue

                    content = message.get(
                        "content",
                        "",
                    )

                    if content:
                        yield str(content)

                    if chunk.get("done"):
                        break

        except requests.ConnectionError as exc:
            raise OllamaConnectionError(
                f"Lost connection to Ollama server at {self.host}."
            ) from exc

        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                f"Ollama streaming request timed out after "
                f"{timeout:.1f} seconds."
            ) from exc

        except requests.RequestException as exc:
            raise OllamaConnectionError(
                f"Ollama streaming request failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        """Safely convert a value to int."""
        try:
            if value is None:
                return None

            return int(value)

        except (TypeError, ValueError):
            return None

    @classmethod
    def _calculate_tokens_used(
        cls,
        data: dict[str, Any],
    ) -> int | None:
        """Calculate total token usage from Ollama response."""
        prompt_tokens = cls._safe_int(
            data.get("prompt_eval_count")
        )

        completion_tokens = cls._safe_int(
            data.get("eval_count")
        )

        if (
            prompt_tokens is not None
            and completion_tokens is not None
        ):
            return prompt_tokens + completion_tokens

        return None

    @staticmethod
    def _extract_http_error(
        response: requests.Response,
    ) -> str:
        """Extract a useful error message from an HTTP response."""
        try:
            data = response.json()

            if isinstance(data, dict):
                error = data.get("error")

                if error:
                    return str(error)

        except (ValueError, TypeError):
            pass

        try:
            text = response.text.strip()

            if text:
                return text[:500]

        except Exception:
            pass

        return response.reason or "Unknown HTTP error"

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return diagnostic information for debugging.
        """
        server = self.get_server_info()

        return {
            "provider": self.name,
            "host": self.host,
            "model": self.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "available": server.available,
            "server_version": server.version,
            "latency_seconds": server.latency_seconds,
            "installed_models": (
                self.list_installed_models()
                if server.available
                else []
            ),
        }


# ============================================================================
# Module-Level Helpers
# ============================================================================


def ollama_available(
    host: str | None = None,
) -> bool:
    """
    Quickly check whether Ollama is available.
    """
    try:
        provider = OllamaProvider(
            host=host,
        )

        return provider.is_available()

    except Exception as exc:
        logger.debug(
            "Ollama availability check failed: %s",
            exc,
        )
        return False


def get_ollama_models(
    host: str | None = None,
) -> list[str]:
    """
    Return installed Ollama model names.
    """
    try:
        provider = OllamaProvider(
            host=host,
        )

        return provider.list_installed_models()

    except Exception as exc:
        logger.warning(
            "Could not retrieve Ollama models: %s",
            exc,
        )
        return []


def pull_ollama_model(
    model_name: str,
    *,
    host: str | None = None,
    timeout: float | None = None,
) -> bool:
    """
    Convenience wrapper for pulling an Ollama model.
    """
    try:
        provider = OllamaProvider(
            host=host,
        )

        return provider.pull_model(
            model_name,
            timeout=timeout,
        )

    except Exception as exc:
        logger.error(
            "Ollama model pull failed: %s",
            exc,
        )
        return False


def ollama_diagnostics(
    host: str | None = None,
) -> dict[str, Any]:
    """
    Return Ollama diagnostic information.
    """
    try:
        provider = OllamaProvider(
            host=host,
        )

        return provider.diagnostics()

    except Exception as exc:
        logger.error(
            "Ollama diagnostics failed: %s",
            exc,
        )

        return {
            "provider": PROVIDER_NAME,
            "available": False,
            "error": str(exc),
        }


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Constants
    "PROVIDER_NAME",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_TOP_P",
    "DEFAULT_TOP_K",
    "DEFAULT_REPEAT_PENALTY",
    "DEFAULT_KEEP_ALIVE",
    "HEALTH_TIMEOUT_SECONDS",
    "MODEL_LIST_TIMEOUT_SECONDS",

    # Exceptions
    "OllamaError",
    "OllamaValidationError",
    "OllamaConnectionError",
    "OllamaTimeoutError",
    "OllamaHTTPError",
    "OllamaResponseError",
    "OllamaModelError",

    # Data classes
    "OllamaModel",
    "OllamaServerInfo",

    # Provider
    "OllamaProvider",

    # Helpers
    "ollama_available",
    "get_ollama_models",
    "pull_ollama_model",
    "ollama_diagnostics",
]
