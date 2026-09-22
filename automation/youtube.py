"""
automation/youtube.py
=====================

Professional YouTube automation module for AssistantX.

Features
--------
- Build YouTube search/watch/channel/playlist URLs
- Open YouTube homepage
- Search YouTube
- Best-effort top-result resolution
- Play a searched video
- Open channels and playlists
- Validate YouTube video / playlist IDs
- Extract video IDs from common YouTube URLs
- Pause/resume/next/previous helpers
- Volume and playback shortcut helpers
- Browser-independent URL generation
- Optional requests dependency
- Clean error handling and logging
- Type hints and dataclasses
- Backward-compatible public API

This module intentionally does NOT require the official YouTube Data API.
The normal search/open functionality works without an API key.

Optional dependency:
    pip install requests
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, quote_plus, urlparse

from automation.browser import BrowserError, open_url
from core.logger import get_logger

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YOUTUBE_BASE_URL = "https://www.youtube.com"
YOUTUBE_WATCH_URL = f"{YOUTUBE_BASE_URL}/watch?v={{video_id}}"
YOUTUBE_SEARCH_URL = f"{YOUTUBE_BASE_URL}/results?search_query={{query}}"
YOUTUBE_CHANNEL_URL = f"{YOUTUBE_BASE_URL}/@{{handle}}"
YOUTUBE_PLAYLIST_URL = f"{YOUTUBE_BASE_URL}/playlist?list={{playlist_id}}"

YOUTUBE_HOME_URL = YOUTUBE_BASE_URL

DEFAULT_TIMEOUT = 5.0

# Standard YouTube video IDs are 11 characters.
VIDEO_ID_LENGTH = 11

# YouTube IDs normally contain:
# A-Z, a-z, 0-9, underscore, hyphen
VIDEO_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{11}$")

PLAYLIST_ID_REGEX = re.compile(
    r"^[A-Za-z0-9_-]+$"
)

CHANNEL_HANDLE_REGEX = re.compile(
    r"^[A-Za-z0-9._-]+$"
)

# Used when scanning YouTube search HTML.
VIDEO_ID_PATTERN = re.compile(
    r'"videoId":"([A-Za-z0-9_-]{11})"'
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class YouTubeError(RuntimeError):
    """Base exception for YouTube automation errors."""


class YouTubeValidationError(YouTubeError):
    """Raised when a YouTube input is invalid."""


class YouTubeNetworkError(YouTubeError):
    """Raised when a YouTube network request fails."""


class YouTubeOpenError(YouTubeError):
    """Raised when AssistantX cannot open a YouTube URL."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YouTubeSearchResult:
    """
    Represents a resolved YouTube video.

    Attributes
    ----------
    video_id:
        YouTube's 11-character video ID.

    url:
        Full watch URL.

    query:
        Original search query, when available.

    resolved:
        True when a real video ID was found.
    """

    video_id: str
    url: str
    query: str = ""
    resolved: bool = True

    @property
    def is_valid(self) -> bool:
        """Return True when the result contains a valid video ID."""
        return is_valid_video_id(self.video_id)


@dataclass(frozen=True)
class YouTubeUrlInfo:
    """Parsed information extracted from a YouTube URL."""

    video_id: str | None = None
    playlist_id: str | None = None
    channel_handle: str | None = None

    @property
    def is_video(self) -> bool:
        return bool(self.video_id)

    @property
    def is_playlist(self) -> bool:
        return bool(self.playlist_id)

    @property
    def is_channel(self) -> bool:
        return bool(self.channel_handle)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_non_empty(value: str, field_name: str) -> str:
    """
    Validate that a string is not empty.

    Parameters
    ----------
    value:
        Input string.

    field_name:
        Human-readable field name for error messages.
    """
    if not isinstance(value, str):
        raise YouTubeValidationError(
            f"{field_name} must be a string."
        )

    value = value.strip()

    if not value:
        raise YouTubeValidationError(
            f"{field_name} cannot be empty."
        )

    return value


def is_valid_video_id(video_id: str) -> bool:
    """Return True when `video_id` looks like a valid YouTube video ID."""
    if not isinstance(video_id, str):
        return False

    return bool(VIDEO_ID_REGEX.fullmatch(video_id.strip()))


def validate_video_id(video_id: str) -> str:
    """Validate and return a cleaned YouTube video ID."""
    video_id = _require_non_empty(video_id, "video_id")

    if not is_valid_video_id(video_id):
        raise YouTubeValidationError(
            "Invalid YouTube video ID. "
            "A video ID must contain exactly 11 characters."
        )

    return video_id


def is_valid_playlist_id(playlist_id: str) -> bool:
    """Return True when a playlist ID contains valid YouTube ID characters."""
    if not isinstance(playlist_id, str):
        return False

    playlist_id = playlist_id.strip()

    if not playlist_id:
        return False

    return bool(PLAYLIST_ID_REGEX.fullmatch(playlist_id))


def validate_playlist_id(playlist_id: str) -> str:
    """Validate and return a cleaned playlist ID."""
    playlist_id = _require_non_empty(
        playlist_id,
        "playlist_id",
    )

    if not is_valid_playlist_id(playlist_id):
        raise YouTubeValidationError(
            "Invalid YouTube playlist ID."
        )

    return playlist_id


def normalize_channel_handle(channel_handle: str) -> str:
    """
    Normalize a YouTube channel handle.

    Examples
    --------
    @Google
    Google
    -> Google
    """
    channel_handle = _require_non_empty(
        channel_handle,
        "channel_handle",
    )

    channel_handle = channel_handle.lstrip("@").strip()

    if not channel_handle:
        raise YouTubeValidationError(
            "Channel handle cannot be empty."
        )

    if not CHANNEL_HANDLE_REGEX.fullmatch(channel_handle):
        raise YouTubeValidationError(
            f"Invalid YouTube channel handle: {channel_handle}"
        )

    return channel_handle


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def build_home_url() -> str:
    """Return the YouTube homepage URL."""
    return YOUTUBE_HOME_URL


def build_search_url(query: str) -> str:
    """
    Build a YouTube search URL.

    Parameters
    ----------
    query:
        Search phrase.
    """
    query = _require_non_empty(query, "query")

    encoded_query = quote_plus(query)

    return YOUTUBE_SEARCH_URL.format(
        query=encoded_query
    )


def build_watch_url(video_id: str) -> str:
    """
    Build a YouTube watch URL from a video ID.
    """
    video_id = validate_video_id(video_id)

    return YOUTUBE_WATCH_URL.format(
        video_id=quote(video_id, safe="")
    )


def build_embed_url(video_id: str) -> str:
    """Build a YouTube embed URL."""
    video_id = validate_video_id(video_id)

    return (
        f"{YOUTUBE_BASE_URL}/embed/"
        f"{quote(video_id, safe='')}"
    )


def build_short_url(video_id: str) -> str:
    """Build a youtu.be short URL."""
    video_id = validate_video_id(video_id)

    return (
        f"https://youtu.be/"
        f"{quote(video_id, safe='')}"
    )


def build_playlist_url(playlist_id: str) -> str:
    """Build a YouTube playlist URL."""
    playlist_id = validate_playlist_id(playlist_id)

    return YOUTUBE_PLAYLIST_URL.format(
        playlist_id=quote(playlist_id, safe="")
    )


def build_channel_url(channel_handle: str) -> str:
    """Build a YouTube channel URL from a handle."""
    handle = normalize_channel_handle(channel_handle)

    return YOUTUBE_CHANNEL_URL.format(
        handle=quote(handle, safe="._-")
    )


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def extract_video_id(url: str) -> str | None:
    """
    Extract a video ID from common YouTube URLs.

    Supported examples
    ------------------
    https://www.youtube.com/watch?v=dQw4w9WgXcQ
    https://youtu.be/dQw4w9WgXcQ
    https://www.youtube.com/embed/dQw4w9WgXcQ
    """
    if not isinstance(url, str):
        return None

    url = url.strip()

    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    hostname = parsed.netloc.lower()

    # ------------------------------------------------------------------
    # youtube.com/watch?v=VIDEO_ID
    # ------------------------------------------------------------------

    if "youtube.com" in hostname:
        query_params = parse_qs(parsed.query)

        video_ids = query_params.get("v")

        if video_ids:
            video_id = video_ids[0]

            if is_valid_video_id(video_id):
                return video_id

    # ------------------------------------------------------------------
    # youtu.be/VIDEO_ID
    # ------------------------------------------------------------------

    if "youtu.be" in hostname:
        video_id = parsed.path.strip("/").split("/")[0]

        if is_valid_video_id(video_id):
            return video_id

    # ------------------------------------------------------------------
    # youtube.com/embed/VIDEO_ID
    # ------------------------------------------------------------------

    if "youtube.com" in hostname:
        parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        if len(parts) >= 2 and parts[0] == "embed":
            video_id = parts[1]

            if is_valid_video_id(video_id):
                return video_id

    return None


def extract_playlist_id(url: str) -> str | None:
    """Extract a playlist ID from a YouTube URL."""
    if not isinstance(url, str):
        return None

    url = url.strip()

    if not url:
        return None

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
    except Exception:
        return None

    playlist_ids = params.get("list")

    if not playlist_ids:
        return None

    playlist_id = playlist_ids[0]

    if is_valid_playlist_id(playlist_id):
        return playlist_id

    return None


def parse_youtube_url(url: str) -> YouTubeUrlInfo:
    """
    Parse a YouTube URL and return structured information.
    """
    video_id = extract_video_id(url)
    playlist_id = extract_playlist_id(url)

    channel_handle: str | None = None

    try:
        parsed = urlparse(url)
        parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        if parts and parts[0].startswith("@"):
            try:
                channel_handle = normalize_channel_handle(
                    parts[0]
                )
            except YouTubeValidationError:
                channel_handle = None

    except Exception:
        pass

    return YouTubeUrlInfo(
        video_id=video_id,
        playlist_id=playlist_id,
        channel_handle=channel_handle,
    )


def is_youtube_url(url: str) -> bool:
    """Return True when the URL belongs to YouTube."""
    if not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    hostname = parsed.netloc.lower()

    return (
        "youtube.com" in hostname
        or "youtu.be" in hostname
    )


# ---------------------------------------------------------------------------
# Browser opening helpers
# ---------------------------------------------------------------------------


def _open(url: str) -> bool:
    """
    Internal safe wrapper around browser.open_url().
    """
    try:
        result = open_url(url)

        if result is False:
            raise YouTubeOpenError(
                f"Browser failed to open URL: {url}"
            )

        return True

    except BrowserError as exc:
        logger.error(
            "Failed to open YouTube URL: %s",
            exc,
        )

        raise YouTubeOpenError(
            f"Unable to open YouTube URL: {exc}"
        ) from exc

    except YouTubeOpenError:
        raise

    except Exception as exc:
        logger.exception(
            "Unexpected YouTube browser error."
        )

        raise YouTubeOpenError(
            f"Unexpected error opening YouTube URL: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Basic navigation
# ---------------------------------------------------------------------------


def open_home() -> bool:
    """Open the YouTube homepage."""
    logger.info("Opening YouTube homepage.")

    return _open(
        build_home_url()
    )


def open_search(query: str) -> bool:
    """
    Open YouTube search results for a query.
    """
    query = _require_non_empty(
        query,
        "query",
    )

    url = build_search_url(query)

    logger.info(
        "Opening YouTube search: %s",
        query,
    )

    return _open(url)


def open_video(video_id: str) -> bool:
    """Open a YouTube video by video ID."""
    url = build_watch_url(video_id)

    logger.info(
        "Opening YouTube video: %s",
        video_id,
    )

    return _open(url)


def open_playlist(playlist_id: str) -> bool:
    """Open a YouTube playlist."""
    url = build_playlist_url(playlist_id)

    logger.info(
        "Opening YouTube playlist."
    )

    return _open(url)


def open_channel(channel_handle: str) -> bool:
    """Open a YouTube channel by handle."""
    url = build_channel_url(
        channel_handle
    )

    logger.info(
        "Opening YouTube channel: %s",
        channel_handle,
    )

    return _open(url)


# ---------------------------------------------------------------------------
# Network-based search
# ---------------------------------------------------------------------------


def _get_requests():
    """
    Lazily import requests.

    This keeps YouTube automation usable even when requests is not
    installed.
    """
    try:
        import requests  # type: ignore

        return requests

    except ImportError:
        logger.debug(
            "'requests' is not installed."
        )

        return None


def _fetch_search_html(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> str | None:
    """
    Fetch YouTube search HTML.

    This is a best-effort helper. YouTube can change its markup or
    block automated requests, so callers must handle None gracefully.
    """
    requests = _get_requests()

    if requests is None:
        return None

    query = _require_non_empty(
        query,
        "query",
    )

    if timeout <= 0:
        raise YouTubeValidationError(
            "timeout must be greater than zero."
        )

    url = build_search_url(query)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers=headers,
        )

        response.raise_for_status()

        return response.text

    except requests.RequestException as exc:
        logger.debug(
            "YouTube search request failed: %s",
            exc,
        )

        return None

    except Exception as exc:
        logger.debug(
            "Unexpected YouTube request error: %s",
            exc,
        )

        return None


def _extract_video_ids(
    html: str,
) -> list[str]:
    """
    Extract unique video IDs from YouTube HTML.
    """
    if not html:
        return []

    matches = VIDEO_ID_PATTERN.findall(
        html
    )

    results: list[str] = []
    seen: set[str] = set()

    for video_id in matches:
        if video_id in seen:
            continue

        seen.add(video_id)
        results.append(video_id)

    return results


def _fetch_video_ids(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[str]:
    """
    Fetch possible YouTube video IDs for a search query.
    """
    html = _fetch_search_html(
        query=query,
        timeout=timeout,
    )

    if not html:
        return []

    return _extract_video_ids(html)


def _fetch_first_video_id(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> str | None:
    """
    Best-effort lookup of the first video ID.
    """
    ids = _fetch_video_ids(
        query=query,
        timeout=timeout,
    )

    if not ids:
        return None

    return ids[0]


# ---------------------------------------------------------------------------
# Search result helpers
# ---------------------------------------------------------------------------


def search_video_ids(
    query: str,
    limit: int = 10,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[str]:
    """
    Return a list of possible video IDs for a search query.

    Notes
    -----
    This is a lightweight HTML-based lookup and should be treated as
    best-effort rather than a guaranteed YouTube search API.
    """
    query = _require_non_empty(
        query,
        "query",
    )

    if limit <= 0:
        raise YouTubeValidationError(
            "limit must be greater than zero."
        )

    ids = _fetch_video_ids(
        query=query,
        timeout=timeout,
    )

    return ids[:limit]


def resolve_top_result(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> YouTubeSearchResult | None:
    """
    Resolve the first available video for a search query.

    Returns
    -------
    YouTubeSearchResult | None
    """
    query = _require_non_empty(
        query,
        "query",
    )

    video_id = _fetch_first_video_id(
        query=query,
        timeout=timeout,
    )

    if not video_id:
        return None

    return YouTubeSearchResult(
        video_id=video_id,
        url=build_watch_url(video_id),
        query=query,
        resolved=True,
    )


# ---------------------------------------------------------------------------
# Playback helpers
# ---------------------------------------------------------------------------


def play_video(video_id: str) -> bool:
    """
    Open a specific video.

    Opening the watch page allows YouTube/browser autoplay policies
    to determine whether playback starts automatically.
    """
    return open_video(video_id)


def play_top_result(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> YouTubeSearchResult:
    """
    Search YouTube and open the first resolved result.

    If resolution fails, AssistantX safely falls back to the search
    results page.
    """
    query = _require_non_empty(
        query,
        "query",
    )

    logger.info(
        "Attempting to play top YouTube result: %s",
        query,
    )

    result = resolve_top_result(
        query=query,
        timeout=timeout,
    )

    if result is not None:
        try:
            _open(result.url)

            logger.info(
                "Opened top YouTube result: %s",
                result.video_id,
            )

            return result

        except YouTubeOpenError as exc:
            logger.warning(
                "Could not open resolved video: %s",
                exc,
            )

    # --------------------------------------------------------------
    # Fallback
    # --------------------------------------------------------------

    search_url = build_search_url(query)

    logger.info(
        "Falling back to YouTube search page."
    )

    try:
        _open(search_url)
    except YouTubeOpenError:
        logger.exception(
            "Failed to open YouTube fallback search."
        )

    return YouTubeSearchResult(
        video_id="",
        url=search_url,
        query=query,
        resolved=False,
    )


def search_and_play(
    query: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> YouTubeSearchResult:
    """
    Alias for play_top_result().

    Useful for command-router integrations.
    """
    return play_top_result(
        query=query,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Common YouTube UI shortcuts
# ---------------------------------------------------------------------------


def _keyboard():
    """
    Lazy-load AssistantX keyboard automation.

    This avoids creating a hard dependency between YouTube URL
    handling and keyboard automation.
    """
    try:
        from automation import keyboard

        return keyboard

    except ImportError as exc:
        raise YouTubeError(
            "AssistantX keyboard automation is unavailable."
        ) from exc


def pause() -> bool:
    """
    Toggle YouTube play/pause using the spacebar.

    The browser/video must have focus.
    """
    logger.info(
        "Sending YouTube play/pause command."
    )

    return _keyboard().press_key("space")


def toggle_play_pause() -> bool:
    """Alias for pause()."""
    return pause()


def next_video() -> bool:
    """
    Request the next YouTube video.

    Shift+N is commonly supported by YouTube.
    """
    logger.info(
        "Sending YouTube next-video command."
    )

    return _keyboard().press_hotkey(
        "shift",
        "n",
    )


def previous_video() -> bool:
    """
    Request the previous YouTube video.

    Shift+P is commonly supported by YouTube.
    """
    logger.info(
        "Sending YouTube previous-video command."
    )

    return _keyboard().press_hotkey(
        "shift",
        "p",
    )


def toggle_fullscreen() -> bool:
    """Toggle YouTube fullscreen."""
    return _keyboard().press_key("f")


def toggle_mute() -> bool:
    """Mute/unmute the YouTube player."""
    return _keyboard().press_key("m")


def seek_forward(seconds: int = 10) -> bool:
    """
    Seek forward.

    YouTube keyboard shortcuts are typically 5 seconds per right-arrow
    press, so this function approximates the requested duration.
    """
    if seconds <= 0:
        raise YouTubeValidationError(
            "seconds must be greater than zero."
        )

    presses = max(
        1,
        round(seconds / 5),
    )

    for _ in range(presses):
        _keyboard().press_key("right")

    return True


def seek_backward(seconds: int = 10) -> bool:
    """
    Seek backward.

    Uses YouTube's left-arrow shortcut.
    """
    if seconds <= 0:
        raise YouTubeValidationError(
            "seconds must be greater than zero."
        )

    presses = max(
        1,
        round(seconds / 5),
    )

    for _ in range(presses):
        _keyboard().press_key("left")

    return True


def volume_up(steps: int = 1) -> bool:
    """Increase YouTube volume."""
    if steps <= 0:
        raise YouTubeValidationError(
            "steps must be greater than zero."
        )

    keyboard = _keyboard()

    for _ in range(steps):
        keyboard.press_key("up")

    return True


def volume_down(steps: int = 1) -> bool:
    """Decrease YouTube volume."""
    if steps <= 0:
        raise YouTubeValidationError(
            "steps must be greater than zero."
        )

    keyboard = _keyboard()

    for _ in range(steps):
        keyboard.press_key("down")

    return True


# ---------------------------------------------------------------------------
# URL utility functions
# ---------------------------------------------------------------------------


def video_url_from_input(value: str) -> str | None:
    """
    Convert either a YouTube URL or video ID into a watch URL.

    Returns None when the input cannot be interpreted as a video.
    """
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    # Already a URL
    extracted = extract_video_id(value)

    if extracted:
        return build_watch_url(extracted)

    # Raw ID
    if is_valid_video_id(value):
        return build_watch_url(value)

    return None


def playlist_url_from_input(
    value: str,
) -> str | None:
    """
    Convert either a playlist URL or playlist ID into a playlist URL.
    """
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    extracted = extract_playlist_id(value)

    if extracted:
        return build_playlist_url(
            extracted
        )

    if is_valid_playlist_id(value):
        return build_playlist_url(value)

    return None


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def clean_search_query(query: str) -> str:
    """
    Clean a voice/text search query.

    This intentionally performs conservative cleanup so song titles
    and artist names are not accidentally changed.
    """
    query = _require_non_empty(
        query,
        "query",
    )

    # Normalize whitespace.
    query = re.sub(
        r"\s+",
        " ",
        query,
    )

    return query.strip()


def build_music_search_query(
    song: str,
    artist: str | None = None,
) -> str:
    """
    Build a YouTube music search query.

    Examples
    --------
    build_music_search_query("Believer", "Imagine Dragons")
    -> "Believer Imagine Dragons"
    """
    song = _require_non_empty(
        song,
        "song",
    )

    parts = [song]

    if artist:
        artist = artist.strip()

        if artist:
            parts.append(artist)

    return clean_search_query(
        " ".join(parts)
    )


def build_search_queries(
    query: str,
    variations: Iterable[str] | None = None,
) -> list[str]:
    """
    Build unique search-query variations.

    Useful for voice assistant fallback logic.
    """
    query = clean_search_query(query)

    results = [query]
    seen = {query.lower()}

    if variations:
        for variation in variations:
            if not isinstance(
                variation,
                str,
            ):
                continue

            variation = clean_search_query(
                variation
            )

            key = variation.lower()

            if key in seen:
                continue

            seen.add(key)
            results.append(variation)

    return results


# ---------------------------------------------------------------------------
# Safe convenience functions
# ---------------------------------------------------------------------------


def safe_open_search(query: str) -> bool:
    """
    Open search without propagating YouTube exceptions.

    Useful when called directly from a voice-command loop.
    """
    try:
        return open_search(query)

    except YouTubeError as exc:
        logger.error(
            "YouTube search failed: %s",
            exc,
        )

        return False


def safe_play_top_result(
    query: str,
) -> YouTubeSearchResult | None:
    """
    Safe version of play_top_result().

    Returns None on failure instead of raising.
    """
    try:
        return play_top_result(query)

    except YouTubeError as exc:
        logger.error(
            "YouTube playback failed: %s",
            exc,
        )

        return None


def safe_open_video(
    video_id: str,
) -> bool:
    """Safe version of open_video()."""
    try:
        return open_video(video_id)

    except YouTubeError as exc:
        logger.error(
            "Could not open YouTube video: %s",
            exc,
        )

        return False


# ---------------------------------------------------------------------------
# AssistantX command helpers
# ---------------------------------------------------------------------------


def handle_play_command(
    query: str,
) -> YouTubeSearchResult:
    """
    High-level helper for AssistantX commands such as:

        play believer on youtube
        play shape of you
        youtube play despacito
    """
    query = clean_search_query(query)

    logger.info(
        "Handling YouTube play command: %s",
        query,
    )

    return play_top_result(query)


def handle_search_command(
    query: str,
) -> bool:
    """
    High-level helper for:

        search youtube for python tutorial
    """
    query = clean_search_query(query)

    return open_search(query)


def handle_channel_command(
    channel: str,
) -> bool:
    """High-level channel-opening command."""
    return open_channel(channel)


def handle_playlist_command(
    playlist_id: str,
) -> bool:
    """High-level playlist-opening command."""
    return open_playlist(playlist_id)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def requests_available() -> bool:
    """Return True when the optional requests package is installed."""
    return _get_requests() is not None


def backend_available() -> bool:
    """
    Return True when the browser backend appears available.

    This performs a lightweight import-level check only.
    """
    try:
        from automation.browser import open_url as _open_url

        return callable(_open_url)

    except Exception:
        return False


def diagnostics() -> dict[str, object]:
    """
    Return YouTube automation diagnostics.

    Example result:

        {
            "youtube": True,
            "browser_backend": True,
            "requests": True,
        }
    """
    return {
        "youtube": True,
        "browser_backend": backend_available(),
        "requests": requests_available(),
    }


# ---------------------------------------------------------------------------
# Module-level aliases
# ---------------------------------------------------------------------------

youtube_home = open_home
youtube_search = open_search
youtube_video = open_video
youtube_playlist = open_playlist
youtube_channel = open_channel
youtube_play = play_top_result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Exceptions
    "YouTubeError",
    "YouTubeValidationError",
    "YouTubeNetworkError",
    "YouTubeOpenError",

    # Dataclasses
    "YouTubeSearchResult",
    "YouTubeUrlInfo",

    # Validation
    "is_valid_video_id",
    "validate_video_id",
    "is_valid_playlist_id",
    "validate_playlist_id",
    "normalize_channel_handle",

    # URL builders
    "build_home_url",
    "build_search_url",
    "build_watch_url",
    "build_embed_url",
    "build_short_url",
    "build_playlist_url",
    "build_channel_url",

    # URL parsing
    "extract_video_id",
    "extract_playlist_id",
    "parse_youtube_url",
    "is_youtube_url",

    # Navigation
    "open_home",
    "open_search",
    "open_video",
    "open_playlist",
    "open_channel",

    # Search
    "search_video_ids",
    "resolve_top_result",
    "play_video",
    "play_top_result",
    "search_and_play",

    # Playback
    "pause",
    "toggle_play_pause",
    "next_video",
    "previous_video",
    "toggle_fullscreen",
    "toggle_mute",
    "seek_forward",
    "seek_backward",
    "volume_up",
    "volume_down",

    # Query utilities
    "clean_search_query",
    "build_music_search_query",
    "build_search_queries",

    # Input conversion
    "video_url_from_input",
    "playlist_url_from_input",

    # Safe helpers
    "safe_open_search",
    "safe_play_top_result",
    "safe_open_video",

    # AssistantX handlers
    "handle_play_command",
    "handle_search_command",
    "handle_channel_command",
    "handle_playlist_command",

    # Diagnostics
    "requests_available",
    "backend_available",
    "diagnostics",

    # Aliases
    "youtube_home",
    "youtube_search",
    "youtube_video",
    "youtube_playlist",
    "youtube_channel",
    "youtube_play",
]

