"""
AssistantX Dashboard Package
============================

Professional graphical application layer for AssistantX.

This module provides the complete GUI foundation:
- DashboardApplication: Main application controller
- Panel system: Modular dashboard sections
- Animation engine: Renderer-independent animation
- Avatar system: JEROX avatar display
- System monitoring: Real-time metrics

Entry Points
------------
    from dashboard import DashboardApplication, create_app, run, get_app

    app = create_app()
    app.run()

Thread Safety
-------------
- RLock on application state
- Safe imports from existing AssistantX modules
- Graceful lifecycle management

Logging (150+ statements)
-------------------------
- DEBUG: Module loads, initialization steps
- INFO: Application lifecycle events
- WARNING: Configuration issues, fallbacks
- ERROR: Critical failures

Integration
-----------
Compatible with:
- core/: Logger, EventBus, Memory, History, Scheduler
- config/: Config, Theme, Settings
- voice/: Speaker (JEROX TTS)
- services/: All external services
- automation/: All automation modules
- database/: Data persistence

Version: 1.0.0
Author: AssistantX Team
License: Same as AssistantX
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
logger.debug("Initializing dashboard package")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    logger.debug("Importing DashboardApplication from app")
    from dashboard.app import (
        ApplicationState,
        DashboardApplication,
        DashboardConfig,
        DashboardError,
        DashboardShutdownError,
        DashboardStartupError,
        DashboardStateError,
        DashboardStats,
        create_app,
        get_app,
        main,
        run,
    )
    logger.info("DashboardApplication imported successfully")
except ImportError as e:
    logger.exception("Failed to import DashboardApplication: %s", e)
    raise

try:
    logger.debug("Importing dashboard config")
    from dashboard.dashboard_config import (
        ASSISTANT_NAME,
        DASHBOARD_NAME,
        DASHBOARD_SETTINGS,
        VERSION,
    )
    logger.info("Dashboard config imported successfully")
except ImportError as e:
    logger.exception("Failed to import dashboard config: %s", e)
    raise

try:
    logger.debug("Importing panels")
    from dashboard import panels
    logger.info("Panels package imported successfully")
except ImportError as e:
    logger.warning("Panels package import failed: %s", e)
    panels = None

try:
    logger.debug("Importing avatar manager")
    from dashboard.avatar import AvatarManager
    logger.info("AvatarManager imported successfully")
except ImportError as e:
    logger.warning("AvatarManager import failed: %s", e)
    AvatarManager = None

try:
    logger.debug("Importing system monitor")
    from dashboard.system_monitor import SystemMonitor
    logger.info("SystemMonitor imported successfully")
except ImportError as e:
    logger.warning("SystemMonitor import failed: %s", e)
    SystemMonitor = None

try:
    logger.debug("Importing animation engine")
    from dashboard.animations import AnimationEngine
    logger.info("AnimationEngine imported successfully")
except ImportError as e:
    logger.warning("AnimationEngine import failed: %s", e)
    AnimationEngine = None

logger.info("Dashboard package initialized successfully")

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Application
    "ApplicationState",
    "DashboardApplication",
    "DashboardConfig",
    "DashboardStats",
    
    # Exceptions
    "DashboardError",
    "DashboardStartupError",
    "DashboardShutdownError",
    "DashboardStateError",
    
    # Functions
    "create_app",
    "get_app",
    "run",
    "main",
    
    # Configuration
    "ASSISTANT_NAME",
    "DASHBOARD_NAME",
    "DASHBOARD_SETTINGS",
    "VERSION",
    
    # Components
    "panels",
    "AvatarManager",
    "SystemMonitor",
    "AnimationEngine",
]
