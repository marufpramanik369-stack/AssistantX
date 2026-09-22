"""
core/logger.py
==============

Centralized production-grade logging system for AssistantX.

Responsibilities
----------------
- Configure application-wide logging.
- Provide consistent console/file formatting.
- Manage rotating log files.
- Separate normal and error logs.
- Support runtime log-level changes.
- Reduce noisy third-party logs.
- Remain safe to initialize multiple times.
- Provide diagnostics and shutdown helpers.

Usage
-----
    from core.logger import get_logger

    logger = get_logger(__name__)

    logger.info("AssistantX started.")
    logger.warning("Something looks unusual.")
    logger.error("Something failed.")

Startup
-------
    from core.logger import setup_logging

    setup_logging()

Log files
---------
    assistant.log  -> INFO+
    error.log      -> ERROR+
    debug.log      -> DEBUG+

The actual paths are controlled by config.constants.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from config.constants import (
    ASSISTANT_LOG,
    DEBUG_LOG,
    ERROR_LOG,
    LOG_BACKUP_COUNT,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)
from config.env_loader import get_env

# ============================================================================
# Module State
# ============================================================================

_CONFIGURED = False
_CONFIG_LOCK = threading.RLock()

_ROOT_LOGGER_NAME = "AssistantX"

_DEFAULT_LOG_LEVEL = logging.INFO

_NOISY_LOGGERS = {
    "urllib3": logging.WARNING,
    "requests": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "asyncio": logging.WARNING,
    "PIL": logging.WARNING,
    "PIL.PngImagePlugin": logging.WARNING,
    "google": logging.WARNING,
    "googleapiclient": logging.WARNING,
}

# Console colors.
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",       # Cyan
    logging.INFO: "\033[32m",        # Green
    logging.WARNING: "\033[33m",     # Yellow
    logging.ERROR: "\033[31m",       # Red
    logging.CRITICAL: "\033[1;41m",  # Bold red background
}

_RESET_COLOR = "\033[0m"


# ============================================================================
# Exceptions
# ============================================================================


class LoggerError(Exception):
    """Base exception for AssistantX logging errors."""


class InvalidLogLevelError(LoggerError):
    """Raised when an invalid logging level is requested."""


# ============================================================================
# Custom Filters
# ============================================================================


class MinimumLevelFilter(logging.Filter):
    """
    Allow only records at or above a minimum log level.
    """

    def __init__(self, min_level: int) -> None:
        super().__init__()
        self.min_level = min_level

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        return record.levelno >= self.min_level


class MaximumLevelFilter(logging.Filter):
    """
    Allow only records below a maximum log level.

    Useful when a handler should receive INFO/WARNING but not ERROR.
    """

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        return record.levelno < self.max_level


# ============================================================================
# Console Formatter
# ============================================================================


class ColorConsoleFormatter(logging.Formatter):
    """
    Console formatter with optional ANSI colors.

    Colors are automatically disabled when stdout is not an interactive
    terminal, which keeps redirected logs and packaged applications clean.
    """

    def __init__(
        self,
        use_color: bool = True,
    ) -> None:

        super().__init__(
            fmt=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
        )

        self.use_color = (
            use_color
            and _supports_color()
        )

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:

        message = super().format(record)

        if not self.use_color:
            return message

        color = _LEVEL_COLORS.get(
            record.levelno,
            "",
        )

        if not color:
            return message

        return (
            f"{color}"
            f"{message}"
            f"{_RESET_COLOR}"
        )


# ============================================================================
# Utility Functions
# ============================================================================


def _supports_color() -> bool:
    """
    Detect whether the current console can safely handle ANSI colors.
    """

    if os.environ.get("NO_COLOR") is not None:
        return False

    if os.environ.get("TERM") == "dumb":
        return False

    stream = sys.stdout

    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError):
        return False

    # Windows 10+ and modern terminals generally support ANSI.
    if sys.platform == "win32":

        if os.environ.get("ANSICON"):
            return True

        if os.environ.get("WT_SESSION"):
            return True

        if os.environ.get("TERM_PROGRAM"):
            return True

        # Windows Terminal / modern Python terminals.
        return True

    return True


def _resolve_level(
    level: str | int | None,
) -> int:
    """
    Convert a logging level name/number to a numeric level.
    """

    if level is None:
        return _DEFAULT_LOG_LEVEL

    if isinstance(level, int):

        if level in {
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        }:
            return level

        raise InvalidLogLevelError(
            f"Invalid numeric log level: {level}"
        )

    level_name = str(level).strip().upper()

    numeric_level = getattr(
        logging,
        level_name,
        None,
    )

    if not isinstance(
        numeric_level,
        int,
    ):
        raise InvalidLogLevelError(
            f"Invalid log level: {level!r}"
        )

    return numeric_level


def _level_name(level: int) -> str:
    """Return human-readable logging level name."""

    return logging.getLevelName(level)


def _ensure_parent_directory(path: Path) -> None:
    """Ensure the log file's parent directory exists."""

    path = Path(path)

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise LoggerError(
            f"Could not create log directory: "
            f"{path.parent}"
        ) from exc


# ============================================================================
# Formatter Factory
# ============================================================================


def _create_file_formatter() -> logging.Formatter:
    """Create the standard file formatter."""

    return logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )


def _create_console_formatter() -> ColorConsoleFormatter:
    """Create the console formatter."""

    return ColorConsoleFormatter(
        use_color=True,
    )


# ============================================================================
# Handler Factory
# ============================================================================


def _make_rotating_file_handler(
    path: Path,
    level: int,
    formatter: logging.Formatter,
    *,
    filter_obj: logging.Filter | None = None,
) -> logging.Handler:
    """
    Create a UTF-8 rotating file handler.

    Args:
        path:
            Destination log file.

        level:
            Handler level.

        formatter:
            Log formatter.

        filter_obj:
            Optional additional filter.
    """

    path = Path(path)

    _ensure_parent_directory(path)

    handler = logging.handlers.RotatingFileHandler(
        filename=str(path),
        maxBytes=max(1, int(LOG_MAX_BYTES)),
        backupCount=max(0, int(LOG_BACKUP_COUNT)),
        encoding="utf-8",
        delay=True,
    )

    handler.setLevel(level)
    handler.setFormatter(formatter)

    if filter_obj is not None:
        handler.addFilter(filter_obj)

    return handler


def _make_console_handler(
    level: int,
) -> logging.Handler:
    """Create the stdout console handler."""

    handler = logging.StreamHandler(
        stream=sys.stdout,
    )

    handler.setLevel(level)

    handler.setFormatter(
        _create_console_formatter()
    )

    return handler


# ============================================================================
# Logger Cleanup
# ============================================================================


def _close_handlers(
    logger: logging.Logger,
) -> None:
    """
    Close and remove all handlers from a logger.
    """

    for handler in list(logger.handlers):

        try:
            handler.flush()
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).debug(
                "Failed to flush logging handler during cleanup: %s",
                exc,
            )

        try:
            handler.close()
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).debug(
                "Failed to close logging handler during cleanup: %s",
                exc,
            )

        logger.removeHandler(handler)


# ============================================================================
# Third-Party Logger Configuration
# ============================================================================


def _configure_third_party_loggers() -> None:
    """
    Reduce unnecessary third-party library noise.
    """

    for name, level in _NOISY_LOGGERS.items():

        logging.getLogger(name).setLevel(level)

    # Prevent noisy libraries from unexpectedly propagating
    # duplicate messages in certain configurations.
    logging.getLogger("PIL.PngImagePlugin").setLevel(
        logging.WARNING
    )


# ============================================================================
# Main Setup
# ============================================================================


def setup_logging(
    level: str | int | None = None,
    *,
    console: bool = True,
    log_to_files: bool = True,
    force: bool = False,
) -> None:
    """
    Configure AssistantX application logging.

    This function is safe to call multiple times.

    Args:
        level:
            Logging level such as DEBUG, INFO, WARNING, ERROR.

            If omitted:
                LOG_LEVEL environment variable is used.

        console:
            Enable console logging.

        log_to_files:
            Enable rotating file logs.

        force:
            Reconfigure logging even if it was already configured.
    """

    global _CONFIGURED

    with _CONFIG_LOCK:

        if _CONFIGURED and not force:

            logging.getLogger(
                _ROOT_LOGGER_NAME
            ).debug(
                "setup_logging() called again; "
                "existing configuration retained."
            )

            return

        # Environment fallback.
        configured_level = (
            level
            if level is not None
            else get_env(
                "LOG_LEVEL",
                default="INFO",
            )
        )

        numeric_level = _resolve_level(
            configured_level
        )

        root_logger = logging.getLogger()

        # Remove previous handlers if forcing or initializing
        # over a third-party logging configuration.
        _close_handlers(root_logger)

        root_logger.setLevel(
            numeric_level
        )

        file_formatter = _create_file_formatter()

        # --------------------------------------------------------------------
        # Console
        # --------------------------------------------------------------------

        if console:

            console_handler = _make_console_handler(
                numeric_level
            )

            root_logger.addHandler(
                console_handler
            )

        # --------------------------------------------------------------------
        # Assistant log
        # --------------------------------------------------------------------

        if log_to_files:

            assistant_handler = _make_rotating_file_handler(
                Path(ASSISTANT_LOG),
                logging.INFO,
                file_formatter,
            )

            root_logger.addHandler(
                assistant_handler
            )

            # ---------------------------------------------------------------
            # Error log
            # ---------------------------------------------------------------

            error_handler = _make_rotating_file_handler(
                Path(ERROR_LOG),
                logging.ERROR,
                file_formatter,
            )

            error_handler.addFilter(
                MinimumLevelFilter(
                    logging.ERROR
                )
            )

            root_logger.addHandler(
                error_handler
            )

            # ---------------------------------------------------------------
            # Debug log
            # ---------------------------------------------------------------

            if numeric_level <= logging.DEBUG:

                debug_handler = _make_rotating_file_handler(
                    Path(DEBUG_LOG),
                    logging.DEBUG,
                    file_formatter,
                )

                root_logger.addHandler(
                    debug_handler
                )

        _configure_third_party_loggers()

        _CONFIGURED = True

        logger = logging.getLogger(
            _ROOT_LOGGER_NAME
        )

        logger.info(
            "Logging initialized "
            "(level=%s, console=%s, files=%s).",
            _level_name(numeric_level),
            console,
            log_to_files,
        )


# ============================================================================
# Logger Access
# ============================================================================


def get_logger(
    name: str | None = None,
) -> logging.Logger:
    """
    Return a module-scoped logger.

    Example:
        logger = get_logger(__name__)

    If logging has not been configured yet, a default INFO configuration
    is initialized automatically.
    """

    if not _CONFIGURED:

        setup_logging()

    logger_name = (
        name
        if name
        else _ROOT_LOGGER_NAME
    )

    return logging.getLogger(
        logger_name
    )


# ============================================================================
# Runtime Configuration
# ============================================================================


def set_level(
    level: str | int,
) -> None:
    """
    Dynamically change the application/root logging level.

    This is useful for a Settings UI where the user can switch between
    DEBUG / INFO / WARNING / ERROR without restarting AssistantX.
    """

    numeric_level = _resolve_level(level)

    root_logger = logging.getLogger()

    root_logger.setLevel(
        numeric_level
    )

    # Update console handler only.
    # File handlers keep their own purpose-specific levels.
    for handler in root_logger.handlers:

        if isinstance(
            handler,
            logging.StreamHandler,
        ) and not isinstance(
            handler,
            logging.handlers.RotatingFileHandler,
        ):

            handler.setLevel(
                numeric_level
            )

    get_logger(
        _ROOT_LOGGER_NAME
    ).info(
        "Log level changed to %s.",
        _level_name(numeric_level),
    )


def get_level() -> str:
    """Return the current root logger level."""

    return _level_name(
        logging.getLogger().level
    )


# ============================================================================
# Convenience Logging Helpers
# ============================================================================


def log_exception(
    message: str,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """
    Log an exception with traceback information.

    Intended to be called inside an exception handler.

    Example:
        try:
            ...
        except Exception:
            log_exception("Failed to load settings.")
    """

    target = (
        logger
        if logger is not None
        else get_logger(__name__)
    )

    target.exception(
        str(message)
    )


def log_startup(
    message: str,
) -> None:
    """Log an AssistantX startup event."""

    get_logger(
        _ROOT_LOGGER_NAME
    ).info(
        "[STARTUP] %s",
        message,
    )


def log_shutdown(
    message: str,
) -> None:
    """Log an AssistantX shutdown event."""

    get_logger(
        _ROOT_LOGGER_NAME
    ).info(
        "[SHUTDOWN] %s",
        message,
    )


# ============================================================================
# Status / Diagnostics
# ============================================================================


def is_configured() -> bool:
    """Return whether logging has been initialized."""

    return _CONFIGURED


def get_log_files() -> dict[str, Path]:
    """Return configured log file locations."""

    return {
        "assistant": Path(ASSISTANT_LOG),
        "error": Path(ERROR_LOG),
        "debug": Path(DEBUG_LOG),
    }


def diagnostics() -> dict[str, object]:
    """
    Return logging diagnostics useful for debugging and Settings UI.
    """

    root_logger = logging.getLogger()

    handlers = []

    for handler in root_logger.handlers:

        handler_info: dict[str, object] = {
            "type": type(handler).__name__,
            "level": _level_name(
                handler.level
            ),
        }

        if isinstance(
            handler,
            logging.handlers.RotatingFileHandler,
        ):
            handler_info["file"] = handler.baseFilename

        handlers.append(
            handler_info
        )

    log_files = get_log_files()

    return {
        "configured": _CONFIGURED,
        "root_level": _level_name(
            root_logger.level
        ),
        "handler_count": len(
            root_logger.handlers
        ),
        "handlers": handlers,
        "files": {
            name: {
                "path": str(path),
                "exists": path.exists(),
            }
            for name, path in log_files.items()
        },
        "console_color": _supports_color(),
        "max_bytes": LOG_MAX_BYTES,
        "backup_count": LOG_BACKUP_COUNT,
    }


# ============================================================================
# Shutdown
# ============================================================================


def shutdown_logging() -> None:
    """
    Flush, close and remove all root logger handlers.

    Useful during application shutdown or controlled restart.
    """

    global _CONFIGURED

    with _CONFIG_LOCK:

        root_logger = logging.getLogger()

        root_logger.info(
            "Shutting down logging system."
        )

        _close_handlers(
            root_logger
        )

        _CONFIGURED = False


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Formatter
    "ColorConsoleFormatter",
    # Exceptions
    "InvalidLogLevelError",
    "LoggerError",
    # Filters
    "MaximumLevelFilter",
    "MinimumLevelFilter",
    "diagnostics",
    "get_level",
    "get_log_files",
    # Logger
    "get_logger",
    # Diagnostics
    "is_configured",
    # Helpers
    "log_exception",
    "log_shutdown",
    "log_startup",
    # Runtime configuration
    "set_level",
    # Setup
    "setup_logging",
    "shutdown_logging",
]
