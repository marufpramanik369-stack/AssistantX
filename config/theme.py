"""
AssistantX - Theme System
=========================

Centralized, framework-agnostic theme management for AssistantX.

Features
--------
- Dark / Light / System theme support
- JSON theme loading
- Built-in fallback palettes
- Thread-safe ThemeManager
- Color / typography / spacing tokens
- CSS variable generation
- Plain dictionary export
- Runtime theme switching
- Theme validation
- Diagnostics
- Custom theme registration
- No UI-framework dependency

Compatible with:
    - CustomTkinter
    - Tkinter
    - PySide / PyQt
    - Web / CSS
    - Future UI frameworks

Recommended usage
-----------------

    from config.theme import theme_manager

    theme = theme_manager.active

    print(theme.colors.primary)
    print(theme.typography.size_md)

    theme_manager.set_theme("dark")
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from config.constants import ThemeMode
from config.settings import settings_manager

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# TYPES
# ============================================================

ThemeName = Literal["dark", "light"]


# ============================================================
# DEFAULT CONSTANTS
# ============================================================

DEFAULT_THEME: ThemeName = "dark"

DEFAULT_FONT_FAMILY = (
    "Segoe UI, -apple-system, BlinkMacSystemFont, "
    "Roboto, sans-serif"
)

DEFAULT_MONO_FONT = (
    "Cascadia Code, Consolas, "
    "Liberation Mono, monospace"
)


# ============================================================
# COLOR PALETTE
# ============================================================

@dataclass(frozen=True)
class ColorPalette:
    """
    Semantic color tokens used throughout AssistantX.

    Keep UI code dependent on these semantic names instead of
    hard-coded hexadecimal values.
    """

    background: str
    surface: str
    surface_alt: str

    primary: str
    primary_variant: str
    secondary: str
    accent: str

    text_primary: str
    text_secondary: str
    text_disabled: str

    border: str
    divider: str

    success: str
    warning: str
    error: str
    info: str

    chat_bubble_user: str
    chat_bubble_assistant: str

    chat_bubble_user_text: str
    chat_bubble_assistant_text: str

    input_background: str
    button_background: str
    button_hover: str

    sidebar: str
    sidebar_hover: str
    sidebar_active: str

    scrollbar: str
    shadow: str


# ============================================================
# TYPOGRAPHY
# ============================================================

@dataclass(frozen=True)
class Typography:
    """
    Global typography tokens.

    Sizes are expressed in points/pixels depending on the
    consuming UI framework.
    """

    font_family: str = DEFAULT_FONT_FAMILY
    font_family_mono: str = DEFAULT_MONO_FONT

    size_xs: int = 10
    size_sm: int = 12
    size_md: int = 14
    size_lg: int = 16
    size_xl: int = 20
    size_xxl: int = 28

    weight_regular: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700

    line_height: float = 1.4


# ============================================================
# SPACING
# ============================================================

@dataclass(frozen=True)
class Spacing:
    """
    Global spacing and border-radius tokens.
    """

    xs: int = 4
    sm: int = 8
    md: int = 16
    lg: int = 24
    xl: int = 32
    xxl: int = 48

    radius_sm: int = 4
    radius_md: int = 8
    radius_lg: int = 16
    radius_xl: int = 20
    radius_pill: int = 999


# ============================================================
# THEME
# ============================================================

@dataclass(frozen=True)
class Theme:
    """
    Complete AssistantX theme configuration.
    """

    name: ThemeName
    colors: ColorPalette
    typography: Typography
    spacing: Spacing

    def to_dict(self) -> dict[str, Any]:
        """
        Convert theme into a JSON-serializable dictionary.
        """

        return {
            "name": self.name,
            "colors": asdict(self.colors),
            "typography": asdict(self.typography),
            "spacing": asdict(self.spacing),
        }


# ============================================================
# BUILT-IN DARK PALETTE
# ============================================================

DARK_PALETTE = ColorPalette(
    background="#0B0F14",
    surface="#111820",
    surface_alt="#17212B",

    primary="#4F8CFF",
    primary_variant="#6A9EFF",
    secondary="#8B5CF6",
    accent="#00D4FF",

    text_primary="#F5F7FA",
    text_secondary="#AAB4C0",
    text_disabled="#6F7B88",

    border="#25313D",
    divider="#1D2731",

    success="#22C55E",
    warning="#F59E0B",
    error="#EF4444",
    info="#38BDF8",

    chat_bubble_user="#1E3A5F",
    chat_bubble_assistant="#151D26",

    chat_bubble_user_text="#FFFFFF",
    chat_bubble_assistant_text="#F5F7FA",

    input_background="#10171F",
    button_background="#182330",
    button_hover="#223246",

    sidebar="#0E141B",
    sidebar_hover="#17212B",
    sidebar_active="#1C2B3A",

    scrollbar="#25313D",
    shadow="rgba(0, 0, 0, 0.40)",
)


# ============================================================
# BUILT-IN LIGHT PALETTE
# ============================================================

LIGHT_PALETTE = ColorPalette(
    background="#F5F7FA",
    surface="#FFFFFF",
    surface_alt="#EEF2F6",

    primary="#2563EB",
    primary_variant="#1D4ED8",
    secondary="#7C3AED",
    accent="#0891B2",

    text_primary="#111827",
    text_secondary="#4B5563",
    text_disabled="#6B7280",

    border="#D9E0E7",
    divider="#E5E7EB",

    success="#16A34A",
    warning="#D97706",
    error="#DC2626",
    info="#0284C7",

    chat_bubble_user="#DBEAFE",
    chat_bubble_assistant="#FFFFFF",

    chat_bubble_user_text="#111827",
    chat_bubble_assistant_text="#111827",

    input_background="#FFFFFF",
    button_background="#F1F5F9",
    button_hover="#E2E8F0",

    sidebar="#F8FAFC",
    sidebar_hover="#EEF2F7",
    sidebar_active="#E2E8F0",

    scrollbar="#CBD5E1",
    shadow="rgba(0, 0, 0, 0.12)",
)


# ============================================================
# DEFAULT TOKENS
# ============================================================

_DEFAULT_TYPOGRAPHY = Typography()
_DEFAULT_SPACING = Spacing()


# ============================================================
# BUILT-IN THEMES
# ============================================================

THEMES: dict[ThemeName, Theme] = {
    "dark": Theme(
        name="dark",
        colors=DARK_PALETTE,
        typography=_DEFAULT_TYPOGRAPHY,
        spacing=_DEFAULT_SPACING,
    ),
    "light": Theme(
        name="light",
        colors=LIGHT_PALETTE,
        typography=_DEFAULT_TYPOGRAPHY,
        spacing=_DEFAULT_SPACING,
    ),
}


# ============================================================
# THEME FILE LOCATIONS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

THEME_DIRECTORY = PROJECT_ROOT / "assets" / "themes"

THEME_FILES: dict[ThemeName, Path] = {
    "dark": THEME_DIRECTORY / "dark.json",
    "light": THEME_DIRECTORY / "light.json",
}


# ============================================================
# SYSTEM THEME DETECTION
# ============================================================

def _detect_system_theme() -> ThemeName:
    """
    Detect the operating system's preferred theme.

    Uses darkdetect when available.

    Falls back safely to dark mode.
    """

    try:
        import darkdetect  # type: ignore

        result = darkdetect.theme()

        if result:
            result = result.lower()

            if result == "light":
                return "light"

            if result == "dark":
                return "dark"

    except (ImportError, AttributeError):
        logger.debug(
            "System theme detection unavailable."
        )

    return DEFAULT_THEME


# ============================================================
# VALIDATION HELPERS
# ============================================================

def _validate_color(value: Any) -> str:
    """
    Validate and normalize a color value.
    """

    if not isinstance(value, str):
        raise TypeError(
            f"Color must be a string, got {type(value).__name__}"
        )

    value = value.strip()

    if not value:
        raise ValueError("Color value cannot be empty.")

    return value


def _safe_int(value: Any, default: int) -> int:
    """
    Safely convert a value to integer.
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    """
    Safely convert a value to float.
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# JSON THEME LOADER
# ============================================================

def _load_json_theme(
    name: ThemeName,
    path: Path,
    fallback: Theme,
) -> Theme:
    """
    Load a theme from JSON.

    Missing fields automatically fall back to the built-in theme.

    This makes theme files backward compatible.
    """

    if not path.exists():
        logger.debug(
            "Theme file does not exist: %s",
            path,
        )
        return fallback

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not load theme '%s': %s",
            name,
            exc,
        )
        return fallback

    if not isinstance(data, dict):
        logger.warning(
            "Invalid theme format: %s",
            path,
        )
        return fallback

    colors_data = data.get("colors", {})
    typography_data = data.get("typography", {})
    spacing_data = data.get("spacing", {})

    if not isinstance(colors_data, Mapping):
        colors_data = {}

    if not isinstance(typography_data, Mapping):
        typography_data = {}

    if not isinstance(spacing_data, Mapping):
        spacing_data = {}

    # --------------------------------------------------------
    # Colors
    # --------------------------------------------------------

    default_colors = asdict(fallback.colors)

    merged_colors = {
        **default_colors,
        **dict(colors_data),
    }

    for key, value in merged_colors.items():
        try:
            merged_colors[key] = _validate_color(
                value
            )
        except ValueError:
            merged_colors[key] = default_colors[key]

    colors = ColorPalette(
        **{
            key: merged_colors[key]
            for key in default_colors
        }
    )

    # --------------------------------------------------------
    # Typography
    # --------------------------------------------------------

    default_typography = asdict(fallback.typography)

    typography = Typography(
        font_family=str(
            typography_data.get(
                "font_family",
                default_typography["font_family"],
            )
        ),
        font_family_mono=str(
            typography_data.get(
                "font_family_mono",
                default_typography["font_family_mono"],
            )
        ),
        size_xs=_safe_int(
            typography_data.get("size_xs"),
            default_typography["size_xs"],
        ),
        size_sm=_safe_int(
            typography_data.get("size_sm"),
            default_typography["size_sm"],
        ),
        size_md=_safe_int(
            typography_data.get("size_md"),
            default_typography["size_md"],
        ),
        size_lg=_safe_int(
            typography_data.get("size_lg"),
            default_typography["size_lg"],
        ),
        size_xl=_safe_int(
            typography_data.get("size_xl"),
            default_typography["size_xl"],
        ),
        size_xxl=_safe_int(
            typography_data.get("size_xxl"),
            default_typography["size_xxl"],
        ),
        weight_regular=_safe_int(
            typography_data.get("weight_regular"),
            default_typography["weight_regular"],
        ),
        weight_medium=_safe_int(
            typography_data.get("weight_medium"),
            default_typography["weight_medium"],
        ),
        weight_semibold=_safe_int(
            typography_data.get("weight_semibold"),
            default_typography["weight_semibold"],
        ),
        weight_bold=_safe_int(
            typography_data.get("weight_bold"),
            default_typography["weight_bold"],
        ),
        line_height=_safe_float(
            typography_data.get("line_height"),
            default_typography["line_height"],
        ),
    )

    # --------------------------------------------------------
    # Spacing
    # --------------------------------------------------------

    default_spacing = asdict(fallback.spacing)

    spacing = Spacing(
        xs=_safe_int(
            spacing_data.get("xs"),
            default_spacing["xs"],
        ),
        sm=_safe_int(
            spacing_data.get("sm"),
            default_spacing["sm"],
        ),
        md=_safe_int(
            spacing_data.get("md"),
            default_spacing["md"],
        ),
        lg=_safe_int(
            spacing_data.get("lg"),
            default_spacing["lg"],
        ),
        xl=_safe_int(
            spacing_data.get("xl"),
            default_spacing["xl"],
        ),
        xxl=_safe_int(
            spacing_data.get("xxl"),
            default_spacing["xxl"],
        ),
        radius_sm=_safe_int(
            spacing_data.get("radius_sm"),
            default_spacing["radius_sm"],
        ),
        radius_md=_safe_int(
            spacing_data.get("radius_md"),
            default_spacing["radius_md"],
        ),
        radius_lg=_safe_int(
            spacing_data.get("radius_lg"),
            default_spacing["radius_lg"],
        ),
        radius_xl=_safe_int(
            spacing_data.get("radius_xl"),
            default_spacing["radius_xl"],
        ),
        radius_pill=_safe_int(
            spacing_data.get("radius_pill"),
            default_spacing["radius_pill"],
        ),
    )

    return Theme(
        name=name,
        colors=colors,
        typography=typography,
        spacing=spacing,
    )


# ============================================================
# THEME MANAGER
# ============================================================

class ThemeManager:
    """
    Thread-safe manager for AssistantX themes.
    """

    def __init__(
        self,
        *,
        load_json: bool = True,
    ) -> None:

        self._lock = threading.RLock()

        self._themes: dict[str, Theme] = dict(THEMES)

        self._active: Theme = self._themes[
            DEFAULT_THEME
        ]

        self._load_json_enabled = load_json

        self.refresh()


    # --------------------------------------------------------
    # Theme loading
    # --------------------------------------------------------

    def reload(self) -> None:
        """
        Reload dark/light themes from JSON files.
        """

        with self._lock:

            for name in ("dark", "light"):

                fallback = THEMES[name]

                theme = _load_json_theme(
                    name,
                    THEME_FILES[name],
                    fallback,
                )

                self._themes[name] = theme

        logger.info(
            "AssistantX themes reloaded."
        )


    # --------------------------------------------------------
    # Refresh
    # --------------------------------------------------------

    def refresh(self) -> Theme:
        """
        Resolve the active theme from settings.
        """

        with self._lock:

            if self._load_json_enabled:
                self.reload()

            mode_value = settings_manager.get(
                "ui.theme",
                ThemeMode.DARK.value,
            )

            try:
                mode = ThemeMode(mode_value)

            except (ValueError, TypeError):
                logger.warning(
                    "Invalid theme mode '%s'. "
                    "Falling back to dark.",
                    mode_value,
                )

                mode = ThemeMode.DARK

            if mode == ThemeMode.SYSTEM:

                resolved_name = _detect_system_theme()

            elif mode == ThemeMode.LIGHT:

                resolved_name = "light"

            else:

                resolved_name = "dark"

            self._active = self._themes[
                resolved_name
            ]

            return self._active


    # --------------------------------------------------------
    # Active theme
    # --------------------------------------------------------

    @property
    def active(self) -> Theme:
        """
        Return the currently active theme.
        """

        with self._lock:
            return self._active


    @property
    def active_name(self) -> str:
        """
        Return active theme name.
        """

        with self._lock:
            return self._active.name


    # --------------------------------------------------------
    # Theme switching
    # --------------------------------------------------------

    def set_theme(
        self,
        name: ThemeName,
    ) -> Theme:
        """
        Change and persist the active theme.

        Returns:
            Theme: Newly activated theme.
        """

        name = str(name).strip().lower()

        if name not in self._themes:
            raise ValueError(
                f"Unknown theme '{name}'. "
                f"Available themes: "
                f"{list(self._themes)}"
            )

        with self._lock:

            settings_manager.set(
                "ui.theme",
                name,
            )

            self._active = self._themes[name]

        logger.info(
            "AssistantX theme switched to '%s'.",
            name,
        )

        return self._active


    # --------------------------------------------------------
    # Custom theme support
    # --------------------------------------------------------

    def register_theme(
        self,
        theme: Theme,
        *,
        overwrite: bool = False,
    ) -> None:
        """
        Register a custom theme.

        Useful for future plugins.

        Example:
            theme_manager.register_theme(my_theme)
        """

        if not isinstance(theme, Theme):
            raise TypeError(
                "theme must be a Theme instance."
            )

        with self._lock:

            if (
                theme.name in self._themes
                and not overwrite
            ):
                raise ValueError(
                    f"Theme '{theme.name}' "
                    "is already registered."
                )

            self._themes[theme.name] = theme

        logger.info(
            "Custom theme registered: %s",
            theme.name,
        )


    # --------------------------------------------------------
    # Theme lookup
    # --------------------------------------------------------

    def get_theme(
        self,
        name: str,
    ) -> Theme | None:
        """
        Get a registered theme by name.
        """

        with self._lock:
            return self._themes.get(
                str(name).strip().lower()
            )


    def list_themes(self) -> list[str]:
        """
        Return all registered theme names.
        """

        with self._lock:
            return list(self._themes.keys())


    # --------------------------------------------------------
    # CSS
    # --------------------------------------------------------

    def to_css_variables(
        self,
        theme: Theme | None = None,
    ) -> str:
        """
        Convert a theme into CSS custom properties.
        """

        with self._lock:

            selected = (
                theme
                if theme is not None
                else self._active
            )

            colors = asdict(
                selected.colors
            )

            typography = asdict(
                selected.typography
            )

            spacing = asdict(
                selected.spacing
            )

        lines = [
            ":root {"
        ]

        # Colors
        for key, value in colors.items():

            css_name = (
                key
                .replace("_", "-")
                .lower()
            )

            lines.append(
                f"  --color-{css_name}: {value};"
            )

        # Typography
        for key, value in typography.items():

            css_name = (
                key
                .replace("_", "-")
                .lower()
            )

            if isinstance(value, (int, float)):
                css_value = str(value) if "weight" in key else f"{value}px"
            else:
                css_value = str(value)

            lines.append(
                f"  --{css_name}: {css_value};"
            )

        # Spacing
        for key, value in spacing.items():

            css_name = (
                key
                .replace("_", "-")
                .lower()
            )

            lines.append(
                f"  --{css_name}: {value}px;"
            )

        lines.append("}")

        return "\n".join(lines)


    # --------------------------------------------------------
    # Dictionary export
    # --------------------------------------------------------

    def to_dict(
        self,
        theme: Theme | None = None,
    ) -> dict[str, Any]:
        """
        Return the selected theme as a plain dictionary.
        """

        selected = (
            theme
            if theme is not None
            else self.active
        )

        return selected.to_dict()


    # --------------------------------------------------------
    # JSON export
    # --------------------------------------------------------

    def save_json(
        self,
        path: str | Path,
        theme: Theme | None = None,
    ) -> Path:
        """
        Save a theme to a JSON file.
        """

        selected = (
            theme
            if theme is not None
            else self.active
        )

        target = Path(path)

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with target.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                selected.to_dict(),
                file,
                indent=4,
                ensure_ascii=False,
            )

        logger.info(
            "Theme saved: %s",
            target,
        )

        return target


    # --------------------------------------------------------
    # Diagnostics
    # --------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:
        """
        Return theme-system diagnostics.
        """

        with self._lock:

            return {
                "component": "ThemeManager",
                "status": "healthy",
                "active_theme": self._active.name,
                "registered_themes": list(
                    self._themes.keys()
                ),
                "json_loading": (
                    self._load_json_enabled
                ),
                "theme_files": {
                    name: {
                        "path": str(path),
                        "exists": path.exists(),
                    }
                    for name, path
                    in THEME_FILES.items()
                },
            }


# ============================================================
# GLOBAL SINGLETON
# ============================================================

theme_manager = ThemeManager()


# ============================================================
# CONVENIENCE HELPERS
# ============================================================

def get_theme() -> Theme:
    """
    Return the currently active theme.
    """

    return theme_manager.active


def set_theme(
    name: ThemeName,
) -> Theme:
    """
    Switch the active theme.
    """

    return theme_manager.set_theme(name)


def reload_themes() -> Theme:
    """
    Reload theme files and refresh the active theme.
    """

    return theme_manager.refresh()


def diagnostics() -> dict[str, Any]:
    """
    Return theme manager diagnostics.
    """

    return theme_manager.diagnostics()


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    # Built-in palettes
    "DARK_PALETTE",
    "LIGHT_PALETTE",
    # Theme registry
    "THEMES",
    "THEME_DIRECTORY",
    "THEME_FILES",
    # Dataclasses
    "ColorPalette",
    "Spacing",
    "Theme",
    # Manager
    "ThemeManager",
    # Types
    "ThemeName",
    "Typography",
    "diagnostics",
    # Helpers
    "get_theme",
    "reload_themes",
    "set_theme",
    "theme_manager",
]
