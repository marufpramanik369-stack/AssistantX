"""
music.py
========

Professional music-control module for AssistantX.

Features
--------
- OS-level media controls
- Play / pause
- Next / previous track
- Stop
- Volume up / down
- Optional Spotify Web API integration
- Spotify track search
- Spotify track playback
- Spotify pause/resume/skip controls
- Device-aware Spotify playback
- Graceful fallback to OS media keys
- Input validation
- Backend availability checks
- Diagnostics
- Safe helper functions
- Module-level Spotify singleton

Primary backend
---------------
PyAutoGUI

Optional Spotify backend
------------------------
Spotipy + Spotify Web API

Environment variables
---------------------
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET

Spotify redirect URI
--------------------
http://localhost:8888/callback

Install
-------
Basic media controls:
    pip install pyautogui

Spotify support:
    pip install spotipy
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

SPOTIFY_REDIRECT_URI = "http://localhost:8888/callback"

SPOTIFY_SCOPES = (
    "user-modify-playback-state "
    "user-read-playback-state "
    "user-read-currently-playing"
)

DEFAULT_SEARCH_LIMIT = 1
MAX_QUERY_LENGTH = 500


# ============================================================================
# EXCEPTIONS
# ============================================================================


class MusicControlError(RuntimeError):
    """Base exception for music-control failures."""


class MusicValidationError(MusicControlError):
    """Raised when music input is invalid."""


class MusicBackendError(MusicControlError):
    """Raised when the requested music backend is unavailable."""


class SpotifyError(MusicControlError):
    """Raised for Spotify-specific failures."""


# ============================================================================
# DATA MODELS
# ============================================================================


@dataclass(frozen=True)
class SpotifyTrack:
    """
    Basic Spotify track information.
    """

    name: str
    artist: str
    uri: str
    url: str
    album: str = ""
    duration_ms: int = 0

    @property
    def duration_seconds(self) -> float:
        """Return track duration in seconds."""
        return self.duration_ms / 1000.0


@dataclass(frozen=True)
class SpotifyDevice:
    """
    Spotify playback device information.
    """

    id: str
    name: str
    device_type: str
    is_active: bool
    volume_percent: int | None = None


# ============================================================================
# VALIDATION
# ============================================================================


def _validate_query(query: str) -> str:
    """
    Validate and normalize a music/Spotify search query.
    """
    if not isinstance(query, str):
        raise MusicValidationError(
            "Music query must be a string."
        )

    query = " ".join(query.strip().split())

    if not query:
        raise MusicValidationError(
            "Music query cannot be empty."
        )

    if len(query) > MAX_QUERY_LENGTH:
        raise MusicValidationError(
            f"Music query is too long. "
            f"Maximum length: {MAX_QUERY_LENGTH} characters."
        )

    return query


# ============================================================================
# OS MEDIA KEY BACKEND
# ============================================================================


def _get_keyboard_backend() -> Any:
    """
    Lazily load PyAutoGUI.

    Raises:
        MusicBackendError:
            If PyAutoGUI is unavailable.
    """
    try:
        import pyautogui  # type: ignore

        return pyautogui

    except ImportError as exc:
        raise MusicBackendError(
            "OS media controls require 'pyautogui'. "
            "Install it with: pip install pyautogui"
        ) from exc


def is_media_key_available() -> bool:
    """
    Return True if PyAutoGUI is installed.
    """
    try:
        _get_keyboard_backend()
        return True

    except MusicBackendError:
        return False


def _press_media_key(key: str, action_name: str) -> bool:
    """
    Press an OS-level media key safely.
    """
    pyautogui = _get_keyboard_backend()

    try:
        pyautogui.press(key)

        logger.debug(
            "Media key action '%s' executed.",
            action_name,
        )

        return True

    except Exception as exc:
        raise MusicControlError(
            f"Failed to {action_name}: {exc}"
        ) from exc


# ============================================================================
# OS MEDIA CONTROLS
# ============================================================================


def play_pause() -> bool:
    """
    Toggle play/pause for the application currently owning
    media playback.
    """
    return _press_media_key(
        "playpause",
        "toggle play/pause",
    )


def play() -> bool:
    """
    Resume/play using the OS media key.

    Note:
        Most operating systems expose play/pause as a single
        toggle media key, so this may toggle rather than force
        playback.
    """
    return play_pause()


def pause() -> bool:
    """
    Pause/resume using the OS media key.

    The OS-level API generally exposes a toggle rather than
    separate guaranteed play/pause commands.
    """
    return play_pause()


def next_track() -> bool:
    """Skip to the next track."""
    return _press_media_key(
        "nexttrack",
        "skip to next track",
    )


def previous_track() -> bool:
    """Go to the previous track."""
    return _press_media_key(
        "prevtrack",
        "go to previous track",
    )


def stop() -> bool:
    """Stop media playback."""
    return _press_media_key(
        "stop",
        "stop playback",
    )


def volume_up() -> bool:
    """Increase system volume."""
    return _press_media_key(
        "volumeup",
        "increase volume",
    )


def volume_down() -> bool:
    """Decrease system volume."""
    return _press_media_key(
        "volumedown",
        "decrease volume",
    )


def volume_mute() -> bool:
    """Toggle system mute."""
    return _press_media_key(
        "volumemute",
        "toggle mute",
    )


# ============================================================================
# SPOTIFY CONTROLLER
# ============================================================================


class SpotifyController:
    """
    Thin, lazy wrapper around Spotipy/Spotify Web API.

    Spotify integration is completely optional.

    The object does not initialize Spotify authentication until
    a Spotify operation is actually requested.
    """

    def __init__(self) -> None:
        self._client: Any = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        """
        Lazily create the Spotify API client.
        """
        if self._client is not None:
            return self._client

        try:
            import spotipy  # type: ignore
            from spotipy.oauth2 import SpotifyOAuth  # type: ignore

        except ImportError as exc:
            raise SpotifyError(
                "Spotify integration requires 'spotipy'. "
                "Install it with: pip install spotipy"
            ) from exc

        client_id = get_env(
            "SPOTIFY_CLIENT_ID"
        )

        client_secret = get_env(
            "SPOTIFY_CLIENT_SECRET"
        )

        if not client_id:
            raise SpotifyError(
                "SPOTIFY_CLIENT_ID is missing "
                "from your environment."
            )

        if not client_secret:
            raise SpotifyError(
                "SPOTIFY_CLIENT_SECRET is missing "
                "from your environment."
            )

        try:
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SPOTIFY_SCOPES,
            )

            self._client = spotipy.Spotify(
                auth_manager=auth_manager
            )

            return self._client

        except Exception as exc:
            raise SpotifyError(
                f"Failed to initialize Spotify client: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Return True when Spotify dependencies and credentials
        are available.
        """
        try:
            self._ensure_client()
            return True

        except MusicControlError:
            return False

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_track(
        self,
        query: str,
    ) -> SpotifyTrack | None:
        """
        Search Spotify and return the best matching track.
        """
        query = _validate_query(query)

        client = self._ensure_client()

        try:
            results = client.search(
                q=query,
                type="track",
                limit=DEFAULT_SEARCH_LIMIT,
            )

        except Exception as exc:
            raise SpotifyError(
                f"Spotify track search failed: {exc}"
            ) from exc

        tracks = (
            results
            .get("tracks", {})
            .get("items", [])
        )

        if not tracks:
            logger.info(
                "No Spotify track found for '%s'.",
                query,
            )

            return None

        track = tracks[0]

        artists = ", ".join(
            artist.get("name", "")
            for artist in track.get(
                "artists",
                [],
            )
            if artist.get("name")
        )

        external_urls = track.get(
            "external_urls",
            {},
        )

        return SpotifyTrack(
            name=track.get("name", ""),
            artist=artists,
            uri=track.get("uri", ""),
            url=external_urls.get(
                "spotify",
                "",
            ),
            album=track.get(
                "album",
                {},
            ).get(
                "name",
                "",
            ),
            duration_ms=int(
                track.get(
                    "duration_ms",
                    0,
                )
                or 0
            ),
        )

    # ------------------------------------------------------------------
    # Device Management
    # ------------------------------------------------------------------

    def get_devices(self) -> list[SpotifyDevice]:
        """
        Return available Spotify playback devices.
        """
        client = self._ensure_client()

        try:
            response = client.devices()

        except Exception as exc:
            raise SpotifyError(
                f"Failed to retrieve Spotify devices: {exc}"
            ) from exc

        devices: list[SpotifyDevice] = []

        for device in response.get(
            "devices",
            [],
        ):
            devices.append(
                SpotifyDevice(
                    id=device.get("id", ""),
                    name=device.get("name", ""),
                    device_type=device.get(
                        "type",
                        "",
                    ),
                    is_active=bool(
                        device.get(
                            "is_active",
                            False,
                        )
                    ),
                    volume_percent=device.get(
                        "volume_percent"
                    ),
                )
            )

        return devices

    def get_active_device(
        self,
    ) -> SpotifyDevice | None:
        """
        Return the currently active Spotify device.
        """
        devices = self.get_devices()

        for device in devices:
            if device.is_active:
                return device

        return None

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play_track(
        self,
        query: str,
    ) -> SpotifyTrack:
        """
        Search for a track and start playback.
        """
        track = self.search_track(query)

        if track is None:
            raise SpotifyError(
                f"No Spotify track found matching "
                f"'{query}'."
            )

        client = self._ensure_client()

        try:
            client.start_playback(
                uris=[track.uri]
            )

        except Exception as exc:
            raise SpotifyError(
                f"Found '{track.name}' but could not "
                f"start Spotify playback. "
                f"Make sure a Spotify device is active. "
                f"Details: {exc}"
            ) from exc

        logger.info(
            "Playing Spotify track: %s - %s",
            track.artist,
            track.name,
        )

        return track

    def resume_playback(self) -> bool:
        """Resume Spotify playback."""
        client = self._ensure_client()

        try:
            client.start_playback()

            return True

        except Exception as exc:
            raise SpotifyError(
                f"Failed to resume Spotify playback: {exc}"
            ) from exc

    def pause_playback(self) -> bool:
        """Pause Spotify playback."""
        client = self._ensure_client()

        try:
            client.pause_playback()

            return True

        except Exception as exc:
            raise SpotifyError(
                f"Failed to pause Spotify playback: {exc}"
            ) from exc

    def next_track(self) -> bool:
        """Skip to the next Spotify track."""
        client = self._ensure_client()

        try:
            client.next_track()

            return True

        except Exception as exc:
            raise SpotifyError(
                f"Failed to skip Spotify track: {exc}"
            ) from exc

    def previous_track(self) -> bool:
        """Go to the previous Spotify track."""
        client = self._ensure_client()

        try:
            client.previous_track()

            return True

        except Exception as exc:
            raise SpotifyError(
                f"Failed to go to previous Spotify track: {exc}"
            ) from exc

    def set_volume(
        self,
        volume_percent: int,
    ) -> bool:
        """
        Set Spotify device volume.

        Args:
            volume_percent:
                0-100
        """
        if not 0 <= volume_percent <= 100:
            raise MusicValidationError(
                "Spotify volume must be between 0 and 100."
            )

        client = self._ensure_client()

        try:
            client.volume(
                volume_percent
            )

            return True

        except Exception as exc:
            raise SpotifyError(
                f"Failed to set Spotify volume: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Current Playback
    # ------------------------------------------------------------------

    def current_playback(self) -> dict[str, Any] | None:
        """
        Return current Spotify playback information.
        """
        client = self._ensure_client()

        try:
            return client.current_playback()

        except Exception as exc:
            raise SpotifyError(
                f"Failed to get Spotify playback state: {exc}"
            ) from exc


# ============================================================================
# SPOTIFY SINGLETON
# ============================================================================


spotify = SpotifyController()


# ============================================================================
# HIGH-LEVEL PLAYBACK API
# ============================================================================


def safe_next_music_track() -> bool:
    """Safely skip to the next music track without raising exceptions.

    Falls back to OS media keys if standard playback controls fail.

    Returns:
        bool: True if the skip command was issued successfully, False otherwise.
    """
    try:
        # 1. Try Spotify integration if available
        if spotify.is_available():
            spotify.next_track()
            return True
    except Exception as exc:
        logger.debug("Spotify next_track failed: %s. Falling back to media keys.", exc)

    try:
        # 2. Fall back to OS media key
        return next_track()
    except Exception as exc:
        logger.warning("Failed to skip to next music track: %s", exc)
        return False


def safe_pause_music() -> bool:
    """Safely pause music playback without raising exceptions.

    Attempts to pause active Spotify playback first, then falls back
    to system media keys if necessary.

    Returns:
        bool: True if the pause command was executed successfully, False otherwise.
    """
    try:
        if spotify.is_available():
            spotify.pause()
            return True
    except Exception as exc:
        logger.debug("Spotify pause failed: %s. Falling back to media keys.", exc)

    try:
        return pause()
    except Exception as exc:
        logger.warning("Failed to pause music playback: %s", exc)
        return False


def safe_play_music(query: str | None = None) -> bool:
    """Safely start or resume music playback without raising exceptions.

    Args:
        query: Optional search term or track name to play via Spotify/OS.

    Returns:
        bool: True if playback started successfully, False otherwise.
    """
    try:
        return bool(play_music(query=query))
    except MusicError as exc:
        logger.warning("Music playback failed for query '%s': %s", query, exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error during safe_play_music: %s", exc, exc_info=True)
        return False


def play_music(
    query: str | None = None,
) -> bool:
    """
    High-level music entry point.

    Behavior:
        - Query + Spotify available:
              Search and play the requested track.
        - Otherwise:
              Fall back to OS media-key play/pause.

    This is useful for AssistantX command routing.
    """
    if query:
        query = _validate_query(query)

        if spotify.is_available():
            try:
                spotify.play_track(
                    query
                )

                return True

            except MusicControlError as exc:
                logger.warning(
                    "Spotify playback failed: %s",
                    exc,
                )

    return play_pause()


def play(
    query: str | None = None,
) -> bool:
    """
    Backward-compatible high-level play function.
    """
    return play_music(query)


def search_and_play(
    query: str,
) -> SpotifyTrack:
    """
    Search Spotify and play a specific track.

    Unlike play_music(), this does not silently fall back
    to the OS media key.
    """
    return spotify.play_track(
        _validate_query(query)
    )


# ============================================================================
# SMART PLAYBACK HELPERS
# ============================================================================


def pause_music() -> bool:
    """
    Pause Spotify when available; otherwise use OS media key.
    """
    if spotify.is_available():
        try:
            return spotify.pause_playback()

        except MusicControlError as exc:
            logger.debug(
                "Spotify pause unavailable: %s",
                exc,
            )

    return pause()


def resume_music() -> bool:
    """
    Resume Spotify when available; otherwise use OS media key.
    """
    if spotify.is_available():
        try:
            return spotify.resume_playback()

        except MusicControlError as exc:
            logger.debug(
                "Spotify resume unavailable: %s",
                exc,
            )

    return play()


def next_music_track() -> bool:
    """
    Skip track using Spotify when possible,
    otherwise OS media key.
    """
    if spotify.is_available():
        try:
            return spotify.next_track()

        except MusicControlError as exc:
            logger.debug(
                "Spotify next-track unavailable: %s",
                exc,
            )

    return next_track()


def previous_music_track() -> bool:
    """
    Previous track using Spotify when possible,
    otherwise OS media key.
    """
    if spotify.is_available():
        try:
            return spotify.previous_track()

        except MusicControlError as exc:
            logger.debug(
                "Spotify previous-track unavailable: %s",
                exc,
            )

    return previous_track()


# ============================================================================
# SAFE API
# ============================================================================


def safe_play(
    query: str | None = None,
) -> bool:
    """
    Non-raising wrapper for AssistantX background/voice commands.
    """
    try:
        return play_music(query)

    except MusicControlError as exc:
        logger.warning(
            "Music playback failed: %s",
            exc,
        )

        return False

    except Exception as exc:
        logger.exception(
            "Unexpected music playback error: %s",
            exc,
        )

        return False


def safe_pause() -> bool:
    """Safe pause wrapper."""
    try:
        return pause_music()

    except Exception as exc:
        logger.warning(
            "Music pause failed: %s",
            exc,
        )

        return False

# UPDATED 

def safe_resume_music() -> bool:
    """Safely resume music playback without raising exceptions.

    Attempts to resume playback via Spotify first if active, then falls back
    to default high-level playback or media control wrappers.

    Returns:
        bool: True if resume command executed successfully, False otherwise.
    """
    try:
        if spotify.is_available():
            spotify.resume()
            return True
    except Exception as exc:
        logger.debug(
            "Spotify resume failed: %s. Falling back to safe playback wrapper.", 
            exc
        )

    try:
        return safe_play()
    except Exception as exc:
        logger.warning("Failed to resume music playback: %s", exc)
        return False
        

def safe_next_track() -> bool:
    """Safe next-track wrapper."""
    try:
        return next_music_track()

    except Exception as exc:
        logger.warning(
            "Next-track command failed: %s",
            exc,
        )

        return False


def safe_previous_track() -> bool:
    """Safe previous-track wrapper."""
    try:
        return previous_music_track()

    except Exception as exc:
        logger.warning(
            "Previous-track command failed: %s",
            exc,
        )

        return False

# Backward compatibility & import aliases for tests/__init__
safe_play_music = safe_play
safe_pause_music = safe_pause
safe_next_music_track = safe_next_track
safe_previous_music_track = safe_previous_track


# ============================================================================
# DIAGNOSTICS
# ============================================================================


def diagnostics() -> dict[str, Any]:
    """
    Return music subsystem diagnostics.
    """
    spotify_configured = bool(
        get_env("SPOTIFY_CLIENT_ID")
        and get_env("SPOTIFY_CLIENT_SECRET")
    )

    return {
        "media_key_available": is_media_key_available(),
        "spotify_configured": spotify_configured,
        "spotify_available": spotify.is_available(),
        "spotify_redirect_uri": SPOTIFY_REDIRECT_URI,
        "spotify_scopes": SPOTIFY_SCOPES,
    }
def music_diagnostics() -> dict[str, Any]:
    """Alias for music diagnostics."""
    return diagnostics()

music_diagnostics = diagnostics

# ============================================================================
# PUBLIC API
# ============================================================================


__all__ = [
    # Exceptions
    "MusicControlError",
    "MusicValidationError",
    "MusicBackendError",
    "SpotifyError",

    # Data models
    "SpotifyTrack",
    "SpotifyDevice",

    # OS media controls
    "play_pause",
    "play",
    "pause",
    "next_track",
    "previous_track",
    "stop",
    "volume_up",
    "volume_down",
    "volume_mute",

    # Spotify
    "SpotifyController",
    "spotify",

    # High-level API
    "play_music",
    "search_and_play",
    "pause_music",
    "resume_music",
    "next_music_track",
    "previous_music_track",

    # Safe API
    "safe_play",
    "safe_pause",
    "safe_next_track",
    "safe_previous_track",
    "safe_play_music",
    "safe_pause_music",
    "safe_resume_music",
    "safe_next_music_track",
    "safe_previous_music_track",


    # Availability
    "is_media_key_available",

    # Diagnostics
    "diagnostics",
    "music_diagnostics",
]
