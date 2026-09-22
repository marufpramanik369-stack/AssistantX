"""
AssistantX - Light Theme
========================

Centralized light theme definition for the AssistantX dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class LightColors:
    """AssistantX light color palette."""

    # Application
    background: str = "#F7F9FC"
    surface: str = "#FFFFFF"
    surface_alt: str = "#F1F4F8"
    surface_hover: str = "#E9EDF3"

    # Sidebar / Header
    sidebar: str = "#F3F6FA"
    sidebar_hover: str = "#E7EBF1"
    header: str = "#FFFFFF"

    # Chat
    chat_background: str = "#F7F9FC"
    user_message: str = "#2F75ED"
    user_message_hover: str = "#286BE0"
    assistant_message: str = "#FFFFFF"
    assistant_message_hover: str = "#F4F6F9"

    # Text
    text_primary: str = "#17202B"
    text_secondary: str = "#586574"
    text_muted: str = "#7B8794"
    text_disabled: str = "#AAB3BD"

    # Accent
    accent: str = "#3478F6"
    accent_hover: str = "#286BE0"
    accent_active: str = "#1F60D0"

    # Status
    success: str = "#249A46"
    warning: str = "#C98200"
    error: str = "#D9363E"
    info: str = "#3478F6"

    # Borders
    border: str = "#DDE3EA"
    border_light: str = "#E8ECF1"
    border_focus: str = "#3478F6"

    # Input
    input_background: str = "#FFFFFF"
    input_hover: str = "#F7F9FC"
    input_focus: str = "#FFFFFF"

    # Buttons
    button: str = "#EEF2F6"
    button_hover: str = "#E3E8EE"
    button_active: str = "#D9E0E8"

    # Scrollbar
    scrollbar: str = "#D4DBE3"
    scrollbar_hover: str = "#BCC6D1"

    # Overlay
    overlay: str = "#000000"

    # Special
    online: str = "#249A46"
    offline: str = "#8A939E"
    recording: str = "#D93657"


@dataclass(frozen=True, slots=True)
class LightTheme:
    """Complete AssistantX light theme."""

    name: str = "light"
    mode: str = "light"

    colors: LightColors = LightColors()


COLORS: Final[LightColors] = LightColors()
THEME: Final[LightTheme] = LightTheme(colors=COLORS)


def get_colors() -> LightColors:
    """Return the immutable light color palette."""
    return COLORS


def get_theme() -> LightTheme:
    """Return the complete light theme."""
    return THEME


def to_dict() -> dict[str, object]:
    """Return a serializable theme dictionary."""
    return {
        "name": THEME.name,
        "mode": THEME.mode,
        "colors": dict(COLORS.__dict__),
    }


__all__ = [
    "COLORS",
    "THEME",
    "LightColors",
    "LightTheme",
    "get_colors",
    "get_theme",
    "to_dict",
]
