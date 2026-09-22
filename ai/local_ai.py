"""
ai/local_ai.py
==============
Dependency-free offline fallback provider for AssistantX.

This provider is intentionally NOT a real language model.

Its purpose is to keep AssistantX minimally useful when:
- Gemini is unavailable
- No API key is configured
- Internet is offline
- Ollama is not running
- No local LLM backend is available

Supported offline capabilities:
- Greetings
- Thanks
- Basic identity/help questions
- Current time/date
- Simple arithmetic
- Banglish-friendly common phrases
- Safe fallback responses

Important:
This module never pretends to understand complex questions.
If a request requires a real language model, it clearly informs the user.

No third-party dependencies are required.
"""

from __future__ import annotations

import ast
import logging
import math
import operator
import random
import re
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    ProviderValidationError,
    Role,
    normalize_messages,
)
from config.constants import (
    DATE_DISPLAY_FORMAT,
    TIME_DISPLAY_FORMAT,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

PROVIDER_NAME = "local"
DEFAULT_LOCAL_MODEL = "rule-based-v2"

MAX_INPUT_LENGTH = 10_000
MAX_EXPRESSION_LENGTH = 250
MAX_AST_DEPTH = 32
MAX_POWER_EXPONENT = 100

FINISH_RULE_MATCH = "offline_rule_match"
FINISH_FALLBACK = "offline_fallback"


# ============================================================================
# Exceptions
# ============================================================================


class LocalAIError(RuntimeError):
    """Base exception for the local rule-based provider."""


class LocalAIValidationError(
    LocalAIError,
    ProviderValidationError,
):
    """Raised when local AI input is invalid."""


class LocalAIMathError(LocalAIError):
    """Raised when offline arithmetic evaluation fails."""


# ============================================================================
# Patterns
# ============================================================================

_GREETING_PATTERN = re.compile(
    r"\b("
    r"hi|hello|hey|hiya|yo|"
    r"good\s+morning|good\s+afternoon|good\s+evening|"
    r"assalamu\s+alaikum|assalamualaikum|salam|"
    r"namaste|salut|"
    r"হাই|হ্যালো|সালাম|আসসালামু\s+আলাইকুম"
    r")\b",
    re.IGNORECASE,
)

_THANKS_PATTERN = re.compile(
    r"\b("
    r"thanks|thank\s+you|thankyou|thx|ty|"
    r"dhonnobad|dhonyobad|dhonnobad|"
    r"ধন্যবাদ|থ্যাংকস"
    r")\b",
    re.IGNORECASE,
)

_TIME_PATTERN = re.compile(
    r"("
    r"\bwhat\s+time\b|"
    r"\bcurrent\s+time\b|"
    r"\btime\s+now\b|"
    r"\bwhat(?:'s|\s+is)\s+the\s+time\b|"
    r"\bkoyta\s+baje\b|"
    r"\bkoto\s+baje\b|"
    r"\btime\s+koto\b|"
    r"কয়টা\s+বাজে|কটা\s+বাজে|সময়\s+কত"
    r")",
    re.IGNORECASE,
)

_DATE_PATTERN = re.compile(
    r"("
    r"\bwhat\s+date\b|"
    r"\btoday(?:'s|\s+is)?\s+date\b|"
    r"\bwhat\s+day\s+is\s+it\b|"
    r"\bcurrent\s+date\b|"
    r"\bajke\s+koto\s+tarikh\b|"
    r"\bajker\s+tarikh\b|"
    r"\btarikh\s+koto\b|"
    r"আজ\s+কত\s+তারিখ|আজকের\s+তারিখ"
    r")",
    re.IGNORECASE,
)

_IDENTITY_PATTERN = re.compile(
    r"("
    r"\bwho\s+are\s+you\b|"
    r"\bwhat\s+are\s+you\b|"
    r"\byour\s+name\b|"
    r"\btomar\s+nam\s+ki\b|"
    r"\btumi\s+ke\b|"
    r"তুমি\s+কে|তোমার\s+নাম\s+কি"
    r")",
    re.IGNORECASE,
)

_HELP_PATTERN = re.compile(
    r"("
    r"\bhelp\b|"
    r"\bwhat\s+can\s+you\s+do\b|"
    r"\bwhat\s+do\s+you\s+do\b|"
    r"\bki\s+ki\s+korte\s+paro\b|"
    r"\btumi\s+ki\s+korte\s+paro\b|"
    r"তুমি\s+কি\s+করতে\s+পারো|সাহায্য"
    r")",
    re.IGNORECASE,
)

_HOW_ARE_YOU_PATTERN = re.compile(
    r"("
    r"\bhow\s+are\s+you\b|"
    r"\bkemon\s+acho\b|"
    r"\bkemon\s+aso\b|"
    r"কেমন\s+আছ"
    r")",
    re.IGNORECASE,
)

_OFFLINE_STATUS_PATTERN = re.compile(
    r"("
    r"\bare\s+you\s+offline\b|"
    r"\boffline\s+mode\b|"
    r"\bno\s+internet\b|"
    r"\binternet\s+ache\b|"
    r"\boffline\s+acho\b|"
    r"অফলাইন"
    r")",
    re.IGNORECASE,
)

_MATH_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"calculate|calc|compute|solve|"
    r"what\s+is|"
    r"koto|hisab|hisab\s+koro|"
    r"হিসাব|হিসাব\s+কর"
    r")\s*[:\-]?\s*",
    re.IGNORECASE,
)

_MATH_ALLOWED_PATTERN = re.compile(
    r"^[\d\s+\-*/().%^]+$"
)


# ============================================================================
# Responses
# ============================================================================

_GREETING_RESPONSES = (
    "Hello! How can I help you?",
    "Hi! I'm ready to help.",
    "Hey! What can I do for you?",
    "Hello! AssistantX is ready.",
)

_THANKS_RESPONSES = (
    "You're welcome!",
    "Anytime!",
    "Happy to help!",
    "You're most welcome.",
)

_HOW_ARE_YOU_RESPONSES = (
    "I'm running well and ready to help.",
    "I'm doing well. What can I help you with?",
    "All systems are ready.",
)

_IDENTITY_RESPONSES = (
    "I'm AssistantX, your personal AI desktop assistant.",
    "I'm AssistantX. In this offline mode I can handle a few basic tasks without an internet connection.",
)

_HELP_RESPONSE = (
    "I'm currently using AssistantX's offline fallback mode. "
    "I can handle greetings, thanks, current time, current date, "
    "and simple arithmetic. For complex questions, use Gemini or "
    "start Ollama for full AI responses."
)

_OFFLINE_STATUS_RESPONSE = (
    "Yes, this response is coming from AssistantX's local offline "
    "fallback provider. It doesn't require internet, an API key, "
    "or an Ollama server."
)

_FALLBACK_RESPONSES = (
    "I'm currently using the basic offline mode, so I can't fully "
    "understand that request. Start Ollama or connect a cloud AI "
    "provider for full conversational support.",

    "That request needs a real AI model. AssistantX's offline fallback "
    "can currently handle only basic conversation, time, date, and "
    "simple calculations.",

    "I can't reliably answer that in rule-based offline mode. "
    "If Ollama is running, AssistantX can use a local language model instead.",
)


# ============================================================================
# Safe Arithmetic
# ============================================================================

_BINARY_OPERATORS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _ast_depth(node: ast.AST) -> int:
    """Return maximum depth of an AST."""
    children = list(ast.iter_child_nodes(node))

    if not children:
        return 1

    return 1 + max(_ast_depth(child) for child in children)


def _evaluate_math_node(node: ast.AST) -> int | float:
    """
    Safely evaluate a restricted arithmetic AST.

    No eval() or exec() is used.
    """
    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)

    if isinstance(node, ast.Constant):
        value = node.value

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LocalAIMathError(
                "Only numeric constants are allowed."
            )

        if isinstance(value, float) and not math.isfinite(value):
            raise LocalAIMathError(
                "Non-finite numbers are not allowed."
            )

        return value

    if isinstance(node, ast.BinOp):
        operator_type = type(node.op)

        if operator_type not in _BINARY_OPERATORS:
            raise LocalAIMathError(
                "Unsupported arithmetic operator."
            )

        left = _evaluate_math_node(node.left)
        right = _evaluate_math_node(node.right)

        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_POWER_EXPONENT:
                raise LocalAIMathError(
                    "Exponent is too large."
                )

        try:
            result = _BINARY_OPERATORS[operator_type](
                left,
                right,
            )
        except ZeroDivisionError as exc:
            raise LocalAIMathError(
                "Division by zero is not allowed."
            ) from exc
        except OverflowError as exc:
            raise LocalAIMathError(
                "Calculation result is too large."
            ) from exc

        if isinstance(result, float) and not math.isfinite(result):
            raise LocalAIMathError(
                "Calculation produced a non-finite result."
            )

        return result

    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)

        if operator_type not in _UNARY_OPERATORS:
            raise LocalAIMathError(
                "Unsupported unary operator."
            )

        operand = _evaluate_math_node(node.operand)

        return _UNARY_OPERATORS[operator_type](operand)

    raise LocalAIMathError(
        f"Unsupported expression element: "
        f"{node.__class__.__name__}"
    )


def safe_calculate(expression: str) -> int | float:
    """
    Safely evaluate a simple arithmetic expression.

    Supported:
        +  -  *  /  //  %  **  parentheses

    Example:
        safe_calculate("10 + 5 * 2")
    """
    if not isinstance(expression, str):
        raise LocalAIValidationError(
            "Math expression must be a string."
        )

    expression = expression.strip()

    if not expression:
        raise LocalAIValidationError(
            "Math expression cannot be empty."
        )

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise LocalAIValidationError(
            "Math expression is too long."
        )

    # User-friendly ^ means exponent.
    expression = expression.replace("^", "**")

    if not _MATH_ALLOWED_PATTERN.fullmatch(expression):
        raise LocalAIMathError(
            "Expression contains unsupported characters."
        )

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        )
    except SyntaxError as exc:
        raise LocalAIMathError(
            "Invalid arithmetic expression."
        ) from exc

    if _ast_depth(tree) > MAX_AST_DEPTH:
        raise LocalAIMathError(
            "Arithmetic expression is too complex."
        )

    return _evaluate_math_node(tree)


# ============================================================================
# Input Helpers
# ============================================================================


def _normalize_user_text(text: str) -> str:
    """Normalize input for rule matching."""
    if not isinstance(text, str):
        return ""

    return " ".join(text.strip().split())


def _extract_math_expression(text: str) -> str:
    """
    Extract a possible arithmetic expression.

    Examples:
        "calculate 2 + 2" -> "2 + 2"
        "what is 5 * 8"   -> "5 * 8"
    """
    cleaned = _normalize_user_text(text)

    cleaned = _MATH_PREFIX_PATTERN.sub(
        "",
        cleaned,
        count=1,
    )

    if cleaned.endswith("?"):
        cleaned = cleaned[:-1].strip()

    return cleaned


def _format_number(value: float) -> str:
    """Format arithmetic result cleanly."""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))

        return f"{value:.12g}"

    return str(value)


# ============================================================================
# Local AI Provider
# ============================================================================


class LocalAIProvider(AIProviderBase):
    """
    Dependency-free AssistantX offline fallback provider.

    This provider is always considered available because it requires:
    - no API key
    - no internet connection
    - no external server
    - no external Python package

    It is deliberately conservative and does not hallucinate answers.
    """

    name = PROVIDER_NAME
    default_model = DEFAULT_LOCAL_MODEL

    def __init__(
        self,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model or self.default_model,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """The built-in rule engine is always available."""
        return True

    # ------------------------------------------------------------------
    # Conversation Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _last_user_message(
        messages: Sequence[ChatMessage],
    ) -> str:
        """Return the latest user message."""
        for message in reversed(messages):
            if message.role == Role.USER:
                return message.content

        return ""

    def _try_math(
        self,
        text: str,
    ) -> str | None:
        """
        Attempt to answer a simple arithmetic request.
        """
        expression = _extract_math_expression(text)

        if not expression:
            return None

        # Avoid attempting math on ordinary natural-language messages.
        if not _MATH_ALLOWED_PATTERN.fullmatch(
            expression.replace("^", "**")
        ):
            return None

        if not any(
            operator_symbol in expression
            for operator_symbol in (
                "+",
                "-",
                "*",
                "/",
                "%",
                "^",
            )
        ):
            return None

        try:
            result = safe_calculate(expression)

            return (
                f"{expression} = "
                f"{_format_number(result)}"
            )

        except LocalAIMathError as exc:
            logger.debug(
                "Offline math evaluation failed for %r: %s",
                expression,
                exc,
            )

            return None

    # ------------------------------------------------------------------
    # Rule Engine
    # ------------------------------------------------------------------

    def _respond(
        self,
        user_text: str,
    ) -> tuple[str, str]:
        """
        Return:
            (response_text, finish_reason)
        """
        normalized = _normalize_user_text(
            user_text
        )

        if not normalized:
            return (
                "I didn't receive a message.",
                FINISH_FALLBACK,
            )

        if len(normalized) > MAX_INPUT_LENGTH:
            return (
                "That message is too long for AssistantX's "
                "basic offline mode.",
                FINISH_FALLBACK,
            )

        # More specific rules should come before broad patterns.

        if _TIME_PATTERN.search(normalized):
            return (
                f"It's currently "
                f"{datetime.now().strftime(TIME_DISPLAY_FORMAT)}.",
                FINISH_RULE_MATCH,
            )

        if _DATE_PATTERN.search(normalized):
            return (
                f"Today is "
                f"{datetime.now().strftime(DATE_DISPLAY_FORMAT)}.",
                FINISH_RULE_MATCH,
            )

        if _IDENTITY_PATTERN.search(normalized):
            return (
                random.choice(_IDENTITY_RESPONSES),
                FINISH_RULE_MATCH,
            )

        if _HELP_PATTERN.search(normalized):
            return (
                _HELP_RESPONSE,
                FINISH_RULE_MATCH,
            )

        if _OFFLINE_STATUS_PATTERN.search(normalized):
            return (
                _OFFLINE_STATUS_RESPONSE,
                FINISH_RULE_MATCH,
            )

        if _HOW_ARE_YOU_PATTERN.search(normalized):
            return (
                random.choice(
                    _HOW_ARE_YOU_RESPONSES
                ),
                FINISH_RULE_MATCH,
            )

        if _THANKS_PATTERN.search(normalized):
            return (
                random.choice(
                    _THANKS_RESPONSES
                ),
                FINISH_RULE_MATCH,
            )

        if _GREETING_PATTERN.search(normalized):
            return (
                random.choice(
                    _GREETING_RESPONSES
                ),
                FINISH_RULE_MATCH,
            )

        math_result = self._try_math(normalized)

        if math_result is not None:
            return (
                math_result,
                FINISH_RULE_MATCH,
            )

        return (
            random.choice(
                _FALLBACK_RESPONSES
            ),
            FINISH_FALLBACK,
        )

    # ------------------------------------------------------------------
    # Provider Contract
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate a rule-based offline completion.
        """
        del kwargs

        start = time.monotonic()

        normalized_messages = normalize_messages(
            messages
        )

        user_text = self._last_user_message(
            normalized_messages
        )

        if not user_text:
            response_text = (
                "I couldn't find a user message "
                "to respond to."
            )
            finish_reason = FINISH_FALLBACK
        else:
            response_text, finish_reason = (
                self._respond(user_text)
            )

        elapsed = time.monotonic() - start

        return CompletionResult(
            text=response_text,
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            finish_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """Return Local AI diagnostic information."""
        return {
            "provider": self.name,
            "model": self.model,
            "available": True,
            "type": "rule_based",
            "offline": True,
            "requires_internet": False,
            "requires_api_key": False,
            "requires_external_server": False,
            "capabilities": [
                "greetings",
                "thanks",
                "basic conversation",
                "current time",
                "current date",
                "simple arithmetic",
                "Banglish basic matching",
            ],
        }


# ============================================================================
# Module-Level Helpers
# ============================================================================


def local_ai_available() -> bool:
    """Return True because LocalAI has no external dependency."""
    return True


def create_local_provider(
    model: str | None = None,
) -> LocalAIProvider:
    """Create a LocalAIProvider instance."""
    return LocalAIProvider(
        model=model,
    )


def local_ai_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the built-in offline provider."""
    try:
        return LocalAIProvider().diagnostics()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "LocalAI diagnostics failed: %s",
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
    "DEFAULT_LOCAL_MODEL",
    "MAX_INPUT_LENGTH",
    "MAX_EXPRESSION_LENGTH",
    "FINISH_RULE_MATCH",
    "FINISH_FALLBACK",

    # Exceptions
    "LocalAIError",
    "LocalAIValidationError",
    "LocalAIMathError",

    # Math
    "safe_calculate",

    # Provider
    "LocalAIProvider",

    # Helpers
    "local_ai_available",
    "create_local_provider",
    "local_ai_diagnostics",
]
