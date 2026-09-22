"""
database.sqlite.migrations
==========================

SQLite schema management and migration system for AssistantX.

Design goals
------------
- Lightweight hand-rolled migrations.
- No ORM or external migration framework.
- Every migration is immutable once released.
- Migrations are applied in ascending version order.
- Each migration runs inside a transaction.
- Failed migrations are rolled back safely.
- SQLite connections use consistent production-friendly settings.
- Optional database backup before migration.
- Thread-safe migration execution within the application process.
- Compatible with sqlite3.Row and the database models layer.

Important
---------
Never edit an already-released migration.

Instead, append a new migration:

    1 -> Initial schema
    2 -> Add something
    3 -> Add another thing

Existing installations will then migrate automatically.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

# =============================================================================
# Optional project imports
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

    logger = logging.getLogger("assistantx.database.migrations")


# =============================================================================
# Constants
# =============================================================================

DEFAULT_SQLITE_TIMEOUT: Final[float] = 15.0
DEFAULT_BUSY_TIMEOUT_MS: Final[int] = 15_000

BACKUP_DIRECTORY_NAME: Final[str] = "backups"

MIGRATION_TABLE: Final[str] = "schema_version"

CURRENT_MIGRATION_VERSION: Final[int] = 2


# =============================================================================
# Exceptions
# =============================================================================


class MigrationError(Exception):
    """Base exception for AssistantX database migration errors."""


class MigrationConfigurationError(MigrationError):
    """Raised when migration configuration is invalid."""


class MigrationValidationError(MigrationError):
    """Raised when migration definitions are invalid."""


class MigrationExecutionError(MigrationError):
    """Raised when a migration fails to execute."""


class DatabaseConnectionError(MigrationError):
    """Raised when SQLite connection setup fails."""


# =============================================================================
# Data models
# =============================================================================


@dataclass(frozen=True, slots=True)
class Migration:
    """
    Immutable migration definition.

    Attributes
    ----------
    version:
        Positive, unique migration version.
    description:
        Human-readable description.
    sql:
        SQL script executed for the migration.
    """

    version: int
    description: str
    sql: str

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise MigrationValidationError(
                "Migration version must be greater than zero."
            )

        if not self.description.strip():
            raise MigrationValidationError(
                f"Migration {self.version} has an empty description."
            )

        if not self.sql.strip():
            raise MigrationValidationError(
                f"Migration {self.version} has empty SQL."
            )


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Result information for a migration run."""

    applied: int
    current_version: int
    previous_version: int
    backup_path: Path | None = None


# =============================================================================
# Migration definitions
# =============================================================================

_MIGRATIONS: Final[tuple[Migration, ...]] = (
    # -------------------------------------------------------------------------
    # Version 1
    # -------------------------------------------------------------------------
    Migration(
        version=1,
        description=(
            "Initial schema: conversations, messages, memories, tasks, "
            "settings, commands, profile, cache"
        ),
        sql="""
        CREATE TABLE IF NOT EXISTS conversations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL DEFAULT 'New Conversation',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
            ON conversations(updated_at);

        CREATE TABLE IF NOT EXISTS messages (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id  INTEGER NOT NULL,
            role             TEXT NOT NULL
                             CHECK (
                                 role IN (
                                     'system',
                                     'user',
                                     'assistant',
                                     'tool'
                                 )
                             ),
            content          TEXT NOT NULL,
            created_at       TEXT NOT NULL,

            FOREIGN KEY (conversation_id)
                REFERENCES conversations(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
            ON messages(conversation_id);

        CREATE INDEX IF NOT EXISTS idx_messages_created_at
            ON messages(created_at);

        CREATE TABLE IF NOT EXISTS memories (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_key     TEXT NOT NULL UNIQUE,
            memory_value   TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_updated_at
            ON memories(updated_at);

        CREATE TABLE IF NOT EXISTS tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            description  TEXT NOT NULL DEFAULT '',

            status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (
                             status IN (
                                 'pending',
                                 'in_progress',
                                 'completed',
                                 'cancelled'
                             )
                         ),

            priority     INTEGER NOT NULL DEFAULT 0,
            due_at      TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status);

        CREATE INDEX IF NOT EXISTS idx_tasks_due_at
            ON tasks(due_at);

        CREATE INDEX IF NOT EXISTS idx_tasks_priority
            ON tasks(priority);

        CREATE TABLE IF NOT EXISTS settings (
            setting_key    TEXT PRIMARY KEY,
            setting_value  TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS commands (
            name         TEXT PRIMARY KEY,
            command      TEXT NOT NULL,
            description  TEXT NOT NULL DEFAULT '',
            enabled      INTEGER NOT NULL DEFAULT 1
                         CHECK (enabled IN (0, 1)),
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_commands_enabled
            ON commands(enabled);

        CREATE TABLE IF NOT EXISTS profile (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            name        TEXT NOT NULL DEFAULT '',
            email       TEXT NOT NULL DEFAULT '',
            language    TEXT NOT NULL DEFAULT 'en',
            theme       TEXT NOT NULL DEFAULT 'dark',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cache (
            cache_key    TEXT PRIMARY KEY,
            cache_value  TEXT NOT NULL,
            expires_at   TEXT,
            created_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cache_expires_at
            ON cache(expires_at);
        """,
    ),

    # -------------------------------------------------------------------------
    # Version 2
    # -------------------------------------------------------------------------
    #
    # Reserved for safe future schema evolution.
    #
    # This migration intentionally creates metadata useful for application
    # diagnostics without changing the existing model contracts.
    #
    Migration(
        version=2,
        description="Add database metadata table for AssistantX diagnostics",
        sql="""
        CREATE TABLE IF NOT EXISTS database_metadata (
            metadata_key    TEXT PRIMARY KEY,
            metadata_value  TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        """,
    ),
)


# =============================================================================
# Internal state
# =============================================================================

_migration_lock = threading.RLock()


# =============================================================================
# Time helpers
# =============================================================================


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Path helpers
# =============================================================================


def _normalize_db_path(db_path: Path | str) -> Path:
    """Normalize and validate a database path."""
    path = Path(db_path).expanduser()

    if path.exists() and path.is_dir():
        raise MigrationConfigurationError(
            f"Database path points to a directory: {path}"
        )

    return path


# =============================================================================
# Migration validation
# =============================================================================


def validate_migrations() -> None:
    """
    Validate the migration registry.

    Raises
    ------
    MigrationValidationError
        If versions are duplicated, unordered, or invalid.
    """
    if not _MIGRATIONS:
        return

    versions = [migration.version for migration in _MIGRATIONS]

    if versions != sorted(versions):
        raise MigrationValidationError(
            "Migrations must be defined in ascending version order."
        )

    if len(versions) != len(set(versions)):
        duplicates = sorted(
            {
                version
                for version in versions
                if versions.count(version) > 1
            }
        )

        raise MigrationValidationError(
            f"Duplicate migration version(s): {duplicates}"
        )

    for migration in _MIGRATIONS:
        if migration.version <= 0:
            raise MigrationValidationError(
                f"Invalid migration version: {migration.version}"
            )

        if not migration.sql.strip():
            raise MigrationValidationError(
                f"Migration {migration.version} has empty SQL."
            )


# =============================================================================
# SQLite connection
# =============================================================================


def create_connection(
    db_path: Path | str = SQLITE_DB_PATH,
) -> sqlite3.Connection:
    """
    Create a consistently configured SQLite connection.

    Configuration
    -------------
    - sqlite3.Row row factory.
    - Foreign key enforcement.
    - WAL journal mode.
    - Busy timeout.
    - Normal synchronous mode.
    - Explicit transaction control.
    """
    path = _normalize_db_path(db_path)

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            str(path),
            timeout=DEFAULT_SQLITE_TIMEOUT,
            isolation_level="",
            check_same_thread=True,
        )

        connection.row_factory = sqlite3.Row

        # SQLite safety / concurrency configuration.
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute(
            f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS};"
        )

        # WAL is persistent at the database level.
        connection.execute("PRAGMA journal_mode = WAL;")

        # Good balance for a desktop application.
        connection.execute("PRAGMA synchronous = NORMAL;")

        return connection

    except sqlite3.Error as exc:
        logger.exception(
            "Failed to open SQLite database: %s",
            path,
        )

        raise DatabaseConnectionError(
            f"Unable to open SQLite database: {path}"
        ) from exc


# =============================================================================
# Schema version table
# =============================================================================


def _ensure_schema_version_table(
    connection: sqlite3.Connection,
) -> None:
    """Create the migration tracking table if necessary."""
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version      INTEGER PRIMARY KEY,
            description  TEXT NOT NULL,
            applied_at   TEXT NOT NULL
        );
        """
    )


def _applied_versions(
    connection: sqlite3.Connection,
) -> set[int]:
    """Return all successfully applied migration versions."""
    rows = connection.execute(
        f"""
        SELECT version
        FROM {MIGRATION_TABLE}
        ORDER BY version ASC;
        """
    ).fetchall()

    return {
        int(row["version"])
        for row in rows
    }


# =============================================================================
# Version helpers
# =============================================================================


def get_current_schema_version(
    db_path: Path | str = SQLITE_DB_PATH,
) -> int:
    """
    Return the highest successfully applied migration version.

    Returns 0 for a new database.
    """
    with _migration_lock:
        connection = create_connection(db_path)

        try:
            _ensure_schema_version_table(connection)

            row = connection.execute(
                f"""
                SELECT MAX(version) AS version
                FROM {MIGRATION_TABLE};
                """
            ).fetchone()

            if row is None or row["version"] is None:
                return 0

            return int(row["version"])

        finally:
            connection.close()


def get_latest_migration_version() -> int:
    """Return the latest migration version bundled with AssistantX."""
    return (
        _MIGRATIONS[-1].version
        if _MIGRATIONS
        else 0
    )


def is_database_up_to_date(
    db_path: Path | str = SQLITE_DB_PATH,
) -> bool:
    """Return True when the database is at the latest migration version."""
    return (
        get_current_schema_version(db_path)
        >= get_latest_migration_version()
    )


# =============================================================================
# Backup
# =============================================================================


def create_database_backup(
    db_path: Path | str = SQLITE_DB_PATH,
    backup_dir: Path | str | None = None,
) -> Path | None:
    """
    Create a timestamped copy of an existing SQLite database.

    Returns None if the database does not exist yet.
    """
    source = _normalize_db_path(db_path)

    if not source.exists():
        return None

    if backup_dir is None:
        backup_dir = source.parent / BACKUP_DIRECTORY_NAME

    destination_dir = Path(backup_dir).expanduser()
    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%d_%H%M%S")
    )

    destination = (
        destination_dir
        / f"{source.stem}_{timestamp}.db"
    )

    try:
        shutil.copy2(
            source,
            destination,
        )

        logger.info(
            "SQLite backup created: %s",
            destination,
        )

        return destination

    except OSError as exc:
        logger.exception(
            "Failed to create SQLite backup."
        )

        raise MigrationError(
            f"Failed to create database backup: {destination}"
        ) from exc


# =============================================================================
# Migration execution
# =============================================================================


def _apply_migration(
    connection: sqlite3.Connection,
    migration: Migration,
) -> None:
    """
    Apply one migration atomically.

    If any SQL statement fails, the transaction is rolled back.
    """
    logger.info(
        "Applying migration %d: %s",
        migration.version,
        migration.description,
    )

    try:
        connection.execute("BEGIN;")

        connection.executescript(migration.sql)

        connection.execute(
            f"""
            INSERT INTO {MIGRATION_TABLE}
                (version, description, applied_at)
            VALUES
                (?, ?, ?);
            """,
            (
                migration.version,
                migration.description,
                _utc_now_iso(),
            ),
        )

        connection.execute("COMMIT;")

    except sqlite3.Error as exc:
        try:
            connection.execute("ROLLBACK;")
        except sqlite3.Error:
            logger.exception(
                "Rollback failed after migration error."
            )

        raise MigrationExecutionError(
            f"Migration {migration.version} failed: "
            f"{migration.description}"
        ) from exc


# =============================================================================
# Main migration runner
# =============================================================================


def run_migrations(
    db_path: Path | str = SQLITE_DB_PATH,
    on_progress: Callable[[int, str], None] | None = None,
    *,
    create_backup: bool = True,
) -> MigrationResult:
    """
    Apply all pending migrations.

    Parameters
    ----------
    db_path:
        SQLite database path.

    on_progress:
        Optional callback:

            callback(version, description)

        Called after each migration has been successfully committed.

    create_backup:
        When True, an existing database is backed up before migrations
        are applied.

    Returns
    -------
    MigrationResult
        Details about the migration operation.

    Raises
    ------
    MigrationError
        If validation, backup, connection, or migration execution fails.
    """
    validate_migrations()

    with _migration_lock:
        path = _normalize_db_path(db_path)

        previous_version = get_current_schema_version(path)

        if previous_version > get_latest_migration_version():
            raise MigrationValidationError(
                "Database schema version is newer than this AssistantX "
                "build. Downgrading is not supported."
            )

        pending = [
            migration
            for migration in _MIGRATIONS
            if migration.version > previous_version
        ]

        if not pending:
            logger.debug(
                "Database schema already up to date: v%d",
                previous_version,
            )

            return MigrationResult(
                applied=0,
                current_version=previous_version,
                previous_version=previous_version,
                backup_path=None,
            )

        backup_path: Path | None = None

        if create_backup and path.exists():
            backup_path = create_database_backup(path)

        connection = create_connection(path)

        applied_count = 0

        try:
            _ensure_schema_version_table(connection)

            already_applied = _applied_versions(connection)

            for migration in pending:
                # Protect against inconsistent migration metadata.
                if migration.version in already_applied:
                    continue

                _apply_migration(
                    connection,
                    migration,
                )

                applied_count += 1

                if on_progress is not None:
                    try:
                        on_progress(
                            migration.version,
                            migration.description,
                        )
                    except Exception:
                        # Progress callbacks must never corrupt database
                        # migration state.
                        logger.exception(
                            "Migration progress callback failed "
                            "for migration %d.",
                            migration.version,
                        )

            current_version = get_current_schema_version(path)

            logger.info(
                "Database migration complete: "
                "%d migration(s), schema v%d.",
                applied_count,
                current_version,
            )

            return MigrationResult(
                applied=applied_count,
                current_version=current_version,
                previous_version=previous_version,
                backup_path=backup_path,
            )

        finally:
            connection.close()


# =============================================================================
# Database integrity
# =============================================================================


def check_database_integrity(
    db_path: Path | str = SQLITE_DB_PATH,
) -> bool:
    """
    Run SQLite's integrity_check pragma.

    Returns True when SQLite reports an ``ok`` result.
    """
    connection = create_connection(db_path)

    try:
        row = connection.execute(
            "PRAGMA integrity_check;"
        ).fetchone()

        if row is None:
            return False

        result = str(row[0]).strip().lower()

        if result == "ok":
            return True

        logger.error(
            "SQLite integrity check failed: %s",
            result,
        )

        return False

    except sqlite3.Error:
        logger.exception(
            "SQLite integrity check failed unexpectedly."
        )
        return False

    finally:
        connection.close()


# =============================================================================
# Foreign-key integrity
# =============================================================================


def check_foreign_keys(
    db_path: Path | str = SQLITE_DB_PATH,
) -> bool:
    """
    Check for foreign-key violations.

    Returns True when no violations are found.
    """
    connection = create_connection(db_path)

    try:
        rows = connection.execute(
            "PRAGMA foreign_key_check;"
        ).fetchall()

        if rows:
            logger.error(
                "SQLite foreign-key violations detected: %d",
                len(rows),
            )
            return False

        return True

    except sqlite3.Error:
        logger.exception(
            "Foreign-key integrity check failed."
        )
        return False

    finally:
        connection.close()


# =============================================================================
# Diagnostics
# =============================================================================


def diagnostics(
    db_path: Path | str = SQLITE_DB_PATH,
) -> dict[str, object]:
    """
    Return safe migration/database diagnostics.

    No user data, message contents, or secrets are included.
    """
    path = _normalize_db_path(db_path)

    current_version = get_current_schema_version(path)
    latest_version = get_latest_migration_version()

    return {
        "database_path": str(path),
        "database_exists": path.exists(),
        "current_schema_version": current_version,
        "latest_schema_version": latest_version,
        "pending_migrations": max(
            latest_version - current_version,
            0,
        ),
        "up_to_date": current_version >= latest_version,
        "database_size_bytes": (
            path.stat().st_size
            if path.exists()
            else 0
        ),
    }


# =============================================================================
# Public exports
# =============================================================================


__all__ = [
    "CURRENT_MIGRATION_VERSION",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_SQLITE_TIMEOUT",
    "DatabaseConnectionError",
    "Migration",
    "MigrationConfigurationError",
    "MigrationError",
    "MigrationExecutionError",
    "MigrationResult",
    "MigrationValidationError",
    "check_database_integrity",
    "check_foreign_keys",
    "create_connection",
    "create_database_backup",
    "diagnostics",
    "get_current_schema_version",
    "get_latest_migration_version",
    "is_database_up_to_date",
    "run_migrations",
    "validate_migrations",
]
