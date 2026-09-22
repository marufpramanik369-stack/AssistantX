"""
AssistantX Dashboard - Splash Screen
=====================================

Professional startup splash screen for AssistantX.

Features:
    - Centered splash window
    - Logo / initials
    - Loading progress
    - Startup status text
    - Optional startup steps
    - Dark professional UI
    - Automatic close
    - Callback support
    - Safe cleanup
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

# ============================================================================
# COLORS
# ============================================================================

BG = "#101010"
SURFACE = "#181818"
BORDER = "#292929"

TEXT = "#F5F5F5"
MUTED = "#8F8F8F"

ACCENT = "#4F8CFF"
ACCENT_LIGHT = "#6A9DFF"

FONT = "Segoe UI"


# ============================================================================
# CONFIG
# ============================================================================

@dataclass(frozen=True)
class SplashConfig:
    """Splash screen configuration."""

    width: int = 520
    height: int = 330

    title: str = "AssistantX"

    subtitle: str = "Your Personal AI Assistant"

    version: str = "v1.0.0"

    minimum_duration: int = 1200

    show_progress: bool = True

    logo_size: int = 76


# ============================================================================
# SPLASH SCREEN
# ============================================================================

class SplashScreen(tk.Toplevel):
    """
    AssistantX startup splash screen.

    Parameters
    ----------
    parent:
        Root Tkinter window.

    config:
        SplashConfig instance.

    on_ready:
        Optional callback called when splash is finished.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        config: SplashConfig | None = None,
        on_ready: Callable[[], None] | None = None,
    ) -> None:

        super().__init__(parent)

        self.parent = parent
        self.config_data = config or SplashConfig()
        self.on_ready = on_ready

        self._closed = False
        self._progress = 0
        self._after_ids: set[str] = set()

        self._setup_window()
        self._build_ui()

        self.after(
            self.config_data.minimum_duration,
            self.finish,
        )

    # ========================================================================
    # WINDOW
    # ========================================================================

    def _setup_window(self) -> None:

        self.title(
            self.config_data.title
        )

        self.geometry(
            f"{self.config_data.width}"
            f"x{self.config_data.height}"
        )

        self.resizable(
            False,
            False,
        )

        self.configure(
            bg=BG,
        )

        # Remove normal title bar
        with suppress(tk.TclError):
            self.overrideredirect(True)

        self.transient(self.parent)

        self.grab_set()

        self._center_window()

        self.protocol(
            "WM_DELETE_WINDOW",
            self.finish,
        )

    def _center_window(self) -> None:

        self.update_idletasks()

        width = self.config_data.width
        height = self.config_data.height

        try:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()

            x = (screen_width - width) // 2
            y = (screen_height - height) // 2

            self.geometry(
                f"{width}x{height}+{x}+{y}"
            )

        except tk.TclError:
            pass

    # ========================================================================
    # UI
    # ========================================================================

    def _build_ui(self) -> None:

        outer = tk.Frame(
            self,
            bg=BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )

        outer.pack(
            fill="both",
            expand=True,
        )

        self._build_logo(outer)

        tk.Label(
            outer,
            text=self.config_data.title,
            bg=BG,
            fg=TEXT,
            font=(FONT, 24, "bold"),
        ).pack(
            pady=(8, 0),
        )

        tk.Label(
            outer,
            text=self.config_data.subtitle,
            bg=BG,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(
            pady=(3, 0),
        )

        self._build_status(outer)

        self._build_progress(outer)

        tk.Label(
            outer,
            text=self.config_data.version,
            bg=BG,
            fg="#666666",
            font=(FONT, 8),
        ).pack(
            side="bottom",
            pady=14,
        )

    # ========================================================================
    # LOGO
    # ========================================================================

    def _build_logo(
        self,
        parent: tk.Frame,
    ) -> None:

        size = self.config_data.logo_size

        logo_frame = tk.Frame(
            parent,
            bg=ACCENT,
            width=size,
            height=size,
        )

        logo_frame.pack(
            pady=(38, 0),
        )

        logo_frame.pack_propagate(False)

        tk.Label(
            logo_frame,
            text="X",
            bg=ACCENT,
            fg="white",
            font=(FONT, 30, "bold"),
        ).pack(
            expand=True,
        )

    # ========================================================================
    # STATUS
    # ========================================================================

    def _build_status(
        self,
        parent: tk.Frame,
    ) -> None:

        self.status_frame = tk.Frame(
            parent,
            bg=BG,
        )

        self.status_frame.pack(
            fill="x",
            padx=70,
            pady=(28, 8),
        )

        self.status_dot = tk.Label(
            self.status_frame,
            text="●",
            bg=BG,
            fg=ACCENT,
            font=(FONT, 8),
        )

        self.status_dot.pack(
            side="left",
            padx=(0, 7),
        )

        self.status_label = tk.Label(
            self.status_frame,
            text="Starting AssistantX...",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
            anchor="w",
        )

        self.status_label.pack(
            side="left",
        )

    # ========================================================================
    # PROGRESS
    # ========================================================================

    def _build_progress(
        self,
        parent: tk.Frame,
    ) -> None:

        if not self.config_data.show_progress:
            return

        container = tk.Frame(
            parent,
            bg="#252525",
            height=4,
        )

        container.pack(
            fill="x",
            padx=70,
        )

        container.pack_propagate(False)

        self.progress_bar = tk.Frame(
            container,
            bg=ACCENT,
            width=0,
        )

        self.progress_bar.pack(
            side="left",
            fill="y",
        )

        self.progress_bar.pack_propagate(False)

        self.progress_container = container

    # ========================================================================
    # STATUS API
    # ========================================================================

    def set_status(
        self,
        text: str,
        *,
        progress: int | None = None,
    ) -> None:
        """
        Update splash status.

        progress:
            Optional value from 0 to 100.
        """

        if self._closed:
            return

        try:

            self.status_label.configure(
                text=str(text),
            )

            if progress is not None:
                self.set_progress(progress)

        except tk.TclError:
            pass

    def set_progress(
        self,
        value: float,
    ) -> None:
        """Set loading progress from 0 to 100."""

        if self._closed:
            return

        try:
            value = max(
                0,
                min(
                    100,
                    float(value),
                ),
            )
        except (TypeError, ValueError):
            return

        self._progress = value

        if not self.config_data.show_progress:
            return

        try:

            self.progress_container.update_idletasks()

            width = self.progress_container.winfo_width()

            if width <= 1:
                width = (
                    self.config_data.width
                    - 140
                )

            new_width = int(
                width * value / 100
            )

            self.progress_bar.configure(
                width=new_width,
            )

        except tk.TclError:
            pass

    # ========================================================================
    # LOADING STEPS
    # ========================================================================

    def run_step(
        self,
        text: str,
        progress: int,
        delay: int = 0,
    ) -> None:
        """
        Schedule a startup status update.
        """

        def update():

            if self._closed:
                return

            self.set_status(
                text,
                progress=progress,
            )

        if delay <= 0:
            update()
            return

        try:

            after_id = self.after(
                delay,
                update,
            )

            self._after_ids.add(
                str(after_id)
            )

        except tk.TclError:
            pass

    # ========================================================================
    # ANIMATION
    # ========================================================================

    def animate_progress(
        self,
        target: int = 100,
        duration: int = 900,
    ) -> None:
        """Smoothly animate progress."""

        if self._closed:
            return

        target = max(
            0,
            min(
                100,
                int(target),
            ),
        )

        start = self._progress

        if target <= start:
            return

        steps = max(
            1,
            duration // 20,
        )

        current_step = 0

        def tick():

            nonlocal current_step

            if self._closed:
                return

            current_step += 1

            ratio = min(
                1.0,
                current_step / steps,
            )

            # Ease-out
            eased = 1 - (
                1 - ratio
            ) ** 2

            value = (
                start
                + (target - start)
                * eased
            )

            self.set_progress(value)

            if ratio < 1.0:

                try:

                    after_id = self.after(
                        20,
                        tick,
                    )

                    self._after_ids.add(
                        str(after_id)
                    )

                except tk.TclError:
                    pass

        tick()

    # ========================================================================
    # FINISH
    # ========================================================================

    def finish(self) -> None:
        """Close splash screen safely."""

        if self._closed:
            return

        self._closed = True

        self._cancel_jobs()

        with suppress(tk.TclError):
            self.grab_release()

        with suppress(tk.TclError):
            self.destroy()

        if self.on_ready:
            self.on_ready()

    # ========================================================================
    # CANCEL JOBS
    # ========================================================================

    def _cancel_jobs(self) -> None:

        for job_id in list(
            self._after_ids
        ):

            with suppress(tk.TclError, ValueError):
                self.after_cancel(
                    job_id
                )

        self._after_ids.clear()

    # ========================================================================
    # CLEANUP
    # ========================================================================

    def destroy(self) -> None:

        if not self._closed:
            self._closed = True

        self._cancel_jobs()

        with suppress(tk.TclError):
            self.grab_release()

        super().destroy()


# ============================================================================
# FACTORY
# ============================================================================

def create_splash(
    parent: tk.Misc,
    **kwargs,
) -> SplashScreen:
    """Create an AssistantX splash screen."""

    return SplashScreen(
        parent,
        **kwargs,
    )


# ============================================================================
# STARTUP HELPER
# ============================================================================

def show_splash(
    root: tk.Misc,
    *,
    on_ready: Callable[[], None] | None = None,
    config: SplashConfig | None = None,
) -> SplashScreen:
    """
    Show AssistantX splash screen.

    Example
    -------
        splash = show_splash(root)

        splash.set_status(
            "Loading configuration...",
            progress=25,
        )
    """

    return SplashScreen(
        root,
        config=config,
        on_ready=on_ready,
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SplashConfig",
    "SplashScreen",
    "create_splash",
    "show_splash",
]
