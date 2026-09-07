"""
prompts.py
==========
Central library of system prompts, persona templates, and reusable
prompt fragments fed to the AI providers (ai/gemini.py, ai/ollama.py,
etc.) via brain/prompt_engine.py.

Keeping prompt text here (rather than scattered inline strings) makes it
trivial to:
    - A/B test different personas
    - Localize prompts per language
    - Version-control prompt changes independently of code logic
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Optional

from config.constants import APP_NAME

# --------------------------------------------------------------------------- #
# Core system persona prompts
# --------------------------------------------------------------------------- #

BASE_SYSTEM_PROMPT: str = f"""\
You are {APP_NAME}, a helpful, concise, and friendly personal AI assistant
running locally on the user's computer. You can control the desktop,
launch applications, search the web, check the weather, manage reminders,
and hold natural conversations.

Guidelines:
- Keep responses conversational and reasonably brief unless the user asks
  for detail.
- When you are not fully certain about something time-sensitive (news,
  weather, current events), say so rather than guessing.
- If the user's request maps to a system action (opening an app, playing
  music, taking a screenshot, etc.), respond as if you performed it and
  briefly confirm the outcome; the automation layer executes the actual
  action separately based on detected intent.
- Never fabricate personal data about the user that has not been shared
  with you in this conversation or stored in memory.
- Match the user's language when reasonable (English or Bangla).
"""

PERSONA_PROMPTS: dict[str, str] = {
    "default": BASE_SYSTEM_PROMPT,
    "professional": BASE_SYSTEM_PROMPT
    + "\nAdopt a formal, business-appropriate tone. Avoid slang and emoji.",
    "friendly": BASE_SYSTEM_PROMPT
    + "\nBe warm, casual, and upbeat. Light emoji use is welcome.",
    "concise": BASE_SYSTEM_PROMPT
    + "\nBe extremely brief. Prefer single-sentence answers unless asked "
    "for more detail.",
    "coding_assistant": f"""\
You are {APP_NAME} operating in coding-assistant mode. Provide accurate,
well-formatted code with brief explanations. Default to Python unless
another language is specified or clearly implied by context.
""",
}

# --------------------------------------------------------------------------- #
# Intent classification prompt (used by brain/classifier.py as a fallback
# to a purely rule-based classifier, when an LLM-based classification pass
# is desired instead).
# --------------------------------------------------------------------------- #

INTENT_CLASSIFICATION_PROMPT = Template(
    """\
Classify the following user utterance into exactly one of these intent
categories: $categories.

Respond with ONLY the category name, nothing else.

Utterance: "$utterance"
Category:"""
)

# --------------------------------------------------------------------------- #
# Memory summarization prompt (used by core/memory.py to compress long
# conversation history into durable long-term memory notes).
# --------------------------------------------------------------------------- #

MEMORY_SUMMARIZATION_PROMPT = Template(
    """\
Summarize the key facts, preferences, and commitments the user has shared
in the conversation below into short, standalone bullet points suitable
for long-term memory storage. Ignore small talk. Output at most $max_bullets
bullet points, each under 20 words.

Conversation:
$conversation

Bullet points:"""
)

# --------------------------------------------------------------------------- #
# Response generation helpers
# --------------------------------------------------------------------------- #

CLARIFICATION_PROMPT = Template(
    "The user's request was ambiguous: \"$utterance\". Ask a single, "
    "short clarifying question to resolve the ambiguity."
)

ERROR_APOLOGY_PROMPT = Template(
    "Briefly and naturally apologize that you were unable to complete "
    "the following action due to an error, without technical jargon: "
    "$action_description"
)


@dataclass
class PromptContext:
    """Structured inputs commonly interpolated into prompt templates."""

    user_name: Optional[str] = None
    persona: str = "default"
    language: str = "en-US"
    current_datetime: Optional[str] = None
    recent_memory: Optional[str] = None


def build_system_prompt(context: PromptContext) -> str:
    """
    Assemble the final system prompt sent to the AI provider, layering
    persona, user identity, locale, and recalled memory on top of the
    base persona prompt.
    """
    persona_text = PERSONA_PROMPTS.get(context.persona, BASE_SYSTEM_PROMPT)
    parts = [persona_text]

    if context.user_name:
        parts.append(f"The user's name is {context.user_name}. Address them naturally.")

    if context.current_datetime:
        parts.append(f"The current date and time is {context.current_datetime}.")

    if context.recent_memory:
        parts.append(
            "Relevant facts you remember about the user:\n" + context.recent_memory
        )

    if context.language and context.language.lower().startswith("bn"):
        parts.append("Respond in Bangla (বাংলা) unless the user switches language.")

    return "\n\n".join(parts)


def get_persona_names() -> list[str]:
    """Return all available persona keys, for populating a settings dropdown."""
    return list(PERSONA_PROMPTS.keys())
    