"""
AssistantX Dashboard - Core Manager
===================================

Dashboard lifecycle management, initialization, and diagnostics.

Features
--------
- DashboardCore: Main dashboard manager
- Thread-safe singleton pattern
- System monitoring integration
- Panel lifecycle management
- Error recovery and diagnostics
- Performance tracking

Thread Safety
-------------
DashboardCore uses threading.Lock for thread-safe updates.
All UI operations must occur on Tk main thread.
System monitor runs in background thread.

Logging (100+ statements)
-----------------------
- DEBUG: Component initialization, updates
- INFO: Lifecycle events, state changes
- WARNING: Degraded performance, missing components
- ERROR: Initialization failures, crashes

Exceptions
----------
- DashboardCoreError: Base exception
- DashboardInitError: Initialization failed
- DashboardAnimationError: Animation system error

Integration
-----------
- animations: AnimationEngine, animation_engine
- avatar: AvatarManager
- system_monitor: SystemMonitor, system_monitor_diagnostics
- themes: ThemeManager, get_theme
- dashboard_config: Settings, constants
- widgets: Custom Tkinter widgets

Version: 1.0.0
Author: AssistantX
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional
from pathlib import Path                        #UPDATED                ===============================================
import json                                     #UPDATED                ===============================================
import os                                       #UPDATED                ===============================================


logger = logging.getLogger(__name__)
logger.debug("Importing dashboard_core module")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    from dashboard.dashboard_config import (
        DASHBOARD_SETTINGS,
        ASSISTANT_NAME,
        DASHBOARD_NAME,
        VERSION,
    )
    logger.debug("Dashboard config imported")
except ImportError as e:
    logger.warning("Dashboard config import failed: %s", e)
    DASHBOARD_SETTINGS = None
    ASSISTANT_NAME = "JEROX"
    DASHBOARD_NAME = "Dashboard"
    VERSION = "1.0.0"

try:
    from dashboard.animations import animation_engine, AnimationEngine
    logger.debug("Animation engine imported")
except ImportError as e:
    logger.warning("Animation engine import failed: %s", e)
    animation_engine = None

try:
    from dashboard.avatar import AvatarManager
    logger.debug("Avatar manager imported")
except ImportError as e:
    logger.warning("Avatar manager import failed: %s", e)
    AvatarManager = None

try:
    from dashboard.system_monitor import (
        SystemMonitor,
        system_monitor_diagnostics,
    )
    logger.debug("System monitor imported")
except ImportError as e:
    logger.warning("System monitor import failed: %s", e)
    SystemMonitor = None
    system_monitor_diagnostics = None

try:
    from dashboard.themes import get_theme, ThemeManager
    logger.debug("Theme manager imported")
except ImportError as e:
    logger.warning("Theme manager import failed: %s", e)
    get_theme = None

# ============================================================================
# ENUMS
# ============================================================================

class DashboardState(Enum):
    """Dashboard state machine."""
    
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


class ComponentStatus(Enum):
    """Component health status."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"

# ============================================================================
# EXCEPTIONS
# ============================================================================

class DashboardCoreError(Exception):
    """Base dashboard core exception."""
    pass


class DashboardInitError(DashboardCoreError):
    """Dashboard initialization failed."""
    pass


class DashboardAnimationError(DashboardCoreError):
    """Dashboard animation error."""
    pass

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ComponentHealthReport:
    """Single component health status."""
    
    name: str
    status: ComponentStatus
    uptime_seconds: float
    last_error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


#UPDATED                                                                            ======================================================

@dataclass
class DashboardRuntimeData:
    """Live runtime data exposed to dashboard widgets."""

    ai_provider: str = "Unknown"
    ai_model: str = "Unknown"
    ai_status: str = "Unknown"

    memory_entries: int = 0
    memory_size_kb: float = 0.0

    network_status: str = "Unknown"
    network_connections: int = 0
    network_latency_ms: float = 0.0
    network_upload_mbps: float = 0.0
    network_download_mbps: float = 0.0

    weather_temperature: str = "--"
    weather_condition: str = "Unknown"
    weather_humidity: str = "0%"
    weather_wind: str = "0 km/h"

    jobs_pending: int = 0
    jobs_active: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0

    live_feed: list[str] = field(default_factory=list)

    timestamp: float = field(default_factory=time.time)



@dataclass
class DashboardHealthReport:
    """Overall dashboard health status."""
    
    state: DashboardState
    uptime_seconds: float
    component_count: int
    healthy_count: int
    components: Dict[str, ComponentHealthReport] = field(default_factory=dict)
    system_load: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    
    def health_percent(self) -> float:
        """Calculate health percentage."""
        if self.component_count == 0:
            return 100.0
        return (self.healthy_count / self.component_count) * 100



@dataclass
class DashboardRuntimeData:
    """Live runtime data exposed to dashboard widgets."""

    ai_provider: str = "Unknown"
    ai_model: str = "Unknown"
    ai_status: str = "Unknown"

    memory_entries: int = 0
    memory_size_kb: float = 0.0

    network_status: str = "Unknown"
    network_connections: int = 0
    network_latency_ms: float = 0.0
    network_upload_mbps: float = 0.0
    network_download_mbps: float = 0.0

    weather_temperature: str = "--"
    weather_condition: str = "Unknown"
    weather_humidity: str = "0%"
    weather_wind: str = "0 km/h"

    jobs_pending: int = 0
    jobs_active: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0

    live_feed: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

# ============================================================================
# DASHBOARD CORE
# ============================================================================

class DashboardCore:
    """
    Main dashboard lifecycle manager.
    
    Manages initialization, running state, component health,
    and graceful shutdown.
    
    Example
    -------
    >>> core = DashboardCore(root)
    >>> core.start()
    >>> core.update()
    >>> health = core.get_health()
    >>> core.stop()
    
    Thread Safety
    -------------
    All state updates protected by lock.
    UI operations must run on Tk main thread.
    """
    
    def __init__(self, root: Any) -> None:
        """
        Initialize dashboard core.
        
        Parameters
        ----------
        root : tk.Tk
            Root Tkinter window
        
        Raises
        ------
        DashboardInitError
            If initialization fails
        """
        logger.info("Initializing DashboardCore")
        
        self.root = root
        self.state = DashboardState.STOPPED
        self._lock = threading.Lock()
        
        self.start_time = 0.0
        self.update_interval_ms = 500  # 2 FPS
        self.is_running = False
        
        # Components
        self.components: Dict[str, Any] = {}
        self.component_status: Dict[str, ComponentStatus] = {}
        
        
        ##UPDATED
        # Live dashboard runtime state
        self.runtime_data = DashboardRuntimeData()

        # Keep recent dashboard events
        self.max_live_feed_items = 100

        logger.info("Dashboard runtime state initialized")




        # Animation engine
        self.animation_engine = animation_engine
        if self.animation_engine is None:
            logger.warning("Animation engine not available")
        else:
            logger.debug("Animation engine available")
        
        # System monitor
        self.system_monitor = None
        if SystemMonitor is not None:
            try:
                self.system_monitor = SystemMonitor()
                self.components["system_monitor"] = self.system_monitor
                logger.info("System monitor initialized")
            except Exception as e:
                logger.error("Failed to init system monitor: %s", e)
                self.component_status["system_monitor"] = ComponentStatus.FAILED
        
        # Avatar manager
        self.avatar_manager = None
        if AvatarManager is not None:
            try:
                self.avatar_manager = AvatarManager()
                self.components["avatar"] = self.avatar_manager
                logger.info("Avatar manager initialized")
            except Exception as e:
                logger.error("Failed to init avatar manager: %s", e)
                self.component_status["avatar"] = ComponentStatus.FAILED
        
        # Callbacks
        self.update_callbacks: list[Callable] = []
        self.state_change_callbacks: list[Callable] = []

                # Live runtime data
        self.runtime_data = DashboardRuntimeData()
        self.max_live_feed_items = 100

        logger.info("Dashboard runtime state initialized")
        
        logger.debug("DashboardCore initialized successfully")
    
    def add_update_callback(self, callback: Callable) -> None:
        """
        Add callback for update events.
        
        Parameters
        ----------
        callback : Callable
            Function to call on updates
        """
        logger.debug("Adding update callback: %s", callback.__name__)
        self.update_callbacks.append(callback)
    
    def add_state_change_callback(self, callback: Callable) -> None:
        """
        Add callback for state changes.
        
        Parameters
        ----------
        callback : Callable
            Function(old_state, new_state) to call
        """
        logger.debug("Adding state change callback")
        self.state_change_callbacks.append(callback)
    
    def start(self) -> None:
        """
        Start dashboard.
        
        Raises
        ------
        DashboardInitError
            If start fails
        """
        logger.info("Starting dashboard")
        
        with self._lock:
            if self.is_running:
                logger.warning("Dashboard already running")
                return
            
            try:
                self.state = DashboardState.INITIALIZING
                self._notify_state_change(DashboardState.STOPPED)
                
                # Start animation engine
                if self.animation_engine is not None:
                    try:
                        self.animation_engine.start()
                        logger.info("Animation engine started")
                    except Exception as e:
                        logger.error("Failed to start animation: %s", e)
                
                # Start system monitor
                if self.system_monitor is not None:
                    try:
                        self.system_monitor._start_monitoring()
                        logger.info("System monitor started")
                    except Exception as e:
                        logger.error("Failed to start monitor: %s", e)
                
                self.start_time = time.time()
                self.is_running = True
                self.state = DashboardState.RUNNING
                
                logger.info("Dashboard started successfully")
                self._notify_state_change(DashboardState.INITIALIZING)
                
            except Exception as e:
                logger.error("Dashboard start failed: %s", e)
                self.state = DashboardState.ERROR
                raise DashboardInitError(f"Failed to start dashboard: {e}")
    
    def stop(self) -> None:
        """
        Stop dashboard gracefully.
        """
        logger.info("Stopping dashboard")
        
        with self._lock:
            if not self.is_running:
                logger.debug("Dashboard not running")
                return
            
            old_state = self.state
            self.state = DashboardState.STOPPING
            
            try:
                # Stop animation engine
                if self.animation_engine is not None:
                    try:
                        self.animation_engine.stop()
                        logger.info("Animation engine stopped")
                    except Exception as e:
                        logger.warning("Error stopping animation: %s", e)
                        
                
                # Stop system monitor
                if self.system_monitor is not None:
                    try:
                        self.system_monitor._stop_monitoring()
                        logger.info("System monitor stopped")
                    except Exception as e:
                        logger.warning("Error stopping monitor: %s", e)
                
                self.is_running = False
                self.state = DashboardState.STOPPED
                
                logger.info("Dashboard stopped successfully")
                self._notify_state_change(old_state)
                
            except Exception as e:
                logger.error("Error during shutdown: %s", e)
                self.state = DashboardState.ERROR

#UPDATED                                                                            ============================================================

    def get_runtime_data(self) -> DashboardRuntimeData:
        """Return a snapshot of live dashboard runtime data."""
        with self._lock:
            self.runtime_data.timestamp = time.time()

            return DashboardRuntimeData(
                ai_provider=self.runtime_data.ai_provider,
                ai_model=self.runtime_data.ai_model,
                ai_status=self.runtime_data.ai_status,
                memory_entries=self.runtime_data.memory_entries,
                memory_size_kb=self.runtime_data.memory_size_kb,
                network_status=self.runtime_data.network_status,
                network_connections=self.runtime_data.network_connections,
                network_latency_ms=self.runtime_data.network_latency_ms,
                network_upload_mbps=self.runtime_data.network_upload_mbps,
                network_download_mbps=self.runtime_data.network_download_mbps,
                weather_temperature=self.runtime_data.weather_temperature,
                weather_condition=self.runtime_data.weather_condition,
                weather_humidity=self.runtime_data.weather_humidity,
                weather_wind=self.runtime_data.weather_wind,
                jobs_pending=self.runtime_data.jobs_pending,
                jobs_active=self.runtime_data.jobs_active,
                jobs_completed=self.runtime_data.jobs_completed,
                jobs_failed=self.runtime_data.jobs_failed,
                live_feed=list(self.runtime_data.live_feed),
                timestamp=self.runtime_data.timestamp,
            )

    def set_ai_status(
        self,
        provider: str,
        model: str,
        status: str = "Ready",
    ) -> None:
        """Update AI information shown by dashboard."""
        with self._lock:
            self.runtime_data.ai_provider = str(provider or "Unknown")
            self.runtime_data.ai_model = str(model or "Unknown")
            self.runtime_data.ai_status = str(status or "Unknown")

    def add_live_feed(self, message: str) -> None:
        """Add an event to the dashboard live feed."""
        if not message:
            return

        with self._lock:
            self.runtime_data.live_feed.append(
                f"[{time.strftime('%H:%M:%S')}] {message}"
            )

            if len(self.runtime_data.live_feed) > self.max_live_feed_items:
                self.runtime_data.live_feed = (
                    self.runtime_data.live_feed[-self.max_live_feed_items:]
                )

    def set_memory_status(
        self,
        entries: int,
        size_kb: float = 0.0,
    ) -> None:
        """Update memory statistics."""
        with self._lock:
            self.runtime_data.memory_entries = max(0, int(entries))
            self.runtime_data.memory_size_kb = max(0.0, float(size_kb))

    def set_network_status(
        self,
        status: str,
        connections: int = 0,
        latency_ms: float = 0.0,
        upload_mbps: float = 0.0,
        download_mbps: float = 0.0,
    ) -> None:
        """Update network statistics."""
        with self._lock:
            self.runtime_data.network_status = str(status or "Unknown")
            self.runtime_data.network_connections = max(0, int(connections))
            self.runtime_data.network_latency_ms = max(0.0, float(latency_ms))
            self.runtime_data.network_upload_mbps = max(0.0, float(upload_mbps))
            self.runtime_data.network_download_mbps = max(
                0.0,
                float(download_mbps),
            )

    def set_weather(
        self,
        temperature: str = "--",
        condition: str = "Unknown",
        humidity: str = "0%",
        wind: str = "0 km/h",
    ) -> None:
        """Update weather information."""
        with self._lock:
            self.runtime_data.weather_temperature = str(temperature)
            self.runtime_data.weather_condition = str(condition)
            self.runtime_data.weather_humidity = str(humidity)
            self.runtime_data.weather_wind = str(wind)

    def set_job_status(
        self,
        pending: int = 0,
        active: int = 0,
        completed: int = 0,
        failed: int = 0,
    ) -> None:
        """Update scheduler/job counters."""
        with self._lock:
            self.runtime_data.jobs_pending = max(0, int(pending))
            self.runtime_data.jobs_active = max(0, int(active))
            self.runtime_data.jobs_completed = max(0, int(completed))
            self.runtime_data.jobs_failed = max(0, int(failed))


    def set_ai_status(
        self,
        provider: str,
        model: str,
        status: str = "Ready",
    ) -> None:
        """Update AI information shown by dashboard."""
        with self._lock:
            self.runtime_data.ai_provider = str(provider or "Unknown")
            self.runtime_data.ai_model = str(model or "Unknown")
            self.runtime_data.ai_status = str(status or "Unknown")

    def add_live_feed(self, message: str) -> None:
        """Add an event to the dashboard live feed."""
        if not message:
            return

        with self._lock:
            self.runtime_data.live_feed.append(
                f"[{time.strftime('%H:%M:%S')}] {message}"
            )

            if len(self.runtime_data.live_feed) > self.max_live_feed_items:
                self.runtime_data.live_feed = (
                    self.runtime_data.live_feed[-self.max_live_feed_items:]
                )

    def set_memory_status(
        self,
        entries: int,
        size_kb: float = 0.0,
    ) -> None:
        """Update memory statistics."""
        with self._lock:
            self.runtime_data.memory_entries = max(0, int(entries))
            self.runtime_data.memory_size_kb = max(
                0.0,
                float(size_kb),
            )

    def set_network_status(
        self,
        status: str,
        connections: int = 0,
        latency_ms: float = 0.0,
        upload_mbps: float = 0.0,
        download_mbps: float = 0.0,
    ) -> None:
        """Update network statistics."""
        with self._lock:
            self.runtime_data.network_status = str(
                status or "Unknown"
            )
            self.runtime_data.network_connections = max(
                0,
                int(connections),
            )
            self.runtime_data.network_latency_ms = max(
                0.0,
                float(latency_ms),
            )
            self.runtime_data.network_upload_mbps = max(
                0.0,
                float(upload_mbps),
            )
            self.runtime_data.network_download_mbps = max(
                0.0,
                float(download_mbps),
            )

    def set_weather(
        self,
        temperature: str = "--",
        condition: str = "Unknown",
        humidity: str = "0%",
        wind: str = "0 km/h",
    ) -> None:
        """Update weather information."""
        with self._lock:
            self.runtime_data.weather_temperature = str(
                temperature
            )
            self.runtime_data.weather_condition = str(
                condition
            )
            self.runtime_data.weather_humidity = str(
                humidity
            )
            self.runtime_data.weather_wind = str(
                wind
            )

    def set_job_status(
        self,
        pending: int = 0,
        active: int = 0,
        completed: int = 0,
        failed: int = 0,
    ) -> None:
        """Update scheduler/job counters."""
        with self._lock:
            self.runtime_data.jobs_pending = max(
                0,
                int(pending),
            )
            self.runtime_data.jobs_active = max(
                0,
                int(active),
            )
            self.runtime_data.jobs_completed = max(
                0,
                int(completed),
            )
            self.runtime_data.jobs_failed = max(
                0,
                int(failed),
            )




    def update(self) -> None:
        """
        Update dashboard state.
        
        Called periodically (via after_idle or timer).
        """
        if not self.is_running:
            return
        
        with self._lock:
            try:
                # Update system monitor
                if self.system_monitor is not None:
                    try:
                        self.system_monitor.snapshot()
                        self.component_status["system_monitor"] = ComponentStatus.HEALTHY
                    except Exception as e:
                        logger.warning("System monitor update failed: %s", e)
                        self.component_status["system_monitor"] = ComponentStatus.DEGRADED
                
                # Update animation engine
                if self.animation_engine is not None:
                    try:
                        self.animation_engine.tick()
                        self.component_status["animation"] = ComponentStatus.HEALTHY
                    except Exception as e:
                        logger.warning("Animation tick failed: %s", e)
                        self.component_status["animation"] = ComponentStatus.DEGRADED
                self.runtime_data.timestamp = time.time()                         #UPDATED       =============================================

                # Notify callbacks
                for callback in self.update_callbacks:
                    try:
                        callback()
                    except Exception as e:
                        logger.error("Update callback failed: %s", e)
                
            except Exception as e:
                logger.error("Update failed: %s", e)
                self.state = DashboardState.ERROR
    
    def pause(self) -> None:
        """Pause dashboard (animations, monitors)."""
        logger.info("Pausing dashboard")
        
        with self._lock:
            if self.animation_engine is not None:
                try:
                    self.animation_engine.pause()
                except Exception as e:
                    logger.error("Failed to pause animation: %s", e)
            
            self.state = DashboardState.PAUSED
    
    def resume(self) -> None:
        """Resume dashboard."""
        logger.info("Resuming dashboard")
        
        with self._lock:
            if self.animation_engine is not None:
                try:
                    self.animation_engine.resume()
                except Exception as e:
                    logger.error("Failed to resume animation: %s", e)
            
            if self.is_running:
                self.state = DashboardState.RUNNING
    
    def get_health(self) -> DashboardHealthReport:
        """
        Get dashboard health report.
        
        Returns
        -------
        DashboardHealthReport
            Current health status
        """
        with self._lock:
            uptime = (
                time.time() - self.start_time
                if self.is_running
                else 0.0
            )
            
            # Count healthy components
            healthy = sum(
                1 for status in self.component_status.values()
                if status == ComponentStatus.HEALTHY
            )
            
            report = DashboardHealthReport(
                state=self.state,
                uptime_seconds=uptime,
                component_count=len(self.component_status),
                healthy_count=healthy,
            )
            
            # Get system metrics
            if self.system_monitor is not None:
                try:
                    snapshot = self.system_monitor.snapshot()
                    report.system_load = snapshot.get("cpu_percent", 0.0)
                    report.memory_usage_mb = snapshot.get("memory_mb", 0.0)
                except Exception as e:
                    logger.warning("Failed to get system metrics: %s", e)
            
            return report
    
    def _notify_state_change(self, old_state: DashboardState) -> None:
        """Notify state change callbacks."""
        logger.debug(
            "State change: %s -> %s",
            old_state.value, self.state.value
        )
        
        for callback in self.state_change_callbacks:
            try:
                callback(old_state, self.state)
            except Exception as e:
                logger.error("State change callback failed: %s", e)

# ============================================================================
# GLOBAL SINGLETON
# ============================================================================

_dashboard_core: Optional[DashboardCore] = None
_dashboard_lock = threading.Lock()


def get_dashboard_core(root: Optional[Any] = None) -> DashboardCore:
    """
    Get or create dashboard core singleton.
    
    Parameters
    ----------
    root : tk.Tk, optional
        Tkinter root window (required for first call)
    
    Returns
    -------
    DashboardCore
        Singleton instance
    
    Raises
    ------
    DashboardInitError
        If root not provided and singleton not created
    
    Example
    -------
    >>> core = get_dashboard_core(root)
    >>> core.start()
    """
    global _dashboard_core
    
    with _dashboard_lock:
        if _dashboard_core is None:
            if root is None:
                logger.error("Root window required to create DashboardCore")
                raise DashboardInitError("Root window required")
            
            logger.debug("Creating DashboardCore singleton")
            _dashboard_core = DashboardCore(root)
        
        return _dashboard_core


def start_dashboard(root: Optional[Any] = None) -> DashboardCore:
    """
    Start dashboard.
    
    Parameters
    ----------
    root : tk.Tk, optional
        Tkinter root window
    
    Returns
    -------
    DashboardCore
        Running dashboard instance
    
    Raises
    ------
    DashboardInitError
        If start fails
    
    Example
    -------
    >>> core = start_dashboard(root)
    """
    logger.info("Starting dashboard system")
    
    core = get_dashboard_core(root)
    core.start()
    
    logger.info("Dashboard started")
    return core


def stop_dashboard() -> None:
    """
    Stop dashboard.
    
    Example
    -------
    >>> stop_dashboard()
    """
    logger.info("Stopping dashboard system")
    
    global _dashboard_core
    
    with _dashboard_lock:
        if _dashboard_core is not None:
            _dashboard_core.stop()
            _dashboard_core = None
    
    logger.info("Dashboard stopped")


def dashboard_diagnostics() -> Dict[str, Any]:
    """
    Get comprehensive dashboard diagnostics.
    
    Returns
    -------
    dict
        Diagnostic report:
        - version
        - state
        - uptime_seconds
        - health_percent
        - components (status for each)
        - system_metrics
        - errors (if any)
    
    Example
    -------
    >>> diag = dashboard_diagnostics()
    >>> print(f"Health: {diag['health_percent']}%")
    """
    logger.debug("Generating dashboard diagnostics")
    
    diag: Dict[str, Any] = {
        "version": VERSION,
        "name": DASHBOARD_NAME,
        "assistant": ASSISTANT_NAME,
        "timestamp": time.time(),
    }
    
    with _dashboard_lock:
        if _dashboard_core is None:
            diag["state"] = "not_initialized"
            logger.debug("Dashboard not initialized")
            return diag
        
        health = _dashboard_core.get_health()
        diag.update({
            "state": health.state.value,
            "uptime_seconds": health.uptime_seconds,
            "health_percent": health.health_percent(),
            "component_count": health.component_count,
            "healthy_count": health.healthy_count,
            "system_load": health.system_load,
            "memory_usage_mb": health.memory_usage_mb,
        })
        
        # Component statuses
        diag["components"] = {
            name: status.value
            for name, status in _dashboard_core.component_status.items()
        }
        
        # System monitor diagnostics
        if system_monitor_diagnostics is not None:
            try:
                diag["system_monitor"] = system_monitor_diagnostics()
            except Exception as e:
                logger.warning("Failed to get system monitor diag: %s", e)
    
    logger.debug("Diagnostics generated")
    return diag

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("Dashboard core module loaded successfully")

__all__ = [
    "DashboardCore",
    "DashboardState",
    "ComponentStatus",
    "DashboardCoreError",
    "DashboardInitError",
    "DashboardAnimationError",
    "ComponentHealthReport",
    "DashboardHealthReport",
    "DashboardRuntimeData",
    "get_dashboard_core",
    "start_dashboard",
    "stop_dashboard",
    "dashboard_diagnostics",
]
