"""
config/settings.py — AssistantX Settings Manager
=================================================

Centralized, validated, thread-safe application settings for AssistantX.

VOICE IDENTITY
--------------
Assistant name : JEROX
Wake word      : jerox (FIXED)
Voice gender   : female (FIXED)
Languages      : bn / en / hi

The voice identity is intentionally not user-configurable.
Language, speaking rate, and volume remain configurable.

This module owns configuration state only.
Actual microphone, wake-word engine, TTS engine, and female-voice
selection remain inside the voice package.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Mapping, Optional
import copy
import json
import os
import re
import shutil
import tempfile


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

try:
    from .constants import (
        APP_NAME,
        APP_VERSION,
        DEFAULT_AI_PROVIDER,
        DEFAULT_GEMINI_MODEL,
        DEFAULT_LANGUAGE_CODE,
        DEFAULT_OLLAMA_MODEL,
        DEFAULT_TEMPERATURE,
        DEFAULT_THEME,
        DEFAULT_WAKE_WORD,
        DEFAULT_WINDOW_HEIGHT,
        DEFAULT_WINDOW_WIDTH,
        SETTINGS_JSON,
        SPEECH_RATE_WPM,
        SPEECH_VOLUME,
        WAKE_WORD_SENSITIVITY,
    )
except ImportError:  # pragma: no cover
    APP_NAME = "AssistantX"
    APP_VERSION = "1.0.0"

    DEFAULT_AI_PROVIDER = "ollama"
    DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
    DEFAULT_LANGUAGE_CODE = "en"
    DEFAULT_OLLAMA_MODEL = "llama3"
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_THEME = "dark"
    DEFAULT_WAKE_WORD = "jerox"

    DEFAULT_WINDOW_WIDTH = 1280
    DEFAULT_WINDOW_HEIGHT = 800

    SPEECH_RATE_WPM = 175
    SPEECH_VOLUME = 1.0
    WAKE_WORD_SENSITIVITY = 0.65

    SETTINGS_JSON = Path("data/settings.json")


# ---------------------------------------------------------------------------
# Fixed JEROX identity
# ---------------------------------------------------------------------------

ASSISTANT_NAME = "JEROX"
FIXED_WAKE_WORD = "jerox"
FIXED_VOICE_GENDER = "female"

SUPPORTED_LANGUAGE_CODES = ("bn", "en", "hi")

CURRENT_SCHEMA_VERSION = 2
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SettingsError(Exception):
    """Base exception for settings-related errors."""


class SettingsValidationError(SettingsError):
    """Raised when a setting value is invalid."""


class SettingsPersistenceError(SettingsError):
    """Raised when settings cannot be loaded or saved."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LANGUAGE_ALIASES = {
    "bn": "bn",
    "bn-bd": "bn",
    "bengali": "bn",
    "bangla": "bn",

    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",

    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
}

_PROVIDER_ALIASES = {
    "gemini": "gemini",
    "google": "gemini",
    "google-gemini": "gemini",

    "ollama": "ollama",

    "local": "local",
    "local-ai": "local",
}

_THEME_VALUES = {"dark", "light", "system"}

_HEX_COLOR_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"
)

_TIME_RE = re.compile(
    r"^(?:[01]\d|2[0-3]):[0-5]\d$"
)


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _deep_copy(value: Any) -> Any:
    """Safely copy arbitrary settings data."""
    return copy.deepcopy(value)


def _normalize_language(value: Any) -> str:
    """
    Normalize language aliases into:
        bn
        en
        hi
    """
    if value is None:
        return _normalize_language(DEFAULT_LANGUAGE_CODE)

    normalized = str(value).strip().lower()

    if normalized in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[normalized]

    raise SettingsValidationError(
        f"Unsupported voice language: {value!r}. "
        f"Supported languages: {', '.join(SUPPORTED_LANGUAGE_CODES)}"
    )


def _normalize_provider(value: Any) -> str:
    """Normalize AI provider name."""
    normalized = str(value).strip().lower()

    if normalized in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[normalized]

    raise SettingsValidationError(
        f"Unsupported AI provider: {value!r}"
    )


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Convert common values into bool safely."""
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True

        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False

    return bool(value)


def _safe_int(
    value: Any,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Convert and clamp an integer value."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


def _safe_float(
    value: Any,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    """Convert and clamp a float value."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


# ---------------------------------------------------------------------------
# Voice settings
# ---------------------------------------------------------------------------

@dataclass
class VoiceSettings:
    """
    JEROX voice configuration.

    Identity-related values are fixed and must never be changed through
    normal settings operations.
    """

    enabled: bool = True

    # Fixed JEROX identity.
    wake_word: str = FIXED_WAKE_WORD
    wake_word_sensitivity: float = WAKE_WORD_SENSITIVITY

    # Normalized language: bn / en / hi.
    language: str = field(
        default_factory=lambda: _normalize_language(DEFAULT_LANGUAGE_CODE)
    )

    # User-adjustable speech parameters.
    rate: int = SPEECH_RATE_WPM
    volume: float = SPEECH_VOLUME

    # Compatibility field only.
    # Actual female voice selection belongs to voice/speaker.py.
    voice_id: Optional[str] = None

    # Fixed identity.
    voice_gender: str = FIXED_VOICE_GENDER
    voice_gender_locked: bool = True

    push_to_talk: bool = False
    noise_suppression: bool = True


# ---------------------------------------------------------------------------
# AI settings
# ---------------------------------------------------------------------------

@dataclass
class AISettings:
    """AI provider and generation configuration."""

    provider: str = DEFAULT_AI_PROVIDER
    gemini_model: str = DEFAULT_GEMINI_MODEL
    ollama_model: str = DEFAULT_OLLAMA_MODEL

    temperature: float = DEFAULT_TEMPERATURE
    max_history_messages: int = 20

    stream_responses: bool = True

    system_persona: str = (
        "You are JEROX, the intelligent personal assistant "
        "inside AssistantX. Be helpful, concise, accurate, and natural."
    )


# ---------------------------------------------------------------------------
# UI settings
# ---------------------------------------------------------------------------

@dataclass
class UISettings:
    """Desktop interface preferences."""

    theme: str = DEFAULT_THEME

    width: int = DEFAULT_WINDOW_WIDTH
    height: int = DEFAULT_WINDOW_HEIGHT

    maximized: bool = False
    font_scale: float = 1.0

    typing_indicator: bool = True
    animations: bool = True
    sidebar: bool = True

    accent: str = "#6C63FF"


# ---------------------------------------------------------------------------
# Privacy settings
# ---------------------------------------------------------------------------

@dataclass
class PrivacySettings:
    """Privacy and local-data controls."""

    save_history: bool = True
    save_memory: bool = True

    telemetry_enabled: bool = False
    analytics_enabled: bool = False

    store_voice_audio: bool = False


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------

@dataclass
class NotificationSettings:
    """Desktop notification preferences."""

    enabled: bool = True
    sound: bool = True

    task_completion: bool = True
    errors: bool = True
    reminders: bool = True


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """Complete AssistantX configuration object."""

    schema_version: int = CURRENT_SCHEMA_VERSION

    app_name: str = APP_NAME
    app_version: str = APP_VERSION

    voice: VoiceSettings = field(default_factory=VoiceSettings)
    ai: AISettings = field(default_factory=AISettings)
    ui: UISettings = field(default_factory=UISettings)

    privacy: PrivacySettings = field(
        default_factory=PrivacySettings
    )

    notifications: NotificationSettings = field(
        default_factory=NotificationSettings
    )

    last_modified: str = field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Settings Manager
# ---------------------------------------------------------------------------

class SettingsManager:
    """
    Thread-safe persistent settings manager.

    Responsibilities:
        - Load settings from JSON
        - Validate settings
        - Migrate old schemas
        - Save atomically
        - Provide dot-path access
        - Protect fixed JEROX identity
        - Export diagnostics
    """

    _PROTECTED_KEYS = {
        "schema_version",
        "last_modified",
        "app_name",
        "app_version",
        "voice.wake_word",
        "voice.voice_id",
        "voice.voice_gender",
        "voice.voice_gender_locked",
    }

    def __init__(
        self,
        path: Optional[Path | str] = None,
        *,
        auto_load: bool = True,
    ) -> None:
        self._lock = RLock()

        self.path = Path(path or SETTINGS_JSON)

        self._settings = Settings()

        self._loaded = False
        self._save_count = 0
        self._load_count = 0
        self._last_error: Optional[str] = None

        if auto_load:
            self.load()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def settings(self) -> Settings:
        """Return a deep copy of current settings."""
        with self._lock:
            return _deep_copy(self._settings)

    @property
    def loaded(self) -> bool:
        """Whether settings have been loaded."""
        with self._lock:
            return self._loaded

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        """Return settings as a plain dictionary."""
        with self._lock:
            return asdict(self._settings)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_path(path: str) -> list[str]:
        if not isinstance(path, str) or not path.strip():
            raise SettingsValidationError(
                "Setting path must be a non-empty string."
            )

        return [
            part.strip()
            for part in path.split(".")
            if part.strip()
        ]

    def get(
        self,
        path: str,
        default: Any = None,
    ) -> Any:
        """Get a setting using dot notation."""
        parts = self._split_path(path)

        with self._lock:
            current: Any = self._settings

            for part in parts:
                if isinstance(current, Mapping):
                    if part not in current:
                        return default

                    current = current[part]

                else:
                    if not hasattr(current, part):
                        return default

                    current = getattr(current, part)

            return _deep_copy(current)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_value(
        self,
        path: str,
        value: Any,
    ) -> Any:
        """Normalize and validate one setting."""

        # --------------------------------------------------------------
        # Fixed JEROX identity
        # --------------------------------------------------------------

        if path == "voice.wake_word":
            if str(value).strip().lower() != FIXED_WAKE_WORD:
                raise SettingsValidationError(
                    "JEROX wake word is fixed and cannot be changed."
                )

            return FIXED_WAKE_WORD

        if path == "voice.voice_gender":
            if str(value).strip().lower() != FIXED_VOICE_GENDER:
                raise SettingsValidationError(
                    "JEROX voice gender is fixed to female."
                )

            return FIXED_VOICE_GENDER

        if path == "voice.voice_gender_locked":
            if not _safe_bool(value, True):
                raise SettingsValidationError(
                    "JEROX voice gender must remain locked."
                )

            return True

        if path == "voice.voice_id":
            raise SettingsValidationError(
                "JEROX voice selection is managed by speaker.py "
                "and cannot be changed from settings."
            )

        # --------------------------------------------------------------
        # Protected metadata
        # --------------------------------------------------------------

        if path in {
            "schema_version",
            "last_modified",
            "app_name",
            "app_version",
        }:
            raise SettingsValidationError(
                f"{path} is read-only."
            )

        # --------------------------------------------------------------
        # Voice
        # --------------------------------------------------------------

        if path == "voice.enabled":
            return _safe_bool(value, True)

        if path == "voice.wake_word_sensitivity":
            return _safe_float(
                value,
                WAKE_WORD_SENSITIVITY,
                0.0,
                1.0,
            )

        if path == "voice.language":
            return _normalize_language(value)

        if path == "voice.rate":
            return _safe_int(
                value,
                SPEECH_RATE_WPM,
                80,
                300,
            )

        if path == "voice.volume":
            return _safe_float(
                value,
                SPEECH_VOLUME,
                0.0,
                1.0,
            )

        if path == "voice.push_to_talk":
            return _safe_bool(value, False)

        if path == "voice.noise_suppression":
            return _safe_bool(value, True)

        # --------------------------------------------------------------
        # AI
        # --------------------------------------------------------------

        if path == "ai.provider":
            return _normalize_provider(value)

        if path in {
            "ai.gemini_model",
            "ai.ollama_model",
            "ai.system_persona",
        }:
            return str(value).strip()

        if path == "ai.temperature":
            return _safe_float(
                value,
                DEFAULT_TEMPERATURE,
                0.0,
                2.0,
            )

        if path == "ai.max_history_messages":
            return _safe_int(
                value,
                20,
                0,
                500,
            )

        if path == "ai.stream_responses":
            return _safe_bool(value, True)

        # --------------------------------------------------------------
        # UI
        # --------------------------------------------------------------

        if path == "ui.theme":
            theme = str(value).strip().lower()

            if theme not in _THEME_VALUES:
                raise SettingsValidationError(
                    f"Unsupported UI theme: {value!r}"
                )

            return theme

        if path == "ui.width":
            return _safe_int(
                value,
                DEFAULT_WINDOW_WIDTH,
                640,
                7680,
            )

        if path == "ui.height":
            return _safe_int(
                value,
                DEFAULT_WINDOW_HEIGHT,
                480,
                4320,
            )

        if path == "ui.maximized":
            return _safe_bool(value, False)

        if path == "ui.font_scale":
            return _safe_float(
                value,
                1.0,
                0.75,
                2.0,
            )

        if path in {
            "ui.typing_indicator",
            "ui.animations",
            "ui.sidebar",
        }:
            return _safe_bool(value, True)

        if path == "ui.accent":
            accent = str(value).strip()

            if not _HEX_COLOR_RE.fullmatch(accent):
                raise SettingsValidationError(
                    "UI accent must be a valid hexadecimal color."
                )

            return accent

        # --------------------------------------------------------------
        # Privacy
        # --------------------------------------------------------------

        if path in {
            "privacy.save_history",
            "privacy.save_memory",
            "privacy.telemetry_enabled",
            "privacy.analytics_enabled",
            "privacy.store_voice_audio",
        }:
            return _safe_bool(value, False)

        # --------------------------------------------------------------
        # Notifications
        # --------------------------------------------------------------

        if path in {
            "notifications.enabled",
            "notifications.sound",
            "notifications.task_completion",
            "notifications.errors",
            "notifications.reminders",
        }:
            return _safe_bool(value, True)

        raise SettingsValidationError(
            f"Unknown setting path: {path}"
        )

    # ------------------------------------------------------------------
    # Set
    # ------------------------------------------------------------------

    def set(
        self,
        path: str,
        value: Any,
        *,
        save: bool = True,
    ) -> bool:
        """
        Set one setting.

        Fixed JEROX identity values cannot be modified.
        """
        path = path.strip()

        if path in self._PROTECTED_KEYS:
            # Allow setting the same fixed values without treating it
            # as a mutation request.
            if path == "voice.wake_word":
                if str(value).strip().lower() == FIXED_WAKE_WORD:
                    return True

            raise SettingsValidationError(
                f"{path} is protected and cannot be changed."
            )

        normalized = self._validate_value(path, value)

        parts = self._split_path(path)

        with self._lock:
            if len(parts) != 2:
                raise SettingsValidationError(
                    "Only nested settings such as 'voice.language' "
                    "are writable."
                )

            section_name, field_name = parts

            section = getattr(
                self._settings,
                section_name,
                None,
            )

            if section is None or not hasattr(
                section,
                field_name,
            ):
                raise SettingsValidationError(
                    f"Unknown setting path: {path}"
                )

            setattr(section, field_name, normalized)

            # Always re-apply fixed identity.
            self._enforce_voice_identity()

            if save:
                self.save()

        return True

    # ------------------------------------------------------------------
    # Batch update
    # ------------------------------------------------------------------

    def update(
        self,
        values: Mapping[str, Any],
        *,
        save: bool = True,
    ) -> bool:
        """Update multiple settings safely."""

        if not isinstance(values, Mapping):
            raise SettingsValidationError(
                "Settings update must be a mapping."
            )

        with self._lock:
            normalized_values: Dict[str, Any] = {}

            for path, value in values.items():
                normalized_values[path] = self._validate_value(
                    path,
                    value,
                )

            for path, value in normalized_values.items():
                if path in self._PROTECTED_KEYS:
                    continue

                parts = self._split_path(path)

                if len(parts) != 2:
                    raise SettingsValidationError(
                        f"Invalid setting path: {path}"
                    )

                section_name, field_name = parts

                section = getattr(
                    self._settings,
                    section_name,
                    None,
                )

                if section is None or not hasattr(
                    section,
                    field_name,
                ):
                    raise SettingsValidationError(
                        f"Unknown setting path: {path}"
                    )

                setattr(section, field_name, value)

            self._enforce_voice_identity()

            if save:
                self.save()

        return True

    # ------------------------------------------------------------------
    # Voice identity enforcement
    # ------------------------------------------------------------------

    def _enforce_voice_identity(self) -> None:
        """Guarantee JEROX voice invariants."""
        voice = self._settings.voice

        voice.wake_word = FIXED_WAKE_WORD
        voice.voice_gender = FIXED_VOICE_GENDER
        voice.voice_gender_locked = True

        # User-selected voice IDs are intentionally discarded.
        voice.voice_id = None

        voice.language = _normalize_language(
            voice.language
        )

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> Settings:
        """
        Load settings from disk.

        Missing or invalid files fall back to safe defaults.
        """
        with self._lock:
            try:
                if not self.path.exists():
                    self._settings = Settings()
                    self._enforce_voice_identity()
                    self._loaded = True
                    self.save()
                    return _deep_copy(self._settings)

                raw = self.path.read_text(
                    encoding="utf-8"
                )

                data = json.loads(raw)

                if not isinstance(data, dict):
                    raise SettingsPersistenceError(
                        "Settings root must be a JSON object."
                    )

                self._settings = self._from_dict(data)

                self._loaded = True
                self._load_count += 1
                self._last_error = None

                # Persist migration/normalization.
                self.save()

                return _deep_copy(self._settings)

            except (
                OSError,
                json.JSONDecodeError,
                SettingsError,
                TypeError,
                ValueError,
            ) as exc:
                self._last_error = str(exc)

                self._backup_corrupt_file()

                self._settings = Settings()
                self._enforce_voice_identity()

                self._loaded = True

                try:
                    self.save()
                except Exception:
                    pass

                return _deep_copy(self._settings)

    # ------------------------------------------------------------------
    # Dict conversion / migration
    # ------------------------------------------------------------------

    def _from_dict(
        self,
        data: Mapping[str, Any],
    ) -> Settings:
        """Build validated Settings from raw JSON data."""

        voice_data = data.get("voice", {})
        ai_data = data.get("ai", {})
        ui_data = data.get("ui", {})
        privacy_data = data.get("privacy", {})
        notification_data = data.get(
            "notifications",
            {},
        )

        if not isinstance(voice_data, Mapping):
            voice_data = {}

        if not isinstance(ai_data, Mapping):
            ai_data = {}

        if not isinstance(ui_data, Mapping):
            ui_data = {}

        if not isinstance(privacy_data, Mapping):
            privacy_data = {}

        if not isinstance(notification_data, Mapping):
            notification_data = {}

        # --------------------------------------------------------------
        # Voice migration
        # --------------------------------------------------------------

        old_language = voice_data.get(
            "language",
            DEFAULT_LANGUAGE_CODE,
        )

        try:
            normalized_language = _normalize_language(
                old_language
            )
        except SettingsValidationError:
            normalized_language = "en"

        voice = VoiceSettings(
            enabled=_safe_bool(
                voice_data.get("enabled", True),
                True,
            ),

            # Always fixed.
            wake_word=FIXED_WAKE_WORD,

            wake_word_sensitivity=_safe_float(
                voice_data.get(
                    "wake_word_sensitivity",
                    WAKE_WORD_SENSITIVITY,
                ),
                WAKE_WORD_SENSITIVITY,
                0.0,
                1.0,
            ),

            language=normalized_language,

            rate=_safe_int(
                voice_data.get(
                    "rate",
                    SPEECH_RATE_WPM,
                ),
                SPEECH_RATE_WPM,
                80,
                300,
            ),

            volume=_safe_float(
                voice_data.get(
                    "volume",
                    SPEECH_VOLUME,
                ),
                SPEECH_VOLUME,
                0.0,
                1.0,
            ),

            # Old custom voice IDs are deliberately discarded.
            voice_id=None,

            voice_gender=FIXED_VOICE_GENDER,
            voice_gender_locked=True,

            push_to_talk=_safe_bool(
                voice_data.get(
                    "push_to_talk",
                    False,
                ),
                False,
            ),

            noise_suppression=_safe_bool(
                voice_data.get(
                    "noise_suppression",
                    True,
                ),
                True,
            ),
        )

        # --------------------------------------------------------------
        # AI migration
        # --------------------------------------------------------------

        raw_provider = ai_data.get(
            "provider",
            DEFAULT_AI_PROVIDER,
        )

        try:
            provider = _normalize_provider(
                raw_provider
            )
        except SettingsValidationError:
            provider = _normalize_provider(
                DEFAULT_AI_PROVIDER
            )

        ai = AISettings(
            provider=provider,

            gemini_model=str(
                ai_data.get(
                    "gemini_model",
                    DEFAULT_GEMINI_MODEL,
                )
            ).strip(),

            ollama_model=str(
                ai_data.get(
                    "ollama_model",
                    DEFAULT_OLLAMA_MODEL,
                )
            ).strip(),

            temperature=_safe_float(
                ai_data.get(
                    "temperature",
                    DEFAULT_TEMPERATURE,
                ),
                DEFAULT_TEMPERATURE,
                0.0,
                2.0,
            ),

            max_history_messages=_safe_int(
                ai_data.get(
                    "max_history_messages",
                    20,
                ),
                20,
                0,
                500,
            ),

            stream_responses=_safe_bool(
                ai_data.get(
                    "stream_responses",
                    True,
                ),
                True,
            ),

            system_persona=str(
                ai_data.get(
                    "system_persona",
                    AISettings.system_persona,
                )
            ).strip(),
        )

        # --------------------------------------------------------------
        # UI migration
        # --------------------------------------------------------------

        theme = str(
            ui_data.get(
                "theme",
                DEFAULT_THEME,
            )
        ).strip().lower()

        if theme not in _THEME_VALUES:
            theme = DEFAULT_THEME

        accent = str(
            ui_data.get(
                "accent",
                "#6C63FF",
            )
        ).strip()

        if not _HEX_COLOR_RE.fullmatch(accent):
            accent = "#6C63FF"

        ui = UISettings(
            theme=theme,

            width=_safe_int(
                ui_data.get(
                    "width",
                    DEFAULT_WINDOW_WIDTH,
                ),
                DEFAULT_WINDOW_WIDTH,
                640,
                7680,
            ),

            height=_safe_int(
                ui_data.get(
                    "height",
                    DEFAULT_WINDOW_HEIGHT,
                ),
                DEFAULT_WINDOW_HEIGHT,
                480,
                4320,
            ),

            maximized=_safe_bool(
                ui_data.get(
                    "maximized",
                    False,
                ),
                False,
            ),

            font_scale=_safe_float(
                ui_data.get(
                    "font_scale",
                    1.0,
                ),
                1.0,
                0.75,
                2.0,
            ),

            typing_indicator=_safe_bool(
                ui_data.get(
                    "typing_indicator",
                    True,
                ),
                True,
            ),

            animations=_safe_bool(
                ui_data.get(
                    "animations",
                    True,
                ),
                True,
            ),

            sidebar=_safe_bool(
                ui_data.get(
                    "sidebar",
                    True,
                ),
                True,
            ),

            accent=accent,
        )

        # --------------------------------------------------------------
        # Privacy
        # --------------------------------------------------------------

        privacy = PrivacySettings(
            save_history=_safe_bool(
                privacy_data.get(
                    "save_history",
                    True,
                ),
                True,
            ),

            save_memory=_safe_bool(
                privacy_data.get(
                    "save_memory",
                    True,
                ),
                True,
            ),

            telemetry_enabled=_safe_bool(
                privacy_data.get(
                    "telemetry_enabled",
                    False,
                ),
                False,
            ),

            analytics_enabled=_safe_bool(
                privacy_data.get(
                    "analytics_enabled",
                    False,
                ),
                False,
            ),

            store_voice_audio=_safe_bool(
                privacy_data.get(
                    "store_voice_audio",
                    False,
                ),
                False,
            ),
        )

        # --------------------------------------------------------------
        # Notifications
        # --------------------------------------------------------------

        notifications = NotificationSettings(
            enabled=_safe_bool(
                notification_data.get(
                    "enabled",
                    True,
                ),
                True,
            ),

            sound=_safe_bool(
                notification_data.get(
                    "sound",
                    True,
                ),
                True,
            ),

            task_completion=_safe_bool(
                notification_data.get(
                    "task_completion",
                    True,
                ),
                True,
            ),

            errors=_safe_bool(
                notification_data.get(
                    "errors",
                    True,
                ),
                True,
            ),

            reminders=_safe_bool(
                notification_data.get(
                    "reminders",
                    True,
                ),
                True,
            ),
        )

        settings = Settings(
            schema_version=CURRENT_SCHEMA_VERSION,

            app_name=APP_NAME,
            app_version=APP_VERSION,

            voice=voice,
            ai=ai,
            ui=ui,

            privacy=privacy,
            notifications=notifications,

            last_modified=_utc_now(),
        )

        self._enforce_voice_identity()

        return settings

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """Atomically save settings to JSON."""
        with self._lock:
            try:
                self.path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                self._enforce_voice_identity()

                self._settings.schema_version = (
                    CURRENT_SCHEMA_VERSION
                )

                self._settings.app_name = APP_NAME
                self._settings.app_version = APP_VERSION
                self._settings.last_modified = _utc_now()

                payload = json.dumps(
                    asdict(self._settings),
                    indent=2,
                    ensure_ascii=False,
                )

                fd, temp_name = tempfile.mkstemp(
                    prefix=".settings_",
                    suffix=".tmp",
                    dir=str(self.path.parent),
                )

                try:
                    with os.fdopen(
                        fd,
                        "w",
                        encoding="utf-8",
                    ) as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())

                    os.replace(
                        temp_name,
                        self.path,
                    )

                finally:
                    try:
                        if os.path.exists(temp_name):
                            os.unlink(temp_name)
                    except OSError:
                        pass

                self._save_count += 1
                self._last_error = None

                return True

            except OSError as exc:
                self._last_error = str(exc)

                raise SettingsPersistenceError(
                    f"Unable to save settings: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(
        self,
        path: Optional[str] = None,
        *,
        save: bool = True,
    ) -> bool:
        """
        Reset all settings or one section.
        """
        with self._lock:
            if path is None:
                self._settings = Settings()
                self._enforce_voice_identity()

            else:
                parts = self._split_path(path)

                if len(parts) != 1:
                    raise SettingsValidationError(
                        "Reset supports only top-level sections."
                    )

                section_name = parts[0]

                defaults = Settings()

                if not hasattr(
                    defaults,
                    section_name,
                ):
                    raise SettingsValidationError(
                        f"Unknown settings section: {section_name}"
                    )

                setattr(
                    self._settings,
                    section_name,
                    _deep_copy(
                        getattr(
                            defaults,
                            section_name,
                        )
                    ),
                )

                self._enforce_voice_identity()

            if save:
                self.save()

        return True

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_json(
        self,
        destination: Path | str,
    ) -> Path:
        """Export current settings to another JSON file."""
        destination = Path(destination)

        with self._lock:
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_text(
                json.dumps(
                    asdict(self._settings),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return destination

    # ------------------------------------------------------------------
    # Corrupt file backup
    # ------------------------------------------------------------------

    def _backup_corrupt_file(self) -> Optional[Path]:
        """Backup an invalid settings file."""
        if not self.path.exists():
            return None

        try:
            timestamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

            backup = self.path.with_name(
                f"{self.path.stem}.corrupt.{timestamp}"
                f"{self.path.suffix}"
            )

            shutil.copy2(
                self.path,
                backup,
            )

            return backup

        except OSError:
            return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> Dict[str, Any]:
        """Return safe runtime diagnostics."""
        with self._lock:
            voice = self._settings.voice

            return {
                "app_name": APP_NAME,
                "app_version": APP_VERSION,

                "settings_path": str(
                    self.path.resolve()
                ),

                "exists": self.path.exists(),
                "loaded": self._loaded,

                "schema_version": (
                    self._settings.schema_version
                ),

                "assistant_name": ASSISTANT_NAME,

                "voice": {
                    "wake_word": FIXED_WAKE_WORD,
                    "language": voice.language,
                    "voice_gender": FIXED_VOICE_GENDER,
                    "voice_gender_locked": True,
                    "voice_id_managed_by": (
                        "voice.speaker"
                    ),
                    "enabled": voice.enabled,
                    "rate": voice.rate,
                    "volume": voice.volume,
                },

                "ai_provider": self._settings.ai.provider,

                "save_count": self._save_count,
                "load_count": self._load_count,

                "last_error": self._last_error,
            }


# ---------------------------------------------------------------------------
# Global manager
# ---------------------------------------------------------------------------

settings_manager = SettingsManager()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def get_setting(
    path: str,
    default: Any = None,
) -> Any:
    """Get a setting from the global settings manager."""
    return settings_manager.get(
        path,
        default,
    )


def set_setting(
    path: str,
    value: Any,
    *,
    save: bool = True,
) -> bool:
    """Set one global setting."""
    return settings_manager.set(
        path,
        value,
        save=save,
    )


def update_settings(
    values: Mapping[str, Any],
    *,
    save: bool = True,
) -> bool:
    """Update multiple global settings."""
    return settings_manager.update(
        values,
        save=save,
    )


def reset_settings(
    path: Optional[str] = None,
    *,
    save: bool = True,
) -> bool:
    """Reset global settings."""
    return settings_manager.reset(
        path,
        save=save,
    )


def get_diagnostics() -> Dict[str, Any]:
    """Return global settings diagnostics."""
    return settings_manager.diagnostics()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Identity
    "ASSISTANT_NAME",
    "FIXED_WAKE_WORD",
    "FIXED_VOICE_GENDER",
    "SUPPORTED_LANGUAGE_CODES",

    # Schema
    "CURRENT_SCHEMA_VERSION",
    "SCHEMA_VERSION",

    # Exceptions
    "SettingsError",
    "SettingsValidationError",
    "SettingsPersistenceError",

    # Dataclasses
    "VoiceSettings",
    "AISettings",
    "UISettings",
    "PrivacySettings",
    "NotificationSettings",
    "Settings",

    # Manager
    "SettingsManager",
    "settings_manager",

    # Helpers
    "get_setting",
    "set_setting",
    "update_settings",
    "reset_settings",
    "get_diagnostics",
]
