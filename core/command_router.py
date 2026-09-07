"""
command_router.py
==================
Routes a classified intent (see brain/intent.py, brain/classifier.py) to
the correct handler function — usually something in automation/ or
services/ — and normalizes the result into a CommandResult the rest of
the app (dashboard, voice speaker) can present uniformly.

This module deliberately does NOT know how to classify intents; it only
knows how to dispatch an already-classified one. Keeping classification
and routing separate means either half can be swapped/improved
independently (e.g. replace a rule-based classifier with an LLM-based
one without touching a single handler).

Usage:
    from core.command_router import command_router

    command_router.register(IntentCategory.WEATHER, weather_handler)
    result = command_router.dispatch(IntentCategory.WEATHER, "what's the weather in Dhaka")
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config.constants import IntentCategory
from core.event_bus import Events, event_bus
from core.logger import get_logger

logger = get_logger(__name__)

# A handler receives the raw utterance plus any extracted slots/entities,
# and returns a CommandResult.
HandlerFunc = Callable[[str, dict], "CommandResult"]


@dataclass
class CommandResult:
    """Normalized outcome of executing a command handler."""

    success: bool
    message: str = ""              # human-readable response to speak/display
    intent: Optional[IntentCategory] = None
    data: dict = field(default_factory=dict)   # structured payload (e.g. weather data)
    error: Optional[str] = None

    @classmethod
    def ok(cls, message: str, intent: Optional[IntentCategory] = None, **data) -> "CommandResult":
        return cls(success=True, message=message, intent=intent, data=data)

    @classmethod
    def fail(cls, error: str, intent: Optional[IntentCategory] = None, message: str = "") -> "CommandResult":
        return cls(
            success=False,
            message=message or "Sorry, I couldn't complete that.",
            intent=intent,
            error=error,
        )


class CommandRouter:
    """Thread-safe registry mapping IntentCategory -> handler function."""

    def __init__(self) -> None:
        self._handlers: dict[IntentCategory, HandlerFunc] = {}
        self._fallback: Optional[HandlerFunc] = None
        self._middleware: list[Callable[[str, dict], None]] = []
        self._lock = threading.RLock()

    # -- registration -------------------------------------------------------- #

    def register(self, intent: IntentCategory, handler: HandlerFunc, overwrite: bool = True) -> None:
        """
        Register a handler for a given intent category.

        Args:
            overwrite: If False, raises if a handler is already registered
                for this intent (helps catch accidental double-registration
                during plugin loading).
        """
        with self._lock:
            if not overwrite and intent in self._handlers:
                raise ValueError(f"A handler is already registered for intent '{intent}'.")
            self._handlers[intent] = handler
        logger.debug("Registered handler '%s' for intent '%s'.", getattr(handler, "__name__", handler), intent)

    def unregister(self, intent: IntentCategory) -> bool:
        with self._lock:
            return self._handlers.pop(intent, None) is not None

    def set_fallback(self, handler: HandlerFunc) -> None:
        """Set the handler used when no specific intent handler matches (e.g. general chat via AI)."""
        self._fallback = handler

    def add_middleware(self, fn: Callable[[str, dict], None]) -> None:
        """
        Register a middleware callback invoked (utterance, slots) before
        every dispatch — useful for logging, analytics, or auth checks.
        Middleware cannot short-circuit dispatch; use it for side effects only.
        """
        self._middleware.append(fn)

    # -- dispatch -------------------------------------------------------- #

    def dispatch(self, intent: IntentCategory, utterance: str, slots: Optional[dict] = None) -> CommandResult:
        """
        Execute the handler registered for `intent`, falling back to the
        default handler (usually general AI chat) if none is registered.
        """
        slots = slots or {}

        for mw in self._middleware:
            try:
                mw(utterance, slots)
            except Exception:  # noqa: BLE001
                logger.exception("Command middleware raised; continuing dispatch.")

        with self._lock:
            handler = self._handlers.get(intent, self._fallback)

        if handler is None:
            logger.warning("No handler registered for intent '%s' and no fallback set.", intent)
            result = CommandResult.fail(
                error=f"No handler for intent '{intent}'",
                intent=intent,
                message="I'm not sure how to help with that yet.",
            )
        else:
            try:
                result = handler(utterance, slots)
                result.intent = result.intent or intent
            except Exception as exc:  # noqa: BLE001
                logger.exception("Handler for intent '%s' raised an exception.", intent)
                result = CommandResult.fail(error=str(exc), intent=intent)

        event_name = Events.COMMAND_EXECUTED if result.success else Events.COMMAND_FAILED
        event_bus.emit(event_name, {
            "intent": intent.value if isinstance(intent, IntentCategory) else str(intent),
            "utterance": utterance,
            "success": result.success,
            "message": result.message,
        })

        return result

    def is_registered(self, intent: IntentCategory) -> bool:
        with self._lock:
            return intent in self._handlers

    def registered_intents(self) -> list[IntentCategory]:
        with self._lock:
            return list(self._handlers.keys())


# Module-level singleton.
command_router: CommandRouter = CommandRouter()
