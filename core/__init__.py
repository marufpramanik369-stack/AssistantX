"""
core/__init__.py — AssistantX Core Public API
==============================================

Stable public API for the AssistantX core layer.

The core package provides the central infrastructure used by higher-level
AssistantX modules such as AI, voice, automation, services, and dashboard.

ARCHITECTURE
============

    config/
        ↓
    core/
        ├── logger
        ├── event_bus
        ├── command_router
        ├── history
        ├── memory
        ├── scheduler
        ├── assistant
        ├── startup
        └── utils
        ↓
    ai/
    voice/
    automation/
    services/
    dashboard/

DESIGN GOALS
============

1. Stable public API
   Public classes, singletons, factories, and lifecycle helpers are exposed
   here while implementation details remain inside their modules.

2. Compatibility
   Existing imports such as:

       from core import event_bus
       from core import memory_manager
       from core import CommandResult
       from core import bootstrap_app

   remain supported.

3. Safe initialization
   Expensive lifecycle initialization is not performed merely by importing
   this package. Application startup is explicitly controlled through
   bootstrap_app().

4. Diagnostics
   core_diagnostics() provides a lightweight health snapshot of core
   subsystems without starting or stopping anything.

5. Thread safety
   Thread safety is delegated to the individual core managers. This module
   does not maintain mutable application state.

6. No domain ownership
   AI, voice, dashboard, automation, and external services must not be
   implemented here. Core only provides shared infrastructure.

IMPORTANT
=========

Do not add heavy third-party dependencies to this module.

Do not perform network access, application startup, scheduler startup,
voice initialization, or UI initialization during package import.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

# ============================================================================
# Package Logger
# ============================================================================

_logger = logging.getLogger(__name__)


# ============================================================================
# Package Metadata
# ============================================================================

__title__ = "AssistantX Core"
__version__ = "1.0.0"
__author__ = "AssistantX"
__description__ = "Core services and orchestration layer for AssistantX."
__package_name__ = "AssistantX Core"


# ============================================================================
# Core Public Imports
# ============================================================================
#
# These modules are lightweight core infrastructure modules and are already
# part of the established AssistantX core API.
#
# Startup remains lazy because it controls application lifecycle.
# ============================================================================


# ----------------------------------------------------------------------------
# Assistant Orchestration
# ----------------------------------------------------------------------------

from .assistant import (
    Assistant,
    TurnResult,
    create_default_assistant,
)


# ----------------------------------------------------------------------------
# Command Router
# ----------------------------------------------------------------------------

from .command_router import (
    CommandResult,
    CommandRouter,
    command_router,
)


# ----------------------------------------------------------------------------
# Event Bus
# ----------------------------------------------------------------------------

from .event_bus import (
    EventBus,
    Events,
    event_bus,
)


# ----------------------------------------------------------------------------
# History
# ----------------------------------------------------------------------------

from .history import (
    HistoryManager,
    Message,
    Role,
    history_manager,
)


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

from .logger import (
    get_logger,
    setup_logging,
)


# ----------------------------------------------------------------------------
# Memory
# ----------------------------------------------------------------------------

from .memory import (
    MemoryCategory,
    MemoryEntry,
    MemoryManager,
    memory_manager,
)


# ----------------------------------------------------------------------------
# Scheduler
# ----------------------------------------------------------------------------

from .scheduler import (
    Scheduler,
    scheduler,
)


# ============================================================================
# Internal Helpers
# ============================================================================


def _load_startup_module():
    """
    Lazily import the application lifecycle module.

    Returns:
        module:
            The ``core.startup`` module.

    This helper intentionally avoids importing startup during the initial
    core package import, reducing lifecycle-related circular dependencies.
    """
    return importlib.import_module(".startup", __name__)


def _diagnostic_error(exc: BaseException) -> dict[str, Any]:
    """
    Convert a subsystem diagnostic exception into a stable result.

    Parameters:
        exc:
            Exception raised while collecting diagnostics.

    Returns:
        dict[str, Any]:
            Standard unavailable diagnostic structure.
    """
    return {
        "available": False,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _safe_diagnostics(
    function: Any,
    *,
    subsystem: str,
) -> dict[str, Any]:
    """
    Execute a diagnostic function without allowing it to break core health
    reporting.

    Parameters:
        function:
            Callable diagnostic function.

        subsystem:
            Human-readable subsystem name.

    Returns:
        dict[str, Any]:
            Diagnostic result or an unavailable/error result.
    """
    if not callable(function):
        return {
            "available": False,
            "error": f"{subsystem} diagnostics are unavailable",
        }

    try:
        result = function()

        if isinstance(result, dict):
            return result

        return {
            "available": True,
            "result": result,
        }

    except Exception as exc:
        _logger.warning(
            "%s diagnostics failed: %s: %s",
            subsystem,
            type(exc).__name__,
            exc,
        )
        return _diagnostic_error(exc)


# ============================================================================
# Package Information
# ============================================================================


def get_version() -> str:
    """
    Return the current AssistantX Core package version.

    Returns:
        str:
            Semantic version string.

    Example:
        from core import get_version

        print(get_version())
    """
    return __version__


def core_info() -> dict[str, str]:
    """
    Return basic metadata about the AssistantX Core package.

    Returns:
        dict[str, str]:
            Package metadata.

    Example:
        from core import core_info

        info = core_info()
        print(info["version"])
    """
    return {
        "title": __title__,
        "version": __version__,
        "author": __author__,
        "description": __description__,
        "package_name": __package_name__,
    }


# ============================================================================
# Diagnostics
# ============================================================================


def core_diagnostics() -> dict[str, Any]:
    """
    Collect a lightweight diagnostic snapshot of the core layer.

    The function does not:

        - start the application
        - stop the application
        - start the scheduler
        - access the network
        - initialize voice
        - initialize the dashboard

    Returns:
        dict[str, Any]:
            Diagnostic information for core subsystems.

    Example:
        from core import core_diagnostics

        diagnostics = core_diagnostics()

        print(diagnostics["version"])
        print(diagnostics["event_bus"])
    """
    diagnostics: dict[str, Any] = {
        "module": __name__,
        "package": __title__,
        "version": __version__,
        "status": "ok",
    }

    # ------------------------------------------------------------------------
    # Logger
    # ------------------------------------------------------------------------

    try:
        from .logger import diagnostics as logger_diagnostics

        diagnostics["logger"] = _safe_diagnostics(
            logger_diagnostics,
            subsystem="logger",
        )
    except (ImportError, AttributeError) as exc:
        diagnostics["logger"] = _diagnostic_error(exc)

    # ------------------------------------------------------------------------
    # Event Bus
    # ------------------------------------------------------------------------

    diagnostics["event_bus"] = _safe_diagnostics(
        getattr(event_bus, "diagnostics", None),
        subsystem="event_bus",
    )

    # ------------------------------------------------------------------------
    # Command Router
    # ------------------------------------------------------------------------

    diagnostics["command_router"] = _safe_diagnostics(
        getattr(command_router, "diagnostics", None),
        subsystem="command_router",
    )

    # ------------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------------

    try:
        from .history import history_diagnostics

        diagnostics["history"] = _safe_diagnostics(
            history_diagnostics,
            subsystem="history",
        )
    except (ImportError, AttributeError) as exc:
        diagnostics["history"] = _diagnostic_error(exc)

    # ------------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------------

    try:
        from .memory import memory_diagnostics

        diagnostics["memory"] = _safe_diagnostics(
            memory_diagnostics,
            subsystem="memory",
        )
    except (ImportError, AttributeError) as exc:
        diagnostics["memory"] = _diagnostic_error(exc)

    # ------------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------------

    diagnostics["scheduler"] = _safe_diagnostics(
        getattr(scheduler, "diagnostics", None),
        subsystem="scheduler",
    )

    # ------------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------------

    try:
        from .utils import utils_diagnostics

        diagnostics["utils"] = _safe_diagnostics(
            utils_diagnostics,
            subsystem="utils",
        )
    except (ImportError, AttributeError) as exc:
        diagnostics["utils"] = _diagnostic_error(exc)

    # ------------------------------------------------------------------------
    # Startup / Lifecycle
    # ------------------------------------------------------------------------

    try:
        startup = _load_startup_module()

        startup_diag = getattr(
            startup,
            "startup_diagnostics",
            None,
        )

        if callable(startup_diag):
            diagnostics["startup"] = _safe_diagnostics(
                startup_diag,
                subsystem="startup",
            )
        else:
            diagnostics["startup"] = {
                "available": True,
                "bootstrapped": bool(
                    getattr(startup, "is_bootstrapped", lambda: False)()
                ),
            }

    except Exception as exc:
        diagnostics["startup"] = _diagnostic_error(exc)

    # ------------------------------------------------------------------------
    # Overall Status
    # ------------------------------------------------------------------------

    subsystem_keys = (
        "logger",
        "event_bus",
        "command_router",
        "history",
        "memory",
        "scheduler",
        "utils",
        "startup",
    )

    unavailable = [
        key
        for key in subsystem_keys
        if diagnostics.get(key, {}).get("available") is False
    ]

    diagnostics["healthy"] = not unavailable
    diagnostics["unavailable_subsystems"] = unavailable

    if unavailable:
        diagnostics["status"] = "degraded"

    return diagnostics


# ============================================================================
# Application Lifecycle
# ============================================================================


def bootstrap_app(
    *,
    log_level: Optional[str] = None,
    start_scheduler: bool = True,
) -> None:
    """
    Initialize the AssistantX core application lifecycle.

    Parameters:
        log_level:
            Optional logging level such as ``DEBUG`` or ``INFO``.

        start_scheduler:
            Whether the core scheduler should be started.

    Raises:
        RuntimeError:
            If startup has already been completed or another lifecycle
            error occurs.

    Example:
        from core import bootstrap_app, shutdown_app

        bootstrap_app(log_level="INFO")

        try:
            ...
        finally:
            shutdown_app()
    """
    _logger.info(
        "Bootstrapping AssistantX Core "
        "(log_level=%s, start_scheduler=%s)",
        log_level,
        start_scheduler,
    )

    startup = _load_startup_module()

    startup.bootstrap_app(
        log_level=log_level,
        start_scheduler=start_scheduler,
    )

    _logger.info("AssistantX Core bootstrap complete")


def shutdown_app() -> None:
    """
    Gracefully shut down AssistantX core services.

    Shutdown is delegated to ``core.startup`` so that lifecycle ordering
    remains centralized.

    Example:
        from core import shutdown_app

        shutdown_app()
    """
    _logger.info("Shutting down AssistantX Core")

    startup = _load_startup_module()
    startup.shutdown_app()

    _logger.info("AssistantX Core shutdown complete")


def is_bootstrapped() -> bool:
    """
    Return whether the core application has been bootstrapped.

    Returns:
        bool:
            True when the application lifecycle is running.

    This function is intentionally failure-safe and returns False if the
    startup subsystem cannot be inspected.
    """
    try:
        startup = _load_startup_module()

        checker = getattr(
            startup,
            "is_bootstrapped",
            None,
        )

        if not callable(checker):
            return False

        return bool(checker())

    except Exception as exc:
        _logger.warning(
            "Unable to determine bootstrap state: %s: %s",
            type(exc).__name__,
            exc,
        )
        return False


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Package metadata
    "__author__",
    "__description__",
    "__package_name__",
    "__title__",
    "__version__",

    # Assistant orchestration
    "Assistant",
    "TurnResult",
    "create_default_assistant",

    # Command routing
    "CommandResult",
    "CommandRouter",
    "command_router",

    # Event management
    "EventBus",
    "Events",
    "event_bus",

    # History
    "HistoryManager",
    "Message",
    "Role",
    "history_manager",

    # Logging
    "get_logger",
    "setup_logging",

    # Memory
    "MemoryCategory",
    "MemoryEntry",
    "MemoryManager",
    "memory_manager",

    # Scheduler
    "Scheduler",
    "scheduler",

    # Lifecycle
    "bootstrap_app",
    "shutdown_app",
    "is_bootstrapped",

    # Package information
    "get_version",
    "core_info",

    # Diagnostics
    "core_diagnostics",
]


# ============================================================================
# Import Completion
# ============================================================================

_logger.info(
    "Core module fully initialized: %d public export(s)",
    len(__all__),
)
