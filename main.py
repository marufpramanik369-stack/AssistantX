"""
AssistantX - Main Application Entry Point
==========================================

Professional application bootstrap for AssistantX.

Responsibilities
----------------
- Application metadata and CLI handling
- Python/runtime validation
- Environment initialization
- Logging bootstrap
- Runtime directory preparation
- Global exception handling
- Graceful shutdown
- Optional dashboard startup
- Optional AssistantX core startup
- Safe-mode support
- Debug/verbose support

Usage
-----
    python main.py
    python main.py --debug
    python main.py --verbose
    python main.py --safe-mode
    python main.py --no-ui
    python main.py --version
    python main.py --check
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import platform
import sys
import time
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

# ============================================================================
# APPLICATION METADATA
# ============================================================================

APP_NAME = "AssistantX"
APP_SLUG = "assistantx"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "Professional desktop AI assistant."

MIN_PYTHON = (3, 10)


# ============================================================================
# PATHS
# ============================================================================

BASE_DIR = Path(__file__).resolve().parent

CONFIG_DIR = BASE_DIR / "config"
CORE_DIR = BASE_DIR / "core"
BRAIN_DIR = BASE_DIR / "brain"
AI_DIR = BASE_DIR / "ai"
VOICE_DIR = BASE_DIR / "voice"
AUTOMATION_DIR = BASE_DIR / "automation"
SERVICES_DIR = BASE_DIR / "services"
DASHBOARD_DIR = BASE_DIR / "dashboard"
DATABASE_DIR = BASE_DIR / "database"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
LOGS_DIR = BASE_DIR / "logs"
RESOURCES_DIR = BASE_DIR / "resources"
PLUGINS_DIR = BASE_DIR / "plugins"


# ============================================================================
# LOGGING
# ============================================================================

LOGGER = logging.getLogger(APP_NAME)


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass(slots=True)
class RuntimeOptions:
    """Runtime configuration collected from CLI arguments."""

    debug: bool = False
    verbose: bool = False
    safe_mode: bool = False
    no_ui: bool = False
    check_only: bool = False


@dataclass(slots=True)
class StartupResult:
    """Result returned by the application startup sequence."""

    success: bool
    message: str = ""
    exit_code: int = 0


# ============================================================================
# EXCEPTIONS
# ============================================================================


class AssistantXError(Exception):
    """Base exception for main application errors."""


class StartupError(AssistantXError):
    """Raised when application startup fails."""


class EnvironmentError(AssistantXError):
    """Raised when the runtime environment is invalid."""


# ============================================================================
# PATH / RUNTIME HELPERS
# ============================================================================


def ensure_project_on_path() -> None:
    """
    Ensure the AssistantX project directory is importable.

    This is useful when main.py is launched from another working directory.
    """

    project_path = str(BASE_DIR)

    if project_path not in sys.path:
        sys.path.insert(0, project_path)


def ensure_runtime_directories() -> None:
    """
    Create directories required by AssistantX at runtime.

    Existing directories are left untouched.
    """

    directories = (
        DATA_DIR,
        CACHE_DIR,
        LOGS_DIR,
        DATABASE_DIR,
        CACHE_DIR / "ai",
        CACHE_DIR / "images",
        CACHE_DIR / "search",
        CACHE_DIR / "temp",
        RESOURCES_DIR,
    )

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def is_project_structure_valid() -> bool:
    """
    Perform a lightweight project structure validation.

    This does not require every optional subsystem to exist.
    """

    required_files = (
        BASE_DIR / "main.py",
        BASE_DIR / "config",
        BASE_DIR / "core",
    )

    missing = [
        str(path.relative_to(BASE_DIR))
        for path in required_files
        if not path.exists()
    ]

    if missing:
        LOGGER.error("Missing required project components: %s", missing)
        return False

    return True


# ============================================================================
# PYTHON / PLATFORM VALIDATION
# ============================================================================


def validate_python_version() -> None:
    """Ensure the current Python version meets the minimum requirement."""

    current = sys.version_info

    if (current.major, current.minor) < MIN_PYTHON:
        required = f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
        actual = f"{current.major}.{current.minor}"

        raise EnvironmentError(
            f"{APP_NAME} requires Python {required}+; "
            f"detected Python {actual}."
        )


def get_platform_info() -> dict[str, str]:
    """Return useful runtime platform information."""

    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or "Unknown",
        "python": platform.python_version(),
    }


def log_platform_info() -> None:
    """Write platform information to the application log."""

    info = get_platform_info()

    LOGGER.debug("Operating system: %s", info["system"])
    LOGGER.debug("OS release: %s", info["release"])
    LOGGER.debug("Architecture: %s", info["machine"])
    LOGGER.debug("Processor: %s", info["processor"])
    LOGGER.debug("Python: %s", info["python"])


# ============================================================================
# ENVIRONMENT
# ============================================================================


def load_environment() -> None:
    """
    Load environment variables from .env when python-dotenv is available.

    Failure to import dotenv does not immediately stop AssistantX because
    environment loading is optional.
    """

    env_file = BASE_DIR / ".env"

    if not env_file.exists():
        LOGGER.debug("No .env file found.")
        return

    try:
        from importlib import import_module

        load_dotenv = import_module("dotenv").load_dotenv
    except ImportError:
        LOGGER.warning(
            "python-dotenv is not installed; .env was not loaded."
        )
        return

    loaded = load_dotenv(env_file)

    if loaded:
        LOGGER.debug("Environment loaded from %s", env_file)
    else:
        LOGGER.debug("Environment file found but no new values were loaded.")


def validate_basic_environment() -> None:
    """
    Validate only the minimum environment required to start AssistantX.

    API keys are intentionally not hard-required here because different
    providers may be configured.
    """

    if not BASE_DIR.exists():
        raise EnvironmentError(
            f"AssistantX project directory does not exist: {BASE_DIR}"
        )

    if not os.access(BASE_DIR, os.R_OK):
        raise EnvironmentError(
            f"AssistantX project directory is not readable: {BASE_DIR}"
        )


# ============================================================================
# LOGGING SETUP
# ============================================================================


def _get_log_level(options: RuntimeOptions) -> int:
    """Resolve logging level from runtime options."""

    if options.debug:
        return logging.DEBUG

    if options.verbose:
        return logging.INFO

    return logging.INFO


def configure_logging(options: RuntimeOptions) -> None:
    """
    Configure console and file logging.

    Existing handlers are removed to avoid duplicate log entries when
    main.py is initialized more than once.
    """

    ensure_runtime_directories()

    level = _get_log_level(options)

    log_file = LOGS_DIR / "assistant.log"

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)-8s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    try:
        file_handler = logging.FileHandler(
            log_file,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)

    except OSError as exc:
        print(
            f"[AssistantX] Warning: file logging unavailable: {exc}",
            file=sys.stderr,
        )

    root_logger.addHandler(console_handler)

    logging.captureWarnings(True)

    LOGGER.debug("Logging initialized.")
    LOGGER.debug("Log file: %s", log_file)


# ============================================================================
# CLI
# ============================================================================


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the AssistantX command-line interface."""

    parser = argparse.ArgumentParser(
        prog=APP_SLUG,
        description=APP_DESCRIPTION,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose application output.",
    )

    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help=(
            "Start with optional subsystems disabled where supported."
        ),
    )

    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Start AssistantX without the graphical dashboard.",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the environment and exit.",
    )

    return parser


def parse_arguments(
    argv: Sequence[str] | None = None,
) -> RuntimeOptions:
    """Parse CLI arguments into RuntimeOptions."""

    parser = build_argument_parser()
    args = parser.parse_args(argv)

    return RuntimeOptions(
        debug=args.debug,
        verbose=args.verbose,
        safe_mode=args.safe_mode,
        no_ui=args.no_ui,
        check_only=args.check,
    )


# ============================================================================
# IMPORT HELPERS
# ============================================================================


def optional_import(module_name: str) -> ModuleType | None:
    """
    Import an optional module without crashing the application.

    Returns:
        Imported module or None when unavailable.
    """

    try:
        module = __import__(module_name, fromlist=["*"])
        LOGGER.debug("Loaded optional module: %s", module_name)
        return module

    except ImportError as exc:
        LOGGER.debug(
            "Optional module unavailable: %s (%s)",
            module_name,
            exc,
        )
        return None

    except Exception:
        LOGGER.exception(
            "Unexpected error while importing optional module: %s",
            module_name,
        )
        return None


# ============================================================================
# CONFIGURATION BOOTSTRAP
# ============================================================================


def initialize_configuration() -> None:
    """
    Initialize AssistantX configuration.

    The function supports the existing config package while remaining
    tolerant of partially completed modules during development.
    """

    config_module = optional_import("config.config")

    if config_module is None:
        LOGGER.debug("config.config is not available.")
        return

    initialize = getattr(config_module, "initialize", None)

    if callable(initialize):
        try:
            initialize()
            LOGGER.debug("Configuration initialized.")
        except Exception as err:
            LOGGER.exception("Configuration initialization failed.")
            raise StartupError(
                "AssistantX configuration could not be initialized."
            ) from err


# ============================================================================
# CORE BOOTSTRAP
# ============================================================================


def initialize_core(
    options: RuntimeOptions,
) -> object | None:
    """
    Initialize the AssistantX core assistant.

    Supports several common initialization patterns so the main entry point
    remains flexible while the core architecture evolves.
    """

    if options.safe_mode:
        LOGGER.info("Safe mode enabled.")

    assistant_module = optional_import("core.assistant")

    if assistant_module is None:
        LOGGER.warning(
            "core.assistant is unavailable. "
            "Starting in limited mode."
        )
        return None

    assistant_class = getattr(
        assistant_module,
        "Assistant",
        None,
    )

    if assistant_class is None:
        LOGGER.debug(
            "No Assistant class found in core.assistant."
        )
        return None

    try:
        assistant = assistant_class()

    except TypeError:
        try:
            assistant = assistant_class(
                safe_mode=options.safe_mode,
            )
        except Exception as exc:
            LOGGER.exception("Assistant initialization failed.")
            raise StartupError(
                f"Assistant initialization failed: {exc}"
            ) from exc

    except Exception as exc:
        LOGGER.exception("Assistant initialization failed.")
        raise StartupError(
            f"Assistant initialization failed: {exc}"
        ) from exc

    initialize = getattr(assistant, "initialize", None)

    if callable(initialize):
        try:
            initialize()
        except Exception as exc:
            LOGGER.exception("Assistant.initialize() failed.")
            raise StartupError(
                f"Assistant initialization failed: {exc}"
            ) from exc

    LOGGER.info("Assistant core initialized.")

    return assistant


# ============================================================================
# MEMORY BOOTSTRAP
# ============================================================================


def initialize_memory() -> object | None:
    """
    Initialize the persistent memory subsystem when available.
    """

    memory_module = optional_import("core.memory")

    if memory_module is None:
        LOGGER.debug("Persistent memory module unavailable.")
        return None

    memory_object = getattr(memory_module, "memory", None)

    if memory_object is not None:
        LOGGER.info("Persistent memory subsystem loaded.")
        return memory_object

    LOGGER.debug(
        "core.memory loaded but no global memory object was found."
    )

    return memory_module


# ============================================================================
# CACHE BOOTSTRAP
# ============================================================================


def initialize_cache() -> object | None:
    """
    Initialize the cache manager when available.
    """

    cache_module = optional_import("core.cache_manager")

    if cache_module is None:
        LOGGER.debug("Cache manager unavailable.")
        return None

    manager = getattr(
        cache_module,
        "cache_manager",
        None,
    )

    if manager is not None:
        LOGGER.info("Cache manager loaded.")
        return manager

    manager_class = getattr(
        cache_module,
        "CacheManager",
        None,
    )

    if manager_class is None:
        LOGGER.debug(
            "No CacheManager found in core.cache_manager."
        )
        return None

    try:
        manager = manager_class()
        LOGGER.info("Cache manager initialized.")
        return manager

    except Exception:
        LOGGER.exception(
            "Cache manager initialization failed."
        )
        return None


# ============================================================================
# SERVICE BOOTSTRAP
# ============================================================================


def initialize_services(
    options: RuntimeOptions,
) -> list[object]:
    """
    Initialize optional service modules.

    Services are intentionally best-effort for Basic AssistantX.
    """

    if options.safe_mode:
        LOGGER.info(
            "Skipping optional services in safe mode."
        )
        return []

    service_modules = (
        "services.search_service",
        "services.weather_service",
        "services.news_service",
        "services.wikipedia_service",
        "services.translate_service",
        "services.reminder_service",
    )

    loaded_services: list[object] = []

    for module_name in service_modules:
        module = optional_import(module_name)

        if module is not None:
            loaded_services.append(module)

    LOGGER.info(
        "Optional services loaded: %d",
        len(loaded_services),
    )

    return loaded_services


# ============================================================================
# DASHBOARD
# ============================================================================


def initialize_dashboard(
    assistant: object | None,
    options: RuntimeOptions,
) -> object | None:
    """
    Initialize the graphical dashboard.

    Supported patterns:
        dashboard.app.create_app()
        dashboard.app.run()
        dashboard.app.App(...)
        dashboard.window.Window(...)
    """

    if options.no_ui:
        LOGGER.info("GUI disabled by --no-ui.")
        return None

    if options.safe_mode:
        LOGGER.info("GUI optional components may be limited in safe mode.")

    dashboard_module = optional_import("dashboard.app")

    if dashboard_module is None:
        LOGGER.warning(
            "dashboard.app is unavailable. "
            "AssistantX will continue without GUI."
        )
        return None

    # Pattern 1: create_app()
    create_app = getattr(
        dashboard_module,
        "create_app",
        None,
    )

    if callable(create_app):
        try:
            app = create_app(assistant=assistant)
            LOGGER.info("Dashboard created using create_app().")
            return app

        except TypeError:
            try:
                app = create_app()
                LOGGER.info("Dashboard created using create_app().")
                return app

            except Exception:
                LOGGER.exception(
                    "Dashboard create_app() failed."
                )

        except Exception:
            LOGGER.exception(
                "Dashboard create_app() failed."
            )

    # Pattern 2: App class
    app_class = getattr(
        dashboard_module,
        "App",
        None,
    )

    if app_class is not None:
        try:
            try:
                app = app_class(assistant=assistant)
            except TypeError:
                app = app_class()

            LOGGER.info("Dashboard created using App class.")
            return app

        except Exception:
            LOGGER.exception(
                "Dashboard App initialization failed."
            )

    LOGGER.warning(
        "No supported dashboard entry point was found."
    )

    return None


# ============================================================================
# APPLICATION RUNNER
# ============================================================================


def run_object(application: object) -> int:
    """
    Run an application object using the first supported method.

    Supported methods:
        run()
        start()
        exec()
        mainloop()
    """

    methods: tuple[str, ...] = (
        "run",
        "start",
        "exec",
        "mainloop",
    )

    for method_name in methods:
        method = getattr(application, method_name, None)

        if not callable(method):
            continue

        LOGGER.debug(
            "Running application using %s().",
            method_name,
        )

        result = method()

        if isinstance(result, int):
            return result

        return 0

    LOGGER.debug(
        "Application object has no recognized run method."
    )

    return 0


# ============================================================================
# SHUTDOWN
# ============================================================================


def shutdown_object(
    obj: object | None,
    name: str,
) -> None:
    """Attempt graceful shutdown of an application component."""

    if obj is None:
        return

    shutdown_methods = (
        "shutdown",
        "close",
        "stop",
        "dispose",
    )

    for method_name in shutdown_methods:
        method = getattr(obj, method_name, None)

        if not callable(method):
            continue

        try:
            method()
            LOGGER.debug("%s shutdown via %s().", name, method_name)
        except Exception:
            LOGGER.exception(
                "Error while shutting down %s.",
                name,
            )

        return


# ============================================================================
# ENVIRONMENT CHECK
# ============================================================================


def perform_environment_check() -> StartupResult:
    """
    Perform a non-destructive environment check.
    """

    try:
        validate_python_version()
        validate_basic_environment()

        if not is_project_structure_valid():
            return StartupResult(
                success=False,
                message="Project structure validation failed.",
                exit_code=2,
            )

        ensure_runtime_directories()

        LOGGER.info("Environment check passed.")

        return StartupResult(
            success=True,
            message="AssistantX environment is ready.",
            exit_code=0,
        )

    except AssistantXError as exc:
        LOGGER.error("%s", exc)

        return StartupResult(
            success=False,
            message=str(exc),
            exit_code=2,
        )

    except Exception as exc:
        LOGGER.exception("Unexpected environment check failure.")

        return StartupResult(
            success=False,
            message=str(exc),
            exit_code=1,
        )


# ============================================================================
# STARTUP SEQUENCE
# ============================================================================


def startup(
    options: RuntimeOptions,
) -> tuple[object | None, object | None]:
    """
    Execute the complete AssistantX startup sequence.

    Returns:
        (assistant, dashboard)
    """

    start_time = time.perf_counter()

    LOGGER.info("=" * 72)
    LOGGER.info(
        "%s %s starting...",
        APP_NAME,
        APP_VERSION,
    )
    LOGGER.info("=" * 72)

    validate_python_version()
    validate_basic_environment()
    ensure_project_on_path()
    ensure_runtime_directories()

    log_platform_info()

    load_environment()
    initialize_configuration()

    environment_result = perform_environment_check()

    if not environment_result.success:
        raise StartupError(
            environment_result.message
        )

    memory = initialize_memory()

    if memory is not None:
        LOGGER.debug("Memory subsystem ready.")

    initialize_cache()

    assistant = initialize_core(options)

    initialize_services(options)

    dashboard = initialize_dashboard(
        assistant=assistant,
        options=options,
    )

    elapsed = time.perf_counter() - start_time

    LOGGER.info(
        "AssistantX startup completed in %.3f seconds.",
        elapsed,
    )

    return assistant, dashboard


# ============================================================================
# UNHANDLED EXCEPTION HANDLER
# ============================================================================


def install_exception_hook() -> None:
    """
    Install a global uncaught-exception handler.

    KeyboardInterrupt remains user-friendly and is not logged as a crash.
    """

    def handle_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: object,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            LOGGER.info("Application interrupted by user.")
            return

        LOGGER.critical(
            "Unhandled application exception: %s",
            exc_value,
        )

        LOGGER.critical(
            "Traceback:\n%s",
            "".join(
                traceback.format_exception(
                    exc_type,
                    exc_value,
                    exc_traceback,
                )
            ),
        )

    sys.excepthook = handle_exception


# ============================================================================
# CONSOLE HELPERS
# ============================================================================


def print_banner() -> None:
    """Print a small startup banner."""

    print()
    print("=" * 64)
    print(f"  {APP_NAME} {APP_VERSION}")
    print("  Professional Desktop AI Assistant")
    print("=" * 64)
    print()


def print_environment_summary() -> None:
    """Print a short runtime summary."""

    info = get_platform_info()

    print(f"  Python      : {info['python']}")
    print(f"  Platform    : {info['system']}")
    print(f"  Architecture: {info['machine']}")
    print(f"  Project     : {BASE_DIR}")
    print()


# ============================================================================
# APPLICATION ENTRY
# ============================================================================


def application_main(
    argv: Sequence[str] | None = None,
) -> int:
    """
    Main application lifecycle.

    Returns:
        Process exit code.
    """

    options = parse_arguments(argv)

    configure_logging(options)
    install_exception_hook()

    if options.debug or options.verbose:
        print_banner()
        print_environment_summary()

    assistant: object | None = None
    dashboard: object | None = None

    try:
        if options.check_only:
            result = perform_environment_check()

            print(result.message)

            return result.exit_code

        assistant, dashboard = startup(options)

        # ------------------------------------------------------------------
        # NO UI MODE
        # ------------------------------------------------------------------

        if options.no_ui:
            LOGGER.info(
                "AssistantX started in headless mode."
            )

            print(
                f"{APP_NAME} is running in headless mode."
            )

            # If the assistant provides its own run loop, use it.
            if assistant is not None:
                run_method = getattr(
                    assistant,
                    "run",
                    None,
                )

                if callable(run_method):
                    return run_object(assistant)

            return 0

        # ------------------------------------------------------------------
        # GUI MODE
        # ------------------------------------------------------------------

        if dashboard is not None:
            LOGGER.info("Starting AssistantX dashboard.")

            return run_object(dashboard)

        # ------------------------------------------------------------------
        # FALLBACK
        # ------------------------------------------------------------------

        if assistant is not None:
            LOGGER.info(
                "Dashboard unavailable; starting assistant core."
            )

            return run_object(assistant)

        LOGGER.warning(
            "No dashboard or assistant runtime is available."
        )

        print(
            f"{APP_NAME} started, but no runtime interface "
            "is currently configured."
        )

        return 0

    except KeyboardInterrupt:
        LOGGER.info("AssistantX stopped by user.")
        return 0

    except AssistantXError as exc:
        LOGGER.error(
            "AssistantX startup/runtime error: %s",
            exc,
        )

        if options.debug:
            traceback.print_exc()

        return 1

    except Exception as exc:
        LOGGER.exception(
            "Fatal AssistantX error: %s",
            exc,
        )

        if options.debug:
            traceback.print_exc()

        return 1

    finally:
        # Graceful shutdown order:
        # Dashboard -> Assistant
        shutdown_object(
            dashboard,
            "Dashboard",
        )

        shutdown_object(
            assistant,
            "Assistant",
        )

        LOGGER.info(
            "%s shutdown complete.",
            APP_NAME,
        )


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================


def main() -> int:
    """Public entry point used by launchers and console scripts."""

    return application_main()


# ============================================================================
# SCRIPT ENTRY
# ============================================================================


if __name__ == "__main__":
    raise SystemExit(main())

