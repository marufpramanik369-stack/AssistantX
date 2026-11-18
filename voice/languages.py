"""
voice/languages.py
==================

Language and locale definitions for the AssistantX voice subsystem.

JEROX Voice Policy
-------------------
- Supported languages:
    - Bengali / Bangla: bn-BD
    - English: en-US / en-GB
    - Hindi: hi-IN

- TTS voice identity is female-only.
- Language selection may change the language/locale,
  but must never change the gender policy.
- Male voice hints are intentionally excluded from the
  female TTS hint lists.

This module contains voice-engine-specific language metadata.
Dashboard-facing language configuration remains in
config/constants.py.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from config.constants import DEFAULT_LANGUAGE_CODE


# ============================================================================
# Constants
# ============================================================================

DEFAULT_CODE = DEFAULT_LANGUAGE_CODE

BANGSLA_PRIMARY = "bn"
ENGLISH_PRIMARY = "en"
HINDI_PRIMARY = "hi"

SUPPORTED_PRIMARY_CODES = frozenset(
    {
        BANGSLA_PRIMARY,
        ENGLISH_PRIMARY,
        HINDI_PRIMARY,
    }
)

# JEROX voice policy.
SUPPORTED_VOICE_LANGUAGES = frozenset(
    {
        BANGSLA_PRIMARY,
        ENGLISH_PRIMARY,
        HINDI_PRIMARY,
    }
)

FIXED_TTS_GENDER = "female"

# Common Unicode script ranges.
BENGALI_RANGE_START = 0x0980
BENGALI_RANGE_END = 0x09FF

DEVANAGARI_RANGE_START = 0x0900
DEVANAGARI_RANGE_END = 0x097F


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """
    Voice-pipeline metadata for one language/locale.

    Attributes
    ----------
    code:
        Canonical BCP-47 style language code.

    display_name:
        Human-readable language name.

    native_name:
        Language name in its native script.

    recognizer_locale:
        Locale passed to the STT backend.

    tts_voice_hints:
        General language/locale hints used for TTS matching.

    female_tts_voice_hints:
        Female-specific voice-name hints.

    default_wake_words:
        Language-specific wake-word suggestions.

    is_rtl:
        Whether the language normally uses right-to-left text.

    aliases:
        Alternative language identifiers accepted by the resolver.
    """

    code: str
    display_name: str
    native_name: str
    recognizer_locale: str

    tts_voice_hints: tuple[str, ...]

    female_tts_voice_hints: tuple[str, ...]

    default_wake_words: tuple[str, ...]

    is_rtl: bool = False
    aliases: tuple[str, ...] = ()

    @property
    def primary_code(self) -> str:
        """Return the primary language subtag."""
        return self.code.split("-", 1)[0].lower()

    @property
    def region_code(self) -> str | None:
        """Return the region subtag when present."""
        parts = self.code.split("-")

        if len(parts) < 2:
            return None

        return parts[1].upper()

    @property
    def is_english(self) -> bool:
        return self.primary_code == ENGLISH_PRIMARY

    @property
    def is_bangla(self) -> bool:
        return self.primary_code == BANGSLA_PRIMARY

    @property
    def is_hindi(self) -> bool:
        return self.primary_code == HINDI_PRIMARY


@dataclass(frozen=True, slots=True)
class ScriptDetectionResult:
    """
    Result of lightweight Unicode-script language detection.

    This is heuristic detection only and should not be treated as
    a general-purpose language-identification model.
    """

    language_code: str
    confidence: float
    bengali_chars: int
    devanagari_chars: int
    latin_chars: int
    other_letters: int

    @property
    def is_confident(self) -> bool:
        """Return True when confidence is at least 60%."""
        return self.confidence >= 0.60


# ============================================================================
# Built-in Profiles
# ============================================================================

_BUILTIN_PROFILES: dict[str, LanguageProfile] = {
    # ------------------------------------------------------------------------
    # English - US
    # ------------------------------------------------------------------------
    "en-US": LanguageProfile(
        code="en-US",
        display_name="English (US)",
        native_name="English",
        recognizer_locale="en-US",

        tts_voice_hints=(
            "en_US",
            "en-US",
            "English (United States)",
            "English (America)",
        ),

        female_tts_voice_hints=(
            "Zira",
            "Jenny",
            "Aria",
            "Samantha",
            "Victoria",
        ),

        default_wake_words=(
            "hey assistant",
            "hey computer",
            "ok assistant",
            "okay assistant",
            "hey jerox",
            "hi jerox",
        ),

        aliases=(
            "en",
            "eng",
            "english",
            "english-us",
            "us-english",
        ),
    ),

    # ------------------------------------------------------------------------
    # English - UK
    # ------------------------------------------------------------------------
    "en-GB": LanguageProfile(
        code="en-GB",
        display_name="English (UK)",
        native_name="English",
        recognizer_locale="en-GB",

        tts_voice_hints=(
            "en_GB",
            "en-GB",
            "English (United Kingdom)",
            "English (Britain)",
        ),

        female_tts_voice_hints=(
            "Hazel",
            "Sonia",
            "Susan",
            "Libby",
        ),

        default_wake_words=(
            "hey assistant",
            "hey computer",
            "ok assistant",
            "hey jerox",
            "hi jerox",
        ),

        aliases=(
            "en-gb",
            "british-english",
            "uk-english",
        ),
    ),

    # ------------------------------------------------------------------------
    # Bangla - Bangladesh
    # ------------------------------------------------------------------------
    "bn-BD": LanguageProfile(
        code="bn-BD",
        display_name="Bangla (Bangladesh)",
        native_name="বাংলা",
        recognizer_locale="bn-BD",

        tts_voice_hints=(
            "bn_BD",
            "bn-BD",
            "Bangla",
            "Bengali",
            "Bangladesh",
        ),

        female_tts_voice_hints=(
            "Bangla",
            "Bengali",
            "Bangladesh",
        ),

        default_wake_words=(
            "হেই অ্যাসিস্ট্যান্ট",
            "হ্যালো অ্যাসিস্ট্যান্ট",
            "এই অ্যাসিস্ট্যান্ট",
            "হেই সহকারী",
            "হেই জেরক্স",
            "হ্যালো জেরক্স",
            "জেরক্স",
        ),

        aliases=(
            "bn",
            "ben",
            "bangla",
            "bengali",
            "bangla-bd",
            "bengali-bd",
        ),
    ),

    # ------------------------------------------------------------------------
    # Hindi - India
    # ------------------------------------------------------------------------
    "hi-IN": LanguageProfile(
        code="hi-IN",
        display_name="Hindi (India)",
        native_name="हिन्दी",
        recognizer_locale="hi-IN",

        tts_voice_hints=(
            "hi_IN",
            "hi-IN",
            "Hindi",
            "Hindi India",
        ),

        female_tts_voice_hints=(
            "Hindi",
            "Hindi India",
        ),

        default_wake_words=(
            "हे असिस्टेंट",
            "हेलो असिस्टेंट",
            "हे मोहना",
            "हेलो मोहना",
            "मोहना",
        ),

        aliases=(
            "hi",
            "hin",
            "hindi",
            "hindi-in",
        ),
    ),
}


# Immutable public mapping.
LANGUAGE_PROFILES: Mapping[str, LanguageProfile] = MappingProxyType(
    _BUILTIN_PROFILES
)


# ============================================================================
# Normalization Helpers
# ============================================================================


def normalize_language_code(code: str | None) -> str:
    """
    Normalize a language identifier.

    Examples
    --------
    EN_us -> en-US
    bn_bd -> bn-BD
    en   -> en
    """

    if not code:
        return ""

    value = str(code).strip()

    if not value:
        return ""

    value = value.replace("_", "-")

    parts = [
        part.strip()
        for part in value.split("-")
        if part.strip()
    ]

    if not parts:
        return ""

    primary = parts[0].lower()

    if len(parts) == 1:
        return primary

    normalized_parts = [primary]

    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized_parts.append(part.upper())
        else:
            normalized_parts.append(part)

    return "-".join(normalized_parts)


def normalize_text(text: str) -> str:
    """Normalize Unicode text for script analysis."""

    if not text:
        return ""

    return unicodedata.normalize(
        "NFC",
        str(text),
    )


# ============================================================================
# Language Resolution
# ============================================================================


def get_language_profile(
    code: str | None = None,
) -> LanguageProfile:
    """
    Resolve a language identifier to a LanguageProfile.

    Resolution order:

        1. Exact canonical code
        2. Alias
        3. Primary language subtag
        4. Default language
    """

    resolved = normalize_language_code(
        code or DEFAULT_CODE
    )

    if not resolved:
        resolved = normalize_language_code(DEFAULT_CODE)

    # Exact canonical match.
    profile = LANGUAGE_PROFILES.get(resolved)

    if profile is not None:
        return profile

    # Alias match.
    resolved_lower = resolved.lower()

    for candidate in LANGUAGE_PROFILES.values():
        aliases = {
            alias.lower()
            for alias in candidate.aliases
        }

        if resolved_lower in aliases:
            return candidate

    # Primary-language fallback.
    primary = resolved.split("-", 1)[0].lower()

    for candidate in LANGUAGE_PROFILES.values():
        if candidate.primary_code == primary:
            return candidate

    # Final safe fallback.
    default_profile = LANGUAGE_PROFILES.get(
        normalize_language_code(DEFAULT_CODE)
    )

    if default_profile is not None:
        return default_profile

    return next(iter(LANGUAGE_PROFILES.values()))


def resolve_language_code(
    code: str | None = None,
) -> str:
    """Return the canonical language code."""

    return get_language_profile(code).code


def list_supported_codes() -> list[str]:
    """Return canonical supported language codes."""

    return list(LANGUAGE_PROFILES.keys())


def list_supported_languages() -> list[LanguageProfile]:
    """Return all supported language profiles."""

    return list(LANGUAGE_PROFILES.values())


def is_supported(code: str | None) -> bool:
    """Check whether a language identifier is supported."""

    if not code:
        return False

    normalized = normalize_language_code(code)

    if not normalized:
        return False

    if normalized in LANGUAGE_PROFILES:
        return True

    lowered = normalized.lower()

    for profile in LANGUAGE_PROFILES.values():
        aliases = {
            alias.lower()
            for alias in profile.aliases
        }

        if lowered in aliases:
            return True

    primary = normalized.split("-", 1)[0]

    return primary in SUPPORTED_PRIMARY_CODES


# ============================================================================
# Language Helpers
# ============================================================================


def is_bangla(code: str | None) -> bool:
    """Return True when the language is Bangla."""

    if not code:
        return False

    normalized = normalize_language_code(code)

    return (
        normalized == BANGSLA_PRIMARY
        or normalized.startswith(f"{BANGSLA_PRIMARY}-")
    )


def is_english(code: str | None) -> bool:
    """Return True when the language is English."""

    if not code:
        return False

    normalized = normalize_language_code(code)

    return (
        normalized == ENGLISH_PRIMARY
        or normalized.startswith(f"{ENGLISH_PRIMARY}-")
    )


def is_hindi(code: str | None) -> bool:
    """Return True when the language is Hindi."""

    if not code:
        return False

    normalized = normalize_language_code(code)

    return (
        normalized == HINDI_PRIMARY
        or normalized.startswith(f"{HINDI_PRIMARY}-")
    )


def get_recognizer_locale(
    code: str | None = None,
) -> str:
    """Return the STT locale for a language."""

    return get_language_profile(code).recognizer_locale


def get_tts_voice_hints(
    code: str | None = None,
) -> tuple[str, ...]:
    """Return general TTS language/locale matching hints."""

    return get_language_profile(code).tts_voice_hints


def get_female_tts_voice_hints(
    code: str | None = None,
) -> tuple[str, ...]:
    """
    Return female-specific TTS voice-name hints.

    JEROX always uses the female voice policy.
    """

    return get_language_profile(
        code
    ).female_tts_voice_hints


def get_default_wake_words(
    code: str | None = None,
) -> tuple[str, ...]:
    """Return language-specific default wake words."""

    return get_language_profile(code).default_wake_words


def get_native_name(
    code: str | None = None,
) -> str:
    """Return the native language name."""

    return get_language_profile(code).native_name


def is_rtl(code: str | None = None) -> bool:
    """Return whether a language is right-to-left."""

    return get_language_profile(code).is_rtl


# ============================================================================
# Script Detection
# ============================================================================


def detect_script(
    text: str,
) -> ScriptDetectionResult:
    """
    Detect the dominant writing system.

    Strong signals:

        - Bengali
        - Devanagari
        - Latin
    """

    text = normalize_text(text)

    bengali = 0
    devanagari = 0
    latin = 0
    other_letters = 0

    for char in text:
        codepoint = ord(char)

        if (
            BENGALI_RANGE_START
            <= codepoint
            <= BENGALI_RANGE_END
        ):
            bengali += 1
            continue

        if (
            DEVANAGARI_RANGE_START
            <= codepoint
            <= DEVANAGARI_RANGE_END
        ):
            devanagari += 1
            continue

        if char.isascii() and char.isalpha():
            latin += 1
            continue

        if char.isalpha():
            other_letters += 1

    total = (
        bengali
        + devanagari
        + latin
        + other_letters
    )

    if total == 0:
        return ScriptDetectionResult(
            language_code=DEFAULT_CODE,
            confidence=0.0,
            bengali_chars=0,
            devanagari_chars=0,
            latin_chars=0,
            other_letters=0,
        )

    counts = {
        "bn-BD": bengali,
        "hi-IN": devanagari,
        "en-US": latin,
    }

    language_code = max(
        counts,
        key=counts.get,
    )

    strongest = counts[language_code]
    confidence = strongest / total

    if other_letters > 0:
        confidence *= 0.75

    return ScriptDetectionResult(
        language_code=language_code,
        confidence=round(
            min(1.0, confidence),
            4,
        ),
        bengali_chars=bengali,
        devanagari_chars=devanagari,
        latin_chars=latin,
        other_letters=other_letters,
    )


def detect_script_language(text: str) -> str:
    """Backward-compatible script language detector."""

    return detect_script(text).language_code


def detect_language(
    text: str,
    *,
    minimum_confidence: float = 0.50,
) -> str:
    """
    Return the most likely supported language.

    This is a lightweight heuristic detector.
    """

    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError(
            "minimum_confidence must be between 0.0 and 1.0."
        )

    result = detect_script(text)

    if result.confidence < minimum_confidence:
        return DEFAULT_CODE

    return result.language_code


# ============================================================================
# Banglish Detection
# ============================================================================


_BANGLISH_HINTS = frozenset(
    {
        "ami",
        "tumi",
        "apni",
        "amar",
        "tomar",
        "ki",
        "kemon",
        "ache",
        "achen",
        "korbo",
        "korben",
        "koro",
        "bolo",
        "bolen",
        "jabo",
        "ashbo",
        "valo",
        "bhalo",
        "hobe",
        "hoy",
        "na",
        "keno",
        "kothay",
        "ekhon",
        "ajke",
        "kalke",
        "please",
    }
)


def is_banglish(text: str) -> bool:
    """
    Lightweight Banglish detector.

    Banglish uses Latin characters to represent Bangla.
    """

    if not text:
        return False

    words = re.findall(
        r"[a-zA-Z]+",
        text.lower(),
    )

    if not words:
        return False

    matches = sum(
        1
        for word in words
        if word in _BANGLISH_HINTS
    )

    return matches >= 1


def detect_voice_language(text: str) -> str:
    """
    Practical language detector for JEROX.

    Priority:

        1. Bangla Unicode
        2. Hindi Unicode
        3. Banglish
        4. English/Latin
        5. Default language
    """

    script_result = detect_script(text)

    if script_result.bengali_chars > 0:
        return "bn-BD"

    if script_result.devanagari_chars > 0:
        return "hi-IN"

    if is_banglish(text):
        return "bn-BD"

    if script_result.latin_chars > 0:
        return "en-US"

    return DEFAULT_CODE


# ============================================================================
# TTS Voice Matching
# ============================================================================


def voice_matches_language(
    voice_name: str,
    code: str | None = None,
) -> bool:
    """
    Check whether an installed TTS voice appears compatible
    with the requested language.
    """

    if not voice_name:
        return False

    normalized_voice = voice_name.casefold()
    profile = get_language_profile(code)

    return any(
        hint.casefold() in normalized_voice
        for hint in profile.tts_voice_hints
        if hint
    )


def voice_matches_female(
    voice_name: str,
    code: str | None = None,
) -> bool:
    """
    Check whether an installed voice matches the female
    voice hints for the requested language.
    """

    if not voice_name:
        return False

    normalized_voice = voice_name.casefold()
    profile = get_language_profile(code)

    return any(
        hint.casefold() in normalized_voice
        for hint in profile.female_tts_voice_hints
        if hint
    )


def rank_tts_voice(
    voice_name: str,
    code: str | None = None,
) -> int:
    """
    Rank an installed voice for language compatibility.

    Scores:

        0 = no language match
        1 = weak language match
        2 = strong language/locale match
    """

    if not voice_name:
        return 0

    normalized_voice = voice_name.casefold()
    profile = get_language_profile(code)

    score = 0

    for hint in profile.tts_voice_hints:
        normalized_hint = hint.casefold()

        if not normalized_hint:
            continue

        if normalized_voice == normalized_hint:
            score = max(score, 2)

        elif normalized_hint in normalized_voice:
            score = max(score, 1)

    locale = profile.code.casefold()

    if (
        locale in normalized_voice
        or locale.replace("-", "_") in normalized_voice
    ):
        score = max(score, 2)

    return score


def rank_female_tts_voice(
    voice_name: str,
    code: str | None = None,
) -> int:
    """
    Rank an installed voice using the female-only policy.

    Returns:

        0 = not suitable
        1 = female-name hint match
        2 = female + language/locale match
        3 = strong female + locale match
    """

    if not voice_name:
        return 0

    profile = get_language_profile(code)
    normalized_voice = voice_name.casefold()

    female_score = 0
    language_score = rank_tts_voice(
        voice_name,
        code,
    )

    for hint in profile.female_tts_voice_hints:
        normalized_hint = hint.casefold()

        if not normalized_hint:
            continue

        if normalized_voice == normalized_hint:
            female_score = max(
                female_score,
                2,
            )

        elif normalized_hint in normalized_voice:
            female_score = max(
                female_score,
                1,
            )

    if female_score == 0:
        return 0

    if language_score >= 2:
        return 3

    return female_score


def select_best_tts_voice(
    voice_names: Iterable[str],
    code: str | None = None,
) -> str | None:
    """
    Select the best language-compatible TTS voice.

    This function remains backward compatible and performs
    general language matching.

    For JEROX's fixed female policy, use:

        select_best_female_tts_voice()
    """

    candidates = [
        voice
        for voice in voice_names
        if voice
    ]

    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda voice: (
            rank_tts_voice(voice, code),
            len(voice),
        ),
        reverse=True,
    )

    best = ranked[0]

    if rank_tts_voice(best, code) <= 0:
        return None

    return best


def select_best_female_tts_voice(
    voice_names: Iterable[str],
    code: str | None = None,
) -> str | None:
    """
    Select the best FEMALE TTS voice.

    Important:
        This function NEVER intentionally falls back to a male voice.

    If no suitable female voice exists, None is returned.
    """

    candidates = [
        voice
        for voice in voice_names
        if voice
    ]

    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda voice: (
            rank_female_tts_voice(
                voice,
                code,
            ),
            rank_tts_voice(
                voice,
                code,
            ),
            len(voice),
        ),
        reverse=True,
    )

    best = ranked[0]

    if rank_female_tts_voice(
        best,
        code,
    ) <= 0:
        return None

    return best


# ============================================================================
# Runtime Registry
# ============================================================================


class LanguageRegistry:
    """
    Thread-safe runtime language registry.

    Built-in profiles are loaded initially. Custom profiles can be
    registered by plugins without modifying built-in definitions.
    """

    def __init__(
        self,
        profiles: Iterable[LanguageProfile] | None = None,
    ) -> None:
        self._lock = threading.RLock()

        self._profiles: dict[
            str,
            LanguageProfile,
        ] = dict(_BUILTIN_PROFILES)

        if profiles:
            for profile in profiles:
                self.register(profile)

    def register(
        self,
        profile: LanguageProfile,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a custom language profile."""

        if not isinstance(
            profile,
            LanguageProfile,
        ):
            raise TypeError(
                "profile must be a LanguageProfile."
            )

        code = normalize_language_code(
            profile.code
        )

        if not code:
            raise ValueError(
                "Language profile code cannot be empty."
            )

        if not profile.display_name.strip():
            raise ValueError(
                "Language profile display_name cannot be empty."
            )

        with self._lock:
            if (
                code in self._profiles
                and not overwrite
            ):
                raise ValueError(
                    f"Language profile already exists: {code}"
                )

            if profile.code != code:
                profile = replace(
                    profile,
                    code=code,
                )

            self._profiles[code] = profile

    def unregister(
        self,
        code: str,
    ) -> bool:
        """Remove a custom language profile."""

        normalized = normalize_language_code(code)

        with self._lock:
            if normalized not in _BUILTIN_PROFILES:
                return self._profiles.pop(
                    normalized,
                    None,
                ) is not None

        # Built-in profiles are protected.
        return False

    def get(
        self,
        code: str | None = None,
    ) -> LanguageProfile:
        """Resolve a profile from the runtime registry."""

        normalized = normalize_language_code(
            code or DEFAULT_CODE
        )

        with self._lock:
            profile = self._profiles.get(
                normalized
            )

            if profile:
                return profile

            lowered = normalized.lower()

            for candidate in self._profiles.values():
                aliases = {
                    alias.lower()
                    for alias in candidate.aliases
                }

                if lowered in aliases:
                    return candidate

            primary = normalized.split(
                "-",
                1,
            )[0]

            for candidate in self._profiles.values():
                if candidate.primary_code == primary:
                    return candidate

            default_code = normalize_language_code(
                DEFAULT_CODE
            )

            return self._profiles.get(
                default_code,
                next(iter(self._profiles.values())),
            )

    def all(self) -> list[LanguageProfile]:
        """Return a snapshot of all registered profiles."""

        with self._lock:
            return list(
                self._profiles.values()
            )

    def codes(self) -> list[str]:
        """Return a snapshot of registered language codes."""

        with self._lock:
            return list(
                self._profiles.keys()
            )

    def diagnostics(self) -> dict:
        """Return safe registry diagnostics."""

        with self._lock:
            return {
                "profile_count": len(
                    self._profiles
                ),
                "codes": list(
                    self._profiles.keys()
                ),
                "default_code": DEFAULT_CODE,
                "supported_primary_codes": sorted(
                    SUPPORTED_PRIMARY_CODES
                ),
                "fixed_tts_gender": FIXED_TTS_GENDER,
            }


language_registry = LanguageRegistry()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Constants
    "DEFAULT_CODE",
    "FIXED_TTS_GENDER",
    "SUPPORTED_PRIMARY_CODES",
    "SUPPORTED_VOICE_LANGUAGES",

    # Profiles
    "LANGUAGE_PROFILES",

    # Models
    "LanguageProfile",
    "ScriptDetectionResult",

    # Registry
    "LanguageRegistry",
    "language_registry",

    # Detection
    "detect_language",
    "detect_script",
    "detect_script_language",
    "detect_voice_language",
    "is_banglish",

    # Resolution
    "get_language_profile",
    "get_native_name",
    "get_recognizer_locale",
    "get_tts_voice_hints",
    "get_female_tts_voice_hints",
    "get_default_wake_words",

    # Language helpers
    "is_bangla",
    "is_english",
    "is_hindi",
    "is_rtl",
    "is_supported",

    # Listing
    "list_supported_codes",
    "list_supported_languages",

    # Normalization
    "normalize_language_code",
    "normalize_text",
    "resolve_language_code",

    # TTS
    "voice_matches_language",
    "voice_matches_female",
    "rank_tts_voice",
    "rank_female_tts_voice",
    "select_best_tts_voice",
    "select_best_female_tts_voice",
]
