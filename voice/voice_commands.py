"""
voice/voice_commands.py
=======================

Professional voice-command preprocessing and shortcut subsystem
for AssistantX / JEROX.

Pipeline
--------
    STT
      ↓
    voice_commands
      ├── JEROX wake-word handling
      ├── utterance normalization
      ├── voice shortcut detection
      ↓
    brain / classifier

Responsibilities
----------------
- Normalize raw speech-to-text output.
- Recognize and remove the fixed JEROX wake word.
- Support common STT representations of JEROX.
- Detect immediate voice meta-commands.
- Provide runtime shortcut registration.
- Keep voice-specific behavior outside the brain/classifier layer.

JEROX identity
---------------
The AssistantX wake word is permanently:

    JEROX

Recognition aliases:

    jerox
    mohana
    জেরক্স

The wake word itself cannot be changed through this module.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import Enum
from re import Pattern

from core.logger import get_logger


logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_MAX_UTTERANCE_LENGTH = 4000
DEFAULT_WAKE_WORD_MAX_LENGTH = 200

FIXED_WAKE_WORD = "jerox"
JEROX_DISPLAY_NAME = "JEROX"

# STT recognition aliases.
# These are NOT configurable wake words.
JEROX_ALIASES: tuple[str, ...] = (
    "jerox",
    "mohana",
    "জেরক্স",
)

_FILLER_WORDS_PATTERN = re.compile(
    r"\b(?:um+|uh+|erm+|er+|hmm+|like|you know|i mean)\b",
    re.IGNORECASE,
)

_MULTI_SPACE_PATTERN = re.compile(r"\s+")

_SPACE_BEFORE_PUNCT_PATTERN = re.compile(
    r"\s+([,.!?;:])"
)

_REPEATED_PUNCT_PATTERN = re.compile(
    r"([!?.,])\1{1,}"
)


# ============================================================================
# Enums
# ============================================================================


class VoiceShortcut(str, Enum):
    """
    Immediate voice-only meta commands.

    These commands normally bypass the normal intent classifier.
    """

    STOP_SPEAKING = "stop_speaking"
    CANCEL = "cancel"
    REPEAT = "repeat"
    LOUDER = "louder"
    QUIETER = "quieter"
    SLEEP_MODE = "sleep_mode"


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True, slots=True)
class VoiceShortcutMatch:
    """Result returned when a voice shortcut is detected."""

    shortcut: VoiceShortcut
    matched_text: str

    @property
    def value(self) -> str:
        """Return the shortcut's machine-readable value."""
        return self.shortcut.value


@dataclass(frozen=True, slots=True)
class VoiceShortcutRule:
    """
    Registered voice shortcut rule.

    Attributes
    ----------
    pattern:
        Compiled regular expression.
    shortcut:
        Shortcut represented by the rule.
    priority:
        Higher priority rules are checked first.
    name:
        Optional human-readable rule name.
    """

    pattern: Pattern[str]
    shortcut: VoiceShortcut
    priority: int = 0
    name: str = ""


# ============================================================================
# Default Shortcut Rules
# ============================================================================

_DEFAULT_SHORTCUT_RULES: tuple[VoiceShortcutRule, ...] = (
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"stop talking|"
            r"be quiet|"
            r"stop speaking|"
            r"silence|"
            r"shut up|"
            r"চুপ কর|"
            r"চুপ|"
            r"থামো|"
            r"কথা বলা বন্ধ কর"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.STOP_SPEAKING,
        priority=100,
        name="stop-speaking",
    ),
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"cancel that|"
            r"cancel|"
            r"never mind|"
            r"nevermind|"
            r"forget it|"
            r"বাদ দাও|"
            r"বাতিল কর|"
            r"থাক বাদ|"
            r"থাক"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.CANCEL,
        priority=90,
        name="cancel",
    ),
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"say that again|"
            r"repeat that|"
            r"repeat|"
            r"what did you say|"
            r"pardon|"
            r"say again|"
            r"আবার বলো|"
            r"আবার বল|"
            r"কি বললে|"
            r"কি বললেন"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.REPEAT,
        priority=80,
        name="repeat",
    ),
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"speak up|"
            r"louder please|"
            r"can't hear you|"
            r"cannot hear you|"
            r"make it louder|"
            r"আরও জোরে|"
            r"জোরে বলো|"
            r"জোরে বল|"
            r"শুনতে পাচ্ছি না"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.LOUDER,
        priority=70,
        name="louder",
    ),
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"too loud|"
            r"quieter please|"
            r"lower your voice|"
            r"make it quieter|"
            r"কম শব্দে|"
            r"আস্তে বলো|"
            r"আস্তে বল|"
            r"আস্তে"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.QUIETER,
        priority=60,
        name="quieter",
    ),
    VoiceShortcutRule(
        pattern=re.compile(
            r"(?:^|[\s,;:])("
            r"go to sleep|"
            r"stop listening|"
            r"sleep mode|"
            r"enter sleep mode|"
            r"ঘুমিয়ে যাও|"
            r"ঘুমাও|"
            r"শোনা বন্ধ কর|"
            r"লিসেনিং বন্ধ কর"
            r")(?=$|[\s,.!?;:])",
            re.IGNORECASE,
        ),
        shortcut=VoiceShortcut.SLEEP_MODE,
        priority=50,
        name="sleep-mode",
    ),
)


# ============================================================================
# Internal Helpers
# ============================================================================


def _safe_text(
    text: object,
    *,
    max_length: int = DEFAULT_MAX_UTTERANCE_LENGTH,
) -> str:
    """Safely convert arbitrary input into bounded text."""

    if text is None:
        return ""

    try:
        value = str(text)
    except (TypeError, ValueError):
        return ""

    value = value.strip()

    if len(value) > max_length:
        logger.warning(
            "Voice utterance exceeded maximum length (%d); truncating.",
            max_length,
        )
        value = value[:max_length]

    return value


def _normalize_spaces(text: str) -> str:
    """Collapse all whitespace into single spaces."""

    return _MULTI_SPACE_PATTERN.sub(" ", text).strip()


def _normalize_punctuation(text: str) -> str:
    """Normalize common STT punctuation artifacts."""

    text = _SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", text)

    return _REPEATED_PUNCT_PATTERN.sub(
        r"\1",
        text,
    )


def _casefold(text: str) -> str:
    """Unicode-safe case normalization."""

    return text.casefold()


def _normalize_for_matching(text: object) -> str:
    """
    Normalize text for wake-word matching.

    Unicode is preserved so Bengali JEROX output remains detectable.
    """

    value = _safe_text(text)

    if not value:
        return ""

    return _casefold(
        _normalize_spaces(value)
    )


def _compile_wake_pattern(
    wake_phrase: str,
) -> Pattern[str]:
    """
    Build a safe regex for a leading wake phrase.

    This helper accepts only the fixed JEROX identity.
    """

    normalized = _normalize_for_matching(wake_phrase)

    if normalized not in JEROX_ALIASES:
        raise ValueError(
            "AssistantX wake word is permanently fixed to JEROX."
        )

    escaped = re.escape(normalized)

    return re.compile(
        rf"^\s*{escaped}(?:\s*[,;:]\s*|\s+|$)",
        re.IGNORECASE,
    )


# ============================================================================
# JEROX Detection
# ============================================================================


def is_jerox(text: str) -> bool:
    """
    Return True when text begins with a recognized JEROX alias.
    """

    value = _normalize_for_matching(text)

    if not value:
        return False

    for alias in JEROX_ALIASES:
        if value == alias:
            return True

        if value.startswith(alias + " "):
            return True

        if value.startswith(alias + ","):
            return True

        if value.startswith(alias + ":"):
            return True

        if value.startswith(alias + ";"):
            return True

    return False


def _strip_jerox_alias(text: str) -> str:
    """
    Remove a leading JEROX recognition alias.

    Only the beginning of the utterance is affected.
    """

    value = _safe_text(text)

    if not value:
        return ""

    normalized = _normalize_for_matching(value)

    for alias in JEROX_ALIASES:
        if normalized == alias:
            return ""

        pattern = re.compile(
            rf"^\s*{re.escape(alias)}"
            rf"(?:\s*[,;:]\s*|\s+)",
            re.IGNORECASE,
        )

        if pattern.match(value):
            return pattern.sub(
                "",
                value,
                count=1,
            ).strip()

    return value


# ============================================================================
# Utterance Normalization
# ============================================================================


def normalize_utterance(
    raw_text: str,
    *,
    remove_fillers: bool = True,
    normalize_punctuation: bool = True,
    max_length: int = DEFAULT_MAX_UTTERANCE_LENGTH,
) -> str:
    """
    Normalize raw STT output.

    Processing order
    ----------------
    1. Safe conversion / length limiting
    2. Remove filler words
    3. Collapse whitespace
    4. Normalize punctuation
    5. Strip surrounding punctuation
    """

    cleaned = _safe_text(
        raw_text,
        max_length=max_length,
    )

    if not cleaned:
        return ""

    if remove_fillers:
        cleaned = _FILLER_WORDS_PATTERN.sub(
            " ",
            cleaned,
        )

    cleaned = _normalize_spaces(cleaned)

    if normalize_punctuation:
        cleaned = _normalize_punctuation(cleaned)

    return cleaned.strip(" \t\r\n.,!?;:")


# ============================================================================
# Wake Word API
# ============================================================================


def strip_wake_word(
    text: str,
    wake_phrase: str | None = None,
    *,
    max_wake_length: int = DEFAULT_WAKE_WORD_MAX_LENGTH,
) -> str:
    """
    Remove a leading JEROX wake word from an utterance.

    ``wake_phrase`` is retained for backward compatibility, but only
    JEROX and its recognition aliases are accepted.
    """

    value = _safe_text(text)

    if not value:
        return ""

    phrase = (
        FIXED_WAKE_WORD
        if wake_phrase is None
        else _safe_text(
            wake_phrase,
            max_length=max_wake_length,
        )
    )

    if not phrase:
        return value

    normalized_phrase = _normalize_for_matching(
        phrase
    )

    if normalized_phrase not in JEROX_ALIASES:
        logger.warning(
            "Ignoring non-JEROX wake phrase %r.",
            phrase,
        )
        return value

    return _strip_jerox_alias(value)


def wake_word_present(
    text: str,
    wake_phrase: str | None = None,
) -> bool:
    """
    Return True when a recognized JEROX alias occurs at the beginning.
    """

    del wake_phrase

    return is_jerox(text)


# ============================================================================
# Shortcut Registry
# ============================================================================


class VoiceShortcutRegistry:
    """
    Thread-safe runtime registry for voice shortcut rules.

    Plugins can register additional shortcut patterns without modifying
    this module.
    """

    def __init__(
        self,
        rules: list[VoiceShortcutRule] | None = None,
    ) -> None:
        self._lock = threading.RLock()

        self._rules: list[VoiceShortcutRule] = list(
            rules
            if rules is not None
            else _DEFAULT_SHORTCUT_RULES
        )

        self._sort_rules()

    def _sort_rules(self) -> None:
        """Sort rules by descending priority."""

        self._rules.sort(
            key=lambda rule: rule.priority,
            reverse=True,
        )

    def register(
        self,
        pattern: str | Pattern[str],
        shortcut: VoiceShortcut,
        *,
        priority: int = 0,
        name: str = "",
        flags: int = re.IGNORECASE,
        replace_name: bool = False,
    ) -> VoiceShortcutRule:
        """Register a custom shortcut rule."""

        if isinstance(pattern, str):
            if not pattern.strip():
                raise ValueError(
                    "Shortcut pattern cannot be empty."
                )

            compiled = re.compile(
                pattern,
                flags,
            )

        elif hasattr(pattern, "search"):
            compiled = pattern

        else:
            raise TypeError(
                "pattern must be a string or compiled regex pattern."
            )

        if not isinstance(
            shortcut,
            VoiceShortcut,
        ):
            try:
                shortcut = VoiceShortcut(shortcut)
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported voice shortcut: {shortcut!r}"
                ) from exc

        normalized_name = name.strip()

        rule = VoiceShortcutRule(
            pattern=compiled,
            shortcut=shortcut,
            priority=int(priority),
            name=normalized_name,
        )

        with self._lock:
            if replace_name and normalized_name:
                self._rules = [
                    existing
                    for existing in self._rules
                    if existing.name != normalized_name
                ]

            self._rules.append(rule)
            self._sort_rules()

        logger.info(
            "Registered voice shortcut: %s -> %s",
            normalized_name or "<unnamed>",
            shortcut.value,
        )

        return rule

    def unregister(
        self,
        name: str,
    ) -> bool:
        """Remove all rules matching a registered name."""

        normalized_name = name.strip()

        if not normalized_name:
            return False

        with self._lock:
            original_count = len(self._rules)

            self._rules = [
                rule
                for rule in self._rules
                if rule.name != normalized_name
            ]

            removed = len(self._rules) < original_count

        if removed:
            logger.info(
                "Unregistered voice shortcut: %s",
                normalized_name,
            )

        return removed

    def clear_custom(self) -> int:
        """
        Restore the registry to built-in rules only.

        Returns the number of removed custom rules.
        """

        with self._lock:
            original_count = len(self._rules)

            builtin_rules = {
                rule.name: rule
                for rule in _DEFAULT_SHORTCUT_RULES
            }

            self._rules = [
                rule
                for rule in self._rules
                if rule.name in builtin_rules
            ]

            self._sort_rules()

            return original_count - len(self._rules)

    def rules(
        self,
    ) -> tuple[VoiceShortcutRule, ...]:
        """Return an immutable snapshot of registered rules."""

        with self._lock:
            return tuple(self._rules)

    def detect(
        self,
        text: str,
    ) -> VoiceShortcutMatch | None:
        """Detect the highest-priority matching shortcut."""

        value = _safe_text(text)

        if not value:
            return None

        with self._lock:
            rules = tuple(self._rules)

        for rule in rules:
            match = rule.pattern.search(value)

            if match:
                matched_text = match.group(0)

                logger.debug(
                    "Voice shortcut detected: %s (%r)",
                    rule.shortcut.value,
                    matched_text,
                )

                return VoiceShortcutMatch(
                    shortcut=rule.shortcut,
                    matched_text=matched_text,
                )

        return None

    def diagnostics(self) -> dict[str, object]:
        """Return safe registry diagnostics."""

        with self._lock:
            rules = tuple(self._rules)

        return {
            "rule_count": len(rules),
            "shortcuts": [
                {
                    "name": rule.name,
                    "shortcut": rule.shortcut.value,
                    "priority": rule.priority,
                }
                for rule in rules
            ],
        }


# ============================================================================
# Global Registry
# ============================================================================

voice_shortcut_registry = VoiceShortcutRegistry()


# ============================================================================
# Public Shortcut API
# ============================================================================


def detect_shortcut(
    text: str,
    *,
    normalize: bool = True,
) -> VoiceShortcutMatch | None:
    """Detect a voice-only shortcut."""

    value = (
        normalize_utterance(text)
        if normalize
        else _safe_text(text)
    )

    if not value:
        return None

    return voice_shortcut_registry.detect(value)


def is_shortcut(
    text: str,
    shortcut: VoiceShortcut,
) -> bool:
    """Check whether a specific voice shortcut is present."""

    match = detect_shortcut(text)

    if match is None:
        return False

    return match.shortcut == shortcut


# ============================================================================
# Complete Voice Pipeline
# ============================================================================


def prepare_utterance_for_classification(
    raw_text: str,
    wake_phrase: str | None = None,
    *,
    remove_fillers: bool = True,
    normalize_punctuation: bool = True,
    detect_after_wake_removal: bool = True,
) -> tuple[str, VoiceShortcutMatch | None]:
    """
    Prepare freshly transcribed voice text for the brain pipeline.

    Processing order:

        raw STT
          ↓
        JEROX removal
          ↓
        shortcut detection
          ↓
        normalization
          ↓
        brain/classifier

    Returns
    -------
    tuple[str, VoiceShortcutMatch | None]

    If a shortcut is returned, the caller should normally execute the
    shortcut immediately instead of sending the text through the normal
    intent classifier.
    """

    text = _safe_text(raw_text)

    if not text:
        return "", None

    # ------------------------------------------------------------
    # JEROX wake-word removal
    # ------------------------------------------------------------

    text = strip_wake_word(
        text,
        wake_phrase,
    )

    if not text:
        return "", None

    # ------------------------------------------------------------
    # Shortcut detection
    # ------------------------------------------------------------

    if detect_after_wake_removal:
        shortcut = detect_shortcut(text)
    else:
        shortcut = detect_shortcut(raw_text)

    # ------------------------------------------------------------
    # Final normalization
    # ------------------------------------------------------------

    cleaned = normalize_utterance(
        text,
        remove_fillers=remove_fillers,
        normalize_punctuation=normalize_punctuation,
    )

    return cleaned, shortcut


# ============================================================================
# Utility Helpers
# ============================================================================


def shortcut_to_action(
    match: VoiceShortcutMatch | None,
) -> str | None:
    """Convert a shortcut match into its machine-readable action."""

    if match is None:
        return None

    return match.shortcut.value


def register_voice_shortcut(
    pattern: str | Pattern[str],
    shortcut: VoiceShortcut,
    *,
    priority: int = 0,
    name: str = "",
    flags: int = re.IGNORECASE,
    replace_name: bool = False,
) -> VoiceShortcutRule:
    """Register a runtime/plugin voice shortcut."""

    return voice_shortcut_registry.register(
        pattern,
        shortcut,
        priority=priority,
        name=name,
        flags=flags,
        replace_name=replace_name,
    )


def unregister_voice_shortcut(
    name: str,
) -> bool:
    """Remove a custom voice shortcut."""

    return voice_shortcut_registry.unregister(name)


def get_voice_shortcut_diagnostics() -> dict[str, object]:
    """Return safe diagnostics for the voice-command subsystem."""

    return {
        "module": __name__,
        "wake_word": JEROX_DISPLAY_NAME,
        "wake_word_fixed": True,
        "wake_word_aliases": list(JEROX_ALIASES),
        "max_utterance_length": DEFAULT_MAX_UTTERANCE_LENGTH,
        "max_wake_word_length": DEFAULT_WAKE_WORD_MAX_LENGTH,
        "built_in_shortcuts": len(_DEFAULT_SHORTCUT_RULES),
        "registry": voice_shortcut_registry.diagnostics(),
    }


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "FIXED_WAKE_WORD",
    "JEROX_ALIASES",
    "JEROX_DISPLAY_NAME",
    "VoiceShortcut",
    "VoiceShortcutMatch",
    "VoiceShortcutRegistry",
    "VoiceShortcutRule",
    "detect_shortcut",
    "get_voice_shortcut_diagnostics",
    "is_jerox",
    "is_shortcut",
    "normalize_utterance",
    "prepare_utterance_for_classification",
    "register_voice_shortcut",
    "shortcut_to_action",
    "strip_wake_word",
    "unregister_voice_shortcut",
    "voice_shortcut_registry",
    "wake_word_present",
]
