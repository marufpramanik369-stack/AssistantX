"""
AssistantX Dashboard Configuration
===================================

Centralized configuration for the AssistantX dashboard.

Responsibilities
----------------
- Dashboard branding and identity
- Window configuration
- Cyberpunk dark theme colors
- Typography
- Animation configuration
- Panel configuration
- Avatar configuration
- System-monitor configuration
- Dashboard-wide settings
- Compatibility constants used by dashboard.app
- Runtime diagnostics

This module is intentionally independent from the main ``config`` package,
while remaining compatible with the rest of AssistantX.

Assistant Identity
------------------
Application : AssistantX
Assistant   : JEROX
Voice       : Female
Wake Word   : JEROX
Version     : 1.0.0

Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

logger.debug("Importing dashboard configuration module")


# ============================================================================
# PATHS
# ============================================================================

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
ICONS_DIR = ASSETS_DIR / "icons"
SOUNDS_DIR = ASSETS_DIR / "sounds"

logger.debug("Dashboard directory: %s", DASHBOARD_DIR)
logger.debug("Project root: %s", PROJECT_ROOT)
logger.debug("Assets directory: %s", ASSETS_DIR)


# ============================================================================
# APPLICATION / BRANDING
# ============================================================================

APPLICATION_NAME = "AssistantX"
ASSISTANT_NAME = "JEROX"
DASHBOARD_NAME = "Dashboard"

VERSION = "1.0.0"
APP_VERSION = f"{ASSISTANT_NAME} {VERSION}"

WINDOW_TITLE = f"{APPLICATION_NAME} — {ASSISTANT_NAME}"

ASSISTANT_WAKE_WORD = "jerox"
FIXED_WAKE_WORD = "jerox"

ASSISTANT_VOICE_GENDER = "female"
FIXED_VOICE_GENDER = "female"
VOICE_GENDER_LOCKED = True
WAKE_WORD_LOCKED = True

SUPPORTED_LANGUAGES = ("bn", "en", "hi")
DEFAULT_LANGUAGE = "en"

logger.info(
    "Dashboard identity loaded | application=%s | assistant=%s | version=%s",
    APPLICATION_NAME,
    ASSISTANT_NAME,
    VERSION,
)


# ============================================================================
# WINDOW COMPATIBILITY CONSTANTS
# ============================================================================

DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900

MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700

MAX_WINDOW_WIDTH: Optional[int] = None
MAX_WINDOW_HEIGHT: Optional[int] = None

WINDOW_RESIZABLE = True
WINDOW_START_MAXIMIZED = False
WINDOW_CENTER = True

logger.info(
    "Window defaults: %dx%d | minimum=%dx%d",
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
)


# ============================================================================
# CYBERPUNK DARK COLOR SCHEME
# ============================================================================

COLOR_BG = "#0B1020"
COLOR_SURFACE = "#11182A"
COLOR_SURFACE_ALT = "#172036"

COLOR_BORDER = "#26324A"
COLOR_BORDER_ACCENT = "#4A6FA5"

COLOR_TEXT = "#F4F7FB"
COLOR_TEXT_SECONDARY = "#D1D5DB"
COLOR_MUTED = "#8D9AB3"

COLOR_ACCENT = "#6C8CFF"
COLOR_ACCENT_LIGHT = "#8E7CFF"
COLOR_ACCENT_DARK = "#4A5FD5"

COLOR_SUCCESS = "#39D98A"
COLOR_WARNING = "#F5B942"
COLOR_ERROR = "#FF5C7A"
COLOR_INFO = "#60A5FA"

COLOR_GLOW = "#00FF88"
COLOR_FEMALE_VOICE = "#FF69B4"

COLOR_CYAN = "#22D3EE"
COLOR_TEAL = "#14B8A6"
COLOR_PURPLE = "#A78BFA"

logger.info(
    "Cyberpunk color scheme loaded | background=%s | accent=%s",
    COLOR_BG,
    COLOR_ACCENT,
)


# ============================================================================
# THEME PALETTES
# ============================================================================

THEME_COLORS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": COLOR_BG,
        "background": COLOR_BG,
        "surface": COLOR_SURFACE,
        "surface_alt": COLOR_SURFACE_ALT,
        "border": COLOR_BORDER,
        "border_accent": COLOR_BORDER_ACCENT,
        "text": COLOR_TEXT,
        "text_secondary": COLOR_TEXT_SECONDARY,
        "muted": COLOR_MUTED,
        "accent": COLOR_ACCENT,
        "accent_light": COLOR_ACCENT_LIGHT,
        "accent_dark": COLOR_ACCENT_DARK,
        "success": COLOR_SUCCESS,
        "warning": COLOR_WARNING,
        "error": COLOR_ERROR,
        "info": COLOR_INFO,
        "glow": COLOR_GLOW,
        "female_voice": COLOR_FEMALE_VOICE,
        "cyan": COLOR_CYAN,
        "teal": COLOR_TEAL,
        "purple": COLOR_PURPLE,
    }
}

AVAILABLE_THEMES = tuple(THEME_COLORS.keys())
DEFAULT_THEME = "dark"

logger.info(
    "Theme palette loaded | themes=%s",
    AVAILABLE_THEMES,
)


# ============================================================================
# STATUS COLORS
# ============================================================================

STATUS_COLORS: dict[str, str] = {
    "idle": COLOR_MUTED,
    "initializing": COLOR_WARNING,
    "starting": COLOR_WARNING,
    "running": COLOR_SUCCESS,
    "online": COLOR_SUCCESS,
    "ready": COLOR_SUCCESS,
    "busy": COLOR_ACCENT,
    "processing": COLOR_ACCENT,
    "speaking": COLOR_ACCENT,
    "listening": COLOR_ACCENT_LIGHT,
    "thinking": COLOR_PURPLE,
    "connecting": COLOR_WARNING,
    "offline": COLOR_ERROR,
    "error": COLOR_ERROR,
    "warning": COLOR_WARNING,
    "info": COLOR_INFO,
    "disabled": COLOR_MUTED,
}


# ============================================================================
# TYPOGRAPHY
# ============================================================================

FONT_FAMILY_DEFAULT = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"

FONT_SIZE_TITLE = 18
FONT_SIZE_HEADING = 14
FONT_SIZE_BODY = 10
FONT_SIZE_SMALL = 9
FONT_SIZE_TINY = 8

FONT_WEIGHT_NORMAL = "normal"
FONT_WEIGHT_BOLD = "bold"


# ============================================================================
# WINDOW SETTINGS
# ============================================================================

@dataclass(slots=True)
class WindowSettings:
    """Dashboard window configuration."""

    width: int = DEFAULT_WINDOW_WIDTH
    height: int = DEFAULT_WINDOW_HEIGHT

    min_width: int = MIN_WINDOW_WIDTH
    min_height: int = MIN_WINDOW_HEIGHT

    max_width: Optional[int] = MAX_WINDOW_WIDTH
    max_height: Optional[int] = MAX_WINDOW_HEIGHT

    resizable: bool = WINDOW_RESIZABLE
    start_maximized: bool = WINDOW_START_MAXIMIZED
    center_window: bool = WINDOW_CENTER

    title: str = WINDOW_TITLE


# ============================================================================
# UI SETTINGS
# ============================================================================

@dataclass(slots=True)
class UISettings:
    """General dashboard UI behavior."""

    debug: bool = False
    show_fps: bool = False
    show_metrics: bool = True

    smooth_updates: bool = True
    auto_refresh: bool = True

    enable_header: bool = True
    enable_footer: bool = True

    enable_tooltips: bool = True
    enable_hover_effects: bool = True


# ============================================================================
# ANIMATION SETTINGS
# ============================================================================

@dataclass(slots=True)
class AnimationSettings:
    """Dashboard animation engine configuration."""

    enabled: bool = True

    # Approximately 60 FPS.
    frame_delay: int = 16
    fps: int = 60

    auto_start: bool = True
    smooth_easing: bool = True

    max_frame_queue: int = 60

    enable_avatar_animation: bool = True
    enable_glow: bool = True
    enable_pulse: bool = True
    enable_breathing: bool = True
    enable_3d: bool = True
    enable_depth: bool = True
    enable_perspective: bool = True


# ============================================================================
# THEME SETTINGS
# ============================================================================

@dataclass(slots=True)
class ThemeSettings:
    """Dashboard theme configuration."""

    active: str = DEFAULT_THEME

    available: list[str] = field(
        default_factory=lambda: list(AVAILABLE_THEMES)
    )

    allow_switching: bool = True
    smooth_transition: bool = True

    def __post_init__(self) -> None:
        if self.active not in self.available:
            logger.warning(
                "Unknown active theme %r. Falling back to %r.",
                self.active,
                DEFAULT_THEME,
            )
            self.active = DEFAULT_THEME


# ============================================================================
# PANEL SETTINGS
# ============================================================================

@dataclass(slots=True)
class PanelSettings:
    """Dashboard panel layout configuration."""

    sidebar_width: int = 285
    right_sidebar_width: int = 350

    enable_sidebar: bool = True
    enable_center: bool = True
    enable_right_sidebar: bool = True

    enable_footer: bool = True
    enable_header: bool = True

    panel_spacing: int = 12
    panel_padding: int = 16

    center_min_width: int = 500


# ============================================================================
# AVATAR SETTINGS
# ============================================================================

AVATAR_FILE = IMAGES_DIR / "avatar_girl.png"
FALLBACK_AVATAR_FILE = IMAGES_DIR / "avatar.png"

AVATAR_PATH = AVATAR_FILE
FALLBACK_AVATAR_PATH = FALLBACK_AVATAR_FILE


@dataclass(slots=True)
class AvatarSettings:
    """JEROX avatar configuration."""

    enabled: bool = True

    show_animation: bool = True
    animate_on_speak: bool = True

    size: str = "medium"

    background_blur: bool = True
    glow_effect: bool = True

    enable_3d_rotation: bool = True
    enable_depth: bool = True
    enable_perspective: bool = True

    image_path: Path = AVATAR_FILE
    fallback_image_path: Path = FALLBACK_AVATAR_FILE


# ============================================================================
# SYSTEM MONITOR SETTINGS
# ============================================================================

@dataclass(slots=True)
class SystemMonitorSettings:
    """System monitoring configuration."""

    enabled: bool = True

    update_interval: int = 1500

    show_cpu: bool = True
    show_memory: bool = True
    show_disk: bool = True
    show_network: bool = True
    show_temperature: bool = True
    show_processes: bool = True

    history_size: int = 60


# ============================================================================
# TERMINAL SETTINGS
# ============================================================================

@dataclass(slots=True)
class TerminalSettings:
    """Dashboard terminal configuration."""

    enabled: bool = True

    max_lines: int = 500
    font_family: str = FONT_FAMILY_MONO
    font_size: int = 9

    prompt: str = "JEROX > "
    readonly_output: bool = True

    auto_scroll: bool = True


# ============================================================================
# COMMAND SETTINGS
# ============================================================================

@dataclass(slots=True)
class CommandSettings:
    """Dashboard command interface configuration."""

    enabled: bool = True

    placeholder: str = "Ask JEROX anything..."
    submit_on_enter: bool = True

    show_wake_word_hint: bool = True
    wake_word: str = FIXED_WAKE_WORD


# ============================================================================
# HEADER SETTINGS
# ============================================================================

@dataclass(slots=True)
class HeaderSettings:
    """Dashboard header configuration."""

    enabled: bool = True

    show_logo: bool = True
    show_assistant_name: bool = True
    show_status: bool = True
    show_clock: bool = True

    title: str = APPLICATION_NAME
    subtitle: str = ASSISTANT_NAME


# ============================================================================
# FOOTER SETTINGS
# ============================================================================

@dataclass(slots=True)
class FooterSettings:
    """Dashboard footer configuration."""

    enabled: bool = True

    show_connection: bool = True
    show_ai_status: bool = True
    show_voice_status: bool = True
    show_memory_status: bool = True

    show_version: bool = True


# ============================================================================
# COMPLETE DASHBOARD SETTINGS
# ============================================================================

@dataclass(slots=True)
class DashboardSettings:
    """Complete dashboard configuration."""

    # ---------------------------------------------------------------------
    # Branding
    # ---------------------------------------------------------------------

    application_name: str = APPLICATION_NAME
    assistant_name: str = ASSISTANT_NAME
    dashboard_name: str = DASHBOARD_NAME
    version: str = VERSION

    wake_word: str = FIXED_WAKE_WORD
    voice_gender: str = FIXED_VOICE_GENDER

    # ---------------------------------------------------------------------
    # Components
    # ---------------------------------------------------------------------

    window: Optional[WindowSettings] = None
    ui: Optional[UISettings] = None
    animation: Optional[AnimationSettings] = None
    theme: Optional[ThemeSettings] = None
    panels: Optional[PanelSettings] = None
    avatar: Optional[AvatarSettings] = None
    system_monitor: Optional[SystemMonitorSettings] = None
    terminal: Optional[TerminalSettings] = None
    command: Optional[CommandSettings] = None
    header: Optional[HeaderSettings] = None
    footer: Optional[FooterSettings] = None

    # ---------------------------------------------------------------------
    # Behavior
    # ---------------------------------------------------------------------

    startup_delay: float = 0.0
    shutdown_timeout: float = 5.0

    enable_logging: bool = True
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Initialize nested configuration objects."""

        if self.window is None:
            self.window = WindowSettings()

        if self.ui is None:
            self.ui = UISettings()

        if self.animation is None:
            self.animation = AnimationSettings()

        if self.theme is None:
            self.theme = ThemeSettings()

        if self.panels is None:
            self.panels = PanelSettings()

        if self.avatar is None:
            self.avatar = AvatarSettings()

        if self.system_monitor is None:
            self.system_monitor = SystemMonitorSettings()

        if self.terminal is None:
            self.terminal = TerminalSettings()

        if self.command is None:
            self.command = CommandSettings()

        if self.header is None:
            self.header = HeaderSettings()

        if self.footer is None:
            self.footer = FooterSettings()

        logger.debug(
            "DashboardSettings initialized | assistant=%s | theme=%s",
            self.assistant_name,
            self.theme.active,
        )


# ============================================================================
# GLOBAL DASHBOARD SETTINGS
# ============================================================================

DASHBOARD_SETTINGS = DashboardSettings()

logger.info(
    "Global dashboard settings initialized | %s | %s",
    DASHBOARD_SETTINGS.application_name,
    DASHBOARD_SETTINGS.assistant_name,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_color(
    name: str,
    theme: str = DEFAULT_THEME,
) -> str:
    """
    Return a color from the selected theme.

    Unknown themes fall back to ``dark``.
    Unknown color names fall back to ``COLOR_TEXT``.
    """

    if not isinstance(name, str):
        logger.warning("Invalid color name: %r", name)
        return COLOR_TEXT

    theme_name = str(theme).strip().lower()

    palette = THEME_COLORS.get(theme_name)

    if palette is None:
        logger.warning(
            "Theme %r not found; using %r.",
            theme_name,
            DEFAULT_THEME,
        )
        palette = THEME_COLORS[DEFAULT_THEME]

    color = palette.get(name)

    if color is None:
        logger.warning(
            "Color %r not found in theme %r; using text color.",
            name,
            theme_name,
        )
        return COLOR_TEXT

    return color


def get_status_color(status: str) -> str:
    """
    Return the color associated with a dashboard status.
    """

    if not isinstance(status, str):
        return COLOR_MUTED

    normalized = status.strip().lower()

    return STATUS_COLORS.get(
        normalized,
        COLOR_MUTED,
    )


def get_avatar_path() -> Path:
    """
    Return the preferred JEROX avatar path.

    ``avatar_girl.png`` is preferred. If unavailable, the legacy
    ``avatar.png`` is used.
    """

    if AVATAR_FILE.is_file():
        return AVATAR_FILE

    if FALLBACK_AVATAR_FILE.is_file():
        logger.warning(
            "Preferred JEROX avatar not found: %s; using fallback: %s",
            AVATAR_FILE,
            FALLBACK_AVATAR_FILE,
        )
        return FALLBACK_AVATAR_FILE

    logger.warning(
        "No dashboard avatar image found. Preferred=%s fallback=%s",
        AVATAR_FILE,
        FALLBACK_AVATAR_FILE,
    )

    return AVATAR_FILE


def get_theme(theme: str = DEFAULT_THEME) -> dict[str, str]:
    """
    Return the complete theme palette.
    """

    normalized = str(theme).strip().lower()

    if normalized not in THEME_COLORS:
        logger.warning(
            "Theme %r unavailable; using %r.",
            normalized,
            DEFAULT_THEME,
        )
        normalized = DEFAULT_THEME

    return dict(THEME_COLORS[normalized])


def diagnostics() -> dict[str, Any]:
    """
    Return dashboard configuration diagnostics.

    This function is intentionally lightweight and safe to call during
    application startup.
    """

    avatar_path = get_avatar_path()

    result: dict[str, Any] = {
        "component": "dashboard.dashboard_config",
        "healthy": True,

        "application_name": APPLICATION_NAME,
        "assistant_name": ASSISTANT_NAME,
        "dashboard_name": DASHBOARD_NAME,
        "version": VERSION,

        "wake_word": FIXED_WAKE_WORD,
        "wake_word_locked": WAKE_WORD_LOCKED,

        "voice_gender": FIXED_VOICE_GENDER,
        "voice_gender_locked": VOICE_GENDER_LOCKED,

        "supported_languages": list(SUPPORTED_LANGUAGES),

        "project_root": str(PROJECT_ROOT),
        "dashboard_dir": str(DASHBOARD_DIR),
        "assets_dir": str(ASSETS_DIR),

        "avatar_exists": AVATAR_FILE.is_file(),
        "fallback_avatar_exists": FALLBACK_AVATAR_FILE.is_file(),
        "selected_avatar": str(avatar_path),

        "theme": {
            "active": DASHBOARD_SETTINGS.theme.active,
            "available": list(DASHBOARD_SETTINGS.theme.available),
        },

        "window": {
            "width": DEFAULT_WINDOW_WIDTH,
            "height": DEFAULT_WINDOW_HEIGHT,
            "min_width": MIN_WINDOW_WIDTH,
            "min_height": MIN_WINDOW_HEIGHT,
            "resizable": WINDOW_RESIZABLE,
        },

        "animation": {
            "enabled": DASHBOARD_SETTINGS.animation.enabled,
            "fps": DASHBOARD_SETTINGS.animation.fps,
            "3d": DASHBOARD_SETTINGS.animation.enable_3d,
            "depth": DASHBOARD_SETTINGS.animation.enable_depth,
            "perspective": DASHBOARD_SETTINGS.animation.enable_perspective,
        },

        "monitor": {
            "enabled": DASHBOARD_SETTINGS.system_monitor.enabled,
            "refresh_ms": DASHBOARD_SETTINGS.system_monitor.update_interval,
            "history_size": DASHBOARD_SETTINGS.system_monitor.history_size,
        },

        "terminal": {
            "enabled": DASHBOARD_SETTINGS.terminal.enabled,
            "max_lines": DASHBOARD_SETTINGS.terminal.max_lines,
        },

        "command": {
            "enabled": DASHBOARD_SETTINGS.command.enabled,
            "wake_word": DASHBOARD_SETTINGS.command.wake_word,
        },
    }

    logger.debug(
        "Dashboard configuration diagnostics: %s",
        result,
    )

    return result


def dashboard_diagnostics() -> dict[str, Any]:
    """
    Compatibility alias for ``diagnostics()``.
    """

    return diagnostics()


# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    # Paths
    "DASHBOARD_DIR",
    "PROJECT_ROOT",
    "ASSETS_DIR",
    "IMAGES_DIR",
    "ICONS_DIR",
    "SOUNDS_DIR",

    # Identity
    "APPLICATION_NAME",
    "ASSISTANT_NAME",
    "DASHBOARD_NAME",
    "VERSION",
    "APP_VERSION",
    "WINDOW_TITLE",

    # Assistant identity
    "ASSISTANT_WAKE_WORD",
    "FIXED_WAKE_WORD",
    "ASSISTANT_VOICE_GENDER",
    "FIXED_VOICE_GENDER",
    "VOICE_GENDER_LOCKED",
    "WAKE_WORD_LOCKED",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",

    # Window constants
    "DEFAULT_WINDOW_WIDTH",
    "DEFAULT_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "MIN_WINDOW_HEIGHT",
    "MAX_WINDOW_WIDTH",
    "MAX_WINDOW_HEIGHT",
    "WINDOW_RESIZABLE",
    "WINDOW_START_MAXIMIZED",
    "WINDOW_CENTER",

    # Colors
    "COLOR_BG",
    "COLOR_SURFACE",
    "COLOR_SURFACE_ALT",
    "COLOR_BORDER",
    "COLOR_BORDER_ACCENT",
    "COLOR_TEXT",
    "COLOR_TEXT_SECONDARY",
    "COLOR_MUTED",
    "COLOR_ACCENT",
    "COLOR_ACCENT_LIGHT",
    "COLOR_ACCENT_DARK",
    "COLOR_SUCCESS",
    "COLOR_WARNING",
    "COLOR_ERROR",
    "COLOR_INFO",
    "COLOR_GLOW",
    "COLOR_FEMALE_VOICE",
    "COLOR_CYAN",
    "COLOR_TEAL",
    "COLOR_PURPLE",

    # Theme
    "THEME_COLORS",
    "AVAILABLE_THEMES",
    "DEFAULT_THEME",
    "STATUS_COLORS",

    # Typography
    "FONT_FAMILY_DEFAULT",
    "FONT_FAMILY_MONO",
    "FONT_SIZE_TITLE",
    "FONT_SIZE_HEADING",
    "FONT_SIZE_BODY",
    "FONT_SIZE_SMALL",
    "FONT_SIZE_TINY",
    "FONT_WEIGHT_NORMAL",
    "FONT_WEIGHT_BOLD",

    # Avatar
    "AVATAR_FILE",
    "FALLBACK_AVATAR_FILE",
    "AVATAR_PATH",
    "FALLBACK_AVATAR_PATH",

    # Settings classes
    "WindowSettings",
    "UISettings",
    "AnimationSettings",
    "ThemeSettings",
    "PanelSettings",
    "AvatarSettings",
    "SystemMonitorSettings",
    "TerminalSettings",
    "CommandSettings",
    "HeaderSettings",
    "FooterSettings",
    "DashboardSettings",

    # Global settings
    "DASHBOARD_SETTINGS",

    # Helpers
    "get_color",
    "get_status_color",
    "get_avatar_path",
    "get_theme",

    # Diagnostics
    "diagnostics",
    "dashboard_diagnostics",
]


logger.info(
    "Dashboard configuration module fully loaded | "
    "application=%s | assistant=%s | version=%s",
    APPLICATION_NAME,
    ASSISTANT_NAME,
    VERSION,
)
