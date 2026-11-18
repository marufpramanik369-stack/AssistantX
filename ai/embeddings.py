"""
ai/embeddings.py (IMPROVED VERSION)
===================================
Text embeddings and semantic similarity utilities for AssistantX.

Backends
--------
1. Gemini Embedding API
   - Higher semantic quality
   - Requires google-generativeai + valid Gemini API key
   - Automatically falls back to local if unavailable

2. Local Hashing Embedding
   - Deterministic and reproducible
   - Zero external dependencies
   - Fully offline operation
   - Useful as graceful fallback

Design Principles
-----------------
- Never hard-fail during embedding generation
- Automatic remote → local fallback with logging
- Deterministic local embeddings for reproducibility
- Thread-safe caching with LRU eviction
- Dimension-aware similarity calculations
- Optional but configurable caching
- Support for multilingual text (Latin + Bangla + Unicode)

Thread Safety
-------------
All caching operations use RLock for thread-safe access.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Optional

from config.secrets import secrets

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Backend identifiers
PROVIDER_GEMINI = "gemini"
PROVIDER_LOCAL = "local_hash"

# Embedding dimensions
DEFAULT_LOCAL_DIMENSIONS = 256
DEFAULT_TOP_K = 5

# Input validation
MAX_TEXT_LENGTH = 20_000
MAX_CANDIDATES = 10_000

# Cache settings
CACHE_ENABLED = True
CACHE_SIZE = 512

# Gemini API model
GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"

# Regex patterns for tokenization (Latin + Bangla + Unicode)
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_NORMALIZE_PATTERN = re.compile(r"\s+")

# Similarity thresholds
DEFAULT_MIN_SIMILARITY = -1.0
DEFAULT_MAX_SIMILARITY = 1.0


# ============================================================================
# Exceptions
# ============================================================================


class EmbeddingError(RuntimeError):
    """Base exception for all embedding-related errors."""

    pass


class EmbeddingValidationError(EmbeddingError):
    """Raised when embedding input validation fails."""

    pass


class EmbeddingBackendError(EmbeddingError):
    """Raised when a specific embedding backend fails unexpectedly."""

    pass


class EmbeddingDimensionError(EmbeddingError):
    """Raised when vector dimensions are invalid or mismatched."""

    pass


class EmbeddingCacheError(EmbeddingError):
    """Raised when cache operations fail."""

    pass


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """
    Result of an embedding generation operation.

    Attributes
    ----------
    vector : list[float]
        The generated embedding vector
    dimensions : int
        Number of dimensions in the vector
    backend : str
        Backend used to generate the embedding (gemini or local_hash)
    """

    vector: list[float]
    dimensions: int
    backend: str

    @property
    def is_local(self) -> bool:
        """Check if embedding was generated locally."""

        return self.backend == PROVIDER_LOCAL

    @property
    def is_remote(self) -> bool:
        """Check if embedding was generated via Gemini API."""

        return self.backend == PROVIDER_GEMINI


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """
    Similarity ranking result for one candidate text.

    Attributes
    ----------
    text : str
        The candidate text
    score : float
        Cosine similarity score (approximately -1.0 to 1.0)
    index : int
        Original index in candidates list
    """

    text: str
    score: float
    index: int = 0


@dataclass(frozen=True, slots=True)
class EmbeddingBackendInfo:
    """
    Information about an available embedding backend.

    Attributes
    ----------
    name : str
        Backend name (gemini or local_hash)
    available : bool
        Whether this backend is currently available
    dimensions : int or None
        Vector dimensions if fixed, None if variable
    """

    name: str
    available: bool
    dimensions: Optional[int] = None


@dataclass(frozen=True, slots=True)
class EmbeddingCacheStats:
    """
    Statistics about the embedding cache.

    Attributes
    ----------
    cache_size : int
        Number of embeddings currently cached
    max_size : int
        Maximum cache capacity
    enabled : bool
        Whether caching is enabled
    """

    cache_size: int
    max_size: int
    enabled: bool

    @property
    def utilization(self) -> float:
        """Return cache utilization as percentage (0.0 to 1.0)."""

        if self.max_size <= 0:
            return 0.0

        return self.cache_size / self.max_size


# ============================================================================
# Internal Cache Management
# ============================================================================

_embedding_cache: OrderedDict[
    tuple[str, str, int],
    tuple[EmbeddingResult, float],
] = OrderedDict()

_cache_lock = threading.RLock()


def _cache_get(
    key: tuple[str, str, int],
) -> Optional[EmbeddingResult]:
    """
    Retrieve cached embedding if available.

    Parameters
    ----------
    key : tuple[str, str, int]
        Cache key (backend_pref, text, dimensions)

    Returns
    -------
    EmbeddingResult or None
        Cached result if found, None otherwise
    """

    if not CACHE_ENABLED:
        return None

    with _cache_lock:
        entry = _embedding_cache.get(key)

        if entry is None:
            return None

        # LRU behavior: move accessed item to end
        _embedding_cache.move_to_end(key)

        result, _timestamp = entry

        return result


def _cache_set(
    key: tuple[str, str, int],
    result: EmbeddingResult,
) -> None:
    """
    Store embedding result in cache with LRU eviction.

    Parameters
    ----------
    key : tuple[str, str, int]
        Cache key (backend_pref, text, dimensions)
    result : EmbeddingResult
        Embedding result to cache
    """

    if not CACHE_ENABLED:
        return

    with _cache_lock:
        timestamp = time.time()

        _embedding_cache[key] = (result, timestamp)
        _embedding_cache.move_to_end(key)

        # Evict oldest entry if cache exceeds size
        while len(_embedding_cache) > CACHE_SIZE:
            oldest_key, _ = _embedding_cache.popitem(last=False)

            logger.debug(
                "Evicted embedding from cache: %s",
                oldest_key[1][:50],  # Log first 50 chars of text
            )


def clear_embedding_cache() -> None:
    """
    Clear all cached embeddings.

    Raises
    ------
    EmbeddingCacheError
        If cache clear fails unexpectedly
    """

    try:
        with _cache_lock:
            cleared_count = len(_embedding_cache)
            _embedding_cache.clear()

        logger.info(
            "Cleared embedding cache (%d entries removed).",
            cleared_count,
        )

    except Exception as exc:
        logger.exception("Failed to clear embedding cache: %s", exc)

        raise EmbeddingCacheError(
            f"Cache clear failed: {exc}"
        ) from exc


def embedding_cache_size() -> int:
    """
    Get number of embeddings currently in cache.

    Returns
    -------
    int
        Number of cached embeddings
    """

    with _cache_lock:
        return len(_embedding_cache)


def embedding_cache_stats() -> EmbeddingCacheStats:
    """
    Get detailed cache statistics.

    Returns
    -------
    EmbeddingCacheStats
        Cache statistics including size and utilization
    """

    with _cache_lock:
        size = len(_embedding_cache)

    return EmbeddingCacheStats(
        cache_size=size,
        max_size=CACHE_SIZE,
        enabled=CACHE_ENABLED,
    )


# ============================================================================
# Validation Helpers
# ============================================================================


def _normalize_text(text: str) -> str:
    """
    Normalize embedding input without changing semantic meaning.

    - Validates string type
    - Removes leading/trailing whitespace
    - Collapses multiple whitespace
    - Validates text length

    Parameters
    ----------
    text : str
        Text to normalize

    Returns
    -------
    str
        Normalized text

    Raises
    ------
    EmbeddingValidationError
        If text is invalid
    """

    if not isinstance(text, str):
        raise EmbeddingValidationError(
            f"Embedding text must be a string, got {type(text).__name__}."
        )

    text = text.strip()

    if not text:
        raise EmbeddingValidationError(
            "Embedding text cannot be empty or whitespace-only."
        )

    if len(text) > MAX_TEXT_LENGTH:
        raise EmbeddingValidationError(
            f"Embedding text exceeds maximum length of {MAX_TEXT_LENGTH} characters "
            f"(got {len(text)})."
        )

    return _NORMALIZE_PATTERN.sub(" ", text)


def _validate_dimensions(dimensions: int) -> int:
    """
    Validate embedding vector dimensions.

    Parameters
    ----------
    dimensions : int
        Number of dimensions

    Returns
    -------
    int
        Validated dimensions

    Raises
    ------
    EmbeddingValidationError
        If dimensions are invalid
    """

    try:
        dimensions = int(dimensions)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            f"Embedding dimensions must be an integer, got {type(dimensions).__name__}."
        ) from exc

    if dimensions <= 0:
        raise EmbeddingValidationError(
            f"Embedding dimensions must be > 0, got {dimensions}."
        )

    if dimensions > 100_000:
        raise EmbeddingValidationError(
            f"Embedding dimensions too large: {dimensions} (max: 100,000)."
        )

    return dimensions


def _validate_top_k(top_k: int) -> int:
    """
    Validate top-K parameter for ranking.

    Parameters
    ----------
    top_k : int
        Number of top results

    Returns
    -------
    int
        Validated top_k

    Raises
    ------
    EmbeddingValidationError
        If top_k is invalid
    """

    try:
        top_k = int(top_k)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            f"top_k must be an integer, got {type(top_k).__name__}."
        ) from exc

    if top_k < 1:
        raise EmbeddingValidationError(
            f"top_k must be >= 1, got {top_k}."
        )

    return top_k


def _validate_vector(
    vector: Sequence[float],
    *,
    name: str = "vector",
) -> list[float]:
    """
    Validate and convert vector to list of floats.

    - Checks type and length
    - Converts to float
    - Validates finite values

    Parameters
    ----------
    vector : Sequence[float]
        Vector to validate
    name : str
        Variable name for error messages

    Returns
    -------
    list[float]
        Validated vector as list

    Raises
    ------
    EmbeddingValidationError
        If vector contains non-numeric or infinite values
    EmbeddingDimensionError
        If vector is empty
    """

    if not isinstance(vector, (list, tuple)):
        raise EmbeddingValidationError(
            f"{name} must be a list or tuple, got {type(vector).__name__}."
        )

    if not vector:
        raise EmbeddingDimensionError(
            f"{name} cannot be empty."
        )

    result: list[float] = []

    for idx, value in enumerate(vector):
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise EmbeddingValidationError(
                f"{name}[{idx}] is not numeric: {value!r}."
            ) from exc

        if not math.isfinite(number):
            raise EmbeddingValidationError(
                f"{name}[{idx}] is NaN or infinite: {number}."
            )

        result.append(number)

    return result


def _validate_similarity_threshold(threshold: float) -> float:
    """
    Validate similarity threshold value.

    Parameters
    ----------
    threshold : float
        Similarity threshold

    Returns
    -------
    float
        Validated threshold

    Raises
    ------
    EmbeddingValidationError
        If threshold is invalid
    """

    try:
        threshold = float(threshold)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            f"Threshold must be numeric, got {type(threshold).__name__}."
        ) from exc

    if not DEFAULT_MIN_SIMILARITY <= threshold <= DEFAULT_MAX_SIMILARITY:
        raise EmbeddingValidationError(
            f"Threshold must be between {DEFAULT_MIN_SIMILARITY} and "
            f"{DEFAULT_MAX_SIMILARITY}, got {threshold}."
        )

    return threshold


# ============================================================================
# Tokenization
# ============================================================================


def _tokenize(text: str) -> list[str]:
    """
    Tokenize text into words (supports Latin, Bangla, Unicode).

    Parameters
    ----------
    text : str
        Text to tokenize

    Returns
    -------
    list[str]
        List of lowercase tokens
    """

    normalized = _normalize_text(text)

    tokens = [
        token.casefold() for token in _WORD_PATTERN.findall(normalized)
    ]

    logger.debug(
        "Tokenized text into %d token(s).",
        len(tokens),
    )

    return tokens


# ============================================================================
# Local Hashing Embedding
# ============================================================================


def _token_hash(token: str) -> bytes:
    """
    Generate stable SHA-256 hash for a token.

    Parameters
    ----------
    token : str
        Token to hash

    Returns
    -------
    bytes
        32-byte SHA-256 digest
    """

    return hashlib.sha256(token.encode("utf-8")).digest()


def _hashing_embedding(
    text: str,
    dimensions: int = DEFAULT_LOCAL_DIMENSIONS,
) -> list[float]:
    """
    Generate deterministic local embedding using token hashing.

    Process:
    1. Tokenize text into words
    2. Hash each token to bucket index
    3. Accumulate signed contributions
    4. L2 normalize result

    The embedding is fully deterministic and reproducible.

    Parameters
    ----------
    text : str
        Text to embed
    dimensions : int
        Vector dimensions (default: 256)

    Returns
    -------
    list[float]
        L2-normalized embedding vector

    Raises
    ------
    EmbeddingValidationError
        If text or dimensions are invalid
    """

    text = _normalize_text(text)
    dimensions = _validate_dimensions(dimensions)

    vector = [0.0] * dimensions

    tokens = _tokenize(text)

    if not tokens:
        logger.debug("Empty token list after tokenization.")

        return vector

    # Accumulate signed contributions from each token
    for token in tokens:
        digest = _token_hash(token)

        # Use first 8 bytes for bucket selection
        bucket = (
            int.from_bytes(
                digest[:8],
                byteorder="big",
                signed=False,
            )
            % dimensions
        )

        # Deterministic sign based on digest byte
        sign = 1.0 if digest[8] % 2 == 0 else -1.0

        vector[bucket] += sign

    # L2 normalization
    norm = math.sqrt(sum(value * value for value in vector))

    if norm <= 0.0:
        logger.debug("Zero-norm vector after hashing; returning zero vector.")

        return vector

    normalized_vector = [value / norm for value in vector]

    logger.debug(
        "Generated local embedding: %d tokens, norm=%.4f",
        len(tokens),
        norm,
    )

    return normalized_vector


# ============================================================================
# Gemini Embedding API
# ============================================================================


def _gemini_embedding(text: str) -> Optional[list[float]]:
    """
    Generate embedding using Gemini API.

    Gracefully returns None if:
    - API key not configured
    - SDK not installed
    - API call fails

    This allows automatic fallback to local embedding.

    Parameters
    ----------
    text : str
        Text to embed

    Returns
    -------
    list[float] or None
        Embedding vector, or None if unavailable/failed
    """

    # Check API key availability
    if not getattr(secrets, "gemini_api_key", None):
        logger.debug("Gemini API key not configured.")

        return None

    # Check SDK availability
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        logger.debug(
            "google-generativeai SDK not installed; "
            "falling back to local embedding."
        )

        return None

    try:
        genai.configure(api_key=str(secrets.gemini_api_key).strip())

        logger.debug(
            "Calling Gemini embedding API: %s",
            GEMINI_EMBEDDING_MODEL,
        )

        response = genai.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            content=text,
        )

        # Handle both dict and object responses
        if isinstance(response, dict):
            embedding = response.get("embedding")
        else:
            embedding = getattr(response, "embedding", None)

        if embedding is None:
            logger.warning("Gemini returned no embedding vector.")

            return None

        vector = _validate_vector(
            list(embedding),
            name="Gemini embedding",
        )

        logger.info(
            "Successfully generated Gemini embedding: %d dimensions",
            len(vector),
        )

        return vector

    except Exception as exc:
        logger.debug(
            "Gemini embedding failed (fallback to local): %s: %s",
            type(exc).__name__,
            exc,
        )

        return None


# ============================================================================
# Backend Information
# ============================================================================


def gemini_embedding_available() -> bool:
    """
    Check if Gemini embedding backend is available.

    Returns True when:
    - API key is configured
    - google-generativeai SDK is installed

    Returns
    -------
    bool
        True if Gemini embedding can be used
    """

    if not getattr(secrets, "gemini_api_key", None):
        return False

    try:
        import google.generativeai  # noqa: F401
    except ImportError:
        return False

    logger.debug("Gemini embedding backend is available.")

    return True


def local_embedding_available() -> bool:
    """
    Check if local embedding backend is available.

    Local embedding is always available (no dependencies).

    Returns
    -------
    bool
        Always True
    """

    return True


def list_embedding_backends() -> list[EmbeddingBackendInfo]:
    """
    List all available embedding backends with status.

    Returns
    -------
    list[EmbeddingBackendInfo]
        Backend information for all available backends
    """

    backends = [
        EmbeddingBackendInfo(
            name=PROVIDER_GEMINI,
            available=gemini_embedding_available(),
            dimensions=None,  # Gemini has variable dimensions
        ),
        EmbeddingBackendInfo(
            name=PROVIDER_LOCAL,
            available=True,  # Always available
            dimensions=DEFAULT_LOCAL_DIMENSIONS,
        ),
    ]

    logger.debug(
        "Listed embedding backends: %s",
        [b.name for b in backends if b.available],
    )

    return backends


# ============================================================================
# Public Embedding API
# ============================================================================


def embed_text(
    text: str,
    prefer_remote: bool = True,
    dimensions: int = DEFAULT_LOCAL_DIMENSIONS,
) -> EmbeddingResult:
    """
    Generate an embedding for text with automatic fallback.

    Fallback chain:
        1. Gemini API (if prefer_remote=True and available)
        2. Local hashing embedding (always available)

    Results are cached unless CACHE_ENABLED=False.

    Parameters
    ----------
    text : str
        Text to embed
    prefer_remote : bool
        If True, attempt Gemini first (default: True)
    dimensions : int
        Dimensions for local embedding (default: 256)

    Returns
    -------
    EmbeddingResult
        Generated vector with backend information

    Raises
    ------
    EmbeddingValidationError
        If text or dimensions are invalid

    Examples
    --------
    >>> result = embed_text("Hello world")
    >>> print(f"Backend: {result.backend}, Dims: {result.dimensions}")
    Backend: local_hash, Dims: 256
    """

    text = _normalize_text(text)
    dimensions = _validate_dimensions(dimensions)

    # Prepare cache key
    cache_backend = "auto" if prefer_remote else PROVIDER_LOCAL
    cache_key = (cache_backend, text, dimensions)

    # Check cache first
    cached = _cache_get(cache_key)

    if cached is not None:
        logger.debug(
            "Cache hit for embedding: %s backend",
            cached.backend,
        )

        return cached

    # ------------------------------------------------------------------
    # Try Gemini (if preferred)
    # ------------------------------------------------------------------

    if prefer_remote:
        remote_vector = _gemini_embedding(text)

        if remote_vector is not None:
            result = EmbeddingResult(
                vector=remote_vector,
                dimensions=len(remote_vector),
                backend=PROVIDER_GEMINI,
            )

            _cache_set(cache_key, result)

            logger.info(
                "Embedded text with Gemini API: %d dimensions.",
                len(remote_vector),
            )

            return result

    # ------------------------------------------------------------------
    # Fall back to local (always available)
    # ------------------------------------------------------------------

    logger.debug(
        "Falling back to local hashing embedding (prefer_remote=%s).",
        prefer_remote,
    )

    local_vector = _hashing_embedding(text, dimensions=dimensions)

    result = EmbeddingResult(
        vector=local_vector,
        dimensions=len(local_vector),
        backend=PROVIDER_LOCAL,
    )

    _cache_set(cache_key, result)

    logger.info(
        "Embedded text with local hash: %d dimensions.",
        len(local_vector),
    )

    return result


# ============================================================================
# Vector Operations
# ============================================================================


def normalize_vector(vector: Sequence[float]) -> list[float]:
    """
    L2-normalize a vector to unit length.

    Parameters
    ----------
    vector : Sequence[float]
        Vector to normalize

    Returns
    -------
    list[float]
        Normalized vector

    Raises
    ------
    EmbeddingValidationError
        If vector contains non-numeric values
    EmbeddingDimensionError
        If vector is empty
    """

    vector = _validate_vector(vector)

    norm = math.sqrt(sum(value * value for value in vector))

    if norm <= 0.0:
        logger.debug("Zero-norm vector; returning zero vector.")

        return [0.0] * len(vector)

    normalized = [value / norm for value in vector]

    logger.debug("Normalized vector: original_norm=%.4f", norm)

    return normalized


# ============================================================================
# Similarity Calculations
# ============================================================================


def cosine_similarity(
    vec_a: Sequence[float],
    vec_b: Sequence[float],
) -> float:
    """
    Calculate cosine similarity between two vectors.

    Handles dimension mismatch by zero-padding shorter vector.
    Result is approximately in range [-1.0, 1.0].

    Parameters
    ----------
    vec_a : Sequence[float]
        First vector
    vec_b : Sequence[float]
        Second vector

    Returns
    -------
    float
        Cosine similarity score

    Raises
    ------
    EmbeddingValidationError
        If vectors contain non-numeric values
    EmbeddingDimensionError
        If either vector is empty
    """

    if not vec_a or not vec_b:
        logger.debug("One or both vectors empty; returning 0.0 similarity.")

        return 0.0

    a = _validate_vector(vec_a, name="vec_a")
    b = _validate_vector(vec_b, name="vec_b")

    # Handle dimension mismatch
    max_length = max(len(a), len(b))

    if len(a) < max_length:
        a.extend([0.0] * (max_length - len(a)))
        logger.debug("Padded vec_a from %d to %d dimensions.", len(a), max_length)

    if len(b) < max_length:
        b.extend([0.0] * (max_length - len(b)))
        logger.debug("Padded vec_b from %d to %d dimensions.", len(b), max_length)

    # Dot product
    dot = sum(x * y for x, y in zip(a, b))

    # Norms
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a <= 0.0 or norm_b <= 0.0:
        logger.debug(
            "Zero-norm vector(s); returning 0.0 similarity "
            "(norm_a=%.4f, norm_b=%.4f).",
            norm_a,
            norm_b,
        )

        return 0.0

    # Cosine similarity with bounds protection
    score = dot / (norm_a * norm_b)

    # Protect against tiny floating-point overshoots
    score = max(
        DEFAULT_MIN_SIMILARITY,
        min(DEFAULT_MAX_SIMILARITY, score),
    )

    logger.debug(
        "Computed cosine similarity: %.4f "
        "(dot=%.4f, norm_a=%.4f, norm_b=%.4f)",
        score,
        dot,
        norm_a,
        norm_b,
    )

    return score


# ============================================================================
# Similarity Ranking
# ============================================================================


def rank_by_similarity(
    query: str,
    candidates: list[tuple[str, list[float]]],
    top_k: int = DEFAULT_TOP_K,
    prefer_remote: bool = True,
    min_score: Optional[float] = None,
) -> list[tuple[str, float]]:
    """
    Rank candidate texts by semantic similarity to query.

    Sorting is stable: by score descending, then by original index ascending.

    Parameters
    ----------
    query : str
        Search query text
    candidates : list[tuple[str, list[float]]]
        List of (text, embedding) tuples
    top_k : int
        Maximum results to return (default: 5)
    prefer_remote : bool
        Prefer Gemini for query embedding (default: True)
    min_score : float or None
        Minimum similarity threshold (default: None)

    Returns
    -------
    list[tuple[str, float]]
        Sorted (text, score) pairs, up to top_k results

    Raises
    ------
    EmbeddingValidationError
        If query or min_score are invalid

    Examples
    --------
    >>> candidates = [
    ...     ("Hello world", [0.1, 0.2, ...]),
    ...     ("Goodbye world", [0.15, 0.25, ...]),
    ... ]
    >>> results = rank_by_similarity("Hi world", candidates)
    >>> for text, score in results:
    ...     print(f"{text}: {score:.3f}")
    """

    query = _normalize_text(query)
    top_k = _validate_top_k(top_k)

    if not candidates:
        logger.debug("Empty candidates list; returning empty results.")

        return []

    if len(candidates) > MAX_CANDIDATES:
        logger.warning(
            "Candidate list has %d items; limiting to %d.",
            len(candidates),
            MAX_CANDIDATES,
        )

        candidates = candidates[:MAX_CANDIDATES]

    if min_score is not None:
        min_score = _validate_similarity_threshold(min_score)

    # Get query embedding
    query_result = embed_text(
        query,
        prefer_remote=prefer_remote,
    )

    logger.info(
        "Ranking %d candidate(s) by similarity to query (%s backend).",
        len(candidates),
        query_result.backend,
    )

    scored: list[SimilarityResult] = []

    for index, candidate in enumerate(candidates):
        # Validate candidate format
        if not isinstance(candidate, tuple) or len(candidate) != 2:
            logger.debug(
                "Skipping malformed candidate at index %d: expected tuple of 2.",
                index,
            )

            continue

        text, candidate_vector = candidate

        # Validate text
        if not isinstance(text, str) or not text.strip():
            logger.debug("Skipping candidate at index %d: empty text.", index)

            continue

        # Calculate similarity
        try:
            score = cosine_similarity(
                query_result.vector,
                candidate_vector,
            )
        except EmbeddingError as exc:
            logger.debug(
                "Skipping candidate at index %d: invalid vector: %s",
                index,
                exc,
            )

            continue

        # Apply minimum score filter
        if min_score is not None and score < min_score:
            logger.debug(
                "Filtering candidate at index %d: score %.4f < min_score %.4f",
                index,
                score,
                min_score,
            )

            continue

        scored.append(
            SimilarityResult(
                text=text,
                score=score,
                index=index,
            )
        )

    # Stable sort: score descending, index ascending
    scored.sort(key=lambda item: (-item.score, item.index))

    results = [(item.text, item.score) for item in scored[:top_k]]

    logger.info(
        "Ranked results: %d items returned (top_%d from %d candidates).",
        len(results),
        top_k,
        len(candidates),
    )

    return results


# ============================================================================
# Advanced Ranking API
# ============================================================================


def rank_results(
    query: str,
    candidates: Iterable[tuple[str, Sequence[float]]],
    top_k: int = DEFAULT_TOP_K,
    prefer_remote: bool = True,
    min_score: Optional[float] = None,
) -> list[SimilarityResult]:
    """
    Advanced ranking that returns typed SimilarityResult objects.

    Parameters
    ----------
    query : str
        Search query
    candidates : Iterable[tuple[str, Sequence[float]]]
        Iterator of (text, embedding) tuples
    top_k : int
        Maximum results (default: 5)
    prefer_remote : bool
        Prefer Gemini backend (default: True)
    min_score : float or None
        Minimum similarity threshold

    Returns
    -------
    list[SimilarityResult]
        Ranked results with typed similarity scores

    Raises
    ------
    EmbeddingValidationError
        If query or parameters are invalid
    """

    query = _normalize_text(query)
    top_k = _validate_top_k(top_k)

    candidate_list = list(candidates)

    logger.info(
        "Advanced ranking: %d candidate(s), top_%d",
        len(candidate_list),
        top_k,
    )

    if not candidate_list:
        return []

    query_vector = embed_text(
        query,
        prefer_remote=prefer_remote,
    ).vector

    results: list[SimilarityResult] = []

    for index, candidate in enumerate(candidate_list):
        if len(candidate) != 2:
            logger.debug(
                "Skipping malformed candidate at index %d.",
                index,
            )

            continue

        text, vector = candidate

        if not isinstance(text, str) or not text.strip():
            continue

        try:
            score = cosine_similarity(query_vector, vector)
        except EmbeddingError as exc:
            logger.debug(
                "Skipping candidate at index %d: %s",
                index,
                exc,
            )

            continue

        if min_score is not None and score < min_score:
            continue

        results.append(
            SimilarityResult(
                text=text,
                score=score,
                index=index,
            )
        )

    results.sort(key=lambda item: (-item.score, item.index))

    return results[:top_k]


# ============================================================================
# Comparison Helpers
# ============================================================================


def embedding_similarity(
    text_a: str,
    text_b: str,
    prefer_remote: bool = True,
) -> float:
    """
    Generate embeddings for two texts and compute similarity.

    Parameters
    ----------
    text_a : str
        First text
    text_b : str
        Second text
    prefer_remote : bool
        Prefer Gemini backend (default: True)

    Returns
    -------
    float
        Cosine similarity score

    Raises
    ------
    EmbeddingValidationError
        If text inputs are invalid
    """

    embedding_a = embed_text(text_a, prefer_remote=prefer_remote)
    embedding_b = embed_text(text_b, prefer_remote=prefer_remote)

    score = cosine_similarity(
        embedding_a.vector,
        embedding_b.vector,
    )

    logger.info(
        "Compared texts: similarity=%.4f (backends: %s, %s)",
        score,
        embedding_a.backend,
        embedding_b.backend,
    )

    return score


def is_semantically_similar(
    text_a: str,
    text_b: str,
    threshold: float = 0.75,
    prefer_remote: bool = True,
) -> bool:
    """
    Check if two texts are semantically similar above threshold.

    Parameters
    ----------
    text_a : str
        First text
    text_b : str
        Second text
    threshold : float
        Similarity threshold (default: 0.75)
    prefer_remote : bool
        Prefer Gemini backend (default: True)

    Returns
    -------
    bool
        True if similarity >= threshold

    Raises
    ------
    EmbeddingValidationError
        If inputs are invalid
    """

    threshold = _validate_similarity_threshold(threshold)

    score = embedding_similarity(
        text_a,
        text_b,
        prefer_remote=prefer_remote,
    )

    result = score >= threshold

    logger.info(
        "Semantic similarity check: %s (score=%.4f, threshold=%.4f)",
        result,
        score,
        threshold,
    )

    return result


# ============================================================================
# Diagnostics
# ============================================================================


def embedding_diagnostics() -> dict:
    """
    Get comprehensive embedding system diagnostics.

    Returns
    -------
    dict
        Diagnostics including backend availability, cache stats, etc.
    """

    backends = list_embedding_backends()
    cache_stats = embedding_cache_stats()

    diagnostics_dict = {
        "gemini_available": gemini_embedding_available(),
        "local_available": local_embedding_available(),
        "default_local_dimensions": DEFAULT_LOCAL_DIMENSIONS,
        "gemini_model": GEMINI_EMBEDDING_MODEL,
        "cache_enabled": CACHE_ENABLED,
        "cache_size": cache_stats.cache_size,
        "cache_max_size": cache_stats.max_size,
        "cache_utilization": cache_stats.utilization,
        "backends": [
            {
                "name": backend.name,
                "available": backend.available,
                "dimensions": backend.dimensions,
            }
            for backend in backends
        ],
    }

    logger.debug(
        "Embedding diagnostics: %d backends, cache %.1f%% full",
        len(backends),
        cache_stats.utilization * 100,
    )

    return diagnostics_dict


# ============================================================================
# Backward-Compatible Aliases
# ============================================================================

# Legacy function names for compatibility
embedding = embed_text
similarity = cosine_similarity
search_similar = rank_by_similarity


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    # Dataclasses
    "EmbeddingResult",
    "SimilarityResult",
    "EmbeddingBackendInfo",
    "EmbeddingCacheStats",

    # Exceptions
    "EmbeddingError",
    "EmbeddingValidationError",
    "EmbeddingBackendError",
    "EmbeddingDimensionError",
    "EmbeddingCacheError",

    # Constants
    "PROVIDER_GEMINI",
    "PROVIDER_LOCAL",
    "DEFAULT_LOCAL_DIMENSIONS",
    "DEFAULT_TOP_K",
    "GEMINI_EMBEDDING_MODEL",

    # Embedding generation
    "embed_text",
    "embedding",  # Alias

    # Backend checking
    "local_embedding_available",
    "gemini_embedding_available",
    "list_embedding_backends",

    # Vector operations
    "normalize_vector",
    "cosine_similarity",
    "similarity",  # Alias

    # Ranking/search
    "rank_by_similarity",
    "rank_results",
    "search_similar",  # Alias

    # Comparison helpers
    "embedding_similarity",
    "is_semantically_similar",

    # Cache management
    "clear_embedding_cache",
    "embedding_cache_size",
    "embedding_cache_stats",

    # Diagnostics
    "embedding_diagnostics",

    # Internal (kept for compatibility)
    "_hashing_embedding",
    "_gemini_embedding",
    "_tokenize",
]
