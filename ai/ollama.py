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

Thread Safety
-------------
This module is thread-safe. The OllamaProvider can be safely used from
multiple threads. The requests library handles connection pooling
and thread-safe HTTP communication.

Logging
-------
Debug logging includes:
- Provider initialization and configuration
- Validation steps with constraints
- Model operations (list, pull, check, install)
- API request/response details
- Stream chunk tracking and completion
- Server connectivity checks

Info logging includes:
- Successful model pulls with progress
- Server availability status
- Important generation operations

Error logging includes:
- Connection failures with host information
- Timeout errors with duration
- HTTP errors with status codes and details
- Response parsing errors with recovery hints
"""


from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional


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
    size_bytes: Optional[int] = None
    digest: Optional[str] = None
    modified_at: Optional[str] = None

    @property
    def size_gb(self) -> Optional[float]:
        """Return model size in GB."""
        if self.size_bytes is None:
            return None

        return self.size_bytes / (1024**3)


@dataclass(frozen=True, slots=True)
class OllamaServerInfo:

    """Basic information about the Ollama server."""

    host: str
    available: bool
    version: Optional[str] = None
    latency_seconds: Optional[float] = None


# ============================================================================
# Validation Helpers
# ============================================================================


def _validate_host(host: str) -> str:


    """
    Validate and normalize Ollama server URL.

    Parameters
    ----------
    host : str
        Server URL (e.g., 'http://127.0.0.1:11434' or '127.0.0.1:11434')

    Returns
    -------
    str
        Normalized URL with proper schema

    Raises
    ------
    OllamaValidationError
        If host is invalid, empty, or too long

    Examples
    --------
        url = _validate_host("127.0.0.1:11434")
        # Returns "http://127.0.0.1:11434"
    """

    if not isinstance(host, str):
        raise OllamaValidationError(
            f"Ollama host must be a string, got {type(host).__name__}."
        )


    value = host.strip().rstrip("/")


    if not value:
        raise OllamaValidationError(
            "Ollama host cannot be empty."
        )


    if len(value) > MAX_HOST_LENGTH:
        raise OllamaValidationError(
            f"Ollama host is too long (max: {MAX_HOST_LENGTH} characters, "
            f"got {len(value)})."
        )
    

    if not value.startswith(("http://", "https://")):
        logger.debug(
            "Ollama host URL missing schema, prepending http:// to %r",
            value,
        )

        value = f"http://{value}"

    return value


def _validate_model_name(model: str) -> str:

    """
    Validate Ollama model name.

    Parameters
    ----------
    model : str
        Model name (e.g., 'llama3.2', 'mistral')

    Returns
    -------
    str
        Validated model name

    Raises
    ------
    OllamaValidationError
        If model name is invalid, empty, or too long

    Examples
    --------
        name = _validate_model_name("llama3.2")
        # Returns "llama3.2"
    """

    if not isinstance(model, str):
        raise OllamaValidationError(
            f"Ollama model name must be a string, got {type(model).__name__}."
        )

    value = model.strip()


    if not value:
        raise OllamaValidationError(
            "Ollama model name cannot be empty."
        )
    

    if len(value) > MAX_MODEL_NAME_LENGTH:
        raise OllamaValidationError(
            f"Ollama model name is too long (max: {MAX_MODEL_NAME_LENGTH} "
            f"characters, got {len(value)})."
        )


    if any(char in value for char in ("\n", "\r", "\t")):
        raise OllamaValidationError(
            f"Ollama model name contains invalid whitespace: {value!r}."
        )


    return value



def _validate_timeout(timeout: float) -> float:

    """
    Validate request timeout.

    Parameters
    ----------
    timeout : float
        Timeout in seconds

    Returns
    -------
    float
        Validated timeout value

    Raises
    ------
    OllamaValidationError
        If timeout is not numeric or out of range

    Examples
    --------
        t = _validate_timeout(30.0)
        # Returns 30.0
    """

    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid timeout: {timeout!r}. Must be numeric."
        ) from exc

    if not MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS:
        raise OllamaValidationError(
            f"Timeout must be between {MIN_TIMEOUT_SECONDS} and "
            f"{MAX_TIMEOUT_SECONDS} seconds (got {value})."
        )

    return value



def _validate_probability(value: float, name: str) -> float:

    """
    Validate probability-like Ollama option (0.0 to 1.0).

    Parameters
    ----------
    value : float
        Value to validate
    name : str
        Parameter name (for error messages)

    Returns
    -------
    float
        Validated probability value

    Raises
    ------
    OllamaValidationError
        If value is not numeric or out of range

    Examples
    --------
        top_p = _validate_probability(0.9, "top_p")
        # Returns 0.9
    """

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid {name}: {value!r}. Must be numeric."
        ) from exc

    if not 0.0 <= number <= 1.0:
        raise OllamaValidationError(
            f"{name} must be between 0.0 and 1.0 (got {number})."
        )

    return number




def _validate_positive_number(value: float, name: str) -> float:

    """
    Validate a positive numeric option.

    Parameters
    ----------
    value : float
        Value to validate
    name : str
        Parameter name (for error messages)

    Returns
    -------
    float
        Validated positive number

    Raises
    ------
    OllamaValidationError
        If value is not numeric or not positive

    Examples
    --------
        repeat_penalty = _validate_positive_number(1.1, "repeat_penalty")
        # Returns 1.1
    """

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OllamaValidationError(
            f"Invalid {name}: {value!r}. Must be numeric."
        ) from exc

    if not math.isfinite(number) or number <= 0:
        raise OllamaValidationError(
            f"{name} must be a positive finite number (got {number})."
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

    Parameters
    ----------
    messages : list[ChatMessage]
        Messages to convert

    Returns
    -------
    list[dict[str, str]]
        List of dicts with 'role' and 'content' keys
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

    This provider communicates with Ollama via REST API (no SDK required).
    Models run locally and never leave the machine.

    Parameters
    ----------
    model : str, optional
        Model name (default: from config)
    temperature : float, optional
        Sampling temperature 0.0-1.0 (default: 0.7)
    timeout : float, optional
        Request timeout in seconds (default: 30.0)
    host : str, optional
        Ollama server URL (default: from secrets or http://127.0.0.1:11434)

    Returns
    -------
    OllamaProvider
        Initialized provider instance

    Raises
    ------
    OllamaValidationError
        If configuration is invalid

    Examples
    --------
        provider = OllamaProvider(model="llama3.2")
        result = provider.generate([
            ChatMessage(Role.USER, "Hello")
        ])
        print(result.text)

        # Streaming
        for chunk in provider.stream([
            ChatMessage(Role.USER, "Explain Python")
        ]):
            print(chunk, end="", flush=True)

        # Model management
        if provider.is_available():
            models = provider.list_installed_models()
            print(f"Available: {models}")
    """


    name = PROVIDER_NAME
    default_model = DEFAULT_OLLAMA_MODEL

    def __init__(
            
        self,
        model: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        host: Optional[str] = None,
    ) -> None:
        
        """
        Initialize Ollama provider.

        Parameters
        ----------
        model : str, optional
            Model name
        temperature : float, optional
            Temperature (0.0-1.0)
        timeout : float, optional
            Timeout in seconds
        host : str, optional
            Server URL
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

            "OllamaProvider initialized: host=%s model=%s temperature=%.1f",
            self.host,
            self.model,
            self.temperature,

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

        Returns
        -------
        bool
            True if server is reachable and responding

        Examples
        --------
            if provider.is_available():
                result = provider.generate(messages)
        """

        try:
            logger.debug("Checking Ollama server availability at %s", self.host)
            response = requests.get(
                self._tags_url(),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )


            available = response.status_code == 200
            logger.debug(
                "Ollama server available: %s (status: %d)",
                available,
                response.status_code,
            )


            return available


        except requests.RequestException as exc:
            logger.debug(
                "Ollama server not reachable at %s: %s",
                self.host,
                exc,

            )

            return False


    def health_check(self) -> bool:

        """
        Explicit health check alias.

        Returns
        -------
        bool
            True if server is healthy
        """

        return self.is_available()

    # ------------------------------------------------------------------
    # Server Info
    # ------------------------------------------------------------------


    def get_server_info(self) -> OllamaServerInfo:

        """
        Retrieve Ollama server availability and version.

        Returns
        -------
        OllamaServerInfo
            Server information including version and latency

        Examples
        --------
            info = provider.get_server_info()
            if info.available:
                print(f"Ollama {info.version} at {info.host}")
        """

        start = time.monotonic()


        try:
            logger.debug("Fetching Ollama server version from %s", self.host)
            response = requests.get(
                self._version_url(),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )

            response.raise_for_status()


            data = response.json()
            latency = time.monotonic() - start


            logger.debug(
                "Ollama server info retrieved: version=%s latency=%.2fs",
                data.get("version"),
                latency,
            )


            return OllamaServerInfo(
                host=self.host,
                available=True,
                version=data.get("version"),
                latency_seconds=latency,
            )


        except requests.RequestException as exc:
            latency = time.monotonic() - start
            logger.debug(
                "Ollama server info request failed after %.2fs: %s",
                latency,
                exc,
            )


            return OllamaServerInfo(
                host=self.host,
                available=False,
                latency_seconds=latency,
            )


        except (ValueError, TypeError) as exc:
            latency = time.monotonic() - start
            logger.debug(
                "Invalid Ollama version response after %.2fs: %s",
                latency,
                exc,
            )


            return OllamaServerInfo(
                host=self.host,
                available=False,
                latency_seconds=latency,
            )


    # ------------------------------------------------------------------
    # Model Management
    # ------------------------------------------------------------------


    def list_installed_models(
        self,
    ) -> list[str]:
        
        """
        Return names of models currently installed in Ollama.

        Returns
        -------
        list[str]
            List of installed model names
        """

        try:
            logger.debug("Listing installed Ollama models from %s", self.host)
            response = requests.get(
                self._tags_url(),
                timeout=MODEL_LIST_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            data = response.json()

            models = data.get("models", [])

            if not isinstance(models, list):
                logger.warning(
                    "Ollama models field is not a list: %s",
                    type(models).__name__,
                )
                return []
            

            result: list[str] = []

            for idx, item in enumerate(models):
                if not isinstance(item, dict):
                    logger.debug(
                        "Ollama model[%d] is not a dict, got %s",
                        idx,
                        type(item).__name__,
                    )
                    continue

                name = item.get("name")

                if isinstance(name, str) and name.strip():
                    result.append(name.strip())

            logger.debug("Found %d installed Ollama models", len(result))
            return result


        except requests.RequestException as exc:
            logger.warning(
                "Could not list Ollama models from %s: %s",
                self.host,
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

        Returns
        -------
        list[OllamaModel]
            List of OllamaModel objects with metadata

        Examples
        --------
            for model in provider.list_models():
                print(f"{model.name}: {model.size_gb:.1f}GB")
        """

        try:
            logger.debug("Fetching detailed Ollama model information")
            response = requests.get(
                self._tags_url(),
                timeout=MODEL_LIST_TIMEOUT_SECONDS,
            )


            response.raise_for_status()

            data = response.json()

            models = data.get("models", [])

            if not isinstance(models, list):
                logger.warning(
                    "Ollama models field is not a list: %s",
                    type(models).__name__,

                )
                return []

            result: list[OllamaModel] = []

            for idx, item in enumerate(models):
                if not isinstance(item, dict):
                    logger.debug(
                        "Ollama model[%d] is not a dict, got %s",
                        idx,
                        type(item).__name__,
                    )
                    continue


                name = item.get("name")

                if not isinstance(name, str) or not name.strip():
                    logger.debug(
                        "Ollama model[%d] has invalid name: %r",
                        idx,
                        name,
                    )
                    continue


                result.append(
                    OllamaModel(
                        name=name.strip(),
                        size_bytes=item.get("size"),
                        digest=item.get("digest"),
                        modified_at=item.get("modified_at"),
                    )
                )


            logger.debug("Retrieved metadata for %d models", len(result))
            return result

        except requests.RequestException as exc:
            logger.warning(
                "Failed to retrieve detailed Ollama models: %s",
                exc,
            )
            return []


        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid Ollama model metadata response: %s",
                exc,
            )
            return []


    def model_installed(
        self,
        model_name: Optional[str] = None,
    ) -> bool:
        
        """
        Check whether a model is installed locally.

        Parameters
        ----------
        model_name : str, optional
            Model to check (default: self.model)

        Returns
        -------
        bool
            True if model is installed

        Examples
        --------
            if not provider.model_installed():
                provider.pull_model()
        """

        target = _validate_model_name(
            model_name or self.model
        )

        installed = self.list_installed_models()

        is_installed = target in installed
        logger.debug(
            "Model '%s' installation check: %s",
            target,
            is_installed,
        )


        return is_installed

    def pull_model(
        self,
        model_name: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
    ) -> bool:
        
        """
        Pull an Ollama model through the REST API.

        The method blocks until the pull finishes. Progress updates
        are logged at INFO level.

        Parameters
        ----------
        model_name : str, optional
            Model to pull (default: self.model)
        timeout : float, optional
            Timeout for pull operation (default: self.timeout)

        Returns
        -------
        bool
            True if pull succeeded

        Examples
        --------
            if provider.pull_model("llama3.2"):
                print("Model ready")
            else:
                print("Pull failed")
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
            "Starting Ollama model pull: %s (timeout: %s)",
            target,
            request_timeout or "default",
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

                chunk_count = 0
                for line in response.iter_lines(
                    decode_unicode=True
                ):
                    
                    if not line:
                        continue

                    chunk_count += 1

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Ignoring invalid JSON in Ollama pull chunk %d",
                            chunk_count,
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
                            "Ollama pull error at chunk %d: %s",
                            chunk_count,
                            data["error"],
                        )
                        return False


                logger.info(
                    "Ollama model '%s' pulled successfully (%d chunks)",
                    target,
                    chunk_count,
                )


            return True


        except requests.ConnectionError as exc:
            logger.error(
                "Connection lost while pulling Ollama model '%s': %s",
                target,
                exc,
            )

            return False


        except requests.Timeout as exc:
            logger.error(
                "Ollama model pull timed out for '%s' after %.1f seconds: %s",
                target,
                request_timeout or REQUEST_TIMEOUT_SECONDS,
                exc,
            )

            return False


        except requests.HTTPError as exc:
            logger.error(
                "HTTP error while pulling Ollama model '%s': %s",
                target,
                exc,
            )

            return False
        

        except requests.RequestException as exc:
            logger.error(
                "Ollama model pull request failed for '%s': %s",
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
            temperature: float (0.0-1.0)
            top_p: float (0.0-1.0)
            top_k: int (>0)
            repeat_penalty: float (>0)
            num_ctx: int (>0)
            num_predict: int (>0)
            seed: int

        Parameters
        ----------
        **kwargs : Any
            Generation parameters

        Returns
        -------
        dict[str, Any]
            Ollama options dict

        Raises
        ------
        OllamaValidationError
            If any option is invalid

        Examples
        --------
            opts = provider._build_options(
                temperature=0.8,
                top_k=50
            )
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
                f"top_k must be an integer, got {type(kwargs.get('top_k')).__name__}."
            ) from exc


        if top_k < 0:
            raise OllamaValidationError(
                f"top_k cannot be negative (got {top_k})."
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
                f"repeat_penalty must be numeric, got {type(kwargs.get('repeat_penalty')).__name__}."
            ) from exc
        

        if repeat_penalty <= 0:
            raise OllamaValidationError(
                f"repeat_penalty must be greater than zero (got {repeat_penalty})."
            )
        

        options: dict[str, Any] = {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repeat_penalty": repeat_penalty,
        }


        logger.debug(
            "Built Ollama options: temperature=%.2f top_p=%.2f top_k=%d penalty=%.2f",
            temperature,
            top_p,
            top_k,
            repeat_penalty,
        )


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
                    f"{key} must be an integer, got {type(kwargs[key]).__name__}."
                ) from exc


            if key != "seed" and value <= 0:
                raise OllamaValidationError(
                    f"{key} must be greater than zero (got {value})."
                )


            options[key] = value
            logger.debug("Set Ollama option: %s=%s", key, value)

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

        Raises
        ------
        OllamaConnectionError
            If server is unreachable
        OllamaTimeoutError
            If request times out
        OllamaHTTPError
            If server returns HTTP error
        OllamaResponseError
            If response is invalid
        OllamaModelError
            If model is unavailable
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

        logger.debug(
            "Starting Ollama API call: model=%s messages=%d",
            target_model,
            len(normalized_messages),
        )
        

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
                f"Make sure Ollama is running (e.g., 'ollama serve'). "
                f"Error: {exc}"
            ) from exc


        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {timeout:.1f} seconds: {exc}"
            ) from exc


        except requests.HTTPError as exc:
            detail = self._extract_http_error(response)


            raise OllamaHTTPError(
                f"Ollama returned HTTP {response.status_code}: {detail}"
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
                "Ollama returned invalid JSON response."
            ) from exc


        if not isinstance(data, dict):
            raise OllamaResponseError(
                f"Ollama response must be a JSON object, got {type(data).__name__}."
            )


        if data.get("error"):
            raise OllamaModelError(
                f"Ollama error: {data['error']}"
            )
        

        message = data.get("message")

        if not isinstance(message, dict):
            raise OllamaResponseError(
                f"Ollama response message must be a dict, got {type(message).__name__}."
            )


        text = message.get("content", "")

        if not isinstance(text, str):
            text = str(text)


        text = text.strip()

        tokens_used = self._calculate_tokens_used(data)

        logger.info(

            "Ollama generation completed: model=%s latency=%.2fs tokens=%s",
            target_model,
            elapsed,
            tokens_used,

        )

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


    def generate(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        
        """
        Generate a response (non-streaming).

        This is the primary generation method. For streaming, use stream().

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs : Any
            Generation options (temperature, top_k, etc.)

        Returns
        -------
        CompletionResult
            Complete generation result

        Examples
        --------
            result = provider.generate([
                ChatMessage(Role.USER, "Hello")
            ])
            print(result.text)
        """

        return self._call_api(messages, **kwargs)

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

        Ollama returns newline-delimited JSON (NDJSON). This method
        yields text chunks as they arrive.

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs : Any
            Generation options (temperature, top_k, etc.)

        Yields
        ------
        str
            Response text chunks

        Raises
        ------
        OllamaConnectionError
            If connection is lost
        OllamaTimeoutError
            If streaming times out
        OllamaResponseError
            If response is invalid

        Examples
        --------
            for chunk in provider.stream([
                ChatMessage(Role.USER, "Explain Python")
            ]):
                print(chunk, end="", flush=True)
            print()  # newline
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
            "Starting Ollama streaming request: model=%s messages=%d",
            target_model,
            len(normalized_messages),
        )


        chunk_count = 0



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
                        f"Ollama returned HTTP {response.status_code}: {detail}"
                    ) from exc

                for line in response.iter_lines(
                    decode_unicode=True
                ):
                    if not line:
                        continue

                    chunk_count += 1

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Ignoring invalid JSON in stream chunk %d",
                            chunk_count,
                        )
                        continue

                    if not isinstance(chunk, dict):
                        logger.debug(
                            "Stream chunk %d is not a dict, got %s",
                            chunk_count,
                            type(chunk).__name__,
                        )
                        continue


                    if chunk.get("error"):
                        raise OllamaResponseError(
                            f"Ollama stream error: {chunk['error']}"
                        )


                    message = chunk.get(
                        "message",
                        {},
                    )


                    if not isinstance(message, dict):
                        logger.debug(
                            "Stream chunk %d message is not a dict, got %s",
                            chunk_count,
                            type(message).__name__,
                        )
                        continue


                    content = message.get(
                        "content",
                        "",
                    )


                    if content:
                        yield str(content)

                    if chunk.get("done"):
                        logger.debug(
                            "Ollama streaming completed: %d chunks",
                            chunk_count,
                        )
                        break


        except requests.ConnectionError as exc:
            logger.error(
                "Lost connection to Ollama server at %s during streaming: %s",
                self.host,
                exc,
            )

            raise OllamaConnectionError(
                f"Lost connection to Ollama server at {self.host}."
            ) from exc
        

        except requests.Timeout as exc:
            logger.error(
                "Ollama streaming timed out after %.1f seconds (chunks: %d): %s",
                timeout,
                chunk_count,
                exc,
            )

            raise OllamaTimeoutError(
                f"Ollama streaming timed out after {timeout:.1f} seconds."
            ) from exc


        except requests.RequestException as exc:
            logger.error(
                "Ollama streaming request failed (chunks: %d): %s",
                chunk_count,
                exc,
            )

            raise OllamaConnectionError(
                f"Ollama streaming request failed: {exc}"
            ) from exc


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:

        """
        Safely convert a value to int.

        Returns None if conversion fails.
        """

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
    ) -> Optional[int]:
        
        """
        Calculate total token usage from Ollama response.

        Parameters
        ----------
        data : dict
            Ollama response data

        Returns
        -------
        int or None
            Total tokens used, or None if unavailable
        """

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
        """
        Extract a useful error message from an HTTP response.

        Parameters
        ----------
        response : requests.Response
            HTTP response object

        Returns
        -------
        str
            Error message (up to 500 chars)
        """

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

        Returns
        -------
        dict[str, Any]
            Diagnostic data including server status, model list, options

        Examples
        --------
            diag = provider.diagnostics()
            if diag['available']:
                print(f"Ollama {diag['server_version']}")
            else:
                print("Ollama offline")
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
    host: Optional[str] = None,
) -> bool:
    
    """
    Quickly check whether Ollama is available.

    Parameters
    ----------
    host : str, optional
        Server URL

    Returns
    -------
    bool
        True if server is reachable

    Examples
    --------
        if ollama_available():
            print("Ready to use local models")
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
    host: Optional[str] = None,
) -> list[str]:
    
    """
    Return installed Ollama model names.

    Parameters
    ----------
    host : str, optional
        Server URL

    Returns
    -------
    list[str]
        List of installed model names

    Examples
    --------
        for model in get_ollama_models():
            print(model)
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
    host: Optional[str] = None,
    timeout: Optional[float] = None,
) -> bool:


    """
    Convenience wrapper for pulling an Ollama model.

    Parameters
    ----------
    model_name : str
        Model to pull
    host : str, optional
        Server URL
    timeout : float, optional
        Pull timeout in seconds

    Returns
    -------
    bool
        True if pull succeeded

    Examples
    --------
        if pull_ollama_model("llama3.2"):
            print("Ready")
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
            "Ollama model pull failed for '%s': %s",
            model_name,
            exc,
        )
        return False


def ollama_diagnostics(
    host: Optional[str] = None,
) -> dict[str, Any]:
    
    """
    Return Ollama diagnostic information.

    Parameters
    ----------
    host : str, optional
        Server URL

    Returns
    -------
    dict[str, Any]
        Diagnostic data

    Examples
    --------
        diag = ollama_diagnostics()
        print(f"Status: {'OK' if diag['available'] else 'OFFLINE'}")
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