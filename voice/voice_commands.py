"""
voice_commands.py
==================
A small library of voice-specific command shortcuts and utterance
normalization helpers that sit between raw STT output
(voice/recognizer.py) and the brain/ classification pipeline.

Purpose: spoken language has quirks that typed text usually doesn't —
filler words ("um", "uh"), STT mishearing common phrases, and
voice-specific shortcuts ("stop talking", "cancel that", "never mind")
that should short-circuit straight to an action rather than going
through full intent classification. Handling these here keeps
brain/classifier.py focused on genuine command/conversation classification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)

_FILLER_WORDS_PATTERN = re.compile(r"\b(um+|uh+|erm+|like|you know|i mean)\b", re.I)
_MULTI_SPACE_PATTERN = re.compile(r"\s+")


class VoiceShortcut(str, Enum):
    """Immediate, voice-only meta-commands that bypass normal classification."""

    STOP_SPEAKING = "stop_speaking"
    CANCEL = "cancel"
    REPEAT = "repeat"
    LOUDER = "louder"
    QUIETER = "quieter"
    SLEEP_MODE = "sleep_mode"  # tell the assistant to stop listening for wake word


@dataclass
class VoiceShortcutMatch:
    shortcut: VoiceShortcut
    matched_text: str


_SHORTCUT_PATTERNS: list[tuple[re.Pattern, VoiceShortcut]] = [
    (re.compile(r"\b(stop talking|be quiet|shut up|stop speaking)\b", re.I), VoiceShortcut.STOP_SPEAKING),
    (re.compile(r"\b(cancel|never mind|nevermind|forget it)\b", re.I), VoiceShortcut.CANCEL),
    (re.compile(r"\b(say that again|repeat that|what did you say|pardon)\b", re.I), VoiceShortcut.REPEAT),
    (re.compile(r"\b(speak up|louder please|can'?t hear you)\b", re.I), VoiceShortcut.LOUDER),
    (re.compile(r"\b(too loud|quieter please|lower your voice)\b", re.I), VoiceShortcut.QUIETER),
    (re.compile(r"\b(go to sleep|stop listening|sleep mode)\b", re.I), VoiceShortcut.SLEEP_MODE),
]


def normalize_utterance(raw_text: str) -> str:
    """
    Clean up raw STT output before it reaches the classifier: strip
    filler words, collapse whitespace, and normalize casing/punctuation
    quirks common in transcribed speech.
    """
    cleaned = _FILLER_WORDS_PATTERN.sub("", raw_text)
    cleaned = _MULTI_SPACE_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.strip(" .,!?")
    return cleaned


def strip_wake_word(text: str, wake_phrase: str) -> str:
    """
    Remove a leading wake-word phrase from an utterance, e.g. transform
    "hey assistant open chrome" into "open chrome", so the remainder is
    fed to the classifier as a normal command. Handles the wake word
    appearing with or without a following comma.
    """
    pattern = re.compile(rf"^\s*{re.escape(wake_phrase)}\s*[,]?\s*", re.I)
    return pattern.sub("", text).strip()


def detect_shortcut(text: str) -> Optional[VoiceShortcutMatch]:
    """
    Check whether an utterance matches one of the voice-only meta
    command shortcuts. Returns None if no shortcut applies, in which
    case the utterance should proceed to normal brain/ classification.
    """
    for pattern, shortcut in _SHORTCUT_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.debug("Voice shortcut detected: %s (matched %r)", shortcut.value, match.group(0))
            return VoiceShortcutMatch(shortcut=shortcut, matched_text=match.group(0))
    return None


def prepare_utterance_for_classification(raw_text: str, wake_phrase: Optional[str] = None) -> tuple[str, Optional[VoiceShortcutMatch]]:
    """
    Full pre-processing pipeline for a freshly transcribed voice
    utterance: strip the wake word (if configured), normalize filler
    words, and check for a voice-only shortcut.

    Returns:
        A tuple of (cleaned_text, shortcut_match_or_None). If
        shortcut_match is not None, the caller should handle it directly
        rather than passing cleaned_text into brain.decision_engine.
    """
    text = raw_text
    if wake_phrase:
        text = strip_wake_word(text, wake_phrase)

    shortcut = detect_shortcut(text)
    cleaned = normalize_utterance(text)
    return cleaned, shortcut
    