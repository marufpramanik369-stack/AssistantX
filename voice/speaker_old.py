"""
voice/speaker.py — JEROX Professional Text-to-Speech Engine

Thread-safe, asynchronous offline TTS engine for AssistantX / JEROX.

VOICE POLICY
============
JEROX has a FIXED FEMALE voice identity.

    Assistant Name : JEROX
    Voice Gender   : FEMALE (LOCKED)
    Supported      : Bengali (bn), English (en), Hindi (hi)

The user/application cannot manually change the voice identity.

Only speech RATE and VOLUME are configurable.

IMPORTANT
=========
pyttsx3 can only use voices installed on the operating system.

When a native female voice for the requested language is unavailable,
JEROX uses another AVAILABLE FEMALE voice as a TTS fallback.

This does NOT change the requested language configuration.

Example:
    requested language = bn
    available female SAPI voice = English Zira

Result:
    configured language = bn
    voice gender = female
    actual TTS voice = Zira
    fallback = True

A MALE voice is never intentionally selected as fallback.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from config.settings import settings_manager
from voice.languages import get_language_profile

logger = logging.getLogger(__name__)


# ============================================================================
# JEROX VOICE POLICY
# ============================================================================

ASSISTANT_NAME = "JEROX"

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
MAX_SPEECH_LENGTH = 10000


# ============================================================================
# Supported Languages
# ============================================================================

SUPPORTED_LANGUAGES = frozenset(
    {
        "bn",
        "en",
        "hi",
    }
)

LANGUAGE_ALIASES: dict[str, str] = {
    "bn": "bn",
    "bn-bd": "bn",
    "bn-in": "bn",
    "bengali": "bn",
    "bangla": "bn",

    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "en-au": "en",
    "english": "en",

    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
}


# ============================================================================
# Female Voice Detection
# ============================================================================

FEMALE_VOICE_MARKERS = frozenset(
    {
        "female",
        "woman",
        "girl",
        "victoria",
        "samantha",
        "zira",
        "hazel",
        "susan",
        "sarah",
        "natasha",
        "heera",
        "veena",
        "priya",
        "neerja",
        "kalpana",
        "raveena",
        "aditi",
        "lekha",
        "tania",
    }
)


# ============================================================================
# Text Cleanup
# ============================================================================

_MARKDOWN_STRIP_PATTERN = re.compile(r"[*_`#>~\[\]{}|]")




_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,.!?;:])")
_REPEATED_PUNCT_PATTERN = re.compile(r"([!?.,])\1{1,}")


# ============================================================================
# Logging State
# ============================================================================

# Prevent repeated fallback warnings during dashboard refreshes.
_logged_fallbacks: set[tuple[str, str]] = set()
_fallback_log_lock = threading.Lock()


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
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    """A single queued speech request."""

    text: str
    interrupt: bool = False
    request_id: int = 0
    created_at: float = 0.0


@dataclass(frozen=True, slots=True)
class SpeakerStats:
    """Runtime JEROX TTS statistics."""

    queued: int = 0
    completed: int = 0
    interrupted: int = 0
    failed: int = 0
    stopped: int = 0
    characters_spoken: int = 0


# ============================================================================
# Language Helpers
# ============================================================================


def normalize_language(language: Any) -> str:
    """
    Normalize language into:

        bn
        en
        hi

    Unknown values fall back to English.
    """

    if language is None:
        return "en"

    value = str(language).strip().lower().replace("_", "-")

    if not value:
        return "en"

    normalized = LANGUAGE_ALIASES.get(value)

    if normalized:
        return normalized

    base = value.split("-", 1)[0]

    return LANGUAGE_ALIASES.get(base, "en")


def _language_candidates(language_code: str) -> set[str]:
    """Build language matching candidates."""

    normalized = str(language_code or "en").strip().lower()
    normalized = normalized.replace("_", "-")

    base = normalize_language(normalized)

    candidates = {
        normalized,
        base,
    }

    if base == "bn":
        candidates.update(
            {
                "bn",
                "bn-bd",
                "bn-in",
                "bengali",
                "bangla",
            }
        )

    elif base == "en":
        candidates.update(
            {
                "en",
                "en-us",
                "en-gb",
                "english",
            }
        )

    elif base == "hi":
        candidates.update(
            {
                "hi",
                "hi-in",
                "hindi",
            }
        )

    return candidates


# ============================================================================
# Voice Metadata Helpers
# ============================================================================


def _decode_voice_language(value: Any) -> str:
    """Safely decode a pyttsx3 voice language value."""

    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return value.decode(
                    encoding,
                    errors="ignore",
                )
            except Exception:
                continue

    return str(value or "")


def _voice_haystack(voice: Any) -> str:
    """Build normalized searchable metadata for a voice."""

    voice_id = str(
        getattr(voice, "id", "") or ""
    )

    voice_name = str(
        getattr(voice, "name", "") or ""
    )

    raw_languages = (
        getattr(voice, "languages", [])
        or []
    )

    languages: list[str] = []

    for language in raw_languages:
        languages.append(
            _decode_voice_language(language)
        )

    return " ".join(
        [
            voice_id,
            voice_name,
            *languages,
        ]
    ).lower()


def _looks_female(voice: Any) -> bool:
    """
    Determine whether an installed voice appears to be female.

    pyttsx3 does not provide a reliable portable gender property,
    therefore voice metadata/name heuristics are used.
    """

    haystack = _voice_haystack(voice)

    return any(
        marker in haystack
        for marker in FEMALE_VOICE_MARKERS
    )


def _voice_language(voice: Any) -> Optional[str]:
    """
    Try to determine the primary language of an installed voice.

    This is diagnostic metadata only.
    """

    haystack = _voice_haystack(voice)

    # Order matters: more specific locale first.
    language_patterns = (
        ("bn", ("bn-bd", "bn_in", "bn-in", "bengali", "bangla")),
        ("hi", ("hi-in", "hindi")),
        ("en", ("en-us", "en-gb", "en-au", "english")),
    )

    for language_code, markers in language_patterns:
        if any(marker in haystack for marker in markers):
            return language_code

    # Some Windows voice IDs contain language LCID values.
    # Do not guess aggressively; unknown remains None.
    return None


# ============================================================================
# Fallback Logging
# ============================================================================


def _log_fallback_once(
    requested_language: str,
    voice_name: str,
) -> None:
    """Log each language/voice fallback only once."""

    key = (
        requested_language,
        voice_name,
    )

    with _fallback_log_lock:
        if key in _logged_fallbacks:
            return

        _logged_fallbacks.add(key)

    logger.info(
        "%s female TTS fallback active: "
        "requested_language=%s voice=%s",
        ASSISTANT_NAME,
        requested_language,
        voice_name,
    )


# ============================================================================
# Text Cleaning
# ============================================================================


def _clean_for_speech(
    text: str,
    *,
    max_length: int = MAX_SPEECH_LENGTH,
) -> str:
    """Clean text before TTS playback."""

    if text is None:
        return ""

    try:
        cleaned = str(text)
    except (TypeError, ValueError):
        logger.debug(
            "Failed to convert text to string (type=%s)",
            type(text).__name__,
        )
        return ""

    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    if len(cleaned) > max_length:
        logger.debug(
            "Text exceeded %d chars; truncating from %d",
            max_length,
            len(cleaned),
        )
        cleaned = cleaned[:max_length]

    cleaned = _MARKDOWN_STRIP_PATTERN.sub(
        "",
        cleaned,
    )

    cleaned = _SPACE_BEFORE_PUNCT_PATTERN.sub(
        r"\1",
        cleaned,
    )

    cleaned = _REPEATED_PUNCT_PATTERN.sub(
        r"\1",
        cleaned,
    )

    cleaned = _MULTI_SPACE_PATTERN.sub(
        " ",
        cleaned,
    )

    result = cleaned.strip()

    logger.debug(
        "Text cleaned: %d -> %d chars",
        len(text),
        len(result),
    )

    return result


# ============================================================================
# Validation Helpers
# ============================================================================


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    """Clamp a value between minimum and maximum."""

    return max(
        minimum,
        min(maximum, value),
    )


def _safe_rate(value: Any) -> int:
    """Normalize speech rate to 50-400 WPM."""

    try:
        rate = int(value)
    except (TypeError, ValueError):
        rate = DEFAULT_VOICE_RATE

    return int(
        _clamp(
            rate,
            MIN_RATE,
            MAX_RATE,
        )
    )


def _safe_volume(value: Any) -> float:
    """Normalize volume to 0.0-1.0."""

    try:
        volume = float(value)
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME

    return _clamp(
        volume,
        MIN_VOLUME,
        MAX_VOLUME,
    )


# ============================================================================
# TextToSpeech Engine
# ============================================================================


class TextToSpeech:
    """
    Thread-safe JEROX Text-to-Speech manager.

    Voice identity is permanently locked to FEMALE.

    User-configurable:
        - language: bn / en / hi
        - rate
        - volume

    Not user-configurable:
        - gender
        - voice identity
    """

    def __init__(
        self,
        *,
        auto_start: bool = True,
    ) -> None:

        logger.info(
            "Initializing %s TTS engine (female voice locked)",
            ASSISTANT_NAME,
        )

        self._lock = threading.RLock()

        self._engine_module: Optional[Any] = None
        self._engine: Optional[Any] = None

        self._queue: queue.Queue[SpeechRequest] = (
            queue.Queue()
        )

        self._worker_thread: Optional[
            threading.Thread
        ] = None

        self._stop_event = threading.Event()
        self._speaking_event = threading.Event()

        self._shutdown = False
        self._request_counter = 0

        self._current_request: Optional[
            SpeechRequest
        ] = None

        # --------------------------------------------------------------------
        # Language state
        # --------------------------------------------------------------------

        # IMPORTANT:
        # This remains the requested/configured language.
        self._active_language = "en"
        self._requested_language = "en"

        # Actual installed TTS voice language.
        # May differ when female fallback is required.
        self._tts_voice_language = "en"

        self._voice_fallback_active = False
        self._voice_fallback_reason: Optional[str] = None

        self._selected_voice_id: Optional[str] = None
        self._selected_voice_name: Optional[str] = None

        # Runtime statistics.
        self._stats_queued = 0
        self._stats_completed = 0
        self._stats_interrupted = 0
        self._stats_failed = 0
        self._stats_stopped = 0
        self._stats_characters = 0

        self._init_backend()

        if auto_start and self.is_available():
            self.start()

    # ========================================================================
    # Backend Initialization
    # ========================================================================

    def _init_backend(self) -> None:
        """Initialize pyttsx3 backend."""

        logger.debug(
            "Initializing pyttsx3 backend"
        )

        try:
            import pyttsx3

            self._engine_module = pyttsx3

        except ImportError:
            logger.warning(
                "pyttsx3 is not installed. "
                "Install with: pip install pyttsx3"
            )
            return

        try:
            self._engine = pyttsx3.init()

            logger.info(
                "%s pyttsx3 engine initialized successfully",
                ASSISTANT_NAME,
            )

        except Exception as exc:
            logger.error(
                "Failed to initialize pyttsx3 (%s): %s",
                type(exc).__name__,
                exc,
            )

            self._engine = None
            return

        try:
            self._apply_settings()

        except Exception as exc:
            logger.warning(
                "Initial TTS settings failed (%s): %s",
                type(exc).__name__,
                exc,
            )

    # ========================================================================
    # Settings
    # ========================================================================

    def _apply_settings(self) -> None:
        """
        Apply allowed TTS settings.

        Language remains the requested language.

        If a native female voice is unavailable,
        an available female fallback voice is selected.

        Gender remains FEMALE-LOCKED.
        """

        engine = self._engine

        if engine is None:
            return

        rate = settings_manager.get(
            "voice.rate",
            DEFAULT_VOICE_RATE,
        )

        volume = settings_manager.get(
            "voice.volume",
            DEFAULT_VOLUME,
        )

        language = settings_manager.get(
            "voice.language",
            "en",
        )

        normalized_language = normalize_language(
            language
        )

        self._requested_language = (
            normalized_language
        )

        self._active_language = (
            normalized_language
        )

        safe_rate = _safe_rate(rate)
        safe_volume = _safe_volume(volume)

        engine.setProperty(
            "rate",
            safe_rate,
        )

        engine.setProperty(
            "volume",
            safe_volume,
        )

        self._select_voice_for_language(
            normalized_language
        )

        logger.debug(
            "%s settings applied: "
            "language=%s rate=%d volume=%.2f "
            "tts_voice_language=%s fallback=%s",
            ASSISTANT_NAME,
            normalized_language,
            safe_rate,
            safe_volume,
            self._tts_voice_language,
            self._voice_fallback_active,
        )

    # ========================================================================
    # Runtime Rate
    # ========================================================================

    def set_rate(
        self,
        rate: int,
        *,
        apply_immediately: bool = True,
        persist: bool = False,
    ) -> int:
        """Set speech rate."""

        normalized = _safe_rate(rate)

        with self._lock:
            engine = self._engine

            if engine is not None and apply_immediately:
                try:
                    engine.setProperty(
                        "rate",
                        normalized,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to apply rate (%s): %s",
                        type(exc).__name__,
                        exc,
                    )

        if persist:
            try:
                settings_manager.set(
                    "voice.rate",
                    normalized,
                    save=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist rate (%s): %s",
                    type(exc).__name__,
                    exc,
                )

        return normalized

    # ========================================================================
    # Runtime Volume
    # ========================================================================

    def set_volume(
        self,
        volume: float,
        *,
        apply_immediately: bool = True,
        persist: bool = False,
    ) -> float:
        """Set speech volume."""

        normalized = _safe_volume(volume)

        with self._lock:
            engine = self._engine

            if engine is not None and apply_immediately:
                try:
                    engine.setProperty(
                        "volume",
                        normalized,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to apply volume (%s): %s",
                        type(exc).__name__,
                        exc,
                    )

        if persist:
            try:
                settings_manager.set(
                    "voice.volume",
                    normalized,
                    save=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist volume (%s): %s",
                    type(exc).__name__,
                    exc,
                )

        return normalized

    # ========================================================================
    # Female Voice Selection
    # ========================================================================

    def _select_voice_for_language(
        self,
        language_code: str,
    ) -> Optional[str]:
        """
        Select a FEMALE voice.

        Priority:

            1. Female + requested language + profile hint
            2. Female + requested language
            3. Any available female voice

        IMPORTANT:

        Priority 3 is a FEMALE-ONLY fallback.

        A male voice is NEVER selected.
        """

        engine = self._engine

        if engine is None:
            return None

        language_code = normalize_language(
            language_code
        )

        try:
            profile = get_language_profile(
                language_code
            )

        except Exception as exc:
            logger.debug(
                "Language profile unavailable for %s (%s): %s",
                language_code,
                type(exc).__name__,
                exc,
            )
            profile = None

        try:
            available_voices = (
                engine.getProperty("voices")
                or []
            )

        except Exception as exc:
            logger.warning(
                "Failed to enumerate voices (%s): %s",
                type(exc).__name__,
                exc,
            )
            return None

        if not available_voices:
            logger.warning(
                "No OS voices installed for %s",
                ASSISTANT_NAME,
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

        language_candidates = (
            _language_candidates(
                language_code
            )
        )

        # --------------------------------------------------------------------
        # Priority 1:
        # Female + language profile hint
        # --------------------------------------------------------------------

        for voice in available_voices:

            if not _looks_female(voice):
                continue

            haystack = _voice_haystack(
                voice
            )

            if hints and any(
                hint in haystack
                for hint in hints
            ):
                if self._activate_voice(
                    voice,
                    language_code,
                    reason=(
                        "female + profile hint"
                    ),
                    fallback=False,
                ):
                    return str(
                        getattr(
                            voice,
                            "id",
                            "",
                        )
                    )

        # --------------------------------------------------------------------
        # Priority 2:
        # Female + requested language
        # --------------------------------------------------------------------

        for voice in available_voices:

            if not _looks_female(voice):
                continue

            haystack = _voice_haystack(
                voice
            )

            if any(
                candidate in haystack
                for candidate in language_candidates
            ):
                if self._activate_voice(
                    voice,
                    language_code,
                    reason="female + language",
                    fallback=False,
                ):
                    return str(
                        getattr(
                            voice,
                            "id",
                            "",
                        )
                    )

        # --------------------------------------------------------------------
        # Priority 3:
        # FEMALE-ONLY fallback
        #
        # This is the important fix.
        #
        # bn/hi remain the requested languages.
        # Only the installed TTS voice changes.
        # --------------------------------------------------------------------

        for voice in available_voices:

            if not _looks_female(voice):
                continue

            if self._activate_voice(
                voice,
                language_code,
                reason="female fallback",
                fallback=True,
            ):
                return str(
                    getattr(
                        voice,
                        "id",
                        "",
                    )
                )

        logger.warning(
            "No female TTS voice available for %s",
            ASSISTANT_NAME,
        )

        self._voice_fallback_active = False
        self._voice_fallback_reason = (
            "no_female_voice_available"
        )

        return None

    def _activate_voice(
        self,
        voice: Any,
        language_code: str,
        *,
        reason: str,
        fallback: bool,
    ) -> bool:
        """Activate a verified female voice."""

        engine = self._engine

        if engine is None:
            return False

        # --------------------------------------------------------------------
        # HARD FEMALE LOCK
        # --------------------------------------------------------------------

        if not _looks_female(voice):
            logger.error(
                "Blocked non-female voice activation: %s",
                getattr(
                    voice,
                    "name",
                    "",
                ),
            )
            return False

        voice_id = str(
            getattr(
                voice,
                "id",
                "",
            )
            or ""
        )

        voice_name = str(
            getattr(
                voice,
                "name",
                voice_id,
            )
            or voice_id
        )

        if not voice_id:
            return False

        try:
            engine.setProperty(
                "voice",
                voice_id,
            )

        except Exception as exc:
            logger.debug(
                "Failed to activate voice %s (%s): %s",
                voice_id,
                type(exc).__name__,
                exc,
            )
            return False

        actual_language = (
            _voice_language(voice)
            or "unknown"
        )

        self._selected_voice_id = voice_id
        self._selected_voice_name = voice_name

        # IMPORTANT:
        # Requested language stays unchanged.
        self._active_language = language_code
        self._requested_language = language_code

        self._tts_voice_language = (
            actual_language
        )

        self._voice_fallback_active = (
            bool(fallback)
        )

        self._voice_fallback_reason = (
            "native_female_voice_unavailable"
            if fallback
            else None
        )

        if fallback:
            _log_fallback_once(
                language_code,
                voice_name,
            )

            logger.debug(
                "%s fallback details: "
                "requested_language=%s "
                "actual_voice_language=%s",
                ASSISTANT_NAME,
                language_code,
                actual_language,
            )

        else:
            logger.info(
                "%s female voice selected: %s | "
                "language=%s | reason=%s",
                ASSISTANT_NAME,
                voice_name,
                language_code,
                reason,
            )

        return True

    # ========================================================================
    # Language Control
    # ========================================================================

    def set_language(
        self,
        language: str,
        *,
        persist: bool = False,
    ) -> bool:
        """
        Change JEROX speech language.

        Supported:

            bn
            en
            hi

        Voice gender remains permanently FEMALE.

        If a native female voice does not exist,
        an available female voice is used as fallback.

        The requested language itself is NOT changed.
        """

        normalized = normalize_language(
            language
        )

        if normalized not in SUPPORTED_LANGUAGES:
            logger.warning(
                "Unsupported JEROX language: %s",
                language,
            )
            return False

        with self._lock:

            if self._engine is None:
                return False

            selected = (
                self._select_voice_for_language(
                    normalized
                )
            )

            if selected is None:
                return False

            # IMPORTANT:
            # Always retain requested language.
            self._active_language = normalized
            self._requested_language = normalized

        if persist:
            try:
                settings_manager.set(
                    "voice.language",
                    normalized,
                    save=True,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist language (%s): %s",
                    type(exc).__name__,
                    exc,
                )

        return True

    @property
    def language(self) -> str:
        """Return requested/active speech language."""

        return self._active_language

    @property
    def requested_language(self) -> str:
        """Return the requested language."""

        return self._requested_language

    @property
    def tts_voice_language(self) -> str:
        """Return detected installed TTS voice language."""

        return self._tts_voice_language

    @property
    def voice_fallback(self) -> bool:
        """Return whether a female fallback voice is active."""

        return self._voice_fallback_active

    # ========================================================================
    # State
    # ========================================================================

    def is_available(self) -> bool:
        """Return whether TTS engine is available."""

        with self._lock:
            return self._engine is not None

    @property
    def is_speaking(self) -> bool:
        """Return whether JEROX is currently speaking."""

        return self._speaking_event.is_set()

    @property
    def is_running(self) -> bool:
        """Return whether the worker thread is alive."""

        thread = self._worker_thread

        return bool(
            thread
            and thread.is_alive()
            and not self._shutdown
        )

    @property
    def queue_size(self) -> int:
        """Return number of pending requests."""

        return self._queue.qsize()

    @property
    def selected_voice(self) -> Optional[str]:
        """Return currently selected female voice ID."""

        return self._selected_voice_id

    @property
    def selected_voice_name(self) -> Optional[str]:
        """Return currently selected female voice name."""

        return self._selected_voice_name

    # ========================================================================
    # Worker Lifecycle
    # ========================================================================

    def start(self) -> bool:
        """Start background TTS worker."""

        with self._lock:

            if self._shutdown:
                logger.warning(
                    "Cannot start %s after shutdown",
                    ASSISTANT_NAME,
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

            self._worker_thread = (
                threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name="AssistantX-JEROX-TTSWorker",
                )
            )

            self._worker_thread.start()

            logger.info(
                "%s TTS worker started",
                ASSISTANT_NAME,
            )

            return True

    def _worker_loop(self) -> None:
        """Process queued speech requests."""

        logger.debug(
            "%s TTS worker loop started",
            ASSISTANT_NAME,
        )

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
                    with self._lock:
                        self._stats_failed += 1
                    continue

                try:
                    engine.say(cleaned)
                    engine.runAndWait()

                    with self._lock:
                        self._stats_completed += 1
                        self._stats_characters += (
                            len(cleaned)
                        )

                    logger.info(
                        "%s request #%d completed",
                        ASSISTANT_NAME,
                        request.request_id,
                    )

                except Exception as exc:

                    with self._lock:
                        self._stats_failed += 1

                    logger.error(
                        "TTS playback failed for "
                        "request #%d (%s): %s",
                        request.request_id,
                        type(exc).__name__,
                        exc,
                    )

            finally:

                self._current_request = None
                self._speaking_event.clear()

                with contextlib.suppress(
                    ValueError
                ):
                    self._queue.task_done()

        logger.debug(
            "%s TTS worker loop stopped",
            ASSISTANT_NAME,
        )

    def _drain_queue(self) -> int:
        """Remove all pending speech requests."""

        removed = 0

        while True:

            try:
                self._queue.get_nowait()

            except queue.Empty:
                break

            with contextlib.suppress(
                ValueError
            ):
                self._queue.task_done()

            removed += 1

        if removed:

            with self._lock:
                self._stats_interrupted += removed

        return removed

    # ========================================================================
    # Speech API
    # ========================================================================

    def speak(
        self,
        text: str,
        *,
        interrupt: bool = False,
    ) -> Optional[int]:
        """Queue asynchronous speech."""

        cleaned = _clean_for_speech(text)

        if not cleaned:
            return None

        with self._lock:

            if self._shutdown:
                return None

            if not self.is_available():
                logger.warning(
                    "%s TTS unavailable",
                    ASSISTANT_NAME,
                )
                return None

            if not self.is_running:

                if not self.start():
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
    ) -> Optional[int]:
        """Explicit asynchronous alias."""

        return self.speak(
            text,
            interrupt=interrupt,
        )

    def speak_blocking(
        self,
        text: str,
    ) -> bool:
        """Speak synchronously."""

        cleaned = _clean_for_speech(text)

        if not cleaned:
            return False

        with self._lock:

            if self._shutdown:
                return False

            engine = self._engine

            if engine is None:
                return False

        self._speaking_event.set()

        try:

            engine.say(cleaned)
            engine.runAndWait()

            with self._lock:
                self._stats_completed += 1
                self._stats_characters += (
                    len(cleaned)
                )

            return True

        except Exception as exc:

            with self._lock:
                self._stats_failed += 1

            logger.error(
                "Blocking TTS failed (%s): %s",
                type(exc).__name__,
                exc,
            )

            return False

        finally:
            self._speaking_event.clear()

    # ========================================================================
    # Stop / Queue Control
    # ========================================================================

    def stop(self) -> None:
        """Stop current speech and clear pending requests."""

        if not self.is_available():
            return

        removed = self._drain_queue()

        with self._lock:
            engine = self._engine

        try:

            if engine is not None:
                engine.stop()

        except Exception as exc:

            logger.warning(
                "TTS stop failed (%s): %s",
                type(exc).__name__,
                exc,
            )

        with self._lock:
            self._stats_stopped += 1

        logger.debug(
            "%s speech stopped; removed=%d",
            ASSISTANT_NAME,
            removed,
        )

    def clear_queue(self) -> int:
        """Clear pending speech without stopping current speech."""

        return self._drain_queue()

    # ========================================================================
    # Settings Refresh
    # ========================================================================

    def refresh_settings(self) -> None:
        """
        Refresh allowed settings.

        Rate and volume are refreshed.

        Requested language is refreshed.

        Voice identity remains FEMALE-LOCKED.
        """

        if not self.is_available():
            return

        try:
            self._apply_settings()

        except Exception as exc:
            logger.error(
                "Failed to refresh TTS settings (%s): %s",
                type(exc).__name__,
                exc,
            )

    # ========================================================================
    # Voice Enumeration
    # ========================================================================

    def list_available_voices(
        self,
    ) -> list[dict[str, Any]]:
        """
        Return installed OS voices for diagnostics.

        This method is NOT a voice-selection API.

        JEROX remains FEMALE-LOCKED.
        """

        engine = self._engine

        if engine is None:
            return []

        try:

            voices = (
                engine.getProperty("voices")
                or []
            )

        except Exception as exc:

            logger.warning(
                "Failed to enumerate voices (%s): %s",
                type(exc).__name__,
                exc,
            )

            return []

        result: list[dict[str, Any]] = []

        for voice in voices:

            voice_id = str(
                getattr(
                    voice,
                    "id",
                    "",
                )
                or ""
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

            raw_languages = (
                getattr(
                    voice,
                    "languages",
                    [],
                )
                or []
            )

            languages = [
                _decode_voice_language(
                    language
                )
                for language in raw_languages
            ]

            result.append(
                {
                    "id": voice_id,
                    "name": name,
                    "languages": languages,
                    "female": _looks_female(
                        voice
                    ),
                    "detected_language": (
                        _voice_language(voice)
                    ),
                }
            )

        return result

    # ========================================================================
    # Locked Voice API
    # ========================================================================

    def set_voice(
        self,
        voice_id: str,
        *,
        persist: bool = False,
    ) -> bool:
        """
        Compatibility method.

        Manual voice switching is intentionally disabled.

        JEROX's voice identity is permanently FEMALE.

        Returns:
            False always.
        """

        logger.debug(
            "Manual voice switching is disabled. "
            "%s uses a fixed FEMALE voice.",
            ASSISTANT_NAME,
        )

        return False

    # ========================================================================
    # Statistics
    # ========================================================================

    def stats(self) -> SpeakerStats:
        """Return runtime statistics."""

        with self._lock:

            return SpeakerStats(
                queued=self._stats_queued,
                completed=self._stats_completed,
                interrupted=self._stats_interrupted,
                failed=self._stats_failed,
                stopped=self._stats_stopped,
                characters_spoken=(
                    self._stats_characters
                ),
            )

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed diagnostic information."""

        statistics = self.stats()

        return {
            "assistant": ASSISTANT_NAME,

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

            # ---------------------------------------------------------------
            # Language information
            # ---------------------------------------------------------------

            "language": self._active_language,
            "requested_language": (
                self._requested_language
            ),
            "tts_voice_language": (
                self._tts_voice_language
            ),

            "supported_languages": sorted(
                SUPPORTED_LANGUAGES
            ),

            # ---------------------------------------------------------------
            # Fixed identity
            # ---------------------------------------------------------------

            "gender": DEFAULT_GENDER,
            "voice_locked": True,

            "selected_voice_id": (
                self._selected_voice_id
            ),

            "selected_voice_name": (
                self._selected_voice_name
            ),

            # ---------------------------------------------------------------
            # Fallback information
            # ---------------------------------------------------------------

            "voice_fallback": (
                self._voice_fallback_active
            ),

            "voice_fallback_reason": (
                self._voice_fallback_reason
            ),

            # ---------------------------------------------------------------
            # Statistics
            # ---------------------------------------------------------------

            "stats": {
                "queued": statistics.queued,
                "completed": statistics.completed,
                "interrupted": statistics.interrupted,
                "failed": statistics.failed,
                "stopped": statistics.stopped,
                "characters_spoken": (
                    statistics.characters_spoken
                ),
            },

            "voice_count": len(
                self.list_available_voices()
            ),
        }

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(
        self,
        *,
        timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        """Gracefully shut down the TTS subsystem."""

        logger.info(
            "Shutting down %s TTS",
            ASSISTANT_NAME,
        )

        with self._lock:

            if self._shutdown:
                return

            self._shutdown = True
            self._stop_event.set()

        self._drain_queue()

        try:

            engine = self._engine

            if engine is not None:
                engine.stop()

        except Exception as exc:

            logger.warning(
                "Engine stop failed (%s): %s",
                type(exc).__name__,
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

        logger.info(
            "%s TTS shutdown complete",
            ASSISTANT_NAME,
        )

    # ========================================================================
    # Restart
    # ========================================================================

    def restart(self) -> bool:
        """Restart the TTS worker."""

        with self._lock:

            if self._shutdown:
                return False

        self.stop()

        if not self.is_available():
            return False

        return self.start()


# ============================================================================
# Global Singleton
# ============================================================================

speaker = TextToSpeech()

logger.info(
    "%s global speaker initialized | female voice locked",
    ASSISTANT_NAME,
)


# ============================================================================
# Convenience Functions
# ============================================================================


def speak(
    text: str,
    *,
    interrupt: bool = False,
) -> Optional[int]:
    """Queue asynchronous speech through global JEROX speaker."""

    return speaker.speak(
        text,
        interrupt=interrupt,
    )


def stop_speaking() -> None:
    """Stop current speech and clear pending queue."""

    speaker.stop()


def is_speaking() -> bool:
    """Return whether JEROX is currently speaking."""

    return speaker.is_speaking


def diagnostics() -> dict[str, Any]:
    """Return global JEROX speaker diagnostics."""

    return speaker.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Identity
    "ASSISTANT_NAME",

    # Exceptions
    "SpeakerError",
    "SpeakerShutdownError",
    "SpeakerUnavailableError",

    # Models
    "SpeechRequest",
    "SpeakerStats",

    # Engine
    "TextToSpeech",
    "speaker",

    # Convenience
    "speak",
    "stop_speaking",
    "is_speaking",
    "diagnostics",

    # Language
    "SUPPORTED_LANGUAGES",
    "normalize_language",

    # Voice policy
    "DEFAULT_GENDER",
    "DEFAULT_VOICE_PITCH",
    "DEFAULT_VOICE_RATE",
    "DEFAULT_VOLUME",
]
