"""
files.py
========
File-level automation: create, delete, rename, move, copy, and search
for files on disk. All destructive operations here are called ONLY
after brain/decision_engine.py has already obtained user confirmation
(for delete/overwrite) — this module itself does not re-prompt; it
trusts the caller to have gated dangerous actions appropriately.

Search defaults to the user's home directory and common subfolders
(Desktop, Documents, Downloads) rather than a full-disk scan, both for
speed and because that's where a spoken "find my file" request usually
means to look.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SEARCH_ROOTS: tuple[str, ...] = ("Desktop", "Documents", "Downloads", "Pictures")
_MAX_SEARCH_RESULTS = 20
_MAX_SEARCH_DEPTH = 6


class FileOperationError(RuntimeError):
    """Raised when a file operation fails or would be unsafe to perform."""


@dataclass
class FileSearchResult:
    path: Path
    size_bytes: int
    is_directory: bool


def _home() -> Path:
    return Path.home()


def _search_roots() -> list[Path]:
    """Resolve the set of directories to search by default, skipping any
    that don't exist on this particular OS/user setup."""
    home = _home()
    roots = [home / sub for sub in _DEFAULT_SEARCH_ROOTS]
    return [r for r in roots if r.exists() and r.is_dir()]


def create_file(filename: str, directory: Optional[str] = None, content: str = "") -> Path:
    """
    Create a new (empty or pre-filled) file.

    Args:
        filename: Name of the file to create, e.g. 'notes.txt'.
        directory: Target directory. Defaults to the user's Desktop.
        content: Optional initial text content.

    Returns:
        The Path to the newly created file.

    Raises:
        FileOperationError: if the file already exists or cannot be created.
    """
    target_dir = Path(directory) if directory else (_home() / "Desktop")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if target_path.exists():
        raise FileOperationError(f"A file named '{filename}' already exists at {target_dir}.")

    try:
        target_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise FileOperationError(f"Could not create '{filename}': {exc}") from exc

    logger.info("Created file: %s", target_path)
    return target_path


def delete_file(path: str) -> bool:
    """
    Delete a single file (not a directory — use delete_directory for that).

    Callers MUST have already obtained user confirmation before calling
    this, since AssistantX's confirmation gating happens upstream in
    brain/decision_engine.py, not here.

    Raises:
        FileOperationError: if the path doesn't exist or isn't a file.
    """
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileOperationError(f"'{path}' does not exist.")
    if not file_path.is_file():
        raise FileOperationError(f"'{path}' is not a file (use delete_directory for folders).")

    try:
        file_path.unlink()
    except OSError as exc:
        raise FileOperationError(f"Could not delete '{path}': {exc}") from exc

    logger.info("Deleted file: %s", file_path)
    return True


def rename_file(path: str, new_name: str) -> Path:
    """Rename a file in-place (keeping it in the same directory)."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileOperationError(f"'{path}' does not exist.")

    new_path = file_path.with_name(new_name)
    if new_path.exists():
        raise FileOperationError(f"A file named '{new_name}' already exists in that location.")

    try:
        file_path.rename(new_path)
    except OSError as exc:
        raise FileOperationError(f"Could not rename '{path}' to '{new_name}': {exc}") from exc

    logger.info("Renamed '%s' -> '%s'", file_path, new_path)
    return new_path


def move_file(path: str, destination_dir: str) -> Path:
    """Move a file to a different directory (creating it if necessary)."""
    file_path = Path(path).expanduser()
    dest_dir = Path(destination_dir).expanduser()

    if not file_path.exists():
        raise FileOperationError(f"'{path}' does not exist.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file_path.name

    try:
        shutil.move(str(file_path), str(dest_path))
    except OSError as exc:
        raise FileOperationError(f"Could not move '{path}' to '{destination_dir}': {exc}") from exc

    logger.info("Moved '%s' -> '%s'", file_path, dest_path)
    return dest_path


def copy_file(path: str, destination_dir: str) -> Path:
    """Copy a file to a different directory, preserving the original."""
    file_path = Path(path).expanduser()
    dest_dir = Path(destination_dir).expanduser()

    if not file_path.exists():
        raise FileOperationError(f"'{path}' does not exist.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file_path.name

    try:
        shutil.copy2(str(file_path), str(dest_path))
    except OSError as exc:
        raise FileOperationError(f"Could not copy '{path}' to '{destination_dir}': {exc}") from exc

    logger.info("Copied '%s' -> '%s'", file_path, dest_path)
    return dest_path


def search_files(
    query: str,
    roots: Optional[list[Path]] = None,
    max_results: int = _MAX_SEARCH_RESULTS,
    max_depth: int = _MAX_SEARCH_DEPTH,
) -> list[FileSearchResult]:
    """
    Search for files/directories whose name contains `query`
    (case-insensitive), within the given root directories (defaulting
    to common user folders). Bounded by max_results and max_depth to
    keep voice-triggered searches fast and predictable.
    """
    search_dirs = roots if roots is not None else _search_roots()
    query_lower = query.strip().lower()
    results: list[FileSearchResult] = []

    for root in search_dirs:
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth >= max_depth:
                dirnames[:] = []  # prune further descent
                continue

            for name in filenames + dirnames:
                if query_lower in name.lower():
                    full_path = Path(dirpath) / name
                    try:
                        is_dir = full_path.is_dir()
                        size = 0 if is_dir else full_path.stat().st_size
                    except OSError:
                        continue
                    results.append(FileSearchResult(path=full_path, size_bytes=size, is_directory=is_dir))

                    if len(results) >= max_results:
                        logger.debug("search_files: hit max_results=%d for query '%s'.", max_results, query)
                        return results

    logger.info("search_files: found %d result(s) for '%s'.", len(results), query)
    return results


def read_text_file(path: str, max_chars: int = 5000) -> str:
    """Read a text file's content (truncated for safety/voice-readback purposes)."""
    file_path = Path(path).expanduser()
    if not file_path.exists() or not file_path.is_file():
        raise FileOperationError(f"'{path}' does not exist or is not a file.")

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise FileOperationError(f"Could not read '{path}': {exc}") from exc

    if len(content) > max_chars:
        return content[:max_chars] + "\n...[truncated]"
    return content


def file_exists(path: str) -> bool:
    return Path(path).expanduser().exists()


def get_file_info(path: str) -> dict:
    """Return basic metadata about a file/directory for display purposes."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileOperationError(f"'{path}' does not exist.")

    stat = file_path.stat()
    return {
        "path": str(file_path),
        "name": file_path.name,
        "is_directory": file_path.is_dir(),
        "size_bytes": stat.st_size,
        "modified_timestamp": stat.st_mtime,
    }
    