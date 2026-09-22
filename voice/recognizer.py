"""
recognizer.py
=============

Professional Speech-to-Text (STT) engine for AssistantX.

Backend
-------
Built around the ``SpeechRecognition`` package while keeping the
recognition layer backend-agnostic.

Supported backends depend on installed SpeechRecognition features:

    google  -> Google Web Speech API (online)
    whisper -> Whisper backend (local, if supported/installed)
    sphinx  -> PocketSphinx (offline, if installed)

Architecture
------------

    Microphone
        |
        v
    SpeechRecognizer
        |
        +---- listen()
        |
        +---- transcribe()
        |
        +---- listen_and_transcribe()
        |
        v
    SpeechRecognition backend
        |
        v
    RecognitionResult

Design goals
------------
- Safe microphone handling.
- Thread-safe recognition.
- Runtime language/engine configuration.
- Offline-capable backend support.
- Ambient noise calibration.
- Graceful failure.
- Useful diagnostics.
- Runtime statistics.
- No hard dependency on SpeechRecognition during module import.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.constants import (
    LISTEN_TIMEOUT_SECONDS,
    MIC_SAMPLE_RATE,
    PHRASE_TIME_LIMIT_SECONDS,
)
from config.settings import settings_manager
from voice.languages import get_language_profile
from voice.noise_filter import AmbientNoiseCalibrator

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_LANGUAGE = "en-US"
DEFAULT_ENGINE = "google"

SUPPORTED_ENGINES = frozenset(
    {
        "google",
        "whisper",
        "sphinx",
    }
)

MIN_TIMEOUT = 1
MAX_TIMEOUT = 120

MIN_PHRASE_TIME_LIMIT = 1
MAX_PHRASE_TIME_LIMIT = 120

DEFAULT_CALIBRATION_DURATION = 1.0

MAX_RECOGNITION_RETRIES = 2


# ============================================================================
# Exceptions
# ============================================================================


class RecognitionError(RuntimeError):
    """
    Base exception for STT-related failures.
    """


class RecognitionUnavailableError(RecognitionError):
    """
    Raised when SpeechRecognition or a microphone is unavailable.
    """


class RecognitionConfigurationError(RecognitionError):
    """
    Raised when STT configuration is invalid.
    """


class RecognitionTimeoutError(RecognitionError):
    """
    Raised when no speech is detected before the timeout.
    """


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """
    Result returned by the speech recognition pipeline.

    Attributes
    ----------
    text:
        Transcribed text.
    confidence:
        Confidence score when available.
    language:
        Resolved language code.
    engine:
        Backend used for recognition.
    duration:
        Recognition/transcription duration in seconds.
    """

    text: str
    confidence: float | None = None
    language: str = DEFAULT_LANGUAGE
    engine: str = DEFAULT_ENGINE
    duration: float = 0.0

    @property
    def success(self) -> bool:
        """Return True when usable text was produced."""

        return bool(self.text.strip())


@dataclass(frozen=True, slots=True)
class RecognitionStats:
    """
    Runtime statistics for the STT subsystem.
    """

    listens: int = 0
    successful_transcriptions: int = 0
    failed_transcriptions: int = 0
    timeouts: int = 0
    calibrations: int = 0
    total_characters: int = 0
    total_duration: float = 0.0


# ============================================================================
# Utility Helpers
# ============================================================================


def _safe_timeout(
    value: Any,
    default: int,
) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default

    return max(
        MIN_TIMEOUT,
        min(MAX_TIMEOUT, value),
    )


def _safe_phrase_time_limit(
    value: Any,
    default: int,
) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default

    return max(
        MIN_PHRASE_TIME_LIMIT,
        min(MAX_PHRASE_TIME_LIMIT, value),
    )


def _normalize_engine(
    engine: str | None,
) -> str:
    value = str(
        engine or DEFAULT_ENGINE
    ).strip().lower()

    aliases = {
        "google_web": "google",
        "google-web": "google",
        "web": "google",
        "local_whisper": "whisper",
        "pocketsphinx": "sphinx",
        "pocket_sphinx": "sphinx",
    }

    value = aliases.get(
        value,
        value,
    )

    if value not in SUPPORTED_ENGINES:
        raise RecognitionConfigurationError(
            f"Unsupported recognition engine: {engine!r}. "
            f"Supported engines: {sorted(SUPPORTED_ENGINES)}"
        )

    return value


def _normalize_language(
    language: str | None,
) -> str:
    value = str(
        language or DEFAULT_LANGUAGE
    ).strip()

    return value or DEFAULT_LANGUAGE


# ============================================================================
# SpeechRecognizer
# ============================================================================


class SpeechRecognizer:
    """
    High-level, thread-safe Speech-to-Text manager.

    Example
    -------

        recognizer = SpeechRecognizer()

        result = recognizer.listen_and_transcribe()

        print(result.text)
    """

    def __init__(
        self,
        language: str | None = None,
        engine: str | None = None,
        *,
        auto_initialize: bool = True,
    ) -> None:

        self._lock = threading.RLock()

        self.language = _normalize_language(
            language
            or settings_manager.get(
                "voice.language",
                DEFAULT_LANGUAGE,
            )
        )

        configured_engine = (
            engine
            or settings_manager.get(
                "voice.stt_engine",
                DEFAULT_ENGINE,
            )
        )

        try:
            self.engine = _normalize_engine(
                configured_engine
            )
        except RecognitionConfigurationError:
            logger.warning(
                "Invalid configured STT engine %r; "
                "falling back to %s.",
                configured_engine,
                DEFAULT_ENGINE,
            )
            self.engine = DEFAULT_ENGINE

        self._sr_module: Any = None
        self._recognizer: Any = None
        self._microphone: Any = None

        self._noise_calibrator = (
            AmbientNoiseCalibrator()
        )

        self._initialized = False
        self._shutdown = False
        self._calibrated = False

        # Statistics
        self._listens = 0
        self._successful_transcriptions = 0
        self._failed_transcriptions = 0
        self._timeouts = 0
        self._calibrations = 0
        self._total_characters = 0
        self._total_duration = 0.0

        if auto_initialize:
            self._init_backend()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_backend(self) -> None:
        """
        Initialize SpeechRecognition and microphone.

        Import is intentionally lazy so AssistantX can still start in
        text-only mode when voice dependencies are missing.
        """

        if self._shutdown:
            return

        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            logger.warning(
                "SpeechRecognition is not installed. "
                "Voice input is unavailable. "
                "Install with: "
                "pip install SpeechRecognition"
            )
            return

        self._sr_module = sr

        try:
            self._recognizer = sr.Recognizer()
        except Exception:
            logger.exception(
                "Failed to create speech recognizer",
            )
            self._recognizer = None
            return

        self._apply_recognizer_settings()

        try:
            self._microphone = sr.Microphone(
                sample_rate=MIC_SAMPLE_RATE
            )
        except (OSError, AttributeError, ImportError) as exc:
            logger.warning(
                "No usable microphone detected: %s",
                exc,
            )
            self._microphone = None
            return

        self._initialized = True

        logger.info(
            "Speech recognizer initialized "
            "(engine=%s, language=%s, sample_rate=%s).",
            self.engine,
            self.language,
            MIC_SAMPLE_RATE,
        )

    def _apply_recognizer_settings(self) -> None:
        """
        Apply safe SpeechRecognition settings.
        """

        recognizer = self._recognizer

        if recognizer is None:
            return

        try:
            pause_threshold = settings_manager.get(
                "voice.pause_threshold",
                0.8,
            )

            recognizer.pause_threshold = max(
                0.1,
                min(5.0, float(pause_threshold)),
            )
        except (TypeError, ValueError, AttributeError):
            recognizer.pause_threshold = 0.8

        try:
            dynamic_energy = settings_manager.get(
                "voice.dynamic_energy_threshold",
                True,
            )

            recognizer.dynamic_energy_threshold = bool(
                dynamic_energy
            )
        except (TypeError, ValueError, AttributeError):
            recognizer.dynamic_energy_threshold = True

        with contextlib.suppress(AttributeError):
            recognizer.non_speaking_duration = 0.5

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True when both STT backend and microphone are available.
        """

        with self._lock:
            return bool(
                self._initialized
                and self._sr_module is not None
                and self._recognizer is not None
                and self._microphone is not None
                and not self._shutdown
            )

    @property
    def available(self) -> bool:
        """Alias for is_available()."""

        return self.is_available()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_language(
        self,
        language: str,
        *,
        persist: bool = False,
    ) -> str:
        """
        Change recognition language at runtime.
        """

        normalized = _normalize_language(
            language
        )

        with self._lock:
            self.language = normalized

        if persist:
            try:
                settings_manager.set(
                    "voice.language",
                    normalized,
                    save=True,
                )
            except TypeError:
                settings_manager.set(
                    "voice.language",
                    normalized,
                )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Could not persist STT language: %s",
                    exc,
                )

        logger.info(
            "STT language changed to %s.",
            normalized,
        )

        return normalized

    def set_engine(
        self,
        engine: str,
        *,
        persist: bool = False,
    ) -> str:
        """
        Change recognition backend at runtime.
        """

        normalized = _normalize_engine(
            engine
        )

        with self._lock:
            self.engine = normalized

        if persist:
            try:
                settings_manager.set(
                    "voice.stt_engine",
                    normalized,
                    save=True,
                )
            except TypeError:
                settings_manager.set(
                    "voice.stt_engine",
                    normalized,
                )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Could not persist STT engine: %s",
                    exc,
                )

        logger.info(
            "STT engine changed to %s.",
            normalized,
        )

        return normalized

    def refresh_settings(self) -> None:
        """
        Reload voice-related settings without recreating the recognizer.
        """

        language = settings_manager.get(
            "voice.language",
            DEFAULT_LANGUAGE,
        )

        engine = settings_manager.get(
            "voice.stt_engine",
            DEFAULT_ENGINE,
        )

        self.set_language(
            str(language or DEFAULT_LANGUAGE)
        )

        try:
            self.set_engine(
                str(engine or DEFAULT_ENGINE)
            )
        except RecognitionConfigurationError:
            logger.warning(
                "Invalid configured STT engine: %r",
                engine,
            )

        self._apply_recognizer_settings()

    # ------------------------------------------------------------------
    # Ambient Noise Calibration
    # ------------------------------------------------------------------

    def calibrate_ambient_noise(
        self,
        duration: float = DEFAULT_CALIBRATION_DURATION,
    ) -> bool:
        """
        Calibrate microphone against ambient noise.

        Returns True on success.
        """

        if not self.is_available():
            logger.debug(
                "Cannot calibrate: microphone unavailable."
            )
            return False

        try:
            duration = max(
                0.1,
                min(30.0, float(duration)),
            )
        except (TypeError, ValueError):
            duration = DEFAULT_CALIBRATION_DURATION

        with self._lock:
            microphone = self._microphone
            recognizer = self._recognizer

        try:
            with microphone as source:
                recognizer.adjust_for_ambient_noise(
                    source,
                    duration=duration,
                )

            self._calibrated = True

            with self._lock:
                self._calibrations += 1

            logger.info(
                "Ambient noise calibrated. "
                "energy_threshold=%.1f",
                recognizer.energy_threshold,
            )

            return True

        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "Ambient noise calibration failed: %s",
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Listening
    # ------------------------------------------------------------------

    def listen(
        self,
        timeout: int = LISTEN_TIMEOUT_SECONDS,
        phrase_time_limit: int = PHRASE_TIME_LIMIT_SECONDS,
        on_listening_start: Callable[[], None] | None = None,
    ) -> Any:
        """
        Capture one audio utterance.

        Returns
        -------
        AudioData

        Raises
        ------
        RecognitionUnavailableError
        RecognitionTimeoutError
        RecognitionError
        """

        if not self.is_available():
            raise RecognitionUnavailableError(
                "No microphone or speech recognition "
                "backend is available."
            )

        timeout = _safe_timeout(
            timeout,
            LISTEN_TIMEOUT_SECONDS,
        )

        phrase_time_limit = _safe_phrase_time_limit(
            phrase_time_limit,
            PHRASE_TIME_LIMIT_SECONDS,
        )

        callback = on_listening_start

        if callback is not None:
            try:
                callback()
            except (RuntimeError, TypeError, ValueError) as exc:
                logger.debug(
                    "Listening-start callback failed: %s",
                    exc,
                )

        with self._lock:
            microphone = self._microphone
            recognizer = self._recognizer
            sr = self._sr_module
            self._listens += 1

        started_at = time.monotonic()

        try:
            # SpeechRecognition / microphone access should not happen
            # concurrently on the same device.
            with self._lock, microphone as source:
                audio = recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )

            logger.debug(
                "Audio captured in %.2fs.",
                time.monotonic() - started_at,
            )

            return audio

        except sr.WaitTimeoutError as exc:
            with self._lock:
                self._timeouts += 1

            raise RecognitionTimeoutError(
                "No speech detected within "
                f"the {timeout}-second timeout window."
            ) from exc

        except (OSError, RuntimeError) as exc:
            logger.exception(
                "Microphone listening failed.",
            )

            raise RecognitionError(
                f"Microphone listening failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio: Any,
        engine: str | None = None,
    ) -> RecognitionResult:
        """
        Transcribe previously captured AudioData.

        Parameters
        ----------
        audio:
            AudioData returned by listen().
        engine:
            google, whisper or sphinx.
        """

        if audio is None:
            raise RecognitionError(
                "Audio data is empty."
            )

        if self._sr_module is None:
            raise RecognitionUnavailableError(
                "Speech recognition backend "
                "is not initialized."
            )

        selected_engine = _normalize_engine(
            engine or self.engine
        )

        profile = get_language_profile(
            self.language
        )

        started_at = time.monotonic()

        try:
            text = self._transcribe_with_engine(
                audio,
                selected_engine,
                profile,
            )

        except RecognitionError:
            with self._lock:
                self._failed_transcriptions += 1
            raise

        except Exception as exc:
            with self._lock:
                self._failed_transcriptions += 1

            raise RecognitionError(
                f"Speech transcription failed: {exc}"
            ) from exc

        duration = (
            time.monotonic()
            - started_at
        )

        text = str(text or "").strip()

        if not text:
            with self._lock:
                self._failed_transcriptions += 1

            raise RecognitionError(
                "Speech recognition returned empty text."
            )

        with self._lock:
            self._successful_transcriptions += 1
            self._total_characters += len(text)
            self._total_duration += duration

        return RecognitionResult(
            text=text,
            confidence=None,
            language=profile.code,
            engine=selected_engine,
            duration=duration,
        )

    def _transcribe_with_engine(
        self,
        audio: Any,
        engine: str,
        profile: Any,
    ) -> str:
        """
        Dispatch transcription to the selected backend.
        """

        recognizer = self._recognizer
        sr = self._sr_module

        if recognizer is None or sr is None:
            raise RecognitionUnavailableError(
                "Speech recognition backend is unavailable."
            )

        if engine == "google":
            try:
                return recognizer.recognize_google(
                    audio,
                    language=profile.recognizer_locale,
                )
            except sr.UnknownValueError as exc:
                raise RecognitionError(
                    "Could not understand the audio."
                ) from exc
            except sr.RequestError as exc:
                raise RecognitionError(
                    f"Google speech recognition service "
                    f"error: {exc}"
                ) from exc

        if engine == "whisper":
            try:
                return recognizer.recognize_whisper(
                    audio,
                    language=profile.code.split("-")[0],
                )
            except AttributeError as exc:
                raise RecognitionError(
                    "Whisper support is not available in the "
                    "installed SpeechRecognition version."
                ) from exc
            except sr.UnknownValueError as exc:
                raise RecognitionError(
                    "Whisper could not understand the audio."
                ) from exc
            except Exception as exc:
                raise RecognitionError(
                    f"Whisper transcription failed: {exc}"
                ) from exc

        if engine == "sphinx":
            try:
                return recognizer.recognize_sphinx(
                    audio
                )
            except AttributeError as exc:
                raise RecognitionError(
                    "Sphinx support is not available."
                ) from exc
            except sr.UnknownValueError as exc:
                raise RecognitionError(
                    "Sphinx could not understand the audio."
                ) from exc
            except Exception as exc:
                raise RecognitionError(
                    f"Sphinx transcription failed: {exc}"
                ) from exc

        raise RecognitionConfigurationError(
            f"Unsupported recognition engine: {engine}"
        )

    # ------------------------------------------------------------------
    # Combined Pipeline
    # ------------------------------------------------------------------

    def listen_and_transcribe(
        self,
        engine: str | None = None,
        timeout: int = LISTEN_TIMEOUT_SECONDS,
        phrase_time_limit: int = PHRASE_TIME_LIMIT_SECONDS,
        on_listening_start: Callable[[], None] | None = None,
    ) -> RecognitionResult:
        """
        Capture and transcribe one utterance.
        """

        audio = self.listen(
            timeout=timeout,
            phrase_time_limit=phrase_time_limit,
            on_listening_start=on_listening_start,
        )

        return self.transcribe(
            audio,
            engine=engine,
        )

    # ------------------------------------------------------------------
    # Audio Files
    # ------------------------------------------------------------------

    def transcribe_file(
        self,
        file_path: str,
        engine: str | None = None,
    ) -> RecognitionResult:
        """
        Transcribe a pre-recorded audio file.

        Supported formats depend on SpeechRecognition / audio backend.
        """

        if self._sr_module is None:
            raise RecognitionUnavailableError(
                "Speech recognition backend "
                "is not initialized."
            )

        path = Path(file_path)

        if not path.exists():
            raise RecognitionError(
                f"Audio file does not exist: {path}"
            )

        if not path.is_file():
            raise RecognitionError(
                f"Audio path is not a file: {path}"
            )

        sr = self._sr_module

        try:
            with sr.AudioFile(
                str(path)
            ) as source:
                audio = self._recognizer.record(
                    source
                )
        except Exception as exc:
            raise RecognitionError(
                f"Could not read audio file: {exc}"
            ) from exc

        return self.transcribe(
            audio,
            engine=engine,
        )

    # ------------------------------------------------------------------
    # Microphone Information
    # ------------------------------------------------------------------

    def list_microphones(self) -> list[dict[str, Any]]:
        """
        Return available microphone devices.

        This is useful for a future AssistantX settings page.
        """

        sr = self._sr_module

        if sr is None:
            return []

        try:
            names = sr.Microphone.list_microphone_names()
        except (AttributeError, OSError, RuntimeError) as exc:
            logger.debug(
                "Could not enumerate microphones: %s",
                exc,
            )
            return []

        return [
            {
                "index": index,
                "name": str(name),
            }
            for index, name in enumerate(names)
        ]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> RecognitionStats:
        """
        Return a snapshot of STT statistics.
        """

        with self._lock:
            return RecognitionStats(
                listens=self._listens,
                successful_transcriptions=(
                    self._successful_transcriptions
                ),
                failed_transcriptions=(
                    self._failed_transcriptions
                ),
                timeouts=self._timeouts,
                calibrations=self._calibrations,
                total_characters=self._total_characters,
                total_duration=self._total_duration,
            )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return safe runtime diagnostics.

        No credentials or sensitive data are exposed.
        """

        statistics = self.stats()

        return {
            "available": self.is_available(),
            "initialized": self._initialized,
            "shutdown": self._shutdown,
            "language": self.language,
            "engine": self.engine,
            "calibrated": self._calibrated,
            "microphone_available": (
                self._microphone is not None
            ),
            "speech_recognition_available": (
                self._sr_module is not None
            ),
            "supported_engines": sorted(
                SUPPORTED_ENGINES
            ),
            "stats": {
                "listens": statistics.listens,
                "successful_transcriptions": (
                    statistics.successful_transcriptions
                ),
                "failed_transcriptions": (
                    statistics.failed_transcriptions
                ),
                "timeouts": statistics.timeouts,
                "calibrations": statistics.calibrations,
                "total_characters": (
                    statistics.total_characters
                ),
                "total_duration": (
                    statistics.total_duration
                ),
            },
        }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        Release microphone/STT resources.

        SpeechRecognition itself does not normally require a persistent
        worker, so shutdown primarily marks this instance unavailable.
        """

        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True

            self._microphone = None
            self._recognizer = None
            self._sr_module = None
            self._initialized = False

        logger.info(
            "Speech recognizer shut down."
        )

    def restart(self) -> bool:
        """
        Reinitialize the STT backend.
        """

        with self._lock:
            self._shutdown = False

        self._sr_module = None
        self._recognizer = None
        self._microphone = None
        self._initialized = False

        self._init_backend()

        return self.is_available()


# ============================================================================
# Module-level Singleton
# ============================================================================

recognizer = SpeechRecognizer()


# ============================================================================
# Convenience Functions
# ============================================================================


def listen_and_transcribe(
    engine: str | None = None,
    timeout: int = LISTEN_TIMEOUT_SECONDS,
    phrase_time_limit: int = PHRASE_TIME_LIMIT_SECONDS,
    on_listening_start: Callable[[], None] | None = None,
) -> RecognitionResult:
    """
    Convenience wrapper around the global recognizer.
    """

    return recognizer.listen_and_transcribe(
        engine=engine,
        timeout=timeout,
        phrase_time_limit=phrase_time_limit,
        on_listening_start=on_listening_start,
    )


def is_available() -> bool:
    """Return global STT availability."""

    return recognizer.is_available()


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "SUPPORTED_ENGINES",
    "RecognitionConfigurationError",
    "RecognitionError",
    "RecognitionResult",
    "RecognitionStats",
    "RecognitionTimeoutError",
    "RecognitionUnavailableError",
    "SpeechRecognizer",
    "is_available",
    "listen_and_transcribe",
    "recognizer",
]
