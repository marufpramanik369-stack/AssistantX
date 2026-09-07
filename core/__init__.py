"""
core
====
The application core: logging, configuration glue, event bus, history,
memory, scheduling, command routing, startup/shutdown orchestration, and
the top-level Assistant façade.

Every other package (ai/, voice/, brain/, automation/, services/,
dashboard/) depends on core/, and core/ depends on nothing above it
(only on config/), keeping the dependency graph acyclic.
"""

from __future__ import annotations

from core.assistant import Assistant, TurnResult, create_default_assistant
from core.command_router import CommandResult, CommandRouter, command_router
from core.event_bus import EventBus, Events, event_bus
from core.history import HistoryManager, Message, Role, history_manager
from core.logger import get_logger, setup_logging
from core.memory import MemoryCategory, MemoryEntry, MemoryManager, memory_manager
from core.scheduler import Scheduler, scheduler
from core.startup import bootstrap_app, is_bootstrapped, shutdown_app

__all__ = [
    "Assistant",
    "TurnResult",
    "create_default_assistant",
    "CommandResult",
    "CommandRouter",
    "command_router",
    "EventBus",
    "Events",
    "event_bus",
    "HistoryManager",
    "Message",
    "Role",
    "history_manager",
    "get_logger",
    "setup_logging",
    "MemoryCategory",
    "MemoryEntry",
    "MemoryManager",
    "memory_manager",
    "Scheduler",
    "scheduler",
    "bootstrap_app",
    "is_bootstrapped",
    "shutdown_app",
]
