"""
dashboard.profile
=================

Professional user/profile widget for AssistantX dashboard.

Features
--------
- User avatar
- Display name
- Username / role
- Online / offline / busy status
- Status indicator
- Edit profile callback
- Compact mode
- Click callback
- Theme-friendly styling
- Safe image loading
- Runtime updates
- Diagnostics
- Tkinter compatible
- No external dependency

Typical usage
-------------

    from dashboard.profile import (
        Profile,
        ProfileData,
        ProfileStatus,
    )

    profile = Profile(
        parent,
        profile=ProfileData(
            name="User",
            username="@user",
            role="AssistantX User",
            status=ProfileStatus.ONLINE,
        ),
    )

    profile.pack(fill="x")
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

# ============================================================================
# Exceptions
# ============================================================================


class ProfileError(Exception):
    """Base exception for profile errors."""


class ProfileConfigurationError(ProfileError):
    """Raised when profile configuration is invalid."""


class ProfileStateError(ProfileError):
    """Raised when an operation is invalid for the current state."""


# ============================================================================
# Enums
# ============================================================================


class ProfileStatus(str, Enum):
    """Profile presence status."""

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    AWAY = "away"
    DO_NOT_DISTURB = "do_not_disturb"


class ProfileState(str, Enum):
    """Runtime widget state."""

    READY = "ready"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


# ============================================================================
# Profile Data
# ============================================================================


@dataclass(frozen=True)
class ProfileData:
    """Immutable profile information."""

    name: str = "User"
    username: str = ""
    role: str = "AssistantX User"

    status: ProfileStatus = ProfileStatus.ONLINE
    status_text: str = ""

    avatar_path: str | None = None

    initials: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ProfileConfigurationError(
                "name must be a string."
            )

        if not isinstance(self.username, str):
            raise ProfileConfigurationError(
                "username must be a string."
            )

        if not isinstance(self.role, str):
            raise ProfileConfigurationError(
                "role must be a string."
            )


@dataclass(frozen=True)
class ProfileConfig:
    """Visual configuration for the profile widget."""

    background: str = "#171717"
    foreground: str = "#F5F5F5"

    secondary_foreground: str = "#9CA3AF"

    border_color: str = "#303030"
    hover_border_color: str = "#5B8CFF"

    avatar_background: str = "#2563EB"
    avatar_foreground: str = "#FFFFFF"

    online_color: str = "#22C55E"
    offline_color: str = "#6B7280"
    busy_color: str = "#EF4444"
    away_color: str = "#F59E0B"
    dnd_color: str = "#DC2626"

    edit_background: str = "#2A2A2A"
    edit_foreground: str = "#DADADA"
    edit_hover_background: str = "#3A3A3A"

    name_font: tuple[str, int] = (
        "Segoe UI Semibold",
        10,
    )

    username_font: tuple[str, int] = (
        "Segoe UI",
        8,
    )

    role_font: tuple[str, int] = (
        "Segoe UI",
        8,
    )

    status_font: tuple[str, int] = (
        "Segoe UI",
        8,
    )

    avatar_font: tuple[str, int] = (
        "Segoe UI Semibold",
        12,
    )

    edit_font: tuple[str, int] = (
        "Segoe UI",
        8,
    )

    avatar_size: int = 42

    padding_x: int = 10
    padding_y: int = 8

    show_username: bool = True
    show_role: bool = True
    show_status: bool = True
    show_edit_button: bool = False

    compact: bool = False

    def __post_init__(self) -> None:
        if self.avatar_size <= 0:
            raise ProfileConfigurationError(
                "avatar_size must be greater than zero."
            )

        if self.padding_x < 0:
            raise ProfileConfigurationError(
                "padding_x cannot be negative."
            )

        if self.padding_y < 0:
            raise ProfileConfigurationError(
                "padding_y cannot be negative."
            )


@dataclass
class ProfileStats:
    """Runtime profile statistics."""

    clicks: int = 0
    edit_clicks: int = 0
    status_updates: int = 0
    profile_updates: int = 0
    hover_events: int = 0


# ============================================================================
# Helper Functions
# ============================================================================


def normalize_name(value: str) -> str:
    """Normalize display name."""

    if not isinstance(value, str):
        return ""

    return " ".join(
        value.strip().split()
    )


def generate_initials(name: str) -> str:
    """Generate profile initials from display name."""

    name = normalize_name(name)

    if not name:
        return "U"

    parts = name.split()

    if len(parts) == 1:
        return parts[0][:2].upper()

    return (
        parts[0][0]
        + parts[-1][0]
    ).upper()


def status_color(
    status: ProfileStatus,
    config: ProfileConfig,
) -> str:
    """Return color associated with profile status."""

    return {
        ProfileStatus.ONLINE: config.online_color,
        ProfileStatus.OFFLINE: config.offline_color,
        ProfileStatus.BUSY: config.busy_color,
        ProfileStatus.AWAY: config.away_color,
        ProfileStatus.DO_NOT_DISTURB: config.dnd_color,
    }.get(
        status,
        config.offline_color,
    )


def status_label(
    status: ProfileStatus,
) -> str:
    """Return human-readable status label."""

    return {
        ProfileStatus.ONLINE: "Online",
        ProfileStatus.OFFLINE: "Offline",
        ProfileStatus.BUSY: "Busy",
        ProfileStatus.AWAY: "Away",
        ProfileStatus.DO_NOT_DISTURB: "Do Not Disturb",
    }.get(
        status,
        "Offline",
    )


def normalize_status(
    status: ProfileStatus | str,
) -> ProfileStatus:
    """Convert status to ProfileStatus."""

    if isinstance(status, ProfileStatus):
        return status

    try:
        return ProfileStatus(
            str(status).strip().lower()
        )
    except ValueError as exc:
        raise ProfileConfigurationError(
            f"Unsupported profile status: {status!r}"
        ) from exc


# ============================================================================
# Profile Widget
# ============================================================================


class Profile(tk.Frame):
    """
    Professional AssistantX profile widget.

    Parameters
    ----------
    parent:
        Parent Tkinter widget.

    profile:
        ProfileData instance.

    config:
        Optional ProfileConfig.

    on_click:
        Called when the profile is clicked.

    on_edit:
        Called when edit button is clicked.
    """

    def __init__(
        self,
        parent: tk.Misc,
        profile: ProfileData | None = None,
        config: ProfileConfig | None = None,
        on_click: Callable[[ProfileData], Any] | None = None,
        on_edit: Callable[[ProfileData], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._config = (
            config or ProfileConfig()
        )

        super().__init__(
            parent,
            bg=self._config.background,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self._lock = RLock()

        self._profile = (
            profile or ProfileData()
        )

        self._on_click = on_click
        self._on_edit = on_edit

        self._state = ProfileState.READY
        self._destroyed = False
        self._hovered = False

        self._avatar_image: tk.PhotoImage | None = None

        self._stats = ProfileStats()

        self._build_ui()
        self._bind_events()
        self._refresh()

    # ----------------------------------------------------------------------
    # UI Construction
    # ----------------------------------------------------------------------

    def _build_ui(self) -> None:
        cfg = self._config

        self._container = tk.Frame(
            self,
            bg=cfg.background,
            bd=1,
            relief="solid",
            highlightthickness=0,
        )

        self._container.pack(
            fill="both",
            expand=True,
        )

        self._avatar_frame = tk.Frame(
            self._container,
            width=cfg.avatar_size,
            height=cfg.avatar_size,
            bg=cfg.avatar_background,
            bd=0,
        )

        self._avatar_frame.pack(
            side="left",
            padx=cfg.padding_x,
            pady=cfg.padding_y,
        )

        self._avatar_frame.pack_propagate(
            False
        )

        self._avatar = tk.Label(
            self._avatar_frame,
            font=cfg.avatar_font,
            bg=cfg.avatar_background,
            fg=cfg.avatar_foreground,
            anchor="center",
        )

        self._avatar.pack(
            fill="both",
            expand=True,
        )

        self._info = tk.Frame(
            self._container,
            bg=cfg.background,
        )

        self._info.pack(
            side="left",
            fill="both",
            expand=True,
            pady=cfg.padding_y,
        )

        self._name_label = tk.Label(
            self._info,
            font=cfg.name_font,
            bg=cfg.background,
            fg=cfg.foreground,
            anchor="w",
        )

        self._name_label.pack(
            anchor="w",
        )

        self._username_label = tk.Label(
            self._info,
            font=cfg.username_font,
            bg=cfg.background,
            fg=cfg.secondary_foreground,
            anchor="w",
        )

        if cfg.show_username:
            self._username_label.pack(
                anchor="w",
            )

        self._role_label = tk.Label(
            self._info,
            font=cfg.role_font,
            bg=cfg.background,
            fg=cfg.secondary_foreground,
            anchor="w",
        )

        if cfg.show_role and not cfg.compact:
            self._role_label.pack(
                anchor="w",
            )

        self._status_frame = tk.Frame(
            self._info,
            bg=cfg.background,
        )

        if cfg.show_status:
            self._status_frame.pack(
                anchor="w",
                pady=(2, 0),
            )

        self._status_indicator = tk.Canvas(
            self._status_frame,
            width=8,
            height=8,
            bg=cfg.background,
            highlightthickness=0,
            bd=0,
        )

        self._status_indicator.pack(
            side="left",
            padx=(0, 4),
        )

        self._status_label = tk.Label(
            self._status_frame,
            font=cfg.status_font,
            bg=cfg.background,
            fg=cfg.secondary_foreground,
            anchor="w",
        )

        self._status_label.pack(
            side="left",
        )

        if cfg.show_edit_button:
            self._edit_button = tk.Button(
                self._container,
                text="Edit",
                command=self._edit,
                font=cfg.edit_font,
                bg=cfg.edit_background,
                fg=cfg.edit_foreground,
                activebackground=cfg.edit_hover_background,
                activeforeground=cfg.edit_foreground,
                relief="flat",
                bd=0,
                cursor="hand2",
                padx=8,
                pady=4,
            )

            self._edit_button.pack(
                side="right",
                padx=(4, cfg.padding_x),
            )
        else:
            self._edit_button = None

    # ----------------------------------------------------------------------
    # Events
    # ----------------------------------------------------------------------

    def _bind_events(self) -> None:
        widgets = (
            self,
            self._container,
            self._avatar_frame,
            self._avatar,
            self._info,
            self._name_label,
            self._username_label,
            self._role_label,
            self._status_frame,
            self._status_indicator,
            self._status_label,
        )

        for widget in widgets:
            try:
                widget.bind(
                    "<Button-1>",
                    self._handle_click,
                    add="+",
                )

                widget.bind(
                    "<Enter>",
                    self._on_enter,
                    add="+",
                )

                widget.bind(
                    "<Leave>",
                    self._on_leave,
                    add="+",
                )
            except tk.TclError:
                pass

    def _handle_click(
        self,
        _event: tk.Event,
    ) -> None:
        if self._destroyed:
            return

        if self._state != ProfileState.READY:
            return

        with self._lock:
            self._stats.clicks += 1

        if self._on_click is not None:
            self._on_click(
                self._profile
            )

    def _on_enter(
        self,
        _event: tk.Event,
    ) -> None:
        if self._destroyed:
            return

        self._hovered = True

        with self._lock:
            self._stats.hover_events += 1

        self._refresh_border()

    def _on_leave(
        self,
        _event: tk.Event,
    ) -> None:
        if self._destroyed:
            return

        self._hovered = False
        self._refresh_border()

    # ----------------------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._destroyed:
            return

        cfg = self._config
        profile = self._profile

        background = cfg.background
        initials = (
            profile.initials
            or generate_initials(
                profile.name
            )
        )

        try:
            self.configure(
                bg=background,
            )

            self._container.configure(
                bg=background,
            )

            self._info.configure(
                bg=background,
            )

            self._avatar_frame.configure(
                bg=cfg.avatar_background,
            )

            self._avatar.configure(
                bg=cfg.avatar_background,
                fg=cfg.avatar_foreground,
                text=initials,
            )

            self._name_label.configure(
                bg=background,
                fg=cfg.foreground,
                text=profile.name or "User",
            )

            self._username_label.configure(
                bg=background,
                fg=cfg.secondary_foreground,
                text=profile.username,
            )

            self._role_label.configure(
                bg=background,
                fg=cfg.secondary_foreground,
                text=profile.role,
            )

            self._status_frame.configure(
                bg=background,
            )

            self._status_label.configure(
                bg=background,
                fg=cfg.secondary_foreground,
                text=(
                    profile.status_text
                    or status_label(
                        profile.status
                    )
                ),
            )

            self._status_indicator.configure(
                bg=background,
            )

            self._status_indicator.delete(
                "all"
            )

            color = status_color(
                profile.status,
                cfg,
            )

            self._status_indicator.create_oval(
                1,
                1,
                7,
                7,
                fill=color,
                outline="",
            )

        except tk.TclError:
            pass

        self._load_avatar()
        self._refresh_border()

    # ----------------------------------------------------------------------
    # Avatar
    # ----------------------------------------------------------------------

    def _load_avatar(self) -> None:
        profile = self._profile

        if not profile.avatar_path:
            self._avatar_image = None
            return

        path = Path(
            profile.avatar_path
        ).expanduser()

        if not path.is_file():
            return

        try:
            image = tk.PhotoImage(
                file=str(path)
            )

            self._avatar_image = image

            self._avatar.configure(
                image=image,
                text="",
            )

        except (tk.TclError, OSError):
            # Keep initials fallback.
            self._avatar_image = None

    # ----------------------------------------------------------------------
    # Border
    # ----------------------------------------------------------------------

    def _refresh_border(self) -> None:
        if self._destroyed:
            return

        color = (
            self._config.hover_border_color
            if self._hovered
            else self._config.border_color
        )

        with contextlib.suppress(tk.TclError):
            self._container.configure(
                highlightbackground=color,
                highlightcolor=color,
                highlightthickness=1,
            )

    # ----------------------------------------------------------------------
    # Profile Updates
    # ----------------------------------------------------------------------

    def update_profile(
        self,
        profile: ProfileData,
    ) -> None:
        """Replace the complete profile."""

        if self._destroyed:
            raise ProfileStateError(
                "Cannot update destroyed Profile."
            )

        if not isinstance(
            profile,
            ProfileData,
        ):
            raise TypeError(
                "profile must be ProfileData."
            )

        self._profile = profile

        with self._lock:
            self._stats.profile_updates += 1

        self._refresh()

    def update_name(
        self,
        name: str,
    ) -> None:
        """Update display name."""

        self._replace_profile(
            name=normalize_name(name)
        )

    def update_username(
        self,
        username: str,
    ) -> None:
        """Update username."""

        self._replace_profile(
            username=str(
                username
            ).strip()
        )

    def update_role(
        self,
        role: str,
    ) -> None:
        """Update profile role."""

        self._replace_profile(
            role=str(
                role
            ).strip()
        )

    def update_avatar(
        self,
        avatar_path: str | None,
    ) -> None:
        """Update avatar path."""

        self._replace_profile(
            avatar_path=avatar_path
        )

    def update_status(
        self,
        status: ProfileStatus | str,
        status_text: str = "",
    ) -> None:
        """Update online/presence status."""

        normalized = normalize_status(
            status
        )

        self._replace_profile(
            status=normalized,
            status_text=status_text.strip(),
        )

        with self._lock:
            self._stats.status_updates += 1

    def _replace_profile(
        self,
        **changes: Any,
    ) -> None:
        current = self._profile

        values = {
            "name": current.name,
            "username": current.username,
            "role": current.role,
            "status": current.status,
            "status_text": current.status_text,
            "avatar_path": current.avatar_path,
            "initials": current.initials,
        }

        values.update(changes)

        self._profile = ProfileData(
            **values
        )

        with self._lock:
            self._stats.profile_updates += 1

        self._refresh()

    # ----------------------------------------------------------------------
    # Edit
    # ----------------------------------------------------------------------

    def _edit(self) -> None:
        if self._destroyed:
            return

        with self._lock:
            self._stats.edit_clicks += 1

        if self._on_edit is not None:
            self._on_edit(
                self._profile
            )

    # ----------------------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------------------

    def set_compact(
        self,
        compact: bool = True,
    ) -> None:
        """Switch compact layout."""

        if self._destroyed:
            return

        self._config = ProfileConfig(
            **{
                **self._config.__dict__,
                "compact": bool(
                    compact
                ),
            }
        )

        if compact:
            with contextlib.suppress(tk.TclError):
                self._role_label.pack_forget()
        else:
            if self._config.show_role:
                with contextlib.suppress(tk.TclError):
                    self._role_label.pack(
                        anchor="w"
                    )

        self._refresh()

    def set_enabled(
        self,
        enabled: bool = True,
    ) -> None:
        """Enable or disable interaction."""

        if self._destroyed:
            return

        self._state = (
            ProfileState.READY
            if enabled
            else ProfileState.DISABLED
        )

        if self._edit_button is not None:
            with contextlib.suppress(tk.TclError):
                self._edit_button.configure(
                    state=(
                        "normal"
                        if enabled
                        else "disabled"
                    )
                )

    # ----------------------------------------------------------------------
    # Accessors
    # ----------------------------------------------------------------------

    @property
    def profile(self) -> ProfileData:
        """Return current profile."""

        return self._profile

    @property
    def state(self) -> ProfileState:
        """Return widget state."""

        return self._state

    def get_name(self) -> str:
        return self._profile.name

    def get_username(self) -> str:
        return self._profile.username

    def get_role(self) -> str:
        return self._profile.role

    def get_status(self) -> ProfileStatus:
        return self._profile.status

    # ----------------------------------------------------------------------
    # Callbacks
    # ----------------------------------------------------------------------

    def set_on_click(
        self,
        callback: Callable[[ProfileData], Any] | None,
    ) -> None:
        """Set profile click callback."""

        if (
            callback is not None
            and not callable(callback)
        ):
            raise TypeError(
                "callback must be callable or None."
            )

        self._on_click = callback

    def set_on_edit(
        self,
        callback: Callable[[ProfileData], Any] | None,
    ) -> None:
        """Set edit callback."""

        if (
            callback is not None
            and not callable(callback)
        ):
            raise TypeError(
                "callback must be callable or None."
            )

        self._on_edit = callback

    # ----------------------------------------------------------------------
    # Stats / Diagnostics
    # ----------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return runtime statistics."""

        with self._lock:
            return {
                "clicks": self._stats.clicks,
                "edit_clicks": self._stats.edit_clicks,
                "status_updates": (
                    self._stats.status_updates
                ),
                "profile_updates": (
                    self._stats.profile_updates
                ),
                "hover_events": (
                    self._stats.hover_events
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return profile diagnostics."""

        return {
            "component": "Profile",
            "state": self._state.value,
            "destroyed": self._destroyed,
            "name": self._profile.name,
            "username": self._profile.username,
            "role": self._profile.role,
            "status": self._profile.status.value,
            "has_avatar": bool(
                self._profile.avatar_path
            ),
            "avatar_exists": (
                bool(
                    self._profile.avatar_path
                )
                and Path(
                    self._profile.avatar_path
                ).expanduser().is_file()
            ),
            "compact": self._config.compact,
            "has_click_callback": (
                self._on_click is not None
            ),
            "has_edit_callback": (
                self._on_edit is not None
            ),
            "stats": self.stats(),
        }

    # ----------------------------------------------------------------------
    # Destroy
    # ----------------------------------------------------------------------

    def destroy(self) -> None:
        """Safely destroy profile widget."""

        if self._destroyed:
            return

        self._destroyed = True
        self._state = ProfileState.DESTROYED

        self._on_click = None
        self._on_edit = None
        self._avatar_image = None

        with contextlib.suppress(tk.TclError):
            super().destroy()


# ============================================================================
# Factory Helpers
# ============================================================================


def create_profile(
    parent: tk.Misc,
    name: str = "User",
    username: str = "",
    role: str = "AssistantX User",
    status: ProfileStatus | str = ProfileStatus.ONLINE,
    **kwargs: Any,
) -> Profile:
    """Create a profile widget quickly."""

    data = ProfileData(
        name=name,
        username=username,
        role=role,
        status=normalize_status(status),
    )

    return Profile(
        parent,
        profile=data,
        **kwargs,
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "Profile",
    "ProfileConfig",
    "ProfileConfigurationError",
    "ProfileData",
    "ProfileError",
    "ProfileState",
    "ProfileStateError",
    "ProfileStats",
    "ProfileStatus",
    "create_profile",
    "generate_initials",
    "normalize_name",
    "normalize_status",
    "status_color",
    "status_label",
]
