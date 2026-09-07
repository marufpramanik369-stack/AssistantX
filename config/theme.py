"""
theme.py
========
Defines color palettes, typography scales, and spacing tokens for the
dashboard UI, and exposes a small ThemeManager that resolves the active
theme based on user settings (dark/light/system).

This module is UI-framework-agnostic: it produces plain Python
dataclasses/dicts that dashboard/styles.py (or any Qt/Tkinter/Web layer)
can consume however it needs — as CSS variables, Qt stylesheets, dict
lookups, etc.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Literal

from config.constants import ThemeMode
from config.settings import settings_manager

logger = logging.getLogger(__name__)

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True)
class ColorPalette:
    """A complete set of semantic color tokens for one theme variant."""

    background: str
    surface: str
    surface_alt: str
    primary: str
    primary_variant: str
    secondary: str
    accent: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    border: str
    success: str
    warning: str
    error: str
    info: str
    chat_bubble_user: str
    chat_bubble_assistant: str
    chat_bubble_user_text: str
    chat_bubble_assistant_text: str
    scrollbar: str
    shadow: str


@dataclass(frozen=True)
class Typography:
    """Font family and size scale, in points (pt), for consistent UI text."""

    font_family: str = "Segoe UI, -apple-system, Roboto, sans-serif"
    font_family_mono: str = "Cascadia Code, Consolas, monospace"
    size_xs: int = 10
    size_sm: int = 12
    size_md: int = 14
    size_lg: int = 16
    size_xl: int = 20
    size_xxl: int = 28
    weight_regular: int = 400
    weight_medium: int = 500
    weight_bold: int = 700
    line_height: float = 1.4


@dataclass(frozen=True)
class Spacing:
    """Consistent spacing scale (px) used across the dashboard layout."""

    xs: int = 4
    sm: int = 8
    md: int = 16
    lg: int = 24
    xl: int = 32
    xxl: int = 48
    radius_sm: int = 4
    radius_md: int = 8
    radius_lg: int = 16
    radius_pill: int = 999


@dataclass(frozen=True)
class Theme:
    """A fully assembled theme: palette + typography + spacing."""

    name: ThemeName
    colors: ColorPalette
    typography: Typography
    spacing: Spacing


# --------------------------------------------------------------------------- #
# Built-in palettes
# --------------------------------------------------------------------------- #

DARK_PALETTE = ColorPalette(
    background="#0F1117",
    surface="#171A23",
    surface_alt="#1F2330",
    primary="#6C5CE7",
    primary_variant="#8479F0",
    secondary="#00CEC9",
    accent="#FD79A8",
    text_primary="#F5F6FA",
    text_secondary="#A4A6B3",
    text_disabled="#5A5D6B",
    border="#2A2E3B",
    success="#2ECC71",
    warning="#F1C40F",
    error="#E74C3C",
    info="#3498DB",
    chat_bubble_user="#6C5CE7",
    chat_bubble_assistant="#1F2330",
    chat_bubble_user_text="#FFFFFF",
    chat_bubble_assistant_text="#F5F6FA",
    scrollbar="#2A2E3B",
    shadow="rgba(0, 0, 0, 0.4)",
)

LIGHT_PALETTE = ColorPalette(
    background="#F7F8FC",
    surface="#FFFFFF",
    surface_alt="#EEF0F7",
    primary="#5B4BDB",
    primary_variant="#7566E8",
    secondary="#00A8A3",
    accent="#E84393",
    text_primary="#1A1C24",
    text_secondary="#5C5F6E",
    text_disabled="#A6A9B5",
    border="#E1E3EC",
    success="#27AE60",
    warning="#F39C12",
    error="#C0392B",
    info="#2980B9",
    chat_bubble_user="#5B4BDB",
    chat_bubble_assistant="#EEF0F7",
    chat_bubble_user_text="#FFFFFF",
    chat_bubble_assistant_text="#1A1C24",
    scrollbar="#D8DAE5",
    shadow="rgba(0, 0, 0, 0.12)",
)

_TYPOGRAPHY = Typography()
_SPACING = Spacing()

THEMES: dict[ThemeName, Theme] = {
    "dark": Theme(name="dark", colors=DARK_PALETTE, typography=_TYPOGRAPHY, spacing=_SPACING),
    "light": Theme(name="light", colors=LIGHT_PALETTE, typography=_TYPOGRAPHY, spacing=_SPACING),
}


# --------------------------------------------------------------------------- #
# Theme resolution
# --------------------------------------------------------------------------- #

def _detect_system_theme() -> ThemeName:
    """
    Best-effort detection of the OS-level light/dark preference.
    Falls back to 'dark' if detection fails or the platform is unsupported.
    """
    try:
        import darkdetect  # type: ignore

        return "light" if darkdetect.isLight() else "dark"
    except Exception:  # noqa: BLE001 - any failure just falls back safely
        logger.debug("System theme detection unavailable; defaulting to dark.")
        return "dark"


class ThemeManager:
    """Resolves and caches the currently active Theme object."""

    def __init__(self) -> None:
        self._active: Theme = THEMES["dark"]
        self.refresh()

    def refresh(self) -> Theme:
        """Re-resolve the active theme based on current settings."""
        mode_value = settings_manager.get("ui.theme", ThemeMode.DARK.value)
        try:
            mode = ThemeMode(mode_value)
        except ValueError:
            mode = ThemeMode.DARK

        if mode == ThemeMode.SYSTEM:
            resolved: ThemeName = _detect_system_theme()
        else:
            resolved = "light" if mode == ThemeMode.LIGHT else "dark"

        self._active = THEMES[resolved]
        return self._active

    @property
    def active(self) -> Theme:
        return self._active

    def set_theme(self, name: ThemeName) -> None:
        """Explicitly set and persist the theme choice."""
        if name not in THEMES:
            raise ValueError(f"Unknown theme '{name}'. Valid options: {list(THEMES)}")
        settings_manager.set("ui.theme", name)
        self.refresh()
        logger.info("Theme switched to '%s'.", name)

    def to_css_variables(self) -> str:
        """Render the active theme as a block of CSS custom properties."""
        colors = asdict(self._active.colors)
        lines = [":root {"]
        for key, value in colors.items():
            css_var = key.replace("_", "-")
            lines.append(f"  --color-{css_var}: {value};")
        lines.append(f"  --font-family: {self._active.typography.font_family};")
        lines.append(f"  --radius-md: {self._active.spacing.radius_md}px;")
        lines.append("}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return the active theme as a plain nested dict (for JSON/JS use)."""
        return {
            "name": self._active.name,
            "colors": asdict(self._active.colors),
            "typography": asdict(self._active.typography),
            "spacing": asdict(self._active.spacing),
        }


# Module-level singleton.
theme_manager: ThemeManager = ThemeManager()
