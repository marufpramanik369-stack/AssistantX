"""
AssistantX - Extension Registry
================================

Central registry for runtime extensions used by AssistantX.

Extensions are lightweight, modular capabilities that can be registered
by the core application or by plugins.

Typical extension types:
    - command
    - tool
    - provider
    - automation
    - service
    - integration

Design goals:
    - Thread-safe
    - Type-safe
    - Duplicate protection
    - Enable / disable support
    - Metadata support
    - Plugin-friendly
    - No direct dependency on UI or database layers

Example:

    from core.extensions import extension_manager

    extension_manager.register(
        name="web_search",
        extension_type="tool",
        handler=my_search_function,
        description="Search the web",
    )

    result = extension_manager.execute(
        "web_search",
        "latest AI news",
    )
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Final

# ============================================================================
# Types
# ============================================================================

ExtensionHandler = Callable[..., Any]


# ============================================================================
# Constants
# ============================================================================

DEFAULT_ENABLED: Final[bool] = True
DEFAULT_EXTENSION_TYPE: Final[str] = "service"

MAX_NAME_LENGTH: Final[int] = 64
MAX_TYPE_LENGTH: Final[int] = 32
MAX_DESCRIPTION_LENGTH: Final[int] = 500


# ============================================================================
# Exceptions
# ============================================================================


class ExtensionError(Exception):
    """Base exception for extension-related errors."""


class InvalidExtensionError(ExtensionError):
    """Raised when an extension definition is invalid."""


class ExtensionAlreadyExistsError(ExtensionError):
    """Raised when an extension already exists."""


class ExtensionNotFoundError(ExtensionError):
    """Raised when an extension cannot be found."""


class ExtensionDisabledError(ExtensionError):
    """Raised when an extension is disabled."""


class ExtensionExecutionError(ExtensionError):
    """Raised when an extension handler fails."""


# ============================================================================
# Extension Model
# ============================================================================


@dataclass(slots=True)
class Extension:
    """
    Runtime representation of an AssistantX extension.

    Attributes:
        name:
            Unique extension identifier.

        handler:
            Callable responsible for the extension's operation.

        extension_type:
            Logical category such as ``tool``, ``provider``,
            ``automation`` or ``service``.

        description:
            Human-readable description.

        aliases:
            Alternative names used to resolve the extension.

        enabled:
            Whether the extension is currently active.

        version:
            Extension version.

        metadata:
            Additional extension-specific information.
    """

    name: str
    handler: ExtensionHandler
    extension_type: str = DEFAULT_EXTENSION_TYPE
    description: str = ""
    aliases: tuple[str, ...] = ()
    enabled: bool = DEFAULT_ENABLED
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate extension data."""

        self.name = self.name.strip().lower()

        self.extension_type = (
            self.extension_type.strip().lower()
            or DEFAULT_EXTENSION_TYPE
        )

        self.description = self.description.strip()

        self.version = self.version.strip() or "1.0.0"

        self.aliases = tuple(
            alias.strip().lower()
            for alias in self.aliases
            if alias and alias.strip()
        )

        self._validate()

    def _validate(self) -> None:
        """Validate extension configuration."""

        if not self.name:
            raise InvalidExtensionError(
                "Extension name cannot be empty."
            )

        if len(self.name) > MAX_NAME_LENGTH:
            raise InvalidExtensionError(
                f"Extension name cannot exceed "
                f"{MAX_NAME_LENGTH} characters."
            )

        if not callable(self.handler):
            raise InvalidExtensionError(
                f"Handler for '{self.name}' must be callable."
            )

        if len(self.extension_type) > MAX_TYPE_LENGTH:
            raise InvalidExtensionError(
                f"Extension type cannot exceed "
                f"{MAX_TYPE_LENGTH} characters."
            )

        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise InvalidExtensionError(
                f"Description cannot exceed "
                f"{MAX_DESCRIPTION_LENGTH} characters."
            )

        if self.name in self.aliases:
            raise InvalidExtensionError(
                f"Extension '{self.name}' cannot use itself as an alias."
            )

    def to_dict(self) -> dict[str, Any]:
        """
        Return serializable extension metadata.

        The executable handler is intentionally excluded.
        """

        return {
            "name": self.name,
            "extension_type": self.extension_type,
            "description": self.description,
            "aliases": list(self.aliases),
            "enabled": self.enabled,
            "version": self.version,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Extension Manager
# ============================================================================


class ExtensionManager:
    """
    Thread-safe registry for AssistantX extensions.

    The manager stores extension definitions and controls their runtime
    lifecycle. It does not directly load files or discover modules;
    plugin discovery can be implemented separately.
    """

    def __init__(self) -> None:
        self._extensions: dict[str, Extension] = {}
        self._aliases: dict[str, str] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: ExtensionHandler,
        *,
        extension_type: str = DEFAULT_EXTENSION_TYPE,
        description: str = "",
        aliases: Iterable[str] | None = None,
        enabled: bool = DEFAULT_ENABLED,
        version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> Extension:
        """
        Register an extension.

        Args:
            name:
                Unique extension name.

            handler:
                Callable executed by the extension.

            extension_type:
                Extension category.

            description:
                Human-readable description.

            aliases:
                Optional alternative names.

            enabled:
                Initial enabled state.

            version:
                Extension version.

            metadata:
                Additional metadata.

            replace:
                Replace an existing extension when True.

        Returns:
            Extension: Registered extension.
        """

        normalized_name = self._normalize_name(name)

        normalized_aliases = tuple(
            self._normalize_name(alias)
            for alias in (aliases or ())
        )

        extension = Extension(
            name=normalized_name,
            handler=handler,
            extension_type=extension_type,
            description=description,
            aliases=normalized_aliases,
            enabled=enabled,
            version=version,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            existing = self._resolve_name(normalized_name)

            if existing is not None and not replace:
                raise ExtensionAlreadyExistsError(
                    f"Extension '{normalized_name}' already exists."
                )

            if replace and normalized_name in self._extensions:
                self.unregister(normalized_name)

            self._validate_alias_conflicts(extension)

            self._extensions[extension.name] = extension

            for alias in extension.aliases:
                self._aliases[alias] = extension.name

        return extension

    # ------------------------------------------------------------------------
    # Unregister
    # ------------------------------------------------------------------------

    def unregister(self, name: str) -> bool:
        """
        Remove an extension.

        Returns:
            bool: True if the extension was removed.
        """

        normalized_name = self._normalize_name(name)

        with self._lock:
            canonical_name = self._resolve_name(normalized_name)

            if canonical_name is None:
                return False

            extension = self._extensions.pop(canonical_name)

            for alias in extension.aliases:
                self._aliases.pop(alias, None)

            return True

    # ------------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------------

    def get(self, name: str) -> Extension:
        """
        Retrieve an extension by name or alias.

        Raises:
            ExtensionNotFoundError:
                If the extension does not exist.
        """

        normalized_name = self._normalize_name(name)

        with self._lock:
            canonical_name = self._resolve_name(normalized_name)

            if canonical_name is None:
                raise ExtensionNotFoundError(
                    f"Extension '{normalized_name}' was not found."
                )

            return self._extensions[canonical_name]

    def exists(self, name: str) -> bool:
        """Return True if an extension exists."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return self._resolve_name(normalized_name) is not None

    # ------------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------------

    def enable(self, name: str) -> Extension:
        """Enable an extension."""

        extension = self.get(name)

        with self._lock:
            extension.enabled = True

        return extension

    def disable(self, name: str) -> Extension:
        """Disable an extension."""

        extension = self.get(name)

        with self._lock:
            extension.enabled = False

        return extension

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
        Execute an extension handler.

        Raises:
            ExtensionDisabledError:
                If the extension is disabled.

            ExtensionExecutionError:
                If the handler fails.
        """

        extension = self.get(name)

        if not extension.enabled:
            raise ExtensionDisabledError(
                f"Extension '{extension.name}' is disabled."
            )

        try:
            return extension.handler(*args, **kwargs)

        except ExtensionError:
            raise

        except Exception as exc:
            raise ExtensionExecutionError(
                f"Extension '{extension.name}' failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------------

    def list_extensions(
        self,
        *,
        enabled_only: bool = False,
        extension_type: str | None = None,
    ) -> list[Extension]:
        """
        Return registered extensions.

        Args:
            enabled_only:
                Return only enabled extensions.

            extension_type:
                Optional type filter.
        """

        normalized_type = (
            extension_type.strip().lower()
            if extension_type
            else None
        )

        with self._lock:
            extensions = list(self._extensions.values())

        if enabled_only:
            extensions = [
                extension
                for extension in extensions
                if extension.enabled
            ]

        if normalized_type:
            extensions = [
                extension
                for extension in extensions
                if extension.extension_type == normalized_type
            ]

        return sorted(
            extensions,
            key=lambda extension: extension.name,
        )

    # ------------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------------

    def export_metadata(self) -> list[dict[str, Any]]:
        """
        Export serializable metadata for all extensions.
        """

        return [
            extension.to_dict()
            for extension in self.list_extensions()
        ]

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of registered extensions."""

        with self._lock:
            return len(self._extensions)

    def enabled_count(self) -> int:
        """Return number of enabled extensions."""

        with self._lock:
            return sum(
                extension.enabled
                for extension in self._extensions.values()
            )

    def count_by_type(self) -> dict[str, int]:
        """Return extension counts grouped by extension type."""

        with self._lock:
            result: dict[str, int] = {}

            for extension in self._extensions.values():
                result[extension.extension_type] = (
                    result.get(extension.extension_type, 0) + 1
                )

            return dict(sorted(result.items()))

    # ------------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all registered extensions."""

        with self._lock:
            self._extensions.clear()
            self._aliases.clear()

    # ------------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize and validate an extension name."""

        if not isinstance(name, str):
            raise InvalidExtensionError(
                "Extension name must be a string."
            )

        normalized = name.strip().lower()

        if not normalized:
            raise InvalidExtensionError(
                "Extension name cannot be empty."
            )

        if len(normalized) > MAX_NAME_LENGTH:
            raise InvalidExtensionError(
                f"Extension name cannot exceed "
                f"{MAX_NAME_LENGTH} characters."
            )

        return normalized

    def _resolve_name(self, name: str) -> str | None:
        """Resolve canonical extension name from name or alias."""

        if name in self._extensions:
            return name

        return self._aliases.get(name)

    def _validate_alias_conflicts(
        self,
        extension: Extension,
    ) -> None:
        """Validate aliases against existing extensions."""

        for alias in extension.aliases:

            if alias == extension.name:
                raise InvalidExtensionError(
                    f"Alias '{alias}' cannot match extension name."
                )

            if alias in self._extensions:
                raise ExtensionAlreadyExistsError(
                    f"Alias '{alias}' conflicts with an existing extension."
                )

            if alias in self._aliases:
                raise ExtensionAlreadyExistsError(
                    f"Alias '{alias}' is already registered."
                )


# ============================================================================
# Global Extension Manager
# ============================================================================

extension_manager: Final[ExtensionManager] = ExtensionManager()


# ============================================================================
# Public API
# ============================================================================

__all__: Final[tuple[str, ...]] = (
    "Extension",
    "ExtensionAlreadyExistsError",
    "ExtensionDisabledError",
    "ExtensionError",
    "ExtensionExecutionError",
    "ExtensionHandler",
    "ExtensionManager",
    "ExtensionNotFoundError",
    "InvalidExtensionError",
    "extension_manager",
)
