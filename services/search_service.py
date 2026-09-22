"""
search_service.py
==================
Programmatic web search: given a query, returns a ranked list of
(title, url, snippet) results the assistant can read aloud or summarize
— as opposed to automation/browser.py's `search()`, which just opens a
search-engine results page in the user's browser for them to read
themselves.

Backend strategy:
    1. DuckDuckGo Instant Answer API (zero API key required) — used
       first for quick factual queries ("what is the capital of Japan"),
       since it often returns a direct abstract/answer with no scraping.
    2. DuckDuckGo HTML results page, lightly parsed — used as the
       general-purpose search fallback when no instant answer is
       available, again requiring no API key. This keeps AssistantX
       fully functional out of the box with zero search-provider
       configuration.
    3. An optional Bing Web Search API path, used instead of DuckDuckGo
       when a BING_SEARCH_API_KEY is configured, for higher-quality
       results where the user has one available.

Results are cached (via database.db_manager's cache table) for a short
TTL to avoid hammering the search backend on repeated/near-duplicate
voice queries in a short window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qs, unquote, urlparse

from config.constants import (
    DEFAULT_SEARCH_RESULTS_LIMIT,
    HTTP_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
)
from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_MINUTES = 10
_DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
_DUCKDUCKGO_INSTANT_URL = "https://api.duckduckgo.com/"
_BING_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"


class SearchServiceError(RuntimeError):
    """Raised when a search request fails or no backend is reachable."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "web"

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source}


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise SearchServiceError(
            "Web search requires the 'requests' package. Run: pip install requests"
        ) from exc


def _cache_key(prefix: str, query: str) -> str:
    return f"search:{prefix}:{query.strip().lower()}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=_CACHE_TTL_MINUTES)).isoformat()


def _try_get_cached(cache_key: str):
    try:
        from database import db_manager

        cached = db_manager.get_cache(cache_key)
        if cached is not None:
            logger.debug("Search cache hit: %s", cache_key)
        return cached
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization, never fatal
        logger.debug("Search cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(cache_key: str, value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(cache_key, value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write search cache (%s); continuing without caching.", exc)


# --------------------------------------------------------------------------- #
# DuckDuckGo Instant Answer API (no key required)
# --------------------------------------------------------------------------- #

def get_instant_answer(query: str) -> str | None:
    """
    Query DuckDuckGo's Instant Answer API for a direct, short factual
    answer (e.g. definitions, simple facts, unit conversions it knows
    about). Returns None if no instant answer is available, in which
    case the caller should fall back to `search()` for regular results.
    """
    cache_key = _cache_key("instant", query)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return cached or None

    requests = _get_requests()
    try:
        response = requests.get(
            _DUCKDUCKGO_INSTANT_URL,
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("Instant answer request failed: %s", exc)
        return None

    data = response.json()
    answer = (
        data.get("AbstractText")
        or data.get("Answer")
        or (data.get("RelatedTopics", [{}])[0].get("Text") if data.get("RelatedTopics") else None)
    )
    answer = answer.strip() if isinstance(answer, str) else None

    _try_set_cached(cache_key, answer or "")
    return answer or None


# --------------------------------------------------------------------------- #
# DuckDuckGo HTML results (no key required) — general-purpose fallback
# --------------------------------------------------------------------------- #

_RESULT_BLOCK_PATTERN = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)
_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")


def _clean_html_fragment(fragment: str) -> str:
    return unescape(_TAG_STRIP_PATTERN.sub("", fragment)).strip()


def _unwrap_duckduckgo_redirect(url: str) -> str:
    """
    DuckDuckGo's HTML results wrap outbound links in a redirect
    (`//duckduckgo.com/l/?uddg=<real_url>`); unwrap it so callers get the
    actual destination URL rather than DDG's tracking redirect.
    """
    if "duckduckgo.com/l/" not in url:
        return url
    parsed = urlparse(url if url.startswith("http") else f"https:{url}")
    query_params = parse_qs(parsed.query)
    real_url = query_params.get("uddg", [None])[0]
    return unquote(real_url) if real_url else url


def _search_duckduckgo_html(query: str, max_results: int) -> list[SearchResult]:
    requests = _get_requests()
    try:
        response = requests.post(
            _DUCKDUCKGO_HTML_URL,
            data={"q": query},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SearchServiceError(f"DuckDuckGo search request failed: {exc}") from exc

    results: list[SearchResult] = []
    for match in _RESULT_BLOCK_PATTERN.finditer(response.text):
        title = _clean_html_fragment(match.group("title"))
        snippet = _clean_html_fragment(match.group("snippet"))
        url = _unwrap_duckduckgo_redirect(match.group("url"))

        if not title or not url:
            continue

        results.append(SearchResult(title=title, url=url, snippet=snippet, source="duckduckgo"))
        if len(results) >= max_results:
            break

    return results


# --------------------------------------------------------------------------- #
# Optional Bing Web Search API (used only if a key is configured)
# --------------------------------------------------------------------------- #

def _search_bing(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    requests = _get_requests()
    try:
        response = requests.get(
            _BING_SEARCH_URL,
            headers={"Ocp-Apim-Subscription-Key": api_key, "User-Agent": HTTP_USER_AGENT},
            params={"q": query, "count": max_results, "textDecorations": False, "textFormat": "Raw"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SearchServiceError(f"Bing search request failed: {exc}") from exc

    data = response.json()
    web_pages = data.get("webPages", {}).get("value", [])
    return [
        SearchResult(
            title=item.get("name", ""),
            url=item.get("url", ""),
            snippet=item.get("snippet", ""),
            source="bing",
        )
        for item in web_pages[:max_results]
    ]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def search(query: str, max_results: int = DEFAULT_SEARCH_RESULTS_LIMIT) -> list[SearchResult]:
    """
    Perform a web search and return structured results.

    Uses Bing's API automatically if BING_SEARCH_API_KEY is configured
    in the environment (generally higher quality, has a free tier with
    limits); otherwise falls back to DuckDuckGo's HTML results, which
    require no API key or configuration at all.

    Results are cached for a short TTL to keep repeated queries within
    a session fast and avoid unnecessary load on the search backend.

    Raises:
        SearchServiceError: if the search request fails outright (e.g.
            no network connectivity) — callers should catch this and
            phrase a natural "couldn't search right now" response.
    """
    query = query.strip()
    if not query:
        raise SearchServiceError("Empty search query.")

    cache_key = _cache_key(f"results:{max_results}", query)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return [SearchResult(**item) for item in cached]

    bing_key = get_env("BING_SEARCH_API_KEY")
    if bing_key:
        results = _search_bing(query, max_results, bing_key)
    else:
        results = _search_duckduckgo_html(query, max_results)

    logger.info("Search for '%s' returned %d result(s) via %s.", query, len(results), results[0].source if results else "none")
    _try_set_cached(cache_key, [r.to_dict() for r in results])
    return results


def search_with_answer(query: str, max_results: int = DEFAULT_SEARCH_RESULTS_LIMIT) -> tuple[str | None, list[SearchResult]]:
    """
    Convenience combined lookup: tries to get a direct instant answer
    first (fast, no scraping needed for many factual queries), and also
    returns a full set of search results as supporting/fallback context.

    This is the function brain/response_generator.py-adjacent code will
    most commonly call for a WEB_SEARCH intent, since it gives both a
    quick spoken answer (if available) and browsable results.
    """
    instant_answer = None
    try:
        instant_answer = get_instant_answer(query)
    except SearchServiceError as exc:
        logger.debug("Instant answer lookup failed (non-fatal): %s", exc)

    try:
        results = search(query, max_results=max_results)
    except SearchServiceError as exc:
        logger.warning("Search results lookup failed: %s", exc)
        results = []

    return instant_answer, results


def format_results_for_speech(results: list[SearchResult], max_spoken: int = 3) -> str:
    """
    Produce a short, natural-language summary of search results suitable
    for text-to-speech readback (as opposed to the full result list,
    which is better suited to a dashboard display).
    """
    if not results:
        return "I couldn't find any results for that."

    lines = []
    for i, result in enumerate(results[:max_spoken], start=1):
        snippet = result.snippet[:140] + ("..." if len(result.snippet) > 140 else "")
        lines.append(f"{i}. {result.title}. {snippet}")

    return " ".join(lines)


def is_available() -> bool:
    """Check whether the search service has a usable backend (i.e. the
    'requests' package is installed) — network reachability itself is
    still only confirmed at actual request time."""
    try:
        _get_requests()
        return True
    except SearchServiceError:
        return False
