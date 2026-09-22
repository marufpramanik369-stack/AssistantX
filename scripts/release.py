"""
AssistantX - Release Manager
============================

Professional release preparation utility.

Pipeline:
    1. Validate version
    2. Run tests
    3. Clean project
    4. Build executable
    5. Create release directory
    6. Copy documentation
    7. Generate release manifest
    8. Generate SHA256 checksum

Usage:
    python scripts/release.py --version 1.0.0
    python scripts/release.py --version 1.0.0 --onefile
    python scripts/release.py --version 1.0.0 --skip-tests
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

APP_NAME: Final[str] = "AssistantX"

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

DIST_DIR: Final[Path] = PROJECT_ROOT / "dist"
RELEASE_DIR: Final[Path] = PROJECT_ROOT / "release"


class ReleaseError(RuntimeError):
    """Raised when release preparation fails."""


class ReleaseManager:
    """Professional AssistantX release manager."""

    def __init__(
        self,
        root: Path,
        version: str,
    ) -> None:
        self.root = root.resolve()
        self.version = version.strip()

        self.release_name = (
            f"{APP_NAME}-v{self.version}"
        )

        self.output_dir = (
            RELEASE_DIR / self.release_name
        )

    def validate_version(self) -> None:
        """Validate semantic-style version."""
        parts = self.version.split(".")

        if len(parts) != 3:
            raise ReleaseError(
                "Version must use MAJOR.MINOR.PATCH format."
            )

        if not all(part.isdigit() for part in parts):
            raise ReleaseError(
                "Version components must be numeric."
            )

    def run(self, command: list[str], description: str) -> None:
        """Run subprocess command."""
        print(f"\n[RELEASE] {description}")
        print("$", " ".join(command))

        try:
            subprocess.run(
                command,
                cwd=self.root,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ReleaseError(
                f"{description} failed."
            ) from exc

    def run_clean(self) -> None:
        """Run cleanup script."""
        self.run(
            [
                sys.executable,
                str(self.root / "scripts" / "clean.py"),
                "--build",
            ],
            "Cleaning previous build artifacts",
        )

    def run_tests(self) -> None:
        """Run tests."""
        self.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
            ],
            "Running test suite",
        )

    def run_build(self, *, onefile: bool) -> None:
        """Build application."""
        command = [
            sys.executable,
            str(self.root / "scripts" / "build.py"),
            "--skip-tests",
            "--clean",
        ]

        if onefile:
            command.append("--onefile")

        self.run(
            command,
            "Building release executable",
        )

    def find_artifacts(self) -> list[Path]:
        """Find generated distribution files."""
        if not DIST_DIR.exists():
            raise ReleaseError(
                "dist/ directory does not exist."
            )

        artifacts = [
            path
            for path in DIST_DIR.rglob("*")
            if path.is_file()
        ]

        if not artifacts:
            raise ReleaseError(
                "No build artifacts found."
            )

        return artifacts

    def prepare_output(self) -> None:
        """Create clean release directory."""
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def copy_artifacts(self, artifacts: list[Path]) -> list[Path]:
        """Copy build artifacts to release directory."""
        copied: list[Path] = []

        for artifact in artifacts:
            relative = artifact.relative_to(DIST_DIR)

            target = self.output_dir / relative

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                artifact,
                target,
            )

            copied.append(target)

        return copied

    def copy_documentation(self) -> None:
        """Copy important release documentation."""
        documentation = (
            "README.md",
            "LICENSE",
        )

        docs_destination = self.output_dir / "docs"

        docs_destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        for filename in documentation:
            source = self.root / filename

            if source.exists():
                shutil.copy2(
                    source,
                    docs_destination / filename,
                )

    @staticmethod
    def sha256(path: Path) -> str:
        """Calculate SHA256 checksum."""
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def create_checksums(
        self,
        files: list[Path],
    ) -> Path:
        """Create SHA256SUMS.txt."""
        checksum_file = (
            self.output_dir / "SHA256SUMS.txt"
        )

        with checksum_file.open(
            "w",
            encoding="utf-8",
        ) as file:
            for path in files:
                checksum = self.sha256(path)

                relative = path.relative_to(
                    self.output_dir
                )

                file.write(
                    f"{checksum}  {relative}\n"
                )

        return checksum_file

    def create_manifest(
        self,
        files: list[Path],
    ) -> Path:
        """Create release manifest."""
        manifest = {
            "application": APP_NAME,
            "version": self.version,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "platform": sys.platform,
            "python": sys.version,
            "files": [
                {
                    "path": str(
                        path.relative_to(
                            self.output_dir
                        )
                    ),
                    "size_bytes": path.stat().st_size,
                    "sha256": self.sha256(path),
                }
                for path in files
            ],
        }

        manifest_path = (
            self.output_dir /
            "release-manifest.json"
        )

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

    def create_release(
        self,
        *,
        run_tests: bool,
        onefile: bool,
    ) -> Path:
        """Execute complete release pipeline."""
        self.validate_version()

        if run_tests:
            self.run_tests()

        self.run_clean()

        self.run_build(
            onefile=onefile,
        )

        artifacts = self.find_artifacts()

        self.prepare_output()

        release_files = self.copy_artifacts(
            artifacts
        )

        self.copy_documentation()

        # Only checksum actual release files.
        checksum_file = self.create_checksums(
            release_files
        )

        self.create_manifest(
            release_files
        )

        print(
            f"[OK] Checksums: {checksum_file}"
        )

        return self.output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} release manager."
    )

    parser.add_argument(
        "--version",
        required=True,
        help="Release version, e.g. 1.0.0",
    )

    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single executable.",
    )

    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip test suite.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manager = ReleaseManager(
        PROJECT_ROOT,
        args.version,
    )

    try:
        output = manager.create_release(
            run_tests=not args.skip_tests,
            onefile=args.onefile,
        )

        print("\n" + "=" * 70)
        print(f"{APP_NAME} RELEASE SUCCESSFUL")
        print("=" * 70)
        print(f"Version : {args.version}")
        print(f"Output  : {output}")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("\n[ABORTED] Release cancelled.")
        return 130

    except ReleaseError as exc:
        print(f"\n[RELEASE ERROR] {exc}")
        return 1

    except (OSError, ValueError) as exc:
        print(f"\n[FATAL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
    