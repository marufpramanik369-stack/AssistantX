"""
AssistantX - Project Cleanup Utility
=====================================

Safely removes generated files, caches, temporary data,
build artifacts and Python bytecode.

Usage:
    python scripts/clean.py
    python scripts/clean.py --all
    python scripts/clean.py --cache
    python scripts/clean.py --build
    python scripts/clean.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Final

APP_NAME: Final[str] = "AssistantX"

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

DIRECTORIES_TO_CLEAN: Final[tuple[Path, ...]] = (
    PROJECT_ROOT / "build",
    PROJECT_ROOT / "dist",
    PROJECT_ROOT / "__pycache__",
    PROJECT_ROOT / ".pytest_cache",
    PROJECT_ROOT / ".mypy_cache",
    PROJECT_ROOT / ".ruff_cache",
)

CACHE_DIRECTORIES: Final[tuple[Path, ...]] = (
    PROJECT_ROOT / "cache" / "ai",
    PROJECT_ROOT / "cache" / "images",
    PROJECT_ROOT / "cache" / "search",
    PROJECT_ROOT / "cache" / "temp",
)

BYTECODE_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
)

IGNORED_DIRECTORIES: Final[set[str]] = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
}


class CleanError(RuntimeError):
    """Base exception for cleanup failures."""


class Cleaner:
    """Professional project cleanup manager."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.removed_files = 0
        self.removed_directories = 0
        self.failed = 0

    def _safe_path(self, path: Path) -> bool:
        """Prevent accidental deletion outside project root."""
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def remove_path(self, path: Path, *, dry_run: bool = False) -> None:
        """Remove a file or directory safely."""
        if not path.exists():
            return

        if not self._safe_path(path):
            raise CleanError(f"Unsafe cleanup path: {path}")

        try:
            if dry_run:
                print(f"[DRY-RUN] Would remove: {path}")
                return

            if path.is_dir():
                shutil.rmtree(path)
                self.removed_directories += 1
            else:
                path.unlink()
                self.removed_files += 1

            print(f"[REMOVED] {path}")

        except OSError as exc:
            self.failed += 1
            print(f"[ERROR] Could not remove {path}: {exc}")

    def clean_build_artifacts(self, *, dry_run: bool = False) -> None:
        """Remove build and distribution artifacts."""
        print("\n== Cleaning build artifacts ==")

        for path in DIRECTORIES_TO_CLEAN:
            self.remove_path(path, dry_run=dry_run)

    def clean_cache(self, *, dry_run: bool = False) -> None:
        """Remove temporary application caches."""
        print("\n== Cleaning cache ==")

        for path in CACHE_DIRECTORIES:
            if path.exists():
                self.remove_path(path, dry_run=dry_run)

                if not dry_run:
                    path.mkdir(parents=True, exist_ok=True)

    def clean_bytecode(self, *, dry_run: bool = False) -> None:
        """Remove Python bytecode recursively."""
        print("\n== Cleaning Python bytecode ==")

        for path in self.root.rglob("*"):
            if any(part in IGNORED_DIRECTORIES for part in path.parts):
                continue

            if path.is_file() and path.suffix in BYTECODE_SUFFIXES or path.is_dir() and path.name == "__pycache__":
                self.remove_path(path, dry_run=dry_run)

    def clean_all(self, *, dry_run: bool = False) -> None:
        """Run complete cleanup."""
        self.clean_build_artifacts(dry_run=dry_run)
        self.clean_cache(dry_run=dry_run)
        self.clean_bytecode(dry_run=dry_run)

    def report(self) -> None:
        """Print cleanup summary."""
        print("\n" + "=" * 60)
        print(f"{APP_NAME} Cleanup Summary")
        print("=" * 60)
        print(f"Removed files       : {self.removed_files}")
        print(f"Removed directories : {self.removed_directories}")
        print(f"Failed operations   : {self.failed}")
        print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} project cleanup utility."
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--all",
        action="store_true",
        help="Clean build artifacts, cache and bytecode.",
    )

    group.add_argument(
        "--cache",
        action="store_true",
        help="Clean application cache.",
    )

    group.add_argument(
        "--build",
        action="store_true",
        help="Clean build and distribution artifacts.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    cleaner = Cleaner(PROJECT_ROOT)

    try:
        if args.cache:
            cleaner.clean_cache(dry_run=args.dry_run)

        elif args.build:
            cleaner.clean_build_artifacts(dry_run=args.dry_run)

        else:
            cleaner.clean_all(dry_run=args.dry_run)

        cleaner.report()

        return 1 if cleaner.failed else 0

    except KeyboardInterrupt:
        print("\n[ABORTED] Cleanup cancelled by user.")
        return 130

    except (CleanError, OSError) as exc:
        print(f"[FATAL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
    