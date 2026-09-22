"""
AssistantX Voice Package
========================

Unified speech I/O layer for AssistantX.

This package provides:

    • Speech-to-Text (STT)
    • Text-to-Speech (TTS)
    • Wake-word detection
    • Audio noise filtering / VAD
    • Language and locale detection
    • Voice shortcut / utterance processing

Typical flow
------------

    Wake Word
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
    TextToSpeech


Example
-------

    from voice import (
        recognizer,
        speaker,
        wake_word_detector,
        prepare_utterance_for_classification,
    )

    wake_word_detector.start(
        on_wake=lambda: print("Wake word detected")
    )

    result = recognizer.listen_and_transcribe()

    if result.success:
        text = prepare_utterance_for_classification(result.text)

        if text:
            speaker.speak(f"You said: {text}")


Package Design
--------------

The package intentionally exposes only stable public APIs.

Internal implementation details should remain inside individual
modules so that STT/TTS engines, wake-word backends, language
registries, and audio-processing implementations can evolve without
requiring changes throughout AssistantX.
"""

from __future__ import annotations

import contextlib

# ============================================================================
# Package Metadata
# ============================================================================

__version__ = "1.0.0"
__author__ = "AssistantX"
__package_name__ = "AssistantX Voice"


# ============================================================================
# Recognizer / Speech-to-Text
# ============================================================================

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
    VADResult,
    detect_voice_activity,
    trim_silence,
)
from voice.recognizer import (
    RecognitionError,
    RecognitionResult,
    SpeechRecognizer,
    recognizer,
)

# ============================================================================
# Speaker / Text-to-Speech
# ============================================================================
from voice.speaker import (
    TextToSpeech,
    speaker,
)

# ============================================================================
# Voice Commands / Shortcuts
# ============================================================================
from voice.voice_commands import (
    VoiceShortcut,
    VoiceShortcutMatch,
    detect_shortcut,
    normalize_utterance,
    prepare_utterance_for_classification,
    strip_wake_word,
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
    "AmbientNoiseCalibrator",
    "LanguageProfile",
    "RecognitionError",
    "RecognitionResult",
    "SpeechRecognizer",
    "TextToSpeech",
    "VADResult",
    "VoiceShortcut",
    "VoiceShortcutMatch",
    "WakeWordDetector",
    "__author__",
    "__package_name__",
    "__version__",
    "detect_script_language",
    "detect_shortcut",
    "detect_voice_activity",
    "get_language_profile",
    "list_supported_codes",
    "normalize_utterance",
    "prepare_utterance_for_classification",
    "recognizer",
    "speaker",
    "strip_wake_word",
    "trim_silence",
    "wake_word_detector",
]


# ============================================================================
# Package Diagnostics
# ============================================================================

def diagnostics() -> dict:
    """
    Return a lightweight diagnostic snapshot for the voice package.

    This function intentionally avoids exposing secrets, microphone
    recordings, API keys, or internal audio data.
    """

    result: dict = {
        "package": __package_name__,
        "version": __version__,
        "components": {
            "recognizer": False,
            "speaker": False,
            "wake_word": False,
            "languages": False,
            "noise_filter": False,
            "voice_commands": False,
        },
    }

    # ------------------------------------------------------------------------
    # Recognizer
    # ------------------------------------------------------------------------
    try:
        result["components"]["recognizer"] = bool(
            recognizer.is_available()
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["recognizer"] = False

    # ------------------------------------------------------------------------
    # Speaker
    # ------------------------------------------------------------------------
    try:
        result["components"]["speaker"] = bool(
            speaker.is_available()
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["speaker"] = False

    # ------------------------------------------------------------------------
    # Wake Word
    # ------------------------------------------------------------------------
    try:
        detector_stats = wake_word_detector.stats()

        result["components"]["wake_word"] = isinstance(
            detector_stats,
            dict,
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["wake_word"] = False

    # ------------------------------------------------------------------------
    # Languages
    # ------------------------------------------------------------------------
    try:
        result["components"]["languages"] = bool(
            list_supported_codes()
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["languages"] = False

    # ------------------------------------------------------------------------
    # Noise Filter
    # ------------------------------------------------------------------------
    try:
        # The filter module itself is dependency-light, so availability
        # means the public API can be accessed successfully.
        result["components"]["noise_filter"] = callable(
            detect_voice_activity
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["noise_filter"] = False

    # ------------------------------------------------------------------------
    # Voice Commands
    # ------------------------------------------------------------------------
    try:
        result["components"]["voice_commands"] = callable(
            prepare_utterance_for_classification
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        result["components"]["voice_commands"] = False

    result["healthy_components"] = sum(
        1
        for value in result["components"].values()
        if value
    )

    result["total_components"] = len(result["components"])

    result["healthy"] = (
        result["healthy_components"]
        == result["total_components"]
    )

    return result


# ============================================================================
# Package Status
# ============================================================================

def is_ready() -> bool:
    """
    Return True when all voice components are accessible.

    This does not guarantee that a physical microphone, speaker,
    network STT engine, or optional backend is currently available.
    """

    try:
        return bool(diagnostics()["healthy"])
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


# ============================================================================
# Safe Shutdown
# ============================================================================

def shutdown() -> None:
    """
    Safely shut down voice resources.

    This function is intentionally defensive so that failure in one
    component does not prevent the remaining components from shutting down.
    """

    # Stop wake-word detector first.
    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        wake_word_detector.stop()

    # Stop / shut down TTS worker.
    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        speaker.shutdown()

    # Shut down recognizer resources.
    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        recognizer.shutdown()


# ============================================================================
# Package Restart
# ============================================================================

def restart() -> None:
    """
    Restart voice services where supported.

    Individual components control their own lifecycle.
    """

    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        recognizer.restart()

    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        speaker.restart()


# ============================================================================
# Extend Public API
# ============================================================================

__all__.extend(
    [
        "diagnostics",
        "is_ready",
        "restart",
        "shutdown",
    ]
)
