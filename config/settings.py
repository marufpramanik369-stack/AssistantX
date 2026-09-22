"""
AssistantX - Settings Manager
=============================

Centralized runtime configuration and user preferences for AssistantX.

Responsibilities
----------------
- Typed application settings
- Persistent JSON storage
- Thread-safe read/write operations
- Dot-path get/set access
- Validation and normalization
- Corrupt-file recovery
- Atomic file saving
- Schema-version support
- Runtime updates
- Factory reset
- Diagnostics

Settings are stored in:

    data/settings.json

Example
-------

    from config.settings import settings_manager

    # Read
    rate = settings_manager.get("voice.rate")

    # Write
    settings_manager.set("voice.rate", 180)

    # Update several values
    settings_manager.update({
        "ui.theme": "dark",
        "ui.font_scale": 1.1,
    })

    # Reset
    settings_manager.reset_to_defaults()
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.constants import (
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

logger = logging.getLogger(__name__)


# ============================================================
# SETTINGS CONSTANTS
# ============================================================

CURRENT_SCHEMA_VERSION = 1

MIN_FONT_SCALE = 0.5
MAX_FONT_SCALE = 2.0

MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0

MIN_SPEECH_VOLUME = 0.0
MAX_SPEECH_VOLUME = 1.0

MIN_WAKE_WORD_SENSITIVITY = 0.0
MAX_WAKE_WORD_SENSITIVITY = 1.0

MIN_SPEECH_RATE = 50
MAX_SPEECH_RATE = 400


# ============================================================
# EXCEPTIONS
# ============================================================

class SettingsError(Exception):
    """Base exception for settings-related errors."""


class SettingsValidationError(SettingsError):
    """Raised when a setting contains an invalid value."""


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def _utc_now() -> str:
    """
    Return the current UTC timestamp in ISO-8601 format.
    """

    return datetime.now(timezone.utc).isoformat()


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    """
    Clamp a numeric value to a safe range.
    """

    return max(minimum, min(maximum, value))


def _safe_bool(
    value: Any,
    default: bool,
) -> bool:
    """
    Convert common boolean representations safely.
    """

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {
            "true",
            "1",
            "yes",
            "on",
        }:
            return True

        if normalized in {
            "false",
            "0",
            "no",
            "off",
        }:
            return False

    return default


def _safe_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Safely convert a value to integer and optionally clamp it.
    """

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
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """
    Safely convert a value to float and optionally clamp it.
    """

    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default

    if minimum is not None:
        result = max(minimum, result)

    if maximum is not None:
        result = min(maximum, result)

    return result


def _safe_string(
    value: Any,
    default: str,
) -> str:
    """
    Safely normalize a string value.
    """

    if value is None:
        return default

    value = str(value).strip()

    return value if value else default


def _safe_dict(value: Any) -> dict[str, Any]:
    """
    Return a dictionary or an empty dictionary.
    """

    if isinstance(value, Mapping):
        return dict(value)

    return {}


# ============================================================
# VOICE SETTINGS
# ============================================================

@dataclass
class VoiceSettings:
    """Voice recognition and speech synthesis preferences."""

    enabled: bool = True

    wake_word: str = DEFAULT_WAKE_WORD

    wake_word_sensitivity: float = (
        WAKE_WORD_SENSITIVITY
    )

    language: str = DEFAULT_LANGUAGE_CODE

    rate: int = SPEECH_RATE_WPM

    volume: float = SPEECH_VOLUME

    voice_id: str | None = None

    push_to_talk: bool = False

    noise_suppression: bool = True


# ============================================================
# AI SETTINGS
# ============================================================

@dataclass
class AISettings:
    """AI provider and response-generation preferences."""

    provider: str = DEFAULT_AI_PROVIDER.value

    gemini_model: str = DEFAULT_GEMINI_MODEL

    ollama_model: str = DEFAULT_OLLAMA_MODEL

    temperature: float = DEFAULT_TEMPERATURE

    max_history_messages: int = 50

    stream_responses: bool = True

    system_persona: str = "default"


# ============================================================
# UI SETTINGS
# ============================================================

@dataclass
class UISettings:
    """Dashboard appearance and window preferences."""

    theme: str = DEFAULT_THEME.value

    window_width: int = DEFAULT_WINDOW_WIDTH

    window_height: int = DEFAULT_WINDOW_HEIGHT

    window_maximized: bool = False

    font_scale: float = 1.0

    show_typing_indicator: bool = True

    animations_enabled: bool = True

    sidebar_collapsed: bool = False

    accent_color: str = "#4F8CFF"


# ============================================================
# PRIVACY SETTINGS
# ============================================================

@dataclass
class PrivacySettings:
    """Conversation, memory and analytics preferences."""

    store_conversation_history: bool = True

    store_memory: bool = True

    send_analytics: bool = False

    auto_clear_history_days: int | None = None


# ============================================================
# NOTIFICATION SETTINGS
# ============================================================

@dataclass
class NotificationSettings:
    """Notification and Do-Not-Disturb preferences."""

    enabled: bool = True

    sound_enabled: bool = True

    reminder_lead_minutes: int = 5

    do_not_disturb: bool = False

    do_not_disturb_start: str = "22:00"

    do_not_disturb_end: str = "07:00"


# ============================================================
# ROOT SETTINGS
# ============================================================

@dataclass
class Settings:
    """
    Complete AssistantX settings schema.
    """

    voice: VoiceSettings = field(
        default_factory=VoiceSettings
    )

    ai: AISettings = field(
        default_factory=AISettings
    )

    ui: UISettings = field(
        default_factory=UISettings
    )

    privacy: PrivacySettings = field(
        default_factory=PrivacySettings
    )

    notifications: NotificationSettings = field(
        default_factory=NotificationSettings
    )

    startup_on_boot: bool = False

    minimize_to_tray: bool = True

    first_run_completed: bool = False

    schema_version: int = CURRENT_SCHEMA_VERSION

    last_modified: str = field(
        default_factory=_utc_now
    )


# ============================================================
# SETTINGS MANAGER
# ============================================================

class SettingsManager:
    """
    Production-ready AssistantX settings manager.

    Features
    --------
    - Thread-safe
    - Atomic writes
    - Corrupt JSON recovery
    - Automatic defaults
    - Dot-path access
    - Batch updates
    - Validation
    - Diagnostics
    """

    def __init__(
        self,
        path: Path | str = SETTINGS_JSON,
        *,
        auto_load: bool = False,
    ) -> None:

        self._path = Path(path)

        self._lock = threading.RLock()

        self.settings = Settings()

        self._loaded = False

        self._save_count = 0

        self._load_count = 0

        self._last_error: str | None = None

        if auto_load:
            self.load()


    # ========================================================
    # PATH
    # ========================================================

    @property
    def path(self) -> Path:
        """Return the settings file path."""

        return self._path


    # ========================================================
    # LOAD
    # ========================================================

    def load(self) -> Settings:
        """
        Load settings from disk.

        If the file does not exist, default settings are created.

        If the file is corrupt, it is backed up and defaults are
        restored safely.
        """

        with self._lock:

            self._load_count += 1

            if not self._path.exists():

                logger.info(
                    "Settings file not found: %s",
                    self._path,
                )

                self.settings = Settings()

                self.save()

                self._loaded = True

                return self.settings

            try:

                raw_text = self._path.read_text(
                    encoding="utf-8"
                )

                raw = json.loads(raw_text)

                if not isinstance(raw, Mapping):
                    raise SettingsValidationError(
                        "Settings root must be a JSON object."
                    )

                self.settings = self._from_dict(
                    dict(raw)
                )

                self._loaded = True

                self._last_error = None

                logger.info(
                    "Settings loaded from %s.",
                    self._path,
                )

                return self.settings

            except (
                OSError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
                SettingsError,
            ) as exc:

                self._last_error = str(exc)

                logger.error(
                    "Failed to load settings: %s",
                    exc,
                )

                self._backup_corrupt_file()

                self.settings = Settings()

                self.save()

                self._loaded = True

                return self.settings


    # ========================================================
    # CORRUPT FILE BACKUP
    # ========================================================

    def _backup_corrupt_file(self) -> Path | None:
        """
        Back up a corrupt settings file.

        Returns:
            Backup path or None.
        """

        if not self._path.exists():
            return None

        try:

            timestamp = datetime.now(timezone.utc).strftime(
                "%Y%m%d_%H%M%S"
            )

            backup_path = self._path.with_name(
                f"{self._path.stem}.corrupt."
                f"{timestamp}.bak"
            )

            shutil.copy2(
                self._path,
                backup_path,
            )

            logger.warning(
                "Corrupt settings backed up to %s",
                backup_path,
            )

            return backup_path

        except OSError as exc:

            logger.warning(
                "Could not back up corrupt settings: %s",
                exc,
            )

            return None


    # ========================================================
    # DICT -> SETTINGS
    # ========================================================

    @staticmethod
    def _from_dict(
        raw: dict[str, Any],
    ) -> Settings:
        """
        Convert a JSON dictionary into a typed Settings object.

        Invalid individual values fall back to safe defaults
        instead of destroying the entire settings tree.
        """

        defaults = Settings()

        voice_raw = _safe_dict(
            raw.get("voice")
        )

        ai_raw = _safe_dict(
            raw.get("ai")
        )

        ui_raw = _safe_dict(
            raw.get("ui")
        )

        privacy_raw = _safe_dict(
            raw.get("privacy")
        )

        notification_raw = _safe_dict(
            raw.get("notifications")
        )

        # ----------------------------------------------------
        # Voice
        # ----------------------------------------------------

        voice = VoiceSettings(
            enabled=_safe_bool(
                voice_raw.get("enabled"),
                defaults.voice.enabled,
            ),

            wake_word=_safe_string(
                voice_raw.get("wake_word"),
                defaults.voice.wake_word,
            ),

            wake_word_sensitivity=_safe_float(
                voice_raw.get(
                    "wake_word_sensitivity"
                ),
                defaults.voice.wake_word_sensitivity,
                minimum=MIN_WAKE_WORD_SENSITIVITY,
                maximum=MAX_WAKE_WORD_SENSITIVITY,
            ),

            language=_safe_string(
                voice_raw.get("language"),
                defaults.voice.language,
            ),

            rate=_safe_int(
                voice_raw.get("rate"),
                defaults.voice.rate,
                minimum=MIN_SPEECH_RATE,
                maximum=MAX_SPEECH_RATE,
            ),

            volume=_safe_float(
                voice_raw.get("volume"),
                defaults.voice.volume,
                minimum=MIN_SPEECH_VOLUME,
                maximum=MAX_SPEECH_VOLUME,
            ),

            voice_id=(
                str(voice_raw["voice_id"]).strip()
                if voice_raw.get("voice_id")
                else None
            ),

            push_to_talk=_safe_bool(
                voice_raw.get("push_to_talk"),
                defaults.voice.push_to_talk,
            ),

            noise_suppression=_safe_bool(
                voice_raw.get("noise_suppression"),
                defaults.voice.noise_suppression,
            ),
        )

        # ----------------------------------------------------
        # AI
        # ----------------------------------------------------

        ai = AISettings(
            provider=_safe_string(
                ai_raw.get("provider"),
                defaults.ai.provider,
            ),

            gemini_model=_safe_string(
                ai_raw.get("gemini_model"),
                defaults.ai.gemini_model,
            ),

            ollama_model=_safe_string(
                ai_raw.get("ollama_model"),
                defaults.ai.ollama_model,
            ),

            temperature=_safe_float(
                ai_raw.get("temperature"),
                defaults.ai.temperature,
                minimum=MIN_TEMPERATURE,
                maximum=MAX_TEMPERATURE,
            ),

            max_history_messages=_safe_int(
                ai_raw.get("max_history_messages"),
                defaults.ai.max_history_messages,
                minimum=1,
                maximum=10000,
            ),

            stream_responses=_safe_bool(
                ai_raw.get("stream_responses"),
                defaults.ai.stream_responses,
            ),

            system_persona=_safe_string(
                ai_raw.get("system_persona"),
                defaults.ai.system_persona,
            ),
        )

        # ----------------------------------------------------
        # UI
        # ----------------------------------------------------

        ui = UISettings(
            theme=_safe_string(
                ui_raw.get("theme"),
                defaults.ui.theme,
            ),

            window_width=_safe_int(
                ui_raw.get("window_width"),
                defaults.ui.window_width,
                minimum=640,
                maximum=7680,
            ),

            window_height=_safe_int(
                ui_raw.get("window_height"),
                defaults.ui.window_height,
                minimum=480,
                maximum=4320,
            ),

            window_maximized=_safe_bool(
                ui_raw.get("window_maximized"),
                defaults.ui.window_maximized,
            ),

            font_scale=_safe_float(
                ui_raw.get("font_scale"),
                defaults.ui.font_scale,
                minimum=MIN_FONT_SCALE,
                maximum=MAX_FONT_SCALE,
            ),

            show_typing_indicator=_safe_bool(
                ui_raw.get(
                    "show_typing_indicator"
                ),
                defaults.ui.show_typing_indicator,
            ),

            animations_enabled=_safe_bool(
                ui_raw.get("animations_enabled"),
                defaults.ui.animations_enabled,
            ),

            sidebar_collapsed=_safe_bool(
                ui_raw.get("sidebar_collapsed"),
                defaults.ui.sidebar_collapsed,
            ),

            accent_color=_safe_string(
                ui_raw.get("accent_color"),
                defaults.ui.accent_color,
            ),
        )

        # ----------------------------------------------------
        # Privacy
        # ----------------------------------------------------

        auto_clear_days = privacy_raw.get(
            "auto_clear_history_days"
        )

        if auto_clear_days is not None:
            auto_clear_days = _safe_int(
                auto_clear_days,
                0,
                minimum=1,
                maximum=3650,
            )

        privacy = PrivacySettings(
            store_conversation_history=_safe_bool(
                privacy_raw.get(
                    "store_conversation_history"
                ),
                defaults.privacy.store_conversation_history,
            ),

            store_memory=_safe_bool(
                privacy_raw.get("store_memory"),
                defaults.privacy.store_memory,
            ),

            send_analytics=_safe_bool(
                privacy_raw.get("send_analytics"),
                defaults.privacy.send_analytics,
            ),

            auto_clear_history_days=auto_clear_days,
        )

        # ----------------------------------------------------
        # Notifications
        # ----------------------------------------------------

        notifications = NotificationSettings(
            enabled=_safe_bool(
                notification_raw.get("enabled"),
                defaults.notifications.enabled,
            ),

            sound_enabled=_safe_bool(
                notification_raw.get("sound_enabled"),
                defaults.notifications.sound_enabled,
            ),

            reminder_lead_minutes=_safe_int(
                notification_raw.get(
                    "reminder_lead_minutes"
                ),
                defaults.notifications.reminder_lead_minutes,
                minimum=0,
                maximum=1440,
            ),

            do_not_disturb=_safe_bool(
                notification_raw.get("do_not_disturb"),
                defaults.notifications.do_not_disturb,
            ),

            do_not_disturb_start=_safe_string(
                notification_raw.get(
                    "do_not_disturb_start"
                ),
                defaults.notifications.do_not_disturb_start,
            ),

            do_not_disturb_end=_safe_string(
                notification_raw.get(
                    "do_not_disturb_end"
                ),
                defaults.notifications.do_not_disturb_end,
            ),
        )

        # ----------------------------------------------------
        # Root
        # ----------------------------------------------------

        schema_version = _safe_int(
            raw.get("schema_version"),
            CURRENT_SCHEMA_VERSION,
            minimum=1,
        )

        return Settings(
            voice=voice,
            ai=ai,
            ui=ui,
            privacy=privacy,
            notifications=notifications,

            startup_on_boot=_safe_bool(
                raw.get("startup_on_boot"),
                defaults.startup_on_boot,
            ),

            minimize_to_tray=_safe_bool(
                raw.get("minimize_to_tray"),
                defaults.minimize_to_tray,
            ),

            first_run_completed=_safe_bool(
                raw.get("first_run_completed"),
                defaults.first_run_completed,
            ),

            schema_version=schema_version,

            last_modified=_safe_string(
                raw.get("last_modified"),
                _utc_now(),
            ),
        )


    # ========================================================
    # SAVE
    # ========================================================

    def save(self) -> bool:
        """
        Atomically save settings to disk.

        Returns:
            True when successfully saved.
        """

        with self._lock:

            self._path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.settings.last_modified = _utc_now()

            payload = asdict(
                self.settings
            )

            temporary_path = self._path.with_name(
                f"{self._path.name}.tmp"
            )

            try:

                temporary_path.write_text(
                    json.dumps(
                        payload,
                        indent=4,
                        ensure_ascii=False,
                    ) + "\n",
                    encoding="utf-8",
                )

                temporary_path.replace(
                    self._path
                )

                self._save_count += 1

                self._last_error = None

                logger.debug(
                    "Settings saved: %s",
                    self._path,
                )

                return True

            except OSError as exc:

                self._last_error = str(exc)

                logger.error(
                    "Failed to save settings to %s: %s",
                    self._path,
                    exc,
                )

                try:
                    if temporary_path.exists():
                        temporary_path.unlink()
                except OSError:
                    pass

                return False


    # ========================================================
    # GET
    # ========================================================

    def get(
        self,
        dotted_key: str,
        default: Any = None,
    ) -> Any:
        """
        Read a setting using dot notation.

        Example:

            settings_manager.get("voice.rate")

            settings_manager.get(
                "ui.theme",
                "dark",
            )
        """

        if not isinstance(dotted_key, str):
            return default

        dotted_key = dotted_key.strip()

        if not dotted_key:
            return default

        parts = dotted_key.split(".")

        with self._lock:

            node: Any = self.settings

            for part in parts:

                if isinstance(node, Mapping):

                    if part not in node:
                        return default

                    node = node[part]

                elif hasattr(node, part):

                    node = getattr(
                        node,
                        part,
                    )

                else:

                    return default

            return node


    # ========================================================
    # SET
    # ========================================================

    def set(
        self,
        dotted_key: str,
        value: Any,
        *,
        autosave: bool = True,
    ) -> bool:
        """
        Set a setting using dot notation.

        Example:

            settings_manager.set(
                "ui.theme",
                "dark",
            )
        """

        if not isinstance(dotted_key, str):
            raise SettingsValidationError(
                "Setting key must be a string."
            )

        dotted_key = dotted_key.strip()

        if not dotted_key:
            raise SettingsValidationError(
                "Setting key cannot be empty."
            )

        parts = dotted_key.split(".")

        if any(
            not part.strip()
            for part in parts
        ):
            raise SettingsValidationError(
                f"Invalid setting path: {dotted_key}"
            )

        with self._lock:

            node: Any = self.settings

            for part in parts[:-1]:

                if not hasattr(node, part):

                    raise SettingsValidationError(
                        f"Unknown setting group: {part}"
                    )

                node = getattr(
                    node,
                    part,
                )

            final_key = parts[-1]

            if not hasattr(node, final_key):

                raise SettingsValidationError(
                    f"Unknown setting: {dotted_key}"
                )

            old_value = getattr(
                node,
                final_key,
            )

            normalized = self._normalize_value(
                dotted_key,
                value,
                old_value,
            )

            setattr(
                node,
                final_key,
                normalized,
            )

            logger.debug(
                "Setting changed: %s = %r",
                dotted_key,
                normalized,
            )

            if autosave:
                return self.save()

            return True


    # ========================================================
    # VALUE NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalize_value(
        key: str,
        value: Any,
        current: Any,
    ) -> Any:
        """
        Validate and normalize a setting value.
        """

        # Boolean
        if isinstance(current, bool):

            return _safe_bool(
                value,
                current,
            )

        # Integer
        if isinstance(current, int) and not isinstance(
            current,
            bool,
        ):

            return _safe_int(
                value,
                current,
            )

        # Float
        if isinstance(current, float):

            return _safe_float(
                value,
                current,
            )

        # Optional string
        if current is None:

            if value is None:
                return None

            return str(value).strip()

        # String
        if isinstance(current, str):

            value = str(value).strip()

            if not value:
                raise SettingsValidationError(
                    f"Setting '{key}' cannot be empty."
                )

            return value

        return value


    # ========================================================
    # BATCH UPDATE
    # ========================================================

    def update(
        self,
        values: Mapping[str, Any],
        *,
        autosave: bool = True,
    ) -> bool:
        """
        Update multiple settings at once.

        Example:

            settings_manager.update({
                "ui.theme": "dark",
                "ui.font_scale": 1.1,
                "voice.enabled": True,
            })
        """

        if not isinstance(values, Mapping):
            raise SettingsValidationError(
                "update() expects a mapping."
            )

        with self._lock:

            for key, value in values.items():

                self.set(
                    str(key),
                    value,
                    autosave=False,
                )

            if autosave:
                return self.save()

            return True


    # ========================================================
    # RESET
    # ========================================================

    def reset_to_defaults(
        self,
        *,
        autosave: bool = True,
    ) -> bool:
        """
        Restore all settings to factory defaults.
        """

        with self._lock:

            self.settings = Settings()

            logger.info(
                "AssistantX settings reset to defaults."
            )

            if autosave:
                return self.save()

            return True


    # ========================================================
    # DICTIONARY
    # ========================================================

    def as_dict(self) -> dict[str, Any]:
        """
        Return settings as a detached dictionary.
        """

        with self._lock:

            return asdict(
                self.settings
            )


    # ========================================================
    # EXPORT
    # ========================================================

    def export_json(
        self,
        path: Path | str,
    ) -> Path:
        """
        Export current settings to another JSON file.
        """

        target = Path(path)

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:

            target.write_text(
                json.dumps(
                    asdict(self.settings),
                    indent=4,
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

        logger.info(
            "Settings exported to %s",
            target,
        )

        return target


    # ========================================================
    # STATUS
    # ========================================================

    @property
    def loaded(self) -> bool:
        """Return whether settings have been loaded."""

        with self._lock:
            return self._loaded


    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    def diagnostics(self) -> dict[str, Any]:
        """
        Return settings subsystem diagnostics.
        """

        with self._lock:

            return {
                "component": "SettingsManager",

                "status": (
                    "healthy"
                    if self._last_error is None
                    else "degraded"
                ),

                "path": str(self._path),

                "exists": self._path.exists(),

                "loaded": self._loaded,

                "schema_version": (
                    self.settings.schema_version
                ),

                "current_schema_version": (
                    CURRENT_SCHEMA_VERSION
                ),

                "load_count": self._load_count,

                "save_count": self._save_count,

                "last_error": self._last_error,
            }


# ============================================================
# GLOBAL SETTINGS MANAGER
# ============================================================

settings_manager = SettingsManager(
    SETTINGS_JSON
)


# ============================================================
# INITIAL LOAD
# ============================================================

settings_manager.load()


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def get_setting(
    key: str,
    default: Any = None,
) -> Any:
    """
    Convenience wrapper for settings_manager.get().
    """

    return settings_manager.get(
        key,
        default,
    )


def set_setting(
    key: str,
    value: Any,
    *,
    autosave: bool = True,
) -> bool:
    """
    Convenience wrapper for settings_manager.set().
    """

    return settings_manager.set(
        key,
        value,
        autosave=autosave,
    )


def update_settings(
    values: Mapping[str, Any],
    *,
    autosave: bool = True,
) -> bool:
    """
    Convenience wrapper for batch settings updates.
    """

    return settings_manager.update(
        values,
        autosave=autosave,
    )


def reset_settings() -> bool:
    """
    Reset settings to factory defaults.
    """

    return settings_manager.reset_to_defaults()


def diagnostics() -> dict[str, Any]:
    """
    Return settings diagnostics.
    """

    return settings_manager.diagnostics()


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    # Constants
    "CURRENT_SCHEMA_VERSION",
    # Dataclasses
    "AISettings",
    "NotificationSettings",
    "PrivacySettings",
    "Settings",
    # Exceptions
    "SettingsError",
    "SettingsValidationError",
    "UISettings",
    "VoiceSettings",
    "diagnostics",
    # Helpers
    "get_setting",
    "reset_settings",
    "set_setting",
    "update_settings",
]
