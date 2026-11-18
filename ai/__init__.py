"""
ai
==
AssistantX AI Package

Central public API for AssistantX AI backends and utilities. This package
provides a unified interface to multiple AI providers (Gemini, Ollama, Local AI),
conversation management, embeddings, and semantic search capabilities.

Modules
-------
provider : Core provider abstraction
    Base classes, validation, factory, and fallback chain

gemini : Google Gemini provider
    Cloud-based AI via Google's Gemini API

ollama : Ollama local provider
    Local AI models via Ollama REST API

local_ai : Local AI provider
    Lightweight local AI inference

conversation : Conversation management
    Multi-turn conversation tracking and history

embeddings : Text embeddings and similarity
    Vector embeddings, similarity search, semantic matching

Thread Safety
-------------
This package is thread-safe. All provider instances can be used from
multiple threads concurrently. The factory functions use lazy imports
to avoid circular dependencies and improve initialization speed.

Conversation management maintains per-session state that is isolated
between threads.

Logging
-------
This package uses Python's standard logging module. Configure logging
to see detailed debug information about:

- Provider initialization and selection
- Message validation and normalization
- API calls and retries
- Embedding operations
- Conversation state changes

Example::

    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("ai")

Quick Start
-----------
Generate a response::

    from ai import get_provider, ChatMessage, Role

    provider = get_provider("ollama")  # or "gemini", "local"
    result = provider.generate([
        ChatMessage(Role.USER, "Hello, AssistantX!")
    ])
    print(result.text)

Use fallback providers::

    from ai import generate_with_fallback, ChatMessage, Role

    # Tries Ollama first, then Gemini, then Local AI
    result = generate_with_fallback(
        [ChatMessage(Role.USER, "Generate code")],
        preferred="ollama"
    )

Stream responses::

    from ai import get_provider, ChatMessage, Role

    provider = get_provider("gemini")
    for chunk in provider.stream([
        ChatMessage(Role.USER, "Write a story")
    ]):
        print(chunk, end="", flush=True)
    print()

Embed text and search::

    from ai import embed_text, is_semantically_similar

    vector = embed_text("AssistantX is smart")
    if is_semantically_similar("AssistantX is intelligent", "AssistantX is smart"):
        print("Semantically similar!")

Manage conversations::

    from ai import conversation_manager, ChatMessage, Role

    # Get or create a session
    conv = conversation_manager.get_conversation("user-123")

    # Add messages
    conv.add_message(Role.USER, "Hello")
    conv.add_message(Role.ASSISTANT, "Hi there!")

    # Get history
    history = conv.messages
    stats = conv.stats

Configuration
--------------
Configuration is loaded from `config/settings.py`:

- `ai.provider`: Default provider ("gemini", "ollama", or "local")
- `ai.gemini_model`: Gemini model name
- `ai.ollama_model`: Ollama model name
- `ai.ollama_host`: Ollama server URL (default: http://127.0.0.1:11434)
- `ai.local_model`: Local AI model name
- `ai.embedding_backend`: Embedding backend (default: "local")
- `ai.similarity_threshold`: Semantic similarity threshold (0.0-1.0)

Examples
--------
Basic generation::

    from ai import get_provider, ChatMessage, Role

    provider = get_provider()
    result = provider.generate([
        ChatMessage(Role.SYSTEM, "You are helpful"),
        ChatMessage(Role.USER, "What is Python?")
    ])
    print(result.text)

Error handling::

    from ai import get_provider, ProviderValidationError, ProviderRequestError

    try:
        provider = get_provider("invalid")
    except ProviderValidationError as e:
        print(f"Invalid config: {e}")

    try:
        result = provider.generate([...], max_retries=5)
        if not result.ok:
            print(f"Generation failed: {result.error}")
    except ProviderRequestError as e:
        print(f"Request failed: {e}")

Embeddings and similarity::

    from ai import embed_text, embedding_similarity, rank_by_similarity

    # Get vector embedding
    vector = embed_text("Hello world")

    # Compare vectors
    similarity = embedding_similarity(
        "Hello world",
        "Hi there"
    )
    print(f"Similarity: {similarity:.2%}")

    # Rank by similarity
    texts = ["Hello", "Hi", "Goodbye"]
    ranked = rank_by_similarity("Hello there", texts)
    for text, score in ranked:
        print(f"{text}: {score:.2%}")

Conversation management::

    from ai import conversation_manager, get_conversation, reset_conversation

    # Get or create conversation
    conv = get_conversation("session-1")

    # Access session properties
    print(f"Messages: {len(conv.messages)}")
    print(f"Tokens: {conv.stats.prompt_tokens}")

    # Reset conversation
    reset_conversation("session-1")

Diagnostics::

    from ai import provider_diagnostics, embedding_diagnostics, conversation_diagnostics

    # Check provider health
    diag = provider_diagnostics()
    print(f"Available providers: {diag['available_providers']}")

    # Check embeddings
    emb_diag = embedding_diagnostics()
    print(f"Embedding backend: {emb_diag['backend']}")

    # Check conversations
    conv_diag = conversation_diagnostics()
    print(f"Active sessions: {conv_diag['session_count']}")

See Also
--------
- `ai.provider`: Provider abstraction and factory
- `ai.gemini`: Google Gemini provider
- `ai.ollama`: Ollama local provider
- `ai.local_ai`: Local AI provider
- `ai.conversation`: Conversation management
- `ai.embeddings`: Text embeddings and similarity
"""



from __future__ import annotations

import logging

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
    normalize_messages,
    normalize_provider_name,
    provider_diagnostics,
    try_get_provider,
    validate_provider_name,
    validate_retries,
    validate_temperature,


)



logger = logging.getLogger(__name__)



# ============================================================================
# Lazy Provider Loading
# ============================================================================
#
# Providers are imported lazily to avoid circular dependencies and reduce
# initialization overhead. This allows the ai package to load quickly even
# if some providers are unavailable or misconfigured.



__version__ = "1.0.0"
__author__ = "AssistantX"
__package_name__ = "AssistantX AI"



# ============================================================================
# Provider Core API
# ============================================================================
#
# Central classes and functions for provider abstraction, factory pattern,
# and fallback chain management.



logger.debug("Loaded ai.provider core API")



# ============================================================================
# Gemini Provider
# ============================================================================
#
# Google Gemini AI provider via cloud API. Supports streaming, multiple
# models, and configurable generation parameters.



logger.debug("Loaded ai.gemini provider")


# ============================================================================
# Ollama Provider
# ============================================================================
#
# Ollama local AI provider via REST API. Supports model pulling, local
# inference, and health checking.



logger.debug("Loaded ai.ollama provider")


# ============================================================================
# Local AI Provider
# ============================================================================
#
# Lightweight local AI provider. Supports basic inference and offline
# math operations.



logger.debug("Loaded ai.local_ai provider")



# ============================================================================
# Conversation Management
# ============================================================================
#
# Multi-turn conversation tracking, history management, and session state.
# Maintains separate conversation contexts for different users/sessions.



logger.debug("Loaded ai.conversation management")




# ============================================================================
# Embeddings & Semantic Search
# ============================================================================
#
# Text embedding vectors, similarity computation, and semantic search.
# Supports multiple embedding backends and similarity metrics.



logger.debug("Loaded ai.embeddings utilities")



# ============================================================================
# Package Initialization
# ============================================================================



logger.debug(
    "AssistantX AI package initialized: version=%s",
    __version__,

)




# ============================================================================
# Public API
# ============================================================================
#
# Everything exported here is part of the stable public API. Internal
# implementation details are kept in submodules and not re-exported.



__all__ = [

    # =====================================================================
    # Package Metadata
    # =====================================================================

    "__version__",
    "__author__",
    "__package_name__",


    # =====================================================================
    # Provider Core (Abstraction & Factory)
    # =====================================================================
    # Base classes and exceptions

    "AIProviderBase",
    "ChatMessage",
    "CompletionResult",
    "ProviderInfo",
    "Role",


    # Exceptions

    "ProviderError",
    "ProviderValidationError",
    "ProviderUnavailableError",
    "ProviderConfigurationError",
    "ProviderRequestError",
    "ProviderFactoryError",
    "ProviderStreamingError",


    # Factory and utilities

    "get_provider",
    "try_get_provider",
    "get_fallback_chain",
    "generate_with_fallback",
    "get_best_available_provider",


    # Provider discovery

    "list_provider_names",
    "list_providers",
    "get_available_provider_names",
    "provider_diagnostics",


    # Validation utilities

    "normalize_provider_name",
    "validate_provider_name",
    "validate_temperature",
    "validate_retries",
    "normalize_messages",


    # =====================================================================
    # Gemini Provider
    # =====================================================================


    # Provider class


    "GeminiProvider",
    "GeminiServerInfo",

    # Exceptions


    "GeminiError",
    "GeminiValidationError",
    "GeminiConfigurationError",
    "GeminiConnectionError",
    "GeminiTimeoutError",
    "GeminiResponseError",
    "GeminiStreamingError",


    # Factory and utilities


    "create_gemini_provider",
    "gemini_available",
    "is_gemini_available",
    "get_gemini_model",
    "gemini_diagnostics",


    # =====================================================================
    # Ollama Provider
    # =====================================================================

    # Provider class and metadata


    "OllamaProvider",
    "OllamaModel",
    "OllamaServerInfo",

    # Exceptions


    "OllamaError",
    "OllamaValidationError",
    "OllamaConnectionError",
    "OllamaTimeoutError",
    "OllamaHTTPError",
    "OllamaResponseError",
    "OllamaModelError",

    # Factory and utilities


    "ollama_available",
    "get_ollama_models",
    "pull_ollama_model",
    "ollama_diagnostics",


    # =====================================================================
    # Local AI Provider
    # =====================================================================


    # Provider class


    "LocalAIProvider",

    # Factory and utilities


    "create_local_provider",
    "local_ai_available",
    "local_ai_diagnostics",
    "safe_calculate",

    # =====================================================================
    # Conversation Management
    # =====================================================================


    # Core classes


    "Conversation",
    "ConversationManager",
    "ConversationStats",
    "ConversationInfo",
    "conversation_manager",

    # Exceptions


    "ConversationError",
    "ConversationValidationError",
    "ConversationProviderError",
    "ConversationStreamError",


    # Utilities


    "get_conversation",
    "reset_conversation",
    "conversation_diagnostics",

    # =====================================================================
    # Embeddings & Similarity Search
    # =====================================================================


    # Data classes


    "EmbeddingResult",
    "SimilarityResult",
    "EmbeddingBackendInfo",

    # Exceptions


    "EmbeddingError",
    "EmbeddingValidationError",
    "EmbeddingBackendError",
    "EmbeddingDimensionError",

    # Core functions


    "embed_text",
    "normalize_vector",
    "cosine_similarity",
    "embedding_similarity",
    "is_semantically_similar",
    "rank_by_similarity",
    "rank_results",


    # Backward-compatible aliases


    "embedding",
    "similarity",
    "search_similar",
    "embedding_diagnostics",

    
]

