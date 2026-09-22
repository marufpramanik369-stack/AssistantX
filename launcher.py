"""
AssistantX - Application Launcher
=================================

Professional startup/bootstrap launcher for AssistantX.

Responsibilities
----------------
- Resolve the AssistantX project/application directory.
- Prepare runtime directories.
- Load environment configuration.
- Validate the Python runtime.
- Forward launcher arguments to the main application.
- Start ``main.py`` safely.
- Provide useful startup diagnostics.
- Handle startup failures gracefully.
- Support development and packaged execution.

Usage
-----

Development:
    python launcher.py

Debug:
    python launcher.py --debug

Safe mode:
    python launcher.py --safe-mode

Skip splash screen:
    python launcher.py --no-splash

Combined:
    python launcher.py --debug --safe-mode

The launcher intentionally contains startup logic only.
Application logic belongs in ``main.py`` and the rest of AssistantX.
"""

from __future__ import annotations

import argparse
import atexit
import os
import subprocess
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# ============================================================================
# APPLICATION CONSTANTS
# ============================================================================

APP_NAME = "AssistantX"
APP_VERSION = "1.0.0"

MIN_PYTHON_VERSION = (3, 10)

PROJECT_ROOT = Path(__file__).resolve().parent

MAIN_SCRIPT = PROJECT_ROOT / "main.py"

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / "cache"
LOG_DIR = PROJECT_ROOT / "logs"
DATABASE_DIR = PROJECT_ROOT / "database"
RESOURCES_DIR = PROJECT_ROOT / "resources"

ENV_FILE = PROJECT_ROOT / ".env"

LOCK_FILE = CACHE_DIR / ".assistantx.lock"


# ============================================================================
# RUNTIME DIRECTORIES
# ============================================================================

RUNTIME_DIRECTORIES = (
    DATA_DIR,
    CACHE_DIR,
    LOG_DIR,
    DATABASE_DIR,
    RESOURCES_DIR,
)


# ============================================================================
# LAUNCH OPTIONS
# ============================================================================


@dataclass(frozen=True)
class LaunchOptions:
    """Configuration collected from launcher command-line arguments."""

    debug: bool = False
    safe_mode: bool = False
    no_splash: bool = False
    no_update_check: bool = False
    console: bool = False


# ============================================================================
# LOGGER
# ============================================================================


class LauncherLogger:
    """Lightweight launcher logger."""

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
# PLATFORM HELPERS
# ============================================================================


def is_windows() -> bool:
    """Return True when running on Windows."""

    return sys.platform.startswith("win")


def is_macos() -> bool:
    """Return True when running on macOS."""

    return sys.platform == "darwin"


def is_linux() -> bool:
    """Return True when running on Linux."""

    return sys.platform.startswith("linux")


# ============================================================================
# PYTHON RUNTIME
# ============================================================================


def validate_python_version() -> None:
    """Ensure the current Python runtime meets the minimum requirement."""

    current = sys.version_info[:2]

    if current < MIN_PYTHON_VERSION:
        raise RuntimeError(
            "Unsupported Python version.\n"
            f"Required: Python {MIN_PYTHON_VERSION[0]}."
            f"{MIN_PYTHON_VERSION[1]}+\n"
            f"Detected: Python {current[0]}.{current[1]}"
        )

    LauncherLogger.success(
        f"Python {current[0]}.{current[1]} detected."
    )


# ============================================================================
# PROJECT VALIDATION
# ============================================================================


def validate_project_structure() -> None:
    """Validate essential AssistantX files and directories."""

    LauncherLogger.section("Validating AssistantX")

    if not PROJECT_ROOT.exists():
        raise RuntimeError(
            f"Project root does not exist: {PROJECT_ROOT}"
        )

    if not MAIN_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Main application file not found: {MAIN_SCRIPT}"
        )

    if not CONFIG_DIR.is_dir():
        LauncherLogger.warning(
            f"Config directory not found: {CONFIG_DIR}"
        )

    LauncherLogger.success(
        f"Application root: {PROJECT_ROOT}"
    )

    LauncherLogger.success(
        f"Entry point: {MAIN_SCRIPT}"
    )


# ============================================================================
# RUNTIME DIRECTORIES
# ============================================================================


def prepare_runtime_directories() -> None:
    """Create directories required during application runtime."""

    LauncherLogger.section("Preparing runtime")

    for directory in RUNTIME_DIRECTORIES:
        try:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            raise RuntimeError(
                f"Unable to create runtime directory: {directory}"
            ) from exc

        LauncherLogger.info(
            f"Ready: {directory.relative_to(PROJECT_ROOT)}"
        )

    LauncherLogger.success(
        "Runtime directories are ready."
    )


# ============================================================================
# ENVIRONMENT LOADING
# ============================================================================


def load_environment_file() -> None:
    """
    Load .env when python-dotenv is available.

    AssistantX can still start without python-dotenv if no .env
    file is required by the selected configuration.
    """

    if not ENV_FILE.is_file():
        LauncherLogger.warning(
            ".env file not found. Using system environment variables."
        )
        return

    try:
        from importlib import import_module

        load_dotenv = import_module("dotenv").load_dotenv
    except ImportError:
        LauncherLogger.warning(
            "python-dotenv is not installed. "
            "Skipping .env loading."
        )
        return

    loaded = load_dotenv(
        dotenv_path=ENV_FILE,
        override=False,
    )

    if loaded:
        LauncherLogger.success(
            "Environment configuration loaded."
        )
    else:
        LauncherLogger.info(
            ".env exists but no new environment variables were loaded."
        )


# ============================================================================
# ENVIRONMENT DEFAULTS
# ============================================================================


def apply_launcher_environment(
    options: LaunchOptions,
) -> None:
    """Apply safe launcher-level environment settings."""

    os.environ.setdefault(
        "ASSISTANTX_ROOT",
        str(PROJECT_ROOT),
    )

    os.environ.setdefault(
        "APP_NAME",
        APP_NAME,
    )

    os.environ.setdefault(
        "APP_VERSION",
        APP_VERSION,
    )

    os.environ.setdefault(
        "APP_ENV",
        "development",
    )

    if options.debug:
        os.environ["DEBUG"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"

    if options.safe_mode:
        os.environ["ASSISTANTX_SAFE_MODE"] = "true"

    if options.no_splash:
        os.environ["ASSISTANTX_NO_SPLASH"] = "true"

    if options.no_update_check:
        os.environ["ASSISTANTX_NO_UPDATE_CHECK"] = "true"


# ============================================================================
# PYTHON PATH
# ============================================================================


def configure_python_path() -> None:
    """Ensure the AssistantX project root is available on sys.path."""

    project_root_string = str(PROJECT_ROOT)

    if project_root_string not in sys.path:
        sys.path.insert(0, project_root_string)


# ============================================================================
# VIRTUAL ENVIRONMENT DETECTION
# ============================================================================


def detect_virtual_environment() -> Path | None:
    """Return the active virtual environment path, if one exists."""

    virtual_env = os.environ.get("VIRTUAL_ENV")

    if virtual_env:
        path = Path(virtual_env)

        if path.exists():
            return path

    executable = Path(sys.executable)

    if executable.parent.name.lower() in {
        "scripts",
        "bin",
    }:
        candidate = executable.parent.parent

        if candidate.exists():
            return candidate

    return None


def report_virtual_environment() -> None:
    """Report the active virtual environment."""

    virtual_env = detect_virtual_environment()

    if virtual_env is None:
        LauncherLogger.warning(
            "No active virtual environment detected."
        )
        return

    LauncherLogger.success(
        f"Virtual environment: {virtual_env}"
    )


# ============================================================================
# LOCK FILE
# ============================================================================


def create_lock_file() -> None:
    """
    Create a lightweight launcher lock file.

    This is primarily a duplicate-launch guard for development builds.
    """

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if LOCK_FILE.exists():
        try:
            old_pid = LOCK_FILE.read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            old_pid = "unknown"

        LauncherLogger.warning(
            "An AssistantX lock file already exists "
            f"(PID: {old_pid})."
        )

        # Do not hard-block startup. A stale lock can exist after a crash.

    try:
        LOCK_FILE.write_text(
            str(os.getpid()),
            encoding="utf-8",
        )
    except OSError as exc:
        LauncherLogger.warning(
            f"Could not create launcher lock file: {exc}"
        )


def remove_lock_file() -> None:
    """Remove the launcher lock file when the launcher exits."""

    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except OSError:
        pass


# ============================================================================
# ARGUMENT FORWARDING
# ============================================================================


def build_application_arguments(
    options: LaunchOptions,
) -> list[str]:
    """
    Build arguments that should be forwarded to main.py.

    Only arguments explicitly understood by AssistantX are forwarded.
    """

    arguments: list[str] = []

    if options.debug:
        arguments.append("--debug")

    if options.safe_mode:
        arguments.append("--safe-mode")

    if options.no_splash:
        arguments.append("--no-splash")

    if options.no_update_check:
        arguments.append("--no-update-check")

    if options.console:
        arguments.append("--console")

    return arguments


# ============================================================================
# APPLICATION COMMAND
# ============================================================================


def build_application_command(
    options: LaunchOptions,
) -> list[str]:
    """Build the command used to start main.py."""

    return [
        sys.executable,
        str(MAIN_SCRIPT),
        *build_application_arguments(options),
    ]


# ============================================================================
# APPLICATION START
# ============================================================================


def start_application(
    options: LaunchOptions,
) -> int:
    """
    Start the main AssistantX process.

    Returns
    -------
    int
        Exit code returned by the application.
    """

    command = build_application_command(options)

    LauncherLogger.section("Starting AssistantX")

    LauncherLogger.info(
        f"Version: {APP_VERSION}"
    )

    LauncherLogger.info(
        f"Python: {sys.executable}"
    )

    LauncherLogger.info(
        f"Working directory: {PROJECT_ROOT}"
    )

    if options.safe_mode:
        LauncherLogger.warning(
            "Safe mode is enabled."
        )

    if options.debug:
        LauncherLogger.warning(
            "Debug mode is enabled."
        )

    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=os.environ.copy(),
        )
    except OSError as exc:
        raise RuntimeError(
            "Unable to start AssistantX."
        ) from exc

    LauncherLogger.success(
        f"AssistantX started with PID {process.pid}."
    )

    return_code = process.wait()

    if return_code == 0:
        LauncherLogger.success(
            "AssistantX exited normally."
        )
    elif return_code < 0:
        LauncherLogger.warning(
            f"AssistantX terminated by signal {-return_code}."
        )
    else:
        LauncherLogger.error(
            f"AssistantX exited with code {return_code}."
        )

    return return_code


# ============================================================================
# ARGUMENT PARSER
# ============================================================================


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the launcher command-line interface."""

    parser = argparse.ArgumentParser(
        prog="AssistantX",
        description=(
            "AssistantX desktop AI assistant launcher."
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help=(
            "Start AssistantX with optional "
            "features disabled."
        ),
    )

    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Skip the application splash screen.",
    )

    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="Disable startup update checking.",
    )

    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep console-oriented startup behaviour enabled.",
    )

    return parser


# ============================================================================
# STARTUP BANNER
# ============================================================================


def print_startup_banner() -> None:
    """Display a compact AssistantX startup banner."""

    print()
    print("=" * 72)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print("  Desktop AI Assistant")
    print("=" * 72)


# ============================================================================
# ERROR HANDLING
# ============================================================================


def report_startup_error(exc: BaseException) -> None:
    """Display a useful startup error."""

    LauncherLogger.error(
        f"{type(exc).__name__}: {exc}"
    )

    if os.environ.get("DEBUG", "").lower() == "true":
        print()
        print("Startup traceback:")
        traceback.print_exc()


# ============================================================================
# MAIN
# ============================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """Launcher entry point."""

    parser = create_argument_parser()
    args = parser.parse_args(argv)

    options = LaunchOptions(
        debug=args.debug,
        safe_mode=args.safe_mode,
        no_splash=args.no_splash,
        no_update_check=args.no_update_check,
        console=args.console,
    )

    print_startup_banner()

    try:
        # --------------------------------------------------------------
        # Basic environment preparation
        # --------------------------------------------------------------

        configure_python_path()

        validate_python_version()

        validate_project_structure()

        report_virtual_environment()

        # --------------------------------------------------------------
        # Runtime setup
        # --------------------------------------------------------------

        prepare_runtime_directories()

        load_environment_file()

        apply_launcher_environment(options)

        # --------------------------------------------------------------
        # Lock management
        # --------------------------------------------------------------

        create_lock_file()
        atexit.register(remove_lock_file)

        # --------------------------------------------------------------
        # Launch main application
        # --------------------------------------------------------------

        return start_application(options)

    except KeyboardInterrupt:
        LauncherLogger.warning(
            "Startup cancelled by user."
        )
        return 130

    except (OSError, RuntimeError, ImportError, ValueError) as exc:
        report_startup_error(exc)
        return 1

    finally:
        remove_lock_file()


# ============================================================================
# SCRIPT ENTRY POINT
# ============================================================================


if __name__ == "__main__":
    raise SystemExit(main())
