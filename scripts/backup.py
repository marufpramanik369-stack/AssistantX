"""
AssistantX - Backup Utility
===========================

Creates safe timestamped backups of AssistantX data.

Backs up:
    database/assistantx.db
    data/*.json

Usage:
    python scripts/backup.py
    python scripts/backup.py --output backups
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

APP_NAME: Final[str] = "AssistantX"

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

DATABASE_FILE: Final[Path] = (
    PROJECT_ROOT / "database" / "assistantx.db"
)

DATA_DIR: Final[Path] = PROJECT_ROOT / "data"

DEFAULT_BACKUP_DIR: Final[Path] = PROJECT_ROOT / "backups"


class BackupError(RuntimeError):
    """Raised when backup creation fails."""


class BackupManager:
    """Professional backup manager."""

    def __init__(
        self,
        project_root: Path,
        output_dir: Path | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.output_dir = (
            output_dir.resolve()
            if output_dir
            else DEFAULT_BACKUP_DIR
        )

    @staticmethod
    def timestamp() -> str:
        """Return filesystem-safe UTC timestamp."""
        return datetime.now(timezone.utc).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )

    def create_backup_directory(self) -> Path:
        """Create timestamped backup directory."""
        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_dir = (
            self.output_dir /
            f"{APP_NAME}_{self.timestamp()}"
        )

        backup_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        return backup_dir

    def backup_database(self, destination: Path) -> Path | None:
        """Create SQLite-consistent backup."""
        if not DATABASE_FILE.exists():
            print("[INFO] SQLite database not found.")
            return None

        target = destination / DATABASE_FILE.name

        try:
            source_connection = sqlite3.connect(
                DATABASE_FILE
            )

            target_connection = sqlite3.connect(
                target
            )

            with target_connection:
                source_connection.backup(
                    target_connection
                )

            target_connection.close()
            source_connection.close()

            print(f"[OK] Database backed up: {target}")

            return target

        except sqlite3.Error as exc:
            raise BackupError(
                f"Database backup failed: {exc}"
            ) from exc

    def backup_json_data(self, destination: Path) -> list[Path]:
        """Backup JSON data files."""
        copied: list[Path] = []

        if not DATA_DIR.exists():
            print("[INFO] data/ directory not found.")
            return copied

        for source in sorted(DATA_DIR.glob("*.json")):
            target = destination / source.name

            try:
                # Validate JSON before backup.
                with source.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    json.load(file)

                shutil.copy2(source, target)

                copied.append(target)

                print(f"[OK] Data backed up: {target}")

            except (OSError, json.JSONDecodeError) as exc:
                raise BackupError(
                    f"Could not backup {source}: {exc}"
                ) from exc

        return copied

    def write_manifest(
        self,
        destination: Path,
        files: list[Path],
    ) -> Path:
        """Write backup manifest."""
        manifest = {
            "application": APP_NAME,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "files": [
                {
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                }
                for path in files
                if path.exists()
            ],
        }

        manifest_path = destination / "manifest.json"

        with manifest_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                manifest,
                file,
                indent=4,
                ensure_ascii=False,
            )

        return manifest_path

    def create_backup(self) -> Path:
        """Create complete application backup."""
        destination = self.create_backup_directory()

        backed_up_files: list[Path] = []

        database = self.backup_database(destination)

        if database:
            backed_up_files.append(database)

        backed_up_files.extend(
            self.backup_json_data(destination)
        )

        manifest = self.write_manifest(
            destination,
            backed_up_files,
        )

        print(f"[OK] Manifest created: {manifest}")

        return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} backup utility."
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help="Backup output directory.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manager = BackupManager(
        PROJECT_ROOT,
        args.output,
    )

    try:
        destination = manager.create_backup()

        print("\n" + "=" * 60)
        print("BACKUP SUCCESSFUL")
        print("=" * 60)
        print(f"Location: {destination}")
        print("=" * 60)

        return 0

    except KeyboardInterrupt:
        print("\n[ABORTED] Backup cancelled.")
        return 130

    except BackupError as exc:
        print(f"\n[BACKUP ERROR] {exc}")
        return 1

    except OSError as exc:
        print(f"\n[FATAL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
