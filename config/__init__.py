"""
config
======

AssistantX configuration package.

This package provides a clean public API for accessing the application's
configuration layer.

Common usage
------------

    from config import (
        app_config,
        settings_manager,
        secrets,
        theme_manager,
    )

    app_config.bootstrap()

    print(settings_manager.settings.ai.provider)
    print(theme_manager.active.name)

Architecture
------------

The configuration layer is intentionally separated into:

    constants.py
        Immutable application constants and paths.

    env_loader.py
        Environment / `.env` loading utilities.

    secrets.py
        API keys, credentials, and other sensitive configuration.

    settings.py
        Runtime-mutable user/application preferences.

    theme.py
        UI theme definitions and theme management.

    prompts.py
        AI system/persona prompt definitions.

    config.py
        High-level `AppConfig` facade and bootstrap orchestration.

Only commonly used objects are exported from this package root.
Specialized APIs should normally be imported from their defining module.
"""

from __future__ import annotations

# ============================================================================
# Package Metadata
# ============================================================================

__package_name__: str = "config"
__version_schema__: int = 1


# ============================================================================
# Public Configuration Facade
# ============================================================================

from config.config import (
    AppConfig,
    BootstrapState,
    ConfigBootstrapError,
    ConfigError,
    app_config,
    bootstrap_config,
    get_config,
    is_config_ready,
)

# ============================================================================
# Secrets
# ============================================================================
from config.secrets import (
    MissingSecretError,
    SecretsManager,
    secrets,
)

# ============================================================================
# Settings
# ============================================================================
from config.settings import (
    Settings,
    SettingsManager,
    settings_manager,
)

# ============================================================================
# Theme
# ============================================================================
from config.theme import (
    Theme,
    ThemeManager,
    theme_manager,
)

# ============================================================================
# Package Public API
# ============================================================================

__all__: list[str] = [
    "AppConfig",
    "BootstrapState",
    "ConfigBootstrapError",
    "ConfigError",
    "MissingSecretError",
    "SecretsManager",
    "Settings",
    "SettingsManager",
    "Theme",
    "ThemeManager",
    "__package_name__",
    "__version_schema__",
    "app_config",
    "bootstrap_config",
    "get_config",
    "is_config_ready",
    "secrets",
    "settings_manager",
    "theme_manager",
]


# ============================================================================
# Package-Level Helpers
# ============================================================================

def bootstrap(
    *,
    strict_secrets: bool = False,
    force: bool = False,
) -> bool:
    """
    Bootstrap the complete AssistantX configuration.

    This is a convenience wrapper around:

        config.app_config.bootstrap()

    Example
    -------
        from config import bootstrap

        bootstrap()
    """

    return app_config.bootstrap(
        strict_secrets=strict_secrets,
        force=force,
    )


def diagnostics() -> dict:
    """
    Return a configuration health/diagnostic snapshot.

    Example
    -------
        from config import diagnostics

        print(diagnostics())
    """

    return app_config.diagnostics()


def is_ready() -> bool:
    """
    Return True when the configuration system is fully bootstrapped.

    Example
    -------
        from config import is_ready

        if is_ready():
            ...
    """

    return app_config.bootstrapped


__all__.extend(
    [
        "bootstrap",
        "diagnostics",
        "is_ready",
    ]
)
