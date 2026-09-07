"""
ai
==
AI backend package for AssistantX.

Exposes the provider abstraction, all three concrete providers, the
conversation manager, and embedding utilities at the package level for
convenient importing:

    from ai import get_provider, conversation_manager, embed_text
"""

from __future__ import annotations

from ai.conversation import Conversation, ConversationManager, conversation_manager
from ai.embeddings import EmbeddingResult, cosine_similarity, embed_text, rank_by_similarity
from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    ProviderError,
    Role,
    get_fallback_chain,
    get_provider,
)

__all__ = [
    # provider core
    "AIProviderBase",
    "ChatMessage",
    "CompletionResult",
    "ProviderError",
    "Role",
    "get_provider",
    "get_fallback_chain",
    # conversation
    "Conversation",
    "ConversationManager",
    "conversation_manager",
    # embeddings
    "EmbeddingResult",
    "embed_text",
    "cosine_similarity",
    "rank_by_similarity",
]
