"""
voice/wake_word.py
==================

Professional wake-word detection subsystem for AssistantX.

Supported detection backends
-----------------------------
1. Fallback STT
   Uses the normal AssistantX recognizer and fuzzy matching.
   No additional wake-word dependency is required.

2. Porcupine
   Optional dedicated wake-word engine.
   Requires:
       - pvporcupine
       - pyaudio
       - PICOVOICE_ACCESS_KEY

The detector automatically selects the best available backend and falls
back to STT when the dedicated engine cannot be initialized.

Design goals
------------
- Thread-safe lifecycle
- Safe start/stop/pause/resume
- Runtime wake-word configuration
- Graceful backend fallback
- Proper native resource cleanup
- Callback isolation
- Diagnostics support
- No crashes from microphone/backend errors
"""

from __future__ import annotations

import difflib
import importlib
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config.constants import (
    DEFAULT_WAKE_WORD,
    WAKE_WORD_SENSITIVITY,
)
from config.settings import settings_manager
from voice.recognizer import (
    RecognitionError,
    recognizer as default_recognizer,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Types
# ============================================================================

WakeWordCallback = Callable[[], None]


# ============================================================================
# Exceptions
# ============================================================================


class WakeWordError(RuntimeError):
    """Base exception for wake-word subsystem errors."""


class WakeWordConfigurationError(WakeWordError):
    """Raised when wake-word configuration is invalid."""


# ============================================================================
# Statistics
# ============================================================================


@dataclass(slots=True)
class WakeWordStats:
    """Runtime statistics for the wake-word detector."""

    detections: int = 0
    callback_errors: int = 0
    recognition_errors: int = 0
    backend_errors: int = 0
    fallback_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "detections": self.detections,
            "callback_errors": self.callback_errors,
            "recognition_errors": self.recognition_errors,
            "backend_errors": self.backend_errors,
            "fallback_count": self.fallback_count,
        }


# ============================================================================
# Helpers
# ============================================================================


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value to a safe range."""

    return max(minimum, min(maximum, value))


def _normalize_phrase(value: str) -> str:
    """
    Normalize a wake phrase.

    Raises:
        WakeWordConfigurationError:
            If the phrase is empty or excessively long.
    """

    if not isinstance(value, str):
        raise WakeWordConfigurationError(
            "Wake phrase must be a string."
        )

    phrase = " ".join(value.strip().lower().split())

    if not phrase:
        raise WakeWordConfigurationError(
            "Wake phrase cannot be empty."
        )

    if len(phrase) > 200:
        raise WakeWordConfigurationError(
            "Wake phrase is too long."
        )

    return phrase


def _fuzzy_contains_wake_word(
    heard_text: str,
    wake_phrase: str,
    sensitivity: float,
) -> bool:
    """
    Check whether the recognized text plausibly contains the wake phrase.

    The matcher supports:
        - Exact substring matching
        - Word-window fuzzy matching

    `sensitivity` follows the AssistantX setting convention:

        higher sensitivity = easier detection

    Internally the fuzzy matcher uses a similarity threshold where a higher
    value means stricter matching, so the value is inverted here.
    """

    heard_lower = " ".join(
        str(heard_text).lower().strip().split()
    )

    wake_lower = _normalize_phrase(wake_phrase)

    if not heard_lower:
        return False

    # Exact match is always accepted.
    if wake_lower in heard_lower:
        return True

    wake_words = wake_lower.split()
    heard_words = heard_lower.split()

    if not wake_words or not heard_words:
        return False

    # Convert user-facing sensitivity into fuzzy-match threshold.
    threshold = _clamp(
        1.0 - float(sensitivity),
        0.50,
        0.95,
    )

    window_size = len(wake_words)

    # Include small windows around the expected phrase length so STT
    # transcription can contain an extra/missing word.
    window_sizes = {
        max(1, window_size - 1),
        window_size,
        window_size + 1,
    }

    best_ratio = 0.0

    for current_size in window_sizes:
        if current_size > len(heard_words):
            continue

        for index in range(
            len(heard_words) - current_size + 1
        ):
            window = " ".join(
                heard_words[
                    index : index + current_size
                ]
            )

            ratio = difflib.SequenceMatcher(
                None,
                window,
                wake_lower,
            ).ratio()

            best_ratio = max(best_ratio, ratio)

            if best_ratio >= threshold:
                return True

    return False


# ============================================================================
# WakeWordDetector
# ============================================================================


class WakeWordDetector:
    """
    Background wake-word detector.

    The detector can be started once and kept alive for the lifetime of
    AssistantX. Detection can be temporarily paused while the assistant is
    speaking or processing a command.
    """

    FALLBACK_BACKEND = "fallback_stt"
    PORCUPINE_BACKEND = "porcupine"

    FALLBACK_LISTEN_TIMEOUT = 3
    FALLBACK_PHRASE_LIMIT = 4

    THREAD_JOIN_TIMEOUT = 3.0
    PAUSE_POLL_INTERVAL = 0.2
    ERROR_RETRY_DELAY = 1.0

    def __init__(
        self,
        wake_phrase: str | None = None,
        sensitivity: float | None = None,
        recognizer_instance: Any = None,
    ) -> None:

        configured_phrase = settings_manager.get(
            "voice.wake_word",
            DEFAULT_WAKE_WORD,
        )

        configured_sensitivity = settings_manager.get(
            "voice.wake_word_sensitivity",
            WAKE_WORD_SENSITIVITY,
        )

        self.wake_phrase = _normalize_phrase(
            wake_phrase or configured_phrase
        )

        user_sensitivity = (
            sensitivity
            if sensitivity is not None
            else configured_sensitivity
        )

        try:
            user_sensitivity = float(user_sensitivity)
        except (TypeError, ValueError):
            user_sensitivity = WAKE_WORD_SENSITIVITY

        self.sensitivity = _clamp(
            user_sensitivity,
            0.0,
            1.0,
        )

        self._recognizer = (
            recognizer_instance
            or default_recognizer
        )

        self._on_wake: WakeWordCallback | None = None

        self._thread: threading.Thread | None = None

        self._running = threading.Event()
        self._paused = threading.Event()

        self._lock = threading.RLock()

        self._stats = WakeWordStats()

        self._backend = self._resolve_backend()

        self._last_error: str | None = None

    # ====================================================================== #
    # Backend
    # ====================================================================== #

    def _resolve_backend(self) -> str:
        """
        Resolve the preferred backend.

        Porcupine is selected only when the package exists. Actual
        initialization still validates the access key and audio backend.
        """

        try:
            import pvporcupine  # type: ignore  # noqa: F401

            return self.PORCUPINE_BACKEND

        except ImportError:
            return self.FALLBACK_BACKEND

    @property
    def backend(self) -> str:
        """Return the currently selected backend."""
        return self._backend

    @property
    def is_using_porcupine(self) -> bool:
        """Return True when Porcupine is the selected backend."""
        return self._backend == self.PORCUPINE_BACKEND

    # ====================================================================== #
    # Availability
    # ====================================================================== #

    def is_available(self) -> bool:
        """
        Check whether the currently selected backend can potentially run.
        """

        if self._backend == self.FALLBACK_BACKEND:
            try:
                return bool(
                    self._recognizer.is_available()
                )
            except (OSError, RecognitionError) as exc:
                logger.warning(
                    "Recognizer availability check failed: %s",
                    exc,
                )
                return False

        # Porcupine package exists, but access key/audio initialization is
        # checked when the engine starts.
        return True

    # ====================================================================== #
    # Lifecycle
    # ====================================================================== #

    def start(
        self,
        on_wake: WakeWordCallback,
    ) -> bool:
        """
        Start background wake-word detection.

        Returns:
            True if started or already running.
            False if no usable backend/microphone is available.
        """

        if not callable(on_wake):
            raise WakeWordConfigurationError(
                "on_wake must be callable."
            )

        with self._lock:

            if self._running.is_set():
                logger.debug(
                    "Wake-word detector already running."
                )
                return True

            if not self.is_available():
                logger.warning(
                    "Wake-word detection unavailable."
                )
                return False

            self._on_wake = on_wake
            self._last_error = None

            self._running.set()
            self._paused.clear()

            target = (
                self._run_porcupine_loop
                if self._backend == self.PORCUPINE_BACKEND
                else self._run_fallback_loop
            )

            self._thread = threading.Thread(
                target=target,
                name="AssistantX-WakeWord",
                daemon=True,
            )

            self._thread.start()

            logger.info(
                "Wake-word detector started "
                "(backend=%s, phrase=%r, sensitivity=%.2f).",
                self._backend,
                self.wake_phrase,
                self.sensitivity,
            )

            return True

    def stop(self) -> None:
        """Stop background detection safely."""

        with self._lock:

            self._running.clear()
            self._paused.clear()

            thread = self._thread

        if (
            thread
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=self.THREAD_JOIN_TIMEOUT
            )

        with self._lock:
            self._thread = None
            self._on_wake = None

        logger.info(
            "Wake-word detector stopped."
        )

    def pause(self) -> None:
        """
        Temporarily pause wake-word detection.

        Recommended while:
            - TTS is speaking
            - Assistant is processing audio
            - Another voice subsystem owns the microphone
        """

        self._paused.set()

        logger.debug(
            "Wake-word detector paused."
        )

    def resume(self) -> None:
        """Resume wake-word detection."""

        if not self._running.is_set():
            logger.debug(
                "Cannot resume wake-word detector; it is not running."
            )
            return

        self._paused.clear()

        logger.debug(
            "Wake-word detector resumed."
        )

    # ====================================================================== #
    # State
    # ====================================================================== #

    @property
    def is_running(self) -> bool:
        """Return True when detector thread is active."""
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        """Return True when detection is paused."""
        return self._paused.is_set()

    @property
    def is_alive(self) -> bool:
        """Return True when the worker thread is alive."""
        thread = self._thread
        return bool(
            thread and thread.is_alive()
        )

    # ====================================================================== #
    # Fallback STT
    # ====================================================================== #

    def _run_fallback_loop(self) -> None:
        """
        Run STT-based wake-word detection.

        This backend intentionally uses the existing AssistantX recognizer
        so no dedicated keyword engine is required.
        """

        logger.info(
            "Starting fallback STT wake-word loop."
        )

        while self._running.is_set():

            if self._paused.is_set():
                time.sleep(
                    self.PAUSE_POLL_INTERVAL
                )
                continue

            try:
                result = (
                    self._recognizer.listen_and_transcribe(
                        timeout=self.FALLBACK_LISTEN_TIMEOUT,
                        phrase_time_limit=self.FALLBACK_PHRASE_LIMIT,
                    )
                )

            except RecognitionError:
                self._stats.recognition_errors += 1
                continue

            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                self._stats.backend_errors += 1
                self._last_error = str(exc)

                logger.error(
                    "Unexpected wake-word STT error: %s",
                    exc,
                )

                time.sleep(
                    self.ERROR_RETRY_DELAY
                )

                continue

            if not self._running.is_set():
                break

            heard_text = getattr(
                result,
                "text",
                "",
            )

            if not heard_text:
                continue

            try:
                detected = _fuzzy_contains_wake_word(
                    heard_text,
                    self.wake_phrase,
                    self.sensitivity,
                )
            except (TypeError, ValueError, WakeWordConfigurationError) as exc:
                logger.warning(
                    "Wake-word matching failed: %s",
                    exc,
                )
                continue

            if detected:
                logger.info(
                    "Wake word detected "
                    "(backend=fallback_stt, heard=%r).",
                    heard_text,
                )

                self._trigger()

    # ====================================================================== #
    # Porcupine
    # ====================================================================== #

    def _run_porcupine_loop(self) -> None:
        """
        Run Porcupine wake-word detection.

        Important:
            Porcupine does not automatically understand arbitrary phrases.
            A custom wake word requires a corresponding Porcupine keyword
            model. Therefore this implementation uses a configured keyword
            model when available and otherwise falls back to STT.
        """

        porcupine = None
        pa = None
        stream = None

        try:
            # Porcupine is an optional dependency; load it dynamically so
            # static analysis does not require it to be installed.
            pvporcupine = importlib.import_module("pvporcupine")
            # Load PyAudio dynamically because it is an optional dependency.
            pyaudio = importlib.import_module("pyaudio")

            from config.env_loader import get_env

            access_key = (
                get_env("PICOVOICE_ACCESS_KEY")
                or os.getenv("PICOVOICE_ACCESS_KEY")
            )

            if not access_key:
                logger.warning(
                    "PICOVOICE_ACCESS_KEY is not configured. "
                    "Falling back to STT wake detection."
                )

                self._switch_to_fallback()
                return

            keyword = settings_manager.get(
                "voice.porcupine_keyword",
                "computer",
            )

            keyword = str(keyword).strip()

            if not keyword:
                logger.warning(
                    "No Porcupine keyword configured. "
                    "Falling back to STT."
                )

                self._switch_to_fallback()
                return

            porcupine = pvporcupine.create(
                access_key=access_key,
                keywords=[keyword],
            )

            pa = pyaudio.PyAudio()

            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )

            logger.info(
                "Porcupine wake-word engine started "
                "(keyword=%r).",
                keyword,
            )

            while self._running.is_set():

                if self._paused.is_set():
                    time.sleep(
                        self.PAUSE_POLL_INTERVAL
                    )
                    continue

                pcm = stream.read(
                    porcupine.frame_length,
                    exception_on_overflow=False,
                )

                # Modern pvporcupine expects PCM samples rather than
                # arbitrary bytes. The API can differ between versions.
                if hasattr(
                    pvporcupine,
                    "util",
                ) and hasattr(
                    pvporcupine.util,
                    "pcm_unpack",
                ):
                    pcm_data = (
                        pvporcupine.util.pcm_unpack(
                            pcm
                        )
                    )
                else:
                    import struct

                    pcm_data = struct.unpack(
                        "<" + "h" * (
                            len(pcm) // 2
                        ),
                        pcm,
                    )

                keyword_index = porcupine.process(
                    pcm_data
                )

                if keyword_index >= 0:
                    logger.info(
                        "Wake word detected via Porcupine."
                    )

                    self._trigger()

        except ImportError as exc:

            self._stats.backend_errors += 1
            self._last_error = str(exc)

            logger.warning(
                "Porcupine dependencies unavailable: %s",
                exc,
            )

            self._switch_to_fallback()

        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:

            self._stats.backend_errors += 1
            self._last_error = str(exc)

            logger.error(
                "Porcupine wake-word engine failed: %s",
                exc,
            )

            if self._running.is_set():
                self._switch_to_fallback()

        finally:
            self._cleanup_porcupine(
                stream=stream,
                audio=pa,
                engine=porcupine,
            )

    def _cleanup_porcupine(
        self,
        *,
        stream: Any,
        audio: Any,
        engine: Any,
    ) -> None:
        """Safely release Porcupine/PyAudio resources."""

        if stream is not None:
            try:
                stream.stop_stream()
            except (AttributeError, OSError, RuntimeError) as exc:
                logger.warning("Failed to stop Porcupine audio stream: %s", exc)

            try:
                stream.close()
            except (AttributeError, OSError, RuntimeError) as exc:
                logger.warning("Failed to close Porcupine audio stream: %s", exc)

        if audio is not None:
            try:
                audio.terminate()
            except (AttributeError, OSError, RuntimeError) as exc:
                logger.warning("Failed to terminate PyAudio: %s", exc)

        if engine is not None:
            try:
                engine.delete()
            except (AttributeError, OSError, RuntimeError) as exc:
                logger.warning("Failed to delete Porcupine engine: %s", exc)

    def _switch_to_fallback(self) -> None:
        """Switch backend to STT fallback."""

        with self._lock:
            if self._backend != self.FALLBACK_BACKEND:
                self._backend = self.FALLBACK_BACKEND
                self._stats.fallback_count += 1

        if self._running.is_set():
            self._run_fallback_loop()

    # ====================================================================== #
    # Trigger
    # ====================================================================== #

    def _trigger(self) -> None:
        """Safely execute the configured wake callback."""

        callback = self._on_wake

        if callback is None:
            logger.debug(
                "Wake word detected but no callback is registered."
            )
            return

        self._stats.detections += 1

        try:
            callback()

        except Exception:
            self._stats.callback_errors += 1

            logger.exception(
                "Wake-word callback failed",
            )

    # ====================================================================== #
    # Runtime Configuration
    # ====================================================================== #

    def update_wake_phrase(
        self,
        phrase: str,
        *,
        persist: bool = True,
    ) -> None:
        """
        Update the wake phrase at runtime.

        Args:
            phrase:
                New wake phrase.

            persist:
                If True, save the phrase into AssistantX settings.
        """

        normalized = _normalize_phrase(
            phrase
        )

        with self._lock:
            self.wake_phrase = normalized

        if persist:
            settings_manager.set(
                "voice.wake_word",
                normalized,
            )

        logger.info(
            "Wake phrase updated to %r.",
            normalized,
        )

    def update_sensitivity(
        self,
        sensitivity: float,
        *,
        persist: bool = True,
    ) -> None:
        """
        Update wake-word sensitivity.

        Range:
            0.0 -> least eager
            1.0 -> most eager
        """

        try:
            value = float(sensitivity)
        except (TypeError, ValueError) as exc:
            raise WakeWordConfigurationError(
                "Sensitivity must be numeric."
            ) from exc

        value = _clamp(
            value,
            0.0,
            1.0,
        )

        with self._lock:
            self.sensitivity = value

        if persist:
            settings_manager.set(
                "voice.wake_word_sensitivity",
                value,
            )

        logger.info(
            "Wake-word sensitivity updated to %.2f.",
            value,
        )

    # ====================================================================== #
    # Callback
    # ====================================================================== #

    def set_callback(
        self,
        callback: WakeWordCallback | None,
    ) -> None:
        """Replace or clear the wake callback."""

        if callback is not None and not callable(callback):
            raise WakeWordConfigurationError(
                "Wake callback must be callable or None."
            )

        with self._lock:
            self._on_wake = callback

    # ====================================================================== #
    # Diagnostics
    # ====================================================================== #

    def diagnostics(self) -> dict[str, Any]:
        """
        Return a safe diagnostic snapshot.

        No credentials or sensitive microphone data are included.
        """

        with self._lock:
            return {
                "running": self.is_running,
                "paused": self.is_paused,
                "alive": self.is_alive,
                "backend": self._backend,
                "wake_phrase": self.wake_phrase,
                "sensitivity": self.sensitivity,
                "callback_registered": (
                    self._on_wake is not None
                ),
                "available": self.is_available(),
                "last_error": self._last_error,
                "stats": self._stats.as_dict(),
            }

    @property
    def stats(self) -> dict[str, int]:
        """Return detector statistics."""
        with self._lock:
            return self._stats.as_dict()


# ============================================================================
# Global Singleton
# ============================================================================

wake_word_detector = WakeWordDetector()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "WakeWordConfigurationError",
    "WakeWordDetector",
    "WakeWordError",
    "WakeWordStats",
    "wake_word_detector",
]
