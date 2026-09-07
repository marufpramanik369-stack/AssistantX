"""
languages.py
============
Language/locale definitions for the voice subsystem — separate from the
UI-facing SUPPORTED_LANGUAGES dict in config/constants.py because this
module also carries voice-engine-specific metadata (recognizer locale
codes, TTS voice name hints, RTL flags) that the dashboard doesn't need.

Used by:
    - voice/recognizer.py: to pick the correct speech_recognition locale
    - voice/speaker.py: to pick an appropriate TTS voice for the language
    - voice/wake_word.py: to select language-appropriate wake phrases
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.constants import DEFAULT_LANGUAGE_CODE


@dataclass(frozen=True)
class LanguageProfile:
    """Everything the voice pipeline needs to know about one language/locale."""

    code: str                     # BCP-47 style code, e.g. 'en-US'
    display_name: str
    native_name: str
    recognizer_locale: str        # code passed to the STT engine
    tts_voice_hints: tuple[str, ...]  # substrings to match against OS voice names
    default_wake_words: tuple[str, ...]
    is_rtl: bool = False


LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "en-US": LanguageProfile(
        code="en-US",
        display_name="English (US)",
        native_name="English",
        recognizer_locale="en-US",
        tts_voice_hints=("en_US", "en-US", "English (America)", "Zira", "David"),
        default_wake_words=("hey assistant", "hey computer", "ok assistant"),
    ),
    "en-GB": LanguageProfile(
        code="en-GB",
        display_name="English (UK)",
        native_name="English",
        recognizer_locale="en-GB",
        tts_voice_hints=("en_GB", "en-GB", "English (Britain)", "Hazel"),
        default_wake_words=("hey assistant", "hey computer"),
    ),
    "bn-BD": LanguageProfile(
        code="bn-BD",
        display_name="Bangla (Bangladesh)",
        native_name="বাংলা",
        recognizer_locale="bn-BD",
        tts_voice_hints=("bn_BD", "bn-BD", "Bangla", "Bengali"),
        default_wake_words=("হেই অ্যাসিস্ট্যান্ট", "হ্যালো অ্যাসিস্ট্যান্ট"),
    ),
    "hi-IN": LanguageProfile(
        code="hi-IN",
        display_name="Hindi (India)",
        native_name="हिन्दी",
        recognizer_locale="hi-IN",
        tts_voice_hints=("hi_IN", "hi-IN", "Hindi"),
        default_wake_words=("हे असिस्टेंट",),
    ),
}


def get_language_profile(code: Optional[str] = None) -> LanguageProfile:
    """
    Resolve a language code to its LanguageProfile, falling back to the
    default language if the code is unknown or unspecified.
    """
    resolved = code or DEFAULT_LANGUAGE_CODE
    profile = LANGUAGE_PROFILES.get(resolved)
    if profile is None:
        # Try a loose match on just the primary subtag (e.g. 'en' -> 'en-US')
        primary = resolved.split("-")[0].lower()
        for candidate_code, candidate_profile in LANGUAGE_PROFILES.items():
            if candidate_code.lower().startswith(primary):
                return candidate_profile
        return LANGUAGE_PROFILES[DEFAULT_LANGUAGE_CODE]
    return profile


def list_supported_codes() -> list[str]:
    return list(LANGUAGE_PROFILES.keys())


def is_bangla(code: str) -> bool:
    return code.lower().startswith("bn")


def detect_script_language(text: str) -> str:
    """
    Very lightweight heuristic language detector based on Unicode block
    ranges — used as a fallback when the user hasn't explicitly set a
    language and we want to guess which TTS voice profile fits their
    typed/spoken text best (e.g. auto-switching Bangla <-> English).

    This is NOT a substitute for a real language-ID model; it only
    distinguishes Bangla script vs. Latin script, which is the practical
    bilingual case AssistantX targets out of the box.
    """
    bangla_chars = sum(1 for ch in text if "\u0980" <= ch <= "\u09FF")
    latin_chars = sum(1 for ch in text if ch.isascii() and ch.isalpha())

    if bangla_chars > latin_chars:
        return "bn-BD"
    return "en-US"
    