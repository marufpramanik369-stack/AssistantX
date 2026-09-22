"""
AssistantX Test Suite
======================

Automated test package for the AssistantX desktop AI assistant.

This package contains tests covering:

    - AI providers and conversation handling
    - Automation modules
    - Browser integration
    - Dashboard/UI components
    - Database and persistence
    - Memory management
    - External services
    - System automation
    - Voice functionality

Test modules:
    test_ai.py
    test_automation.py
    test_browser.py
    test_dashboard.py
    test_database.py
    test_memory.py
    test_services.py
    test_system.py
    test_voice.py

The test suite is designed to be executed with pytest.

Example:
    python -m pytest

Run with verbose output:
    python -m pytest -v

Run a specific module:
    python -m pytest tests/test_ai.py
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Package Metadata
# ---------------------------------------------------------------------------

__title__: Final[str] = "AssistantX Test Suite"
__description__: Final[str] = (
    "Automated tests for the AssistantX desktop AI assistant."
)
__version__: Final[str] = "0.1.0"
__author__: Final[str] = "AssistantX Development Team"


# ---------------------------------------------------------------------------
# Test Configuration
# ---------------------------------------------------------------------------

TEST_PACKAGE_NAME: Final[str] = "tests"

SUPPORTED_TEST_MODULES: Final[tuple[str, ...]] = (
    "test_ai",
    "test_automation",
    "test_browser",
    "test_dashboard",
    "test_database",
    "test_memory",
    "test_services",
    "test_system",
    "test_voice",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "SUPPORTED_TEST_MODULES",
    "TEST_PACKAGE_NAME",
    "__author__",
    "__description__",
    "__title__",
    "__version__",
)
