"""
config
======
Configuration package for AssistantX.

Exposes the most commonly needed objects at the package level so callers
can write:

    from config import app_config, settings_manager, secrets, theme_manager

instead of reaching into individual submodules. Deeper/rarer APIs (e.g.
specific dataclasses like `VoiceSettings`) should still be imported from
their defining submodule directly.
"""

from __future__ import annotations

from config.config import AppConfig, app_config
from config.secrets import MissingSecretError, SecretsManager, secrets
from config.settings import Settings, SettingsManager, settings_manager
from config.theme import Theme, ThemeManager, theme_manager

__all__ = [
    "AppConfig",
    "app_config",
    "SecretsManager",
    "MissingSecretError",
    "secrets",
    "Settings",
    "SettingsManager",
    "settings_manager",
    "Theme",
    "ThemeManager",
    "theme_manager",
]

__version_schema__ = 1
