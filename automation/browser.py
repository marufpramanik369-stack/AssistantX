"""
browser.py
==========
Web browser automation: opening URLs, performing searches on common
search engines, and navigating to well-known sites by friendly name.
Built on Python's standard `webbrowser` module, so it works with
whatever the user's OS default browser is, without needing
browser-specific automation (Selenium etc.) for these simple cases.
"""

from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from core.logger import get_logger

logger = get_logger(__name__)

_URL_PATTERN = re.compile(r"^https?://", re.I)
_DOMAIN_LIKE_PATTERN = re.compile(r"^[\w-]+(\.[\w-]+)+$")


class BrowserError(RuntimeError):
    """Raised when a browser action could not be completed."""


@dataclass(frozen=True)
class SearchEngine:
    name: str
    url_template: str  # must contain '{query}'


SEARCH_ENGINES: dict[str, SearchEngine] = {
    "google": SearchEngine("Google", "https://www.google.com/search?q={query}"),
    "bing": SearchEngine("Bing", "https://www.bing.com/search?q={query}"),
    "duckduckgo": SearchEngine("DuckDuckGo", "https://duckduckgo.com/?q={query}"),
    "youtube": SearchEngine("YouTube", "https://www.youtube.com/results?search_query={query}"),
    "wikipedia": SearchEngine("Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search={query}"),
}

# Friendly site name -> URL, for "open <site>" style commands.
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
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
}


def _normalize_url(raw: str) -> str:
    """
    Turn user-provided input into a proper URL: pass through if already
    a full URL, add https:// if it looks like a bare domain, otherwise
    treat it as a search query (handled by the caller before reaching
    here — this function assumes URL-like input).
    """
    raw = raw.strip()
    if _URL_PATTERN.match(raw):
        return raw
    if _DOMAIN_LIKE_PATTERN.match(raw):
        return f"https://{raw}"
    return raw  # caller should have routed non-URL-like input to search() instead


def open_url(url: str, new_tab: bool = True) -> bool:
    """
    Open a specific URL in the default browser.

    Returns:
        True if the browser was successfully invoked.

    Raises:
        BrowserError: if webbrowser fails to find any usable browser.
    """
    normalized = _normalize_url(url)
    logger.info("Opening URL: %s", normalized)
    try:
        opener = webbrowser.open_new_tab if new_tab else webbrowser.open
        success = opener(normalized)
        if not success:
            raise BrowserError(f"No browser controller could open '{normalized}'.")
        return True
    except webbrowser.Error as exc:
        raise BrowserError(f"Failed to open browser: {exc}") from exc


def open_site(site_name: str) -> bool:
    """
    Open a well-known site by friendly name (e.g. 'youtube' -> youtube.com).
    Falls back to treating the name as a raw URL/domain if it's not in
    the KNOWN_SITES table.
    """
    key = site_name.strip().lower()
    url = KNOWN_SITES.get(key)
    if url is None:
        logger.debug("'%s' not in known sites table; treating as direct URL.", site_name)
        url = _normalize_url(site_name)
    return open_url(url)


def search(query: str, engine: str = "google") -> bool:
    """
    Perform a web search for `query` using the specified search engine.

    Args:
        query: The search terms.
        engine: One of SEARCH_ENGINES' keys ('google', 'bing',
            'duckduckgo', 'youtube', 'wikipedia'). Defaults to Google.

    Raises:
        BrowserError: if the engine name is unrecognized.
    """
    engine_key = engine.strip().lower()
    search_engine = SEARCH_ENGINES.get(engine_key)
    if search_engine is None:
        raise BrowserError(
            f"Unknown search engine '{engine}'. Available: {', '.join(SEARCH_ENGINES)}"
        )

    url = search_engine.url_template.format(query=quote_plus(query.strip()))
    logger.info("Searching '%s' via %s.", query, search_engine.name)
    return open_url(url)


def is_url_like(text: str) -> bool:
    """Heuristic check for whether `text` looks like a URL/domain rather
    than a search query — used by brain/classifier.py-adjacent logic to
    decide between open_url() and search()."""
    stripped = text.strip()
    return bool(_URL_PATTERN.match(stripped) or _DOMAIN_LIKE_PATTERN.match(stripped))


def smart_open(text: str, default_engine: str = "google") -> bool:
    """
    Convenience dispatcher: opens `text` directly if it looks like a
    URL/known site, otherwise performs a search for it. This is the
    function automation-facing callers (e.g. core/command_router.py)
    will most often use for WEB_SEARCH / OPEN_WEBSITE sub-intents.
    """
    key = text.strip().lower()
    if key in KNOWN_SITES:
        return open_site(key)
    if is_url_like(text):
        return open_url(text)
    return search(text, engine=default_engine)
    