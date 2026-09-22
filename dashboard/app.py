"""
AssistantX Dashboard - Application
===================================

Main application controller for the AssistantX desktop dashboard.

Responsibilities
-----------------
    • Dashboard application lifecycle
    • Window creation and ownership
    • Core service bootstrap
    • Theme initialization
    • Application event loop
    • Graceful shutdown
    • Exception-safe startup
    • Runtime diagnostics

Architecture
------------

    launcher.py / main.py
            │
            ▼
    DashboardApplication
            │
            ├── Core Services
            ├── Theme System
            ├── Main Window
            └── Shutdown
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

# ============================================================================
# Logging
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================

class DashboardError(Exception):
    """Base exception for dashboard application errors."""


class DashboardStartupError(DashboardError):
    """Raised when dashboard startup fails."""


class DashboardShutdownError(DashboardError):
    """Raised when dashboard shutdown fails."""


class DashboardStateError(DashboardError):
    """Raised when an invalid application state transition occurs."""


# ============================================================================
# Application State
# ============================================================================

class ApplicationState(str, Enum):
    """Dashboard application lifecycle states."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


# ============================================================================
# Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """
    Dashboard runtime configuration.

    Values can later be loaded from AssistantX config/settings.
    """

    title: str = "AssistantX"

    width: int = 1200
    height: int = 760

    min_width: int = 900
    min_height: int = 600

    theme: str = "dark"

    resizable: bool = True

    enable_animations: bool = True

    start_maximized: bool = False

    center_window: bool = True

    debug: bool = False

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("width must be greater than zero.")

        if self.height <= 0:
            raise ValueError("height must be greater than zero.")

        if self.min_width <= 0:
            raise ValueError("min_width must be greater than zero.")

        if self.min_height <= 0:
            raise ValueError("min_height must be greater than zero.")

        if self.min_width > self.width:
            raise ValueError(
                "min_width cannot be greater than width."
            )

        if self.min_height > self.height:
            raise ValueError(
                "min_height cannot be greater than height."
            )


# ============================================================================
# Runtime Statistics
# ============================================================================

@dataclass(slots=True)
class DashboardStats:
    """Runtime statistics for the dashboard."""

    startup_attempts: int = 0
    successful_starts: int = 0
    shutdown_attempts: int = 0
    successful_shutdowns: int = 0
    startup_failures: int = 0
    shutdown_failures: int = 0


# ============================================================================
# Dashboard Application
# ============================================================================

class DashboardApplication:
    """
    Main AssistantX dashboard application controller.

    The controller owns the dashboard lifecycle but keeps UI implementation
    inside `dashboard.window`.

    This separation allows the UI to evolve without changing the
    application bootstrap logic.
    """

    def __init__(
        self,
        config: DashboardConfig | None = None,
        *,
        window_factory: Callable[..., Any] | None = None,
        bootstrap_services: bool = True,
    ) -> None:

        self.config = config or DashboardConfig()

        self._lock = RLock()

        self._state = ApplicationState.CREATED

        self._window: Any = None

        self._window_factory = window_factory

        self._bootstrap_services_enabled = bootstrap_services

        self._services_ready = False

        self._shutdown_requested = False

        self._stats = DashboardStats()

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def state(self) -> ApplicationState:
        """Return current application state."""

        with self._lock:
            return self._state

    @property
    def window(self) -> Any:
        """Return the main dashboard window."""

        with self._lock:
            return self._window

    @property
    def running(self) -> bool:
        """Return True when the dashboard is running."""

        return self.state == ApplicationState.RUNNING

    @property
    def services_ready(self) -> bool:
        """Return service bootstrap status."""

        with self._lock:
            return self._services_ready

    # ========================================================================
    # State Management
    # ========================================================================

    def _set_state(self, state: ApplicationState) -> None:
        with self._lock:
            self._state = state

    # ========================================================================
    # Startup
    # ========================================================================

    def start(self) -> None:
        """
        Start the AssistantX dashboard.

        This method performs startup only. The Tk event loop is entered
        separately by `run()`.
        """

        with self._lock:

            if self._state == ApplicationState.RUNNING:
                return

            if self._state == ApplicationState.STARTING:
                raise DashboardStateError(
                    "Dashboard is already starting."
                )

            if self._state == ApplicationState.STOPPING:
                raise DashboardStateError(
                    "Dashboard is currently stopping."
                )

            self._stats.startup_attempts += 1
            self._state = ApplicationState.STARTING

        logger.info("Starting AssistantX dashboard...")

        try:
            # ---------------------------------------------------------------
            # Environment
            # ---------------------------------------------------------------

            self._prepare_environment()

            # ---------------------------------------------------------------
            # Core Services
            # ---------------------------------------------------------------

            if self._bootstrap_services_enabled:
                self._bootstrap_services()

            # ---------------------------------------------------------------
            # Theme
            # ---------------------------------------------------------------

            self._initialize_theme()

            # ---------------------------------------------------------------
            # Main Window
            # ---------------------------------------------------------------

            self._create_window()

            # ---------------------------------------------------------------
            # Window Configuration
            # ---------------------------------------------------------------

            self._configure_window()

            # ---------------------------------------------------------------
            # Lifecycle Hooks
            # ---------------------------------------------------------------

            self._bind_lifecycle_events()

            with self._lock:
                self._state = ApplicationState.RUNNING
                self._stats.successful_starts += 1

            logger.info("AssistantX dashboard started successfully.")

        except Exception as exc:

            with self._lock:
                self._state = ApplicationState.FAILED
                self._stats.startup_failures += 1

            logger.exception(
                "Failed to start AssistantX dashboard."
            )

            self._safe_destroy_window()

            raise DashboardStartupError(
                f"Dashboard startup failed: {exc}"
            ) from exc

    # ========================================================================
    # Environment
    # ========================================================================

    def _prepare_environment(self) -> None:
        """
        Prepare process-level environment.

        Keep this lightweight. Heavy initialization belongs in service
        modules rather than the dashboard controller.
        """

        os.environ.setdefault(
            "ASSISTANTX_APP",
            "dashboard",
        )

        if self.config.debug:
            os.environ.setdefault(
                "ASSISTANTX_DEBUG",
                "1",
            )

    # ========================================================================
    # Core Services
    # ========================================================================

    def _bootstrap_services(self) -> None:
        """
        Bootstrap AssistantX core configuration/services.

        Import is intentionally lazy so importing dashboard.app does not
        immediately initialize the entire application.
        """

        try:

            from config import bootstrap

            bootstrap()

            self._services_ready = True

            logger.info(
                "AssistantX core configuration initialized."
            )

        except ImportError:

            logger.warning(
                "Core configuration bootstrap is unavailable. "
                "Continuing with dashboard-only mode."
            )

            self._services_ready = False

        except Exception:

            logger.exception(
                "Core service bootstrap failed."
            )

            raise

    # ========================================================================
    # Theme
    # ========================================================================

    def _initialize_theme(self) -> None:
        """Initialize the dashboard theme system."""

        try:

            from dashboard.themes import set_theme

            if not set_theme(self.config.theme):
                logger.warning(
                    "Unknown theme '%s'. Falling back to dark.",
                    self.config.theme,
                )

                set_theme("dark")

            logger.info(
                "Dashboard theme initialized: %s",
                self.config.theme,
            )

        except ImportError:

            logger.warning(
                "Dashboard theme manager unavailable."
            )

        except Exception:

            logger.exception(
                "Theme initialization failed."
            )

            raise

    # ========================================================================
    # Window
    # ========================================================================

    def _create_window(self) -> None:
        """
        Create the main application window.

        A custom factory can be supplied for testing or alternate UI
        implementations.
        """

        factory = self._window_factory

        if factory is not None:

            self._window = self._call_window_factory(factory)

            if self._window is None:
                raise DashboardStartupError(
                    "Window factory returned None."
                )

            return

        # ---------------------------------------------------------------
        # Default window implementation
        # ---------------------------------------------------------------

        try:
            from dashboard.window import Window

            self._window = Window()

        except ImportError as exc:

            raise DashboardStartupError(
                "dashboard.window.Window could not be imported."
            ) from exc

    def _call_window_factory(
        self,
        factory: Callable[..., Any],
    ) -> Any:
        """
        Call a custom window factory.

        Supports both:
            factory()
        and:
            factory(config)
        """

        try:
            return factory(self.config)

        except TypeError:

            return factory()

    # ========================================================================
    # Window Configuration
    # ========================================================================

    def _configure_window(self) -> None:
        """Apply common window configuration when supported."""

        window = self._window

        if window is None:
            return

        # ---------------------------------------------------------------
        # Title
        # ---------------------------------------------------------------

        self._safe_call(
            window,
            "title",
            self.config.title,
        )

        # ---------------------------------------------------------------
        # Geometry
        # ---------------------------------------------------------------

        self._configure_geometry(window)

        # ---------------------------------------------------------------
        # Resizable
        # ---------------------------------------------------------------

        self._safe_call(
            window,
            "resizable",
            self.config.resizable,
            self.config.resizable,
        )

        # ---------------------------------------------------------------
        # Start Maximized
        # ---------------------------------------------------------------

        if self.config.start_maximized:

            self._safe_call(
                window,
                "state",
                "zoomed",
            )

    def _configure_geometry(self, window: Any) -> None:
        """Configure and optionally center the window."""

        geometry = (
            f"{self.config.width}x"
            f"{self.config.height}"
        )

        # Prefer a dedicated geometry method.
        if hasattr(window, "geometry"):

            try:
                window.geometry(geometry)
            except Exception:
                logger.debug(
                    "Could not set window geometry.",
                    exc_info=True,
                )

        if self.config.center_window:
            self._center_window(window)

    def _center_window(self, window: Any) -> None:
        """Center the window on the available screen."""

        try:

            window.update_idletasks()

            width = window.winfo_width()
            height = window.winfo_height()

            if width <= 1:
                width = self.config.width

            if height <= 1:
                height = self.config.height

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

        except Exception:
            logger.debug(
                "Could not center dashboard window.",
                exc_info=True,
            )

    # ========================================================================
    # Lifecycle Events
    # ========================================================================

    def _bind_lifecycle_events(self) -> None:
        """Bind window close event when supported."""

        window = self._window

        if window is None:
            return

        protocol = getattr(
            window,
            "protocol",
            None,
        )

        if callable(protocol):

            try:
                protocol(
                    "WM_DELETE_WINDOW",
                    self.shutdown,
                )

            except Exception:
                logger.debug(
                    "Could not bind WM_DELETE_WINDOW.",
                    exc_info=True,
                )

    # ========================================================================
    # Event Loop
    # ========================================================================

    def run(self) -> int:
        """
        Start the dashboard and enter the UI event loop.

        Returns:
            Process-style exit code.
        """

        try:

            if self.state == ApplicationState.CREATED:
                self.start()

            if self.state != ApplicationState.RUNNING:
                return 1

            self._mainloop()

            return 0

        except KeyboardInterrupt:

            logger.info(
                "Keyboard interrupt received."
            )

            self.shutdown()

            return 0

        except Exception:

            logger.exception(
                "Unhandled dashboard runtime error."
            )

            self.shutdown()

            return 1

    def _mainloop(self) -> None:
        """Enter the main window event loop."""

        window = self._window

        if window is None:
            raise DashboardStateError(
                "Cannot start event loop without a window."
            )

        mainloop = getattr(
            window,
            "mainloop",
            None,
        )

        if not callable(mainloop):
            raise DashboardStateError(
                "Dashboard window does not provide mainloop()."
            )

        mainloop()

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(self) -> None:
        """
        Gracefully shut down the dashboard and application services.
        """

        with self._lock:

            if self._state in (
                ApplicationState.STOPPED,
                ApplicationState.STOPPING,
            ):
                return

            self._stats.shutdown_attempts += 1
            self._state = ApplicationState.STOPPING

        logger.info(
            "Shutting down AssistantX dashboard..."
        )

        errors: list[Exception] = []

        # ---------------------------------------------------------------
        # Stop UI animations
        # ---------------------------------------------------------------

        try:
            self._shutdown_animations()
        except Exception as exc:
            errors.append(exc)
            logger.exception(
                "Failed to shutdown animations."
            )

        # ---------------------------------------------------------------
        # Shutdown voice
        # ---------------------------------------------------------------

        try:
            self._shutdown_voice()
        except Exception as exc:
            errors.append(exc)
            logger.exception(
                "Failed to shutdown voice services."
            )

        # ---------------------------------------------------------------
        # Shutdown core
        # ---------------------------------------------------------------

        try:
            self._shutdown_core()
        except Exception as exc:
            errors.append(exc)
            logger.exception(
                "Failed to shutdown core services."
            )

        # ---------------------------------------------------------------
        # Destroy window
        # ---------------------------------------------------------------

        try:
            self._safe_destroy_window()
        except (OSError, RuntimeError) as exc:
            errors.append(exc)

        with self._lock:

            if errors:
                self._state = ApplicationState.FAILED
                self._stats.shutdown_failures += 1

            else:
                self._state = ApplicationState.STOPPED
                self._stats.successful_shutdowns += 1

        logger.info(
            "AssistantX dashboard shutdown complete."
        )

        if errors and self.config.debug:
            raise DashboardShutdownError(
                f"{len(errors)} shutdown operation(s) failed."
            )

    # ========================================================================
    # Animation Shutdown
    # ========================================================================

    def _shutdown_animations(self) -> None:
        """Stop active dashboard animations."""

        # The animation engine is normally owned by the window.
        window = self._window

        if window is None:
            return

        engine = getattr(
            window,
            "animation_engine",
            None,
        )

        if engine is not None:

            shutdown = getattr(
                engine,
                "shutdown",
                None,
            )

            if callable(shutdown):
                shutdown()

    # ========================================================================
    # Voice Shutdown
    # ========================================================================

    def _shutdown_voice(self) -> None:
        """Shutdown AssistantX voice resources when available."""

        try:

            from voice import shutdown

            shutdown()

        except ImportError:

            logger.debug(
                "Voice package unavailable during shutdown."
            )

    # ========================================================================
    # Core Shutdown
    # ========================================================================

    def _shutdown_core(self) -> None:
        """Shutdown AssistantX core lifecycle when available."""

        try:

            from core import shutdown

            if callable(shutdown):
                shutdown()

        except ImportError:

            logger.debug(
                "Core shutdown hook unavailable."
            )

    # ========================================================================
    # Window Destruction
    # ========================================================================

    def _safe_destroy_window(self) -> None:
        """Destroy the window safely."""

        window = self._window

        if window is None:
            return

        destroy = getattr(
            window,
            "destroy",
            None,
        )

        if callable(destroy):

            try:
                destroy()
            except Exception:
                logger.debug(
                    "Window destruction failed.",
                    exc_info=True,
                )

        self._window = None

    # ========================================================================
    # Utility
    # ========================================================================

    @staticmethod
    def _safe_call(
        target: Any,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """Call a method safely if it exists."""

        method = getattr(
            target,
            method_name,
            None,
        )

        if not callable(method):
            return False

        try:
            method(*args, **kwargs)
            return True

        except Exception:
            logger.debug(
                "Failed calling %s().",
                method_name,
                exc_info=True,
            )

            return False

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:
        """
        Return safe dashboard diagnostics.

        No API keys, passwords, tokens, or private user data are returned.
        """

        with self._lock:

            return {
                "state": self._state.value,
                "running": self._state == ApplicationState.RUNNING,
                "services_ready": self._services_ready,
                "window_created": self._window is not None,
                "shutdown_requested": self._shutdown_requested,

                "config": {
                    "title": self.config.title,
                    "width": self.config.width,
                    "height": self.config.height,
                    "theme": self.config.theme,
                    "resizable": self.config.resizable,
                    "animations": self.config.enable_animations,
                    "debug": self.config.debug,
                },

                "stats": {
                    "startup_attempts":
                        self._stats.startup_attempts,

                    "successful_starts":
                        self._stats.successful_starts,

                    "shutdown_attempts":
                        self._stats.shutdown_attempts,

                    "successful_shutdowns":
                        self._stats.successful_shutdowns,

                    "startup_failures":
                        self._stats.startup_failures,

                    "shutdown_failures":
                        self._stats.shutdown_failures,
                },
            }


# ============================================================================
# Global Dashboard Application
# ============================================================================

_app: DashboardApplication | None = None
_app_lock = RLock()


def get_app() -> DashboardApplication:
    """
    Return the global dashboard application instance.

    The instance is created lazily.
    """

    global _app

    with _app_lock:

        if _app is None:
            _app = DashboardApplication()

        return _app


def create_app(
    config: DashboardConfig | None = None,
    *,
    window_factory: Callable[..., Any] | None = None,
    bootstrap_services: bool = True,
) -> DashboardApplication:
    """
    Create a new dashboard application instance.

    Useful for testing, alternate configurations, and development tools.
    """

    return DashboardApplication(
        config=config,
        window_factory=window_factory,
        bootstrap_services=bootstrap_services,
    )


# ============================================================================
# Application Entry Point
# ============================================================================

def run(
    config: DashboardConfig | None = None,
    *,
    window_factory: Callable[..., Any] | None = None,
    bootstrap_services: bool = True,
) -> int:
    """
    Start AssistantX dashboard.

    This is the preferred entry point for `main.py` or `launcher.py`.
    """

    application = create_app(
        config=config,
        window_factory=window_factory,
        bootstrap_services=bootstrap_services,
    )

    return application.run()


def main() -> int:
    """Console entry point."""

    return run()


# ============================================================================
# Module Entry Point
# ============================================================================

if __name__ == "__main__":
    sys.exit(main())


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # State
    "ApplicationState",
    # Application
    "DashboardApplication",
    # Configuration
    "DashboardConfig",
    # Exceptions
    "DashboardError",
    "DashboardShutdownError",
    "DashboardStartupError",
    "DashboardStateError",
    # Statistics
    "DashboardStats",
    "create_app",
    # Global helpers
    "get_app",
    "main",
    "run",
]
