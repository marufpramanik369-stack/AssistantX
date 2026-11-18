"""
config/constants.py
===================

Centralized immutable constants for AssistantX.

Design rules
------------
- Runtime-mutable values belong in ``config/settings.py``.
- Secrets and credentials belong in ``config/secrets.py`` / ``.env``.
- This module must not import other AssistantX modules.
- Standard-library imports only.
- No startup work, I/O, network calls, or filesystem creation.
- Constants are safe to import from any AssistantX subsystem.

Core identity
-------------
AssistantX application:
    AssistantX

Assistant identity:
    Name         : JEROX
    Wake Word    : JEROX
    Voice Gender : Female (LOCKED)
    Languages    : Bengali, English, Hindi

Language may change at runtime, but the assistant's female voice identity
and wake-word identity must remain fixed.
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
    "A professional voice-driven personal AI assistant."
)

APP_LICENSE: Final[str] = "MIT"

APP_VERSION_TUPLE: Final[tuple[int, int, int]] = tuple(
    int(part) for part in APP_VERSION.split(".")
)


# ============================================================================
# Assistant Identity
# ============================================================================

# Public assistant name.
ASSISTANT_NAME: Final[str] = "JEROX"

# Canonical machine-readable wake word.
ASSISTANT_WAKE_WORD: Final[str] = "jerox"

# Human-readable wake name.
ASSISTANT_WAKE_NAME: Final[str] = "JEROX"

# ---------------------------------------------------------------------------
# Fixed voice identity
# ---------------------------------------------------------------------------
# These values define JEROX's identity.
# They are NOT runtime-configurable settings.

ASSISTANT_VOICE_GENDER: Final[str] = "female"
FIXED_VOICE_GENDER: Final[str] = "female"
VOICE_GENDER_LOCKED: Final[bool] = True

# ---------------------------------------------------------------------------
# Fixed wake-word identity
# ---------------------------------------------------------------------------

FIXED_WAKE_WORD: Final[str] = ASSISTANT_WAKE_WORD

WAKE_WORD_ALIASES: Final[tuple[str, ...]] = (
    "jerox",
    "jerox",
    "জেরক্স",
)

WAKE_WORD_LOCKED: Final[bool] = True


# ============================================================================
# Language Identity
# ============================================================================

SUPPORTED_LANGUAGE_CODES: Final[tuple[str, ...]] = (
    "bn",
    "en",
    "hi",
)

# Compatibility/public alias.
VOICE_LANGUAGE_CODES: Final[tuple[str, ...]] = SUPPORTED_LANGUAGE_CODES

SUPPORTED_LANGUAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "bn": "Bangla",
        "en": "English",
        "hi": "Hindi",
    }
)

LANGUAGE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        # Bengali
        "bn": "bn",
        "bn-bd": "bn",
        "bangla": "bn",
        "bengali": "bn",
        "বাংলা": "bn",

        # English
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "english": "en",

        # Hindi
        "hi": "hi",
        "hi-in": "hi",
        "hindi": "hi",
        "हिन्दी": "hi",
        "हिंदी": "hi",
    }
)

DEFAULT_VOICE_LANGUAGE: Final[str] = "en"

# Single canonical default language constant.
DEFAULT_LANGUAGE_CODE: Final[str] = DEFAULT_VOICE_LANGUAGE

# TTS compatibility alias.
DEFAULT_TTS_LANGUAGE: Final[str] = DEFAULT_VOICE_LANGUAGE

# Legacy wake-word compatibility alias.
DEFAULT_WAKE_WORD: Final[str] = ASSISTANT_WAKE_WORD


# ============================================================================
# Platform
# ============================================================================

PLATFORM: Final[str] = sys.platform

IS_WINDOWS: Final[bool] = PLATFORM.startswith("win")
IS_LINUX: Final[bool] = PLATFORM.startswith("linux")
IS_MAC: Final[bool] = PLATFORM.startswith("darwin")
IS_POSIX: Final[bool] = not IS_WINDOWS

if IS_WINDOWS:
    PLATFORM_NAME: Final[str] = "windows"
elif IS_MAC:
    PLATFORM_NAME: Final[str] = "macos"
elif IS_LINUX:
    PLATFORM_NAME: Final[str] = "linux"
else:
    PLATFORM_NAME: Final[str] = "unknown"


# ============================================================================
# Project Paths
# ============================================================================

# config/constants.py -> AssistantX project root.
BASE_DIR: Final[Path] = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

ASSETS_DIR: Final[Path] = BASE_DIR / "assets"

ICONS_DIR: Final[Path] = ASSETS_DIR / "icons"
IMAGES_DIR: Final[Path] = ASSETS_DIR / "images"
SOUNDS_DIR: Final[Path] = ASSETS_DIR / "sounds"
FONTS_DIR: Final[Path] = ASSETS_DIR / "fonts"
THEMES_DIR: Final[Path] = ASSETS_DIR / "themes"
ANIMATIONS_DIR: Final[Path] = ASSETS_DIR / "animations"

# ---------------------------------------------------------------------------
# Application data
# ---------------------------------------------------------------------------

DATABASE_DIR: Final[Path] = BASE_DIR / "database"
DATA_DIR: Final[Path] = BASE_DIR / "data"
CACHE_DIR: Final[Path] = BASE_DIR / "cache"
LOGS_DIR: Final[Path] = BASE_DIR / "logs"
RESOURCES_DIR: Final[Path] = BASE_DIR / "resources"
PLUGINS_DIR: Final[Path] = BASE_DIR / "plugins"
DOCS_DIR: Final[Path] = BASE_DIR / "docs"

# ---------------------------------------------------------------------------
# Runtime cache directories
# ---------------------------------------------------------------------------

AI_CACHE_DIR: Final[Path] = CACHE_DIR / "ai"
IMAGE_CACHE_DIR: Final[Path] = CACHE_DIR / "images"
SEARCH_CACHE_DIR: Final[Path] = CACHE_DIR / "search"
TEMP_CACHE_DIR: Final[Path] = CACHE_DIR / "temp"

# ---------------------------------------------------------------------------
# Environment/config files
# ---------------------------------------------------------------------------

DOTENV_PATH: Final[Path] = BASE_DIR / ".env"
DOTENV_EXAMPLE_PATH: Final[Path] = BASE_DIR / ".env.example"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SQLITE_DB_PATH: Final[Path] = DATABASE_DIR / "assistantx.db"

# ---------------------------------------------------------------------------
# JSON data
# ---------------------------------------------------------------------------

HISTORY_JSON: Final[Path] = DATA_DIR / "history.json"
MEMORY_JSON: Final[Path] = DATA_DIR / "memory.json"
PROFILE_JSON: Final[Path] = DATA_DIR / "profile.json"
SETTINGS_JSON: Final[Path] = DATA_DIR / "settings.json"
TASKS_JSON: Final[Path] = DATA_DIR / "tasks.json"
COMMANDS_JSON: Final[Path] = DATA_DIR / "commands.json"
CACHE_JSON: Final[Path] = DATA_DIR / "cache.json"

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

ASSISTANT_LOG: Final[Path] = LOGS_DIR / "assistant.log"
DEBUG_LOG: Final[Path] = LOGS_DIR / "debug.log"
ERROR_LOG: Final[Path] = LOGS_DIR / "error.log"


# ============================================================================
# Environment Variable Names
# ============================================================================

ENV_APP_NAME: Final[str] = "APP_NAME"
ENV_APP_ENV: Final[str] = "APP_ENV"
ENV_DEBUG: Final[str] = "DEBUG"
ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"

ENV_LANGUAGE: Final[str] = "ASSISTANTX_LANGUAGE"
ENV_THEME: Final[str] = "ASSISTANTX_THEME"

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

ENV_AI_PROVIDER: Final[str] = "AI_PROVIDER"

ENV_GEMINI_API_KEY: Final[str] = "GEMINI_API_KEY"
ENV_GEMINI_MODEL: Final[str] = "GEMINI_MODEL"

ENV_OLLAMA_BASE_URL: Final[str] = "OLLAMA_BASE_URL"
ENV_OLLAMA_HOST: Final[str] = "OLLAMA_HOST"
ENV_OLLAMA_MODEL: Final[str] = "OLLAMA_MODEL"

ENV_LOCAL_AI_MODEL: Final[str] = "LOCAL_AI_MODEL"
ENV_LOCAL_AI_BASE_URL: Final[str] = "LOCAL_AI_BASE_URL"

# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

ENV_VOICE_ENABLED: Final[str] = "VOICE_ENABLED"
ENV_WAKE_WORD_ENABLED: Final[str] = "WAKE_WORD_ENABLED"
ENV_SPEECH_LANGUAGE: Final[str] = "SPEECH_LANGUAGE"
ENV_TTS_LANGUAGE: Final[str] = "TTS_LANGUAGE"
ENV_TTS_RATE: Final[str] = "TTS_RATE"
ENV_TTS_VOLUME: Final[str] = "TTS_VOLUME"

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

ENV_OPENWEATHER_API_KEY: Final[str] = "OPENWEATHER_API_KEY"
ENV_NEWSAPI_KEY: Final[str] = "NEWSAPI_KEY"

# ---------------------------------------------------------------------------
# Database / security
# ---------------------------------------------------------------------------

ENV_DATABASE_URL: Final[str] = "DATABASE_URL"
ENV_SECRET_KEY: Final[str] = "SECRET_KEY"


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


# The current project direction uses Ollama by default.
DEFAULT_AI_PROVIDER: Final[AIProvider] = AIProvider.OLLAMA

# ---------------------------------------------------------------------------
# Provider defaults
# ---------------------------------------------------------------------------

DEFAULT_GEMINI_MODEL: Final[str] = "gemini-3.5-flash-lite"

DEFAULT_OLLAMA_MODEL: Final[str] = "llama3"

DEFAULT_OLLAMA_BASE_URL: Final[str] = (
    "http://127.0.0.1:11434"
)

# Compatibility alias.
DEFAULT_OLLAMA_HOST: Final[str] = DEFAULT_OLLAMA_BASE_URL

# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------

MAX_CONTEXT_TOKENS: Final[int] = 8192
MAX_HISTORY_MESSAGES: Final[int] = 50

DEFAULT_TEMPERATURE: Final[float] = 0.7
DEFAULT_TOP_P: Final[float] = 0.9

MIN_TEMPERATURE: Final[float] = 0.0
MAX_TEMPERATURE: Final[float] = 2.0

MIN_TOP_P: Final[float] = 0.0
MAX_TOP_P: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Networking / retry
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT_SECONDS: Final[int] = 30
CONNECT_TIMEOUT_SECONDS: Final[int] = 10
READ_TIMEOUT_SECONDS: Final[int] = 30

MAX_RETRIES: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[float] = 1.5

# ---------------------------------------------------------------------------
# AI message limits
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Wake-word configuration
# ---------------------------------------------------------------------------

WAKE_WORD_SENSITIVITY: Final[float] = 0.5

MIN_WAKE_WORD_SENSITIVITY: Final[float] = 0.0
MAX_WAKE_WORD_SENSITIVITY: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Female voice configuration
# ---------------------------------------------------------------------------

# Female-only identity.
DEFAULT_VOICE_GENDER: Final[str] = FIXED_VOICE_GENDER

# Compatibility name for older modules.
VOICE_GENDER: Final[str] = FIXED_VOICE_GENDER

# Diagnostic/configuration representation.
VOICE_MODE: Final[str] = "female_locked"

# pyttsx3 does not expose a portable pitch control.
# Kept as compatibility metadata only.
DEFAULT_VOICE_PITCH: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Speech rate
# ---------------------------------------------------------------------------

SPEECH_RATE_WPM: Final[int] = 170

MIN_SPEECH_RATE_WPM: Final[int] = 80
MAX_SPEECH_RATE_WPM: Final[int] = 300

# ---------------------------------------------------------------------------
# Speech volume
# ---------------------------------------------------------------------------

SPEECH_VOLUME: Final[float] = 1.0

MIN_SPEECH_VOLUME: Final[float] = 0.0
MAX_SPEECH_VOLUME: Final[float] = 1.0

# ---------------------------------------------------------------------------
# Microphone
# ---------------------------------------------------------------------------

MIC_SAMPLE_RATE: Final[int] = 16_000
MIC_CHANNELS: Final[int] = 1

# ---------------------------------------------------------------------------
# Listening
# ---------------------------------------------------------------------------

SILENCE_THRESHOLD_SECONDS: Final[float] = 1.0
LISTEN_TIMEOUT_SECONDS: Final[int] = 12
PHRASE_TIME_LIMIT_SECONDS: Final[int] = 30


# ============================================================================
# Dashboard / UI
# ============================================================================

class ThemeMode(StrEnum):
    """Available dashboard theme modes."""

    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


DEFAULT_THEME: Final[ThemeMode] = ThemeMode.DARK

# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_WIDTH: Final[int] = 1100
DEFAULT_WINDOW_HEIGHT: Final[int] = 720

MIN_WINDOW_WIDTH: Final[int] = 780
MIN_WINDOW_HEIGHT: Final[int] = 520

MAX_WINDOW_WIDTH: Final[int] = 3840
MAX_WINDOW_HEIGHT: Final[int] = 2160

# ---------------------------------------------------------------------------
# Splash
# ---------------------------------------------------------------------------

SPLASH_DURATION_MS: Final[int] = 2200

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

CHAT_BUBBLE_MAX_WIDTH_RATIO: Final[float] = 0.72
CHAT_INPUT_MAX_LENGTH: Final[int] = 10_000
CHAT_HISTORY_PAGE_SIZE: Final[int] = 50

# ---------------------------------------------------------------------------
# Typing / animation
# ---------------------------------------------------------------------------

TYPING_INDICATOR_INTERVAL_MS: Final[int] = 350
ANIMATION_FPS: Final[int] = 60

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

SIDEBAR_WIDTH: Final[int] = 260
SIDEBAR_COLLAPSED_WIDTH: Final[int] = 64

# ---------------------------------------------------------------------------
# UI scaling
# ---------------------------------------------------------------------------

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
    VOICE_CONTROL = "voice_control"
    MEMORY = "memory"
    AUTOMATION = "automation"
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

CACHE_TTL_SECONDS: Final[int] = 3_600

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

# Never store actual secrets here.
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

PROJECT_ROOT: Final[Path] = BASE_DIR
ROOT_DIR: Final[Path] = BASE_DIR

DB_PATH: Final[Path] = SQLITE_DB_PATH
LOG_DIR: Final[Path] = LOGS_DIR

# Provider compatibility alias.
DEFAULT_PROVIDER: Final[AIProvider] = DEFAULT_AI_PROVIDER

# IMPORTANT:
# DEFAULT_AI_PROVIDER is Ollama, therefore DEFAULT_MODEL must resolve
# to the Ollama default model rather than the Gemini model.
DEFAULT_MODEL: Final[str] = DEFAULT_OLLAMA_MODEL

# Legacy language mapping alias.
LANGUAGE_CODES: Final[Mapping[str, str]] = SUPPORTED_LANGUAGES


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Application
    "APP_NAME",
    "APP_VERSION",
    "APP_CODENAME",
    "APP_AUTHOR",
    "APP_ORGANIZATION",
    "APP_DESCRIPTION",
    "APP_LICENSE",
    "APP_VERSION_TUPLE",

    # Assistant identity
    "ASSISTANT_NAME",
    "ASSISTANT_WAKE_WORD",
    "ASSISTANT_WAKE_NAME",
    "ASSISTANT_VOICE_GENDER",
    "FIXED_VOICE_GENDER",
    "VOICE_GENDER_LOCKED",
    "VOICE_GENDER",
    "VOICE_MODE",
    "FIXED_WAKE_WORD",
    "WAKE_WORD_ALIASES",
    "WAKE_WORD_LOCKED",

    # Language
    "VOICE_LANGUAGE_CODES",
    "SUPPORTED_LANGUAGE_CODES",
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_ALIASES",
    "LANGUAGE_CODES",
    "DEFAULT_VOICE_LANGUAGE",
    "DEFAULT_LANGUAGE_CODE",
    "DEFAULT_TTS_LANGUAGE",
    "DEFAULT_WAKE_WORD",

    # Platform
    "PLATFORM",
    "PLATFORM_NAME",
    "IS_WINDOWS",
    "IS_LINUX",
    "IS_MAC",
    "IS_POSIX",

    # Paths
    "BASE_DIR",
    "PROJECT_ROOT",
    "ROOT_DIR",
    "ASSETS_DIR",
    "ICONS_DIR",
    "IMAGES_DIR",
    "SOUNDS_DIR",
    "FONTS_DIR",
    "THEMES_DIR",
    "ANIMATIONS_DIR",
    "DATABASE_DIR",
    "DATA_DIR",
    "CACHE_DIR",
    "LOGS_DIR",
    "LOG_DIR",
    "RESOURCES_DIR",
    "PLUGINS_DIR",
    "DOCS_DIR",
    "AI_CACHE_DIR",
    "IMAGE_CACHE_DIR",
    "SEARCH_CACHE_DIR",
    "TEMP_CACHE_DIR",

    # Files
    "DOTENV_PATH",
    "DOTENV_EXAMPLE_PATH",
    "SQLITE_DB_PATH",
    "DB_PATH",
    "HISTORY_JSON",
    "MEMORY_JSON",
    "PROFILE_JSON",
    "SETTINGS_JSON",
    "TASKS_JSON",
    "COMMANDS_JSON",
    "CACHE_JSON",
    "ASSISTANT_LOG",
    "DEBUG_LOG",
    "ERROR_LOG",

    # Environment variables
    "ENV_APP_NAME",
    "ENV_APP_ENV",
    "ENV_DEBUG",
    "ENV_LOG_LEVEL",
    "ENV_LANGUAGE",
    "ENV_THEME",
    "ENV_AI_PROVIDER",
    "ENV_GEMINI_API_KEY",
    "ENV_GEMINI_MODEL",
    "ENV_OLLAMA_BASE_URL",
    "ENV_OLLAMA_HOST",
    "ENV_OLLAMA_MODEL",
    "ENV_LOCAL_AI_MODEL",
    "ENV_LOCAL_AI_BASE_URL",
    "ENV_VOICE_ENABLED",
    "ENV_WAKE_WORD_ENABLED",
    "ENV_SPEECH_LANGUAGE",
    "ENV_TTS_LANGUAGE",
    "ENV_TTS_RATE",
    "ENV_TTS_VOLUME",
    "ENV_OPENWEATHER_API_KEY",
    "ENV_NEWSAPI_KEY",
    "ENV_DATABASE_URL",
    "ENV_SECRET_KEY",

    # Environment
    "AppEnvironment",
    "DEFAULT_APP_ENV",

    # AI
    "AIProvider",
    "DEFAULT_AI_PROVIDER",
    "DEFAULT_PROVIDER",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_OLLAMA_HOST",
    "DEFAULT_MODEL",
    "MAX_CONTEXT_TOKENS",
    "MAX_HISTORY_MESSAGES",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOP_P",
    "MIN_TEMPERATURE",
    "MAX_TEMPERATURE",
    "MIN_TOP_P",
    "MAX_TOP_P",
    "MAX_INPUT_CHARS",
    "MAX_OUTPUT_CHARS",
    "MAX_SYSTEM_PROMPT_CHARS",

    # Networking
    "REQUEST_TIMEOUT_SECONDS",
    "CONNECT_TIMEOUT_SECONDS",
    "READ_TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "RETRY_BACKOFF_SECONDS",
    "HTTP_USER_AGENT",
    "HTTP_DEFAULT_TIMEOUT",
    "HTTP_MAX_REDIRECTS",

    # Voice
    "VoiceState",
    "WAKE_WORD_SENSITIVITY",
    "MIN_WAKE_WORD_SENSITIVITY",
    "MAX_WAKE_WORD_SENSITIVITY",
    "DEFAULT_VOICE_GENDER",
    "DEFAULT_VOICE_PITCH",
    "SPEECH_RATE_WPM",
    "MIN_SPEECH_RATE_WPM",
    "MAX_SPEECH_RATE_WPM",
    "SPEECH_VOLUME",
    "MIN_SPEECH_VOLUME",
    "MAX_SPEECH_VOLUME",
    "MIC_SAMPLE_RATE",
    "MIC_CHANNELS",
    "SILENCE_THRESHOLD_SECONDS",
    "LISTEN_TIMEOUT_SECONDS",
    "PHRASE_TIME_LIMIT_SECONDS",

    # UI
    "ThemeMode",
    "DEFAULT_THEME",
    "DEFAULT_WINDOW_WIDTH",
    "DEFAULT_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "MIN_WINDOW_HEIGHT",
    "MAX_WINDOW_WIDTH",
    "MAX_WINDOW_HEIGHT",
    "SPLASH_DURATION_MS",
    "CHAT_BUBBLE_MAX_WIDTH_RATIO",
    "CHAT_INPUT_MAX_LENGTH",
    "CHAT_HISTORY_PAGE_SIZE",
    "TYPING_INDICATOR_INTERVAL_MS",
    "ANIMATION_FPS",
    "SIDEBAR_WIDTH",
    "SIDEBAR_COLLAPSED_WIDTH",
    "DEFAULT_UI_SCALE",
    "MIN_UI_SCALE",
    "MAX_UI_SCALE",

    # Logging
    "LOG_FORMAT",
    "LOG_DATE_FORMAT",
    "DEFAULT_LOG_LEVEL",
    "SUPPORTED_LOG_LEVELS",
    "LOG_MAX_BYTES",
    "LOG_BACKUP_COUNT",
    "LOG_ENCODING",

    # Services
    "DEFAULT_SEARCH_RESULTS_LIMIT",
    "MAX_SEARCH_RESULTS_LIMIT",
    "WEATHER_UNITS",
    "NEWS_LANGUAGE",
    "NEWS_PAGE_SIZE",
    "WIKIPEDIA_SENTENCES",
    "TRANSLATE_DEFAULT_TARGET",

    # Intents
    "IntentCategory",
    "EXIT_KEYWORDS",
    "CONFIRMATION_KEYWORDS",
    "NEGATION_KEYWORDS",

    # Scheduler
    "DEFAULT_SCHEDULER_POLL_INTERVAL",
    "MAX_SCHEDULED_TASKS",
    "DEFAULT_TASK_TIMEOUT_SECONDS",
    "MIN_RECURRING_INTERVAL_SECONDS",

    # Storage
    "DEFAULT_ENCODING",
    "JSON_INDENT",
    "MAX_HISTORY_SESSIONS",
    "MAX_MEMORY_ENTRIES",
    "MAX_FILE_NAME_LENGTH",
    "MAX_PATH_LENGTH",
    "BACKUP_FILE_SUFFIX",

    # Cache
    "CACHE_TTL_SECONDS",
    "AI_CACHE_TTL_SECONDS",
    "SEARCH_CACHE_TTL_SECONDS",
    "IMAGE_CACHE_TTL_SECONDS",
    "MAX_CACHE_SIZE_MB",

    # Date/time
    "DATE_DISPLAY_FORMAT",
    "TIME_DISPLAY_FORMAT",
    "DATETIME_DISPLAY_FORMAT",

    # Notifications
    "DEFAULT_NOTIFICATION_DURATION_MS",
    "NOTIFICATION_MAX_TITLE_LENGTH",
    "NOTIFICATION_MAX_MESSAGE_LENGTH",

    # Security
    "MAX_COMMAND_LENGTH",
    "MAX_URL_LENGTH",
    "MAX_PLUGIN_NAME_LENGTH",
    "MAX_PLUGIN_DESCRIPTION_LENGTH",
    "SECRET_MASK",

    # Application assets
    "ICON_FILE",
    "APP_LOGO_FILE",
    "SPLASH_IMAGE_FILE",
    "AVATAR_FILE",
    "DARK_THEME_FILE",
    "LIGHT_THEME_FILE",

    # Features
    "Feature",
    "DEFAULT_FEATURES",

    # Runtime
    "DEFAULT_MAX_MEMORY_CONTEXT",
    "DEFAULT_MAX_HISTORY_CONTEXT",
    "DEFAULT_CONFIRMATION_TIMEOUT_SECONDS",
    "DEFAULT_CLARIFICATION_TIMEOUT_SECONDS",
]
