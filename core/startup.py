"""
core.startup
============

Centralized AssistantX application lifecycle manager.

Responsible for:

1. Logging initialization
2. Configuration bootstrap
3. Core subsystem initialization
4. Event-bus listener wiring
5. Scheduler startup
6. Shutdown hook registration
7. APP_STARTED event emission
8. Graceful and idempotent shutdown

The goal is to ensure that every AssistantX entry point
(main.py, launcher.py, tests, etc.) uses the same lifecycle.

Example
-------

    from core.startup import bootstrap_app, shutdown_app

    bootstrap_app()

    try:
        ...
    finally:
        shutdown_app()
"""

from __future__ import annotations

import atexit
import signal
import threading
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, Self

from core.logger import get_logger, setup_logging

# ============================================================================
# Types
# ============================================================================


class StartupState(str, Enum):
    """Application lifecycle states."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class StartupInfo:
    """Snapshot of the current AssistantX lifecycle state."""

    state: StartupState
    bootstrapped: bool
    scheduler_running: bool
    shutdown_done: bool
    listeners_wired: bool


# ============================================================================
# Logger
# ============================================================================

logger = get_logger(__name__)


# ============================================================================
# Internal state
# ============================================================================

_state = StartupState.NOT_STARTED

_bootstrapped = False
_shutdown_done = False
_listeners_wired = False
_hooks_registered = False

_bootstrap_lock = threading.RLock()
_shutdown_lock = threading.Lock()


# ============================================================================
# Event listeners
# ============================================================================


def _wire_core_event_listeners() -> None:
    """
    Register cross-subsystem event listeners.

    This is intentionally kept inside startup.py so core modules do not
    need to import each other directly.
    """

    global _listeners_wired

    if _listeners_wired:
        logger.debug(
            "Core event listeners already wired."
        )
        return

    from core.event_bus import Events, event_bus
    from core.history import history_manager

    def _on_command_executed(
        payload: dict[str, Any] | None,
    ) -> None:
        """
        Store successful command output in conversation history.
        """

        if not isinstance(payload, dict):
            logger.debug(
                "Ignoring malformed COMMAND_EXECUTED payload."
            )
            return

        message = payload.get("message")

        if not message:
            return

        try:
            history_manager.add_assistant_message(
                str(message),
                intent=payload.get("intent"),
            )

        except Exception:
            logger.exception(
                "Failed to persist command execution "
                "to conversation history."
            )

    try:
        event_bus.subscribe(
            Events.COMMAND_EXECUTED,
            _on_command_executed,
        )

        _listeners_wired = True

        logger.debug(
            "Core event listeners wired successfully."
        )

    except Exception:
        logger.exception(
            "Failed to wire core event listeners."
        )
        raise


# ============================================================================
# Shutdown hooks
# ============================================================================


def _register_shutdown_hooks() -> None:
    """
    Register atexit and signal handlers.

    Signal handlers are only registered when running in the main thread.
    """

    global _hooks_registered

    if _hooks_registered:
        logger.debug(
            "Shutdown hooks already registered."
        )
        return

    # ------------------------------------------------------------------------
    # Normal interpreter exit
    # ------------------------------------------------------------------------

    try:
        atexit.register(shutdown_app)
    except Exception:
        logger.exception(
            "Failed to register atexit shutdown hook."
        )

    # ------------------------------------------------------------------------
    # Signal handler
    # ------------------------------------------------------------------------

    def _signal_handler(
        signum: int,
        _frame: Any,
    ) -> None:
        logger.info(
            "Received signal %s. "
            "Starting graceful shutdown.",
            signum,
        )

        try:
            shutdown_app()
        finally:
            # Avoid calling sys.exit() from non-main contexts.
            if threading.current_thread() is threading.main_thread():
                raise SystemExit(0)

    try:
        signal.signal(
            signal.SIGINT,
            _signal_handler,
        )

        # SIGTERM does not exist on every platform.
        if hasattr(signal, "SIGTERM"):
            signal.signal(
                signal.SIGTERM,
                _signal_handler,
            )

        _hooks_registered = True

        logger.debug(
            "Shutdown hooks registered."
        )

    except (
        ValueError,
        OSError,
        RuntimeError,
    ):
        # Common when called from a worker thread,
        # test runner, embedded interpreter, etc.
        logger.debug(
            "Signal handlers could not be registered "
            "in the current execution context."
        )


# ============================================================================
# Subsystem initialization
# ============================================================================


def _initialize_core_subsystems() -> dict[str, Any]:
    """
    Import and initialize core singletons.

    Imports are intentionally performed here rather than at module level
    to preserve the application's controlled boot order.
    """

    logger.debug(
        "Initializing core subsystems..."
    )

    from core.command_router import (
        command_router,
    )
    from core.history import (
        history_manager,
    )
    from core.memory import (
        memory_manager,
    )
    from core.scheduler import (
        scheduler,
    )

    subsystems = {
        "command_router": command_router,
        "history": history_manager,
        "memory": memory_manager,
        "scheduler": scheduler,
    }

    logger.debug(
        "Core subsystems initialized: %s",
        ", ".join(subsystems.keys()),
    )

    return subsystems


# ============================================================================
# Scheduler
# ============================================================================


def _start_scheduler(
    scheduler: Any,
) -> None:
    """
    Start the background scheduler safely.
    """

    if scheduler is None:
        logger.warning(
            "Scheduler object is unavailable."
        )
        return

    try:
        scheduler.start()

        logger.info(
            "Background scheduler started."
        )

    except Exception:
        logger.exception(
            "Failed to start background scheduler."
        )
        raise


# ============================================================================
# Bootstrap
# ============================================================================


def bootstrap_app(
    log_level: str | None = None,
    strict_secrets: bool = False,
    start_scheduler: bool = True,
) -> None:
    """
    Bootstrap AssistantX.

    This function is thread-safe and idempotent.

    Parameters
    ----------
    log_level:
        Optional logging level override.

    strict_secrets:
        Passed to AppConfig.bootstrap().

    start_scheduler:
        Whether to start the background scheduler.

    Raises
    ------
    Exception
        Re-raises bootstrap failures so callers can decide how to handle
        application startup errors.
    """

    global _bootstrapped
    global _shutdown_done
    global _state

    with _bootstrap_lock:

        # --------------------------------------------------------------------
        # Already running
        # --------------------------------------------------------------------

        if _state is StartupState.RUNNING:
            logger.debug(
                "bootstrap_app() called while AssistantX "
                "is already running."
            )
            return

        # --------------------------------------------------------------------
        # Currently starting
        # --------------------------------------------------------------------

        if _state is StartupState.STARTING:
            logger.warning(
                "bootstrap_app() called while startup "
                "is already in progress."
            )
            return

        # --------------------------------------------------------------------
        # Previously stopped
        # --------------------------------------------------------------------

        if _state is StartupState.STOPPING:
            raise RuntimeError(
                "AssistantX is currently shutting down."
            )

        _state = StartupState.STARTING

        # Reset lifecycle flag for a new successful startup.
        _shutdown_done = False

        logger.info("=" * 70)
        logger.info("Starting AssistantX...")
        logger.info("=" * 70)

        try:

            # ================================================================
            # 1. Logging
            # ================================================================

            setup_logging(
                level=log_level
            )

            logger.info(
                "[1/6] Logging initialized."
            )

            # ================================================================
            # 2. Configuration
            # ================================================================

            from config.config import app_config

            app_config.bootstrap(
                strict_secrets=strict_secrets
            )

            logger.info(
                "[2/6] Configuration loaded."
            )

            # ================================================================
            # 3. Core subsystems
            # ================================================================

            subsystems = _initialize_core_subsystems()

            logger.info(
                "[3/6] Core subsystems initialized."
            )

            # ================================================================
            # 4. Event bus
            # ================================================================

            _wire_core_event_listeners()

            logger.info(
                "[4/6] Event listeners wired."
            )

            # ================================================================
            # 5. Scheduler
            # ================================================================

            if start_scheduler:
                _start_scheduler(
                    subsystems["scheduler"]
                )
            else:
                logger.info(
                    "[5/6] Scheduler start skipped."
                )

            if start_scheduler:
                logger.info(
                    "[5/6] Scheduler started."
                )

            # ================================================================
            # 6. Shutdown hooks
            # ================================================================

            _register_shutdown_hooks()

            logger.info(
                "[6/6] Shutdown hooks registered."
            )

            # ================================================================
            # Mark application as running
            # ================================================================

            _bootstrapped = True
            _state = StartupState.RUNNING

            # ================================================================
            # APP_STARTED event
            # ================================================================

            from core.event_bus import (
                Events,
                event_bus,
            )

            event_bus.emit(
                Events.APP_STARTED,
                {
                    "version": getattr(
                        app_config,
                        "version",
                        None,
                    ),
                    "scheduler_started": start_scheduler,
                },
            )

            logger.info("=" * 70)
            logger.info(
                "AssistantX startup complete."
            )
            logger.info("=" * 70)

        except Exception:

            _state = StartupState.FAILED
            _bootstrapped = False

            logger.exception(
                "AssistantX startup failed.",
            )

            # Try to stop partially-started resources.
            try:
                _shutdown_partial_startup()
            except Exception:
                logger.exception(
                    "Failed to clean up partial startup."
                )

            raise


# ============================================================================
# Partial startup cleanup
# ============================================================================


def _shutdown_partial_startup() -> None:
    """
    Best-effort cleanup when bootstrap fails halfway through.
    """

    try:
        from core.scheduler import scheduler

        scheduler.stop()

        logger.debug(
            "Partial-startup scheduler cleanup completed."
        )

    except Exception:
        # Scheduler may not have been initialized yet.
        logger.debug(
            "Partial-startup scheduler cleanup skipped.",
            exc_info=True,
        )


# ============================================================================
# Shutdown
# ============================================================================


def shutdown_app() -> None:
    """
    Gracefully shut down AssistantX.

    Shutdown order:

    1. APP_SHUTTING_DOWN event
    2. Scheduler stop
    3. History save
    4. Memory save
    5. Final state update

    The function is fully idempotent.
    """

    global _shutdown_done
    global _bootstrapped
    global _state

    with _shutdown_lock:

        if _shutdown_done:
            logger.debug(
                "shutdown_app() called again; ignoring."
            )
            return

        _shutdown_done = True
        _state = StartupState.STOPPING

    logger.info("=" * 70)
    logger.info(
        "Shutting down AssistantX..."
    )
    logger.info("=" * 70)

    # ------------------------------------------------------------------------
    # 1. Notify subsystems
    # ------------------------------------------------------------------------

    try:
        from core.event_bus import (
            Events,
            event_bus,
        )

        event_bus.emit(
            Events.APP_SHUTTING_DOWN,
            {},
        )

    except Exception:
        logger.exception(
            "Failed to emit APP_SHUTTING_DOWN event."
        )

    # ------------------------------------------------------------------------
    # 2. Stop scheduler
    # ------------------------------------------------------------------------

    try:
        from core.scheduler import scheduler

        scheduler.stop()

        logger.info(
            "Scheduler stopped."
        )

    except Exception:
        logger.exception(
            "Error stopping scheduler during shutdown."
        )

    # ------------------------------------------------------------------------
    # 3. Save history
    # ------------------------------------------------------------------------

    try:
        from core.history import history_manager

        history_manager.save()

        logger.info(
            "Conversation history saved."
        )

    except Exception:
        logger.exception(
            "Error saving conversation history."
        )

    # ------------------------------------------------------------------------
    # 4. Save memory
    # ------------------------------------------------------------------------

    try:
        from core.memory import memory_manager

        memory_manager.save()

        logger.info(
            "Long-term memory saved."
        )

    except Exception:
        logger.exception(
            "Error saving long-term memory."
        )

    # ------------------------------------------------------------------------
    # 5. Final state
    # ------------------------------------------------------------------------

    with _shutdown_lock:
        _bootstrapped = False
        _state = StartupState.STOPPED

    logger.info("=" * 70)
    logger.info(
        "AssistantX shutdown complete. Goodbye!"
    )
    logger.info("=" * 70)


# ============================================================================
# Lifecycle helpers
# ============================================================================


def is_bootstrapped() -> bool:
    """
    Return True when AssistantX is fully running.
    """

    return _bootstrapped


def is_running() -> bool:
    """
    Return True when application lifecycle state is RUNNING.
    """

    return _state is StartupState.RUNNING


def is_shutting_down() -> bool:
    """
    Return True when shutdown is in progress.
    """

    return _state is StartupState.STOPPING


def is_shutdown() -> bool:
    """
    Return True when application has stopped.
    """

    return _state is StartupState.STOPPED


def get_startup_state() -> StartupState:
    """
    Return current lifecycle state.
    """

    return _state


def get_startup_info() -> StartupInfo:
    """
    Return a snapshot of startup/shutdown status.
    """

    scheduler_running = False

    try:
        from core.scheduler import scheduler

        # Support common scheduler APIs without requiring one exact
        # implementation.
        if hasattr(scheduler, "is_running"):
            value = scheduler.is_running

            if callable(value):
                value = value()

            scheduler_running = bool(value)

        elif hasattr(scheduler, "running"):
            scheduler_running = bool(
                scheduler.running
            )

    except (ImportError, AttributeError, TypeError, RuntimeError):
        scheduler_running = False

    return StartupInfo(
        state=_state,
        bootstrapped=_bootstrapped,
        scheduler_running=scheduler_running,
        shutdown_done=_shutdown_done,
        listeners_wired=_listeners_wired,
    )


def startup_diagnostics() -> dict[str, Any]:
    """
    Return diagnostic information about application lifecycle.
    """

    info = get_startup_info()

    return {
        "module": "core.startup",
        "state": info.state.value,
        "bootstrapped": info.bootstrapped,
        "scheduler_running": info.scheduler_running,
        "shutdown_done": info.shutdown_done,
        "listeners_wired": info.listeners_wired,
        "hooks_registered": _hooks_registered,
    }


# ============================================================================
# Context manager
# ============================================================================


class ApplicationLifecycle:
    """
    Context manager for controlled AssistantX lifecycle.

    Example
    -------

        with ApplicationLifecycle():
            run_application()
    """

    def __init__(
        self,
        *,
        log_level: str | None = None,
        strict_secrets: bool = False,
        start_scheduler: bool = True,
    ) -> None:

        self.log_level = log_level
        self.strict_secrets = strict_secrets
        self.start_scheduler = start_scheduler

    def __enter__(self) -> Self:
        bootstrap_app(
            log_level=self.log_level,
            strict_secrets=self.strict_secrets,
            start_scheduler=self.start_scheduler,
        )

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:

        shutdown_app()

        # Do not suppress application exceptions.
        return False


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "ApplicationLifecycle",
    "StartupInfo",
    # Lifecycle
    "StartupState",
    # Bootstrap / shutdown
    "bootstrap_app",
    "get_startup_info",
    "get_startup_state",
    # State helpers
    "is_bootstrapped",
    "is_running",
    "is_shutdown",
    "is_shutting_down",
    "shutdown_app",
    # Diagnostics
    "startup_diagnostics",
]
