"""
constants.py
============
Central repository for all immutable, hard-coded values used throughout
AssistantX. Nothing in this file should change at runtime. Anything that
CAN change at runtime (user preferences, API keys, feature toggles)
belongs in settings.py or secrets.py instead.

Grouping conventions:
    - ALL_CAPS_SNAKE_CASE for scalar constants
    - Dictionaries/Enums for grouped constants
    - No side effects, no imports from other project modules (to avoid
      circular imports) except the standard library.
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path

# --------------------------------------------------------------------------- #
# Application metadata
# --------------------------------------------------------------------------- #

APP_NAME: str = "AssistantX"
APP_VERSION: str = "1.0.0"
APP_CODENAME: str = "Genesis"
APP_AUTHOR: str = "AssistantX Team"
APP_DESCRIPTION: str = "A cross-platform, voice-driven personal AI assistant."
APP_LICENSE: str = "MIT"
APP_ORGANIZATION: str = "AssistantX"

# Semantic version tuple, useful for programmatic comparisons.
APP_VERSION_TUPLE: tuple[int, int, int] = tuple(
    int(part) for part in APP_VERSION.split(".")
)

# --------------------------------------------------------------------------- #
# Platform detection
# --------------------------------------------------------------------------- #

PLATFORM: str = sys.platform  # 'win32', 'linux', 'darwin'
IS_WINDOWS: bool = PLATFORM.startswith("win")
IS_LINUX: bool = PLATFORM.startswith("linux")
IS_MAC: bool = PLATFORM.startswith("darwin")

# --------------------------------------------------------------------------- #
# Root paths
# --------------------------------------------------------------------------- #

# config/constants.py -> parents[1] is the project root (AssistantX/)
BASE_DIR: Path = Path(__file__).resolve().parents[1]

ASSETS_DIR: Path = BASE_DIR / "assets"
ICONS_DIR: Path = ASSETS_DIR / "icons"
IMAGES_DIR: Path = ASSETS_DIR / "images"
SOUNDS_DIR: Path = ASSETS_DIR / "sounds"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
THEMES_DIR: Path = ASSETS_DIR / "themes"
ANIMATIONS_DIR: Path = ASSETS_DIR / "animations"

DATABASE_DIR: Path = BASE_DIR / "database"
DATA_DIR: Path = BASE_DIR / "data"
CACHE_DIR: Path = BASE_DIR / "cache"
LOGS_DIR: Path = BASE_DIR / "logs"
RESOURCES_DIR: Path = BASE_DIR / "resources"
PLUGINS_DIR: Path = BASE_DIR / "plugins"

# Individual well-known files
DOTENV_PATH: Path = BASE_DIR / ".env"
DOTENV_EXAMPLE_PATH: Path = BASE_DIR / ".env.example"
SQLITE_DB_PATH: Path = DATABASE_DIR / "assistantx.db"

HISTORY_JSON: Path = DATA_DIR / "history.json"
MEMORY_JSON: Path = DATA_DIR / "memory.json"
PROFILE_JSON: Path = DATA_DIR / "profile.json"
SETTINGS_JSON: Path = DATA_DIR / "settings.json"
TASKS_JSON: Path = DATA_DIR / "tasks.json"
COMMANDS_JSON: Path = DATA_DIR / "commands.json"
CACHE_JSON: Path = DATA_DIR / "cache.json"

ASSISTANT_LOG: Path = LOGS_DIR / "assistant.log"
DEBUG_LOG: Path = LOGS_DIR / "debug.log"
ERROR_LOG: Path = LOGS_DIR / "error.log"

# Ensure the "runtime-writable" directories exist as soon as constants is
# imported. This makes the rest of the codebase safe to assume they exist.
for _dir in (DATA_DIR, CACHE_DIR, LOGS_DIR, DATABASE_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Environment variable keys (names only — actual values live in secrets.py)
# --------------------------------------------------------------------------- #

ENV_GEMINI_API_KEY: str = "GEMINI_API_KEY"
ENV_OPENWEATHER_API_KEY: str = "OPENWEATHER_API_KEY"
ENV_NEWSAPI_KEY: str = "NEWSAPI_KEY"
ENV_OLLAMA_HOST: str = "OLLAMA_HOST"
ENV_APP_ENV: str = "APP_ENV"  # 'development' | 'production' | 'testing'
ENV_LOG_LEVEL: str = "LOG_LEVEL"

# --------------------------------------------------------------------------- #
# AI providers
# --------------------------------------------------------------------------- #

class AIProvider(str, Enum):
    """Supported AI backend providers."""

    GEMINI = "gemini"
    OLLAMA = "ollama"
    LOCAL = "local"

DEFAULT_AI_PROVIDER: AIProvider = AIProvider.GEMINI
DEFAULT_GEMINI_MODEL: str = "gemini-1.5-flash"
DEFAULT_OLLAMA_MODEL: str = "llama3"
DEFAULT_OLLAMA_HOST: str = "http://localhost:11434"

MAX_CONTEXT_TOKENS: int = 8192
MAX_HISTORY_MESSAGES: int = 50
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_TOP_P: float = 0.9
REQUEST_TIMEOUT_SECONDS: int = 30
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 1.5

# --------------------------------------------------------------------------- #
# Voice engine
# --------------------------------------------------------------------------- #

class VoiceState(str, Enum):
    """Finite states of the voice subsystem."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"

DEFAULT_WAKE_WORD: str = "hey assistant"
WAKE_WORD_SENSITIVITY: float = 0.5
DEFAULT_LANGUAGE_CODE: str = "en-US"
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "bn-BD": "Bangla (Bangladesh)",
    "hi-IN": "Hindi (India)",
}
SPEECH_RATE_WPM: int = 175
SPEECH_VOLUME: float = 1.0
MIC_SAMPLE_RATE: int = 16000
MIC_CHANNELS: int = 1
SILENCE_THRESHOLD_SECONDS: float = 1.2
LISTEN_TIMEOUT_SECONDS: int = 8
PHRASE_TIME_LIMIT_SECONDS: int = 15

# --------------------------------------------------------------------------- #
# Dashboard / UI
# --------------------------------------------------------------------------- #

class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"

DEFAULT_THEME: ThemeMode = ThemeMode.DARK
DEFAULT_WINDOW_WIDTH: int = 1100
DEFAULT_WINDOW_HEIGHT: int = 720
MIN_WINDOW_WIDTH: int = 780
MIN_WINDOW_HEIGHT: int = 520
SPLASH_DURATION_MS: int = 2200
CHAT_BUBBLE_MAX_WIDTH_RATIO: float = 0.72
TYPING_INDICATOR_INTERVAL_MS: int = 350
ANIMATION_FPS: int = 60
SIDEBAR_WIDTH: int = 260
SIDEBAR_COLLAPSED_WIDTH: int = 64

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOG_FORMAT: str = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL: str = "INFO"
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 5

# --------------------------------------------------------------------------- #
# Networking / services
# --------------------------------------------------------------------------- #

HTTP_USER_AGENT: str = f"{APP_NAME}/{APP_VERSION}"
DEFAULT_SEARCH_RESULTS_LIMIT: int = 5
WEATHER_UNITS: str = "metric"
NEWS_LANGUAGE: str = "en"
NEWS_PAGE_SIZE: int = 10
WIKIPEDIA_SENTENCES: int = 3
TRANSLATE_DEFAULT_TARGET: str = "en"

# --------------------------------------------------------------------------- #
# Commands / intents
# --------------------------------------------------------------------------- #

class IntentCategory(str, Enum):
    """Top-level intent buckets used by the brain/classifier module."""

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

EXIT_KEYWORDS: tuple[str, ...] = ("exit", "quit", "goodbye", "bye", "shutdown")
CONFIRMATION_KEYWORDS: tuple[str, ...] = ("yes", "yeah", "sure", "ok", "okay", "confirm")
NEGATION_KEYWORDS: tuple[str, ...] = ("no", "nope", "cancel", "never mind")

# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #

DATE_DISPLAY_FORMAT: str = "%A, %d %B %Y"
TIME_DISPLAY_FORMAT: str = "%I:%M %p"
DEFAULT_ENCODING: str = "utf-8"
