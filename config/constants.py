"""
config/constants.py
===================

Centralized immutable constants for AssistantX.

Rules
-----
- Runtime-mutable values belong in `settings.py`.
- Secrets/API credentials belong in `secrets.py` / `.env`.
- No imports from other AssistantX modules.
- Standard-library imports only.
- Constants should not perform application startup work.
- Keep this module lightweight and safe to import from anywhere.

This module contains:
    • Application metadata
    • Platform information
    • Project paths
    • Environment variable names
    • AI provider defaults
    • Voice defaults
    • Dashboard/UI defaults
    • Logging defaults
    • Network/service defaults
    • Intent constants
    • File/runtime defaults
    • Validation limits
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

# ============================================================================
# Application Metadata
# ============================================================================

APP_NAME: Final[str] = "AssistantX"
APP_VERSION: Final[str] = "1.0.0"
APP_CODENAME: Final[str] = "Genesis"
APP_AUTHOR: Final[str] = "AssistantX Team"
APP_ORGANIZATION: Final[str] = "AssistantX"
APP_DESCRIPTION: Final[str] = (
    "A cross-platform, voice-driven personal AI assistant."
)
APP_LICENSE: Final[str] = "MIT"

# Semantic version tuple.
APP_VERSION_TUPLE: Final[tuple[int, int, int]] = tuple(
    int(part) for part in APP_VERSION.split(".")
)


# ============================================================================
# Platform
# ============================================================================

PLATFORM: Final[str] = sys.platform

IS_WINDOWS: Final[bool] = PLATFORM.startswith("win")
IS_LINUX: Final[bool] = PLATFORM.startswith("linux")
IS_MAC: Final[bool] = PLATFORM.startswith("darwin")
IS_POSIX: Final[bool] = not IS_WINDOWS

PLATFORM_NAME: Final[str] = (
    "windows"
    if IS_WINDOWS
    else "macos"
    if IS_MAC
    else "linux"
    if IS_LINUX
    else "unknown"
)


# ============================================================================
# Project Paths
# ============================================================================

# config/constants.py -> project root
BASE_DIR: Final[Path] = Path(__file__).resolve().parents[1]

# Assets
ASSETS_DIR: Final[Path] = BASE_DIR / "assets"
ICONS_DIR: Final[Path] = ASSETS_DIR / "icons"
IMAGES_DIR: Final[Path] = ASSETS_DIR / "images"
SOUNDS_DIR: Final[Path] = ASSETS_DIR / "sounds"
FONTS_DIR: Final[Path] = ASSETS_DIR / "fonts"
THEMES_DIR: Final[Path] = ASSETS_DIR / "themes"
ANIMATIONS_DIR: Final[Path] = ASSETS_DIR / "animations"

# Application modules/data
DATABASE_DIR: Final[Path] = BASE_DIR / "database"
DATA_DIR: Final[Path] = BASE_DIR / "data"
CACHE_DIR: Final[Path] = BASE_DIR / "cache"
LOGS_DIR: Final[Path] = BASE_DIR / "logs"
RESOURCES_DIR: Final[Path] = BASE_DIR / "resources"
PLUGINS_DIR: Final[Path] = BASE_DIR / "plugins"
DOCS_DIR: Final[Path] = BASE_DIR / "docs"

# Runtime cache directories
AI_CACHE_DIR: Final[Path] = CACHE_DIR / "ai"
IMAGE_CACHE_DIR: Final[Path] = CACHE_DIR / "images"
SEARCH_CACHE_DIR: Final[Path] = CACHE_DIR / "search"
TEMP_CACHE_DIR: Final[Path] = CACHE_DIR / "temp"

# Environment/config files
DOTENV_PATH: Final[Path] = BASE_DIR / ".env"
DOTENV_EXAMPLE_PATH: Final[Path] = BASE_DIR / ".env.example"

# Database
SQLITE_DB_PATH: Final[Path] = DATABASE_DIR / "assistantx.db"

# JSON data
HISTORY_JSON: Final[Path] = DATA_DIR / "history.json"
MEMORY_JSON: Final[Path] = DATA_DIR / "memory.json"
PROFILE_JSON: Final[Path] = DATA_DIR / "profile.json"
SETTINGS_JSON: Final[Path] = DATA_DIR / "settings.json"
TASKS_JSON: Final[Path] = DATA_DIR / "tasks.json"
COMMANDS_JSON: Final[Path] = DATA_DIR / "commands.json"
CACHE_JSON: Final[Path] = DATA_DIR / "cache.json"

# Logs
ASSISTANT_LOG: Final[Path] = LOGS_DIR / "assistant.log"
DEBUG_LOG: Final[Path] = LOGS_DIR / "debug.log"
ERROR_LOG: Final[Path] = LOGS_DIR / "error.log"


# ============================================================================
# Environment Variable Names
# ============================================================================

ENV_GEMINI_API_KEY: Final[str] = "GEMINI_API_KEY"
ENV_OPENWEATHER_API_KEY: Final[str] = "OPENWEATHER_API_KEY"
ENV_NEWSAPI_KEY: Final[str] = "NEWSAPI_KEY"
ENV_OLLAMA_HOST: Final[str] = "OLLAMA_HOST"

ENV_APP_ENV: Final[str] = "APP_ENV"
ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"

ENV_DEBUG: Final[str] = "ASSISTANTX_DEBUG"
ENV_LANGUAGE: Final[str] = "ASSISTANTX_LANGUAGE"
ENV_THEME: Final[str] = "ASSISTANTX_THEME"


# ============================================================================
# Application Environment
# ============================================================================

class AppEnvironment(StrEnum):
    """Supported AssistantX runtime environments."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


DEFAULT_APP_ENV: Final[AppEnvironment] = AppEnvironment.DEVELOPMENT


# ============================================================================
# AI Providers
# ============================================================================

class AIProvider(StrEnum):
    """Supported AI backend providers."""

    GEMINI = "gemini"
    OLLAMA = "ollama"
    LOCAL = "local"


DEFAULT_AI_PROVIDER: Final[AIProvider] = AIProvider.GEMINI

# Provider defaults
DEFAULT_GEMINI_MODEL: Final[str] = "gemini-1.5-flash"
DEFAULT_OLLAMA_MODEL: Final[str] = "llama3"
DEFAULT_OLLAMA_HOST: Final[str] = "http://localhost:11434"

# AI generation
MAX_CONTEXT_TOKENS: Final[int] = 8192
MAX_HISTORY_MESSAGES: Final[int] = 50

DEFAULT_TEMPERATURE: Final[float] = 0.7
DEFAULT_TOP_P: Final[float] = 0.9

MIN_TEMPERATURE: Final[float] = 0.0
MAX_TEMPERATURE: Final[float] = 2.0

MIN_TOP_P: Final[float] = 0.0
MAX_TOP_P: Final[float] = 1.0

# Networking/retry
REQUEST_TIMEOUT_SECONDS: Final[int] = 30
CONNECT_TIMEOUT_SECONDS: Final[int] = 10
READ_TIMEOUT_SECONDS: Final[int] = 30

MAX_RETRIES: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[float] = 1.5

# AI message limits
MAX_INPUT_CHARS: Final[int] = 20_000
MAX_OUTPUT_CHARS: Final[int] = 50_000
MAX_SYSTEM_PROMPT_CHARS: Final[int] = 30_000


# ============================================================================
# Voice System
# ============================================================================

class VoiceState(StrEnum):
    """Finite states of the AssistantX voice subsystem."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


DEFAULT_WAKE_WORD: Final[str] = "hey assistant"
WAKE_WORD_SENSITIVITY: Final[float] = 0.5

MIN_WAKE_WORD_SENSITIVITY: Final[float] = 0.0
MAX_WAKE_WORD_SENSITIVITY: Final[float] = 1.0

DEFAULT_LANGUAGE_CODE: Final[str] = "en-US"

SUPPORTED_LANGUAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "en-US": "English (US)",
        "en-GB": "English (UK)",
        "bn-BD": "Bangla (Bangladesh)",
        "hi-IN": "Hindi (India)",
    }
)

DEFAULT_TTS_LANGUAGE: Final[str] = "en-US"

SPEECH_RATE_WPM: Final[int] = 175
MIN_SPEECH_RATE_WPM: Final[int] = 80
MAX_SPEECH_RATE_WPM: Final[int] = 300

SPEECH_VOLUME: Final[float] = 1.0

MIN_SPEECH_VOLUME: Final[float] = 0.0
MAX_SPEECH_VOLUME: Final[float] = 1.0

MIC_SAMPLE_RATE: Final[int] = 16_000
MIC_CHANNELS: Final[int] = 1

SILENCE_THRESHOLD_SECONDS: Final[float] = 1.2
LISTEN_TIMEOUT_SECONDS: Final[int] = 8
PHRASE_TIME_LIMIT_SECONDS: Final[int] = 15


# ============================================================================
# Dashboard / UI
# ============================================================================

class ThemeMode(StrEnum):
    """Available dashboard theme modes."""

    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


DEFAULT_THEME: Final[ThemeMode] = ThemeMode.DARK

# Window
DEFAULT_WINDOW_WIDTH: Final[int] = 1100
DEFAULT_WINDOW_HEIGHT: Final[int] = 720

MIN_WINDOW_WIDTH: Final[int] = 780
MIN_WINDOW_HEIGHT: Final[int] = 520

MAX_WINDOW_WIDTH: Final[int] = 3840
MAX_WINDOW_HEIGHT: Final[int] = 2160

# Splash
SPLASH_DURATION_MS: Final[int] = 2200

# Chat
CHAT_BUBBLE_MAX_WIDTH_RATIO: Final[float] = 0.72
CHAT_INPUT_MAX_LENGTH: Final[int] = 10_000
CHAT_HISTORY_PAGE_SIZE: Final[int] = 50

# Typing/animation
TYPING_INDICATOR_INTERVAL_MS: Final[int] = 350
ANIMATION_FPS: Final[int] = 60

# Sidebar
SIDEBAR_WIDTH: Final[int] = 260
SIDEBAR_COLLAPSED_WIDTH: Final[int] = 64

# UI scaling
DEFAULT_UI_SCALE: Final[float] = 1.0
MIN_UI_SCALE: Final[float] = 0.75
MAX_UI_SCALE: Final[float] = 2.0


# ============================================================================
# Logging
# ============================================================================

LOG_FORMAT: Final[str] = (
    "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
)

LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

DEFAULT_LOG_LEVEL: Final[str] = "INFO"

SUPPORTED_LOG_LEVELS: Final[tuple[str, ...]] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)

LOG_MAX_BYTES: Final[int] = 5 * 1024 * 1024
LOG_BACKUP_COUNT: Final[int] = 5

LOG_ENCODING: Final[str] = "utf-8"


# ============================================================================
# Networking / Web Services
# ============================================================================

HTTP_USER_AGENT: Final[str] = f"{APP_NAME}/{APP_VERSION}"

HTTP_DEFAULT_TIMEOUT: Final[int] = 30
HTTP_MAX_REDIRECTS: Final[int] = 5

DEFAULT_SEARCH_RESULTS_LIMIT: Final[int] = 5
MAX_SEARCH_RESULTS_LIMIT: Final[int] = 20

WEATHER_UNITS: Final[str] = "metric"
NEWS_LANGUAGE: Final[str] = "en"
NEWS_PAGE_SIZE: Final[int] = 10

WIKIPEDIA_SENTENCES: Final[int] = 3
TRANSLATE_DEFAULT_TARGET: Final[str] = "en"


# ============================================================================
# Commands / Intents
# ============================================================================

class IntentCategory(StrEnum):
    """Top-level intent categories used by AssistantX Brain."""

    GENERAL_CHAT = "general_chat"
    SYSTEM_CONTROL = "system_control"
    APP_LAUNCH = "app_launch"
    WEB_SEARCH = "web_search"
    WEATHER = "weather"
    NEWS = "news"
    REMINDER = "reminder"
    MUSIC = "music"
    FILE_OPERATION = "file_operation"
    CALCULATION = "calculation"
    UNKNOWN = "unknown"


EXIT_KEYWORDS: Final[tuple[str, ...]] = (
    "exit",
    "quit",
    "goodbye",
    "bye",
    "shutdown",
)

CONFIRMATION_KEYWORDS: Final[tuple[str, ...]] = (
    "yes",
    "yeah",
    "sure",
    "ok",
    "okay",
    "confirm",
)

NEGATION_KEYWORDS: Final[tuple[str, ...]] = (
    "no",
    "nope",
    "cancel",
    "never mind",
)


# ============================================================================
# Scheduler
# ============================================================================

DEFAULT_SCHEDULER_POLL_INTERVAL: Final[float] = 0.5
MAX_SCHEDULED_TASKS: Final[int] = 1_000

DEFAULT_TASK_TIMEOUT_SECONDS: Final[int] = 300

MIN_RECURRING_INTERVAL_SECONDS: Final[float] = 1.0


# ============================================================================
# File / Storage
# ============================================================================

DEFAULT_ENCODING: Final[str] = "utf-8"

JSON_INDENT: Final[int] = 2

MAX_HISTORY_SESSIONS: Final[int] = 100
MAX_MEMORY_ENTRIES: Final[int] = 5_000

MAX_FILE_NAME_LENGTH: Final[int] = 255
MAX_PATH_LENGTH: Final[int] = 4_096

BACKUP_FILE_SUFFIX: Final[str] = ".bak"


# ============================================================================
# Cache
# ============================================================================

CACHE_TTL_SECONDS: Final[int] = 3600

AI_CACHE_TTL_SECONDS: Final[int] = 86_400
SEARCH_CACHE_TTL_SECONDS: Final[int] = 1_800
IMAGE_CACHE_TTL_SECONDS: Final[int] = 86_400

MAX_CACHE_SIZE_MB: Final[int] = 512


# ============================================================================
# Date / Time
# ============================================================================

DATE_DISPLAY_FORMAT: Final[str] = "%A, %d %B %Y"
TIME_DISPLAY_FORMAT: Final[str] = "%I:%M %p"

DATETIME_DISPLAY_FORMAT: Final[str] = (
    "%A, %d %B %Y • %I:%M %p"
)


# ============================================================================
# Notifications
# ============================================================================

DEFAULT_NOTIFICATION_DURATION_MS: Final[int] = 4_000

NOTIFICATION_MAX_TITLE_LENGTH: Final[int] = 100
NOTIFICATION_MAX_MESSAGE_LENGTH: Final[int] = 500


# ============================================================================
# Security / Safety Limits
# ============================================================================

MAX_COMMAND_LENGTH: Final[int] = 10_000
MAX_URL_LENGTH: Final[int] = 4_096

MAX_PLUGIN_NAME_LENGTH: Final[int] = 100
MAX_PLUGIN_DESCRIPTION_LENGTH: Final[int] = 500

# Never store secrets in constants.py.
SECRET_MASK: Final[str] = "********"


# ============================================================================
# Application Files
# ============================================================================

ICON_FILE: Final[Path] = ICONS_DIR / "icon.ico"
APP_LOGO_FILE: Final[Path] = IMAGES_DIR / "logo.png"
SPLASH_IMAGE_FILE: Final[Path] = IMAGES_DIR / "splash.png"
AVATAR_FILE: Final[Path] = IMAGES_DIR / "avatar.png"

DARK_THEME_FILE: Final[Path] = THEMES_DIR / "dark.json"
LIGHT_THEME_FILE: Final[Path] = THEMES_DIR / "light.json"


# ============================================================================
# Feature Identifiers
# ============================================================================

class Feature(StrEnum):
    """Stable feature identifiers used across AssistantX."""

    CHAT = "chat"
    VOICE = "voice"
    WEB_SEARCH = "web_search"
    WEATHER = "weather"
    NEWS = "news"
    REMINDERS = "reminders"
    AUTOMATION = "automation"
    MEMORY = "memory"
    HISTORY = "history"
    PLUGINS = "plugins"
    DASHBOARD = "dashboard"


DEFAULT_FEATURES: Final[Mapping[str, bool]] = MappingProxyType(
    {
        Feature.CHAT: True,
        Feature.VOICE: True,
        Feature.WEB_SEARCH: True,
        Feature.WEATHER: True,
        Feature.NEWS: True,
        Feature.REMINDERS: True,
        Feature.AUTOMATION: True,
        Feature.MEMORY: True,
        Feature.HISTORY: True,
        Feature.PLUGINS: True,
        Feature.DASHBOARD: True,
    }
)


# ============================================================================
# Runtime Defaults
# ============================================================================

DEFAULT_MAX_MEMORY_CONTEXT: Final[int] = 10
DEFAULT_MAX_HISTORY_CONTEXT: Final[int] = 20

DEFAULT_CONFIRMATION_TIMEOUT_SECONDS: Final[int] = 30
DEFAULT_CLARIFICATION_TIMEOUT_SECONDS: Final[int] = 60


# ============================================================================
# Compatibility Aliases
# ============================================================================

# Keep these aliases so existing modules can continue working if they use
# older naming conventions.

PROJECT_ROOT: Final[Path] = BASE_DIR
ROOT_DIR: Final[Path] = BASE_DIR

DB_PATH: Final[Path] = SQLITE_DB_PATH

LOG_DIR: Final[Path] = LOGS_DIR

DEFAULT_PROVIDER: Final[AIProvider] = DEFAULT_AI_PROVIDER

DEFAULT_MODEL: Final[str] = DEFAULT_GEMINI_MODEL

LANGUAGE_CODES: Final[Mapping[str, str]] = SUPPORTED_LANGUAGES


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "AI_CACHE_DIR",
    "AI_CACHE_TTL_SECONDS",
    "ANIMATIONS_DIR",
    "ANIMATION_FPS",
    "APP_AUTHOR",
    "APP_CODENAME",
    "APP_DESCRIPTION",
    "APP_LICENSE",
    "APP_LOGO_FILE",
    # Application
    "APP_NAME",
    "APP_ORGANIZATION",
    "APP_VERSION",
    "APP_VERSION_TUPLE",
    "ASSETS_DIR",
    "ASSISTANT_LOG",
    "AVATAR_FILE",
    "BACKUP_FILE_SUFFIX",
    # Paths
    "BASE_DIR",
    "CACHE_DIR",
    "CACHE_JSON",
    # Cache
    "CACHE_TTL_SECONDS",
    "CHAT_BUBBLE_MAX_WIDTH_RATIO",
    "CHAT_HISTORY_PAGE_SIZE",
    "CHAT_INPUT_MAX_LENGTH",
    "COMMANDS_JSON",
    "CONFIRMATION_KEYWORDS",
    "CONNECT_TIMEOUT_SECONDS",
    "DARK_THEME_FILE",
    "DATABASE_DIR",
    "DATA_DIR",
    "DATETIME_DISPLAY_FORMAT",
    # Date/time
    "DATE_DISPLAY_FORMAT",
    "DB_PATH",
    "DEBUG_LOG",
    "DEFAULT_AI_PROVIDER",
    "DEFAULT_APP_ENV",
    "DEFAULT_CLARIFICATION_TIMEOUT_SECONDS",
    "DEFAULT_CONFIRMATION_TIMEOUT_SECONDS",
    # Storage
    "DEFAULT_ENCODING",
    "DEFAULT_FEATURES",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_LANGUAGE_CODE",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_MAX_HISTORY_CONTEXT",
    # Runtime
    "DEFAULT_MAX_MEMORY_CONTEXT",
    "DEFAULT_MODEL",
    # Notifications
    "DEFAULT_NOTIFICATION_DURATION_MS",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_PROVIDER",
    # Scheduler
    "DEFAULT_SCHEDULER_POLL_INTERVAL",
    "DEFAULT_SEARCH_RESULTS_LIMIT",
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_THEME",
    "DEFAULT_TOP_P",
    "DEFAULT_TTS_LANGUAGE",
    "DEFAULT_UI_SCALE",
    "DEFAULT_WAKE_WORD",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_WIDTH",
    "DOCS_DIR",
    "DOTENV_EXAMPLE_PATH",
    # Files
    "DOTENV_PATH",
    "ENV_APP_ENV",
    "ENV_DEBUG",
    # Environment
    "ENV_GEMINI_API_KEY",
    "ENV_LANGUAGE",
    "ENV_LOG_LEVEL",
    "ENV_NEWSAPI_KEY",
    "ENV_OLLAMA_HOST",
    "ENV_OPENWEATHER_API_KEY",
    "ENV_THEME",
    "ERROR_LOG",
    "EXIT_KEYWORDS",
    "FONTS_DIR",
    "HISTORY_JSON",
    "HTTP_DEFAULT_TIMEOUT",
    "HTTP_MAX_REDIRECTS",
    # Networking
    "HTTP_USER_AGENT",
    "ICONS_DIR",
    # Assets
    "ICON_FILE",
    "IMAGES_DIR",
    "IMAGE_CACHE_DIR",
    "IMAGE_CACHE_TTL_SECONDS",
    "IS_LINUX",
    "IS_MAC",
    "IS_POSIX",
    "IS_WINDOWS",
    "JSON_INDENT",
    "LANGUAGE_CODES",
    "LIGHT_THEME_FILE",
    "LISTEN_TIMEOUT_SECONDS",
    "LOGS_DIR",
    "LOG_BACKUP_COUNT",
    "LOG_DATE_FORMAT",
    "LOG_DIR",
    "LOG_ENCODING",
    # Logging
    "LOG_FORMAT",
    "LOG_MAX_BYTES",
    "MAX_CACHE_SIZE_MB",
    # Security
    "MAX_COMMAND_LENGTH",
    "MAX_CONTEXT_TOKENS",
    "MAX_FILE_NAME_LENGTH",
    "MAX_HISTORY_MESSAGES",
    "MAX_HISTORY_SESSIONS",
    "MAX_INPUT_CHARS",
    "MAX_MEMORY_ENTRIES",
    "MAX_OUTPUT_CHARS",
    "MAX_PATH_LENGTH",
    "MAX_PLUGIN_DESCRIPTION_LENGTH",
    "MAX_PLUGIN_NAME_LENGTH",
    "MAX_RETRIES",
    "MAX_SCHEDULED_TASKS",
    "MAX_SEARCH_RESULTS_LIMIT",
    "MAX_SPEECH_RATE_WPM",
    "MAX_SPEECH_VOLUME",
    "MAX_SYSTEM_PROMPT_CHARS",
    "MAX_TEMPERATURE",
    "MAX_TOP_P",
    "MAX_UI_SCALE",
    "MAX_URL_LENGTH",
    "MAX_WAKE_WORD_SENSITIVITY",
    "MAX_WINDOW_HEIGHT",
    "MAX_WINDOW_WIDTH",
    "MEMORY_JSON",
    "MIC_CHANNELS",
    "MIC_SAMPLE_RATE",
    "MIN_RECURRING_INTERVAL_SECONDS",
    "MIN_SPEECH_RATE_WPM",
    "MIN_SPEECH_VOLUME",
    "MIN_TEMPERATURE",
    "MIN_TOP_P",
    "MIN_UI_SCALE",
    "MIN_WAKE_WORD_SENSITIVITY",
    "MIN_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "NEGATION_KEYWORDS",
    "NEWS_LANGUAGE",
    "NEWS_PAGE_SIZE",
    "NOTIFICATION_MAX_MESSAGE_LENGTH",
    "NOTIFICATION_MAX_TITLE_LENGTH",
    "PHRASE_TIME_LIMIT_SECONDS",
    # Platform
    "PLATFORM",
    "PLATFORM_NAME",
    "PLUGINS_DIR",
    "PROFILE_JSON",
    "PROJECT_ROOT",
    "READ_TIMEOUT_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "RESOURCES_DIR",
    "RETRY_BACKOFF_SECONDS",
    "ROOT_DIR",
    "SEARCH_CACHE_DIR",
    "SEARCH_CACHE_TTL_SECONDS",
    "SECRET_MASK",
    "SETTINGS_JSON",
    "SIDEBAR_COLLAPSED_WIDTH",
    "SIDEBAR_WIDTH",
    "SILENCE_THRESHOLD_SECONDS",
    "SOUNDS_DIR",
    "SPEECH_RATE_WPM",
    "SPEECH_VOLUME",
    "SPLASH_DURATION_MS",
    "SPLASH_IMAGE_FILE",
    "SQLITE_DB_PATH",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_LOG_LEVELS",
    "TASKS_JSON",
    "TEMP_CACHE_DIR",
    "THEMES_DIR",
    "TIME_DISPLAY_FORMAT",
    "TRANSLATE_DEFAULT_TARGET",
    "TYPING_INDICATOR_INTERVAL_MS",
    "WAKE_WORD_SENSITIVITY",
    "WEATHER_UNITS",
    "WIKIPEDIA_SENTENCES",
    # AI
    "AIProvider",
    # Environment
    "AppEnvironment",
    # Features
    "Feature",
    # Intents
    "IntentCategory",
    # UI
    "ThemeMode",
    # Voice
    "VoiceState",
]
