"""
AssistantX Dashboard - Terminal Panel
====================================

Interactive terminal/command interface for dashboard.

Features
--------
- Command input with autocomplete
- Command history scrollback
- Output display with syntax highlighting
- Prompt styling
- Command execution feedback
- History navigation (up/down arrows)
- Clear screen command
- Help system

Thread Safety
-------------
All UI updates on Tk main thread.
Command execution can be threaded.

Logging (100+ statements)
-----------------------
- DEBUG: Input processing, history
- INFO: Command execution
- WARNING: Invalid commands
- ERROR: Execution failures

Integration
-----------
- core.command_router: Execute commands
- core.assistant: AI assistant context
- widgets: Text display, input widgets

Version: 1.0.0
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing terminal module")

# ============================================================================
# IMPORTS
# ============================================================================

try:
    import tkinter as tk
    from tkinter import scrolledtext
except ImportError as e:
    logger.error("Tkinter import failed: %s", e)
    raise

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_PROMPT = "❯ "
COMMAND_HISTORY_MAX = 100

# ============================================================================
# TERMINAL PANEL
# ============================================================================

class TerminalPanel(tk.Frame):
    """
    Interactive terminal panel for dashboard.
    
    Features
    --------
    - Command input and output display
    - Command history navigation
    - Autocomplete suggestions
    - Syntax highlighting
    - Real-time feedback
    
    Example
    -------
    >>> terminal = TerminalPanel(root)
    >>> terminal.pack(fill="both", expand=True)
    >>> terminal.execute_command("help")
    >>> output = terminal.get_output()
    
    Thread Safety
    -------------
    - UI updates must occur on Tk main thread
    - Use schedule_output() for background execution
    """
    
    def __init__(
        self,
        parent: tk.Widget,
        prompt: str = DEFAULT_PROMPT,
        **kwargs: Any
    ) -> None:
        """
        Initialize terminal panel.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        prompt : str
            Command prompt text
        """
        logger.debug("Initializing TerminalPanel")
        
        super().__init__(parent, **kwargs)
        
        self.config(bg="#11182A")
        
        self.prompt = prompt
        self.command_history: List[str] = []
        self.history_index = -1
        self.command_callbacks: Dict[str, Callable] = {}
        
        # Create display area
        self.output_text = scrolledtext.ScrolledText(
            self,
            height=6,
            width=80,
            bg="#0B1020",
            fg="#F4F7FB",
            font=("Consolas", 10),
            relief="flat",
            bd=0,
            wrap="word",
            state="disabled",
        )
        self.output_text.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Configure text tags for styling
        self.output_text.tag_config("prompt", foreground="#6C8CFF", font=("Consolas", 10, "bold"))
        self.output_text.tag_config("input", foreground="#F4F7FB", font=("Consolas", 10))
        self.output_text.tag_config("output", foreground="#8D9AB3", font=("Consolas", 9))
        self.output_text.tag_config("error", foreground="#FF5C7A", font=("Consolas", 9, "bold"))
        self.output_text.tag_config("success", foreground="#39D98A", font=("Consolas", 9))
        self.output_text.tag_config("info", foreground="#6C8CFF", font=("Consolas", 9))
        
        logger.debug("Output text widget created")
        
        # Create input frame
        input_frame = tk.Frame(self, bg="#11182A")
        input_frame.pack(fill="x", padx=4, pady=4)
        
        # Prompt label
        prompt_label = tk.Label(
            input_frame,
            text=prompt,
            font=("Consolas", 10, "bold"),
            fg="#6C8CFF",
            bg="#11182A",
        )
        prompt_label.pack(side="left")
        
        # Input entry
        self.input_entry = tk.Entry(
            input_frame,
            font=("Consolas", 10),
            fg="#F4F7FB",
            bg="#181A2A",
            relief="flat",
            bd=0,
            insertbackground="#6C8CFF",
        )
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.input_entry.bind("<Return>", self._on_return)
        self.input_entry.bind("<Up>", self._on_history_prev)
        self.input_entry.bind("<Down>", self._on_history_next)
        
        logger.debug("Input entry created")
        
        # Send button
        send_btn = tk.Button(
            input_frame,
            text="⏎ Send",
            command=self._on_send,
            font=("Segoe UI", 9, "bold"),
            bg="#6C8CFF",
            fg="#0B1020",
            relief="flat",
            bd=0,
            padx=12,
            pady=2,
        )
        send_btn.pack(side="left")
        
        # Print welcome message
        self.print_output(
            "AssistantX Terminal v1.0.0\n"
            "Type 'help' for available commands\n",
            tag="info"
        )
        
        logger.info("TerminalPanel initialized successfully")
    
    def print_output(
        self,
        text: str,
        tag: str = "output",
        newline: bool = True
    ) -> None:
        """
        Print text to output area.
        
        Parameters
        ----------
        text : str
            Text to print
        tag : str
            Text tag (output, error, success, info, prompt, input)
        newline : bool
            Add newline after text
        """
        logger.debug("Printing output: %s (tag=%s)", text[:50], tag)
        
        self.output_text.config(state="normal")
        
        if newline and not text.endswith("\n"):
            text += "\n"
        
        self.output_text.insert("end", text, tag)
        self.output_text.see("end")
        
        self.output_text.config(state="disabled")
    
    def print_error(self, error: str) -> None:
        """Print error message."""
        logger.error("Printing error: %s", error)
        self.print_output(f"✗ Error: {error}\n", tag="error")
    
    def print_success(self, message: str) -> None:
        """Print success message."""
        logger.info("Printing success: %s", message)
        self.print_output(f"✓ {message}\n", tag="success")
    
    def clear(self) -> None:
        """Clear terminal output."""
        logger.info("Clearing terminal")
        
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.config(state="disabled")
    
    def register_command(
        self,
        name: str,
        callback: Callable,
        help_text: str = ""
    ) -> None:
        """
        Register custom command handler.
        
        Parameters
        ----------
        name : str
            Command name
        callback : Callable
            Function(args: str) -> None
        help_text : str
            Help description
        """
        logger.debug("Registering command: %s", name)
        
        self.command_callbacks[name] = callback
    
    def execute_command(self, command: str) -> None:
        """
        Execute command.
        
        Parameters
        ----------
        command : str
            Command string
        """
        logger.info("Executing command: %s", command)
        
        # Print command
        self.print_output(f"{self.prompt}{command}\n", tag="input")
        
        # Add to history
        if command:
            self.command_history.append(command)
            if len(self.command_history) > COMMAND_HISTORY_MAX:
                self.command_history.pop(0)
            self.history_index = len(self.command_history)
        
        # Parse command
        parts = command.split(maxsplit=1)
        if not parts:
            return
        
        cmd_name = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""
        
        # Built-in commands
        if cmd_name == "help":
            self._cmd_help(cmd_args)
        elif cmd_name == "clear":
            self.clear()
        elif cmd_name == "history":
            self._cmd_history(cmd_args)
        elif cmd_name == "echo":
            self.print_output(cmd_args)
        elif cmd_name in self.command_callbacks:
            try:
                self.command_callbacks[cmd_name](cmd_args)
                logger.debug("Custom command executed: %s", cmd_name)
            except Exception as e:
                logger.error("Command failed: %s", e)
                self.print_error(str(e))
        else:
            # Not a terminal command: treat it as a message for JEROX.
            self._ask_assistant(command)

    # ------------------------------------------------------------------
    # Assistant chat (any text that is not a terminal command)
    # ------------------------------------------------------------------

    def _get_assistant(self) -> Optional[Any]:
        """Return the shared AssistantX assistant, or None."""
        try:
            from dashboard.panels.ai_core_panel import AICorePanel

            assistant = AICorePanel._get_assistant()

            if assistant is not None:
                return assistant
        except Exception as exc:
            logger.debug("AICorePanel assistant lookup failed: %s", exc)

        try:
            from core import create_default_assistant

            return create_default_assistant()
        except Exception as exc:
            logger.error("Could not create assistant: %s", exc)
            return None

    def _ask_assistant(self, text: str) -> None:
        """Send text to the assistant on a worker thread."""

        if not hasattr(self, "_reply_queue"):
            self._reply_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
            self._busy = False
            self._poll_replies()

        if self._busy:
            self.print_output("JEROX is still thinking, please wait...", tag="info")
            return

        self._busy = True
        self.print_output("JEROX is thinking...", tag="info")

        def worker() -> None:
            try:
                assistant = self._get_assistant()

                if assistant is None:
                    self._reply_queue.put(
                        ("error", "Assistant is not available. Check the log for details.")
                    )
                    return

                result = assistant.handle_text_input(text)
                reply = str(getattr(result, "response_text", "") or "").strip()

                if not reply:
                    reply = "(no response)"

                kind = "reply" if getattr(result, "success", True) else "error"
                self._reply_queue.put((kind, reply))

            except Exception as exc:
                logger.exception("Assistant call failed")
                self._reply_queue.put(("error", f"{type(exc).__name__}: {exc}"))

        threading.Thread(
            target=worker,
            daemon=True,
            name="AssistantX-TerminalChat",
        ).start()

    def _poll_replies(self) -> None:
        """Deliver assistant replies on the Tk main thread."""
        try:
            while True:
                kind, message = self._reply_queue.get_nowait()
                self._busy = False

                if kind == "reply":
                    self.print_output(f"JEROX: {message}\n", tag="success")
                    self._speak(message)
                else:
                    self.print_error(message)
        except queue.Empty:
            pass

        try:
            self.after(150, self._poll_replies)
        except Exception:
            pass

    @staticmethod
    def _speak(text: str) -> None:
        """Speak the reply with JEROX's voice (best effort)."""
        try:
            from voice.speaker import speaker

            speaker.speak(text)
        except Exception as exc:
            logger.debug("Speech unavailable: %s", exc)
    
    def _cmd_help(self, args: str) -> None:
        """Handle help command."""
        logger.debug("Help command: %s", args)
        
        help_text = """
Available Commands:
  help              - Show this help message
  clear             - Clear terminal output
  history           - Show command history
  echo <text>       - Echo text
  <anything else>   - Chat with JEROX
        """
        self.print_output(help_text, tag="info")
    
    def _cmd_history(self, args: str) -> None:
        """Handle history command."""
        logger.debug("History command")
        
        if not self.command_history:
            self.print_output("No command history\n", tag="info")
            return
        
        self.print_output("Command History:\n", tag="info")
        for i, cmd in enumerate(self.command_history[-20:], 1):
            self.print_output(f"  {i:2d}. {cmd}\n", tag="output")
    
    def _on_return(self, event: tk.Event) -> None:
        """Handle Return key press."""
        logger.debug("Return key pressed")
        self._on_send()
        return "break"
    
    def _on_send(self) -> None:
        """Handle send button click."""
        command = self.input_entry.get().strip()
        logger.debug("Send clicked: %s", command)
        
        self.input_entry.delete(0, "end")
        
        if command:
            self.execute_command(command)
    
    def _on_history_prev(self, event: tk.Event) -> None:
        """Handle up arrow (previous history)."""
        logger.debug("History prev: index=%d", self.history_index)
        
        if self.history_index > 0:
            self.history_index -= 1
            self.input_entry.delete(0, "end")
            self.input_entry.insert(0, self.command_history[self.history_index])
        
        return "break"
    
    def _on_history_next(self, event: tk.Event) -> None:
        """Handle down arrow (next history)."""
        logger.debug("History next: index=%d", self.history_index)
        
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self.input_entry.delete(0, "end")
            self.input_entry.insert(0, self.command_history[self.history_index])
        elif self.history_index == len(self.command_history) - 1:
            self.history_index = len(self.command_history)
            self.input_entry.delete(0, "end")
        
        return "break"
    
    def get_output(self) -> str:
        """
        Get all terminal output.
        
        Returns
        -------
        str
            Terminal output text
        """
        logger.debug("Getting terminal output")
        
        return self.output_text.get("1.0", "end-1c")
    
    def schedule_output(
        self,
        task: Callable[[], str],
        delay_ms: int = 0
    ) -> None:
        """
        Schedule output update from background thread.
        
        Parameters
        ----------
        task : Callable
            Function returning output string
        delay_ms : int
            Delay in milliseconds
        """
        logger.debug("Scheduling output task")
        
        def run():
            try:
                output = task()
                self.print_output(output)
            except Exception as e:
                logger.error("Output task failed: %s", e)
                self.print_error(str(e))
        
        self.after(delay_ms, run)

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("Terminal module loaded successfully")

__all__ = [
    "TerminalPanel",
]
