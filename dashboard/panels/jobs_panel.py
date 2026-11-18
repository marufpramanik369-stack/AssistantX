"""
AssistantX Dashboard - Jobs Panel
================================

Task/job queue status display.

Features
--------
- Queue length
- Active jobs
- Completed count
- Failed count
- Job list

Version: 1.0.0
"""

from __future__ import annotations
import logging
from typing import Any, Optional
import tkinter as tk

logger = logging.getLogger(__name__)
logger.debug("Importing jobs_panel module")

try:
    from .base_panel import BasePanel, PanelConfig, RefreshMode
    from dashboard.widgets import StatDisplay
    from dashboard.dashboard_config import COLOR_ACCENT, COLOR_MUTED, COLOR_SUCCESS
except ImportError as e:
    logger.error("Import failed: %s", e)
    raise

class JobsPanel(BasePanel):
    """Job queue status panel."""
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        if config is None:
            config = PanelConfig(
                title="CROWN JOBS",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=1000,
            )
        logger.debug("Initializing JobsPanel")
        super().__init__(parent, config, **kwargs)
    
    def on_initialize(self) -> None:
        """Create job widgets."""
        logger.info("Initializing JobsPanel UI")
        
        # Queue stats
        queue_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        queue_frame.pack(fill="x", padx=12, pady=6)
        
        queue_label = tk.Label(
            queue_frame, text="QUEUE",
            font=("Segoe UI", 10, "bold"), fg=COLOR_ACCENT, bg=self.bg_color
        )
        queue_label.pack(anchor="w")
        
        stat1 = StatDisplay(queue_frame, "Pending", "0", color=COLOR_MUTED)
        stat1.pack(fill="x")
        self.widgets["pending"] = stat1
        
        stat2 = StatDisplay(queue_frame, "Active", "0", color=COLOR_MUTED)
        stat2.pack(fill="x")
        self.widgets["active"] = stat2
        
        stat3 = StatDisplay(queue_frame, "Completed", "0", color=COLOR_MUTED)
        stat3.pack(fill="x")
        self.widgets["completed"] = stat3
        
        stat4 = StatDisplay(queue_frame, "Failed", "0", color=COLOR_MUTED)
        stat4.pack(fill="x")
        self.widgets["failed"] = stat4
        
        logger.info("JobsPanel UI created")
    
    def on_refresh(self) -> None:
        """Update job queue."""
        logger.debug("Refreshing JobsPanel")
        try:
            self.update_stat("pending", "0")
            self.update_stat("active", "0")
            self.update_stat("completed", "0")
            self.update_stat("failed", "0")
        except Exception as e:
            logger.error("JobsPanel refresh failed: %s", e)
    
    def on_cleanup(self) -> None:
        """Cleanup jobs panel."""
        logger.info("Cleaning up JobsPanel")

logger.info("Jobs panel module loaded")
__all__ = ["JobsPanel"]
