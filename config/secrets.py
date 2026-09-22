"""
AssistantX - Secrets Manager
============================

Centralized and secure access to sensitive credentials.

This module NEVER hard-codes real credentials.

Secrets are loaded exclusively from environment variables through
``config.env_loader`` and exposed through a typed singleton so the
rest of AssistantX never needs to access ``os.environ`` directly.

Security Features
-----------------
- No hard-coded secrets
- Environment-based configuration
- Redacted representations
- Thread-safe reload/access
- Optional and required secret validation
- Safe diagnostics
- Centralized environment-variable mapping
- Clear missing-secret errors
- No secret values written to logs

Recommended usage
-----------------

    from config.secrets import secrets

    if secrets.has("gemini_api_key"):
        api_key = secrets.gemini_api_key

Reload environment values:

    secrets.reload()

Validate configured credentials:

    missing = secrets.validate()

Strict validation:

    secrets.validate(strict=True)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, ClassVar

from config.constants import (
    DEFAULT_OLLAMA_HOST,
    ENV_GEMINI_API_KEY,
    ENV_NEWSAPI_KEY,
    ENV_OLLAMA_HOST,
    ENV_OPENWEATHER_API_KEY,
)
from config.env_loader import get_env, load_environment

logger = logging.getLogger(__name__)


# ============================================================
# EXCEPTIONS
# ============================================================

class SecretsError(RuntimeError):
    """Base exception for secrets-related errors."""


class MissingSecretError(SecretsError):
    """
    Raised when one or more required secrets are missing.
    """


class UnknownSecretError(SecretsError):
    """
    Raised when code requests an unknown secret name.
    """


# ============================================================
# HELPERS
# ============================================================

def _clean_secret(value: str | None) -> str | None:
    """
    Normalize a secret value.

    Empty strings are converted to None.
    """

    if value is None:
        return None

    value = str(value).strip()

    return value or None


def _clean_host(
    value: str | None,
    default: str,
) -> str:
    """
    Normalize a non-secret service host value.
    """

    if not value:
        return default

    value = str(value).strip()

    return value or default


def _redact(
    value: str | None,
    *,
    visible_prefix: int = 4,
    visible_suffix: int = 4,
) -> str:
    """
    Return a display-safe masked representation.

    Examples
    --------
    None:
        <unset>

    Short value:
        ********

    Longer value:
        abcd********wxyz
    """

    if not value:
        return "<unset>"

    value = str(value)

    visible_total = (
        visible_prefix + visible_suffix
    )

    if len(value) <= visible_total:
        return "*" * len(value)

    hidden_count = (
        len(value) - visible_total
    )

    return (
        value[:visible_prefix]
        + ("*" * hidden_count)
        + value[-visible_suffix:]
    )


# ============================================================
# SECRETS MANAGER
# ============================================================

@dataclass
class SecretsManager:
    """
    Typed, secure accessor for AssistantX credentials.

    All sensitive values are excluded from dataclass repr output.

    The module-level ``secrets`` instance should normally be used
    instead of creating additional instances.
    """

    gemini_api_key: str | None = field(
        default=None,
        repr=False,
    )

    openweather_api_key: str | None = field(
        default=None,
        repr=False,
    )

    newsapi_key: str | None = field(
        default=None,
        repr=False,
    )

    ollama_host: str = field(
        default=DEFAULT_OLLAMA_HOST,
        repr=False,
    )

    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
        compare=False,
    )

    # --------------------------------------------------------
    # Environment mapping
    # --------------------------------------------------------

    ENVIRONMENT_MAP: ClassVar[
        dict[str, str]
    ] = {
        "gemini_api_key": ENV_GEMINI_API_KEY,
        "openweather_api_key": ENV_OPENWEATHER_API_KEY,
        "newsapi_key": ENV_NEWSAPI_KEY,
        "ollama_host": ENV_OLLAMA_HOST,
    }

    # --------------------------------------------------------
    # Secret classification
    # --------------------------------------------------------

    SECRET_FIELDS: ClassVar[
        tuple[str, ...]
    ] = (
        "gemini_api_key",
        "openweather_api_key",
        "newsapi_key",
    )

    OPTIONAL_SECRETS: ClassVar[
        tuple[str, ...]
    ] = (
        "gemini_api_key",
        "openweather_api_key",
        "newsapi_key",
    )

    # None are globally mandatory because AssistantX can
    # gracefully fall back between providers/services.
    REQUIRED_SECRETS: ClassVar[
        tuple[str, ...]
    ] = ()


    # ========================================================
    # FACTORY
    # ========================================================

    @classmethod
    def load(
        cls,
        *,
        refresh_env: bool = True,
    ) -> SecretsManager:
        """
        Build a SecretsManager using current environment values.

        Args
        ----
        refresh_env:
            Reload the .env/environment configuration before
            reading values.

        Returns
        -------
        SecretsManager
            Newly populated manager.
        """

        if refresh_env:
            try:
                load_environment(
                    quiet=True
                )

            except OSError as exc:
                logger.warning(
                    "Environment reload failed: %s",
                    exc,
                )

        gemini_key = _clean_secret(
            get_env(
                ENV_GEMINI_API_KEY
            )
        )

        weather_key = _clean_secret(
            get_env(
                ENV_OPENWEATHER_API_KEY
            )
        )

        news_key = _clean_secret(
            get_env(
                ENV_NEWSAPI_KEY
            )
        )

        ollama_host = _clean_host(
            get_env(
                ENV_OLLAMA_HOST,
                default=DEFAULT_OLLAMA_HOST,
            ),
            DEFAULT_OLLAMA_HOST,
        )

        return cls(
            gemini_api_key=gemini_key,
            openweather_api_key=weather_key,
            newsapi_key=news_key,
            ollama_host=ollama_host,
        )


    # ========================================================
    # RELOAD
    # ========================================================

    def reload(
        self,
        *,
        refresh_env: bool = True,
    ) -> None:
        """
        Reload all credential values in-place.

        Existing imports of the module-level singleton continue
        to see the newly loaded values.
        """

        fresh = type(self).load(
            refresh_env=refresh_env
        )

        with self._lock:

            self.gemini_api_key = (
                fresh.gemini_api_key
            )

            self.openweather_api_key = (
                fresh.openweather_api_key
            )

            self.newsapi_key = (
                fresh.newsapi_key
            )

            self.ollama_host = (
                fresh.ollama_host
            )

        logger.info(
            "AssistantX secrets reloaded from environment."
        )


    # ========================================================
    # SECRET LOOKUP
    # ========================================================

    @classmethod
    def valid_names(cls) -> tuple[str, ...]:
        """
        Return all supported secret/configuration names.
        """

        return tuple(
            cls.ENVIRONMENT_MAP.keys()
        )


    def get(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """
        Safely return a configured value by name.

        Example
        -------

            secrets.get("gemini_api_key")
        """

        if not isinstance(name, str):
            return default

        key = name.strip()

        if key not in self.ENVIRONMENT_MAP:
            return default

        with self._lock:
            return getattr(
                self,
                key,
                default,
            )


    def require(
        self,
        name: str,
    ) -> str:
        """
        Return a secret value or raise MissingSecretError.

        This is useful when a specific feature absolutely requires
        one credential.

        Example
        -------

            api_key = secrets.require(
                "gemini_api_key"
            )
        """

        if name not in self.ENVIRONMENT_MAP:
            raise UnknownSecretError(
                f"Unknown secret: {name}"
            )

        value = self.get(name)

        if not value:
            env_name = self.ENVIRONMENT_MAP[
                name
            ]

            raise MissingSecretError(
                f"Required secret '{name}' is not configured. "
                f"Set environment variable '{env_name}'."
            )

        return str(value)


    # ========================================================
    # STATUS
    # ========================================================

    def has(
        self,
        name: str,
    ) -> bool:
        """
        Return True when a supported value is configured.
        """

        if name not in self.ENVIRONMENT_MAP:
            return False

        value = self.get(name)

        if value is None:
            return False

        if isinstance(value, str):
            return bool(
                value.strip()
            )

        return bool(value)


    def missing(
        self,
        names: tuple[str, ...] | list[str] | None = None,
    ) -> list[str]:
        """
        Return names of missing credentials.

        If names is omitted, all sensitive credential fields are
        checked.
        """

        targets = (
            tuple(names)
            if names is not None
            else self.SECRET_FIELDS
        )

        result: list[str] = []

        for name in targets:

            if name not in self.ENVIRONMENT_MAP:
                raise UnknownSecretError(
                    f"Unknown secret: {name}"
                )

            if not self.has(name):
                result.append(name)

        return result


    # ========================================================
    # VALIDATION
    # ========================================================

    def validate(
        self,
        *,
        strict: bool = False,
        required: tuple[str, ...] | list[str] | None = None,
    ) -> list[str]:
        """
        Validate configured credentials.

        Args
        ----
        strict:
            Raise MissingSecretError when required credentials
            are missing.

        required:
            Optional specific list of credentials that should be
            treated as mandatory.

            Example:

                secrets.validate(
                    strict=True,
                    required=[
                        "gemini_api_key"
                    ],
                )

        Returns
        -------
        list[str]
            Missing credential names.
        """

        required_names = (
            tuple(required)
            if required is not None
            else self.REQUIRED_SECRETS
        )

        # Validate requested secret names first.

        for name in required_names:
            if name not in self.ENVIRONMENT_MAP:
                raise UnknownSecretError(
                    f"Unknown secret: {name}"
                )

        missing_required = self.missing(
            list(required_names)
        )

        missing_optional = [
            name
            for name in self.OPTIONAL_SECRETS
            if (
                name not in required_names
                and not self.has(name)
            )
        ]

        for name in missing_optional:

            logger.warning(
                "Credential '%s' is not configured. "
                "Related AssistantX features may be unavailable "
                "or use fallback providers.",
                name,
            )

        if strict and missing_required:

            env_names = [
                self.ENVIRONMENT_MAP[name]
                for name in missing_required
            ]

            raise MissingSecretError(
                "Missing required credentials: "
                f"{', '.join(missing_required)}. "
                "Configure environment variables: "
                f"{', '.join(env_names)}."
            )

        # For backward compatibility, return every missing
        # sensitive credential.

        return self.missing()


    # ========================================================
    # REDACTED SUMMARY
    # ========================================================

    def summary(
        self,
        *,
        reveal_host: bool = True,
    ) -> dict[str, str]:
        """
        Return a log-safe status summary.

        Sensitive credentials are always redacted.
        """

        with self._lock:

            return {
                "gemini_api_key": _redact(
                    self.gemini_api_key
                ),

                "openweather_api_key": _redact(
                    self.openweather_api_key
                ),

                "newsapi_key": _redact(
                    self.newsapi_key
                ),

                "ollama_host": (
                    self.ollama_host
                    if reveal_host
                    else "<configured>"
                ),
            }

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    def diagnostics(
        self,
    ) -> dict[str, Any]:
        """
        Return safe diagnostics without exposing secret values.
        """

        with self._lock:

            configured = {
                name: self.has(name)
                for name in self.SECRET_FIELDS
            }

            missing = [
                name
                for name, available
                in configured.items()
                if not available
            ]

            return {
                "component": "SecretsManager",

                "status": (
                    "healthy"
                    if not self.REQUIRED_SECRETS
                    or all(
                        self.has(name)
                        for name
                        in self.REQUIRED_SECRETS
                    )
                    else "degraded"
                ),

                "configured": configured,

                "missing_optional": missing,

                "required": list(
                    self.REQUIRED_SECRETS
                ),

                "ollama_host_configured": bool(
                    self.ollama_host
                ),
            }


    # ========================================================
    # ENVIRONMENT NAME
    # ========================================================

    @classmethod
    def environment_name(
        cls,
        secret_name: str,
    ) -> str:
        """
        Return the environment variable associated with a field.

        Example:

            SecretsManager.environment_name(
                "gemini_api_key"
            )
        """

        try:
            return cls.ENVIRONMENT_MAP[
                secret_name
            ]

        except KeyError as exc:
            raise UnknownSecretError(
                f"Unknown secret: {secret_name}"
            ) from exc


    # ========================================================
    # SAFE REPRESENTATION
    # ========================================================

    def __repr__(self) -> str:
        """
        Safe developer representation.

        Real credential values are never exposed.
        """

        summary = self.summary()

        details = ", ".join(
            f"{key}={value}"
            for key, value
            in summary.items()
        )

        return (
            f"{self.__class__.__name__}"
            f"({details})"
        )


    __str__ = __repr__


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

secrets: SecretsManager = (
    SecretsManager.load()
)


# ============================================================
# CONVENIENCE HELPERS
# ============================================================

def get_secret(
    name: str,
    default: Any = None,
) -> Any:
    """
    Convenience wrapper for secrets.get().
    """

    return secrets.get(
        name,
        default,
    )


def require_secret(
    name: str,
) -> str:
    """
    Convenience wrapper for secrets.require().
    """

    return secrets.require(
        name
    )


def has_secret(
    name: str,
) -> bool:
    """
    Convenience wrapper for secrets.has().
    """

    return secrets.has(
        name
    )


def reload_secrets() -> None:
    """
    Reload secrets from the environment.
    """

    secrets.reload()


def diagnostics() -> dict[str, Any]:
    """
    Return safe secret-system diagnostics.
    """

    return secrets.diagnostics()


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "MissingSecretError",
    # Exceptions
    "SecretsError",
    # Manager
    "SecretsManager",
    "UnknownSecretError",
    "diagnostics",
    # Helpers
    "get_secret",
    "has_secret",
    "reload_secrets",
    "require_secret",
    # Singleton
    "secrets",
]
