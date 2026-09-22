"""
database.sqlite.db_manager
==========================

Professional SQLite access layer for AssistantX.

This module is the application's central relational database API.

Managed data
------------
- Conversations
- Messages
- Memories
- Tasks
- Settings
- Commands
- Profile
- Cache

Design principles
-----------------
- SQLite only; no ORM.
- Parameterized SQL everywhere.
- One short-lived connection per operation.
- Explicit transactions.
- Thread-safe manager operations.
- Strong input validation.
- Safe JSON serialization/deserialization.
- Typed model helpers are available alongside dict-based APIs.
- Database migrations are automatically ensured before use.
- No secrets or user content are exposed through diagnostics.

The database layer is intentionally independent from:
    core/history.py
    core/memory.py
    ai/*
    dashboard/*

Higher-level modules may use this manager as their persistent
relational storage layer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.migrations import (
    check_database_integrity,
    check_foreign_keys,
    create_connection,
    create_database_backup,
    get_current_schema_version,
    get_latest_migration_version,
    is_database_up_to_date,
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
)

# =============================================================================
# Optional project constants
# =============================================================================

try:
    from config.constants import SQLITE_DB_PATH
except ImportError:
    SQLITE_DB_PATH = Path("database/sqlite/assistantx.db")


try:
    from core.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger("assistantx.database")


# =============================================================================
# Exceptions
# =============================================================================


class DatabaseManagerError(Exception):
    """Base exception for DatabaseManager."""


class DatabaseValidationError(DatabaseManagerError):
    """Raised when database input is invalid."""


class DatabaseNotFoundError(DatabaseManagerError):
    """Raised when a requested database record does not exist."""


class DatabaseSerializationError(DatabaseManagerError):
    """Raised when JSON serialization/deserialization fails."""


class DatabaseOperationError(DatabaseManagerError):
    """Raised when a database operation fails."""


# =============================================================================
# Constants
# =============================================================================

DEFAULT_CONVERSATION_TITLE = "New Conversation"

DEFAULT_LANGUAGE = "en"
DEFAULT_THEME = "dark"

DEFAULT_TASK_STATUS = "pending"

VALID_MESSAGE_ROLES = frozenset(
    {
        "system",
        "user",
        "assistant",
        "tool",
    }
)

VALID_TASK_STATUSES = frozenset(
    {
        "pending",
        "in_progress",
        "completed",
        "cancelled",
    }
)

MAX_TITLE_LENGTH = 500
MAX_CONTENT_LENGTH = 1_000_000
MAX_KEY_LENGTH = 500
MAX_COMMAND_LENGTH = 1_000
MAX_DESCRIPTION_LENGTH = 10_000
MAX_EMAIL_LENGTH = 320
MAX_LANGUAGE_LENGTH = 32
MAX_THEME_LENGTH = 64

DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1_000


# =============================================================================
# Database Manager
# =============================================================================


class DatabaseManager:
    """
    Central thread-safe SQLite database manager.

    Example
    -------
        from database.sqlite.db_manager import db_manager

        conversation_id = db_manager.create_conversation(
            "My Chat"
        )

        db_manager.add_message(
            conversation_id,
            "user",
            "Hello AssistantX!",
        )

        messages = db_manager.get_message_models(
            conversation_id
        )
    """

    def __init__(
        self,
        db_path: Path | str = SQLITE_DB_PATH,
        *,
        auto_migrate: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path).expanduser()

        if auto_migrate:
            self.migrate()

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def db_path(self) -> Path:
        """Return the configured SQLite database path."""
        return self._db_path

    @property
    def schema_version(self) -> int:
        """Return the current database schema version."""
        return get_current_schema_version(self._db_path)

    @property
    def latest_schema_version(self) -> int:
        """Return the latest schema version shipped with AssistantX."""
        return get_latest_migration_version()

    # =========================================================================
    # Validation helpers
    # =========================================================================

    @staticmethod
    def _require_positive_id(
        value: int,
        field_name: str,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DatabaseValidationError(
                f"{field_name} must be an integer."
            )

        if value <= 0:
            raise DatabaseValidationError(
                f"{field_name} must be greater than zero."
            )

        return value

    @staticmethod
    def _require_text(
        value: str,
        field_name: str,
        *,
        max_length: int | None = None,
        allow_empty: bool = False,
    ) -> str:
        if not isinstance(value, str):
            raise DatabaseValidationError(
                f"{field_name} must be a string."
            )

        value = value.strip()

        if not allow_empty and not value:
            raise DatabaseValidationError(
                f"{field_name} cannot be empty."
            )

        if max_length is not None and len(value) > max_length:
            raise DatabaseValidationError(
                f"{field_name} exceeds the maximum length "
                f"of {max_length} characters."
            )

        return value

    @staticmethod
    def _validate_limit(
        limit: int | None,
        *,
        default: int = DEFAULT_LIST_LIMIT,
    ) -> int:
        if limit is None:
            return default

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise DatabaseValidationError(
                "limit must be an integer."
            )

        if limit <= 0:
            raise DatabaseValidationError(
                "limit must be greater than zero."
            )

        return min(limit, MAX_LIST_LIMIT)

    @staticmethod
    def _validate_message_role(role: str) -> str:
        role = DatabaseManager._require_text(
            role,
            "role",
            max_length=32,
        ).lower()

        if role not in VALID_MESSAGE_ROLES:
            raise DatabaseValidationError(
                f"Invalid message role: {role!r}. "
                f"Allowed: {sorted(VALID_MESSAGE_ROLES)}"
            )

        return role

    @staticmethod
    def _validate_task_status(status: str) -> str:
        status = DatabaseManager._require_text(
            status,
            "status",
            max_length=32,
        ).lower()

        if status not in VALID_TASK_STATUSES:
            raise DatabaseValidationError(
                f"Invalid task status: {status!r}. "
                f"Allowed: {sorted(VALID_TASK_STATUSES)}"
            )

        return status

    # =========================================================================
    # Utility
    # =========================================================================

    @staticmethod
    def now() -> str:
        """Return a timezone-aware UTC ISO-8601 timestamp."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def serialize(value: Any) -> str:
        """
        Serialize a Python value into JSON.

        Raises
        ------
        DatabaseSerializationError
            If the value cannot be JSON encoded.
        """
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise DatabaseSerializationError(
                f"Unable to serialize value as JSON: {exc}"
            ) from exc

    @staticmethod
    def deserialize(
        value: str,
        default: Any = None,
    ) -> Any:
        """
        Safely deserialize a JSON string.

        Invalid JSON returns ``default``.
        """
        if value is None:
            return default

        if not isinstance(value, str):
            return value

        try:
            return json.loads(value)
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return default

    # =========================================================================
    # Lifecycle / migration
    # =========================================================================

    def migrate(
        self,
        *,
        create_backup: bool = True,
    ):
        """Run all pending database migrations."""
        with self._lock:
            return run_migrations(
                self._db_path,
                create_backup=create_backup,
            )

    def backup(self) -> Path | None:
        """Create a timestamped backup of the database."""
        with self._lock:
            return create_database_backup(
                self._db_path
            )

    def integrity_check(self) -> bool:
        """Run SQLite integrity validation."""
        return check_database_integrity(
            self._db_path
        )

    def foreign_key_check(self) -> bool:
        """Check SQLite foreign-key integrity."""
        return check_foreign_keys(
            self._db_path
        )

    def health(self) -> dict[str, Any]:
        """Return safe database health information."""
        return {
            "database_exists": self._db_path.exists(),
            "database_path": str(self._db_path),
            "schema_version": self.schema_version,
            "latest_schema_version": self.latest_schema_version,
            "up_to_date": is_database_up_to_date(
                self._db_path
            ),
            "integrity_ok": self.integrity_check(),
            "foreign_keys_ok": self.foreign_key_check(),
        }

    # =========================================================================
    # Connection
    # =========================================================================

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """
        Open a short-lived database connection.

        Each operation receives its own connection. This is intentional
        for desktop applications where background threads such as voice,
        scheduler, and UI may access SQLite concurrently.
        """
        connection = create_connection(
            self._db_path
        )

        try:
            yield connection

        except Exception:
            try:
                connection.rollback()
            except sqlite3.Error:
                logger.exception(
                    "SQLite rollback failed."
                )
            raise

        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Execute multiple statements as one explicit transaction.
        """
        connection = create_connection(
            self._db_path
        )

        try:
            connection.execute("BEGIN;")

            yield connection

            connection.execute("COMMIT;")

        except Exception:
            try:
                connection.execute("ROLLBACK;")
            except sqlite3.Error:
                logger.exception(
                    "SQLite transaction rollback failed."
                )
            raise

        finally:
            connection.close()

    # =========================================================================
    # Conversations
    # =========================================================================

    def create_conversation(
        self,
        title: str = DEFAULT_CONVERSATION_TITLE,
    ) -> int:
        title = self._require_text(
            title,
            "title",
            max_length=MAX_TITLE_LENGTH,
        )

        timestamp = self.now()

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversations
                    (title, created_at, updated_at)
                VALUES
                    (?, ?, ?);
                """,
                (
                    title,
                    timestamp,
                    timestamp,
                ),
            )

            return int(cursor.lastrowid)

    def get_conversation(
        self,
        conversation_id: int,
    ) -> dict[str, Any] | None:
        conversation_id = self._require_positive_id(
            conversation_id,
            "conversation_id",
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM conversations
                WHERE id = ?;
                """,
                (conversation_id,),
            ).fetchone()

            return dict(row) if row else None

    def get_conversation_model(
        self,
        conversation_id: int,
    ) -> Conversation | None:
        row = self.get_conversation(
            conversation_id
        )

        return (
            Conversation.from_row(row)
            if row
            else None
        )

    def get_conversations(
        self,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)

        with self._lock, self.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM conversations
                ORDER BY updated_at DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()

            return [dict(row) for row in rows]

    def get_conversation_models(
        self,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[Conversation]:
        return [
            Conversation.from_row(row)
            for row in self.get_conversations(limit)
        ]

    def update_conversation_title(
        self,
        conversation_id: int,
        title: str,
    ) -> bool:
        conversation_id = self._require_positive_id(
            conversation_id,
            "conversation_id",
        )

        title = self._require_text(
            title,
            "title",
            max_length=MAX_TITLE_LENGTH,
        )

        timestamp = self.now()

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET
                    title = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    title,
                    timestamp,
                    conversation_id,
                ),
            )

            return cursor.rowcount > 0

    def delete_conversation(
        self,
        conversation_id: int,
    ) -> bool:
        conversation_id = self._require_positive_id(
            conversation_id,
            "conversation_id",
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM conversations
                WHERE id = ?;
                """,
                (conversation_id,),
            )

            return cursor.rowcount > 0

    def conversation_exists(
        self,
        conversation_id: int,
    ) -> bool:
        return (
            self.get_conversation(
                conversation_id
            )
            is not None
        )

    # =========================================================================
    # Messages
    # =========================================================================

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
    ) -> int:
        conversation_id = self._require_positive_id(
            conversation_id,
            "conversation_id",
        )

        role = self._validate_message_role(role)

        content = self._require_text(
            content,
            "content",
            max_length=MAX_CONTENT_LENGTH,
        )

        timestamp = self.now()

        with self._lock, self.transaction() as connection:
            conversation = connection.execute(
                """
                SELECT id
                FROM conversations
                WHERE id = ?;
                """,
                (conversation_id,),
            ).fetchone()

            if conversation is None:
                raise DatabaseNotFoundError(
                    f"Conversation not found: {conversation_id}"
                )

            cursor = connection.execute(
                """
                INSERT INTO messages
                    (
                        conversation_id,
                        role,
                        content,
                        created_at
                    )
                VALUES
                    (?, ?, ?, ?);
                """,
                (
                    conversation_id,
                    role,
                    content,
                    timestamp,
                ),
            )

            connection.execute(
                """
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?;
                """,
                (
                    timestamp,
                    conversation_id,
                ),
            )

            return int(cursor.lastrowid)

    def get_messages(
        self,
        conversation_id: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        conversation_id = self._require_positive_id(
            conversation_id,
            "conversation_id",
        )

        if limit is not None:
            limit = self._validate_limit(limit)

        with self._lock, self.connection() as connection:
            if limit is None:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id ASC;
                    """,
                    (conversation_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM (
                        SELECT *
                        FROM messages
                        WHERE conversation_id = ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    ORDER BY id ASC;
                    """,
                    (
                        conversation_id,
                        limit,
                    ),
                ).fetchall()

            return [dict(row) for row in rows]

    def get_message_models(
        self,
        conversation_id: int,
        limit: int | None = None,
    ) -> list[Message]:
        return [
            Message.from_row(row)
            for row in self.get_messages(
                conversation_id,
                limit,
            )
        ]

    def delete_message(
        self,
        message_id: int,
    ) -> bool:
        message_id = self._require_positive_id(
            message_id,
            "message_id",
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM messages
                WHERE id = ?;
                """,
                (message_id,),
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Memory
    # =========================================================================

    def save_memory(
        self,
        key: str,
        value: Any,
    ) -> None:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        serialized = self.serialize(value)
        timestamp = self.now()

        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO memories
                    (
                        memory_key,
                        memory_value,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?)

                ON CONFLICT(memory_key)
                DO UPDATE SET
                    memory_value = excluded.memory_value,
                    updated_at = excluded.updated_at;
                """,
                (
                    key,
                    serialized,
                    timestamp,
                    timestamp,
                ),
            )

    def get_memory(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT memory_value
                FROM memories
                WHERE memory_key = ?;
                """,
                (key,),
            ).fetchone()

            if row is None:
                return default

            return self.deserialize(
                row["memory_value"],
                default,
            )

    def get_memories(self) -> list[dict[str, Any]]:
        with self._lock, self.connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM memories
                ORDER BY updated_at DESC;
                """
            ).fetchall()

            result: list[dict[str, Any]] = []

            for row in rows:
                item = dict(row)
                item["memory_value"] = self.deserialize(
                    item["memory_value"]
                )
                result.append(item)

            return result

    def get_memory_models(self) -> list[MemoryRecord]:
        return [
            MemoryRecord.from_row(row)
            for row in self.get_memories()
        ]

    def delete_memory(
        self,
        key: str,
    ) -> bool:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memories
                WHERE memory_key = ?;
                """,
                (key,),
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Tasks
    # =========================================================================

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = 0,
        due_at: str | None = None,
    ) -> int:
        title = self._require_text(
            title,
            "title",
            max_length=MAX_TITLE_LENGTH,
        )

        description = self._require_text(
            description,
            "description",
            max_length=MAX_DESCRIPTION_LENGTH,
            allow_empty=True,
        )

        if isinstance(priority, bool) or not isinstance(
            priority,
            int,
        ):
            raise DatabaseValidationError(
                "priority must be an integer."
            )

        if due_at is not None:
            due_at = self._require_text(
                due_at,
                "due_at",
                max_length=128,
            )

        timestamp = self.now()

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks
                    (
                        title,
                        description,
                        status,
                        priority,
                        due_at,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    title,
                    description,
                    DEFAULT_TASK_STATUS,
                    priority,
                    due_at,
                    timestamp,
                    timestamp,
                ),
            )

            return int(cursor.lastrowid)

    def get_task(
        self,
        task_id: int,
    ) -> dict[str, Any] | None:
        task_id = self._require_positive_id(
            task_id,
            "task_id",
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tasks
                WHERE id = ?;
                """,
                (task_id,),
            ).fetchone()

            return dict(row) if row else None

    def get_task_model(
        self,
        task_id: int,
    ) -> Task | None:
        row = self.get_task(task_id)

        return (
            Task.from_row(row)
            if row
            else None
        )

    def get_tasks(
        self,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        limit = self._validate_limit(limit)

        if status is not None:
            status = self._validate_task_status(status)

        with self._lock, self.connection() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM tasks
                    WHERE status = ?
                    ORDER BY priority DESC, created_at DESC
                    LIMIT ?;
                    """,
                    (
                        status,
                        limit,
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM tasks
                    ORDER BY priority DESC, created_at DESC
                    LIMIT ?;
                    """,
                    (limit,),
                ).fetchall()

            return [dict(row) for row in rows]

    def get_task_models(
        self,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[Task]:
        return [
            Task.from_row(row)
            for row in self.get_tasks(
                status,
                limit,
            )
        ]

    def update_task_status(
        self,
        task_id: int,
        status: str,
    ) -> bool:
        task_id = self._require_positive_id(
            task_id,
            "task_id",
        )

        status = self._validate_task_status(status)

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET
                    status = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    status,
                    self.now(),
                    task_id,
                ),
            )

            return cursor.rowcount > 0

    def delete_task(
        self,
        task_id: int,
    ) -> bool:
        task_id = self._require_positive_id(
            task_id,
            "task_id",
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM tasks
                WHERE id = ?;
                """,
                (task_id,),
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Settings
    # =========================================================================

    def set_setting(
        self,
        key: str,
        value: Any,
    ) -> None:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        serialized = self.serialize(value)
        timestamp = self.now()

        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO settings
                    (
                        setting_key,
                        setting_value,
                        updated_at
                    )
                VALUES
                    (?, ?, ?)

                ON CONFLICT(setting_key)
                DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at;
                """,
                (
                    key,
                    serialized,
                    timestamp,
                ),
            )

    def get_setting(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT setting_value
                FROM settings
                WHERE setting_key = ?;
                """,
                (key,),
            ).fetchone()

            if row is None:
                return default

            return self.deserialize(
                row["setting_value"],
                default,
            )

    def get_settings(self) -> dict[str, Any]:
        with self._lock, self.connection() as connection:
            rows = connection.execute(
                """
                SELECT setting_key, setting_value
                FROM settings
                ORDER BY setting_key ASC;
                """
            ).fetchall()

            result: dict[str, Any] = {}

            for row in rows:
                result[row["setting_key"]] = self.deserialize(
                    row["setting_value"]
                )

            return result

    def delete_setting(
        self,
        key: str,
    ) -> bool:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM settings
                WHERE setting_key = ?;
                """,
                (key,),
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Commands
    # =========================================================================

    def save_command(
        self,
        name: str,
        command: str,
        description: str = "",
        enabled: bool = True,
    ) -> None:
        name = self._require_text(
            name,
            "name",
            max_length=MAX_KEY_LENGTH,
        )

        command = self._require_text(
            command,
            "command",
            max_length=MAX_COMMAND_LENGTH,
        )

        description = self._require_text(
            description,
            "description",
            max_length=MAX_DESCRIPTION_LENGTH,
            allow_empty=True,
        )

        if not isinstance(enabled, bool):
            raise DatabaseValidationError(
                "enabled must be a boolean."
            )

        timestamp = self.now()

        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO commands
                    (
                        name,
                        command,
                        description,
                        enabled,
                        created_at,
                        updated_at
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?)

                ON CONFLICT(name)
                DO UPDATE SET
                    command = excluded.command,
                    description = excluded.description,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at;
                """,
                (
                    name,
                    command,
                    description,
                    int(enabled),
                    timestamp,
                    timestamp,
                ),
            )

    def get_command(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        name = self._require_text(
            name,
            "name",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM commands
                WHERE name = ?;
                """,
                (name,),
            ).fetchone()

            return dict(row) if row else None

    def get_command_model(
        self,
        name: str,
    ) -> CommandRecord | None:
        row = self.get_command(name)

        return (
            CommandRecord.from_row(row)
            if row
            else None
        )

    def get_commands(
        self,
        enabled_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[dict[str, Any]]:
        if not isinstance(enabled_only, bool):
            raise DatabaseValidationError(
                "enabled_only must be a boolean."
            )

        limit = self._validate_limit(limit)

        with self._lock, self.connection() as connection:
            if enabled_only:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM commands
                    WHERE enabled = 1
                    ORDER BY name ASC
                    LIMIT ?;
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT *
                    FROM commands
                    ORDER BY name ASC
                    LIMIT ?;
                    """,
                    (limit,),
                ).fetchall()

            return [dict(row) for row in rows]

    def get_command_models(
        self,
        enabled_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[CommandRecord]:
        return [
            CommandRecord.from_row(row)
            for row in self.get_commands(
                enabled_only,
                limit,
            )
        ]

    def delete_command(
        self,
        name: str,
    ) -> bool:
        name = self._require_text(
            name,
            "name",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM commands
                WHERE name = ?;
                """,
                (name,),
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Profile
    # =========================================================================

    def save_profile(
        self,
        name: str = "",
        email: str = "",
        language: str = DEFAULT_LANGUAGE,
        theme: str = DEFAULT_THEME,
    ) -> None:
        name = self._require_text(
            name,
            "name",
            max_length=MAX_TITLE_LENGTH,
            allow_empty=True,
        )

        email = self._require_text(
            email,
            "email",
            max_length=MAX_EMAIL_LENGTH,
            allow_empty=True,
        )

        language = self._require_text(
            language,
            "language",
            max_length=MAX_LANGUAGE_LENGTH,
        )

        theme = self._require_text(
            theme,
            "theme",
            max_length=MAX_THEME_LENGTH,
        )

        timestamp = self.now()

        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO profile
                    (
                        id,
                        name,
                        email,
                        language,
                        theme,
                        created_at,
                        updated_at
                    )
                VALUES
                    (1, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(id)
                DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    language = excluded.language,
                    theme = excluded.theme,
                    updated_at = excluded.updated_at;
                """,
                (
                    name,
                    email,
                    language,
                    theme,
                    timestamp,
                    timestamp,
                ),
            )

    def get_profile(self) -> dict[str, Any] | None:
        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM profile
                WHERE id = 1;
                """
            ).fetchone()

            return dict(row) if row else None

    def get_profile_model(self) -> Profile | None:
        row = self.get_profile()

        return (
            Profile.from_row(row)
            if row
            else None
        )

    def delete_profile(self) -> bool:
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM profile
                WHERE id = 1;
                """
            )

            return cursor.rowcount > 0

    # =========================================================================
    # Cache
    # =========================================================================

    def set_cache(
        self,
        key: str,
        value: Any,
        expires_at: str | None = None,
    ) -> None:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        if expires_at is not None:
            expires_at = self._require_text(
                expires_at,
                "expires_at",
                max_length=128,
            )

        serialized = self.serialize(value)
        timestamp = self.now()

        with self._lock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO cache
                    (
                        cache_key,
                        cache_value,
                        expires_at,
                        created_at
                    )
                VALUES
                    (?, ?, ?, ?)

                ON CONFLICT(cache_key)
                DO UPDATE SET
                    cache_value = excluded.cache_value,
                    expires_at = excluded.expires_at;
                """,
                (
                    key,
                    serialized,
                    expires_at,
                    timestamp,
                ),
            )

    def get_cache(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    cache_value,
                    expires_at
                FROM cache
                WHERE cache_key = ?;
                """,
                (key,),
            ).fetchone()

            if row is None:
                return default

            expires_at = row["expires_at"]

            if expires_at:
                try:
                    expiry_text = str(expires_at)

                    if expiry_text.endswith("Z"):
                        expiry_text = (
                            expiry_text[:-1] + "+00:00"
                        )

                    expiry = datetime.fromisoformat(
                        expiry_text
                    )

                    now = (
                        datetime.now(expiry.tzinfo)
                        if expiry.tzinfo
                        else datetime.now(timezone.utc)
                    )

                    if now >= expiry:
                        connection.execute(
                            """
                            DELETE FROM cache
                            WHERE cache_key = ?;
                            """,
                            (key,),
                        )
                        return default

                except ValueError:
                    # Invalid expiry metadata should not crash
                    # the application. Treat the cache entry as
                    # non-expiring rather than deleting valid data.
                    logger.warning(
                        "Invalid cache expiry for key: %s",
                        key,
                    )

            return self.deserialize(
                row["cache_value"],
                default,
            )

    def get_cache_record(
        self,
        key: str,
    ) -> CacheRecord | None:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM cache
                WHERE cache_key = ?;
                """,
                (key,),
            ).fetchone()

            if row is None:
                return None

            return CacheRecord.from_row(row)

    def delete_cache(
        self,
        key: str,
    ) -> bool:
        key = self._require_text(
            key,
            "key",
            max_length=MAX_KEY_LENGTH,
        )

        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM cache
                WHERE cache_key = ?;
                """,
                (key,),
            )

            return cursor.rowcount > 0

    def clear_expired_cache(self) -> int:
        """
        Delete expired cache records.

        Returns the number of removed records.
        """
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM cache
                WHERE expires_at IS NOT NULL
                AND (
                    expires_at <= datetime('now')
                    OR expires_at <= ?
                );
                """,
                (self.now(),),
            )

            return max(cursor.rowcount, 0)

    def clear_cache(self) -> int:
        """Delete all cache records."""
        with self._lock, self.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM cache;"
            )

            return max(cursor.rowcount, 0)

    # =========================================================================
    # Counts / diagnostics
    # =========================================================================

    def counts(self) -> dict[str, int]:
        """Return row counts for all AssistantX database tables."""
        tables = (
            "conversations",
            "messages",
            "memories",
            "tasks",
            "settings",
            "commands",
            "profile",
            "cache",
        )

        result: dict[str, int] = {}

        with self._lock, self.connection() as connection:
            for table in tables:
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table};"
                ).fetchone()

                result[table] = int(
                    row["count"]
                )

        return result

    def diagnostics(self) -> dict[str, Any]:
        """
        Return safe operational diagnostics.

        User message contents, memory values, commands, and secrets are
        intentionally excluded.
        """
        try:
            counts = self.counts()
        except Exception:
            logger.exception(
                "Failed to collect database counts."
            )
            counts = {}

        try:
            integrity_ok = self.integrity_check()
        except Exception:
            logger.exception(
                "Failed to run database integrity check."
            )
            integrity_ok = False

        try:
            foreign_keys_ok = self.foreign_key_check()
        except Exception:
            logger.exception(
                "Failed to run foreign-key check."
            )
            foreign_keys_ok = False

        return {
            "database_path": str(self._db_path),
            "database_exists": self._db_path.exists(),
            "database_size_bytes": (
                self._db_path.stat().st_size
                if self._db_path.exists()
                else 0
            ),
            "schema_version": self.schema_version,
            "latest_schema_version": (
                self.latest_schema_version
            ),
            "up_to_date": is_database_up_to_date(
                self._db_path
            ),
            "integrity_ok": integrity_ok,
            "foreign_keys_ok": foreign_keys_ok,
            "counts": counts,
        }

    # =========================================================================
    # Shutdown
    # =========================================================================

    def close(self) -> None:
        """
        Compatibility method.

        DatabaseManager intentionally uses short-lived connections,
        so there is no persistent connection to close.
        """
        return

    # UPDATED                                                                    ====================================================================


    # =============================================================================
# Backward compatibility aliases
# =============================================================================

# Message API aliases
def create_message(
    conversation_id: int,
    role: str,
    content: str,
) -> int:
    """Alias for add_message() for compatibility."""
    return db_manager.add_message(
        conversation_id,
        role,
        content,
    )


# Memory API aliases
def upsert_memory(
    key: str,
    value: Any,
) -> None:
    """Alias for save_memory() for compatibility."""
    return db_manager.save_memory(key, value)

# UPDATED                                                                   ====================================================================


# =============================================================================
# Module-level convenience aliases
# =============================================================================

# Direct access to singleton methods
def create_conversation(title: str = DEFAULT_CONVERSATION_TITLE) -> int:
    """Create a conversation."""
    return db_manager.create_conversation(title)

def create_task(
    title: str,
    description: str = "",
    priority: int = 0,
    due_at: str | None = None,
) -> int:
    """Create a task."""
    return db_manager.create_task(title, description, priority, due_at)



def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting."""
    return db_manager.get_setting(key, default)

def set_setting(key: str, value: Any) -> None:
    """Set a setting."""
    return db_manager.set_setting(key, value)

def get_profile() -> dict | None:
    """Get user profile."""
    return db_manager.get_profile()

def save_profile(name: str = "", email: str = "", language: str = DEFAULT_LANGUAGE, theme: str = DEFAULT_THEME) -> None:
    """Save user profile."""
    return db_manager.save_profile(name, email, language, theme)

def get_cache(key: str, default: Any = None) -> Any:
    """Get cache value."""
    return db_manager.get_cache(key, default)

def set_cache(key: str, value: Any, expires_at: str | None = None) -> None:
    """Set cache value."""
    return db_manager.set_cache(key, value, expires_at)

def get_command(name: str) -> dict | None:
    """Get a command."""
    return db_manager.get_command(name)

def save_command(name: str, command: str, description: str = "", enabled: bool = True) -> None:
    """Save a command."""
    return db_manager.save_command(name, command, description, enabled)



# =============================================================================
# Global singleton
# =============================================================================

db_manager = DatabaseManager()


# =============================================================================
# Public exports
# =============================================================================

__all__ = [
    # Manager
    "DatabaseManager",
    # Exceptions
    "DatabaseManagerError",
    "DatabaseNotFoundError",
    "DatabaseOperationError",
    "DatabaseSerializationError",
    "DatabaseValidationError",
    # Module-level convenience functions
    "create_conversation",
    "create_message",
    "create_task",
    "db_manager",
    "get_cache",
    "get_command",
    "get_profile",
    "get_setting",
    "save_command",
    "save_profile",
    "set_cache",
    "set_setting",
    "upsert_memory",
]
