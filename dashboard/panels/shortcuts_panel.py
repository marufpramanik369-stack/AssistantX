"""
AssistantX Dashboard - Shortcuts Panel
====================================

Quick action buttons and shortcuts.

Features
--------
- Quick action buttons
- Command shortcuts
- System shortcuts
- Custom shortcuts
- Button callbacks

Version: 1.0.0
"""

from __future__ import annotations
import logging
from typing import Any, Callable, Optional
import tkinter as tk

logger = logging.getLogger(__name__)
logger.debug("Importing shortcuts_panel module")

try:
    from .base_panel import BasePanel, PanelConfig, RefreshMode
    from dashboard.dashboard_config import COLOR_ACCENT, COLOR_MUTED, COLOR_SUCCESS
except ImportError as e:
    logger.error("Import failed: %s", e)
    raise

class ShortcutsPanel(BasePanel):
    """Quick action shortcuts panel."""
    
    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        if config is None:
            config = PanelConfig(
                title="QUICK ACTIONS",
                refresh_mode=RefreshMode.MANUAL,
            )
        logger.debug("Initializing ShortcutsPanel")
        super().__init__(parent, config, **kwargs)
        self.shortcuts = {}
    
    def on_initialize(self) -> None:
        """Create shortcut buttons."""
        logger.info("Initializing ShortcutsPanel UI")
        
        # Shortcuts frame
        shortcuts_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        shortcuts_frame.pack(fill="both", expand=True, padx=6, pady=6)
        
        # Sample shortcuts
        shortcuts = [
            ("CLEAR", self._on_clear),
            ("RESET", self._on_reset),
            ("SETTINGS", self._on_settings),
        ]
        
        for label, callback in shortcuts:
            btn = tk.Button(
                shortcuts_frame,
                text=label,
                command=callback,
                font=("Segoe UI", 9, "bold"),
                bg=COLOR_ACCENT,
                fg="#0B1020",
                relief="flat",
                bd=0,
                padx=12,
                pady=6,
            )
            btn.pack(fill="x", pady=2)
            self.widgets[label.lower()] = btn
        
        logger.info("ShortcutsPanel UI created")
    
    def add_shortcut(
        self,
        label: str,
        callback: Callable,
    ) -> None:
        """Add custom shortcut."""
        logger.debug("Adding shortcut: %s", label)
        
        btn = tk.Button(
            self.content_frame,
            text=label,
            command=callback,
            font=("Segoe UI", 9, "bold"),
            bg=COLOR_ACCENT,
            fg="#0B1020",
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
        )
        btn.pack(fill="x", pady=2)
        self.widgets[label.lower()] = btn
        self.shortcuts[label] = callback
    
    def on_refresh(self) -> None:
        """No refresh needed for shortcuts."""
        pass
    
    def on_cleanup(self) -> None:
        """Cleanup shortcuts panel."""
        logger.info("Cleaning up ShortcutsPanel")
    
    def _on_clear(self) -> None:
        logger.info("Clear action triggered")
    
    def _on_reset(self) -> None:
        logger.info("Reset action triggered")
    
    def _on_settings(self) -> None:
        logger.info("Settings action triggered")

logger.info("Shortcuts panel module loaded")
__all__ = ["ShortcutsPanel"]
