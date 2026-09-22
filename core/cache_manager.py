"""
AssistantX Cache Manager
=========================

Production-grade cache management for AssistantX.

Supported cache areas:
    - ai
    - images
    - search
    - temp

Features:
    - JSON cache storage
    - TTL expiration
    - Atomic writes
    - SHA-256 cache keys
    - Safe filesystem names
    - Cache statistics
    - Expired-cache cleanup
    - Category cleanup
    - Complete cache cleanup
    - Maximum cache-size protection
    - Logging
    - Thread-safe file operations

The cache directory must contain runtime data only.
Application logic belongs in the core/ package.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

# ============================================================================
# PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CACHE_ROOT = PROJECT_ROOT / "cache"

AI_CACHE = CACHE_ROOT / "ai"
IMAGE_CACHE = CACHE_ROOT / "images"
SEARCH_CACHE = CACHE_ROOT / "search"
TEMP_CACHE = CACHE_ROOT / "temp"


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_TTL = 3600

MAX_CACHE_SIZE_MB = 512

CACHE_VERSION = 1

DEFAULT_ENCODING = "utf-8"

CACHE_CATEGORIES: dict[str, Path] = {
    "ai": AI_CACHE,
    "images": IMAGE_CACHE,
    "search": SEARCH_CACHE,
    "temp": TEMP_CACHE,
}


# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class CacheError(Exception):
    """Base exception for AssistantX cache errors."""


class CacheReadError(CacheError):
    """Raised when cache data cannot be read."""


class CacheWriteError(CacheError):
    """Raised when cache data cannot be written."""


class CacheValidationError(CacheError):
    """Raised when cache data is invalid."""


# ============================================================================
# DATA MODELS
# ============================================================================


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Metadata for a cache entry."""

    key: str
    category: str
    path: Path
    size_bytes: int
    created_at: float
    expires_at: float | None

    @property
    def expired(self) -> bool:
        """Return whether the cache entry has expired."""

        if self.expires_at is None:
            return False

        return time.time() >= self.expires_at


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Cache statistics."""

    files: int
    directories: int
    size_bytes: int

    @property
    def size_mb(self) -> float:
        """Return cache size in megabytes."""

        return self.size_bytes / (1024 * 1024)


# ============================================================================
# CACHE MANAGER
# ============================================================================


class CacheManager:
    """
    Central cache manager for AssistantX.

    Example:

        cache = CacheManager()

        cache.set(
            "weather",
            {"temperature": 30},
            category="search",
            ttl=1800,
        )

        result = cache.get(
            "weather",
            category="search",
        )
    """

    def __init__(
        self,
        root: Path | None = None,
        default_ttl: int = DEFAULT_TTL,
        max_size_mb: int = MAX_CACHE_SIZE_MB,
    ) -> None:

        self.root = (
            Path(root).resolve()
            if root is not None
            else CACHE_ROOT
        )

        self.default_ttl = max(
            0,
            int(default_ttl),
        )

        self.max_size_bytes = (
            max(1, int(max_size_mb))
            * 1024
            * 1024
        )

        self._lock = RLock()

        self._initialize()

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def _initialize(self) -> None:
        """Create the cache directory structure."""

        with self._lock:

            self.root.mkdir(
                parents=True,
                exist_ok=True,
            )

            for category in CACHE_CATEGORIES:
                self.category_path(category)

    # ========================================================================
    # CATEGORY
    # ========================================================================

    def category_path(
        self,
        category: str,
    ) -> Path:
        """
        Return the directory for a cache category.

        Unknown categories are allowed and created safely
        inside the cache root.
        """

        safe_category = self._safe_name(
            category
        )

        path = self.root / safe_category

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    # ========================================================================
    # SAFE NAME
    # ========================================================================

    @staticmethod
    def _safe_name(value: str) -> str:
        """Convert a value into a filesystem-safe name."""

        value = str(value).strip()

        if not value:
            raise CacheValidationError(
                "Cache key cannot be empty."
            )

        safe = "".join(
            char
            if char.isalnum()
            or char in "._-"
            else "_"
            for char in value
        )

        return safe[:200]

    # ========================================================================
    # HASH KEY
    # ========================================================================

    @staticmethod
    def make_key(value: str) -> str:
        """Generate a deterministic SHA-256 cache key."""

        return hashlib.sha256(
            value.encode(DEFAULT_ENCODING)
        ).hexdigest()

    # ========================================================================
    # CACHE PATH
    # ========================================================================

    def _cache_path(
        self,
        key: str,
        category: str,
        extension: str = ".json",
    ) -> Path:
        """Build a cache file path."""

        safe_key = self._safe_name(key)

        if not extension.startswith("."):
            extension = f".{extension}"

        return (
            self.category_path(category)
            / f"{safe_key}{extension}"
        )

    # ========================================================================
    # TTL
    # ========================================================================

    def _expiration(
        self,
        ttl: int | None,
    ) -> float | None:
        """Calculate cache expiration timestamp."""

        lifetime = (
            self.default_ttl
            if ttl is None
            else max(0, int(ttl))
        )

        if lifetime == 0:
            return None

        return time.time() + lifetime

    # ========================================================================
    # JSON SET
    # ========================================================================

    def set(
        self,
        key: str,
        value: Any,
        *,
        category: str = "temp",
        ttl: int | None = None,
    ) -> Path:
        """
        Store JSON-compatible data in cache.

        Args:
            key:
                Unique cache identifier.

            value:
                JSON-compatible Python object.

            category:
                Cache category.

            ttl:
                Lifetime in seconds.
                0 means no expiration.
        """

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        created_at = time.time()

        payload = {
            "version": CACHE_VERSION,
            "key": key,
            "category": category,
            "created_at": created_at,
            "expires_at": self._expiration(ttl),
            "data": value,
        }

        try:
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        except (TypeError, ValueError) as exc:

            raise CacheWriteError(
                f"Value cannot be serialized: {key}"
            ) from exc

        with self._lock:

            self._ensure_capacity(
                len(serialized.encode(DEFAULT_ENCODING))
            )

            self._atomic_write(
                path,
                serialized,
            )

        logger.debug(
            "Cache written: %s",
            path,
        )

        return path

    # ========================================================================
    # ATOMIC WRITE
    # ========================================================================

    def _atomic_write(
        self,
        path: Path,
        content: str,
    ) -> None:
        """Write a file atomically."""

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding=DEFAULT_ENCODING,
                dir=path.parent,
                prefix=".cache_",
                suffix=".tmp",
                delete=False,
            ) as temporary:

                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())

                temporary_path = Path(
                    temporary.name
                )

            temporary_path.replace(path)

        except OSError as exc:

            raise CacheWriteError(
                f"Unable to write cache: {path}"
            ) from exc

        finally:

            if (
                temporary_path is not None
                and temporary_path.exists()
            ):
                with contextlib.suppress(OSError):
                    temporary_path.unlink()

    # ========================================================================
    # JSON GET
    # ========================================================================

    def get(
        self,
        key: str,
        *,
        category: str = "temp",
        default: Any = None,
    ) -> Any:
        """Read a JSON cache entry."""

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            return default

        try:

            payload = json.loads(
                path.read_text(
                    encoding=DEFAULT_ENCODING,
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:

            logger.warning(
                "Invalid cache file: %s",
                path,
            )

            raise CacheReadError(
                f"Unable to read cache: {path}"
            ) from exc

        if not isinstance(payload, dict):
            raise CacheReadError(
                f"Invalid cache format: {path}"
            )

        if self._is_expired(payload):

            self.delete(
                key,
                category=category,
            )

            return default

        return payload.get(
            "data",
            default,
        )

    # ========================================================================
    # EXISTS
    # ========================================================================

    def exists(
        self,
        key: str,
        *,
        category: str = "temp",
    ) -> bool:
        """Check whether a valid cache entry exists."""

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            return False

        try:

            payload = json.loads(
                path.read_text(
                    encoding=DEFAULT_ENCODING,
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            return False

        if not isinstance(payload, dict):
            return False

        if self._is_expired(payload):

            self.delete(
                key,
                category=category,
            )

            return False

        return True

    # ========================================================================
    # EXPIRATION CHECK
    # ========================================================================

    @staticmethod
    def _is_expired(
        payload: dict[str, Any],
    ) -> bool:
        """Check whether a cache payload has expired."""

        expires_at = payload.get(
            "expires_at"
        )

        if expires_at is None:
            return False

        try:
            return time.time() >= float(
                expires_at
            )

        except (TypeError, ValueError):
            return True

    # ========================================================================
    # DELETE
    # ========================================================================

    def delete(
        self,
        key: str,
        *,
        category: str = "temp",
    ) -> bool:
        """Delete one JSON cache entry."""

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.exists():
            return False

        with self._lock:

            try:
                path.unlink()

            except OSError as exc:

                logger.warning(
                    "Unable to delete cache: %s",
                    path,
                    exc_info=exc,
                )

                return False

        return True

    # ========================================================================
    # CLEAR CATEGORY
    # ========================================================================

    def clear_category(
        self,
        category: str,
    ) -> int:
        """Delete all cache files from one category."""

        directory = self.category_path(
            category
        )

        removed = 0

        with self._lock:

            for item in directory.iterdir():

                try:

                    if item.is_file():

                        item.unlink()
                        removed += 1

                    elif item.is_dir():

                        import shutil

                        shutil.rmtree(item)
                        removed += 1

                except OSError:

                    logger.warning(
                        "Unable to remove: %s",
                        item,
                        exc_info=True,
                    )

        return removed

    # ========================================================================
    # CLEAR ALL
    # ========================================================================

    def clear_all(self) -> int:
        """Clear every cache category."""

        removed = 0

        for category in CACHE_CATEGORIES:
            removed += self.clear_category(
                category
            )

        return removed

    # ========================================================================
    # CLEAN EXPIRED
    # ========================================================================

    def clean_expired(self) -> int:
        """Remove all expired JSON cache entries."""

        removed = 0

        with self._lock:

            for path in self.root.rglob(
                "*.json"
            ):

                try:

                    payload = json.loads(
                        path.read_text(
                            encoding=DEFAULT_ENCODING,
                        )
                    )

                    if (
                        isinstance(payload, dict)
                        and self._is_expired(payload)
                    ):

                        path.unlink()
                        removed += 1

                except (
                    OSError,
                    json.JSONDecodeError,
                ):

                    logger.debug(
                        "Skipping invalid cache: %s",
                        path,
                    )

        return removed

    # ========================================================================
    # CACHE SIZE
    # ========================================================================

    def size_bytes(self) -> int:
        """Return total cache size in bytes."""

        total = 0

        if not self.root.exists():
            return 0

        for path in self.root.rglob("*"):

            if not path.is_file():
                continue

            try:
                total += path.stat().st_size

            except OSError:
                continue

        return total

    # ========================================================================
    # CACHE SIZE MB
    # ========================================================================

    def size_mb(self) -> float:
        """Return total cache size in megabytes."""

        return self.size_bytes() / (
            1024 * 1024
        )

    # ========================================================================
    # CACHE CAPACITY
    # ========================================================================

    def _ensure_capacity(
        self,
        incoming_size: int,
    ) -> None:
        """
        Ensure enough cache capacity exists.

        Expired entries are removed first.
        """

        current_size = self.size_bytes()

        if (
            current_size + incoming_size
            <= self.max_size_bytes
        ):
            return

        logger.info(
            "Cache limit reached. Cleaning expired entries."
        )

        self.clean_expired()

        current_size = self.size_bytes()

        if (
            current_size + incoming_size
            > self.max_size_bytes
        ):

            logger.warning(
                "Cache is above configured limit."
            )

    # ========================================================================
    # CACHE ENTRY INFO
    # ========================================================================

    def info(
        self,
        key: str,
        *,
        category: str = "temp",
    ) -> CacheEntry | None:
        """Return metadata for a cache entry."""

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            return None

        try:

            stat = path.stat()

            payload = json.loads(
                path.read_text(
                    encoding=DEFAULT_ENCODING,
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):

            return None

        return CacheEntry(
            key=key,
            category=category,
            path=path,
            size_bytes=stat.st_size,
            created_at=float(
                payload.get(
                    "created_at",
                    stat.st_ctime,
                )
            ),
            expires_at=payload.get(
                "expires_at"
            ),
        )

    # ========================================================================
    # CACHE STATISTICS
    # ========================================================================

    def stats(self) -> CacheStats:
        """Return cache statistics."""

        files = 0
        directories = 0
        size = 0

        if not self.root.exists():
            return CacheStats(
                files=0,
                directories=0,
                size_bytes=0,
            )

        for path in self.root.rglob("*"):

            try:

                if path.is_file():

                    files += 1
                    size += path.stat().st_size

                elif path.is_dir():

                    directories += 1

            except OSError:
                continue

        return CacheStats(
            files=files,
            directories=directories,
            size_bytes=size,
        )


# ============================================================================
# GLOBAL CACHE INSTANCE
# ============================================================================

cache_manager = CacheManager()


# ============================================================================
# PUBLIC API
# ============================================================================


def cache_set(
    key: str,
    value: Any,
    *,
    category: str = "temp",
    ttl: int | None = None,
) -> Path:
    """Store data in AssistantX cache."""

    return cache_manager.set(
        key,
        value,
        category=category,
        ttl=ttl,
    )


def cache_get(
    key: str,
    *,
    category: str = "temp",
    default: Any = None,
) -> Any:
    """Retrieve data from AssistantX cache."""

    return cache_manager.get(
        key,
        category=category,
        default=default,
    )


def cache_exists(
    key: str,
    *,
    category: str = "temp",
) -> bool:
    """Check whether a cache entry exists."""

    return cache_manager.exists(
        key,
        category=category,
    )


def cache_delete(
    key: str,
    *,
    category: str = "temp",
) -> bool:
    """Delete a cache entry."""

    return cache_manager.delete(
        key,
        category=category,
    )


def clear_cache(
    category: str | None = None,
) -> int:
    """Clear one category or all cache data."""

    if category is not None:
        return cache_manager.clear_category(
            category
        )

    return cache_manager.clear_all()


def clean_cache() -> int:
    """Remove expired cache entries."""

    return cache_manager.clean_expired()


def cache_stats() -> CacheStats:
    """Return current cache statistics."""

    return cache_manager.stats()
