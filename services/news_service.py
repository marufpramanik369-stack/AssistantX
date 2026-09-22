"""
news_service.py
================
Live news headlines and topic search.

Backend strategy (mirrors search_service.py's pattern):
    1. NewsAPI.org (https://newsapi.org) — used automatically when
       NEWSAPI_KEY is configured. Its /v2/top-headlines endpoint returns
       genuinely live, frequently-updated headlines (typically refreshed
       every few minutes), and /v2/everything supports full-text topic
       search across thousands of sources.
    2. Google News RSS — used as the zero-configuration fallback when no
       NewsAPI key is set. Google News RSS feeds are updated in
       real time and require no API key at all, so AssistantX can
       always answer "what's in the news" out of the box, even with
       nothing configured.

Because "live" news specifically means results should reflect what's
happening *right now*, this service intentionally uses a much shorter
cache TTL than search_service.py's general web search cache — long
enough to avoid hammering the backend on rapid repeated queries, short
enough that headlines don't go stale mid-session.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from config.constants import (
    HTTP_USER_AGENT,
    NEWS_LANGUAGE,
    NEWS_PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
)
from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_MINUTES = 5  # short TTL — headlines should stay genuinely "live"
_NEWSAPI_TOP_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"
_NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
_GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss"
_GOOGLE_NEWS_SEARCH_RSS_URL = "https://news.google.com/rss/search"

_VALID_CATEGORIES = {
    "business", "entertainment", "general", "health", "science", "sports", "technology",
}


class NewsServiceError(RuntimeError):
    """Raised when a news lookup fails outright (network failure, invalid
    parameters) — NOT raised merely for 'no articles found', which
    returns an empty list instead so callers can phrase that naturally."""


@dataclass
class NewsArticle:
    title: str
    source: str
    url: str
    published_at: datetime | None
    description: str = ""

    def age_minutes(self) -> float | None:
        if self.published_at is None:
            return None
        delta = datetime.now(timezone.utc) - self.published_at
        return delta.total_seconds() / 60

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> NewsArticle:
        published = datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None
        return cls(
            title=data["title"],
            source=data["source"],
            url=data["url"],
            published_at=published,
            description=data.get("description", ""),
        )


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise NewsServiceError(
            "News lookups require the 'requests' package. Run: pip install requests"
        ) from exc


def _cache_key(prefix: str, *parts: str) -> str:
    normalized = ":".join(p.strip().lower() for p in parts if p)
    return f"news:{prefix}:{normalized}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=_CACHE_TTL_MINUTES)).isoformat()


def _try_get_cached(cache_key: str):
    try:
        from database import db_manager

        return db_manager.get_cache(cache_key)
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization, never fatal
        logger.debug("News cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(cache_key: str, value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(cache_key, value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write news cache (%s); continuing without caching.", exc)


# --------------------------------------------------------------------------- #
# NewsAPI.org backend (used when NEWSAPI_KEY is configured)
# --------------------------------------------------------------------------- #

def _parse_newsapi_articles(payload: dict) -> list[NewsArticle]:
    articles = []
    for item in payload.get("articles", []):
        published_raw = item.get("publishedAt")
        published_at = None
        if published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        articles.append(
            NewsArticle(
                title=item.get("title", "").strip(),
                source=(item.get("source") or {}).get("name", "Unknown"),
                url=item.get("url", ""),
                published_at=published_at,
                description=(item.get("description") or "").strip(),
            )
        )
    return articles


def _fetch_newsapi_top_headlines(
    api_key: str,
    category: str | None,
    country: str,
    max_results: int,
) -> list[NewsArticle]:
    requests = _get_requests()
    params = {"apiKey": api_key, "pageSize": max_results, "country": country}
    if category:
        params["category"] = category

    try:
        response = requests.get(
            _NEWSAPI_TOP_HEADLINES_URL,
            params=params,
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NewsServiceError(f"NewsAPI top-headlines request failed: {exc}") from exc

    return _parse_newsapi_articles(response.json())


def _fetch_newsapi_search(api_key: str, query: str, language: str, max_results: int) -> list[NewsArticle]:
    requests = _get_requests()
    try:
        response = requests.get(
            _NEWSAPI_EVERYTHING_URL,
            params={
                "apiKey": api_key,
                "q": query,
                "language": language,
                "sortBy": "publishedAt",  # prioritize the most recent articles for "live" relevance
                "pageSize": max_results,
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NewsServiceError(f"NewsAPI search request failed: {exc}") from exc

    return _parse_newsapi_articles(response.json())


# --------------------------------------------------------------------------- #
# Google News RSS backend (zero-configuration fallback, always live)
# --------------------------------------------------------------------------- #

def _parse_rss_feed(xml_text: str, max_results: int) -> list[NewsArticle]:
    articles: list[NewsArticle] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NewsServiceError(f"Could not parse RSS feed: {exc}") from exc

    for item in root.findall(".//item")[:max_results]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"
        description = (item.findtext("description") or "").strip()

        published_at = None
        if pub_date_raw:
            try:
                published_at = parsedate_to_datetime(pub_date_raw)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                published_at = None

        if not title or not link:
            continue

        articles.append(
            NewsArticle(title=title, source=source, url=link, published_at=published_at, description=description)
        )

    return articles


def _fetch_google_news_top(country: str, language: str, max_results: int) -> list[NewsArticle]:
    requests = _get_requests()
    try:
        response = requests.get(
            _GOOGLE_NEWS_RSS_URL,
            params={"hl": language, "gl": country.upper(), "ceid": f"{country.upper()}:{language}"},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NewsServiceError(f"Google News RSS request failed: {exc}") from exc

    return _parse_rss_feed(response.text, max_results)


def _fetch_google_news_search(query: str, language: str, country: str, max_results: int) -> list[NewsArticle]:
    requests = _get_requests()
    try:
        response = requests.get(
            _GOOGLE_NEWS_SEARCH_RSS_URL,
            params={
                "q": query,
                "hl": language,
                "gl": country.upper(),
                "ceid": f"{country.upper()}:{language}",
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NewsServiceError(f"Google News RSS search request failed: {exc}") from exc

    return _parse_rss_feed(response.text, max_results)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def get_top_headlines(
    category: str | None = None,
    country: str = "us",
    language: str = NEWS_LANGUAGE,
    max_results: int = NEWS_PAGE_SIZE,
) -> list[NewsArticle]:
    """
    Fetch current top headlines, optionally filtered by category
    ('business', 'technology', 'sports', etc).

    Uses NewsAPI automatically if NEWSAPI_KEY is configured (higher
    reliability, structured categories); otherwise falls back to Google
    News' live RSS feed with zero configuration required.

    Raises:
        NewsServiceError: on an invalid category or a request failure.
            An empty result set (no matching articles) is returned as
            an empty list, not an error.
    """
    if category and category.lower() not in _VALID_CATEGORIES:
        raise NewsServiceError(
            f"Invalid news category '{category}'. Valid options: {', '.join(sorted(_VALID_CATEGORIES))}"
        )

    cache_key = _cache_key("top", category or "", country, language, str(max_results))
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return [NewsArticle.from_dict(a) for a in cached]

    api_key = get_env("NEWSAPI_KEY")
    if api_key:
        articles = _fetch_newsapi_top_headlines(api_key, category, country, max_results)
        backend = "newsapi"
    else:
        articles = _fetch_google_news_top(country, language, max_results)
        backend = "google_news_rss"

    logger.info("Fetched %d top headline(s) via %s (category=%s).", len(articles), backend, category or "general")
    _try_set_cached(cache_key, [a.to_dict() for a in articles])
    return articles


def search_news(
    query: str,
    language: str = NEWS_LANGUAGE,
    country: str = "us",
    max_results: int = NEWS_PAGE_SIZE,
) -> list[NewsArticle]:
    """
    Search for recent news articles about a specific topic, e.g.
    "search_news('elections')" — sorted by recency so results reflect
    the most current coverage available.

    Raises:
        NewsServiceError: on an empty query or a request failure.
    """
    query = query.strip()
    if not query:
        raise NewsServiceError("Empty news search query.")

    cache_key = _cache_key("search", query, language, country, str(max_results))
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return [NewsArticle.from_dict(a) for a in cached]

    api_key = get_env("NEWSAPI_KEY")
    if api_key:
        articles = _fetch_newsapi_search(api_key, query, language, max_results)
        backend = "newsapi"
    else:
        articles = _fetch_google_news_search(query, language, country, max_results)
        backend = "google_news_rss"

    logger.info("News search for '%s' returned %d result(s) via %s.", query, len(articles), backend)
    _try_set_cached(cache_key, [a.to_dict() for a in articles])
    return articles


def format_headlines_for_speech(articles: list[NewsArticle], max_spoken: int = 5) -> str:
    """
    Produce a short, natural-language readout of headlines suitable for
    text-to-speech, e.g. for a "what's in the news" voice response.
    """
    if not articles:
        return "I couldn't find any news on that right now."

    lines = []
    for i, article in enumerate(articles[:max_spoken], start=1):
        lines.append(f"{i}. From {article.source}: {article.title}.")

    return " ".join(lines)


def is_available() -> bool:
    """
    News lookups always have a usable backend (Google News RSS needs no
    key), so this only checks that the 'requests' package is installed.
    """
    try:
        _get_requests()
        return True
    except NewsServiceError:
        return False


def is_using_premium_backend() -> bool:
    """Whether a NEWSAPI_KEY is configured (True) or the free Google
    News RSS fallback is in use (False) — useful for a settings/status display."""
    return bool(get_env("NEWSAPI_KEY"))


def get_news(*args, **kwargs):
    """Fetch latest news items."""

    return get_top_headlines(*args, **kwargs)


# my all section is Oke                                               =======================================================================================================

__all__ = [
    "NewsArticle",
    "NewsServiceError",
    "format_headlines_for_speech",
    "get_news",
    "get_top_headlines",
    "is_available",
    "is_using_premium_backend",
    "search_news",
]

