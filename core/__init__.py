"""
AssistantX Core
===============

Central application-core package for AssistantX.

This package provides the public interface for:

- Assistant orchestration
- Command routing
- Event management
- Conversation history
- Long-term memory
- Logging
- Task scheduling
- Application startup/shutdown

Architecture
------------
The core package is intentionally kept below the higher-level packages
such as ``ai``, ``voice``, ``automation``, ``services`` and ``dashboard``.

High-level dependency direction:

    config
       ↓
     core
       ↓
    ┌───────────────┬───────────────┬───────────────┐
    ↓               ↓               ↓               ↓
   ai             voice        automation       services
                                                    ↓
                                               dashboard

The modules exposed here should be considered the stable public API
of the ``core`` package. Internal implementation details should remain
inside their respective modules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

__title__ = "AssistantX Core"
__version__ = "1.0.0"
__author__ = "AssistantX"
__description__ = "Core services and orchestration layer for AssistantX."


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------

from core.assistant import (
    Assistant,
    TurnResult,
    create_default_assistant,
)

# ---------------------------------------------------------------------------
# Command Router
# ---------------------------------------------------------------------------
from core.command_router import (
    CommandResult,
    CommandRouter,
    command_router,
)

# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------
from core.event_bus import (
    EventBus,
    Events,
    event_bus,
)

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
from core.history import (
    HistoryManager,
    Message,
    Role,
    history_manager,
)

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
from core.logger import (
    get_logger,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
from core.memory import (
    MemoryCategory,
    MemoryEntry,
    MemoryManager,
    memory_manager,
)

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
from core.scheduler import (
    Scheduler,
    scheduler,
)

# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------
from core.startup import (
    bootstrap_app,
    is_bootstrapped,
    shutdown_app,
)

# ===========================================================================
# Public API
# ===========================================================================

__all__ = [
    # Assistant
    "Assistant",
    # Command Router
    "CommandResult",
    "CommandRouter",
    # Event Bus
    "EventBus",
    "Events",
    # History
    "HistoryManager",
    # Memory
    "MemoryCategory",
    "MemoryEntry",
    "MemoryManager",
    "Message",
    "Role",
    # Scheduler
    "Scheduler",
    "TurnResult",
    "__author__",
    "__description__",
    # Package metadata
    "__title__",
    "__version__",
    # Application lifecycle
    "bootstrap_app",
    "command_router",
    "create_default_assistant",
    "event_bus",
    # Logger
    "get_logger",
    "history_manager",
    "is_bootstrapped",
    "memory_manager",
    "scheduler",
    "setup_logging",
    "shutdown_app",
]


# ===========================================================================
# Package-level helpers
# ===========================================================================

def get_version() -> str:
    """
    Return the current AssistantX Core version.

    Returns
    -------
    str
        Current package version.
    """
    return __version__


def core_info() -> dict[str, str]:
    """
    Return basic metadata about the core package.

    Returns
    -------
    dict[str, str]
        Package metadata.
    """
    return {
        "title": __title__,
        "version": __version__,
        "author": __author__,
        "description": __description__,
    }


def core_diagnostics() -> dict[str, object]:
    """
    Collect lightweight diagnostics from the core subsystems.

    This function intentionally avoids performing expensive operations.
    It is useful for debugging, support screens and startup checks.

    Returns
    -------
    dict[str, object]
        Diagnostic information for available core components.
    """

    diagnostics: dict[str, object] = {
        "package": __title__,
        "version": __version__,
    }

    # Logger ---------------------------------------------------------------
    try:
        from core.logger import diagnostics as logger_diagnostics

        diagnostics["logger"] = logger_diagnostics()
    except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["logger"] = {
            "available": False,
            "error": str(exc),
        }

    # Memory ---------------------------------------------------------------
    try:
        from core.memory import memory_diagnostics

        diagnostics["memory"] = memory_diagnostics()
    except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["memory"] = {
            "available": False,
            "error": str(exc),
        }

    # History --------------------------------------------------------------
    try:
        from core.history import history_diagnostics

        diagnostics["history"] = history_diagnostics()
    except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["history"] = {
            "available": False,
            "error": str(exc),
        }

    # Scheduler ------------------------------------------------------------
    try:
        scheduler_diagnostics = getattr(
            scheduler,
            "diagnostics",
            None,
        )

        if callable(scheduler_diagnostics):
            diagnostics["scheduler"] = scheduler_diagnostics()
        else:
            diagnostics["scheduler"] = {
                "available": True,
            }

    except (AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["scheduler"] = {
            "available": False,
            "error": str(exc),
        }

    # Command Router -------------------------------------------------------
    try:
        router_diagnostics = getattr(
            command_router,
            "diagnostics",
            None,
        )

        if callable(router_diagnostics):
            diagnostics["command_router"] = router_diagnostics()
        else:
            diagnostics["command_router"] = {
                "available": True,
            }

    except (AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["command_router"] = {
            "available": False,
            "error": str(exc),
        }

    # Event Bus ------------------------------------------------------------
    try:
        event_diagnostics = getattr(
            event_bus,
            "diagnostics",
            None,
        )

        if callable(event_diagnostics):
            diagnostics["event_bus"] = event_diagnostics()
        else:
            diagnostics["event_bus"] = {
                "available": True,
            }

    except (AttributeError, TypeError, RuntimeError) as exc:
        diagnostics["event_bus"] = {
            "available": False,
            "error": str(exc),
        }

    return diagnostics


__all__.extend(
    [
        "core_diagnostics",
        "core_info",
        "get_version",
    ]
)
