"""
brain.prompt_engine
===================

Prompt orchestration layer for AssistantX.

Responsibilities
----------------
This module connects:

    Intent
      ↓
    Context Manager
      ↓
    Long-term Memory
      ↓
    User Preferences / Persona
      ↓
    Conversation
      ↓
    AI Provider

The module is responsible for deciding WHAT contextual information
should be injected into an AI conversation.

It does NOT:
    - Execute commands
    - Control the operating system
    - Perform browser automation
    - Decide whether a command is safe
    - Directly communicate with dashboard/UI

Those responsibilities belong to the appropriate core/brain modules.

Design Goals
------------
- Clean separation of prompt logic and prompt templates
- Safe memory retrieval
- Configurable memory limits
- Provider-agnostic conversation handling
- Streaming support
- Centralized response phrasing
- Plugin-friendly architecture
- Defensive error handling
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ai.conversation import Conversation
from brain.intent import Intent
from config.prompts import (
    CLARIFICATION_PROMPT,
    ERROR_APOLOGY_PROMPT,
)
from config.settings import settings_manager
from core.logger import get_logger
from core.memory import memory_manager

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_PERSONA = "default"

DEFAULT_MEMORY_TOP_K = 3
MIN_MEMORY_TOP_K = 0
MAX_MEMORY_TOP_K = 20

DEFAULT_CLARIFICATION = (
    "Could you clarify what you'd like me to do?"
)

DEFAULT_ERROR_APOLOGY = (
    "Sorry, I couldn't complete that action. "
    "Something went wrong — please try again."
)

DEFAULT_CANCELLATION = "Okay, I won't do that."

DEFAULT_ACTION_SUCCESS = "Done."

MAX_USER_TEXT_LENGTH = 100_000
MAX_MEMORY_ITEM_LENGTH = 5_000


# ============================================================================
# Exceptions
# ============================================================================


class PromptEngineError(Exception):
    """Base exception for prompt-engine failures."""


class PromptValidationError(PromptEngineError):
    """Raised when prompt input is invalid."""


class PromptContextError(PromptEngineError):
    """Raised when contextual information cannot be resolved."""


# ============================================================================
# Prompt Plan
# ============================================================================


@dataclass(slots=True)
class PromptPlan:
    """
    Resolved prompt inputs for a single conversational turn.

    Attributes
    ----------
    user_message:
        Original normalized user message.

    injected_memory:
        Relevant memory formatted for AI context.

    persona:
        Active assistant persona.

    metadata:
        Additional context/debug information.
    """

    user_message: str
    injected_memory: str | None
    persona: str

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_message = str(self.user_message or "").strip()
        self.persona = str(self.persona or DEFAULT_PERSONA).strip()

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata or {})

    @property
    def has_memory(self) -> bool:
        """Return whether memory context is available."""
        return bool(self.injected_memory)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation."""
        return {
            "user_message": self.user_message,
            "injected_memory": self.injected_memory,
            "persona": self.persona,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Prompt Engine
# ============================================================================


class PromptEngine:
    """
    Central prompt/context orchestration service.

    The engine is intentionally independent of a specific AI provider.
    It prepares the context and delegates actual generation to
    ``Conversation``.
    """

    def __init__(
        self,
        memory_top_k: int = DEFAULT_MEMORY_TOP_K,
    ) -> None:
        self.memory_top_k = self._validate_memory_limit(
            memory_top_k
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_memory_limit(self, limit: int) -> None:
        """
        Change the maximum number of memory entries injected into
        prompts.
        """
        self.memory_top_k = self._validate_memory_limit(limit)

        logger.debug(
            "PromptEngine memory limit changed to %d",
            self.memory_top_k,
        )

    @staticmethod
    def _validate_memory_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise PromptValidationError(
                "memory_top_k must be an integer."
            )

        if not (
            MIN_MEMORY_TOP_K
            <= limit
            <= MAX_MEMORY_TOP_K
        ):
            raise PromptValidationError(
                f"memory_top_k must be between "
                f"{MIN_MEMORY_TOP_K} and "
                f"{MAX_MEMORY_TOP_K}."
            )

        return limit

    # ------------------------------------------------------------------
    # Plan building
    # ------------------------------------------------------------------

    def build_plan(
        self,
        user_text: str,
        intent: Intent | None = None,
    ) -> PromptPlan:
        """
        Build all contextual information required for an AI request.

        This method does NOT call the AI provider.
        """

        user_text = self._validate_user_text(user_text)

        persona = self._resolve_persona()

        memory_context = self._resolve_memory(
            user_text=user_text,
            intent=intent,
        )

        metadata: dict[str, Any] = {
            "memory_count": self._count_memory_lines(
                memory_context
            ),
            "has_memory": bool(memory_context),
        }

        if intent is not None:
            metadata["intent"] = self._get_intent_name(intent)

        return PromptPlan(
            user_message=user_text,
            injected_memory=memory_context,
            persona=persona,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Persona
    # ------------------------------------------------------------------

    def _resolve_persona(self) -> str:
        """Resolve the active AI persona from application settings."""

        try:
            persona = settings_manager.get(
                "ai.system_persona",
                DEFAULT_PERSONA,
            )
        except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning(
                "Unable to load AI persona: %s",
                exc,
            )
            persona = DEFAULT_PERSONA

        persona = str(persona or DEFAULT_PERSONA).strip()

        return persona or DEFAULT_PERSONA

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _resolve_memory(
        self,
        user_text: str,
        intent: Intent | None = None,
    ) -> str | None:
        """
        Resolve relevant memory for the current turn.

        Strategy:

        1. Try keyword/context search.
        2. If useful results exist, use those.
        3. Otherwise fall back to the manager's general context.
        4. Limit the final result.
        """

        if self.memory_top_k <= 0:
            return None

        try:
            matched = memory_manager.search(user_text)

            if matched:
                return self._format_memory_entries(
                    matched[: self.memory_top_k]
                )

        except (
            AttributeError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Memory search failed: %s",
                exc,
            )

        # Fallback context.
        try:
            context = memory_manager.as_context_string(
                limit=self.memory_top_k
            )

            return self._clean_memory_text(context)

        except (
            AttributeError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Memory context retrieval failed: %s",
                exc,
            )

            return None

    def _format_memory_entries(
        self,
        entries: list[Any],
    ) -> str | None:
        """Convert memory entries into compact AI context."""

        lines: list[str] = []

        for entry in entries:
            try:
                value = getattr(entry, "value", entry)

                if value is None:
                    continue

                text = str(value).strip()

                if not text:
                    continue

                text = text[:MAX_MEMORY_ITEM_LENGTH]

                lines.append(f"- {text}")

            except (AttributeError, TypeError, ValueError) as exc:
                logger.debug(
                    "Skipping invalid memory entry: %s",
                    exc,
                )

        if not lines:
            return None

        return "\n".join(lines)

    @staticmethod
    def _clean_memory_text(
        value: Any,
    ) -> str | None:
        """Normalize fallback memory context."""

        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        return text

    @staticmethod
    def _count_memory_lines(
        value: str | None,
    ) -> int:
        """Count injected memory lines."""

        if not value:
            return 0

        return len(
            [
                line
                for line in value.splitlines()
                if line.strip()
            ]
        )

    # ------------------------------------------------------------------
    # AI generation
    # ------------------------------------------------------------------

    def generate_reply(
        self,
        conversation: Conversation,
        user_text: str,
        intent: Intent | None = None,
    ) -> str:
        """
        Generate a complete AI response.

        The actual provider call is delegated to ``Conversation``.
        """

        self._validate_conversation(conversation)

        plan = self.build_plan(
            user_text,
            intent=intent,
        )

        self._apply_plan(
            conversation,
            plan,
        )

        try:
            result = conversation.send(
                plan.user_message,
                extra_memory=plan.injected_memory,
            )

        except (AttributeError, TypeError, ValueError) as exc:
            logger.exception(
                "Conversation generation failed: %s"
            )

            raise PromptEngineError(
                "Failed to generate AI response."
            ) from exc

        if not getattr(result, "ok", False):
            logger.warning(
                "AI generation failed: %s",
                getattr(result, "error", None),
            )

        return str(
            getattr(result, "text", "") or ""
        ).strip()

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------

    def stream_reply(
        self,
        conversation: Conversation,
        user_text: str,
        intent: Intent | None = None,
    ) -> Iterator[str]:
        """
        Stream an AI response chunk-by-chunk.

        The method intentionally yields provider output directly
        instead of buffering the complete response.
        """

        self._validate_conversation(conversation)

        plan = self.build_plan(
            user_text,
            intent=intent,
        )

        self._apply_plan(
            conversation,
            plan,
        )

        try:
            stream = conversation.stream(
                plan.user_message,
                extra_memory=plan.injected_memory,
            )

            for chunk in stream:
                if chunk is None:
                    continue

                text = str(chunk)

                if text:
                    yield text

        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception(
                "Streaming response generation failed: %s"
            )

            raise PromptEngineError(
                "Failed to stream AI response."
            ) from exc

    # ------------------------------------------------------------------
    # Plan application
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_plan(
        conversation: Conversation,
        plan: PromptPlan,
    ) -> None:
        """Apply resolved prompt settings to a conversation."""

        try:
            conversation.persona = plan.persona
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Unable to apply conversation persona: %s",
                exc,
            )

    # ------------------------------------------------------------------
    # Non-AI phrasing
    # ------------------------------------------------------------------

    def phrase_clarification(
        self,
        question: str,
    ) -> str:
        """
        Return a user-friendly clarification message.

        ``question`` normally comes from decision_engine.py.
        """

        question = self._clean_phrase(
            question,
            DEFAULT_CLARIFICATION,
        )

        # Keep this connected to config/prompts.py so the template
        # remains centrally configurable.
        try:
            if "{question}" in CLARIFICATION_PROMPT:
                return CLARIFICATION_PROMPT.format(
                    question=question
                ).strip()

        except (KeyError, ValueError, TypeError) as exc:
            logger.debug(
                "Clarification template formatting failed: %s",
                exc,
            )

        return question

    def phrase_error_apology(
        self,
        action_description: str,
    ) -> str:
        """
        Produce a short non-technical error response.

        Raw exception details should never be exposed here.
        """

        action = self._clean_action_description(
            action_description
        )

        try:
            if "{action}" in ERROR_APOLOGY_PROMPT:
                return ERROR_APOLOGY_PROMPT.format(
                    action=action
                ).strip()

            if "{action_description}" in ERROR_APOLOGY_PROMPT:
                return ERROR_APOLOGY_PROMPT.format(
                    action_description=action
                ).strip()

        except (KeyError, IndexError, ValueError) as exc:
            logger.debug(
                "Error-apology template formatting failed: %s",
                exc,
            )

        if action:
            return (
                f"Sorry, I couldn't {action}. "
                f"Something went wrong — please try again."
            )

        return DEFAULT_ERROR_APOLOGY

    def phrase_confirmation_prompt(
        self,
        prompt: str,
    ) -> str:
        """Return a confirmation prompt."""
        return self._clean_phrase(
            prompt,
            "Are you sure?",
        )

    def phrase_cancellation(self) -> str:
        """Return a standard cancellation response."""
        return DEFAULT_CANCELLATION

    # ------------------------------------------------------------------
    # Action success phrasing
    # ------------------------------------------------------------------

    def phrase_action_success(
        self,
        intent: Intent,
    ) -> str:
        """
        Generate a short confirmation message after successful
        command execution.
        """

        if intent is None:
            return DEFAULT_ACTION_SUCCESS

        sub_intent = self._get_sub_intent(intent)

        entity = self._safe_entity(
            intent,
            "app_name",
        )

        templates = {
            "open_app": (
                lambda: f"Opened {entity or 'the app'}."
            ),
            "close_app": (
                lambda: f"Closed {entity or 'the app'}."
            ),
            "play_music": (
                lambda: (
                    f"Playing "
                    f"{self._safe_entity(intent, 'song_or_query') or 'music'}."
                )
            ),
            "pause_music": (
                lambda: "Paused."
            ),
            "resume_music": (
                lambda: "Resumed playback."
            ),
            "next_track": (
                lambda: "Skipped to the next track."
            ),
            "previous_track": (
                lambda: "Went back to the previous track."
            ),
            "set_reminder": (
                lambda: (
                    "Reminder set"
                    + (
                        f": {self._safe_entity(intent, 'reminder_text')}."
                        if self._safe_entity(
                            intent,
                            "reminder_text",
                        )
                        else "."
                    )
                )
            ),
            "shutdown": (
                lambda: "Shutting down now."
            ),
            "restart": (
                lambda: "Restarting now."
            ),
            "lock_screen": (
                lambda: "Locking the screen."
            ),
            "screenshot": (
                lambda: "Screenshot taken."
            ),
            "create_file": (
                lambda: (
                    f"Created "
                    f"{self._safe_entity(intent, 'filename') or 'the file'}."
                )
            ),
            "delete_file": (
                lambda: (
                    f"Deleted "
                    f"{self._safe_entity(intent, 'filename') or 'the file'}."
                )
            ),
            "create_folder": (
                lambda: (
                    f"Created "
                    f"{self._safe_entity(intent, 'folder_name') or 'the folder'}."
                )
            ),
            "delete_folder": (
                lambda: (
                    f"Deleted "
                    f"{self._safe_entity(intent, 'folder_name') or 'the folder'}."
                )
            ),
            "open_url": (
                lambda: "Opened the requested website."
            ),
            "web_search": (
                lambda: "Search completed."
            ),
            "copy": (
                lambda: "Copied to the clipboard."
            ),
            "clear_clipboard": (
                lambda: "Clipboard cleared."
            ),
        }

        builder = templates.get(sub_intent)

        if builder is not None:
            try:
                return str(builder()).strip()
            except (AttributeError, TypeError, ValueError) as exc:
                logger.debug(
                    "Action success template failed: %s",
                    exc,
                )

        category = self._get_category(intent)

        if category:
            readable = category.replace(
                "_",
                " ",
            )

            return f"Done — {readable} completed."

        return DEFAULT_ACTION_SUCCESS

    # ------------------------------------------------------------------
    # Intent helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_sub_intent(
        intent: Intent,
    ) -> str:
        """Safely resolve sub-intent."""

        value = getattr(
            intent,
            "sub_intent",
            None,
        )

        return str(value or "").strip()

    @staticmethod
    def _get_category(
        intent: Intent,
    ) -> str:
        """Safely resolve intent category."""

        category = getattr(
            intent,
            "category",
            None,
        )

        if category is None:
            return ""

        return str(
            getattr(
                category,
                "value",
                category,
            )
        ).strip()

    @staticmethod
    def _get_intent_name(
        intent: Intent,
    ) -> str:
        """Return a safe intent name for metadata."""

        sub_intent = getattr(
            intent,
            "sub_intent",
            None,
        )

        if sub_intent:
            return str(sub_intent)

        return PromptEngine._get_category(intent)

    @staticmethod
    def _safe_entity(
        intent: Intent,
        key: str,
    ) -> str:
        """
        Safely retrieve an intent entity.

        Intent implementations may differ slightly, so this method
        avoids allowing an entity lookup failure to crash response
        generation.
        """

        try:
            getter = getattr(
                intent,
                "get_entity_value",
                None,
            )

            if not callable(getter):
                return ""

            value = getter(
                key,
                "",
            )

            return str(value or "").strip()

        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "Entity lookup failed: key=%s error=%s",
                key,
                exc,
            )

            return ""

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_user_text(
        user_text: str,
    ) -> str:
        """Validate and normalize user text."""

        if user_text is None:
            raise PromptValidationError(
                "user_text cannot be None."
            )

        text = str(user_text).strip()

        if not text:
            raise PromptValidationError(
                "user_text cannot be empty."
            )

        if len(text) > MAX_USER_TEXT_LENGTH:
            raise PromptValidationError(
                "user_text exceeds the maximum allowed length."
            )

        return text

    @staticmethod
    def _validate_conversation(
        conversation: Conversation,
    ) -> None:
        """Validate the Conversation object."""

        if conversation is None:
            raise PromptValidationError(
                "conversation cannot be None."
            )

        required_methods = (
            "send",
            "stream",
        )

        for method_name in required_methods:
            if not callable(
                getattr(
                    conversation,
                    method_name,
                    None,
                )
            ):
                raise PromptValidationError(
                    f"Conversation is missing required "
                    f"method: {method_name}"
                )

    @staticmethod
    def _clean_phrase(
        value: Any,
        fallback: str,
    ) -> str:
        """Normalize a short user-facing phrase."""

        text = str(value or "").strip()

        return text or fallback

    @staticmethod
    def _clean_action_description(
        value: Any,
    ) -> str:
        """Normalize an action description."""

        text = str(value or "").strip()

        text = text.replace(
            "_",
            " ",
        )

        return " ".join(
            text.split()
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """Return prompt-engine diagnostics."""

        return {
            "engine": self.__class__.__name__,
            "memory_top_k": self.memory_top_k,
            "memory_enabled": self.memory_top_k > 0,
            "default_persona": DEFAULT_PERSONA,
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"memory_top_k={self.memory_top_k})"
        )


# ============================================================================
# Global Singleton
# ============================================================================

prompt_engine = PromptEngine()


# ============================================================================
# Convenience API
# ============================================================================


def build_prompt_plan(
    user_text: str,
    intent: Intent | None = None,
) -> PromptPlan:
    """Build a prompt plan using the global engine."""

    return prompt_engine.build_plan(
        user_text,
        intent=intent,
    )


def generate_reply(
    conversation: Conversation,
    user_text: str,
    intent: Intent | None = None,
) -> str:
    """Generate a complete AI reply using the global engine."""

    return prompt_engine.generate_reply(
        conversation,
        user_text,
        intent=intent,
    )


def stream_reply(
    conversation: Conversation,
    user_text: str,
    intent: Intent | None = None,
) -> Iterator[str]:
    """Stream an AI reply using the global engine."""

    yield from prompt_engine.stream_reply(
        conversation,
        user_text,
        intent=intent,
    )


def prompt_engine_diagnostics() -> dict[str, Any]:
    """Return diagnostics for the global prompt engine."""

    return prompt_engine.diagnostics()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "PromptContextError",
    # Engine
    "PromptEngine",
    # Exceptions
    "PromptEngineError",
    # Data
    "PromptPlan",
    "PromptValidationError",
    # Convenience API
    "build_prompt_plan",
    "generate_reply",
    # Singleton
    "prompt_engine",
    "prompt_engine_diagnostics",
    "stream_reply",
]
