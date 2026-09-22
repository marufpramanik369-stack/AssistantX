"""
update_service.py
==================
Checks whether a newer version of AssistantX is available, by querying
a GitHub repository's Releases API (https://docs.github.com/en/rest/releases)
— chosen since it requires no API key for public repos and is a common,
low-friction distribution channel for desktop apps.

The target repository is configurable via the UPDATE_CHECK_REPO
environment variable (format: "owner/repo"), so this module works
out of the box for AssistantX's own repo but can be pointed at a fork
or private distribution mirror without code changes.

Version comparison uses simple (major, minor, patch) tuple comparison
against config.constants.APP_VERSION_TUPLE — sufficient for standard
semantic versioning without needing the third-party `packaging` library
for this one comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.constants import (
    APP_VERSION,
    APP_VERSION_TUPLE,
    HTTP_USER_AGENT,
    REQUEST_TIMEOUT_SECONDS,
)
from config.env_loader import get_env
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_HOURS = 6
_DEFAULT_REPO = "assistantx-project/assistantx"  # placeholder; override via UPDATE_CHECK_REPO
_GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/{repo}/releases/latest"
_VERSION_TAG_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


class UpdateServiceError(RuntimeError):
    """Raised when the update check itself fails (network error, malformed
    response) — NOT raised when simply no update is available, which is
    represented by check_for_updates() returning None."""


@dataclass
class UpdateInfo:
    version: str
    version_tuple: tuple[int, int, int]
    release_notes: str
    download_url: str | None
    published_at: datetime | None
    html_url: str

    @property
    def is_newer_than_current(self) -> bool:
        return self.version_tuple > APP_VERSION_TUPLE

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "release_notes": self.release_notes,
            "download_url": self.download_url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "html_url": self.html_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> UpdateInfo:
        published = datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None
        version_tuple = _parse_version_tuple(data["version"]) or (0, 0, 0)
        return cls(
            version=data["version"],
            version_tuple=version_tuple,
            release_notes=data["release_notes"],
            download_url=data.get("download_url"),
            published_at=published,
            html_url=data["html_url"],
        )


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise UpdateServiceError(
            "Update checks require the 'requests' package. Run: pip install requests"
        ) from exc


def _parse_version_tuple(tag_or_version: str) -> tuple[int, int, int] | None:
    """Extract (major, minor, patch) from a version string or git tag
    like 'v1.2.3' or '1.2.3'."""
    match = _VERSION_TAG_PATTERN.search(tag_or_version)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _target_repo() -> str:
    return get_env("UPDATE_CHECK_REPO", default=_DEFAULT_REPO) or _DEFAULT_REPO


def _cache_key() -> str:
    return f"update_check:{_target_repo()}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)).isoformat()


def _try_get_cached():
    try:
        from database import db_manager

        return db_manager.get_cache(_cache_key())
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization, never fatal
        logger.debug("Update-check cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(_cache_key(), value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write update-check cache (%s); continuing without caching.", exc)


def _select_download_asset(assets: list[dict]) -> str | None:
    """
    Pick the most relevant release asset URL for the current platform,
    preferring an installer/archive whose filename hints at the running
    OS; falls back to the first available asset if no platform-specific
    match is found.
    """
    from config.constants import IS_LINUX, IS_MAC, IS_WINDOWS

    if not assets:
        return None

    platform_hints = (
        ("win", "exe", "msi") if IS_WINDOWS else
        ("mac", "dmg", "darwin") if IS_MAC else
        ("linux", "appimage", "deb", "tar.gz") if IS_LINUX else
        ()
    )

    for asset in assets:
        name_lower = asset.get("name", "").lower()
        if any(hint in name_lower for hint in platform_hints):
            return asset.get("browser_download_url")

    return assets[0].get("browser_download_url")


def check_for_updates(force_refresh: bool = False) -> UpdateInfo | None:
    """
    Check the configured GitHub repository for a newer release than the
    currently running version.

    Args:
        force_refresh: Bypass the cache and query GitHub directly, even
            if a recent cached result exists.

    Returns:
        UpdateInfo if a newer version is available, otherwise None (this
        includes the case where the latest release IS the current
        version, or an older one — not an error condition).

    Raises:
        UpdateServiceError: if the update check request itself fails
            (network error, repo not found, malformed API response).
    """
    if not force_refresh:
        cached = _try_get_cached()
        if cached is not None:
            if cached == {}:
                return None
            return UpdateInfo.from_dict(cached)

    requests = _get_requests()
    repo = _target_repo()
    url = _GITHUB_LATEST_RELEASE_URL.format(repo=repo)

    try:
        response = requests.get(
            url,
            headers={"User-Agent": HTTP_USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            raise UpdateServiceError(f"Repository '{repo}' has no releases, or does not exist.")
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateServiceError(f"Update check request failed: {exc}") from exc

    data = response.json()
    tag_name = data.get("tag_name", "")
    version_tuple = _parse_version_tuple(tag_name)

    if version_tuple is None:
        raise UpdateServiceError(f"Could not parse version from release tag '{tag_name}'.")

    published_at = None
    published_raw = data.get("published_at")
    if published_raw:
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    info = UpdateInfo(
        version=".".join(str(v) for v in version_tuple),
        version_tuple=version_tuple,
        release_notes=(data.get("body") or "").strip(),
        download_url=_select_download_asset(data.get("assets", [])),
        published_at=published_at,
        html_url=data.get("html_url", ""),
    )

    if info.is_newer_than_current:
        logger.info("Update available: %s -> %s", APP_VERSION, info.version)
        _try_set_cached(info.to_dict())
        return info

    logger.debug("No update available. Current=%s, latest=%s.", APP_VERSION, info.version)
    _try_set_cached({})
    return None


def download_update(update_info: UpdateInfo, destination_dir: str | None = None) -> Path:
    """
    Download the platform-appropriate release asset for `update_info`
    to disk. Does NOT install it — installation is inherently
    platform/packaging-specific (see build_exe.py / setup.py) and is
    left to the caller or the user running the downloaded installer
    themselves.

    Raises:
        UpdateServiceError: if no download URL is available for this
            platform, or the download fails.
    """
    if not update_info.download_url:
        raise UpdateServiceError(
            f"No downloadable asset found for this platform in release {update_info.version}. "
            f"Visit {update_info.html_url} to download manually."
        )

    requests = _get_requests()
    target_dir = Path(destination_dir) if destination_dir else (Path.home() / "Downloads")
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = update_info.download_url.rsplit("/", 1)[-1] or f"assistantx-{update_info.version}"
    destination = target_dir / filename

    try:
        with requests.get(update_info.download_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with destination.open("wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))
    except requests.RequestException as exc:
        raise UpdateServiceError(f"Failed to download update: {exc}") from exc
    except OSError as exc:
        raise UpdateServiceError(f"Failed to save update to '{destination}': {exc}") from exc

    logger.info("Downloaded update %s to %s.", update_info.version, destination)
    return destination


def get_current_version() -> str:
    return APP_VERSION


def is_available() -> bool:
    """Check whether update checks are usable (the 'requests' package is
    installed) — does not verify network reachability."""
    try:
        _get_requests()
        return True
    except UpdateServiceError:
        return False
