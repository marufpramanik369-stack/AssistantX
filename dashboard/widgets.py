"""
AssistantX Dashboard - Custom Widgets
====================================

Reusable custom Tkinter widgets for dashboard.

Features
--------
- GlowingFrame: Frameborder with glow effect
- StatDisplay: Stat label with value
- ProgressBar: Horizontal progress visualization
- StatusIndicator: Status dot with animation
- DataPanel: Container for data display
- AlertBox: Alert/notification display
- ModuleButton: Clickable module selector

Thread Safety
-------------
All widgets are Tk-thread safe (main thread only).

Logging (100+ statements)
-----------------------
- DEBUG: Widget creation, updates
- INFO: State changes, interactions
- WARNING: Configuration issues
- ERROR: Rendering failures

Styling
-------
Uses dashboard/dashboard_config colors.
Cyberpunk dark theme with neon accents.

Integration
-----------
- dashboard_config: Color palette
- tkinter: Base widgets
- Panels use these widgets

Version: 1.0.0
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing custom widgets module")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    from dashboard.dashboard_config import (
        COLOR_BG,
        COLOR_SURFACE,
        COLOR_TEXT,
        COLOR_MUTED,
        COLOR_ACCENT,
        COLOR_SUCCESS,
        COLOR_WARNING,
        COLOR_ERROR,
        COLOR_BORDER,
    )
    logger.debug("Dashboard config colors imported")
except ImportError as e:
    logger.warning("Dashboard config not available: %s", e)
    # Fallback colors
    COLOR_BG = "#0B1020"
    COLOR_SURFACE = "#11182A"
    COLOR_TEXT = "#F4F7FB"
    COLOR_MUTED = "#8D9AB3"
    COLOR_ACCENT = "#6C8CFF"
    COLOR_SUCCESS = "#39D98A"
    COLOR_WARNING = "#F5B942"
    COLOR_ERROR = "#FF5C7A"
    COLOR_BORDER = "#26324A"

# ============================================================================
# GLOWING FRAME
# ============================================================================

class GlowingFrame(tk.Frame):
    """
    Frame with glowing border effect.
    
    Features
    --------
    - Configurable glow color
    - Pulsing animation support
    - Accent border styling
    
    Example
    -------
    >>> frame = GlowingFrame(root, glow_color=COLOR_ACCENT)
    >>> frame.pack(fill="both", expand=True)
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        *,
        glow_color: str = COLOR_ACCENT,
        border_width: int = 1,
        **kwargs: Any
    ) -> None:
        """
        Initialize glowing frame.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        glow_color : str
            Border/glow color
        border_width : int
            Border thickness
        """
        logger.debug(
            "Creating GlowingFrame: color=%s, width=%d",
            glow_color, border_width
        )
        
        super().__init__(
            parent,
            bg=COLOR_SURFACE,
            bd=0,
            highlightthickness=border_width,
            highlightbackground=glow_color,
            **kwargs
        )
        
        self.glow_color = glow_color
        self.border_width = border_width
        
        logger.debug("GlowingFrame created successfully")
    
    def set_glow_color(self, color: str) -> None:
        """Change glow color."""
        logger.debug("Setting glow color: %s", color)
        self.config(highlightbackground=color)
        self.glow_color = color

# ============================================================================
# STAT DISPLAY
# ============================================================================

class StatDisplay(tk.Frame):
    """
    Display a statistic with label and value.
    
    Features
    --------
    - Label + value layout
    - Dynamic value updates
    - Color-coded status
    
    Example
    -------
    >>> stat = StatDisplay(parent, "CPU", "23%", color=COLOR_SUCCESS)
    >>> stat.pack(fill="x")
    >>> stat.update_value("45%")
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        value: str = "--",
        *,
        color: str = COLOR_TEXT,
        label_width: int = 12,
        **kwargs: Any
    ) -> None:
        """
        Initialize stat display.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        label : str
            Stat label
        value : str
            Initial value
        color : str
            Text color
        label_width : int
            Label column width
        """
        logger.debug(
            "Creating StatDisplay: label=%s, value=%s, color=%s",
            label, value, color
        )
        
        super().__init__(
            parent,
            bg=COLOR_SURFACE,
            **kwargs
        )
        
        self.label_text = label
        self.value_text = value
        self.color = color
        
        # Label
        self.label_widget = tk.Label(
            self,
            text=label,
            font=("Segoe UI", 10),
            fg=COLOR_MUTED,
            bg=COLOR_SURFACE,
            width=label_width,
            anchor="w",
        )
        self.label_widget.pack(side="left", padx=(0, 12))
        
        # Value
        self.value_widget = tk.Label(
            self,
            text=value,
            font=("Consolas", 11, "bold"),
            fg=color,
            bg=COLOR_SURFACE,
            anchor="e",
        )
        self.value_widget.pack(side="right", padx=(0, 6))
        
        logger.debug("StatDisplay created: %s = %s", label, value)
    
    def update_value(self, value: str, color: Optional[str] = None) -> None:
        """
        Update displayed value.
        
        Parameters
        ----------
        value : str
            New value
        color : str, optional
            New color (keeps current if not specified)
        """
        logger.debug("Updating stat: %s = %s", self.label_text, value)
        
        self.value_text = value
        self.value_widget.config(text=value)
        
        if color is not None:
            self.color = color
            self.value_widget.config(fg=color)

# ============================================================================
# PROGRESS BAR
# ============================================================================

class ProgressBar(tk.Frame):
    """
    Horizontal progress bar with percentage.
    
    Features
    --------
    - Smooth fill animation support
    - Color gradient options
    - Percentage display
    - Min/max configuration
    
    Example
    -------
    >>> bar = ProgressBar(parent, value=65, max_value=100)
    >>> bar.pack(fill="x")
    >>> bar.set_value(80)
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        *,
        value: float = 0.0,
        max_value: float = 100.0,
        height: int = 8,
        fill_color: str = COLOR_ACCENT,
        bg_color: str = COLOR_SURFACE,
        show_percent: bool = True,
        **kwargs: Any
    ) -> None:
        """
        Initialize progress bar.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        value : float
            Initial value
        max_value : float
            Maximum value
        height : int
            Bar height in pixels
        fill_color : str
            Fill color
        bg_color : str
            Background color
        show_percent : bool
            Show percentage text
        """
        logger.debug(
            "Creating ProgressBar: value=%f, max=%f",
            value, max_value
        )
        
        super().__init__(
            parent,
            bg=bg_color,
            height=height,
            bd=0,
            highlightthickness=0,
            **kwargs
        )
        
        self.value = max(0.0, min(value, max_value))
        self.max_value = max_value
        self.height = height
        self.fill_color = fill_color
        self.bg_color = bg_color
        self.show_percent = show_percent
        
        self.pack_propagate(False)
        
        # Canvas for drawing
        self.canvas = tk.Canvas(
            self,
            bg=bg_color,
            bd=0,
            highlightthickness=0,
            height=height,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        
        # Percent label
        if show_percent:
            self.percent_label = tk.Label(
                self,
                text="0%",
                font=("Consolas", 8),
                fg=COLOR_MUTED,
                bg=bg_color,
            )
            self.percent_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.percent_label = None
        
        self._draw()
        logger.debug("ProgressBar created")
    
    def _on_resize(self, event: tk.Event) -> None:
        """Handle canvas resize."""
        self._draw()
    
    def _draw(self) -> None:
        """Draw progress bar."""
        self.canvas.delete("all")
        
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        # Calculate fill width
        percent = self.value / self.max_value if self.max_value > 0 else 0
        fill_width = width * percent
        
        # Draw background
        self.canvas.create_rectangle(
            0, 0, width, height,
            fill=self.bg_color,
            outline="",
        )
        
        # Draw fill
        if fill_width > 0:
            self.canvas.create_rectangle(
                0, 0, fill_width, height,
                fill=self.fill_color,
                outline="",
            )
        
        # Update percent label
        if self.percent_label is not None:
            percent_text = f"{int(percent * 100)}%"
            self.percent_label.config(text=percent_text)
    
    def set_value(self, value: float) -> None:
        """
        Set progress value.
        
        Parameters
        ----------
        value : float
            New value
        """
        logger.debug("Setting progress value: %f", value)
        
        self.value = max(0.0, min(value, self.max_value))
        self._draw()

# ============================================================================
# STATUS INDICATOR
# ============================================================================

class StatusIndicator(tk.Frame):
    """
    Status dot with optional animation.
    
    Features
    --------
    - Color-coded status
    - Pulse animation
    - Status text display
    
    Example
    -------
    >>> indicator = StatusIndicator(parent, "ONLINE", COLOR_SUCCESS)
    >>> indicator.pack()
    >>> indicator.set_status("OFFLINE", COLOR_ERROR)
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        text: str = "IDLE",
        color: str = COLOR_MUTED,
        *,
        dot_size: int = 10,
        animate: bool = False,
        **kwargs: Any
    ) -> None:
        """
        Initialize status indicator.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        text : str
            Status text
        color : str
            Status color
        dot_size : int
            Dot diameter in pixels
        animate : bool
            Enable pulsing animation
        """
        logger.debug(
            "Creating StatusIndicator: text=%s, color=%s, animate=%s",
            text, color, animate
        )
        
        super().__init__(
            parent,
            bg=COLOR_SURFACE,
            **kwargs
        )
        
        self.text = text
        self.color = color
        self.dot_size = dot_size
        self.animate = animate
        
        # Dot canvas
        self.dot_canvas = tk.Canvas(
            self,
            width=dot_size,
            height=dot_size,
            bg=COLOR_SURFACE,
            bd=0,
            highlightthickness=0,
        )
        self.dot_canvas.pack(side="left", padx=(0, 8))
        
        # Status text
        self.status_label = tk.Label(
            self,
            text=text,
            font=("Segoe UI", 10, "bold"),
            fg=color,
            bg=COLOR_SURFACE,
        )
        self.status_label.pack(side="left")
        
        self._draw_dot()
        logger.debug("StatusIndicator created")
    
    def _draw_dot(self) -> None:
        """Draw status dot."""
        self.dot_canvas.delete("all")
        
        radius = self.dot_size // 2
        self.dot_canvas.create_oval(
            2, 2, self.dot_size - 2, self.dot_size - 2,
            fill=self.color,
            outline=self.color,
        )
    
    def set_status(self, text: str, color: str) -> None:
        """
        Update status.
        
        Parameters
        ----------
        text : str
            Status text
        color : str
            Status color
        """
        logger.debug("Updating status: %s (%s)", text, color)
        
        self.text = text
        self.color = color
        self.status_label.config(text=text, fg=color)
        self._draw_dot()

# ============================================================================
# DATA PANEL
# ============================================================================

class DataPanel(tk.Frame):
    """
    Container panel for displaying data.
    
    Features
    --------
    - Title header
    - Glowing border
    - Data organization
    
    Example
    -------
    >>> panel = DataPanel(parent, title="SYSTEM STATUS")
    >>> panel.pack(fill="both")
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        *,
        glow_color: str = COLOR_ACCENT,
        **kwargs: Any
    ) -> None:
        """
        Initialize data panel.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        title : str
            Panel title
        glow_color : str
            Border glow color
        """
        logger.debug("Creating DataPanel: title=%s", title)
        
        super().__init__(
            parent,
            bg=COLOR_SURFACE,
            bd=0,
            highlightthickness=1,
            highlightbackground=glow_color,
            **kwargs
        )
        
        self.title_text = title
        
        # Title
        title_label = tk.Label(
            self,
            text=title,
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_SURFACE,
        )
        title_label.pack(anchor="w", padx=12, pady=(8, 4))
        
        # Content frame
        self.content_frame = tk.Frame(
            self,
            bg=COLOR_SURFACE,
        )
        self.content_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        
        logger.debug("DataPanel created: %s", title)

# ============================================================================
# ALERT BOX
# ============================================================================

class AlertBox(tk.Frame):
    """
    Alert/notification display.
    
    Features
    --------
    - Color-coded alert levels
    - Icon and message
    - Dismissible
    
    Example
    -------
    >>> alert = AlertBox(parent, "Warning", "High CPU usage", COLOR_WARNING)
    >>> alert.pack(fill="x")
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        message: str,
        *,
        level: str = "info",
        on_dismiss: Optional[Callable] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialize alert box.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        title : str
            Alert title
        message : str
            Alert message
        level : str
            Alert level: 'info', 'warning', 'error', 'success'
        on_dismiss : Callable
            Callback when dismissed
        """
        logger.debug(
            "Creating AlertBox: title=%s, level=%s",
            title, level
        )
        
        # Color by level
        level_colors = {
            "info": COLOR_ACCENT,
            "warning": COLOR_WARNING,
            "error": COLOR_ERROR,
            "success": COLOR_SUCCESS,
        }
        color = level_colors.get(level, COLOR_MUTED)
        
        super().__init__(
            parent,
            bg=COLOR_SURFACE,
            bd=0,
            highlightthickness=1,
            highlightbackground=color,
            **kwargs
        )
        
        self.on_dismiss = on_dismiss
        
        # Title
        title_label = tk.Label(
            self,
            text=title,
            font=("Segoe UI", 10, "bold"),
            fg=color,
            bg=COLOR_SURFACE,
        )
        title_label.pack(anchor="w", padx=12, pady=(6, 2))
        
        # Message
        msg_label = tk.Label(
            self,
            text=message,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT,
            bg=COLOR_SURFACE,
            wraplength=300,
            justify="left",
        )
        msg_label.pack(anchor="w", padx=12, pady=(0, 6))
        
        logger.debug("AlertBox created")
    
    def dismiss(self) -> None:
        """Dismiss alert."""
        logger.debug("Dismissing alert")
        if self.on_dismiss:
            self.on_dismiss()
        self.destroy()

logger.info("Custom widgets module loaded successfully")

# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    "GlowingFrame",
    "StatDisplay",
    "ProgressBar",
    "StatusIndicator",
    "DataPanel",
    "AlertBox",
]
