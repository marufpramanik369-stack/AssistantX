"""
core/event_bus.py — AssistantX Professional Event Bus
======================================================

Thread-safe publish/subscribe event system for AssistantX.

Responsibilities
----------------
• Synchronous and asynchronous event delivery
• Thread-safe subscription management
• One-time subscriptions
• Event history and diagnostics
• Future-event coordination via wait_for()
• Safe handler isolation
• Graceful executor shutdown
• Multiple concurrent waiters per event
• Stable public API for the AssistantX ecosystem

Design
------
    EventBus
        ├── subscribe()
        ├── subscribe_once()
        ├── unsubscribe()
        ├── emit()
        ├── emit_async()
        ├── wait_for()
        ├── recent_events()
        ├── diagnostics()
        └── shutdown()

Important guarantees
--------------------
1. Internal state is protected by RLock.
2. User handlers are NEVER executed while the bus lock is held.
3. Handler exceptions never crash the publisher.
4. Multiple wait_for() callers may safely wait for the same event.
5. once=True subscriptions are claimed atomically before execution.
6. Event history is bounded.
7. Async workers are isolated in a dedicated executor.
8. Shutdown is idempotent.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from core.logger import get_logger


logger = get_logger(__name__)


# ============================================================================
# Public Types
# ============================================================================

EventHandler = Callable[[Any], None]


# ============================================================================
# Exceptions
# ============================================================================


class EventBusError(Exception):
    """Base exception for EventBus-related failures."""


class InvalidEventError(EventBusError):
    """Raised when an event name is invalid."""


class InvalidHandlerError(EventBusError):
    """Raised when an event handler is invalid."""


class EventBusShutdownError(EventBusError):
    """Raised when an operation requires an active EventBus."""


# ============================================================================
# Well-Known AssistantX Events
# ============================================================================


class Events:
    """
    Canonical AssistantX event names.

    Event names intentionally remain plain strings so they are easy to:

    • serialize
    • log
    • inspect
    • forward to dashboards
    • mirror to future web/mobile clients
    """

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------

    APP_STARTED = "app.started"
    APP_SHUTTING_DOWN = "app.shutting_down"

    # ------------------------------------------------------------------
    # Voice
    # ------------------------------------------------------------------

    WAKE_WORD_DETECTED = "voice.wake_word_detected"

    LISTENING_STARTED = "voice.listening_started"
    LISTENING_STOPPED = "voice.listening_stopped"

    SPEECH_RECOGNIZED = "voice.speech_recognized"
    SPEECH_RECOGNITION_FAILED = "voice.speech_recognition_failed"

    SPEAKING_STARTED = "voice.speaking_started"
    SPEAKING_FINISHED = "voice.speaking_finished"

    # ------------------------------------------------------------------
    # Brain / AI
    # ------------------------------------------------------------------

    INTENT_CLASSIFIED = "brain.intent_classified"

    AI_RESPONSE_CHUNK = "ai.response_chunk"
    AI_RESPONSE_COMPLETE = "ai.response_complete"
    AI_ERROR = "ai.error"

    # ------------------------------------------------------------------
    # Commands / Automation
    # ------------------------------------------------------------------

    COMMAND_EXECUTED = "command.executed"
    COMMAND_FAILED = "command.failed"

    # ------------------------------------------------------------------
    # Memory / History
    # ------------------------------------------------------------------

    MEMORY_UPDATED = "memory.updated"

    HISTORY_APPENDED = "history.appended"
    HISTORY_CLEARED = "history.cleared"

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    REMINDER_DUE = "scheduler.reminder_due"
    TASK_SCHEDULED = "scheduler.task_scheduled"

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    THEME_CHANGED = "ui.theme_changed"
    SETTINGS_CHANGED = "ui.settings_changed"
    NOTIFICATION_REQUESTED = "ui.notification_requested"


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class Subscription:
    """
    Immutable event subscription descriptor.
    """

    id: str
    event_name: str
    handler: EventHandler
    once: bool = False

    @property
    def handler_name(self) -> str:
        """Return a readable handler name."""

        return getattr(
            self.handler,
            "__name__",
            self.handler.__class__.__name__,
        )


@dataclass(frozen=True, slots=True)
class EventRecord:
    """
    Immutable event history record.

    Attributes
    ----------
    event_name:
        Event identifier.

    payload:
        Arbitrary event payload.

    timestamp:
        UTC ISO-8601 timestamp.

    event_id:
        Unique event identifier.
    """

    event_name: str
    payload: Any
    timestamp: str
    event_id: str = field(
        default_factory=lambda: uuid.uuid4().hex
    )

    @classmethod
    def create(
        cls,
        event_name: str,
        payload: Any,
    ) -> EventRecord:
        """Create a new UTC event record."""

        return cls(
            event_name=event_name,
            payload=payload,
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )


# ============================================================================
# Internal Waiting State
# ============================================================================


@dataclass(slots=True)
class _Waiter:
    """
    Internal state for one wait_for() caller.

    This is intentionally private and never exposed through the public API.
    """

    condition: threading.Condition
    baseline_version: int


# ============================================================================
# Event Bus
# ============================================================================


class EventBus:
    """
    Thread-safe AssistantX publish/subscribe event bus.

    Parameters
    ----------
    max_history:
        Maximum number of event records retained.

    max_workers:
        Number of background workers used by emit_async().
    """

    DEFAULT_MAX_HISTORY = 200
    DEFAULT_MAX_WORKERS = 4

    MAX_EVENT_NAME_LENGTH = 200

    def __init__(
        self,
        *,
        max_history: int = DEFAULT_MAX_HISTORY,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:

        self._validate_limits(
            max_history=max_history,
            max_workers=max_workers,
        )

        # --------------------------------------------------------------
        # Core state
        # --------------------------------------------------------------

        self._subscriptions: dict[
            str,
            list[Subscription],
        ] = defaultdict(list)

        self._history: list[EventRecord] = []

        self._max_history = max_history

        self._lock = threading.RLock()

        # --------------------------------------------------------------
        # Event waiting / coordination
        # --------------------------------------------------------------

        self._waiters: dict[
            str,
            set[_Waiter],
        ] = defaultdict(set)

        # Version counter allows wait_for() to distinguish a new event
        # from an event that existed before the wait started.
        self._event_versions: dict[str, int] = defaultdict(int)

        # Last emitted record is retained independently of history.
        # This allows wait_for() to work even when history is disabled.
        self._last_records: dict[str, EventRecord] = {}

        # --------------------------------------------------------------
        # Async execution
        # --------------------------------------------------------------

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="assistantx-event",
        )

        self._max_workers = max_workers

        # --------------------------------------------------------------
        # Lifecycle
        # --------------------------------------------------------------

        self._shutdown = False

        # --------------------------------------------------------------
        # Statistics
        # --------------------------------------------------------------

        self._emitted_count = 0
        self._handler_error_count = 0
        self._async_submitted_count = 0
        self._async_completed_count = 0

        logger.debug(
            "EventBus initialized "
            "(max_history=%d, max_workers=%d)",
            max_history,
            max_workers,
        )

    # ====================================================================
    # Validation
    # ====================================================================

    @classmethod
    def _validate_limits(
        cls,
        *,
        max_history: int,
        max_workers: int,
    ) -> None:
        """Validate constructor limits."""

        if isinstance(max_history, bool) or not isinstance(
            max_history,
            int,
        ):
            raise ValueError(
                "max_history must be an integer"
            )

        if max_history < 0:
            raise ValueError(
                f"max_history must be >= 0 (got {max_history})"
            )

        if isinstance(max_workers, bool) or not isinstance(
            max_workers,
            int,
        ):
            raise ValueError(
                "max_workers must be an integer"
            )

        if max_workers < 1:
            raise ValueError(
                f"max_workers must be >= 1 (got {max_workers})"
            )

    @classmethod
    def _validate_event_name(
        cls,
        event_name: str,
    ) -> str:
        """Normalize and validate an event name."""

        if not isinstance(event_name, str):
            raise InvalidEventError(
                "event_name must be str "
                f"(got {type(event_name).__name__})"
            )

        normalized = event_name.strip()

        if not normalized:
            raise InvalidEventError(
                "event_name cannot be empty"
            )

        if len(normalized) > cls.MAX_EVENT_NAME_LENGTH:
            raise InvalidEventError(
                "event_name exceeds maximum length "
                f"({len(normalized)} > "
                f"{cls.MAX_EVENT_NAME_LENGTH})"
            )

        return normalized

    @staticmethod
    def _validate_handler(
        handler: EventHandler,
    ) -> EventHandler:
        """Validate an event handler."""

        if not callable(handler):
            raise InvalidHandlerError(
                "handler must be callable "
                f"(got {type(handler).__name__})"
            )

        return handler

    def _ensure_active(self) -> None:
        """Raise when the bus is no longer active."""

        if self._shutdown:
            raise EventBusShutdownError(
                "EventBus has been shut down"
            )

    # ====================================================================
    # Subscription Management
    # ====================================================================

    def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
        once: bool = False,
    ) -> str:
        """
        Register a persistent or one-time event handler.

        Returns
        -------
        str
            Unique subscription ID.
        """

        event_name = self._validate_event_name(event_name)
        handler = self._validate_handler(handler)

        with self._lock:
            self._ensure_active()

            subscription = Subscription(
                id=uuid.uuid4().hex,
                event_name=event_name,
                handler=handler,
                once=bool(once),
            )

            self._subscriptions[event_name].append(
                subscription
            )

        logger.debug(
            "Subscribed handler '%s' "
            "to '%s' (once=%s, sid=%s)",
            subscription.handler_name,
            event_name,
            subscription.once,
            subscription.id[:8],
        )

        return subscription.id

    def subscribe_once(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> str:
        """Register a handler that executes at most once."""

        return self.subscribe(
            event_name,
            handler,
            once=True,
        )

    def unsubscribe(
        self,
        subscription_id: str,
    ) -> bool:
        """
        Remove one subscription.

        Returns
        -------
        bool
            True if removed, otherwise False.
        """

        if not isinstance(subscription_id, str):
            return False

        subscription_id = subscription_id.strip()

        if not subscription_id:
            return False

        with self._lock:
            for event_name, subscriptions in tuple(
                self._subscriptions.items()
            ):
                for index, subscription in enumerate(
                    subscriptions
                ):
                    if subscription.id != subscription_id:
                        continue

                    subscriptions.pop(index)

                    if not subscriptions:
                        self._subscriptions.pop(
                            event_name,
                            None,
                        )

                    logger.debug(
                        "Unsubscribed '%s' "
                        "from '%s'",
                        subscription_id[:8],
                        event_name,
                    )

                    return True

        return False

    def unsubscribe_all(
        self,
        event_name: Optional[str] = None,
    ) -> int:
        """
        Remove subscriptions.

        If event_name is None, all subscriptions are removed.
        """

        with self._lock:
            if event_name is None:
                count = sum(
                    len(items)
                    for items in self._subscriptions.values()
                )

                self._subscriptions.clear()

                logger.info(
                    "Removed all event subscriptions: %d",
                    count,
                )

                return count

            event_name = self._validate_event_name(
                event_name
            )

            removed = self._subscriptions.pop(
                event_name,
                [],
            )

            count = len(removed)

        logger.debug(
            "Removed %d subscription(s) "
            "from '%s'",
            count,
            event_name,
        )

        return count

    # ====================================================================
    # Emission
    # ====================================================================

    def emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:
        """
        Emit an event synchronously.

        Event recording and subscription snapshotting happen atomically.
        Handler execution happens outside the internal lock.
        """

        event_name = self._validate_event_name(
            event_name
        )

        with self._lock:
            self._ensure_active()

            record = self._record_event(
                event_name,
                payload,
            )

            subscriptions = list(
                self._subscriptions.get(
                    event_name,
                    (),
                )
            )

            # ----------------------------------------------------------
            # Atomically claim one-time subscriptions.
            #
            # This prevents two concurrent emit() calls from invoking
            # the same once=True handler twice.
            # ----------------------------------------------------------

            claimed_once_ids: set[str] = set()

            if subscriptions:
                remaining: list[Subscription] = []

                for subscription in subscriptions:
                    if subscription.once:
                        claimed_once_ids.add(
                            subscription.id
                        )
                    else:
                        remaining.append(subscription)

                if claimed_once_ids:
                    if remaining:
                        self._subscriptions[
                            event_name
                        ] = remaining
                    else:
                        self._subscriptions.pop(
                            event_name,
                            None,
                        )

        logger.debug(
            "Event emitted: '%s' "
            "(subscribers=%d, event_id=%s)",
            event_name,
            len(subscriptions),
            record.event_id[:8],
        )

        for subscription in subscriptions:
            try:
                subscription.handler(payload)

            except Exception as exc:
                with self._lock:
                    self._handler_error_count += 1

                logger.exception(
                    "Event handler failed: "
                    "event='%s', handler='%s', error=%s",
                    event_name,
                    subscription.handler_name,
                    type(exc).__name__,
                )

            else:
                logger.debug(
                    "Event handler completed: "
                    "event='%s', handler='%s'",
                    event_name,
                    subscription.handler_name,
                )

    def emit_async(
        self,
        event_name: str,
        payload: Any = None,
    ) -> Future[None]:
        """
        Emit an event asynchronously.

        Returns
        -------
        Future[None]
            Future representing the complete emit operation.
        """

        event_name = self._validate_event_name(
            event_name
        )

        with self._lock:
            self._ensure_active()

            try:
                future = self._executor.submit(
                    self.emit,
                    event_name,
                    payload,
                )
            except RuntimeError as exc:
                raise EventBusShutdownError(
                    "EventBus executor is unavailable"
                ) from exc

            self._async_submitted_count += 1

        future.add_done_callback(
            self._on_async_complete
        )

        logger.debug(
            "Async event submitted: '%s'",
            event_name,
        )

        return future

    def _on_async_complete(
        self,
        future: Future[Any],
    ) -> None:
        """Track completion of asynchronous event delivery."""

        with self._lock:
            self._async_completed_count += 1

        if future.cancelled():
            logger.debug(
                "Async event task cancelled"
            )
            return

        exception = future.exception()

        if exception is not None:
            logger.debug(
                "Async event task completed "
                "with exception: %s",
                type(exception).__name__,
            )

    # ====================================================================
    # Event Recording
    # ====================================================================

    def _record_event(
        self,
        event_name: str,
        payload: Any,
    ) -> EventRecord:
        """
        Record an event and notify all waiters.

        Caller MUST hold _lock.
        """

        record = EventRecord.create(
            event_name,
            payload,
        )

        self._emitted_count += 1

        self._event_versions[event_name] += 1

        self._last_records[event_name] = record

        if self._max_history > 0:
            self._history.append(record)

            overflow = (
                len(self._history)
                - self._max_history
            )

            if overflow > 0:
                del self._history[:overflow]

        # Notify every waiter registered for this event.
        waiters = tuple(
            self._waiters.get(
                event_name,
                (),
            )
        )

        for waiter in waiters:
            waiter.condition.notify_all()

        return record

    # ====================================================================
    # History
    # ====================================================================

    def recent_events(
        self,
        limit: int = 20,
    ) -> list[EventRecord]:
        """
        Return a snapshot of recent events.

        Events are returned oldest-first.
        """

        if isinstance(limit, bool) or not isinstance(
            limit,
            int,
        ):
            raise ValueError(
                "limit must be an integer"
            )

        if limit < 0:
            raise ValueError(
                f"limit must be >= 0 (got {limit})"
            )

        if limit == 0:
            return []

        with self._lock:
            return list(
                self._history[-limit:]
            )

    def clear_history(self) -> None:
        """Clear retained event history."""

        with self._lock:
            count = len(self._history)
            self._history.clear()

        logger.info(
            "Event history cleared: %d record(s)",
            count,
        )

    # ====================================================================
    # Waiting
    # ====================================================================

    def wait_for(
        self,
        event_name: str,
        timeout: Optional[float] = None,
    ) -> Optional[EventRecord]:
        """
        Wait for the next occurrence of an event.

        Unlike a history lookup, this method only accepts an event emitted
        after this call begins waiting.

        Multiple threads can independently wait for the same event.
        """

        event_name = self._validate_event_name(
            event_name
        )

        if timeout is not None:
            if isinstance(timeout, bool):
                raise ValueError(
                    "timeout must be a real number"
                )

            if timeout < 0:
                raise ValueError(
                    f"timeout must be >= 0 (got {timeout})"
                )

        condition = threading.Condition(
            self._lock
        )

        with self._lock:
            self._ensure_active()

            baseline_version = self._event_versions[
                event_name
            ]

            waiter = _Waiter(
                condition=condition,
                baseline_version=baseline_version,
            )

            self._waiters[event_name].add(waiter)

            logger.debug(
                "Waiting for event '%s' "
                "(timeout=%s, version=%d)",
                event_name,
                timeout,
                baseline_version,
            )

            deadline = (
                None
                if timeout is None
                else time.monotonic() + timeout
            )

            try:
                while True:
                    current_version = (
                        self._event_versions[
                            event_name
                        ]
                    )

                    if current_version > baseline_version:
                        record = self._last_records.get(
                            event_name
                        )

                        if record is not None:
                            logger.debug(
                                "wait_for() received "
                                "event '%s'",
                                event_name,
                            )
                            return record

                    if timeout is None:
                        condition.wait()
                        continue

                    remaining = (
                        deadline
                        - time.monotonic()
                    )

                    if remaining <= 0:
                        logger.debug(
                            "wait_for() timed out "
                            "for '%s'",
                            event_name,
                        )
                        return None

                    condition.wait(
                        timeout=remaining
                    )

            finally:
                waiters = self._waiters.get(
                    event_name
                )

                if waiters is not None:
                    waiters.discard(waiter)

                    if not waiters:
                        self._waiters.pop(
                            event_name,
                            None,
                        )

    # ====================================================================
    # Introspection
    # ====================================================================

    def subscriber_count(
        self,
        event_name: str,
    ) -> int:
        """Return active subscription count for one event."""

        event_name = self._validate_event_name(
            event_name
        )

        with self._lock:
            return len(
                self._subscriptions.get(
                    event_name,
                    (),
                )
            )

    def total_subscribers(self) -> int:
        """Return total active subscription count."""

        with self._lock:
            return sum(
                len(items)
                for items in self._subscriptions.values()
            )

    def event_names(self) -> list[str]:
        """Return event names that currently have subscribers."""

        with self._lock:
            return sorted(
                self._subscriptions.keys()
            )

    def get_subscriptions(
        self,
        event_name: Optional[str] = None,
    ) -> list[Subscription]:
        """
        Return a snapshot of active subscriptions.
        """

        with self._lock:
            if event_name is not None:
                event_name = self._validate_event_name(
                    event_name
                )

                return list(
                    self._subscriptions.get(
                        event_name,
                        (),
                    )
                )

            return [
                subscription
                for subscriptions
                in self._subscriptions.values()
                for subscription in subscriptions
            ]

    # ====================================================================
    # Lifecycle / State
    # ====================================================================

    @property
    def is_shutdown(self) -> bool:
        """Return True when the bus has been shut down."""

        with self._lock:
            return self._shutdown

    @property
    def is_running(self) -> bool:
        """Return True while the bus is active."""

        with self._lock:
            return not self._shutdown

    @property
    def emitted_count(self) -> int:
        """Return total emitted event count."""

        with self._lock:
            return self._emitted_count

    @property
    def handler_error_count(self) -> int:
        """Return total handler exception count."""

        with self._lock:
            return self._handler_error_count

    # ====================================================================
    # Statistics
    # ====================================================================

    def stats(self) -> dict[str, Any]:
        """Return a lightweight statistics snapshot."""

        with self._lock:
            subscriptions = sum(
                len(items)
                for items in self._subscriptions.values()
            )

            return {
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "event_types": len(
                    self._subscriptions
                ),
                "subscriptions": subscriptions,
                "history_size": len(
                    self._history
                ),
                "max_history": self._max_history,
                "emitted_count": self._emitted_count,
                "handler_errors": self._handler_error_count,
                "async_submitted": (
                    self._async_submitted_count
                ),
                "async_completed": (
                    self._async_completed_count
                ),
                "active_waiters": sum(
                    len(items)
                    for items in self._waiters.values()
                ),
                "tracked_event_versions": len(
                    self._event_versions
                ),
                "max_workers": self._max_workers,
            }

    def diagnostics(self) -> dict[str, Any]:
        """
        Return a detailed diagnostic snapshot.

        Intended for debugging, dashboard monitoring and support tools.
        """

        with self._lock:
            subscriptions = {
                event_name: len(items)
                for event_name, items
                in self._subscriptions.items()
            }

            waiter_counts = {
                event_name: len(waiters)
                for event_name, waiters
                in self._waiters.items()
            }

            return {
                "module": __name__,
                "class": self.__class__.__name__,
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "subscriptions": subscriptions,
                "total_subscribers": sum(
                    subscriptions.values()
                ),
                "history_size": len(
                    self._history
                ),
                "max_history": self._max_history,
                "emitted_count": self._emitted_count,
                "handler_error_count": (
                    self._handler_error_count
                ),
                "async_executor": {
                    "enabled": True,
                    "max_workers": self._max_workers,
                    "submitted": (
                        self._async_submitted_count
                    ),
                    "completed": (
                        self._async_completed_count
                    ),
                    "pending": max(
                        0,
                        self._async_submitted_count
                        - self._async_completed_count,
                    ),
                },
                "waiters": waiter_counts,
                "active_waiters": sum(
                    waiter_counts.values()
                ),
                "event_versions": dict(
                    self._event_versions
                ),
            }

    # ====================================================================
    # Configuration
    # ====================================================================

    def set_history_limit(
        self,
        limit: int,
    ) -> None:
        """
        Change the maximum retained event history.
        """

        if isinstance(limit, bool) or not isinstance(
            limit,
            int,
        ):
            raise ValueError(
                "limit must be an integer"
            )

        if limit < 0:
            raise ValueError(
                f"limit must be >= 0 (got {limit})"
            )

        with self._lock:
            old_limit = self._max_history
            self._max_history = limit

            if limit == 0:
                removed = len(self._history)
                self._history.clear()

                logger.info(
                    "Event history disabled "
                    "(removed=%d)",
                    removed,
                )

                return

            if len(self._history) > limit:
                overflow = (
                    len(self._history) - limit
                )

                del self._history[:overflow]

                logger.info(
                    "Event history limit changed "
                    "%d -> %d "
                    "(trimmed=%d)",
                    old_limit,
                    limit,
                    overflow,
                )

    @property
    def history_limit(self) -> int:
        """Return current history limit."""

        with self._lock:
            return self._max_history

    # ====================================================================
    # Shutdown
    # ====================================================================

    def shutdown(
        self,
        *,
        wait: bool = True,
    ) -> None:
        """
        Gracefully shut down the event bus.

        Parameters
        ----------
        wait:
            When True, wait for running async tasks.

        Notes
        -----
        • Shutdown is idempotent.
        • New events/subscriptions are rejected after shutdown.
        • Pending executor tasks are cancelled where possible.
        """

        with self._lock:
            if self._shutdown:
                logger.debug(
                    "EventBus already shut down"
                )
                return

            self._shutdown = True

            self._subscriptions.clear()

            # Wake all waiters so they don't remain blocked forever.
            waiters = [
                waiter
                for items in self._waiters.values()
                for waiter in items
            ]

            for waiter in waiters:
                waiter.condition.notify_all()

        logger.info(
            "EventBus shutting down (wait=%s)",
            wait,
        )

        self._executor.shutdown(
            wait=wait,
            cancel_futures=True,
        )

        logger.info(
            "EventBus shutdown complete"
        )

    # ====================================================================
    # Context Manager
    # ====================================================================

    def __enter__(self) -> EventBus:
        """Enter EventBus context manager."""

        with self._lock:
            self._ensure_active()

        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        """Shutdown the EventBus when leaving context."""

        self.shutdown()

    # ====================================================================
    # Representation
    # ====================================================================

    def __repr__(self) -> str:
        """Return concise diagnostic representation."""

        with self._lock:
            return (
                f"{self.__class__.__name__}("
                f"running={not self._shutdown}, "
                f"subscriptions="
                f"{sum(len(v) for v in self._subscriptions.values())}, "
                f"history={len(self._history)}, "
                f"emitted={self._emitted_count}"
                f")"
            )


# ============================================================================
# Global AssistantX Event Bus
# ============================================================================


event_bus = EventBus()


logger.info(
    "Global AssistantX EventBus initialized "
    "(max_history=%d, max_workers=%d)",
    event_bus.history_limit,
    event_bus._max_workers,
)


# ============================================================================
# Global Convenience API
# ============================================================================


def subscribe(
    event_name: str,
    handler: EventHandler,
    *,
    once: bool = False,
) -> str:
    """Subscribe using the global AssistantX EventBus."""

    return event_bus.subscribe(
        event_name,
        handler,
        once=once,
    )


def subscribe_once(
    event_name: str,
    handler: EventHandler,
) -> str:
    """Create a one-time global subscription."""

    return event_bus.subscribe_once(
        event_name,
        handler,
    )


def unsubscribe(
    subscription_id: str,
) -> bool:
    """Remove a global subscription."""

    return event_bus.unsubscribe(
        subscription_id
    )


def unsubscribe_all(
    event_name: Optional[str] = None,
) -> int:
    """Remove global subscriptions."""

    return event_bus.unsubscribe_all(
        event_name
    )


def emit(
    event_name: str,
    payload: Any = None,
) -> None:
    """Synchronously emit through the global EventBus."""

    event_bus.emit(
        event_name,
        payload,
    )


def emit_async(
    event_name: str,
    payload: Any = None,
) -> Future[None]:
    """Asynchronously emit through the global EventBus."""

    return event_bus.emit_async(
        event_name,
        payload,
    )


def wait_for(
    event_name: str,
    timeout: Optional[float] = None,
) -> Optional[EventRecord]:
    """Wait for a future global event."""

    return event_bus.wait_for(
        event_name,
        timeout,
    )


def recent_events(
    limit: int = 20,
) -> list[EventRecord]:
    """Return recent events from the global EventBus."""

    return event_bus.recent_events(
        limit
    )


def event_bus_diagnostics() -> dict[str, Any]:
    """Return diagnostics from the global EventBus."""

    return event_bus.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Main class
    "EventBus",

    # Exceptions
    "EventBusError",
    "EventBusShutdownError",
    "InvalidEventError",
    "InvalidHandlerError",

    # Types
    "EventHandler",
    "EventRecord",
    "Subscription",

    # Event names
    "Events",

    # Global instance
    "event_bus",

    # Convenience functions
    "emit",
    "emit_async",
    "event_bus_diagnostics",
    "recent_events",
    "subscribe",
    "subscribe_once",
    "unsubscribe",
    "unsubscribe_all",
    "wait_for",
]
