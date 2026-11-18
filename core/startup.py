"""
core/startup.py — Production-Grade AssistantX Application Lifecycle
=====================================================================

Centralized application lifecycle manager.

Responsibilities
----------------
1. Configure logging
2. Bootstrap application configuration
3. Initialize core subsystems
4. Wire core event listeners exactly once per process
5. Start the scheduler
6. Register process shutdown hooks
7. Emit lifecycle events
8. Perform graceful, idempotent shutdown
9. Recover safely from partial startup failures

Lifecycle
---------

    NOT_STARTED
        ↓
    STARTING
        ↓
      RUNNING
        ↓
     STOPPING
        ↓
      STOPPED

Any startup failure:

    STARTING
        ↓
      FAILED
        ↓
    cleanup
        ↓
      STOPPED

Design Notes
------------
- No module-level get_logger() call is used before bootstrap.
- Logging configuration therefore happens in the intended startup order.
- Startup is thread-safe.
- Shutdown is idempotent.
- Event listeners are not duplicated across repeated bootstrap calls.
- Signal handlers are only installed from the main thread.
- Partial startup resources are cleaned up best-effort.
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
# Lifecycle State
# ============================================================================


class StartupState(str, Enum):
    """AssistantX application lifecycle states."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StartupInfo:
    """Immutable snapshot of the current application lifecycle."""

    state: StartupState
    bootstrapped: bool
    scheduler_running: bool
    shutdown_done: bool
    listeners_wired: bool
    hooks_registered: bool


# ============================================================================
# Internal State
# ============================================================================

_state = StartupState.NOT_STARTED

_bootstrapped = False
_shutdown_done = False
_listeners_wired = False
_hooks_registered = False

_bootstrap_lock = threading.RLock()
_shutdown_lock = threading.RLock()
_listener_lock = threading.RLock()
_hooks_lock = threading.RLock()


# ============================================================================
# Logger Access
# ============================================================================


def _logger():
    """
    Return the startup logger lazily.

    Important:
        Do not create a module-level logger during import because
        core.logger.get_logger() may auto-initialize logging before
        bootstrap_app() receives its requested configuration.
    """

    return get_logger(__name__)


# ============================================================================
# Event Listener Wiring
# ============================================================================


def _wire_core_event_listeners() -> None:
    """
    Wire cross-subsystem event listeners.

    Listener registration is guarded so repeated bootstrap calls never
    register the same callback more than once.
    """

    global _listeners_wired

    with _listener_lock:

        if _listeners_wired:
            _logger().debug(
                "Core event listeners already wired."
            )
            return

        from core.event_bus import Events, event_bus
        from core.history import history_manager

        def _on_command_executed(
            payload: dict[str, Any] | None,
        ) -> None:
            """
            Persist command output into conversation history.

            Only payloads containing a non-empty ``message`` are persisted.
            """

            if not isinstance(payload, dict):
                _logger().debug(
                    "Ignoring malformed COMMAND_EXECUTED payload."
                )
                return

            message = payload.get("message")

            if message is None:
                return

            text = str(message).strip()

            if not text:
                return

            try:
                history_manager.add_assistant_message(
                    text,
                    intent=payload.get("intent"),
                )

            except Exception:
                _logger().exception(
                    "Failed to persist command execution "
                    "to conversation history."
                )

        try:
            event_bus.subscribe(
                Events.COMMAND_EXECUTED,
                _on_command_executed,
            )

            _listeners_wired = True

            _logger().debug(
                "Core event listeners wired successfully."
            )

        except Exception:
            _logger().exception(
                "Failed to wire core event listeners."
            )
            raise


# ============================================================================
# Shutdown Hook Registration
# ============================================================================


def _register_shutdown_hooks() -> None:
    """
    Register interpreter-exit and OS signal shutdown hooks.

    atexit registration is always attempted.

    SIGINT/SIGTERM are installed only from the main thread because Python
    restricts signal registration to the main interpreter thread.
    """

    global _hooks_registered

    with _hooks_lock:

        if _hooks_registered:
            _logger().debug(
                "Shutdown hooks already registered."
            )
            return

        # ------------------------------------------------------------------
        # atexit
        # ------------------------------------------------------------------

        try:
            atexit.register(shutdown_app)
        except Exception:
            _logger().exception(
                "Failed to register atexit shutdown hook."
            )

        # ------------------------------------------------------------------
        # Signals
        # ------------------------------------------------------------------

        if threading.current_thread() is not threading.main_thread():
            _logger().debug(
                "Skipping signal registration because startup "
                "is running outside the main thread."
            )

            _hooks_registered = True
            return

        def _signal_handler(
            signum: int,
            _frame: Any,
        ) -> None:
            """
            Handle SIGINT/SIGTERM gracefully.
            """

            _logger().info(
                "Received signal %s. Starting graceful shutdown.",
                signum,
            )

            shutdown_app()

            raise SystemExit(0)

        try:
            signal.signal(
                signal.SIGINT,
                _signal_handler,
            )

            if hasattr(signal, "SIGTERM"):
                signal.signal(
                    signal.SIGTERM,
                    _signal_handler,
                )

        except (
            ValueError,
            OSError,
            RuntimeError,
        ):
            # Embedded environments/test runners may reject signal handlers.
            _logger().debug(
                "Signal handlers could not be registered "
                "in the current execution context.",
                exc_info=True,
            )

        _hooks_registered = True

        _logger().debug(
            "Shutdown hooks registered."
        )


# ============================================================================
# Core Subsystem Initialization
# ============================================================================


def _initialize_core_subsystems() -> dict[str, Any]:
    """
    Import and initialize AssistantX core singleton modules.

    Imports intentionally happen during bootstrap to maintain predictable
    initialization order.
    """

    _logger().debug(
        "Initializing core subsystems..."
    )

    from core.command_router import command_router
    from core.history import history_manager
    from core.memory import memory_manager
    from core.scheduler import scheduler

    subsystems = {
        "command_router": command_router,
        "history": history_manager,
        "memory": memory_manager,
        "scheduler": scheduler,
    }

    _logger().debug(
        "Core subsystems available: %s",
        ", ".join(subsystems.keys()),
    )

    return subsystems


# ============================================================================
# Scheduler
# ============================================================================


def _scheduler_is_running(
    scheduler: Any,
) -> bool:
    """
    Determine scheduler running state while supporting common scheduler APIs.
    """

    if scheduler is None:
        return False

    try:
        value = getattr(
            scheduler,
            "is_running",
            None,
        )

        if callable(value):
            return bool(value())

        if value is not None:
            return bool(value)

        value = getattr(
            scheduler,
            "running",
            None,
        )

        if callable(value):
            return bool(value())

        if value is not None:
            return bool(value)

    except Exception:
        return False

    return False


def _start_scheduler(
    scheduler: Any,
) -> None:
    """
    Start the background scheduler if available and not already running.
    """

    if scheduler is None:
        raise RuntimeError(
            "Scheduler subsystem is unavailable."
        )

    if _scheduler_is_running(scheduler):
        _logger().debug(
            "Scheduler is already running."
        )
        return

    try:
        scheduler.start()

    except Exception:
        _logger().exception(
            "Failed to start background scheduler."
        )
        raise

    _logger().info(
        "Background scheduler started."
    )


def _stop_scheduler(
    scheduler: Any,
) -> None:
    """
    Stop scheduler safely.

    If the scheduler is already stopped, no error is raised.
    """

    if scheduler is None:
        return

    if not _scheduler_is_running(scheduler):
        _logger().debug(
            "Scheduler already stopped."
        )
        return

    try:
        scheduler.stop()
        _logger().info(
            "Scheduler stopped."
        )

    except Exception:
        _logger().exception(
            "Error stopping scheduler."
        )


# ============================================================================
# Logging Initialization
# ============================================================================


def _initialize_logging(
    log_level: str | None,
) -> None:
    """
    Initialize AssistantX logging.

    This is deliberately the first bootstrap operation.
    """

    setup_logging(
        level=log_level,
        console=True,
        log_to_files=True,
    )

    _logger().info(
        "[1/6] Logging initialized."
    )


# ============================================================================
# Partial Startup Cleanup
# ============================================================================


def _shutdown_partial_startup(
    subsystems: dict[str, Any] | None = None,
) -> None:
    """
    Best-effort cleanup after a failed bootstrap.

    This function never raises its own cleanup errors.
    """

    resources = subsystems or {}

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    try:
        scheduler = resources.get("scheduler")

        if scheduler is None:
            try:
                from core.scheduler import scheduler as global_scheduler

                scheduler = global_scheduler

            except Exception:
                scheduler = None

        _stop_scheduler(
            scheduler
        )

    except Exception:
        _logger().debug(
            "Partial-startup scheduler cleanup failed.",
            exc_info=True,
        )

    # ------------------------------------------------------------------
    # Other core subsystems currently do not require explicit shutdown.
    # Their persistent state is saved during normal shutdown.
    # ------------------------------------------------------------------


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

    Parameters
    ----------
    log_level:
        Optional logging level override.

    strict_secrets:
        Passed to ``app_config.bootstrap()``.

    start_scheduler:
        Whether the background scheduler should be started.

    Notes
    -----
    The function is thread-safe and idempotent while RUNNING.

    A failed startup raises the original exception after best-effort cleanup.
    """

    global _state
    global _bootstrapped
    global _shutdown_done

    with _bootstrap_lock:

        # ------------------------------------------------------------------
        # Already running
        # ------------------------------------------------------------------

        if _state is StartupState.RUNNING:
            _logger().debug(
                "bootstrap_app() called while AssistantX is already running."
            )
            return

        # ------------------------------------------------------------------
        # Startup already in progress
        # ------------------------------------------------------------------

        if _state is StartupState.STARTING:
            _logger().warning(
                "bootstrap_app() called while startup is already in progress."
            )
            return

        # ------------------------------------------------------------------
        # Shutdown in progress
        # ------------------------------------------------------------------

        if _state is StartupState.STOPPING:
            raise RuntimeError(
                "AssistantX is currently shutting down."
            )

        # ------------------------------------------------------------------
        # Begin startup
        # ------------------------------------------------------------------

        _state = StartupState.STARTING
        _bootstrapped = False
        _shutdown_done = False

        # Resources initialized during this startup attempt.
        subsystems: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # Logging must be initialized before using startup logger.
        # ------------------------------------------------------------------

        try:
            _initialize_logging(
                log_level
            )

            _logger().info("=" * 70)
            _logger().info(
                "Starting AssistantX..."
            )
            _logger().info("=" * 70)

            # ==============================================================
            # 2. Configuration
            # ==============================================================

            from config.config import app_config

            app_config.bootstrap(
                strict_secrets=strict_secrets
            )

            _logger().info(
                "[2/6] Configuration loaded."
            )

            # ==============================================================
            # 3. Core subsystems
            # ==============================================================

            subsystems = _initialize_core_subsystems()

            _logger().info(
                "[3/6] Core subsystems initialized."
            )

            # ==============================================================
            # 4. Event listeners
            # ==============================================================

            _wire_core_event_listeners()

            _logger().info(
                "[4/6] Event listeners wired."
            )

            # ==============================================================
            # 5. Scheduler
            # ==============================================================

            if start_scheduler:
                _start_scheduler(
                    subsystems["scheduler"]
                )

                _logger().info(
                    "[5/6] Scheduler started."
                )

            else:
                _logger().info(
                    "[5/6] Scheduler start skipped."
                )

            # ==============================================================
            # 6. Shutdown hooks
            # ==============================================================

            _register_shutdown_hooks()

            _logger().info(
                "[6/6] Shutdown hooks registered."
            )

            # ==============================================================
            # Mark RUNNING before APP_STARTED
            # ==============================================================

            _bootstrapped = True
            _state = StartupState.RUNNING

            # ==============================================================
            # APP_STARTED
            # ==============================================================

            from core.event_bus import Events, event_bus

            event_bus.emit(
                Events.APP_STARTED,
                {
                    "scheduler_started": bool(
                        start_scheduler
                    ),
                    "startup_state": _state.value,
                },
            )

            _logger().info("=" * 70)
            _logger().info(
                "AssistantX startup complete."
            )
            _logger().info("=" * 70)

        except Exception:

            _state = StartupState.FAILED
            _bootstrapped = False

            _logger().exception(
                "AssistantX startup failed."
            )

            _shutdown_partial_startup(
                subsystems
            )

            # After cleanup, remain FAILED so diagnostics can explain that
            # startup failed rather than pretending the application stopped
            # normally.
            _shutdown_done = False

            raise


# ============================================================================
# Shutdown
# ============================================================================


def shutdown_app() -> None:
    """
    Gracefully shut down AssistantX.

    Shutdown order
    --------------
    1. Transition to STOPPING
    2. Emit APP_SHUTTING_DOWN
    3. Stop scheduler
    4. Save history
    5. Save memory
    6. Mark STOPPED

    The operation is idempotent.
    """

    global _state
    global _bootstrapped
    global _shutdown_done

    with _shutdown_lock:

        if _shutdown_done:
            _logger().debug(
                "shutdown_app() already completed; ignoring duplicate call."
            )
            return

        if _state is StartupState.STOPPING:
            _logger().debug(
                "shutdown_app() already in progress."
            )
            return

        # Nothing was ever started.
        if _state is StartupState.NOT_STARTED:
            _shutdown_done = True
            _bootstrapped = False
            _state = StartupState.STOPPED

            return

        _shutdown_done = True
        _state = StartupState.STOPPING

    _logger().info("=" * 70)
    _logger().info(
        "Shutting down AssistantX..."
    )
    _logger().info("=" * 70)

    # ------------------------------------------------------------------
    # 1. APP_SHUTTING_DOWN
    # ------------------------------------------------------------------

    try:
        from core.event_bus import Events, event_bus

        event_bus.emit(
            Events.APP_SHUTTING_DOWN,
            {
                "state": StartupState.STOPPING.value,
            },
        )

    except Exception:
        _logger().exception(
            "Failed to emit APP_SHUTTING_DOWN event."
        )

    # ------------------------------------------------------------------
    # 2. Scheduler
    # ------------------------------------------------------------------

    try:
        from core.scheduler import scheduler

        _stop_scheduler(
            scheduler
        )

    except Exception:
        _logger().exception(
            "Error accessing scheduler during shutdown."
        )

    # ------------------------------------------------------------------
    # 3. History
    # ------------------------------------------------------------------

    try:
        from core.history import history_manager

        history_manager.save()

        _logger().info(
            "Conversation history saved."
        )

    except Exception:
        _logger().exception(
            "Error saving conversation history."
        )

    # ------------------------------------------------------------------
    # 4. Memory
    # ------------------------------------------------------------------

    try:
        from core.memory import memory_manager

        memory_manager.save()

        _logger().info(
            "Long-term memory saved."
        )

    except Exception:
        _logger().exception(
            "Error saving long-term memory."
        )

    # ------------------------------------------------------------------
    # 5. Final state
    # ------------------------------------------------------------------

    with _shutdown_lock:
        _bootstrapped = False
        _state = StartupState.STOPPED

    _logger().info("=" * 70)
    _logger().info(
        "AssistantX shutdown complete."
    )
    _logger().info("=" * 70)


# ============================================================================
# Lifecycle State Helpers
# ============================================================================


def is_bootstrapped() -> bool:
    """Return True when AssistantX is fully initialized."""

    return _bootstrapped


def is_running() -> bool:
    """Return True when lifecycle state is RUNNING."""

    return _state is StartupState.RUNNING


def is_shutting_down() -> bool:
    """Return True while shutdown is in progress."""

    return _state is StartupState.STOPPING


def is_shutdown() -> bool:
    """Return True when lifecycle state is STOPPED."""

    return _state is StartupState.STOPPED


def get_startup_state() -> StartupState:
    """Return the current lifecycle state."""

    return _state


# ============================================================================
# Diagnostics
# ============================================================================


def get_startup_info() -> StartupInfo:
    """Return an immutable lifecycle status snapshot."""

    scheduler_running = False

    try:
        from core.scheduler import scheduler

        scheduler_running = _scheduler_is_running(
            scheduler
        )

    except (
        ImportError,
        AttributeError,
        RuntimeError,
        TypeError,
    ):
        scheduler_running = False

    return StartupInfo(
        state=_state,
        bootstrapped=_bootstrapped,
        scheduler_running=scheduler_running,
        shutdown_done=_shutdown_done,
        listeners_wired=_listeners_wired,
        hooks_registered=_hooks_registered,
    )


def startup_diagnostics() -> dict[str, Any]:
    """
    Return lifecycle diagnostics for dashboard/settings/debugging.
    """

    info = get_startup_info()

    return {
        "module": "core.startup",
        "state": info.state.value,
        "bootstrapped": info.bootstrapped,
        "scheduler_running": info.scheduler_running,
        "shutdown_done": info.shutdown_done,
        "listeners_wired": info.listeners_wired,
        "hooks_registered": info.hooks_registered,
    }


# ============================================================================
# Context Manager
# ============================================================================


class ApplicationLifecycle:
    """
    Context manager for controlled AssistantX execution.

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

        # Never suppress application exceptions.
        return False


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Types
    "StartupState",
    "StartupInfo",

    # Lifecycle
    "bootstrap_app",
    "shutdown_app",

    # State
    "is_bootstrapped",
    "is_running",
    "is_shutting_down",
    "is_shutdown",
    "get_startup_state",
    "get_startup_info",

    # Diagnostics
    "startup_diagnostics",

    # Context manager
    "ApplicationLifecycle",
]
