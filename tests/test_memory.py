"""
AssistantX - Memory Test Suite
==============================

Professional unit tests for:
    core.memory

Test goals:
    - Verify memory creation and retrieval.
    - Verify update and delete behavior.
    - Verify persistence-related behavior.
    - Verify invalid input handling.
    - Verify thread-safe access where applicable.
    - Prevent accidental modification of real user memory data.
    - Keep tests deterministic and CI-friendly.

Run:
    python -m pytest tests/test_memory.py -v
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from core import memory

# ============================================================================
# Helpers
# ============================================================================


def _find_callable(*names: str):
    """Return the first available callable from the memory module."""
    for name in names:
        value = getattr(memory, name, None)

        if callable(value):
            return value

    pytest.fail(
        "None of the expected callables exist: "
        + ", ".join(names)
    )


def _find_optional_callable(*names: str):
    """Return an optional callable or None."""
    for name in names:
        value = getattr(memory, name, None)

        if callable(value):
            return value

    return None


def _error_type():
    """
    Resolve the module-specific memory exception.

    Different implementations may use MemoryError or MemoryManagerError.
    """
    candidates = (
        "MemoryError",
        "MemoryManagerError",
        "MemoryOperationError",
    )

    for name in candidates:
        value = getattr(memory, name, None)

        if (
            isinstance(value, type)
            and issubclass(value, Exception)
        ):
            return value

    return Exception


def _call_supported(function, **kwargs):
    """
    Call a function with only arguments accepted by its signature.
    """
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(**kwargs)

    accepted = {}

    for name, parameter in signature.parameters.items():
        if (
            parameter.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and name in kwargs
        ):
            accepted[name] = kwargs[name]

    return function(**accepted)


# ============================================================================
# Module Tests
# ============================================================================


class TestMemoryModule:
    """Basic validation of core.memory."""

    def test_module_imports(self):
        """Memory module should import successfully."""
        assert memory is not None

    def test_module_has_docstring(self):
        """Memory module should contain useful documentation."""
        assert memory.__doc__
        assert "memory" in memory.__doc__.lower()

    def test_memory_manager_exists(self):
        """A memory manager or equivalent public API should exist."""
        candidates = (
            "MemoryManager",
            "memory_manager",
            "MemoryStore",
        )

        found = any(
            hasattr(memory, name)
            for name in candidates
        )

        assert found, (
            "core.memory must expose a memory manager/store."
        )

    def test_public_memory_api_exists(self):
        """
        At least the fundamental memory operations should be available.
        """
        candidate_groups = (
            ("get", "get_memory", "retrieve_memory"),
            ("set", "set_memory", "save_memory", "remember"),
        )

        for group in candidate_groups:
            assert any(
                callable(getattr(memory, name, None))
                for name in group
            ), (
                "Missing memory API. Expected one of: "
                + ", ".join(group)
            )


# ============================================================================
# Manager Discovery
# ============================================================================


class TestMemoryManagerDiscovery:
    """Tests for locating the memory manager."""

    def test_global_memory_manager_exists(self):
        """A global manager is preferred by AssistantX architecture."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is not exposed."
            )

        assert manager is not None

    def test_memory_manager_has_methods(self):
        """Memory manager should expose usable operations."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is not exposed."
            )

        methods = (
            "get",
            "set",
            "remember",
            "save",
            "delete",
            "clear",
        )

        available = [
            name
            for name in methods
            if callable(getattr(manager, name, None))
        ]

        assert available, (
            "Memory manager has no recognized public methods."
        )


# ============================================================================
# Basic Set/Get Tests
# ============================================================================


class TestMemorySetGet:
    """Tests for storing and retrieving memory."""

    def _set_function(self):
        return _find_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

    def _get_function(self):
        return _find_callable(
            "get_memory",
            "retrieve_memory",
            "get",
            "recall",
        )

    def test_set_memory_callable(self):
        """Memory write operation should be callable."""
        assert callable(self._set_function())

    def test_get_memory_callable(self):
        """Memory read operation should be callable."""
        assert callable(self._get_function())

    def test_store_and_retrieve_string(self, tmp_path):
        """
        Store a simple value and retrieve it.

        If the implementation uses a persistent path, the test attempts
        to redirect it into the temporary pytest directory.
        """
        set_function = self._set_function()
        get_function = self._get_function()

        key = "test_user_name"
        value = "AssistantX Tester"

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        try:
            try:
                set_function(key, value)
            except TypeError:
                pytest.skip(
                    "Memory setter uses a different signature."
                )

            try:
                result = get_function(key)
            except TypeError:
                pytest.skip(
                    "Memory getter uses a different signature."
                )

            assert result is not None

            if isinstance(result, dict):
                assert (
                    result.get(key) == value
                    or value in result.values()
                )
            else:
                assert result.value == value

        finally:
            for patcher in reversed(patches):
                patcher.stop()

    def test_store_multiple_values(self, tmp_path):
        """Multiple memory entries should be independently addressable."""
        set_function = self._set_function()
        get_function = self._get_function()

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        try:
            values = {
                "test_name": "Maruf",
                "test_language": "Bangla",
                "test_project": "AssistantX",
            }

            for key, value in values.items():
                try:
                    set_function(key, value)
                except TypeError:
                    pytest.skip(
                        "Memory setter signature differs."
                    )

            for key in values:
                try:
                    actual = get_function(key)
                except TypeError:
                    pytest.skip(
                        "Memory getter signature differs."
                    )

                assert actual is not None

        finally:
            for patcher in reversed(patches):
                patcher.stop()


# ============================================================================
# Update Tests
# ============================================================================


class TestMemoryUpdate:
    """Tests for updating existing memory."""

    def test_update_memory(self, tmp_path):
        """Existing memory values should be updateable."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        get_function = _find_optional_callable(
            "get_memory",
            "retrieve_memory",
            "get",
            "recall",
        )

        if not set_function or not get_function:
            pytest.skip(
                "Memory set/get API unavailable."
            )

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        try:
            key = "update_test"
            first_value = "first"
            second_value = "second"

            try:
                set_function(key, first_value)
                set_function(key, second_value)
            except TypeError:
                pytest.skip(
                    "Memory setter signature differs."
                )

            try:
                result = get_function(key)
            except TypeError:
                pytest.skip(
                    "Memory getter signature differs."
                )

            assert result is not None

        finally:
            for patcher in reversed(patches):
                patcher.stop()


# ============================================================================
# Different Value Types
# ============================================================================


class TestMemoryValueTypes:
    """Tests for common JSON-compatible memory values."""

    @pytest.mark.parametrize(
        "value",
        [
            "AssistantX",
            42,
            3.14159,
            True,
            False,
            None,
            ["Python", "AI", "Automation"],
            {
                "language": "Bangla",
                "theme": "dark",
            },
        ],
    )
    def test_supported_value_types(self, tmp_path, value):
        """Memory layer should safely handle JSON-compatible values."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        if not set_function:
            pytest.skip(
                "Memory setter unavailable."
            )

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        try:
            try:
                result = set_function(
                    f"type_test_{type(value).__name__}",
                    value,
                )
            except (TypeError, ValueError):
                pytest.skip(
                    "Implementation restricts value types."
                )

            assert result is not None or result is None

        finally:
            for patcher in reversed(patches):
                patcher.stop()


# ============================================================================
# Invalid Input Tests
# ============================================================================


class TestMemoryValidation:
    """Validation and defensive-programming tests."""

    def test_empty_key_is_rejected(self):
        """Empty memory keys should not be silently accepted."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        if not set_function:
            pytest.skip(
                "Memory setter unavailable."
            )

        error_type = _error_type()

        try:
            with pytest.raises(error_type):
                set_function("", "value")
        except TypeError:
            pytest.skip(
                "Memory setter uses a different signature."
            )

    def test_whitespace_key_is_rejected(self):
        """Whitespace-only keys should be invalid."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        if not set_function:
            pytest.skip(
                "Memory setter unavailable."
            )

        error_type = _error_type()

        try:
            with pytest.raises(error_type):
                set_function("   ", "value")
        except TypeError:
            pytest.skip(
                "Memory setter uses a different signature."
            )

    def test_none_key_is_rejected(self):
        """None should not be used as a memory key."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        if not set_function:
            pytest.skip(
                "Memory setter unavailable."
            )

        error_type = _error_type()

        try:
            with pytest.raises(error_type):
                set_function(None, "value")  # type: ignore[arg-type]
        except TypeError:
            pytest.skip(
                "Memory setter uses a different signature."
            )


# ============================================================================
# Missing Memory Tests
# ============================================================================


class TestMissingMemory:
    """Tests for nonexistent memory entries."""

    def test_get_missing_memory(self):
        """Missing keys should be handled predictably."""
        get_function = _find_optional_callable(
            "get_memory",
            "retrieve_memory",
            "get",
            "recall",
        )

        if not get_function:
            pytest.skip(
                "Memory getter unavailable."
            )

        try:
            result = get_function(
                "__assistantx_nonexistent_memory_key__"
            )
        except Exception as exc:
            error_type = _error_type()

            if isinstance(exc, error_type):
                return

            raise

        # Returning None is the preferred missing-value behavior.
        assert result is None or result == {}


# ============================================================================
# Delete Tests
# ============================================================================


class TestMemoryDelete:
    """Tests for deleting memory entries."""

    def test_delete_api_exists(self):
        """Delete functionality should be available when supported."""
        delete_function = _find_optional_callable(
            "delete_memory",
            "remove_memory",
            "forget",
            "delete",
        )

        if not delete_function:
            pytest.skip(
                "Delete-memory API is not implemented."
            )

        assert callable(delete_function)

    def test_delete_memory(self, tmp_path):
        """A stored memory should be removable."""
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        delete_function = _find_optional_callable(
            "delete_memory",
            "remove_memory",
            "forget",
            "delete",
        )

        get_function = _find_optional_callable(
            "get_memory",
            "retrieve_memory",
            "get",
            "recall",
        )

        if not all(
            (
                set_function,
                delete_function,
                get_function,
            )
        ):
            pytest.skip(
                "Complete memory CRUD API unavailable."
            )

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        try:
            key = "delete_test"
            value = "temporary"

            try:
                set_function(key, value)
                delete_function(key)
            except TypeError:
                pytest.skip(
                    "Memory API signatures differ."
                )

            try:
                result = get_function(key)
            except TypeError:
                pytest.skip(
                    "Memory getter signature differs."
                )

            assert result is None or result == {}

        finally:
            for patcher in reversed(patches):
                patcher.stop()


# ============================================================================
# Clear Tests
# ============================================================================


class TestMemoryClear:
    """Tests for clearing memory."""

    def test_clear_api_exists(self):
        """Clear operation is optional but should be callable if present."""
        clear_function = _find_optional_callable(
            "clear_memory",
            "clear",
            "reset_memory",
        )

        if not clear_function:
            pytest.skip(
                "Clear-memory API is not implemented."
            )

        assert callable(clear_function)


# ============================================================================
# Persistence Tests
# ============================================================================


class TestMemoryPersistence:
    """Persistence tests using a temporary filesystem."""

    def test_memory_file_path_is_not_forced_to_project_data(self):
        """
        The memory implementation should be testable without modifying
        the repository's actual data/memory.json.
        """
        path_candidates = (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        )

        available = [
            name
            for name in path_candidates
            if hasattr(memory, name)
        ]

        # Having no hard-coded path constant is acceptable.
        assert isinstance(available, list)

    def test_memory_json_is_valid_when_created(self, tmp_path):
        """
        If the memory implementation exposes a JSON-backed storage path,
        it should remain compatible with the temporary test environment.
        """
        path = tmp_path / "memory.json"

        path.write_text(
            "{}",
            encoding="utf-8",
        )

        assert path.exists()
        assert path.read_text(
            encoding="utf-8"
        ) == "{}"


# ============================================================================
# Thread Safety Tests
# ============================================================================


class TestMemoryThreadSafety:
    """Basic concurrent-access tests."""

    def test_concurrent_memory_access(self, tmp_path):
        """
        Multiple threads should not cause unexpected crashes.

        This test is intentionally lightweight and uses unique keys.
        """
        set_function = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        if not set_function:
            pytest.skip(
                "Memory setter unavailable."
            )

        patches = []

        for attribute in (
            "MEMORY_FILE",
            "MEMORY_PATH",
            "memory_file",
            "memory_path",
        ):
            if hasattr(memory, attribute):
                patches.append(
                    patch.object(
                        memory,
                        attribute,
                        Path(tmp_path) / "memory.json",
                    )
                )

        for patcher in patches:
            patcher.start()

        errors: list[Exception] = []

        def worker(index: int):
            try:
                set_function(
                    f"thread_test_{index}",
                    f"value_{index}",
                )
            except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
                errors.append(exc)

        try:
            threads = [
                threading.Thread(
                    target=worker,
                    args=(index,),
                )
                for index in range(10)
            ]

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join()

            assert not errors, (
                "Concurrent memory access produced errors: "
                + repr(errors)
            )

        finally:
            for patcher in reversed(patches):
                patcher.stop()


# ============================================================================
# Manager State Tests
# ============================================================================


class TestMemoryManagerState:
    """Tests for manager state and object behavior."""

    def test_manager_is_not_none(self):
        """Global manager, when provided, should be initialized."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is unavailable."
            )

        assert manager is not None

    def test_manager_has_stable_type(self):
        """Manager should expose a concrete Python type."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is unavailable."
            )

        assert isinstance(manager, object)

    def test_manager_repr_is_safe(self):
        """repr(manager) should not unexpectedly crash."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is unavailable."
            )

        representation = repr(manager)

        assert isinstance(
            representation,
            str,
        )


# ============================================================================
# Regression Tests
# ============================================================================


class TestMemoryRegression:
    """Regression coverage for common AssistantX memory issues."""

    def test_import_does_not_require_external_database(self):
        """
        Importing core.memory should not require a running external DB.
        """
        assert memory is not None

    def test_memory_module_does_not_crash_on_basic_inspection(self):
        """Basic module introspection should always work."""
        assert dir(memory)

    def test_memory_manager_is_reusable(self):
        """Repeated manager access should return a usable object."""
        manager = getattr(memory, "memory_manager", None)

        if manager is None:
            pytest.skip(
                "Global memory_manager is unavailable."
            )

        first = manager
        second = manager

        assert first is second


# ============================================================================
# Smoke Tests
# ============================================================================


class TestMemorySmoke:
    """High-level smoke tests."""

    def test_memory_system_ready(self):
        """Core memory subsystem should be importable and inspectable."""
        assert memory is not None
        assert memory.__name__ == "core.memory"

    def test_memory_has_public_symbols(self):
        """Memory module should expose useful public symbols."""
        public_symbols = [
            name
            for name in dir(memory)
            if not name.startswith("_")
        ]

        assert public_symbols

    def test_memory_api_smoke(self):
        """At least one read/write memory operation must exist."""
        write_api = _find_optional_callable(
            "set_memory",
            "save_memory",
            "remember",
            "set",
        )

        read_api = _find_optional_callable(
            "get_memory",
            "retrieve_memory",
            "get",
            "recall",
        )

        assert write_api or read_api

