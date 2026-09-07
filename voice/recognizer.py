"""
recognizer.py
=============
Speech-to-text (STT) engine wrapper. Built on top of the `SpeechRecognition`
package (https://pypi.org/project/SpeechRecognition/), which itself can
delegate to several backends (Google Web Speech API, Whisper, Sphinx,
etc.) — this module picks a sensible default (Google's free web API for
online recognition) while keeping the door open for offline engines.

If the `speech_recognition` package or a working microphone isn't
available (e.g. running in a headless/server/testing environment),
`is_available()` returns False and callers (voice/wake_word.py,
core/assistant.py) should fall back to text-only interaction rather
than crashing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from config.constants import (
    LISTEN_TIMEOUT_SECONDS,
    MIC_SAMPLE_RATE,
    PHRASE_TIME_LIMIT_SECONDS,
)
from config.settings import settings_manager
from voice.languages import get_language_profile
from voice.noise_filter import AmbientNoiseCalibrator

logger = logging.getLogger(__name__)


class RecognitionError(RuntimeError):
    """Raised for STT-specific failures (distinguished from generic errors
    so core/assistant.py can phrase a natural "I didn't catch that")."""


@dataclass
class RecognitionResult:
    text: str
    confidence: Optional[float] = None
    language: str = "en-US"
    engine: str = "google"


class SpeechRecognizer:
    """
    High-level speech-to-text interface. Wraps the microphone lifecycle
    (open, calibrate, listen, close) and the actual recognition call, so
    callers just do:

        recognizer = SpeechRecognizer()
        result = recognizer.listen_and_transcribe()
        print(result.text)
    """

    def __init__(self, language: Optional[str] = None) -> None:
        self.language = language or settings_manager.get("voice.language", "en-US")
        self._sr_module = None
        self._recognizer = None
        self._microphone = None
        self._noise_calibrator = AmbientNoiseCalibrator()
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            logger.warning(
                "The 'SpeechRecognition' package is not installed. "
                "Voice input will be unavailable; run: pip install SpeechRecognition pyaudio"
            )
            return

        self._sr_module = sr
        self._recognizer = sr.Recognizer()
        # Tunables mapped from user settings, applied to the underlying engine.
        self._recognizer.pause_threshold = 0.8
        self._recognizer.dynamic_energy_threshold = True

        try:
            self._microphone = sr.Microphone(sample_rate=MIC_SAMPLE_RATE)
        except OSError as exc:
            logger.warning("No microphone detected (%s). Voice input disabled.", exc)
            self._microphone = None

    def is_available(self) -> bool:
        return self._sr_module is not None and self._microphone is not None

    def calibrate_ambient_noise(self, duration: float = 1.0) -> None:
        """
        Sample ambient background noise for `duration` seconds to set an
        appropriate silence threshold. Should be called once at startup
        and optionally re-run if the assistant moves to a noisier
        environment (e.g. user explicitly requests recalibration).
        """
        if not self.is_available():
            return

        with self._microphone as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=duration)
        logger.info(
            "Ambient noise calibrated. energy_threshold=%.1f",
            self._recognizer.energy_threshold,
        )

    def listen(
        self,
        timeout: int = LISTEN_TIMEOUT_SECONDS,
        phrase_time_limit: int = PHRASE_TIME_LIMIT_SECONDS,
        on_listening_start: Optional[Callable[[], None]] = None,
    ):
        """
        Capture one utterance from the microphone and return the raw
        AudioData object (speech_recognition's internal representation),
        WITHOUT transcribing it yet — useful when the caller wants to
        show a "listening..." UI state before processing begins.

        Raises:
            RecognitionError: if no microphone is available, or if the
                listen times out with no speech detected.
        """
        if not self.is_available():
            raise RecognitionError("No microphone/speech_recognition backend available.")

        if on_listening_start:
            on_listening_start()

        try:
            with self._microphone as source:
                audio = self._recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            return audio
        except self._sr_module.WaitTimeoutError as exc:
            raise RecognitionError("No speech detected within the timeout window.") from exc

    def transcribe(self, audio, engine: str = "google") -> RecognitionResult:
        """
        Transcribe a previously captured AudioData object into text.

        Args:
            audio: The AudioData object returned by `listen()`.
            engine: Which backend to use — 'google' (free, online),
                'whisper' (local, if openai-whisper is installed), or
                'sphinx' (fully offline, lower accuracy).

        Raises:
            RecognitionError: on unrecognized speech or backend failure.
        """
        if self._sr_module is None:
            raise RecognitionError("Speech recognition backend not initialized.")

        profile = get_language_profile(self.language)
        sr = self._sr_module

        try:
            if engine == "google":
                text = self._recognizer.recognize_google(audio, language=profile.recognizer_locale)
            elif engine == "whisper":
                text = self._recognizer.recognize_whisper(audio, language=profile.code.split("-")[0])
            elif engine == "sphinx":
                text = self._recognizer.recognize_sphinx(audio)
            else:
                raise RecognitionError(f"Unknown recognition engine: '{engine}'")

            return RecognitionResult(text=text.strip(), language=profile.code, engine=engine)

        except sr.UnknownValueError as exc:
            raise RecognitionError("Could not understand the audio.") from exc
        except sr.RequestError as exc:
            raise RecognitionError(f"Speech recognition service error: {exc}") from exc

    def listen_and_transcribe(
        self,
        engine: str = "google",
        timeout: int = LISTEN_TIMEOUT_SECONDS,
        phrase_time_limit: int = PHRASE_TIME_LIMIT_SECONDS,
        on_listening_start: Optional[Callable[[], None]] = None,
    ) -> RecognitionResult:
        """Convenience method combining listen() + transcribe() in one call."""
        audio = self.listen(
            timeout=timeout,
            phrase_time_limit=phrase_time_limit,
            on_listening_start=on_listening_start,
        )
        return self.transcribe(audio, engine=engine)

    def transcribe_file(self, file_path: str, engine: str = "google") -> RecognitionResult:
        """Transcribe a pre-recorded audio file (wav/aiff/flac) instead of live mic input."""
        if self._sr_module is None:
            raise RecognitionError("Speech recognition backend not initialized.")

        with self._sr_module.AudioFile(file_path) as source:
            audio = self._recognizer.record(source)
        return self.transcribe(audio, engine=engine)


# Module-level singleton for convenient importing; core/assistant.py and
# voice/wake_word.py share this one instance so microphone calibration
# state is consistent across the app.
recognizer: SpeechRecognizer = SpeechRecognizer()
