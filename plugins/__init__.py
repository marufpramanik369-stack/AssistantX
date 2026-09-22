"""
AssistantX Plugin System
========================

Central package for all AssistantX plugins.

Plugins are optional, modular extensions that add new capabilities
without modifying the AssistantX core application.

Possible plugin categories:
    - AI Providers
    - Web / Browser Tools
    - Automation
    - Productivity
    - External Services
    - Utility Tools

Recommended structure:

    plugins/
    ├── __init__.py
    ├── base.py
    ├── manager.py
    ├── registry.py
    │
    ├── gemini/
    │   ├── __init__.py
    │   └── plugin.py
    │
    ├── ollama/
    │   ├── __init__.py
    │   └── plugin.py
    │
    ├── browser/
    │   ├── __init__.py
    │   └── plugin.py
    │
    └── automation/
        ├── __init__.py
        └── plugin.py

Design principles:
    - Plugins must remain modular.
    - Core application logic should not depend directly on plugins.
    - Plugins should communicate through defined interfaces.
    - Optional plugins should fail gracefully.
    - Plugin discovery and lifecycle should be handled by the
      plugin manager/registry.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Package Metadata
# ---------------------------------------------------------------------------

__title__: Final[str] = "AssistantX Plugins"
__description__: Final[str] = (
    "Modular plugin system for the AssistantX desktop assistant."
)
__version__: Final[str] = "0.1.0"
__author__: Final[str] = "AssistantX Team"


# ---------------------------------------------------------------------------
# Public Package API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "__author__",
    "__description__",
    "__title__",
    "__version__",
)


# ---------------------------------------------------------------------------
# Compatibility Metadata
# ---------------------------------------------------------------------------

PLUGIN_API_VERSION: Final[str] = "1.0"
MIN_PYTHON_VERSION: Final[tuple[int, int]] = (3, 11)


# ---------------------------------------------------------------------------
# Package Helper
# ---------------------------------------------------------------------------

def get_plugin_api_version() -> str:
    """
    Return the current AssistantX plugin API version.

    This allows plugin implementations to verify compatibility with
    the currently installed AssistantX plugin system.

    Returns:
        str: Plugin API version.
    """
    return PLUGIN_API_VERSION
    