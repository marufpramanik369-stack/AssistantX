"""
env_loader.py
=============
Responsible for locating, parsing, and loading environment variables from
a `.env` file into `os.environ`, without requiring the third-party
`python-dotenv` package (though it will use it if available, since it is
more robust). This keeps AssistantX bootable even in minimal environments.

Usage:
    from config.env_loader import load_environment
    load_environment()

Design notes:
    - Loading is idempotent: calling load_environment() multiple times is
      safe and will not clobber variables that were already explicitly
      set in the OS environment (OS env always wins over .env file,
      unless `override=True` is passed).
    - A very small hand-rolled parser is provided as a fallback so this
      module has zero hard dependencies.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LINE_PATTERN = re.compile(
    r"""
    ^\s*
    (?:export\s+)?              # optional 'export ' prefix (bash-style)
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*=\s*
    (?P<value>.*?)
    \s*$
    """,
    re.VERBOSE,
)

_loaded_files: set[Path] = set()


def _strip_inline_comment(value: str) -> str:
    """Remove trailing unquoted comments like `KEY=value # comment`."""
    if value.startswith(('"', "'")):
        return value
    hash_idx = value.find("#")
    if hash_idx != -1:
        return value[:hash_idx].rstrip()
    return value


def _unquote(value: str) -> str:
    """Strip matching surrounding quotes, handling simple escapes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace("\\n", "\n").replace('\\"', '"')
        return inner
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env-style file into a dict without external dependencies."""
    parsed: dict[str, str] = {}
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read env file %s: %s", path, exc)
        return parsed

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if not match:
            logger.debug("Skipping unparsable line %d in %s", line_number, path)
            continue
        key = match.group("key")
        value = _unquote(_strip_inline_comment(match.group("value")))
        parsed[key] = value

    return parsed


def load_environment(
    dotenv_path: Optional[Path] = None,
    override: bool = False,
    quiet: bool = False,
) -> dict[str, str]:
    """
    Load environment variables from a `.env` file into `os.environ`.

    Args:
        dotenv_path: Explicit path to the .env file. Defaults to
            `<project_root>/.env`.
        override: If True, values from the file overwrite existing
            OS environment variables. Defaults to False (OS wins).
        quiet: Suppress informational log messages.

    Returns:
        A dict of the key/value pairs that were parsed from the file
        (regardless of whether they were actually applied due to
        `override` rules).
    """
    from config.constants import DOTENV_PATH  # local import avoids cycle

    path = dotenv_path or DOTENV_PATH

    if not path.exists():
        if not quiet:
            logger.info(
                "No .env file found at %s — relying on OS environment "
                "variables and defaults only.",
                path,
            )
        return {}

    # Try python-dotenv first for maximum compatibility with edge cases.
    try:
        from dotenv import dotenv_values  # type: ignore

        parsed = dict(dotenv_values(path))
        parsed = {k: v for k, v in parsed.items() if v is not None}
    except ImportError:
        parsed = _parse_env_file(path)

    applied = 0
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
            applied += 1

    if not quiet:
        logger.info(
            "Loaded %d/%d environment variable(s) from %s (override=%s).",
            applied,
            len(parsed),
            path,
            override,
        )

    _loaded_files.add(path)
    return parsed


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """
    Fetch a single environment variable with optional strict enforcement.

    Args:
        key: Environment variable name.
        default: Value returned if the key is absent.
        required: If True, raises EnvironmentError when the key is missing
            and no default is provided.

    Returns:
        The string value, or `default` if not found.

    Raises:
        EnvironmentError: If `required=True` and the variable is unset.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Add it to your .env file or export it in your shell."
        )
    return value


def get_bool_env(key: str, default: bool = False) -> bool:
    """Parse an environment variable as a boolean (1/true/yes/on)."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def get_int_env(key: str, default: int = 0) -> int:
    """Parse an environment variable as an integer, falling back on error."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Env var %s=%r is not a valid int; using default %d", key, raw, default)
        return default


def get_float_env(key: str, default: float = 0.0) -> float:
    """Parse an environment variable as a float, falling back on error."""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Env var %s=%r is not a valid float; using default %.2f", key, raw, default)
        return default


def is_loaded(dotenv_path: Optional[Path] = None) -> bool:
    """Check whether a given .env path has already been loaded this run."""
    from config.constants import DOTENV_PATH

    return (dotenv_path or DOTENV_PATH) in _loaded_files
    