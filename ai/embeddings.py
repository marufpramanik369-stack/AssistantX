"""
embeddings.py
=============
Provides text embedding generation and simple vector-similarity search,
used by core/memory.py to retrieve the most relevant long-term memories
for the current conversation context (rather than dumping all memories
into every prompt).

Two backends are supported, resolved automatically:
    1. Gemini's embedding API (if configured) — higher quality.
    2. A local hashing-based fallback embedding — zero dependencies,
       lower quality but keeps semantic search functional offline.

Design goal: never hard-fail. If no proper embedding backend is
available, callers still get *a* vector (from the fallback), so memory
search degrades gracefully rather than crashing.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Optional

from config.secrets import secrets

logger = logging.getLogger(__name__)

_FALLBACK_DIMENSIONS = 256
_WORD_PATTERN = re.compile(r"[a-zA-Z\u0980-\u09FF]+", re.UNICODE)  # Latin + Bangla script


@dataclass
class EmbeddingResult:
    vector: list[float]
    dimensions: int
    backend: str


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_PATTERN.findall(text)]


def _hashing_embedding(text: str, dimensions: int = _FALLBACK_DIMENSIONS) -> list[float]:
    """
    Deterministic, dependency-free "bag of hashed words" embedding.

    Each token is hashed into a bucket in a fixed-size vector; the vector
    is then L2-normalized. This is a well-known cheap trick (the
    "hashing trick") that captures rough lexical overlap between texts
    without needing a real embedding model — good enough for approximate
    memory retrieval when no API is available.
    """
    vector = [0.0] * dimensions
    tokens = _tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        bucket = int(digest, 16) % dimensions
        sign = 1.0 if int(digest[:2], 16) % 2 == 0 else -1.0
        vector[bucket] += sign

    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _gemini_embedding(text: str) -> Optional[list[float]]:
    """Attempt to use Gemini's embedding endpoint; returns None on any failure."""
    if not secrets.gemini_api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=secrets.gemini_api_key)
        response = genai.embed_content(model="models/text-embedding-004", content=text)
        return list(response["embedding"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gemini embedding unavailable, using fallback: %s", exc)
        return None


def embed_text(text: str, prefer_remote: bool = True) -> EmbeddingResult:
    """
    Generate an embedding vector for the given text.

    Args:
        text: The text to embed.
        prefer_remote: If True (default), tries the Gemini embedding API
            first and only falls back to the local hashing embedding on
            failure. Set False to force the offline fallback (useful for
            tests, or to keep memory search fully local).

    Returns:
        An EmbeddingResult with the vector and which backend produced it.
    """
    if prefer_remote:
        remote_vector = _gemini_embedding(text)
        if remote_vector is not None:
            return EmbeddingResult(vector=remote_vector, dimensions=len(remote_vector), backend="gemini")

    local_vector = _hashing_embedding(text)
    return EmbeddingResult(vector=local_vector, dimensions=len(local_vector), backend="local_hash")


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors of potentially
    different lengths (shorter one is zero-padded) — guards against
    mixing embeddings from different backends/dimensions gracefully,
    though callers should generally avoid comparing across backends.
    """
    if not vec_a or not vec_b:
        return 0.0

    length = max(len(vec_a), len(vec_b))
    a = vec_a + [0.0] * (length - len(vec_a))
    b = vec_b + [0.0] * (length - len(vec_b))

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def rank_by_similarity(
    query: str,
    candidates: list[tuple[str, list[float]]],
    top_k: int = 5,
    prefer_remote: bool = True,
) -> list[tuple[str, float]]:
    """
    Rank a list of (text, precomputed_embedding) candidates by similarity
    to the query, returning the top_k (text, score) pairs in descending
    order of relevance.

    Used by core/memory.py to select which stored memories are most
    relevant to inject into the current prompt.
    """
    query_vector = embed_text(query, prefer_remote=prefer_remote).vector

    scored = [
        (text, cosine_similarity(query_vector, candidate_vector))
        for text, candidate_vector in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]
    