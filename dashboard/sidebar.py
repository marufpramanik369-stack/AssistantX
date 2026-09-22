"""
AssistantX Dashboard - Sidebar
==============================

Professional navigation sidebar for AssistantX.

Features:
    - Navigation items
    - Active item highlighting
    - Collapsible sidebar
    - Hover effects
    - Profile area
    - Settings button
    - Callback based navigation
    - Keyboard-friendly structure
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

# ============================================================================
# COLORS
# ============================================================================

BG = "#141414"
SURFACE = "#181818"
HOVER = "#202020"
ACTIVE = "#263A5C"

TEXT = "#F5F5F5"
MUTED = "#8F8F8F"

ACCENT = "#4F8CFF"
SUCCESS = "#6FD08C"
BORDER = "#292929"


FONT = "Segoe UI"


# ============================================================================
# ENUMS
# ============================================================================

class SidebarPage(str, Enum):
    """Available dashboard pages."""

    HOME = "home"
    CHAT = "chat"
    HISTORY = "history"
    VOICE = "voice"
    AUTOMATION = "automation"
    MEMORY = "memory"
    SETTINGS = "settings"


# ============================================================================
# DATA
# ============================================================================

@dataclass(frozen=True)
class SidebarItem:
    """Sidebar navigation item."""

    page: SidebarPage
    title: str
    icon: str
    description: str = ""


DEFAULT_ITEMS = (
    SidebarItem(
        SidebarPage.HOME,
        "Home",
        "⌂",
        "Dashboard",
    ),
    SidebarItem(
        SidebarPage.CHAT,
        "Chat",
        "◉",
        "Talk with AssistantX",
    ),
    SidebarItem(
        SidebarPage.HISTORY,
        "History",
        "◷",
        "Conversation history",
    ),
    SidebarItem(
        SidebarPage.VOICE,
        "Voice",
        "♬",
        "Voice assistant",
    ),
    SidebarItem(
        SidebarPage.AUTOMATION,
        "Automation",
        "⚡",
        "PC automation",
    ),
    SidebarItem(
        SidebarPage.MEMORY,
        "Memory",
        "◆",
        "Assistant memory",
    ),
)


# ============================================================================
# SIDEBAR
# ============================================================================

class Sidebar(tk.Frame):
    """
    Main AssistantX navigation sidebar.

    Parameters
    ----------
    parent:
        Parent Tkinter widget.

    on_navigate:
        Callback receiving SidebarPage when a navigation item is clicked.

    on_settings:
        Callback for Settings button.

    width:
        Initial sidebar width.

    collapsed_width:
        Width when sidebar is collapsed.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_navigate: Callable[[SidebarPage], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        width: int = 245,
        collapsed_width: int = 72,
        items: tuple[SidebarItem, ...] = DEFAULT_ITEMS,
        **kwargs,
    ) -> None:

        super().__init__(
            parent,
            bg=BG,
            width=width,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.parent = parent

        self.on_navigate = on_navigate
        self.on_settings = on_settings

        self.sidebar_width = width
        self.collapsed_width = collapsed_width

        self.items = tuple(items)

        self.active_page = SidebarPage.HOME

        self.collapsed = False

        self._buttons: dict[
            SidebarPage,
            tk.Frame,
        ] = {}

        self._labels: dict[
            SidebarPage,
            tuple[tk.Label, tk.Label],
        ] = {}

        self._build()

    # ========================================================================
    # BUILD
    # ========================================================================

    def _build(self) -> None:

        self.pack_propagate(False)

        self._build_header()
        self._build_navigation()
        self._build_bottom()

        self._refresh_active_state()

    # ========================================================================
    # HEADER
    # ========================================================================

    def _build_header(self) -> None:

        self.header = tk.Frame(
            self,
            bg=BG,
            height=72,
        )

        self.header.pack(
            fill="x",
            padx=12,
            pady=(10, 4),
        )

        self.header.pack_propagate(False)

        # Logo
        self.logo = tk.Label(
            self.header,
            text="X",
            bg=ACCENT,
            fg="white",
            font=(FONT, 14, "bold"),
            width=3,
            height=1,
        )

        self.logo.pack(
            side="left",
            padx=(4, 10),
            pady=10,
        )

        # Brand
        self.brand_frame = tk.Frame(
            self.header,
            bg=BG,
        )

        self.brand_frame.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.brand = tk.Label(
            self.brand_frame,
            text="AssistantX",
            bg=BG,
            fg=TEXT,
            font=(FONT, 12, "bold"),
        )

        self.brand.pack(
            anchor="w",
            pady=(12, 0),
        )

        self.brand_subtitle = tk.Label(
            self.brand_frame,
            text="AI Assistant",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
        )

        self.brand_subtitle.pack(
            anchor="w",
        )

        # Collapse button
        self.toggle_button = tk.Button(
            self.header,
            text="‹",
            command=self.toggle,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=(FONT, 18),
            cursor="hand2",
        )

        self.toggle_button.pack(
            side="right",
            padx=2,
        )

    # ========================================================================
    # NAVIGATION
    # ========================================================================

    def _build_navigation(self) -> None:

        self.navigation = tk.Frame(
            self,
            bg=BG,
        )

        self.navigation.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=8,
        )

        for item in self.items:
            self._create_navigation_item(item)

    def _create_navigation_item(
        self,
        item: SidebarItem,
    ) -> None:

        button = tk.Frame(
            self.navigation,
            bg=BG,
            height=46,
            cursor="hand2",
        )

        button.pack(
            fill="x",
            pady=2,
        )

        button.pack_propagate(False)

        # Active indicator
        indicator = tk.Frame(
            button,
            bg=BG,
            width=3,
        )

        indicator.pack(
            side="left",
            fill="y",
        )

        # Icon
        icon = tk.Label(
            button,
            text=item.icon,
            bg=BG,
            fg=MUTED,
            font=(FONT, 15),
            width=3,
        )

        icon.pack(
            side="left",
            padx=(5, 4),
        )

        # Text container
        text_frame = tk.Frame(
            button,
            bg=BG,
        )

        text_frame.pack(
            side="left",
            fill="both",
            expand=True,
        )

        title = tk.Label(
            text_frame,
            text=item.title,
            bg=BG,
            fg=MUTED,
            font=(FONT, 10),
            anchor="w",
        )

        title.pack(
            anchor="w",
            pady=(7, 0),
        )

        description = tk.Label(
            text_frame,
            text=item.description,
            bg=BG,
            fg="#666666",
            font=(FONT, 7),
            anchor="w",
        )

        description.pack(
            anchor="w",
        )

        self._buttons[item.page] = button
        self._labels[item.page] = (
            icon,
            title,
        )

        # Click handlers
        widgets = (
            button,
            indicator,
            icon,
            text_frame,
            title,
            description,
        )

        for widget in widgets:
            widget.bind(
                "<Button-1>",
                lambda _event, page=item.page:
                self.select(page),
                add="+",
            )

            widget.bind(
                "<Enter>",
                lambda _event, page=item.page:
                self._hover(page, True),
                add="+",
            )

            widget.bind(
                "<Leave>",
                lambda _event, page=item.page:
                self._hover(page, False),
                add="+",
            )

    # ========================================================================
    # BOTTOM
    # ========================================================================

    def _build_bottom(self) -> None:

        self.bottom = tk.Frame(
            self,
            bg=BG,
        )

        self.bottom.pack(
            fill="x",
            padx=10,
            pady=(4, 14),
        )

        # Status
        self.status_frame = tk.Frame(
            self.bottom,
            bg=SURFACE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.status_frame.pack(
            fill="x",
            pady=(0, 8),
        )

        self.status_dot = tk.Label(
            self.status_frame,
            text="●",
            bg=SURFACE,
            fg=SUCCESS,
            font=(FONT, 9),
        )

        self.status_dot.pack(
            side="left",
            padx=(10, 5),
            pady=9,
        )

        self.status_label = tk.Label(
            self.status_frame,
            text="System Online",
            bg=SURFACE,
            fg=TEXT,
            font=(FONT, 8),
        )

        self.status_label.pack(
            side="left",
            pady=9,
        )

        # Settings
        self.settings_button = tk.Frame(
            self.bottom,
            bg=BG,
            height=44,
            cursor="hand2",
        )

        self.settings_button.pack(
            fill="x",
        )

        self.settings_button.pack_propagate(False)

        self.settings_icon = tk.Label(
            self.settings_button,
            text="⚙",
            bg=BG,
            fg=MUTED,
            font=(FONT, 15),
            width=3,
        )

        self.settings_icon.pack(
            side="left",
            padx=(5, 4),
        )

        self.settings_label = tk.Label(
            self.settings_button,
            text="Settings",
            bg=BG,
            fg=MUTED,
            font=(FONT, 10),
        )

        self.settings_label.pack(
            side="left",
        )

        widgets = (
            self.settings_button,
            self.settings_icon,
            self.settings_label,
        )

        for widget in widgets:

            widget.bind(
                "<Button-1>",
                self._settings_clicked,
                add="+",
            )

            widget.bind(
                "<Enter>",
                lambda _event:
                self._settings_hover(True),
                add="+",
            )

            widget.bind(
                "<Leave>",
                lambda _event:
                self._settings_hover(False),
                add="+",
            )

    # ========================================================================
    # SELECT
    # ========================================================================

    def select(
        self,
        page: SidebarPage | str,
    ) -> None:
        """Select a navigation page."""

        if not isinstance(page, SidebarPage):

            try:
                page = SidebarPage(str(page))
            except ValueError:
                return

        self.active_page = page

        self._refresh_active_state()

        if self.on_navigate:
            self.on_navigate(page)

    # ========================================================================
    # ACTIVE STATE
    # ========================================================================

    def _refresh_active_state(self) -> None:

        for page, button in self._buttons.items():

            icon, title = self._labels[page]

            if page == self.active_page:

                button.configure(
                    bg=ACTIVE,
                )

                icon.configure(
                    bg=ACTIVE,
                    fg=TEXT,
                )

                title.configure(
                    bg=ACTIVE,
                    fg=TEXT,
                )

            else:

                button.configure(
                    bg=BG,
                )

                icon.configure(
                    bg=BG,
                    fg=MUTED,
                )

                title.configure(
                    bg=BG,
                    fg=MUTED,
                )

    # ========================================================================
    # HOVER
    # ========================================================================

    def _hover(
        self,
        page: SidebarPage,
        entering: bool,
    ) -> None:

        if page == self.active_page:
            return

        button = self._buttons.get(page)

        if button is None:
            return

        color = HOVER if entering else BG

        try:
            button.configure(bg=color)

            icon, title = self._labels[page]

            icon.configure(bg=color)
            title.configure(bg=color)

        except tk.TclError:
            pass

    # ========================================================================
    # SETTINGS HOVER
    # ========================================================================

    def _settings_hover(
        self,
        entering: bool,
    ) -> None:

        color = HOVER if entering else BG

        try:
            self.settings_button.configure(
                bg=color,
            )

            self.settings_icon.configure(
                bg=color,
            )

            self.settings_label.configure(
                bg=color,
            )

        except tk.TclError:
            pass

    # ========================================================================
    # SETTINGS CLICK
    # ========================================================================

    def _settings_clicked(
        self,
        _event=None,
    ) -> None:

        if self.on_settings:
            self.on_settings()

        else:
            self.select(
                SidebarPage.SETTINGS
            )


    # ========================================================================
    # COLLAPSE
    # ========================================================================

    def toggle(self) -> None:
        """Toggle collapsed/expanded mode."""

        if self.collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self) -> None:
        """Collapse sidebar."""

        if self.collapsed:
            return

        self.collapsed = True

        self.configure(
            width=self.collapsed_width,
        )

        self.toggle_button.configure(
            text="›",
        )

        self.brand_frame.pack_forget()

        for _icon, title in self._labels.values():

            title.pack_forget()

        self.settings_label.pack_forget()

        self.status_label.pack_forget()

    def expand(self) -> None:
        """Expand sidebar."""

        if not self.collapsed:
            return

        self.collapsed = False

        self.configure(
            width=self.sidebar_width,
        )

        self.toggle_button.configure(
            text="‹",
        )

        self.brand_frame.pack(
            side="left",
            fill="both",
            expand=True,
        )

        for page in self.items:

            labels = self._labels.get(
                page.page
            )

            if labels:

                _, title = labels

                title.pack(
                    anchor="w",
                    pady=(7, 0),
                )

        self.settings_label.pack(
            side="left",
        )

        self.status_label.pack(
            side="left",
            pady=9,
        )

        self._refresh_active_state()

    # ========================================================================
    # PUBLIC HELPERS
    # ========================================================================

    def set_status(
        self,
        text: str,
        *,
        online: bool = True,
    ) -> None:
        """Update system status."""

        try:

            self.status_label.configure(
                text=text,
            )

            self.status_dot.configure(
                fg=SUCCESS if online else "#777777",
            )

        except tk.TclError:
            pass

    def get_active_page(self) -> SidebarPage:
        """Return currently selected page."""

        return self.active_page

    def set_active_page(
        self,
        page: SidebarPage | str,
    ) -> None:
        """Programmatically select a page."""

        self.select(page)

    def add_item(
        self,
        item: SidebarItem,
    ) -> None:
        """Add a new navigation item."""

        if item.page in self._buttons:
            return

        self.items = (*self.items, item)

        self._create_navigation_item(item)

        self._refresh_active_state()

    def remove_item(
        self,
        page: SidebarPage | str,
    ) -> None:
        """Remove a navigation item."""

        if not isinstance(page, SidebarPage):

            try:
                page = SidebarPage(str(page))
            except ValueError:
                return

        button = self._buttons.pop(
            page,
            None,
        )

        self._labels.pop(
            page,
            None,
        )

        if button:
            button.destroy()

        self.items = tuple(
            item
            for item in self.items
            if item.page != page
        )

    # ========================================================================
    # CLEANUP
    # ========================================================================

    def destroy(self) -> None:

        self._buttons.clear()
        self._labels.clear()

        super().destroy()


# ============================================================================
# FACTORY
# ============================================================================

def create_sidebar(
    parent: tk.Misc,
    **kwargs,
) -> Sidebar:
    """Create an AssistantX Sidebar."""

    return Sidebar(
        parent,
        **kwargs,
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DEFAULT_ITEMS",
    "Sidebar",
    "SidebarItem",
    "SidebarPage",
    "create_sidebar",
]
