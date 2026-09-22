"""
AssistantX Dashboard Themes
===========================

Centralized theme management for the AssistantX dashboard.

Supported themes
----------------
- dark
- light

Animation theme helpers are also exposed through this package.

Example
-------

    from dashboard.themes import (
        get_theme,
        get_colors,
        set_theme,
    )

    set_theme("dark")

    colors = get_colors()

    print(colors.background)

"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from threading import RLock
from typing import Final

# ============================================================================
# Theme Imports
# ============================================================================
from dashboard.themes.animation_theme import (
    AnimationTheme,
    animation_duration,
    get_animation_theme,
    is_animation_enabled,
)
from dashboard.themes.dark_theme import (
    DarkColors,
    DarkTheme,
)
from dashboard.themes.light_theme import (
    LightColors,
    LightTheme,
)

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

THEME_DARK: Final[str] = "dark"
THEME_LIGHT: Final[str] = "light"

DEFAULT_THEME: Final[str] = THEME_DARK

SUPPORTED_THEMES: Final[tuple[str, ...]] = (
    THEME_DARK,
    THEME_LIGHT,
)


# ============================================================================
# Theme Registry
# ============================================================================

_THEME_REGISTRY: Final[dict[str, object]] = {
    THEME_DARK: DarkTheme(),
    THEME_LIGHT: LightTheme(),
}


# ============================================================================
# Theme Errors
# ============================================================================


class ThemeError(Exception):
    """Base exception for dashboard theme errors."""


class ThemeConfigurationError(ThemeError):
    """Raised when theme configuration is invalid."""


class ThemeNotFoundError(ThemeError):
    """Raised when a requested theme does not exist."""


# ============================================================================
# Theme Manager
# ============================================================================


class DashboardThemeManager:
    """
    Thread-safe dashboard theme manager.

    The manager stores the active theme but does not directly modify
    dashboard widgets.

    Widgets/components should subscribe to theme changes and apply the
    relevant colors themselves.
    """

    def __init__(
        self,
        default: str = DEFAULT_THEME,
    ) -> None:

        self._lock = RLock()

        self._active = self._normalize_name(
            default,
            strict=False,
        )

        self._listeners: list[
            Callable[[str, object], None]
        ] = []

        self._change_count = 0

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_name(
        name: object,
        *,
        strict: bool = True,
    ) -> str:

        normalized = str(name).strip().lower()

        if normalized in SUPPORTED_THEMES:
            return normalized

        if strict:
            raise ThemeNotFoundError(
                f"Unsupported theme: {name!r}. "
                f"Supported themes: {SUPPORTED_THEMES}"
            )

        return DEFAULT_THEME

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_name(self) -> str:
        """Return the active theme name."""

        with self._lock:
            return self._active

    @property
    def active(self) -> object:
        """Return the active theme object."""

        with self._lock:
            return _THEME_REGISTRY[self._active]

    @property
    def change_count(self) -> int:
        """Return number of successful theme changes."""

        with self._lock:
            return self._change_count

    # ------------------------------------------------------------------
    # Theme Operations
    # ------------------------------------------------------------------

    def set_theme(
        self,
        name: str,
        *,
        notify: bool = True,
    ) -> bool:
        """
        Change the active dashboard theme.

        Returns
        -------
        bool
            True when the theme changed.
            False when the requested theme was already active.
        """

        normalized = self._normalize_name(name)

        with self._lock:

            if normalized == self._active:
                return False

            self._active = normalized
            self._change_count += 1

            theme = _THEME_REGISTRY[normalized]

            listeners = tuple(self._listeners)

        if notify:
            self._notify_listeners(
                normalized,
                theme,
                listeners,
            )

        return True

    def toggle(
        self,
        *,
        notify: bool = True,
    ) -> str:
        """Toggle between dark and light themes."""

        with self._lock:

            next_theme = (
                THEME_LIGHT
                if self._active == THEME_DARK
                else THEME_DARK
            )

        self.set_theme(
            next_theme,
            notify=notify,
        )

        return next_theme

    def reset(
        self,
        *,
        notify: bool = True,
    ) -> bool:
        """Reset to the default theme."""

        return self.set_theme(
            DEFAULT_THEME,
            notify=notify,
        )

    # ------------------------------------------------------------------
    # Theme Queries
    # ------------------------------------------------------------------

    def is_supported(
        self,
        name: str,
    ) -> bool:
        """Return True when a theme name is supported."""

        normalized = str(name).strip().lower()

        return normalized in SUPPORTED_THEMES

    def is_dark(self) -> bool:
        """Return True when dark theme is active."""

        return self.active_name == THEME_DARK

    def is_light(self) -> bool:
        """Return True when light theme is active."""

        return self.active_name == THEME_LIGHT

    def get_colors(self):
        """Return the active theme color palette."""

        theme = self.active

        if not hasattr(theme, "colors"):
            raise ThemeConfigurationError(
                f"Theme {self.active_name!r} does not provide colors."
            )

        return theme.colors

    def get(
        self,
        name: str | None = None,
    ):
        """
        Return a specific theme.

        If name is omitted, return the active theme.
        """

        if name is None:
            return self.active

        normalized = self._normalize_name(name)

        with self._lock:
            return _THEME_REGISTRY[normalized]

    def get_colors_for(
        self,
        name: str,
    ):
        """Return colors for a specific theme."""

        theme = self.get(name)

        if not hasattr(theme, "colors"):
            raise ThemeConfigurationError(
                f"Theme {name!r} does not provide colors."
            )

        return theme.colors

    def available_themes(self) -> tuple[str, ...]:
        """Return all supported theme names."""

        return SUPPORTED_THEMES

    # ------------------------------------------------------------------
    # Listener System
    # ------------------------------------------------------------------

    def subscribe(
        self,
        callback: Callable[[str, object], None],
    ) -> Callable[[], None]:
        """
        Subscribe to theme changes.

        Callback signature:

            callback(theme_name, theme_object)

        Returns an unsubscribe function.
        """

        if not callable(callback):
            raise ThemeConfigurationError(
                "Theme listener must be callable."
            )

        with self._lock:

            if callback not in self._listeners:
                self._listeners.append(callback)

        def unsubscribe() -> None:
            self.unsubscribe(callback)

        return unsubscribe

    def unsubscribe(
        self,
        callback: Callable[[str, object], None],
    ) -> bool:
        """Remove a theme listener."""

        with self._lock:

            if callback not in self._listeners:
                return False

            self._listeners.remove(callback)

            return True

    def clear_listeners(self) -> None:
        """Remove all theme listeners."""

        with self._lock:
            self._listeners.clear()

    def _notify_listeners(
        self,
        name: str,
        theme: object,
        listeners: tuple[
            Callable[[str, object], None],
            ...,
        ],
    ) -> None:

        for callback in listeners:
            try:
                callback(
                    name,
                    theme,
                )
            except Exception as exc:
                # A broken UI listener must not break theme switching.
                _LOGGER.exception(
                    "Theme listener failed for %s",
                    name,
                    exc_info=exc,
                )
                continue

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(value: object):
        """
        Safely serialize dataclasses and simple theme objects.
        """

        if is_dataclass(value):
            return asdict(value)

        if isinstance(value, dict):
            return {
                str(key): DashboardThemeManager._serialize(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                DashboardThemeManager._serialize(item)
                for item in value
            ]

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        return str(value)

    def to_dict(
        self,
        name: str | None = None,
    ) -> dict:
        """
        Return a serializable representation of a theme.

        If name is omitted, serialize the active theme.
        """

        theme_name = (
            self.active_name
            if name is None
            else self._normalize_name(name)
        )

        theme = self.get(theme_name)

        result = {
            "name": theme_name,
        }

        if hasattr(theme, "mode"):
            result["mode"] = self._serialize(
                theme.mode
            )

        if hasattr(theme, "colors"):
            result["colors"] = self._serialize(
                theme.colors
            )

        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict:
        """Return safe runtime diagnostics."""

        with self._lock:

            return {
                "component": "DashboardThemeManager",
                "active": self._active,
                "default": DEFAULT_THEME,
                "supported": list(SUPPORTED_THEMES),
                "is_dark": self._active == THEME_DARK,
                "is_light": self._active == THEME_LIGHT,
                "listener_count": len(self._listeners),
                "change_count": self._change_count,
                "animations_enabled": is_animation_enabled(),
            }


# ============================================================================
# Global Theme Manager
# ============================================================================

theme_manager: Final[DashboardThemeManager] = (
    DashboardThemeManager()
)


# ============================================================================
# Convenience API
# ============================================================================


def get_theme():
    """Return the active dashboard theme."""

    return theme_manager.active


def get_colors():
    """Return the active color palette."""

    return theme_manager.get_colors()


def get_theme_by_name(name: str):
    """Return a specific dashboard theme."""

    return theme_manager.get(name)


def get_colors_by_name(name: str):
    """Return colors for a specific theme."""

    return theme_manager.get_colors_for(name)


def set_theme(
    name: str,
    *,
    notify: bool = True,
) -> bool:
    """Set the active dashboard theme."""

    return theme_manager.set_theme(
        name,
        notify=notify,
    )


def toggle_theme(
    *,
    notify: bool = True,
) -> str:
    """Toggle between dark and light themes."""

    return theme_manager.toggle(
        notify=notify,
    )


def reset_theme(
    *,
    notify: bool = True,
) -> bool:
    """Reset to the default dashboard theme."""

    return theme_manager.reset(
        notify=notify,
    )


def current_theme() -> str:
    """Return active theme name."""

    return theme_manager.active_name


def is_dark() -> bool:
    """Return True when dark mode is active."""

    return theme_manager.is_dark()


def is_light() -> bool:
    """Return True when light mode is active."""

    return theme_manager.is_light()


def is_supported_theme(name: str) -> bool:
    """Return True if the theme exists."""

    return theme_manager.is_supported(name)


def subscribe_theme(
    callback: Callable[[str, object], None],
) -> Callable[[], None]:
    """Subscribe to global theme changes."""

    return theme_manager.subscribe(callback)


def unsubscribe_theme(
    callback: Callable[[str, object], None],
) -> bool:
    """Unsubscribe from global theme changes."""

    return theme_manager.unsubscribe(callback)


def theme_to_dict(
    name: str | None = None,
) -> dict:
    """Serialize the active or requested theme."""

    return theme_manager.to_dict(name)


def diagnostics() -> dict:
    """Return safe global theme diagnostics."""

    return theme_manager.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "DEFAULT_THEME",
    "SUPPORTED_THEMES",
    # Constants
    "THEME_DARK",
    "THEME_LIGHT",
    "AnimationTheme",
    # Theme classes
    "DarkColors",
    "DarkTheme",
    # Manager
    "DashboardThemeManager",
    "LightColors",
    "LightTheme",
    "ThemeConfigurationError",
    # Errors
    "ThemeError",
    "ThemeNotFoundError",
    "animation_duration",
    "current_theme",
    # Diagnostics
    "diagnostics",
    # Animation API
    "get_animation_theme",
    "get_colors",
    "get_colors_by_name",
    # Theme helpers
    "get_theme",
    "get_theme_by_name",
    "is_animation_enabled",
    "is_dark",
    "is_light",
    "is_supported_theme",
    "reset_theme",
    "set_theme",
    # Listener API
    "subscribe_theme",
    "theme_manager",
    # Serialization
    "theme_to_dict",
    "toggle_theme",
    "unsubscribe_theme",
]
