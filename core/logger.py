"""
logger.py
=========
Centralized logging configuration for AssistantX.

Provides a single `setup_logging()` entry point (call once at startup)
plus a `get_logger(name)` helper that every other module should use
instead of calling `logging.getLogger` directly, so log formatting and
handlers stay consistent app-wide.

Features:
    - Rotating file handlers for assistant.log, error.log, debug.log.
    - Colorized console output (falls back gracefully if colorama is
      unavailable or the terminal doesn't support ANSI colors).
    - Separate error-only log file for quick triage.
    - Idempotent setup (safe to call multiple times).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
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

_CONFIGURED = False

_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",     # cyan
    logging.INFO: "\033[32m",      # green
    logging.WARNING: "\033[33m",   # yellow
    logging.ERROR: "\033[31m",     # red
    logging.CRITICAL: "\033[41m",  # red background
}
_RESET_COLOR = "\033[0m"


class ColorConsoleFormatter(logging.Formatter):
    """Formatter that adds ANSI colors to console output based on level."""

    def __init__(self, use_color: bool = True) -> None:
        super().__init__(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        self.use_color = use_color and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self.use_color:
            return message
        color = _LEVEL_COLORS.get(record.levelno, "")
        return f"{color}{message}{_RESET_COLOR}" if color else message


class OnlyLevelAndAbove(logging.Filter):
    """Filter that only allows records at or above a given level through."""

    def __init__(self, min_level: int) -> None:
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


def _make_rotating_file_handler(
    path: Path, level: int, formatter: logging.Formatter
) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        filename=str(path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def setup_logging(
    level: Optional[str] = None,
    console: bool = True,
    log_to_files: bool = True,
) -> None:
    """
    Configure the root logger for the whole application. Call this ONCE,
    as early as possible (typically from main.py / launcher.py / core/startup.py).

    Args:
        level: Root log level string ('DEBUG', 'INFO', 'WARNING', ...).
            Defaults to the LOG_LEVEL env var, or 'INFO'.
        console: Whether to attach a colorized stdout handler.
        log_to_files: Whether to attach rotating file handlers for
            assistant.log (INFO+), error.log (ERROR+), and debug.log
            (DEBUG+, only when the effective level is DEBUG).
    """
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger(__name__).debug("setup_logging() called again; ignoring.")
        return

    level_name = (level or get_env("LOG_LEVEL", default="INFO") or "INFO").upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove any pre-existing handlers (e.g. from a library import that
    # called logging.basicConfig() before us) so we own formatting fully.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    plain_formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    if console:
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(ColorConsoleFormatter())
        root_logger.addHandler(console_handler)

    if log_to_files:
        info_handler = _make_rotating_file_handler(ASSISTANT_LOG, logging.INFO, plain_formatter)
        root_logger.addHandler(info_handler)

        error_handler = _make_rotating_file_handler(ERROR_LOG, logging.ERROR, plain_formatter)
        root_logger.addHandler(error_handler)

        if numeric_level <= logging.DEBUG:
            debug_handler = _make_rotating_file_handler(DEBUG_LOG, logging.DEBUG, plain_formatter)
            root_logger.addHandler(debug_handler)

    # Quiet down noisy third-party libraries by default.
    for noisy in ("urllib3", "requests", "asyncio", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger(__name__).info(
        "Logging initialized (level=%s, console=%s, files=%s).",
        level_name, console, log_to_files,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Return a module-scoped logger. Ensures setup_logging() has run at
    least once with defaults, so individual modules never crash if they
    happen to import before main.py calls setup_logging() explicitly.
    """
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name)


def set_level(level: str) -> None:
    """Dynamically change the root logger's level at runtime (e.g. from Settings UI)."""
    numeric_level = getattr(logging, level.upper(), None)
    if numeric_level is None:
        raise ValueError(f"Invalid log level: {level}")
    logging.getLogger().setLevel(numeric_level)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.handlers.RotatingFileHandler
        ):
            handler.setLevel(numeric_level)
    get_logger(__name__).info("Log level changed to %s.", level.upper())
    