"""
AssistantX Dashboard - Base Panel
=================================

Abstract base class for all dashboard panels.

Features
--------
- BasePanel: Abstract panel class
- Panel lifecycle management
- Refresh scheduling
- Data binding
- Error handling
- Standard layout structure

Thread Safety
-------------
All panel updates must occur on Tk main thread.
Background data fetching is allowed via threading.

Logging (80+ statements)
-----------------------
- DEBUG: Panel initialization, updates, refreshes
- INFO: Panel state changes
- WARNING: Refresh delays, data fetch failures
- ERROR: Panel crashes, exception handling

Integration
-----------
- widgets: GlowingFrame, StatDisplay, DataPanel, etc.
- dashboard_config: Colors, settings
- dashboard_core: DashboardCore integration

Version: 1.0.0
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing base_panel module")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    import tkinter as tk
    logger.debug("Tkinter imported")
except ImportError as e:
    logger.error("Tkinter import failed: %s", e)
    raise

try:
    from dashboard.widgets import (
        GlowingFrame,
        DataPanel,
        StatDisplay,
        ProgressBar,
        StatusIndicator,
    )
    logger.debug("Dashboard widgets imported")
except ImportError as e:
    logger.warning("Dashboard widgets not available: %s", e)

try:
    from dashboard.dashboard_config import (
        COLOR_BG,
        COLOR_SURFACE,
        COLOR_TEXT,
        COLOR_ACCENT,
        COLOR_SUCCESS,
        COLOR_ERROR,
        COLOR_MUTED,
    )
    logger.debug("Dashboard config imported")
except ImportError as e:
    logger.warning("Dashboard config not available: %s", e)
    COLOR_BG = "#0B1020"
    COLOR_SURFACE = "#11182A"
    COLOR_TEXT = "#F4F7FB"
    COLOR_ACCENT = "#6C8CFF"
    COLOR_SUCCESS = "#39D98A"
    COLOR_ERROR = "#FF5C7A"
    COLOR_MUTED = "#8D9AB3"

# ============================================================================
# ENUMS
# ============================================================================

class PanelState(Enum):
    """Panel lifecycle state."""
    
    CREATED = "created"
    INITIALIZED = "initialized"
    VISIBLE = "visible"
    HIDDEN = "hidden"
    ERROR = "error"
    DESTROYED = "destroyed"


class RefreshMode(Enum):
    """Panel refresh strategy."""
    
    MANUAL = "manual"           # Only on explicit refresh()
    PERIODIC = "periodic"       # Every interval_ms
    ON_DEMAND = "on_demand"     # When data changes
    HYBRID = "hybrid"           # Periodic + on-demand

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PanelConfig:
    """Panel configuration."""
    
    title: str
    width: int = 300
    height: int = 400
    bg_color: str = COLOR_SURFACE
    border_color: str = COLOR_ACCENT
    refresh_mode: RefreshMode = RefreshMode.PERIODIC
    refresh_interval_ms: int = 1000
    scroll_enabled: bool = False
    collapsible: bool = False


@dataclass
class PanelMetrics:
    """Panel performance metrics."""
    
    refresh_count: int = 0
    last_refresh_time: float = 0.0
    avg_refresh_ms: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None
    uptime_seconds: float = 0.0

# ============================================================================
# BASE PANEL
# ============================================================================

class BasePanel(ABC, tk.Frame):
    """
    Abstract base class for dashboard panels.
    
    All panels must inherit from this and implement:
    - on_initialize()
    - on_refresh()
    - on_cleanup()
    
    Features
    --------
    - Automatic lifecycle management
    - Periodic refresh scheduling
    - Error recovery
    - Data binding support
    - Performance metrics
    
    Example
    -------
    >>> class SystemPanel(BasePanel):
    ...     async def on_refresh(self):
    ...         cpu = await get_cpu_usage()
    ...         self.update_stat("cpu", f"{cpu}%")
    
    Thread Safety
    -------------
    - UI updates must be called from Tk main thread
    - Use schedule_ui_task() for background->UI transfers
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        config: PanelConfig,
        **kwargs: Any
    ) -> None:
        """
        Initialize base panel.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        config : PanelConfig
            Panel configuration
        """
        logger.debug(
            "Initializing BasePanel: title=%s, refresh=%s",
            config.title, config.refresh_mode.value
        )
        
        super().__init__(
            parent,
            bg=config.bg_color,
            bd=0,
            **kwargs
        )
        
        # Configuration
        self.config_data = config
        self.title = config.title
        self.bg_color = config.bg_color
        self.border_color = config.border_color
        
        # State
        self.state = PanelState.CREATED
        self._lock = threading.Lock()
        self.is_visible = True
        self.is_destroyed = False
        
        # Timing
        self.creation_time = time.time()
        self.start_time = 0.0
        self.last_refresh_time = 0.0
        
        # Refresh management
        self.refresh_mode = config.refresh_mode
        self.refresh_interval_ms = config.refresh_interval_ms
        self._refresh_job: Optional[str] = None
        self._refresh_thread: Optional[threading.Thread] = None
        
        # Widgets & data
        self.widgets: Dict[str, tk.Widget] = {}
        self.data: Dict[str, Any] = {}
        self.update_callbacks: list[Callable] = []
        
        # Metrics
        self.metrics = PanelMetrics()
        
        # Create main frame with border
        self.main_frame = GlowingFrame(
            self,
            glow_color=self.border_color,
        )
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Title bar
        self._create_title_bar()
        
        # Content frame
        self.content_frame = tk.Frame(
            self.main_frame,
            bg=config.bg_color,
        )
        self.content_frame.pack(fill="both", expand=True)
        
        logger.debug("BasePanel created: %s", config.title)
    
    def _create_title_bar(self) -> None:
        """Create panel title bar."""
        logger.debug("Creating title bar for %s", self.title)
        
        title_frame = tk.Frame(
            self.main_frame,
            bg=COLOR_SURFACE,
            height=32,
        )
        title_frame.pack(fill="x", padx=1, pady=1)
        title_frame.pack_propagate(False)
        
        # Title label
        title_label = tk.Label(
            title_frame,
            text=self.title,
            font=("Segoe UI", 11, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_SURFACE,
        )
        title_label.pack(side="left", padx=12, pady=6)
        
        self.widgets["title"] = title_label
    
    def initialize(self) -> None:
        """
        Initialize panel (call after UI construction).
        
        Calls on_initialize() and starts refresh schedule.
        """
        logger.info("Initializing panel: %s", self.title)
        
        with self._lock:
            try:
                self.state = PanelState.INITIALIZED
                self.start_time = time.time()
                
                # Call subclass initialization
                self.on_initialize()
                
                # Start refresh scheduler
                self._schedule_refresh()
                
                logger.info("Panel initialized: %s", self.title)
                
            except Exception as e:
                logger.error("Panel initialization failed: %s", e)
                self.state = PanelState.ERROR
                self.metrics.last_error = str(e)
    
    def refresh(self) -> None:
        """
        Refresh panel data immediately.
        
        Calls on_refresh() and updates metrics.
        """
        if self.is_destroyed:
            logger.debug("Panel destroyed, skipping refresh")
            return
        
        logger.debug("Refreshing panel: %s", self.title)
        
        with self._lock:
            refresh_start = time.time()
            
            try:
                self.on_refresh()
                
                # Update metrics
                refresh_time = (time.time() - refresh_start) * 1000  # ms
                self.metrics.refresh_count += 1
                self.metrics.last_refresh_time = refresh_time
                
                # Running average
                if self.metrics.avg_refresh_ms == 0.0:
                    self.metrics.avg_refresh_ms = refresh_time
                else:
                    alpha = 0.3  # Exponential smoothing
                    self.metrics.avg_refresh_ms = (
                        alpha * refresh_time +
                        (1 - alpha) * self.metrics.avg_refresh_ms
                    )
                
                self.last_refresh_time = time.time()
                
                logger.debug(
                    "Panel refreshed: %s (%.1fms)",
                    self.title, refresh_time
                )
                
            except Exception as e:
                logger.error("Panel refresh failed (%s): %s", self.title, e)
                self.metrics.error_count += 1
                self.metrics.last_error = str(e)
                self.state = PanelState.ERROR
            
            # Reschedule if periodic
            if self.refresh_mode in (
                RefreshMode.PERIODIC,
                RefreshMode.HYBRID,
            ):
                self._schedule_refresh()
    
    def _schedule_refresh(self) -> None:
        """Schedule next refresh based on mode."""
        if not self.is_visible or self.is_destroyed:
            return
        
        if self.refresh_mode == RefreshMode.MANUAL:
            logger.debug("Manual refresh mode, no scheduling")
            return
        
        # Cancel previous job
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except Exception as e:
                logger.debug("Error canceling previous job: %s", e)
        
        # Schedule next
        logger.debug(
            "Scheduling refresh: %s (interval=%dms)",
            self.title, self.refresh_interval_ms
        )
        
        self._refresh_job = self.after(
            self.refresh_interval_ms,
            self.refresh
        )
    
    def schedule_ui_task(
        self,
        task: Callable[[], None],
        delay_ms: int = 0
    ) -> None:
        """
        Schedule task on UI thread.
        
        Safe way to update UI from background thread.
        
        Parameters
        ----------
        task : Callable
            Function to call on UI thread
        delay_ms : int
            Delay in milliseconds
        
        Example
        -------
        >>> def update_cpu():
        ...     self.update_stat("cpu", "45%")
        >>> self.schedule_ui_task(update_cpu)
        """
        logger.debug("Scheduling UI task: %s", task.__name__)
        
        self.after(delay_ms, task)
    
    def update_stat(
        self,
        stat_name: str,
        value: str,
        color: Optional[str] = None
    ) -> None:
        """
        Update a stat display.
        
        Parameters
        ----------
        stat_name : str
            Stat widget key
        value : str
            New value
        color : str, optional
            New color (keeps current if None)
        
        Example
        -------
        >>> self.update_stat("cpu", "45%", COLOR_SUCCESS)
        """
        logger.debug("Updating stat: %s = %s", stat_name, value)
        
        widget = self.widgets.get(stat_name)
        if widget is None:
            logger.warning("Stat widget not found: %s", stat_name)
            return
        
        if isinstance(widget, StatDisplay):
            widget.update_value(value, color)
        else:
            logger.warning("Widget is not StatDisplay: %s", stat_name)
    
    def update_progress(
        self,
        bar_name: str,
        value: float
    ) -> None:
        """
        Update a progress bar.
        
        Parameters
        ----------
        bar_name : str
            Progress bar widget key
        value : float
            New value (0-max)
        
        Example
        -------
        >>> self.update_progress("cpu_bar", 45.5)
        """
        logger.debug("Updating progress: %s = %.1f", bar_name, value)
        
        widget = self.widgets.get(bar_name)
        if widget is None:
            logger.warning("Progress bar not found: %s", bar_name)
            return
        
        if isinstance(widget, ProgressBar):
            widget.set_value(value)
        else:
            logger.warning("Widget is not ProgressBar: %s", bar_name)
    
    def set_data(self, key: str, value: Any) -> None:
        """
        Set panel data value.
        
        Parameters
        ----------
        key : str
            Data key
        value : Any
            Data value
        """
        self.data[key] = value
    
    def get_data(self, key: str, default: Any = None) -> Any:
        """
        Get panel data value.
        
        Parameters
        ----------
        key : str
            Data key
        default : Any
            Default if not found
        
        Returns
        -------
        Any
            Data value or default
        """
        return self.data.get(key, default)
    
    def hide(self) -> None:
        """Hide panel."""
        logger.info("Hiding panel: %s", self.title)
        self.is_visible = False
        self.pack_forget()
        self.state = PanelState.HIDDEN
    
    def show(self) -> None:
        """Show panel."""
        logger.info("Showing panel: %s", self.title)
        self.is_visible = True
        self.pack(fill="both", expand=True)
        self.state = PanelState.VISIBLE
    
    def cleanup(self) -> None:
        """
        Cleanup panel (call before destroy).
        
        Calls on_cleanup() and cancels refresh jobs.
        """
        logger.info("Cleaning up panel: %s", self.title)
        
        with self._lock:
            if self.is_destroyed:
                logger.debug("Panel already destroyed")
                return
            
            # Cancel refresh job
            if self._refresh_job is not None:
                try:
                    self.after_cancel(self._refresh_job)
                    logger.debug("Refresh job cancelled")
                except Exception as e:
                    logger.debug("Error canceling refresh: %s", e)
            
            # Call subclass cleanup
            try:
                self.on_cleanup()
            except Exception as e:
                logger.error("Cleanup error: %s", e)
            
            self.is_destroyed = True
            self.state = PanelState.DESTROYED
            
            logger.info("Panel cleaned up: %s", self.title)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get panel performance metrics.
        
        Returns
        -------
        dict
            Metrics:
            - refresh_count
            - avg_refresh_ms
            - error_count
            - uptime_seconds
        """
        uptime = time.time() - self.creation_time
        
        return {
            "title": self.title,
            "state": self.state.value,
            "refresh_count": self.metrics.refresh_count,
            "avg_refresh_ms": self.metrics.avg_refresh_ms,
            "error_count": self.metrics.error_count,
            "uptime_seconds": uptime,
            "last_error": self.metrics.last_error,
        }
    
    # ========================================================================
    # ABSTRACT METHODS (implement in subclasses)
    # ========================================================================
    
    @abstractmethod
    def on_initialize(self) -> None:
        """
        Initialize panel UI.
        
        Called once when panel is initialized.
        Create all widgets here.
        
        Example
        -------
        >>> def on_initialize(self):
        ...     stat = StatDisplay(self.content_frame, "CPU", "0%")
        ...     stat.pack(fill="x")
        ...     self.widgets["cpu"] = stat
        """
        pass
    
    @abstractmethod
    def on_refresh(self) -> None:
        """
        Refresh panel data.
        
        Called periodically (interval_ms).
        Update widget values here.
        
        Example
        -------
        >>> def on_refresh(self):
        ...     cpu = psutil.cpu_percent()
        ...     self.update_stat("cpu", f"{cpu}%")
        """
        pass
    
    @abstractmethod
    def on_cleanup(self) -> None:
        """
        Cleanup panel resources.
        
        Called when panel is destroyed.
        Stop threads, close files, etc.
        
        Example
        -------
        >>> def on_cleanup(self):
        ...     self.monitor.stop()
        """
        pass

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("Base panel module loaded successfully")

__all__ = [
    "BasePanel",
    "PanelState",
    "RefreshMode",
    "PanelConfig",
    "PanelMetrics",
]
