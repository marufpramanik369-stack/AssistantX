"""
database
========
Relational (SQLite) storage package for AssistantX.

Exposes the DatabaseManager singleton, migration utilities, and typed
model classes at the package level:

    from database import db_manager, Conversation, Message

    conv_id = db_manager.create_conversation("Trip Planning")
    db_manager.add_message(conv_id, "user", "Plan a weekend in Kyoto")
"""

from __future__ import annotations

from database.db_manager import DatabaseManager, db_manager
from database.migrations import (
    create_connection,
    get_current_schema_version,
    run_migrations,
)
from database.sqlite.models import (
    CacheRecord,
    CommandRecord,
    Conversation,
    MemoryRecord,
    Message,
    Profile,
    Task,
    TaskStatus,
)

__all__ = [
    # models
    "CacheRecord",
    "CommandRecord",
    "Conversation",
    # manager
    "DatabaseManager",
    "MemoryRecord",
    "Message",
    "Profile",
    "Task",
    "TaskStatus",
    # migrations
    "create_connection",
    "db_manager",
    "get_current_schema_version",
    "run_migrations",
]
