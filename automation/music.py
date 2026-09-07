"""
music.py
========
Music playback control: OS-level media key simulation (play/pause/
next/previous/volume — works with whatever app currently owns media
focus, e.g. Spotify, Windows Media Player, browser tab playing audio)
plus optional direct Spotify Web API integration for more precise
control (search-and-play a specific track) when the user has connected
a Spotify account.

Falls back gracefully: if pyautogui (for media keys) or spotipy (for
the Web API) aren't available/configured, functions raise a clear
MusicControlError rather than crashing the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)


class MusicControlError(RuntimeError):
    """Raised when a music control action fails or is unavailable."""


# --------------------------------------------------------------------------- #
# OS-level media key simulation (works with whatever app has media focus)
# --------------------------------------------------------------------------- #

def _get_keyboard_backend():
    try:
        import pyautogui  # type: ignore

        return pyautogui
    except ImportError as exc:
        raise MusicControlError(
            "Media key simulation requires 'pyautogui'. Run: pip install pyautogui"
        ) from exc


def play_pause() -> bool:
    """Toggle play/pause on whichever app currently has media focus."""
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("playpause")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to toggle play/pause: {exc}") from exc


def pause() -> bool:
    """Alias for play_pause() — most OS media key APIs expose a single
    toggle key rather than distinct play/pause keys."""
    return play_pause()


def next_track() -> bool:
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("nexttrack")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to skip to next track: {exc}") from exc


def previous_track() -> bool:
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("prevtrack")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to go to previous track: {exc}") from exc


def stop() -> bool:
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("stop")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to stop playback: {exc}") from exc


def volume_up() -> bool:
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("volumeup")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to increase volume: {exc}") from exc


def volume_down() -> bool:
    pyautogui = _get_keyboard_backend()
    try:
        pyautogui.press("volumedown")
        return True
    except Exception as exc:  # noqa: BLE001
        raise MusicControlError(f"Failed to decrease volume: {exc}") from exc


# --------------------------------------------------------------------------- #
# Optional Spotify Web API integration (precise "play this specific song")
# --------------------------------------------------------------------------- #

@dataclass
class SpotifyTrack:
    name: str
    artist: str
    uri: str
    url: str


class SpotifyController:
    """
    Thin wrapper around `spotipy` for authenticated Spotify Web API
    control. Requires SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in the
    environment and an active Spotify Premium account with an open
    device (the Web API can't control playback on free-tier accounts or
    when no device is active).

    This is intentionally optional — automation.music's OS-media-key
    functions above work regardless of whether Spotify integration is
    configured, so "play/pause/skip" always works even without this.
    """

    def __init__(self) -> None:
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client

        try:
            import spotipy  # type: ignore
            from spotipy.oauth2 import SpotifyOAuth  # type: ignore
        except ImportError as exc:
            raise MusicControlError(
                "Spotify integration requires 'spotipy'. Run: pip install spotipy"
            ) from exc

        client_id = get_env("SPOTIFY_CLIENT_ID")
        client_secret = get_env("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise MusicControlError(
                "Spotify integration requires SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET in your .env file."
            )

        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://localhost:8888/callback",
            scope="user-modify-playback-state user-read-playback-state",
        )
        self._client = spotipy.Spotify(auth_manager=auth_manager)
        return self._client

    def is_available(self) -> bool:
        try:
            self._ensure_client()
            return True
        except MusicControlError:
            return False

    def search_track(self, query: str) -> Optional[SpotifyTrack]:
        client = self._ensure_client()
        try:
            results = client.search(q=query, type="track", limit=1)
        except Exception as exc:  # noqa: BLE001
            raise MusicControlError(f"Spotify search failed: {exc}") from exc

        items = results.get("tracks", {}).get("items", [])
        if not items:
            return None

        track = items[0]
        artists = ", ".join(a["name"] for a in track.get("artists", []))
        return SpotifyTrack(
            name=track["name"],
            artist=artists,
            uri=track["uri"],
            url=track["external_urls"].get("spotify", ""),
        )

    def play_track(self, query: str) -> SpotifyTrack:
        """Search for and immediately play a track on the user's active
        Spotify device."""
        track = self.search_track(query)
        if track is None:
            raise MusicControlError(f"No Spotify track found matching '{query}'.")

        client = self._ensure_client()
        try:
            client.start_playback(uris=[track.uri])
        except Exception as exc:  # noqa: BLE001
            raise MusicControlError(
                f"Found '{track.name}' but could not start playback (is Spotify open on a device?): {exc}"
            ) from exc

        logger.info("Playing Spotify track: %s - %s", track.artist, track.name)
        return track

    def pause_playback(self) -> bool:
        client = self._ensure_client()
        try:
            client.pause_playback()
            return True
        except Exception as exc:  # noqa: BLE001
            raise MusicControlError(f"Failed to pause Spotify playback: {exc}") from exc


# Module-level singleton — lazily connects on first real use, so simply
# importing this module has no side effects if Spotify isn't configured.
spotify: SpotifyController = SpotifyController()


def play(query: Optional[str] = None) -> bool:
    """
    High-level entry point used by core/command_router.py for the
    PLAY_MUSIC sub-intent: if a specific song/query is given and Spotify
    is configured, plays that exact track; otherwise falls back to a
    generic media-key play/pause toggle (resuming whatever was paused).
    """
    if query and spotify.is_available():
        try:
            spotify.play_track(query)
            return True
        except MusicControlError as exc:
            logger.warning("Spotify play failed (%s); falling back to media-key toggle.", exc)

    return play_pause()
    