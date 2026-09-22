"""
AssistantX - Custom Commands
============================

Provides a professional, thread-safe custom command registry for
AssistantX.

Features:
    - Register custom commands
    - Remove commands
    - Enable / disable commands
    - Execute commands
    - Command aliases
    - Positional arguments
    - Keyword arguments
    - Metadata support
    - Safe command validation
    - Thread-safe registry
    - Easy integration with UI, automation, and database layers

Example:

    from core.custom_commands import CustomCommandManager

    commands = CustomCommandManager()

    commands.register(
        name="hello",
        handler=lambda: "Hello from AssistantX!",
        description="Say hello",
    )

    result = commands.execute("hello")

"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Final

# ============================================================================
# Types
# ============================================================================

CommandHandler = Callable[..., Any]


# ============================================================================
# Constants
# ============================================================================

DEFAULT_ENABLED: Final[bool] = True
MAX_COMMAND_NAME_LENGTH: Final[int] = 64
MAX_DESCRIPTION_LENGTH: Final[int] = 500


# ============================================================================
# Exceptions
# ============================================================================


class CustomCommandError(Exception):
    """Base exception for custom command errors."""


class InvalidCommandError(CustomCommandError):
    """Raised when a command definition is invalid."""


class CommandAlreadyExistsError(CustomCommandError):
    """Raised when attempting to register an existing command."""


class CommandNotFoundError(CustomCommandError):
    """Raised when a requested command does not exist."""


class CommandDisabledError(CustomCommandError):
    """Raised when attempting to execute a disabled command."""


class CommandExecutionError(CustomCommandError):
    """Raised when a command handler fails during execution."""


# ============================================================================
# Command Model
# ============================================================================


@dataclass(slots=True)
class CustomCommand:
    """
    Represents a registered AssistantX custom command.

    Attributes:
        name:
            Unique command name.

        handler:
            Callable executed when the command runs.

        description:
            Human-readable command description.

        aliases:
            Alternative names for the command.

        enabled:
            Whether the command can currently be executed.

        category:
            Optional command category.

        metadata:
            Additional plugin/application-specific information.
    """

    name: str
    handler: CommandHandler
    description: str = ""
    aliases: tuple[str, ...] = ()
    enabled: bool = DEFAULT_ENABLED
    category: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and normalize the command definition."""

        self.name = self.name.strip().lower()
        self.description = self.description.strip()
        self.category = self.category.strip().lower() or "general"

        self.aliases = tuple(
            alias.strip().lower()
            for alias in self.aliases
            if alias and alias.strip()
        )

        self._validate()

    def _validate(self) -> None:
        """Validate command fields."""

        if not self.name:
            raise InvalidCommandError("Command name cannot be empty.")

        if len(self.name) > MAX_COMMAND_NAME_LENGTH:
            raise InvalidCommandError(
                f"Command name cannot exceed "
                f"{MAX_COMMAND_NAME_LENGTH} characters."
            )

        if not callable(self.handler):
            raise InvalidCommandError(
                f"Handler for '{self.name}' must be callable."
            )

        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise InvalidCommandError(
                f"Description for '{self.name}' cannot exceed "
                f"{MAX_DESCRIPTION_LENGTH} characters."
            )

        if self.name in self.aliases:
            raise InvalidCommandError(
                f"Command '{self.name}' cannot use itself as an alias."
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert command metadata into a serializable dictionary.

        The handler itself is intentionally excluded.
        """

        return {
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "enabled": self.enabled,
            "category": self.category,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Command Manager
# ============================================================================


class CustomCommandManager:
    """
    Thread-safe manager for AssistantX custom commands.

    This class acts as the runtime command registry.

    It does NOT execute arbitrary shell commands by itself.
    Handlers must be explicitly registered by application/plugin code.
    """

    def __init__(self) -> None:
        self._commands: dict[str, CustomCommand] = {}
        self._aliases: dict[str, str] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        description: str = "",
        aliases: Iterable[str] | None = None,
        enabled: bool = DEFAULT_ENABLED,
        category: str = "general",
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> CustomCommand:
        """
        Register a new custom command.

        Args:
            name:
                Unique command name.

            handler:
                Callable to execute.

            description:
                Human-readable description.

            aliases:
                Optional alternative command names.

            enabled:
                Whether the command starts enabled.

            category:
                Command category.

            metadata:
                Optional extra information.

            replace:
                Replace an existing command if True.

        Returns:
            CustomCommand: Registered command.
        """

        normalized_name = self._normalize_name(name)
        normalized_aliases = tuple(
            self._normalize_name(alias)
            for alias in (aliases or ())
        )

        command = CustomCommand(
            name=normalized_name,
            handler=handler,
            description=description,
            aliases=normalized_aliases,
            enabled=enabled,
            category=category,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            if not replace and self._resolve_name(normalized_name) is not None:
                raise CommandAlreadyExistsError(
                    f"Command '{normalized_name}' already exists."
                )

            if replace and normalized_name in self._commands:
                self.unregister(normalized_name)

            self._validate_alias_conflicts(command)

            self._commands[command.name] = command

            for alias in command.aliases:
                self._aliases[alias] = command.name

        return command

    # ------------------------------------------------------------------------
    # Unregister
    # ------------------------------------------------------------------------

    def unregister(self, name: str) -> bool:
        """
        Remove a command.

        Returns:
            bool: True if a command was removed.
        """

        normalized_name = self._normalize_name(name)

        with self._lock:
            command_name = self._resolve_name(normalized_name)

            if command_name is None:
                return False

            command = self._commands.pop(command_name)

            for alias in command.aliases:
                self._aliases.pop(alias, None)

            return True

    # ------------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------------

    def get(self, name: str) -> CustomCommand:
        """
        Retrieve a command by name or alias.

        Raises:
            CommandNotFoundError:
                If the command does not exist.
        """

        normalized_name = self._normalize_name(name)

        with self._lock:
            command_name = self._resolve_name(normalized_name)

            if command_name is None:
                raise CommandNotFoundError(
                    f"Command '{normalized_name}' was not found."
                )

            return self._commands[command_name]

    def exists(self, name: str) -> bool:
        """Return True if a command exists."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return self._resolve_name(normalized_name) is not None

    # ------------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------------

    def enable(self, name: str) -> CustomCommand:
        """Enable a command."""

        command = self.get(name)

        with self._lock:
            command.enabled = True

        return command

    def disable(self, name: str) -> CustomCommand:
        """Disable a command."""

        command = self.get(name)

        with self._lock:
            command.enabled = False

        return command

    # ------------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------------

    def execute(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a registered command.

        Args:
            name:
                Command name or alias.

            *args:
                Positional arguments passed to the handler.

            **kwargs:
                Keyword arguments passed to the handler.

        Returns:
            Any: Handler result.

        Raises:
            CommandDisabledError:
                If the command is disabled.

            CommandExecutionError:
                If the handler raises an exception.
        """

        command = self.get(name)

        if not command.enabled:
            raise CommandDisabledError(
                f"Command '{command.name}' is disabled."
            )

        try:
            return command.handler(*args, **kwargs)

        except CustomCommandError:
            raise

        except Exception as exc:
            raise CommandExecutionError(
                f"Command '{command.name}' failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------------

    def list_commands(
        self,
        *,
        enabled_only: bool = False,
        category: str | None = None,
    ) -> list[CustomCommand]:
        """
        Return registered commands.

        Args:
            enabled_only:
                Return only enabled commands.

            category:
                Optional category filter.
        """

        normalized_category = (
            category.strip().lower()
            if category
            else None
        )

        with self._lock:
            commands = list(self._commands.values())

        if enabled_only:
            commands = [
                command
                for command in commands
                if command.enabled
            ]

        if normalized_category:
            commands = [
                command
                for command in commands
                if command.category == normalized_category
            ]

        return sorted(commands, key=lambda command: command.name)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def export_metadata(self) -> list[dict[str, Any]]:
        """
        Export command metadata.

        Handlers are excluded because they are not safely serializable.
        """

        return [
            command.to_dict()
            for command in self.list_commands()
        ]

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of registered commands."""

        with self._lock:
            return len(self._commands)

    def enabled_count(self) -> int:
        """Return number of enabled commands."""

        with self._lock:
            return sum(
                command.enabled
                for command in self._commands.values()
            )

    # ------------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all registered commands."""

        with self._lock:
            self._commands.clear()
            self._aliases.clear()

    # ------------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize and validate a command name."""

        if not isinstance(name, str):
            raise InvalidCommandError(
                "Command name must be a string."
            )

        normalized = name.strip().lower()

        if not normalized:
            raise InvalidCommandError(
                "Command name cannot be empty."
            )

        if len(normalized) > MAX_COMMAND_NAME_LENGTH:
            raise InvalidCommandError(
                f"Command name cannot exceed "
                f"{MAX_COMMAND_NAME_LENGTH} characters."
            )

        return normalized

    def _resolve_name(self, name: str) -> str | None:
        """Resolve a command name or alias to the canonical name."""

        if name in self._commands:
            return name

        return self._aliases.get(name)

    def _validate_alias_conflicts(
        self,
        command: CustomCommand,
    ) -> None:
        """Ensure aliases do not conflict with existing commands."""

        for alias in command.aliases:
            if alias == command.name:
                raise InvalidCommandError(
                    f"Alias '{alias}' cannot match command name."
                )

            if alias in self._commands:
                raise CommandAlreadyExistsError(
                    f"Alias '{alias}' conflicts with an existing command."
                )

            if alias in self._aliases:
                raise CommandAlreadyExistsError(
                    f"Alias '{alias}' is already registered."
                )


# ============================================================================
# Default Global Manager
# ============================================================================

custom_command_manager: Final[CustomCommandManager] = (
    CustomCommandManager()
)


# ============================================================================
# Public API
# ============================================================================

__all__: Final[tuple[str, ...]] = (
    "CommandAlreadyExistsError",
    "CommandDisabledError",
    "CommandExecutionError",
    "CommandHandler",
    "CommandNotFoundError",
    "CustomCommand",
    "CustomCommandError",
    "CustomCommandManager",
    "InvalidCommandError",
    "custom_command_manager",
)
