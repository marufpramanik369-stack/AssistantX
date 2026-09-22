"""
core.utils
==========

General-purpose utility helpers for AssistantX.

This module intentionally avoids importing other AssistantX modules so it can
be safely used throughout the project without creating circular imports.

Features
--------
- Path normalization and directory helpers
- Safe / atomic JSON reading and writing
- Text normalization and truncation
- Safe filename creation
- Date / time helpers
- Unique ID generation
- Number clamping
- Human-readable file sizes
- Dictionary deep merge
- Retry decorator
- Safe callable execution
- Small validation helpers
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

# ============================================================================
# Type helpers
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

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

WHITESPACE_PATTERN = re.compile(r"\s+")


# ============================================================================
# Exceptions
# ============================================================================


class UtilsError(Exception):
    """Base exception for core utility errors."""


class ValidationError(UtilsError):
    """Raised when a utility function receives invalid input."""


class JSONFileError(UtilsError):
    """Raised when reading or writing JSON fails."""


class PathValidationError(UtilsError):
    """Raised when a path is invalid."""


# ============================================================================
# Path utilities
# ============================================================================


def normalize_path(
    path: PathLike,
    *,
    expand_user: bool = True,
    resolve: bool = False,
) -> Path:
    """
    Normalize a filesystem path.

    Parameters
    ----------
    path:
        Path to normalize.

    expand_user:
        Expand ``~`` to the user's home directory.

    resolve:
        Resolve the path to an absolute path.

    Returns
    -------
    pathlib.Path
    """

    if path is None:
        raise PathValidationError("Path cannot be None.")

    text = str(path).strip()

    if not text:
        raise PathValidationError("Path cannot be empty.")

    result = Path(text)

    if expand_user:
        result = result.expanduser()

    if resolve:
        try:
            result = result.resolve()
        except OSError as exc:
            raise PathValidationError(
                f"Could not resolve path: {result}"
            ) from exc

    return result


def ensure_directory(path: PathLike) -> Path:
    """
    Ensure a directory exists.

    Returns the normalized directory path.
    """

    directory = normalize_path(path)

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PathValidationError(
            f"Could not create directory: {directory}"
        ) from exc

    return directory


def ensure_parent_directory(path: PathLike) -> Path:
    """
    Ensure the parent directory of a file exists.
    """

    file_path = normalize_path(path)

    return ensure_directory(file_path.parent)


def path_exists(path: PathLike) -> bool:
    """Return True if the path exists."""

    try:
        return normalize_path(path).exists()
    except (UtilsError, OSError):
        return False


def is_file(path: PathLike) -> bool:
    """Return True if path exists and is a file."""

    try:
        return normalize_path(path).is_file()
    except (UtilsError, OSError):
        return False


def is_directory(path: PathLike) -> bool:
    """Return True if path exists and is a directory."""

    try:
        return normalize_path(path).is_dir()
    except (UtilsError, OSError):
        return False


# ============================================================================
# JSON utilities
# ============================================================================


def read_json(
    path: PathLike,
    *,
    default: T | None = None,
    encoding: str = DEFAULT_ENCODING,
) -> Any | T:
    """
    Read JSON data from a file.

    If the file does not exist and ``default`` is provided,
    ``default`` is returned.
    """

    file_path = normalize_path(path)

    if not file_path.exists():
        if default is not None:
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
            return json.load(file)

    except json.JSONDecodeError as exc:
        raise JSONFileError(
            f"Invalid JSON in file '{file_path}': {exc}"
        ) from exc

    except (OSError, UnicodeError) as exc:
        raise JSONFileError(
            f"Could not read JSON file: {file_path}"
        ) from exc


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
    Write data to a JSON file.

    Atomic mode writes to a temporary file first and then replaces
    the target file, reducing the risk of corrupted JSON.
    """

    file_path = normalize_path(path)

    ensure_parent_directory(file_path)

    if indent < 0:
        raise ValidationError(
            "JSON indent cannot be negative."
        )

    if not atomic:
        try:
            with file_path.open(
                "w",
                encoding=encoding,
            ) as file:
                json.dump(
                    data,
                    file,
                    indent=indent,
                    ensure_ascii=ensure_ascii,
                )

            return file_path

        except (OSError, TypeError, ValueError) as exc:
            raise JSONFileError(
                f"Could not write JSON file: {file_path}"
            ) from exc

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:

            temporary_path = Path(temp_file.name)

            json.dump(
                data,
                temp_file,
                indent=indent,
                ensure_ascii=ensure_ascii,
            )

            temp_file.flush()

            with contextlib.suppress(OSError):
                os.fsync(temp_file.fileno())

        temporary_path.replace(file_path)

        return file_path

    except (OSError, TypeError, ValueError) as exc:

        if temporary_path is not None:
            with contextlib.suppress(OSError):
                temporary_path.unlink(missing_ok=True)

        raise JSONFileError(
            f"Could not write JSON file: {file_path}"
        ) from exc


def update_json(
    path: PathLike,
    updates: Mapping[str, Any],
    *,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    """
    Update a JSON dictionary and save it.

    Existing nested dictionaries are merged recursively.
    """

    if not isinstance(updates, Mapping):
        raise ValidationError(
            "updates must be a mapping."
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
            f"JSON file does not exist: {file_path}"
        )

    if not isinstance(current, dict):
        raise JSONFileError(
            "Existing JSON root must be an object/dictionary."
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
# Text utilities
# ============================================================================


def normalize_whitespace(text: str) -> str:
    """
    Collapse consecutive whitespace into single spaces.
    """

    if text is None:
        return ""

    return WHITESPACE_PATTERN.sub(
        " ",
        str(text),
    ).strip()

# ============= Update

def normalize_text(
    text: str | None,
    *,
    lowercase: bool = False,
) -> str:
    """
    Normalize text for consistent AssistantX processing.
    """

    value = normalize_whitespace(
        text or ""
    )

    if lowercase:
        value = value.casefold()

    return value

def contains_any(
    text: str | None,
    values: list[str] | tuple[str, ...] | set[str],
    *,
    case_sensitive: bool = False,
) -> bool:
    """
    Return True if any value exists inside the given text.

    Args:
        text: Text to search.
        values: Collection of words or phrases to look for.
        case_sensitive: Whether matching should be case-sensitive.

    Returns:
        True if at least one value is found, otherwise False.
    """

    if not text or not values:
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
    Truncate text while preserving the maximum length.
    """

    value = str(text or "")

    if max_length < 0:
        raise ValidationError(
            "max_length cannot be negative."
        )

    if len(value) <= max_length:
        return value

    if max_length == 0:
        return ""

    if len(suffix) >= max_length:
        return suffix[:max_length]

    return value[
        : max_length - len(suffix)
    ] + suffix


def safe_filename(
    filename: str,
    *,
    replacement: str = "_",
    max_length: int = MAX_FILENAME_LENGTH,
) -> str:
    """
    Convert arbitrary text into a safe filename.
    """

    if filename is None:
        raise ValidationError(
            "Filename cannot be None."
        )

    filename = str(filename).strip()

    if not filename:
        raise ValidationError(
            "Filename cannot be empty."
        )

    if max_length <= 0:
        raise ValidationError(
            "max_length must be greater than zero."
        )

    cleaned = INVALID_FILENAME_CHARS.sub(
        replacement,
        filename,
    )

    cleaned = cleaned.rstrip(
        ". "
    )

    cleaned = normalize_whitespace(
        cleaned
    )

    if not cleaned:
        cleaned = "untitled"

    # Windows reserved device names
    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    stem = Path(cleaned).stem.upper()

    if stem in reserved_names:
        cleaned = f"_{cleaned}"

    return cleaned[:max_length]


def is_blank(value: Any) -> bool:
    """
    Return True for None or empty/whitespace-only strings.
    """

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    return False


# ============================================================================
# Time / date utilities
# ============================================================================


def utc_now() -> datetime:
    """
    Return current timezone-aware UTC datetime.
    """

    return datetime.now(
        timezone.utc
    )


def local_now() -> datetime:
    """
    Return current timezone-aware local datetime.
    """

    return datetime.now().astimezone()


def timestamp() -> float:
    """
    Return UNIX timestamp.
    """

    return time.time()


def iso_timestamp(
    *,
    utc: bool = True,
    timespec: str = "seconds",
) -> str:
    """
    Return current timestamp in ISO-8601 format.
    """

    value = (
        utc_now()
        if utc
        else local_now()
    )

    return value.isoformat(
        timespec=timespec
    )


def format_datetime(
    value: datetime | None = None,
    *,
    format_string: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """
    Format a datetime into a readable string.
    """

    value = value or local_now()

    return value.strftime(
        format_string
    )


# ============================================================================
# ID helpers
# ============================================================================


def generate_id(
    *,
    prefix: str | None = None,
    length: int | None = None,
) -> str:
    """
    Generate a UUID-based identifier.

    Examples
    --------
    generate_id()
    -> 'c8511bf4411e4de99b9ef4921836c04a'

    generate_id(prefix="msg", length=12)
    -> 'msg_a31c492b19fe'
    """

    identifier = uuid.uuid4().hex

    if length is not None:

        if length <= 0:
            raise ValidationError(
                "ID length must be greater than zero."
            )

        identifier = identifier[:length]

    if prefix:
        prefix = safe_filename(
            prefix,
            replacement="_",
            max_length=50,
        )

        return f"{prefix}_{identifier}"

    return identifier


# ============================================================================
# Number utilities
# ============================================================================


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    """
    Clamp a numeric value between minimum and maximum.
    """

    if minimum > maximum:
        raise ValidationError(
            "minimum cannot be greater than maximum."
        )

    return max(
        minimum,
        min(value, maximum),
    )


def is_finite_number(value: Any) -> bool:
    """
    Check whether value is a finite int/float.

    Booleans are rejected.
    """

    if isinstance(value, bool):
        return False

    if not isinstance(value, (int, float)):
        return False

    return math.isfinite(
        float(value)
    )


def safe_int(
    value: Any,
    *,
    default: int | None = None,
) -> int | None:
    """
    Safely convert value to integer.
    """

    try:
        if isinstance(value, bool):
            raise TypeError(f"Expected string, got {type(value).__name__}")

        return int(value)

    except (TypeError, ValueError):
        return default


def safe_float(
    value: Any,
    *,
    default: float | None = None,
) -> float | None:
    """
    Safely convert value to float.
    """

    try:
        if isinstance(value, bool):
            raise TypeError(f"Expected number, got {type(value).__name__}")

        result = float(value)

        if not math.isfinite(result):
            raise ValueError

        return result

    except (TypeError, ValueError):
        return default


# ============================================================================
# Size utilities
# ============================================================================


def format_bytes(
    size: float,
    *,
    precision: int = 2,
) -> str:
    """
    Convert a byte count into a human-readable size.

    Examples
    --------
    1024 -> 1.00 KB
    """

    if not is_finite_number(size):
        raise ValidationError(
            "size must be a finite number."
        )

    if size < 0:
        raise ValidationError(
            "size cannot be negative."
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
        return f"{int(value)} {units[unit_index]}"

    return (
        f"{value:.{precision}f} "
        f"{units[unit_index]}"
    )


# ============================================================================
# Dictionary utilities
# ============================================================================


def deep_merge(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Recursively merge two dictionaries.

    ``override`` values take priority.
    """

    if not isinstance(base, Mapping):
        raise ValidationError(
            "base must be a mapping."
        )

    if not isinstance(override, Mapping):
        raise ValidationError(
            "override must be a mapping."
        )

    result = dict(base)

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
    Return a dictionary without values that are None.
    """

    return {
        key: value
        for key, value in data.items()
        if value is not None
    }


# ============================================================================
# Retry utilities
# ============================================================================


def retry(
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    delay: float = DEFAULT_RETRY_DELAY,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[
    [Callable[..., R]],
    Callable[..., R],
]:
    """
    Retry decorator with exponential backoff.

    Example
    -------
        @retry(attempts=3)
        def connect():
            ...
    """

    if attempts <= 0:
        raise ValidationError(
            "attempts must be greater than zero."
        )

    if delay < 0:
        raise ValidationError(
            "delay cannot be negative."
        )

    if backoff < 1:
        raise ValidationError(
            "backoff must be at least 1."
        )

    def decorator(
        function: Callable[..., R],
    ) -> Callable[..., R]:

        @wraps(function)
        def wrapper(
            *args: Any,
            **kwargs: Any,
        ) -> R:

            current_delay = delay
            last_error: BaseException | None = None

            for attempt in range(
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

                    if attempt >= attempts:
                        break

                    if current_delay > 0:
                        time.sleep(
                            current_delay
                        )

                    current_delay *= backoff

            assert last_error is not None
            raise last_error

        return wrapper

    return decorator


# ============================================================================
# Safe execution
# ============================================================================


def safe_call(
    function: Callable[..., R],
    *args: Any,
    default: T | None = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> R | T | None:
    """
    Execute a callable and return ``default`` if it raises an allowed exception.

    This should be used only where failure is intentionally non-critical.
    """

    if not callable(function):
        raise ValidationError(
            "function must be callable."
        )

    try:
        return function(
            *args,
            **kwargs,
        )

    except exceptions:
        return default


# ============================================================================
# Miscellaneous
# ============================================================================


def first_not_none(
    *values: T | None,
) -> T | None:
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
    Return the first non-empty string representation.
    """

    for value in values:

        if value is None:
            continue

        text = str(value).strip()

        if text:
            return text

    return default


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1000,
) -> list[str]:
    """
    Split text into fixed-size chunks.
    """

    if chunk_size <= 0:
        raise ValidationError(
            "chunk_size must be greater than zero."
        )

    text = str(text or "")

    if not text:
        return []

    return [
        text[index:index + chunk_size]
        for index in range(
            0,
            len(text),
            chunk_size,
        )
    ]


# ============================================================================
# Diagnostics
# ============================================================================


def utils_diagnostics() -> dict[str, Any]:
    """
    Return lightweight diagnostics for the utility module.
    """

    return {
        "module": "core.utils",
        "status": "ok",
        "python_cwd": str(Path.cwd()),
        "home": str(Path.home()),
        "platform": os.name,
        "timestamp": iso_timestamp(),
        "default_encoding": DEFAULT_ENCODING,
    }
# UPDATE

# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "JSONFileError",
    "PathValidationError",
    "UtilsError",
    "ValidationError",
    "chunk_text",
    "clamp",
    "coalesce_text",
    "contains_any",
    "deep_merge",
    "ensure_directory",
    "ensure_parent_directory",
    "first_not_none",
    "format_bytes",
    "format_datetime",
    "generate_id",
    "is_blank",
    "is_directory",
    "is_file",
    "is_finite_number",
    "iso_timestamp",
    "local_now",
    "normalize_path",
    "normalize_text",
    "normalize_whitespace",
    "path_exists",
    "read_json",
    "remove_none_values",
    "retry",
    "safe_call",
    "safe_filename",
    "safe_float",
    "safe_int",
    "timestamp",
    "truncate_text",
    "update_json",
    "utc_now",
    "utils_diagnostics",
    "write_json",
]
