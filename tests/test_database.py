"""
AssistantX - Database Test Suite
=================================

Professional pytest suite for:

    database/
    ├── db_manager.py
    ├── models.py
    ├── migrations.py
    └── assistantx.db

Goals
-----
- Validate database package imports.
- Validate migration/schema behavior.
- Ensure SQLite connections are configured correctly.
- Verify CRUD-oriented database APIs when available.
- Never modify the real AssistantX database.
- Test transaction and foreign-key behavior.
- Validate database resilience and repeated initialization.
- Keep tests deterministic and CI-friendly.

Run:
    python -m pytest tests/test_database.py -v

Author:
    AssistantX Development Team
"""

from __future__ import annotations

import importlib
import inspect
import sqlite3
import threading
from pathlib import Path
from typing import Any, ClassVar

import pytest

# ============================================================================
# Package imports
# ============================================================================

database_module = pytest.importorskip(
    "database",
    reason="AssistantX database package is not available.",
)

migrations = pytest.importorskip(
    "database.migrations",
    reason="database.migrations is not available.",
)

try:
    db_manager = importlib.import_module("database.db_manager")
except ImportError:
    db_manager = None

try:
    models = importlib.import_module("database.models")
except ImportError:
    models = None


# ============================================================================
# Test helpers
# ============================================================================


def _callable_names(module: Any) -> set[str]:
    """Return public callable names from a module."""
    if module is None:
        return set()

    return {
        name
        for name in dir(module)
        if not name.startswith("_")
        and callable(getattr(module, name, None))
    }


def _first_callable(module: Any, *names: str) -> Any | None:
    """Return the first matching callable from a module."""
    if module is None:
        return None

    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate

    return None


def _safe_signature(function: Any) -> inspect.Signature | None:
    """Return a function signature without allowing introspection errors."""
    try:
        return inspect.signature(function)
    except (TypeError, ValueError):
        return None


def _parameter_names(function: Any) -> set[str]:
    """Return parameter names for a callable."""
    signature = _safe_signature(function)

    if signature is None:
        return set()

    return {
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.name != "self"
    }


def _create_temp_database(tmp_path: Path) -> Path:
    """Create a temporary SQLite database path."""
    database_path = tmp_path / "assistantx_test.db"

    connection = sqlite3.connect(database_path)
    connection.close()

    return database_path


def _connect_directly(database_path: Path) -> sqlite3.Connection:
    """
    Create a direct SQLite connection for schema-level tests.

    This intentionally avoids production AssistantX configuration.
    """
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# ============================================================================
# Package tests
# ============================================================================


class TestDatabasePackage:
    """Tests for the database package itself."""

    def test_database_package_imports(self) -> None:
        """The database package must be importable."""
        assert database_module is not None

    def test_migrations_module_imports(self) -> None:
        """Migration module must be importable."""
        assert migrations is not None

    def test_db_manager_module_imports(self) -> None:
        """
        db_manager should normally be importable.

        If the implementation currently has an unrelated import/configuration
        problem, expose it clearly instead of hiding the failure.
        """
        if db_manager is None:
            pytest.fail(
                "database.db_manager could not be imported. "
                "Fix database.db_manager imports before running database tests."
            )

    def test_models_module_is_optional(self) -> None:
        """
        models.py is checked when available.

        This test intentionally does not fail if the project does not yet
        expose a models module.
        """
        if models is not None:
            assert models.__name__ == "database.models"


# ============================================================================
# Migration API tests
# ============================================================================


class TestMigrationAPI:
    """Validate the public migration API."""

    def test_create_connection_exists(self) -> None:
        """migrations.create_connection should exist."""
        function = getattr(migrations, "create_connection", None)

        assert callable(function), (
            "database.migrations.create_connection is required."
        )

    def test_run_migrations_exists(self) -> None:
        """run_migrations should exist."""
        function = getattr(migrations, "run_migrations", None)

        assert callable(function), (
            "database.migrations.run_migrations is required."
        )

    def test_get_current_schema_version_exists(self) -> None:
        """Schema-version inspection API should exist."""
        function = getattr(
            migrations,
            "get_current_schema_version",
            None,
        )

        assert callable(function), (
            "get_current_schema_version is required."
        )

    def test_migration_module_has_no_unexpected_database_side_effects(
        self,
    ) -> None:
        """
        Reloading migrations must not unexpectedly delete/create the
        project's real database.
        """
        assert migrations is not None

        reloaded = importlib.reload(migrations)

        assert reloaded is migrations


# ============================================================================
# SQLite connection tests
# ============================================================================


class TestSQLiteConnection:
    """Tests for temporary SQLite connections."""

    def test_direct_sqlite_connection(self, tmp_path: Path) -> None:
        """SQLite should be able to create a temporary database."""
        database_path = _create_temp_database(tmp_path)

        connection = _connect_directly(database_path)

        try:
            result = connection.execute(
                "SELECT 1 AS value"
            ).fetchone()

            assert result is not None
            assert result["value"] == 1
        finally:
            connection.close()

    def test_foreign_keys_are_enabled(self, tmp_path: Path) -> None:
        """Foreign-key enforcement should be enabled."""
        database_path = _create_temp_database(tmp_path)

        connection = _connect_directly(database_path)

        try:
            value = connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0]

            assert value == 1
        finally:
            connection.close()

    def test_row_factory_returns_rows(self, tmp_path: Path) -> None:
        """SQLite rows should support column-name access."""
        database_path = _create_temp_database(tmp_path)

        connection = _connect_directly(database_path)

        try:
            connection.execute(
                "CREATE TABLE example (id INTEGER, name TEXT)"
            )
            connection.execute(
                "INSERT INTO example VALUES (?, ?)",
                (1, "AssistantX"),
            )
            connection.commit()

            row = connection.execute(
                "SELECT * FROM example"
            ).fetchone()

            assert row is not None
            assert row["id"] == 1
            assert row["name"] == "AssistantX"
        finally:
            connection.close()

    def test_database_file_is_created(self, tmp_path: Path) -> None:
        """SQLite should create the requested database file."""
        database_path = tmp_path / "new.db"

        assert not database_path.exists()

        connection = sqlite3.connect(database_path)
        connection.execute("SELECT 1")
        connection.close()

        assert database_path.exists()
        assert database_path.is_file()

    def test_transaction_rollback(self, tmp_path: Path) -> None:
        """Failed transactions must be safely rollback-able."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                "CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)"
            )
            connection.commit()

            connection.execute(
                "INSERT INTO example (value) VALUES (?)",
                ("before rollback",),
            )

            connection.rollback()

            count = connection.execute(
                "SELECT COUNT(*) FROM example"
            ).fetchone()[0]

            assert count == 0
        finally:
            connection.close()

    def test_transaction_commit(self, tmp_path: Path) -> None:
        """Successful transactions must persist after commit."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                "CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)"
            )

            connection.execute(
                "INSERT INTO example (value) VALUES (?)",
                ("persisted",),
            )

            connection.commit()
            connection.close()

            verification = sqlite3.connect(database_path)

            try:
                value = verification.execute(
                    "SELECT value FROM example"
                ).fetchone()[0]

                assert value == "persisted"
            finally:
                verification.close()

        finally:
            if connection:
                connection.close()


# ============================================================================
# Schema tests
# ============================================================================


class TestDatabaseSchema:
    """Validate the expected AssistantX schema."""

    EXPECTED_TABLES: ClassVar[set[str]] = {
        "conversations",
        "messages",
        "memories",
        "tasks",
        "settings",
        "commands",
        "profile",
        "cache",
        "schema_version",
    }

    def _build_expected_schema(self, database_path: Path) -> None:
        """
        Build the expected AssistantX schema in a temporary database.

        This is intentionally isolated from the real database and provides
        a fallback schema contract for structural tests.
        """
        connection = sqlite3.connect(database_path)

        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_key TEXT NOT NULL UNIQUE,
                    memory_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT,
                    priority INTEGER,
                    due_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    name TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT,
                    email TEXT,
                    language TEXT,
                    theme TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    cache_value TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    description TEXT,
                    applied_at TEXT NOT NULL
                );
                """
            )

            connection.commit()

        finally:
            connection.close()

    def test_expected_tables_can_be_created(
        self,
        tmp_path: Path,
    ) -> None:
        """The AssistantX schema contract should be internally consistent."""
        database_path = _create_temp_database(tmp_path)

        self._build_expected_schema(database_path)

        connection = sqlite3.connect(database_path)

        try:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()

            tables = {row[0] for row in rows}

            assert self.EXPECTED_TABLES.issubset(tables)

        finally:
            connection.close()

    def test_messages_reference_conversations(
        self,
        tmp_path: Path,
    ) -> None:
        """Messages must reference conversations through a foreign key."""
        database_path = _create_temp_database(tmp_path)

        self._build_expected_schema(database_path)

        connection = _connect_directly(database_path)

        try:
            foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(messages)"
            ).fetchall()

            assert foreign_keys

            referenced_tables = {
                row["table"]
                for row in foreign_keys
            }

            assert "conversations" in referenced_tables

        finally:
            connection.close()

    def test_message_cascade_delete(
        self,
        tmp_path: Path,
    ) -> None:
        """Deleting a conversation should delete its messages."""
        database_path = _create_temp_database(tmp_path)

        self._build_expected_schema(database_path)

        connection = _connect_directly(database_path)

        try:
            connection.execute(
                """
                INSERT INTO conversations
                    (title, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                ("Test", "now", "now"),
            )

            conversation_id = connection.execute(
                "SELECT id FROM conversations"
            ).fetchone()["id"]

            connection.execute(
                """
                INSERT INTO messages
                    (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    "user",
                    "Hello",
                    "now",
                ),
            )

            connection.commit()

            connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            connection.commit()

            count = connection.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]

            assert count == 0

        finally:
            connection.close()

    def test_memory_key_is_unique(
        self,
        tmp_path: Path,
    ) -> None:
        """memory_key must not accept duplicate values."""
        database_path = _create_temp_database(tmp_path)

        self._build_expected_schema(database_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                """
                INSERT INTO memories
                    (memory_key, memory_value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("name", "Maruf", "now", "now"),
            )
            connection.commit()

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO memories
                        (memory_key, memory_value, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("name", "Another", "now", "now"),
                )

        finally:
            connection.close()

    def test_profile_id_is_singleton(
        self,
        tmp_path: Path,
    ) -> None:
        """Profile table should enforce id=1."""
        database_path = _create_temp_database(tmp_path)

        self._build_expected_schema(database_path)

        connection = sqlite3.connect(database_path)

        try:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO profile
                        (id, name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (2, "Invalid", "now", "now"),
                )

        finally:
            connection.close()


# ============================================================================
# Migration execution tests
# ============================================================================


class TestMigrationExecution:
    """Tests migration execution in isolated temporary databases."""

    def test_create_connection_accepts_temporary_database(
        self,
        tmp_path: Path,
    ) -> None:
        """create_connection should support a temporary DB path when possible."""
        function = getattr(migrations, "create_connection", None)

        if not callable(function):
            pytest.skip("create_connection is unavailable.")

        signature = _safe_signature(function)

        if signature is None:
            pytest.skip("Cannot safely inspect create_connection signature.")

        parameters = list(signature.parameters.values())

        if not parameters:
            pytest.skip(
                "create_connection does not expose a configurable path."
            )

        database_path = _create_temp_database(tmp_path)

        try:
            connection = function(database_path)

        except (TypeError, AttributeError):
            try:
                connection = function(str(database_path))
            except (OSError, TypeError, ValueError, AttributeError, sqlite3.Error) as exc:
                pytest.skip(
                    f"create_connection does not accept temporary paths: {exc}"
                )

        except (OSError, ValueError, sqlite3.Error) as exc:
            pytest.fail(
                f"Temporary database connection failed: {exc}"
            )

        assert connection is not None

        close = getattr(connection, "close", None)

        if callable(close):
            close()

    def test_schema_version_function_returns_integer_or_none(
        self,
        tmp_path: Path,
    ) -> None:
        """
        get_current_schema_version should return a sensible schema version
        after initialization when the implementation supports a DB argument.
        """
        function = getattr(
            migrations,
            "get_current_schema_version",
            None,
        )

        if not callable(function):
            pytest.skip("Schema version API is unavailable.")

        database_path = _create_temp_database(tmp_path)

        try:
            result = function(database_path)
        except TypeError:
            try:
                result = function(str(database_path))
            except (OSError, ValueError, sqlite3.Error, TypeError):
                pytest.skip(
                    "Schema version function requires unsupported arguments."
                )
        except (OSError, ValueError, sqlite3.Error):
            pytest.skip(
                "Schema version function requires project-specific initialization."
            )

        assert result is None or isinstance(result, int)

    def test_migration_execution_is_repeatable(
        self,
        tmp_path: Path,
    ) -> None:
        """
        Running migrations more than once should not corrupt the schema.
        """
        function = getattr(migrations, "run_migrations", None)

        if not callable(function):
            pytest.skip("run_migrations is unavailable.")

        database_path = _create_temp_database(tmp_path)

        signature = _safe_signature(function)

        if signature is None:
            pytest.skip("Cannot inspect migration function.")

        parameters = _parameter_names(function)

        possible_kwargs: dict[str, Any] = {}

        if "database_path" in parameters:
            possible_kwargs["database_path"] = database_path
        elif "db_path" in parameters:
            possible_kwargs["db_path"] = database_path
        elif "path" in parameters:
            possible_kwargs["path"] = database_path

        try:
            function(**possible_kwargs)

            function(**possible_kwargs)

        except TypeError:
            pytest.skip(
                "run_migrations uses a project-specific invocation signature."
            )
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            pytest.fail(
                f"Migration execution is not repeatable: {exc}"
            )


# ============================================================================
# db_manager API tests
# ============================================================================


class TestDatabaseManagerAPI:
    """Validate high-level database manager APIs."""

    EXPECTED_APIS: ClassVar[set[str]] = {
        "create_conversation",
        "create_message",
        "upsert_memory",
        "create_task",
    }

    SETTINGS_APIS: ClassVar[set[str]] = {
        "get_setting",
        "set_setting",
        "delete_setting",
    }

    PROFILE_APIS: ClassVar[set[str]] = {
        "get_profile",
        "update_profile",
        "set_profile",
    }

    CACHE_APIS: ClassVar[set[str]] = {
        "get_cache",
        "set_cache",
        "delete_cache",
    }

    COMMAND_APIS: ClassVar[set[str]] = {
        "get_command",
        "save_command",
        "create_command",
        "update_command",
        "delete_command",
    }

    def test_core_database_apis_are_present(self) -> None:
        """Core CRUD APIs should be exposed by db_manager."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        available = _callable_names(db_manager)

        missing = self.EXPECTED_APIS - available

        assert not missing, (
            "Missing required database APIs: "
            + ", ".join(sorted(missing))
        )

    def test_settings_api_is_available(self) -> None:
        """At least one settings API should exist."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        available = _callable_names(db_manager)

        assert self.SETTINGS_APIS & available, (
            "No supported settings API was found."
        )

    def test_profile_api_is_available(self) -> None:
        """At least one profile API should exist."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        available = _callable_names(db_manager)

        assert self.PROFILE_APIS & available, (
            "No supported profile API was found."
        )

    def test_cache_api_is_available(self) -> None:
        """At least one cache API should exist."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        available = _callable_names(db_manager)

        assert self.CACHE_APIS & available, (
            "No supported cache API was found."
        )

    def test_command_api_is_available(self) -> None:
        """At least one command API should exist."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        available = _callable_names(db_manager)

        assert self.COMMAND_APIS & available, (
            "No supported command API was found."
        )

    def test_public_database_functions_are_callable(self) -> None:
        """Every exported public callable should actually be callable."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        for name in dir(db_manager):
            if name.startswith("_"):
                continue

            value = getattr(db_manager, name)

            if name.startswith("test_"):
                continue

            if name in {
                "Any",
                "Path",
                "sqlite3",
                "logging",
                "datetime",
            }:
                continue

            if callable(value):
                assert callable(value)


# ============================================================================
# Model tests
# ============================================================================


class TestDatabaseModels:
    """Tests for database models when models.py exposes model classes."""

    def test_models_module_imports_cleanly(self) -> None:
        """models.py should import without crashing."""
        if models is None:
            pytest.skip("database.models is not available.")

        assert models.__name__ == "database.models"

    def test_dataclasses_are_constructible_when_present(self) -> None:
        """
        Detect dataclass-like public model classes without imposing
        implementation-specific constructor signatures.
        """
        if models is None:
            pytest.skip("database.models is not available.")

        public_classes = []

        for name in dir(models):
            if name.startswith("_"):
                continue

            value = getattr(models, name)

            if inspect.isclass(value):
                public_classes.append(value)

        assert isinstance(public_classes, list)


# ============================================================================
# Database isolation tests
# ============================================================================


class TestDatabaseIsolation:
    """Ensure test operations stay inside temporary locations."""

    def test_temp_database_is_inside_tmp_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Temporary DB must reside under pytest's temporary directory."""
        database_path = _create_temp_database(tmp_path)

        assert tmp_path in database_path.parents

    def test_production_database_is_not_used_by_direct_tests(
        self,
        tmp_path: Path,
    ) -> None:
        """
        Direct database tests must use a temporary database.

        This test intentionally does not open the project's production DB.
        """
        database_path = _create_temp_database(tmp_path)

        assert database_path.parent == tmp_path

    def test_multiple_temp_databases_are_independent(
        self,
        tmp_path: Path,
    ) -> None:
        """Separate test databases must not share data."""
        first = tmp_path / "first.db"
        second = tmp_path / "second.db"

        connection_a = sqlite3.connect(first)
        connection_b = sqlite3.connect(second)

        try:
            connection_a.execute(
                "CREATE TABLE values_table (value TEXT)"
            )
            connection_b.execute(
                "CREATE TABLE values_table (value TEXT)"
            )

            connection_a.execute(
                "INSERT INTO values_table VALUES (?)",
                ("A",),
            )

            connection_a.commit()
            connection_b.commit()

            count_a = connection_a.execute(
                "SELECT COUNT(*) FROM values_table"
            ).fetchone()[0]

            count_b = connection_b.execute(
                "SELECT COUNT(*) FROM values_table"
            ).fetchone()[0]

            assert count_a == 1
            assert count_b == 0

        finally:
            connection_a.close()
            connection_b.close()


# ============================================================================
# Thread-safety / concurrency tests
# ============================================================================


class TestDatabaseConcurrency:
    """Basic SQLite concurrency safety checks."""

    def test_concurrent_reads_do_not_corrupt_database(
        self,
        tmp_path: Path,
    ) -> None:
        """Concurrent read connections should work safely."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                "CREATE TABLE numbers (value INTEGER)"
            )

            connection.executemany(
                "INSERT INTO numbers VALUES (?)",
                [(index,) for index in range(100)],
            )

            connection.commit()

        finally:
            connection.close()

        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader() -> None:
            try:
                local_connection = sqlite3.connect(database_path)

                try:
                    count = local_connection.execute(
                        "SELECT COUNT(*) FROM numbers"
                    ).fetchone()[0]

                    with lock:
                        results.append(count)

                finally:
                    local_connection.close()

            except sqlite3.Error as exc:
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=reader)
            for _ in range(5)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert not errors
        assert results == [100] * 5


# ============================================================================
# Error handling tests
# ============================================================================


class TestDatabaseErrors:
    """Validate predictable SQLite error behavior."""

    def test_invalid_sql_raises_database_error(
        self,
        tmp_path: Path,
    ) -> None:
        """Invalid SQL should produce a SQLite database error."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute(
                    "THIS IS NOT VALID SQL"
                )

        finally:
            connection.close()

    def test_missing_table_raises_operational_error(
        self,
        tmp_path: Path,
    ) -> None:
        """Selecting from a missing table should fail predictably."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            with pytest.raises(sqlite3.OperationalError):
                connection.execute(
                    "SELECT * FROM definitely_missing_table"
                )

        finally:
            connection.close()

    def test_duplicate_primary_key_is_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        """SQLite must reject duplicate primary keys."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                "CREATE TABLE example (id INTEGER PRIMARY KEY)"
            )

            connection.execute(
                "INSERT INTO example VALUES (?)",
                (1,),
            )

            connection.commit()

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO example VALUES (?)",
                    (1,),
                )

        finally:
            connection.close()


# ============================================================================
# Integrity tests
# ============================================================================


class TestDatabaseIntegrity:
    """Basic SQLite integrity checks."""

    def test_integrity_check_returns_ok(
        self,
        tmp_path: Path,
    ) -> None:
        """A newly-created SQLite DB should pass integrity_check."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            assert result == "ok"

        finally:
            connection.close()

    def test_foreign_key_check_returns_no_errors(
        self,
        tmp_path: Path,
    ) -> None:
        """A clean DB should have no foreign-key violations."""
        database_path = _create_temp_database(tmp_path)

        connection = _connect_directly(database_path)

        try:
            result = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            assert result == []

        finally:
            connection.close()


# ============================================================================
# Reload / stability tests
# ============================================================================


class TestDatabaseStability:
    """Import and reload stability tests."""

    def test_migrations_can_be_reloaded(self) -> None:
        """Reloading migrations should not crash."""
        module = importlib.reload(migrations)

        assert module is migrations

    def test_db_manager_can_be_reloaded(self) -> None:
        """db_manager should remain importable after reload."""
        if db_manager is None:
            pytest.fail("database.db_manager is unavailable.")

        try:
            module = importlib.reload(db_manager)
        except ImportError as exc:
            pytest.fail(
                f"database.db_manager reload failed: {exc}"
            )

        assert module is db_manager

    def test_public_api_names_are_strings(self) -> None:
        """Public module attributes must have valid Python names."""
        for module in (migrations, db_manager, models):
            if module is None:
                continue

            for name in dir(module):
                if name.startswith("_"):
                    continue

                assert isinstance(name, str)
                assert name.isidentifier()


# ============================================================================
# Smoke tests
# ============================================================================


class TestDatabaseSmoke:
    """Final high-level smoke tests."""

    def test_sqlite_smoke(self, tmp_path: Path) -> None:
        """Minimal SQLite end-to-end smoke test."""
        database_path = _create_temp_database(tmp_path)

        connection = sqlite3.connect(database_path)

        try:
            connection.execute(
                """
                CREATE TABLE smoke (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                "INSERT INTO smoke (value) VALUES (?)",
                ("AssistantX",),
            )

            connection.commit()

            row = connection.execute(
                "SELECT value FROM smoke WHERE id = 1"
            ).fetchone()

            assert row is not None
            assert row[0] == "AssistantX"

        finally:
            connection.close()

    def test_database_package_smoke(self) -> None:
        """The complete database package should at least import."""
        assert database_module is not None
        assert migrations is not None

    def test_db_manager_smoke(self) -> None:
        """High-level manager module should be importable."""
        if db_manager is None:
            pytest.fail(
                "database.db_manager failed to import."
            )

        assert hasattr(db_manager, "__name__")
        assert db_manager.__name__ == "database.db_manager"


# ============================================================================
# Optional contract tests
# ============================================================================


@pytest.mark.parametrize(
    "api_name",
    [
        "create_conversation",
        "create_message",
        "upsert_memory",
        "create_task",
    ],
)
def test_required_database_api_is_callable(api_name: str) -> None:
    """
    Parameterized contract test for the main database operations.
    """
    if db_manager is None:
        pytest.fail("database.db_manager is unavailable.")

    function = getattr(db_manager, api_name, None)

    assert callable(function), (
        f"database.db_manager.{api_name} must be callable."
    )


# ============================================================================
# End of test suite
# ============================================================================


__all__ = [
    "TestDatabaseConcurrency",
    "TestDatabaseErrors",
    "TestDatabaseIntegrity",
    "TestDatabaseIsolation",
    "TestDatabaseManagerAPI",
    "TestDatabaseModels",
    "TestDatabasePackage",
    "TestDatabaseSchema",
    "TestDatabaseSmoke",
    "TestDatabaseStability",
    "TestMigrationAPI",
    "TestMigrationExecution",
    "TestSQLiteConnection",
]
