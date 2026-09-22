"""
AssistantX - Intent Classifier
================================

Fast, deterministic, dependency-free intent classification engine.

Responsibilities
-----------------
- Convert raw user text into a structured Intent.
- Detect actionable commands using ordered regex rules.
- Extract useful entities from commands.
- Support English + common Banglish command patterns.
- Keep classification deterministic and offline.
- Provide rule management for plugins/custom commands.
- Provide diagnostics and classification statistics.

Design Goals
------------
- Fast
- Thread-safe
- Easy to debug
- Easy to extend
- Plugin-friendly
- No ML dependency
- Safe fallback to GENERAL_CHAT

Examples
--------
    "open chrome"
        -> APP_LAUNCH / OPEN_APP

    "play shape of you"
        -> MUSIC / PLAY_MUSIC

    "weather in Dhaka"
        -> WEATHER / location=Dhaka

    "remind me to call mom"
        -> REMINDER / SET_REMINDER

    "delete file test.txt"
        -> FILE_OPERATION / DELETE_FILE
           requires_confirmation=True

    "hello assistant"
        -> GENERAL_CHAT
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from re import Pattern
from typing import Any

from brain.intent import (
    Entity,
    Intent,
    SubIntent,
    general_chat_intent,
    unknown_intent,
)
from config.constants import IntentCategory
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_CHAT_CONFIDENCE = 0.60
DEFAULT_RULE_CONFIDENCE = 0.90
DEFAULT_ENTITY_CONFIDENCE = 0.95

MAX_INPUT_LENGTH = 4000
MAX_ENTITY_LENGTH = 1000


# ============================================================================
# Exceptions
# ============================================================================


class ClassifierError(Exception):
    """Base exception for classifier-related errors."""


class RuleValidationError(ClassifierError):
    """Raised when an invalid classification rule is registered."""


# ============================================================================
# Rule
# ============================================================================


EntityExtractor = Callable[[re.Match[str]], list[Entity]]


@dataclass
class Rule:
    """
    Defines one intent classification rule.

    Parameters
    ----------
    pattern:
        Compiled regular expression.

    category:
        IntentCategory associated with the rule.

    sub_intent:
        Optional sub-intent identifier.

    confidence:
        Confidence assigned when this rule matches.

    entity_extractor:
        Optional callable used to extract entities from regex groups.

    requires_confirmation:
        Whether the resulting action requires confirmation.

    name:
        Optional human-readable rule name.

    priority:
        Optional priority value. Higher priority rules are checked first.

    enabled:
        Allows temporarily disabling a rule without deleting it.
    """

    pattern: Pattern[str]
    category: IntentCategory
    sub_intent: str | None = None
    confidence: float = DEFAULT_RULE_CONFIDENCE
    entity_extractor: EntityExtractor | None = None
    requires_confirmation: bool = False

    # New optional fields keep backward compatibility with the old API.
    name: str = ""
    priority: int = 0
    enabled: bool = True

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate rule configuration."""

        if not hasattr(self.pattern, "search"):
            raise RuleValidationError(
                "Rule.pattern must be a compiled regular expression."
            )

        if not isinstance(self.confidence, (int, float)):
            raise RuleValidationError("Rule.confidence must be numeric.")

        if not 0.0 <= float(self.confidence) <= 1.0:
            raise RuleValidationError(
                "Rule.confidence must be between 0.0 and 1.0."
            )

        if not isinstance(self.priority, int):
            raise RuleValidationError("Rule.priority must be an integer.")

        if not isinstance(self.enabled, bool):
            raise RuleValidationError("Rule.enabled must be boolean.")

        if not self.name:
            self.name = self.sub_intent or self.category_name()

    def category_name(self) -> str:
        """Return a readable category name."""

        try:
            return str(self.category.value)
        except AttributeError:
            return str(self.category)

    def matches(self, text: str) -> re.Match[str] | None:
        """Return a regex match if the rule matches."""

        if not self.enabled:
            return None

        return self.pattern.search(text)


# ============================================================================
# Entity Helpers
# ============================================================================


def _clean_entity_value(value: Any) -> str:
    """
    Normalize an extracted entity value.

    Removes surrounding whitespace and quotes and limits
    excessively large values.
    """

    if value is None:
        return ""

    value = str(value).strip()

    # Remove common surrounding quotes.
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {'"', "'", "`"}
    ):
            value = value[1:-1].strip()

    # Normalize repeated whitespace.
    value = re.sub(r"\s+", " ", value)

    return value[:MAX_ENTITY_LENGTH].strip()


def _entity_from_group(
    name: str,
    group: str = "value",
    confidence: float = DEFAULT_ENTITY_CONFIDENCE,
) -> EntityExtractor:
    """
    Build a simple entity extractor from a named regex group.

    Example
    -------
        _entity_from_group("app_name")
    """

    def extractor(match: re.Match[str]) -> list[Entity]:
        try:
            value = match.group(group)
        except (IndexError, KeyError):
            return []

        value = _clean_entity_value(value)

        if not value:
            return []

        return [
            Entity(
                name=name,
                value=value,
                confidence=confidence,
            )
        ]

    return extractor


def _entities_from_groups(
    *groups: tuple[str, str],
    confidence: float = DEFAULT_ENTITY_CONFIDENCE,
) -> EntityExtractor:
    """
    Extract multiple entities.

    Example
    -------
        _entities_from_groups(
            ("value", "expression"),
            ("unit", "unit"),
        )
    """

    def extractor(match: re.Match[str]) -> list[Entity]:
        entities: list[Entity] = []

        for group, entity_name in groups:
            try:
                value = match.group(group)
            except (IndexError, KeyError):
                continue

            value = _clean_entity_value(value)

            if value:
                entities.append(
                    Entity(
                        name=entity_name,
                        value=value,
                        confidence=confidence,
                    )
                )

        return entities

    return extractor


# ============================================================================
# Regex Helpers
# ============================================================================


def _rx(pattern: str, flags: int = re.IGNORECASE) -> Pattern[str]:
    """Compile a regular expression safely."""

    return re.compile(pattern, flags)


# ============================================================================
# Rule Table
# ============================================================================
#
# IMPORTANT:
# Rules are checked from top to bottom after priority sorting.
#
# Specific/actionable commands should always be placed before broad rules.
# ============================================================================


_RULES: list[Rule] = [

    # ------------------------------------------------------------------------
    # SYSTEM CONTROL
    # ------------------------------------------------------------------------

    Rule(
        _rx(r"\b(?:shut\s*down|shutdown)\b"),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.SHUTDOWN,
        confidence=0.98,
        requires_confirmation=True,
        name="system.shutdown",
        priority=100,
    ),

    Rule(
        _rx(
            r"\b(?:restart|reboot)\b.*\b(?:computer|system|pc|laptop|windows)?\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.RESTART,
        confidence=0.97,
        requires_confirmation=True,
        name="system.restart",
        priority=99,
    ),

    Rule(
        _rx(r"\b(?:sleep|hibernate)\b"),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.SLEEP,
        confidence=0.97,
        name="system.sleep",
        priority=98,
    ),

    Rule(
        _rx(
            r"\b(?:lock|lock\s+the)\b.*\b(?:computer|screen|pc|windows)?\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.LOCK,
        confidence=0.97,
        name="system.lock",
        priority=97,
    ),

    Rule(
        _rx(r"\b(?:mute|silence)\b"),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.MUTE,
        confidence=0.97,
        name="system.mute",
        priority=96,
    ),

    Rule(
        _rx(
            r"\b(?:volume\s*(?:up|increase)|increase\s+volume|"
            r"turn\s+up\s+(?:the\s+)?volume|louder)\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.VOLUME_UP,
        confidence=0.96,
        name="system.volume_up",
        priority=95,
    ),

    Rule(
        _rx(
            r"\b(?:volume\s*(?:down|decrease)|decrease\s+volume|"
            r"turn\s+down\s+(?:the\s+)?volume|quieter)\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.VOLUME_DOWN,
        confidence=0.96,
        name="system.volume_down",
        priority=94,
    ),

    Rule(
        _rx(
            r"\b(?:brightness\s*(?:up|increase)|"
            r"increase\s+brightness|brighter)\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.BRIGHTNESS_UP,
        confidence=0.96,
        name="system.brightness_up",
        priority=93,
    ),

    Rule(
        _rx(
            r"\b(?:brightness\s*(?:down|decrease)|"
            r"decrease\s+brightness|dimmer)\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.BRIGHTNESS_DOWN,
        confidence=0.96,
        name="system.brightness_down",
        priority=92,
    ),

    Rule(
        _rx(
            r"\b(?:take\s+(?:a\s+)?screenshot|"
            r"capture\s+(?:a\s+)?screenshot|"
            r"screenshot)\b"
        ),
        IntentCategory.SYSTEM_CONTROL,
        "screenshot",
        confidence=0.98,
        name="system.screenshot",
        priority=91,
    ),

    # Banglish system commands
    Rule(
        _rx(r"\b(?:pc|computer)\s+(?:bondho|off)\s+koro\b"),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.SHUTDOWN,
        confidence=0.95,
        requires_confirmation=True,
        name="system.shutdown.banglish",
        priority=90,
    ),

    Rule(
        _rx(r"\b(?:pc|computer)\s+restart\s+koro\b"),
        IntentCategory.SYSTEM_CONTROL,
        SubIntent.RESTART,
        confidence=0.95,
        requires_confirmation=True,
        name="system.restart.banglish",
        priority=89,
    ),

    # ------------------------------------------------------------------------
    # APP CONTROL
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?:please\s+)?open\s+"
            r"(?P<value>[\w .&()+#_-]+?)"
            r"(?:\s+(?:app|application))?$"
        ),
        IntentCategory.APP_LAUNCH,
        SubIntent.OPEN_APP,
        confidence=0.96,
        entity_extractor=_entity_from_group("app_name"),
        name="app.open",
        priority=80,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?(?:launch|start|run)\s+"
            r"(?P<value>[\w .&()+#_-]+)$"
        ),
        IntentCategory.APP_LAUNCH,
        SubIntent.OPEN_APP,
        confidence=0.95,
        entity_extractor=_entity_from_group("app_name"),
        name="app.launch",
        priority=79,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?close\s+"
            r"(?P<value>[\w .&()+#_-]+)$"
        ),
        IntentCategory.APP_LAUNCH,
        SubIntent.CLOSE_APP,
        confidence=0.96,
        entity_extractor=_entity_from_group("app_name"),
        name="app.close",
        priority=78,
    ),

    # Banglish app control
    Rule(
        _rx(
            r"^(?:please\s+)?(?P<value>[\w .&()+#_-]+)\s+"
            r"(?:khulo|open\s+koro)$"
        ),
        IntentCategory.APP_LAUNCH,
        SubIntent.OPEN_APP,
        confidence=0.91,
        entity_extractor=_entity_from_group("app_name"),
        name="app.open.banglish",
        priority=77,
    ),

    # ------------------------------------------------------------------------
    # MUSIC
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?:please\s+)?play\s+"
            r"(?P<value>.+?)"
            r"(?:\s+(?:on|from)\s+\w+)?$"
        ),
        IntentCategory.MUSIC,
        SubIntent.PLAY_MUSIC,
        confidence=0.95,
        entity_extractor=_entity_from_group("song_or_query"),
        name="music.play",
        priority=70,
    ),

    Rule(
        _rx(r"\b(?:pause|pause\s+(?:the\s+)?(?:music|song|track))\b"),
        IntentCategory.MUSIC,
        SubIntent.PAUSE_MUSIC,
        confidence=0.96,
        name="music.pause",
        priority=69,
    ),

    Rule(
        _rx(
            r"\b(?:next\s+(?:song|track)|"
            r"skip\s+(?:song|track)?|skip)\b"
        ),
        IntentCategory.MUSIC,
        SubIntent.NEXT_TRACK,
        confidence=0.96,
        name="music.next",
        priority=68,
    ),

    Rule(
        _rx(
            r"\b(?:previous|prev|last)\s+(?:song|track)\b"
        ),
        IntentCategory.MUSIC,
        SubIntent.PREVIOUS_TRACK,
        confidence=0.96,
        name="music.previous",
        priority=67,
    ),

    # ------------------------------------------------------------------------
    # WEATHER
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"\bweather\b.*?\b(?:in|at|for)\s+"
            r"(?P<value>[\w\s,.-]+)$"
        ),
        IntentCategory.WEATHER,
        entity_extractor=_entity_from_group("location"),
        confidence=0.96,
        name="weather.location",
        priority=60,
    ),

    Rule(
        _rx(
            r"\b(?:weather|temperature|forecast)\b"
        ),
        IntentCategory.WEATHER,
        confidence=0.91,
        name="weather.general",
        priority=59,
    ),

    # Banglish weather
    Rule(
        _rx(
            r"\b(?:ajker|ajke|ekhon)\s+"
            r"(?:abohawa|weather|tapmatra)\b"
        ),
        IntentCategory.WEATHER,
        confidence=0.90,
        name="weather.banglish",
        priority=58,
    ),

    # ------------------------------------------------------------------------
    # NEWS
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"\bnews\b.*?\babout\s+"
            r"(?P<value>.+)$"
        ),
        IntentCategory.NEWS,
        entity_extractor=_entity_from_group("topic"),
        confidence=0.95,
        name="news.topic",
        priority=55,
    ),

    Rule(
        _rx(
            r"\b(?:latest\s+)?news\b|"
            r"\bheadlines\b|"
            r"\btop\s+news\b"
        ),
        IntentCategory.NEWS,
        confidence=0.91,
        name="news.general",
        priority=54,
    ),

    # ------------------------------------------------------------------------
    # REMINDERS
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?:please\s+)?remind\s+me\s+"
            r"(?:to\s+)?(?P<value>.+)$"
        ),
        IntentCategory.REMINDER,
        SubIntent.SET_REMINDER,
        confidence=0.97,
        entity_extractor=_entity_from_group("reminder_text"),
        name="reminder.set",
        priority=50,
    ),

    Rule(
        _rx(
            r"\b(?:list|show|view)\s+"
            r"(?:my\s+)?reminders\b"
        ),
        IntentCategory.REMINDER,
        SubIntent.LIST_REMINDERS,
        confidence=0.96,
        name="reminder.list",
        priority=49,
    ),

    Rule(
        _rx(
            r"\bcancel\s+(?:the\s+)?reminder\s*"
            r"(?:about\s+)?(?P<value>.+)$"
        ),
        IntentCategory.REMINDER,
        SubIntent.CANCEL_REMINDER,
        confidence=0.96,
        entity_extractor=_entity_from_group("reminder_text"),
        name="reminder.cancel",
        priority=48,
    ),

    # ------------------------------------------------------------------------
    # FILE OPERATIONS
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?:please\s+)?create\s+"
            r"(?:a\s+)?(?:new\s+)?file\s+"
            r"(?:called\s+|named\s+)?"
            r"(?P<value>[\w ._-]+\.[A-Za-z0-9]+)$"
        ),
        IntentCategory.FILE_OPERATION,
        SubIntent.CREATE_FILE,
        confidence=0.97,
        entity_extractor=_entity_from_group("filename"),
        name="file.create",
        priority=45,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?delete\s+"
            r"(?:the\s+)?file\s+"
            r"(?P<value>[\w ._-]+)$"
        ),
        IntentCategory.FILE_OPERATION,
        SubIntent.DELETE_FILE,
        confidence=0.98,
        entity_extractor=_entity_from_group("filename"),
        requires_confirmation=True,
        name="file.delete",
        priority=44,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?open\s+"
            r"(?:the\s+)?folder\s+"
            r"(?P<value>.+)$"
        ),
        IntentCategory.FILE_OPERATION,
        SubIntent.OPEN_FOLDER,
        confidence=0.97,
        entity_extractor=_entity_from_group("folder_path"),
        name="folder.open",
        priority=43,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?find\s+"
            r"(?:the\s+)?file\s+"
            r"(?P<value>[\w ._-]+)$"
        ),
        IntentCategory.FILE_OPERATION,
        SubIntent.SEARCH_FILE,
        confidence=0.96,
        entity_extractor=_entity_from_group("filename"),
        name="file.search",
        priority=42,
    ),

    # ------------------------------------------------------------------------
    # CALCULATION
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?P<value>"
            r"[\d\s+\-*/().%]+"
            r")$"
        ),
        IntentCategory.CALCULATION,
        SubIntent.ARITHMETIC,
        confidence=0.93,
        entity_extractor=_entity_from_group("expression"),
        name="calculator.arithmetic",
        priority=35,
    ),

    Rule(
        _rx(
            r"^(?:what(?:'s| is)|calculate|compute)\s+"
            r"(?P<value>[\d\s+\-*/().%]+)\??$"
        ),
        IntentCategory.CALCULATION,
        SubIntent.ARITHMETIC,
        confidence=0.97,
        entity_extractor=_entity_from_group("expression"),
        name="calculator.expression",
        priority=34,
    ),

    Rule(
        _rx(
            r"^convert\s+"
            r"(?P<value>.+?)\s+to\s+"
            r"(?P<unit>[\w°.-]+)$"
        ),
        IntentCategory.CALCULATION,
        SubIntent.UNIT_CONVERSION,
        confidence=0.95,
        entity_extractor=_entities_from_groups(
            ("value", "value"),
            ("unit", "unit"),
        ),
        name="calculator.convert",
        priority=33,
    ),

    # ------------------------------------------------------------------------
    # WEB SEARCH
    # ------------------------------------------------------------------------

    Rule(
        _rx(
            r"^(?:please\s+)?search\s+"
            r"(?:for\s+)?(?P<value>.+)$"
        ),
        IntentCategory.WEB_SEARCH,
        SubIntent.GENERAL_SEARCH,
        confidence=0.94,
        entity_extractor=_entity_from_group("query"),
        name="web.search",
        priority=20,
    ),

    Rule(
        _rx(
            r"^(?:please\s+)?google\s+"
            r"(?P<value>.+)$"
        ),
        IntentCategory.WEB_SEARCH,
        SubIntent.GENERAL_SEARCH,
        confidence=0.94,
        entity_extractor=_entity_from_group("query"),
        name="web.google",
        priority=19,
    ),

    # Banglish search
    Rule(
        _rx(
            r"^(?:please\s+)?"
            r"(?:search|khujo|khujhe)\s+"
            r"(?P<value>.+)$"
        ),
        IntentCategory.WEB_SEARCH,
        SubIntent.GENERAL_SEARCH,
        confidence=0.89,
        entity_extractor=_entity_from_group("query"),
        name="web.search.banglish",
        priority=18,
    ),
]


# ============================================================================
# Intent Classifier
# ============================================================================


class IntentClassifier:
    """
    Production-ready rule-based intent classifier.

    The classifier is thread-safe and keeps classification calls stateless.

    Custom rules can be added at runtime for plugins:

        classifier.add_rule(custom_rule)

    Rules can also be removed, enabled or disabled.
    """

    def __init__(
        self,
        rules: Sequence[Rule] | None = None,
        *,
        min_confidence: float = 0.0,
        chat_confidence: float = DEFAULT_CHAT_CONFIDENCE,
    ) -> None:

        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0.")

        if not 0.0 <= chat_confidence <= 1.0:
            raise ValueError("chat_confidence must be between 0.0 and 1.0.")

        self._lock = threading.RLock()

        # Copy rules so callers cannot accidentally mutate the original
        # module-level rule table.
        self.rules: list[Rule] = list(
            rules if rules is not None else _RULES
        )

        self.min_confidence = float(min_confidence)
        self.chat_confidence = float(chat_confidence)

        # Runtime statistics.
        self._stats: dict[str, int] = {
            "total": 0,
            "matched": 0,
            "general_chat": 0,
            "unknown": 0,
            "errors": 0,
        }

        self._rule_hits: dict[str, int] = {}

        self._sort_rules()

    # ----------------------------------------------------------------------
    # Internal Helpers
    # ----------------------------------------------------------------------

    def _sort_rules(self) -> None:
        """
        Sort rules by priority while preserving insertion order for
        equal priorities.
        """

        self.rules.sort(
            key=lambda rule: rule.priority,
            reverse=True,
        )

    @staticmethod
    def _clean_input(text: Any) -> str:
        """Normalize classifier input."""

        if text is None:
            return ""

        text = str(text)

        # Prevent unexpectedly huge input from entering regex processing.
        text = text[:MAX_INPUT_LENGTH]

        # Normalize whitespace.
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def _record_stat(self, key: str) -> None:
        """Increment a classifier statistic safely."""

        with self._lock:
            self._stats[key] = self._stats.get(key, 0) + 1

    def _record_rule_hit(self, rule: Rule) -> None:
        """Record a rule match."""

        with self._lock:
            self._rule_hits[rule.name] = (
                self._rule_hits.get(rule.name, 0) + 1
            )

    def _build_intent(
        self,
        *,
        text: str,
        rule: Rule,
        match: re.Match[str],
    ) -> Intent:
        """Create an Intent from a matched rule."""

        entities: list[Entity] = []

        if rule.entity_extractor is not None:
            try:
                entities = rule.entity_extractor(match)
            except Exception:
                logger.exception(
                    "Entity extraction failed for rule '%s'.",
                    rule.name,
                )
                entities = []

        confidence = max(
            0.0,
            min(1.0, float(rule.confidence)),
        )

        return Intent(
            category=rule.category,
            raw_text=text,
            confidence=confidence,
            entities=entities,
            sub_intent=rule.sub_intent,
            requires_confirmation=rule.requires_confirmation,
        )

    # ----------------------------------------------------------------------
    # Classification
    # ----------------------------------------------------------------------

    def classify(self, text: str) -> Intent:
        """
        Classify raw user input.

        Returns
        -------
        Intent
            Structured intent object.

        Behavior
        --------
        - Empty input -> UNKNOWN
        - Matching actionable rule -> classified Intent
        - No rule -> GENERAL_CHAT
        """

        self._record_stat("total")

        cleaned = self._clean_input(text)

        if not cleaned:
            self._record_stat("unknown")
            return unknown_intent(text)

        try:
            with self._lock:
                rules_snapshot = tuple(self.rules)

            for rule in rules_snapshot:

                if not rule.enabled:
                    continue

                if rule.confidence < self.min_confidence:
                    continue

                match = rule.matches(cleaned)

                if match is None:
                    continue

                intent = self._build_intent(
                    text=text,
                    rule=rule,
                    match=match,
                )

                self._record_stat("matched")
                self._record_rule_hit(rule)

                logger.debug(
                    "Intent classified: text=%r rule=%s category=%s "
                    "sub_intent=%s confidence=%.2f",
                    text,
                    rule.name,
                    intent.category,
                    intent.sub_intent,
                    intent.confidence,
                )

                return intent

        except Exception:
            self._record_stat("errors")

            logger.exception(
                "Unexpected classifier error for input: %r",
                text,
            )

            # Never crash the assistant because of classification.
            return general_chat_intent(
                text,
                confidence=self.chat_confidence,
            )

        # No actionable rule matched.
        self._record_stat("general_chat")

        return general_chat_intent(
            text,
            confidence=self.chat_confidence,
        )

    # ----------------------------------------------------------------------
    # Batch Classification
    # ----------------------------------------------------------------------

    def classify_many(
        self,
        texts: Sequence[str],
    ) -> list[Intent]:
        """
        Classify multiple inputs.

        Useful for testing, batch processing and diagnostics.
        """

        return [
            self.classify(text)
            for text in texts
        ]

    # ----------------------------------------------------------------------
    # Rule Management
    # ----------------------------------------------------------------------

    def add_rule(
        self,
        rule: Rule,
        priority: int | None = None,
    ) -> None:
        """
        Add a custom rule.

        Backward-compatible with the old API:

            classifier.add_rule(rule, priority=0)

        New style:

            classifier.add_rule(rule)

        Higher priority rules are checked first.
        """

        if not isinstance(rule, Rule):
            raise RuleValidationError(
                "add_rule() expects a Rule instance."
            )

        with self._lock:

            if priority is not None:
                rule.priority = int(priority)

            self.rules.append(rule)
            self._sort_rules()

        logger.info(
            "Classification rule added: %s (priority=%d)",
            rule.name,
            rule.priority,
        )

    def remove_rule(self, name: str) -> bool:
        """
        Remove a rule by name.

        Returns True if removed.
        """

        name = str(name).strip()

        if not name:
            return False

        with self._lock:

            for index, rule in enumerate(self.rules):
                if rule.name == name:
                    self.rules.pop(index)

                    logger.info(
                        "Classification rule removed: %s",
                        name,
                    )

                    return True

        return False

    def enable_rule(self, name: str) -> bool:
        """Enable a rule by name."""

        with self._lock:

            for rule in self.rules:
                if rule.name == name:
                    rule.enabled = True
                    return True

        return False

    def disable_rule(self, name: str) -> bool:
        """Disable a rule by name."""

        with self._lock:

            for rule in self.rules:
                if rule.name == name:
                    rule.enabled = False
                    return True

        return False

    def get_rule(self, name: str) -> Rule | None:
        """Return a rule by name."""

        with self._lock:

            for rule in self.rules:
                if rule.name == name:
                    return rule

        return None

    def list_rules(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[Rule]:
        """Return a copy of registered rules."""

        with self._lock:

            if enabled_only:
                return [
                    rule
                    for rule in self.rules
                    if rule.enabled
                ]

            return list(self.rules)

    # ----------------------------------------------------------------------
    # Matching / Debugging
    # ----------------------------------------------------------------------

    def match_rule(
        self,
        text: str,
    ) -> Rule | None:
        """
        Return the first rule that matches the input.

        Useful when debugging why a command was classified.
        """

        cleaned = self._clean_input(text)

        if not cleaned:
            return None

        with self._lock:
            rules_snapshot = tuple(self.rules)

        for rule in rules_snapshot:

            if not rule.enabled:
                continue

            if rule.confidence < self.min_confidence:
                continue

            if rule.matches(cleaned):
                return rule

        return None

    def explain(self, text: str) -> dict[str, Any]:
        """
        Explain how the classifier interpreted an input.

        Example result:

            {
                "text": "open chrome",
                "matched": True,
                "rule": "app.open",
                "category": "...",
                "sub_intent": "...",
                "confidence": 0.96,
            }
        """

        cleaned = self._clean_input(text)

        if not cleaned:
            return {
                "text": text,
                "matched": False,
                "type": "unknown",
            }

        rule = self.match_rule(cleaned)

        if rule is None:
            return {
                "text": text,
                "matched": False,
                "type": "general_chat",
                "confidence": self.chat_confidence,
            }

        return {
            "text": text,
            "matched": True,
            "type": "actionable",
            "rule": rule.name,
            "category": str(rule.category),
            "sub_intent": rule.sub_intent,
            "confidence": rule.confidence,
            "requires_confirmation": rule.requires_confirmation,
        }

    # ----------------------------------------------------------------------
    # Statistics
    # ----------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return classifier statistics."""

        with self._lock:

            return {
                "total": self._stats.get("total", 0),
                "matched": self._stats.get("matched", 0),
                "general_chat": self._stats.get("general_chat", 0),
                "unknown": self._stats.get("unknown", 0),
                "errors": self._stats.get("errors", 0),
                "registered_rules": len(self.rules),
                "enabled_rules": sum(
                    1
                    for rule in self.rules
                    if rule.enabled
                ),
                "rule_hits": dict(self._rule_hits),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return a complete diagnostic snapshot."""

        with self._lock:

            total = self._stats.get("total", 0)
            matched = self._stats.get("matched", 0)

            match_rate = (
                matched / total
                if total
                else 0.0
            )

            return {
                "component": "IntentClassifier",
                "status": "healthy",
                "rules": {
                    "total": len(self.rules),
                    "enabled": sum(
                        1
                        for rule in self.rules
                        if rule.enabled
                    ),
                },
                "statistics": dict(self._stats),
                "match_rate": round(match_rate, 4),
                "rule_hits": dict(self._rule_hits),
                "settings": {
                    "min_confidence": self.min_confidence,
                    "chat_confidence": self.chat_confidence,
                    "max_input_length": MAX_INPUT_LENGTH,
                },
            }

    def reset_stats(self) -> None:
        """Reset runtime classification statistics."""

        with self._lock:

            for key in self._stats:
                self._stats[key] = 0

            self._rule_hits.clear()

        logger.info("Intent classifier statistics reset.")


# ============================================================================
# Global Singleton
# ============================================================================

classifier: IntentClassifier = IntentClassifier()


# ============================================================================
# Convenience Function
# ============================================================================


def classify(text: str) -> Intent:
    """
    Convenience wrapper around the global classifier.

    Example
    -------
        from brain.classifier import classify

        intent = classify("open chrome")
    """

    return classifier.classify(text)


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "ClassifierError",
    "IntentClassifier",
    "Rule",
    "RuleValidationError",
    "classifier",
    "classify",
]
