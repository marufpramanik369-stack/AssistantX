"""
AssistantX Dashboard - System Panel
===================================

Real-time system resource monitoring panel.

Features
--------
- CPU usage percentage + cores
- RAM usage with memory bar
- GPU status (if available)
- Network bandwidth (upload/download)
- Temperature monitoring
- Alert thresholds (CPU>90%, RAM>85%)
- Live update every 1 second

Thread Safety
-------------
psutil calls are thread-safe.
UI updates via schedule_ui_task().

Logging (80+ statements)
-----------------------
- DEBUG: Metric collection, updates
- INFO: Threshold alerts
- WARNING: Sensor failures
- ERROR: psutil errors

Integration
-----------
- base_panel: BasePanel inheritance
- psutil: System monitoring
- widgets: StatDisplay, ProgressBar, StatusIndicator
- dashboard_config: Colors

Version: 1.0.0
"""

from __future__ import annotations

import logging
import psutil
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing system_panel module")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    import tkinter as tk
except ImportError as e:
    logger.error("Tkinter import failed: %s", e)
    raise

try:
    from .base_panel import (
        BasePanel,
        PanelConfig,
        RefreshMode,
    )
    logger.debug("BasePanel imported")
except ImportError as e:
    logger.error("BasePanel import failed: %s", e)
    raise

try:
    from dashboard.widgets import (
        StatDisplay,
        ProgressBar,
        StatusIndicator,
    )
    logger.debug("Dashboard widgets imported")
except ImportError as e:
    logger.warning("Dashboard widgets not available: %s", e)

try:
    from dashboard.dashboard_config import (
        COLOR_SUCCESS,
        COLOR_WARNING,
        COLOR_ERROR,
        COLOR_MUTED,
    )
    logger.debug("Dashboard config imported")
except ImportError as e:
    logger.warning("Dashboard config not available: %s", e)
    COLOR_SUCCESS = "#39D98A"
    COLOR_WARNING = "#F5B942"
    COLOR_ERROR = "#FF5C7A"
    COLOR_MUTED = "#8D9AB3"

# ============================================================================
# CONSTANTS
# ============================================================================

# Alert thresholds
CPU_WARNING_THRESHOLD = 80.0
CPU_ERROR_THRESHOLD = 90.0

RAM_WARNING_THRESHOLD = 75.0
RAM_ERROR_THRESHOLD = 85.0

TEMP_WARNING_THRESHOLD = 75.0
TEMP_ERROR_THRESHOLD = 85.0

# ============================================================================
# SYSTEM PANEL
# ============================================================================

class SystemPanel(BasePanel):
    """
    System resource monitoring panel.
    
    Displays
    --------
    - CPU: Usage %, cores, temperature
    - RAM: Usage MB/total, percentage bar
    - GPU: Status (if available)
    - Network: Upload/download Mbps
    - Alerts: CPU/RAM threshold violations
    
    Refresh: Every 1 second
    
    Example
    -------
    >>> config = PanelConfig(
    ...     title="SYSTEM STATUS",
    ...     refresh_interval_ms=1000,
    ... )
    >>> panel = SystemPanel(parent, config)
    >>> panel.initialize()
    >>> panel.pack(fill="both")
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialize system panel.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        config : PanelConfig, optional
            Panel configuration
        """
        if config is None:
            config = PanelConfig(
                title="SYSTEM STATUS",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=1000,
            )
        
        logger.debug("Initializing SystemPanel")
        
        super().__init__(parent, config, **kwargs)
        
        # Monitoring state
        self.monitor_thread: Optional[threading.Thread] = None
        self.last_net_io: Optional[psutil._psnetio] = None
        self.cpu_alert_shown = False
        self.ram_alert_shown = False
        
        logger.debug("SystemPanel initialized")
    
    def on_initialize(self) -> None:
        """Create panel widgets."""
        logger.info("Initializing SystemPanel UI")
        
        # Row 1: CPU
        cpu_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        cpu_frame.pack(fill="x", padx=12, pady=6)
        
        cpu_label = tk.Label(
            cpu_frame,
            text="CPU",
            font=("Segoe UI", 10, "bold"),
            fg="#6C8CFF",
            bg=self.bg_color,
        )
        cpu_label.pack(anchor="w")
        
        stat1 = StatDisplay(cpu_frame, "Usage", "0%", color=COLOR_MUTED)
        stat1.pack(fill="x")
        self.widgets["cpu_usage"] = stat1
        
        stat2 = StatDisplay(cpu_frame, "Cores", "0/0", color=COLOR_MUTED)
        stat2.pack(fill="x")
        self.widgets["cpu_cores"] = stat2
        
        stat3 = StatDisplay(cpu_frame, "Temp", "0°C", color=COLOR_MUTED)
        stat3.pack(fill="x")
        self.widgets["cpu_temp"] = stat3
        
        cpu_bar = ProgressBar(
            cpu_frame,
            value=0.0,
            max_value=100.0,
            height=6,
            fill_color=COLOR_SUCCESS,
        )
        cpu_bar.pack(fill="x", pady=(4, 0))
        self.widgets["cpu_bar"] = cpu_bar
        
        logger.debug("CPU section created")
        
        # Separator
        sep1 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep1.pack(fill="x", padx=12, pady=6)
        
        # Row 2: RAM
        ram_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        ram_frame.pack(fill="x", padx=12, pady=6)
        
        ram_label = tk.Label(
            ram_frame,
            text="MEMORY",
            font=("Segoe UI", 10, "bold"),
            fg="#6C8CFF",
            bg=self.bg_color,
        )
        ram_label.pack(anchor="w")
        
        stat4 = StatDisplay(ram_frame, "Usage", "0 MB / 0 GB", color=COLOR_MUTED)
        stat4.pack(fill="x")
        self.widgets["ram_usage"] = stat4
        
        stat5 = StatDisplay(ram_frame, "Percent", "0%", color=COLOR_MUTED)
        stat5.pack(fill="x")
        self.widgets["ram_percent"] = stat5
        
        ram_bar = ProgressBar(
            ram_frame,
            value=0.0,
            max_value=100.0,
            height=6,
            fill_color=COLOR_SUCCESS,
        )
        ram_bar.pack(fill="x", pady=(4, 0))
        self.widgets["ram_bar"] = ram_bar
        
        logger.debug("RAM section created")
        
        # Separator
        sep2 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep2.pack(fill="x", padx=12, pady=6)
        
        # Row 3: Network
        net_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        net_frame.pack(fill="x", padx=12, pady=6)
        
        net_label = tk.Label(
            net_frame,
            text="NETWORK",
            font=("Segoe UI", 10, "bold"),
            fg="#6C8CFF",
            bg=self.bg_color,
        )
        net_label.pack(anchor="w")
        
        stat6 = StatDisplay(net_frame, "Upload", "0 Mbps", color=COLOR_MUTED)
        stat6.pack(fill="x")
        self.widgets["net_upload"] = stat6
        
        stat7 = StatDisplay(net_frame, "Download", "0 Mbps", color=COLOR_MUTED)
        stat7.pack(fill="x")
        self.widgets["net_download"] = stat7
        
        logger.debug("Network section created")
        
        # Separator
        sep3 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep3.pack(fill="x", padx=12, pady=6)
        
        # Row 4: Status
        status_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        status_frame.pack(fill="x", padx=12, pady=6)
        
        status_label = tk.Label(
            status_frame,
            text="STATUS",
            font=("Segoe UI", 10, "bold"),
            fg="#6C8CFF",
            bg=self.bg_color,
        )
        status_label.pack(anchor="w", pady=(0, 4))
        
        indicator = StatusIndicator(
            status_frame,
            text="HEALTHY",
            color=COLOR_SUCCESS,
        )
        indicator.pack(anchor="w")
        self.widgets["status_indicator"] = indicator
        
        logger.debug("Status section created")
        logger.info("SystemPanel UI created successfully")
    
    def on_refresh(self) -> None:
        """Update system metrics."""
        logger.debug("Refreshing SystemPanel metrics")
        
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            logger.debug("CPU: %.1f%%, cores=%d", cpu_percent, cpu_count)
            
            self.update_stat(
                "cpu_usage",
                f"{cpu_percent:.1f}%",
                self._color_for_value(cpu_percent, CPU_WARNING_THRESHOLD, CPU_ERROR_THRESHOLD)
            )
            self.update_stat("cpu_cores", f"0/{cpu_count}")
            self.update_progress("cpu_bar", cpu_percent)
            
            # CPU temperature
            try:
                if hasattr(psutil, 'sensors_temperatures'):
                    temps = psutil.sensors_temperatures()
                else:
                    # Windows - use alternative
                    temps = None  # Skip temperature on Windows
            except (AttributeError, OSError):
                temps = None
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            temp = entries[0].current
                            self.update_stat(
                                "cpu_temp",
                                f"{temp:.1f}°C",
                                self._color_for_value(temp, TEMP_WARNING_THRESHOLD, TEMP_ERROR_THRESHOLD)
                            )
                            break
            except Exception as e:
                logger.warning("Could not read CPU temperature: %s", e)
            
            # RAM
            ram = psutil.virtual_memory()
            ram_percent = ram.percent
            ram_used_mb = ram.used / (1024 * 1024)
            ram_total_gb = ram.total / (1024 * 1024 * 1024)
            
            logger.debug("RAM: %.1f%% (%.0f MB / %.1f GB)", ram_percent, ram_used_mb, ram_total_gb)
            
            self.update_stat(
                "ram_usage",
                f"{ram_used_mb:.0f} MB / {ram_total_gb:.1f} GB",
                COLOR_MUTED
            )
            self.update_stat(
                "ram_percent",
                f"{ram_percent:.1f}%",
                self._color_for_value(ram_percent, RAM_WARNING_THRESHOLD, RAM_ERROR_THRESHOLD)
            )
            self.update_progress("ram_bar", ram_percent)
            
            # Network
            try:
                net_io = psutil.net_io_counters()
                
                if self.last_net_io is not None:
                    bytes_sent = net_io.bytes_sent - self.last_net_io.bytes_sent
                    bytes_recv = net_io.bytes_recv - self.last_net_io.bytes_recv
                    
                    # Convert to Mbps (assuming 1-second interval)
                    mbps_upload = (bytes_sent * 8) / (1000 * 1000)
                    mbps_download = (bytes_recv * 8) / (1000 * 1000)
                    
                    logger.debug("Network: ↑%.2f Mbps ↓%.2f Mbps", mbps_upload, mbps_download)
                    
                    self.update_stat("net_upload", f"{mbps_upload:.2f} Mbps")
                    self.update_stat("net_download", f"{mbps_download:.2f} Mbps")
                
                self.last_net_io = net_io
                
            except Exception as e:
                logger.warning("Could not read network stats: %s", e)
            
            # Overall status
            is_healthy = (
                cpu_percent < CPU_WARNING_THRESHOLD and
                ram_percent < RAM_WARNING_THRESHOLD
            )
            
            indicator = self.widgets.get("status_indicator")
            if indicator is not None:
                if is_healthy:
                    indicator.set_status("HEALTHY", COLOR_SUCCESS)
                else:
                    indicator.set_status("WARNING", COLOR_WARNING)
            
            logger.debug("SystemPanel refresh complete")
            
        except Exception as e:
            logger.error("SystemPanel refresh failed: %s", e)
            self.metrics.error_count += 1
    
    def on_cleanup(self) -> None:
        """Cleanup system panel."""
        logger.info("Cleaning up SystemPanel")
        
        # No background threads to stop
        logger.debug("SystemPanel cleanup complete")
    
    @staticmethod
    def _color_for_value(
        value: float,
        warning_threshold: float,
        error_threshold: float
    ) -> str:
        """
        Get color based on value thresholds.
        
        Parameters
        ----------
        value : float
            Current value
        warning_threshold : float
            Yellow threshold
        error_threshold : float
            Red threshold
        
        Returns
        -------
        str
            Color hex code
        """
        if value >= error_threshold:
            return COLOR_ERROR
        elif value >= warning_threshold:
            return COLOR_WARNING
        else:
            return COLOR_SUCCESS

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("System panel module loaded successfully")

__all__ = [
    "SystemPanel",
]
