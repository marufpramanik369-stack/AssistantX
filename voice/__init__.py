"""
voice
=====
Speech I/O package for AssistantX: speech-to-text (recognizer.py),
text-to-speech (speaker.py), wake-word detection (wake_word.py), audio
pre-processing (noise_filter.py), locale metadata (languages.py), and
voice-specific utterance handling (voice_commands.py).

Typical flow:

    wake_word_detector.start(on_wake=handle_wake)
        │  (user says "hey assistant")
        ▼
    recognizer.listen_and_transcribe()   -> RecognitionResult
        │
        ▼
    voice_commands.prepare_utterance_for_classification()
        │  (strips wake word, checks for shortcuts like "stop talking")
        ▼
    brain.decision_engine.process(cleaned_text)   [outside this package]
        │
        ▼
    speaker.speak(response_text)
"""

from __future__ import annotations

from voice.languages import LanguageProfile, detect_script_language, get_language_profile, list_supported_codes
from voice.noise_filter import AmbientNoiseCalibrator, VADResult, detect_voice_activity, trim_silence
from voice.recognizer import RecognitionError, RecognitionResult, SpeechRecognizer, recognizer
from voice.speaker import TextToSpeech, speaker
from voice.voice_commands import (
    VoiceShortcut,
    VoiceShortcutMatch,
    detect_shortcut,
    normalize_utterance,
    prepare_utterance_for_classification,
    strip_wake_word,
)
from voice.wake_word import WakeWordDetector, wake_word_detector

__all__ = [
    # recognizer
    "SpeechRecognizer",
    "RecognitionResult",
    "RecognitionError",
    "recognizer",
    # speaker
    "TextToSpeech",
    "speaker",
    # wake word
    "WakeWordDetector",
    "wake_word_detector",
    # languages
    "LanguageProfile",
    "get_language_profile",
    "list_supported_codes",
    "detect_script_language",
    # noise filter
    "AmbientNoiseCalibrator",
    "VADResult",
    "detect_voice_activity",
    "trim_silence",
    # voice commands
    "VoiceShortcut",
    "VoiceShortcutMatch",
    "detect_shortcut",
    "normalize_utterance",
    "strip_wake_word",
    "prepare_utterance_for_classification",
]
