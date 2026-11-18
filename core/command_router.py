"""
core/command_router.py — AssistantX Command Routing Layer
===========================================================

Production-grade intent-to-handler routing layer for AssistantX.

Responsibilities
----------------
• Route classified IntentCategory values to command handlers.
• Maintain a safe global fallback handler.
• Execute optional middleware before dispatch.
• Support synchronous and asynchronous dispatch.
• Normalize handler return values into CommandResult.
• Emit command execution/failure events.
• Maintain thread-safe runtime statistics.
• Provide handler introspection and diagnostics.
• Support graceful shutdown and context-manager usage.

Architecture
------------

    User Input
        ↓
    Brain / Classifier
        ↓
    IntentCategory
        ↓
    CommandRouter
        ├── Middleware
        ├── Registered Handler
        │       OR
        └── Fallback Handler
        ↓
    CommandResult
        ↓
    Event Bus / Assistant / Dashboard

Handler contract
----------------

    handler(
        utterance: str,
        slots: dict[str, Any],
    ) -> CommandResult | str | dict | None

Thread safety
-------------

All mutable router state is protected by RLock.

Important:
    The router lock is never held while executing user handlers or
    middleware. This prevents long-running handlers from blocking
    registration, diagnostics, or unrelated dispatch calls.

Compatibility
-------------

The public API intentionally preserves the established AssistantX
interfaces:

    CommandResult
    HandlerInfo
    RouterStats
    CommandRouter
    command_router

    register_command()
    unregister_command()
    dispatch_command()
    dispatch_command_async()
    command_router_diagnostics()
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from config.constants import IntentCategory
from core.event_bus import Events, event_bus
from core.logger import get_logger


logger = get_logger(__name__)


# ============================================================================
# Type aliases
# ============================================================================

HandlerFunc = Callable[
    [str, dict[str, Any]],
    Any,
]

MiddlewareFunc = Callable[
    [IntentCategory, str, dict[str, Any]],
    None,
]


# ============================================================================
# Exceptions
# ============================================================================


class CommandRouterError(Exception):
    """Base exception for CommandRouter errors."""


class InvalidIntentError(CommandRouterError):
    """Raised when an invalid intent is supplied."""


class InvalidHandlerError(CommandRouterError):
    """Raised when a non-callable handler or middleware is supplied."""


class HandlerAlreadyRegisteredError(CommandRouterError):
    """Raised when duplicate registration is explicitly disallowed."""


class HandlerNotFoundError(CommandRouterError):
    """Raised when a requested handler does not exist."""


class RouterShutdownError(CommandRouterError):
    """Raised when an operation is attempted on a shut-down router."""


# ============================================================================
# Command result
# ============================================================================


@dataclass
class CommandResult:
    """
    Normalized result returned by a command handler.

    Attributes
    ----------
    success:
        Whether command execution succeeded.

    message:
        User-facing response text.

    intent:
        Intent associated with the command.

    data:
        Structured response data.

    error:
        Technical error description when execution fails.

    command_id:
        Unique command execution identifier.

    duration_ms:
        Total dispatch duration in milliseconds.

    metadata:
        Diagnostic/runtime metadata.
    """

    success: bool

    message: str = ""

    intent: Optional[IntentCategory] = None

    data: dict[str, Any] = field(
        default_factory=dict
    )

    error: Optional[str] = None

    command_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    duration_ms: Optional[float] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def ok(
        cls,
        message: str,
        intent: Optional[IntentCategory] = None,
        *,
        data: Optional[dict[str, Any]] = None,
        **extra_data: Any,
    ) -> "CommandResult":
        """
        Create a successful command result.

        ``data=`` and keyword payload are merged. Keyword payload wins
        when the same key exists.
        """

        payload: dict[str, Any] = {}

        if isinstance(data, dict):
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
        intent: Optional[IntentCategory] = None,
        message: str = "",
        *,
        data: Optional[dict[str, Any]] = None,
    ) -> "CommandResult":
        """Create a failed command result."""

        return cls(
            success=False,
            message=(
                str(message)
                if message
                else "Sorry, I couldn't complete that."
            ),
            intent=intent,
            data=dict(data) if isinstance(data, dict) else {},
            error=str(error),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        if isinstance(self.intent, IntentCategory):
            intent_value = self.intent.value
        elif self.intent is None:
            intent_value = None
        else:
            intent_value = str(self.intent)

        return {
            "success": bool(self.success),
            "message": str(self.message),
            "intent": intent_value,
            "data": dict(self.data),
            "error": self.error,
            "command_id": self.command_id,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
        }

    def __bool__(self) -> bool:
        """Allow ``if result:`` success checks."""

        return bool(self.success)


# ============================================================================
# Handler metadata
# ============================================================================


@dataclass(frozen=True)
class HandlerInfo:
    """Read-only metadata describing a registered handler."""

    intent: IntentCategory

    handler_name: str

    module: str

    description: str = ""

    registered_at: str = ""

    priority: int = 0


# ============================================================================
# Router statistics
# ============================================================================


@dataclass
class RouterStats:
    """Mutable runtime statistics for CommandRouter."""

    total_dispatches: int = 0

    successful_dispatches: int = 0

    failed_dispatches: int = 0

    handler_errors: int = 0

    middleware_errors: int = 0

    fallback_dispatches: int = 0

    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return calculated statistics as a dictionary."""

        total = self.total_dispatches

        average = (
            self.total_duration_ms / total
            if total
            else 0.0
        )

        success_rate = (
            self.successful_dispatches / total
            if total
            else 0.0
        )

        return {
            "total_dispatches": total,
            "successful_dispatches": (
                self.successful_dispatches
            ),
            "failed_dispatches": (
                self.failed_dispatches
            ),
            "handler_errors": self.handler_errors,
            "middleware_errors": self.middleware_errors,
            "fallback_dispatches": (
                self.fallback_dispatches
            ),
            "total_duration_ms": round(
                self.total_duration_ms,
                3,
            ),
            "average_duration_ms": round(
                average,
                3,
            ),
            "success_rate": round(
                success_rate,
                4,
            ),
        }


# ============================================================================
# Command router
# ============================================================================


class CommandRouter:
    """
    Thread-safe intent-to-handler command router.

    The router does not perform intent classification. It receives an
    already-classified IntentCategory and determines which handler should
    execute.
    """

    def __init__(
        self,
        *,
        max_workers: int = 4,
        thread_name_prefix: str = "assistantx-command",
    ) -> None:

        if not isinstance(max_workers, int):
            raise TypeError(
                "max_workers must be an integer"
            )

        if max_workers < 1:
            raise ValueError(
                "max_workers must be >= 1"
            )

        if not isinstance(thread_name_prefix, str):
            raise TypeError(
                "thread_name_prefix must be a string"
            )

        self._handlers: dict[
            IntentCategory,
            HandlerFunc,
        ] = {}

        self._handler_info: dict[
            IntentCategory,
            HandlerInfo,
        ] = {}

        self._fallback: Optional[HandlerFunc] = None

        self._middleware: list[
            MiddlewareFunc
        ] = []

        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )

        self._stats = RouterStats()

        self._shutdown = False

        self._max_workers = max_workers

        self._thread_name_prefix = (
            thread_name_prefix
        )

        logger.debug(
            "CommandRouter initialized "
            "(workers=%d)",
            max_workers,
        )

    # ========================================================================
    # Validation
    # ========================================================================

    @staticmethod
    def _validate_intent(
        intent: IntentCategory,
    ) -> IntentCategory:
        """Validate and return an IntentCategory."""

        if not isinstance(
            intent,
            IntentCategory,
        ):
            raise InvalidIntentError(
                "intent must be an IntentCategory "
                f"(got {type(intent).__name__})"
            )

        return intent

    @staticmethod
    def _validate_handler(
        handler: Any,
    ) -> HandlerFunc:
        """Validate and return a callable handler."""

        if not callable(handler):
            raise InvalidHandlerError(
                "handler must be callable "
                f"(got {type(handler).__name__})"
            )

        return handler

    @staticmethod
    def _normalize_slots(
        slots: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate and copy command slots."""

        if slots is None:
            return {}

        if not isinstance(slots, dict):
            raise TypeError(
                "slots must be dict or None "
                f"(got {type(slots).__name__})"
            )

        return dict(slots)

    @staticmethod
    def _normalize_utterance(
        utterance: Any,
    ) -> str:
        """Normalize command utterance."""

        if utterance is None:
            return ""

        return str(utterance).strip()

    def _ensure_active(self) -> None:
        """Raise if router is shut down."""

        if self._shutdown:
            raise RouterShutdownError(
                "CommandRouter has been shut down"
            )

    # ========================================================================
    # Registration
    # ========================================================================

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

        Parameters
        ----------
        intent:
            IntentCategory handled by the function.

        handler:
            Callable accepting ``(utterance, slots)``.

        overwrite:
            Replace an existing handler when True.

        description:
            Human-readable handler description.

        priority:
            Metadata priority value.
        """

        intent = self._validate_intent(intent)

        handler = self._validate_handler(
            handler
        )

        if not isinstance(priority, int):
            raise TypeError(
                "priority must be an integer"
            )

        description = str(
            description or ""
        ).strip()

        handler_name = getattr(
            handler,
            "__name__",
            handler.__class__.__name__,
        )

        module = getattr(
            handler,
            "__module__",
            "",
        )

        with self._lock:

            self._ensure_active()

            if (
                not overwrite
                and intent in self._handlers
            ):
                raise HandlerAlreadyRegisteredError(
                    "Handler already registered for "
                    f"'{intent.value}'"
                )

            self._handlers[intent] = handler

            self._handler_info[intent] = HandlerInfo(
                intent=intent,
                handler_name=str(
                    handler_name
                ),
                module=str(module),
                description=description,
                registered_at=(
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
                priority=priority,
            )

        logger.info(
            "Registered command handler "
            "'%s' → '%s'",
            handler_name,
            intent.value,
        )

    def unregister(
        self,
        intent: IntentCategory,
    ) -> bool:
        """Remove a registered intent handler."""

        intent = self._validate_intent(
            intent
        )

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
            logger.info(
                "Unregistered handler for '%s'",
                intent.value,
            )

        return removed

    def clear_handlers(self) -> int:
        """Remove all registered intent handlers."""

        with self._lock:

            count = len(
                self._handlers
            )

            self._handlers.clear()
            self._handler_info.clear()

        logger.info(
            "Cleared %d command handler(s)",
            count,
        )

        return count

    # ========================================================================
    # Fallback
    # ========================================================================

    def set_fallback(
        self,
        handler: Optional[HandlerFunc],
    ) -> None:
        """
        Set the fallback handler.

        ``None`` clears the fallback.
        """

        if handler is not None:
            handler = self._validate_handler(
                handler
            )

        with self._lock:

            self._ensure_active()

            self._fallback = handler

        logger.debug(
            "Fallback handler: %s",
            (
                getattr(
                    handler,
                    "__name__",
                    repr(handler),
                )
                if handler is not None
                else "None"
            ),
        )

    def clear_fallback(self) -> None:
        """Remove the fallback handler."""

        self.set_fallback(None)

    def has_fallback(self) -> bool:
        """Return whether a fallback is configured."""

        with self._lock:
            return self._fallback is not None

    def get_fallback(
        self,
    ) -> Optional[HandlerFunc]:
        """Return the current fallback handler."""

        with self._lock:
            return self._fallback

    # ========================================================================
    # Middleware
    # ========================================================================

    def add_middleware(
        self,
        fn: MiddlewareFunc,
    ) -> None:
        """
        Add middleware executed before dispatch.

        Middleware exceptions are isolated and do not stop dispatch.
        """

        if not callable(fn):
            raise InvalidHandlerError(
                "middleware must be callable "
                f"(got {type(fn).__name__})"
            )

        with self._lock:

            self._ensure_active()

            if fn not in self._middleware:
                self._middleware.append(fn)

        logger.debug(
            "Added middleware: %s",
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
        """Remove a middleware function."""

        with self._lock:

            try:
                self._middleware.remove(
                    fn
                )
            except ValueError:
                return False

        logger.debug(
            "Removed middleware: %s",
            getattr(
                fn,
                "__name__",
                repr(fn),
            ),
        )

        return True

    def clear_middleware(self) -> int:
        """Remove all middleware functions."""

        with self._lock:

            count = len(
                self._middleware
            )

            self._middleware.clear()

        logger.debug(
            "Cleared %d middleware function(s)",
            count,
        )

        return count

    def _run_middleware(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: dict[str, Any],
    ) -> None:
        """Execute a snapshot of all configured middleware."""

        with self._lock:
            middleware = tuple(
                self._middleware
            )

        for fn in middleware:

            try:
                fn(
                    intent,
                    utterance,
                    dict(slots),
                )

            except Exception as exc:

                with self._lock:
                    self._stats.middleware_errors += 1

                logger.warning(
                    "Middleware '%s' failed: %s",
                    getattr(
                        fn,
                        "__name__",
                        repr(fn),
                    ),
                    exc,
                    exc_info=True,
                )

    # ========================================================================
    # Result normalization
    # ========================================================================

    @staticmethod
    def _normalize_result(
        result: Any,
        intent: IntentCategory,
    ) -> CommandResult:
        """
        Normalize arbitrary handler output into CommandResult.

        Supported:
            CommandResult
            str
            dict
            None
            any other object
        """

        if isinstance(
            result,
            CommandResult,
        ):

            if result.intent is None:
                result.intent = intent

            if not isinstance(
                result.data,
                dict,
            ):
                result.data = {}

            if not isinstance(
                result.metadata,
                dict,
            ):
                result.metadata = {}

            return result

        if isinstance(
            result,
            str,
        ):
            return CommandResult.ok(
                result,
                intent=intent,
            )

        if isinstance(
            result,
            dict,
        ):
            payload = dict(result)

            message = payload.pop(
                "message",
                "Command completed.",
            )

            return CommandResult.ok(
                str(message),
                intent=intent,
                data=payload,
            )

        if result is None:
            return CommandResult.ok(
                "Command completed.",
                intent=intent,
            )

        return CommandResult.ok(
            str(result),
            intent=intent,
            data={
                "result": result,
            },
        )

    # ========================================================================
    # Event integration
    # ========================================================================

    def _emit_command_event(
        self,
        intent: IntentCategory,
        utterance: str,
        result: CommandResult,
        *,
        used_fallback: bool,
    ) -> None:
        """Emit the appropriate command event safely."""

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
            "data": dict(result.data),
        }

        try:

            event_bus.emit(
                event_name,
                payload,
            )

        except Exception as exc:

            logger.warning(
                "Command event emission failed "
                "(event=%s, error=%s)",
                event_name,
                exc,
                exc_info=True,
            )

    # ========================================================================
    # Dispatch
    # ========================================================================

    def dispatch(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: Optional[dict[str, Any]] = None,
    ) -> CommandResult:
        """
        Dispatch a command synchronously.

        Handler execution never occurs while the router lock is held.
        """

        intent = self._validate_intent(
            intent
        )

        utterance = self._normalize_utterance(
            utterance
        )

        slots = self._normalize_slots(
            slots
        )

        with self._lock:

            self._ensure_active()

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

        command_id = uuid.uuid4().hex

        started = time.perf_counter()

        logger.debug(
            "Dispatch started: intent=%s command=%s",
            intent.value,
            command_id[:8],
        )

        # Middleware runs outside the router lock.
        self._run_middleware(
            intent,
            utterance,
            slots,
        )

        if handler is None:

            logger.warning(
                "No handler registered for intent '%s' "
                "and no fallback configured",
                intent.value,
            )

            result = CommandResult.fail(
                error=(
                    f"No handler registered for "
                    f"'{intent.value}'"
                ),
                intent=intent,
                message=(
                    "I'm not sure how to help "
                    "with that yet."
                ),
            )

        else:

            handler_name = getattr(
                handler,
                "__name__",
                handler.__class__.__name__,
            )

            try:

                raw_result = handler(
                    utterance,
                    dict(slots),
                )

                result = self._normalize_result(
                    raw_result,
                    intent,
                )

            except Exception as exc:

                with self._lock:
                    self._stats.handler_errors += 1

                logger.error(
                    "Command handler '%s' failed "
                    "for intent '%s': %s",
                    handler_name,
                    intent.value,
                    exc,
                    exc_info=True,
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

        if not isinstance(
            result.metadata,
            dict,
        ):
            result.metadata = {}

        result.metadata.setdefault(
            "handler",
            (
                getattr(
                    handler,
                    "__name__",
                    handler.__class__.__name__,
                )
                if handler is not None
                else None
            ),
        )

        result.metadata.setdefault(
            "used_fallback",
            used_fallback,
        )

        result.metadata.setdefault(
            "intent",
            intent.value,
        )

        # Update statistics atomically.
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

        logger.info(
            "Command completed: intent=%s "
            "success=%s duration=%.2fms",
            intent.value,
            result.success,
            duration_ms,
        )

        return result

    # ========================================================================
    # Async dispatch
    # ========================================================================

    def dispatch_async(
        self,
        intent: IntentCategory,
        utterance: str,
        slots: Optional[dict[str, Any]] = None,
    ) -> Future:
        """
        Dispatch asynchronously.

        Returns a Future[CommandResult].
        """

        intent = self._validate_intent(
            intent
        )

        with self._lock:
            self._ensure_active()

        return self._executor.submit(
            self.dispatch,
            intent,
            utterance,
            slots,
        )

    # ========================================================================
    # Lookup / introspection
    # ========================================================================

    def is_registered(
        self,
        intent: IntentCategory,
    ) -> bool:
        """Return whether an intent has a dedicated handler."""

        intent = self._validate_intent(
            intent
        )

        with self._lock:
            return intent in self._handlers

    def get_handler(
        self,
        intent: IntentCategory,
    ) -> Optional[HandlerFunc]:
        """Return the registered handler for an intent."""

        intent = self._validate_intent(
            intent
        )

        with self._lock:
            return self._handlers.get(
                intent
            )

    def require_handler(
        self,
        intent: IntentCategory,
    ) -> HandlerFunc:
        """
        Return a registered handler or raise HandlerNotFoundError.
        """

        handler = self.get_handler(
            intent
        )

        if handler is None:
            raise HandlerNotFoundError(
                f"No handler registered for "
                f"'{intent.value}'"
            )

        return handler

    def get_handler_info(
        self,
        intent: IntentCategory,
    ) -> Optional[HandlerInfo]:
        """Return handler metadata."""

        intent = self._validate_intent(
            intent
        )

        with self._lock:
            return self._handler_info.get(
                intent
            )

    def registered_intents(
        self,
    ) -> list[IntentCategory]:
        """Return all currently registered intents."""

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

    def middleware_count(self) -> int:
        """Return number of registered middleware functions."""

        with self._lock:
            return len(
                self._middleware
            )

    # ========================================================================
    # Statistics
    # ========================================================================

    def stats(self) -> dict[str, Any]:
        """Return a thread-safe runtime statistics snapshot."""

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
                        self._fallback is not None
                    ),
                    "shutdown": self._shutdown,
                    "running": not self._shutdown,
                    "max_workers": self._max_workers,
                }
            )

            return data

    def reset_stats(self) -> None:
        """Reset runtime statistics."""

        with self._lock:
            self._stats = RouterStats()

        logger.info(
            "CommandRouter statistics reset"
        )

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """Return a complete diagnostic snapshot."""

        with self._lock:

            handlers = {}

            for intent, info in (
                self._handler_info.items()
            ):

                handlers[intent.value] = {
                    "handler": info.handler_name,
                    "module": info.module,
                    "description": info.description,
                    "priority": info.priority,
                    "registered_at": (
                        info.registered_at
                    ),
                }

            return {
                "module": __name__,
                "class": self.__class__.__name__,
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "max_workers": self._max_workers,
                "thread_name_prefix": (
                    self._thread_name_prefix
                ),
                "registered_handlers": len(
                    self._handlers
                ),
                "middleware_count": len(
                    self._middleware
                ),
                "fallback_configured": (
                    self._fallback is not None
                ),
                "handlers": handlers,
                "stats": self._stats.to_dict(),
            }

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(
        self,
        *,
        wait: bool = True,
    ) -> None:
        """
        Gracefully shut down the router.

        After shutdown:
            • New dispatches are rejected.
            • New registrations are rejected.
            • Async submissions are rejected.
            • Existing synchronous handler calls are allowed to finish.
            • Executor shutdown is performed.
        """

        with self._lock:

            if self._shutdown:
                logger.debug(
                    "CommandRouter already shut down"
                )
                return

            self._shutdown = True

            # Prevent new routing immediately.
            self._handlers.clear()
            self._handler_info.clear()
            self._middleware.clear()
            self._fallback = None

        logger.info(
            "CommandRouter shutting down "
            "(wait=%s)",
            wait,
        )

        try:

            self._executor.shutdown(
                wait=wait,
                cancel_futures=True,
            )

        except Exception:

            logger.exception(
                "CommandRouter executor shutdown failed"
            )

            raise

        logger.info(
            "CommandRouter shutdown complete"
        )

    @property
    def is_running(self) -> bool:
        """Return True when router accepts new operations."""

        with self._lock:
            return not self._shutdown

    @property
    def is_shutdown(self) -> bool:
        """Return True after router shutdown."""

        with self._lock:
            return self._shutdown

    # ========================================================================
    # Context manager
    # ========================================================================

    def __enter__(self) -> "CommandRouter":
        """Enter router context."""

        with self._lock:
            self._ensure_active()

        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        """Shutdown router when leaving context."""

        self.shutdown()

    # ========================================================================
    # Representation
    # ========================================================================

    def __repr__(self) -> str:
        """Return concise router representation."""

        with self._lock:

            return (
                f"{self.__class__.__name__}("
                f"running={not self._shutdown}, "
                f"handlers={len(self._handlers)}, "
                f"middleware={len(self._middleware)}, "
                f"fallback={self._fallback is not None}"
                f")"
            )


# ============================================================================
# Global singleton
# ============================================================================

command_router = CommandRouter()

logger.info(
    "Global command_router initialized"
)


# ============================================================================
# Convenience API
# ============================================================================


def register_command(
    intent: IntentCategory,
    handler: HandlerFunc,
    *,
    overwrite: bool = True,
    description: str = "",
    priority: int = 0,
) -> None:
    """Register a handler on the global command router."""

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
    """Unregister a handler from the global router."""

    return command_router.unregister(
        intent
    )


def dispatch_command(
    intent: IntentCategory,
    utterance: str,
    slots: Optional[dict[str, Any]] = None,
) -> CommandResult:
    """Synchronously dispatch through the global router."""

    return command_router.dispatch(
        intent,
        utterance,
        slots,
    )


def dispatch_command_async(
    intent: IntentCategory,
    utterance: str,
    slots: Optional[dict[str, Any]] = None,
) -> Future:
    """Asynchronously dispatch through the global router."""

    return command_router.dispatch_async(
        intent,
        utterance,
        slots,
    )


def command_router_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global router."""

    return command_router.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Result models
    "CommandResult",
    "HandlerInfo",
    "RouterStats",

    # Router
    "CommandRouter",

    # Exceptions
    "CommandRouterError",
    "HandlerAlreadyRegisteredError",
    "HandlerNotFoundError",
    "InvalidHandlerError",
    "InvalidIntentError",
    "RouterShutdownError",

    # Types
    "HandlerFunc",
    "MiddlewareFunc",

    # Singleton
    "command_router",

    # Convenience API
    "command_router_diagnostics",
    "dispatch_command",
    "dispatch_command_async",
    "register_command",
    "unregister_command",
]
