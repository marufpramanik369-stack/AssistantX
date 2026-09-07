"""
config.py
=========
The single entry point the rest of AssistantX should import from when it
needs "configuration" in the general sense. It composes the other
config/ submodules (constants, settings, secrets, theme, prompts,
env_loader) into one convenient `AppConfig` facade and handles the
correct bootstrap ORDER:

    1. Load .env into the process environment.
    2. Load secrets from the now-populated environment.
    3. Load persisted user settings from disk.
    4. Resolve the active theme from those settings.

Usage:
    from config.config import app_config

    app_config.bootstrap()
    print(app_config.secrets.summary())
    print(app_config.settings.ui.theme)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import constants
from config.env_loader import load_environment
from config.secrets import SecretsManager, secrets as _secrets_singleton
from config.settings import Settings, SettingsManager, settings_manager as _settings_singleton
from config.theme import Theme, ThemeManager, theme_manager as _theme_singleton

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """
    Facade object aggregating every configuration concern. Exists mainly
    for ergonomics — so callers can do `app_config.settings.ai.provider`
    instead of importing four different singletons individually — while
    still allowing direct submodule imports where that reads more clearly.
    """

    _bootstrapped: bool = False

    @property
    def secrets(self) -> SecretsManager:
        return _secrets_singleton

    @property
    def settings_manager(self) -> SettingsManager:
        return _settings_singleton

    @property
    def settings(self) -> Settings:
        return _settings_singleton.settings

    @property
    def theme_manager(self) -> ThemeManager:
        return _theme_singleton

    @property
    def theme(self) -> Theme:
        return _theme_singleton.active

    def bootstrap(self, strict_secrets: bool = False) -> None:
        """
        Perform the full configuration bootstrap sequence. Safe to call
        multiple times (idempotent) — subsequent calls just refresh state.

        Args:
            strict_secrets: If True, raises if any secret is missing.
                Should generally stay False for a personal assistant app
                where individual features degrade gracefully; set True
                for CI/production deployments that require full config.
        """
        logger.info("Bootstrapping %s v%s configuration...", constants.APP_NAME, constants.APP_VERSION)

        load_environment(quiet=False)
        self.secrets.reload()
        self.secrets.validate(strict=strict_secrets)

        self.settings_manager.load()
        self.theme_manager.refresh()

        self._bootstrapped = True
        logger.info(
            "Configuration bootstrap complete. Provider=%s Theme=%s",
            self.settings.ai.provider,
            self.theme.name,
        )

    def as_debug_dict(self) -> dict:
        """Return a redacted snapshot of the full config, useful for /debug views."""
        return {
            "app": {
                "name": constants.APP_NAME,
                "version": constants.APP_VERSION,
                "platform": constants.PLATFORM,
            },
            "secrets": self.secrets.summary(),
            "settings": self.settings_manager.as_dict(),
            "theme": self.theme_manager.to_dict()["name"],
        }


# Module-level singleton used throughout the application.
app_config: AppConfig = AppConfig()
