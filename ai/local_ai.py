"""
ai/local_ai.py (IMPROVED VERSION)
=================================
Dependency-free offline fallback provider for AssistantX.

This provider is intentionally NOT a real language model.

Its purpose is to keep AssistantX minimally useful when:
- Gemini is unavailable
- No API key is configured
- Internet is offline
- Ollama is not running
- No local LLM backend is available

Supported Offline Capabilities
------------------------------
- Greetings (English + Bangla/Banglish)
- Thanks and acknowledgments
- Basic identity/help questions
- Current time/date retrieval
- Simple arithmetic evaluation (+, -, *, /, %, ^)
- Banglish-friendly common phrases
- Safe fallback responses

Philosophy
----------
This module never pretends to understand complex questions or hallucinate answers.
If a request requires a real language model, it clearly informs the user.
No external dependencies are required.
Safe arithmetic evaluation uses AST parsing, never eval().

Thread Safety
-------------
The provider is thread-safe. Pattern matching is read-only.
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
from dataclasses import dataclass
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

# Input validation
MAX_INPUT_LENGTH = 10_000
MAX_EXPRESSION_LENGTH = 250
MAX_AST_DEPTH = 32
MAX_POWER_EXPONENT = 100

# Finish reasons
FINISH_RULE_MATCH = "offline_rule_match"
FINISH_FALLBACK = "offline_fallback"
FINISH_MATH_RESULT = "offline_math"


# ============================================================================
# Exceptions
# ============================================================================


class LocalAIError(RuntimeError):
    """Base exception for the local rule-based provider."""



class LocalAIValidationError(LocalAIError, ProviderValidationError):
    """Raised when local AI input validation fails."""




class LocalAIMathError(LocalAIError):
    """Raised when offline arithmetic evaluation fails safely."""




# ============================================================================
# Pattern Definitions
# ============================================================================

# Greeting pattern (English + Bangla/Banglish)
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

# Thanks/acknowledgment pattern
_THANKS_PATTERN = re.compile(
    r"\b("
    r"thanks|thank\s+you|thankyou|thx|ty|"
    r"dhonnobad|dhonyobad|"
    r"ধন্যবাদ|থ্যাংকস"
    r")\b",
    re.IGNORECASE,
)

# Time query pattern
_TIME_PATTERN = re.compile(
    r"("
    r"\bwhat\s+time\b|"
    r"\bcurrent\s+time\b|"
    r"\btime\s+now\b|"
    r"\bwhat(?:'s|\s+is)\s+the\s+time\b|"
    r"\bkoyta\s+baje\b|"
    r"\bkoto\s+baje\b|"
    r"\btime\s+koto\b|"
    r"কয়টা\s+বাজে|কটা\s+বাজে|সময়\s+কত"
    r")",
    re.IGNORECASE,
)

# Date query pattern
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

# Identity query pattern
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

# Help/capabilities pattern
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

# "How are you" pattern
_HOW_ARE_YOU_PATTERN = re.compile(
    r"("
    r"\bhow\s+are\s+you\b|"
    r"\bkemon\s+acho\b|"
    r"\bkemon\s+aso\b|"
    r"কেমন\s+আছ"
    r")",
    re.IGNORECASE,
)

# Offline status query pattern
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

# Math prefix pattern (to extract expression)
_MATH_PREFIX_PATTERN = re.compile(
    r"^\s*(?:"
    r"calculate|calc|compute|solve|"
    r"what\s+is|"
    r"koto|hisab|hisab\s+koro|"
    r"হিসাব|হিসাব\s+কর"
    r")\s*[:\-]?\s*",
    re.IGNORECASE,
)

# Math allowed characters (digits, operators, parentheses)
_MATH_ALLOWED_PATTERN = re.compile(r"^[\d\s+\-*/().%^]+$")


# ============================================================================
# Response Strings
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
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class LocalAICapabilities:
    """
    LocalAI provider capabilities information.

    Attributes
    ----------
    greetings : bool
        Recognizes greetings
    thanks : bool
        Recognizes thanks
    time : bool
        Can return current time
    date : bool
        Can return current date
    arithmetic : bool
        Can evaluate simple math
    offline : bool
        Requires no internet
    requires_dependencies : bool
        Requires external packages
    """

    greetings: bool = True
    thanks: bool = True
    time: bool = True
    date: bool = True
    arithmetic: bool = True
    offline: bool = True
    requires_dependencies: bool = False


# ============================================================================
# Safe Arithmetic Evaluation
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
    """
    Calculate maximum depth of an AST node.

    Parameters
    ----------
    node : ast.AST
        AST node to analyze

    Returns
    -------
    int
        Maximum depth (1 for leaf nodes)
    """

    children = list(ast.iter_child_nodes(node))

    return 1 + max(_ast_depth(child) for child in children) if children else 1


def _evaluate_binary_node(node: ast.BinOp) -> int | float:
    """Evaluate a supported binary arithmetic operation."""

    operator_type = type(node.op)

    if operator_type not in _BINARY_OPERATORS:
        raise LocalAIMathError(
            f"Unsupported arithmetic operator: {node.op.__class__.__name__}."
        )

    left = _evaluate_math_node(node.left)
    right = _evaluate_math_node(node.right)

    # Limit exponent size
    if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER_EXPONENT:
        raise LocalAIMathError(
            f"Exponent is too large: {right} (max: {MAX_POWER_EXPONENT})."
        )

    try:
        result = _BINARY_OPERATORS[operator_type](left, right)

    except ZeroDivisionError as exc:
        raise LocalAIMathError(
            "Division by zero is not allowed."
        ) from exc

    except OverflowError as exc:
        raise LocalAIMathError(
            "Calculation result overflowed."
        ) from exc

    # Validate result
    if isinstance(result, float) and not math.isfinite(result):
        raise LocalAIMathError(
            "Calculation produced a non-finite result."
        )

    return result


def _evaluate_math_node(node: ast.AST) -> int | float:
    """
    Safely evaluate a restricted arithmetic AST.

    No eval() or exec() is used. Only basic math operations allowed.

    Parameters
    ----------
    node : ast.AST
        AST node to evaluate

    Returns
    -------
    int or float
        Evaluation result

    Raises
    ------
    LocalAIMathError
        If evaluation fails
    """

    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)

    # Constant values
    if isinstance(node, ast.Constant):
        value = node.value

        # Reject booleans and non-numeric types
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LocalAIMathError(
                "Only numeric constants are allowed (got non-numeric)."
            )

        # Reject non-finite numbers
        if isinstance(value, float) and not math.isfinite(value):
            raise LocalAIMathError(
                "Non-finite numbers (NaN, inf) are not allowed."
            )

        return value

    # Binary operations
    if isinstance(node, ast.BinOp):
        return _evaluate_binary_node(node)

    # Unary operations
    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)

        if operator_type not in _UNARY_OPERATORS:
            raise LocalAIMathError(
                f"Unsupported unary operator: {node.op.__class__.__name__}."
            )

        operand = _evaluate_math_node(node.operand)

        return _UNARY_OPERATORS[operator_type](operand)

    raise LocalAIMathError(
        f"Unsupported expression element: {node.__class__.__name__}."
    )


def safe_calculate(expression: str) -> int | float:
    """
    Safely evaluate a simple arithmetic expression.

    Supported operations: +, -, *, /, //, %, ** (power)
    Supports parentheses for grouping.
    Uses AST parsing, never eval().

    Parameters
    ----------
    expression : str
        Arithmetic expression to evaluate

    Returns
    -------
    int or float
        Calculation result

    Raises
    ------
    LocalAIValidationError
        If expression format is invalid
    LocalAIMathError
        If evaluation fails

    Examples
    --------
    >>> safe_calculate("10 + 5 * 2")
    20.0
    >>> safe_calculate("2 ** 3")
    8.0
    """

    if not isinstance(expression, str):
        raise LocalAIValidationError(
            f"Math expression must be a string, got {type(expression).__name__}."
        )

    expression = expression.strip()

    if not expression:
        raise LocalAIValidationError(
            "Math expression cannot be empty."
        )

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise LocalAIValidationError(
            f"Math expression exceeds {MAX_EXPRESSION_LENGTH} characters "
            f"(got {len(expression)})."
        )

    # User-friendly ^ means exponent
    expression = expression.replace("^", "**")

    # Validate characters
    if not _MATH_ALLOWED_PATTERN.fullmatch(expression):
        raise LocalAIMathError(
            "Expression contains unsupported characters. "
            "Only digits, operators (+,-,*,/,//,%,^), and parentheses are allowed."
        )

    try:
        tree = ast.parse(expression, mode="eval")

    except SyntaxError as exc:
        raise LocalAIMathError(
            f"Invalid arithmetic expression: {exc.msg}"
        ) from exc

    # Check AST depth to prevent pathological cases
    if _ast_depth(tree) > MAX_AST_DEPTH:
        raise LocalAIMathError(
            f"Arithmetic expression is too complex (depth > {MAX_AST_DEPTH})."
        )

    result = _evaluate_math_node(tree)

    logger.debug(
        "Evaluated arithmetic: %r = %s",
        expression,
        result,
    )

    return result


# ============================================================================
# Input Helpers
# ============================================================================


def _normalize_user_text(text: str) -> str:
    """
    Normalize input text for pattern matching.

    - Strips whitespace
    - Collapses multiple spaces
    - Preserves case for case-insensitive regex matching

    Parameters
    ----------
    text : str
        Text to normalize

    Returns
    -------
    str
        Normalized text
    """

    if not isinstance(text, str):
        logger.debug("Non-string input to normalize_user_text: %s", type(text))

        return ""

    normalized = " ".join(text.strip().split())

    logger.debug("Normalized text: %r -> %r", text[:50], normalized[:50])

    return normalized


def _extract_math_expression(text: str) -> str:
    """
    Extract arithmetic expression from user input.

    Removes common math query prefixes.

    Parameters
    ----------
    text : str
        User input

    Returns
    -------
    str
        Extracted expression or empty string

    Examples
    --------
    >>> _extract_math_expression("calculate 2 + 2")
    '2 + 2'
    >>> _extract_math_expression("what is 5 * 8")
    '5 * 8'
    """

    cleaned = _normalize_user_text(text)

    # Remove math prefix
    cleaned = _MATH_PREFIX_PATTERN.sub("", cleaned, count=1)

    # Remove trailing question mark
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1].strip()

    logger.debug("Extracted math expression: %r", cleaned)

    return cleaned


def _format_number(value: float) -> str:
    """
    Format arithmetic result for display.

    Parameters
    ----------
    value : float
        Number to format

    Returns
    -------
    str
        Formatted number string
    """

    if isinstance(value, float):
        # Show as integer if whole number
        return str(int(value)) if value.is_integer() else f"{value:.12g}"

    return str(value)


# ============================================================================
# Local AI Provider Implementation
# ============================================================================


class LocalAIProvider(AIProviderBase):
    """
    Dependency-free AssistantX offline fallback provider.

    This provider is always considered available because:
    - No API key required
    - No internet connection required
    - No external server required
    - No external Python packages required

    It is deliberately conservative and never hallucinate answers.

    Attributes
    ----------
    name : str
        Provider name (always "local")
    model : str
        Model identifier (always "rule-based-v2")
    """

    name = PROVIDER_NAME
    default_model = DEFAULT_LOCAL_MODEL

    @staticmethod
    def _current_datetime(format_string: str) -> str:
        """Return the current local date/time using the requested format."""

        return datetime.now().strftime(format_string)

    def _datetime_response(self, prefix: str, format_string: str) -> str:
        """Build a response containing the current local date or time."""

        return f"{prefix}{self._current_datetime(format_string)}."

    def __init__(
        self,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize LocalAI provider.

        Parameters
        ----------
        model : str or None
            Model ID (default: rule-based-v2)
        **kwargs
            Other parameters (ignored)
        """

        super().__init__(
            model=model or self.default_model,
            **kwargs,
        )

        logger.info(
            "Initialized LocalAIProvider: model=%r",
            self.model,
        )

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        LocalAI is always available (no dependencies).

        Returns
        -------
        bool
            Always True
        """

        logger.debug("LocalAI provider is always available (no dependencies).")

        return True

    def health_check(self) -> bool:
        """
        Health check (always succeeds).

        Returns
        -------
        bool
            Always True
        """

        return True

    # ------------------------------------------------------------------
    # Message Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _last_user_message(messages: Sequence[ChatMessage]) -> str:
        """
        Extract the most recent user message.

        Parameters
        ----------
        messages : Sequence[ChatMessage]
            Conversation messages

        Returns
        -------
        str
            Most recent user message or empty string
        """

        for message in reversed(messages):
            if message.role == Role.USER and (content := message.content.strip()):
                return content

        logger.debug("No user message found in conversation.")

        return ""

    def _try_math(self, text: str) -> str | None:
        """
        Attempt to evaluate simple arithmetic.

        Returns None if not an arithmetic request or evaluation fails.

        Parameters
        ----------
        text : str
            User input

        Returns
        -------
        str or None
            Formatted result or None
        """

        expression = _extract_math_expression(text)

        if not expression:
            return None

        # Avoid attempting math on ordinary messages
        if not _MATH_ALLOWED_PATTERN.fullmatch(expression.replace("^", "**")):
            logger.debug("Expression contains non-math characters: %r", expression)

            return None

        # Require at least one operator
        if all(
            op not in expression for op in ("+", "-", "*", "/", "%", "^")
        ):
            logger.debug("Expression has no operators: %r", expression)

            return None

        try:
            result = safe_calculate(expression)

            formatted = (
                f"{expression} = {_format_number(result)}"
            )

            logger.info("Math evaluation: %s", formatted)

            return formatted

        except (LocalAIMathError, LocalAIValidationError) as exc:
            logger.debug(
                "Offline math evaluation failed for %r: %s",
                expression,
                exc,
            )

            return None

    # ------------------------------------------------------------------
    # Rule Engine
    # ------------------------------------------------------------------

    def _respond(self, user_text: str) -> tuple[str, str]:
        """
        Generate a rule-based response.

        More specific rules are checked before general fallbacks.

        Parameters
        ----------
        user_text : str
            User input

        Returns
        -------
        tuple[str, str]
            (response_text, finish_reason)
        """

        normalized = _normalize_user_text(user_text)

        if not normalized:
            logger.debug("Empty user text after normalization.")

            return (
                "I didn't receive a message.",
                FINISH_FALLBACK,
            )

        if len(normalized) > MAX_INPUT_LENGTH:
            logger.debug(
                "User input exceeds max length: %d > %d",
                len(normalized),
                MAX_INPUT_LENGTH,
            )

            return (
                f"That message is too long for AssistantX's "
                f"basic offline mode (max: {MAX_INPUT_LENGTH} characters).",
                FINISH_FALLBACK,
            )

        # Check patterns in order (specific before general)

        if _TIME_PATTERN.search(normalized):
            logger.debug("Matched time pattern.")

            return (
                self._datetime_response(
                    "It's currently ",
                    TIME_DISPLAY_FORMAT,
                ),
                FINISH_RULE_MATCH,
            )

        if _DATE_PATTERN.search(normalized):
            logger.debug("Matched date pattern.")

            return (
                self._datetime_response(
                    "Today is ",
                    DATE_DISPLAY_FORMAT,
                ),
                FINISH_RULE_MATCH,
            )

        if _IDENTITY_PATTERN.search(normalized):
            logger.debug("Matched identity pattern.")

            return (
                random.choice(_IDENTITY_RESPONSES),
                FINISH_RULE_MATCH,
            )

        if _HELP_PATTERN.search(normalized):
            logger.debug("Matched help pattern.")

            return (
                _HELP_RESPONSE,
                FINISH_RULE_MATCH,
            )

        if _OFFLINE_STATUS_PATTERN.search(normalized):
            logger.debug("Matched offline status pattern.")

            return (
                _OFFLINE_STATUS_RESPONSE,
                FINISH_RULE_MATCH,
            )

        if _HOW_ARE_YOU_PATTERN.search(normalized):
            logger.debug("Matched 'how are you' pattern.")

            return (
                random.choice(_HOW_ARE_YOU_RESPONSES),
                FINISH_RULE_MATCH,
            )

        if _THANKS_PATTERN.search(normalized):
            logger.debug("Matched thanks pattern.")

            return (
                random.choice(_THANKS_RESPONSES),
                FINISH_RULE_MATCH,
            )

        if _GREETING_PATTERN.search(normalized):
            logger.debug("Matched greeting pattern.")

            return (
                random.choice(_GREETING_RESPONSES),
                FINISH_RULE_MATCH,
            )

        # Try arithmetic
        math_result = self._try_math(normalized)

        if math_result is not None:
            logger.debug("Successfully evaluated math expression.")

            return (
                math_result,
                FINISH_MATH_RESULT,
            )

        # Fallback response
        logger.debug("No patterns matched; using fallback response.")

        return (
            random.choice(_FALLBACK_RESPONSES),
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

        Parameters
        ----------
        messages : list[ChatMessage]
            Conversation messages
        **kwargs
            Ignored

        Returns
        -------
        CompletionResult
            Response with rule-based finish reason
        """

        del kwargs  # Not used by rule engine

        start = time.monotonic()

        try:
            normalized_messages = normalize_messages(messages)

            if user_text := self._last_user_message(normalized_messages):
                response_text, finish_reason = self._respond(user_text)
            else:
                response_text = (
                    "I couldn't find a user message to respond to."
                )
                finish_reason = FINISH_FALLBACK

        except Exception as exc:
            logger.exception("LocalAI generation failed: %s", exc)

            response_text = (
                "An error occurred in offline mode. "
                "Please check your internet and try a cloud provider."
            )
            finish_reason = FINISH_FALLBACK

        elapsed = time.monotonic() - start

        logger.info(
            "LocalAI generation complete: %.2f seconds, finish=%s",
            elapsed,
            finish_reason,
        )

        return CompletionResult(
            text=response_text,
            provider=self.name,
            model=self.model,
            latency_seconds=elapsed,
            finish_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    # Streaming (not supported)
    # ------------------------------------------------------------------

    def stream(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ):
        """
        LocalAI doesn't support streaming.

        This method is provided for compatibility but raises NotImplementedError.

        Raises
        ------
        NotImplementedError
            Streaming is not supported
        """

        raise NotImplementedError(
            "LocalAI offline provider does not support streaming. "
            "Use a real AI provider (Gemini, Ollama) for streaming responses."
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Get LocalAI provider diagnostics.

        Returns
        -------
        dict
            JSON-friendly diagnostics
        """

        capabilities = LocalAICapabilities()

        diags = {
            "provider": self.name,
            "model": self.model,
            "available": True,
            "type": "rule_based_offline",
            "offline": True,
            "requires_internet": False,
            "requires_api_key": False,
            "requires_external_server": False,
            "requires_external_dependencies": False,
            "capabilities": {
                "greetings": capabilities.greetings,
                "thanks": capabilities.thanks,
                "time": capabilities.time,
                "date": capabilities.date,
                "arithmetic": capabilities.arithmetic,
                "streaming": False,
            },
        }

        logger.debug("LocalAI diagnostics: %s", diags)

        return diags


# ============================================================================
# Module-Level Helpers
# ============================================================================


def local_ai_available() -> bool:
    """
    Check if LocalAI provider is available.

    Returns True because LocalAI has no external dependencies.

    Returns
    -------
    bool
        Always True
    """

    logger.debug("LocalAI is always available (no dependencies).")

    return True


def create_local_provider(
    model: str | None = None,
) -> LocalAIProvider:
    """
    Factory function to create a LocalAIProvider.

    Parameters
    ----------
    model : str or None
        Model ID (default: rule-based-v2)

    Returns
    -------
    LocalAIProvider
        Configured provider instance
    """

    return LocalAIProvider(model=model)


def local_ai_diagnostics() -> dict[str, Any]:
    """
    Get LocalAI provider diagnostics.

    Returns
    -------
    dict
        Provider diagnostics
    """

    try:
        provider = LocalAIProvider()

        return provider.diagnostics()

    except Exception as exc:
        logger.error("LocalAI diagnostics failed: %s", exc)

        return {
            "provider": PROVIDER_NAME,
            "available": False,
            "error": str(exc),
        }


def get_local_model() -> str:
    """
    Get the LocalAI model name.

    Returns
    -------
    str
        Model name
    """

    return DEFAULT_LOCAL_MODEL


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
    "FINISH_MATH_RESULT",

    # Exceptions
    "LocalAIError",
    "LocalAIValidationError",
    "LocalAIMathError",

    # Dataclasses
    "LocalAICapabilities",

    # Math evaluation
    "safe_calculate",

    # Provider class
    "LocalAIProvider",

    # Helper functions
    "local_ai_available",
    "create_local_provider",
    "local_ai_diagnostics",
    "get_local_model",
]
