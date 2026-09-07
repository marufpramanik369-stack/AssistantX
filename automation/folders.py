"""
folders.py
==========
Directory-level automation: creating, deleting, and opening folders in
the OS file manager. Complements automation/files.py (which handles
individual files) — kept as a separate module since folder semantics
differ meaningfully (e.g. recursive delete requires extra care, and
"open" means something different for a folder — reveal it in Explorer/
Finder — versus for a file, which usually means launch its default
application).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS
from core.logger import get_logger

logger = get_logger(__name__)


class FolderOperationError(RuntimeError):
    """Raised when a folder operation fails or would be unsafe to perform."""


def create_folder(name: str, parent_dir: Optional[str] = None) -> Path:
    """
    Create a new folder (and any missing parent directories).

    Args:
        name: Folder name, e.g. 'Project Files'.
        parent_dir: Where to create it. Defaults to the user's Desktop.

    Returns:
        The Path to the newly created folder.
    """
    base = Path(parent_dir).expanduser() if parent_dir else (Path.home() / "Desktop")
    target = base / name

    if target.exists():
        raise FolderOperationError(f"A folder named '{name}' already exists at {base}.")

    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise FolderOperationError(f"Could not create folder '{name}': {exc}") from exc

    logger.info("Created folder: %s", target)
    return target


def delete_folder(path: str, recursive: bool = False) -> bool:
    """
    Delete a folder.

    Args:
        path: Path to the folder.
        recursive: If False (default), only succeeds on an EMPTY folder
            — a safety net against accidentally wiping out a folder full
            of files from a misheard voice command. Callers wanting
            recursive delete must explicitly opt in, and
            brain/decision_engine.py should always require confirmation
            for this sub-intent regardless.

    Raises:
        FolderOperationError: on missing path, non-directory path, a
            non-empty folder with recursive=False, or an OS-level failure.
    """
    folder_path = Path(path).expanduser()
    if not folder_path.exists():
        raise FolderOperationError(f"'{path}' does not exist.")
    if not folder_path.is_dir():
        raise FolderOperationError(f"'{path}' is not a folder.")

    try:
        if recursive:
            shutil.rmtree(folder_path)
        else:
            folder_path.rmdir()  # raises OSError if not empty
    except OSError as exc:
        raise FolderOperationError(
            f"Could not delete folder '{path}': {exc}. "
            f"(If it's not empty, deletion requires explicit recursive confirmation.)"
        ) from exc

    logger.info("Deleted folder: %s (recursive=%s)", folder_path, recursive)
    return True


def open_folder(path: str) -> bool:
    """
    Open a folder in the OS's default file manager (Explorer on Windows,
    Finder on macOS, the default file manager on Linux).
    """
    folder_path = Path(path).expanduser()
    if not folder_path.exists():
        raise FolderOperationError(f"'{path}' does not exist.")
    if not folder_path.is_dir():
        raise FolderOperationError(f"'{path}' is not a folder.")

    try:
        if IS_WINDOWS:
            subprocess.run(["explorer", str(folder_path)], check=False)
        elif IS_MAC:
            subprocess.run(["open", str(folder_path)], check=True)
        elif IS_LINUX:
            subprocess.run(["xdg-open", str(folder_path)], check=True)
        else:
            raise FolderOperationError("Unsupported platform for opening folders.")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FolderOperationError(f"Could not open folder '{path}': {exc}") from exc

    logger.info("Opened folder: %s", folder_path)
    return True


def list_folder_contents(path: str, include_hidden: bool = False) -> list[dict]:
    """
    List the immediate contents of a folder (non-recursive), returning
    simple metadata dicts suitable for display in the dashboard or
    reading aloud a summary ("You have 12 files and 3 folders here.").
    """
    folder_path = Path(path).expanduser()
    if not folder_path.exists() or not folder_path.is_dir():
        raise FolderOperationError(f"'{path}' does not exist or is not a folder.")

    entries = []
    try:
        for item in sorted(folder_path.iterdir()):
            if not include_hidden and item.name.startswith("."):
                continue
            try:
                stat = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "is_directory": item.is_dir(),
                        "size_bytes": 0 if item.is_dir() else stat.st_size,
                    }
                )
            except OSError:
                continue
    except OSError as exc:
        raise FolderOperationError(f"Could not list contents of '{path}': {exc}") from exc

    return entries


def get_well_known_folder(name: str) -> Path:
    """
    Resolve common spoken folder references ('desktop', 'downloads',
    'documents', 'home') to their actual OS paths.
    """
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
    key = name.strip().lower()
    if key not in mapping:
        raise FolderOperationError(f"'{name}' is not a recognized well-known folder.")
    return mapping[key]
    