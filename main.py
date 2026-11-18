#!/usr/bin/env python3
"""
AssistantX - Production Main Entry Point
==========================================

FIXED VERSION - All issues resolved:
✅ Core bootstrap BEFORE dashboard (CRITICAL)
✅ Proper core.bootstrap_app() usage
✅ Dashboard.app.main() pattern
✅ All PyQt5/Lottie code removed (was causing issues)
✅ Proper shutdown sequence
✅ Windows compatible
✅ Clean error handling

Usage:
    python main.py                  # Start with dashboard
    python main.py --debug          # Debug logging
    python main.py --no-ui          # Headless mode
    python main.py --check          # Environment check
"""

import argparse
import contextlib
import logging
import os
import platform
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path


# ============================================================================
# APPLICATION METADATA
# ============================================================================

APP_NAME = "AssistantX"
APP_VERSION = "1.0.0"
MIN_PYTHON = (3, 10)

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

LOGGER = logging.getLogger(APP_NAME)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass(slots=True)
class RuntimeOptions:
    """Runtime configuration from CLI."""
    debug: bool = False
    verbose: bool = False
    safe_mode: bool = False
    no_ui: bool = False
    check_only: bool = False


# ============================================================================
# EXCEPTIONS
# ============================================================================

class AssistantXError(Exception):
    """Base exception for AssistantX errors."""


class BootstrapError(AssistantXError):
    """Raised when core bootstrap fails."""


class EnvironmentError(AssistantXError):
    """Raised when environment validation fails."""


# ============================================================================
# PATH HELPERS
# ============================================================================

def ensure_project_on_path() -> None:
    """Add project directory to sys.path if not already present."""
    project_path = str(BASE_DIR)
    if project_path not in sys.path:
        sys.path.insert(0, project_path)


def ensure_runtime_directories() -> None:
    """Create required runtime directories."""
    for directory in [LOGS_DIR, DATA_DIR, BASE_DIR / "cache"]:
        directory.mkdir(parents=True, exist_ok=True)


# ============================================================================
# PYTHON / PLATFORM VALIDATION
# ============================================================================

def validate_python_version() -> None:
    """Ensure Python version >= 3.10."""
    current = sys.version_info
    if (current.major, current.minor) < MIN_PYTHON:
        required = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
        actual = f"{current.major}.{current.minor}"
        raise EnvironmentError(
            f"{APP_NAME} requires Python {required}+; "
            f"detected Python {actual}."
        )


def validate_basic_environment() -> None:
    """Validate project directory exists and is readable."""
    if not BASE_DIR.exists():
        raise EnvironmentError(f"Project directory not found: {BASE_DIR}")
    if not os.access(BASE_DIR, os.R_OK):
        raise EnvironmentError(f"Project directory not readable: {BASE_DIR}")


def get_platform_info() -> dict[str, str]:
    """Get platform information."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


# ============================================================================
# LOGGING SETUP
# ============================================================================

def configure_logging(options: RuntimeOptions) -> None:
    """Configure console and file logging (single system: core.logger)."""
    ensure_runtime_directories()

    level = logging.DEBUG if options.debug else logging.INFO

    # Use AssistantX's own logging setup so handlers are never duplicated.
    # (Previously this function added its own handlers and core.startup
    # added a second set on top, so every line was logged twice.)
    try:
        from core.logger import setup_logging

        setup_logging(
            level=level,
            console=True,
            log_to_files=True,
            force=True,
        )
    except Exception as exc:
        print(
            f"[{APP_NAME}] Warning: core logging unavailable: {exc}",
            file=sys.stderr,
        )
        logging.basicConfig(
            level=level,
            format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        )

    logging.captureWarnings(True)
    LOGGER.debug("Logging initialized")


# ============================================================================
# CLI ARGUMENT PARSING
# ============================================================================

def parse_arguments(argv=None) -> RuntimeOptions:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="assistantx",
        description="Professional desktop AI assistant",
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--safe-mode", action="store_true", help="Start with limited features")
    parser.add_argument("--no-ui", action="store_true", help="Start without dashboard")
    parser.add_argument("--check", action="store_true", help="Environment check only")

    args = parser.parse_args(argv)

    return RuntimeOptions(
        debug=args.debug,
        verbose=args.verbose,
        safe_mode=args.safe_mode,
        no_ui=args.no_ui,
        check_only=args.check,
    )


# ============================================================================
# CORE BOOTSTRAP - PRIORITY #1 (CRITICAL FIX)
# ============================================================================

def bootstrap_core(options: RuntimeOptions) -> bool:
    """
    Bootstrap AssistantX Core - MUST happen BEFORE dashboard.

    This imports and calls core.bootstrap_app() which initializes:
    - EventBus
    - CommandRouter
    - HistoryManager
    - MemoryManager
    - Scheduler
    - All core subsystems

    Returns:
        True if bootstrap successful, False otherwise.
    """
    try:
        # ✅ CRITICAL: Import from core/__init__.py
        from core import bootstrap_app, is_bootstrapped

        log_level = "DEBUG" if options.debug else "INFO"

        LOGGER.info("=== CORE BOOTSTRAP START ===")
        LOGGER.info("Bootstrapping AssistantX Core (log_level=%s, start_scheduler=True)", log_level)

        # ✅ This initializes ALL core subsystems
        bootstrap_app(
            log_level=log_level,
            start_scheduler=True,  # Start background scheduler
        )

        # ✅ Verify bootstrap succeeded
        if is_bootstrapped():
            LOGGER.info("✅ AssistantX Core bootstrapped successfully")
            LOGGER.info("=== CORE BOOTSTRAP COMPLETE ===")
            return True
        else:
            LOGGER.error("❌ Core bootstrap failed: is_bootstrapped() returned False")
            return False

    except ImportError as exc:
        LOGGER.error("❌ Cannot import core.bootstrap_app: %s", exc)
        LOGGER.error("   Project structure issue or core/__init__.py missing")
        return False

    except Exception as exc:
        LOGGER.exception("❌ Core bootstrap failed with exception")
        return False


# ============================================================================
# DASHBOARD BOOTSTRAP - AFTER CORE (PRIORITY #2)
# ============================================================================

def bootstrap_dashboard(options: RuntimeOptions) -> int:
    """
    Bootstrap and run the dashboard.

    IMPORTANT: This is called AFTER core bootstrap.
    Uses the NEW dashboard.app.main() pattern.

    Returns:
        Exit code from dashboard or 0 if skipped.
    """
    if options.no_ui:
        LOGGER.info("Dashboard disabled by --no-ui")
        return 0

    try:
        LOGGER.info("=== DASHBOARD BOOTSTRAP START ===")

        # ✅ Import dashboard module
        import dashboard.app

        # ✅ Get main() function (NEW pattern)
        main_func = getattr(dashboard.app, "main", None)

        if not callable(main_func):
            LOGGER.error("❌ dashboard.app.main() not found!")
            LOGGER.error("   Expected: def main() -> int in dashboard/app.py")
            return 1

        LOGGER.info("Launching dashboard via dashboard.app.main()")

        # ✅ Run dashboard
        exit_code = main_func()

        LOGGER.info("=== DASHBOARD SHUTDOWN COMPLETE ===")

        return exit_code if isinstance(exit_code, int) else 0

    except ImportError as exc:
        LOGGER.error("❌ Cannot import dashboard.app: %s", exc)
        LOGGER.error("   Dashboard package missing or not installed")
        return 1

    except Exception as exc:
        LOGGER.exception("❌ Dashboard bootstrap failed")
        return 1


# ============================================================================
# ENVIRONMENT CHECK
# ============================================================================

def check_environment() -> bool:
    """Perform environment validation."""
    try:
        validate_python_version()
        validate_basic_environment()
        ensure_runtime_directories()

        info = get_platform_info()
        LOGGER.info("Environment check passed")
        LOGGER.info("  Python: %s", info["python"])
        LOGGER.info("  Platform: %s %s", info["system"], info["machine"])
        LOGGER.info("  Project: %s", BASE_DIR)

        return True

    except AssistantXError as exc:
        LOGGER.error("Environment check failed: %s", exc)
        return False


# ============================================================================
# STARTUP SEQUENCE (CORRECT ORDER - FIXED)
# ============================================================================

def startup(options: RuntimeOptions) -> int:
    """
    Complete startup sequence in correct order:

    1. ✅ Environment validation
    2. ✅ Logging configuration
    3. ✅ CORE BOOTSTRAP (CRITICAL - BEFORE DASHBOARD)
    4. ✅ DASHBOARD BOOTSTRAP (AFTER CORE)

    Returns:
        Exit code for process.
    """
    start_time = time.perf_counter()

    LOGGER.info("=" * 72)
    LOGGER.info("%s %s - Startup sequence starting...", APP_NAME, APP_VERSION)
    LOGGER.info("=" * 72)

    # ✅ STEP 1: Validate environment
    if not check_environment():
        return 2

    # ✅ STEP 2: Bootstrap CORE first (CRITICAL)
    if not bootstrap_core(options):
        LOGGER.error("FATAL: Core bootstrap failed - cannot start dashboard")
        return 1

    # ✅ STEP 3: Bootstrap and run dashboard (after core is ready)
    elapsed = time.perf_counter() - start_time
    LOGGER.info("Startup sequence completed in %.3f seconds", elapsed)

    return bootstrap_dashboard(options)


# ============================================================================
# SHUTDOWN CLEANUP
# ============================================================================

def shutdown_core() -> None:
    """Gracefully shutdown AssistantX Core."""
    try:
        from core import shutdown_app

        LOGGER.info("Shutting down AssistantX Core...")
        shutdown_app()
        LOGGER.info("✅ Core shutdown complete")

    except ImportError:
        LOGGER.debug("Core not bootstrapped, skipping shutdown")

    except Exception as exc:
        LOGGER.warning("Error during core shutdown: %s", exc)


# ============================================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================================

def install_exception_hook() -> None:
    """Install global uncaught exception handler."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            LOGGER.info("Application interrupted by user")
            return

        LOGGER.critical("Unhandled exception: %s", exc_value)
        LOGGER.critical(
            "Traceback:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        )

    sys.excepthook = handle_exception


# ============================================================================
# MAIN APPLICATION ENTRY POINT
# ============================================================================

def main() -> int:
    """
    Main application entry point.

    Returns:
        Process exit code (0 = success, 1 = error, 2 = env check failed).
    """
    # ✅ Parse arguments
    options = parse_arguments()

    # ✅ Setup logging BEFORE anything else
    configure_logging(options)

    # ✅ Install exception handler
    install_exception_hook()

    # ✅ Print banner if debug/verbose
    if options.debug or options.verbose:
        print()
        print("=" * 64)
        print(f"  {APP_NAME} {APP_VERSION}")
        print("  Professional Desktop AI Assistant")
        print("=" * 64)
        print()

    try:
        # ✅ Environment check only?
        if options.check_only:
            success = check_environment()
            return 0 if success else 2

        # ✅ Full startup with correct bootstrap order
        return startup(options)

    except KeyboardInterrupt:
        LOGGER.info("Caught KeyboardInterrupt - shutting down")
        return 0

    except AssistantXError as exc:
        LOGGER.error("AssistantX error: %s", exc)
        if options.debug:
            traceback.print_exc()
        return 1

    except Exception as exc:
        LOGGER.exception("Unexpected error: %s", exc)
        if options.debug:
            traceback.print_exc()
        return 1

    finally:
        # ✅ Always cleanup
        LOGGER.info("=" * 72)
        LOGGER.info("Shutdown sequence starting...")
        shutdown_core()
        LOGGER.info("%s shutdown complete", APP_NAME)
        LOGGER.info("=" * 72)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
    