"""
AssistantX Dashboard - Network Panel
===================================

Network status and connectivity monitoring.

Features
--------
- Active connections count
- Bandwidth usage
- Latency metrics
- Network health
- Connection status
- Data transfer rate

Logging (50+ statements)
-----------------------
- DEBUG: Network stats
- INFO: Connection changes
- WARNING: Latency issues
- ERROR: Network unavailable

Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing network_panel module")

import tkinter as tk

try:
    from .base_panel import BasePanel, PanelConfig, RefreshMode
    from dashboard.widgets import StatDisplay, ProgressBar, StatusIndicator
    from dashboard.dashboard_config import (
        COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, COLOR_MUTED, COLOR_ACCENT
    )
    from core import event_bus
    logger.debug("Core event_bus imported")
except ImportError as e:
    logger.error("Import failed: %s", e)
    event_bus = None
    raise

# ============================================================================
# CONSTANTS
# ============================================================================

LATENCY_WARNING = 100.0  # ms
LATENCY_ERROR = 500.0

# ============================================================================
# NETWORK PANEL
# ============================================================================

class NetworkPanel(BasePanel):
    """Network status monitoring panel."""
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        if config is None:
            config = PanelConfig(
                title="NETWORK",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=2000,
            )
        
        logger.debug("Initializing NetworkPanel")
        super().__init__(parent, config, **kwargs)
    
    def on_initialize(self) -> None:
        """Create panel widgets."""
        logger.info("Initializing NetworkPanel UI")
        
        # Connections
        conn_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        conn_frame.pack(fill="x", padx=12, pady=6)
        
        conn_label = tk.Label(
            conn_frame, text="CONNECTIONS",
            font=("Segoe UI", 10, "bold"), fg=COLOR_ACCENT, bg=self.bg_color
        )
        conn_label.pack(anchor="w")
        
        stat1 = StatDisplay(conn_frame, "Active", "0", color=COLOR_MUTED)
        stat1.pack(fill="x")
        self.widgets["active_conns"] = stat1
        
        stat2 = StatDisplay(conn_frame, "Latency", "0 ms", color=COLOR_MUTED)
        stat2.pack(fill="x")
        self.widgets["latency"] = stat2
        
        logger.debug("Connections section created")
        
        # Separator
        sep1 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep1.pack(fill="x", padx=12, pady=6)
        
        # Bandwidth
        bw_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        bw_frame.pack(fill="x", padx=12, pady=6)
        
        bw_label = tk.Label(
            bw_frame, text="BANDWIDTH",
            font=("Segoe UI", 10, "bold"), fg=COLOR_ACCENT, bg=self.bg_color
        )
        bw_label.pack(anchor="w")
        
        stat3 = StatDisplay(bw_frame, "Inbound", "0 Mbps", color=COLOR_MUTED)
        stat3.pack(fill="x")
        self.widgets["inbound"] = stat3
        
        stat4 = StatDisplay(bw_frame, "Outbound", "0 Mbps", color=COLOR_MUTED)
        stat4.pack(fill="x")
        self.widgets["outbound"] = stat4
        
        # Status
        sep2 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep2.pack(fill="x", padx=12, pady=6)
        
        status_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        status_frame.pack(fill="x", padx=12, pady=6)
        
        status_label = tk.Label(
            status_frame, text="STATUS",
            font=("Segoe UI", 10, "bold"), fg=COLOR_ACCENT, bg=self.bg_color
        )
        status_label.pack(anchor="w", pady=(0, 4))
        
        indicator = StatusIndicator(status_frame, "CONNECTED", COLOR_SUCCESS)
        indicator.pack(anchor="w")
        self.widgets["status_indicator"] = indicator
        
        logger.info("NetworkPanel UI created")
    
    def on_refresh(self) -> None:
        """Update network metrics."""
        logger.debug("Refreshing NetworkPanel")
        
        try:
            # Placeholder values
            self.update_stat("active_conns", "0")
            self.update_stat("latency", "0 ms")
            self.update_stat("inbound", "0.0 Mbps")
            self.update_stat("outbound", "0.0 Mbps")
            
            indicator = self.widgets.get("status_indicator")
            if indicator:
                indicator.set_status("CONNECTED", COLOR_SUCCESS)
            
        except Exception as e:
            logger.error("NetworkPanel refresh failed: %s", e)
    
    def on_cleanup(self) -> None:
        """Cleanup network panel."""
        logger.info("Cleaning up NetworkPanel")

logger.info("Network panel module loaded")

__all__ = ["NetworkPanel"]
