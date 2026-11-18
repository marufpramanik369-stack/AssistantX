"""
AssistantX Voice Package
========================

Unified speech I/O layer for AssistantX.

Public responsibilities
-----------------------
- Speech-to-Text (STT)
- Text-to-Speech (TTS)
- Fixed JEROX wake-word detection
- PCM audio analysis / VAD / filtering
- Bengali / English / Hindi language support
- Voice shortcut and utterance processing

Typical flow
------------

    JEROX Wake Word
          │
          ▼
    SpeechRecognizer
          │
          ▼
    Noise Filter / VAD
          │
          ▼
    Voice Command Processor
          │
          ▼
    Brain / Decision Engine
          │
          ▼
    Female JEROX TTS


Architecture
------------

This package is the stable public boundary for AssistantX voice
functionality.

Individual implementation details remain inside:

    voice.languages
    voice.recognizer
    voice.speaker
    voice.wake_word
    voice.noise_filter
    voice.voice_commands

The package itself does not implement microphone access, TTS,
wake-word recognition, or audio processing logic.

Important
---------

JEROX is a fixed assistant identity.

    Wake word : JEROX
    Voice     : Female
    Gender    : Fixed

Language may change between supported languages, but the assistant's
female voice identity must not be changed through this package.
"""

from __future__ import annotations

import contextlib


# ============================================================================
# Package Metadata
# ============================================================================

__version__ = "1.0.0"
__author__ = "AssistantX"
__package_name__ = "AssistantX Voice"

# Fixed assistant identity exposed by the voice package.
ASSISTANT_NAME = "JEROX"
FIXED_WAKE_WORD = "jerox"
FIXED_VOICE_GENDER = "female"

SUPPORTED_VOICE_LANGUAGES = (
    "bn",
    "en",
    "hi",
)


# ============================================================================
# Language Support
# ============================================================================

from voice.languages import (
    LanguageProfile,
    detect_script_language,
    get_language_profile,
    list_supported_codes,
)


# ============================================================================
# Audio Processing
# ============================================================================

from voice.noise_filter import (
    AmbientNoiseCalibrator,
    AudioConfigurationError,
    AudioFormatError,
    AudioMetrics,
    NoiseFilter,
    NoiseFilterError,
    NoiseFilterStats,
    TrimResult,
    VADResult,
    analyze_audio,
    compute_peak,
    compute_rms,
    detect_voice_activity,
    filter_audio,
    get_audio_metrics,
    is_voice,
    noise_filter,
    normalize_volume,
    trim_silence,
    trim_silence_with_result,
)


# ============================================================================
# Speech-to-Text
# ============================================================================

from voice.recognizer import (
    RecognitionError,
    RecognitionResult,
    SpeechRecognizer,
    recognizer,
)


# ============================================================================
# Text-to-Speech
# ============================================================================

from voice.speaker import (
    TextToSpeech,
    speaker,
)

# ---------------------------------------------------------------------------
# Backward-compatible dashboard API
# ---------------------------------------------------------------------------
# Some dashboard components import `Speaker` directly from `voice`.
# The canonical implementation is `TextToSpeech`; exposing this alias keeps
# the existing voice architecture unchanged while restoring that public API.
Speaker = TextToSpeech


# ============================================================================
# Voice Commands
# ============================================================================

from voice.voice_commands import (
    VoiceShortcut,
    VoiceShortcutMatch,
    detect_shortcut,
    normalize_utterance,
    prepare_utterance_for_classification,
    strip_wake_word,
    wake_word_present,
)


# ============================================================================
# Wake Word
# ============================================================================

from voice.wake_word import (
    WakeWordDetector,
    wake_word_detector,
)


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # ------------------------------------------------------------------
    # Package metadata / identity
    # ------------------------------------------------------------------
    "__author__",
    "__package_name__",
    "__version__",
    "ASSISTANT_NAME",
    "FIXED_WAKE_WORD",
    "FIXED_VOICE_GENDER",
    "SUPPORTED_VOICE_LANGUAGES",

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    "LanguageProfile",
    "detect_script_language",
    "get_language_profile",
    "list_supported_codes",

    # ------------------------------------------------------------------
    # Recognizer / STT
    # ------------------------------------------------------------------
    "RecognitionError",
    "RecognitionResult",
    "SpeechRecognizer",
    "recognizer",

    # ------------------------------------------------------------------
    # Speaker / TTS
    # ------------------------------------------------------------------
    "TextToSpeech",
    "Speaker",
    "speaker",

    # ------------------------------------------------------------------
    # Wake word
    # ------------------------------------------------------------------
    "WakeWordDetector",
    "wake_word_detector",

    # ------------------------------------------------------------------
    # Voice commands
    # ------------------------------------------------------------------
    "VoiceShortcut",
    "VoiceShortcutMatch",
    "detect_shortcut",
    "normalize_utterance",
    "prepare_utterance_for_classification",
    "strip_wake_word",
    "wake_word_present",

    # ------------------------------------------------------------------
    # Audio analysis
    # ------------------------------------------------------------------
    "AudioMetrics",
    "VADResult",
    "TrimResult",
    "compute_rms",
    "compute_peak",
    "analyze_audio",
    "get_audio_metrics",
    "detect_voice_activity",
    "is_voice",

    # ------------------------------------------------------------------
    # Audio processing
    # ------------------------------------------------------------------
    "NoiseFilter",
    "NoiseFilterError",
    "AudioFormatError",
    "AudioConfigurationError",
    "NoiseFilterStats",
    "AmbientNoiseCalibrator",
    "noise_filter",
    "filter_audio",
    "normalize_volume",
    "trim_silence",
    "trim_silence_with_result",

    # ------------------------------------------------------------------
    # Package lifecycle / diagnostics
    # ------------------------------------------------------------------
    "diagnostics",
    "is_ready",
    "restart",
    "shutdown",
]


# ============================================================================
# Package Diagnostics
# ============================================================================


def diagnostics() -> dict:
    """
    Return a safe diagnostic snapshot for the complete voice package.

    No microphone recordings, API keys, secrets, or raw audio are exposed.
    """
    result: dict = {
        "package": __package_name__,
        "version": __version__,
        "identity": {
            "assistant_name": ASSISTANT_NAME,
            "wake_word": FIXED_WAKE_WORD,
            "voice_gender": FIXED_VOICE_GENDER,
            "voice_gender_locked": True,
            "supported_languages": list(
                SUPPORTED_VOICE_LANGUAGES
            ),
        },
        "components": {
            "recognizer": False,
            "speaker": False,
            "wake_word": False,
            "languages": False,
            "noise_filter": False,
            "voice_commands": False,
        },
    }

    # ------------------------------------------------------------------
    # Recognizer
    # ------------------------------------------------------------------
    try:
        result["components"]["recognizer"] = bool(
            recognizer.is_available()
        )
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["recognizer"] = False

    # ------------------------------------------------------------------
    # Speaker
    # ------------------------------------------------------------------
    try:
        result["components"]["speaker"] = bool(
            speaker.is_available()
        )
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["speaker"] = False

    # ------------------------------------------------------------------
    # Wake Word
    # ------------------------------------------------------------------
    try:
        wake_stats = wake_word_detector.stats()

        result["components"]["wake_word"] = isinstance(
            wake_stats,
            dict,
        )

        if isinstance(wake_stats, dict):
            result["wake_word"] = {
                "fixed": True,
                "word": FIXED_WAKE_WORD,
                "stats": wake_stats,
            }

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["wake_word"] = False

    # ------------------------------------------------------------------
    # Languages
    # ------------------------------------------------------------------
    try:
        supported_codes = list_supported_codes()

        result["components"]["languages"] = bool(
            supported_codes
        )

        result["languages"] = {
            "supported_codes": list(
                supported_codes
            )
            if supported_codes
            else [],
        }

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["languages"] = False

    # ------------------------------------------------------------------
    # Noise Filter
    # ------------------------------------------------------------------
    try:
        result["components"]["noise_filter"] = all(
            callable(function)
            for function in (
                compute_rms,
                compute_peak,
                detect_voice_activity,
                filter_audio,
            )
        )

        if result["components"]["noise_filter"]:
            with contextlib.suppress(
                AttributeError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                result["noise_filter"] = (
                    noise_filter.diagnostics()
                )

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["noise_filter"] = False

    # ------------------------------------------------------------------
    # Voice Commands
    # ------------------------------------------------------------------
    try:
        result["components"]["voice_commands"] = all(
            callable(function)
            for function in (
                normalize_utterance,
                strip_wake_word,
                prepare_utterance_for_classification,
            )
        )

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["voice_commands"] = False

    # ------------------------------------------------------------------
    # Health summary
    # ------------------------------------------------------------------
    healthy_components = sum(
        1
        for value in result["components"].values()
        if value
    )

    total_components = len(
        result["components"]
    )

    result["healthy_components"] = (
        healthy_components
    )

    result["total_components"] = (
        total_components
    )

    result["healthy"] = (
        healthy_components == total_components
    )

    return result


# ============================================================================
# Package Readiness
# ============================================================================


def is_ready() -> bool:
    """
    Return True when all public voice components are accessible.

    This does NOT guarantee that:

    - a physical microphone is available,
    - a speaker device is available,
    - an STT network backend is reachable,
    - an optional wake-word backend is installed,
    - a TTS engine has a suitable female voice installed.

    It only verifies package-level component readiness.
    """
    try:
        return bool(
            diagnostics()["healthy"]
        )
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


# ============================================================================
# Safe Shutdown
# ============================================================================


def shutdown() -> None:
    """
    Safely shut down all voice resources.

    Shutdown order:

        Wake Word
            ↓
        Speaker / TTS
            ↓
        Recognizer / STT

    Failure in one component does not prevent cleanup of others.
    """

    # --------------------------------------------------------------
    # Wake word must stop first.
    # --------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        wake_word_detector.stop()

    # --------------------------------------------------------------
    # TTS worker / engine.
    # --------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        speaker.shutdown()

    # --------------------------------------------------------------
    # STT / recognizer resources.
    # --------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        recognizer.shutdown()


# ============================================================================
# Package Restart
# ============================================================================


def restart() -> None:
    """
    Restart restartable voice services.

    Component lifecycle remains owned by each individual module.
    """
    # --------------------------------------------------------------
    # Recognizer
    # --------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        recognizer.restart()

    # --------------------------------------------------------------
    # Speaker
    # --------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        speaker.restart()


# ============================================================================
# End of Package
# ============================================================================

# ============================================================================
# Compatibility Diagnostic API
# ============================================================================

def voice_diagnostics() -> dict:
    """
    Public compatibility diagnostic API for the AssistantX voice package.

    Keeps the legacy diagnostics() structure intact while exposing the
    canonical JEROX identity fields at the top level.
    """
    result = diagnostics()

    identity = result.get("identity", {})

    result["assistant_name"] = identity.get(
        "assistant_name",
        ASSISTANT_NAME,
    )

    result["voice_gender"] = identity.get(
        "voice_gender",
        FIXED_VOICE_GENDER,
    )

    result["supported_languages"] = list(
        identity.get(
            "supported_languages",
            SUPPORTED_VOICE_LANGUAGES,
        )
    )

    result["fixed_wake_word"] = identity.get(
        "wake_word",
        FIXED_WAKE_WORD,
    )

    result["status"] = (
        "healthy"
        if result.get("healthy", False)
        else "degraded"
    )

    return result

