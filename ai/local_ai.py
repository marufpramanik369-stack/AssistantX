"""
local_ai.py
===========
A fully offline, dependency-free "provider" used as the last resort in
the fallback chain when neither Gemini nor Ollama are reachable (no
internet, no API key, Ollama server not running, etc.).

This is intentionally NOT a real language model — it's a lightweight
rule-based responder that:
    - Handles common conversational patterns (greetings, thanks, time,
      date, simple math) directly.
    - Clearly tells the user when it cannot answer something that
      requires a real LLM, rather than hallucinating.

This keeps AssistantX minimally functional even with zero external
dependencies configured, which matters a lot for first-run experience.
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Optional

from ai.provider import AIProviderBase, ChatMessage, CompletionResult, Role
from config.constants import DATE_DISPLAY_FORMAT, TIME_DISPLAY_FORMAT

logger = logging.getLogger(__name__)


_GREETING_PATTERNS = re.compile(
    r"\b(hi|hello|hey|good morning|good evening|good afternoon|salut|namaste|assalamu)\b",
    re.IGNORECASE,
)
_THANKS_PATTERNS = re.compile(r"\b(thanks|thank you|thx|dhonnobad|dhonyobad)\b", re.IGNORECASE)
_TIME_PATTERNS = re.compile(r"\b(what time|current time|time now)\b", re.IGNORECASE)
_DATE_PATTERNS = re.compile(r"\b(what date|today'?s date|what day is it)\b", re.IGNORECASE)
_MATH_PATTERN = re.compile(r"^[\d\s+\-*/().]+$")

_GREETING_RESPONSES = [
    "Hello! How can I help you today?",
    "Hi there! What can I do for you?",
    "Hey! I'm listening.",
]

_THANKS_RESPONSES = [
    "You're welcome!",
    "Anytime!",
    "Happy to help!",
]

_FALLBACK_RESPONSES = [
    "I'm currently running in offline mode and can't fully process that "
    "request. Once an internet connection or a local AI model (via "
    "Ollama) is available, I'll be able to help much more.",
    "That's beyond what I can answer offline right now. Try connecting "
    "to the internet or starting Ollama for full conversational ability.",
]


class LocalAIProvider(AIProviderBase):
    """Offline rule-based fallback provider — always available, never fails."""

    name = "local"
    default_model = "rule-based-v1"

    def is_available(self) -> bool:
        # This provider has no external dependency — always available.
        return True

    def _last_user_message(self, messages: list[ChatMessage]) -> str:
        for msg in reversed(messages):
            if msg.role == Role.USER:
                return msg.content
        return ""

    def _try_math(self, text: str) -> Optional[str]:
        cleaned = text.strip()
        if _MATH_PATTERN.match(cleaned) and any(op in cleaned for op in "+-*/"):
            try:
                # Restricted eval: only digits/operators reach this point
                # due to the regex guard above, so this is safe from
                # arbitrary code execution.
                result = eval(cleaned, {"__builtins__": {}}, {})  # noqa: S307
                return f"{cleaned} = {result}"
            except (ZeroDivisionError, SyntaxError, TypeError):
                return None
        return None

    def _call_api(self, messages: list[ChatMessage], **kwargs) -> CompletionResult:
        start = time.monotonic()
        user_text = self._last_user_message(messages)

        if _GREETING_PATTERNS.search(user_text):
            text = random.choice(_GREETING_RESPONSES)
        elif _THANKS_PATTERNS.search(user_text):
            text = random.choice(_THANKS_RESPONSES)
        elif _TIME_PATTERNS.search(user_text):
            text = f"It's currently {datetime.now().strftime(TIME_DISPLAY_FORMAT)}."
        elif _DATE_PATTERNS.search(user_text):
            text = f"Today is {datetime.now().strftime(DATE_DISPLAY_FORMAT)}."
        else:
            math_result = self._try_math(user_text)
            text = math_result if math_result else random.choice(_FALLBACK_RESPONSES)

        elapsed = time.monotonic() - start
        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            finish_reason="offline_rule_match",
        )

