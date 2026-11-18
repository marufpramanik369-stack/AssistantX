"""
AssistantX Dashboard - Weather Panel
===================================

Weather information display.

Features
--------
- Current temperature
- Weather condition
- Humidity
- Wind speed
- Weather alerts

Version: 1.0.0
"""

from __future__ import annotations
import logging
from typing import Any, Optional
import tkinter as tk

logger = logging.getLogger(__name__)
logger.debug("Importing weather_panel module")

try:
    from .base_panel import BasePanel, PanelConfig, RefreshMode
    from dashboard.widgets import StatDisplay, StatusIndicator
    from dashboard.dashboard_config import COLOR_ACCENT, COLOR_MUTED, COLOR_SUCCESS
except ImportError as e:
    logger.error("Import failed: %s", e)
    raise

class WeatherPanel(BasePanel):
    """Weather information panel."""
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        if config is None:
            config = PanelConfig(
                title="WEATHER REPORT",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=5000,
            )
        logger.debug("Initializing WeatherPanel")
        super().__init__(parent, config, **kwargs)
    
    def on_initialize(self) -> None:
        """Create weather widgets."""
        logger.info("Initializing WeatherPanel UI")
        
        # Weather info
        weather_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        weather_frame.pack(fill="x", padx=12, pady=6)
        
        weather_label = tk.Label(
            weather_frame, text="CONDITIONS",
            font=("Segoe UI", 10, "bold"), fg=COLOR_ACCENT, bg=self.bg_color
        )
        weather_label.pack(anchor="w")
        
        stat1 = StatDisplay(weather_frame, "Temp", "--°C", color=COLOR_MUTED)
        stat1.pack(fill="x")
        self.widgets["temperature"] = stat1
        
        stat2 = StatDisplay(weather_frame, "Condition", "Unknown", color=COLOR_MUTED)
        stat2.pack(fill="x")
        self.widgets["condition"] = stat2
        
        stat3 = StatDisplay(weather_frame, "Humidity", "0%", color=COLOR_MUTED)
        stat3.pack(fill="x")
        self.widgets["humidity"] = stat3
        
        stat4 = StatDisplay(weather_frame, "Wind", "0 km/h", color=COLOR_MUTED)
        stat4.pack(fill="x")
        self.widgets["wind"] = stat4
        
        logger.info("WeatherPanel UI created")
    
    def on_refresh(self) -> None:
        """Update weather."""
        logger.debug("Refreshing WeatherPanel")
        try:
            self.update_stat("temperature", "--°C")
            self.update_stat("condition", "Unknown")
            self.update_stat("humidity", "0%")
            self.update_stat("wind", "0 km/h")
        except Exception as e:
            logger.error("WeatherPanel refresh failed: %s", e)
    
    def on_cleanup(self) -> None:
        """Cleanup weather panel."""
        logger.info("Cleaning up WeatherPanel")

logger.info("Weather panel module loaded")
__all__ = ["WeatherPanel"]
