"""
voice/speaker.py — JEROX Text-to-Speech Engine (Bangla-first)

Same public API as the previous pyttsx3 version, but the primary backend is
now Microsoft Edge neural voices via `edge-tts` (needs internet):

    bn -> bn-BD-NabanitaNeural (female)   fallback: bn-IN-TanishaaNeural
    hi -> hi-IN-SwaraNeural    (female)
    en -> en-US-JennyNeural    (female)

If edge-tts is missing or the network is down, JEROX falls back to the
offline pyttsx3 female voice (Bengali text will then sound wrong, because
Windows has no Bengali SAPI voice installed by default).

Playback uses Windows MCI (built in, no extra package) so speech can be
stopped instantly.

Install:
    pip install edge-tts
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from config.settings import settings_manager

logger = logging.getLogger(__name__)

# ============================================================================
# Policy
# ============================================================================

ASSISTANT_NAME = "JEROX"

DEFAULT_LANGUAGE = "bn"
DEFAULT_GENDER = "female"
DEFAULT_VOICE_PITCH = 1.0
DEFAULT_VOICE_RATE = 155
DEFAULT_VOLUME = 1.0

MIN_RATE = 50
MAX_RATE = 400
MIN_VOLUME = 0.0
MAX_VOLUME = 1.0

DEFAULT_QUEUE_TIMEOUT = 0.25
DEFAULT_SHUTDOWN_TIMEOUT = 3.0
MAX_SPEECH_LENGTH = 20500

SUPPORTED_LANGUAGES = frozenset({"bn", "en", "hi"})

LANGUAGE_ALIASES: dict[str, str] = {
    "bn": "bn", "bn-bd": "bn", "bn-in": "bn", "bengali": "bn", "bangla": "bn",
    "en": "en", "en-us": "en", "en-gb": "en", "en-au": "en", "english": "en",
    "hi": "hi", "hi-in": "hi", "hindi": "hi",
}

# Female neural voices only (voice identity is locked to female).
EDGE_VOICES: dict[str, tuple[str, ...]] = {
    "bn": ("bn-BD-NabanitaNeural", "bn-IN-TanishaaNeural"),
    "hi": ("hi-IN-SwaraNeural",),
    "en": ("en-US-JennyNeural", "en-US-AriaNeural"),
}

FEMALE_VOICE_MARKERS = frozenset(
    {
        "female", "woman", "girl", "victoria", "samantha", "zira", "hazel",
        "susan", "sarah", "natasha", "heera", "veena", "priya", "neerja",
        "kalpana", "raveena", "aditi", "lekha", "tania",
    }
)

_MARKDOWN_STRIP_PATTERN = re.compile(r"[*_`#>~\[\]{}|]")
_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,.!?;:।])")
_REPEATED_PUNCT_PATTERN = re.compile(r"([!?.,।])\1{1,}")


# ============================================================================
# Exceptions
# ============================================================================


class SpeakerError(RuntimeError):
    """Base exception for JEROX speaker subsystem."""


class SpeakerUnavailableError(SpeakerError):
    """Raised when the TTS backend is unavailable."""


class SpeakerShutdownError(SpeakerError):
    """Raised when an operation is attempted after shutdown."""


# ============================================================================
# Data models
# ============================================================================


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    text: str
    interrupt: bool = False
    request_id: int = 0
    created_at: float = 0.0


@dataclass(frozen=True, slots=True)
class SpeakerStats:
    queued: int = 0
    completed: int = 0
    interrupted: int = 0
    failed: int = 0
    stopped: int = 0
    characters_spoken: int = 0


# ============================================================================
# Helpers
# ============================================================================


def normalize_language(language: Any) -> str:
    """Normalize to bn / en / hi. Unknown values fall back to Bangla."""
    if language is None:
        return DEFAULT_LANGUAGE
    value = str(language).strip().lower().replace("_", "-")
    if not value:
        return DEFAULT_LANGUAGE
    if value in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[value]
    return LANGUAGE_ALIASES.get(value.split("-", 1)[0], DEFAULT_LANGUAGE)


def _clean_for_speech(text: Any, *, max_length: int = MAX_SPEECH_LENGTH) -> str:
    if text is None:
        return ""
    try:
        cleaned = str(text).strip()
    except (TypeError, ValueError):
        return ""
    if not cleaned:
        return ""
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    cleaned = _MARKDOWN_STRIP_PATTERN.sub("", cleaned)

# Remove assistant display prefix from spoken text.
    cleaned = re.sub(r"^\s*JEROX\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"আমি\s+জেরক্স\s*\(\s*JEROX\s*\)", "আমি জেরক্স", cleaned, flags=re.IGNORECASE)



    cleaned = _SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", cleaned)
    cleaned = _REPEATED_PUNCT_PATTERN.sub(r"\1", cleaned)
    cleaned = _MULTI_SPACE_PATTERN.sub(" ", cleaned)
    return cleaned.strip()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_rate(value: Any) -> int:
    try:
        rate = int(value)
    except (TypeError, ValueError):
        rate = DEFAULT_VOICE_RATE
    return int(_clamp(rate, MIN_RATE, MAX_RATE))


def _safe_volume(value: Any) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    return _clamp(volume, MIN_VOLUME, MAX_VOLUME)


def _edge_rate(rate: int) -> str:
    """pyttsx3-style WPM -> edge-tts percentage string."""
    pct = round((rate - DEFAULT_VOICE_RATE) / DEFAULT_VOICE_RATE * 100)
    pct = int(_clamp(pct + 15, -50, 100))  # +15% faster speech (JEROX tuning)
    return f"{pct:+d}%"


def _edge_volume(volume: float) -> str:
    """0.0-1.0 -> edge-tts percentage string (1.0 == +0%)."""
    pct = int(round((volume - 1.0) * 100))
    pct = int(_clamp(pct, -95, 0))
    return f"{pct:+d}%"


def _decode_voice_language(value: Any) -> str:
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return value.decode(encoding, errors="ignore")
            except Exception:
                continue
    return str(value or "")


def _voice_haystack(voice: Any) -> str:
    voice_id = str(getattr(voice, "id", "") or "")
    voice_name = str(getattr(voice, "name", "") or "")
    langs = [_decode_voice_language(x) for x in (getattr(voice, "languages", []) or [])]
    return " ".join([voice_id, voice_name, *langs]).lower()


def _looks_female(voice: Any) -> bool:
    haystack = _voice_haystack(voice)
    return any(marker in haystack for marker in FEMALE_VOICE_MARKERS)


# ============================================================================
# MP3 playback via Windows MCI (stoppable, no extra dependency)
# ============================================================================


class _Mp3Player:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alias: Optional[str] = None
        self._winmm = ctypes.windll.winmm if sys.platform == "win32" else None

    @property
    def available(self) -> bool:
        return self._winmm is not None

    def _cmd(self, command: str) -> int:
        buf = ctypes.create_unicode_buffer(256)
        return int(self._winmm.mciSendStringW(command, buf, 255, 0))

    def play(self, path: str, alias: str) -> None:
        if self._winmm is None:
            raise RuntimeError("MCI playback is only available on Windows")
        with self._lock:
            self._alias = alias
        try:
            if self._cmd(f'open "{path}" type mpegvideo alias {alias}') != 0:
                raise RuntimeError("MCI failed to open audio file")
            self._cmd(f"play {alias} wait")
        finally:
            self._cmd(f"close {alias}")
            with self._lock:
                if self._alias == alias:
                    self._alias = None

    def stop(self) -> None:
        with self._lock:
            alias = self._alias
        if alias and self._winmm is not None:
            self._cmd(f"stop {alias}")


# ============================================================================
# TextToSpeech
# ============================================================================


class TextToSpeech:
    """Thread-safe JEROX TTS manager (female voice locked, Bangla default)."""

    def __init__(self, *, auto_start: bool = True) -> None:
        logger.info(
            "Initializing %s TTS engine (female voice locked, Bangla neural)",
            ASSISTANT_NAME,
        )

        self._lock = threading.RLock()
        self._queue: queue.Queue[SpeechRequest] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._speaking_event = threading.Event()
        self._shutdown = False
        self._request_counter = 0
        self._current_request: Optional[SpeechRequest] = None

        # Settings
        self._active_language = DEFAULT_LANGUAGE
        self._requested_language = DEFAULT_LANGUAGE
        self._rate = DEFAULT_VOICE_RATE
        self._volume = DEFAULT_VOLUME

        # Backends
        self._edge_module: Optional[Any] = None
        self._player = _Mp3Player()
        self._edge_ok = False
        self._pyttsx3_module: Optional[Any] = None
        self._fallback_engine: Optional[Any] = None  # created in worker thread

        # Voice state
        self._selected_voice_id: Optional[str] = None
        self._selected_voice_name: Optional[str] = None
        self._tts_voice_language = DEFAULT_LANGUAGE
        self._voice_fallback_active = False
        self._voice_fallback_reason: Optional[str] = None
        self._backend = "none"

        # Stats
        self._stats_queued = 0
        self._stats_completed = 0
        self._stats_interrupted = 0
        self._stats_failed = 0
        self._stats_stopped = 0
        self._stats_characters = 0

        self._init_backends()
        self._load_settings()

        if auto_start and self.is_available():
            self.start()

    # ------------------------------------------------------------------ init

    def _init_backends(self) -> None:
        try:
            import edge_tts

            self._edge_module = edge_tts
            self._edge_ok = self._player.available
            if not self._player.available:
                logger.warning("MCI playback unavailable (not Windows); edge-tts disabled")
        except ImportError:
            logger.warning("edge-tts is not installed. Install with: pip install edge-tts")

        try:
            import pyttsx3

            self._pyttsx3_module = pyttsx3
        except ImportError:
            logger.warning("pyttsx3 is not installed (offline fallback unavailable)")

        if self._edge_ok:
            self._backend = "edge-tts"
            self._selected_voice_id = EDGE_VOICES[self._active_language][0]
            self._selected_voice_name = self._selected_voice_id
        elif self._pyttsx3_module is not None:
            self._backend = "pyttsx3"

        logger.info("%s TTS backend: %s", ASSISTANT_NAME, self._backend)

    def _load_settings(self) -> None:
        try:
            self._rate = _safe_rate(settings_manager.get("voice.rate", DEFAULT_VOICE_RATE))
            self._volume = _safe_volume(settings_manager.get("voice.volume", DEFAULT_VOLUME))
            language = normalize_language(settings_manager.get("voice.language", DEFAULT_LANGUAGE))
        except Exception as exc:
            logger.warning("Failed to load voice settings (%s): %s", type(exc).__name__, exc)
            language = DEFAULT_LANGUAGE

        self._apply_language(language)

    def _apply_language(self, language: str) -> None:
        self._active_language = language
        self._requested_language = language
        voices = EDGE_VOICES.get(language, EDGE_VOICES[DEFAULT_LANGUAGE])
        self._tts_voice_language = language
        if self._edge_ok:
            self._selected_voice_id = voices[0]
            self._selected_voice_name = voices[0]
            self._voice_fallback_active = False
            self._voice_fallback_reason = None

    # -------------------------------------------------------------- settings

    def _apply_settings(self) -> None:
        self._load_settings()

    def refresh_settings(self) -> None:
        if not self.is_available():
            return
        try:
            self._load_settings()
        except Exception as exc:
            logger.error("Failed to refresh TTS settings (%s): %s", type(exc).__name__, exc)

    def set_rate(self, rate: int, *, apply_immediately: bool = True, persist: bool = False) -> int:
        normalized = _safe_rate(rate)
        if apply_immediately:
            with self._lock:
                self._rate = normalized
        if persist:
            try:
                settings_manager.set("voice.rate", normalized, save=True)
            except Exception as exc:
                logger.warning("Failed to persist rate (%s): %s", type(exc).__name__, exc)
        return normalized

    def set_volume(self, volume: float, *, apply_immediately: bool = True, persist: bool = False) -> float:
        normalized = _safe_volume(volume)
        if apply_immediately:
            with self._lock:
                self._volume = normalized
        if persist:
            try:
                settings_manager.set("voice.volume", normalized, save=True)
            except Exception as exc:
                logger.warning("Failed to persist volume (%s): %s", type(exc).__name__, exc)
        return normalized

    def set_language(self, language: str, *, persist: bool = False) -> bool:
        normalized = normalize_language(language)
        if normalized not in SUPPORTED_LANGUAGES:
            logger.warning("Unsupported JEROX language: %s", language)
            return False
        with self._lock:
            self._apply_language(normalized)
        if persist:
            try:
                settings_manager.set("voice.language", normalized, save=True)
            except Exception as exc:
                logger.warning("Failed to persist language (%s): %s", type(exc).__name__, exc)
        return True

    def set_voice(self, voice_id: str, *, persist: bool = False) -> bool:
        """Compatibility only: JEROX's voice identity is locked to female."""
        return False

    # ------------------------------------------------------------ properties

    @property
    def language(self) -> str:
        return self._active_language

    @property
    def requested_language(self) -> str:
        return self._requested_language

    @property
    def tts_voice_language(self) -> str:
        return self._tts_voice_language

    @property
    def voice_fallback(self) -> bool:
        return self._voice_fallback_active

    @property
    def is_speaking(self) -> bool:
        return self._speaking_event.is_set()

    @property
    def is_running(self) -> bool:
        thread = self._worker_thread
        return bool(thread and thread.is_alive() and not self._shutdown)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def selected_voice(self) -> Optional[str]:
        return self._selected_voice_id

    @property
    def selected_voice_name(self) -> Optional[str]:
        return self._selected_voice_name

    def is_available(self) -> bool:
        return self._edge_ok or self._pyttsx3_module is not None

    # --------------------------------------------------------------- backends

    def _synthesize_edge(self, text: str, voice: str, path: str) -> None:
        communicate = self._edge_module.Communicate(
            text,
            voice,
            rate=_edge_rate(self._rate),
            volume=_edge_volume(self._volume),
        )
        asyncio.run(communicate.save(path))

    def _speak_edge(self, text: str, request_id: int) -> bool:
        """Speak with edge-tts. Returns True on success."""
        text = _clean_for_speech(text)
        if not text:
            logger.warning("Empty text for TTS, skipping.")
            return False

        voices = EDGE_VOICES.get(self._active_language, EDGE_VOICES[DEFAULT_LANGUAGE])

        for index, voice in enumerate(voices):
            if self._stop_event.is_set():
                return True

            path: Optional[str] = None
            try:
                fd, path = tempfile.mkstemp(suffix=".mp3", prefix="jerox_")
                os.close(fd)

                self._synthesize_edge(text, voice, path)

                if self._stop_event.is_set():
                    return True

                self._selected_voice_id = voice
                self._selected_voice_name = voice
                self._voice_fallback_active = index > 0
                self._voice_fallback_reason = "primary_voice_failed" if index > 0 else None

                self._player.play(path, alias=f"jerox{request_id}")
                return True

            except Exception as exc:
                logger.warning(
                    "edge-tts failed with %s (%s): %s", voice, type(exc).__name__, exc
                )
            finally:
                if path and os.path.exists(path):
                    with contextlib.suppress(OSError):
                        os.remove(path)

        return False

    def _ensure_fallback_engine(self) -> Optional[Any]:
        """Create the offline pyttsx3 engine (inside the worker thread)."""
        if self._fallback_engine is not None:
            return self._fallback_engine
        if self._pyttsx3_module is None:
            return None

        try:
            if sys.platform == "win32":
                try:
                    import pythoncom  # type: ignore
                    pythoncom.CoInitialize()
                except Exception:
                    try:
                        ctypes.windll.ole32.CoInitialize(None)
                    except Exception:
                        pass

            engine = self._pyttsx3_module.init()
            for voice in engine.getProperty("voices") or []:
                if _looks_female(voice):
                    engine.setProperty("voice", str(voice.id))
                    self._selected_voice_id = str(voice.id)
                    self._selected_voice_name = str(getattr(voice, "name", voice.id))
                    break
            self._fallback_engine = engine
            logger.info(
                "%s offline fallback voice: %s",
                ASSISTANT_NAME,
                self._selected_voice_name,
            )
            return engine
        except Exception as exc:
            logger.error("Failed to initialize pyttsx3 fallback (%s): %s", type(exc).__name__, exc)
            return None

    def _speak_fallback(self, text: str) -> bool:
        engine = self._ensure_fallback_engine()
        if engine is None:
            return False
        try:
            self._voice_fallback_active = True
            self._voice_fallback_reason = "edge_tts_unavailable_offline_voice"
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception as exc:
            logger.error("Offline TTS failed (%s): %s", type(exc).__name__, exc)
            return False

    def _speak_text(self, text: str, request_id: int) -> bool:
        if self._speak_edge(text, request_id):
            return True
        return self._speak_fallback(text)

    # -------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        with self._lock:
            if self._shutdown:
                return False
            if not self.is_available():
                return False
            if self._worker_thread and self._worker_thread.is_alive():
                return True

            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="AssistantX-JEROX-TTSWorker",
            )
            self._worker_thread.start()
            logger.info("%s TTS worker started", ASSISTANT_NAME)
            return True

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._queue.get(timeout=DEFAULT_QUEUE_TIMEOUT)
            except queue.Empty:
                continue

            try:
                if request.interrupt:
                    self._drain_queue()

                self._current_request = request
                self._speaking_event.set()

                cleaned = _clean_for_speech(request.text)
                if not cleaned:
                    continue

                ok = self._speak_text(cleaned, request.request_id)

                with self._lock:
                    if ok:
                        self._stats_completed += 1
                        self._stats_characters += len(cleaned)
                    else:
                        self._stats_failed += 1

                if ok:
                    logger.info("%s request #%d completed", ASSISTANT_NAME, request.request_id)
                else:
                    logger.error("%s request #%d failed", ASSISTANT_NAME, request.request_id)

                    
            except Exception as exc:
                logger.exception("TTS request #%d crashed: %s", request.request_id, exc)
                with self._lock:
                    self._stats_failed += 1


            finally:
                self._current_request = None
                self._speaking_event.clear()
                with contextlib.suppress(ValueError):
                    self._queue.task_done()

    def _drain_queue(self) -> int:
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

    # -------------------------------------------------------------- speech API

    def speak(self, text: str, *, interrupt: bool = False) -> Optional[int]:
        cleaned = _clean_for_speech(text)
        if not cleaned:
            return None

        with self._lock:
            if self._shutdown:
                return None
            if not self.is_available():
                logger.warning("%s TTS unavailable", ASSISTANT_NAME)
                return None
            if not self.is_running and not self.start():
                return None

            if interrupt:
                self._drain_queue()
                self._player.stop()

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

    def speak_async(self, text: str, *, interrupt: bool = False) -> Optional[int]:
        return self.speak(text, interrupt=interrupt)

    def speak_blocking(self, text: str) -> bool:
        cleaned = _clean_for_speech(text)
        if not cleaned:
            return False

        with self._lock:
            if self._shutdown:
                return False
            self._request_counter += 1
            request_id = self._request_counter

        self._speaking_event.set()
        try:
            ok = self._speak_edge(cleaned, request_id)
            if not ok:
                ok = self._speak_fallback(cleaned)
            with self._lock:
                if ok:
                    self._stats_completed += 1
                    self._stats_characters += len(cleaned)
                else:
                    self._stats_failed += 1
            return ok
        finally:
            self._speaking_event.clear()

    # ------------------------------------------------------------ stop / clear

    def stop(self) -> None:
        if not self.is_available():
            return

        removed = self._drain_queue()
        self._player.stop()

        engine = self._fallback_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception as exc:
                logger.warning("TTS stop failed (%s): %s", type(exc).__name__, exc)

        with self._lock:
            self._stats_stopped += 1

        logger.debug("%s speech stopped; removed=%d", ASSISTANT_NAME, removed)

    def clear_queue(self) -> int:
        return self._drain_queue()

    # ------------------------------------------------------------ enumeration

    def list_available_voices(self) -> list[dict[str, Any]]:
        """Voices JEROX can use (diagnostics only, not a selection API)."""
        result: list[dict[str, Any]] = []
        for language, voices in EDGE_VOICES.items():
            for voice in voices:
                result.append(
                    {
                        "id": voice,
                        "name": voice,
                        "languages": [language],
                        "female": True,
                        "detected_language": language,
                        "backend": "edge-tts",
                    }
                )
        return result

    # ------------------------------------------------------------ statistics

    def stats(self) -> SpeakerStats:
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
        statistics = self.stats()
        return {
            "assistant": ASSISTANT_NAME,
            "backend": self._backend,
            "edge_tts_available": self._edge_ok,
            "available": self.is_available(),
            "running": self.is_running,
            "speaking": self.is_speaking,
            "queue_size": self.queue_size,
            "shutdown": self._shutdown,
            "worker_alive": bool(self._worker_thread and self._worker_thread.is_alive()),
            "current_request_id": (
                self._current_request.request_id if self._current_request else None
            ),
            "language": self._active_language,
            "requested_language": self._requested_language,
            "tts_voice_language": self._tts_voice_language,
            "supported_languages": sorted(SUPPORTED_LANGUAGES),
            "rate": self._rate,
            "volume": self._volume,
            "gender": DEFAULT_GENDER,
            "voice_locked": True,
            "selected_voice_id": self._selected_voice_id,
            "selected_voice_name": self._selected_voice_name,
            "voice_fallback": self._voice_fallback_active,
            "voice_fallback_reason": self._voice_fallback_reason,
            "stats": {
                "queued": statistics.queued,
                "completed": statistics.completed,
                "interrupted": statistics.interrupted,
                "failed": statistics.failed,
                "stopped": statistics.stopped,
                "characters_spoken": statistics.characters_spoken,
            },
            "voice_count": len(self.list_available_voices()),
        }

    # ---------------------------------------------------------------- shutdown

    def shutdown(self, *, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> None:
        logger.info("Shutting down %s TTS", ASSISTANT_NAME)

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._stop_event.set()

        self._drain_queue()
        self._player.stop()

        engine = self._fallback_engine
        if engine is not None:
            with contextlib.suppress(Exception):
                engine.stop()

        thread = self._worker_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, float(timeout)))

        self._worker_thread = None
        logger.info("%s TTS shutdown complete", ASSISTANT_NAME)

    def restart(self) -> bool:
        with self._lock:
            if self._shutdown:
                return False
        self.stop()
        if not self.is_available():
            return False
        return self.start()


# ============================================================================
# Global singleton
# ============================================================================

speaker = TextToSpeech()

logger.info("%s global speaker initialized | female voice locked", ASSISTANT_NAME)


# ============================================================================
# Convenience functions
# ============================================================================


def speak(text: str, *, interrupt: bool = False) -> Optional[int]:
    return speaker.speak(text, interrupt=interrupt)


def stop_speaking() -> None:
    speaker.stop()


def is_speaking() -> bool:
    return speaker.is_speaking


def diagnostics() -> dict[str, Any]:
    return speaker.diagnostics()


__all__ = [
    "ASSISTANT_NAME",
    "SpeakerError",
    "SpeakerShutdownError",
    "SpeakerUnavailableError",
    "SpeechRequest",
    "SpeakerStats",
    "TextToSpeech",
    "speaker",
    "speak",
    "stop_speaking",
    "is_speaking",
    "diagnostics",
    "SUPPORTED_LANGUAGES",
    "normalize_language",
    "DEFAULT_GENDER",
    "DEFAULT_VOICE_PITCH",
    "DEFAULT_VOICE_RATE",
    "DEFAULT_VOLUME",
]
