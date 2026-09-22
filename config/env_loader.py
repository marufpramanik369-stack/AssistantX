"""
AssistantX - Environment Loader
================================

Secure, dependency-light environment configuration loader.

Responsibilities
----------------
- Locate the AssistantX `.env` file
- Load environment variables safely
- Prefer OS environment variables by default
- Support optional python-dotenv integration
- Provide a dependency-free fallback parser
- Parse bool/int/float values
- Track loaded environment files
- Avoid logging sensitive values
- Provide diagnostics
- Remain compatible with config.secrets

Security
--------
This module loads configuration values but does not expose secret values
through logs or diagnostics.

Recommended usage
-----------------

    from config.env_loader import load_environment

    load_environment()

    from config.env_loader import get_env

    api_key = get_env("GEMINI_API_KEY")
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_ENV_FILENAME: Final[str] = ".env"

TRUE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "1",
        "true",
        "yes",
        "on",
        "y",
        "enabled",
    }
)

FALSE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "0",
        "false",
        "no",
        "off",
        "n",
        "disabled",
    }
)


# ============================================================
# REGEX
# ============================================================

_ENV_LINE_PATTERN = re.compile(
    r"""
    ^\s*
    (?:export\s+)?
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*=\s*
    (?P<value>.*?)
    \s*$
    """,
    re.VERBOSE,
)


# ============================================================
# STATE
# ============================================================

_state_lock = threading.RLock()

_loaded_files: set[Path] = set()

_load_count: int = 0

_last_loaded_path: Path | None = None

_last_error: str | None = None


# ============================================================
# PATH HELPERS
# ============================================================

def _resolve_path(
    path: Path | str,
) -> Path:
    """
    Normalize an environment-file path.

    The returned path is absolute and resolved where possible.
    """

    resolved = Path(path).expanduser()

    try:
        return resolved.resolve()
    except OSError:
        return resolved.absolute()


def _default_env_path() -> Path:
    """
    Return the default AssistantX `.env` path.

    Uses ``config.constants.DOTENV_PATH`` when available.
    """

    try:

        from config.constants import DOTENV_PATH

        return _resolve_path(
            DOTENV_PATH
        )

    except (ImportError, AttributeError):

        # Safe fallback for minimal environments.
        return _resolve_path(
            Path.cwd() / DEFAULT_ENV_FILENAME
        )


# ============================================================
# VALUE PARSING
# ============================================================

def _strip_inline_comment(
    value: str,
) -> str:
    """
    Remove unquoted inline comments.

    Example:

        KEY=value # comment

    becomes:

        value

    Hash characters inside quotes are preserved.
    """

    if not value:
        return ""

    quote: str | None = None

    escaped = False

    for index, char in enumerate(value):

        if escaped:

            escaped = False
            continue

        if char == "\\" and quote == '"':
            escaped = True
            continue

        if char in {"'", '"'}:

            if quote is None:
                quote = char

            elif quote == char:
                quote = None

            continue

        if (
            char == "#"
            and quote is None
            and (index == 0 or value[index - 1].isspace())
        ):
            return value[:index].rstrip()

    return value.rstrip()


def _unescape_double_quoted(
    value: str,
) -> str:
    """
    Handle common escape sequences in double-quoted values.
    """

    return (
        value
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _unquote(
    value: str,
) -> str:
    """
    Remove matching surrounding quotes.
    """

    value = value.strip()

    if len(value) < 2:
        return value

    first = value[0]
    last = value[-1]

    if first != last:
        return value

    if first not in {"'", '"'}:
        return value

    inner = value[1:-1]

    if first == '"':
        return _unescape_double_quoted(
            inner
        )

    # Single quotes are intentionally kept literal.
    return inner


def _expand_environment_reference(
    value: str,
) -> str:
    """
    Expand simple environment references.

    Supported:

        $HOME
        ${HOME}

    Existing environment variables are used.

    Unknown variables remain unchanged.
    """

    pattern = re.compile(
        r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
        r"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
    )

    def replace(
        match: re.Match[str],
    ) -> str:

        key = (
            match.group("braced")
            or match.group("plain")
        )

        return os.environ.get(
            key,
            match.group(0),
        )

    return pattern.sub(
        replace,
        value,
    )


def _parse_value(
    raw_value: str,
) -> str:
    """
    Parse and normalize one `.env` value.
    """

    value = _strip_inline_comment(
        raw_value
    )

    value = _unquote(
        value
    )



# ============================================================
# FALLBACK ENV PARSER
# ============================================================

def _parse_env_file(
    path: Path,
) -> dict[str, str]:
    """
    Parse a `.env` file without third-party dependencies.

    Supported:
        KEY=value
        KEY="value"
        KEY='value'
        export KEY=value
        inline comments
        basic $VAR / ${VAR} expansion
    """

    parsed: dict[str, str] = {}

    try:

        raw_text = path.read_text(
            encoding="utf-8"
        )

    except OSError as exc:

        logger.warning(
            "Could not read environment file %s: %s",
            path,
            exc,
        )

        return parsed

    for line_number, raw_line in enumerate(
        raw_text.splitlines(),
        start=1,
    ):

        line = raw_line.strip()

        # Empty line
        if not line:
            continue

        # Comment
        if line.startswith("#"):
            continue

        match = _ENV_LINE_PATTERN.match(
            line
        )

        if not match:

            logger.debug(
                "Skipping invalid .env line %d in %s",
                line_number,
                path,
            )

            continue

        key = match.group(
            "key"
        ).strip()

        raw_value = match.group(
            "value"
        )

        value = _parse_value(
            raw_value
        )

        value = _expand_environment_reference(
            value
        )

        parsed[key] = value

    return parsed


# ============================================================
# PYTHON-DOTENV LOADER
# ============================================================

def _load_with_python_dotenv(
    path: Path,
) -> dict[str, str] | None:
    """
    Attempt to parse the environment file using python-dotenv.

    Returns None when the package is unavailable.
    """

    try:

        from dotenv import dotenv_values  # type: ignore

    except ImportError:

        return None

    try:

        values = dotenv_values(
            dotenv_path=path
        )

        return {
            str(key): str(value)
            for key, value in values.items()
            if key is not None
            and value is not None
        }

    except (OSError, UnicodeError, ValueError) as exc:

        logger.warning(
            "python-dotenv failed to parse %s: %s. "
            "Using fallback parser.",
            path,
            exc,
        )

        return None


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

def load_environment(
    dotenv_path: Path | str | None = None,
    override: bool = False,
    quiet: bool = False,
) -> dict[str, str]:
    """
    Load environment variables from a `.env` file.

    Parameters
    ----------
    dotenv_path:
        Explicit `.env` path.

        If omitted, AssistantX's configured ``DOTENV_PATH`` is used.

    override:
        If False, existing OS environment variables win.

        If True, `.env` values replace existing values.

    quiet:
        Suppress informational logs.

    Returns
    -------
    dict[str, str]
        Parsed values from the `.env` file.

    Notes
    -----
    Parsed values are returned regardless of whether they were applied
    to ``os.environ``.
    """

    global _load_count
    global _last_loaded_path
    global _last_error

    path = _resolve_path(
        dotenv_path
        if dotenv_path is not None
        else _default_env_path()
    )

    with _state_lock:

        _load_count += 1

        _last_loaded_path = path

        _last_error = None

    if not path.exists():

        if not quiet:

            logger.info(
                "No .env file found at %s. "
                "Using OS environment and defaults.",
                path,
            )

        return {}

    if not path.is_file():

        message = (
            f"Environment path is not a file: {path}"
        )

        with _state_lock:
            _last_error = message

        logger.warning(
            message
        )

        return {}

    # --------------------------------------------------------
    # Try python-dotenv
    # --------------------------------------------------------

    parsed = _load_with_python_dotenv(
        path
    )

    # --------------------------------------------------------
    # Fallback parser
    # --------------------------------------------------------

    if parsed is None:

        parsed = _parse_env_file(
            path
        )

    # --------------------------------------------------------
    # Apply values
    # --------------------------------------------------------

    applied = 0

    for key, value in parsed.items():

        if override or key not in os.environ:

            os.environ[key] = value

            applied += 1

    # --------------------------------------------------------
    # Track loaded file
    # --------------------------------------------------------

    with _state_lock:

        _loaded_files.add(
            path
        )

    if not quiet:

        logger.info(
            "Loaded %d/%d environment variable(s) "
            "from %s (override=%s).",
            applied,
            len(parsed),
            path,
            override,
        )

    return parsed


# ============================================================
# ENV GETTERS
# ============================================================

def get_env(
    key: str,
    default: str | None = None,
    required: bool = False,
) -> str | None:
    """
    Fetch one environment variable.

    Parameters
    ----------
    key:
        Environment variable name.

    default:
        Fallback value.

    required:
        Raise EnvironmentError when the value is unavailable.

    Returns
    -------
    Optional[str]
        Environment value or default.
    """

    if not isinstance(key, str):
        raise TypeError(
            "Environment variable name must be a string."
        )

    key = key.strip()

    if not key:
        raise ValueError(
            "Environment variable name cannot be empty."
        )

    value = os.environ.get(
        key
    )

    if value is None:

        if required and default is None:

            raise OSError(
                f"Required environment variable "
                f"'{key}' is not set."
            )

        return default

    value = value.strip()

    if not value:

        if required and default is None:

            raise OSError(
                f"Required environment variable "
                f"'{key}' is empty."
            )

        return default

    return value


# ============================================================
# BOOLEAN
# ============================================================

def get_bool_env(
    key: str,
    default: bool = False,
) -> bool:
    """
    Parse an environment variable as a boolean.

    Accepted true values:
        1, true, yes, on, y, enabled

    Accepted false values:
        0, false, no, off, n, disabled

    Unknown values return the supplied default.
    """

    raw = get_env(
        key
    )

    if raw is None:
        return default

    normalized = raw.strip().lower()

    if normalized in TRUE_VALUES:
        return True

    if normalized in FALSE_VALUES:
        return False

    logger.warning(
        "Environment variable %s contains an invalid boolean value. "
        "Using default.",
        key,
    )

    return default


# ============================================================
# INTEGER
# ============================================================

def get_int_env(
    key: str,
    default: int = 0,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Parse an environment variable as an integer.

    Optional minimum/maximum bounds can be supplied.
    """

    raw = get_env(
        key
    )

    if raw is None:
        return default

    try:

        value = int(
            raw.strip()
        )

    except (TypeError, ValueError):

        logger.warning(
            "Environment variable %s is not a valid integer. "
            "Using default.",
            key,
        )

        return default

    if minimum is not None:
        value = max(
            minimum,
            value,
        )

    if maximum is not None:
        value = min(
            maximum,
            value,
        )

    return value


# ============================================================
# FLOAT
# ============================================================

def get_float_env(
    key: str,
    default: float = 0.0,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """
    Parse an environment variable as a floating-point number.
    """

    raw = get_env(
        key
    )

    if raw is None:
        return default

    try:

        value = float(
            raw.strip()
        )

    except (TypeError, ValueError):

        logger.warning(
            "Environment variable %s is not a valid float. "
            "Using default.",
            key,
        )

        return default

    if minimum is not None:
        value = max(
            minimum,
            value,
        )

    if maximum is not None:
        value = min(
            maximum,
            value,
        )

    return value


# ============================================================
# LOADED STATE
# ============================================================

def is_loaded(
    dotenv_path: Path | str | None = None,
) -> bool:
    """
    Check whether a `.env` path has already been loaded.
    """

    path = _resolve_path(
        dotenv_path
        if dotenv_path is not None
        else _default_env_path()
    )

    with _state_lock:

        return path in _loaded_files


def loaded_files() -> list[Path]:
    """
    Return all environment files loaded during this process.
    """

    with _state_lock:

        return sorted(
            _loaded_files,
            key=str,
        )


# ============================================================
# SECRET-SAFE STATUS
# ============================================================

def environment_exists(
    key: str,
) -> bool:
    """
    Return True when an environment variable exists and is non-empty.

    The actual value is never returned.
    """

    value = get_env(
        key
    )

    return bool(
        value
    )


# ============================================================
# DIAGNOSTICS
# ============================================================

def diagnostics() -> dict[str, object]:
    """
    Return safe environment-loader diagnostics.

    Environment values are intentionally excluded.
    """

    with _state_lock:

        path = _default_env_path()

        return {
            "component": "EnvironmentLoader",
            "status": (
                "healthy"
                if _last_error is None
                else "degraded"
            ),
            "default_env_path": str(path),
            "default_env_exists": path.exists(),
            "default_env_is_file": (
                path.is_file()
                if path.exists()
                else False
            ),
            "loaded": path in _loaded_files,
            "loaded_files": [
                str(item)
                for item in sorted(
                    _loaded_files,
                    key=str,
                )
            ],
            "load_count": _load_count,
            "last_loaded_path": (
                str(_last_loaded_path)
                if _last_loaded_path
                else None
            ),
            "last_error": _last_error,
            "python_dotenv_available": (
                _python_dotenv_available()
            ),
        }


def _python_dotenv_available() -> bool:
    """
    Check whether python-dotenv is installed.

    No import error is exposed to the caller.
    """

    try:

        import dotenv  # type: ignore

        return dotenv is not None

    except ImportError:

        return False


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    # Constants
    "DEFAULT_ENV_FILENAME",
    "FALSE_VALUES",
    "TRUE_VALUES",
    # Diagnostics
    "diagnostics",
    "environment_exists",
    "get_bool_env",
    # Getters
    "get_env",
    "get_float_env",
    "get_int_env",
    # Status
    "is_loaded",
    # Loading
    "load_environment",
    "loaded_files",
]
