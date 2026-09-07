"""
conversation.py
================
Manages an in-memory, provider-agnostic conversation session: the
running list of ChatMessage turns, token/length budgeting, and the glue
that ties together core/history.py (persistence), config/prompts.py
(system prompt construction), and ai/provider.py (actual generation).

This is the object brain/response_generator.py and core/assistant.py
interact with day-to-day, rather than talking to a raw provider or the
history store directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ai.provider import AIProviderBase, ChatMessage, CompletionResult, Role, get_fallback_chain, get_provider
from config.constants import MAX_HISTORY_MESSAGES
from config.prompts import PromptContext, build_system_prompt
from config.settings import settings_manager
from core.history import Role as HistoryRole
from core.history import history_manager

logger = logging.getLogger(__name__)


@dataclass
class Conversation:
    """
    Represents one active conversation session with the assistant.

    Not necessarily 1:1 with "app lifetime" — a new Conversation can be
    started explicitly (e.g. a "New Chat" button in the dashboard) while
    still sharing the same underlying persisted history store if desired.
    """

    session_id: str = "default"
    messages: list[ChatMessage] = field(default_factory=list)
    max_messages: int = MAX_HISTORY_MESSAGES
    persona: str = "default"
    _provider: Optional[AIProviderBase] = field(default=None, repr=False, compare=False)

    # -- lifecycle --------------------------------------------------------- #

    def __post_init__(self) -> None:
        self.persona = settings_manager.get("ai.system_persona", "default")
        self._load_persisted_history()

    def _load_persisted_history(self) -> None:
        """
        Hydrate this session from previously saved history, if any.

        Note: core.history.HistoryManager currently maintains a single
        rolling transcript rather than per-session logs. When
        session_id == 'default' we hydrate from it directly; other
        session ids simply start empty (still persisted going forward
        via the same shared store) until history.py grows native
        multi-session support.
        """
        if self.session_id != "default":
            return

        stored = history_manager.as_provider_messages(limit=self.max_messages)
        for entry in stored:
            try:
                role = Role(entry["role"])
            except ValueError:
                continue
            self.messages.append(ChatMessage(role=role, content=entry["content"]))
        if stored:
            logger.debug("Conversation '%s' hydrated with %d prior message(s).", self.session_id, len(stored))

    # -- provider resolution ------------------------------------------------ #

    @property
    def provider(self) -> AIProviderBase:
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def set_provider(self, provider: AIProviderBase) -> None:
        """Override the active provider (e.g. user manually switches to Ollama)."""
        self._provider = provider

    # -- message management -------------------------------------------------- #

    def add_user_message(self, content: str) -> ChatMessage:
        msg = ChatMessage(role=Role.USER, content=content)
        self._append(msg)
        return msg

    def add_assistant_message(self, content: str) -> ChatMessage:
        msg = ChatMessage(role=Role.ASSISTANT, content=content)
        self._append(msg)
        return msg

    def _append(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self._trim()
        if msg.role == Role.USER:
            history_manager.add_user_message(msg.content)
        elif msg.role == Role.ASSISTANT:
            history_manager.add_assistant_message(msg.content)

    def _trim(self) -> None:
        """Keep only the most recent N messages in memory to bound context size."""
        if len(self.messages) > self.max_messages:
            overflow = len(self.messages) - self.max_messages
            self.messages = self.messages[overflow:]

    def clear(self) -> None:
        """Wipe this session's in-memory and persisted messages."""
        self.messages.clear()
        if self.session_id == "default":
            history_manager.clear()
        logger.info("Conversation '%s' cleared.", self.session_id)

    # -- prompt assembly -------------------------------------------------- #

    def _build_payload(self, extra_memory: Optional[str] = None) -> list[ChatMessage]:
        """Assemble the full message list (system + history) sent to the provider."""
        from datetime import datetime

        context = PromptContext(
            persona=self.persona,
            language=settings_manager.get("voice.language", "en-US"),
            current_datetime=datetime.now().strftime("%A, %d %B %Y %I:%M %p"),
            recent_memory=extra_memory,
        )
        system_text = build_system_prompt(context)
        system_msg = ChatMessage(role=Role.SYSTEM, content=system_text)
        return [system_msg, *self.messages]

    # -- generation --------------------------------------------------------- #

    def send(self, user_text: str, extra_memory: Optional[str] = None, use_fallback: bool = True) -> CompletionResult:
        """
        Send a new user message and get back the assistant's reply,
        persisting both turns. On provider failure, automatically tries
        the fallback chain (Gemini -> Ollama -> Local) if use_fallback=True.
        """
        self.add_user_message(user_text)
        payload = self._build_payload(extra_memory=extra_memory)

        providers: Iterable[AIProviderBase] = (
            get_fallback_chain(preferred=self.provider.name) if use_fallback else [self.provider]
        )

        result: Optional[CompletionResult] = None
        for candidate in providers:
            if not candidate.is_available():
                logger.debug("Provider '%s' unavailable, skipping.", candidate.name)
                continue
            result = candidate.generate(payload)
            if result.ok:
                self._provider = candidate
                break
            logger.warning("Provider '%s' failed: %s", candidate.name, result.error)

        if result is None or not result.ok:
            error_text = (
                "I'm sorry, I couldn't reach any AI provider right now. "
                "Please check your internet connection or local Ollama server."
            )
            self.add_assistant_message(error_text)
            return result or CompletionResult(
                text=error_text, provider="none", model="none", latency_seconds=0.0, error="all_providers_failed"
            )

        self.add_assistant_message(result.text)
        return result

    def stream(self, user_text: str, extra_memory: Optional[str] = None) -> Iterable[str]:
        """Streaming variant of send(); yields text chunks as they arrive."""
        self.add_user_message(user_text)
        payload = self._build_payload(extra_memory=extra_memory)

        collected = []
        for chunk in self.provider.stream(payload):
            collected.append(chunk)
            yield chunk

        full_text = "".join(collected).strip()
        if full_text:
            self.add_assistant_message(full_text)

    def token_estimate(self) -> int:
        """Rough token estimate (chars / 4) for the current message list, used
        by higher layers to decide when to trigger memory summarization."""
        total_chars = sum(len(m.content) for m in self.messages)
        return total_chars // 4


class ConversationManager:
    """Registry of active Conversation objects, keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, Conversation] = {}

    def get_or_create(self, session_id: str = "default") -> Conversation:
        if session_id not in self._sessions:
            self._sessions[session_id] = Conversation(session_id=session_id)
        return self._sessions[session_id]

    def end_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def all_session_ids(self) -> list[str]:
        return list(self._sessions.keys())


conversation_manager: ConversationManager = ConversationManager()
