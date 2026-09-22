"""
AssistantX Dashboard - Dialog System
====================================

Professional, reusable Tkinter dialog system for AssistantX.

Supported dialogs
-----------------
    • Information
    • Warning
    • Error
    • Confirmation
    • Text input
    • Choice selection
    • Loading dialog
    • Custom dialog
    • Dialog manager
    • Convenience helper functions

Design goals
------------
    • Dependency-free
    • Thread-safe request scheduling
    • Consistent AssistantX theme
    • Modal behavior
    • Keyboard-friendly
    • Safe window cleanup
    • Reusable from all dashboard modules

Example
-------

    from dashboard.dialogs import DialogManager

    dialogs = DialogManager(root)

    dialogs.info(
        "Welcome",
        "AssistantX is ready."
    )

    if dialogs.confirm(
        "Exit",
        "Are you sure you want to exit?"
    ):
        root.destroy()
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_BG = "#0f1117"
DEFAULT_SURFACE = "#171a21"
DEFAULT_SURFACE_ALT = "#20242d"

DEFAULT_TEXT = "#f5f7fa"
DEFAULT_MUTED = "#9ca3af"

DEFAULT_BORDER = "#2a2f3a"

DEFAULT_ACCENT = "#2563eb"
DEFAULT_SUCCESS = "#16a34a"
DEFAULT_WARNING = "#d97706"
DEFAULT_ERROR = "#dc2626"

DEFAULT_FONT = "Segoe UI"

DEFAULT_WIDTH = 430
DEFAULT_MIN_HEIGHT = 170

DEFAULT_PADDING = 20


# ============================================================================
# Exceptions
# ============================================================================

class DialogError(Exception):
    """Base exception for dialog errors."""


class DialogConfigurationError(DialogError):
    """Raised when dialog configuration is invalid."""


class DialogStateError(DialogError):
    """Raised when a dialog is used in an invalid state."""


# ============================================================================
# Enums
# ============================================================================

class DialogType(str, Enum):
    """Supported dialog types."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CONFIRM = "confirm"
    INPUT = "input"
    CHOICE = "choice"
    CUSTOM = "custom"


class DialogResult(str, Enum):
    """Common dialog results."""

    OK = "ok"
    CANCEL = "cancel"
    YES = "yes"
    NO = "no"


# ============================================================================
# Dialog Theme
# ============================================================================

@dataclass(frozen=True, slots=True)
class DialogTheme:
    """Visual theme for AssistantX dialogs."""

    background: str = DEFAULT_BG
    surface: str = DEFAULT_SURFACE
    surface_alt: str = DEFAULT_SURFACE_ALT

    text: str = DEFAULT_TEXT
    muted: str = DEFAULT_MUTED

    border: str = DEFAULT_BORDER

    accent: str = DEFAULT_ACCENT
    success: str = DEFAULT_SUCCESS
    warning: str = DEFAULT_WARNING
    error: str = DEFAULT_ERROR

    font_family: str = DEFAULT_FONT

    title_size: int = 14
    body_size: int = 10
    small_size: int = 9
    button_size: int = 10

    width: int = DEFAULT_WIDTH
    min_height: int = DEFAULT_MIN_HEIGHT

    padding: int = DEFAULT_PADDING

    def __post_init__(self) -> None:

        if self.width <= 0:
            raise DialogConfigurationError(
                "Dialog width must be greater than zero."
            )

        if self.min_height <= 0:
            raise DialogConfigurationError(
                "Dialog min_height must be greater than zero."
            )

        if self.padding < 0:
            raise DialogConfigurationError(
                "Dialog padding cannot be negative."
            )


# ============================================================================
# Dialog Request
# ============================================================================

@dataclass(slots=True)
class DialogRequest:
    """Description of a dialog request."""

    dialog_type: DialogType

    title: str
    message: str

    default_value: str = ""

    choices: tuple[str, ...] = ()

    confirm_text: str = "OK"
    cancel_text: str = "Cancel"

    width: int | None = None
    height: int | None = None

    parent: tk.Misc | None = None

    password: bool = False

    validate: Callable[[str], bool] | None = None


# ============================================================================
# Base Dialog
# ============================================================================

class BaseDialog(tk.Toplevel):
    """
    Base modal dialog used by all AssistantX dialogs.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        theme: DialogTheme,
        width: int | None = None,
        height: int | None = None,
        modal: bool = True,
    ) -> None:

        super().__init__(parent)

        self.parent = parent
        self.theme = theme

        self._lock = RLock()

        self._closed = False
        self._result: Any = None

        self._modal = modal

        self.title(title)

        self.configure(
            bg=theme.background
        )

        self.resizable(
            False,
            False,
        )

        self.transient(parent)

        self.protocol(
            "WM_DELETE_WINDOW",
            self.close,
        )

        self._center(
            width or theme.width,
            height or theme.min_height,
        )

        self._build_shell()

        if modal:

            self.grab_set()

            self.focus_force()

    # ========================================================================
    # Shell
    # ========================================================================

    def _build_shell(self) -> None:

        self.outer = tk.Frame(
            self,
            bg=self.theme.background,
        )

        self.outer.pack(
            fill="both",
            expand=True,
            padx=1,
            pady=1,
        )

        self.content = tk.Frame(
            self.outer,
            bg=self.theme.surface,
        )

        self.content.pack(
            fill="both",
            expand=True,
            padx=1,
            pady=1,
        )

        self.body = tk.Frame(
            self.content,
            bg=self.theme.surface,
        )

        self.body.pack(
            fill="both",
            expand=True,
            padx=self.theme.padding,
            pady=self.theme.padding,
        )

    # ========================================================================
    # Center
    # ========================================================================

    def _center(
        self,
        width: int,
        height: int,
    ) -> None:

        try:

            self.update_idletasks()

            parent_x = self.parent.winfo_rootx()
            parent_y = self.parent.winfo_rooty()

            parent_width = self.parent.winfo_width()
            parent_height = self.parent.winfo_height()

            if parent_width <= 1:
                parent_width = self.winfo_screenwidth()

            if parent_height <= 1:
                parent_height = self.winfo_screenheight()

            x = (
                parent_x
                + max(
                    0,
                    (parent_width - width) // 2,
                )
            )

            y = (
                parent_y
                + max(
                    0,
                    (parent_height - height) // 2,
                )
            )

            self.geometry(
                f"{width}x{height}+{x}+{y}"
            )

        except tk.TclError:

            self.geometry(
                f"{width}x{height}"
            )

    # ========================================================================
    # Keyboard
    # ========================================================================

    def bind_default_keys(
        self,
        *,
        on_enter: Callable[[], None] | None = None,
        on_escape: Callable[[], None] | None = None,
    ) -> None:

        if on_enter:
            self.bind(
                "<Return>",
                lambda _event: on_enter(),
            )

        if on_escape:
            self.bind(
                "<Escape>",
                lambda _event: on_escape(),
            )

    # ========================================================================
    # Result
    # ========================================================================

    @property
    def result(self) -> Any:
        with self._lock:
            return self._result

    def set_result(
        self,
        result: Any,
    ) -> None:

        with self._lock:
            self._result = result

    # ========================================================================
    # Close
    # ========================================================================

    def close(self) -> None:
        """Close the dialog safely."""

        with self._lock:

            if self._closed:
                return

            self._closed = True

        try:

            if self._modal:

                with contextlib.suppress(tk.TclError):
                    self.grab_release()

            self.destroy()

        except tk.TclError:
            pass

    # ========================================================================
    # Wait
    # ========================================================================

    def show(self) -> Any:
        """
        Display the dialog and wait for the modal result.
        """

        with contextlib.suppress(tk.TclError):
            self.wait_window()

        return self.result


# ============================================================================
# Message Dialog
# ============================================================================

class MessageDialog(BaseDialog):
    """Information, warning and error dialog."""

    ICONS: ClassVar[dict[DialogType, str]] = {
        DialogType.INFO: "●",
        DialogType.WARNING: "▲",
        DialogType.ERROR: "✕",
    }

    def __init__(
        self,
        parent: tk.Misc,
        *,
        dialog_type: DialogType,
        title: str,
        message: str,
        theme: DialogTheme,
        button_text: str = "OK",
    ) -> None:

        super().__init__(
            parent,
            title=title,
            theme=theme,
            width=theme.width,
            height=210,
        )

        self.dialog_type = dialog_type

        self._build_message(
            message,
            button_text,
        )

    def _build_message(
        self,
        message: str,
        button_text: str,
    ) -> None:

        icon = self.ICONS.get(
            self.dialog_type,
            "●",
        )

        if self.dialog_type == DialogType.ERROR:
            icon_font = self.theme.error
        elif self.dialog_type == DialogType.WARNING:
            icon_font = self.theme.warning
        else:
            icon_font = self.theme.accent

        icon_label = tk.Label(
            self.body,
            text=icon,
            bg=self.theme.surface,
            fg=icon_font,
            font=(
                self.theme.font_family,
                22,
                "bold",
            ),
        )

        icon_label.pack(
            pady=(2, 8),
        )

        message_label = tk.Label(
            self.body,
            text=str(message),
            bg=self.theme.surface,
            fg=self.theme.text,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
            justify="center",
            wraplength=self.theme.width - 70,
        )

        message_label.pack(
            fill="x",
            pady=(0, 15),
        )

        button = self._create_button(
            text=button_text,
            command=lambda: self._finish(
                DialogResult.OK
            ),
            primary=True,
        )

        button.pack()

        self.bind_default_keys(
            on_enter=lambda: self._finish(
                DialogResult.OK
            ),
            on_escape=self.close,
        )

        button.focus_set()

    def _finish(
        self,
        result: DialogResult,
    ) -> None:

        self.set_result(result)
        self.close()

    def _create_button(
        self,
        *,
        text: str,
        command: Callable[[], None],
        primary: bool = False,
    ) -> tk.Button:

        background = (
            self.theme.accent
            if primary
            else self.theme.surface_alt
        )

        return tk.Button(
            self.body,
            text=text,
            command=command,
            bg=background,
            fg=self.theme.text,
            activebackground=background,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=(
                self.theme.font_family,
                self.theme.button_size,
                "bold",
            ),
            padx=20,
            pady=8,
        )


# ============================================================================
# Confirmation Dialog
# ============================================================================

class ConfirmDialog(BaseDialog):
    """Yes/No confirmation dialog."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        message: str,
        theme: DialogTheme,
        yes_text: str = "Yes",
        no_text: str = "No",
    ) -> None:

        super().__init__(
            parent,
            title=title,
            theme=theme,
            width=theme.width,
            height=210,
        )

        self._build(
            message,
            yes_text,
            no_text,
        )

    def _build(
        self,
        message: str,
        yes_text: str,
        no_text: str,
    ) -> None:

        title_label = tk.Label(
            self.body,
            text="Confirmation",
            bg=self.theme.surface,
            fg=self.theme.text,
            font=(
                self.theme.font_family,
                self.theme.title_size,
                "bold",
            ),
        )

        title_label.pack(
            pady=(0, 10),
        )

        message_label = tk.Label(
            self.body,
            text=str(message),
            bg=self.theme.surface,
            fg=self.theme.muted,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
            justify="center",
            wraplength=self.theme.width - 60,
        )

        message_label.pack(
            fill="x",
            pady=(0, 20),
        )

        button_frame = tk.Frame(
            self.body,
            bg=self.theme.surface,
        )

        button_frame.pack()

        no_button = tk.Button(
            button_frame,
            text=no_text,
            command=lambda: self._finish(
                DialogResult.NO
            ),
            bg=self.theme.surface_alt,
            fg=self.theme.text,
            activebackground=self.theme.surface_alt,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=(
                self.theme.font_family,
                self.theme.button_size,
                "bold",
            ),
            padx=18,
            pady=8,
        )

        no_button.pack(
            side="left",
            padx=5,
        )

        yes_button = tk.Button(
            button_frame,
            text=yes_text,
            command=lambda: self._finish(
                DialogResult.YES
            ),
            bg=self.theme.accent,
            fg=self.theme.text,
            activebackground=self.theme.accent,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=(
                self.theme.font_family,
                self.theme.button_size,
                "bold",
            ),
            padx=18,
            pady=8,
        )

        yes_button.pack(
            side="left",
            padx=5,
        )

        self.bind_default_keys(
            on_enter=lambda: self._finish(
                DialogResult.YES
            ),
            on_escape=lambda: self._finish(
                DialogResult.NO
            ),
        )

        yes_button.focus_set()

    def _finish(
        self,
        result: DialogResult,
    ) -> None:

        self.set_result(result)
        self.close()


# ============================================================================
# Input Dialog
# ============================================================================

class InputDialog(BaseDialog):
    """Single-line text input dialog."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        message: str,
        theme: DialogTheme,
        default_value: str = "",
        confirm_text: str = "OK",
        cancel_text: str = "Cancel",
        password: bool = False,
        validate: Callable[[str], bool] | None = None,
    ) -> None:

        super().__init__(
            parent,
            title=title,
            theme=theme,
            width=theme.width,
            height=235,
        )

        self._validate = validate

        self._build(
            message,
            default_value,
            confirm_text,
            cancel_text,
            password,
        )

    def _build(
        self,
        message: str,
        default_value: str,
        confirm_text: str,
        cancel_text: str,
        password: bool,
    ) -> None:

        message_label = tk.Label(
            self.body,
            text=str(message),
            bg=self.theme.surface,
            fg=self.theme.text,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
            justify="left",
            anchor="w",
            wraplength=self.theme.width - 50,
        )

        message_label.pack(
            fill="x",
            pady=(0, 10),
        )

        self.entry = tk.Entry(
            self.body,
            bg=self.theme.surface_alt,
            fg=self.theme.text,
            insertbackground=self.theme.text,
            relief="flat",
            borderwidth=0,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
        )

        if password:
            self.entry.configure(
                show="•"
            )

        self.entry.pack(
            fill="x",
            ipady=8,
            pady=(0, 15),
        )

        self.entry.insert(
            0,
            str(default_value),
        )

        button_frame = tk.Frame(
            self.body,
            bg=self.theme.surface,
        )

        button_frame.pack()

        cancel_button = tk.Button(
            button_frame,
            text=cancel_text,
            command=lambda: self._finish(
                None
            ),
            bg=self.theme.surface_alt,
            fg=self.theme.text,
            activebackground=self.theme.surface_alt,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=15,
            pady=7,
        )

        cancel_button.pack(
            side="left",
            padx=5,
        )

        ok_button = tk.Button(
            button_frame,
            text=confirm_text,
            command=self._submit,
            bg=self.theme.accent,
            fg=self.theme.text,
            activebackground=self.theme.accent,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=15,
            pady=7,
        )

        ok_button.pack(
            side="left",
            padx=5,
        )

        self.bind_default_keys(
            on_enter=self._submit,
            on_escape=lambda: self._finish(None),
        )

        self.entry.focus_set()

    def _submit(self) -> None:

        value = self.entry.get()

        if self._validate:

            try:

                valid = bool(
                    self._validate(value)
                )

            except Exception:

                logger.exception(
                    "Input validation failed."
                )

                valid = False

            if not valid:

                self._show_validation_error()

                return

        self._finish(value)

    def _show_validation_error(self) -> None:

        error = tk.Label(
            self.body,
            text="Please enter a valid value.",
            bg=self.theme.surface,
            fg=self.theme.error,
            font=(
                self.theme.font_family,
                self.theme.small_size,
            ),
        )

        error.pack(
            before=self.entry,
            pady=(0, 5),
        )

    def _finish(
        self,
        value: str | None,
    ) -> None:

        self.set_result(value)
        self.close()


# ============================================================================
# Choice Dialog
# ============================================================================

class ChoiceDialog(BaseDialog):
    """Multiple-choice selection dialog."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        message: str,
        choices: tuple[str, ...],
        theme: DialogTheme,
        default_value: str | None = None,
    ) -> None:

        if not choices:
            raise DialogConfigurationError(
                "Choice dialog requires at least one choice."
            )

        super().__init__(
            parent,
            title=title,
            theme=theme,
            width=theme.width,
            height=min(
                500,
                190 + len(choices) * 42,
            ),
        )

        self._choices = choices

        self._build(
            message,
            default_value,
        )

    def _build(
        self,
        message: str,
        default_value: str | None,
    ) -> None:

        label = tk.Label(
            self.body,
            text=str(message),
            bg=self.theme.surface,
            fg=self.theme.text,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
            wraplength=self.theme.width - 50,
            justify="left",
        )

        label.pack(
            fill="x",
            pady=(0, 12),
        )

        self.variable = tk.StringVar(
            value=(
                default_value
                if default_value in self._choices
                else self._choices[0]
            )
        )

        choices_frame = tk.Frame(
            self.body,
            bg=self.theme.surface,
        )

        choices_frame.pack(
            fill="both",
            expand=True,
        )

        for choice in self._choices:

            radio = tk.Radiobutton(
                choices_frame,
                text=choice,
                variable=self.variable,
                value=choice,
                bg=self.theme.surface,
                fg=self.theme.text,
                selectcolor=self.theme.surface_alt,
                activebackground=self.theme.surface,
                activeforeground=self.theme.text,
                font=(
                    self.theme.font_family,
                    self.theme.body_size,
                ),
                anchor="w",
            )

            radio.pack(
                fill="x",
                pady=3,
            )

        button = tk.Button(
            self.body,
            text="Select",
            command=self._finish,
            bg=self.theme.accent,
            fg=self.theme.text,
            activebackground=self.theme.accent,
            activeforeground=self.theme.text,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            padx=18,
            pady=8,
        )

        button.pack(
            pady=(12, 0),
        )

        self.bind_default_keys(
            on_enter=self._finish,
            on_escape=self.close,
        )

        button.focus_set()

    def _finish(self) -> None:

        self.set_result(
            self.variable.get()
        )

        self.close()


# ============================================================================
# Loading Dialog
# ============================================================================

class LoadingDialog(BaseDialog):
    """
    Lightweight non-blocking loading dialog.

    Example
    -------
        loading = LoadingDialog(
            root,
            title="Please wait",
            message="Connecting to AssistantX..."
        )

        loading.show_async()

        # Later:
        loading.close()
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str = "Please wait",
        message: str = "Loading...",
        theme: DialogTheme | None = None,
    ) -> None:

        super().__init__(
            parent,
            title=title,
            theme=theme or DialogTheme(),
            width=400,
            height=180,
            modal=False,
        )

        self._message = message
        self._animation_id: str | None = None
        self._dots = 0

        self._build()

    def _build(self) -> None:

        self.message_label = tk.Label(
            self.body,
            text=self._message,
            bg=self.theme.surface,
            fg=self.theme.text,
            font=(
                self.theme.font_family,
                self.theme.body_size,
            ),
            wraplength=330,
        )

        self.message_label.pack(
            pady=(15, 15),
        )

        self.progress = tk.Label(
            self.body,
            text="",
            bg=self.theme.surface,
            fg=self.theme.accent,
            font=(
                self.theme.font_family,
                16,
                "bold",
            ),
        )

        self.progress.pack()

    def show_async(self) -> None:
        """Show loading dialog without blocking."""

        try:
            self.deiconify()
            self.lift()
            self._animate()
        except tk.TclError:
            pass

    def _animate(self) -> None:

        if self._closed:
            return

        self._dots = (
            self._dots + 1
        ) % 4

        self.progress.configure(
            text="." * self._dots
        )

        try:

            self._animation_id = self.after(
                350,
                self._animate,
            )

        except tk.TclError:
            return

    def set_message(
        self,
        message: str,
    ) -> None:

        self._message = str(message)

        with contextlib.suppress(tk.TclError):
            self.message_label.configure(
                text=self._message
            )

    def close(self) -> None:

        if self._animation_id:

            with contextlib.suppress(tk.TclError):
                self.after_cancel(
                    self._animation_id
                )

            self._animation_id = None

        super().close()


# ============================================================================
# Custom Dialog
# ============================================================================

class CustomDialog(BaseDialog):
    """
    Generic custom dialog.

    `builder` receives the dialog body frame and can add
    arbitrary widgets.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        builder: Callable[[tk.Frame], None],
        theme: DialogTheme | None = None,
        width: int | None = None,
        height: int | None = None,
        modal: bool = True,
    ) -> None:

        super().__init__(
            parent,
            title=title,
            theme=theme or DialogTheme(),
            width=width,
            height=height,
            modal=modal,
        )

        if not callable(builder):
            raise DialogConfigurationError(
                "builder must be callable."
            )

        try:
            builder(self.body)
        except Exception:
            self.close()

            logger.exception(
                "Custom dialog builder failed."
            )

            raise


# ============================================================================
# Dialog Manager
# ============================================================================

class DialogManager:
    """
    Central dialog manager for AssistantX.

    Recommended approach:

        dialogs = DialogManager(root)

        dialogs.info(...)
        dialogs.warning(...)
        dialogs.error(...)

        if dialogs.confirm(...):
            ...

        value = dialogs.input(...)
    """

    def __init__(
        self,
        root: tk.Misc,
        *,
        theme: DialogTheme | None = None,
    ) -> None:

        if root is None:
            raise DialogConfigurationError(
                "root is required."
            )

        self.root = root

        self.theme = (
            theme
            or DialogTheme()
        )

        self._lock = RLock()

        self._active: set[BaseDialog] = set()

    # ========================================================================
    # Registration
    # ========================================================================

    def _register(
        self,
        dialog: BaseDialog,
    ) -> BaseDialog:

        with self._lock:
            self._active.add(dialog)

        return dialog

    def _unregister(
        self,
        dialog: BaseDialog,
    ) -> None:

        with self._lock:
            self._active.discard(dialog)

    # ========================================================================
    # Information
    # ========================================================================

    def info(
        self,
        title: str,
        message: str,
    ) -> DialogResult:

        dialog = MessageDialog(
            self.root,
            dialog_type=DialogType.INFO,
            title=title,
            message=message,
            theme=self.theme,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Warning
    # ========================================================================

    def warning(
        self,
        title: str,
        message: str,
    ) -> DialogResult:

        dialog = MessageDialog(
            self.root,
            dialog_type=DialogType.WARNING,
            title=title,
            message=message,
            theme=self.theme,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Error
    # ========================================================================

    def error(
        self,
        title: str,
        message: str,
    ) -> DialogResult:

        dialog = MessageDialog(
            self.root,
            dialog_type=DialogType.ERROR,
            title=title,
            message=message,
            theme=self.theme,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Confirmation
    # ========================================================================

    def confirm(
        self,
        title: str,
        message: str,
    ) -> bool:

        dialog = ConfirmDialog(
            self.root,
            title=title,
            message=message,
            theme=self.theme,
        )

        self._register(dialog)

        try:

            result = dialog.show()

            return result == DialogResult.YES

        finally:

            self._unregister(dialog)

    # ========================================================================
    # Input
    # ========================================================================

    def input(
        self,
        title: str,
        message: str,
        *,
        default_value: str = "",
        password: bool = False,
        validate: Callable[[str], bool] | None = None,
    ) -> str | None:

        dialog = InputDialog(
            self.root,
            title=title,
            message=message,
            theme=self.theme,
            default_value=default_value,
            password=password,
            validate=validate,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Choice
    # ========================================================================

    def choice(
        self,
        title: str,
        message: str,
        choices: list[str] | tuple[str, ...],
        *,
        default_value: str | None = None,
    ) -> str | None:

        normalized = tuple(
            str(item)
            for item in choices
            if str(item).strip()
        )

        if not normalized:
            raise DialogConfigurationError(
                "choices cannot be empty."
            )

        dialog = ChoiceDialog(
            self.root,
            title=title,
            message=message,
            choices=normalized,
            theme=self.theme,
            default_value=default_value,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Loading
    # ========================================================================

    def loading(
        self,
        title: str = "Please wait",
        message: str = "Loading...",
    ) -> LoadingDialog:

        dialog = LoadingDialog(
            self.root,
            title=title,
            message=message,
            theme=self.theme,
        )

        self._register(dialog)

        dialog.show_async()

        return dialog

    # ========================================================================
    # Custom
    # ========================================================================

    def custom(
        self,
        title: str,
        builder: Callable[[tk.Frame], None],
        *,
        width: int | None = None,
        height: int | None = None,
        modal: bool = True,
    ) -> Any:

        dialog = CustomDialog(
            self.root,
            title=title,
            builder=builder,
            theme=self.theme,
            width=width,
            height=height,
            modal=modal,
        )

        self._register(dialog)

        try:
            return dialog.show()
        finally:
            self._unregister(dialog)

    # ========================================================================
    # Active Dialogs
    # ========================================================================

    def active_count(self) -> int:

        with self._lock:
            return len(self._active)

    def close_all(self) -> None:
        """Close every active dialog."""

        with self._lock:
            dialogs = list(self._active)

        for dialog in dialogs:

            try:
                dialog.close()
            except Exception:
                logger.exception(
                    "Failed to close dialog."
                )

        with self._lock:
            self._active.clear()

    # ========================================================================
    # Diagnostics
    # ========================================================================

    def diagnostics(self) -> dict[str, Any]:

        with self._lock:

            return {
                "active_dialogs": len(
                    self._active
                ),
                "theme": {
                    "background":
                        self.theme.background,

                    "surface":
                        self.theme.surface,

                    "accent":
                        self.theme.accent,

                    "width":
                        self.theme.width,
                },
            }

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(self) -> None:
        """Close all dialogs."""

        self.close_all()


# ============================================================================
# Convenience Functions
# ============================================================================

def show_info(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    theme: DialogTheme | None = None,
) -> DialogResult:
    """Show an information dialog."""

    return DialogManager(
        parent,
        theme=theme,
    ).info(
        title,
        message,
    )


def show_warning(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    theme: DialogTheme | None = None,
) -> DialogResult:
    """Show a warning dialog."""

    return DialogManager(
        parent,
        theme=theme,
    ).warning(
        title,
        message,
    )


def show_error(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    theme: DialogTheme | None = None,
) -> DialogResult:
    """Show an error dialog."""

    return DialogManager(
        parent,
        theme=theme,
    ).error(
        title,
        message,
    )


def ask_confirmation(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    theme: DialogTheme | None = None,
) -> bool:
    """Ask the user for confirmation."""

    return DialogManager(
        parent,
        theme=theme,
    ).confirm(
        title,
        message,
    )


def ask_input(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    default_value: str = "",
    password: bool = False,
    validate: Callable[[str], bool] | None = None,
    theme: DialogTheme | None = None,
) -> str | None:
    """Ask the user for text input."""

    return DialogManager(
        parent,
        theme=theme,
    ).input(
        title,
        message,
        default_value=default_value,
        password=password,
        validate=validate,
    )


def ask_choice(
    parent: tk.Misc,
    title: str,
    message: str,
    choices: list[str] | tuple[str, ...],
    *,
    default_value: str | None = None,
    theme: DialogTheme | None = None,
) -> str | None:
    """Ask the user to select one option."""

    return DialogManager(
        parent,
        theme=theme,
    ).choice(
        title,
        message,
        choices,
        default_value=default_value,
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Dialogs
    "BaseDialog",
    "ChoiceDialog",
    "ConfirmDialog",
    "CustomDialog",
    "DialogConfigurationError",
    # Exceptions
    "DialogError",
    # Manager
    "DialogManager",
    "DialogRequest",
    "DialogResult",
    "DialogStateError",
    # Models
    "DialogTheme",
    # Enums
    "DialogType",
    "InputDialog",
    "LoadingDialog",
    "MessageDialog",
    "ask_choice",
    "ask_confirmation",
    "ask_input",
    "show_error",
    # Helpers
    "show_info",
    "show_warning",
]
