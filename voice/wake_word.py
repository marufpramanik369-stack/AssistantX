"""
wake_word.py
============
Continuous, low-power listening for a wake phrase (e.g. "hey assistant")
so the user doesn't need to click a button to start talking.

Two detection strategies are supported:

    1. Lightweight fallback (default, zero extra dependencies): runs
       voice/recognizer.py's normal STT on short audio chunks and does
       fuzzy substring matching against the configured wake phrase. This
       is less efficient than a dedicated wake-word engine (it uses full
       STT rather than a tiny keyword-spotting model) but works with
       zero additional setup.

    2. Porcupine engine (optional, higher accuracy + lower CPU): if the
       `pvporcupine` package and an access key are available, delegates
       to Picovoice's purpose-built wake-word engine.

The active strategy is resolved automatically based on what's installed
— callers don't need to know which one is running.
"""

from __future__ import annotations

import difflib
import logging
import threading
import time
from typing import Callable, Optional

from config.constants import WAKE_WORD_SENSITIVITY
from config.settings import settings_manager
from voice.languages import get_language_profile
from voice.recognizer import RecognitionError, recognizer as default_recognizer

logger = logging.getLogger(__name__)

WakeWordCallback = Callable[[], None]


def _fuzzy_contains_wake_word(heard_text: str, wake_phrase: str, sensitivity: float) -> bool:
    """
    Check whether `heard_text` plausibly contains `wake_phrase`, tolerant
    of STT transcription noise (e.g. "hey assistant" heard as "a
    assistant" or "hey assistants").

    Uses difflib's SequenceMatcher ratio over a sliding window of the
    heard text roughly the same length as the wake phrase, which is more
    forgiving than exact substring matching for short spoken phrases.
    """
    heard_lower = heard_text.lower().strip()
    wake_lower = wake_phrase.lower().strip()

    if not heard_lower or not wake_lower:
        return False

    if wake_lower in heard_lower:
        return True

    wake_word_count = len(wake_lower.split())
    heard_words = heard_lower.split()

    best_ratio = 0.0
    for i in range(max(1, len(heard_words) - wake_word_count + 1)):
        window = " ".join(heard_words[i : i + wake_word_count])
        ratio = difflib.SequenceMatcher(None, window, wake_lower).ratio()
        best_ratio = max(best_ratio, ratio)

    return best_ratio >= sensitivity


class WakeWordDetector:
    """
    Runs a background listening loop that calls `on_wake` whenever the
    configured wake phrase is detected. Designed to run for the entire
    app lifetime once started, pausing automatically while the assistant
    is actively processing a command (to avoid re-triggering on its own
    speech output).
    """

    def __init__(
        self,
        wake_phrase: Optional[str] = None,
        sensitivity: Optional[float] = None,
        recognizer_instance=None,
    ) -> None:
        self.wake_phrase = wake_phrase or settings_manager.get("voice.wake_word", "hey assistant")
        self.sensitivity = sensitivity if sensitivity is not None else (
            1.0 - settings_manager.get("voice.wake_word_sensitivity", WAKE_WORD_SENSITIVITY)
        )
        # Note: settings store "sensitivity" as how eager detection should
        # be (higher = easier to trigger), while our fuzzy-match ratio
        # threshold works the opposite way (higher = stricter), hence the
        # inversion above with a floor/ceiling clamp below.
        self.sensitivity = max(0.5, min(0.95, self.sensitivity))

        self._recognizer = recognizer_instance or default_recognizer
        self._on_wake: Optional[WakeWordCallback] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._engine_backend = self._resolve_backend()

    def _resolve_backend(self) -> str:
        try:
            import pvporcupine  # type: ignore  # noqa: F401

            return "porcupine"
        except ImportError:
            return "fallback_stt"

    def is_available(self) -> bool:
        if self._engine_backend == "fallback_stt":
            return self._recognizer.is_available()
        return True  # porcupine backend assumed available if import succeeded

    # -- lifecycle ------------------------------------------------------------ #

    def start(self, on_wake: WakeWordCallback) -> bool:
        """
        Begin background listening. Returns False immediately (without
        starting a thread) if no working microphone/backend is available.
        """
        if not self.is_available():
            logger.warning("Wake word detection unavailable (no mic/backend). Skipping.")
            return False

        if self._running.is_set():
            logger.debug("Wake word detector already running.")
            return True

        self._on_wake = on_wake
        self._running.set()
        self._paused.clear()

        target = self._run_porcupine_loop if self._engine_backend == "porcupine" else self._run_fallback_loop
        self._thread = threading.Thread(target=target, daemon=True, name="WakeWordDetector")
        self._thread.start()
        logger.info("Wake word detector started (backend=%s, phrase=%r).", self._engine_backend, self.wake_phrase)
        return True

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Wake word detector stopped.")

    def pause(self) -> None:
        """Temporarily suspend detection — call while the assistant itself
        is speaking, to avoid the TTS output re-triggering the wake word."""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # -- fallback (STT-based) loop ------------------------------------------------ #

    def _run_fallback_loop(self) -> None:
        """
        Repeatedly listens for short phrases and fuzzy-matches them
        against the wake phrase. Less efficient than a dedicated
        keyword-spotting model, but requires no extra dependencies.
        """
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

            try:
                result = self._recognizer.listen_and_transcribe(
                    timeout=3, phrase_time_limit=4
                )
            except RecognitionError:
                continue  # timeout or unintelligible audio — just keep listening
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in wake word fallback loop: %s", exc)
                time.sleep(1.0)
                continue

            if _fuzzy_contains_wake_word(result.text, self.wake_phrase, self.sensitivity):
                logger.info("Wake word detected (heard: %r).", result.text)
                self._trigger()

    # -- Porcupine (optional, higher-accuracy) loop ------------------------------- #

    def _run_porcupine_loop(self) -> None:  # pragma: no cover - requires optional native dependency
        """
        Uses Picovoice Porcupine for dedicated, low-CPU wake-word
        detection. Requires `pvporcupine` and a valid access key
        (PICOVOICE_ACCESS_KEY env var) plus a PyAudio-compatible stream.
        Falls back to the STT loop on any initialization failure.
        """
        try:
            import pvporcupine
            import pyaudio

            from config.env_loader import get_env

            access_key = get_env("PICOVOICE_ACCESS_KEY")
            if not access_key:
                logger.warning("PICOVOICE_ACCESS_KEY not set; falling back to STT-based wake detection.")
                self._run_fallback_loop()
                return

            porcupine = pvporcupine.create(access_key=access_key, keywords=["computer"])
            pa = pyaudio.PyAudio()
            stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )

            while self._running.is_set():
                if self._paused.is_set():
                    time.sleep(0.2)
                    continue
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm_unpacked = pvporcupine.util.pcm_unpack(pcm) if hasattr(pvporcupine, "util") else pcm
                keyword_index = porcupine.process(pcm_unpacked)
                if keyword_index >= 0:
                    logger.info("Wake word detected via Porcupine.")
                    self._trigger()

            stream.close()
            pa.terminate()
            porcupine.delete()

        except Exception as exc:  # noqa: BLE001
            logger.error("Porcupine wake word engine failed (%s); falling back to STT loop.", exc)
            self._run_fallback_loop()

    # -- trigger ---------------------------------------------------------------------- #

    def _trigger(self) -> None:
        if self._on_wake is not None:
            try:
                self._on_wake()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in on_wake callback: %s", exc)

    def update_wake_phrase(self, phrase: str) -> None:
        self.wake_phrase = phrase
        settings_manager.set("voice.wake_word", phrase)
        logger.info("Wake phrase updated to %r.", phrase)


# Module-level singleton.
wake_word_detector: WakeWordDetector = WakeWordDetector()
