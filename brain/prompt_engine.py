"""
prompt_engine.py
================
Bridges brain/ context (intent, conversational state, retrieved memory)
with config/prompts.py's template functions, and ai/conversation.py's
Conversation object, to build the exact payload sent to the AI provider
for a GENERAL_CHAT-routed turn.

Where config/prompts.py owns the raw template TEXT, prompt_engine.py
owns the LOGIC of what dynamic content should be gathered and injected
for a given turn (which memories are relevant, what persona to use,
whether to include a system action summary, etc).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ai.conversation import Conversation
from brain.context_manager import context_manager
from brain.intent import Intent
from config.prompts import CLARIFICATION_PROMPT, ERROR_APOLOGY_PROMPT
from config.settings import settings_manager
from core.logger import get_logger
from core.memory import memory_manager

logger = get_logger(__name__)


@dataclass
class PromptPlan:
    """
    The resolved set of inputs that will shape the AI provider call for
    this turn: the user's message, any injected memory context, and
    metadata for logging/debugging.
    """

    user_message: str
    injected_memory: Optional[str]
    persona: str


class PromptEngine:
    """
    Prepares and executes the AI-facing side of a conversational turn.
    Complements decision_engine.py, which handles the *command* side —
    prompt_engine.py only comes into play once a Decision has resolved
    to DecisionAction.CHAT (or a system message needs to be phrased
    naturally, e.g. a clarification or apology).
    """

    def __init__(self, memory_top_k: int = 3) -> None:
        self.memory_top_k = memory_top_k

    def build_plan(self, user_text: str, intent: Optional[Intent] = None) -> PromptPlan:
        """Gather the relevant memory + persona for this turn without yet calling the AI."""
        persona = settings_manager.get("ai.system_persona", "default")

        # core.memory.MemoryManager offers keyword search rather than
        # embedding-based ranking; combine a keyword search on the raw
        # utterance with the manager's own importance-sorted context
        # string so at least some relevant memory is surfaced even when
        # the search misses (e.g. paraphrased queries).
        matched = memory_manager.search(user_text)
        if matched:
            injected_memory = "\n".join(f"- {m.value}" for m in matched[: self.memory_top_k])
        else:
            injected_memory = memory_manager.as_context_string(limit=self.memory_top_k) or None

        return PromptPlan(user_message=user_text, injected_memory=injected_memory, persona=persona)

    def generate_reply(self, conversation: Conversation, user_text: str, intent: Optional[Intent] = None) -> str:
        """
        Full pipeline: build the plan, send it through the Conversation
        object (which itself talks to ai/provider.py), and return the
        assistant's reply text.
        """
        plan = self.build_plan(user_text, intent=intent)
        conversation.persona = plan.persona

        result = conversation.send(plan.user_message, extra_memory=plan.injected_memory)

        if not result.ok:
            logger.warning("AI generation failed for turn: %s", result.error)

        return result.text

    def stream_reply(self, conversation: Conversation, user_text: str, intent: Optional[Intent] = None):
        """Streaming variant of generate_reply — yields text chunks."""
        plan = self.build_plan(user_text, intent=intent)
        conversation.persona = plan.persona
        yield from conversation.stream(plan.user_message, extra_memory=plan.injected_memory)

    # -- non-AI phrasing helpers -------------------------------------------- #
    # These produce natural-sounding system utterances (clarifications,
    # apologies) WITHOUT calling the AI provider, so they're instant and
    # don't burn API quota for simple templated phrasing.

    def phrase_clarification(self, question: str) -> str:
        """Return the clarifying question as-is (already phrased naturally
        by decision_engine.py's _CLARIFICATION_QUESTIONS table)."""
        return question

    def phrase_error_apology(self, action_description: str) -> str:
        """Produce a short, non-technical apology for a failed action."""
        return (
            f"Sorry, I couldn't {action_description}. "
            f"Something went wrong — you may want to try again."
        )

    def phrase_confirmation_prompt(self, prompt: str) -> str:
        return prompt

    def phrase_cancellation(self) -> str:
        return "Okay, I won't do that."

    def phrase_action_success(self, intent: Intent) -> str:
        """
        Generate a short, natural confirmation message after a command
        successfully executes (e.g. "Opened Chrome.", "Reminder set.").
        This deliberately does NOT call the AI — it's templated for
        speed and consistency, mirroring how voice assistants confirm
        actions instantly.
        """
        category = intent.category.value
        sub = intent.sub_intent or ""

        templates = {
            "open_app": lambda: f"Opened {intent.get_entity_value('app_name', 'the app')}.",
            "close_app": lambda: f"Closed {intent.get_entity_value('app_name', 'the app')}.",
            "play_music": lambda: f"Playing {intent.get_entity_value('song_or_query', 'music')}.",
            "pause_music": lambda: "Paused.",
            "next_track": lambda: "Skipped to the next track.",
            "set_reminder": lambda: f"Reminder set: {intent.get_entity_value('reminder_text', '')}.",
            "shutdown": lambda: "Shutting down now.",
            "restart": lambda: "Restarting now.",
            "screenshot": lambda: "Screenshot taken.",
            "create_file": lambda: f"Created {intent.get_entity_value('filename', 'the file')}.",
            "delete_file": lambda: f"Deleted {intent.get_entity_value('filename', 'the file')}.",
        }

        builder = templates.get(sub)
        if builder:
            return builder()
        return f"Done — {category.replace('_', ' ')} completed."


# Module-level singleton.
prompt_engine: PromptEngine = PromptEngine()
