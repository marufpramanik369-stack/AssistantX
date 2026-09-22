"""
speaker.py
==========

Professional offline Text-to-Speech (TTS) engine for AssistantX.

Backend
-------
Uses ``pyttsx3`` when available.

Supported platform backends depend on the operating system:

    Windows -> SAPI5
    macOS   -> NSSpeechSynthesizer
    Linux   -> eSpeak

Architecture
------------
UI / Assistant
      |
      v
  TextToSpeech
      |
      v
  Thread-safe Queue
      |
      v
  Dedicated TTS Worker
      |
      v
  pyttsx3 engine

Design goals
------------
- Fully asynchronous ``speak()``.
- Optional synchronous ``speak_blocking()``.
- Interrupt currently queued speech.
- Stop current speech immediately.
- Thread-safe lifecycle.
- Runtime settings refresh.
- Automatic language/voice selection.
- Voice enumeration.
- Runtime statistics.
- Graceful shutdown.
- Safe fallback when pyttsx3 is unavailable.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from config.settings import settings_manager
from voice.languages import get_language_profile

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_RATE = 175
DEFAULT_VOLUME = 1.0

MIN_RATE = 50
MAX_RATE = 400

MIN_VOLUME = 0.0
MAX_VOLUME = 1.0

DEFAULT_QUEUE_TIMEOUT = 0.25
DEFAULT_SHUTDOWN_TIMEOUT = 3.0

MAX_SPEECH_LENGTH = 10000


# Markdown / formatting characters that should normally not be spoken.
_MARKDOWN_STRIP_PATTERN = re.compile(
    r"[*_`#>~\[\]{}|]"
)

_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,.!?;:])")
_REPEATED_PUNCT_PATTERN = re.compile(r"([!?.,])\1{1,}")


# ============================================================================
# Exceptions
# ============================================================================


class SpeakerError(RuntimeError):
    """Base exception for the AssistantX speaker subsystem."""


class SpeakerUnavailableError(SpeakerError):
    """Raised when TTS is requested but no backend is available."""


class SpeakerShutdownError(SpeakerError):
    """Raised when an operation is attempted after shutdown."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """
    A single queued speech request.
    """

    text: str
    interrupt: bool = False
    request_id: int = 0
    created_at: float = 0.0


@dataclass(frozen=True, slots=True)
class SpeakerStats:
    """
    Runtime TTS statistics.
    """

    queued: int = 0
    completed: int = 0
    interrupted: int = 0
    failed: int = 0
    stopped: int = 0
    characters_spoken: int = 0


# ============================================================================
# Text Cleaning
# ============================================================================


def _clean_for_speech(
    text: str,
    *,
    max_length: int = MAX_SPEECH_LENGTH,
) -> str:
    """
    Clean text before sending it to the TTS engine.

    Removes common Markdown formatting and normalizes whitespace.
    """

    if text is None:
        return ""

    try:
        cleaned = str(text)
    except (TypeError, ValueError):
        return ""

    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    if len(cleaned) > max_length:
        logger.debug(
            "Speech text exceeded %d characters; truncating.",
            max_length,
        )
        cleaned = cleaned[:max_length]

    cleaned = _MARKDOWN_STRIP_PATTERN.sub("", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", cleaned)
    cleaned = _REPEATED_PUNCT_PATTERN.sub(r"\1", cleaned)
    cleaned = _MULTI_SPACE_PATTERN.sub(" ", cleaned)

    return cleaned.strip()


# ============================================================================
# Validation Helpers
# ============================================================================


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(minimum, min(maximum, value))


def _safe_rate(value: Any) -> int:
    try:
        rate = int(value)
    except (TypeError, ValueError):
        rate = DEFAULT_RATE

    return int(_clamp(rate, MIN_RATE, MAX_RATE))


def _safe_volume(value: Any) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME

    return _clamp(volume, MIN_VOLUME, MAX_VOLUME)


# ============================================================================
# TextToSpeech
# ============================================================================


class TextToSpeech:
    """
    High-level, thread-safe TTS manager.

    ``speak()`` is asynchronous and safe to call from the UI thread.

    Example
    -------
    >>> speaker.speak("Hello")
    >>> speaker.speak("How can I help you?")
    """

    def __init__(
        self,
        *,
        auto_start: bool = True,
    ) -> None:
        self._lock = threading.RLock()

        self._engine_module: Any = None
        self._engine: Any = None

        self._queue: queue.Queue[SpeechRequest] = queue.Queue()

        self._worker_thread: threading.Thread | None = None

        self._stop_event = threading.Event()
        self._speaking_event = threading.Event()

        self._shutdown = False
        self._request_counter = 0

        self._current_request: SpeechRequest | None = None

        self._stats_queued = 0
        self._stats_completed = 0
        self._stats_interrupted = 0
        self._stats_failed = 0
        self._stats_stopped = 0
        self._stats_characters = 0

        self._init_backend()

        if auto_start and self.is_available():
            self.start()

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------

    def _init_backend(self) -> None:
        """
        Lazily initialize pyttsx3.
        """

        try:
            import pyttsx3  # type: ignore
        except ImportError:
            logger.warning(
                "pyttsx3 is not installed. "
                "Offline TTS is unavailable. "
                "Install it with: pip install pyttsx3"
            )
            return

        self._engine_module = pyttsx3

        try:
            self._engine = pyttsx3.init()
        except Exception:
            logger.exception(
                "Failed to initialize pyttsx3 TTS engine",
            )
            self._engine = None
            return

        try:
            self._apply_settings()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to apply initial TTS settings: %s",
                exc,
            )

        logger.info("TTS engine initialized successfully.")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _apply_settings(self) -> None:
        """
        Apply current AssistantX voice settings.
        """

        engine = self._engine

        if engine is None:
            return

        try:
            rate = settings_manager.get(
                "voice.rate",
                DEFAULT_RATE,
            )

            volume = settings_manager.get(
                "voice.volume",
                DEFAULT_VOLUME,
            )

            language = settings_manager.get(
                "voice.language",
                "en-US",
            )

            self.set_rate(
                _safe_rate(rate),
                apply_immediately=False,
            )

            self.set_volume(
                _safe_volume(volume),
                apply_immediately=False,
            )

            self._select_voice_for_language(
                str(language or "en-US")
            )

        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            logger.warning(
                "Could not apply TTS settings: %s",
                exc,
            )

    def set_rate(
        self,
        rate: int,
        *,
        apply_immediately: bool = True,
        persist: bool = False,
    ) -> int:
        """
        Set speech rate.

        Returns the normalized rate actually used.
        """

        normalized = _safe_rate(rate)

        with self._lock:
            engine = self._engine

            if engine is not None and apply_immediately:
                try:
                    engine.setProperty(
                        "rate",
                        normalized,
                    )
                except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
                    logger.warning(
                        "Failed to set TTS rate: %s",
                        exc,
                    )

        if persist:
            try:
                settings_manager.set(
                    "voice.rate",
                    normalized,
                    save=True,
                )
            except TypeError:
                settings_manager.set(
                    "voice.rate",
                    normalized,
                )
            except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "Could not persist voice rate: %s",
                    exc,
                )

        return normalized

    def set_volume(
        self,
        volume: float,
        *,
        apply_immediately: bool = True,
        persist: bool = False,
    ) -> float:
        """
        Set TTS volume between 0.0 and 1.0.
        """

        normalized = _safe_volume(volume)

        with self._lock:
            engine = self._engine

            if engine is not None and apply_immediately:
                try:
                    engine.setProperty(
                        "volume",
                        normalized,
                    )
                except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
                    logger.warning(
                        "Failed to set TTS volume: %s",
                        exc,
                    )

        if persist:
            try:
                settings_manager.set(
                    "voice.volume",
                    normalized,
                    save=True,
                )
            except TypeError:
                settings_manager.set(
                    "voice.volume",
                    normalized,
                )
            except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "Could not persist voice volume: %s",
                    exc,
                )

        return normalized

    # ------------------------------------------------------------------
    # Voice Selection
    # ------------------------------------------------------------------

    def _select_voice_for_language(
        self,
        language_code: str,
    ) -> str | None:
        """
        Select the best installed OS voice for a language.
        """

        engine = self._engine

        if engine is None:
            return None

        language_code = str(
            language_code or "en-US"
        ).strip()

        try:
            profile = get_language_profile(
                language_code
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "Could not load language profile %s: %s",
                language_code,
                exc,
            )
            profile = None

        try:
            available_voices = (
                engine.getProperty("voices") or []
            )
        except (AttributeError, RuntimeError, TypeError) as exc:
            logger.debug(
                "Could not enumerate TTS voices: %s",
                exc,
            )
            return None

        hints: tuple[str, ...] = ()

        if profile is not None:
            hints = tuple(
                str(hint).lower()
                for hint in getattr(
                    profile,
                    "tts_voice_hints",
                    (),
                )
                if hint
            )

        normalized_language = (
            language_code.lower()
            .replace("_", "-")
        )

        # Try exact language information first.
        language_parts = normalized_language.split("-")

        language_candidates = {
            normalized_language,
            language_parts[0],
        }

        for voice in available_voices:
            voice_id = str(
                getattr(voice, "id", "") or ""
            )

            voice_name = str(
                getattr(voice, "name", "") or ""
            )

            voice_languages = getattr(
                voice,
                "languages",
                [],
            ) or []

            haystack = (
                f"{voice_name} "
                f"{voice_id} "
                f"{voice_languages}"
            ).lower()

            if hints and any(
                hint in haystack
                for hint in hints
            ):
                try:
                    engine.setProperty(
                        "voice",
                        voice_id,
                    )

                    logger.info(
                        "Selected TTS voice '%s' for %s.",
                        voice_name or voice_id,
                        language_code,
                    )

                    return voice_id

                except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                    logger.debug(
                        "Failed to select voice %s: %s",
                        voice_id,
                        exc,
                    )

        # Generic language fallback.
        for voice in available_voices:
            voice_id = str(
                getattr(voice, "id", "") or ""
            )

            voice_name = str(
                getattr(voice, "name", "") or ""
            )

            haystack = (
                f"{voice_name} {voice_id}"
            ).lower()

            if any(
                candidate in haystack
                for candidate in language_candidates
            ):
                try:
                    engine.setProperty(
                        "voice",
                        voice_id,
                    )

                    logger.info(
                        "Selected language-compatible TTS voice '%s'.",
                        voice_name or voice_id,
                    )

                    return voice_id

                except (AttributeError, RuntimeError, TypeError, ValueError):
                    continue

        logger.debug(
            "No matching TTS voice found for %s; "
            "using system default.",
            language_code,
        )

        return None

    # ------------------------------------------------------------------
    # Availability / State
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True when the TTS backend is initialized.
        """

        with self._lock:
            return self._engine is not None

    @property
    def is_speaking(self) -> bool:
        """Whether the worker is currently speaking."""

        return self._speaking_event.is_set()

    @property
    def is_running(self) -> bool:
        """Whether the background worker is alive."""

        thread = self._worker_thread

        return bool(
            thread
            and thread.is_alive()
            and not self._shutdown
        )

    @property
    def queue_size(self) -> int:
        """Number of pending speech requests."""

        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Worker Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the TTS worker.

        Returns True when running.
        """

        with self._lock:
            if self._shutdown:
                logger.warning(
                    "Cannot start TTS after shutdown."
                )
                return False

            if not self.is_available():
                return False

            if (
                self._worker_thread
                and self._worker_thread.is_alive()
            ):
                return True

            self._stop_event.clear()

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="AssistantX-TTSWorker",
            )

            self._worker_thread.start()

            logger.info("TTS worker started.")

            return True

    def _worker_loop(self) -> None:
        """
        Dedicated background TTS worker.
        """

        while not self._stop_event.is_set():

            try:
                request = self._queue.get(
                    timeout=DEFAULT_QUEUE_TIMEOUT
                )
            except queue.Empty:
                continue

            try:
                if request.interrupt:
                    self._drain_queue()

                self._current_request = request
                self._speaking_event.set()

                cleaned = _clean_for_speech(
                    request.text
                )

                if not cleaned:
                    continue

                engine = self._engine

                if engine is None:
                    self._stats_failed += 1
                    continue

                try:
                    engine.say(cleaned)
                    engine.runAndWait()

                    with self._lock:
                        self._stats_completed += 1
                        self._stats_characters += len(cleaned)

                except Exception:
                    with self._lock:
                        self._stats_failed += 1

                    logger.exception("TTS playback error")

            finally:
                self._current_request = None
                self._speaking_event.clear()

                try:
                    self._queue.task_done()
                except ValueError:
                    logger.debug(
                        "TTS queue task accounting error."
                    )

    def _drain_queue(self) -> int:
        """
        Remove all pending requests.

        Returns number of removed requests.
        """

        removed = 0

        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

            with contextlib.suppress(ValueError):
                self._queue.task_done()

            removed += 1

        if removed:
            with self._lock:
                self._stats_interrupted += removed

        return removed

    # ------------------------------------------------------------------
    # Speech
    # ------------------------------------------------------------------

    def speak(
        self,
        text: str,
        *,
        interrupt: bool = False,
    ) -> int | None:
        """
        Queue text for asynchronous speech.

        Parameters
        ----------
        text:
            Text to speak.
        interrupt:
            Clear pending speech before processing this request.

        Returns
        -------
        int | None
            Request ID when queued successfully.
        """

        cleaned = _clean_for_speech(text)

        if not cleaned:
            return None

        with self._lock:
            if self._shutdown:
                logger.debug(
                    "Ignoring speak() after shutdown."
                )
                return None

            if not self.is_available():
                logger.debug(
                    "TTS unavailable; skipping: %r",
                    cleaned[:80],
                )
                return None

            if not self.is_running and not self.start():
                return None

            if interrupt:
                self._drain_queue()

            self._request_counter += 1

            request = SpeechRequest(
                text=cleaned,
                interrupt=interrupt,
                request_id=self._request_counter,
                created_at=time.monotonic(),
            )

            self._queue.put(request)
            self._stats_queued += 1

            return request.request_id

    def speak_async(
        self,
        text: str,
        *,
        interrupt: bool = False,
    ) -> int | None:
        """
        Explicit alias for ``speak()``.
        """

        return self.speak(
            text,
            interrupt=interrupt,
        )

    def speak_blocking(
        self,
        text: str,
    ) -> bool:
        """
        Speak synchronously.

        This bypasses the background queue and should generally be used
        only by CLI/scripted contexts.
        """

        cleaned = _clean_for_speech(text)

        if not cleaned:
            return False

        with self._lock:
            if self._shutdown:
                return False

            engine = self._engine

            if engine is None:
                logger.debug(
                    "TTS unavailable for blocking speech."
                )
                return False

        self._speaking_event.set()

        try:
            engine.say(cleaned)
            engine.runAndWait()

            with self._lock:
                self._stats_completed += 1
                self._stats_characters += len(cleaned)

            return True

        except Exception:
            with self._lock:
                self._stats_failed += 1

            logger.exception("Blocking TTS playback error")

            return False

        finally:
            self._speaking_event.clear()

    # ------------------------------------------------------------------
    # Stop / Pause
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """
        Stop current speech and clear pending requests.
        """

        if not self.is_available():
            return

        removed = self._drain_queue()

        with self._lock:
            engine = self._engine

        try:
            if engine is not None:
                engine.stop()
        except (AttributeError, RuntimeError) as exc:
            logger.debug(
                "Error stopping TTS engine: %s",
                exc,
            )

        with self._lock:
            self._stats_stopped += 1

        logger.debug(
            "TTS stopped; removed %d queued requests.",
            removed,
        )

    def clear_queue(self) -> int:
        """
        Clear pending speech without stopping current speech.
        """

        return self._drain_queue()

    # ------------------------------------------------------------------
    # Settings Refresh
    # ------------------------------------------------------------------

    def refresh_settings(self) -> None:
        """
        Re-apply current settings.

        Call this after changing voice settings from the dashboard.
        """

        if not self.is_available():
            return

        self._apply_settings()

        logger.debug(
            "TTS settings refreshed."
        )

    # ------------------------------------------------------------------
    # Voice Enumeration
    # ------------------------------------------------------------------

    def list_available_voices(self) -> list[dict[str, Any]]:
        """
        Return installed OS TTS voices.

        Suitable for a settings dropdown.
        """

        engine = self._engine

        if engine is None:
            return []

        try:
            voices = (
                engine.getProperty("voices") or []
            )
        except (AttributeError, RuntimeError, OSError, ValueError) as exc:
            logger.debug(
                "Could not enumerate TTS voices: %s",
                exc,
            )
            return []

        result: list[dict[str, Any]] = []

        for voice in voices:
            voice_id = str(
                getattr(voice, "id", "") or ""
            )

            if not voice_id:
                continue

            name = str(
                getattr(
                    voice,
                    "name",
                    voice_id,
                )
                or voice_id
            )

            languages = getattr(
                voice,
                "languages",
                [],
            ) or []

            normalized_languages = []

            for language in languages:
                try:
                    if isinstance(
                        language,
                        bytes,
                    ):
                        language = language.decode(
                            "utf-8",
                            errors="ignore",
                        )

                    normalized_languages.append(
                        str(language)
                    )
                except (TypeError, UnicodeError, ValueError) as exc:
                    logger.debug(
                        "Unable to normalize voice language %r",
                        language,
                        exc_info=exc,
                    )
                else:
                    normalized_languages.append(
                        str(language)
                    )

            result.append(
                {
                    "id": voice_id,
                    "name": name,
                    "languages": normalized_languages,
                }
            )

        return result

    def set_voice(
        self,
        voice_id: str,
        *,
        persist: bool = False,
    ) -> bool:
        """
        Explicitly select an installed voice.
        """

        voice_id = str(
            voice_id or ""
        ).strip()

        if not voice_id:
            return False

        engine = self._engine

        if engine is None:
            return False

        available = {
            voice["id"]
            for voice in self.list_available_voices()
        }

        if voice_id not in available:
            logger.warning(
                "Requested TTS voice is not installed: %s",
                voice_id,
            )
            return False

        try:
            engine.setProperty(
                "voice",
                voice_id,
            )
        except (AttributeError, RuntimeError, ValueError) as exc:
            logger.error(
                "Failed to select TTS voice: %s",
                exc,
            )
            return False

        if persist:
            try:
                settings_manager.set(
                    "voice.voice_id",
                    voice_id,
                    save=True,
                )
            except TypeError:
                settings_manager.set(
                    "voice.voice_id",
                    voice_id,
                )
            except (AttributeError, KeyError, OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "Could not persist voice selection: %s",
                    exc,
                )

        return True

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> SpeakerStats:
        """
        Return a snapshot of runtime statistics.
        """

        with self._lock:
            return SpeakerStats(
                queued=self._stats_queued,
                completed=self._stats_completed,
                interrupted=self._stats_interrupted,
                failed=self._stats_failed,
                stopped=self._stats_stopped,
                characters_spoken=self._stats_characters,
            )

    def diagnostics(self) -> dict[str, Any]:
        """
        Return safe diagnostic information.

        No secrets are exposed.
        """

        statistics = self.stats()

        return {
            "available": self.is_available(),
            "running": self.is_running,
            "speaking": self.is_speaking,
            "queue_size": self.queue_size,
            "shutdown": self._shutdown,
            "worker_alive": bool(
                self._worker_thread
                and self._worker_thread.is_alive()
            ),
            "current_request_id": (
                self._current_request.request_id
                if self._current_request
                else None
            ),
            "stats": {
                "queued": statistics.queued,
                "completed": statistics.completed,
                "interrupted": statistics.interrupted,
                "failed": statistics.failed,
                "stopped": statistics.stopped,
                "characters_spoken": statistics.characters_spoken,
            },
            "voice_count": len(
                self.list_available_voices()
            ),
        }

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(
        self,
        *,
        timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        """
        Gracefully shut down the TTS worker and engine.
        """

        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True
            self._stop_event.set()

        self._drain_queue()

        try:
            if self._engine is not None:
                self._engine.stop()
        except (OSError, RuntimeError) as exc:
            logger.debug(
                "Error stopping TTS engine during shutdown: %s",
                exc,
            )

        thread = self._worker_thread

        if (
            thread
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=max(
                    0.1,
                    float(timeout),
                )
            )

        self._worker_thread = None

        logger.info("TTS subsystem shut down.")

    def restart(self) -> bool:
        """
        Restart the worker thread.

        The pyttsx3 engine itself is reused.
        """

        with self._lock:
            if self._shutdown:
                return False

        self.stop()

        if not self.is_available():
            return False

        return self.start()


# ============================================================================
# Module-level Singleton
# ============================================================================


speaker = TextToSpeech()


# ============================================================================
# Convenience Functions
# ============================================================================


def speak(
    text: str,
    *,
    interrupt: bool = False,
) -> int | None:
    """
    Convenience wrapper around the global speaker.
    """

    return speaker.speak(
        text,
        interrupt=interrupt,
    )


def stop_speaking() -> None:
    """
    Stop current speech and clear the queue.
    """

    speaker.stop()


def is_speaking() -> bool:
    """
    Return whether AssistantX is currently speaking.
    """

    return speaker.is_speaking


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "SpeakerError",
    "SpeakerShutdownError",
    "SpeakerStats",
    "SpeakerUnavailableError",
    "SpeechRequest",
    "TextToSpeech",
    "is_speaking",
    "speak",
    "speaker",
    "stop_speaking",
]
