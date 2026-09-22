"""
AssistantX Dashboard - Settings Panel
=====================================

Professional settings UI for AssistantX.

Responsibilities:
    - Display application settings
    - Modify UI preferences
    - Modify voice preferences
    - Modify AI preferences
    - Modify privacy preferences
    - Save settings through config.settings
    - Reset settings
    - Notify parent dashboard about changes
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

# ============================================================================
# CONFIG SETTINGS
# ============================================================================

try:
    from config.settings import settings_manager
except ImportError:
    settings_manager = None


# ============================================================================
# THEME
# ============================================================================

BG = "#111111"
CARD = "#181818"
CARD_HOVER = "#202020"
INPUT_BG = "#202020"
BORDER = "#2B2B2B"

TEXT = "#F5F5F5"
MUTED = "#9A9A9A"

ACCENT = "#4F8CFF"
ACCENT_HOVER = "#6A9DFF"

DANGER = "#E05252"
SUCCESS = "#6FD08C"

FONT = "Segoe UI"


# ============================================================================
# OPTIONS
# ============================================================================

THEME_OPTIONS = (
    ("Dark", "dark"),
    ("Light", "light"),
    ("System", "system"),
)

LANGUAGE_OPTIONS = (
    ("English (US)", "en-US"),
    ("English (UK)", "en-GB"),
    ("Bangla", "bn-BD"),
    ("Hindi", "hi-IN"),
)

AI_PROVIDER_OPTIONS = (
    ("Local AI", "local"),
    ("Ollama", "ollama"),
    ("Gemini", "gemini"),
)


# ============================================================================
# SETTINGS PANEL
# ============================================================================

class SettingsPanel(tk.Frame):
    """
    Main AssistantX Settings Panel.

    Parameters
    ----------
    parent:
        Parent Tkinter widget.

    on_close:
        Callback called when settings panel is closed.

    on_settings_changed:
        Callback called after successful save.

    on_theme_changed:
        Callback called when theme setting changes.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_close: Callable[[], None] | None = None,
        on_settings_changed: Callable[[dict[str, Any]], None] | None = None,
        on_theme_changed: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            parent,
            bg=BG,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )

        self.on_close = on_close
        self.on_settings_changed = on_settings_changed
        self.on_theme_changed = on_theme_changed

        self._variables: dict[str, tk.Variable] = {}
        self._combo_maps: dict[
            str,
            dict[str, str]
        ] = {}

        self._build_styles()
        self._build_ui()
        self.load_settings()

    # ========================================================================
    # STYLES
    # ========================================================================

    def _build_styles(self) -> None:
        """Configure ttk widgets."""

        style = ttk.Style(self)

        with contextlib.suppress(tk.TclError):
            style.theme_use("clam")

        style.configure(
            "AssistantX.TCombobox",
            fieldbackground=INPUT_BG,
            background=INPUT_BG,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=7,
        )

        style.map(
            "AssistantX.TCombobox",
            fieldbackground=[
                ("readonly", INPUT_BG),
            ],
            foreground=[
                ("readonly", TEXT),
            ],
        )

        style.configure(
            "AssistantX.Horizontal.TScale",
            background=CARD,
            troughcolor=INPUT_BG,
            bordercolor=CARD,
            lightcolor=CARD,
            darkcolor=CARD,
        )

    # ========================================================================
    # MAIN UI
    # ========================================================================

    def _build_ui(self) -> None:
        """Build the complete settings page."""

        self._build_header()
        self._build_scroll_area()
        self._build_footer()

    # ========================================================================
    # HEADER
    # ========================================================================

    def _build_header(self) -> None:

        header = tk.Frame(
            self,
            bg=BG,
            height=80,
        )

        header.pack(
            fill="x",
            padx=28,
            pady=(18, 0),
        )

        header.pack_propagate(False)

        title_frame = tk.Frame(
            header,
            bg=BG,
        )

        title_frame.pack(
            side="left",
            fill="y",
        )

        tk.Label(
            title_frame,
            text="Settings",
            bg=BG,
            fg=TEXT,
            font=(FONT, 24, "bold"),
        ).pack(
            anchor="w",
        )

        tk.Label(
            title_frame,
            text="Customize your AssistantX experience",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).pack(
            anchor="w",
            pady=(3, 0),
        )

        close_button = tk.Button(
            header,
            text="×",
            command=self.close,
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=(FONT, 22),
            cursor="hand2",
        )

        close_button.pack(
            side="right",
            padx=4,
        )

    # ========================================================================
    # SCROLL AREA
    # ========================================================================

    def _build_scroll_area(self) -> None:

        container = tk.Frame(
            self,
            bg=BG,
        )

        container.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=(8, 0),
        )

        self.canvas = tk.Canvas(
            container,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        scrollbar.pack(
            side="right",
            fill="y",
        )

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )

        self.content = tk.Frame(
            self.canvas,
            bg=BG,
        )

        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )

        self.content.bind(
            "<Configure>",
            self._update_scroll_region,
        )

        self.canvas.bind(
            "<Configure>",
            self._resize_content,
        )

        self.canvas.bind(
            "<Enter>",
            self._bind_mousewheel,
        )

        self.canvas.bind(
            "<Leave>",
            self._unbind_mousewheel,
        )

        self._build_sections()

    def _update_scroll_region(self, _event=None) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )

    def _resize_content(self, event) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.itemconfigure(
                self.window_id,
                width=event.width,
            )

    def _bind_mousewheel(self, _event=None) -> None:

        self.canvas.bind_all(
            "<MouseWheel>",
            self._mousewheel,
        )

    def _unbind_mousewheel(self, _event=None) -> None:

        self.canvas.unbind_all(
            "<MouseWheel>"
        )

    def _mousewheel(self, event) -> None:

        with contextlib.suppress(tk.TclError):
            self.canvas.yview_scroll(
                int(-event.delta / 120),
                "units",
            )

    # ========================================================================
    # SECTIONS
    # ========================================================================

    def _build_sections(self) -> None:

        self._build_appearance()
        self._build_voice()
        self._build_ai()
        self._build_privacy()
        self._build_notifications()

    # ========================================================================
    # CARD
    # ========================================================================

    def _create_card(
        self,
        title: str,
        description: str,
    ) -> tk.Frame:

        card = tk.Frame(
            self.content,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            bd=0,
        )

        card.pack(
            fill="x",
            padx=8,
            pady=7,
        )

        tk.Label(
            card,
            text=title,
            bg=CARD,
            fg=TEXT,
            font=(FONT, 14, "bold"),
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 2),
        )

        tk.Label(
            card,
            text=description,
            bg=CARD,
            fg=MUTED,
            font=(FONT, 9),
        ).pack(
            anchor="w",
            padx=18,
            pady=(0, 10),
        )

        return card

    # ========================================================================
    # APPEARANCE
    # ========================================================================

    def _build_appearance(self) -> None:

        card = self._create_card(
            "Appearance",
            "Customize the look and feel of AssistantX.",
        )

        self._add_combo(
            card,
            "Theme",
            "ui.theme",
            THEME_OPTIONS,
        )

        self._add_boolean(
            card,
            "Animations",
            "ui.animations",
        )

        self._add_boolean(
            card,
            "Reduced motion",
            "ui.reduced_motion",
        )

        self._add_boolean(
            card,
            "Particle background",
            "ui.show_particles",
        )

        self._add_integer(
            card,
            "Font size",
            "ui.font_size",
            8,
            32,
        )

    # ========================================================================
    # VOICE
    # ========================================================================

    def _build_voice(self) -> None:

        card = self._create_card(
            "Voice",
            "Configure speech recognition and voice output.",
        )

        self._add_boolean(
            card,
            "Voice assistant",
            "voice.enabled",
        )

        self._add_combo(
            card,
            "Language",
            "voice.language",
            LANGUAGE_OPTIONS,
        )

        self._add_boolean(
            card,
            "Wake word detection",
            "voice.wake_word_enabled",
        )

        self._add_entry(
            card,
            "Wake word",
            "voice.wake_word",
        )

        self._add_integer(
            card,
            "Speech rate",
            "voice.speech_rate",
            80,
            300,
        )

        self._add_float(
            card,
            "Volume",
            "voice.volume",
            0.0,
            1.0,
        )

    # ========================================================================
    # AI
    # ========================================================================

    def _build_ai(self) -> None:

        card = self._create_card(
            "AI",
            "Configure the AI engine used by AssistantX.",
        )

        self._add_combo(
            card,
            "Provider",
            "ai.provider",
            AI_PROVIDER_OPTIONS,
        )

        self._add_entry(
            card,
            "Model",
            "ai.model",
        )

        self._add_float(
            card,
            "Temperature",
            "ai.temperature",
            0.0,
            2.0,
        )

        self._add_boolean(
            card,
            "Streaming responses",
            "ai.streaming",
        )

    # ========================================================================
    # PRIVACY
    # ========================================================================

    def _build_privacy(self) -> None:

        card = self._create_card(
            "Privacy",
            "Control local data storage and privacy options.",
        )

        self._add_boolean(
            card,
            "Save chat history",
            "privacy.save_history",
        )

        self._add_boolean(
            card,
            "Save memory",
            "privacy.save_memory",
        )

        self._add_boolean(
            card,
            "Telemetry",
            "privacy.telemetry",
        )

    # ========================================================================
    # NOTIFICATIONS
    # ========================================================================

    def _build_notifications(self) -> None:

        card = self._create_card(
            "Notifications",
            "Configure AssistantX notification behavior.",
        )

        self._add_boolean(
            card,
            "Notifications",
            "notifications.enabled",
        )

        self._add_boolean(
            card,
            "Notification sound",
            "notifications.sound",
        )

    # ========================================================================
    # BOOLEAN
    # ========================================================================

    def _add_boolean(
        self,
        parent: tk.Frame,
        title: str,
        path: str,
    ) -> None:

        variable = tk.BooleanVar(
            master=self,
            value=False,
        )

        self._variables[path] = variable

        row = tk.Frame(
            parent,
            bg=CARD,
        )

        row.pack(
            fill="x",
            padx=18,
            pady=5,
        )

        tk.Label(
            row,
            text=title,
            bg=CARD,
            fg=TEXT,
            font=(FONT, 10),
        ).pack(
            side="left",
        )

        tk.Checkbutton(
            row,
            variable=variable,
            bg=CARD,
            activebackground=CARD,
            selectcolor=INPUT_BG,
            activeforeground=TEXT,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        ).pack(
            side="right",
        )

    # ========================================================================
    # COMBOBOX
    # ========================================================================

    def _add_combo(
        self,
        parent: tk.Frame,
        title: str,
        path: str,
        options,
    ) -> None:

        row = tk.Frame(
            parent,
            bg=CARD,
        )

        row.pack(
            fill="x",
            padx=18,
            pady=6,
        )

        tk.Label(
            row,
            text=title,
            bg=CARD,
            fg=TEXT,
            font=(FONT, 10),
        ).pack(
            side="left",
        )

        variable = tk.StringVar(
            master=self,
        )

        self._variables[path] = variable

        mapping = dict(options)

        self._combo_maps[path] = mapping

        combo = ttk.Combobox(
            row,
            textvariable=variable,
            values=list(mapping.keys()),
            state="readonly",
            width=20,
            style="AssistantX.TCombobox",
        )

        combo.pack(
            side="right",
        )

    # ========================================================================
    # ENTRY
    # ========================================================================

    def _add_entry(
        self,
        parent: tk.Frame,
        title: str,
        path: str,
    ) -> None:

        row = tk.Frame(
            parent,
            bg=CARD,
        )

        row.pack(
            fill="x",
            padx=18,
            pady=6,
        )

        tk.Label(
            row,
            text=title,
            bg=CARD,
            fg=TEXT,
            font=(FONT, 10),
        ).pack(
            side="left",
        )

        variable = tk.StringVar(
            master=self,
        )

        self._variables[path] = variable

        entry = tk.Entry(
            row,
            textvariable=variable,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            selectforeground="white",
            relief="flat",
            bd=0,
            width=25,
            font=(FONT, 9),
        )

        entry.pack(
            side="right",
            ipady=6,
        )

    # ========================================================================
    # INTEGER
    # ========================================================================

    def _add_integer(
        self,
        parent: tk.Frame,
        title: str,
        path: str,
        minimum: int,
        maximum: int,
    ) -> None:

        row = tk.Frame(
            parent,
            bg=CARD,
        )

        row.pack(
            fill="x",
            padx=18,
            pady=6,
        )

        tk.Label(
            row,
            text=title,
            bg=CARD,
            fg=TEXT,
        ).pack(side="left")

        variable = tk.IntVar(
            master=self,
            value=minimum,
        )

        self._variables[path] = variable

        spinbox = tk.Spinbox(
            row,
            from_=minimum,
            to=maximum,
            textvariable=variable,
            bg=INPUT_BG,
            fg=TEXT,
            buttonbackground=INPUT_BG,
            insertbackground=TEXT,
            relief="flat",
            width=8,
        )

        spinbox.pack(
            side="right",
        )

    # ========================================================================
    # FLOAT
    # ========================================================================

    def _add_float(
        self,
        parent: tk.Frame,
        title: str,
        path: str,
        minimum: float,
        maximum: float,
    ) -> None:

        row = tk.Frame(
            parent,
            bg=CARD,
        )

        row.pack(
            fill="x",
            padx=18,
            pady=6,
        )

        tk.Label(
            row,
            text=title,
            bg=CARD,
            fg=TEXT,
        ).pack(side="left")

        variable = tk.DoubleVar(
            master=self,
            value=minimum,
        )

        self._variables[path] = variable

        scale = ttk.Scale(
            row,
            from_=minimum,
            to=maximum,
            variable=variable,
            orient="horizontal",
            length=170,
            style="AssistantX.Horizontal.TScale",
        )

        scale.pack(
            side="right",
        )

    # ========================================================================
    # FOOTER
    # ========================================================================

    def _build_footer(self) -> None:

        footer = tk.Frame(
            self,
            bg=BG,
            height=65,
        )

        footer.pack(
            fill="x",
            padx=28,
            pady=(8, 18),
        )

        footer.pack_propagate(False)

        tk.Button(
            footer,
            text="Reset",
            command=self.reset_settings,
            bg=INPUT_BG,
            fg=TEXT,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2",
            font=(FONT, 9),
        ).pack(
            side="left",
            anchor="center",
        )

        tk.Button(
            footer,
            text="Save Changes",
            command=self.save_settings,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_HOVER,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=22,
            pady=9,
            cursor="hand2",
            font=(FONT, 9, "bold"),
        ).pack(
            side="right",
            anchor="center",
        )

    # ========================================================================
    # LOAD
    # ========================================================================

    def load_settings(self) -> None:
        """Load persistent settings into the UI."""

        for path, variable in self._variables.items():

            if settings_manager is None:
                continue

            value = settings_manager.get(
                path,
                None,
            )

            if value is None:
                continue

            try:

                if path in self._combo_maps:

                    mapping = self._combo_maps[path]

                    label = next(
                        (
                            label
                            for label, internal in mapping.items()
                            if internal == value
                        ),
                        None,
                    )

                    if label is not None:
                        variable.set(label)

                else:
                    variable.set(value)

            except (tk.TclError, ValueError):
                continue

    # ========================================================================
    # COLLECT
    # ========================================================================

    def collect_settings(self) -> dict[str, Any]:
        """Collect current UI values."""

        result: dict[str, Any] = {}

        for path, variable in self._variables.items():

            value = variable.get()

            if path in self._combo_maps:

                value = self._combo_maps[path].get(
                    value,
                    value,
                )

            result[path] = value

        return result

    # ========================================================================
    # SAVE
    # ========================================================================

    def save_settings(self) -> bool:
        """Save current settings."""

        data = self.collect_settings()

        try:

            if settings_manager is not None:

                settings_manager.update(
                    data,
                    save=True,
                )

            # Theme callback
            theme = data.get("ui.theme")

            if (
                theme
                and self.on_theme_changed
            ):
                self.on_theme_changed(theme)

            # General callback
            if self.on_settings_changed:
                self.on_settings_changed(data)

            messagebox.showinfo(
                "Settings",
                "Settings saved successfully.",
                parent=self.winfo_toplevel(),
            )

            return True

        except (OSError, TypeError, ValueError, tk.TclError) as exc:

            messagebox.showerror(
                "Settings Error",
                f"Could not save settings.\n\n{exc}",
                parent=self.winfo_toplevel(),
            )

            return False

    # ========================================================================
    # RESET
    # ========================================================================

    def reset_settings(self) -> None:
        """Reset all settings to defaults."""

        confirmed = messagebox.askyesno(
            "Reset Settings",
            "Are you sure you want to reset all settings?",
            parent=self.winfo_toplevel(),
        )

        if not confirmed:
            return

        try:

            if settings_manager is not None:
                settings_manager.reset(
                    save=True,
                )

            self.load_settings()

            messagebox.showinfo(
                "Settings",
                "Settings have been reset successfully.",
                parent=self.winfo_toplevel(),
            )

        except (OSError, TypeError, ValueError, tk.TclError) as exc:

            messagebox.showerror(
                "Settings Error",
                f"Could not reset settings.\n\n{exc}",
                parent=self.winfo_toplevel(),
            )

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    def get_settings(self) -> dict[str, Any]:
        """Return current unsaved settings."""
        return self.collect_settings()

    def reload(self) -> None:
        """Reload settings from disk."""
        self.load_settings()

    def close(self) -> None:
        """Close the settings panel."""

        self._unbind_mousewheel()

        if self.on_close:
            self.on_close()
            return

        self.destroy()

    # ========================================================================
    # CLEANUP
    # ========================================================================

    def destroy(self) -> None:

        with contextlib.suppress(tk.TclError):
            self._unbind_mousewheel()

        super().destroy()


# ============================================================================
# FACTORY
# ============================================================================

def create_settings_panel(
    parent: tk.Misc,
    **kwargs: Any,
) -> SettingsPanel:
    """Create a SettingsPanel instance."""

    return SettingsPanel(
        parent,
        **kwargs,
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "SettingsPanel",
    "create_settings_panel",
]
