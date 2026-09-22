"""
wikipedia_service.py
=====================
Encyclopedia lookups via Wikipedia's public REST API
(https://en.wikipedia.org/api/rest_v1/) — no API key required, since
Wikipedia's content API is fully open. Handles the common "who/what is
X" voice query pattern: search for the best-matching article title,
then fetch a concise summary suitable for speech.

Two-step lookup:
    1. Search (opensearch API) — resolves a loosely-phrased query
       ("einstein", "eiffel tower") to the canonical article title,
       tolerating typos and partial names.
    2. Summary (REST v1 /page/summary/{title}) — fetches a short,
       pre-generated extract plus the canonical URL and thumbnail,
       avoiding the need to parse full wikitext/HTML ourselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config.constants import (
    HTTP_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
    WIKIPEDIA_SENTENCES,
)
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_HOURS = 24  # encyclopedia content changes slowly; cache generously
_OPENSEARCH_URL_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"
_SUMMARY_URL_TEMPLATE = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"

_DISAMBIGUATION_TYPE = "disambiguation"


class WikipediaServiceError(RuntimeError):
    """Raised when a Wikipedia lookup fails or no matching article exists."""


class DisambiguationError(WikipediaServiceError):
    """
    Raised when the resolved title is a disambiguation page (multiple
    distinct topics share the name, e.g. "Mercury" the planet vs. the
    element vs. the Roman god). Carries the list of candidate options
    so the caller (brain/decision_engine.py) can ask the user to
    clarify rather than guessing.
    """

    def __init__(self, query: str, options: list[str]) -> None:
        self.query = query
        self.options = options
        super().__init__(
            f"'{query}' could refer to multiple things: {', '.join(options[:5])}."
        )


@dataclass
class WikipediaSummary:
    title: str
    extract: str
    url: str
    thumbnail_url: str | None = None

    def to_speech(self, max_sentences: int = WIKIPEDIA_SENTENCES) -> str:
        """Return a speech-friendly excerpt limited to the first N sentences,
        so voice responses don't run on for a full paragraph unless asked."""
        sentences = self._split_sentences(self.extract)
        excerpt = " ".join(sentences[:max_sentences])
        return excerpt or self.extract

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """
        Lightweight sentence splitter — good enough for Wikipedia's
        clean, well-punctuated summary text without pulling in a full
        NLP sentence tokenizer for this one use case.
        """
        import re

        # Avoid splitting on abbreviations like "U.S." by requiring the
        # period to be followed by whitespace and a capital letter/end.
        raw_sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9]|$)", text.strip())
        return [s for s in raw_sentences if s]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "extract": self.extract,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WikipediaSummary:
        return cls(**data)


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise WikipediaServiceError(
            "Wikipedia lookups require the 'requests' package. Run: pip install requests"
        ) from exc


def _cache_key(prefix: str, query: str, lang: str) -> str:
    return f"wikipedia:{prefix}:{lang}:{query.strip().lower()}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)).isoformat()


def _try_get_cached(cache_key: str):
    try:
        from database import db_manager

        return db_manager.get_cache(cache_key)
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization, never fatal
        logger.debug("Wikipedia cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(cache_key: str, value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(cache_key, value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write Wikipedia cache (%s); continuing without caching.", exc)


def resolve_title(query: str, lang: str = "en", limit: int = 5) -> list[str]:
    """
    Resolve a loosely-phrased query into candidate Wikipedia article
    titles, using the OpenSearch API (tolerant of partial names and
    minor misspellings via Wikipedia's own search relevance ranking).

    Returns:
        A list of candidate titles, best match first. Empty if nothing
        matched.
    """
    requests = _get_requests()
    url = _OPENSEARCH_URL_TEMPLATE.format(lang=lang)

    try:
        response = requests.get(
            url,
            params={
                "action": "opensearch",
                "search": query,
                "limit": limit,
                "namespace": 0,
                "format": "json",
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WikipediaServiceError(f"Wikipedia search request failed: {exc}") from exc

    data = response.json()
    # OpenSearch response format: [query, [titles], [descriptions], [urls]]
    return data[1] if len(data) > 1 else []


def get_summary(query: str, lang: str = "en") -> WikipediaSummary:
    """
    Look up a topic and return a concise summary.

    Performs a two-step lookup: resolve the best-matching article title
    via search, then fetch its summary extract. Raises
    DisambiguationError (rather than guessing) if the resolved article
    is itself a disambiguation page listing multiple distinct topics.

    Raises:
        WikipediaServiceError: if no matching article is found or the
            request fails.
        DisambiguationError: if the query is ambiguous between multiple
            distinct topics — carries `.options` with the candidates.
    """
    query = query.strip()
    if not query:
        raise WikipediaServiceError("Empty Wikipedia query.")

    cache_key = _cache_key("summary", query, lang)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        if cached.get("_disambiguation"):
            raise DisambiguationError(query, cached["options"])
        return WikipediaSummary.from_dict(cached)

    candidates = resolve_title(query, lang=lang, limit=1)
    if not candidates:
        raise WikipediaServiceError(f"No Wikipedia article found for '{query}'.")

    title = candidates[0]
    summary = _fetch_summary_by_title(title, lang=lang)

    _try_set_cached(cache_key, summary.to_dict())
    return summary


def _fetch_summary_by_title(title: str, lang: str = "en") -> WikipediaSummary:
    requests = _get_requests()
    url = _SUMMARY_URL_TEMPLATE.format(lang=lang, title=quote(title.replace(" ", "_")))

    try:
        response = requests.get(
            url,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            raise WikipediaServiceError(f"No Wikipedia article found for '{title}'.")
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WikipediaServiceError(f"Wikipedia summary request failed: {exc}") from exc

    data = response.json()

    if data.get("type") == _DISAMBIGUATION_TYPE:
        options = _extract_disambiguation_options(data)
        cache_key = _cache_key("summary", title, lang)
        _try_set_cached(cache_key, {"_disambiguation": True, "options": options})
        raise DisambiguationError(title, options)

    thumbnail = data.get("thumbnail", {}).get("source")
    page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

    return WikipediaSummary(
        title=data.get("title", title),
        extract=data.get("extract", "").strip(),
        url=page_url,
        thumbnail_url=thumbnail,
    )


def _extract_disambiguation_options(data: dict) -> list[str]:
    """
    Best-effort extraction of candidate topic names from a
    disambiguation page's summary payload. The REST summary endpoint
    doesn't structurally list disambiguation options, so this falls
    back to a plain-text heuristic split of the extract, which
    Wikipedia typically formats as a short list-like description.
    """
    extract = data.get("extract", "")
    # Disambiguation extracts commonly look like: "X may refer to: ..."
    # without a clean machine-readable list; return the raw extract as
    # a single "option" summary if we can't do better, so at least the
    # caller has something informative to relay to the user.
    if not extract:
        return [data.get("title", "multiple topics")]
    return [extract]


def search_and_summarize(query: str, lang: str = "en", max_sentences: int = WIKIPEDIA_SENTENCES) -> str:
    """
    Convenience one-call helper for brain/response_generator.py: look up
    `query` and return a ready-to-speak summary string, handling the
    'not found' and 'ambiguous' cases with natural fallback phrasing
    instead of raising all the way up to the caller.
    """
    try:
        summary = get_summary(query, lang=lang)
        return summary.to_speech(max_sentences=max_sentences)
    except DisambiguationError:
        return f"'{query}' could mean a few different things. Could you be more specific?"
    except WikipediaServiceError as exc:
        logger.info("Wikipedia lookup failed for '%s': %s", query, exc)
        return f"I couldn't find anything on Wikipedia about '{query}'."


def is_available() -> bool:
    """Wikipedia's API needs no key, so this only checks that the
    'requests' package is installed."""
    try:
        _get_requests()
        return True
    except WikipediaServiceError:
        return False


def search_wikipedia(*args, **kwargs):
    """Search Wikipedia entries."""
    return search_and_summarize(*args, **kwargs)

# my all section is ok                                              ==================================================================================================

__all__ = [
    "DisambiguationError",
    "WikipediaServiceError",
    "WikipediaSummary",
    "get_summary",
    "is_available",
    "resolve_title",
    "search_and_summarize",
    "search_wikipedia",
]
