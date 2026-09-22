"""
AssistantX - Animation Theme
============================

Centralized animation and transition configuration.

Keeping animation values separate from widgets makes the dashboard
easy to tune without modifying UI implementation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class AnimationTheme:
    """Global AssistantX animation configuration."""

    # General
    enabled: bool = True
    reduced_motion: bool = False

    # Timing
    instant: int = 0
    fast: int = 120
    normal: int = 200
    medium: int = 300
    slow: int = 450
    very_slow: int = 700

    # Sidebar
    sidebar_expand: int = 250
    sidebar_collapse: int = 220

    # Chat
    message_enter: int = 180
    message_exit: int = 140
    typing_interval: int = 450

    # Window
    window_fade: int = 220
    splash_duration: int = 1000

    # Transitions
    transition_duration: int = 250
    hover_duration: int = 120

    # Particles
    particle_enabled: bool = True
    particle_count: int = 35
    particle_speed: float = 0.6

    # Effects
    glow_enabled: bool = True
    shadow_enabled: bool = True
    blur_enabled: bool = False

    # FPS
    target_fps: int = 60


THEME: Final[AnimationTheme] = AnimationTheme()


def get_animation_theme() -> AnimationTheme:
    """Return the global animation configuration."""
    return THEME


def animation_duration(
    speed: str = "normal",
) -> int:
    """
    Return an animation duration by name.

    Supported:
        instant
        fast
        normal
        medium
        slow
        very_slow
    """

    value = getattr(THEME, speed, None)

    if not isinstance(value, int):
        return THEME.normal

    return max(0, value)


def is_animation_enabled() -> bool:
    """Return whether animations are enabled."""
    return THEME.enabled and not THEME.reduced_motion


__all__ = [
    "THEME",
    "AnimationTheme",
    "animation_duration",
    "get_animation_theme",
    "is_animation_enabled",
]
