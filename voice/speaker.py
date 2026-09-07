"""
speaker.py
==========
Text-to-speech (TTS) engine wrapper, built on `pyttsx3`
(https://pypi.org/project/pyttsx3/) — chosen because it works fully
offline and cross-platform (SAPI5 on Windows, NSSpeechSynthesizer on
macOS, espeak on Linux), which matters for a desktop assistant that
should speak even without an internet connection.

Design notes:
    - Speech runs in a dedicated background thread with a queue, so
      `speak()` calls from the main/UI thread never block, and multiple
      rapid responses queue up naturally instead of overlapping/garbling.
    - `speak_async()` / `stop()` let the dashboard interrupt speech
      (e.g. user clicks a "stop talking" button while the assistant is
      mid-sentence).
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from dataclasses import dataclass
from typing import Optional

from config.settings import settings_manager
from voice.languages import get_language_profile

logger = logging.getLogger(__name__)

# Strip characters that read awkwardly aloud (markdown symbols, excessive
# punctuation) before handing text to the TTS engine.
_MARKDOWN_STRIP_PATTERN = re.compile(r"[*_`#>~\[\]]")
_MULTI_SPACE_PATTERN = re.compile(r"\s+")


def _clean_for_speech(text: str) -> str:
    """Strip markdown/formatting noise so TTS doesn't read out symbols."""
    cleaned = _MARKDOWN_STRIP_PATTERN.sub("", text)
    cleaned = _MULTI_SPACE_PATTERN.sub(" ", cleaned)
    return cleaned.strip()


@dataclass
class SpeechRequest:
    text: str
    interrupt: bool = False  # if True, clears the queue and speaks this immediately


class TextToSpeech:
    """
    High-level TTS interface with a background worker thread so callers
    never block waiting for speech playback to finish (unless they
    explicitly want to via `speak_blocking()`).
    """

    def __init__(self) -> None:
        self._engine_module = None
        self._engine = None
        self._queue: "queue.Queue[SpeechRequest]" = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._speaking = threading.Event()
        self._init_backend()
        self._start_worker()

    def _init_backend(self) -> None:
        try:
            import pyttsx3  # type: ignore
        except ImportError:
            logger.warning(
                "The 'pyttsx3' package is not installed. Text-to-speech will "
                "be unavailable; run: pip install pyttsx3"
            )
            return

        self._engine_module = pyttsx3
        try:
            self._engine = pyttsx3.init()
        except Exception as exc:  # noqa: BLE001 - platform TTS init can fail in many ways
            logger.error("Failed to initialize TTS engine: %s", exc)
            self._engine = None
            return

        self._apply_settings()

    def _apply_settings(self) -> None:
        if self._engine is None:
            return
        rate = settings_manager.get("voice.rate", 175)
        volume = settings_manager.get("voice.volume", 1.0)
        self._engine.setProperty("rate", rate)
        self._engine.setProperty("volume", volume)
        self._select_voice_for_language(settings_manager.get("voice.language", "en-US"))

    def _select_voice_for_language(self, language_code: str) -> None:
        """Pick the best-matching installed OS voice for the given language."""
        if self._engine is None:
            return

        profile = get_language_profile(language_code)
        try:
            available_voices = self._engine.getProperty("voices")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not enumerate TTS voices: %s", exc)
            return

        for voice in available_voices:
            voice_name = getattr(voice, "name", "") or ""
            voice_id = getattr(voice, "id", "") or ""
            haystack = f"{voice_name} {voice_id}"
            if any(hint.lower() in haystack.lower() for hint in profile.tts_voice_hints):
                self._engine.setProperty("voice", voice.id)
                logger.info("Selected TTS voice '%s' for language %s.", voice_name, profile.code)
                return

        logger.debug("No matching TTS voice found for %s; using system default.", profile.code)

    def is_available(self) -> bool:
        return self._engine is not None

    # -- worker thread ------------------------------------------------------ #

    def _start_worker(self) -> None:
        if not self.is_available():
            return
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="TTSWorker")
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if request.interrupt:
                self._drain_queue()

            self._speaking.set()
            try:
                cleaned = _clean_for_speech(request.text)
                if cleaned:
                    self._engine.say(cleaned)
                    self._engine.runAndWait()
            except Exception as exc:  # noqa: BLE001
                logger.error("TTS playback error: %s", exc)
            finally:
                self._speaking.clear()
                self._queue.task_done()

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    # -- public API ----------------------------------------------------------- #

    def speak(self, text: str, interrupt: bool = False) -> None:
        """
        Queue text to be spoken asynchronously. Returns immediately —
        does not block the calling thread. If `interrupt=True`, clears
        any currently queued (not yet started) speech first.
        """
        if not text or not text.strip():
            return
        if not self.is_available():
            logger.debug("TTS unavailable; skipping speak() for: %r", text[:50])
            return
        self._queue.put(SpeechRequest(text=text, interrupt=interrupt))

    def speak_blocking(self, text: str) -> None:
        """
        Speak text synchronously, blocking the calling thread until
        playback finishes. Useful for CLI/scripted contexts where async
        queuing isn't needed.
        """
        if not text or not self.is_available():
            return
        cleaned = _clean_for_speech(text)
        if not cleaned:
            return
        self._engine.say(cleaned)
        self._engine.runAndWait()

    def stop(self) -> None:
        """Immediately stop current speech and clear any queued requests."""
        if not self.is_available():
            return
        self._drain_queue()
        try:
            self._engine.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error stopping TTS engine: %s", exc)

    @property
    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def refresh_settings(self) -> None:
        """Re-apply rate/volume/voice from current user settings — call
        after the user changes voice settings in the dashboard."""
        self._apply_settings()

    def shutdown(self) -> None:
        """Cleanly stop the worker thread, e.g. during app shutdown."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def list_available_voices(self) -> list[dict]:
        """Return metadata for all installed OS TTS voices, for a settings dropdown."""
        if not self.is_available():
            return []
        try:
            voices = self._engine.getProperty("voices")
        except Exception:  # noqa: BLE001
            return []
        return [{"id": v.id, "name": getattr(v, "name", v.id)} for v in voices]


# Module-level singleton.
speaker: TextToSpeech = TextToSpeech()
