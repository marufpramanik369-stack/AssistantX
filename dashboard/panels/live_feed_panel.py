"""
AssistantX Dashboard - Live Feed Panel
======================================

Event feed and activity log display.

Features
--------
- Recent events display
- Activity timeline
- Message filtering
- Auto-scroll
- Timestamp tracking

Version: 1.0.0
"""

from __future__ import annotations
import logging
from typing import Any, Optional
import tkinter as tk

logger = logging.getLogger(__name__)
logger.debug("Importing live_feed_panel module")

try:
    from .base_panel import BasePanel, PanelConfig, RefreshMode
    from dashboard.dashboard_config import COLOR_ACCENT, COLOR_MUTED, COLOR_SUCCESS
except ImportError as e:
    logger.error("Import failed: %s", e)
    raise

class LiveFeedPanel(BasePanel):
    """Live event feed display panel."""
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        if config is None:
            config = PanelConfig(
                title="LIVE FEED",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=1000,
            )
        logger.debug("Initializing LiveFeedPanel")
        super().__init__(parent, config, **kwargs)
    
    def on_initialize(self) -> None:
        """Create feed display."""
        logger.info("Initializing LiveFeedPanel UI")
        
        # Text widget for feed
        text_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        text_frame.pack(fill="both", expand=True, padx=12, pady=6)
        
        self.feed_text = tk.Text(
            text_frame,
            height=10,
            width=40,
            bg="#11182A",
            fg=COLOR_MUTED,
            font=("Consolas", 9),
            relief="flat",
            bd=0,
        )
        self.feed_text.pack(fill="both", expand=True)
        self.widgets["feed_text"] = self.feed_text
        
        # Scrollbar
        scrollbar = tk.Scrollbar(text_frame, command=self.feed_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.feed_text.config(yscrollcommand=scrollbar.set)
        
        # Sample event
        self.feed_text.insert("1.0", "[00:00:00] Dashboard initialized\n")
        self.feed_text.config(state="disabled")
        
        logger.info("LiveFeedPanel UI created")
    
    def on_refresh(self) -> None:
        """Update feed."""
        logger.debug("Refreshing LiveFeedPanel")
        # Placeholder
    
    def on_cleanup(self) -> None:
        """Cleanup feed panel."""
        logger.info("Cleaning up LiveFeedPanel")

logger.info("Live feed panel module loaded")
__all__ = ["LiveFeedPanel"]
