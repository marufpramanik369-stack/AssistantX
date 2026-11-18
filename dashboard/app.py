"""
AssistantX Dashboard - Main Application
=======================================

Main dashboard application controller.

Features
--------
- Tkinter window management
- Panel lifecycle management
- Command routing
- JEROX voice integration
- Configuration compatibility
- Error recovery
- Graceful shutdown
- Performance monitoring
- Runtime diagnostics
- Capability/support detection
- Incident handling

Thread Safety
-------------
All UI operations run on the Tk main thread.
Background work is delegated to existing AssistantX services.

Integration
-----------
- dashboard_core: DashboardCore lifecycle
- panels: Dashboard panel system
- voice: Existing JEROX speaker service
- core: AssistantX core services
- dashboard_config: Dashboard configuration

Version: 1.0.0
"""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing dashboard app module")

LOGGER = logging.getLogger("AssistantX.dashboard")


# ============================================================================
# DASHBOARD CORE
# ============================================================================

try:
    from dashboard.dashboard_core import (
        DashboardCore,
        get_dashboard_core,
        start_dashboard,
        stop_dashboard,
    )

    logger.debug("DashboardCore imported successfully")

except ImportError as exc:
    DashboardCore = None
    get_dashboard_core = None
    start_dashboard = None
    stop_dashboard = None

    logger.warning(
        "DashboardCore not available: %s",
        exc,
    )


# ============================================================================
# DASHBOARD TERMINAL
# ============================================================================

try:
    from dashboard.terminal import TerminalPanel

    logger.debug("TerminalPanel imported successfully")

except ImportError as exc:
    TerminalPanel = None

    logger.warning(
        "TerminalPanel not available: %s",
        exc,
    )


# ============================================================================
# DASHBOARD PANELS
# ============================================================================

try:
    from dashboard.panels import (
        load_panel,
        list_available_panels,
    )

    logger.debug(
        "Dashboard panel system imported successfully"
    )

except ImportError as exc:
    load_panel = None
    list_available_panels = None

    logger.warning(
        "Dashboard panel system not available: %s",
        exc,
    )


# ============================================================================
# DASHBOARD CONFIGURATION
# ============================================================================

try:
    from dashboard.dashboard_config import (
        APPLICATION_NAME,
        ASSISTANT_NAME,
        WINDOW_TITLE,
        VERSION,
        DEFAULT_WINDOW_WIDTH,
        DEFAULT_WINDOW_HEIGHT,
        MIN_WINDOW_WIDTH,
        MIN_WINDOW_HEIGHT,
    )

    logger.debug(
        "Dashboard configuration imported successfully"
    )

except ImportError as exc:
    APPLICATION_NAME = "AssistantX"
    ASSISTANT_NAME = "JEROX"
    WINDOW_TITLE = "AssistantX — JEROX"
    VERSION = "1.0.0"

    DEFAULT_WINDOW_WIDTH = 1440
    DEFAULT_WINDOW_HEIGHT = 900
    MIN_WINDOW_WIDTH = 1100
    MIN_WINDOW_HEIGHT = 700

    logger.warning(
        "Dashboard configuration fallback activated: %s",
        exc,
    )


# ============================================================================
# LEGACY CONFIG COMPATIBILITY
# ============================================================================

Config = None
bootstrap = None

try:
    import config as _config_package

    if hasattr(_config_package, "Config"):
        Config = getattr(
            _config_package,
            "Config",
        )

    if hasattr(_config_package, "bootstrap"):
        bootstrap = getattr(
            _config_package,
            "bootstrap",
        )

    if Config is not None:
        logger.debug(
            "Legacy Config API detected"
        )
    else:
        logger.debug(
            "Legacy Config API not present; "
            "dashboard uses dashboard_config directly"
        )

except Exception as exc:
    logger.debug(
        "Legacy config compatibility unavailable: %s",
        exc,
    )


# ============================================================================
# JEROX VOICE INTEGRATION
# ============================================================================

voice_speaker = None
Speaker = None

try:
    import voice as _voice

    for _name in (
        "global_speaker",
        "speaker",
        "voice_speaker",
        "tts",
    ):
        _candidate = getattr(
            _voice,
            _name,
            None,
        )

        if _candidate is not None:
            voice_speaker = _candidate
            break

    _speaker_class = getattr(
        _voice,
        "Speaker",
        None,
    )

    if _speaker_class is not None:
        Speaker = _speaker_class

    if voice_speaker is not None:
        logger.info(
            "JEROX voice speaker connected to dashboard"
        )

    elif Speaker is not None:
        logger.info(
            "JEROX Speaker class connected to dashboard"
        )

    else:
        logger.warning(
            "JEROX voice service is not exposed by voice package"
        )

except Exception as exc:
    logger.warning(
        "JEROX voice integration unavailable: %s",
        exc,
    )


# ============================================================================
# CORE SERVICES
# ============================================================================

memory_manager = None
event_bus = None
history_manager = None
command_router = None
scheduler = None

try:
    from core import (
        memory_manager,
        event_bus,
        history_manager,
        command_router,
        scheduler,
    )

    logger.debug(
        "AssistantX core services imported successfully"
    )

except ImportError as exc:
    logger.warning(
        "Core services not available: %s",
        exc,
    )


# ============================================================================
# ENUMS
# ============================================================================

class ApplicationState(Enum):
    """Dashboard application lifecycle state."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class DashboardConfig:
    """Runtime configuration for DashboardApplication."""

    width: int = DEFAULT_WINDOW_WIDTH
    height: int = DEFAULT_WINDOW_HEIGHT

    min_width: int = MIN_WINDOW_WIDTH
    min_height: int = MIN_WINDOW_HEIGHT

    theme: str = "dark"
    resizable: bool = True

    title: str = WINDOW_TITLE

    panels_enabled: Optional[list[str]] = None

    update_interval_ms: int = 500

    def __post_init__(self) -> None:
        """Normalize dashboard configuration."""

        if self.panels_enabled is None:
            self.panels_enabled = [
                "system",
                "ai_core",
                "memory",
                "network",
                "live_feed",
                "weather",
                "jobs",
                "shortcuts",
            ]

        self.width = max(
            int(self.width),
            self.min_width,
        )

        self.height = max(
            int(self.height),
            self.min_height,
        )

        self.update_interval_ms = max(
            int(self.update_interval_ms),
            100,
        )


@dataclass
class DashboardStats:
    """Dashboard runtime statistics."""

    start_time: float = 0.0
    uptime_seconds: float = 0.0

    panel_count: int = 0
    active_panels: int = 0

    fps: float = 0.0
    memory_mb: float = 0.0

    update_count: int = 0
    last_update_time: float = 0.0


# ============================================================================
# EXCEPTIONS
# ============================================================================

class DashboardError(Exception):
    """Base dashboard exception."""


class DashboardStartupError(DashboardError):
    """Dashboard startup failed."""


class DashboardShutdownError(DashboardError):
    """Dashboard shutdown failed."""


class DashboardStateError(DashboardError):
    """Invalid dashboard state transition."""


# ============================================================================
# DASHBOARD APPLICATION
# ============================================================================

class DashboardApplication:
    """
    Main AssistantX Dashboard controller.

    The dashboard is a UI layer over existing AssistantX services.
    It does not replace the core, brain, voice, or memory systems.
    """

    def __init__(
        self,
        config: Optional[DashboardConfig] = None,
    ) -> None:
        """Initialize DashboardApplication."""

        logger.info(
            "Initializing DashboardApplication"
        )

        self.config = config or DashboardConfig()

        self.state = ApplicationState.STOPPED
        self.running = False

        self._lock = threading.RLock()
        self._update_job: Optional[str] = None
        self._shutdown_requested = False

        # Diagnostic incident storage.
        self._diagnostic_incidents: list[dict[str, Any]] = []

        self.root = tk.Tk()

        self.root.title(
            self.config.title
        )

        self.root.geometry(
            f"{self.config.width}x{self.config.height}"
        )

        self.root.minsize(
            self.config.min_width,
            self.config.min_height,
        )

        self.root.resizable(
            self.config.resizable,
            self.config.resizable,
        )

        self.root.configure(
            bg="#0B1020"
        )

        self.main_frame = tk.Frame(
            self.root,
            bg="#0B1020",
            bd=0,
            highlightthickness=0,
        )

        self.main_frame.pack(
            fill="both",
            expand=True,
        )

        self.panels: Dict[str, Any] = {}
        self.panel_frames: Dict[str, tk.Frame] = {}

        # Grid placement state (used while building the panel area).
        self._grid_mode = False
        self._grid_cols = 4
        self._grid_row = 0
        self._grid_col = 0

        self.stats = DashboardStats()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        logger.info(
            "DashboardApplication initialized | "
            "Assistant=%s | Version=%s",
            ASSISTANT_NAME,
            VERSION,
        )

    # ========================================================================
    # VOICE
    # ========================================================================

    def speak(
        self,
        text: str,
        *,
        language: Optional[str] = None,
        interrupt: bool = False,
    ) -> bool:
        """
        Send text to the existing JEROX TTS service.

        The dashboard does not create a second TTS engine.
        """

        if not text:
            return False

        speaker = voice_speaker

        if speaker is None:
            logger.debug(
                "JEROX speaker is unavailable"
            )
            return False

        try:
            if hasattr(speaker, "speak"):
                try:
                    result = speaker.speak(
                        text,
                        language=language,
                        interrupt=interrupt,
                    )
                except TypeError:
                    result = speaker.speak(text)

                return (
                    True
                    if result is None
                    else bool(result)
                )

            if hasattr(speaker, "say"):
                result = speaker.say(text)

                return (
                    True
                    if result is None
                    else bool(result)
                )

            if hasattr(speaker, "enqueue"):
                speaker.enqueue(text)
                return True

            logger.warning(
                "JEROX speaker has no supported speech method"
            )

            return False

        except Exception as exc:
            self.handle_incident(
                "voice_failure",
                str(exc),
                severity="warning",
                source="voice",
                exception=exc,
            )

            return False

    # ========================================================================
    # PANELS
    # ========================================================================

    def _place_frame(
        self,
        frame: tk.Frame,
        *,
        span: bool = False,
    ) -> None:
        """Place a panel container frame in the dashboard grid."""

        if not self._grid_mode:
            frame.pack(
                fill="both",
                expand=True,
                padx=4,
                pady=4,
            )
            return

        cols = self._grid_cols

        if span:
            if self._grid_col:
                self._grid_row += 1
                self._grid_col = 0

            frame.grid(
                row=self._grid_row,
                column=0,
                columnspan=cols,
                sticky="nsew",
                padx=4,
                pady=4,
            )
            self._grid_row += 1
            return

        frame.grid(
            row=self._grid_row,
            column=self._grid_col,
            sticky="nsew",
            padx=4,
            pady=4,
        )

        self._grid_col += 1

        if self._grid_col >= cols:
            self._grid_col = 0
            self._grid_row += 1

    def add_panel(
        self,
        key: str,
        title: str,
    ) -> Optional[Any]:
        """Create and initialize a dashboard panel."""

        logger.info(
            "Adding panel: %s (%s)",
            key,
            title,
        )

        if load_panel is None:
            self.handle_incident(
                "panel_loader_unavailable",
                f"Panel loader unavailable: {key}",
                severity="warning",
                source="panels",
            )
            return None

        try:
            panel_class = load_panel(key)

            if panel_class is None:
                self.handle_incident(
                    "panel_not_found",
                    f"Panel class not found: {key}",
                    severity="warning",
                    source="panels",
                )
                return None

            frame = tk.Frame(
                self.main_frame,
                bg="#0B1020",
                bd=0,
                highlightthickness=0,
            )

            self._place_frame(frame)

            panel = panel_class(frame)

            # BasePanel is a tk.Frame that does not pack itself.
            # Without this line the panel stays 1x1 and invisible.
            panel.pack(
                fill="both",
                expand=True,
            )

            if hasattr(panel, "initialize"):
                panel.initialize()

            self.panels[key] = panel
            self.panel_frames[key] = frame

            self.stats.panel_count = len(
                self.panels
            )

            logger.info(
                "Panel added successfully: %s",
                key,
            )

            return panel

        except Exception as exc:
            self.handle_incident(
                "panel_startup_failure",
                f"Failed to add panel {key}: {exc}",
                severity="error",
                source="panels",
                exception=exc,
            )

            return None

    def add_terminal(self) -> Optional[Any]:
        """Add the dashboard terminal panel."""

        logger.info(
            "Adding terminal panel"
        )

        if TerminalPanel is None:
            self.handle_incident(
                "terminal_unavailable",
                "TerminalPanel is unavailable",
                severity="warning",
                source="terminal",
            )
            return None

        try:
            frame = tk.Frame(
                self.main_frame,
                bg="#0B1020",
                bd=0,
                highlightthickness=0,
            )

            self._place_frame(
                frame,
                span=True,
            )

            terminal = TerminalPanel(frame)

            terminal.pack(
                fill="both",
                expand=True,
            )

            if hasattr(terminal, "initialize"):
                terminal.initialize()

            self.panels["terminal"] = terminal
            self.panel_frames["terminal"] = frame

            self.stats.panel_count = len(
                self.panels
            )

            logger.info(
                "Terminal panel added successfully"
            )

            return terminal

        except Exception as exc:
            self.handle_incident(
                "terminal_startup_failure",
                f"Failed to add terminal: {exc}",
                severity="error",
                source="terminal",
                exception=exc,
            )

            return None

    # ========================================================================
    # START
    # ========================================================================


    def start(self) -> None:
        """Start the dashboard application."""

        with self._lock:
            if self.state in (
                ApplicationState.STARTING,
                ApplicationState.RUNNING,
            ):
                logger.debug(
                    "Dashboard already running"
                )
                return

            self.state = ApplicationState.STARTING
            self._shutdown_requested = False

        logger.info(
            "Starting DashboardApplication"
        )

        try:
            if start_dashboard is not None:
                try:
                    start_dashboard(self.root)

                    logger.info(
                        "Dashboard core started"
                    )

                except Exception as exc:
                    self.handle_incident(
                        "dashboard_core_start_failure",
                        str(exc),
                        severity="warning",
                        source="dashboard_core",
                        exception=exc,
                    )

            # Single-page layout (no scrolling):
            #   4 columns x 2 rows of panels, terminal across the bottom.
            self._grid_mode = True
            self._grid_row = 0
            self._grid_col = 0

            for column in range(self._grid_cols):
                self.main_frame.grid_columnconfigure(
                    column,
                    weight=1,
                    uniform="panels",
                )

            panel_rows = -(-len(self.config.panels_enabled or []) // self._grid_cols)

            # First row holds the tallest panels, so it gets a larger share.
            for row in range(panel_rows):
                self.main_frame.grid_rowconfigure(
                    row,
                    weight=5 if row == 0 else 3,
                )

            for panel_key in (
                self.config.panels_enabled or []
            ):
                title = (
                    panel_key
                    .replace("_", " ")
                    .upper()
                )

                self.add_panel(
                    panel_key,
                    title,
                )

            self.add_terminal()

            # Terminal row: smaller share of the height.
            self.main_frame.grid_rowconfigure(
                self._grid_row - 1,
                weight=2,
                minsize=170,
            )

            with self._lock:
                self.running = True
                self.state = ApplicationState.RUNNING

                self.stats.start_time = time.time()
                self.stats.last_update_time = time.time()

            logger.info(
                "DashboardApplication started successfully | "
                "panels=%d | voice=%s",
                len(self.panels),
                voice_speaker is not None,
            )

        except Exception as exc:
            with self._lock:
                self.running = False
                self.state = ApplicationState.ERROR

            self.handle_incident(
                "dashboard_startup_failure",
                str(exc),
                severity="critical",
                source="dashboard",
                exception=exc,
            )

            raise DashboardStartupError(
                f"Dashboard startup failed: {exc}"
            ) from exc


    # ========================================================================
    # STOP
    # ========================================================================

    def stop(self) -> None:
        """Stop the dashboard gracefully."""

        with self._lock:
            if self.state == ApplicationState.STOPPED:
                return

            self.state = ApplicationState.STOPPING
            self.running = False
            self._shutdown_requested = True

        logger.info(
            "Stopping DashboardApplication"
        )

        try:
            if self._update_job is not None:
                try:
                    self.root.after_cancel(
                        self._update_job
                    )
                except Exception:
                    pass

                self._update_job = None

            for key, panel in list(
                self.panels.items()
            ):
                try:
                    if hasattr(panel, "cleanup"):
                        panel.cleanup()

                    elif hasattr(panel, "stop"):
                        panel.stop()

                    logger.debug(
                        "Panel cleaned up: %s",
                        key,
                    )

                except Exception as exc:
                    self.handle_incident(
                        "panel_cleanup_failure",
                        f"{key}: {exc}",
                        severity="warning",
                        source="panels",
                        exception=exc,
                    )

            if stop_dashboard is not None:
                try:
                    stop_dashboard()

                    logger.info(
                        "Dashboard core stopped"
                    )

                except Exception as exc:
                    self.handle_incident(
                        "dashboard_core_stop_failure",
                        str(exc),
                        severity="warning",
                        source="dashboard_core",
                        exception=exc,
                    )

            with self._lock:
                self.state = ApplicationState.STOPPED
                self.running = False

            logger.info(
                "DashboardApplication stopped"
            )

        except Exception as exc:
            with self._lock:
                self.state = ApplicationState.ERROR
                self.running = False

            self.handle_incident(
                "dashboard_shutdown_failure",
                str(exc),
                severity="critical",
                source="dashboard",
                exception=exc,
            )

            raise DashboardShutdownError(
                f"Dashboard shutdown failed: {exc}"
            ) from exc

    # ========================================================================
    # UPDATE LOOP
    # ========================================================================

    def update(self) -> None:
        """Refresh dashboard panels periodically."""

        if not self.running:
            return

        try:
            active = 0

            for key, panel in list(
                self.panels.items()
            ):
                try:
                    if hasattr(panel, "refresh"):
                        panel.refresh()
                        active += 1

                    elif hasattr(panel, "update"):
                        panel.update()
                        active += 1

                except Exception as exc:
                    self.handle_incident(
                        "panel_refresh_failure",
                        f"{key}: {exc}",
                        severity="warning",
                        source="panels",
                        exception=exc,
                    )

            now = time.time()

            self.stats.active_panels = active
            self.stats.update_count += 1
            self.stats.last_update_time = now

            if self.stats.start_time:
                self.stats.uptime_seconds = (
                    now - self.stats.start_time
                )

            if self.running:
                self._update_job = self.root.after(
                    self.config.update_interval_ms,
                    self.update,
                )

        except Exception as exc:
            self.handle_incident(
                "dashboard_update_failure",
                str(exc),
                severity="error",
                source="dashboard",
                exception=exc,
            )

    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """
        Return a safe runtime health report.

        The diagnostic system must not become another failure point.
        Missing optional services are reported as unavailable.
        """

        try:
            with self._lock:
                now = time.time()

                start_time = getattr(
                    self.stats,
                    "start_time",
                    0.0,
                )

                uptime = 0.0

                if start_time:
                    try:
                        uptime = max(
                            0.0,
                            now - float(start_time),
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        uptime = 0.0

                state = getattr(
                    self.state,
                    "value",
                    str(self.state),
                )

                panels = self.panels

                supported = {
                    "tkinter": (
                        self.root is not None
                    ),
                    "dashboard_core": (
                        start_dashboard is not None
                    ),
                    "panel_loader": (
                        load_panel is not None
                    ),
                    "panel_registry": (
                        list_available_panels is not None
                    ),
                    "terminal": (
                        TerminalPanel is not None
                    ),
                    "voice_speaker": (
                        voice_speaker is not None
                    ),
                    "memory_manager": (
                        memory_manager is not None
                    ),
                    "event_bus": (
                        event_bus is not None
                    ),
                    "history_manager": (
                        history_manager is not None
                    ),
                    "command_router": (
                        command_router is not None
                    ),
                    "scheduler": (
                        scheduler is not None
                    ),
                }

                supported_count = sum(
                    1
                    for value in supported.values()
                    if value
                )

                unsupported_count = (
                    len(supported)
                    - supported_count
                )

                incidents = list(
                    self._diagnostic_incidents[-20:]
                )

                critical_incidents = sum(
                    1
                    for incident in incidents
                    if str(
                        incident.get(
                            "severity",
                            "",
                        )
                    ).lower()
                    in {
                        "critical",
                        "fatal",
                    }
                )

                error_incidents = sum(
                    1
                    for incident in incidents
                    if str(
                        incident.get(
                            "severity",
                            "",
                        )
                    ).lower()
                    in {
                        "error",
                        "high",
                    }
                )

                if critical_incidents > 0:
                    health = "failed"

                elif (
                    error_incidents > 0
                    or unsupported_count > 0
                ):
                    health = "degraded"

                elif not self.running:
                    health = "stopped"

                else:
                    health = "healthy"

                return {
                    "component": "dashboard.app",

                    "application": APPLICATION_NAME,
                    "assistant": ASSISTANT_NAME,
                    "version": VERSION,

                    "health": health,

                    "state": state,
                    "running": bool(
                        self.running
                    ),
                    "shutdown_requested": bool(
                        self._shutdown_requested
                    ),

                    "uptime_seconds": round(
                        uptime,
                        2,
                    ),

                    "performance": {
                        "update_count": (
                            self.stats.update_count
                        ),
                        "last_update_time": (
                            self.stats.last_update_time
                        ),
                        "active_panels": (
                            self.stats.active_panels
                        ),
                        "panel_count": len(
                            panels
                        ),
                        "fps": self.stats.fps,
                        "memory_mb": (
                            self.stats.memory_mb
                        ),
                    },

                    "supported": {
                        "available": supported,
                        "supported_count": (
                            supported_count
                        ),
                        "unsupported_count": (
                            unsupported_count
                        ),
                    },

                    "panels": {
                        "loaded": list(
                            panels.keys()
                        ),
                        "count": len(
                            panels
                        ),
                    },

                    "voice": {
                        "assistant": ASSISTANT_NAME,
                        "available": (
                            voice_speaker is not None
                        ),
                        "gender": "female",
                        "gender_locked": True,
                    },

                    "incident_handling": {
                        "enabled": True,
                        "incident_count": len(
                            self._diagnostic_incidents
                        ),
                        "critical_count": (
                            critical_incidents
                        ),
                        "error_count": (
                            error_incidents
                        ),
                        "recent_incidents": incidents,
                    },

                    "window": {
                        "width": (
                            self.config.width
                        ),
                        "height": (
                            self.config.height
                        ),
                        "min_width": (
                            self.config.min_width
                        ),
                        "min_height": (
                            self.config.min_height
                        ),
                        "resizable": (
                            self.config.resizable
                        ),
                    },
                }

        except Exception as exc:
            logger.error(
                "Dashboard diagnostics failed: %s",
                exc,
                exc_info=True,
            )

            return {
                "component": "dashboard.app",
                "application": APPLICATION_NAME,
                "assistant": ASSISTANT_NAME,
                "version": VERSION,
                "health": "failed",

                "supported": {
                    "available": {},
                    "supported_count": 0,
                    "unsupported_count": 0,
                },

                "incident_handling": {
                    "enabled": True,
                    "incident_count": 1,
                    "critical_count": 1,
                    "error_count": 0,
                    "recent_incidents": [
                        {
                            "type": (
                                "diagnostics_failure"
                            ),
                            "severity": "critical",
                            "source": "diagnostics",
                            "message": str(
                                exc
                            ),
                            "timestamp": time.time(),
                        }
                    ],
                },
            }

    # ========================================================================
    # INCIDENT HANDLING
    # ========================================================================

    def handle_incident(
        self,
        incident_type: str,
        message: str,
        *,
        severity: str = "error",
        source: str = "dashboard",
        exception: Optional[Exception] = None,
    ) -> dict[str, Any]:
        """
        Record a dashboard incident without crashing the application.

        Incidents are kept in a bounded in-memory history.
        """

        try:
            incident = {
                "type": str(
                    incident_type
                ),
                "severity": str(
                    severity
                ).lower(),
                "source": str(
                    source
                ),
                "message": str(
                    message
                ),
                "timestamp": time.time(),
            }

            if exception is not None:
                incident["exception"] = (
                    type(exception).__name__
                )

            with self._lock:
                self._diagnostic_incidents.append(
                    incident
                )

                self._diagnostic_incidents = (
                    self._diagnostic_incidents[-20:]
                )

            normalized_severity = str(
                severity
            ).lower()

            if normalized_severity in {
                "critical",
                "fatal",
            }:
                logger.critical(
                    "Dashboard incident [%s] %s: %s",
                    source,
                    incident_type,
                    message,
                )

            elif normalized_severity in {
                "error",
                "high",
            }:
                logger.error(
                    "Dashboard incident [%s] %s: %s",
                    source,
                    incident_type,
                    message,
                )

            elif normalized_severity in {
                "warning",
                "medium",
            }:
                logger.warning(
                    "Dashboard incident [%s] %s: %s",
                    source,
                    incident_type,
                    message,
                )

            else:
                logger.info(
                    "Dashboard incident [%s] %s: %s",
                    source,
                    incident_type,
                    message,
                )

            return incident

        except Exception as exc:
            logger.error(
                "Incident handling failed: %s",
                exc,
                exc_info=True,
            )

            return {
                "type": "incident_handler_failure",
                "severity": "critical",
                "source": "dashboard",
                "message": str(exc),
                "timestamp": time.time(),
            }

    def clear_incidents(self) -> None:
        """Clear recorded dashboard diagnostic incidents."""

        try:
            with self._lock:
                self._diagnostic_incidents.clear()

            logger.info(
                "Dashboard diagnostic incidents cleared"
            )

        except Exception as exc:
            logger.error(
                "Failed to clear dashboard incidents: %s",
                exc,
                exc_info=True,
            )

    # ========================================================================
    # RUN
    # ========================================================================

    def run(self) -> int:
        """Start dashboard and enter Tk event loop."""

        logger.info(
            "Running DashboardApplication"
        )

        try:
            self.start()

            self.update()

            self.root.mainloop()

            return 0

        except Exception as exc:
            self.handle_incident(
                "dashboard_runtime_failure",
                str(exc),
                severity="critical",
                source="dashboard",
                exception=exc,
            )

            logger.error(
                "Dashboard application error: %s",
                exc,
                exc_info=True,
            )

            return 1

        finally:
            try:
                self.stop()

            except Exception as exc:
                logger.error(
                    "Dashboard cleanup failed: %s",
                    exc,
                    exc_info=True,
                )

    # ========================================================================
    # CLOSE
    # ========================================================================

    def _on_close(self) -> None:
        """Handle Tk window close event."""

        logger.info(
            "Dashboard window close event"
        )

        try:
            self.stop()

        except Exception as exc:
            logger.error(
                "Error stopping dashboard: %s",
                exc,
                exc_info=True,
            )

        try:
            self.root.destroy()

        except Exception as exc:
            logger.debug(
                "Tk root destroy failed: %s",
                exc,
            )


# ============================================================================
# GLOBAL APPLICATION
# ============================================================================

_global_app: Optional[DashboardApplication] = None


def get_app() -> Optional[DashboardApplication]:
    """Return the global DashboardApplication instance."""

    return _global_app


def create_app(
    config: Optional[DashboardConfig] = None,
) -> DashboardApplication:
    """Create or return the global DashboardApplication."""

    global _global_app

    if _global_app is not None:
        logger.debug(
            "Global DashboardApplication already exists"
        )

        return _global_app

    logger.info(
        "Creating global DashboardApplication"
    )

    _global_app = DashboardApplication(
        config
    )

    logger.info(
        "Global DashboardApplication created"
    )

    return _global_app


def run() -> int:
    """Run the global dashboard application."""

    try:
        app = create_app()

        exit_code = app.run()

        logger.info(
            "Dashboard exited with code: %d",
            exit_code,
        )

        return exit_code

    except Exception as exc:
        logger.error(
            "Fatal dashboard error: %s",
            exc,
            exc_info=True,
        )

        return 1


def main() -> int:
    """
    Main entry point for dashboard application.

    Bootstrap sequence:
    1. Initialize core services
    2. Start dashboard
    3. Graceful shutdown
    """

    logger.info(
        "Dashboard main() called"
    )

    try:
        from core import (
            bootstrap_app,
            shutdown_app,
        )

        logger.info(
            "Bootstrapping AssistantX core"
        )

        bootstrap_app(
            log_level="INFO",
            start_scheduler=True,
        )

        logger.info(
            "Starting dashboard"
        )

        exit_code = run()

        logger.info(
            "Dashboard exited with code: %d",
            exit_code,
        )

        return exit_code

    except Exception as exc:
        logger.error(
            "Fatal error in main: %s",
            exc,
            exc_info=True,
        )

        return 1

    finally:
        logger.info(
            "Shutting down core"
        )

        try:
            from core import shutdown_app

            shutdown_app()

        except Exception as exc:
            logger.error(
                "Error during shutdown: %s",
                exc,
                exc_info=True,
            )



def main() -> int:
    try:
        from dashboard import neon_ui
        LOGGER.info("Launching NEON dashboard")
        return neon_ui.main()
    except Exception:
        LOGGER.exception("Neon dashboard failed - falling back to old dashboard")
 
    try:
        from dashboard import app_old
        return app_old.main()
    except Exception:
        LOGGER.exception("Old dashboard failed too")
        return 1
 
 
if __name__ == "__main__":
    raise SystemExit(main())
 


# ============================================================================
# MODULE-LEVEL DIAGNOSTICS
# ============================================================================

def diagnostics() -> dict[str, Any]:
    """
    Return diagnostics for the global dashboard application.

    If the global application has not been created yet, the dashboard is
    reported as not initialized instead of creating a Tk window implicitly.
    """

    try:
        app = get_app()

        if app is None:
            return {
                "component": "dashboard.app",
                "application": APPLICATION_NAME,
                "assistant": ASSISTANT_NAME,
                "version": VERSION,
                "health": "not_initialized",

                "supported": {
                    "available": {
                        "dashboard_core": (
                            start_dashboard is not None
                        ),
                        "panel_loader": (
                            load_panel is not None
                        ),
                        "panel_registry": (
                            list_available_panels is not None
                        ),
                        "terminal": (
                            TerminalPanel is not None
                        ),
                        "voice_speaker": (
                            voice_speaker is not None
                        ),
                    },
                },

                "incident_handling": {
                    "enabled": True,
                    "incident_count": 0,
                    "critical_count": 0,
                    "error_count": 0,
                    "recent_incidents": [],
                },
            }

        return app.diagnostics()

    except Exception as exc:
        logger.error(
            "Global dashboard diagnostics failed: %s",
            exc,
            exc_info=True,
        )

        return {
            "component": "dashboard.app",
            "application": APPLICATION_NAME,
            "assistant": ASSISTANT_NAME,
            "version": VERSION,
            "health": "failed",

            "incident_handling": {
                "enabled": True,
                "incident_count": 1,
                "critical_count": 1,
                "error_count": 0,
                "recent_incidents": [
                    {
                        "type": (
                            "global_diagnostics_failure"
                        ),
                        "severity": "critical",
                        "source": "dashboard.app",
                        "message": str(
                            exc
                        ),
                        "timestamp": time.time(),
                    }
                ],
            },
        }


# ============================================================================
# EXPORTS
# ============================================================================

logger.info(
    "Dashboard app module loaded successfully"
)


__all__ = [
    "ApplicationState",
    "DashboardApplication",
    "DashboardConfig",
    "DashboardError",
    "DashboardShutdownError",
    "DashboardStartupError",
    "DashboardStateError",
    "DashboardStats",
    "Speaker",
    "create_app",
    "diagnostics",
    "get_app",
    "main",
    "run",
    "voice_speaker",
]


# ============================================================================
# MODULE ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
