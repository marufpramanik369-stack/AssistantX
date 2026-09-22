"""
automation/files.py
===================

Professional file-level automation for AssistantX.

Features:
    - Create files
    - Delete files
    - Rename files
    - Move files
    - Copy files
    - Search files/directories
    - Read text files
    - File existence checks
    - File metadata
    - Safe wrappers for automation layer
    - Cross-platform path handling
    - Validation and logging

IMPORTANT:
    Destructive operations such as delete/overwrite should normally be
    confirmation-gated by brain/decision_engine.py before reaching this
    module.

This module intentionally does NOT ask the user for confirmation.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from fileinput import filename
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_SEARCH_ROOT_NAMES: tuple[str, ...] = (
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
)

DEFAULT_MAX_SEARCH_RESULTS = 20
DEFAULT_MAX_SEARCH_DEPTH = 6
DEFAULT_MAX_READ_CHARS = 5000

# Files that AssistantX should never silently replace/delete.
PROTECTED_FILENAMES = {
    ".env",
    ".gitignore",
}

# Common dangerous/system locations.
PROTECTED_DIRECTORY_NAMES = {
    "Windows",
    "System32",
    "Program Files",
    "Program Files (x86)",
}


# ============================================================================
# Exceptions
# ============================================================================


class FileOperationError(RuntimeError):
    """Base exception for file automation failures."""


class FileValidationError(FileOperationError):
    """Raised when an input path/name/value is invalid."""


class FileNotFoundError(FileOperationError):
    """Raised when a requested file does not exist."""


class FileAlreadyExistsError(FileOperationError):
    """Raised when a destination already exists."""


class FileSafetyError(FileOperationError):
    """Raised when an operation would be unsafe."""


class FileReadError(FileOperationError):
    """Raised when a file cannot be read."""


class FileWriteError(FileOperationError):
    """Raised when a file cannot be written."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class FileSearchResult:
    """Represents one search result."""

    path: Path
    size_bytes: int
    is_directory: bool

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "size_bytes": self.size_bytes,
            "is_directory": self.is_directory,
        }


@dataclass(frozen=True)
class FileInfo:
    """Basic metadata about a file or directory."""

    path: Path
    name: str
    size_bytes: int
    is_directory: bool
    is_file: bool
    is_symlink: bool
    modified_timestamp: float
    created_timestamp: float

    def to_dict(self) -> dict:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


# ============================================================================
# Internal Helpers
# ============================================================================


def _home() -> Path:
    """Return the current user's home directory."""
    return Path.home()


def normalize_path(path: str | Path) -> Path:
    """
    Normalize and expand a filesystem path.

    Does not require the path to exist.
    """
    if path is None:
        raise FileValidationError("Path cannot be None.")

    raw = str(path).strip()

    if not raw:
        raise FileValidationError("Path cannot be empty.")

    return Path(raw).expanduser()


def _validate_filename(filename: str) -> str:
    """Validate a filename without allowing path traversal."""
    if filename is None:
        raise FileValidationError("Filename cannot be None.")

    name = str(filename).strip()

    if not name:
        raise FileValidationError("Filename cannot be empty.")

    if name in {".", ".."}:
        raise FileValidationError("Invalid filename.")

    # A filename should not contain path separators.
    if "/" in name or "\\" in name:
        raise FileValidationError(
            f"Invalid filename '{filename}'. Use a filename only, not a path."
        )

    return name


def _validate_positive_int(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FileValidationError(f"{name} must be an integer.")

    if value <= 0:
        raise FileValidationError(f"{name} must be greater than zero.")

    return value


def _ensure_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"'{path}' does not exist.")


def _ensure_file(path: Path) -> None:
    _ensure_exists(path)

    if not path.is_file():
        raise FileValidationError(f"'{path}' is not a file.")


def _ensure_directory(path: Path) -> None:
    _ensure_exists(path)

    if not path.is_dir():
        raise FileValidationError(f"'{path}' is not a directory.")


def _is_protected_file(path: Path) -> bool:
    """Return True if the file is considered sensitive/protected."""
    return path.name.lower() in {
        name.lower() for name in PROTECTED_FILENAMES
    }


def _is_protected_location(path: Path) -> bool:
    """
    Prevent accidental destructive operations on obvious system locations.
    """
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path.absolute()

    # Filesystem root.
    if resolved == Path(resolved.anchor):
        return True

    # Home directory itself.
    if resolved == _home().resolve():
        return True

    # Windows/system-style protected folders.
    for part in resolved.parts:
        if part in PROTECTED_DIRECTORY_NAMES:
            return True

    return False


def _search_roots() -> list[Path]:
    """
    Resolve default search roots.

    Existing common user directories are returned.
    """
    home = _home()

    roots: list[Path] = []

    for name in DEFAULT_SEARCH_ROOT_NAMES:
        directory = home / name

        try:
            if directory.exists() and directory.is_dir():
                roots.append(directory)
        except OSError:
            continue

    return roots


def _safe_stat_size(path: Path) -> int:
    """Return file size without allowing stat errors to break a search."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ============================================================================
# Create
# ============================================================================


def create_file(
    filename: str,
    directory: str | None = None,
    content: str = "",
) -> Path:
    """
    Create a new file.

    By default the file is created on Desktop.

    Existing files are never overwritten.
    """
    parsed_path = Path(filename)
    if (parsed_path.is_absolute() or len(parsed_path.parts) > 1) and directory is None:
        directory = str(parsed_path.parent)

    filename = os.path.basename(filename)

    if not isinstance(content, str):
        raise FileValidationError("File content must be a string.")

    target_dir = (
        normalize_path(directory)
        if directory
        else _home() / "Desktop"
    )

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileWriteError(
            f"Could not create directory '{target_dir}': {exc}"
        ) from exc

    if not target_dir.is_dir():
        raise FileValidationError(
            f"'{target_dir}' is not a directory."
        )

    target_path = target_dir / filename

    if target_path.exists():
        raise FileAlreadyExistsError(
            f"A file named '{filename}' already exists at '{target_dir}'."
        )

    try:
        target_path.write_text(
            content,
            encoding="utf-8",
            errors="strict",
        )
    except OSError as exc:
        raise FileWriteError(
            f"Could not create '{target_path}': {exc}"
        ) from exc

    logger.info("Created file: %s", target_path)

    return target_path


# ============================================================================
# Delete
# ============================================================================


def delete_file(path: str) -> bool:
    """
    Delete a single file.

    This function does not ask for confirmation.
    Confirmation should be handled upstream.
    """
    file_path = normalize_path(path)

    _ensure_file(file_path)

    if _is_protected_file(file_path):
        raise FileSafetyError(
            f"Refusing to delete protected file '{file_path.name}'."
        )

    if _is_protected_location(file_path):
        raise FileSafetyError(
            f"Refusing to delete protected/system location '{file_path}'."
        )

    try:
        file_path.unlink()
    except OSError as exc:
        raise FileOperationError(
            f"Could not delete '{file_path}': {exc}"
        ) from exc

    logger.warning("Deleted file: %s", file_path)

    return True


# ============================================================================
# Rename
# ============================================================================


def rename_file(path: str, new_name: str) -> Path:
    """Rename a file while keeping it in the same directory."""
    file_path = normalize_path(path)

    _ensure_file(file_path)

    new_name = os.path.basename(new_name)

    if _is_protected_file(file_path):
        raise FileSafetyError(
            f"Refusing to rename protected file '{file_path.name}'."
        )

    new_path = file_path.with_name(new_name)

    if new_path == file_path:
        return file_path

    if new_path.exists():
        raise FileAlreadyExistsError(
            f"A file named '{filename}' already exists in that location."  
        )

    try:
        file_path.rename(new_path)
    except OSError as exc:
        raise FileOperationError(
            f"Could not rename '{file_path}' to '{new_path}': {exc}"
        ) from exc

    logger.info(
        "Renamed file '%s' -> '%s'",
        file_path,
        new_path,
    )

    return new_path


# ============================================================================
# Move
# ============================================================================


def move_file(
    path: str,
    destination_dir: str,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Move a file to another directory.

    Args:
        path: Source file.
        destination_dir: Destination directory.
        overwrite: Whether an existing destination may be replaced.

    Existing destination is protected by default.
    """
    file_path = normalize_path(path)
    dest_dir = normalize_path(destination_dir)

    _ensure_file(file_path)

    if _is_protected_file(file_path):
        raise FileSafetyError(
            f"Refusing to move protected file '{file_path.name}'."
        )

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileOperationError(
            f"Could not create destination directory '{dest_dir}': {exc}"
        ) from exc

    if not dest_dir.is_dir():
        raise FileValidationError(
            f"Destination '{dest_dir}' is not a directory."
        )

    dest_path = dest_dir / file_path.name

    if dest_path.exists():
        if not overwrite:
            raise FileAlreadyExistsError(
                f"Destination file already exists: '{dest_path}'."
            )

        if _is_protected_file(dest_path):
            raise FileSafetyError(
                f"Refusing to overwrite protected file '{dest_path.name}'."
            )

        if _is_protected_location(dest_path):
            raise FileSafetyError(
                f"Refusing to overwrite protected location '{dest_path}'."
            )

        try:
            dest_path.unlink()
        except OSError as exc:
            raise FileOperationError(
                f"Could not remove existing destination '{dest_path}': {exc}"
            ) from exc

    try:
        shutil.move(str(file_path), str(dest_path))
    except OSError as exc:
        raise FileOperationError(
            f"Could not move '{file_path}' to '{dest_dir}': {exc}"
        ) from exc

    logger.info(
        "Moved file '%s' -> '%s'",
        file_path,
        dest_path,
    )

    return dest_path


# ============================================================================
# Copy
# ============================================================================


def copy_file(
    path: str,
    destination_dir: str,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Copy a file to another directory.

    The original file remains untouched.
    """
    file_path = normalize_path(path)
    dest_dir = normalize_path(destination_dir)

    _ensure_file(file_path)

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileOperationError(
            f"Could not create destination directory '{dest_dir}': {exc}"
        ) from exc

    if not dest_dir.is_dir():
        raise FileValidationError(
            f"Destination '{dest_dir}' is not a directory."
        )

    dest_path = dest_dir / file_path.name

    if dest_path.exists():
        if not overwrite:
            raise FileAlreadyExistsError(
                f"Destination file already exists: '{dest_path}'."
            )

        if _is_protected_file(dest_path):
            raise FileSafetyError(
                f"Refusing to overwrite protected file '{dest_path.name}'."
            )

        if _is_protected_location(dest_path):
            raise FileSafetyError(
                f"Refusing to overwrite protected location '{dest_path}'."
            )

    try:
        shutil.copy2(
            str(file_path),
            str(dest_path),
        )
    except OSError as exc:
        raise FileOperationError(
            f"Could not copy '{file_path}' to '{dest_dir}': {exc}"
        ) from exc

    logger.info(
        "Copied file '%s' -> '%s'",
        file_path,
        dest_path,
    )

    return dest_path


# ============================================================================
# Search
# ============================================================================

def search_files(
    query: str,
    roots: Iterable[Path] | None = None,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_depth: int = DEFAULT_MAX_SEARCH_DEPTH,
) -> list[FileSearchResult]:
    """
    Search for files/directories by name.

    Search is case-insensitive.

    Default roots:
        Desktop
        Documents
        Downloads
        Pictures

    Search depth and result count are bounded for performance.
    """
    if query is None:
        raise FileValidationError("Search query cannot be None.")

    query_clean = str(query).strip()

    if not query_clean:
        raise FileValidationError(
            "Search query cannot be empty."
        )

    max_results = _validate_positive_int(
        max_results,
        "max_results",
    )

    if not isinstance(max_depth, int) or isinstance(max_depth, bool):
        raise FileValidationError(
            "max_depth must be an integer."
        )

    if max_depth < 0:
        raise FileValidationError(
            "max_depth cannot be negative."
        )

    search_dirs = (
        list(roots)
        if roots is not None
        else _search_roots()
    )

    results: list[FileSearchResult] = []
    seen: set[Path] = set()

    query_lower = query_clean.casefold()

    for raw_root in search_dirs:
        try:
            root = normalize_path(raw_root)
        except FileValidationError:
            logger.debug(
                "Skipping invalid search root: %r",
                raw_root,
            )
            continue

        if not root.exists() or not root.is_dir():
            continue

        try:
            root_resolved = root.resolve() 
        except OSError:
            root_resolved = root.absolute()

        for dirpath, dirnames, filenames in os.walk(
            root_resolved,
            topdown=True,
            followlinks=False,
        ):
            current_dir = Path(dirpath)

            try:
                relative = current_dir.relative_to(root)
                depth = len(relative.parts)
            except ValueError:
                continue

            if depth >= max_depth:
                dirnames[:] = []

            # Skip hidden/system-ish directories when possible.
            dirnames[:] = [
                directory
                for directory in dirnames
                if not directory.startswith(".")
            ]

            entries = list(filenames) + list(dirnames)

            for name in entries:
                if query_lower not in name.casefold():
                    continue

                full_path = current_dir / name

                try:
                    resolved = full_path.resolve()
                except OSError:
                    resolved = full_path.absolute()

                if resolved in seen:
                    continue

                # Avoid duplicate roots/results.
                seen.add(resolved)

                try:
                    is_directory = full_path.is_dir()
                    size_bytes = (
                        0
                        if is_directory
                        else _safe_stat_size(full_path)
                    )
                except OSError:
                    continue

                results.append(
                    FileSearchResult(
                        path=full_path,
                        size_bytes=size_bytes,
                        is_directory=is_directory,
                    )
                )

                if len(results) >= max_results:
                    logger.debug(
                        "search_files reached max_results=%d for '%s'.",
                        max_results,
                        query_clean,
                    )
                    return results

    logger.info(
        "search_files found %d result(s) for '%s'.",
        len(results),
        query_clean,
    )

    return results


def search_file_paths(
    query: str,
    roots: Iterable[Path] | None = None,
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    max_depth: int = DEFAULT_MAX_SEARCH_DEPTH,
) -> list[Path]:
    """Convenience version of search_files() returning only Paths."""
    return [
        result.path
        for result in search_files(
            query=query,
            roots=roots,
            max_results=max_results,
            max_depth=max_depth,
        )
    ]


# ============================================================================
# Read
# ============================================================================


def read_text_file(
    path: str,
    max_chars: int = DEFAULT_MAX_READ_CHARS,
) -> str:
    """
    Read a UTF-8 text file.

    Content is truncated to max_chars.
    """
    file_path = normalize_path(path)

    _ensure_file(file_path)

    max_chars = _validate_positive_int(
        max_chars,
        "max_chars",
    )

    try:
        content = file_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, UnicodeError) as exc:
        raise FileReadError(
            f"Could not read '{file_path}': {exc}"
        ) from exc

    if len(content) > max_chars:
        return (
            content[:max_chars]
            + "\n...[truncated by AssistantX]"
        )

    return content


# ============================================================================
# Write / Append
# ============================================================================


def write_text_file(
    path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Write text to a file.

    By default existing files are protected.
    """
    file_path = normalize_path(path)

    if not isinstance(content, str):
        raise FileValidationError(
            "Content must be a string."
        )

    if file_path.exists() and not overwrite:
        raise FileAlreadyExistsError(
            f"File already exists: '{file_path}'."
        )

    if _is_protected_file(file_path) and overwrite:
        raise FileSafetyError(
            f"Refusing to overwrite protected file '{file_path.name}'."
        )

    if _is_protected_location(file_path) and overwrite:
        raise FileSafetyError(
            f"Refusing to overwrite protected location '{file_path}'."
        )

    try:
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )
    except OSError as exc:
        raise FileWriteError(
            f"Could not write '{file_path}': {exc}"
        ) from exc

    logger.info("Wrote text file: %s", file_path)

    return file_path


def append_text_file(
    path: str,
    content: str,
) -> Path:
    """Append UTF-8 text to an existing file."""
    file_path = normalize_path(path)

    if not isinstance(content, str):
        raise FileValidationError(
            "Content must be a string."
        )

    if file_path.exists():
        _ensure_file(file_path)

    try:
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with file_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(content)

    except OSError as exc:
        raise FileWriteError(
            f"Could not append to '{file_path}': {exc}"
        ) from exc

    logger.info("Appended text to: %s", file_path)

    return file_path


# ============================================================================
# Existence / Type
# ============================================================================


def file_exists(path: str) -> bool:
    """Return True when the given path exists."""
    try:
        return normalize_path(path).exists()
    except FileValidationError:
        return False


def is_file(path: str) -> bool:
    """Return True when the path points to a regular file."""
    try:
        return normalize_path(path).is_file()
    except FileValidationError:
        return False


def is_directory(path: str) -> bool:
    """Return True when the path points to a directory."""
    try:
        return normalize_path(path).is_dir()
    except FileValidationError:
        return False


# ============================================================================
# Metadata
# ============================================================================


def get_file_info(path: str) -> dict:
    """
    Return basic metadata about a file or directory.

    Backward-compatible dictionary format is preserved.
    """
    file_path = normalize_path(path)

    _ensure_exists(file_path)

    try:
        stat = file_path.stat()

        info = FileInfo(
            path=file_path,
            name=file_path.name,
            size_bytes=stat.st_size,
            is_directory=file_path.is_dir(),
            is_file=file_path.is_file(),
            is_symlink=file_path.is_symlink(),
            modified_timestamp=stat.st_mtime,
            created_timestamp=stat.st_ctime,
        )

    except OSError as exc:
        raise FileOperationError(
            f"Could not inspect '{file_path}': {exc}"
        ) from exc

    return info.to_dict()


def get_file_info_model(path: str) -> FileInfo:
    """Return FileInfo dataclass instead of a dictionary."""
    file_path = normalize_path(path)

    _ensure_exists(file_path)

    try:
        stat = file_path.stat()

        return FileInfo(
            path=file_path,
            name=file_path.name,
            size_bytes=stat.st_size,
            is_directory=file_path.is_dir(),
            is_file=file_path.is_file(),
            is_symlink=file_path.is_symlink(),
            modified_timestamp=stat.st_mtime,
            created_timestamp=stat.st_ctime,
        )

    except OSError as exc:
        raise FileOperationError(
            f"Could not inspect '{file_path}': {exc}"
        ) from exc


# ============================================================================
# File Size
# ============================================================================


def get_file_size(path: str) -> int:
    """Return file size in bytes."""
    file_path = normalize_path(path)

    _ensure_file(file_path)

    try:
        return file_path.stat().st_size
    except OSError as exc:
        raise FileOperationError(
            f"Could not determine size of '{file_path}': {exc}"
        ) from exc


# ============================================================================
# Safe Wrappers
# ============================================================================


def safe_create_file(
    filename: str,
    directory: str | None = None,
    content: str = "",
) -> Path | None:
    """
    Create a file safely.

    Returns:
        Path: Created file path on success.
        None: When the operation fails.
    """
    try:
        return create_file(
            filename=filename,
            directory=directory,
            content=content,
        )
    except FileOperationError as exc:
        logger.warning(
            "safe_create_file failed: %s",
            exc,
        )
        return None


def safe_rename_file(
    path: str,
    new_name: str,
) -> Path | None:
    """
    Rename a file safely.

    Returns:
        Path: New file path on success.
        None: When the operation fails.
    """
    try:
        return rename_file(
            path=path,
            new_name=new_name,
        )
    except FileOperationError as exc:
        logger.warning(
            "safe_rename_file failed: %s",
            exc,
        )
        return None


def safe_delete_file(path: str) -> bool:
    """
    Delete a file safely.

    Returns:
        True: When deletion succeeds.
        False: When the operation fails.
    """
    try:
        return delete_file(path)
    except FileOperationError as exc:
        logger.warning(
            "safe_delete_file failed: %s",
            exc,
        )
        return False


def safe_move_file(
    path: str,
    destination_dir: str,
    *,
    overwrite: bool = False,
) -> Path | None:
    """
    Move a file safely.

    Returns:
        Path: Destination path on success.
        None: When the operation fails.
    """
    try:
        return move_file(
            path=path,
            destination_dir=destination_dir,
            overwrite=overwrite,
        )
    except FileOperationError as exc:
        logger.warning(
            "safe_move_file failed: %s",
            exc,
        )
        return None


def safe_copy_file(
    path: str,
    destination_dir: str,
    *,
    overwrite: bool = False,
) -> Path | None:
    """
    Copy a file safely.

    Returns:
        Path: Copied file path on success.
        None: When the operation fails.
    """
    try:
        return copy_file(
            path=path,
            destination_dir=destination_dir,
            overwrite=overwrite,
        )
    except FileOperationError as exc:
        logger.warning(
            "safe_copy_file failed: %s",
            exc,
        )
        return None


def safe_read_text_file(
    path: str,
    max_chars: int = DEFAULT_MAX_READ_CHARS,
) -> str | None:
    """
    Read a text file safely.

    Returns:
        str: File content on success.
        None: When the operation fails.
    """
    try:
        return read_text_file(
            path=path,
            max_chars=max_chars,
        )
    except FileOperationError as exc:
        logger.warning(
            "safe_read_text_file failed: %s",
            exc,
        )
        return None


# ============================================================================
# Diagnostics
# ============================================================================


def diagnostics() -> dict:
    """
    Return diagnostic information for the file automation module.
    """
    roots = _search_roots()

    return {
        "module": "automation.files",
        "home_directory": str(_home()),
        "default_search_roots": [str(root) for root in roots],
        "default_max_search_results": DEFAULT_MAX_SEARCH_RESULTS,
        "default_max_search_depth": DEFAULT_MAX_SEARCH_DEPTH,
        "platform": os.name,
    }

"""
File writing utilities for AssistantX.

Provides safe and reliable helpers for writing text files while
handling parent-directory creation, encoding, atomic replacement,
and filesystem errors consistently.
"""



import tempfile

try:
    from core.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


PathLike = str | Path


def safe_write_text_file(
    file_path: PathLike,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    create_parents: bool = True,
    atomic: bool = True,
) -> Path:
    """
    Safely write text content to a file.

    Args:
        file_path:
            Target file path as a string or pathlib.Path.

        content:
            Text content to write.

        encoding:
            Text encoding used when writing the file.
            Defaults to ``utf-8``.

        newline:
            Newline handling passed to ``open()``.
            ``None`` preserves Python's default newline behavior.

        create_parents:
            Create missing parent directories automatically.
            Defaults to ``True``.

        atomic:
            When ``True``, write to a temporary file first and then
            replace the destination. This reduces the risk of leaving
            a partially-written file if the application crashes during
            the write operation.

    Returns:
        Path:
            The resolved target path.

    Raises:
        TypeError:
            If ``content`` is not a string.

        ValueError:
            If the file path is empty.

        FileWriteError:
            If the file cannot be written.

    Example:
        >>> path = safe_write_text_file(
        ...     "data/example.txt",
        ...     "Hello AssistantX!"
        ... )
        >>> print(path)
    """

    if not isinstance(content, str):
        raise TypeError(
            "content must be a string."
        )

    if not isinstance(file_path, (str, Path)):
        raise TypeError(
            "file_path must be a string or pathlib.Path."
        )

    path = Path(file_path).expanduser()

    if not str(path).strip():
        raise ValueError(
            "file_path cannot be empty."
        )

    path = path.resolve()

    try:
        if create_parents:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        if atomic:
            _atomic_write(
                path=path,
                content=content,
                encoding=encoding,
                newline=newline,
            )
        else:
            _direct_write(
                path=path,
                content=content,
                encoding=encoding,
                newline=newline,
            )

        logger.debug(
            "Text file written successfully: %s",
            path,
        )

        return path

    except (OSError, UnicodeError) as exc:
        logger.error(
            "Failed to write text file '%s': %s",
            path,
            exc,
        )

        raise FileWriteError(
            f"Unable to write text file: {path}"
        ) from exc


def _direct_write(
    *,
    path: Path,
    content: str,
    encoding: str,
    newline: str | None,
) -> None:
    """Write text directly to the destination file."""

    with path.open(
        mode="w",
        encoding=encoding,
        newline=newline,
    ) as file:
        file.write(content)


def _atomic_write(
    *,
    path: Path,
    content: str,
    encoding: str,
    newline: str | None,
) -> None:

#pore add korse \\\\\\\\\\\\\

    """
    Write content through a temporary file and atomically replace
    the destination.

    The temporary file is created in the same directory as the target
    so that ``os.replace()`` remains atomic on the same filesystem.
    """

    temp_path: Path | None = None

    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )

        temp_path = Path(temp_name)

        with os.fdopen(
            fd,
            mode="w",
            encoding=encoding,
            newline=newline,
        ) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.replace(
            temp_path,
            path,
        )

        temp_path = None

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(
                    missing_ok=True,
                )
            except OSError:
                logger.warning(
                    "Unable to remove temporary file: %s",
                    temp_path,
                )


def safe_append_text_file(
    file_path: PathLike,
    content: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    create_parents: bool = True,
) -> Path:
    """
    Safely append text to an existing file.

    The file is created automatically when it does not exist.
    """

    if not isinstance(content, str):
        raise TypeError(
            "content must be a string."
        )

    path = Path(file_path).expanduser().resolve()

    if create_parents:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    try:
        with path.open(
            mode="a",
            encoding=encoding,
            newline=newline,
        ) as file:
            file.write(content)

        logger.debug(
            "Text appended successfully: %s",
            path,
        )

        return path

    except (OSError, UnicodeError) as exc:
        logger.error(
            "Failed to append text file '%s': %s",
            path,
            exc,
        )

        raise FileWriteError(
            f"Unable to append text file: {path}"
        ) from exc

    
# ============================================================================
# Public API
# ============================================================================

__all__ = [  # noqa: RUF022
    # Exceptions
    "FileAlreadyExistsError",
    "FileNotFoundError",
    "FileOperationError",
    "FileReadError",
    "FileSafetyError",
    "FileValidationError",
    "FileWriteError",
    
    # Models
    "FileInfo",
    "FileSearchResult",
    
    # Constants
    "DEFAULT_MAX_READ_CHARS",
    "DEFAULT_MAX_SEARCH_DEPTH",
    "DEFAULT_MAX_SEARCH_RESULTS",
    "DEFAULT_SEARCH_ROOT_NAMES",
    
    # Path helpers
    "normalize_path",
    
    # Core operations
    "copy_file",
    "create_file",
    "delete_file",
    "move_file",
    "rename_file",
    
    # Search
    "search_file_paths",
    "search_files",
    
    # Text
    "append_text_file",
    "read_text_file",
    "write_text_file",
    
    # Checks
    "file_exists",
    "is_directory",
    "is_file",
    
    # Metadata
    "get_file_info",
    "get_file_info_model",
    "get_file_size",

    # Diagnostics
    "diagnostics",
    
    # Safe wrappers
    "safe_append_text_file",
    "safe_copy_file",
    "safe_create_file",
    "safe_delete_file",
    "safe_move_file",
    "safe_read_text_file",
    "safe_write_text_file",
]
