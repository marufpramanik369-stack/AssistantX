"""
core/command_router.py
======================

Professional command routing layer for AssistantX.

Responsibilities
----------------
- Route already-classified intents to registered handlers.
- Keep intent classification separate from command execution.
- Normalize handler output into CommandResult.
- Support fallback handlers.
- Support middleware.
- Provide safe synchronous/asynchronous dispatch.
- Emit command lifecycle events through EventBus.
- Maintain lightweight execution statistics.
- Provide diagnostics and introspection.

Architecture
------------
Classifier
    ↓
IntentCategory
    ↓
CommandRouter
    ↓
Handler
    ↓
CommandResult
    ↓
Dashboard / Voice / EventBus

Example
-------
    from core.command_router import command_router
    from config.constants import IntentCategory

    def weather_handler(utterance, slots):
        return CommandResult.ok(
            "The weather is sunny.",
            intent=IntentCategory.WEATHER,
            temperature=32,
        )

    command_router.register(
        IntentCategory.WEATHER,
        weather_handler,
    )

    result = command_router.dispatch(
        IntentCategory.WEATHER,
        "What's the weather?",
    )
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

from config.constants import IntentCategory
from core.event_bus import Events, event_bus
from core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

HandlerFunc = Callable[[str, dict[str, Any]], "CommandResult"]

MiddlewareFunc = Callable[
    [IntentCategory, str, dict[str, Any]],
    None,
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CommandRouterError(Exception):
    """Base exception for command router errors."""


class InvalidIntentError(CommandRouterError):
    """Raised when an invalid intent is supplied."""


class InvalidHandlerError(CommandRouterError):
    """Raised when an invalid command handler is supplied."""


class HandlerAlreadyRegisteredError(CommandRouterError):
    """Raised when duplicate registration is not allowed."""


class HandlerNotFoundError(CommandRouterError):
    """Raised when a requested handler does not exist."""


class RouterShutdownError(CommandRouterError):
    """Raised when using a shutdown router."""


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    """
    Normalized result returned by command handlers.

    Attributes:
        success:
            Whether command execution succeeded.

        message:
            Human-readable message for dashboard/voice.

        intent:
            Intent associated with the result.

        data:
            Structured response payload.

        error:
            Error description when execution fails.

        command_id:
            Unique execution ID.

        duration_ms:
            Handler execution time.

        metadata:
            Additional diagnostic information.
    """

    success: bool

    message: str = ""

    intent: IntentCategory | None = None

    data: dict[str, Any] = field(
        default_factory=dict
    )

    error: str | None = None

    command_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    duration_ms: float | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def ok(
        cls,
        message: str,
        intent: IntentCategory | None = None,
        *,
        data: dict[str, Any] | None = None,
        **extra_data: Any,
    ) -> CommandResult:
        """
        Create a successful CommandResult.

        Both forms are supported:

            CommandResult.ok("Done", data={"x": 1})

        or:

            CommandResult.ok("Done", x=1)
        """

        payload: dict[str, Any] = {}

        if data:
            payload.update(data)

        payload.update(extra_data)

        return cls(
            success=True,
            message=str(message),
            intent=intent,
            data=payload,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        intent: IntentCategory | None = None,
        message: str = "",
        *,
        data: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Create a failed CommandResult."""

        return cls(
            success=False,
            message=(
                message
                or "Sorry, I couldn't complete that."
            ),
            intent=intent,
            data=data or {},
            error=str(error),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result into a JSON-friendly dictionary."""

        return {
            "success": self.success,
            "message": self.message,
            "intent": (
                self.intent.value
                if isinstance(
                    self.intent,
                    IntentCategory,
                )
                else (
                    str(self.intent)
                    if self.intent is not None
                    else None
                )
            ),
            "data": dict(self.data),
            "error": self.error,
            "command_id": self.command_id,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
        }

    def __bool__(self) -> bool:
        """Allow `if result:` style checks."""

        return self.success


# ---------------------------------------------------------------------------
# Handler metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandlerInfo:
    """Metadata about a registered command handler."""

    intent: IntentCategory

    handler_name: str

    module: str

    description: str = ""

    registered_at: str = ""

    priority: int = 0


# ---------------------------------------------------------------------------
# Router statistics
# ---------------------------------------------------------------------------


@dataclass
class RouterStats:
    """Runtime statistics for CommandRouter."""

    total_dispatches: int = 0
    successful_dispatches: int = 0
    failed_dispatches: int = 0
    handler_errors: int = 0
    middleware_errors: int = 0
    fallback_dispatches: int = 0
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_dispatches": self.total_dispatches,
            "successful_dispatches": self.successful_dispatches,
            "failed_dispatches": self.failed_dispatches,
            "handler_errors": self.handler_errors,
            "middleware_errors": self.middleware_errors,
            "fallback_dispatches": self.fallback_dispatches,
            "total_duration_ms": round(
                self.total_duration_ms,
                3,
            ),
            "average_duration_ms": round(
                (
                    self.total_duration_ms
                    / self.total_dispatches
                )
                if self.total_dispatches
                else 0.0,
                3,
            ),
        }


# ---------------------------------------------------------------------------
# Command Router
# ---------------------------------------------------------------------------


class CommandRouter:
    """
    Thread-safe intent → handler router.

    The router does not classify user input. It only executes handlers
    for already-classified intents.
    """

    def __init__(
        self,
        *,
        max_workers: int = 4,
    ) -> None:
        if max_workers < 1:
            raise ValueError(
                "max_workers must be >= 1."
            )

        self._handlers: dict[
            IntentCategory,
            HandlerFunc,
        ] = {}

        self._handler_info: dict[
            IntentCategory,
            HandlerInfo,
        ] = {}

        self._fallback: HandlerFunc | None = None

        self._middleware: list[
            MiddlewareFunc
        ] = []

        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="assistantx-command",
        )

        self._stats = RouterStats()

        self._shutdown = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_intent(
        intent: IntentCategory,
    ) -> IntentCategory:
        if not isinstance(
            intent,
            IntentCategory,
        ):
            raise InvalidIntentError(
                f"Invalid intent: {intent!r}"
            )

        return intent

    @staticmethod
    def _validate_handler(
        handler: HandlerFunc,
    ) -> HandlerFunc:
        if not callable(handler):
            raise InvalidHandlerError(
                "Handler must be callable."
            )

        return handler

    @staticmethod
    def _normalize_slots(
        slots: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if slots is None:
            return {}

        if not isinstance(slots, dict):
            raise TypeError(
                "slots must be a dictionary."
            )

        return dict(slots)

    @staticmethod
    def _normalize_utterance(
        utterance: str,
    ) -> str:
        if utterance is None:
            return ""

        return str(utterance).strip()

    def _ensure_active(self) -> None:
        if self._shutdown:
            raise RouterShutdownError(
                "CommandRouter has been shut down."
            )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        intent: IntentCategory,
        handler: HandlerFunc,
        overwrite: bool = True,
        *,
        description: str = "",
        priority: int = 0,
    ) -> None:
        """
        Register a handler for an intent.

        Args:
            intent:
                IntentCategory handled by the function.

            handler:
                Callable receiving `(utterance, slots)`.

            overwrite:
                Replace an existing handler when True.

            description:
                Optional human-readable description.

            priority:
                Optional handler priority for introspection/future
                plugin systems.
        """

        intent = self._validate_intent(intent)
        handler = self._validate_handler(handler)

        if not isinstance(priority, int):
            raise TypeError(
                "priority must be an integer."
            )

        with self._lock:
            self._ensure_active()

            if (
                not overwrite
                and intent in self._handlers
            ):
                raise HandlerAlreadyRegisteredError(
                    "A handler is already registered "
                    f"for intent '{intent}'."
                )

            self._handlers[intent] = handler

            self._handler_info[intent] = HandlerInfo(
                intent=intent,
                handler_name=getattr(
                    handler,
                    "__name__",
                    handler.__class__.__name__,
                ),
                module=getattr(
                    handler,
                    "__module__",
                    "",
                ),
                description=description.strip(),
                registered_at=(
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
                priority=priority,
            )

        logger.debug(
            "Registered handler '%s' for intent '%s'.",
            self._handler_info[intent].handler_name,
            intent.value,
        )

    def unregister(
        self,
        intent: IntentCategory,
    ) -> bool:
        """Remove a registered handler."""

        intent = self._validate_intent(intent)

        with self._lock:
            removed = (
                self._handlers.pop(
                    intent,
                    None,
                )
                is not None
            )

            self._handler_info.pop(
                intent,
                None,
            )

        if removed:
            logger.debug(
                "Unregistered handler for '%s'.",
                intent.value,
            )

        return removed

    def clear_handlers(self) -> int:
        """Remove all intent-specific handlers."""

        with self._lock:
            count = len(
                self._handlers
            )

            self._handlers.clear()
            self._handler_info.clear()

        logger.debug(
            "Cleared %d command handlers.",
            count,
        )

        return count

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def set_fallback(
        self,
        handler: HandlerFunc | None,
    ) -> None:
        """
        Set or clear the fallback handler.

        Usually this points to general AI conversation.
        """

        if handler is not None:
            handler = self._validate_handler(
                handler
            )

        with self._lock:
            self._ensure_active()
            self._fallback = handler

        logger.debug(
            "Fallback handler %s.",
            "configured"
            if handler
            else "cleared",
        )

    def clear_fallback(self) -> None:
        """Remove the fallback handler."""

        self.set_fallback(None)

    def has_fallback(self) -> bool:
        """Return True when fallback is configured."""

        with self._lock:
            return self._fallback is not None

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    def add_middleware(
        self,
        fn: MiddlewareFunc,
    ) -> None:
        """
        Add middleware executed before every dispatch.

        Middleware receives:

            intent, utterance, slots

        Middleware exceptions are caught and logged.
        They cannot break command execution.
        """

        if not callable(fn):
            raise InvalidHandlerError(
                "Middleware must be callable."
            )

        with self._lock:
            self._ensure_active()

            if fn not in self._middleware:
                self._middleware.append(fn)

        logger.debug(
            "Added command middleware '%s'.",
            getattr(
                fn,
                "__name__",
                repr(fn),
            ),
        )

    def remove_middleware(
        self,
        fn: MiddlewareFunc,
    ) -> bool:
        """Remove a previously registered middleware."""

        with self._lock:
            try:
                self._middleware.remove(fn)
                return True
            except ValueError:
                return False

    def clear_middleware(self) -> int:
        """Remove all middleware."""

        with self._lock:
            count = len(
                self._middleware
            )

            self._middleware.clear()

        return count

    # ------------------------------------------------------------------
    # Handler execution
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_result(
        result: Any,
        intent: IntentCategory,
    ) -> CommandResult:
        """
        Normalize different handler return values.

        Supported:

            CommandResult

            str

            dict

            None
        """

        if isinstance(
            result,
            CommandResult,
        ):
            if result.intent is None:
                result.intent = intent

            return result

        if isinstance(result, str):
            return CommandResult.ok(
                result,
                intent=intent,
            )

        if isinstance(result, dict):
            return CommandResult.ok(
                message=str(
                    result.get(
                        "message",
                        "Command completed.",
                    )
                ),
                intent=intent,
                data=result,
            )

        if result is None:
            return CommandResult.ok(
                "Command completed.",
                intent=intent,
            )

        return CommandResult.ok(
            str(result),
            intent=intent,
            result=result,
        )

    def _run_middleware(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: dict[str, Any],
    ) -> None:
        with self._lock:
            middleware = list(
                self._middleware
            )

        for fn in middleware:
            try:
                fn(
                    intent,
                    utterance,
                    slots,
                )
            except Exception:
                with self._lock:
                    self._stats.middleware_errors += 1

                logger.exception(
                    "Command middleware '%s' failed.",
                    getattr(
                        fn,
                        "__name__",
                        repr(fn),
                    ),
                )

    def _emit_command_event(
        self,
        intent: IntentCategory,
        utterance: str,
        result: CommandResult,
        *,
        used_fallback: bool,
    ) -> None:
        event_name = (
            Events.COMMAND_EXECUTED
            if result.success
            else Events.COMMAND_FAILED
        )

        payload = {
            "command_id": result.command_id,
            "intent": intent.value,
            "utterance": utterance,
            "success": result.success,
            "message": result.message,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "used_fallback": used_fallback,
            "data": result.data,
        }

        try:
            event_bus.emit(
                event_name,
                payload,
            )
        except Exception:
            logger.exception(
                "Failed to emit command event '%s'.",
                event_name,
            )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: dict[str, Any] | None = None,
    ) -> CommandResult:
        """
        Execute the handler registered for an intent.

        If no specific handler exists, the fallback handler is used.

        Handler errors are converted into CommandResult failures.
        """

        intent = self._validate_intent(intent)

        utterance = self._normalize_utterance(
            utterance
        )

        slots = self._normalize_slots(
            slots
        )

        with self._lock:
            self._ensure_active()

        command_id = uuid.uuid4().hex

        started = time.perf_counter()

        self._run_middleware(
            intent,
            utterance,
            slots,
        )

        with self._lock:
            handler = self._handlers.get(
                intent
            )

            used_fallback = False

            if handler is None:
                handler = self._fallback
                used_fallback = (
                    handler is not None
                )

            if used_fallback:
                self._stats.fallback_dispatches += 1

        if handler is None:
            logger.warning(
                "No handler registered for intent '%s' "
                "and no fallback configured.",
                intent.value,
            )

            result = CommandResult.fail(
                error=(
                    f"No handler registered "
                    f"for intent '{intent.value}'."
                ),
                intent=intent,
                message=(
                    "I'm not sure how to help "
                    "with that yet."
                ),
            )

        else:
            try:
                raw_result = handler(
                    utterance,
                    slots,
                )

                result = self._normalize_result(
                    raw_result,
                    intent,
                )

            except Exception as exc:
                with self._lock:
                    self._stats.handler_errors += 1

                logger.exception(
                    "Handler '%s' failed for intent '%s'.",
                    getattr(
                        handler,
                        "__name__",
                        repr(handler),
                    ),
                    intent.value,
                )

                result = CommandResult.fail(
                    error=str(exc),
                    intent=intent,
                )

        duration_ms = (
            time.perf_counter()
            - started
        ) * 1000.0

        result.command_id = command_id
        result.duration_ms = round(
            duration_ms,
            3,
        )

        result.metadata.setdefault(
            "handler",
            getattr(
                handler,
                "__name__",
                None,
            )
            if handler
            else None,
        )

        result.metadata.setdefault(
            "used_fallback",
            used_fallback,
        )

        with self._lock:
            self._stats.total_dispatches += 1

            self._stats.total_duration_ms += (
                duration_ms
            )

            if result.success:
                self._stats.successful_dispatches += 1
            else:
                self._stats.failed_dispatches += 1

        self._emit_command_event(
            intent,
            utterance,
            result,
            used_fallback=used_fallback,
        )

        return result

    # ------------------------------------------------------------------
    # Async dispatch
    # ------------------------------------------------------------------

    def dispatch_async(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: dict[str, Any] | None = None,
    ) -> Future:
        """
        Dispatch a command asynchronously.

        Returns:
            concurrent.futures.Future
        """

        with self._lock:
            self._ensure_active()

        return self._executor.submit(
            self.dispatch,
            intent,
            utterance,
            slots,
        )

    # ------------------------------------------------------------------
    # Lookup / introspection
    # ------------------------------------------------------------------

    def is_registered(
        self,
        intent: IntentCategory,
    ) -> bool:
        """Check whether an intent has a dedicated handler."""

        intent = self._validate_intent(intent)

        with self._lock:
            return intent in self._handlers

    def get_handler(
        self,
        intent: IntentCategory,
    ) -> HandlerFunc | None:
        """Return the handler registered for an intent."""

        intent = self._validate_intent(intent)

        with self._lock:
            return self._handlers.get(
                intent
            )

    def get_handler_info(
        self,
        intent: IntentCategory,
    ) -> HandlerInfo | None:
        """Return metadata for an intent handler."""

        intent = self._validate_intent(intent)

        with self._lock:
            return self._handler_info.get(
                intent
            )

    def registered_intents(
        self,
    ) -> list[IntentCategory]:
        """Return all registered intents."""

        with self._lock:
            return list(
                self._handlers.keys()
            )

    def handler_infos(
        self,
    ) -> list[HandlerInfo]:
        """Return metadata for all registered handlers."""

        with self._lock:
            return list(
                self._handler_info.values()
            )

    def handler_count(self) -> int:
        """Return number of registered handlers."""

        with self._lock:
            return len(
                self._handlers
            )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return router statistics."""

        with self._lock:
            data = self._stats.to_dict()

            data.update(
                {
                    "registered_handlers": len(
                        self._handlers
                    ),
                    "middleware_count": len(
                        self._middleware
                    ),
                    "fallback_configured": (
                        self._fallback
                        is not None
                    ),
                    "shutdown": self._shutdown,
                }
            )

            return data

    def reset_stats(self) -> None:
        """Reset runtime statistics."""

        with self._lock:
            self._stats = RouterStats()

        logger.debug(
            "CommandRouter statistics reset."
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed router diagnostics."""

        with self._lock:
            handlers = {}

            for intent, info in (
                self._handler_info.items()
            ):
                handlers[
                    intent.value
                ] = {
                    "handler": info.handler_name,
                    "module": info.module,
                    "description": info.description,
                    "priority": info.priority,
                    "registered_at": info.registered_at,
                }

            return {
                "module": __name__,
                "class": self.__class__.__name__,
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "registered_handlers": len(
                    self._handlers
                ),
                "middleware_count": len(
                    self._middleware
                ),
                "fallback_configured": (
                    self._fallback
                    is not None
                ),
                "handlers": handlers,
                "stats": self._stats.to_dict(),
            }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(
        self,
        *,
        wait: bool = True,
    ) -> None:
        """
        Gracefully shut down the router's async executor.

        Existing synchronous operations are unaffected.
        """

        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True

            self._handlers.clear()
            self._handler_info.clear()
            self._middleware.clear()
            self._fallback = None

        logger.debug(
            "CommandRouter shutting down."
        )

        self._executor.shutdown(
            wait=wait,
            cancel_futures=True,
        )

        logger.debug(
            "CommandRouter shutdown complete."
        )

    @property
    def is_running(self) -> bool:
        """Return True when router is active."""

        with self._lock:
            return not self._shutdown

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        with self._lock:
            self._ensure_active()

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.shutdown()

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"{self.__class__.__name__}("
                f"running={not self._shutdown}, "
                f"handlers={len(self._handlers)}, "
                f"middleware={len(self._middleware)}"
                f")"
            )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

command_router = CommandRouter()


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------


def register_command(
    intent: IntentCategory,
    handler: HandlerFunc,
    *,
    overwrite: bool = True,
    description: str = "",
    priority: int = 0,
) -> None:
    """Register a command on the global router."""

    command_router.register(
        intent,
        handler,
        overwrite=overwrite,
        description=description,
        priority=priority,
    )


def unregister_command(
    intent: IntentCategory,
) -> bool:
    """Unregister a command."""

    return command_router.unregister(
        intent
    )


def dispatch_command(
    intent: IntentCategory,
    utterance: str,
    slots: dict[str, Any] | None = None,
) -> CommandResult:
    """Dispatch using the global router."""

    return command_router.dispatch(
        intent,
        utterance,
        slots,
    )


def dispatch_command_async(
    intent: IntentCategory,
    utterance: str,
    slots: dict[str, Any] | None = None,
) -> Future:
    """Asynchronously dispatch using the global router."""

    return command_router.dispatch_async(
        intent,
        utterance,
        slots,
    )


def command_router_diagnostics() -> dict[str, Any]:
    """Return global CommandRouter diagnostics."""

    return command_router.diagnostics()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Models
    "CommandResult",
    # Router
    "CommandRouter",
    # Exceptions
    "CommandRouterError",
    "HandlerAlreadyRegisteredError",
    # Types
    "HandlerFunc",
    "HandlerInfo",
    "HandlerNotFoundError",
    "InvalidHandlerError",
    "InvalidIntentError",
    "MiddlewareFunc",
    "RouterShutdownError",
    "RouterStats",
    "command_router",
    "command_router_diagnostics",
    "dispatch_command",
    "dispatch_command_async",
    # Convenience API
    "register_command",
    "unregister_command",
]
