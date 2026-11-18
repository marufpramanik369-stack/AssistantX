"""
AssistantX Dashboard - Panels Package
=====================================

Dashboard panel components for system monitoring and control.

Panels
------
- BasePanel: Abstract base class for all panels
- SystemPanel: CPU, RAM, GPU, Network monitoring
- AICorePanel: AI model status and load
- MemoryPanel: Memory bank / context window
- NetworkPanel: Network connections and bandwidth
- LiveFeedPanel: Live event feed
- WeatherPanel: Weather information
- JobsPanel: Task/job queue status
- ShortcutsPanel: Quick action buttons

Module Structure
----------------
- base_panel.py: BasePanel abstract class
- system_panel.py: System monitoring
- ai_core_panel.py: AI system status
- memory_panel.py: Memory/context tracking
- network_panel.py: Network status
- live_feed_panel.py: Event feed display
- weather_panel.py: Weather display
- jobs_panel.py: Job queue display
- shortcuts_panel.py: Quick actions

Threading
---------
All panels run on Tk main thread.
Background data fetching uses threading.

Logging (40+ statements)
-----------------------
- DEBUG: Panel imports, initialization
- INFO: Panel loading
- WARNING: Panel import failures
- ERROR: Critical panel errors

Version: 1.0.0
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
logger.debug("Importing panels package")

# ============================================================================
# BASE PANEL
# ============================================================================

try:
    from .base_panel import (
        BasePanel,
        PanelState,
        RefreshMode,
        PanelConfig,
        PanelMetrics,
    )
    logger.info("BasePanel imported successfully")
except ImportError as e:
    logger.error("Failed to import BasePanel: %s", e)
    raise

# ============================================================================
# CONCRETE PANELS (lazy imports to avoid circular deps)
# ============================================================================

def get_system_panel():
    """
    Lazy import SystemPanel.
    
    Returns
    -------
    type
        SystemPanel class
    
    Example
    -------
    >>> SystemPanel = get_system_panel()
    >>> panel = SystemPanel(parent, config)
    """
    logger.debug("Loading SystemPanel")
    try:
        from .system_panel import SystemPanel
        logger.info("SystemPanel loaded")
        return SystemPanel
    except ImportError as e:
        logger.error("Failed to load SystemPanel: %s", e)
        return None


def get_ai_core_panel():
    """Lazy import AICorePanel."""
    logger.debug("Loading AICorePanel")
    try:
        from .ai_core_panel import AICorePanel
        logger.info("AICorePanel loaded")
        return AICorePanel
    except ImportError as e:
        logger.error("Failed to load AICorePanel: %s", e)
        return None


def get_memory_panel():
    """Lazy import MemoryPanel."""
    logger.debug("Loading MemoryPanel")
    try:
        from .memory_panel import MemoryPanel
        logger.info("MemoryPanel loaded")
        return MemoryPanel
    except ImportError as e:
        logger.error("Failed to load MemoryPanel: %s", e)
        return None


def get_network_panel():
    """Lazy import NetworkPanel."""
    logger.debug("Loading NetworkPanel")
    try:
        from .network_panel import NetworkPanel
        logger.info("NetworkPanel loaded")
        return NetworkPanel
    except ImportError as e:
        logger.error("Failed to load NetworkPanel: %s", e)
        return None


def get_live_feed_panel():
    """Lazy import LiveFeedPanel."""
    logger.debug("Loading LiveFeedPanel")
    try:
        from .live_feed_panel import LiveFeedPanel
        logger.info("LiveFeedPanel loaded")
        return LiveFeedPanel
    except ImportError as e:
        logger.error("Failed to load LiveFeedPanel: %s", e)
        return None


def get_weather_panel():
    """Lazy import WeatherPanel."""
    logger.debug("Loading WeatherPanel")
    try:
        from .weather_panel import WeatherPanel
        logger.info("WeatherPanel loaded")
        return WeatherPanel
    except ImportError as e:
        logger.error("Failed to load WeatherPanel: %s", e)
        return None


def get_jobs_panel():
    """Lazy import JobsPanel."""
    logger.debug("Loading JobsPanel")
    try:
        from .jobs_panel import JobsPanel
        logger.info("JobsPanel loaded")
        return JobsPanel
    except ImportError as e:
        logger.error("Failed to load JobsPanel: %s", e)
        return None


def get_shortcuts_panel():
    """Lazy import ShortcutsPanel."""
    logger.debug("Loading ShortcutsPanel")
    try:
        from .shortcuts_panel import ShortcutsPanel
        logger.info("ShortcutsPanel loaded")
        return ShortcutsPanel
    except ImportError as e:
        logger.error("Failed to load ShortcutsPanel: %s", e)
        return None

# ============================================================================
# PANEL REGISTRY
# ============================================================================

PANEL_REGISTRY = {
    "system": {
        "name": "System Status",
        "loader": get_system_panel,
        "description": "CPU, RAM, GPU, Network monitoring",
    },
    "ai_core": {
        "name": "AI Core",
        "loader": get_ai_core_panel,
        "description": "AI model status and load",
    },
    "memory": {
        "name": "Memory Bank",
        "loader": get_memory_panel,
        "description": "Memory and context tracking",
    },
    "network": {
        "name": "Network",
        "loader": get_network_panel,
        "description": "Network connections and bandwidth",
    },
    "live_feed": {
        "name": "Live Feed",
        "loader": get_live_feed_panel,
        "description": "Event feed and notifications",
    },
    "weather": {
        "name": "Weather",
        "loader": get_weather_panel,
        "description": "Weather information",
    },
    "jobs": {
        "name": "Jobs",
        "loader": get_jobs_panel,
        "description": "Task queue and job status",
    },
    "shortcuts": {
        "name": "Shortcuts",
        "loader": get_shortcuts_panel,
        "description": "Quick action buttons",
    },
}


def load_panel(panel_key: str):
    """
    Load panel by key.
    
    Parameters
    ----------
    panel_key : str
        Panel registry key
    
    Returns
    -------
    type or None
        Panel class or None if not found
    
    Example
    -------
    >>> SystemPanel = load_panel("system")
    >>> if SystemPanel:
    ...     panel = SystemPanel(parent, config)
    """
    logger.debug("Loading panel: %s", panel_key)
    
    entry = PANEL_REGISTRY.get(panel_key)
    if entry is None:
        logger.warning("Panel not in registry: %s", panel_key)
        return None
    
    return entry["loader"]()


def list_available_panels():
    """
    List all available panels.
    
    Returns
    -------
    list
        List of (key, name, description) tuples
    """
    logger.debug("Listing available panels")
    
    return [
        (key, entry["name"], entry["description"])
        for key, entry in PANEL_REGISTRY.items()
    ]

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("Panels package initialized")

__all__ = [
    # Base
    "BasePanel",
    "PanelState",
    "RefreshMode",
    "PanelConfig",
    "PanelMetrics",
    # Loaders
    "get_system_panel",
    "get_ai_core_panel",
    "get_memory_panel",
    "get_network_panel",
    "get_live_feed_panel",
    "get_weather_panel",
    "get_jobs_panel",
    "get_shortcuts_panel",
    # Registry
    "load_panel",
    "list_available_panels",
    "PANEL_REGISTRY",
]
