"""
AssistantX - System Automation Test Suite
==========================================

Professional unit tests for:
    automation.system

Design goals:
    - Never execute real system power operations.
    - Never modify the user's actual system settings.
    - Mock OS/subprocess backends.
    - Validate public API and error handling.
    - Windows/Linux/macOS compatible test structure.
    - Suitable for local development and CI.

Run:
    python -m pytest tests/test_system.py -v
"""

from __future__ import annotations

import inspect
from unittest.mock import Mock, patch

import pytest

from automation import system

# ============================================================================
# Test Helpers
# ============================================================================


def _require_callable(name: str):
    """Return a required callable from automation.system."""
    value = getattr(system, name, None)

    if value is None:
        pytest.fail(
            f"automation.system is missing required callable: {name}"
        )

    if not callable(value):
        pytest.fail(
            f"automation.system.{name} exists but is not callable."
        )

    return value


def _error_type():
    """Return the module-specific system automation exception."""
    error = getattr(system, "SystemAutomationError", None)

    if error is None:
        error = getattr(system, "SystemError", None)

    if error is None:
        pytest.fail(
            "automation.system does not expose "
            "SystemAutomationError or SystemError."
        )

    return error


def _call_if_supported(function, **kwargs):
    """
    Call a function using only parameters accepted by its signature.

    This is useful when implementations expose optional keyword arguments.
    """
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(**kwargs)

    accepted = {}

    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ) and name in kwargs:
            accepted[name] = kwargs[name]

    return function(**accepted)


# ============================================================================
# Module Tests
# ============================================================================


class TestSystemModule:
    """Basic module/API validation."""

    def test_module_imports(self):
        """automation.system should import successfully."""
        assert system is not None

    def test_module_has_docstring(self):
        """The module should have documentation."""
        assert system.__doc__
        assert "system" in system.__doc__.lower()

    def test_error_class_exists(self):
        """A module-specific system exception should exist."""
        error_type = _error_type()

        assert issubclass(error_type, Exception)

    def test_core_system_functions_exist(self):
        """
        Validate the expected AssistantX system automation API.

        The test accepts common professional naming variants for some
        operations because implementations may evolve.
        """
        expected_groups = {
            "shutdown": (
                "shutdown",
                "shutdown_system",
            ),
            "restart": (
                "restart",
                "restart_system",
            ),
            "sleep": (
                "sleep",
                "sleep_system",
            ),
            "lock": (
                "lock",
                "lock_system",
            ),
        }

        for operation, candidates in expected_groups.items():
            if not any(hasattr(system, name) for name in candidates):
                pytest.fail(
                    f"No API found for '{operation}'. "
                    f"Expected one of: {', '.join(candidates)}"
                )


# ============================================================================
# Power Operation Discovery
# ============================================================================


class TestPowerOperations:
    """Tests for shutdown, restart, sleep and lock operations."""

    @staticmethod
    def _find(*names):
        for name in names:
            value = getattr(system, name, None)
            if callable(value):
                return value

        pytest.fail(
            "None of the expected functions exist: "
            + ", ".join(names)
        )

    @patch("automation.system.subprocess.run")
    def test_shutdown_does_not_execute_real_command(
        self,
        mock_run,
    ):
        """Shutdown should use the mocked subprocess backend."""
        mock_run.return_value = Mock(returncode=0)

        function = self._find(
            "shutdown",
            "shutdown_system",
        )

        try:
            result = function()
        except TypeError:
            pytest.skip(
                "Shutdown function requires additional parameters."
            )

        assert mock_run.called
        assert result is not None

    @patch("automation.system.subprocess.run")
    def test_restart_does_not_execute_real_command(
        self,
        mock_run,
    ):
        """Restart should use the mocked subprocess backend."""
        mock_run.return_value = Mock(returncode=0)

        function = self._find(
            "restart",
            "restart_system",
        )

        try:
            result = function()
        except TypeError:
            pytest.skip(
                "Restart function requires additional parameters."
            )

        assert mock_run.called
        assert result is not None

    @patch("automation.system.subprocess.run")
    def test_sleep_does_not_execute_real_operation(
        self,
        mock_run,
    ):
        """Sleep should use the mocked system backend."""
        mock_run.return_value = Mock(returncode=0)

        function = self._find(
            "sleep",
            "sleep_system",
        )

        try:
            result = function()
        except TypeError:
            pytest.skip(
                "Sleep function requires additional parameters."
            )

        assert mock_run.called
        assert result is not None

    @patch("automation.system.subprocess.run")
    def test_lock_does_not_execute_real_operation(
        self,
        mock_run,
    ):
        """Lock should use the mocked system backend."""
        mock_run.return_value = Mock(returncode=0)

        function = self._find(
            "lock",
            "lock_system",
        )

        try:
            result = function()
        except TypeError:
            pytest.skip(
                "Lock function requires additional parameters."
            )

        assert mock_run.called
        assert result is not None


# ============================================================================
# Volume Tests
# ============================================================================


class TestVolumeControl:
    """Tests for system volume operations."""

    def _find_volume_function(self, *names):
        for name in names:
            value = getattr(system, name, None)

            if callable(value):
                return value

        return None

    def test_volume_api_exists(self):
        """At least one volume-control API should be exposed."""
        function = self._find_volume_function(
            "set_volume",
            "change_volume",
            "volume_up",
            "volume_down",
            "get_volume",
        )

        if function is None:
            pytest.skip(
                "Volume API is not implemented in this version."
            )

        assert callable(function)

    @patch("automation.system.subprocess.run")
    def test_set_volume_uses_backend(self, mock_run):
        """set_volume should not touch the real system in tests."""
        function = self._find_volume_function(
            "set_volume",
        )

        if function is None:
            pytest.skip("set_volume is not available.")

        mock_run.return_value = Mock(returncode=0)

        try:
            result = function(50)
        except TypeError:
            pytest.skip(
                "set_volume has a different signature."
            )

        assert mock_run.called or result is not None

    def test_set_volume_rejects_invalid_value(self):
        """Invalid volume values should be rejected."""
        function = self._find_volume_function(
            "set_volume",
        )

        if function is None:
            pytest.skip("set_volume is not available.")

        error_type = _error_type()

        invalid_values = (
            -1,
            101,
            1000,
        )

        for value in invalid_values:
            try:
                with pytest.raises(error_type):
                    function(value)
            except TypeError:
                pytest.skip(
                    "set_volume uses a different argument contract."
                )


# ============================================================================
# Brightness Tests
# ============================================================================


class TestBrightnessControl:
    """Tests for display brightness operations."""

    def _find(self, *names):
        for name in names:
            value = getattr(system, name, None)

            if callable(value):
                return value

        return None

    def test_brightness_api_exists(self):
        """Brightness API may be optional depending on platform."""
        function = self._find(
            "set_brightness",
            "change_brightness",
            "brightness_up",
            "brightness_down",
            "get_brightness",
        )

        if function is None:
            pytest.skip(
                "Brightness API is not implemented."
            )

        assert callable(function)

    def test_set_brightness_rejects_invalid_values(self):
        """Brightness should normally remain within 0-100."""
        function = self._find(
            "set_brightness",
        )

        if function is None:
            pytest.skip("set_brightness is not available.")

        error_type = _error_type()

        for value in (-1, 101, 500):
            try:
                with pytest.raises(error_type):
                    function(value)
            except TypeError:
                pytest.skip(
                    "set_brightness uses a different signature."
                )


# ============================================================================
# Generic System Command Tests
# ============================================================================


class TestSystemCommandExecution:
    """Tests for low-level system command execution."""

    def test_subprocess_module_available(self):
        """System module should have subprocess when command execution exists."""
        assert hasattr(system, "subprocess")

    @patch("automation.system.subprocess.run")
    def test_command_backend_failure(
        self,
        mock_run,
    ):
        """
        Backend failure should be converted into the module-specific
        exception rather than leaking raw RuntimeError.
        """
        mock_run.side_effect = RuntimeError(
            "Simulated command failure"
        )

        function = getattr(
            system,
            "shutdown",
            None,
        )

        if not callable(function):
            function = getattr(
                system,
                "restart",
                None,
            )

        if not callable(function):
            pytest.skip(
                "No power-operation function available."
            )

        error_type = _error_type()

        try:
            with pytest.raises(error_type):
                function()
        except TypeError:
            pytest.skip(
                "Function requires additional parameters."
            )

    @patch("automation.system.subprocess.run")
    def test_os_error_is_wrapped(
        self,
        mock_run,
    ):
        """OSError should be converted into a clean application error."""
        mock_run.side_effect = OSError(
            "Simulated operating-system failure"
        )

        function = getattr(system, "shutdown", None)

        if not callable(function):
            function = getattr(system, "restart", None)

        if not callable(function):
            pytest.skip(
                "No suitable system operation exists."
            )

        error_type = _error_type()

        try:
            with pytest.raises(error_type):
                function()
        except TypeError:
            pytest.skip(
                "Function requires additional parameters."
            )


# ============================================================================
# Platform Tests
# ============================================================================


class TestPlatformHandling:
    """Tests for platform-aware behavior."""

    def test_platform_information_is_available(self):
        """The module should expose or derive platform information."""
        platform_names = (
            "IS_WINDOWS",
            "IS_LINUX",
            "IS_MAC",
            "PLATFORM",
            "SYSTEM",
        )

        available = [
            name
            for name in platform_names
            if hasattr(system, name)
        ]

        # It is acceptable for the module to use platform module directly.
        if not available:
            assert hasattr(system, "platform") or hasattr(
                system,
                "sys",
            )

    def test_current_python_platform_is_supported(self):
        """The current test platform should be recognized by Python."""
        import sys

        assert sys.platform
        assert isinstance(sys.platform, str)
        assert sys.platform != ""


# ============================================================================
# Confirmation / Safety Tests
# ============================================================================


class TestSafety:
    """
    Safety-focused tests.

    These ensure the test suite itself cannot accidentally power off,
    restart, or lock the developer's machine.
    """

    @patch("automation.system.subprocess.run")
    def test_shutdown_is_mocked(
        self,
        mock_run,
    ):
        """Shutdown must remain mocked during the test."""
        mock_run.return_value = Mock(returncode=0)

        function = getattr(system, "shutdown", None)

        if not callable(function):
            function = getattr(system, "shutdown_system", None)

        if not callable(function):
            pytest.skip("Shutdown API is unavailable.")

        try:
            function()
        except TypeError:
            pytest.skip(
                "Shutdown requires explicit arguments."
            )

        assert mock_run.called

    @patch("automation.system.subprocess.run")
    def test_restart_is_mocked(
        self,
        mock_run,
    ):
        """Restart must remain mocked during the test."""
        mock_run.return_value = Mock(returncode=0)

        function = getattr(system, "restart", None)

        if not callable(function):
            function = getattr(system, "restart_system", None)

        if not callable(function):
            pytest.skip("Restart API is unavailable.")

        try:
            function()
        except TypeError:
            pytest.skip(
                "Restart requires explicit arguments."
            )

        assert mock_run.called


# ============================================================================
# API Stability Tests
# ============================================================================


class TestAPIStability:
    """Regression tests for AssistantX integration."""

    def test_exception_can_be_caught_as_exception(self):
        """System-specific errors must inherit from Exception."""
        error_type = _error_type()

        assert issubclass(error_type, Exception)

    def test_public_api_is_callable(self):
        """Every known public function should remain callable."""
        candidate_names = (
            "shutdown",
            "shutdown_system",
            "restart",
            "restart_system",
            "sleep",
            "sleep_system",
            "lock",
            "lock_system",
            "set_volume",
            "get_volume",
            "volume_up",
            "volume_down",
            "set_brightness",
            "get_brightness",
            "brightness_up",
            "brightness_down",
        )

        found = 0

        for name in candidate_names:
            if hasattr(system, name):
                value = getattr(system, name)

                assert callable(value), (
                    f"Public system symbol '{name}' "
                    "must be callable."
                )

                found += 1

        assert found >= 1


# ============================================================================
# Repeated Stability Tests
# ============================================================================


class TestStability:
    """Repeated mocked operations for basic stability."""

    @patch("automation.system.subprocess.run")
    def test_repeated_shutdown_calls(
        self,
        mock_run,
    ):
        """Repeated shutdown requests should remain deterministic."""
        mock_run.return_value = Mock(returncode=0)

        function = getattr(system, "shutdown", None)

        if not callable(function):
            function = getattr(system, "shutdown_system", None)

        if not callable(function):
            pytest.skip("Shutdown API unavailable.")

        successful_calls = 0

        for _ in range(5):
            try:
                function()
                successful_calls += 1
            except TypeError:
                break

        if successful_calls:
            assert mock_run.call_count == successful_calls

    @patch("automation.system.subprocess.run")
    def test_repeated_restart_calls(
        self,
        mock_run,
    ):
        """Repeated restart requests should remain deterministic."""
        mock_run.return_value = Mock(returncode=0)

        function = getattr(system, "restart", None)

        if not callable(function):
            function = getattr(system, "restart_system", None)

        if not callable(function):
            pytest.skip("Restart API unavailable.")

        successful_calls = 0

        for _ in range(5):
            try:
                function()
                successful_calls += 1
            except TypeError:
                break

        if successful_calls:
            assert mock_run.call_count == successful_calls


# ============================================================================
# Smoke Tests
# ============================================================================


class TestSystemSmoke:
    """High-level system automation smoke tests."""

    def test_system_module_is_ready(self):
        """Basic smoke test for AssistantX system automation."""
        assert system is not None
        assert hasattr(system, "__doc__")

    def test_system_error_contract(self):
        """Application code should be able to catch system errors."""
        error_type = _error_type()

        assert isinstance(
            error_type("test"),
            Exception,
        )

    @patch("automation.system.subprocess.run")
    def test_power_operation_smoke(
        self,
        mock_run,
    ):
        """At least one power operation should be executable under mock."""
        mock_run.return_value = Mock(returncode=0)

        functions = (
            getattr(system, "shutdown", None),
            getattr(system, "shutdown_system", None),
            getattr(system, "restart", None),
            getattr(system, "restart_system", None),
            getattr(system, "sleep", None),
            getattr(system, "sleep_system", None),
            getattr(system, "lock", None),
            getattr(system, "lock_system", None),
        )

        functions = [
            function
            for function in functions
            if callable(function)
        ]

        if not functions:
            pytest.fail(
                "No system power operation is available."
            )

        function = functions[0]

        try:
            result = function()
        except TypeError:
            pytest.skip(
                "Available system operation requires parameters."
            )

        assert result is not None
