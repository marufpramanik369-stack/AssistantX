"""
AssistantX Dashboard - Styles
=============================

Centralized styling system for the AssistantX dashboard.

Responsibilities:
    - Colors
    - Typography
    - Spacing
    - Dimensions
    - Tkinter / ttk style configuration
    - Button styles
    - Entry styles
    - Combobox styles
    - Scrollbar styles
    - Reusable style helpers

No business logic belongs in this module.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

# ============================================================================
# COLOR PALETTE
# ============================================================================

@dataclass(frozen=True)
class Colors:
    """AssistantX dashboard color palette."""

    # Backgrounds
    background: str = "#101010"
    surface: str = "#151515"
    surface_alt: str = "#1A1A1A"
    card: str = "#181818"
    card_hover: str = "#202020"
    input_background: str = "#202020"

    # Borders
    border: str = "#292929"
    border_light: str = "#353535"

    # Text
    text: str = "#F5F5F5"
    text_secondary: str = "#B0B0B0"
    text_muted: str = "#858585"
    text_disabled: str = "#555555"

    # Accent
    accent: str = "#4F8CFF"
    accent_hover: str = "#6A9DFF"
    accent_dark: str = "#315FAF"

    # Status
    success: str = "#6FD08C"
    warning: str = "#E6B85C"
    danger: str = "#E05252"
    info: str = "#62B5E5"

    # Special
    white: str = "#FFFFFF"
    black: str = "#000000"


COLORS = Colors()


# ============================================================================
# TYPOGRAPHY
# ============================================================================

@dataclass(frozen=True)
class Typography:
    """Dashboard typography configuration."""

    font_family: str = "Segoe UI"

    # Sizes
    tiny: int = 8
    small: int = 9
    body: int = 10
    medium: int = 11
    subtitle: int = 12
    heading: int = 16
    title: int = 22
    large_title: int = 28

    # Weights
    normal: str = "normal"
    medium_weight: str = "normal"
    bold: str = "bold"


TYPOGRAPHY = Typography()


# ============================================================================
# SPACING
# ============================================================================

@dataclass(frozen=True)
class Spacing:
    """Standard dashboard spacing values."""

    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 20
    xxl: int = 28
    huge: int = 36


SPACING = Spacing()


# ============================================================================
# DIMENSIONS
# ============================================================================

@dataclass(frozen=True)
class Dimensions:
    """Standard dashboard component dimensions."""

    sidebar_width: int = 245
    sidebar_collapsed_width: int = 72

    header_height: int = 64
    footer_height: int = 60

    button_height: int = 40
    input_height: int = 38

    card_radius: int = 10
    border_width: int = 1

    avatar_small: int = 32
    avatar_medium: int = 44
    avatar_large: int = 72

    scrollbar_width: int = 8


DIMENSIONS = Dimensions()


# ============================================================================
# STYLE NAMES
# ============================================================================

class StyleNames:
    """Centralized ttk style names."""

    FRAME = "AssistantX.TFrame"

    LABEL = "AssistantX.TLabel"
    TITLE = "AssistantX.Title.TLabel"
    SUBTITLE = "AssistantX.Subtitle.TLabel"
    MUTED = "AssistantX.Muted.TLabel"

    BUTTON = "AssistantX.TButton"
    PRIMARY_BUTTON = "AssistantX.Primary.TButton"
    DANGER_BUTTON = "AssistantX.Danger.TButton"

    ENTRY = "AssistantX.TEntry"
    COMBOBOX = "AssistantX.TCombobox"

    CHECKBUTTON = "AssistantX.TCheckbutton"

    SCALE = "AssistantX.Horizontal.TScale"

    SCROLLBAR = "AssistantX.Vertical.TScrollbar"


STYLES = StyleNames()


# ============================================================================
# FONT HELPERS
# ============================================================================

def font(
    size: int | None = None,
    *,
    weight: str = "normal",
    family: str | None = None,
) -> tuple:
    """
    Create a standard AssistantX font tuple.

    Example:
        font(12, weight="bold")
    """

    return (
        family or TYPOGRAPHY.font_family,
        size or TYPOGRAPHY.body,
        weight,
    )


def title_font() -> tuple:
    return font(
        TYPOGRAPHY.title,
        weight="bold",
    )


def heading_font() -> tuple:
    return font(
        TYPOGRAPHY.heading,
        weight="bold",
    )


def body_font() -> tuple:
    return font(
        TYPOGRAPHY.body,
    )


def small_font() -> tuple:
    return font(
        TYPOGRAPHY.small,
    )


# ============================================================================
# TKINTER STYLE CONFIGURATION
# ============================================================================

def configure_styles(
    root: tk.Misc,
) -> ttk.Style:
    """
    Configure all global ttk styles.

    Call once during application startup.
    """

    style = ttk.Style(root)

    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")

    # ------------------------------------------------------------------------
    # Frame
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.FRAME,
        background=COLORS.background,
    )

    # ------------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.LABEL,
        background=COLORS.background,
        foreground=COLORS.text,
        font=body_font(),
    )

    style.configure(
        STYLES.TITLE,
        background=COLORS.background,
        foreground=COLORS.text,
        font=title_font(),
    )

    style.configure(
        STYLES.SUBTITLE,
        background=COLORS.background,
        foreground=COLORS.text_secondary,
        font=font(
            TYPOGRAPHY.subtitle,
        ),
    )

    style.configure(
        STYLES.MUTED,
        background=COLORS.background,
        foreground=COLORS.text_muted,
        font=small_font(),
    )

    # ------------------------------------------------------------------------
    # Normal Button
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.BUTTON,
        background=COLORS.surface_alt,
        foreground=COLORS.text,
        font=font(
            TYPOGRAPHY.body,
            weight="bold",
        ),
        padding=(
            SPACING.md,
            SPACING.sm,
        ),
        borderwidth=0,
        relief="flat",
    )

    style.map(
        STYLES.BUTTON,
        background=[
            ("active", COLORS.card_hover),
            ("pressed", COLORS.border),
            ("disabled", COLORS.surface),
        ],
        foreground=[
            ("disabled", COLORS.text_disabled),
            ("active", COLORS.text),
        ],
    )

    # ------------------------------------------------------------------------
    # Primary Button
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.PRIMARY_BUTTON,
        background=COLORS.accent,
        foreground=COLORS.white,
        font=font(
            TYPOGRAPHY.body,
            weight="bold",
        ),
        padding=(
            SPACING.lg,
            SPACING.sm,
        ),
        borderwidth=0,
        relief="flat",
    )

    style.map(
        STYLES.PRIMARY_BUTTON,
        background=[
            ("active", COLORS.accent_hover),
            ("pressed", COLORS.accent_dark),
            ("disabled", COLORS.surface),
        ],
        foreground=[
            ("disabled", COLORS.text_disabled),
        ],
    )

    # ------------------------------------------------------------------------
    # Danger Button
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.DANGER_BUTTON,
        background=COLORS.danger,
        foreground=COLORS.white,
        font=font(
            TYPOGRAPHY.body,
            weight="bold",
        ),
        padding=(
            SPACING.md,
            SPACING.sm,
        ),
        borderwidth=0,
        relief="flat",
    )

    style.map(
        STYLES.DANGER_BUTTON,
        background=[
            ("active", "#F06A6A"),
            ("pressed", "#B83C3C"),
            ("disabled", COLORS.surface),
        ],
    )

    # ------------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.ENTRY,
        fieldbackground=COLORS.input_background,
        foreground=COLORS.text,
        insertcolor=COLORS.text,
        bordercolor=COLORS.border,
        lightcolor=COLORS.border,
        darkcolor=COLORS.border,
        padding=SPACING.sm,
        relief="flat",
    )

    style.map(
        STYLES.ENTRY,
        bordercolor=[
            ("focus", COLORS.accent),
        ],
        lightcolor=[
            ("focus", COLORS.accent),
        ],
        darkcolor=[
            ("focus", COLORS.accent),
        ],
    )

    # ------------------------------------------------------------------------
    # Combobox
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.COMBOBOX,
        fieldbackground=COLORS.input_background,
        background=COLORS.input_background,
        foreground=COLORS.text,
        arrowcolor=COLORS.text_secondary,
        bordercolor=COLORS.border,
        lightcolor=COLORS.border,
        darkcolor=COLORS.border,
        padding=SPACING.sm,
    )

    style.map(
        STYLES.COMBOBOX,
        fieldbackground=[
            ("readonly", COLORS.input_background),
        ],
        foreground=[
            ("readonly", COLORS.text),
        ],
        bordercolor=[
            ("focus", COLORS.accent),
        ],
    )

    # ------------------------------------------------------------------------
    # Checkbutton
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.CHECKBUTTON,
        background=COLORS.card,
        foreground=COLORS.text,
        font=body_font(),
        padding=SPACING.xs,
        borderwidth=0,
    )

    style.map(
        STYLES.CHECKBUTTON,
        background=[
            ("active", COLORS.card),
        ],
        foreground=[
            ("disabled", COLORS.text_disabled),
        ],
    )

    # ------------------------------------------------------------------------
    # Scale
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.SCALE,
        background=COLORS.card,
        troughcolor=COLORS.input_background,
        bordercolor=COLORS.card,
        lightcolor=COLORS.card,
        darkcolor=COLORS.card,
    )

    # ------------------------------------------------------------------------
    # Scrollbar
    # ------------------------------------------------------------------------

    style.configure(
        STYLES.SCROLLBAR,
        background=COLORS.surface_alt,
        troughcolor=COLORS.background,
        bordercolor=COLORS.background,
        arrowcolor=COLORS.text_muted,
        width=DIMENSIONS.scrollbar_width,
    )

    style.map(
        STYLES.SCROLLBAR,
        background=[
            ("active", COLORS.accent),
        ],
    )

    return style


# ============================================================================
# TK BUTTON HELPER
# ============================================================================

def configure_button(
    button: tk.Button,
    *,
    primary: bool = False,
    danger: bool = False,
    width: int | None = None,
) -> tk.Button:
    """
    Apply AssistantX styling to a classic tk.Button.

    Useful for existing dashboard components that use tk.Button.
    """

    if danger:
        background = COLORS.danger
        active_background = "#F06A6A"

    elif primary:
        background = COLORS.accent
        active_background = COLORS.accent_hover

    else:
        background = COLORS.surface_alt
        active_background = COLORS.card_hover

    button.configure(
        bg=background,
        fg=COLORS.white if (
            primary or danger
        ) else COLORS.text,

        activebackground=active_background,

        activeforeground=COLORS.white,

        relief="flat",
        bd=0,

        highlightthickness=0,

        font=font(
            TYPOGRAPHY.body,
            weight="bold",
        ),

        cursor="hand2",
    )

    if width is not None:
        button.configure(
            width=width,
        )

    return button


# ============================================================================
# LABEL HELPERS
# ============================================================================

def configure_label(
    label: tk.Label,
    *,
    muted: bool = False,
    title: bool = False,
) -> tk.Label:
    """Apply AssistantX label styling."""

    if title:

        label.configure(
            bg=COLORS.background,
            fg=COLORS.text,
            font=title_font(),
        )

    elif muted:

        label.configure(
            bg=COLORS.background,
            fg=COLORS.text_muted,
            font=small_font(),
        )

    else:

        label.configure(
            bg=COLORS.background,
            fg=COLORS.text,
            font=body_font(),
        )

    return label


# ============================================================================
# CARD HELPER
# ============================================================================

def create_card(
    parent: tk.Misc,
    *,
    padding: int = SPACING.lg,
    background: str | None = None,
) -> tk.Frame:
    """
    Create a standard AssistantX card.

    Note:
        Tkinter Frame does not provide native rounded corners.
        The border/highlight system provides the visual card effect.
    """

    card = tk.Frame(
        parent,
        bg=background or COLORS.card,
        bd=0,
        highlightthickness=1,
        highlightbackground=COLORS.border,
        highlightcolor=COLORS.border,
    )

    # Internal padding container
    content = tk.Frame(
        card,
        bg=background or COLORS.card,
    )

    content.pack(
        fill="both",
        expand=True,
        padx=padding,
        pady=padding,
    )

    # Store content reference
    card.content = content  # type: ignore[attr-defined]

    return card


# ============================================================================
# ENTRY HELPER
# ============================================================================

def style_entry(
    entry: tk.Entry,
) -> tk.Entry:
    """Style a classic Tkinter Entry."""

    entry.configure(
        bg=COLORS.input_background,
        fg=COLORS.text,
        insertbackground=COLORS.text,
        selectbackground=COLORS.accent,
        selectforeground=COLORS.white,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLORS.border,
        highlightcolor=COLORS.accent,
        font=body_font(),
    )

    return entry


# ============================================================================
# TEXT HELPER
# ============================================================================

def style_text(
    text: tk.Text,
) -> tk.Text:
    """Style a classic Tkinter Text widget."""

    text.configure(
        bg=COLORS.input_background,
        fg=COLORS.text,
        insertbackground=COLORS.text,
        selectbackground=COLORS.accent,
        selectforeground=COLORS.white,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=COLORS.border,
        highlightcolor=COLORS.accent,
        font=body_font(),
        padx=SPACING.md,
        pady=SPACING.md,
    )

    return text


# ============================================================================
# STATUS COLORS
# ============================================================================

def status_color(status: str) -> str:
    """
    Return a standard color for a status.

    Supported:
        online
        ready
        success
        warning
        busy
        error
        offline
        disabled
    """

    normalized = str(
        status
    ).strip().lower()

    mapping = {
        "online": COLORS.success,
        "ready": COLORS.success,
        "success": COLORS.success,

        "warning": COLORS.warning,
        "pending": COLORS.warning,

        "busy": COLORS.accent,
        "working": COLORS.accent,

        "error": COLORS.danger,
        "failed": COLORS.danger,

        "offline": COLORS.text_muted,
        "disabled": COLORS.text_disabled,
    }

    return mapping.get(
        normalized,
        COLORS.text_muted,
    )


# ============================================================================
# THEME EXPORT
# ============================================================================

def theme_dict() -> dict[str, dict[str, str]]:
    """
    Return theme values as a serializable dictionary.
    """

    return {
        "colors": {
            "background": COLORS.background,
            "surface": COLORS.surface,
            "surface_alt": COLORS.surface_alt,
            "card": COLORS.card,
            "card_hover": COLORS.card_hover,
            "input_background": COLORS.input_background,
            "border": COLORS.border,
            "border_light": COLORS.border_light,
            "text": COLORS.text,
            "text_secondary": COLORS.text_secondary,
            "text_muted": COLORS.text_muted,
            "accent": COLORS.accent,
            "accent_hover": COLORS.accent_hover,
            "accent_dark": COLORS.accent_dark,
            "success": COLORS.success,
            "warning": COLORS.warning,
            "danger": COLORS.danger,
            "info": COLORS.info,
        }
    }


# ============================================================================
# DEFAULT STYLE INITIALIZER
# ============================================================================

def initialize_styles(
    root: tk.Misc,
) -> ttk.Style:
    """
    Initialize all AssistantX styles.

    Recommended usage in app.py:

        from dashboard.styles import initialize_styles

        initialize_styles(root)
    """

    return configure_styles(root)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Instances
    "COLORS",
    "DIMENSIONS",
    "SPACING",
    "STYLES",
    "TYPOGRAPHY",
    # Data
    "Colors",
    "Dimensions",
    "Spacing",
    "StyleNames",
    "Typography",
    "body_font",
    "configure_button",
    "configure_label",
    # Styling
    "configure_styles",
    "create_card",
    # Fonts
    "font",
    "heading_font",
    "initialize_styles",
    "small_font",
    # Helpers
    "status_color",
    "style_entry",
    "style_text",
    "theme_dict",
    "title_font",
]
