"""
ollama.py
=========
AI provider backed by a locally-running Ollama server
(https://ollama.com). This gives AssistantX a fully offline, private
fallback (or primary choice) when the user prefers not to depend on a
cloud API, or when Gemini is unreachable / unconfigured.

Communicates with Ollama's REST API directly via `requests`, so no
Ollama-specific Python SDK is required.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Iterable, Optional

import requests

from ai.provider import AIProviderBase, ChatMessage, CompletionResult, ProviderError, Role
from config.constants import DEFAULT_OLLAMA_MODEL, DEFAULT_TEMPERATURE, REQUEST_TIMEOUT_SECONDS
from config.secrets import secrets

logger = logging.getLogger(__name__)


def _messages_to_ollama_format(messages: list[ChatMessage]) -> list[dict]:
    """Convert normalized ChatMessages into Ollama's /api/chat message shape."""
    return [{"role": msg.role.value, "content": msg.content} for msg in messages]


class OllamaProvider(AIProviderBase):
    """AI provider implementation wrapping a local Ollama server."""

    name = "ollama"
    default_model = DEFAULT_OLLAMA_MODEL

    def __init__(self, model: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> None:
        super().__init__(model=model, temperature=temperature)
        self.host = secrets.ollama_host.rstrip("/")

    def _chat_url(self) -> str:
        return f"{self.host}/api/chat"

    def _tags_url(self) -> str:
        return f"{self.host}/api/tags"

    def is_available(self) -> bool:
        """Ping the Ollama server's /api/tags endpoint to confirm it's up."""
        try:
            response = requests.get(self._tags_url(), timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def list_installed_models(self) -> list[str]:
        """Return the list of model tags currently pulled on the Ollama server."""
        try:
            response = requests.get(self._tags_url(), timeout=5)
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except requests.RequestException as exc:
            logger.warning("Could not list Ollama models: %s", exc)
            return []

    def _call_api(self, messages: list[ChatMessage], **kwargs) -> CompletionResult:
        payload = {
            "model": self.model,
            "messages": _messages_to_ollama_format(messages),
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "top_p": kwargs.get("top_p", 0.9),
            },
        }

        start = time.monotonic()
        try:
            response = requests.post(
                self._chat_url(),
                json=payload,
                timeout=kwargs.get("timeout", REQUEST_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
        except requests.ConnectionError as exc:
            raise ProviderError(
                f"Could not reach Ollama server at {self.host}. "
                f"Is 'ollama serve' running?"
            ) from exc
        except requests.Timeout as exc:
            raise ProviderError(f"Ollama request timed out after {REQUEST_TIMEOUT_SECONDS}s.") from exc
        except requests.HTTPError as exc:
            raise ProviderError(f"Ollama returned an HTTP error: {exc}") from exc

        elapsed = time.monotonic() - start
        data = response.json()

        message = data.get("message", {})
        text = message.get("content", "").strip()

        tokens_used = None
        if "eval_count" in data and "prompt_eval_count" in data:
            tokens_used = data["eval_count"] + data["prompt_eval_count"]

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            tokens_used=tokens_used,
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    def stream(self, messages: list[ChatMessage], **kwargs) -> Iterable[str]:
        """True token-by-token streaming using Ollama's NDJSON stream mode."""
        payload = {
            "model": self.model,
            "messages": _messages_to_ollama_format(messages),
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
            },
        }

        try:
            with requests.post(
                self._chat_url(),
                json=payload,
                stream=True,
                timeout=kwargs.get("timeout", REQUEST_TIMEOUT_SECONDS),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break
        except requests.RequestException as exc:
            logger.error("Ollama streaming error: %s", exc)

    def pull_model(self, model_name: Optional[str] = None) -> bool:
        """
        Trigger a `ollama pull` for the given model via the REST API.
        Blocks until the pull completes. Returns True on success.
        """
        target = model_name or self.model
        try:
            with requests.post(
                f"{self.host}/api/pull",
                json={"name": target, "stream": True},
                stream=True,
                timeout=None,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    status = json.loads(line).get("status", "")
                    logger.info("[ollama pull:%s] %s", target, status)
            return True
        except requests.RequestException as exc:
            logger.error("Failed to pull Ollama model '%s': %s", target, exc)
            return False