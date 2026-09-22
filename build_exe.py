"""
AssistantX - Windows Executable Builder
=======================================

Professional PyInstaller build script for AssistantX.

Features
--------
- Builds AssistantX using PyInstaller.
- Supports one-directory and one-file builds.
- Automatically detects the project root.
- Includes assets, resources, themes and required runtime files.
- Cleans previous build artifacts.
- Supports debug and console modes.
- Validates Python and PyInstaller availability.
- Provides clear build progress and error messages.

Usage
-----

Standard release build:
    python build_exe.py

Clean release build:
    python build_exe.py --clean

One-file executable:
    python build_exe.py --onefile

Console-enabled build:
    python build_exe.py --console

Debug build:
    python build_exe.py --debug

Clean + one-file:
    python build_exe.py --clean --onefile

Requirements
------------
PyInstaller must be installed:

    python -m pip install pyinstaller

The main application entry point is expected to be:

    main.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# ============================================================================
# PROJECT CONFIGURATION
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent

APP_NAME = "AssistantX"
APP_VERSION = "1.0.0"

ENTRY_POINT = PROJECT_ROOT / "main.py"

BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"

# PyInstaller working directory.
PYINSTALLER_BUILD_DIR = BUILD_DIR / "pyinstaller"

# Final distribution directory.
RELEASE_DIR = DIST_DIR / APP_NAME

# Optional application icon.
ICON_CANDIDATES = (
    PROJECT_ROOT / "assets" / "icons" / "app.ico",
    PROJECT_ROOT / "assets" / "icons" / "assistantx.ico",
    PROJECT_ROOT / "assets" / "app.ico",
)

# Directories containing runtime resources.
DATA_DIRECTORIES = (
    "assets",
    "resources",
)

# Optional runtime directories.
# These are intentionally created in the final application directory
# instead of copying potentially user-specific runtime data.
RUNTIME_DIRECTORIES = (
    "cache",
    "logs",
    "data",
)


# ============================================================================
# BUILD OPTIONS
# ============================================================================


@dataclass(frozen=True)
class BuildOptions:
    """Runtime options used by the build process."""

    onefile: bool = False
    console: bool = False
    clean: bool = False
    debug: bool = False
    strip: bool = False
    version: str = APP_VERSION


# ============================================================================
# LOGGING
# ============================================================================


class BuildLogger:
    """Small terminal logger used by the build system."""

    PREFIX = "[AssistantX]"

    @classmethod
    def info(cls, message: str) -> None:
        print(f"{cls.PREFIX} {message}")

    @classmethod
    def success(cls, message: str) -> None:
        print(f"{cls.PREFIX} OK: {message}")

    @classmethod
    def warning(cls, message: str) -> None:
        print(f"{cls.PREFIX} WARNING: {message}")

    @classmethod
    def error(cls, message: str) -> None:
        print(f"{cls.PREFIX} ERROR: {message}")

    @classmethod
    def section(cls, title: str) -> None:
        print()
        print("=" * 72)
        print(title)
        print("=" * 72)


# ============================================================================
# PATH UTILITIES
# ============================================================================


def path_exists(path: Path) -> bool:
    """Return True when a path exists."""
    return path.exists()


def find_icon() -> Path | None:
    """
    Find the first available AssistantX icon.

    Returns
    -------
    Path | None
        Existing icon path or None.
    """

    for candidate in ICON_CANDIDATES:
        if candidate.is_file():
            return candidate

    return None


def ensure_project_structure() -> None:
    """Validate important project files before starting the build."""

    BuildLogger.section("Validating project")

    if not PROJECT_ROOT.exists():
        raise RuntimeError("Project root directory does not exist.")

    if not ENTRY_POINT.is_file():
        raise FileNotFoundError(
            f"Application entry point was not found: {ENTRY_POINT}"
        )

    BuildLogger.success(f"Project root: {PROJECT_ROOT}")
    BuildLogger.success(f"Entry point: {ENTRY_POINT}")


# ============================================================================
# ENVIRONMENT VALIDATION
# ============================================================================


def check_python_version() -> None:
    """Validate the Python version."""

    minimum = (3, 10)
    current = sys.version_info[:2]

    if current < minimum:
        raise RuntimeError(
            "AssistantX requires Python "
            f"{minimum[0]}.{minimum[1]} or newer. "
            f"Current version: {current[0]}.{current[1]}"
        )

    BuildLogger.success(
        f"Python {current[0]}.{current[1]} detected."
    )


def check_pyinstaller() -> None:
    """Verify that PyInstaller is available."""

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--version",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(
            "PyInstaller is not installed.\n"
            "Install it with:\n\n"
            "    python -m pip install pyinstaller"
        ) from exc

    version = result.stdout.strip() or result.stderr.strip()

    BuildLogger.success(
        f"PyInstaller {version} detected."
    )


# ============================================================================
# CLEANING
# ============================================================================


def remove_path(path: Path) -> None:
    """Remove a file or directory safely."""

    if not path.exists():
        return

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def clean_build_directories() -> None:
    """Remove previous PyInstaller build artifacts."""

    BuildLogger.section("Cleaning previous build")

    targets = (
        BUILD_DIR,
        DIST_DIR,
    )

    for target in targets:
        if target.exists():
            BuildLogger.info(f"Removing: {target}")
            remove_path(target)

    BuildLogger.success("Previous build artifacts removed.")


# ============================================================================
# DATA FILE HANDLING
# ============================================================================


def existing_data_directories() -> list[Path]:
    """
    Return resource directories that actually exist.

    Runtime-generated directories such as cache and logs are not copied.
    """

    directories: list[Path] = []

    for directory_name in DATA_DIRECTORIES:
        directory = PROJECT_ROOT / directory_name

        if directory.is_dir():
            directories.append(directory)
        else:
            BuildLogger.warning(
                f"Optional resource directory missing: {directory}"
            )

    return directories


def create_runtime_directories(output_dir: Path) -> None:
    """Create runtime directories required by AssistantX."""

    for directory_name in RUNTIME_DIRECTORIES:
        directory = output_dir / directory_name
        directory.mkdir(parents=True, exist_ok=True)

        # Keep empty runtime directories visible in packaged releases.
        gitkeep = directory / ".gitkeep"

        if not gitkeep.exists():
            gitkeep.write_text(
                "# AssistantX runtime directory\n",
                encoding="utf-8",
            )


# ============================================================================
# PYINSTALLER DATA ARGUMENTS
# ============================================================================


def build_add_data_arguments(
    directories: Iterable[Path],
) -> list[str]:
    """
    Create PyInstaller --add-data arguments.

    On Windows PyInstaller uses:

        source;destination
    """

    arguments: list[str] = []

    separator = os.pathsep

    for directory in directories:
        destination = directory.name

        arguments.extend(
            [
                "--add-data",
                f"{directory}{separator}{destination}",
            ]
        )

        BuildLogger.info(
            f"Including resources: {directory.name}/"
        )

    return arguments


# ============================================================================
# HIDDEN IMPORTS
# ============================================================================


def get_hidden_imports() -> list[str]:
    """
    Return modules that may be imported dynamically.

    Keep this list limited to packages actually used by AssistantX.
    """

    return [
        # AssistantX packages
        "config",
        "core",
        "brain",
        "ai",
        "voice",
        "automation",
        "services",
        "dashboard",
        "database",
        "plugins",

        # Optional common runtime modules
        "sqlite3",
        "tkinter",
    ]


def build_hidden_import_arguments() -> list[str]:
    """Convert hidden imports to PyInstaller CLI arguments."""

    arguments: list[str] = []

    for module in get_hidden_imports():
        arguments.extend(
            [
                "--hidden-import",
                module,
            ]
        )

    return arguments


# ============================================================================
# EXCLUDE MODULES
# ============================================================================


def get_excluded_modules() -> list[str]:
    """
    Return modules that should not be bundled.

    These exclusions reduce unnecessary bundle size.
    """

    return [
        "pytest",
        "unittest",
        "IPython",
        "jupyter",
        "notebook",
    ]


def build_exclude_arguments() -> list[str]:
    """Convert excluded modules to PyInstaller arguments."""

    arguments: list[str] = []

    for module in get_excluded_modules():
        arguments.extend(
            [
                "--exclude-module",
                module,
            ]
        )

    return arguments


# ============================================================================
# OUTPUT NAME
# ============================================================================


def get_distribution_name(options: BuildOptions) -> str:
    """Return the executable/distribution name."""

    safe_version = options.version.replace(" ", "_")

    if options.onefile:
        return f"{APP_NAME}_v{safe_version}"

    return f"{APP_NAME}_v{safe_version}"


# ============================================================================
# PYINSTALLER COMMAND
# ============================================================================


def build_pyinstaller_command(
    options: BuildOptions,
) -> list[str]:
    """Build the complete PyInstaller command."""

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
    ]

    # ----------------------------------------------------------------------
    # General options
    # ----------------------------------------------------------------------

    command.extend(
        [
            "--name",
            get_distribution_name(options),
        ]
    )

    command.extend(
        [
            "--distpath",
            str(DIST_DIR),
        ]
    )

    command.extend(
        [
            "--workpath",
            str(PYINSTALLER_BUILD_DIR),
        ]
    )

    command.extend(
        [
            "--specpath",
            str(BUILD_DIR),
        ]
    )

    # ----------------------------------------------------------------------
    # Clean build
    # ----------------------------------------------------------------------

    if options.clean:
        command.append("--clean")

    # ----------------------------------------------------------------------
    # One-file / one-directory
    # ----------------------------------------------------------------------

    if options.onefile:
        command.append("--onefile")
    else:
        command.append("--onedir")

    # ----------------------------------------------------------------------
    # Console
    # ----------------------------------------------------------------------

    if options.console:
        command.append("--console")
    else:
        command.append("--windowed")

    # ----------------------------------------------------------------------
    # Debug
    # ----------------------------------------------------------------------

    if options.debug:
        command.extend(
            [
                "--debug",
                "all",
            ]
        )

    # ----------------------------------------------------------------------
    # Strip symbols
    # ----------------------------------------------------------------------

    if options.strip:
        command.append("--strip")

    # ----------------------------------------------------------------------
    # Icon
    # ----------------------------------------------------------------------

    icon = find_icon()

    if icon is not None:
        command.extend(
            [
                "--icon",
                str(icon),
            ]
        )

        BuildLogger.info(
            f"Application icon: {icon}"
        )
    else:
        BuildLogger.warning(
            "No application icon found. "
            "Build will continue without a custom icon."
        )

    # ----------------------------------------------------------------------
    # Resource directories
    # ----------------------------------------------------------------------

    command.extend(
        build_add_data_arguments(
            existing_data_directories()
        )
    )

    # ----------------------------------------------------------------------
    # Hidden imports
    # ----------------------------------------------------------------------

    command.extend(
        build_hidden_import_arguments()
    )

    # ----------------------------------------------------------------------
    # Excluded modules
    # ----------------------------------------------------------------------

    command.extend(
        build_exclude_arguments()
    )

    # ----------------------------------------------------------------------
    # Entry point
    # ----------------------------------------------------------------------

    command.append(str(ENTRY_POINT))

    return command


# ============================================================================
# BUILD EXECUTION
# ============================================================================


def run_build(command: list[str]) -> None:
    """Execute PyInstaller."""

    BuildLogger.section("Building AssistantX")

    BuildLogger.info("Running PyInstaller...")
    BuildLogger.info("")

    if options_debug_enabled(command):
        BuildLogger.warning(
            "Debug mode is enabled."
        )

    try:
        subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "PyInstaller build failed."
        ) from exc


def options_debug_enabled(command: list[str]) -> bool:
    """Check whether the generated command contains debug mode."""

    return "--debug" in command


# ============================================================================
# RELEASE PREPARATION
# ============================================================================


def find_final_output(options: BuildOptions) -> Path:
    """Find the generated executable or application directory."""

    distribution_name = get_distribution_name(options)

    if options.onefile:
        executable = DIST_DIR / f"{distribution_name}.exe"

        if executable.is_file():
            return executable

        raise FileNotFoundError(
            f"Expected executable was not found: {executable}"
        )

    application_directory = DIST_DIR / distribution_name

    if application_directory.is_dir():
        executable = application_directory / f"{distribution_name}.exe"

        if executable.is_file():
            return executable

        raise FileNotFoundError(
            f"Expected executable was not found: {executable}"
        )

    raise FileNotFoundError(
        f"Expected distribution directory was not found: "
        f"{application_directory}"
    )


def prepare_release_directory(
    options: BuildOptions,
) -> Path:
    """Prepare runtime directories for a directory-based build."""

    output = find_final_output(options)

    if options.onefile:
        # One-file applications extract to a temporary runtime directory
        # at execution time. Persistent runtime folders should normally live
        # outside the executable directory.
        return output

    application_directory = output.parent

    create_runtime_directories(application_directory)

    return application_directory


# ============================================================================
# BUILD SUMMARY
# ============================================================================


def print_build_summary(
    options: BuildOptions,
    output: Path,
) -> None:
    """Print final build information."""

    BuildLogger.section("Build completed")

    BuildLogger.success(
        f"Application : {APP_NAME}"
    )

    BuildLogger.success(
        f"Version     : {options.version}"
    )

    BuildLogger.success(
        f"Build type  : "
        f"{'OneFile' if options.onefile else 'OneDir'}"
    )

    BuildLogger.success(
        f"Console     : "
        f"{'Enabled' if options.console else 'Disabled'}"
    )

    BuildLogger.success(
        f"Output      : {output}"
    )

    print()
    print("Next step:")
    print(f"    {output}")


# ============================================================================
# ARGUMENT PARSER
# ============================================================================


def create_argument_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Build AssistantX Windows executable "
            "using PyInstaller."
        )
    )

    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single executable file.",
    )

    parser.add_argument(
        "--console",
        action="store_true",
        help="Show a console window when AssistantX runs.",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build and dist directories.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable PyInstaller debug output.",
    )

    parser.add_argument(
        "--strip",
        action="store_true",
        help="Strip symbols from binaries where supported.",
    )

    parser.add_argument(
        "--version",
        default=APP_VERSION,
        help=(
            "Application version. "
            f"Default: {APP_VERSION}"
        ),
    )

    return parser


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    """Application entry point."""

    parser = create_argument_parser()
    options = parser.parse_args()

    build_options = BuildOptions(
        onefile=options.onefile,
        console=options.console,
        clean=options.clean,
        debug=options.debug,
        strip=options.strip,
        version=options.version,
    )

    try:
        # --------------------------------------------------------------
        # Validation
        # --------------------------------------------------------------

        ensure_project_structure()
        check_python_version()
        check_pyinstaller()

        # --------------------------------------------------------------
        # Clean
        # --------------------------------------------------------------

        if build_options.clean:
            clean_build_directories()

        # --------------------------------------------------------------
        # Build command
        # --------------------------------------------------------------

        command = build_pyinstaller_command(
            build_options
        )

        # --------------------------------------------------------------
        # Build
        # --------------------------------------------------------------

        run_build(command)

        # --------------------------------------------------------------
        # Verify output
        # --------------------------------------------------------------

        output = prepare_release_directory(
            build_options
        )

        # --------------------------------------------------------------
        # Summary
        # --------------------------------------------------------------

        print_build_summary(
            build_options,
            output,
        )

        return 0

    except KeyboardInterrupt:
        BuildLogger.warning(
            "Build cancelled by user."
        )
        return 130

    except (OSError, RuntimeError, ValueError) as exc:
        BuildLogger.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

