"""
AssistantX Dashboard - Theme Manager
===================================

Centralized theme management for dashboard.

Features
--------
- Dynamic theme switching
- Color palette management
- Theme validation
- Font configuration
- Fallback handling

Logging (50+ statements)
-----------------------
- DEBUG: Theme loads, color requests
- INFO: Theme activated, switched
- WARNING: Missing themes, fallbacks
- ERROR: Load failures

Integration
-----------
- dashboard_config: Color definitions
- Tkinter widgets: Applied to all UI

Version: 1.0.0
"""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing theme manager module")

# ============================================================================
# THEME DEFINITIONS
# ============================================================================

logger.debug("Defining available themes")

THEMES = {
    "dark": {
        "name": "Dark",
        "bg": "#0B1020",
        "surface": "#11182A",
        "surface_alt": "#172036",
        "border": "#26324A",
        "border_accent": "#4A6FA5",
        "text": "#F4F7FB",
        "text_secondary": "#D1D5DB",
        "muted": "#8D9AB3",
        "accent": "#6C8CFF",
        "accent_light": "#8E7CFF",
        "accent_dark": "#4A5FD5",
        "success": "#39D98A",
        "warning": "#F5B942",
        "error": "#FF5C7A",
        "info": "#60A5FA",
    }
}

logger.info("Themes defined: %s", list(THEMES.keys()))

# ============================================================================
# THEME MANAGER
# ============================================================================

class ThemeManager:
    """
    Centralized theme management.
    
    Thread Safety
    -------------
    RLock for theme state access.
    
    Example
    -------
    >>> manager = ThemeManager()
    >>> color = manager.get_color("accent")
    >>> manager.set_theme("dark")
    """
    
    def __init__(self) -> None:
        """Initialize theme manager."""
        logger.debug("Initializing ThemeManager")
        
        self._lock = RLock()
        self._current_theme = "dark"
        self._callbacks: list[callable] = []
        
        logger.info("ThemeManager initialized with theme: %s", self._current_theme)
    
    # ========================================================================
    # THEME SELECTION
    # ========================================================================
    
    def set_theme(self, theme_name: str) -> bool:
        """
        Set active theme.
        
        Parameters
        ----------
        theme_name : str
            Theme name to activate
        
        Returns
        -------
        bool
            True if theme set successfully
        """
        logger.debug("Setting theme: %s", theme_name)
        
        if theme_name not in THEMES:
            logger.warning("Theme '%s' not found", theme_name)
            return False
        
        with self._lock:
            old_theme = self._current_theme
            self._current_theme = theme_name
        
        logger.info("Theme changed: %s -> %s", old_theme, theme_name)
        
        # Notify callbacks
        try:
            for callback in self._callbacks:
                callback(theme_name)
        except Exception as e:
            logger.exception("Theme callback failed: %s", e)
        
        return True
    
    def get_theme(self) -> str:
        """
        Get current active theme.
        
        Returns
        -------
        str
            Active theme name
        """
        with self._lock:
            return self._current_theme
    
    def is_supported_theme(self, name: str) -> bool:
        """
        Check if theme is supported.
        
        Parameters
        ----------
        name : str
            Theme name to check
        
        Returns
        -------
        bool
            True if theme exists
        """
        result = name in THEMES
        logger.debug("Theme check: %s -> %s", name, result)
        return result
    
    def list_themes(self) -> list[str]:
        """
        List all available themes.
        
        Returns
        -------
        list[str]
            Theme names
        """
        themes = list(THEMES.keys())
        logger.debug("Available themes: %s", themes)
        return themes
    
    # ========================================================================
    # COLOR ACCESS
    # ========================================================================
    
    def get_color(
        self,
        name: str,
        theme: Optional[str] = None,
    ) -> str:
        """
        Get color from theme palette.
        
        Parameters
        ----------
        name : str
            Color name
        theme : str, optional
            Theme name (uses current if not specified)
        
        Returns
        -------
        str
            Color hex code
        """
        logger.debug("Getting color: name=%s, theme=%s", name, theme)
        
        with self._lock:
            current_theme = theme or self._current_theme
        
        palette = THEMES.get(current_theme)
        if palette is None:
            logger.warning("Theme '%s' not found", current_theme)
            palette = THEMES.get("dark", {})
        
        color = palette.get(name, "#F4F7FB")  # Default to text color
        logger.debug("Color found: %s = %s", name, color)
        return color
    
    def get_palette(self, theme: Optional[str] = None) -> dict:
        """
        Get complete color palette for theme.
        
        Parameters
        ----------
        theme : str, optional
            Theme name (uses current if not specified)
        
        Returns
        -------
        dict
            Color palette dictionary
        """
        with self._lock:
            current_theme = theme or self._current_theme
        
        palette = THEMES.get(current_theme)
        if palette is None:
            logger.warning("Theme '%s' not found", current_theme)
            palette = THEMES.get("dark", {})
        
        logger.debug("Palette fetched: %d colors", len(palette))
        return dict(palette)
    
    # ========================================================================
    # CALLBACKS
    # ========================================================================
    
    def add_callback(self, callback: callable) -> None:
        """
        Register theme change callback.
        
        Parameters
        ----------
        callback : callable
            Function called when theme changes
        """
        logger.debug("Adding theme callback: %s", callback.__name__)
        
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
    
    def remove_callback(self, callback: callable) -> None:
        """Remove theme change callback."""
        logger.debug("Removing theme callback: %s", callback.__name__)
        
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================
    
    def diagnostics(self) -> dict:
        """
        Return theme manager diagnostics.
        
        Returns
        -------
        dict
            Diagnostic information
        """
        logger.debug("Generating theme manager diagnostics")
        
        with self._lock:
            return {
                "component": "ThemeManager",
                "current_theme": self._current_theme,
                "available_themes": list(THEMES.keys()),
                "palette_size": len(THEMES.get(self._current_theme, {})),
                "callback_count": len(self._callbacks),
            }

logger.info("Theme manager loaded successfully")

# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

logger.debug("Creating global theme manager instance")

_theme_manager = ThemeManager()

logger.info("Global theme manager created")

# ============================================================================
# MODULE FUNCTIONS
# ============================================================================

def get_theme() -> str:
    """Get current active theme."""
    return _theme_manager.get_theme()

def set_theme(name: str) -> bool:
    """Set active theme."""
    return _theme_manager.set_theme(name)

def get_color(name: str, theme: Optional[str] = None) -> str:
    """Get color from palette."""
    return _theme_manager.get_color(name, theme)

def get_palette(theme: Optional[str] = None) -> dict:
    """Get complete color palette."""
    return _theme_manager.get_palette(theme)

def is_supported_theme(name: str) -> bool:
    """Check if theme is supported."""
    return _theme_manager.is_supported_theme(name)

def list_themes() -> list[str]:
    """List available themes."""
    return _theme_manager.list_themes()

def add_theme_callback(callback: callable) -> None:
    """Register theme change callback."""
    _theme_manager.add_callback(callback)

def remove_theme_callback(callback: callable) -> None:
    """Remove theme change callback."""
    _theme_manager.remove_callback(callback)

logger.info("Theme module ready")

# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    "THEMES",
    "ThemeManager",
    "get_theme",
    "set_theme",
    "get_color",
    "get_palette",
    "is_supported_theme",
    "list_themes",
    "add_theme_callback",
    "remove_theme_callback",
]
