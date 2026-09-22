"""
AssistantX - Dark Theme
=======================

Centralized dark theme definition for the AssistantX dashboard.

This module contains no widget creation logic. It only defines
theme values so the UI remains modular and easy to maintain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class DarkColors:
    """AssistantX dark color palette."""

    # Application
    background: str = "#0B0F14"
    surface: str = "#11161D"
    surface_alt: str = "#171D25"
    surface_hover: str = "#1D2530"

    # Sidebar / Header
    sidebar: str = "#0E1319"
    sidebar_hover: str = "#171E27"
    header: str = "#10151C"

    # Chat
    chat_background: str = "#0B0F14"
    user_message: str = "#1F6FEB"
    user_message_hover: str = "#2878F0"
    assistant_message: str = "#151B23"
    assistant_message_hover: str = "#1B222C"

    # Text
    text_primary: str = "#F3F6FA"
    text_secondary: str = "#AAB4C0"
    text_muted: str = "#6F7B88"
    text_disabled: str = "#4B5561"

    # Accent
    accent: str = "#4F8CFF"
    accent_hover: str = "#6A9DFF"
    accent_active: str = "#3478F6"

    # Status
    success: str = "#35C759"
    warning: str = "#FFB020"
    error: str = "#FF5C5C"
    info: str = "#4F8CFF"

    # Borders
    border: str = "#242C36"
    border_light: str = "#303946"
    border_focus: str = "#4F8CFF"

    # Input
    input_background: str = "#121820"
    input_hover: str = "#171F29"
    input_focus: str = "#18212C"

    # Buttons
    button: str = "#1A222D"
    button_hover: str = "#232D39"
    button_active: str = "#2C3745"

    # Scrollbar
    scrollbar: str = "#202833"
    scrollbar_hover: str = "#2C3744"

    # Overlay
    overlay: str = "#000000"

    # Special
    online: str = "#35C759"
    offline: str = "#8A939E"
    recording: str = "#FF4D67"


@dataclass(frozen=True, slots=True)
class DarkTheme:
    """Complete AssistantX dark theme."""

    name: str = "dark"
    mode: str = "dark"

    colors: DarkColors = DarkColors()


COLORS: Final[DarkColors] = DarkColors()
THEME: Final[DarkTheme] = DarkTheme(colors=COLORS)


def get_colors() -> DarkColors:
    """Return the immutable dark color palette."""
    return COLORS


def get_theme() -> DarkTheme:
    """Return the complete dark theme."""
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
    "DarkColors",
    "DarkTheme",
    "get_colors",
    "get_theme",
    "to_dict",
]
