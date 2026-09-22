"""
ai/embeddings.py
================
Text embeddings and semantic similarity utilities for AssistantX.

Backends
--------
1. Gemini embedding API
   - Higher semantic quality
   - Requires google-generativeai + Gemini API key

2. Local hashing embedding
   - Dependency-free
   - Fully offline
   - Deterministic
   - Useful as a graceful fallback

Design goals
------------
- Never hard-fail during normal embedding generation
- Automatic remote -> local fallback
- Deterministic local embeddings
- Safe vector validation
- Dimension-aware similarity
- Optional embedding cache
- Simple semantic ranking for core/memory.py
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from config.secrets import secrets

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

PROVIDER_GEMINI = "gemini"
PROVIDER_LOCAL = "local_hash"

DEFAULT_LOCAL_DIMENSIONS = 256
DEFAULT_TOP_K = 5

MAX_TEXT_LENGTH = 20_000
MAX_CANDIDATES = 10_000

CACHE_ENABLED = True
CACHE_SIZE = 512

GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"

# Latin + Bangla + numbers/Unicode letters.
_WORD_PATTERN = re.compile(
    r"[^\W_]+",
    re.UNICODE,
)

# Common separators that should behave like whitespace.
_NORMALIZE_PATTERN = re.compile(r"\s+")


# ============================================================================
# Exceptions
# ============================================================================


class EmbeddingError(RuntimeError):
    """Base exception for embedding-related errors."""


class EmbeddingValidationError(EmbeddingError):
    """Raised when embedding input is invalid."""


class EmbeddingBackendError(EmbeddingError):
    """Raised when a specific embedding backend fails."""


class EmbeddingDimensionError(EmbeddingError):
    """Raised when vector dimensions are invalid."""


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """
    Result returned by embed_text().
    """

    vector: list[float]
    dimensions: int
    backend: str

    @property
    def is_local(self) -> bool:
        return self.backend == PROVIDER_LOCAL

    @property
    def is_remote(self) -> bool:
        return self.backend == PROVIDER_GEMINI


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """
    Similarity result for one candidate.
    """

    text: str
    score: float
    index: int = 0


@dataclass(frozen=True, slots=True)
class EmbeddingBackendInfo:
    """
    Information about an embedding backend.
    """

    name: str
    available: bool
    dimensions: int | None = None


# ============================================================================
# Internal cache
# ============================================================================


_embedding_cache: OrderedDict[
    tuple[str, str, int],
    EmbeddingResult,
] = OrderedDict()

_cache_lock = threading.RLock()


def _cache_get(
    key: tuple[str, str, int],
) -> EmbeddingResult | None:

    if not CACHE_ENABLED:
        return None

    with _cache_lock:
        result = _embedding_cache.get(key)

        if result is None:
            return None

        # LRU behavior.
        _embedding_cache.move_to_end(key)

        return result


def _cache_set(
    key: tuple[str, str, int],
    result: EmbeddingResult,
) -> None:

    if not CACHE_ENABLED:
        return

    with _cache_lock:
        _embedding_cache[key] = result
        _embedding_cache.move_to_end(key)

        while len(_embedding_cache) > CACHE_SIZE:
            _embedding_cache.popitem(last=False)


def clear_embedding_cache() -> None:
    """Clear all cached embeddings."""

    with _cache_lock:
        _embedding_cache.clear()


def embedding_cache_size() -> int:
    """Return the current number of cached embeddings."""

    with _cache_lock:
        return len(_embedding_cache)


# ============================================================================
# Validation helpers
# ============================================================================


def _normalize_text(text: str) -> str:
    """
    Normalize embedding input without changing its meaning.
    """

    if not isinstance(text, str):
        raise EmbeddingValidationError(
            "Embedding text must be a string."
        )

    text = text.strip()

    if not text:
        raise EmbeddingValidationError(
            "Embedding text cannot be empty."
        )

    if len(text) > MAX_TEXT_LENGTH:
        raise EmbeddingValidationError(
            f"Embedding text is too long. "
            f"Maximum length: {MAX_TEXT_LENGTH} characters."
        )

    return _NORMALIZE_PATTERN.sub(" ", text)


def _validate_dimensions(dimensions: int) -> int:
    try:
        dimensions = int(dimensions)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            "Embedding dimensions must be an integer."
        ) from exc

    if dimensions <= 0:
        raise EmbeddingValidationError(
            "Embedding dimensions must be greater than zero."
        )

    if dimensions > 100_000:
        raise EmbeddingValidationError(
            "Embedding dimensions are too large."
        )

    return dimensions


def _validate_top_k(top_k: int) -> int:
    try:
        top_k = int(top_k)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            "top_k must be an integer."
        ) from exc

    if top_k < 1:
        raise EmbeddingValidationError(
            "top_k must be at least 1."
        )

    return top_k


def _validate_vector(
    vector: Sequence[float],
    *,
    name: str = "vector",
) -> list[float]:

    if not isinstance(vector, (list, tuple)):
        raise EmbeddingValidationError(
            f"{name} must be a list or tuple of numbers."
        )

    if not vector:
        raise EmbeddingDimensionError(
            f"{name} cannot be empty."
        )

    result: list[float] = []

    for value in vector:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise EmbeddingValidationError(
                f"{name} contains a non-numeric value."
            ) from exc

        if not math.isfinite(number):
            raise EmbeddingValidationError(
                f"{name} contains NaN or infinite values."
            )

        result.append(number)

    return result


# ============================================================================
# Tokenization
# ============================================================================


def _tokenize(text: str) -> list[str]:
    """
    Tokenize Latin, Bangla and other Unicode word characters.
    """

    normalized = _normalize_text(text)

    return [
        token.casefold()
        for token in _WORD_PATTERN.findall(normalized)
    ]


# ============================================================================
# Local hashing embedding
# ============================================================================


def _token_hash(token: str) -> bytes:
    """
    Generate a stable SHA-256 digest for a token.
    """

    return hashlib.sha256(
        token.encode("utf-8")
    ).digest()


def _hashing_embedding(
    text: str,
    dimensions: int = DEFAULT_LOCAL_DIMENSIONS,
) -> list[float]:
    """
    Generate a deterministic local hashing embedding.

    Uses signed hashing so collisions do not always reinforce each other.
    """

    text = _normalize_text(text)
    dimensions = _validate_dimensions(dimensions)

    vector = [0.0] * dimensions

    tokens = _tokenize(text)

    if not tokens:
        return vector

    for token in tokens:
        digest = _token_hash(token)

        # Use the first 8 bytes for bucket selection.
        bucket = (
            int.from_bytes(
                digest[:8],
                byteorder="big",
                signed=False,
            )
            % dimensions
        )

        # Deterministic sign.
        sign = 1.0 if digest[8] % 2 == 0 else -1.0

        vector[bucket] += sign

    # L2 normalize.
    norm = math.sqrt(
        sum(value * value for value in vector)
    )

    if norm <= 0.0:
        return vector

    return [
        value / norm
        for value in vector
    ]


# ============================================================================
# Gemini embedding
# ============================================================================


def _gemini_embedding(
    text: str,
) -> list[float] | None:
    """
    Try to generate a Gemini embedding.

    Returns None when Gemini is unavailable or fails, allowing
    the caller to use the local fallback.
    """

    if not getattr(secrets, "gemini_api_key", None):
        return None

    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        logger.debug(
            "Gemini SDK is not installed."
        )
        return None

    try:
        genai.configure(
            api_key=str(
                secrets.gemini_api_key
            ).strip()
        )

        response = genai.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            content=text,
        )

        # Current SDK commonly returns:
        # {"embedding": [...]}
        if isinstance(response, dict):
            embedding = response.get("embedding")
        else:
            embedding = getattr(
                response,
                "embedding",
                None,
            )

        if embedding is None:
            logger.warning(
                "Gemini returned no embedding vector."
            )
            return None

        vector = _validate_vector(
            list(embedding),
            name="Gemini embedding",
        )

        return vector

    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Gemini embedding failed; using local fallback: %s",
            exc,
        )
        return None


# ============================================================================
# Backend information
# ============================================================================


def gemini_embedding_available() -> bool:
    """
    Return True when Gemini embedding can potentially be used.
    """

    if not getattr(secrets, "gemini_api_key", None):
        return False

    try:
        import google.generativeai  # noqa: F401
    except ImportError:
        return False

    return True


def local_embedding_available() -> bool:
    """
    Local hashing embedding is always available.
    """

    return True


def list_embedding_backends() -> list[EmbeddingBackendInfo]:
    """
    Return available embedding backends.
    """

    return [
        EmbeddingBackendInfo(
            name=PROVIDER_GEMINI,
            available=gemini_embedding_available(),
        ),
        EmbeddingBackendInfo(
            name=PROVIDER_LOCAL,
            available=True,
            dimensions=DEFAULT_LOCAL_DIMENSIONS,
        ),
    ]


# ============================================================================
# Public embedding API
# ============================================================================


def embed_text(
    text: str,
    prefer_remote: bool = True,
    dimensions: int = DEFAULT_LOCAL_DIMENSIONS,
) -> EmbeddingResult:
    """
    Generate an embedding for text.

    Parameters
    ----------
    text:
        Text to embed.

    prefer_remote:
        If True, Gemini is attempted first.

    dimensions:
        Dimension used by the local hashing backend.

    Returns
    -------
    EmbeddingResult
        Generated vector and backend information.

    Notes
    -----
    If Gemini fails, this function automatically falls back to the
    local hashing embedding.
    """

    text = _normalize_text(text)
    dimensions = _validate_dimensions(dimensions)

    cache_backend = (
        "auto"
        if prefer_remote
        else PROVIDER_LOCAL
    )

    cache_key = (
        cache_backend,
        text,
        dimensions,
    )

    cached = _cache_get(cache_key)

    if cached is not None:
        return cached

    # ------------------------------------------------------------------
    # Gemini
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

            return result

    # ------------------------------------------------------------------
    # Local fallback
    # ------------------------------------------------------------------

    local_vector = _hashing_embedding(
        text,
        dimensions=dimensions,
    )

    result = EmbeddingResult(
        vector=local_vector,
        dimensions=len(local_vector),
        backend=PROVIDER_LOCAL,
    )

    _cache_set(cache_key, result)

    return result


# ============================================================================
# Vector normalization
# ============================================================================


def normalize_vector(
    vector: Sequence[float],
) -> list[float]:
    """
    L2-normalize a vector.
    """

    vector = _validate_vector(vector)

    norm = math.sqrt(
        sum(value * value for value in vector)
    )

    if norm <= 0.0:
        return [0.0] * len(vector)

    return [
        value / norm
        for value in vector
    ]


# ============================================================================
# Cosine similarity
# ============================================================================


def cosine_similarity(
    vec_a: Sequence[float],
    vec_b: Sequence[float],
) -> float:
    """
    Calculate cosine similarity between two vectors.

    If dimensions differ, the shorter vector is zero-padded.
    This preserves backward compatibility with mixed stored vectors.

    Returns
    -------
    float
        Similarity from approximately -1.0 to 1.0.
    """

    if not vec_a or not vec_b:
        return 0.0

    a = _validate_vector(
        vec_a,
        name="vec_a",
    )

    b = _validate_vector(
        vec_b,
        name="vec_b",
    )

    length = max(
        len(a),
        len(b),
    )

    if len(a) < length:
        a.extend([0.0] * (length - len(a)))

    if len(b) < length:
        b.extend([0.0] * (length - len(b)))

    dot = sum(
        x * y
        for x, y in zip(a, b)
    )

    norm_a = math.sqrt(
        sum(x * x for x in a)
    )

    norm_b = math.sqrt(
        sum(y * y for y in b)
    )

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    score = dot / (norm_a * norm_b)

    # Protect against tiny floating-point overshoots.
    return max(
        -1.0,
        min(1.0, score),
    )


# ============================================================================
# Similarity ranking
# ============================================================================


def rank_by_similarity(
    query: str,
    candidates: list[tuple[str, list[float]]],
    top_k: int = DEFAULT_TOP_K,
    prefer_remote: bool = True,
    min_score: float | None = None,
) -> list[tuple[str, float]]:
    """
    Rank candidate texts by cosine similarity.

    Parameters
    ----------
    query:
        Search query.

    candidates:
        List of:
            (text, embedding)

    top_k:
        Maximum number of results.

    prefer_remote:
        Whether Gemini should be preferred for the query embedding.

    min_score:
        Optional minimum similarity score.

    Returns
    -------
    list[tuple[str, float]]
        Sorted (text, score) pairs.
    """

    query = _normalize_text(query)
    top_k = _validate_top_k(top_k)

    if not candidates:
        return []

    if len(candidates) > MAX_CANDIDATES:
        logger.warning(
            "Candidate list contains %d items; limiting to %d.",
            len(candidates),
            MAX_CANDIDATES,
        )
        candidates = candidates[:MAX_CANDIDATES]

    if min_score is not None:
        try:
            min_score = float(min_score)
        except (TypeError, ValueError) as exc:
            raise EmbeddingValidationError(
                "min_score must be a number."
            ) from exc

        if not -1.0 <= min_score <= 1.0:
            raise EmbeddingValidationError(
                "min_score must be between -1.0 and 1.0."
            )

    query_result = embed_text(
        query,
        prefer_remote=prefer_remote,
    )

    scored: list[SimilarityResult] = []

    for index, candidate in enumerate(candidates):

        if not isinstance(candidate, tuple) or len(candidate) != 2:
            logger.debug(
                "Skipping malformed embedding candidate at index %d.",
                index,
            )
            continue

        text, candidate_vector = candidate

        if not isinstance(text, str) or not text.strip():
            continue

        try:
            score = cosine_similarity(
                query_result.vector,
                candidate_vector,
            )
        except EmbeddingError as exc:
            logger.debug(
                "Skipping invalid candidate at index %d: %s",
                index,
                exc,
            )
            continue

        if min_score is not None and score < min_score:
            continue

        scored.append(
            SimilarityResult(
                text=text,
                score=score,
                index=index,
            )
        )

    # Stable deterministic sorting:
    # score descending, original index ascending.
    scored.sort(
        key=lambda item: (
            -item.score,
            item.index,
        )
    )

    return [
        (item.text, item.score)
        for item in scored[:top_k]
    ]


# ============================================================================
# Advanced ranking API
# ============================================================================


def rank_results(
    query: str,
    candidates: Iterable[tuple[str, Sequence[float]]],
    top_k: int = DEFAULT_TOP_K,
    prefer_remote: bool = True,
    min_score: float | None = None,
) -> list[SimilarityResult]:
    """
    Advanced version of rank_by_similarity() that returns SimilarityResult.
    """

    query = _normalize_text(query)
    top_k = _validate_top_k(top_k)

    candidate_list = list(candidates)

    query_vector = embed_text(
        query,
        prefer_remote=prefer_remote,
    ).vector

    results: list[SimilarityResult] = []

    for index, candidate in enumerate(candidate_list):
        if len(candidate) != 2:
            continue

        text, vector = candidate

        if not isinstance(text, str) or not text.strip():
            continue

        try:
            score = cosine_similarity(
                query_vector,
                vector,
            )
        except EmbeddingError:
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

    results.sort(
        key=lambda item: (
            -item.score,
            item.index,
        )
    )

    return results[:top_k]


# ============================================================================
# Embedding comparison helpers
# ============================================================================


def embedding_similarity(
    text_a: str,
    text_b: str,
    prefer_remote: bool = True,
) -> float:
    """
    Generate embeddings for two texts and compare them.
    """

    embedding_a = embed_text(
        text_a,
        prefer_remote=prefer_remote,
    )

    embedding_b = embed_text(
        text_b,
        prefer_remote=prefer_remote,
    )

    return cosine_similarity(
        embedding_a.vector,
        embedding_b.vector,
    )


def is_semantically_similar(
    text_a: str,
    text_b: str,
    threshold: float = 0.75,
    prefer_remote: bool = True,
) -> bool:
    """
    Return True when two texts meet the similarity threshold.
    """

    try:
        threshold = float(threshold)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            "threshold must be a number."
        ) from exc

    if not -1.0 <= threshold <= 1.0:
        raise EmbeddingValidationError(
            "threshold must be between -1.0 and 1.0."
        )

    score = embedding_similarity(
        text_a,
        text_b,
        prefer_remote=prefer_remote,
    )

    return score >= threshold


# ============================================================================
# Diagnostics
# ============================================================================


def embedding_diagnostics() -> dict:
    """
    Return JSON-friendly embedding diagnostics.
    """

    backends = list_embedding_backends()

    return {
        "gemini_available": gemini_embedding_available(),
        "local_available": local_embedding_available(),
        "default_local_dimensions": DEFAULT_LOCAL_DIMENSIONS,
        "gemini_model": GEMINI_EMBEDDING_MODEL,
        "cache_enabled": CACHE_ENABLED,
        "cache_size": embedding_cache_size(),
        "backends": [
            {
                "name": backend.name,
                "available": backend.available,
                "dimensions": backend.dimensions,
            }
            for backend in backends
        ],
    }


# ============================================================================
# Backward-compatible aliases
# ============================================================================


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

    # Exceptions
    "EmbeddingError",
    "EmbeddingValidationError",
    "EmbeddingBackendError",
    "EmbeddingDimensionError",

    # Constants
    "PROVIDER_GEMINI",
    "PROVIDER_LOCAL",
    "DEFAULT_LOCAL_DIMENSIONS",
    "DEFAULT_TOP_K",
    "GEMINI_EMBEDDING_MODEL",

    # Embedding
    "embed_text",
    "embedding",

    # Local
    "local_embedding_available",

    # Gemini
    "gemini_embedding_available",

    # Vector
    "normalize_vector",
    "cosine_similarity",
    "similarity",

    # Search / ranking
    "rank_by_similarity",
    "rank_results",
    "search_similar",

    # Comparison
    "embedding_similarity",
    "is_semantically_similar",

    # Cache
    "clear_embedding_cache",
    "embedding_cache_size",

    # Diagnostics
    "list_embedding_backends",
    "embedding_diagnostics",

    # Internal helper kept for compatibility
    "_hashing_embedding",
    "_gemini_embedding",
    "_tokenize",
]
