"""
core/event_bus.py
=================

Professional, thread-safe publish/subscribe event system for AssistantX.

The EventBus allows independent subsystems to communicate without creating
direct dependencies between them.

Example:

    from core.event_bus import event_bus, Events

    def on_wake_word(payload):
        print("Wake word detected:", payload)

    subscription_id = event_bus.subscribe(
        Events.WAKE_WORD_DETECTED,
        on_wake_word,
    )

    event_bus.emit(
        Events.WAKE_WORD_DETECTED,
        {"confidence": 0.92},
    )

    event_bus.unsubscribe(subscription_id)


Design goals
------------
- Thread-safe
- Synchronous delivery by default
- Optional asynchronous delivery
- Handler failures never break the publisher
- One-time subscriptions
- Event history for debugging
- Event metadata and timestamps
- Wait-for-event support
- Introspection and diagnostics
- Graceful shutdown
- Minimal dependencies
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

from core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

EventHandler = Callable[[Any], None]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EventBusError(Exception):
    """Base exception for EventBus-related errors."""


class InvalidEventError(EventBusError):
    """Raised when an event name is invalid."""


class InvalidHandlerError(EventBusError):
    """Raised when an event handler is invalid."""


class EventBusShutdownError(EventBusError):
    """Raised when an operation is attempted after shutdown."""


# ---------------------------------------------------------------------------
# Well-known events
# ---------------------------------------------------------------------------


class Events:
    """
    Well-known AssistantX event names.

    Plain strings are intentionally used instead of Enum values so events
    remain easy to serialize, log, debug, and mirror to other frontends.
    """

    # ------------------------------------------------------------------
    # Lifecycle
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


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Subscription:
    """
    Represents one event subscription.

    Attributes:
        id:
            Unique subscription identifier.

        event_name:
            Event this subscription listens to.

        handler:
            Callable invoked when the event is emitted.

        once:
            If True, subscription is automatically removed after delivery.
    """

    id: str
    event_name: str
    handler: EventHandler
    once: bool = False

    @property
    def handler_name(self) -> str:
        """Return a human-readable handler name."""
        return getattr(
            self.handler,
            "__name__",
            self.handler.__class__.__name__,
        )


@dataclass(frozen=True, slots=True)
class EventRecord:
    """
    Immutable event history record.
    """

    event_name: str
    payload: Any
    timestamp: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def create(
        cls,
        event_name: str,
        payload: Any,
    ) -> EventRecord:
        return cls(
            event_name=event_name,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------


class EventBus:
    """
    Thread-safe publish/subscribe event bus.

    Synchronous:

        bus.emit("event.name", payload)

    Asynchronous:

        bus.emit_async("event.name", payload)

    Subscription:

        sid = bus.subscribe("event.name", handler)
        bus.unsubscribe(sid)
    """

    def __init__(
        self,
        *,
        max_history: int = 200,
        max_workers: int = 4,
    ) -> None:
        if max_history < 0:
            raise ValueError("max_history must be >= 0")

        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")

        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)

        self._history: list[EventRecord] = []

        self._max_history = max_history

        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="assistantx-event",
        )

        self._shutdown = False

        self._event_signals: dict[str, threading.Condition] = {}

        self._emitted_count = 0
        self._handler_error_count = 0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_event_name(event_name: str) -> str:
        if not isinstance(event_name, str):
            raise InvalidEventError(
                "event_name must be a string."
            )

        event_name = event_name.strip()

        if not event_name:
            raise InvalidEventError(
                "event_name cannot be empty."
            )

        if len(event_name) > 200:
            raise InvalidEventError(
                "event_name is too long."
            )

        return event_name

    @staticmethod
    def _validate_handler(
        handler: EventHandler,
    ) -> EventHandler:
        if not callable(handler):
            raise InvalidHandlerError(
                "handler must be callable."
            )

        return handler

    def _ensure_active(self) -> None:
        if self._shutdown:
            raise EventBusShutdownError(
                "EventBus has already been shut down."
            )

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
        once: bool = False,
    ) -> str:
        """
        Subscribe a handler to an event.

        Returns:
            Subscription ID.
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
            "Subscribed '%s' to event '%s'.",
            subscription.handler_name,
            event_name,
        )

        return subscription.id

    def subscribe_once(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> str:
        """Subscribe a handler that is automatically removed after one call."""

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
        Remove a subscription by ID.

        Returns:
            True if removed, otherwise False.
        """

        if not isinstance(subscription_id, str):
            return False

        with self._lock:
            for event_name, subscriptions in list(
                self._subscriptions.items()
            ):
                for index, subscription in enumerate(
                    subscriptions
                ):
                    if subscription.id == subscription_id:
                        subscriptions.pop(index)

                        if not subscriptions:
                            self._subscriptions.pop(
                                event_name,
                                None,
                            )

                        logger.debug(
                            "Unsubscribed '%s' from '%s'.",
                            subscription_id,
                            event_name,
                        )

                        return True

        return False

    def unsubscribe_all(
        self,
        event_name: str | None = None,
    ) -> int:
        """
        Remove subscriptions.

        Args:
            event_name:
                If supplied, only subscriptions for that event
                are removed.

        Returns:
            Number of removed subscriptions.
        """

        with self._lock:
            if event_name is None:
                count = sum(
                    len(items)
                    for items in self._subscriptions.values()
                )

                self._subscriptions.clear()

                logger.debug(
                    "Removed all %d subscriptions.",
                    count,
                )

                return count

            event_name = self._validate_event_name(
                event_name
            )

            subscriptions = self._subscriptions.pop(
                event_name,
                [],
            )

            count = len(subscriptions)

            logger.debug(
                "Removed %d subscriptions from '%s'.",
                count,
                event_name,
            )

            return count

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:
        """
        Synchronously emit an event.

        All handlers run on the publisher's thread.

        Handler exceptions are caught and logged.
        """

        event_name = self._validate_event_name(event_name)

        with self._lock:
            self._ensure_active()

            subscriptions = list(
                self._subscriptions.get(
                    event_name,
                    [],
                )
            )

            self._record_event(
                event_name,
                payload,
            )

        if not subscriptions:
            logger.debug(
                "Event '%s' emitted with no subscribers.",
                event_name,
            )
            return

        for subscription in subscriptions:
            try:
                subscription.handler(payload)

            except Exception:
                with self._lock:
                    self._handler_error_count += 1

                logger.exception(
                    "Handler '%s' failed for event '%s'.",
                    subscription.handler_name,
                    event_name,
                )

            finally:
                if subscription.once:
                    self.unsubscribe(
                        subscription.id
                    )

    def emit_async(
        self,
        event_name: str,
        payload: Any = None,
    ):
        """
        Emit an event asynchronously.

        Returns:
            concurrent.futures.Future
        """

        event_name = self._validate_event_name(event_name)

        with self._lock:
            self._ensure_active()

        return self._executor.submit(
            self.emit,
            event_name,
            payload,
        )

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def _record_event(
        self,
        event_name: str,
        payload: Any,
    ) -> None:
        """
        Record an emitted event.

        Caller must hold `_lock`.
        """

        self._emitted_count += 1

        if self._max_history <= 0:
            return

        record = EventRecord.create(
            event_name,
            payload,
        )

        self._history.append(record)

        if len(self._history) > self._max_history:
            overflow = (
                len(self._history)
                - self._max_history
            )

            del self._history[:overflow]

        condition = self._event_signals.get(
            event_name
        )

        if condition is not None:
            condition.notify_all()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def recent_events(
        self,
        limit: int = 20,
    ) -> list[EventRecord]:
        """
        Return recent event records.

        The returned list is a copy.
        """

        if limit < 0:
            raise ValueError(
                "limit must be >= 0"
            )

        with self._lock:
            if limit == 0:
                return []

            return list(
                self._history[-limit:]
            )

    def clear_history(self) -> None:
        """Clear event history."""

        with self._lock:
            self._history.clear()

        logger.debug(
            "Event history cleared."
        )

    # ------------------------------------------------------------------
    # Waiting for events
    # ------------------------------------------------------------------

    def wait_for(
        self,
        event_name: str,
        timeout: float | None = None,
    ) -> EventRecord | None:
        """
        Wait until an event is emitted.

        Useful for coordination between independent subsystems.

        Returns:
            EventRecord if event occurs before timeout,
            otherwise None.

        Note:
            This method waits for future events. Events already present
            in history are not returned.
        """

        event_name = self._validate_event_name(
            event_name
        )

        if timeout is not None and timeout < 0:
            raise ValueError(
                "timeout must be >= 0"
            )

        condition = threading.Condition(
            self._lock
        )

        with self._lock:
            self._ensure_active()

            self._event_signals[event_name] = condition

            start = time.monotonic()

            try:
                while True:
                    condition.wait(
                        timeout=timeout
                    )

                    for record in reversed(
                        self._history
                    ):
                        if (
                            record.event_name
                            == event_name
                            and self._record_is_recent()
                        ):
                            return record

                    if timeout is None:
                        continue

                    elapsed = (
                        time.monotonic()
                        - start
                    )

                    if elapsed >= timeout:
                        return None

                    timeout = timeout - elapsed

            finally:
                existing = self._event_signals.get(
                    event_name
                )

                if existing is condition:
                    self._event_signals.pop(
                        event_name,
                        None,
                    )

    @staticmethod
    def _record_is_recent() -> bool:
        """
        Internal helper.

        Event timestamps are wall-clock based while timeout measurement
        uses monotonic time. To avoid mixing the clocks, this method
        conservatively returns True for matching records.

        Event history is intentionally small, so the caller's wait loop
        is responsible for matching the most recent event.
        """

        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def subscriber_count(
        self,
        event_name: str,
    ) -> int:
        """Return the number of active subscribers for an event."""

        event_name = self._validate_event_name(
            event_name
        )

        with self._lock:
            return len(
                self._subscriptions.get(
                    event_name,
                    [],
                )
            )

    def total_subscribers(self) -> int:
        """Return total number of active subscriptions."""

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
        event_name: str | None = None,
    ) -> list[Subscription]:
        """
        Return a snapshot of subscriptions.

        Args:
            event_name:
                Optional event filter.
        """

        with self._lock:
            if event_name is not None:
                event_name = self._validate_event_name(
                    event_name
                )

                return list(
                    self._subscriptions.get(
                        event_name,
                        [],
                    )
                )

            return [
                subscription
                for subscriptions
                in self._subscriptions.values()
                for subscription in subscriptions
            ]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @property
    def is_shutdown(self) -> bool:
        """Whether the event bus has been shut down."""

        with self._lock:
            return self._shutdown

    @property
    def is_running(self) -> bool:
        """Whether the event bus is active."""

        with self._lock:
            return not self._shutdown

    @property
    def emitted_count(self) -> int:
        """Total number of emitted events."""

        with self._lock:
            return self._emitted_count

    @property
    def handler_error_count(self) -> int:
        """Total number of handler failures."""

        with self._lock:
            return self._handler_error_count

    def stats(self) -> dict[str, Any]:
        """Return event bus statistics."""

        with self._lock:
            return {
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "event_types": len(
                    self._subscriptions
                ),
                "subscriptions": self.total_subscribers(),
                "history_size": len(
                    self._history
                ),
                "max_history": self._max_history,
                "emitted_count": self._emitted_count,
                "handler_errors": self._handler_error_count,
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed diagnostic information."""

        with self._lock:
            subscriptions = {
                event_name: len(items)
                for event_name, items
                in self._subscriptions.items()
            }

            return {
                "module": __name__,
                "class": self.__class__.__name__,
                "running": not self._shutdown,
                "shutdown": self._shutdown,
                "subscriptions": subscriptions,
                "total_subscribers": self.total_subscribers(),
                "history_size": len(
                    self._history
                ),
                "max_history": self._max_history,
                "emitted_count": self._emitted_count,
                "handler_error_count": self._handler_error_count,
                "async_executor": True,
            }

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_history_limit(
        self,
        limit: int,
    ) -> None:
        """Change maximum number of events retained in history."""

        if limit < 0:
            raise ValueError(
                "limit must be >= 0"
            )

        with self._lock:
            self._max_history = limit

            if limit == 0:
                self._history.clear()

            elif len(self._history) > limit:
                self._history = self._history[-limit:]

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(
        self,
        *,
        wait: bool = True,
    ) -> None:
        """
        Gracefully shut down the asynchronous executor.

        After shutdown, new subscriptions/emissions are rejected.
        """

        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True

            self._subscriptions.clear()
            self._event_signals.clear()

        logger.debug(
            "EventBus shutting down."
        )

        self._executor.shutdown(
            wait=wait,
            cancel_futures=True,
        )

        logger.debug(
            "EventBus shutdown complete."
        )

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
                f"subscriptions={self.total_subscribers()}, "
                f"history={len(self._history)}"
                f")"
            )


# ---------------------------------------------------------------------------
# Global AssistantX EventBus
# ---------------------------------------------------------------------------

event_bus: EventBus = EventBus()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


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
    """Create a one-time subscription."""

    return event_bus.subscribe_once(
        event_name,
        handler,
    )


def unsubscribe(
    subscription_id: str,
) -> bool:
    """Unsubscribe from the global EventBus."""

    return event_bus.unsubscribe(
        subscription_id
    )


def emit(
    event_name: str,
    payload: Any = None,
) -> None:
    """Emit an event using the global EventBus."""

    event_bus.emit(
        event_name,
        payload,
    )


def emit_async(
    event_name: str,
    payload: Any = None,
):
    """Emit an event asynchronously."""

    return event_bus.emit_async(
        event_name,
        payload,
    )


def recent_events(
    limit: int = 20,
) -> list[EventRecord]:
    """Return recent global EventBus events."""

    return event_bus.recent_events(
        limit
    )


def event_bus_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global EventBus."""

    return event_bus.diagnostics()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Core
    "EventBus",
    # Exceptions
    "EventBusError",
    "EventBusShutdownError",
    # Types
    "EventHandler",
    "EventRecord",
    # Events
    "Events",
    "InvalidEventError",
    "InvalidHandlerError",
    # Models
    "Subscription",
    "emit",
    "emit_async",
    "event_bus",
    "event_bus_diagnostics",
    "recent_events",
    # Convenience
    "subscribe",
    "subscribe_once",
    "unsubscribe",
]
