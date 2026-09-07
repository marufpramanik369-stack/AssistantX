"""
classifier.py
=============
Converts a raw user utterance (text, already transcribed from voice or
typed) into a structured Intent object.

Strategy: a fast, dependency-free, rule-based classifier using keyword
and regex matching, ordered by specificity. This is deliberately NOT an
ML model — for a desktop assistant, deterministic rules are:
    - Instant (no model load / inference latency)
    - Fully offline
    - Easy to debug and extend ("why did it think I meant X?")
    - Good enough for command-style utterances, which make up the
      majority of assistant interactions (open X, play Y, what's the
      weather, set a reminder...).

Utterances that don't match any rule confidently fall through to
GENERAL_CHAT, which routes to the AI provider for a conversational
response — the classifier's job is only to catch actionable commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Pattern

from brain.intent import Entity, Intent, SubIntent, general_chat_intent, unknown_intent
from config.constants import IntentCategory
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Rule:
    """A single classification rule: pattern -> (category, sub_intent, entity extractor)."""

    pattern: Pattern
    category: IntentCategory
    sub_intent: Optional[str] = None
    confidence: float = 0.9
    entity_extractor: Optional[Callable[[re.Match], list[Entity]]] = None
    requires_confirmation: bool = False


def _entity_from_group(name: str, group: str = "value") -> Callable[[re.Match], list[Entity]]:
    """Build a simple single-entity extractor pulling a named regex group."""

    def extractor(match: re.Match) -> list[Entity]:
        try:
            value = match.group(group).strip()
        except (IndexError, AttributeError):
            return []
        return [Entity(name=name, value=value, confidence=0.95)] if value else []

    return extractor


# --------------------------------------------------------------------------- #
# Rule table — ORDER MATTERS. More specific patterns should appear before
# more general ones, since the first matching rule wins.
# --------------------------------------------------------------------------- #

_RULES: list[Rule] = [
    # -- System control -------------------------------------------------- #
    Rule(re.compile(r"\bshut ?down\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.SHUTDOWN, requires_confirmation=True),
    Rule(re.compile(r"\brestart\b.*\b(computer|system|pc)\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.RESTART, requires_confirmation=True),
    Rule(re.compile(r"\b(sleep|hibernate)\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.SLEEP),
    Rule(re.compile(r"\block\b.*\b(computer|screen|pc)\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.LOCK),
    Rule(re.compile(r"\bmute\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.MUTE),
    Rule(re.compile(r"\bvolume\s*up\b|\bincrease\s*volume\b|\blouder\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.VOLUME_UP),
    Rule(re.compile(r"\bvolume\s*down\b|\bdecrease\s*volume\b|\bquieter\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.VOLUME_DOWN),
    Rule(re.compile(r"\bbrightness\s*up\b|\bbrighter\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.BRIGHTNESS_UP),
    Rule(re.compile(r"\bbrightness\s*down\b|\bdimmer\b", re.I), IntentCategory.SYSTEM_CONTROL, SubIntent.BRIGHTNESS_DOWN),
    Rule(re.compile(r"\btake\s*a?\s*screenshot\b", re.I), IntentCategory.SYSTEM_CONTROL, "screenshot"),

    # -- App launch --------------------------------------------------------- #
    Rule(
        re.compile(r"\bopen\s+(?P<value>[\w\s]+?)(?:\s+app|\s+application)?$", re.I),
        IntentCategory.APP_LAUNCH,
        SubIntent.OPEN_APP,
        entity_extractor=_entity_from_group("app_name"),
    ),
    Rule(
        re.compile(r"\b(?:launch|start)\s+(?P<value>[\w\s]+)$", re.I),
        IntentCategory.APP_LAUNCH,
        SubIntent.OPEN_APP,
        entity_extractor=_entity_from_group("app_name"),
    ),
    Rule(
        re.compile(r"\bclose\s+(?P<value>[\w\s]+)$", re.I),
        IntentCategory.APP_LAUNCH,
        SubIntent.CLOSE_APP,
        entity_extractor=_entity_from_group("app_name"),
    ),

    # -- Music -------------------------------------------------------------- #
    Rule(
        re.compile(r"\bplay\s+(?P<value>.+?)(?:\s+(?:on|from)\s+\w+)?$", re.I),
        IntentCategory.MUSIC,
        SubIntent.PLAY_MUSIC,
        entity_extractor=_entity_from_group("song_or_query"),
    ),
    Rule(re.compile(r"\bpause\s*(music|song|track)?\b", re.I), IntentCategory.MUSIC, SubIntent.PAUSE_MUSIC),
    Rule(re.compile(r"\bnext\s*(song|track)\b|\bskip\b", re.I), IntentCategory.MUSIC, SubIntent.NEXT_TRACK),
    Rule(re.compile(r"\b(previous|last)\s*(song|track)\b", re.I), IntentCategory.MUSIC, SubIntent.PREVIOUS_TRACK),

    # -- Weather -------------------------------------------------------------- #
    Rule(
        re.compile(r"\bweather\b.*\b(?:in|at|for)\s+(?P<value>[\w\s]+)$", re.I),
        IntentCategory.WEATHER,
        entity_extractor=_entity_from_group("location"),
    ),
    Rule(re.compile(r"\b(weather|temperature|forecast)\b", re.I), IntentCategory.WEATHER),

    # -- News ------------------------------------------------------------------ #
    Rule(
        re.compile(r"\bnews\b.*\babout\s+(?P<value>[\w\s]+)$", re.I),
        IntentCategory.NEWS,
        entity_extractor=_entity_from_group("topic"),
    ),
    Rule(re.compile(r"\b(latest\s+)?news\b|\bheadlines\b", re.I), IntentCategory.NEWS),

    # -- Reminders --------------------------------------------------------------- #
    Rule(
        re.compile(r"\bremind\s+me\s+(?:to\s+)?(?P<value>.+)$", re.I),
        IntentCategory.REMINDER,
        SubIntent.SET_REMINDER,
        entity_extractor=_entity_from_group("reminder_text"),
    ),
    Rule(re.compile(r"\b(list|show)\s+(my\s+)?reminders\b", re.I), IntentCategory.REMINDER, SubIntent.LIST_REMINDERS),
    Rule(
        re.compile(r"\bcancel\s+(?:the\s+)?reminder\s*(?:about\s+)?(?P<value>.*)$", re.I),
        IntentCategory.REMINDER,
        SubIntent.CANCEL_REMINDER,
        entity_extractor=_entity_from_group("reminder_text"),
    ),

    # -- File operations ------------------------------------------------------------- #
    Rule(
        re.compile(r"\bcreate\s+(?:a\s+)?(?:new\s+)?file\s+(?:called\s+|named\s+)?(?P<value>[\w\-. ]+)$", re.I),
        IntentCategory.FILE_OPERATION,
        SubIntent.CREATE_FILE,
        entity_extractor=_entity_from_group("filename"),
    ),
    Rule(
        re.compile(r"\bdelete\s+(?:the\s+)?file\s+(?P<value>[\w\-. ]+)$", re.I),
        IntentCategory.FILE_OPERATION,
        SubIntent.DELETE_FILE,
        entity_extractor=_entity_from_group("filename"),
        requires_confirmation=True,
    ),
    Rule(
        re.compile(r"\bopen\s+(?:the\s+)?folder\s+(?P<value>[\w\-. /\\]+)$", re.I),
        IntentCategory.FILE_OPERATION,
        SubIntent.OPEN_FOLDER,
        entity_extractor=_entity_from_group("folder_path"),
    ),
    Rule(
        re.compile(r"\bfind\s+(?:the\s+)?file\s+(?P<value>[\w\-. ]+)$", re.I),
        IntentCategory.FILE_OPERATION,
        SubIntent.SEARCH_FILE,
        entity_extractor=_entity_from_group("filename"),
    ),

    # -- Calculation ------------------------------------------------------------------- #
    Rule(
        re.compile(r"^(?P<value>[\d\s+\-*/().]+)$"),
        IntentCategory.CALCULATION,
        SubIntent.ARITHMETIC,
        entity_extractor=_entity_from_group("expression"),
        confidence=0.85,
    ),
    Rule(
        re.compile(r"\bwhat(?:'s| is)\s+(?P<value>[\d\s+\-*/().]+)\??$", re.I),
        IntentCategory.CALCULATION,
        SubIntent.ARITHMETIC,
        entity_extractor=_entity_from_group("expression"),
    ),
    Rule(
        re.compile(r"\bconvert\s+(?P<value>.+?)\s+to\s+(?P<unit>[\w]+)$", re.I),
        IntentCategory.CALCULATION,
        SubIntent.UNIT_CONVERSION,
    ),

    # -- Web search (broad, kept low in priority) -------------------------------------- #
    Rule(
        re.compile(r"\bsearch\s+(?:for\s+)?(?P<value>.+)$", re.I),
        IntentCategory.WEB_SEARCH,
        SubIntent.GENERAL_SEARCH,
        entity_extractor=_entity_from_group("query"),
    ),
    Rule(
        re.compile(r"\bgoogle\s+(?P<value>.+)$", re.I),
        IntentCategory.WEB_SEARCH,
        SubIntent.GENERAL_SEARCH,
        entity_extractor=_entity_from_group("query"),
    ),
]


class IntentClassifier:
    """
    Stateless rule-based classifier. Instantiate once and reuse
    (see `classifier` singleton at the bottom of this file) — it holds
    no per-call mutable state.
    """

    def __init__(self, rules: Optional[list[Rule]] = None) -> None:
        self.rules = rules if rules is not None else _RULES

    def classify(self, text: str) -> Intent:
        """
        Classify a raw utterance into an Intent.

        Falls through to GENERAL_CHAT if no rule matches with sufficient
        confidence, so conversational utterances are handled naturally
        by the AI provider rather than misfiring as a bogus command.
        """
        cleaned = text.strip()
        if not cleaned:
            return unknown_intent(text)

        for rule in self.rules:
            match = rule.pattern.search(cleaned)
            if not match:
                continue

            entities = rule.entity_extractor(match) if rule.entity_extractor else []

            intent = Intent(
                category=rule.category,
                raw_text=text,
                confidence=rule.confidence,
                entities=entities,
                sub_intent=rule.sub_intent,
                requires_confirmation=rule.requires_confirmation,
            )
            logger.debug("Classified %r -> %s", text, intent)
            return intent

        # No rule matched -> treat as general conversation.
        return general_chat_intent(text, confidence=0.6)

    def add_rule(self, rule: Rule, priority: int = 0) -> None:
        """
        Insert a custom rule (e.g. from plugins/custom_commands.py) at
        the given priority index (0 = highest priority, checked first).
        """
        self.rules.insert(priority, rule)
        logger.info("Custom classification rule added at priority %d.", priority)


# Module-level singleton for convenient importing across the codebase.
classifier: IntentClassifier = IntentClassifier()
