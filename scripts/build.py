"""
AssistantX - Production Build System
=====================================

Builds AssistantX into a distributable executable.

Usage:
    python scripts/build.py
    python scripts/build.py --debug
    python scripts/build.py --onefile
    python scripts/build.py --clean
    python scripts/build.py --skip-tests
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

APP_NAME: Final[str] = "AssistantX"
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

MAIN_SCRIPT: Final[Path] = PROJECT_ROOT / "launcher.py"

BUILD_DIR: Final[Path] = PROJECT_ROOT / "build"
DIST_DIR: Final[Path] = PROJECT_ROOT / "dist"

DEFAULT_SPEC_NAME: Final[str] = "AssistantX"


class BuildError(RuntimeError):
    """Raised when the build process fails."""


class Builder:
    """Professional AssistantX build manager."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run_command(
        self,
        command: list[str],
        *,
        description: str,
    ) -> None:
        print(f"\n[BUILD] {description}")
        print("$", " ".join(command))

        try:
            subprocess.run(
                command,
                cwd=self.root,
                check=True,
            )
        except FileNotFoundError as exc:
            raise BuildError(
                f"Required command not found: {command[0]}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise BuildError(
                f"{description} failed with exit code {exc.returncode}."
            ) from exc

    def validate(self) -> None:
        """Validate project before building."""
        print("[CHECK] Validating project...")

        if not MAIN_SCRIPT.exists():
            raise BuildError(
                f"Entry point not found: {MAIN_SCRIPT}"
            )

        if not (PROJECT_ROOT / "requirements.txt").exists():
            print("[WARNING] requirements.txt not found.")

        if importlib.util.find_spec("PyInstaller") is None:
            raise BuildError(
                "PyInstaller is not installed. "
                "Install it with: pip install pyinstaller"
            )

        print("[OK] Project validation passed.")

    def clean(self) -> None:
        """Remove old build artifacts."""
        print("[CLEAN] Removing previous build artifacts...")

        for path in (BUILD_DIR, DIST_DIR):
            if path.exists():
                shutil.rmtree(path)

        for spec in self.root.glob("*.spec"):
            if spec.name.lower().startswith("assistantx"):
                spec.unlink(missing_ok=True)

    def run_tests(self) -> None:
        """Run project tests."""
        tests_dir = self.root / "tests"

        if not tests_dir.exists():
            print("[WARNING] tests/ directory not found.")
            return

        self.run_command(
            [sys.executable, "-m", "pytest", "tests"],
            description="Running test suite",
        )

    def build(
        self,
        *,
        debug: bool = False,
        onefile: bool = False,
    ) -> None:
        """Build executable using PyInstaller."""

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
        ]

        if onefile:
            command.append("--onefile")
        else:
            command.append("--onedir")

        command.extend(
            [
                "--name",
                DEFAULT_SPEC_NAME,
                "--noconfirm",
                "--clean",
            ]
        )

        if not debug:
            command.append("--windowed")

        # Application data
        data_mappings = [
            ("assets", "assets"),
            ("config", "config"),
            ("resources", "resources"),
            ("data", "data"),
        ]

        for source, destination in data_mappings:
            source_path = self.root / source

            if source_path.exists():
                separator = ";" if sys.platform.startswith("win") else ":"

                command.extend(
                    [
                        "--add-data",
                        f"{source_path}{separator}{destination}",
                    ]
                )

        command.append(str(MAIN_SCRIPT))

        self.run_command(
            command,
            description="Building AssistantX executable",
        )

    def verify_output(self) -> Path:
        """Verify generated executable."""
        if sys.platform.startswith("win"):
            executable = DIST_DIR / DEFAULT_SPEC_NAME / f"{DEFAULT_SPEC_NAME}.exe"

            onefile_executable = (
                DIST_DIR / f"{DEFAULT_SPEC_NAME}.exe"
            )

        else:
            executable = DIST_DIR / DEFAULT_SPEC_NAME / DEFAULT_SPEC_NAME
            onefile_executable = DIST_DIR / DEFAULT_SPEC_NAME

        if executable.exists():
            return executable

        if onefile_executable.exists():
            return onefile_executable

        raise BuildError(
            "Build completed but executable was not found."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} production build utility."
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Build with console output enabled.",
    )

    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Create a single executable.",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean old artifacts before building.",
    )

    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pytest before building.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    builder = Builder(PROJECT_ROOT)

    try:
        builder.validate()

        if args.clean:
            builder.clean()

        if not args.skip_tests:
            builder.run_tests()

        builder.build(
            debug=args.debug,
            onefile=args.onefile,
        )

        output = builder.verify_output()

        print("\n" + "=" * 60)
        print(f"{APP_NAME} BUILD SUCCESSFUL")
        print("=" * 60)
        print(f"Output: {output}")
        print("=" * 60)

        return 0

    except KeyboardInterrupt:
        print("\n[ABORTED] Build cancelled.")
        return 130

    except BuildError as exc:
        print(f"\n[BUILD ERROR] {exc}")
        return 1

    except (OSError, RuntimeError) as exc:
        print(f"\n[FATAL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
