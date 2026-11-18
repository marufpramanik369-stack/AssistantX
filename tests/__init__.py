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
- Package-level diagnostics and lifecycle management

Architecture
------------

    JEROX Wake Word
          |
          v
    SpeechRecognizer
          |
          v
    Noise Filter / VAD
          |
          v
    Voice Command Processor
          |
          v
    Brain / Decision Engine
          |
          v
    Female JEROX TTS

Important
---------

JEROX is a fixed assistant identity.

    Assistant : JEROX
    Wake word : jerox
    Voice     : Female
    Gender    : Fixed

Supported languages:

    bn = Bengali
    en = English
    hi = Hindi

Language may change, but the JEROX female voice identity
and wake word remain locked.
"""

from __future__ import annotations

import contextlib
from typing import Any


# ============================================================================
# Package Metadata
# ============================================================================

__version__ = "1.0.0"
__author__ = "AssistantX"
__package_name__ = "AssistantX Voice"


# ============================================================================
# Fixed JEROX Identity
# ============================================================================

ASSISTANT_NAME = "JEROX"
FIXED_WAKE_WORD = "jerox"
FIXED_VOICE_GENDER = "female"

VOICE_GENDER_LOCKED = True
WAKE_WORD_LOCKED = True

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
    # Metadata
    "__author__",
    "__package_name__",
    "__version__",

    # Fixed identity
    "ASSISTANT_NAME",
    "FIXED_WAKE_WORD",
    "FIXED_VOICE_GENDER",
    "VOICE_GENDER_LOCKED",
    "WAKE_WORD_LOCKED",
    "SUPPORTED_VOICE_LANGUAGES",

    # Language
    "LanguageProfile",
    "detect_script_language",
    "get_language_profile",
    "list_supported_codes",

    # Recognizer
    "RecognitionError",
    "RecognitionResult",
    "SpeechRecognizer",
    "recognizer",

    # Speaker
    "TextToSpeech",
    "speaker",

    # Wake word
    "WakeWordDetector",
    "wake_word_detector",

    # Voice commands
    "VoiceShortcut",
    "VoiceShortcutMatch",
    "detect_shortcut",
    "normalize_utterance",
    "prepare_utterance_for_classification",
    "strip_wake_word",
    "wake_word_present",

    # Audio analysis
    "AudioMetrics",
    "VADResult",
    "TrimResult",
    "compute_rms",
    "compute_peak",
    "analyze_audio",
    "get_audio_metrics",
    "detect_voice_activity",
    "is_voice",

    # Audio processing
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

    # Package lifecycle
    "diagnostics",
    "voice_diagnostics",
    "is_ready",
    "restart",
    "shutdown",
]


# ============================================================================
# Internal Safe Call
# ============================================================================

def _safe_component_check(
    component: Any,
    method_name: str,
) -> bool:
    """Safely check whether a voice component reports availability."""
    try:
        method = getattr(component, method_name, None)

        if not callable(method):
            return False

        return bool(method())

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


# ============================================================================
# Package Diagnostics
# ============================================================================

def diagnostics() -> dict[str, Any]:
    """
    Return a safe diagnostic snapshot for the complete voice package.

    No microphone recordings, raw audio, API keys, or secrets are exposed.

    The returned structure intentionally contains both:

        identity = {...}

    and compatibility-level fields:

        assistant_name
        voice_gender
        supported_languages
        fixed_wake_word

    This keeps the package convenient for application health checks.
    """

    supported_languages = list(SUPPORTED_VOICE_LANGUAGES)

    result: dict[str, Any] = {
        "module": "voice",
        "package": __package_name__,
        "version": __version__,

        # ----------------------------------------------------------------
        # Stable top-level identity fields
        # ----------------------------------------------------------------
        "assistant_name": ASSISTANT_NAME,
        "fixed_wake_word": FIXED_WAKE_WORD,
        "voice_gender": FIXED_VOICE_GENDER,
        "voice_gender_locked": VOICE_GENDER_LOCKED,
        "wake_word_locked": WAKE_WORD_LOCKED,
        "supported_languages": supported_languages,

        # ----------------------------------------------------------------
        # Nested identity information
        # ----------------------------------------------------------------
        "identity": {
            "assistant_name": ASSISTANT_NAME,
            "wake_word": FIXED_WAKE_WORD,
            "voice_gender": FIXED_VOICE_GENDER,
            "voice_gender_locked": VOICE_GENDER_LOCKED,
            "wake_word_locked": WAKE_WORD_LOCKED,
            "supported_languages": supported_languages,
        },

        # ----------------------------------------------------------------
        # Component health
        # ----------------------------------------------------------------
        "components": {
            "recognizer": False,
            "speaker": False,
            "wake_word": False,
            "languages": False,
            "noise_filter": False,
            "voice_commands": False,
        },

        "status": "unhealthy",
    }

    # =========================================================================
    # Recognizer
    # =========================================================================

    result["components"]["recognizer"] = _safe_component_check(
        recognizer,
        "is_available",
    )

    # =========================================================================
    # Speaker
    # =========================================================================

    result["components"]["speaker"] = _safe_component_check(
        speaker,
        "is_available",
    )

    # =========================================================================
    # Wake Word
    # =========================================================================

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
                "locked": WAKE_WORD_LOCKED,
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

    # =========================================================================
    # Languages
    # =========================================================================

    try:
        supported_codes = list_supported_codes()

        normalized_codes = [
            str(code).strip().lower()
            for code in supported_codes
            if str(code).strip()
        ]

        result["components"]["languages"] = all(
            language in normalized_codes
            for language in SUPPORTED_VOICE_LANGUAGES
        )

        result["languages"] = {
            "supported_codes": normalized_codes,
            "required_codes": supported_languages,
        }

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["languages"] = False

    # =========================================================================
    # Noise Filter
    # =========================================================================

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
                result["noise_filter"] = noise_filter.diagnostics()

    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        result["components"]["noise_filter"] = False

    # =========================================================================
    # Voice Commands
    # =========================================================================

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

    # =========================================================================
    # Health Summary
    # =========================================================================

    component_values = list(
        result["components"].values()
    )

    healthy_components = sum(
        1
        for value in component_values
        if value
    )

    total_components = len(component_values)

    result["healthy_components"] = healthy_components
    result["total_components"] = total_components
    result["healthy"] = (
        healthy_components == total_components
    )

    result["status"] = (
        "healthy"
        if result["healthy"]
        else "degraded"
    )

    return result


# ============================================================================
# Compatibility Diagnostic API
# ============================================================================

def voice_diagnostics() -> dict[str, Any]:
    """
    Public compatibility wrapper for voice package diagnostics.

    This is the canonical package-level diagnostic entry point used by:

        AssistantX health checks
        startup validation
        dashboard status
        automated tests
        CLI diagnostics

    Returns the same diagnostic structure as ``diagnostics()``.
    """
    return diagnostics()


# ============================================================================
# Package Readiness
# ============================================================================

def is_ready() -> bool:
    """
    Return True when all public voice components are accessible.

    This does not guarantee that:

    - a physical microphone is available,
    - a speaker device is available,
    - an STT network backend is reachable,
    - an optional wake-word backend is installed,
    - a TTS engine has a suitable female voice installed.

    It verifies package-level component readiness.
    """

    try:
        return bool(
            voice_diagnostics().get("healthy", False)
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
            |
            v
        Speaker / TTS
            |
            v
        Recognizer / STT

    Failure in one component does not prevent cleanup of others.
    """

    # ----------------------------------------------------------------
    # Wake word
    # ----------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        wake_word_detector.stop()

    # ----------------------------------------------------------------
    # Speaker / TTS
    # ----------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        speaker.shutdown()

    # ----------------------------------------------------------------
    # Recognizer / STT
    # ----------------------------------------------------------------
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

    Individual modules remain responsible for their own lifecycle.
    """

    # ----------------------------------------------------------------
    # Recognizer
    # ----------------------------------------------------------------
    with contextlib.suppress(
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        recognizer.restart()

    # ----------------------------------------------------------------
    # Speaker
    # ----------------------------------------------------------------
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
