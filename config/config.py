"""
config/config.py
================

Central configuration facade for AssistantX.

This module provides a single, convenient entry point for application
configuration while keeping individual configuration concerns separated.

Bootstrap order
---------------
    1. Load `.env` into the process environment.
    2. Load/reload secrets from environment variables.
    3. Validate secrets according to the selected strictness.
    4. Load persisted application settings.
    5. Resolve/refresh the active theme.

Usage
-----
    from config.config import app_config

    app_config.bootstrap()

    print(app_config.settings.ai.provider)
    print(app_config.theme.name)
    print(app_config.secrets.summary())

Design goals
------------
- Thread-safe
- Idempotent bootstrap
- Safe for repeated refreshes
- Graceful failure in non-strict mode
- Strict validation when requested
- No secret leakage
- Useful diagnostics for the dashboard/debug system
- Backward compatible with existing AssistantX modules
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

from config import constants
from config.env_loader import load_environment
from config.secrets import (
    SecretsManager,
    secrets as _secrets_singleton,
)
from config.settings import (
    Settings,
    SettingsManager,
    settings_manager as _settings_singleton,
)
from config.theme import (
    Theme,
    ThemeManager,
    theme_manager as _theme_singleton,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class ConfigError(RuntimeError):
    """Base exception for AssistantX configuration errors."""


class ConfigBootstrapError(ConfigError):
    """Raised when the configuration bootstrap process fails."""


# ============================================================================
# Bootstrap State
# ============================================================================


@dataclass(slots=True)
class BootstrapState:
    """
    Runtime state of the configuration facade.

    This is diagnostic/runtime state, not persisted application settings.
    """

    bootstrapped: bool = False
    bootstrap_count: int = 0

    last_bootstrap_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None

    environment_loaded: bool = False
    secrets_loaded: bool = False
    settings_loaded: bool = False
    theme_loaded: bool = False

    strict_mode: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly state representation."""

        return {
            "bootstrapped": self.bootstrapped,
            "bootstrap_count": self.bootstrap_count,
            "last_bootstrap_at": (
                self.last_bootstrap_at.isoformat()
                if self.last_bootstrap_at
                else None
            ),
            "last_success_at": (
                self.last_success_at.isoformat()
                if self.last_success_at
                else None
            ),
            "last_error": self.last_error,
            "environment_loaded": self.environment_loaded,
            "secrets_loaded": self.secrets_loaded,
            "settings_loaded": self.settings_loaded,
            "theme_loaded": self.theme_loaded,
            "strict_mode": self.strict_mode,
        }


# ============================================================================
# AppConfig
# ============================================================================


@dataclass
class AppConfig:
    """
    Central configuration facade for AssistantX.

    The facade exposes:

        app_config.constants
        app_config.secrets
        app_config.settings_manager
        app_config.settings
        app_config.theme_manager
        app_config.theme

    Configuration sources remain separated internally, while application
    code gets one convenient access point.
    """

    _bootstrapped: bool = field(default=False, init=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _state: BootstrapState = field(
        default_factory=BootstrapState,
        init=False,
        repr=False,
    )

    # --------------------------------------------------------------------- #
    # Configuration accessors
    # --------------------------------------------------------------------- #

    @property
    def constants(self):
        """
        Access immutable application constants.

        Example:
            app_config.constants.APP_NAME
        """
        return constants

    @property
    def secrets(self) -> SecretsManager:
        """Return the global secrets manager."""
        return _secrets_singleton

    @property
    def settings_manager(self) -> SettingsManager:
        """Return the global settings manager."""
        return _settings_singleton

    @property
    def settings(self) -> Settings:
        """Return the currently loaded application settings."""
        return _settings_singleton.settings

    @property
    def theme_manager(self) -> ThemeManager:
        """Return the global theme manager."""
        return _theme_singleton

    @property
    def theme(self) -> Theme:
        """Return the currently active theme."""
        return _theme_singleton.active

    # --------------------------------------------------------------------- #
    # State
    # --------------------------------------------------------------------- #

    @property
    def bootstrapped(self) -> bool:
        """Return True when configuration has successfully bootstrapped."""
        with self._lock:
            return self._bootstrapped

    @property
    def state(self) -> BootstrapState:
        """
        Return a snapshot of the current bootstrap state.

        A copy is returned so callers cannot mutate internal state.
        """
        with self._lock:
            current = self._state

            return BootstrapState(
                bootstrapped=current.bootstrapped,
                bootstrap_count=current.bootstrap_count,
                last_bootstrap_at=current.last_bootstrap_at,
                last_success_at=current.last_success_at,
                last_error=current.last_error,
                environment_loaded=current.environment_loaded,
                secrets_loaded=current.secrets_loaded,
                settings_loaded=current.settings_loaded,
                theme_loaded=current.theme_loaded,
                strict_mode=current.strict_mode,
            )

    # --------------------------------------------------------------------- #
    # Bootstrap
    # --------------------------------------------------------------------- #

    def bootstrap(
        self,
        *,
        strict_secrets: bool = False,
        force: bool = False,
    ) -> bool:
        """
        Bootstrap the complete AssistantX configuration.

        Order:

            1. Environment
            2. Secrets
            3. Settings
            4. Theme

        Args:
            strict_secrets:
                If True, missing/invalid required secrets raise an error.

            force:
                If True, perform the full bootstrap even if configuration
                has already been initialized.

        Returns:
            True when bootstrap succeeds.

        Raises:
            ConfigBootstrapError:
                If a required bootstrap step fails.
        """

        with self._lock:
            if self._bootstrapped and not force:
                logger.debug(
                    "Configuration already bootstrapped; skipping."
                )
                return True

            started_at = datetime.now(timezone.utc)

            self._state.bootstrap_count += 1
            self._state.last_bootstrap_at = started_at
            self._state.last_error = None
            self._state.strict_mode = strict_secrets

            # Reset individual stage flags before a fresh bootstrap.
            self._state.environment_loaded = False
            self._state.secrets_loaded = False
            self._state.settings_loaded = False
            self._state.theme_loaded = False

            logger.info(
                "Bootstrapping %s v%s configuration...",
                constants.APP_NAME,
                constants.APP_VERSION,
            )

            try:
                # --------------------------------------------------------- #
                # 1. Environment
                # --------------------------------------------------------- #

                load_environment(quiet=False)

                self._state.environment_loaded = True

                logger.debug("Environment configuration loaded.")

                # --------------------------------------------------------- #
                # 2. Secrets
                # --------------------------------------------------------- #

                self.secrets.reload()

                self._state.secrets_loaded = True

                self.secrets.validate(
                    strict=strict_secrets
                )

                logger.debug(
                    "Secrets loaded and validated. strict=%s",
                    strict_secrets,
                )

                # --------------------------------------------------------- #
                # 3. Persisted settings
                # --------------------------------------------------------- #

                self.settings_manager.load()

                self._state.settings_loaded = True

                logger.debug("Application settings loaded.")

                # --------------------------------------------------------- #
                # 4. Active theme
                # --------------------------------------------------------- #

                self.theme_manager.refresh()

                self._state.theme_loaded = True

                logger.debug(
                    "Active theme resolved: %s",
                    self.theme.name,
                )

                # --------------------------------------------------------- #
                # Success
                # --------------------------------------------------------- #

                self._bootstrapped = True
                self._state.bootstrapped = True
                self._state.last_success_at = (
                    datetime.now(timezone.utc)
                )

                logger.info(
                    "Configuration bootstrap complete. "
                    "Provider=%s Theme=%s",
                    self.settings.ai.provider,
                    self.theme.name,
                )

                return True

            except (AttributeError, TypeError, ValueError) as exc:
                self._bootstrapped = False
                self._state.bootstrapped = False
                self._state.last_error = str(exc)

                logger.exception(
                    "AssistantX configuration bootstrap failed."
                )

                if isinstance(exc, ConfigError):
                    raise

                raise ConfigBootstrapError(
                    f"Failed to bootstrap {constants.APP_NAME} "
                    f"configuration: {exc}"
                ) from exc

    # --------------------------------------------------------------------- #
    # Refresh
    # --------------------------------------------------------------------- #

    def refresh(
        self,
        *,
        strict_secrets: bool = False,
    ) -> bool:
        """
        Force a complete configuration refresh.

        Useful after:
            - Editing `.env`
            - Changing settings
            - Switching theme
            - Updating provider configuration
        """

        logger.info("Refreshing AssistantX configuration...")

        return self.bootstrap(
            strict_secrets=strict_secrets,
            force=True,
        )

    # --------------------------------------------------------------------- #
    # Ensure Ready
    # --------------------------------------------------------------------- #

    def ensure_bootstrapped(
        self,
        *,
        strict_secrets: bool = False,
    ) -> bool:
        """
        Ensure configuration is initialized.

        This is convenient for services that may be called before the
        normal application startup sequence.
        """

        if self.bootstrapped:
            return True

        return self.bootstrap(
            strict_secrets=strict_secrets
        )

    # --------------------------------------------------------------------- #
    # Debug Snapshot
    # --------------------------------------------------------------------- #

    def as_debug_dict(self) -> dict[str, Any]:
        """
        Return a safe, diagnostic snapshot of application configuration.

        Secrets are delegated to `SecretsManager.summary()`, which is
        expected to return redacted information only.

        This method must never expose raw API keys/passwords/tokens.
        """

        with self._lock:
            try:
                settings_snapshot = self.settings_manager.as_dict()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not serialize settings for debug snapshot: %s",
                    exc,
                )
                settings_snapshot = {
                    "error": "settings_unavailable"
                }

            try:
                secret_snapshot = self.secrets.summary()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not serialize secrets summary: %s",
                    exc,
                )
                secret_snapshot = {
                    "error": "secrets_unavailable"
                }

            try:
                theme_snapshot = self.theme_manager.to_dict()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Could not serialize theme information: %s",
                    exc,
                )
                theme_snapshot = {
                    "error": "theme_unavailable"
                }

            return {
                "app": {
                    "name": constants.APP_NAME,
                    "version": constants.APP_VERSION,
                    "codename": constants.APP_CODENAME,
                    "platform": constants.PLATFORM,
                    "platform_name": constants.PLATFORM_NAME,
                },
                "bootstrap": self._state.as_dict(),
                "secrets": secret_snapshot,
                "settings": settings_snapshot,
                "theme": theme_snapshot,
            }

    # --------------------------------------------------------------------- #
    # Diagnostics
    # --------------------------------------------------------------------- #

    def diagnostics(self) -> dict[str, Any]:
        """
        Return a lightweight configuration health report.

        Intended for:
            - Dashboard diagnostics
            - `/debug`
            - Logging
            - Automated tests
        """

        with self._lock:
            checks: dict[str, bool] = {
                "environment": self._state.environment_loaded,
                "secrets": self._state.secrets_loaded,
                "settings": self._state.settings_loaded,
                "theme": self._state.theme_loaded,
            }

            return {
                "healthy": (
                    self._bootstrapped
                    and all(checks.values())
                ),
                "bootstrapped": self._bootstrapped,
                "checks": checks,
                "provider": self._safe_provider_name(),
                "theme": self._safe_theme_name(),
                "state": self._state.as_dict(),
            }

    def _safe_provider_name(self) -> str | None:
        """Safely retrieve the configured AI provider name."""

        try:
            provider = self.settings.ai.provider

            if hasattr(provider, "value"):
                return str(provider.value)

            return str(provider)

        except AttributeError:
            return None

    def _safe_theme_name(self) -> str | None:
        """Safely retrieve the active theme name."""

        try:
            return str(self.theme.name)
        except AttributeError:
            return None

    # --------------------------------------------------------------------- #
    # Reset Runtime State
    # --------------------------------------------------------------------- #

    def reset_runtime_state(self) -> None:
        """
        Reset only AppConfig's runtime bootstrap state.

        This does NOT:
            - Delete settings
            - Delete secrets
            - Delete database files
            - Delete user data

        It simply marks the facade as requiring bootstrap again.
        """

        with self._lock:
            logger.debug(
                "Resetting AppConfig runtime bootstrap state."
            )

            self._bootstrapped = False
            self._state = BootstrapState()

    # --------------------------------------------------------------------- #
    # Context Manager
    # --------------------------------------------------------------------- #

    def __enter__(self) -> Self:
        """Enter configuration context and ensure bootstrap."""
        self.ensure_bootstrapped()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> bool:
        """
        Leave configuration context.

        Configuration itself is intentionally not destroyed because the
        global managers may still be used by the application.
        """
        # Do not suppress exceptions raised inside the configuration context.
        return False


# ============================================================================
# Global Singleton
# ============================================================================

app_config: AppConfig = AppConfig()


# ============================================================================
# Convenience Helpers
# ============================================================================


def bootstrap_config(
    *,
    strict_secrets: bool = False,
    force: bool = False,
) -> bool:
    """
    Convenience wrapper around `app_config.bootstrap()`.

    Example:
        from config.config import bootstrap_config

        bootstrap_config()
    """

    return app_config.bootstrap(
        strict_secrets=strict_secrets,
        force=force,
    )


def get_config() -> AppConfig:
    """Return the global AssistantX configuration facade."""
    return app_config


def is_config_ready() -> bool:
    """Return True if configuration has completed successfully."""
    return app_config.bootstrapped


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "AppConfig",
    "BootstrapState",
    "ConfigBootstrapError",
    "ConfigError",
    "app_config",
    "bootstrap_config",
    "get_config",
    "is_config_ready",
]
