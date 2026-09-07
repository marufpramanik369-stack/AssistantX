"""
startup.py
==========
Orchestrates the application's boot sequence in the correct order,
independent of whether the entry point is main.py (CLI), launcher.py
(GUI splash + dashboard), or a test harness. Centralizing this avoids
subtle bugs where two entry points initialize subsystems in a different
order and hit different bugs.

Boot order:
    1. Logging            (core.logger)
    2. Configuration       (config.config.app_config.bootstrap)
    3. Core singletons     (history, memory, scheduler, command_router)
    4. Event bus wiring    (cross-subsystem listeners)
    5. Scheduler start     (background thread)
    6. APP_STARTED event emitted

Usage:
    from core.startup import bootstrap_app

    if __name__ == "__main__":
        bootstrap_app()
        ...
"""

from __future__ import annotations

import atexit
import signal
import sys
import threading
from typing import Optional

from core.logger import get_logger, setup_logging

logger = get_logger(__name__)

_bootstrapped = False
_shutdown_lock = threading.Lock()
_shutdown_done = False


def _wire_core_event_listeners() -> None:
    """
    Connect core subsystems to each other via the event bus. This is the
    one place allowed to know about multiple core modules at once, so
    that history.py, memory.py, and scheduler.py don't import each other
    directly.
    """
    from core.event_bus import Events, event_bus
    from core.history import history_manager

    def _on_command_executed(payload: dict) -> None:
        # Every successful command execution also becomes part of the
        # visible conversation transcript for context continuity.
        message = payload.get("message")
        if message:
            history_manager.add_assistant_message(message, intent=payload.get("intent"))

    event_bus.subscribe(Events.COMMAND_EXECUTED, _on_command_executed)
    logger.debug("Core event listeners wired.")


def _register_shutdown_hooks() -> None:
    """Ensure graceful shutdown runs on normal exit AND on SIGINT/SIGTERM."""
    atexit.register(shutdown_app)

    def _signal_handler(signum, _frame) -> None:  # noqa: ANN001
        logger.info("Received signal %s; shutting down gracefully.", signum)
        shutdown_app()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        # Signal handling only works in the main thread of the main
        # interpreter; silently skip if we're not in that context
        # (e.g. running inside a test runner or embedded interpreter).
        logger.debug("Could not register signal handlers in this context.")


def bootstrap_app(
    log_level: Optional[str] = None,
    strict_secrets: bool = False,
    start_scheduler: bool = True,
) -> None:
    """
    Run the full application bootstrap sequence. Idempotent — calling
    this more than once is a no-op after the first successful call.

    Args:
        log_level: Optional override for the root log level.
        strict_secrets: Passed through to AppConfig.bootstrap(); if True,
            missing required API keys raise instead of just warning.
        start_scheduler: Whether to start the background scheduler thread
            immediately. Test harnesses may want this False.
    """
    global _bootstrapped
    if _bootstrapped:
        logger.debug("bootstrap_app() called again; ignoring.")
        return

    # 1. Logging must come first so every subsequent step can log.
    setup_logging(level=log_level)
    logger.info("=" * 60)
    logger.info("Starting AssistantX...")

    # 2. Configuration (env, secrets, settings, theme).
    from config.config import app_config

    app_config.bootstrap(strict_secrets=strict_secrets)

    # 3. Core singletons are imported (which triggers their own module-level
    #    initialization) — done here explicitly so import order is obvious
    #    and centrally controlled rather than implicit via other modules.
    #    NOTE: we import the singleton objects directly rather than the
    #    submodules themselves, because core/__init__.py re-exports these
    #    same names (e.g. `core.scheduler`) as singleton instances, which
    #    would shadow the submodule if imported via `from core import x`.
    from core.command_router import command_router as _command_router  # noqa: F401
    from core.history import history_manager as _history_manager  # noqa: F401
    from core.memory import memory_manager as _memory_manager  # noqa: F401
    from core.scheduler import scheduler as _scheduler

    # 4. Wire cross-module event listeners.
    _wire_core_event_listeners()

    # 5. Start background scheduler.
    if start_scheduler:
        _scheduler.start()

    # 6. Register graceful shutdown handling.
    _register_shutdown_hooks()

    _bootstrapped = True

    from core.event_bus import Events, event_bus

    event_bus.emit(Events.APP_STARTED, {"version": app_config.settings_manager is not None})
    logger.info("AssistantX startup complete.")
    logger.info("=" * 60)


def shutdown_app() -> None:
    """
    Gracefully tear down background resources (scheduler thread, open
    file handles via final saves, etc.). Idempotent.
    """
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    logger.info("Shutting down AssistantX...")

    try:
        from core.event_bus import Events, event_bus

        event_bus.emit(Events.APP_SHUTTING_DOWN, {})
    except Exception:  # noqa: BLE001
        pass

    try:
        from core.scheduler import scheduler

        scheduler.stop()
    except Exception:  # noqa: BLE001
        logger.exception("Error stopping scheduler during shutdown.")

    try:
        from core.history import history_manager

        history_manager.save()
    except Exception:  # noqa: BLE001
        logger.exception("Error saving history during shutdown.")

    try:
        from core.memory import memory_manager

        memory_manager.save()
    except Exception:  # noqa: BLE001
        logger.exception("Error saving memory during shutdown.")

    logger.info("AssistantX shutdown complete. Goodbye!")


def is_bootstrapped() -> bool:
    return _bootstrapped
    