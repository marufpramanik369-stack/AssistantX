"""
core/utils.py — General-Purpose Utility Helpers for AssistantX

======================================================================

Dependency-light utility layer used across AssistantX.

DESIGN GOALS
============

• No imports from other AssistantX modules.
• No import-time application initialization.
• Thread-safe by design.
• Defensive input validation.
• Cross-platform pathlib-based filesystem handling.
• Atomic JSON persistence where requested.
• Clear, stable exception types.
• Backward-compatible public helper API.
• Suitable for Windows desktop deployment.
• Safe to import from any AssistantX package.

CATEGORIES
==========

1. PATH UTILITIES
2. JSON I/O
3. TEXT PROCESSING
4. DATE/TIME
5. ID GENERATION
6. NUMBERS & VALIDATION
7. SIZE FORMATTING
8. DICTIONARIES
9. RETRY & SAFE EXECUTION
10. FALLBACK HELPERS
11. DATA STRUCTURES
12. DIAGNOSTICS

IMPORTANT
=========

This module deliberately does not configure logging.

A module-level logger is used only for optional debug information.
Application logging configuration remains the responsibility of
core.logger / startup infrastructure.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional, TypeVar


# ============================================================================
# Logger
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Type Variables
# ============================================================================

T = TypeVar("T")
R = TypeVar("R")

PathLike = str | os.PathLike[str]


# ============================================================================
# Constants
# ============================================================================

DEFAULT_ENCODING = "utf-8"
DEFAULT_JSON_INDENT = 4

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 0.5
DEFAULT_RETRY_BACKOFF = 2.0

DEFAULT_TEXT_PREVIEW_LENGTH = 100
MAX_FILENAME_LENGTH = 255

INVALID_FILENAME_CHARS = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)

WHITESPACE_PATTERN = re.compile(r"\s+")

WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


# ============================================================================
# Exceptions
# ============================================================================


class UtilsError(Exception):
    """Base exception for core utility errors."""


class ValidationError(UtilsError):
    """Raised when a utility receives invalid input."""


class JSONFileError(UtilsError):
    """Raised when JSON file operations fail."""


class PathValidationError(UtilsError):
    """Raised when filesystem path validation or creation fails."""


# ============================================================================
# Internal Validation Helpers
# ============================================================================


def _require_positive_int(value: Any, name: str) -> int:
    """Validate and return a positive integer."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"{name} must be an integer (got {type(value).__name__})"
        )

    if value <= 0:
        raise ValidationError(
            f"{name} must be > 0 (got {value})"
        )

    return value


def _require_non_negative_number(value: Any, name: str) -> float:
    """Validate a finite non-negative numeric value."""

    if isinstance(value, bool):
        raise ValidationError(
            f"{name} must be numeric (got bool)"
        )

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{name} must be numeric (got {type(value).__name__})"
        ) from exc

    if not math.isfinite(number):
        raise ValidationError(
            f"{name} must be finite (got {value!r})"
        )

    if number < 0:
        raise ValidationError(
            f"{name} cannot be negative (got {value!r})"
        )

    return number


def _validate_encoding(encoding: str) -> str:
    """Validate a text encoding name."""

    if not isinstance(encoding, str) or not encoding.strip():
        raise ValidationError(
            f"encoding must be a non-empty string (got {encoding!r})"
        )

    return encoding.strip()


# ============================================================================
# Path Utilities
# ============================================================================


def normalize_path(
    path: PathLike,
    *,
    expand_user: bool = True,
    resolve: bool = False,
) -> Path:
    """
    Normalize a filesystem path.

    Does not create the path.

    Args:
        path: String or os.PathLike path.
        expand_user: Expand ``~`` when True.
        resolve: Resolve to an absolute path when True.

    Returns:
        Normalized pathlib.Path.

    Raises:
        PathValidationError: Invalid path input or resolution failure.
    """

    if path is None:
        raise PathValidationError(
            "path cannot be None (got NoneType)"
        )

    if isinstance(path, bytes):
        raise PathValidationError(
            "path must be str or os.PathLike, not bytes"
        )

    try:
        text = os.fspath(path)
    except TypeError as exc:
        raise PathValidationError(
            f"path must be str or os.PathLike "
            f"(got {type(path).__name__})"
        ) from exc

    if isinstance(text, bytes):
        raise PathValidationError(
            "path must be text-based, not bytes"
        )

    text = text.strip()

    if not text:
        raise PathValidationError(
            "path cannot be an empty string"
        )

    result = Path(text)

    if expand_user:
        try:
            result = result.expanduser()
        except RuntimeError as exc:
            raise PathValidationError(
                f"could not expand user path: {result}"
            ) from exc

    if resolve:
        try:
            result = result.resolve()
        except OSError as exc:
            raise PathValidationError(
                f"could not resolve path: {result}"
            ) from exc

    logger.debug(
        "Path normalized: %s -> %s",
        text,
        result,
    )

    return result


def ensure_directory(path: PathLike) -> Path:
    """
    Ensure a directory exists.

    Creates missing parent directories automatically.

    Returns:
        The normalized directory Path.
    """

    directory = normalize_path(path)

    try:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        logger.error(
            "Failed to create directory %s: %s",
            directory,
            type(exc).__name__,
        )
        raise PathValidationError(
            f"could not create directory: {directory}"
        ) from exc

    if not directory.is_dir():
        raise PathValidationError(
            f"path exists but is not a directory: {directory}"
        )

    logger.debug("Directory ensured: %s", directory)

    return directory


def ensure_parent_directory(path: PathLike) -> Path:
    """
    Ensure the parent directory of a file path exists.

    Returns:
        The normalized parent directory.
    """

    file_path = normalize_path(path)

    return ensure_directory(file_path.parent)


def path_exists(path: PathLike) -> bool:
    """Return True when the supplied path exists."""

    try:
        return normalize_path(path).exists()
    except (PathValidationError, OSError):
        return False


def is_file(path: PathLike) -> bool:
    """Return True when the supplied path is a regular file."""

    try:
        return normalize_path(path).is_file()
    except (PathValidationError, OSError):
        return False


def is_directory(path: PathLike) -> bool:
    """Return True when the supplied path is a directory."""

    try:
        return normalize_path(path).is_dir()
    except (PathValidationError, OSError):
        return False


# ============================================================================
# JSON Utilities
# ============================================================================


def read_json(
    path: PathLike,
    *,
    default: Optional[T] = None,
    encoding: str = DEFAULT_ENCODING,
) -> Any | T:
    """
    Read JSON from disk.

    If the file does not exist and ``default`` is not None, the default
    value is returned.

    Important:
        ``default=None`` means "raise when missing". Therefore a literal
        JSON ``null`` fallback cannot be distinguished from "no default"
        using this API. This preserves the original public behavior.
    """

    file_path = normalize_path(path)
    encoding = _validate_encoding(encoding)

    if not file_path.exists():
        if default is not None:
            logger.debug(
                "JSON file missing; returning default: %s",
                file_path,
            )
            return default

        raise JSONFileError(
            f"JSON file does not exist: {file_path}"
        )

    if not file_path.is_file():
        raise JSONFileError(
            f"JSON path is not a file: {file_path}"
        )

    try:
        with file_path.open(
            "r",
            encoding=encoding,
        ) as file:
            data = json.load(file)

    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON in %s: line=%s column=%s",
            file_path,
            exc.lineno,
            exc.colno,
        )
        raise JSONFileError(
            f"invalid JSON in '{file_path}': {exc}"
        ) from exc

    except (OSError, UnicodeError) as exc:
        raise JSONFileError(
            f"could not read JSON file: {file_path}"
        ) from exc

    logger.debug("JSON loaded successfully: %s", file_path)

    return data


def write_json(
    path: PathLike,
    data: Any,
    *,
    indent: int = DEFAULT_JSON_INDENT,
    encoding: str = DEFAULT_ENCODING,
    ensure_ascii: bool = False,
    atomic: bool = True,
) -> Path:
    """
    Write JSON to disk.

    Atomic mode writes into the destination directory and replaces the
    target only after successful serialization and flushing.
    """

    file_path = normalize_path(path)
    encoding = _validate_encoding(encoding)

    if isinstance(indent, bool) or not isinstance(indent, int):
        raise ValidationError(
            f"indent must be an integer (got {type(indent).__name__})"
        )

    if indent < 0:
        raise ValidationError(
            f"indent must be >= 0 (got {indent})"
        )

    ensure_parent_directory(file_path)

    # Serialize before touching the existing destination.
    try:
        payload = json.dumps(
            data,
            indent=indent,
            ensure_ascii=ensure_ascii,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise JSONFileError(
            f"could not serialize JSON for: {file_path}"
        ) from exc

    if not atomic:
        try:
            with file_path.open(
                "w",
                encoding=encoding,
                newline="",
            ) as file:
                file.write(payload)
                file.flush()

            logger.debug(
                "JSON written: %s",
                file_path,
            )

            return file_path

        except (OSError, UnicodeError) as exc:
            raise JSONFileError(
                f"could not write JSON file: {file_path}"
            ) from exc

    temporary_path: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:

            temporary_path = Path(temp_file.name)

            temp_file.write(payload)
            temp_file.flush()

            # Best-effort durability.
            with contextlib.suppress(OSError):
                os.fsync(temp_file.fileno())

        # Path.replace() is atomic on the same filesystem under normal
        # filesystem semantics and works on Windows for replacement.
        temporary_path.replace(file_path)

        logger.debug(
            "JSON written atomically: %s",
            file_path,
        )

        return file_path

    except (OSError, UnicodeError) as exc:
        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink(missing_ok=True)

        raise JSONFileError(
            f"could not atomically write JSON file: {file_path}"
        ) from exc


def update_json(
    path: PathLike,
    updates: Mapping[str, Any],
    *,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    """
    Deep-merge updates into a JSON object and save it.

    Returns:
        Updated dictionary.
    """

    if not isinstance(updates, Mapping):
        raise ValidationError(
            f"updates must be a Mapping "
            f"(got {type(updates).__name__})"
        )

    file_path = normalize_path(path)

    if file_path.exists():
        current = read_json(
            file_path,
            default={},
        )
    elif create_if_missing:
        current = {}
    else:
        raise JSONFileError(
            f"JSON file does not exist and create_if_missing=False: "
            f"{file_path}"
        )

    if not isinstance(current, dict):
        raise JSONFileError(
            f"existing JSON root must be a dictionary "
            f"(got {type(current).__name__})"
        )

    merged = deep_merge(
        current,
        dict(updates),
    )

    write_json(
        file_path,
        merged,
    )

    return merged


# ============================================================================
# Text Utilities
# ============================================================================


def normalize_whitespace(
    text: Optional[str],
) -> str:
    """
    Collapse consecutive whitespace into single spaces.
    """

    if text is None:
        return ""

    value = str(text)

    result = WHITESPACE_PATTERN.sub(
        " ",
        value,
    ).strip()

    return result


def normalize_text(
    text: Optional[str],
    *,
    lowercase: bool = False,
) -> str:
    """
    Normalize whitespace and optionally apply Unicode case folding.
    """

    value = normalize_whitespace(text)

    if lowercase:
        value = value.casefold()

    return value


def contains_any(
    text: Optional[str],
    values: Iterable[str],
    *,
    case_sensitive: bool = False,
) -> bool:
    """
    Return True when any non-empty value occurs as a substring.
    """

    if not text:
        return False

    source = str(text)

    if not case_sensitive:
        source = source.casefold()

    for value in values:
        if value is None:
            continue

        candidate = str(value).strip()

        if not candidate:
            continue

        if not case_sensitive:
            candidate = candidate.casefold()

        if candidate in source:
            return True

    return False


def truncate_text(
    text: str,
    max_length: int = DEFAULT_TEXT_PREVIEW_LENGTH,
    *,
    suffix: str = "...",
) -> str:
    """
    Truncate text to at most ``max_length`` characters.
    """

    if isinstance(max_length, bool) or not isinstance(max_length, int):
        raise ValidationError(
            f"max_length must be an integer "
            f"(got {type(max_length).__name__})"
        )

    if max_length < 0:
        raise ValidationError(
            f"max_length must be >= 0 (got {max_length})"
        )

    value = "" if text is None else str(text)
    suffix = "" if suffix is None else str(suffix)

    if len(value) <= max_length:
        return value

    if max_length == 0:
        return ""

    if len(suffix) >= max_length:
        return suffix[:max_length]

    return value[: max_length - len(suffix)] + suffix


def safe_filename(
    filename: str,
    *,
    replacement: str = "_",
    max_length: int = MAX_FILENAME_LENGTH,
) -> str:
    """
    Sanitize arbitrary text for use as a filesystem filename.

    Handles Windows-invalid characters, control characters, reserved
    device names, trailing dots/spaces, and excessive length.
    """

    if filename is None:
        raise ValidationError(
            "filename cannot be None"
        )

    if isinstance(max_length, bool) or not isinstance(max_length, int):
        raise ValidationError(
            f"max_length must be an integer "
            f"(got {type(max_length).__name__})"
        )

    if max_length <= 0:
        raise ValidationError(
            f"max_length must be > 0 (got {max_length})"
        )

    replacement = str(replacement)

    value = str(filename).strip()

    if not value:
        raise ValidationError(
            "filename cannot be empty"
        )

    cleaned = INVALID_FILENAME_CHARS.sub(
        replacement,
        value,
    )

    cleaned = normalize_whitespace(cleaned)

    # Windows does not allow filenames ending in dot or space.
    cleaned = cleaned.rstrip(". ")

    if not cleaned:
        cleaned = "untitled"

    # Handle reserved Windows device names.
    stem = Path(cleaned).stem.upper()

    if stem in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    cleaned = cleaned.rstrip(". ")

    if not cleaned:
        cleaned = "untitled"

    return cleaned[:max_length]


def is_blank(value: Any) -> bool:
    """Return True for None or whitespace-only strings."""

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    return False


# ============================================================================
# Date / Time Utilities
# ============================================================================


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Return the current timezone-aware local datetime."""

    return datetime.now().astimezone()


def timestamp() -> float:
    """Return the current UNIX timestamp in seconds."""

    return time.time()


def iso_timestamp(
    *,
    utc: bool = True,
    timespec: str = "seconds",
) -> str:
    """
    Return the current timezone-aware ISO-8601 timestamp.
    """

    value = utc_now() if utc else local_now()

    try:
        return value.isoformat(
            timespec=timespec,
        )
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            f"invalid ISO timestamp timespec: {timespec!r}"
        ) from exc


def format_datetime(
    value: Optional[datetime] = None,
    *,
    format_string: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """
    Format a datetime using ``strftime``.
    """

    if value is None:
        value = local_now()

    if not isinstance(value, datetime):
        raise ValidationError(
            f"value must be datetime or None "
            f"(got {type(value).__name__})"
        )

    if not isinstance(format_string, str) or not format_string:
        raise ValidationError(
            "format_string must be a non-empty string"
        )

    try:
        return value.strftime(format_string)
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            f"invalid datetime format string: {format_string!r}"
        ) from exc


# ============================================================================
# ID Generation
# ============================================================================


def generate_id(
    *,
    prefix: Optional[str] = None,
    length: Optional[int] = None,
) -> str:
    """
    Generate a UUID4 hexadecimal identifier.

    If ``length`` is supplied, the UUID portion is shortened.
    """

    if length is not None:
        if isinstance(length, bool) or not isinstance(length, int):
            raise ValidationError(
                f"length must be an integer "
                f"(got {type(length).__name__})"
            )

        if length <= 0:
            raise ValidationError(
                f"length must be > 0 (got {length})"
            )

    identifier = uuid.uuid4().hex

    if length is not None:
        identifier = identifier[:length]

    if prefix is not None and str(prefix).strip():
        clean_prefix = safe_filename(
            str(prefix),
            replacement="_",
            max_length=50,
        )

        return f"{clean_prefix}_{identifier}"

    return identifier


# ============================================================================
# Number Utilities
# ============================================================================


def clamp(
    value: T,
    minimum: T,
    maximum: T,
) -> T:
    """
    Clamp a comparable value between inclusive bounds.
    """

    try:
        if minimum > maximum:
            raise ValidationError(
                f"minimum must be <= maximum "
                f"(got {minimum!r} > {maximum!r})"
            )

        return max(
            minimum,
            min(value, maximum),
        )

    except TypeError as exc:
        raise ValidationError(
            "value, minimum, and maximum must be mutually comparable"
        ) from exc


def is_finite_number(value: Any) -> bool:
    """
    Return True for finite int/float values, excluding bool.
    """

    if isinstance(value, bool):
        return False

    if not isinstance(value, (int, float)):
        return False

    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def safe_int(
    value: Any,
    *,
    default: Optional[int] = None,
) -> Optional[int]:
    """
    Safely convert a value to int.

    Booleans are intentionally rejected.
    """

    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not accepted")

        return int(value)

    except (TypeError, ValueError, OverflowError):
        return default


def safe_float(
    value: Any,
    *,
    default: Optional[float] = None,
) -> Optional[float]:
    """
    Safely convert a value to a finite float.

    Booleans, NaN, and infinity are rejected.
    """

    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not accepted")

        result = float(value)

        if not math.isfinite(result):
            raise ValueError(
                "float value is not finite"
            )

        return result

    except (TypeError, ValueError, OverflowError):
        return default


# ============================================================================
# Size Utilities
# ============================================================================


def format_bytes(
    size: float,
    *,
    precision: int = 2,
) -> str:
    """
    Convert bytes into a human-readable binary size.

    Examples:
        1024 -> ``1.00 KB``
        1048576 -> ``1.00 MB``
        123 -> ``123 B``
    """

    if not is_finite_number(size):
        raise ValidationError(
            f"size must be a finite number (got {size!r})"
        )

    if size < 0:
        raise ValidationError(
            f"size cannot be negative (got {size!r})"
        )

    if isinstance(precision, bool) or not isinstance(precision, int):
        raise ValidationError(
            f"precision must be an integer "
            f"(got {type(precision).__name__})"
        )

    if precision < 0:
        raise ValidationError(
            f"precision must be >= 0 (got {precision})"
        )

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
        "PB",
    )

    value = float(size)
    unit_index = 0

    while (
        value >= 1024
        and unit_index < len(units) - 1
    ):
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} B"

    return f"{value:.{precision}f} {units[unit_index]}"


# ============================================================================
# Dictionary Utilities
# ============================================================================


def deep_merge(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Recursively merge mappings.

    The input mappings are never modified.
    """

    if not isinstance(base, Mapping):
        raise ValidationError(
            f"base must be a Mapping "
            f"(got {type(base).__name__})"
        )

    if not isinstance(override, Mapping):
        raise ValidationError(
            f"override must be a Mapping "
            f"(got {type(override).__name__})"
        )

    result: dict[str, Any] = dict(base)

    for key, value in override.items():
        existing = result.get(key)

        if (
            isinstance(existing, Mapping)
            and isinstance(value, Mapping)
        ):
            result[key] = deep_merge(
                existing,
                value,
            )
        else:
            result[key] = value

    return result


def remove_none_values(
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Return a shallow dictionary without None-valued entries.
    """

    if not isinstance(data, Mapping):
        raise ValidationError(
            f"data must be a Mapping "
            f"(got {type(data).__name__})"
        )

    return {
        key: value
        for key, value in data.items()
        if value is not None
    }


# ============================================================================
# Retry & Safe Execution
# ============================================================================


def retry(
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    delay: float = DEFAULT_RETRY_DELAY,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    Decorator implementing retry with exponential backoff.
    """

    _require_positive_int(
        attempts,
        "attempts",
    )

    delay_value = _require_non_negative_number(
        delay,
        "delay",
    )

    backoff_value = _require_non_negative_number(
        backoff,
        "backoff",
    )

    if backoff_value < 1:
        raise ValidationError(
            f"backoff must be >= 1 (got {backoff})"
        )

    if not isinstance(exceptions, tuple) or not exceptions:
        raise ValidationError(
            "exceptions must be a non-empty tuple of exception types"
        )

    if not all(
        isinstance(exc, type)
        and issubclass(exc, BaseException)
        for exc in exceptions
    ):
        raise ValidationError(
            "exceptions must contain only exception classes"
        )

    def decorator(
        function: Callable[..., R],
    ) -> Callable[..., R]:

        if not callable(function):
            raise ValidationError(
                f"function must be callable "
                f"(got {type(function).__name__})"
            )

        @wraps(function)
        def wrapper(
            *args: Any,
            **kwargs: Any,
        ) -> R:

            current_delay = delay_value
            last_error: Optional[BaseException] = None

            for attempt_number in range(
                1,
                attempts + 1,
            ):
                try:
                    return function(
                        *args,
                        **kwargs,
                    )

                except exceptions as exc:
                    last_error = exc

                    if attempt_number >= attempts:
                        logger.error(
                            "Retry exhausted for %s after %d attempt(s)",
                            getattr(
                                function,
                                "__qualname__",
                                repr(function),
                            ),
                            attempts,
                        )
                        break

                    if current_delay > 0:
                        time.sleep(current_delay)

                    current_delay *= backoff_value

            if last_error is None:
                raise RuntimeError(
                    "retry completed without result or exception"
                )

            raise last_error

        return wrapper

    return decorator


def safe_call(
    function: Callable[..., R],
    *args: Any,
    default: Optional[T] = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> R | T | None:
    """
    Execute a callable and return ``default`` for selected exceptions.
    """

    if not callable(function):
        raise ValidationError(
            f"function must be callable "
            f"(got {type(function).__name__})"
        )

    if not isinstance(exceptions, tuple) or not exceptions:
        raise ValidationError(
            "exceptions must be a non-empty tuple"
        )

    try:
        return function(
            *args,
            **kwargs,
        )

    except exceptions as exc:
        logger.debug(
            "safe_call suppressed %s from %s",
            type(exc).__name__,
            getattr(
                function,
                "__qualname__",
                repr(function),
            ),
        )
        return default


# ============================================================================
# Fallback Helpers
# ============================================================================


def first_not_none(
    *values: Optional[T],
) -> Optional[T]:
    """
    Return the first value that is not None.
    """

    for value in values:
        if value is not None:
            return value

    return None


def coalesce_text(
    *values: Any,
    default: str = "",
) -> str:
    """
    Return the first non-blank textual representation.
    """

    for value in values:
        if value is None:
            continue

        text = str(value).strip()

        if text:
            return text

    return default


# ============================================================================
# Data Structures
# ============================================================================


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1000,
) -> list[str]:
    """
    Split text into fixed-size character chunks.

    Note:
        ``chunk_size`` represents characters, not bytes.
    """

    _require_positive_int(
        chunk_size,
        "chunk_size",
    )

    value = "" if text is None else str(text)

    if not value:
        return []

    return [
        value[index : index + chunk_size]
        for index in range(
            0,
            len(value),
            chunk_size,
        )
    ]


# ============================================================================
# Diagnostics
# ============================================================================


def utils_diagnostics() -> dict[str, Any]:
    """
    Return a lightweight diagnostics snapshot.

    No filesystem mutation is performed.
    """

    try:
        cwd = str(Path.cwd())
    except OSError:
        cwd = "<unavailable>"

    try:
        home = str(Path.home())
    except RuntimeError:
        home = "<unavailable>"

    return {
        "module": __name__,
        "status": "ok",
        "python_cwd": cwd,
        "home": home,
        "platform": os.name,
        "path_separator": os.sep,
        "default_encoding": DEFAULT_ENCODING,
        "timestamp": iso_timestamp(),
    }


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Exceptions
    "UtilsError",
    "ValidationError",
    "JSONFileError",
    "PathValidationError",

    # Path utilities
    "normalize_path",
    "ensure_directory",
    "ensure_parent_directory",
    "path_exists",
    "is_file",
    "is_directory",

    # JSON utilities
    "read_json",
    "write_json",
    "update_json",

    # Text utilities
    "normalize_whitespace",
    "normalize_text",
    "contains_any",
    "truncate_text",
    "safe_filename",
    "is_blank",

    # Date/time
    "utc_now",
    "local_now",
    "timestamp",
    "iso_timestamp",
    "format_datetime",

    # IDs
    "generate_id",

    # Numbers
    "clamp",
    "is_finite_number",
    "safe_int",
    "safe_float",

    # Size
    "format_bytes",

    # Dictionaries
    "deep_merge",
    "remove_none_values",

    # Retry / execution
    "retry",
    "safe_call",

    # Fallbacks
    "first_not_none",
    "coalesce_text",

    # Data structures
    "chunk_text",

    # Diagnostics
    "utils_diagnostics",
]
