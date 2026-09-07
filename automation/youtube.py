"""
youtube.py
==========
YouTube-specific automation: searching, opening the top result directly,
and building playlist/channel URLs. Built on top of automation/browser.py
for the actual URL opening, plus a lightweight (dependency-optional)
"first result" lookup so "play <song> on youtube" can jump straight to
a video instead of just showing search results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from automation.browser import BrowserError, open_url
from core.logger import get_logger

logger = get_logger(__name__)

_VIDEO_ID_PATTERN = re.compile(r'"videoId":"([\w-]{11})"')


class YouTubeError(RuntimeError):
    """Raised when a YouTube automation action fails."""


@dataclass(frozen=True)
class YouTubeSearchResult:
    video_id: str
    url: str


def build_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query.strip())}"


def build_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def open_search(query: str) -> bool:
    """Open YouTube's search results page for `query` (does not auto-play
    anything — just shows the results, letting the user pick)."""
    logger.info("Opening YouTube search for '%s'.", query)
    return open_url(build_search_url(query))


def _fetch_first_video_id(query: str, timeout: float = 5.0) -> Optional[str]:
    """
    Best-effort lookup of the first video ID for a search query by
    fetching YouTube's search results HTML and regex-scanning for a
    videoId occurrence. This intentionally avoids the official YouTube
    Data API (which requires an API key/quota) for a simple "play the
    top result" convenience feature — if it fails for any reason
    (network, YouTube markup changes), callers should fall back to
    open_search() instead of hard-failing.
    """
    try:
        import requests
    except ImportError:
        logger.debug("'requests' not installed; cannot auto-resolve top YouTube result.")
        return None

    try:
        response = requests.get(
            build_search_url(query),
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AssistantX/1.0)"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("YouTube search fetch failed: %s", exc)
        return None

    match = _VIDEO_ID_PATTERN.search(response.text)
    if not match:
        return None
    return match.group(1)


def play_top_result(query: str) -> YouTubeSearchResult:
    """
    Search YouTube for `query` and open the top result's watch page
    directly (best-effort "auto-play" experience for voice commands like
    "play shape of you on youtube"). Falls back to opening the search
    results page if the top result couldn't be resolved automatically.
    """
    video_id = _fetch_first_video_id(query)

    if video_id is None:
        logger.info("Could not resolve top result for '%s'; opening search page instead.", query)
        open_search(query)
        return YouTubeSearchResult(video_id="", url=build_search_url(query))

    url = build_watch_url(video_id)
    logger.info("Playing top YouTube result for '%s': %s", query, url)
    open_url(url)
    return YouTubeSearchResult(video_id=video_id, url=url)


def open_channel(channel_handle: str) -> bool:
    """Open a YouTube channel by its @handle or channel name."""
    handle = channel_handle.strip().lstrip("@")
    url = f"https://www.youtube.com/@{quote_plus(handle)}"
    logger.info("Opening YouTube channel: %s", url)
    return open_url(url)


def open_playlist(playlist_id: str) -> bool:
    """Open a YouTube playlist by its ID."""
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    return open_url(url)

    