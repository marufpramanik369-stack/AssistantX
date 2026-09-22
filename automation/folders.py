"""
folders.py
==========

Professional directory/folder automation module for AssistantX.

Features
--------
- Create folders
- Delete empty folders safely
- Recursive folder deletion with explicit opt-in
- Open folders in the native file manager
- List folder contents
- Resolve well-known folders
- Rename folders
- Move folders
- Check folder existence
- Calculate folder size
- Get folder metadata
- Search inside folders
- Safe operation wrappers
- Diagnostics

Safety
------
Recursive deletion is NEVER performed implicitly.

Callers should explicitly pass:
    recursive=True

For voice/AI commands, destructive recursive operations should also
be confirmed by the command/decision layer before execution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.constants import (
    IS_LINUX,
    IS_MAC,
    IS_WINDOWS,
)
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_DESKTOP = Path.home() / "Desktop"

WELL_KNOWN_FOLDER_NAMES = (
    "home",
    "desktop",
    "documents",
    "downloads",
    "pictures",
    "music",
    "videos",
)

MAX_SEARCH_RESULTS = 500


# ============================================================================
# EXCEPTIONS
# ============================================================================


class FolderOperationError(RuntimeError):
    """Base exception for folder operation failures."""


class FolderValidationError(FolderOperationError):
    """Raised when a folder path or parameter is invalid."""


class FolderSafetyError(FolderOperationError):
    """Raised when an operation would be unsafe."""


class FolderNotFoundError(FolderOperationError):
    """Raised when a requested folder does not exist."""


# ============================================================================
# DATA MODELS
# ============================================================================


@dataclass(frozen=True)
class FolderEntry:
    """
    Metadata for a folder entry.
    """

    name: str
    path: Path
    is_directory: bool
    is_file: bool
    size_bytes: int
    modified_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the entry to a JSON/dashboard-friendly dictionary."""
        return {
            "name": self.name,
            "path": str(self.path),
            "is_directory": self.is_directory,
            "is_file": self.is_file,
            "size_bytes": self.size_bytes,
            "modified_at": (
                self.modified_at.isoformat()
                if self.modified_at
                else None
            ),
        }


@dataclass(frozen=True)
class FolderInfo:
    """
    Metadata about a folder.
    """

    path: Path
    name: str
    exists: bool
    item_count: int
    file_count: int
    folder_count: int
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to a serializable dictionary."""
        return {
            "path": str(self.path),
            "name": self.name,
            "exists": self.exists,
            "item_count": self.item_count,
            "file_count": self.file_count,
            "folder_count": self.folder_count,
            "size_bytes": self.size_bytes,
        }


# ============================================================================
# PATH HELPERS
# ============================================================================


def normalize_path(
    path: str | Path,
) -> Path:
    """
    Expand user references and return a normalized absolute path.

    Examples:
        ~/Desktop
        ./Project
        C:\\Users\\Name\\Documents
    """
    if path is None:
        raise FolderValidationError(
            "Folder path cannot be None."
        )

    path = str(path).strip()

    if not path:
        raise FolderValidationError(
            "Folder path cannot be empty."
        )

    return Path(path).expanduser().resolve()


def _validate_folder_exists(
    path: str | Path,
) -> Path:
    """Validate that a path exists and is a directory."""
    folder_path = normalize_path(path)

    if not folder_path.exists():
        raise FolderNotFoundError(
            f"Folder does not exist: '{folder_path}'."
        )

    if not folder_path.is_dir():
        raise FolderValidationError(
            f"Path is not a folder: '{folder_path}'."
        )

    return folder_path


def folder_exists(
    path: str | Path,
) -> bool:
    """Return True if the given path is an existing directory."""
    try:
        return normalize_path(path).is_dir()
    except FolderOperationError:
        return False


# ============================================================================
# SAFETY HELPERS
# ============================================================================


def _is_dangerous_root(path: Path) -> bool:
    """
    Prevent destructive operations against filesystem roots.
    """
    try:
        return path == Path(path.anchor)

    except Exception:
        return False


def _is_home_directory(path: Path) -> bool:
    """Return True when path is the current user's home directory."""
    try:
        return path == Path.home().resolve()
    except Exception:
        return False


def _validate_recursive_delete_target(
    folder_path: Path,
) -> None:
    """
    Apply additional safety checks before recursive deletion.
    """
    if _is_dangerous_root(folder_path):
        raise FolderSafetyError(
            f"Refusing to recursively delete filesystem root: "
            f"'{folder_path}'."
        )

    if _is_home_directory(folder_path):
        raise FolderSafetyError(
            "Refusing to recursively delete the user's home directory."
        )

    # Protect important well-known user directories.
    protected = {
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home() / "Pictures",
        Path.home() / "Music",
        Path.home() / "Videos",
    }

    resolved_protected = {
        item.resolve()
        for item in protected
    }

    if folder_path in resolved_protected:
        raise FolderSafetyError(
            f"Refusing to recursively delete protected folder: "
            f"'{folder_path}'."
        )


# ===========================================================================
# MOVE / RENAME SAFETY HELPERS
# ===========================================================================


def safe_move_folder(
    path: str,
    destination_dir: str,
) -> Path | None:
    """
    Safely move a folder to another directory.

    Returns:
        Path: Destination path on success.
        None: If the operation fails.
    """
    try:
        return move_folder(
            path=path,
            destination_dir=destination_dir,
        )
    except FolderOperationError as exc:
        logger.warning(
            "safe_move_folder failed: %s",
            exc,
        )
        return None


# ============================================================================
# CREATE
# ============================================================================


def create_folder(
    name: str,
    parent_dir: str | Path | None = None,
    exist_ok: bool = False,
) -> Path:
    """
    Create a new folder.

    Args:
        name:
            Folder name.

        parent_dir:
            Parent directory. Defaults to Desktop.

        exist_ok:
            If True, return an existing directory instead of
            raising an error.
    """
    if not isinstance(name, str):
        raise FolderValidationError(
            "Folder name must be a string."
        )

    name = name.strip()

    if not name:
        raise FolderValidationError(
            "Folder name cannot be empty."
        )

    if name in {".", ".."}:
        raise FolderValidationError(
            "Invalid folder name."
        )

    base = (
        normalize_path(parent_dir)
        if parent_dir
        else DEFAULT_DESKTOP.resolve()
    )

    if not base.exists():
        raise FolderNotFoundError(
            f"Parent directory does not exist: '{base}'."
        )

    if not base.is_dir():
        raise FolderValidationError(
            f"Parent path is not a directory: '{base}'."
        )

    target = base / name

    if target.exists():
        if exist_ok and target.is_dir():
            return target

        raise FolderOperationError(
            f"A folder named '{name}' already exists at '{base}'."
        )

    try:
        target.mkdir(
            parents=True,
            exist_ok=False,
        )

    except OSError as exc:
        raise FolderOperationError(
            f"Could not create folder '{target}': {exc}"
        ) from exc

    logger.info(
        "Created folder: %s",
        target,
    )

    return target


# ============================================================================
# DELETE
# ============================================================================


def delete_folder(
    path: str | Path,
    recursive: bool = False,
) -> bool:
    """
    Delete a folder.

    By default only empty folders can be deleted.

    Recursive deletion must be explicitly requested:

        delete_folder(path, recursive=True)

    Even with recursive=True, protected directories such as the
    user's home/Desktop/Documents/Downloads/etc. are refused.
    """
    folder_path = _validate_folder_exists(path)

    if recursive:
        _validate_recursive_delete_target(
            folder_path
        )

    try:
        if recursive:
            shutil.rmtree(folder_path)
        else:
            folder_path.rmdir()

    except OSError as exc:
        if not recursive:
            raise FolderOperationError(
                f"Could not delete '{folder_path}'. "
                f"The folder may not be empty or may be in use. "
                f"Use recursive=True only after explicit confirmation."
            ) from exc

        raise FolderOperationError(
            f"Could not recursively delete "
            f"'{folder_path}': {exc}"
        ) from exc

    logger.info(
        "Deleted folder: %s (recursive=%s)",
        folder_path,
        recursive,
    )

    return True


# ============================================================================
# OPEN
# ============================================================================


def open_folder(
    path: str | Path,
) -> bool:
    """
    Open a folder in the operating system's default file manager.

    Windows:
        Explorer

    macOS:
        Finder

    Linux:
        xdg-open
    """
    folder_path = _validate_folder_exists(path)

    try:
        if IS_WINDOWS:
            subprocess.Popen(
                [
                    "explorer",
                    str(folder_path),
                ]
            )

        elif IS_MAC:
            subprocess.Popen(
                [
                    "open",
                    str(folder_path),
                ]
            )

        elif IS_LINUX:
            subprocess.Popen(
                [
                    "xdg-open",
                    str(folder_path),
                ]
            )

        else:
            raise FolderOperationError(
                "Unsupported operating system."
            )

    except OSError as exc:
        raise FolderOperationError(
            f"Could not open folder '{folder_path}': {exc}"
        ) from exc

    logger.info(
        "Opened folder: %s",
        folder_path,
    )

    return True


# ============================================================================
# LIST CONTENTS
# ============================================================================


def list_folder_contents(
    path: str | Path,
    include_hidden: bool = False,
    directories_first: bool = False,
) -> list[FolderEntry]:
    """
    List immediate folder contents.

    Args:
        path:
            Folder to inspect.

        include_hidden:
            Include entries beginning with '.'.

        directories_first:
            Sort directories before files.
    """
    folder_path = _validate_folder_exists(path)

    entries: list[FolderEntry] = []

    try:
        items = list(folder_path.iterdir())

    except OSError as exc:
        raise FolderOperationError(
            f"Could not list contents of "
            f"'{folder_path}': {exc}"
        ) from exc

    if not include_hidden:
        items = [
            item
            for item in items
            if not item.name.startswith(".")
        ]

    if directories_first:
        items.sort(
            key=lambda item: (
                not item.is_dir(),
                item.name.lower(),
            )
        )
    else:
        items.sort(
            key=lambda item: item.name.lower()
        )

    for item in items:
        try:
            stat = item.stat()

            entries.append(
                FolderEntry(
                    name=item.name,
                    path=item,
                    is_directory=item.is_dir(),
                    is_file=item.is_file(),
                    size_bytes=(
                        0
                        if item.is_dir()
                        else stat.st_size
                    ),
                    modified_at=datetime.fromtimestamp(
                        stat.st_mtime
                    ),
                )
            )

        except OSError as exc:
            logger.debug(
                "Could not inspect '%s': %s",
                item,
                exc,
            )

    return entries


def list_folder_contents_dict(
    path: str | Path,
    include_hidden: bool = False,
    directories_first: bool = False,
) -> list[dict[str, Any]]:
    """
    Dashboard/JSON-friendly version of list_folder_contents().
    """
    return [
        entry.to_dict()
        for entry in list_folder_contents(
            path,
            include_hidden=include_hidden,
            directories_first=directories_first,
        )
    ]


# ============================================================================
# FOLDER INFORMATION
# ============================================================================


def get_folder_size(
    path: str | Path,
) -> int:
    """
    Calculate total folder size recursively in bytes.

    Unreadable files are skipped and logged.
    """
    folder_path = _validate_folder_exists(path)

    total_size = 0

    for root, _, files in os.walk(folder_path):
        for filename in files:
            file_path = Path(root) / filename

            try:
                total_size += file_path.stat().st_size

            except OSError as exc:
                logger.debug(
                    "Could not read size of '%s': %s",
                    file_path,
                    exc,
                )

    return total_size


def get_folder_info(
    path: str | Path,
) -> FolderInfo:
    """
    Return summary information about a folder.
    """
    folder_path = _validate_folder_exists(path)

    file_count = 0
    folder_count = 0

    try:
        for item in folder_path.iterdir():
            if item.is_dir():
                folder_count += 1
            elif item.is_file():
                file_count += 1

    except OSError as exc:
        raise FolderOperationError(
            f"Could not inspect folder '{folder_path}': {exc}"
        ) from exc

    return FolderInfo(
        path=folder_path,
        name=folder_path.name,
        exists=True,
        item_count=file_count + folder_count,
        file_count=file_count,
        folder_count=folder_count,
        size_bytes=get_folder_size(folder_path),
    )


# ============================================================================
# RENAME
# ============================================================================


def rename_folder(
    path: str | Path,
    new_name: str,
) -> Path:
    """
    Rename an existing folder.
    """
    folder_path = _validate_folder_exists(path)

    if not isinstance(new_name, str):
        raise FolderValidationError(
            "New folder name must be a string."
        )

    new_name = new_name.strip()

    if not new_name:
        raise FolderValidationError(
            "New folder name cannot be empty."
        )

    if new_name in {".", ".."}:
        raise FolderValidationError(
            "Invalid folder name."
        )

    target = folder_path.parent / new_name

    if target.exists():
        raise FolderOperationError(
            f"A file or folder already exists at '{target}'."
        )

    try:
        folder_path.rename(target)

    except OSError as exc:
        raise FolderOperationError(
            f"Could not rename '{folder_path}' "
            f"to '{new_name}': {exc}"
        ) from exc

    logger.info(
        "Renamed folder: %s -> %s",
        folder_path,
        target,
    )

    return target


# ============================================================================
# MOVE
# ============================================================================


def move_folder(
    source: str | Path,
    destination: str | Path,
) -> Path:
    """
    Move a folder to another directory.

    Args:
        source:
            Existing folder.

        destination:
            Destination directory or final destination path.
    """
    source_path = _validate_folder_exists(source)
    destination_path = normalize_path(destination)

    if source_path == destination_path:
        raise FolderOperationError(
            "Source and destination are identical."
        )

    if source_path in destination_path.parents:
        raise FolderSafetyError(
            "Cannot move a folder into one of its own descendants."
        )

    if not destination_path.exists():
        raise FolderNotFoundError(
            f"Destination does not exist: '{destination_path}'."
        )

    if not destination_path.is_dir():
        raise FolderValidationError(
            f"Destination is not a directory: "
            f"'{destination_path}'."
        )

    final_path = destination_path / source_path.name

    if final_path.exists():
        raise FolderOperationError(
            f"Destination already contains "
            f"'{source_path.name}'."
        )

    try:
        result = shutil.move(
            str(source_path),
            str(destination_path),
        )

    except OSError as exc:
        raise FolderOperationError(
            f"Could not move '{source_path}' "
            f"to '{destination_path}': {exc}"
        ) from exc

    final_path = Path(result)

    logger.info(
        "Moved folder: %s -> %s",
        source_path,
        final_path,
    )

    return final_path


# ============================================================================
# SEARCH
# ============================================================================


def search_folders(
    root: str | Path,
    query: str,
    max_results: int = MAX_SEARCH_RESULTS,
    include_files: bool = False,
) -> list[Path]:
    """
    Search recursively for folders matching a name.

    Args:
        root:
            Root folder to search.

        query:
            Case-insensitive substring.

        max_results:
            Maximum number of results.

        include_files:
            If True, matching files are included too.
    """
    root_path = _validate_folder_exists(root)

    query = query.strip().lower()

    if not query:
        raise FolderValidationError(
            "Search query cannot be empty."
        )

    if max_results <= 0:
        return []

    results: list[Path] = []

    try:
        for current_root, dirs, files in os.walk(
            root_path
        ):
            current_path = Path(current_root)

            for dirname in dirs:
                if query in dirname.lower():
                    results.append(
                        current_path / dirname
                    )

                    if len(results) >= max_results:
                        return results

            if include_files:
                for filename in files:
                    if query in filename.lower():
                        results.append(
                            current_path / filename
                        )

                        if len(results) >= max_results:
                            return results

    except OSError as exc:
        raise FolderOperationError(
            f"Folder search failed in "
            f"'{root_path}': {exc}"
        ) from exc

    return results


# ============================================================================
# WELL-KNOWN FOLDERS
# ============================================================================


def get_well_known_folder(
    name: str,
) -> Path:
    """
    Resolve common spoken folder references.

    Supported:
        home
        desktop
        documents
        downloads
        pictures
        music
        videos
    """
    if not isinstance(name, str):
        raise FolderValidationError(
            "Folder name must be a string."
        )

    key = (
        name
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )

    home = Path.home()

    mapping = {
        "home": home,
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
    }

    if key not in mapping:
        raise FolderOperationError(
            f"'{name}' is not a recognized "
            f"well-known folder."
        )

    return mapping[key].resolve()


# ============================================================================
# SAFE WRAPPERS
# ============================================================================


def safe_create_folder(
    name: str,
    parent_dir: str | Path | None = None,
) -> Path | None:
    """Safe wrapper for create_folder()."""
    try:
        return create_folder(
            name,
            parent_dir,
        )

    except FolderOperationError as exc:
        logger.warning(
            "Create folder failed: %s",
            exc,
        )

        return None


def safe_open_folder(
    path: str | Path,
) -> bool:
    """Safe wrapper for open_folder()."""
    try:
        return open_folder(path)

    except FolderOperationError as exc:
        logger.warning(
            "Open folder failed: %s",
            exc,
        )

        return False


def safe_delete_folder(
    path: str | Path,
    recursive: bool = False,
) -> bool:
    """
    Safe delete wrapper.

    Any safety or operation error returns False instead
    of crashing the AssistantX process.
    """
    try:
        return delete_folder(
            path,
            recursive=recursive,
        )

    except FolderOperationError as exc:
        logger.warning(
            "Delete folder failed: %s",
            exc,
        )

        return False


# ============================================================================
# DIAGNOSTICS
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return folder automation subsystem diagnostics.
    """
    return {
        "platform": (
            "windows"
            if IS_WINDOWS
            else "macos"
            if IS_MAC
            else "linux"
            if IS_LINUX
            else "unknown"
        ),
        "home_directory": str(
            Path.home()
        ),
        "desktop_directory": str(
            DEFAULT_DESKTOP
        ),
        "desktop_exists": DEFAULT_DESKTOP.exists(),
        "well_known_folders": list(
            WELL_KNOWN_FOLDER_NAMES
        ),
    }


# ============================================================================
# PUBLIC API
# ============================================================================


__all__ = [
    # Exceptions
    "FolderOperationError",
    "FolderValidationError",
    "FolderSafetyError",
    "FolderNotFoundError",

    # Data models
    "FolderEntry",
    "FolderInfo",

    # Path
    "normalize_path",
    "folder_exists",

    # Create / delete
    "create_folder",
    "delete_folder",

    # Move / rename 
    "safe_move_folder",
    "safe_rename_folder",

    # Open
    "open_folder",

    # Contents
    "list_folder_contents",
    "list_folder_contents_dict",

    # Information
    "get_folder_size",
    "get_folder_info",

    # Rename / move
    "rename_folder",
    "move_folder",

    # Search
    "search_folders",

    # Well-known folders
    "get_well_known_folder",

    # Safe wrappers
    "safe_create_folder",
    "safe_open_folder",
    "safe_delete_folder",

    # Diagnostics
    "diagnostics",
]
