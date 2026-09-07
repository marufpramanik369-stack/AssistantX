"""
secrets.py
==========
Centralizes access to all sensitive credentials (API keys, tokens).

This module NEVER hard-codes a real secret. Values are always sourced
from environment variables (populated via env_loader.load_environment()),
and are exposed here as a single, typed, importable object so the rest
of the codebase never touches `os.environ` directly for secrets.

Security notes:
    - `.env` must be listed in `.gitignore` (it is, by default).
    - `__repr__`/`__str__` on SecretsManager intentionally redact values
      so secrets never leak into logs or tracebacks accidentally.
    - Call `SecretsManager.validate()` at startup to fail fast with a
      clear error message if required keys are missing, instead of
      failing deep inside an HTTP call later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Optional

from config.constants import (
    ENV_GEMINI_API_KEY,
    ENV_NEWSAPI_KEY,
    ENV_OLLAMA_HOST,
    ENV_OPENWEATHER_API_KEY,
    DEFAULT_OLLAMA_HOST,
)
from config.env_loader import get_env, load_environment

logger = logging.getLogger(__name__)


class MissingSecretError(RuntimeError):
    """Raised when a required secret is absent at validation time."""


def _redact(value: Optional[str]) -> str:
    """Return a display-safe, masked representation of a secret value."""
    if not value:
        return "<unset>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


@dataclass
class SecretsManager:
    """
    Typed accessor for every secret AssistantX might need.

    Instantiate once (see `secrets` singleton at the bottom of this file)
    and import that singleton elsewhere:

        from config.secrets import secrets
        api_key = secrets.gemini_api_key
    """

    gemini_api_key: Optional[str] = field(default=None, repr=False)
    openweather_api_key: Optional[str] = field(default=None, repr=False)
    newsapi_key: Optional[str] = field(default=None, repr=False)
    ollama_host: str = field(default=DEFAULT_OLLAMA_HOST, repr=False)

    # Keys considered mandatory for a "full" installation. Individual
    # features degrade gracefully if their specific key is missing, but
    # validate() can be called with strict=True to enforce all of them.
    _OPTIONAL_KEYS: tuple[str, ...] = field(
        default=("gemini_api_key", "openweather_api_key", "newsapi_key"),
        repr=False,
        compare=False,
    )

    @classmethod
    def load(cls, refresh_env: bool = True) -> "SecretsManager":
        """
        Build a SecretsManager from the current environment.

        Args:
            refresh_env: If True, (re)loads the .env file before reading
                values, so callers don't need to call load_environment()
                separately.
        """
        if refresh_env:
            load_environment(quiet=True)

        return cls(
            gemini_api_key=get_env(ENV_GEMINI_API_KEY),
            openweather_api_key=get_env(ENV_OPENWEATHER_API_KEY),
            newsapi_key=get_env(ENV_NEWSAPI_KEY),
            ollama_host=get_env(ENV_OLLAMA_HOST, default=DEFAULT_OLLAMA_HOST) or DEFAULT_OLLAMA_HOST,
        )

    def reload(self) -> None:
        """Re-read all secrets from the environment in-place."""
        fresh = SecretsManager.load(refresh_env=True)
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            setattr(self, f.name, getattr(fresh, f.name))
        logger.info("Secrets reloaded from environment.")

    def has(self, name: str) -> bool:
        """Check whether a given secret attribute is populated."""
        return bool(getattr(self, name, None))

    def validate(self, strict: bool = False) -> list[str]:
        """
        Check for missing secrets.

        Args:
            strict: If True, raises MissingSecretError when any secret
                (including optional ones) is missing. If False, only
                logs warnings for missing optional secrets and returns
                the list of missing names.

        Returns:
            List of attribute names that are currently unset.
        """
        missing = [
            f.name
            for f in fields(self)
            if not f.name.startswith("_") and not getattr(self, f.name)
            and f.name != "ollama_host"  # has a hard default, never "missing"
        ]

        for name in missing:
            logger.warning(
                "Secret '%s' is not configured. Related features will be "
                "disabled or will fall back to alternatives.",
                name,
            )

        if strict and missing:
            raise MissingSecretError(
                f"Missing required secrets: {', '.join(missing)}. "
                f"Populate them in your .env file (see .env.example)."
            )

        return missing

    def summary(self) -> dict[str, str]:
        """Return a redacted, log-safe summary of all secrets' status."""
        return {
            "gemini_api_key": _redact(self.gemini_api_key),
            "openweather_api_key": _redact(self.openweather_api_key),
            "newsapi_key": _redact(self.newsapi_key),
            "ollama_host": self.ollama_host,  # not sensitive, shown in full
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic only
        redacted = ", ".join(f"{k}={v}" for k, v in self.summary().items())
        return f"SecretsManager({redacted})"

    __str__ = __repr__


# Module-level singleton — import this everywhere instead of constructing
# a new SecretsManager, so the whole app shares one consistent view.
secrets: SecretsManager = SecretsManager.load()
