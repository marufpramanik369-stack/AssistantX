"""
core/logger.py — Production-Grade Centralized Logging System
==============================================================

Thread-safe, configurable logging infrastructure for AssistantX.

Responsibilities
----------------
- Central application logging
- Console logging with optional ANSI colors
- Rotating UTF-8 file logging
- Separate assistant / error / debug logs
- Runtime log-level changes
- Third-party logger noise reduction
- Safe repeated initialization / reconfiguration
- Diagnostics for dashboard/settings
- Startup / shutdown helpers
- Exception logging helpers

Logging flow
------------

    Application
        │
        ▼
    Root Logger
        ├── Console Handler
        ├── assistant.log
        ├── error.log
        └── debug.log (when DEBUG is active)

The module intentionally keeps logging independent from AssistantX business
logic so every package can safely use:

    from core.logger import get_logger

    logger = get_logger(__name__)

The logger is safe to use from multiple threads.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from typing import Optional

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

_CONFIG_LOCK = threading.RLock()
_CONFIGURED = False

_ROOT_LOGGER_NAME = "AssistantX"

_SUPPORTED_LEVELS = frozenset(
    {
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    }
)

_DEFAULT_LOG_LEVEL = logging.INFO

# Third-party libraries which can become excessively verbose.
_NOISY_LOGGERS: dict[str, int] = {
    "urllib3": logging.WARNING,
    "requests": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "asyncio": logging.WARNING,
    "PIL": logging.WARNING,
    "PIL.PngImagePlugin": logging.WARNING,
    "google": logging.WARNING,
    "googleapiclient": logging.WARNING,
    "grpc": logging.WARNING,
    "grpc._cython.cygrpc": logging.WARNING,
}

# ANSI colors.
_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[36m",       # Cyan
    logging.INFO: "\033[32m",        # Green
    logging.WARNING: "\033[33m",     # Yellow
    logging.ERROR: "\033[31m",       # Red
    logging.CRITICAL: "\033[1;31m",  # Bold red
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
# Filters
# ============================================================================


class MinimumLevelFilter(logging.Filter):
    """
    Allow records at or above a minimum level.

    Example
    -------
    >>> handler.addFilter(MinimumLevelFilter(logging.ERROR))
    """

    def __init__(self, min_level: int) -> None:
        super().__init__()
        self.min_level = _validate_numeric_level(min_level)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


class MaximumLevelFilter(logging.Filter):
    """
    Allow records strictly below a maximum level.

    Example
    -------
    >>> handler.addFilter(MaximumLevelFilter(logging.ERROR))
    """

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = _validate_numeric_level(max_level)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level


# ============================================================================
# Console Formatter
# ============================================================================


class ColorConsoleFormatter(logging.Formatter):
    """
    Console formatter with automatic ANSI color detection.

    Color is disabled when:
    - NO_COLOR is set
    - TERM=dumb
    - stdout is not interactive
    - the environment does not safely support ANSI output
    """

    def __init__(self, use_color: bool = True) -> None:
        super().__init__(
            fmt=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
        )

        self.use_color = bool(use_color and _supports_color())

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)

        if not self.use_color:
            return message

        color = _LEVEL_COLORS.get(record.levelno)

        if not color:
            return message

        return f"{color}{message}{_RESET_COLOR}"


# ============================================================================
# Utility Functions
# ============================================================================


def _validate_numeric_level(level: int) -> int:
    """Validate and return a supported numeric logging level."""

    if isinstance(level, bool):
        raise InvalidLogLevelError(
            f"Invalid numeric log level: {level!r}"
        )

    if not isinstance(level, int):
        raise InvalidLogLevelError(
            f"Log level must be an integer, got {type(level).__name__}"
        )

    if level not in _SUPPORTED_LEVELS:
        raise InvalidLogLevelError(
            "Invalid numeric log level "
            f"(expected one of {sorted(_SUPPORTED_LEVELS)}, got {level})"
        )

    return level


def _supports_color() -> bool:
    """
    Determine whether ANSI console colors should be enabled.

    Returns
    -------
    bool
        True when stdout appears to support ANSI colors.
    """

    if os.environ.get("NO_COLOR") is not None:
        return False

    if os.environ.get("TERM", "").lower() == "dumb":
        return False

    stream = sys.stdout

    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError):
        return False

    if sys.platform != "win32":
        return True

    # Modern Windows terminals.
    if os.environ.get("WT_SESSION"):
        return True

    if os.environ.get("ANSICON"):
        return True

    if os.environ.get("TERM_PROGRAM"):
        return True

    # Windows console on modern Python/Windows generally supports ANSI.
    return True


def _resolve_level(level: Optional[str | int]) -> int:
    """
    Resolve a logging level from string, integer, or None.

    Supported names:
        DEBUG
        INFO
        WARNING
        ERROR
        CRITICAL
    """

    if level is None:
        return _DEFAULT_LOG_LEVEL

    if isinstance(level, bool):
        raise InvalidLogLevelError(
            f"Invalid log level: {level!r}"
        )

    if isinstance(level, int):
        return _validate_numeric_level(level)

    if not isinstance(level, str):
        raise InvalidLogLevelError(
            "Log level must be str, int, or None "
            f"(got {type(level).__name__})"
        )

    normalized = level.strip().upper()

    # Accept common aliases.
    aliases = {
        "WARN": "WARNING",
        "FATAL": "CRITICAL",
    }

    normalized = aliases.get(normalized, normalized)

    numeric_level = logging._nameToLevel.get(normalized)

    if numeric_level not in _SUPPORTED_LEVELS:
        raise InvalidLogLevelError(
            f"Invalid log level '{level}'. "
            "Expected DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )

    return int(numeric_level)


def _level_name(level: int) -> str:
    """Return a normalized human-readable level name."""

    name = logging.getLevelName(level)

    if isinstance(name, str):
        return name.upper()

    return str(level)


def _ensure_parent_directory(path: Path) -> None:
    """Create the parent directory for a log file."""

    path = Path(path)

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise LoggerError(
            f"Could not create log directory '{path.parent}': {exc}"
        ) from exc


def _is_file_handler(handler: logging.Handler) -> bool:
    """Return True when handler is a rotating file handler."""

    return isinstance(
        handler,
        logging.handlers.RotatingFileHandler,
    )


def _is_console_handler(handler: logging.Handler) -> bool:
    """
    Return True when handler is a console stream handler.

    File handlers are excluded because RotatingFileHandler is also a
    StreamHandler subclass.
    """

    return (
        isinstance(handler, logging.StreamHandler)
        and not _is_file_handler(handler)
    )


# ============================================================================
# Formatter Factories
# ============================================================================


def _create_file_formatter() -> logging.Formatter:
    """Create the standard non-colored file formatter."""

    return logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )


def _create_console_formatter() -> ColorConsoleFormatter:
    """Create the automatic-color console formatter."""

    return ColorConsoleFormatter(use_color=True)


# ============================================================================
# Handler Factories
# ============================================================================


def _make_rotating_file_handler(
    path: Path,
    level: int,
    formatter: logging.Formatter,
    *,
    filter_obj: Optional[logging.Filter] = None,
) -> logging.handlers.RotatingFileHandler:
    """
    Create a UTF-8 rotating file handler.

    Parameters
    ----------
    path:
        Destination log file.
    level:
        Minimum handler level.
    formatter:
        Formatter instance.
    filter_obj:
        Optional additional filter.
    """

    path = Path(path)

    _ensure_parent_directory(path)

    numeric_level = _validate_numeric_level(level)

    try:
        handler = logging.handlers.RotatingFileHandler(
            filename=str(path),
            maxBytes=max(1, int(LOG_MAX_BYTES)),
            backupCount=max(0, int(LOG_BACKUP_COUNT)),
            encoding="utf-8",
            delay=True,
        )
    except (OSError, ValueError) as exc:
        raise LoggerError(
            f"Could not create log file handler for '{path}': {exc}"
        ) from exc

    handler.setLevel(numeric_level)
    handler.setFormatter(formatter)

    if filter_obj is not None:
        handler.addFilter(filter_obj)

    return handler


def _make_console_handler(
    level: int,
) -> logging.StreamHandler:
    """Create the stdout console handler."""

    numeric_level = _validate_numeric_level(level)

    handler = logging.StreamHandler(
        stream=sys.stdout,
    )

    handler.setLevel(numeric_level)
    handler.setFormatter(_create_console_formatter())

    return handler


# ============================================================================
# Handler Management
# ============================================================================


def _close_handlers(logger: logging.Logger) -> None:
    """
    Flush, close, and remove every handler from a logger.

    Cleanup errors are intentionally suppressed so one broken handler does
    not prevent other handlers from being closed.
    """

    for handler in list(logger.handlers):
        try:
            handler.flush()
        except Exception:
            pass

        try:
            handler.close()
        except Exception:
            pass

        try:
            logger.removeHandler(handler)
        except Exception:
            pass


def _remove_assistant_handlers(
    logger: logging.Logger,
) -> None:
    """
    Remove handlers created by AssistantX logging.

    This is useful when another library installed its own root handler.
    Only handlers marked by this module are removed.
    """

    for handler in list(logger.handlers):
        if getattr(handler, "_assistantx_handler", False):
            try:
                handler.flush()
            except Exception:
                pass

            try:
                handler.close()
            except Exception:
                pass

            try:
                logger.removeHandler(handler)
            except Exception:
                pass


def _mark_assistantx_handler(
    handler: logging.Handler,
    handler_name: str,
) -> logging.Handler:
    """Mark a handler as owned by AssistantX."""

    setattr(handler, "_assistantx_handler", True)
    setattr(handler, "_assistantx_handler_name", handler_name)

    return handler


# ============================================================================
# Third-Party Logging
# ============================================================================


def _configure_third_party_loggers() -> None:
    """
    Reduce noisy third-party logging.

    These logger levels are intentionally conservative so warnings/errors
    from dependencies remain visible.
    """

    for name, level in _NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(level)


# ============================================================================
# Main Setup
# ============================================================================


def setup_logging(
    level: Optional[str | int] = None,
    *,
    console: bool = True,
    log_to_files: bool = True,
    force: bool = False,
) -> None:
    """
    Initialize or reconfigure AssistantX logging.

    Parameters
    ----------
    level:
        DEBUG / INFO / WARNING / ERROR / CRITICAL.
        When None, LOG_LEVEL from environment is used.

    console:
        Enable console logging.

    log_to_files:
        Enable rotating file logging.

    force:
        Force reconfiguration even when already configured.
    """

    global _CONFIGURED

    with _CONFIG_LOCK:

        if _CONFIGURED and not force:
            return

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

        # Remove only AssistantX-owned handlers.
        #
        # We deliberately do not blindly destroy handlers installed by
        # embedding applications, test runners, IDEs, or other libraries.
        _remove_assistant_handlers(root_logger)

        root_logger.setLevel(numeric_level)

        file_formatter = _create_file_formatter()

        # ------------------------------------------------------------------
        # Console
        # ------------------------------------------------------------------

        if console:
            console_handler = _make_console_handler(
                numeric_level
            )

            _mark_assistantx_handler(
                console_handler,
                "console",
            )

            root_logger.addHandler(
                console_handler
            )

        # ------------------------------------------------------------------
        # General Assistant Log
        # ------------------------------------------------------------------

        if log_to_files:

            assistant_handler = _make_rotating_file_handler(
                Path(ASSISTANT_LOG),
                logging.INFO,
                file_formatter,
            )

            _mark_assistantx_handler(
                assistant_handler,
                "assistant",
            )

            root_logger.addHandler(
                assistant_handler
            )

            # --------------------------------------------------------------
            # Error Log
            # --------------------------------------------------------------

            error_handler = _make_rotating_file_handler(
                Path(ERROR_LOG),
                logging.ERROR,
                file_formatter,
                filter_obj=MinimumLevelFilter(
                    logging.ERROR
                ),
            )

            _mark_assistantx_handler(
                error_handler,
                "error",
            )

            root_logger.addHandler(
                error_handler
            )

            # --------------------------------------------------------------
            # Debug Log
            # --------------------------------------------------------------

            if numeric_level <= logging.DEBUG:

                debug_handler = _make_rotating_file_handler(
                    Path(DEBUG_LOG),
                    logging.DEBUG,
                    file_formatter,
                )

                _mark_assistantx_handler(
                    debug_handler,
                    "debug",
                )

                root_logger.addHandler(
                    debug_handler
                )

        _configure_third_party_loggers()

        _CONFIGURED = True

        app_logger = logging.getLogger(
            _ROOT_LOGGER_NAME
        )

        app_logger.info(
            "Logging initialized "
            "(level=%s, console=%s, files=%s)",
            _level_name(numeric_level),
            console,
            log_to_files,
        )


# ============================================================================
# Logger Access
# ============================================================================


def get_logger(
    name: Optional[str] = None,
) -> logging.Logger:
    """
    Return an AssistantX logger.

    Logging is automatically initialized on first use.
    """

    if not _CONFIGURED:
        setup_logging()

    if name is None or not str(name).strip():
        return logging.getLogger(
            _ROOT_LOGGER_NAME
        )

    return logging.getLogger(
        str(name).strip()
    )


# ============================================================================
# Runtime Configuration
# ============================================================================


def set_level(level: str | int) -> None:
    """
    Change the application logging level at runtime.

    Root logger and console handler are updated.

    File handlers retain their intended responsibilities:
        assistant.log -> INFO+
        error.log     -> ERROR+
        debug.log     -> DEBUG+
    """

    numeric_level = _resolve_level(level)

    with _CONFIG_LOCK:

        root_logger = logging.getLogger()

        root_logger.setLevel(
            numeric_level
        )

        for handler in root_logger.handlers:

            if _is_console_handler(handler):
                handler.setLevel(
                    numeric_level
                )

        # Debug file is useful only when DEBUG is enabled.
        #
        # If logging was initialized without a debug handler, create it
        # dynamically when switching to DEBUG.
        debug_handler_exists = any(
            getattr(
                handler,
                "_assistantx_handler_name",
                None,
            )
            == "debug"
            for handler in root_logger.handlers
        )

        if (
            numeric_level <= logging.DEBUG
            and _CONFIGURED
            and not debug_handler_exists
        ):
            debug_handler = _make_rotating_file_handler(
                Path(DEBUG_LOG),
                logging.DEBUG,
                _create_file_formatter(),
            )

            _mark_assistantx_handler(
                debug_handler,
                "debug",
            )

            root_logger.addHandler(
                debug_handler
            )

        logging.getLogger(
            _ROOT_LOGGER_NAME
        ).info(
            "Log level changed to %s",
            _level_name(numeric_level),
        )


def get_level() -> str:
    """Return the current root logger level name."""

    return _level_name(
        logging.getLogger().level
    )


# ============================================================================
# Convenience Helpers
# ============================================================================


def log_exception(
    message: str,
    *,
    logger: Optional[logging.Logger] = None,
) -> None:
    """
    Log the current exception with traceback.

    Intended for use inside an except block.
    """

    target = (
        logger
        if logger is not None
        else get_logger(__name__)
    )

    target.exception(
        str(message)
    )


def log_startup(message: str) -> None:
    """Log a startup event."""

    get_logger(
        _ROOT_LOGGER_NAME
    ).info(
        "[STARTUP] %s",
        str(message),
    )


def log_shutdown(message: str) -> None:
    """Log a shutdown event."""

    get_logger(
        _ROOT_LOGGER_NAME
    ).info(
        "[SHUTDOWN] %s",
        str(message),
    )


# ============================================================================
# Diagnostics
# ============================================================================


def is_configured() -> bool:
    """Return whether AssistantX logging has been configured."""

    return _CONFIGURED


def get_log_files() -> dict[str, Path]:
    """Return configured AssistantX log file paths."""

    return {
        "assistant": Path(ASSISTANT_LOG),
        "error": Path(ERROR_LOG),
        "debug": Path(DEBUG_LOG),
    }


def diagnostics() -> dict[str, object]:
    """
    Return a complete logging diagnostics snapshot.

    Suitable for:
        - Settings UI
        - Dashboard
        - startup diagnostics
        - troubleshooting
    """

    root_logger = logging.getLogger()

    handlers: list[dict[str, object]] = []

    for handler in root_logger.handlers:

        info: dict[str, object] = {
            "type": type(handler).__name__,
            "level": _level_name(
                handler.level
            ),
            "assistantx_owned": bool(
                getattr(
                    handler,
                    "_assistantx_handler",
                    False,
                )
            ),
        }

        handler_name = getattr(
            handler,
            "_assistantx_handler_name",
            None,
        )

        if handler_name:
            info["name"] = handler_name

        if _is_file_handler(handler):
            info["file"] = handler.baseFilename

        if _is_console_handler(handler):
            info["stream"] = (
                getattr(
                    handler.stream,
                    "name",
                    None,
                )
                or "stdout"
            )

        handlers.append(info)

    log_files = get_log_files()

    files: dict[str, dict[str, object]] = {}

    for name, path in log_files.items():

        file_info: dict[str, object] = {
            "path": str(path),
            "exists": path.exists(),
        }

        if path.exists():

            try:
                file_info["size_bytes"] = path.stat().st_size
            except OSError:
                file_info["size_bytes"] = None

        else:
            file_info["size_bytes"] = 0

        files[name] = file_info

    return {
        "module": __name__,
        "configured": _CONFIGURED,
        "root_level": _level_name(
            root_logger.level
        ),
        "handler_count": len(
            root_logger.handlers
        ),
        "assistantx_handler_count": sum(
            1
            for handler in root_logger.handlers
            if getattr(
                handler,
                "_assistantx_handler",
                False,
            )
        ),
        "handlers": handlers,
        "files": files,
        "console_color": _supports_color(),
        "max_bytes": int(LOG_MAX_BYTES),
        "backup_count": int(LOG_BACKUP_COUNT),
        "third_party_logger_count": len(
            _NOISY_LOGGERS
        ),
    }


# ============================================================================
# Shutdown
# ============================================================================


def shutdown_logging() -> None:
    """
    Flush and close AssistantX-owned handlers.

    Does not destroy handlers belonging to an embedding application.
    """

    global _CONFIGURED

    with _CONFIG_LOCK:

        root_logger = logging.getLogger()

        if _CONFIGURED:
            root_logger.info(
                "Shutting down logging system"
            )

        _remove_assistant_handlers(
            root_logger
        )

        _CONFIGURED = False


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Formatter
    "ColorConsoleFormatter",

    # Filters
    "MinimumLevelFilter",
    "MaximumLevelFilter",

    # Exceptions
    "LoggerError",
    "InvalidLogLevelError",

    # Setup / access
    "setup_logging",
    "get_logger",
    "shutdown_logging",

    # Runtime control
    "set_level",
    "get_level",

    # Helpers
    "log_exception",
    "log_startup",
    "log_shutdown",

    # Diagnostics
    "is_configured",
    "get_log_files",
    "diagnostics",
]
