"""
settings.py
===========
User-configurable, runtime-mutable preferences for AssistantX (as opposed
to `constants.py`, which holds immutable hard-coded values, and
`secrets.py`, which holds sensitive credentials).

Settings are persisted to `data/settings.json` and are safe to edit by
hand or through the dashboard's Settings screen. This module provides:

    - A typed `Settings` dataclass mirroring the JSON schema.
    - Load/save helpers with sane defaults and corruption recovery.
    - Dot-path get/set helpers for convenience (`settings.get("voice.rate")`).

Usage:
    from config.settings import settings_manager

    settings_manager.load()
    rate = settings_manager.settings.voice.rate
    settings_manager.settings.theme = "light"
    settings_manager.save()
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config.constants import (
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_THEME,
    DEFAULT_WAKE_WORD,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_AI_PROVIDER,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_TEMPERATURE,
    SETTINGS_JSON,
    SPEECH_RATE_WPM,
    SPEECH_VOLUME,
    WAKE_WORD_SENSITIVITY,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Nested settings groups
# --------------------------------------------------------------------------- #

@dataclass
class VoiceSettings:
    enabled: bool = True
    wake_word: str = DEFAULT_WAKE_WORD
    wake_word_sensitivity: float = WAKE_WORD_SENSITIVITY
    language: str = DEFAULT_LANGUAGE_CODE
    rate: int = SPEECH_RATE_WPM
    volume: float = SPEECH_VOLUME
    voice_id: Optional[str] = None  # OS-specific TTS voice identifier
    push_to_talk: bool = False
    noise_suppression: bool = True


@dataclass
class AISettings:
    provider: str = DEFAULT_AI_PROVIDER.value
    gemini_model: str = DEFAULT_GEMINI_MODEL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    max_history_messages: int = 50
    stream_responses: bool = True
    system_persona: str = "default"


@dataclass
class UISettings:
    theme: str = DEFAULT_THEME.value
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT
    window_maximized: bool = False
    font_scale: float = 1.0
    show_typing_indicator: bool = True
    animations_enabled: bool = True
    sidebar_collapsed: bool = False
    accent_color: str = "#6C5CE7"


@dataclass
class PrivacySettings:
    store_conversation_history: bool = True
    store_memory: bool = True
    send_analytics: bool = False
    auto_clear_history_days: Optional[int] = None  # None = never


@dataclass
class NotificationSettings:
    enabled: bool = True
    sound_enabled: bool = True
    reminder_lead_minutes: int = 5
    do_not_disturb: bool = False
    do_not_disturb_start: str = "22:00"
    do_not_disturb_end: str = "07:00"


@dataclass
class Settings:
    """Top-level settings schema. Nested dataclasses group related options."""

    voice: VoiceSettings = field(default_factory=VoiceSettings)
    ai: AISettings = field(default_factory=AISettings)
    ui: UISettings = field(default_factory=UISettings)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)

    startup_on_boot: bool = False
    minimize_to_tray: bool = True
    first_run_completed: bool = False
    schema_version: int = 1
    last_modified: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# --------------------------------------------------------------------------- #
# Persistence manager
# --------------------------------------------------------------------------- #

class SettingsManager:
    """
    Handles loading, saving, and safely mutating the Settings object.

    Thread-safe: a re-entrant lock guards load/save so the dashboard
    (UI thread) and background workers (voice/scheduler threads) can
    both touch settings without corrupting the JSON file.
    """

    def __init__(self, path: Path = SETTINGS_JSON) -> None:
        self._path = path
        self._lock = threading.RLock()
        self.settings: Settings = Settings()

    # -- loading ------------------------------------------------------- #

    def load(self) -> Settings:
        """Load settings from disk, creating defaults if absent/corrupt."""
        with self._lock:
            if not self._path.exists():
                logger.info("No settings file found at %s; creating defaults.", self._path)
                self.settings = Settings()
                self.save()
                return self.settings

            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self.settings = self._from_dict(raw)
                logger.info("Settings loaded from %s.", self._path)
            except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
                logger.error(
                    "Failed to parse settings file (%s). Backing up corrupt "
                    "file and restoring defaults.",
                    exc,
                )
                self._backup_corrupt_file()
                self.settings = Settings()
                self.save()

            return self.settings

    def _backup_corrupt_file(self) -> None:
        if self._path.exists():
            backup_path = self._path.with_suffix(".corrupt.bak")
            try:
                shutil.copy2(self._path, backup_path)
                logger.info("Corrupt settings backed up to %s.", backup_path)
            except OSError as exc:
                logger.warning("Could not back up corrupt settings file: %s", exc)

    @staticmethod
    def _from_dict(raw: dict[str, Any]) -> Settings:
        """Reconstruct a Settings object (with nested dataclasses) from JSON."""
        return Settings(
            voice=VoiceSettings(**raw.get("voice", {})),
            ai=AISettings(**raw.get("ai", {})),
            ui=UISettings(**raw.get("ui", {})),
            privacy=PrivacySettings(**raw.get("privacy", {})),
            notifications=NotificationSettings(**raw.get("notifications", {})),
            startup_on_boot=raw.get("startup_on_boot", False),
            minimize_to_tray=raw.get("minimize_to_tray", True),
            first_run_completed=raw.get("first_run_completed", False),
            schema_version=raw.get("schema_version", 1),
            last_modified=raw.get("last_modified", datetime.utcnow().isoformat()),
        )

    # -- saving ---------------------------------------------------------- #

    def save(self) -> None:
        """Persist the current settings object to disk as pretty JSON."""
        with self._lock:
            self.settings.last_modified = datetime.utcnow().isoformat()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".tmp")
            try:
                tmp_path.write_text(
                    json.dumps(asdict(self.settings), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp_path.replace(self._path)  # atomic on POSIX and Windows
                logger.debug("Settings saved to %s.", self._path)
            except OSError as exc:
                logger.error("Failed to save settings to %s: %s", self._path, exc)

    # -- dot-path convenience access -------------------------------------- #

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """
        Fetch a nested setting via dot notation, e.g. get('voice.rate').
        """
        parts = dotted_key.split(".")
        node: Any = self.settings
        for part in parts:
            if hasattr(node, part):
                node = getattr(node, part)
            else:
                return default
        return node

    def set(self, dotted_key: str, value: Any, autosave: bool = True) -> None:
        """
        Set a nested setting via dot notation, e.g. set('voice.rate', 200).
        """
        parts = dotted_key.split(".")
        node: Any = self.settings
        for part in parts[:-1]:
            node = getattr(node, part)
        setattr(node, parts[-1], value)
        if autosave:
            self.save()

    def reset_to_defaults(self) -> None:
        """Discard all customizations and restore factory defaults."""
        with self._lock:
            self.settings = Settings()
            self.save()
            logger.info("Settings reset to factory defaults.")

    def as_dict(self) -> dict[str, Any]:
        """Return the full settings tree as a plain dict (for the UI/API)."""
        return asdict(self.settings)


# Module-level singleton, mirroring the pattern used in secrets.py.
settings_manager: SettingsManager = SettingsManager()
settings_manager.load()
