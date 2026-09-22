"""
AssistantX AI Package
======================

Central public API for AssistantX AI backends.

This package exposes:
- Provider abstraction and factory
- Gemini / Ollama / Local AI providers
- Conversation management
- Embedding and similarity utilities
- Provider diagnostics and fallback helpers

Example
-------
    from ai import get_provider, embed_text

    provider = get_provider("ollama")
    result = provider.generate([
        {"role": "user", "content": "Hello"}
    ])

    vector = embed_text("AssistantX is smart.")
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
from ai.conversation import (
    Conversation,
    ConversationError,
    ConversationInfo,
    ConversationManager,
    ConversationProviderError,
    ConversationStats,
    ConversationStreamError,
    ConversationValidationError,
    conversation_diagnostics,
    conversation_manager,
    get_conversation,
    reset_conversation,
)

# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
from ai.embeddings import (
    EmbeddingBackendError,
    EmbeddingBackendInfo,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingResult,
    EmbeddingValidationError,
    SimilarityResult,
    cosine_similarity,
    embed_text,
    embedding,
    embedding_diagnostics,
    embedding_similarity,
    is_semantically_similar,
    normalize_vector,
    rank_by_similarity,
    rank_results,
    search_similar,
    similarity,
)

# ---------------------------------------------------------------------------
# Concrete Providers
# ---------------------------------------------------------------------------
from ai.gemini import (
    GeminiConfigurationError,
    GeminiConnectionError,
    GeminiError,
    GeminiProvider,
    GeminiResponseError,
    GeminiServerInfo,
    GeminiStreamingError,
    GeminiTimeoutError,
    GeminiValidationError,
    create_gemini_provider,
    gemini_available,
    gemini_diagnostics,
    get_gemini_model,
    is_gemini_available,
)
from ai.local_ai import (
    LocalAIProvider,
    create_local_provider,
    local_ai_available,
    local_ai_diagnostics,
    safe_calculate,
)
from ai.ollama import (
    OllamaConnectionError,
    OllamaError,
    OllamaHTTPError,
    OllamaModel,
    OllamaModelError,
    OllamaProvider,
    OllamaResponseError,
    OllamaServerInfo,
    OllamaTimeoutError,
    OllamaValidationError,
    get_ollama_models,
    ollama_available,
    ollama_diagnostics,
    pull_ollama_model,
)

# ---------------------------------------------------------------------------
# Provider Core
# ---------------------------------------------------------------------------
from ai.provider import (
    AIProviderBase,
    ChatMessage,
    CompletionResult,
    ProviderConfigurationError,
    ProviderError,
    ProviderFactoryError,
    ProviderInfo,
    ProviderRequestError,
    ProviderStreamingError,
    ProviderUnavailableError,
    ProviderValidationError,
    Role,
    generate_with_fallback,
    get_available_provider_names,
    get_best_available_provider,
    get_fallback_chain,
    get_provider,
    list_provider_names,
    list_providers,
    provider_diagnostics,
    try_get_provider,
)

# ---------------------------------------------------------------------------
# Package Metadata
# ---------------------------------------------------------------------------

__version__ = "1.0.0"
__author__ = "AssistantX"
__package_name__ = "AssistantX AI"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # -----------------------------------------------------------------------
    # Provider Core
    # -----------------------------------------------------------------------
    "AIProviderBase",
    "ChatMessage",
    "CompletionResult",
    "ProviderInfo",
    "Role",

    # Provider exceptions
    "ProviderError",
    "ProviderValidationError",
    "ProviderUnavailableError",
    "ProviderConfigurationError",
    "ProviderRequestError",
    "ProviderFactoryError",
    "ProviderStreamingError",

    # Provider factory / utilities
    "get_provider",
    "try_get_provider",
    "get_fallback_chain",
    "generate_with_fallback",
    "list_provider_names",
    "list_providers",
    "get_available_provider_names",
    "get_best_available_provider",
    "provider_diagnostics",

    # -----------------------------------------------------------------------
    # Gemini
    # -----------------------------------------------------------------------
    "GeminiProvider",
    "GeminiServerInfo",

    "GeminiError",
    "GeminiValidationError",
    "GeminiConfigurationError",
    "GeminiConnectionError",
    "GeminiTimeoutError",
    "GeminiResponseError",
    "GeminiStreamingError",

    "gemini_available",
    "create_gemini_provider",
    "gemini_diagnostics",
    "get_gemini_model",
    "is_gemini_available",

    # -----------------------------------------------------------------------
    # Ollama
    # -----------------------------------------------------------------------
    "OllamaProvider",
    "OllamaModel",
    "OllamaServerInfo",

    "OllamaError",
    "OllamaValidationError",
    "OllamaConnectionError",
    "OllamaTimeoutError",
    "OllamaHTTPError",
    "OllamaResponseError",
    "OllamaModelError",

    "ollama_available",
    "get_ollama_models",
    "pull_ollama_model",
    "ollama_diagnostics",

    # -----------------------------------------------------------------------
    # Local AI
    # -----------------------------------------------------------------------
    "LocalAIProvider",
    "local_ai_available",
    "create_local_provider",
    "local_ai_diagnostics",
    "safe_calculate",

    # -----------------------------------------------------------------------
    # Conversation
    # -----------------------------------------------------------------------
    "Conversation",
    "ConversationManager",
    "ConversationStats",
    "ConversationInfo",
    "conversation_manager",

    # Conversation exceptions
    "ConversationError",
    "ConversationValidationError",
    "ConversationProviderError",
    "ConversationStreamError",

    # Conversation helpers
    "get_conversation",
    "reset_conversation",
    "conversation_diagnostics",

    # -----------------------------------------------------------------------
    # Embeddings
    # -----------------------------------------------------------------------
    "EmbeddingResult",
    "SimilarityResult",
    "EmbeddingBackendInfo",

    # Embedding exceptions
    "EmbeddingError",
    "EmbeddingValidationError",
    "EmbeddingBackendError",
    "EmbeddingDimensionError",

    # Embedding functions
    "embed_text",
    "normalize_vector",
    "cosine_similarity",
    "rank_by_similarity",
    "rank_results",
    "embedding_similarity",
    "is_semantically_similar",

    # Backward-compatible aliases
    "embedding",
    "similarity",
    "search_similar",
    "embedding_diagnostics",
]
