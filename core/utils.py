"""
utils.py
========
Grab-bag of small, dependency-free helper functions shared across
AssistantX modules: string cleanup, datetime formatting, safe JSON I/O,
retry/backoff decorators, and simple performance timing.

Rule of thumb for what belongs here: if a function is generic (doesn't
know about "assistants" or "intents" or "voice") and is used by 2+
unrelated modules, it belongs in utils.py. Domain-specific helpers stay
in their owning module.
"""

from __future__ import annotations

import functools
import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# String helpers
# --------------------------------------------------------------------------- #

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s\u0980-\u09FF]")  # keeps Bangla Unicode block


def normalize_text(text: str) -> str:
    """
    Lowercase, strip, and collapse whitespace. Unicode-normalizes so
    accented/Bangla combining characters compare consistently.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.strip().lower()
    text = _WHITESPACE_RE.sub(" ", text)
    return text


def strip_punctuation(text: str, keep_bangla: bool = True) -> str:
    """Remove punctuation while optionally preserving the Bangla Unicode range."""
    pattern = _PUNCTUATION_RE if keep_bangla else re.compile(r"[^\w\s]")
    return pattern.sub("", text)


def truncate(text: str, max_length: int = 200, suffix: str = "…") -> str:
    """Truncate text to at most max_length characters, adding a suffix if cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)].rstrip() + suffix


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Case-insensitive check whether any keyword appears in text."""
    normalized = normalize_text(text)
    return any(keyword in normalized for keyword in keywords)


def slugify(text: str) -> str:
    """Convert text into a filesystem/URL-safe slug (ASCII only)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    ascii_text = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    return re.sub(r"[-\s]+", "-", ascii_text)


# --------------------------------------------------------------------------- #
# Date / time helpers
# --------------------------------------------------------------------------- #

def now_iso() -> str:
    """Current UTC timestamp in ISO-8601 format."""
    return datetime.utcnow().isoformat()


def format_datetime(dt: datetime, fmt: str) -> str:
    """Thin wrapper around strftime for consistency/testability."""
    return dt.strftime(fmt)


def human_time_delta(seconds: float) -> str:
    """Convert a duration in seconds to a short human string ('2h 5m', '34s')."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


# --------------------------------------------------------------------------- #
# JSON file I/O (atomic, corruption-safe — mirrors config/settings.py pattern)
# --------------------------------------------------------------------------- #

def read_json(path: Path, default: Any = None) -> Any:
    """Safely read a JSON file, returning `default` if missing or corrupt."""
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read JSON from %s: %s", path, exc)
        return default if default is not None else {}


def write_json(path: Path, data: Any, indent: int = 2) -> bool:
    """Atomically write `data` as JSON to `path`. Returns True on success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(data, indent=indent, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        return True
    except OSError as exc:
        logger.error("Failed to write JSON to %s: %s", path, exc)
        return False


# --------------------------------------------------------------------------- #
# Decorators
# --------------------------------------------------------------------------- #

def retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that retries a function call on failure with exponential
    backoff. Intended for flaky I/O (network calls, mic access, etc.).

    Example:
        @retry(max_attempts=3, delay_seconds=0.5, exceptions=(IOError,))
        def fetch():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            current_delay = delay_seconds
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "%s failed (attempt %d/%d): %s",
                        func.__name__, attempt, max_attempts, exc,
                    )
                    if attempt < max_attempts:
                        time.sleep(current_delay)
                        current_delay *= backoff
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


def timed(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that logs how long a function took to execute (DEBUG level)."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.debug("%s took %.2fms", func.__name__, elapsed_ms)

    return wrapper


def singleton(cls: type[T]) -> Callable[..., T]:
    """Class decorator turning any class into a lazy singleton."""
    instances: dict[type, T] = {}

    @functools.wraps(cls)
    def get_instance(*args: Any, **kwargs: Any) -> T:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #

def safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int conversion that never raises."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float conversion that never raises."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def chunk_list(items: list[T], size: int) -> list[list[T]]:
    """Split a list into consecutive chunks of at most `size` elements."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def clamp(value: float, low: float, high: float) -> float:
    """Constrain value to the inclusive [low, high] range."""
    return max(low, min(value, high))
    