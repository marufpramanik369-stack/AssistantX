"""
browser.py
==========
Professional web-browser automation for AssistantX.

Features
--------
- Open URLs in the default browser
- Open known websites by friendly name
- Search using multiple search engines
- Smart URL/search detection
- URL normalization and validation
- Search-engine registration support
- Safe wrappers for automation callers
- Browser availability diagnostics
- Backward-compatible public functions

This module intentionally uses Python's standard `webbrowser` module.
No Selenium or browser-specific driver is required.
"""

from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_SEARCH_ENGINE = "google"

_URL_PATTERN = re.compile(
    r"^https?://",
    re.IGNORECASE,
)

_DOMAIN_LIKE_PATTERN = re.compile(
    r"^(?:[\w-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:[/?#].*)?$",
)

_LOCALHOST_PATTERN = re.compile(
    r"^(?:localhost|127\.0\.0\.1)(?::\d+)?(?:[/?#].*)?$",
    re.IGNORECASE,
)

_MAX_QUERY_LENGTH = 2_000
_MAX_URL_LENGTH = 8_192


# ============================================================================
# Exceptions
# ============================================================================


class BrowserError(RuntimeError):
    """Base exception for browser automation failures."""


class BrowserValidationError(BrowserError):
    """Raised when browser input is invalid."""


class BrowserBackendError(BrowserError):
    """Raised when the operating system browser backend fails."""


class SearchEngineError(BrowserError):
    """Raised for search-engine configuration errors."""


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class SearchEngine:
    """
    Search-engine definition.

    `url_template` must contain `{query}`.
    """

    name: str
    url_template: str

    def build_url(self, query: str) -> str:
        """Build a search URL from a query."""
        if "{query}" not in self.url_template:
            raise SearchEngineError(
                f"Search engine '{self.name}' has an invalid URL template."
            )

        encoded_query = quote_plus(query.strip())
        return self.url_template.format(query=encoded_query)


@dataclass(frozen=True)
class BrowserInfo:
    """Diagnostic information about the browser backend."""

    available: bool
    controller_count: int
    controllers: tuple[str, ...]


# ============================================================================
# Search Engines
# ============================================================================


SEARCH_ENGINES: dict[str, SearchEngine] = {
    "google": SearchEngine(
        name="Google",
        url_template="https://www.google.com/search?q={query}",
    ),
    "bing": SearchEngine(
        name="Bing",
        url_template="https://www.bing.com/search?q={query}",
    ),
    "duckduckgo": SearchEngine(
        name="DuckDuckGo",
        url_template="https://duckduckgo.com/?q={query}",
    ),
    "youtube": SearchEngine(
        name="YouTube",
        url_template="https://www.youtube.com/results?search_query={query}",
    ),
    "wikipedia": SearchEngine(
        name="Wikipedia",
        url_template="https://en.wikipedia.org/wiki/Special:Search?search={query}",
    ),
}


# ============================================================================
# Known Websites
# ============================================================================


KNOWN_SITES: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://www.twitter.com",
    "x": "https://www.x.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org",
    "amazon": "https://www.amazon.com",
    "netflix": "https://www.netflix.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "stackoverflow": "https://stackoverflow.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://openai.com",
    "claude": "https://claude.ai",
    "discord": "https://discord.com",
    "spotify": "https://open.spotify.com",
    "telegram": "https://web.telegram.org",
    "whatsapp": "https://web.whatsapp.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "google maps": "https://maps.google.com",
}


# ============================================================================
# Validation
# ============================================================================


def _validate_text(value: str, field_name: str = "text") -> str:
    """Validate and normalize a generic text input."""
    if not isinstance(value, str):
        raise BrowserValidationError(
            f"{field_name} must be a string."
        )

    value = value.strip()

    if not value:
        raise BrowserValidationError(
            f"{field_name} cannot be empty."
        )

    return value


def _validate_query(query: str) -> str:
    """Validate a search query."""
    query = _validate_text(query, "Search query")

    if len(query) > _MAX_QUERY_LENGTH:
        raise BrowserValidationError(
            f"Search query is too long. Maximum length is "
            f"{_MAX_QUERY_LENGTH} characters."
        )

    return query


def _validate_url_length(url: str) -> str:
    """Validate URL length."""
    if len(url) > _MAX_URL_LENGTH:
        raise BrowserValidationError(
            f"URL is too long. Maximum length is {_MAX_URL_LENGTH} characters."
        )

    return url


# ============================================================================
# URL Helpers
# ============================================================================


def is_url_like(text: str) -> bool:
    """
    Return True when text looks like a URL or domain.

    Examples
    --------
    https://example.com -> True
    http://example.com -> True
    example.com         -> True
    localhost:8000      -> True
    hello world         -> False
    """
    if not isinstance(text, str):
        return False

    stripped = text.strip()

    if not stripped:
        return False

    if _URL_PATTERN.match(stripped):
        return True

    if _DOMAIN_LIKE_PATTERN.match(stripped):
        return True

    return bool(_LOCALHOST_PATTERN.match(stripped))


def _normalize_url(raw: str) -> str:
    """
    Normalize a URL/domain.

    Full HTTP/HTTPS URLs are preserved.
    Bare domains receive https://.
    localhost receives http://.
    """
    raw = _validate_text(raw, "URL")
    raw = _validate_url_length(raw)

    if _URL_PATTERN.match(raw):
        normalized = raw

    elif _LOCALHOST_PATTERN.match(raw):
        normalized = f"http://{raw}"

    elif _DOMAIN_LIKE_PATTERN.match(raw):
        normalized = f"https://{raw}"

    else:
        raise BrowserValidationError(
            f"'{raw}' does not look like a valid URL or domain."
        )

    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"}:
        raise BrowserValidationError(
            "Only HTTP and HTTPS URLs are supported."
        )

    if not parsed.netloc:
        raise BrowserValidationError(
            f"Invalid URL: '{normalized}'."
        )

    return normalized


def normalize_url(raw: str) -> str:
    """
    Public URL normalization helper.

    Raises BrowserValidationError for non-URL-like input.
    """
    return _normalize_url(raw)


# ============================================================================
# Browser Backend
# ============================================================================


def _get_browser_controllers() -> list[webbrowser.BaseBrowser]:
    """Return available browser controllers."""
    try:
        controllers = webbrowser._tryorder

        if not controllers:
            return []

        result: list[webbrowser.BaseBrowser] = []

        for browser_name in controllers:
            try:
                controller = webbrowser.get(browser_name)
                result.append(controller)
            except webbrowser.Error:
                continue

        return result

    except Exception as exc:# noqa: BLE001
        logger.debug(
            "Could not inspect browser controllers: %s",
            exc,
        )
        return []


def is_available() -> bool:
    """Return True if a usable browser controller appears available."""
    try:
        controller = webbrowser.get()
        return controller is not None
    except webbrowser.Error:
        return False
    except Exception as exc:# noqa: BLE001
        logger.debug(
            "Browser availability check failed: %s",
            exc,
        )
        return False


def get_browser_info() -> BrowserInfo:
    """Return diagnostic information about browser availability."""
    controllers = _get_browser_controllers()

    names: list[str] = []

    for controller in controllers:
        name = getattr(controller, "name", None)

        if name:
            names.append(str(name))
        else:
            names.append(controller.__class__.__name__)

    return BrowserInfo(
        available=is_available(),
        controller_count=len(names),
        controllers=tuple(names),
    )


# ============================================================================
# Core Browser Operations
# ============================================================================


def open_url(
    url: str,
    new_tab: bool = True,
) -> bool:
    """
    Open a specific URL in the default browser.

    Parameters
    ----------
    url:
        Full URL or bare domain.
    new_tab:
        If True, open in a new tab. Otherwise use normal browser.open().

    Returns
    -------
    bool
        True when the browser reports successful invocation.

    Raises
    ------
    BrowserValidationError
        If the URL is invalid.
    BrowserBackendError
        If the browser cannot be invoked.
    """
    normalized = _normalize_url(url)

    logger.info(
        "Opening URL: %s",
        normalized,
    )

    if not is_available():
        raise BrowserBackendError(
            "No usable default web browser was found."
        )

    try:
        if new_tab:
            success = webbrowser.open_new_tab(normalized)
        else:
            success = webbrowser.open(normalized)

    except webbrowser.Error as exc:
        logger.error(
            "Browser failed to open URL '%s': %s",
            normalized,
            exc,
        )

        raise BrowserBackendError(
            f"Failed to open browser: {exc}"
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected browser error while opening '%s'.",
            normalized,
        )

        raise BrowserBackendError(
            f"Unexpected browser error: {exc}"
        ) from exc

    if not success:
        raise BrowserBackendError(
            f"No browser controller could open '{normalized}'."
        )

    return True


def open_site(
    site_name: str,
    new_tab: bool = True,
) -> bool:
    """
    Open a known website by friendly name.

    Unknown names are treated as direct URL/domain input.
    """
    site_name = _validate_text(
        site_name,
        "Site name",
    )

    key = site_name.casefold()

    url = KNOWN_SITES.get(key)

    if url is None:
        logger.debug(
            "'%s' is not a known site; treating it as URL/domain.",
            site_name,
        )

        url = _normalize_url(site_name)

    logger.info(
        "Opening site '%s' -> %s",
        site_name,
        url,
    )

    return open_url(
        url,
        new_tab=new_tab,
    )


# ============================================================================
# Search
# ============================================================================


def get_search_engine(engine: str) -> SearchEngine:
    """
    Return a configured search engine.

    Raises SearchEngineError if unknown.
    """
    engine = _validate_text(
        engine,
        "Search engine",
    ).casefold()

    search_engine = SEARCH_ENGINES.get(engine)

    if search_engine is None:
        available = ", ".join(sorted(SEARCH_ENGINES))

        raise SearchEngineError(
            f"Unknown search engine '{engine}'. "
            f"Available: {available}"
        )

    return search_engine


def list_search_engines() -> tuple[str, ...]:
    """Return available search-engine keys."""
    return tuple(sorted(SEARCH_ENGINES))


def search(
    query: str,
    engine: str = DEFAULT_SEARCH_ENGINE,
) -> bool:
    """
    Search the web using a configured search engine.
    """
    query = _validate_query(query)
    search_engine = get_search_engine(engine)

    url = search_engine.build_url(query)

    logger.info(
        "Searching '%s' via %s.",
        query,
        search_engine.name,
    )

    return open_url(url)


def build_search_url(
    query: str,
    engine: str = DEFAULT_SEARCH_ENGINE,
) -> str:
    """
    Build a search URL without opening the browser.
    """
    query = _validate_query(query)
    search_engine = get_search_engine(engine)

    return search_engine.build_url(query)

# UPDATED                                                                                      ===============================================================================


import logging
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

def search_web(query: str, engine: str = "google") -> dict[str, Any]:
    """Execute a web search query using the specified search engine.

    Args:
        query: The search terms or text string to query.
        engine: The search engine name (defaults to "google").

    Returns:
        Dict[str, Any]: Search metadata including query, engine, formatted URL, and status.

    Raises:
        ValueError: If the input query is None, empty, or consists only of whitespace.
    """
    if query is None or not isinstance(query, str) or not query.strip():
        raise ValueError("Search query cannot be empty or whitespace.")

    clean_query = query.strip()
    encoded_query = urllib.parse.quote_plus(clean_query)
    
    # Engine base URL mapping
    engines = {
        "google": f"https://www.google.com/search?q={encoded_query}",
        "bing": f"https://www.bing.com/search?q={encoded_query}",
        "duckduckgo": f"https://duckduckgo.com/?q={encoded_query}",
    }

    target_url = engines.get(engine.lower(), f"https://www.google.com/search?q={encoded_query}")

    logger.info("Initiating web search for query: '%s' using engine: %s", clean_query, engine)

    webbrowser.open(target_url)
    
    return {
        "query": clean_query,
        "engine": engine.lower(),
        "url": target_url,
        "status": "success",
    }


# ============================================================================
# Smart Open
# ============================================================================


def smart_open(
    text: str,
    default_engine: str = DEFAULT_SEARCH_ENGINE,
) -> bool:
    """
    Intelligent browser dispatcher.

    Behavior
    --------
    Known site:
        open_site()

    URL/domain:
        open_url()

    Anything else:
        search()
    """
    text = _validate_text(
        text,
        "Input",
    )

    key = text.casefold()

    if key in KNOWN_SITES:
        return open_site(key)

    if is_url_like(text):
        return open_url(text)

    return search(
        text,
        engine=default_engine,
    )


# ============================================================================
# Safe Wrappers
# ============================================================================


def safe_open_url(
    url: str,
    new_tab: bool = True,
) -> bool:
    """
    Safe version of open_url().

    Returns False instead of raising BrowserError.
    """
    try:
        return open_url(
            url,
            new_tab=new_tab,
        )

    except BrowserError as exc:
        logger.warning(
            "safe_open_url failed: %s",
            exc,
        )
        return False


def safe_open_site(
    site_name: str,
    new_tab: bool = True,
) -> bool:
    """Safe version of open_site()."""
    try:
        return open_site(
            site_name,
            new_tab=new_tab,
        )

    except BrowserError as exc:
        logger.warning(
            "safe_open_site failed: %s",
            exc,
        )
        return False


def safe_search(
    query: str,
    engine: str = DEFAULT_SEARCH_ENGINE,
) -> bool:
    """Safe version of search()."""
    try:
        return search(
            query,
            engine=engine,
        )

    except BrowserError as exc:
        logger.warning(
            "safe_search failed: %s",
            exc,
        )
        return False


def safe_smart_open(
    text: str,
    default_engine: str = DEFAULT_SEARCH_ENGINE,
) -> bool:
    """Safe version of smart_open()."""
    try:
        return smart_open(
            text,
            default_engine=default_engine,
        )

    except BrowserError as exc:
        logger.warning(
            "safe_smart_open failed: %s",
            exc,
        )
        return False


# ============================================================================
# Search Engine Management
# ============================================================================


def register_search_engine(
    key: str,
    name: str,
    url_template: str,
) -> None:
    """
    Register or replace a search engine at runtime.

    Example
    -------
    register_search_engine(
        "example",
        "Example Search",
        "https://example.com/search?q={query}",
    )
    """
    key = _validate_text(
        key,
        "Search engine key",
    ).casefold()

    name = _validate_text(
        name,
        "Search engine name",
    )

    url_template = _validate_text(
        url_template,
        "Search engine URL template",
    )

    if "{query}" not in url_template:
        raise SearchEngineError(
            "Search engine URL template must contain '{query}'."
        )

    SEARCH_ENGINES[key] = SearchEngine(
        name=name,
        url_template=url_template,
    )

    logger.info(
        "Registered search engine '%s'.",
        key,
    )


def register_site(
    key: str,
    url: str,
) -> None:
    """
    Register or replace a friendly website shortcut.
    """
    key = _validate_text(
        key,
        "Site key",
    ).casefold()

    normalized = _normalize_url(url)

    KNOWN_SITES[key] = normalized

    logger.info(
        "Registered known site '%s' -> %s",
        key,
        normalized,
    )


# ============================================================================
# Diagnostics
# ============================================================================


def diagnostics() -> dict[str, object]:
    """
    Return browser-module diagnostic information.
    """
    info = get_browser_info()

    return {
        "available": info.available,
        "controller_count": info.controller_count,
        "controllers": list(info.controllers),
        "default_search_engine": DEFAULT_SEARCH_ENGINE,
        "search_engines": list_search_engines(),
        "known_site_count": len(KNOWN_SITES),
    }


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "DEFAULT_SEARCH_ENGINE",
    "KNOWN_SITES",
    "SEARCH_ENGINES",
    "BrowserBackendError",
    "BrowserError",
    "BrowserInfo",
    "BrowserValidationError",
    "SearchEngine",
    "SearchEngineError",
    "build_search_url",
    "diagnostics",
    "get_browser_info",
    "get_search_engine",
    "is_available",
    "is_url_like",
    "list_search_engines",
    "normalize_url",
    "open_site",
    "open_url",
    "register_search_engine",
    "register_site",
    "safe_open_site",
    "safe_open_url",
    "safe_search",
    "safe_smart_open",
    "search",
    "search_web",
    "smart_open",
]
