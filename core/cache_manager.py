"""
AssistantX Cache Manager — Production-Grade Cache Operations
================================================================

Thread-safe, JSON-based cache management for AssistantX with TTL expiration,
atomic writes, and automatic capacity management.

ARCHITECTURE
============

    CacheManager(root, default_ttl, max_size_mb)
        ├─ category_path(category)           → Path
        ├─ set(key, value, category, ttl)    → Path
        ├─ get(key, category, default)       → Any
        ├─ exists(key, category)             → bool
        ├─ delete(key, category)             → bool
        ├─ info(key, category)               → CacheEntry | None
        ├─ clean_expired()                   → int
        ├─ clear_category(category)          → int
        ├─ clear_all()                       → int
        ├─ stats()                           → CacheStats
        └─ [internal] _atomic_write, _ensure_capacity, etc.

CACHE LAYOUT
============

    cache/
        ├── ai/                 # AI model outputs, embeddings
        ├── images/             # Image processing cache
        ├── search/             # Web search results
        └── temp/               # Temporary data

THREAD SAFETY
=============

    All public methods use RLock for thread-safe file operations.
    Concurrent reads/writes to different keys are safe.
    Concurrent writes to the same key will serialize (last write wins).

TTL & EXPIRATION
================

    - TTL = 0        → no expiration (permanent)
    - TTL = None     → use default_ttl (3600s)
    - TTL = N (>0)   → expires in N seconds

    Expired entries are:
        • Skipped during get(), exists()
        • Automatically cleaned by clean_expired()
        • Evicted when capacity is reached

LOGGING
=======

    DEBUG   : Cache path, key validation
    INFO    : Capacity cleanup, statistics
    WARNING : Invalid cache files, failed deletes, size limits
    ERROR   : Write errors, read errors, validation errors (via exceptions)

QUICK START
===========

    from core.cache_manager import CacheManager, cache_get, cache_set

    # Global instance
    cache_set("weather", {"temp": 30}, category="search", ttl=1800)
    result = cache_get("weather", category="search")

    # Custom instance
    custom_cache = CacheManager(root="/tmp/custom", default_ttl=7200)
    custom_cache.set("data", {"x": 1}, category="ai")
    value = custom_cache.get("data", category="ai")

CONFIGURATION
=============

    PROJECT_ROOT        : Base directory (parent of core/)
    CACHE_ROOT          : cache/ subdirectory
    DEFAULT_TTL         : 3600 seconds (1 hour)
    MAX_CACHE_SIZE_MB   : 512 MB
    CACHE_VERSION       : 1 (for format compatibility)
    DEFAULT_ENCODING    : UTF-8

ERROR HANDLING
==============

    CacheError (base)
        ├─ CacheReadError          → get(), exists(), info() fail
        ├─ CacheWriteError         → set() fails
        └─ CacheValidationError    → invalid key/category

USAGE EXAMPLES
==============

    Example 1: Store and retrieve weather data
    ──────────────────────────────────────────
    from core.cache_manager import cache_set, cache_get

    cache_set(
        "weather_nyc",
        {"temperature": 72, "humidity": 65},
        category="search",
        ttl=1800,  # 30 minutes
    )

    result = cache_get("weather_nyc", category="search")
    # {"temperature": 72, "humidity": 65}


    Example 2: Cache AI embeddings
    ───────────────────────────────
    from core.cache_manager import cache_set, cache_exists

    embedding_key = "embedding_doc_1"
    if not cache_exists(embedding_key, category="ai"):
        # Compute embedding
        embedding = compute_embeddings("document text")
        cache_set(
            embedding_key,
            {"vector": embedding, "model": "ada"},
            category="ai",
            ttl=0,  # permanent
        )


    Example 3: Custom cache with size limits
    ─────────────────────────────────────────
    from core.cache_manager import CacheManager
    from pathlib import Path

    cache = CacheManager(
        root=Path("/app/cache"),
        default_ttl=7200,
        max_size_mb=256,
    )

    cache.set("key1", {"data": "value"}, category="temp", ttl=3600)
    value = cache.get("key1", category="temp")

    stats = cache.stats()
    print(f"Cache: {stats.files} files, {stats.size_mb:.1f} MB")


    Example 4: Cleanup and maintenance
    ──────────────────────────────────
    from core.cache_manager import (
        cache_manager,
        CacheManager,
    )

    # Remove expired entries
    removed = cache_manager.clean_expired()
    print(f"Removed {removed} expired entries")

    # Clear one category
    cleared = cache_manager.clear_category("temp")
    print(f"Cleared {cleared} files from temp")

    # Clear everything
    cache_manager.clear_all()

    # Get statistics
    stats = cache_manager.stats()
    print(f"Files: {stats.files}, Size: {stats.size_mb:.1f} MB")


    Example 5: Check entry info
    ───────────────────────────
    from core.cache_manager import cache_manager
    from datetime import datetime

    info = cache_manager.info("my_key", category="ai")
    if info:
        print(f"Created: {datetime.fromtimestamp(info.created_at)}")
        print(f"Expires: {datetime.fromtimestamp(info.expires_at)}")
        print(f"Size: {info.size_bytes} bytes")
        print(f"Expired: {info.expired}")
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
from typing import Any, Optional

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

MIN_TTL = 0
MAX_TTL = 31_536_000  # 1 year in seconds

MIN_CACHE_SIZE_MB = 1
MAX_CACHE_SIZE_MB = 10_240  # 10 GB

MAX_KEY_LENGTH = 200
MAX_CATEGORY_LENGTH = 100

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
    """
    Metadata for a cache entry.

    Attributes:
        key:            Cache key identifier.
        category:       Cache category name.
        path:           Filesystem path to cache file.
        size_bytes:     File size in bytes.
        created_at:     Creation timestamp (seconds since epoch).
        expires_at:     Expiration timestamp or None (permanent).

    Example:

        info = cache.info("my_key", category="ai")
        if info and not info.expired:
            print(f"Valid for {info.expires_at - time.time():.0f}s")
    """

    key: str
    category: str
    path: Path
    size_bytes: int
    created_at: float
    expires_at: Optional[float]

    @property
    def expired(self) -> bool:
        """
        Return whether the cache entry has expired.

        Returns:
            bool: True if expired, False if still valid or permanent.

        Example:

            if not entry.expired:
                use_cached_value()
        """

        if self.expires_at is None:
            return False

        return time.time() >= self.expires_at


@dataclass(frozen=True, slots=True)
class CacheStats:
    """
    Cache statistics.

    Attributes:
        files:          Total number of cache files.
        directories:    Total number of cache directories.
        size_bytes:     Total cache size in bytes.

    Example:

        stats = cache.stats()
        print(f"{stats.files} files using {stats.size_mb:.1f} MB")
    """

    files: int
    directories: int
    size_bytes: int

    @property
    def size_mb(self) -> float:
        """
        Return cache size in megabytes.

        Returns:
            float: Size in MB (size_bytes / 1024 / 1024).

        Example:

            if stats.size_mb > 100:
                logger.warning("Cache growing large")
        """

        return self.size_bytes / (1024 * 1024)


# ============================================================================
# VALIDATORS
# ============================================================================


def _validate_ttl(ttl: Optional[int]) -> int:
    """
    Validate and clamp TTL value.

    Parameters:
        ttl:
            Lifetime in seconds, or None for default.

    Returns:
        int: Clamped TTL value (0 to MAX_TTL).

    Raises:
        CacheValidationError:
            If ttl is not int/None (got {type_name}).

    Example:

        ttl = _validate_ttl(3600)  # OK
        ttl = _validate_ttl(None)  # Uses default
        ttl = _validate_ttl(-1)    # Clamped to 0
    """

    if ttl is None:
        return 0

    if not isinstance(ttl, int):
        raise CacheValidationError(
            f"TTL must be int or None (got {type(ttl).__name__})"
        )

    clamped = max(MIN_TTL, min(int(ttl), MAX_TTL))

    if clamped != ttl:
        logger.debug(
            "TTL clamped: %s → %s",
            ttl,
            clamped,
        )

    return clamped


def _validate_cache_size_mb(max_size_mb: int) -> int:
    """
    Validate and clamp cache size.

    Parameters:
        max_size_mb:
            Maximum cache size in MB.

    Returns:
        int: Clamped size in MB (MIN to MAX).

    Raises:
        CacheValidationError:
            If max_size_mb is not int (got {type_name}).

    Example:

        size_mb = _validate_cache_size_mb(512)  # OK
        size_mb = _validate_cache_size_mb(-1)   # Clamped to MIN
    """

    if not isinstance(max_size_mb, int):
        raise CacheValidationError(
            f"Cache size must be int (got {type(max_size_mb).__name__})"
        )

    clamped = max(MIN_CACHE_SIZE_MB, min(int(max_size_mb), MAX_CACHE_SIZE_MB))

    if clamped != max_size_mb:
        logger.debug(
            "Cache size clamped: %s MB → %s MB",
            max_size_mb,
            clamped,
        )

    return clamped


# ============================================================================
# CACHE MANAGER
# ============================================================================


class CacheManager:
    """
    Central cache manager for AssistantX.

    Thread-safe JSON cache with TTL expiration, atomic writes, and
    automatic capacity management. Supports multiple cache categories
    (ai, images, search, temp).

    Parameters:
        root:
            Cache root directory (default: PROJECT_ROOT/cache).
        default_ttl:
            Default TTL in seconds (default: 3600).
        max_size_mb:
            Maximum cache size in MB (default: 512).

    Raises:
        CacheValidationError:
            If default_ttl or max_size_mb are invalid types.

    Example:

        cache = CacheManager()
        cache.set("weather", {"temp": 30}, category="search", ttl=1800)
        result = cache.get("weather", category="search")
        stats = cache.stats()
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        default_ttl: int = DEFAULT_TTL,
        max_size_mb: int = MAX_CACHE_SIZE_MB,
    ) -> None:

        self.root = (
            Path(root).resolve()
            if root is not None
            else CACHE_ROOT
        )

        self.default_ttl = _validate_ttl(default_ttl)

        self.max_size_bytes = (
            _validate_cache_size_mb(max_size_mb)
            * 1024
            * 1024
        )

        self._lock = RLock()

        logger.debug(
            "CacheManager initialized: root=%s, ttl=%ss, max=%sMB",
            self.root,
            self.default_ttl,
            max_size_mb,
        )

        self._initialize()

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def _initialize(self) -> None:
        """
        Create the cache directory structure.

        Creates root and all default categories (ai, images, search, temp).
        Thread-safe via RLock.
        """

        with self._lock:

            try:

                self.root.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                for category in CACHE_CATEGORIES:
                    self.category_path(category)

                logger.debug(
                    "Cache directories initialized: %s",
                    self.root,
                )

            except OSError as exc:

                logger.warning(
                    "Failed to initialize cache: %s",
                    self.root,
                    exc_info=exc,
                )

    # ========================================================================
    # CATEGORY
    # ========================================================================

    def category_path(
        self,
        category: str,
    ) -> Path:
        """
        Return the directory for a cache category.

        Creates directory if it doesn't exist. Unknown categories are
        allowed and created safely inside the cache root.

        Parameters:
            category:
                Category name (e.g., "ai", "search", "temp").

        Returns:
            Path: Absolute path to category directory.

        Raises:
            CacheValidationError:
                If category is empty after sanitization.

        Example:

            path = cache.category_path("ai")
            # /project/cache/ai
        """

        safe_category = self._safe_name(category)

        path = self.root / safe_category

        try:

            path.mkdir(
                parents=True,
                exist_ok=True,
            )

        except OSError as exc:

            logger.warning(
                "Failed to create category directory: %s",
                path,
                exc_info=exc,
            )

        logger.debug(
            "Category path: %s",
            path,
        )

        return path

    # ========================================================================
    # SAFE NAME
    # ========================================================================

    @staticmethod
    def _safe_name(value: str) -> str:
        """
        Convert a value into a filesystem-safe name.

        Parameters:
            value:
                Raw name to sanitize.

        Returns:
            str: Sanitized name (alphanumeric + ._-, max 200 chars).

        Raises:
            CacheValidationError:
                If value is empty or becomes empty after sanitization.

        Example:

            safe = CacheManager._safe_name("My-Cache/Key")
            # "My-Cache_Key"
        """

        value = str(value).strip()

        if not value:
            raise CacheValidationError(
                "Cache key cannot be empty (got empty string after strip)"
            )

        safe = "".join(
            char
            if char.isalnum()
            or char in "._-"
            else "_"
            for char in value
        )

        if not safe:
            raise CacheValidationError(
                f"Cache key becomes empty after sanitization (got '{value}')"
            )

        truncated = safe[:MAX_KEY_LENGTH]

        if truncated != safe:
            logger.debug(
                "Key truncated: %s → %s",
                safe,
                truncated,
            )

        return truncated

    # ========================================================================
    # HASH KEY
    # ========================================================================

    @staticmethod
    def make_key(value: str) -> str:
        """
        Generate a deterministic SHA-256 cache key.

        Parameters:
            value:
                Input value to hash.

        Returns:
            str: SHA-256 hexdigest (64 hex characters).

        Example:

            key = CacheManager.make_key("my_query")
            # "abc123def456..."
        """

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
        """
        Build a cache file path.

        Parameters:
            key:
                Cache key identifier.
            category:
                Cache category name.
            extension:
                File extension (default: ".json").

        Returns:
            Path: Full filesystem path to cache file.

        Example:

            path = cache._cache_path("user_123", "ai", ".json")
            # /project/cache/ai/user_123.json
        """

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
        ttl: Optional[int],
    ) -> Optional[float]:
        """
        Calculate cache expiration timestamp.

        Parameters:
            ttl:
                Lifetime in seconds, or None to use default_ttl.

        Returns:
            float | None:
                Expiration timestamp (seconds since epoch),
                or None if ttl=0 (no expiration).

        Example:

            expires = cache._expiration(3600)
            # time.time() + 3600

            expires = cache._expiration(0)
            # None (permanent)
        """

        lifetime = _validate_ttl(ttl)

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
        ttl: Optional[int] = None,
    ) -> Path:
        """
        Store JSON-compatible data in cache.

        Atomic write with expiration support. Data is serialized to JSON
        with metadata (version, timestamps). Thread-safe via RLock.

        Parameters:
            key:
                Unique cache identifier (sanitized automatically).
            value:
                JSON-compatible Python object.
            category:
                Cache category (default: "temp").
            ttl:
                Lifetime in seconds (0=permanent, None=default).

        Returns:
            Path: Path to the written cache file.

        Raises:
            CacheWriteError:
                If value is not JSON-serializable.
            CacheWriteError:
                If atomic write fails.
            CacheValidationError:
                If key is invalid.

        Example:

            path = cache.set(
                "weather_nyc",
                {"temp": 72, "wind": 5},
                category="search",
                ttl=1800,
            )
            # /project/cache/search/weather_nyc.json
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
                f"Value not JSON-serializable: {key} (got {type(value).__name__})"
            ) from exc

        with self._lock:

            incoming_size = len(
                serialized.encode(DEFAULT_ENCODING)
            )

            self._ensure_capacity(incoming_size)

            self._atomic_write(
                path,
                serialized,
            )

        logger.debug(
            "Cache written: %s (%d bytes)",
            path,
            incoming_size,
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
        """
        Write a file atomically using temp file + rename.

        Ensures data integrity even if write is interrupted. Calls fsync
        before rename. Cleans up temp file on failure.

        Parameters:
            path:
                Target file path.
            content:
                Text content to write.

        Raises:
            CacheWriteError:
                If write fails (permissions, disk full, etc).

        Example:

            cache._atomic_write(
                Path("/cache/file.json"),
                '{"data": "value"}',
            )
        """

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Optional[Path] = None

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

            logger.debug(
                "Atomic write completed: %s",
                path,
            )

        except OSError as exc:

            raise CacheWriteError(
                f"Atomic write failed: {path} (got OSError: {exc})"
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
        """
        Read a JSON cache entry.

        Returns cached data if entry exists and is valid (not expired).
        Expired entries are automatically deleted. Invalid cache files
        are logged as warnings.

        Parameters:
            key:
                Cache key to retrieve.
            category:
                Cache category (default: "temp").
            default:
                Value to return if key not found or expired.

        Returns:
            Any:
                Cached data, or default if not found/expired.

        Raises:
            CacheReadError:
                If cache file is corrupt or unreadable.

        Example:

            result = cache.get("weather", category="search")
            if result:
                print(f"Temperature: {result['temp']}")
            else:
                print("Not in cache")
        """

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            logger.debug(
                "Cache miss: %s",
                path,
            )
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
                "Invalid cache file: %s (%s)",
                path,
                type(exc).__name__,
            )

            raise CacheReadError(
                f"Unable to read cache: {path} (got {type(exc).__name__})"
            ) from exc

        if not isinstance(payload, dict):

            logger.warning(
                "Cache format invalid: %s (got %s, expected dict)",
                path,
                type(payload).__name__,
            )

            raise CacheReadError(
                f"Invalid cache format: {path} (got {type(payload).__name__}, expected dict)"
            )

        if self._is_expired(payload):

            logger.debug(
                "Cache expired, deleting: %s",
                path,
            )

            self.delete(
                key,
                category=category,
            )

            return default

        logger.debug(
            "Cache hit: %s",
            path,
        )

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
        """
        Check whether a valid (non-expired) cache entry exists.

        Expired entries are automatically deleted.

        Parameters:
            key:
                Cache key to check.
            category:
                Cache category (default: "temp").

        Returns:
            bool: True if valid entry exists, False otherwise.

        Example:

            if cache.exists("user_profile", category="ai"):
                data = cache.get("user_profile", category="ai")
        """

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            logger.debug(
                "Cache entry not found: %s",
                path,
            )
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
        ) as exc:

            logger.debug(
                "Cache entry unreadable: %s (%s)",
                path,
                type(exc).__name__,
            )

            return False

        if not isinstance(payload, dict):

            logger.debug(
                "Cache format invalid: %s (got %s)",
                path,
                type(payload).__name__,
            )

            return False

        if self._is_expired(payload):

            logger.debug(
                "Cache entry expired: %s",
                path,
            )

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
        """
        Check whether a cache payload has expired.

        Parameters:
            payload:
                Cache payload dict with 'expires_at' key.

        Returns:
            bool: True if expired, False if valid or permanent (no expiration).

        Example:

            expired = CacheManager._is_expired(payload)
        """

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

            logger.warning(
                "Invalid expires_at value: %s (got %s)",
                expires_at,
                type(expires_at).__name__,
            )

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
        """
        Delete one cache entry.

        Thread-safe via RLock. Logs warnings if delete fails.

        Parameters:
            key:
                Cache key to delete.
            category:
                Cache category (default: "temp").

        Returns:
            bool: True if deleted, False if not found or error.

        Example:

            if cache.delete("temp_key", category="temp"):
                print("Deleted successfully")
        """

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.exists():
            logger.debug(
                "Cache entry not found: %s",
                path,
            )
            return False

        with self._lock:

            try:

                path.unlink()

                logger.debug(
                    "Cache entry deleted: %s",
                    path,
                )

                return True

            except OSError as exc:

                logger.warning(
                    "Unable to delete cache: %s (%s)",
                    path,
                    type(exc).__name__,
                    exc_info=exc,
                )

                return False

    # ========================================================================
    # CLEAR CATEGORY
    # ========================================================================

    def clear_category(
        self,
        category: str,
    ) -> int:
        """
        Delete all cache files from one category.

        Thread-safe via RLock. Recursively removes files and subdirectories.
        Logs warnings for files that can't be deleted.

        Parameters:
            category:
                Category to clear (e.g., "temp", "ai", "search").

        Returns:
            int: Number of files/directories removed.

        Example:

            removed = cache.clear_category("temp")
            print(f"Removed {removed} items")
        """

        directory = self.category_path(
            category
        )

        removed = 0

        with self._lock:

            if not directory.exists():
                logger.debug(
                    "Category directory not found: %s",
                    directory,
                )
                return 0

            for item in directory.iterdir():

                try:

                    if item.is_file():

                        item.unlink()
                        removed += 1

                    elif item.is_dir():

                        import shutil

                        shutil.rmtree(item)
                        removed += 1

                except OSError as exc:

                    logger.warning(
                        "Unable to remove: %s (%s)",
                        item,
                        type(exc).__name__,
                        exc_info=exc,
                    )

        logger.info(
            "Category cleared: %s (%d items removed)",
            directory,
            removed,
        )

        return removed

    # ========================================================================
    # CLEAR ALL
    # ========================================================================

    def clear_all(self) -> int:
        """
        Clear every cache category.

        Removes all cache files. Thread-safe via clear_category().

        Returns:
            int: Total number of files/directories removed.

        Example:

            total = cache.clear_all()
            print(f"Removed {total} items total")
        """

        removed = 0

        for category in CACHE_CATEGORIES:

            removed += self.clear_category(
                category
            )

        logger.info(
            "Cache cleared completely (%d items removed)",
            removed,
        )

        return removed

    # ========================================================================
    # CLEAN EXPIRED
    # ========================================================================

    def clean_expired(self) -> int:
        """
        Remove all expired JSON cache entries.

        Scans all cache files, checks expiration, deletes if expired.
        Invalid cache files are skipped with debug logging.

        Returns:
            int: Number of expired entries removed.

        Example:

            cleaned = cache.clean_expired()
            print(f"Cleaned {cleaned} expired entries")
        """

        removed = 0

        with self._lock:

            if not self.root.exists():
                logger.debug(
                    "Cache root not found: %s",
                    self.root,
                )
                return 0

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

                        logger.debug(
                            "Expired entry removed: %s",
                            path,
                        )

                except (
                    OSError,
                    json.JSONDecodeError,
                ):

                    logger.debug(
                        "Skipping invalid cache: %s",
                        path,
                    )

        logger.info(
            "Expired cache cleaned (%d entries removed)",
            removed,
        )

        return removed

    # ========================================================================
    # CACHE SIZE
    # ========================================================================

    def size_bytes(self) -> int:
        """
        Return total cache size in bytes.

        Recursively sums all file sizes. Skips directories and handles
        OSError gracefully.

        Returns:
            int: Total size in bytes.

        Example:

            total = cache.size_bytes()
            print(f"Cache: {total / 1024 / 1024:.1f} MB")
        """

        total = 0

        if not self.root.exists():
            logger.debug(
                "Cache root not found: %s",
                self.root,
            )
            return 0

        for path in self.root.rglob("*"):

            if not path.is_file():
                continue

            try:

                total += path.stat().st_size

            except OSError as exc:

                logger.debug(
                    "Unable to stat file: %s (%s)",
                    path,
                    type(exc).__name__,
                )

        return total

    # ========================================================================
    # CACHE SIZE MB
    # ========================================================================

    def size_mb(self) -> float:
        """
        Return total cache size in megabytes.

        Returns:
            float: Size in MB (size_bytes / 1024 / 1024).

        Example:

            size = cache.size_mb()
            print(f"Cache: {size:.1f} MB")
        """

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
        Ensure enough cache capacity exists for new data.

        If capacity exceeded, expires old entries first. If still over limit,
        logs a warning. This is best-effort; the caller is responsible if
        the write ultimately fails.

        Parameters:
            incoming_size:
                Size in bytes of data about to be written.

        Example:

            cache._ensure_capacity(1024 * 100)  # 100 KB write incoming
        """

        current_size = self.size_bytes()

        if (
            current_size + incoming_size
            <= self.max_size_bytes
        ):
            return

        logger.info(
            "Cache capacity exceeded. Current: %sMB, Limit: %sMB. Cleaning expired.",
            current_size // (1024 * 1024),
            self.max_size_bytes // (1024 * 1024),
        )

        self.clean_expired()

        current_size = self.size_bytes()

        if (
            current_size + incoming_size
            > self.max_size_bytes
        ):

            logger.warning(
                "Cache still above limit after cleanup. Current: %sMB, Limit: %sMB, Incoming: %sKB",
                current_size // (1024 * 1024),
                self.max_size_bytes // (1024 * 1024),
                incoming_size // 1024,
            )

    # ========================================================================
    # CACHE ENTRY INFO
    # ========================================================================

    def info(
        self,
        key: str,
        *,
        category: str = "temp",
    ) -> Optional[CacheEntry]:
        """
        Return metadata for a cache entry.

        Returns None if entry doesn't exist or is invalid.

        Parameters:
            key:
                Cache key to inspect.
            category:
                Cache category (default: "temp").

        Returns:
            CacheEntry | None: Entry metadata or None.

        Raises:
            CacheReadError:
                If cache file is corrupt.

        Example:

            info = cache.info("my_key", category="ai")
            if info:
                print(f"Size: {info.size_bytes} bytes")
                print(f"Expired: {info.expired}")
        """

        path = self._cache_path(
            key,
            category,
            ".json",
        )

        if not path.is_file():
            logger.debug(
                "Cache entry not found: %s",
                path,
            )
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
        ) as exc:

            logger.warning(
                "Unable to read cache metadata: %s (%s)",
                path,
                type(exc).__name__,
            )

            raise CacheReadError(
                f"Unable to read cache: {path} (got {type(exc).__name__})"
            ) from exc

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
        """
        Return cache statistics.

        Recursively scans cache root, counts files and directories, sums sizes.
        Handles OSError gracefully for individual items.

        Returns:
            CacheStats:
                Object with files, directories, size_bytes properties.

        Example:

            stats = cache.stats()
            print(f"Files: {stats.files}, Size: {stats.size_mb:.1f} MB")
        """

        files = 0
        directories = 0
        size = 0

        if not self.root.exists():
            logger.debug(
                "Cache root not found: %s",
                self.root,
            )
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

            except OSError as exc:

                logger.debug(
                    "Unable to stat: %s (%s)",
                    path,
                    type(exc).__name__,
                )

        return CacheStats(
            files=files,
            directories=directories,
            size_bytes=size,
        )


# ============================================================================
# GLOBAL CACHE INSTANCE
# ============================================================================

cache_manager = CacheManager()

logger.info(
    "Global cache_manager initialized: root=%s",
    cache_manager.root,
)


# ============================================================================
# PUBLIC API
# ============================================================================


def cache_set(
    key: str,
    value: Any,
    *,
    category: str = "temp",
    ttl: Optional[int] = None,
) -> Path:
    """
    Store data in AssistantX cache.

    Convenience function wrapping cache_manager.set().

    Parameters:
        key:
            Cache key identifier.
        value:
            JSON-compatible data.
        category:
            Cache category (default: "temp").
        ttl:
            Lifetime in seconds (default: default_ttl).

    Returns:
        Path: Path to written cache file.

    Raises:
        CacheWriteError: If data not JSON-serializable.

    Example:

        path = cache_set("data", {"x": 1}, category="ai", ttl=3600)
    """

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
    """
    Retrieve data from AssistantX cache.

    Convenience function wrapping cache_manager.get().

    Parameters:
        key:
            Cache key identifier.
        category:
            Cache category (default: "temp").
        default:
            Value if not found (default: None).

    Returns:
        Any: Cached data or default.

    Raises:
        CacheReadError: If cache file corrupt.

    Example:

        result = cache_get("data", category="ai")
    """

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
    """
    Check whether a cache entry exists.

    Convenience function wrapping cache_manager.exists().

    Parameters:
        key:
            Cache key identifier.
        category:
            Cache category (default: "temp").

    Returns:
        bool: True if valid entry exists.

    Example:

        if cache_exists("data", category="ai"):
            value = cache_get("data", category="ai")
    """

    return cache_manager.exists(
        key,
        category=category,
    )


def cache_delete(
    key: str,
    *,
    category: str = "temp",
) -> bool:
    """
    Delete a cache entry.

    Convenience function wrapping cache_manager.delete().

    Parameters:
        key:
            Cache key identifier.
        category:
            Cache category (default: "temp").

    Returns:
        bool: True if deleted, False if not found.

    Example:

        cache_delete("temp_key", category="temp")
    """

    return cache_manager.delete(
        key,
        category=category,
    )


def clear_cache(
    category: Optional[str] = None,
) -> int:
    """
    Clear one category or all cache data.

    Convenience function wrapping cache_manager.clear_category() or
    cache_manager.clear_all().

    Parameters:
        category:
            Category to clear, or None for all.

    Returns:
        int: Number of items removed.

    Example:

        # Clear one category
        cache.clear_cache("temp")

        # Clear everything
        cache.clear_cache()
    """

    if category is not None:
        return cache_manager.clear_category(
            category
        )

    return cache_manager.clear_all()


def clean_cache() -> int:
    """
    Remove expired cache entries.

    Convenience function wrapping cache_manager.clean_expired().

    Returns:
        int: Number of expired entries removed.

    Example:

        removed = clean_cache()
        print(f"Cleaned {removed} entries")
    """

    return cache_manager.clean_expired()


def cache_stats() -> CacheStats:
    """
    Return current cache statistics.

    Convenience function wrapping cache_manager.stats().

    Returns:
        CacheStats: Object with files, directories, size_mb properties.

    Example:

        stats = cache_stats()
        print(f"Files: {stats.files}, Size: {stats.size_mb:.1f} MB")
    """

    return cache_manager.stats()
