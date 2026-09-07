"""
gemini.py
=========
AI provider backed by Google's Gemini API (via the `google-generativeai`
SDK). This is the default cloud provider for AssistantX.

If the `google-generativeai` package is not installed, or no API key is
configured, `is_available()` returns False and the fallback chain in
ai/provider.py transparently moves on to the next provider (Ollama or
local).
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from ai.provider import AIProviderBase, ChatMessage, CompletionResult, ProviderError, Role
from config.constants import DEFAULT_GEMINI_MODEL, DEFAULT_TEMPERATURE, REQUEST_TIMEOUT_SECONDS
from config.secrets import secrets

logger = logging.getLogger(__name__)


def _messages_to_gemini_format(messages: list[ChatMessage]) -> tuple[Optional[str], list[dict]]:
    """
    Split a normalized ChatMessage list into (system_instruction, history)
    matching the shape the Gemini SDK expects. Gemini treats the system
    prompt as a separate top-level parameter rather than a chat turn.
    """
    system_instruction: Optional[str] = None
    history: list[dict] = []

    for msg in messages:
        if msg.role == Role.SYSTEM:
            # Concatenate multiple system messages if present.
            system_instruction = (
                msg.content if system_instruction is None else f"{system_instruction}\n{msg.content}"
            )
        else:
            gemini_role = "model" if msg.role == Role.ASSISTANT else "user"
            history.append({"role": gemini_role, "parts": [msg.content]})

    return system_instruction, history


class GeminiProvider(AIProviderBase):
    """AI provider implementation wrapping Google's Gemini chat models."""

    name = "gemini"
    default_model = DEFAULT_GEMINI_MODEL

    def __init__(self, model: Optional[str] = None, temperature: float = DEFAULT_TEMPERATURE) -> None:
        super().__init__(model=model, temperature=temperature)
        self._client_module = None
        self._model_instance = None

    def _ensure_client(self):
        """Lazily import and configure the Gemini SDK on first use."""
        if self._model_instance is not None:
            return self._model_instance

        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise ProviderError(
                "The 'google-generativeai' package is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        if not secrets.gemini_api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not configured. Add it to your .env file."
            )

        genai.configure(api_key=secrets.gemini_api_key)
        self._client_module = genai
        self._model_instance = genai.GenerativeModel(self.model)
        return self._model_instance

    def is_available(self) -> bool:
        if not secrets.gemini_api_key:
            return False
        try:
            import google.generativeai  # noqa: F401
        except ImportError:
            return False
        return True

    def _call_api(self, messages: list[ChatMessage], **kwargs) -> CompletionResult:
        model = self._ensure_client()
        system_instruction, history = _messages_to_gemini_format(messages)

        # Re-instantiate with system_instruction if one was provided and
        # differs from what the cached model was built with.
        if system_instruction:
            model = self._client_module.GenerativeModel(
                self.model, system_instruction=system_instruction
            )

        generation_config = {
            "temperature": kwargs.get("temperature", self.temperature),
            "max_output_tokens": kwargs.get("max_tokens", 2048),
            "top_p": kwargs.get("top_p", 0.9),
        }

        start = time.monotonic()

        # The last message is the "new" user turn; everything before it
        # is prior chat history for context.
        if not history:
            raise ProviderError("No user/assistant messages provided to Gemini.")

        chat_history, latest_turn = history[:-1], history[-1]
        chat_session = model.start_chat(history=chat_history)

        response = chat_session.send_message(
            latest_turn["parts"][0],
            generation_config=generation_config,
            request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
        )

        elapsed = time.monotonic() - start

        text = getattr(response, "text", "") or ""
        finish_reason = None
        tokens_used = None
        try:
            candidate = response.candidates[0]
            finish_reason = str(candidate.finish_reason)
        except (AttributeError, IndexError):
            pass
        try:
            tokens_used = response.usage_metadata.total_token_count
        except AttributeError:
            pass

        return CompletionResult(
            text=text.strip(),
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            tokens_used=tokens_used,
            finish_reason=finish_reason,
        )

    def stream(self, messages: list[ChatMessage], **kwargs) -> Iterable[str]:
        """True token-by-token streaming via the Gemini SDK's stream=True flag."""
        try:
            model = self._ensure_client()
        except ProviderError as exc:
            logger.error("Gemini stream unavailable: %s", exc)
            return

        system_instruction, history = _messages_to_gemini_format(messages)
        if system_instruction:
            model = self._client_module.GenerativeModel(
                self.model, system_instruction=system_instruction
            )

        if not history:
            return

        chat_history, latest_turn = history[:-1], history[-1]
        chat_session = model.start_chat(history=chat_history)

        generation_config = {
            "temperature": kwargs.get("temperature", self.temperature),
            "max_output_tokens": kwargs.get("max_tokens", 2048),
        }

        try:
            response_stream = chat_session.send_message(
                latest_turn["parts"][0],
                generation_config=generation_config,
                stream=True,
            )
            for chunk in response_stream:
                if getattr(chunk, "text", None):
                    yield chunk.text
        except Exception as exc:  # noqa: BLE001
            logger.error("Gemini streaming error: %s", exc)
            