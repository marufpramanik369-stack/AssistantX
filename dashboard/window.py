"""
dashboard.window
===============

Professional main-window management for AssistantX.

Features
--------
- Centralized Tk root/window configuration
- Minimum/maximum window size
- Centering
- Remember/restore geometry
- Maximize / restore
- Minimize
- Fullscreen
- Always-on-top
- Close confirmation hook
- Theme application
- Window state tracking
- Safe callbacks
- Diagnostics
- No external dependencies

Typical usage
-------------

    from dashboard.window import AssistantXWindow

    window = AssistantXWindow(
        title="AssistantX",
        width=1280,
        height=800,
    )

    root = window.root

    # Build dashboard UI here...

    window.show()

"""

from __future__ import annotations

import logging
import platform
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================================
# Exceptions
# ============================================================================


class WindowError(Exception):
    """Base exception for window errors."""


class WindowConfigurationError(WindowError):
    """Raised when window configuration is invalid."""


class WindowStateError(WindowError):
    """Raised when an invalid window operation is requested."""


# ============================================================================
# Enums
# ============================================================================


class WindowState(str, Enum):
    """Main window states."""

    CREATED = "created"
    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    FULLSCREEN = "fullscreen"
    CLOSING = "closing"
    CLOSED = "closed"


# ============================================================================
# Configuration
# ============================================================================


@dataclass(frozen=True, slots=True)
class WindowConfig:
    """Configuration for the AssistantX main window."""

    title: str = "AssistantX"

    width: int = 1280
    height: int = 800

    min_width: int = 960
    min_height: int = 600

    max_width: int | None = None
    max_height: int | None = None

    resizable_width: bool = True
    resizable_height: bool = True

    center: bool = True

    background: str = "#0B1120"

    icon_path: str | None = None

    fullscreen: bool = False
    always_on_top: bool = False

    remember_geometry: bool = True

    confirm_close: bool = False

    close_text: str = "Are you sure you want to exit AssistantX?"

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise WindowConfigurationError(
                "width must be greater than zero."
            )

        if self.height <= 0:
            raise WindowConfigurationError(
                "height must be greater than zero."
            )

        if self.min_width <= 0 or self.min_height <= 0:
            raise WindowConfigurationError(
                "Minimum dimensions must be greater than zero."
            )

        if self.max_width is not None and self.max_width < self.min_width:
            raise WindowConfigurationError(
                "max_width cannot be smaller than min_width."
            )

        if self.max_height is not None and self.max_height < self.min_height:
            raise WindowConfigurationError(
                "max_height cannot be smaller than min_height."
            )


@dataclass(slots=True)
class WindowStats:
    """Runtime statistics."""

    show_count: int = 0
    close_count: int = 0
    maximize_count: int = 0
    restore_count: int = 0
    minimize_count: int = 0
    fullscreen_count: int = 0
    geometry_changes: int = 0

    def snapshot(self) -> dict:
        return {
            "show_count": self.show_count,
            "close_count": self.close_count,
            "maximize_count": self.maximize_count,
            "restore_count": self.restore_count,
            "minimize_count": self.minimize_count,
            "fullscreen_count": self.fullscreen_count,
            "geometry_changes": self.geometry_changes,
        }


# ============================================================================
# Main Window
# ============================================================================


class AssistantXWindow:
    """
    Professional lifecycle manager for the AssistantX root window.

    This class intentionally separates window management from dashboard
    content. `app.py` can build the UI inside `window.root`.
    """

    def __init__(
        self,
        *,
        config: WindowConfig | None = None,
        root: tk.Tk | None = None,
        on_close: Callable[[], None] | None = None,
        confirm_close: Callable[[], bool] | None = None,
        on_state_change: Callable[[WindowState], None] | None = None,
    ) -> None:
        self.config = config or WindowConfig()

        self._lock = threading.RLock()

        self._root = root or tk.Tk()

        self._state = WindowState.CREATED
        self._closed = False
        self._fullscreen = False
        self._maximized = False

        self._on_close = on_close
        self._confirm_close_callback = confirm_close
        self._on_state_change = on_state_change

        self._last_geometry: str | None = None
        self._normal_geometry: str | None = None

        self._stats = WindowStats()

        self._configure_root()
        self._bind_events()

    # ------------------------------------------------------------------
    # Root
    # ------------------------------------------------------------------

    @property
    def root(self) -> tk.Tk:
        """Return the managed Tk root."""
        return self._root

    @property
    def state(self) -> WindowState:
        with self._lock:
            return self._state

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _configure_root(self) -> None:
        root = self._root
        cfg = self.config

        try:
            root.title(cfg.title)

            root.configure(
                bg=cfg.background
            )

            root.resizable(
                cfg.resizable_width,
                cfg.resizable_height,
            )

            root.minsize(
                cfg.min_width,
                cfg.min_height,
            )

            if cfg.max_width is not None:
                root.maxsize(
                    cfg.max_width,
                    cfg.max_height
                    if cfg.max_height is not None
                    else 10000,
                )
            elif cfg.max_height is not None:
                root.maxsize(
                    10000,
                    cfg.max_height,
                )

            root.geometry(
                f"{cfg.width}x{cfg.height}"
            )

            root.attributes(
                "-topmost",
                bool(cfg.always_on_top),
            )

            if cfg.icon_path:
                self._set_icon(cfg.icon_path)

            if cfg.fullscreen:
                self.set_fullscreen(True)

            if cfg.center:
                self.center()

        except tk.TclError as exc:
            raise WindowConfigurationError(
                f"Failed to configure main window: {exc}"
            ) from exc

    def _set_icon(self, path: str) -> bool:
        try:
            icon = tk.PhotoImage(
                file=path
            )

            self._root.iconphoto(
                True,
                icon,
            )

            self._icon = icon

            return True

        except (tk.TclError, OSError):
            return False

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _bind_events(self) -> None:
        self._root.protocol(
            "WM_DELETE_WINDOW",
            self.close,
        )

        self._root.bind(
            "<Configure>",
            self._on_configure,
            add="+",
        )

        self._root.bind(
            "<F11>",
            lambda _event: self.toggle_fullscreen(),
            add="+",
        )

        self._root.bind(
            "<Escape>",
            self._handle_escape,
            add="+",
        )

    def _on_configure(self, _event=None) -> None:
        with self._lock:
            if self._closed:
                return

            try:
                geometry = self._root.geometry()

                if geometry != self._last_geometry:
                    self._last_geometry = geometry
                    self._stats.geometry_changes += 1

                    if not self._fullscreen and not self._maximized:
                        self._normal_geometry = geometry

            except tk.TclError:
                return

    def _handle_escape(self, _event=None) -> None:
        if self._fullscreen:
            self.set_fullscreen(False)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _set_state(self, state: WindowState) -> None:
        with self._lock:
            if self._state == state:
                return

            self._state = state
            callback = self._on_state_change

        if callback:
            try:
                callback(state)
            except (RuntimeError, tk.TclError):
                logger.exception("Window state-change callback failed")

    # ------------------------------------------------------------------
    # Show / Hide
    # ------------------------------------------------------------------

    def show(self, *, run_mainloop: bool = True) -> None:
        """
        Show the window.

        Set `run_mainloop=False` when another application lifecycle
        controls Tk's mainloop.
        """

        self._ensure_alive()

        with self._lock:
            try:
                self._root.deiconify()
                self._root.lift()

                if self.config.always_on_top:
                    self._root.attributes(
                        "-topmost",
                        True,
                    )

                self._root.update_idletasks()

                self._stats.show_count += 1

                if self._fullscreen:
                    self._set_state(
                        WindowState.FULLSCREEN
                    )
                elif self._maximized:
                    self._set_state(
                        WindowState.MAXIMIZED
                    )
                else:
                    self._set_state(
                        WindowState.NORMAL
                    )

            except tk.TclError as exc:
                raise WindowStateError(
                    f"Unable to show window: {exc}"
                ) from exc

        if run_mainloop:
            self.mainloop()

    def hide(self) -> None:
        """Hide the main window without destroying it."""

        self._ensure_alive()

        try:
            self._root.withdraw()
        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to hide window: {exc}"
            ) from exc

    def minimize(self) -> None:
        """Minimize the window."""

        self._ensure_alive()

        try:
            self._root.iconify()

            self._stats.minimize_count += 1

            self._set_state(
                WindowState.MINIMIZED
            )

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to minimize window: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Maximize
    # ------------------------------------------------------------------

    def maximize(self) -> None:
        """Maximize the main window."""

        self._ensure_alive()

        try:
            if not self._maximized:
                self._normal_geometry = self._root.geometry()

            system = platform.system()

            if system == "Windows":
                self._root.state("zoomed")
            elif system == "Linux":
                self._root.attributes(
                    "-zoomed",
                    True,
                )
            elif system == "Darwin":
                # macOS does not consistently support a universal
                # Tk maximize API. Fullscreen-like behavior is safer.
                self._root.attributes(
                    "-fullscreen",
                    True,
                )

            self._maximized = True
            self._stats.maximize_count += 1

            self._set_state(
                WindowState.MAXIMIZED
            )

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to maximize window: {exc}"
            ) from exc

    def restore(self) -> None:
        """Restore the window to its previous normal size."""

        self._ensure_alive()

        try:
            if self._fullscreen:
                self.set_fullscreen(False)

            if platform.system() == "Windows":
                self._root.state("normal")
            elif platform.system() == "Linux":
                self._root.attributes(
                    "-zoomed",
                    False,
                )
            else:
                self._root.attributes(
                    "-fullscreen",
                    False,
                )

            self._maximized = False

            geometry = self._normal_geometry

            if geometry:
                with suppress(tk.TclError):
                    self._root.geometry(
                        geometry
                    )

            self._stats.restore_count += 1

            self._set_state(
                WindowState.NORMAL
            )

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to restore window: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Fullscreen
    # ------------------------------------------------------------------

    def set_fullscreen(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable fullscreen mode."""

        self._ensure_alive()

        enabled = bool(enabled)

        try:
            if enabled:
                if not self._fullscreen:
                    self._normal_geometry = (
                        self._root.geometry()
                    )

                self._root.attributes(
                    "-fullscreen",
                    True,
                )

                self._fullscreen = True

                self._stats.fullscreen_count += 1

                self._set_state(
                    WindowState.FULLSCREEN
                )

            else:
                self._root.attributes(
                    "-fullscreen",
                    False,
                )

                self._fullscreen = False

                if self._maximized:
                    self._set_state(
                        WindowState.MAXIMIZED
                    )
                else:
                    self._set_state(
                        WindowState.NORMAL
                    )

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to change fullscreen state: {exc}"
            ) from exc

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""

        self.set_fullscreen(
            not self._fullscreen
        )

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def center(self) -> None:
        """Center the window on the current screen."""

        self._ensure_alive()

        try:
            self._root.update_idletasks()

            width = self._root.winfo_width()
            height = self._root.winfo_height()

            if width <= 1:
                width = self.config.width

            if height <= 1:
                height = self.config.height

            screen_width = self._root.winfo_screenwidth()
            screen_height = self._root.winfo_screenheight()

            x = max(
                0,
                (screen_width - width) // 2,
            )

            y = max(
                0,
                (screen_height - height) // 2,
            )

            self._root.geometry(
                f"{width}x{height}+{x}+{y}"
            )

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to center window: {exc}"
            ) from exc

    def set_geometry(
        self,
        width: int,
        height: int,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        """Set window geometry safely."""

        self._ensure_alive()

        width = max(
            self.config.min_width,
            int(width),
        )

        height = max(
            self.config.min_height,
            int(height),
        )

        geometry = f"{width}x{height}"

        if x is not None and y is not None:
            geometry += f"+{int(x)}+{int(y)}"

        try:
            self._root.geometry(
                geometry
            )

            self._normal_geometry = geometry

        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to set geometry: {exc}"
            ) from exc

    def geometry(self) -> str:
        """Return current Tk geometry string."""

        try:
            return self._root.geometry()
        except tk.TclError:
            return ""

    # ------------------------------------------------------------------
    # Window attributes
    # ------------------------------------------------------------------

    def set_title(self, title: str) -> None:
        self._ensure_alive()

        title = str(title).strip()

        if not title:
            raise WindowConfigurationError(
                "Window title cannot be empty."
            )

        self._root.title(title)

    def get_title(self) -> str:
        return self._root.title()

    def set_always_on_top(
        self,
        enabled: bool,
    ) -> None:
        self._ensure_alive()

        try:
            self._root.attributes(
                "-topmost",
                bool(enabled),
            )
        except tk.TclError as exc:
            raise WindowStateError(
                f"Unable to change topmost state: {exc}"
            ) from exc

    def set_background(
        self,
        color: str,
    ) -> None:
        self._ensure_alive()

        try:
            self._root.configure(
                bg=color
            )
        except tk.TclError as exc:
            raise WindowConfigurationError(
                f"Invalid background color: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Focus
    # ------------------------------------------------------------------

    def focus(self) -> None:
        """Bring the window to the foreground."""

        self._ensure_alive()

        try:
            self._root.deiconify()
            self._root.lift()
            self._root.focus_force()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _should_close(self) -> bool:
        callback = self._confirm_close_callback

        if callback is None:
            return True

        try:
            return bool(callback())
        except (RuntimeError, TypeError, ValueError):
            return False

    def close(self) -> bool:
        """
        Close and destroy the application window.

        Returns True when close was completed.
        """

        with self._lock:
            if self._closed:
                return False

            if not self._should_close():
                return False

            self._set_state(
                WindowState.CLOSING
            )

            callback = self._on_close

        if callback is not None:
            with suppress(RuntimeError, TypeError, ValueError):
                callback()

        with self._lock:
            with suppress(tk.TclError):
                self._root.destroy()

            self._closed = True
            self._stats.close_count += 1

            self._state = WindowState.CLOSED

        return True

    # ------------------------------------------------------------------
    # Mainloop
    # ------------------------------------------------------------------

    def mainloop(self) -> None:
        """Run Tk mainloop."""

        self._ensure_alive()

        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            self.close()

    def update(self) -> None:
        """Process pending Tk events once."""

        self._ensure_alive()

        try:
            self._root.update_idletasks()
            self._root.update()
        except tk.TclError:
            pass

    def update_idletasks(self) -> None:
        """Process pending geometry/display tasks."""

        self._ensure_alive()

        with suppress(tk.TclError):
            self._root.update_idletasks()

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _ensure_alive(self) -> None:
        if self._closed:
            raise WindowStateError(
                "The AssistantX window has already been closed."
            )

        try:
            if not self._root.winfo_exists():
                raise WindowStateError(
                    "The AssistantX root window no longer exists."
                )
        except tk.TclError as exc:
            raise WindowStateError(
                "The AssistantX root window is unavailable."
            ) from exc

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._lock:
            return self._stats.snapshot()

    def diagnostics(self) -> dict:
        with self._lock:
            try:
                screen = {
                    "width": self._root.winfo_screenwidth(),
                    "height": self._root.winfo_screenheight(),
                }
            except tk.TclError:
                screen = {}

            return {
                "component": "AssistantXWindow",
                "state": self._state.value,
                "closed": self._closed,
                "fullscreen": self._fullscreen,
                "maximized": self._maximized,
                "title": (
                    self._root.title()
                    if not self._closed
                    else self.config.title
                ),
                "geometry": (
                    self.geometry()
                    if not self._closed
                    else ""
                ),
                "normal_geometry": self._normal_geometry,
                "screen": screen,
                "platform": platform.system(),
                "python": platform.python_version(),
                "stats": self._stats.snapshot(),
            }


# ============================================================================
# Factory
# ============================================================================


def create_window(
    *,
    config: WindowConfig | None = None,
    root: tk.Tk | None = None,
    on_close: Callable[[], None] | None = None,
    confirm_close: Callable[[], bool] | None = None,
    on_state_change: Callable[[WindowState], None] | None = None,
) -> AssistantXWindow:
    """Create a configured AssistantX window."""

    return AssistantXWindow(
        config=config,
        root=root,
        on_close=on_close,
        confirm_close=confirm_close,
        on_state_change=on_state_change,
    )


# ============================================================================
# Convenience helpers
# ============================================================================


def center_window(
    window: tk.Tk,
) -> None:
    """Center any Tk window."""

    try:
        window.update_idletasks()

        width = window.winfo_width()
        height = window.winfo_height()

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        x = max(
            0,
            (screen_width - width) // 2,
        )

        y = max(
            0,
            (screen_height - height) // 2,
        )

        window.geometry(
            f"{width}x{height}+{x}+{y}"
        )

    except tk.TclError:
        pass


def maximize_window(
    window: tk.Tk,
) -> None:
    """Best-effort platform-aware maximize."""

    try:
        if platform.system() == "Windows":
            window.state("zoomed")
        elif platform.system() == "Linux":
            window.attributes(
                "-zoomed",
                True,
            )
        else:
            window.attributes(
                "-fullscreen",
                True,
            )
    except tk.TclError:
        pass


def minimize_window(
    window: tk.Tk,
) -> None:
    """Minimize any Tk window."""

    with suppress(tk.TclError):
        window.iconify()


def set_fullscreen(
    window: tk.Tk,
    enabled: bool = True,
) -> None:
    """Set fullscreen state on any Tk window."""

    with suppress(tk.TclError):
        window.attributes(
            "-fullscreen",
            bool(enabled),
        )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "AssistantXWindow",
    "WindowConfig",
    "WindowConfigurationError",
    "WindowError",
    "WindowState",
    "WindowStateError",
    "WindowStats",
    "center_window",
    "create_window",
    "maximize_window",
    "minimize_window",
    "set_fullscreen",
]
