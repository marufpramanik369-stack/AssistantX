"""
event_bus.py
============
A lightweight, thread-safe publish/subscribe event bus that decouples
AssistantX's subsystems from one another. Instead of `voice/` importing
`dashboard/` directly to update a "listening..." indicator, it publishes
an event; the dashboard subscribes to that event without either module
knowing the other exists.

Design:
    - Synchronous delivery by default (handlers run on the publisher's
      thread) — simplest, fewest surprises for a desktop app.
    - Handlers that raise are caught and logged, never allowed to break
      the publisher or other subscribers.
    - `EventBus.emit_async` offers fire-and-forget delivery on a worker
      thread for handlers that might block (e.g. writing to disk).

Usage:
    from core.event_bus import event_bus, Events

    def on_wake_word(payload):
        print("Woke up!", payload)

    event_bus.subscribe(Events.WAKE_WORD_DETECTED, on_wake_word)
    event_bus.emit(Events.WAKE_WORD_DETECTED, {"confidence": 0.92})
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.logger import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[Any], None]


class Events:
    """
    Well-known event name constants. Using a class-of-constants (rather
    than a bare Enum) keeps event names as plain strings, which is more
    convenient for logging and for any future cross-language (e.g. JS
    dashboard front-end) event mirroring.
    """

    # Lifecycle
    APP_STARTED = "app.started"
    APP_SHUTTING_DOWN = "app.shutting_down"

    # Voice subsystem
    WAKE_WORD_DETECTED = "voice.wake_word_detected"
    LISTENING_STARTED = "voice.listening_started"
    LISTENING_STOPPED = "voice.listening_stopped"
    SPEECH_RECOGNIZED = "voice.speech_recognized"
    SPEECH_RECOGNITION_FAILED = "voice.speech_recognition_failed"
    SPEAKING_STARTED = "voice.speaking_started"
    SPEAKING_FINISHED = "voice.speaking_finished"

    # Brain / AI
    INTENT_CLASSIFIED = "brain.intent_classified"
    AI_RESPONSE_CHUNK = "ai.response_chunk"
    AI_RESPONSE_COMPLETE = "ai.response_complete"
    AI_ERROR = "ai.error"

    # Commands / automation
    COMMAND_EXECUTED = "command.executed"
    COMMAND_FAILED = "command.failed"

    # Memory / history
    MEMORY_UPDATED = "memory.updated"
    HISTORY_APPENDED = "history.appended"
    HISTORY_CLEARED = "history.cleared"

    # Scheduler
    REMINDER_DUE = "scheduler.reminder_due"
    TASK_SCHEDULED = "scheduler.task_scheduled"

    # UI
    THEME_CHANGED = "ui.theme_changed"
    SETTINGS_CHANGED = "ui.settings_changed"
    NOTIFICATION_REQUESTED = "ui.notification_requested"


@dataclass
class Subscription:
    """A single handler registration, returned so callers can unsubscribe."""

    id: str
    event_name: str
    handler: EventHandler
    once: bool = False


class EventBus:
    """Thread-safe synchronous/asynchronous pub-sub event bus."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history: list[tuple[str, Any]] = []
        self._max_history = 200

    # -- subscription management ------------------------------------- #

    def subscribe(self, event_name: str, handler: EventHandler, once: bool = False) -> str:
        """
        Register `handler` to be called whenever `event_name` is emitted.

        Returns:
            A subscription id usable with `unsubscribe()`.
        """
        sub = Subscription(id=str(uuid.uuid4()), event_name=event_name, handler=handler, once=once)
        with self._lock:
            self._subscriptions[event_name].append(sub)
        logger.debug("Subscribed handler %s to event '%s'.", handler.__name__, event_name)
        return sub.id

    def subscribe_once(self, event_name: str, handler: EventHandler) -> str:
        """Convenience wrapper for a subscription that auto-removes after firing once."""
        return self.subscribe(event_name, handler, once=True)

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by id. Returns True if it was found and removed."""
        with self._lock:
            for event_name, subs in self._subscriptions.items():
                for sub in subs:
                    if sub.id == subscription_id:
                        subs.remove(sub)
                        logger.debug("Unsubscribed %s from '%s'.", subscription_id, event_name)
                        return True
        return False

    def unsubscribe_all(self, event_name: Optional[str] = None) -> None:
        """Remove all subscriptions, optionally scoped to a single event name."""
        with self._lock:
            if event_name is None:
                self._subscriptions.clear()
            else:
                self._subscriptions.pop(event_name, None)

    # -- emission -------------------------------------------------------- #

    def emit(self, event_name: str, payload: Any = None) -> None:
        """
        Synchronously notify all subscribers of `event_name`. Handler
        exceptions are caught and logged so one broken subscriber cannot
        break the publisher or other subscribers.
        """
        with self._lock:
            subs = list(self._subscriptions.get(event_name, []))
            self._record_history(event_name, payload)

        if not subs:
            logger.debug("Event '%s' emitted with no subscribers.", event_name)

        for sub in subs:
            try:
                sub.handler(payload)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Handler '%s' raised while handling event '%s'.",
                    getattr(sub.handler, "__name__", repr(sub.handler)),
                    event_name,
                )
            finally:
                if sub.once:
                    self.unsubscribe(sub.id)

    def emit_async(self, event_name: str, payload: Any = None) -> threading.Thread:
        """
        Fire-and-forget variant of emit(), running delivery on a daemon
        thread so the caller never blocks on slow subscribers.
        """
        thread = threading.Thread(
            target=self.emit, args=(event_name, payload), daemon=True, name=f"event-{event_name}"
        )
        thread.start()
        return thread

    # -- introspection / debugging ---------------------------------------- #

    def _record_history(self, event_name: str, payload: Any) -> None:
        self._history.append((event_name, payload))
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def recent_events(self, limit: int = 20) -> list[tuple[str, Any]]:
        """Return the most recent emitted events, for debugging/inspection."""
        with self._lock:
            return self._history[-limit:]

    def subscriber_count(self, event_name: str) -> int:
        with self._lock:
            return len(self._subscriptions.get(event_name, []))


# Module-level singleton shared across the whole application.
event_bus: EventBus = EventBus()
