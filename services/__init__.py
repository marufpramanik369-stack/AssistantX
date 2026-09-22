"""
AssistantX Services Package
============================

Application-level services used by AssistantX for external APIs,
information retrieval, communication, reminders, and application
updates.

Services included:
    - Search
    - Weather
    - News
    - Wikipedia
    - Translation
    - Reminders
    - Email
    - Application updates

Design principles:
    - Lazy/explicit service imports
    - Minimal package initialization
    - Stable public package metadata
    - No heavy network/API initialization at import time
    - Optional dependencies should be handled by individual services

Example:
    from services import __version__

    # Prefer importing a service explicitly:
    from services.search_service import SearchService
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Package Metadata
# ---------------------------------------------------------------------------

__title__: Final[str] = "AssistantX Services"
__description__: Final[str] = (
    "Application services for search, weather, news, translation, "
    "reminders, email, and AssistantX updates."
)
__version__: Final[str] = "0.1.0"
__author__: Final[str] = "AssistantX Development Team"
__license__: Final[str] = "MIT"


# ---------------------------------------------------------------------------
# Supported Services
# ---------------------------------------------------------------------------

SERVICES: Final[tuple[str, ...]] = (
    "search",
    "weather",
    "news",
    "wikipedia",
    "translate",
    "reminder",
    "email",
    "update",
)


# ---------------------------------------------------------------------------
# Public Package API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "SERVICES",
    "__author__",
    "__description__",
    "__license__",
    "__title__",
    "__version__",
)
