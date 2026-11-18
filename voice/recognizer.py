"""
voice/recognizer.py
===================

Professional Speech-to-Text (STT) engine for AssistantX.

Architecture
------------

    Microphone
        │
        ▼
    SpeechRecognizer
        │
        ├── listen()
        │
        ├── transcribe()
        │
        ├── listen_and_transcribe()
        │
        └── transcribe_file()
        │
        ▼
    SpeechRecognition backend
        │
        ├── Google Web Speech API
        ├── Whisper
        └── PocketSphinx
        │
        ▼
    RecognitionResult

Supported Languages
-------------------
AssistantX voice input currently supports:

    bn  -> Bengali
    en  -> English
    hi  -> Hindi

Language aliases such as:

    bn-BD
    en-US
    en-GB
    hi-IN

are normalized internally while preserving the appropriate
recognizer locale through voice.languages.

Design Goals
------------
- Safe microphone handling.
- Thread-safe recognition.
- Lazy dependency loading.
- Runtime language configuration.
- Runtime engine configuration.
- Google / Whisper / Sphinx support.
- Ambient-noise calibration.
- Graceful failure.
- Runtime diagnostics.
- Runtime statistics.
- Audio-file transcription.
- No credentials exposed in diagnostics.
- No hard dependency on SpeechRecognition during import.
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

DEFAULT_LANGUAGE = "en"
DEFAULT_ENGINE = "google"

SUPPORTED_LANGUAGES = frozenset(
    {
        "bn",
        "en",
        "hi",
    }
)

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

_AUTO_LANG_MODEL = None
_AUTO_LANG_LOCALES = {"bn": "bn-BD", "en": "en-US", "hi": "hi-IN"}


def _detect_spoken_locale(audio):
    """Detect the spoken language (bn / en / hi) with Whisper."""
    global _AUTO_LANG_MODEL
    try:
        import io

        if _AUTO_LANG_MODEL is None:
            from faster_whisper import WhisperModel

            _AUTO_LANG_MODEL = WhisperModel(
                "base", device="cpu", compute_type="int8"
            )
        wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
        _segments, info = _AUTO_LANG_MODEL.transcribe(
            io.BytesIO(wav), beam_size=1
        )
        probs = dict(getattr(info, "all_language_probs", None) or [])
        if probs:
            best = max(_AUTO_LANG_LOCALES, key=lambda k: probs.get(k, 0.0))
        else:
            best = info.language
        logger.debug(
            "[LANG] whisper=%s bn=%.2f en=%.2f hi=%.2f -> %s",
            getattr(info, "language", ""),
            probs.get("bn", 0),
            probs.get("en", 0),
            probs.get("hi", 0),
            best,
        )
        return _AUTO_LANG_LOCALES.get(best)
    except Exception as exc:
        logger.debug("[LANG] detection failed: %s", exc)
        return None


MAX_RECOGNITION_RETRIES = 2


# ============================================================================
# Language Aliases
# ============================================================================

_LANGUAGE_ALIASES: dict[str, str] = {
    # Bengali
    "bn": "bn",
    "bn-bd": "bn",
    "bn-in": "bn",
    "bengali": "bn",
    "bangla": "bn",

    # English
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-au": "en",
    "en-ca": "en",
    "en-in": "en",
    "en-nz": "en",
    "english": "en",

    # Hindi
    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
}


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
        Normalized AssistantX language code.

    engine:
        Backend used for recognition.

    duration:
        Transcription duration in seconds.
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
    """
    Normalize a listening timeout into a safe range.
    """

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
    """
    Normalize phrase time limit into a safe range.
    """

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
    """
    Normalize and validate an STT engine name.
    """

    value = str(
        engine or DEFAULT_ENGINE
    ).strip().lower()

    aliases = {
        "google_web": "google",
        "google-web": "google",
        "web": "google",
        "online": "google",
        "local_whisper": "whisper",
        "whisper_local": "whisper",
        "pocketsphinx": "sphinx",
        "pocket_sphinx": "sphinx",
        "pocket-sphinx": "sphinx",
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
    """
    Normalize AssistantX language codes.

    Examples
    --------
    bn-BD -> bn
    en-US -> en
    hi-IN -> hi
    """

    value = str(
        language or DEFAULT_LANGUAGE
    ).strip().lower().replace("_", "-")

    if not value:
        return DEFAULT_LANGUAGE

    normalized = _LANGUAGE_ALIASES.get(
        value
    )

    if normalized:
        return normalized

    base = value.split("-", 1)[0]

    if base in SUPPORTED_LANGUAGES:
        return base

    logger.warning(
        "Unsupported STT language %r. "
        "Falling back to %s.",
        language,
        DEFAULT_LANGUAGE,
    )

    return DEFAULT_LANGUAGE


def _safe_float(
    value: Any,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """
    Convert a value to a bounded float.
    """

    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    return max(
        minimum,
        min(maximum, number),
    )


# ============================================================================
# SpeechRecognizer
# ============================================================================


class SpeechRecognizer:
    """
    High-level, thread-safe Speech-to-Text manager.

    The recognizer is intentionally independent from the TTS speaker.

    JEROX's fixed female voice belongs to ``voice.speaker``.
    This class is responsible only for microphone input and STT.

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

        # Configuration/state lock.
        self._lock = threading.RLock()

        # Audio-operation lock.
        #
        # A physical microphone should not normally be accessed by
        # multiple listen/calibration operations simultaneously.
        self._audio_lock = threading.Lock()

        configured_language = (
            language
            or settings_manager.get(
                "voice.language",
                DEFAULT_LANGUAGE,
            )
        )

        self.language = _normalize_language(
            configured_language
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

        # Runtime state.
        self._listening = False

        # Statistics.
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
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Alias for is_available()."""

        return self.is_available()

    @property
    def listening(self) -> bool:
        """Return whether a microphone operation is currently active."""

        with self._lock:
            return self._listening

    @property
    def language_code(self) -> str:
        """Return the normalized STT language code."""

        with self._lock:
            return self.language

    @property
    def engine_name(self) -> str:
        """Return the currently selected STT engine."""

        with self._lock:
            return self.engine

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_backend(self) -> None:
        """
        Initialize SpeechRecognition and microphone.

        SpeechRecognition is imported lazily so AssistantX can still
        start in text-only mode when voice dependencies are missing.
        """

        with self._lock:
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
                "Failed to create SpeechRecognition recognizer."
            )

            self._recognizer = None
            return

        self._apply_recognizer_settings()

        try:
            self._microphone = sr.Microphone(
                sample_rate=MIC_SAMPLE_RATE
            )

        except (
            OSError,
            AttributeError,
            ImportError,
        ) as exc:

            logger.warning(
                "No usable microphone detected: %s",
                exc,
            )

            self._microphone = None
            return

        with self._lock:
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
                1.9,
            )

            recognizer.pause_threshold = _safe_float(
                pause_threshold,
                default=1.9,
                minimum=0.1,
                maximum=5.0,
            )

        except AttributeError:
            logger.debug(
                "Recognizer does not expose pause_threshold."
            )

        try:
            dynamic_energy = settings_manager.get(
                "voice.dynamic_energy_threshold",
                True,
            )

            recognizer.dynamic_energy_threshold = bool(
                dynamic_energy
            )

        except AttributeError:
            logger.debug(
                "Recognizer does not expose "
                "dynamic_energy_threshold."
            )

        with contextlib.suppress(AttributeError):
            recognizer.non_speaking_duration = 1.0

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True when STT backend and microphone are available.
        """

        with self._lock:
            return bool(
                self._initialized
                and self._sr_module is not None
                and self._recognizer is not None
                and self._microphone is not None
                and not self._shutdown
            )

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
        Change STT language at runtime.

        Supported languages:

            bn
            en
            hi
        """

        normalized = _normalize_language(
            language
        )

        with self._lock:
            self.language = normalized

        if persist:
            self._persist_setting(
                "voice.language",
                normalized,
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
            self._persist_setting(
                "voice.stt_engine",
                normalized,
            )

        logger.info(
            "STT engine changed to %s.",
            normalized,
        )

        return normalized

    @staticmethod
    def _persist_setting(
        key: str,
        value: Any,
    ) -> None:
        """
        Persist a setting while remaining compatible with different
        settings-manager implementations.
        """

        try:
            settings_manager.set(
                key,
                value,
                save=True,
            )

        except TypeError:
            try:
                settings_manager.set(
                    key,
                    value,
                )
            except (
                OSError,
                ValueError,
                TypeError,
            ) as exc:
                logger.warning(
                    "Could not persist setting %s: %s",
                    key,
                    exc,
                )

        except (
            OSError,
            ValueError,
        ) as exc:

            logger.warning(
                "Could not persist setting %s: %s",
                key,
                exc,
            )

    def refresh_settings(self) -> None:
        """
        Reload voice-related STT settings.
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
            str(
                language
                or DEFAULT_LANGUAGE
            )
        )

        try:
            self.set_engine(
                str(
                    engine
                    or DEFAULT_ENGINE
                )
            )

        except RecognitionConfigurationError:
            logger.warning(
                "Invalid configured STT engine: %r. "
                "Keeping current engine=%s.",
                engine,
                self.engine,
            )

        self._apply_recognizer_settings()

    # ------------------------------------------------------------------
    # Language Profile
    # ------------------------------------------------------------------

    def _get_language_profile(self) -> Any:
        """
        Resolve the configured AssistantX language profile.

        The languages module remains the source of truth for
        recognizer-specific locale information.
        """

        try:
            return get_language_profile(
                self.language
            )

        except Exception as exc:
            logger.exception(
                "Could not load language profile for %s.",
                self.language,
            )

            raise RecognitionConfigurationError(
                f"Invalid language profile: "
                f"{self.language}"
            ) from exc

    # ------------------------------------------------------------------
    # Ambient Noise Calibration
    # ------------------------------------------------------------------

    def calibrate_ambient_noise(
        self,
        duration: float = DEFAULT_CALIBRATION_DURATION,
    ) -> bool:
        """
        Calibrate the microphone against ambient noise.

        Returns
        -------
        bool
            True when calibration succeeds.
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

        if not self._audio_lock.acquire(
            blocking=False
        ):
            logger.debug(
                "Cannot calibrate: microphone is busy."
            )
            return False

        try:
            with self._lock:
                microphone = self._microphone
                recognizer = self._recognizer

            if microphone is None or recognizer is None:
                return False

            with self._lock:
                self._listening = True

            try:
                with microphone as source:
                    recognizer.adjust_for_ambient_noise(
                        source,
                        duration=duration,
                    )

                with self._lock:
                    self._calibrated = True
                    self._calibrations += 1

                logger.info(
                    "Ambient noise calibrated. "
                    "energy_threshold=%.1f",
                    recognizer.energy_threshold,
                )

                return True

            finally:
                with self._lock:
                    self._listening = False

        except (
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:

            logger.warning(
                "Ambient noise calibration failed: %s",
                exc,
            )

            return False

        finally:
            self._audio_lock.release()

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

        Raises
        ------
        RecognitionUnavailableError
            When STT or microphone is unavailable.

        RecognitionTimeoutError
            When no speech is detected before timeout.

        RecognitionError
            For other microphone failures.
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

        if not self._audio_lock.acquire(
            blocking=False
        ):
            raise RecognitionError(
                "Microphone is currently busy."
            )

        try:
            with self._lock:
                microphone = self._microphone
                recognizer = self._recognizer
                sr = self._sr_module

                self._listens += 1
                self._listening = True

            if (
                microphone is None
                or recognizer is None
                or sr is None
            ):
                raise RecognitionUnavailableError(
                    "Speech recognition backend "
                    "became unavailable."
                )

            if on_listening_start is not None:
                try:
                    on_listening_start()

                except Exception as exc:
                    logger.debug(
                        "Listening-start callback failed: %s",
                        exc,
                    )

            started_at = time.monotonic()

            try:
                with microphone as source:
                    audio = recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=(
                            phrase_time_limit
                        ),
                    )

                logger.debug(
                    "Audio captured in %.2fs.",
                    time.monotonic()
                    - started_at,
                )

                return audio

            except sr.WaitTimeoutError as exc:
                with self._lock:
                    self._timeouts += 1

                raise RecognitionTimeoutError(
                    "No speech detected within "
                    f"the {timeout}-second timeout window."
                ) from exc

            except (
                OSError,
                RuntimeError,
            ) as exc:

                logger.exception(
                    "Microphone listening failed."
                )

                raise RecognitionError(
                    f"Microphone listening failed: {exc}"
                ) from exc

        finally:
            with self._lock:
                self._listening = False

            self._audio_lock.release()

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
            Optional backend override:

                google
                whisper
                sphinx
        """

        if audio is None:
            raise RecognitionError(
                "Audio data is empty."
            )

        with self._lock:
            sr = self._sr_module
            current_language = self.language
            current_engine = self.engine

        if sr is None:
            raise RecognitionUnavailableError(
                "Speech recognition backend "
                "is not initialized."
            )

        selected_engine = _normalize_engine(
            engine or current_engine
        )

        profile = get_language_profile(
            current_language
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

        text = str(
            text or ""
        ).strip()

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
            language=current_language,
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

        # --------------------------------------------------------------
        # Google
        # --------------------------------------------------------------

        if engine == "google":
            recognizer_locale = getattr(
                profile,
                "recognizer_locale",
                None,
            )

            if not recognizer_locale:
                recognizer_locale = (
                    f"{profile.code}"
                )

            _clip_seconds = len(audio.frame_data) / float(
                audio.sample_rate * audio.sample_width
            )
            logger.debug("[CLIP] %.2fs", _clip_seconds)
            if _clip_seconds < 0.3:
                logger.debug("[CLIP] too short (%.2fs), ignored", _clip_seconds)
                raise RecognitionTimeoutError("Clip too short.")

            if getattr(self, "language", None) in ("auto", None):
                detected_locale = _detect_spoken_locale(audio)
                if detected_locale:
                    recognizer_locale = detected_locale

            try:
                return recognizer.recognize_google(
                    audio,
                    language=recognizer_locale,
                )

            except sr.UnknownValueError as exc:
                raise RecognitionError(
                    "Could not understand the audio."
                ) from exc

            except sr.RequestError as exc:
                raise RecognitionError(
                    "Google speech recognition service "
                    f"error: {exc}"
                ) from exc

        # --------------------------------------------------------------
        # Whisper
        # --------------------------------------------------------------

        if engine == "whisper":
            if not hasattr(
                recognizer,
                "recognize_whisper",
            ):
                raise RecognitionError(
                    "Whisper support is not available "
                    "in the installed SpeechRecognition "
                    "version."
                )

            whisper_language = str(
                getattr(
                    profile,
                    "code",
                    self.language,
                )
            ).split("-")[0]

            try:
                return recognizer.recognize_whisper(
                    audio,
                    language=whisper_language,
                )

            except sr.UnknownValueError as exc:
                raise RecognitionError(
                    "Whisper could not understand the audio."
                ) from exc

            except Exception as exc:
                raise RecognitionError(
                    f"Whisper transcription failed: {exc}"
                ) from exc

        # --------------------------------------------------------------
        # Sphinx
        # --------------------------------------------------------------

        if engine == "sphinx":
            if not hasattr(
                recognizer,
                "recognize_sphinx",
            ):
                raise RecognitionError(
                    "Sphinx support is not available."
                )

            if self.language != "en":
                logger.warning(
                    "Sphinx does not provide reliable native "
                    "bn/hi support through the current "
                    "SpeechRecognition integration. "
                    "Using Sphinx anyway."
                )

            try:
                return recognizer.recognize_sphinx(
                    audio
                )

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
        file_path: str | Path,
        engine: str | None = None,
    ) -> RecognitionResult:
        """
        Transcribe a pre-recorded audio file.

        Supported formats depend on SpeechRecognition and
        the installed audio backend.
        """

        with self._lock:
            sr = self._sr_module
            recognizer = self._recognizer

        if sr is None or recognizer is None:
            raise RecognitionUnavailableError(
                "Speech recognition backend "
                "is not initialized."
            )

        path = Path(file_path).expanduser()

        if not path.exists():
            raise RecognitionError(
                f"Audio file does not exist: {path}"
            )

        if not path.is_file():
            raise RecognitionError(
                f"Audio path is not a file: {path}"
            )

        try:
            with sr.AudioFile(
                str(path)
            ) as source:
                audio = recognizer.record(
                    source
                )

        except (
            OSError,
            ValueError,
            RuntimeError,
        ) as exc:

            raise RecognitionError(
                f"Could not read audio file: {exc}"
            ) from exc

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
            names = (
                sr.Microphone
                .list_microphone_names()
            )

        except (
            AttributeError,
            OSError,
            RuntimeError,
        ) as exc:

            logger.debug(
                "Could not enumerate microphones: %s",
                exc,
            )

            return []

        microphones: list[dict[str, Any]] = []

        for index, name in enumerate(names):
            microphones.append(
                {
                    "index": index,
                    "name": str(name),
                }
            )

        return microphones

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
                total_characters=(
                    self._total_characters
                ),
                total_duration=(
                    self._total_duration
                ),
            )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return safe runtime diagnostics.

        No credentials, audio data, or sensitive information
        are exposed.
        """

        statistics = self.stats()

        with self._lock:
            language = self.language
            engine = self.engine
            initialized = self._initialized
            shutdown = self._shutdown
            calibrated = self._calibrated
            listening = self._listening
            microphone_available = (
                self._microphone is not None
            )
            speech_recognition_available = (
                self._sr_module is not None
            )

        try:
            profile = get_language_profile(
                language
            )

            profile_locale = getattr(
                profile,
                "recognizer_locale",
                None,
            )

        except Exception:
            profile_locale = None

        return {
            "available": self.is_available(),
            "initialized": initialized,
            "shutdown": shutdown,
            "listening": listening,
            "language": language,
            "recognizer_locale": profile_locale,
            "engine": engine,
            "calibrated": calibrated,
            "microphone_available": (
                microphone_available
            ),
            "speech_recognition_available": (
                speech_recognition_available
            ),
            "supported_languages": sorted(
                SUPPORTED_LANGUAGES
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

        SpeechRecognition does not normally require a persistent
        worker thread, so shutdown primarily releases references
        and marks this instance unavailable.
        """

        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True
            self._initialized = False
            self._listening = False

            self._microphone = None
            self._recognizer = None
            self._sr_module = None

        logger.info(
            "Speech recognizer shut down."
        )

    def restart(self) -> bool:
        """
        Reinitialize the STT backend.
        """

        with self._lock:
            self._shutdown = False
            self._initialized = False
            self._listening = False

            self._microphone = None
            self._recognizer = None
            self._sr_module = None

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
    """
    Return global STT availability.
    """

    return recognizer.is_available()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "DEFAULT_ENGINE",
    "DEFAULT_LANGUAGE",
    "SUPPORTED_ENGINES",
    "SUPPORTED_LANGUAGES",
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
