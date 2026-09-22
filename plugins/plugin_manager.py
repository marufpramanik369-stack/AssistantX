"""
AssistantX - Plugin Manager
===========================

Professional plugin lifecycle and registry manager for AssistantX.

Responsibilities:
    - Discover plugins from the plugins package
    - Register plugin instances
    - Load / unload plugins
    - Enable / disable plugins
    - Resolve plugin dependencies
    - Prevent duplicate registrations
    - Isolate plugin failures
    - Expose plugin metadata
    - Provide lifecycle hooks
    - Support future Gemini / Ollama / Browser / Automation plugins

Architecture:

    PluginManager
          |
          +---- Plugin Registry
          |
          +---- Dependency Resolver
          |
          +---- Lifecycle Manager
          |
          +---- Plugin Instances
          |
          +---- AssistantX Core

The manager intentionally does not depend on Dashboard/UI code.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from threading import RLock
from types import ModuleType
from typing import Any, Final

from core.logger import get_logger

# ============================================================================
# Logger
# ============================================================================

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_PLUGIN_API_VERSION: Final[str] = "1.0"

PLUGIN_STATE_DISCOVERED: Final[str] = "discovered"
PLUGIN_STATE_LOADED: Final[str] = "loaded"
PLUGIN_STATE_ENABLED: Final[str] = "enabled"
PLUGIN_STATE_DISABLED: Final[str] = "disabled"
PLUGIN_STATE_FAILED: Final[str] = "failed"
PLUGIN_STATE_UNLOADED: Final[str] = "unloaded"


# ============================================================================
# Exceptions
# ============================================================================


class PluginManagerError(Exception):
    """Base exception for plugin manager errors."""


class PluginRegistrationError(PluginManagerError):
    """Raised when a plugin cannot be registered."""


class PluginAlreadyExistsError(PluginManagerError):
    """Raised when a plugin is already registered."""


class PluginNotFoundError(PluginManagerError):
    """Raised when a plugin cannot be found."""


class PluginLoadError(PluginManagerError):
    """Raised when a plugin cannot be loaded."""


class PluginUnloadError(PluginManagerError):
    """Raised when a plugin cannot be unloaded."""


class PluginDependencyError(PluginManagerError):
    """Raised when plugin dependencies cannot be satisfied."""


class PluginLifecycleError(PluginManagerError):
    """Raised when a plugin lifecycle operation fails."""


# ============================================================================
# Plugin Record
# ============================================================================


@dataclass(slots=True)
class PluginRecord:
    """
    Runtime information about a registered plugin.

    Attributes:
        name:
            Unique plugin identifier.

        plugin:
            Plugin instance.

        module:
            Python module containing the plugin.

        enabled:
            Current enabled state.

        state:
            Current lifecycle state.

        error:
            Last known plugin error.

        metadata:
            Additional runtime information.
    """

    name: str
    plugin: Any
    module: ModuleType | None = None
    enabled: bool = False
    state: str = PLUGIN_STATE_DISCOVERED
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return serializable plugin metadata."""

        plugin = self.plugin

        return {
            "name": self.name,
            "version": getattr(plugin, "version", "unknown"),
            "description": getattr(plugin, "description", ""),
            "author": getattr(plugin, "author", ""),
            "enabled": self.enabled,
            "state": self.state,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# Plugin Manager
# ============================================================================


class PluginManager:
    """
    Central manager for AssistantX plugins.

    The manager controls plugin registration and lifecycle.

    Typical lifecycle:

        discover()
            ↓
        register()
            ↓
        load()
            ↓
        enable()
            ↓
        running
            ↓
        disable()
            ↓
        unload()

    Plugin implementations should expose lifecycle methods where
    appropriate:

        on_load()
        on_enable()
        on_disable()
        on_unload()

    All lifecycle methods are optional.
    """

    def __init__(
        self,
        *,
        plugin_package: str = "plugins",
        plugin_api_version: str = DEFAULT_PLUGIN_API_VERSION,
    ) -> None:
        self.plugin_package = plugin_package
        self.plugin_api_version = plugin_api_version

        self._plugins: dict[str, PluginRecord] = {}
        self._lock = RLock()

    # ========================================================================
    # Registration
    # ========================================================================

    def register(
        self,
        plugin: Any,
        *,
        module: ModuleType | None = None,
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> PluginRecord:
        """
        Register a plugin instance.

        Args:
            plugin:
                Plugin instance.

            module:
                Optional Python module containing the plugin.

            metadata:
                Additional plugin metadata.

            replace:
                Replace an existing plugin when True.
        """

        name = self._get_plugin_name(plugin)

        with self._lock:
            if name in self._plugins and not replace:
                raise PluginAlreadyExistsError(
                    f"Plugin '{name}' is already registered."
                )

            if replace and name in self._plugins:
                self.unregister(name)

            self._validate_plugin(plugin)

            record = PluginRecord(
                name=name,
                plugin=plugin,
                module=module,
                enabled=False,
                state=PLUGIN_STATE_DISCOVERED,
                metadata=dict(metadata or {}),
            )

            self._plugins[name] = record

        logger.info("Plugin registered: %s", name)

        return record

    # ========================================================================
    # Unregister
    # ========================================================================

    def unregister(
        self,
        name: str,
        *,
        force: bool = False,
    ) -> bool:
        """
        Unregister a plugin.

        If the plugin is loaded/enabled, it will be disabled and unloaded
        before removal unless force=True.
        """

        normalized_name = self._normalize_name(name)

        with self._lock:
            record = self._plugins.get(normalized_name)

            if record is None:
                return False

        if not force:
            if record.enabled:
                self.disable(normalized_name)

            if record.state == PLUGIN_STATE_LOADED:
                self.unload(normalized_name)

        with self._lock:
            self._plugins.pop(normalized_name, None)

        logger.info("Plugin unregistered: %s", normalized_name)

        return True

    # ========================================================================
    # Lookup
    # ========================================================================

    def get(self, name: str) -> PluginRecord:
        """Return a plugin record by name."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            record = self._plugins.get(normalized_name)

            if record is None:
                raise PluginNotFoundError(
                    f"Plugin '{normalized_name}' was not found."
                )

            return record

    def exists(self, name: str) -> bool:
        """Return True if a plugin is registered."""

        normalized_name = self._normalize_name(name)

        with self._lock:
            return normalized_name in self._plugins

    # ========================================================================
    # Load
    # ========================================================================

    def load(self, name: str) -> PluginRecord:
        """
        Load a registered plugin.

        Calls the optional ``on_load()`` lifecycle hook.
        """

        record = self.get(name)

        if record.state == PLUGIN_STATE_LOADED:
            return record

        self._check_dependencies(record)

        try:
            self._call_lifecycle(record.plugin, "on_load")

        except Exception as exc:
            self._mark_failed(record, exc)

            logger.exception(
                "Failed to load plugin '%s'.",
                record.name,
            )

            raise PluginLoadError(
                f"Failed to load plugin '{record.name}': {exc}"
            ) from exc

        with self._lock:
            record.state = PLUGIN_STATE_LOADED
            record.error = None

        logger.info("Plugin loaded: %s", record.name)

        return record

    # ========================================================================
    # Enable
    # ========================================================================

    def enable(self, name: str) -> PluginRecord:
        """
        Enable a plugin.

        The plugin is automatically loaded first when necessary.
        """

        record = self.get(name)

        if record.enabled:
            return record

        if record.state != PLUGIN_STATE_LOADED:
            record = self.load(record.name)

        try:
            self._call_lifecycle(record.plugin, "on_enable")

        except Exception as exc:
            self._mark_failed(record, exc)

            logger.exception(
                "Failed to enable plugin '%s'.",
                record.name,
            )

            raise PluginLifecycleError(
                f"Failed to enable plugin '{record.name}': {exc}"
            ) from exc

        with self._lock:
            record.enabled = True
            record.state = PLUGIN_STATE_ENABLED
            record.error = None

        logger.info("Plugin enabled: %s", record.name)

        return record

    # ========================================================================
    # Disable
    # ========================================================================

    def disable(self, name: str) -> PluginRecord:
        """Disable a running plugin."""

        record = self.get(name)

        if not record.enabled:
            return record

        try:
            self._call_lifecycle(record.plugin, "on_disable")

        except Exception as exc:
            self._mark_failed(record, exc)

            logger.exception(
                "Failed to disable plugin '%s'.",
                record.name,
            )

            raise PluginLifecycleError(
                f"Failed to disable plugin '{record.name}': {exc}"
            ) from exc

        with self._lock:
            record.enabled = False
            record.state = PLUGIN_STATE_DISABLED
            record.error = None

        logger.info("Plugin disabled: %s", record.name)

        return record

    # ========================================================================
    # Unload
    # ========================================================================

    def unload(self, name: str) -> PluginRecord:
        """
        Unload a plugin.

        Disables the plugin first when necessary, then calls ``on_unload()``.
        """

        record = self.get(name)

        if record.enabled:
            self.disable(record.name)

        if record.state == PLUGIN_STATE_UNLOADED:
            return record

        try:
            self._call_lifecycle(record.plugin, "on_unload")

        except Exception as exc:
            self._mark_failed(record, exc)

            logger.exception(
                "Failed to unload plugin '%s'.",
                record.name,
            )

            raise PluginUnloadError(
                f"Failed to unload plugin '{record.name}': {exc}"
            ) from exc

        with self._lock:
            record.state = PLUGIN_STATE_UNLOADED
            record.error = None

        logger.info("Plugin unloaded: %s", record.name)

        return record

    # ========================================================================
    # Bulk Operations
    # ========================================================================

    def load_all(self) -> list[PluginRecord]:
        """Load all registered plugins."""

        loaded: list[PluginRecord] = []

        for record in self.list_plugins():
            try:
                loaded.append(self.load(record.name))
            except PluginManagerError:
                logger.exception(
                    "Skipping failed plugin: %s",
                    record.name,
                )

        return loaded

    def enable_all(self) -> list[PluginRecord]:
        """Enable all registered plugins."""

        enabled: list[PluginRecord] = []

        for record in self.list_plugins():
            try:
                enabled.append(self.enable(record.name))
            except PluginManagerError:
                logger.exception(
                    "Skipping failed plugin: %s",
                    record.name,
                )

        return enabled

    def disable_all(self) -> None:
        """Disable all enabled plugins."""

        for record in self.list_plugins():
            if record.enabled:
                try:
                    self.disable(record.name)
                except PluginManagerError:
                    logger.exception(
                        "Failed to disable plugin: %s",
                        record.name,
                    )

    def unload_all(self) -> None:
        """Unload all loaded plugins."""

        for record in self.list_plugins():
            if record.state == PLUGIN_STATE_LOADED:
                try:
                    self.unload(record.name)
                except PluginManagerError:
                    logger.exception(
                        "Failed to unload plugin: %s",
                        record.name,
                    )

    # ========================================================================
    # Discovery
    # ========================================================================

    def discover(
        self,
        *,
        package_name: str | None = None,
    ) -> list[ModuleType]:
        """
        Discover Python modules inside the configured plugin package.

        Discovery only imports modules. It does not automatically instantiate
        arbitrary classes. Explicit registration remains the safer default.
        """

        package_name = package_name or self.plugin_package

        try:
            package = importlib.import_module(package_name)

        except ImportError as exc:
            raise PluginLoadError(
                f"Could not import plugin package '{package_name}'."
            ) from exc

        if not hasattr(package, "__path__"):
            raise PluginLoadError(
                f"'{package_name}' is not a package."
            )

        modules: list[ModuleType] = []

        for module_info in pkgutil.iter_modules(package.__path__):
            module_name = module_info.name

            if module_name.startswith("_"):
                continue

            full_name = f"{package_name}.{module_name}"

            try:
                module = importlib.import_module(full_name)
                modules.append(module)

                logger.debug(
                    "Discovered plugin module: %s",
                    full_name,
                )

            except Exception:
                logger.exception(
                    "Failed to import plugin module: %s",
                    full_name,
                )

        return modules

    # ========================================================================
    # Auto Registration
    # ========================================================================

    def discover_and_register(
        self,
        *,
        package_name: str | None = None,
    ) -> list[PluginRecord]:
        """
        Discover plugin modules and register supported plugin objects.

        A module may expose:

            PLUGIN

        or:

            create_plugin()

        or:

            get_plugin()

        The first supported mechanism is used.
        """

        modules = self.discover(package_name=package_name)
        registered: list[PluginRecord] = []

        for module in modules:
            plugin = self._extract_plugin(module)

            if plugin is None:
                logger.debug(
                    "No plugin entry point found in %s",
                    module.__name__,
                )
                continue

            try:
                record = self.register(
                    plugin,
                    module=module,
                )
                registered.append(record)

            except PluginManagerError:
                logger.exception(
                    "Failed to register plugin from %s",
                    module.__name__,
                )

        return registered

    # ========================================================================
    # Listing
    # ========================================================================

    def list_plugins(
        self,
        *,
        enabled_only: bool = False,
        state: str | None = None,
    ) -> list[PluginRecord]:
        """Return registered plugins."""

        with self._lock:
            plugins = list(self._plugins.values())

        if enabled_only:
            plugins = [
                record
                for record in plugins
                if record.enabled
            ]

        if state:
            plugins = [
                record
                for record in plugins
                if record.state == state
            ]

        return sorted(
            plugins,
            key=lambda record: record.name,
        )

    # ========================================================================
    # Metadata
    # ========================================================================

    def export_metadata(self) -> list[dict[str, Any]]:
        """Return serializable metadata for all plugins."""

        return [
            record.to_dict()
            for record in self.list_plugins()
        ]

    # ========================================================================
    # Statistics
    # ========================================================================

    def count(self) -> int:
        """Return total registered plugin count."""

        with self._lock:
            return len(self._plugins)

    def enabled_count(self) -> int:
        """Return number of enabled plugins."""

        with self._lock:
            return sum(
                record.enabled
                for record in self._plugins.values()
            )

    def failed_count(self) -> int:
        """Return number of failed plugins."""

        with self._lock:
            return sum(
                record.state == PLUGIN_STATE_FAILED
                for record in self._plugins.values()
            )

    # ========================================================================
    # Shutdown
    # ========================================================================

    def shutdown(self) -> None:
        """
        Safely shut down the plugin system.

        Plugins are disabled and unloaded individually so one broken
        plugin does not prevent the remaining plugins from shutting down.
        """

        logger.info("Shutting down plugin manager.")

        self.disable_all()

        for record in self.list_plugins():
            if record.state in {
                PLUGIN_STATE_LOADED,
                PLUGIN_STATE_DISABLED,
                PLUGIN_STATE_FAILED,
            }:
                try:
                    self.unload(record.name)
                except PluginManagerError:
                    logger.exception(
                        "Plugin shutdown failed: %s",
                        record.name,
                    )

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a plugin name."""

        if not isinstance(name, str):
            raise PluginRegistrationError(
                "Plugin name must be a string."
            )

        normalized = name.strip().lower()

        if not normalized:
            raise PluginRegistrationError(
                "Plugin name cannot be empty."
            )

        return normalized

    def _get_plugin_name(self, plugin: Any) -> str:
        """Extract and normalize a plugin name."""

        name = getattr(plugin, "name", None)

        if not isinstance(name, str) or not name.strip():
            raise PluginRegistrationError(
                "Plugin must define a non-empty 'name'."
            )

        return self._normalize_name(name)

    def _validate_plugin(self, plugin: Any) -> None:
        """Validate basic plugin compatibility."""

        if plugin is None:
            raise PluginRegistrationError(
                "Plugin cannot be None."
            )

        name = getattr(plugin, "name", None)

        if not isinstance(name, str) or not name.strip():
            raise PluginRegistrationError(
                "Plugin must define a valid 'name'."
            )

        plugin_api = getattr(
            plugin,
            "plugin_api_version",
            self.plugin_api_version,
        )

        if str(plugin_api) != str(self.plugin_api_version):
            raise PluginRegistrationError(
                f"Plugin '{name}' requires API version "
                f"{plugin_api}, but AssistantX provides "
                f"{self.plugin_api_version}."
            )

    def _check_dependencies(
        self,
        record: PluginRecord,
    ) -> None:
        """Check declared plugin dependencies."""

        dependencies = getattr(
            record.plugin,
            "dependencies",
            (),
        )

        if dependencies is None:
            return

        for dependency in dependencies:
            dependency_name = self._normalize_name(
                str(dependency)
            )

            if dependency_name not in self._plugins:
                raise PluginDependencyError(
                    f"Plugin '{record.name}' requires "
                    f"'{dependency_name}', which is not registered."
                )

            dependency_record = self._plugins[dependency_name]

            if not dependency_record.enabled:
                self.enable(dependency_name)

    @staticmethod
    def _call_lifecycle(
        plugin: Any,
        method_name: str,
    ) -> None:
        """Call an optional plugin lifecycle method."""

        method = getattr(plugin, method_name, None)

        if method is None:
            return

        if not callable(method):
            raise PluginLifecycleError(
                f"Plugin lifecycle member '{method_name}' "
                f"must be callable."
            )

        result = method()

        if inspect.isawaitable(result):
            raise PluginLifecycleError(
                f"Async lifecycle method '{method_name}' is not "
                f"supported by the synchronous PluginManager."
            )

    @staticmethod
    def _mark_failed(
        record: PluginRecord,
        error: Exception,
    ) -> None:
        """Mark a plugin as failed."""

        record.state = PLUGIN_STATE_FAILED
        record.error = str(error)
        record.enabled = False

    @staticmethod
    def _extract_plugin(
        module: ModuleType,
    ) -> Any | None:
        """Extract a plugin object from a module."""

        # Explicit plugin instance.
        plugin = getattr(module, "PLUGIN", None)

        if plugin is not None:
            return plugin

        # Factory function.
        factory = getattr(module, "create_plugin", None)

        if callable(factory):
            return factory()

        # Alternative factory name.
        factory = getattr(module, "get_plugin", None)

        if callable(factory):
            return factory()

        return None


# ============================================================================
# Global Plugin Manager
# ============================================================================

plugin_manager: Final[PluginManager] = PluginManager()


# ============================================================================
# Public API
# ============================================================================

__all__: Final[tuple[str, ...]] = (
    "PLUGIN_STATE_DISABLED",
    "PLUGIN_STATE_DISCOVERED",
    "PLUGIN_STATE_ENABLED",
    "PLUGIN_STATE_FAILED",
    "PLUGIN_STATE_LOADED",
    "PLUGIN_STATE_UNLOADED",
    "PluginAlreadyExistsError",
    "PluginDependencyError",
    "PluginLifecycleError",
    "PluginLoadError",
    "PluginManager",
    "PluginManagerError",
    "PluginNotFoundError",
    "PluginRecord",
    "PluginRegistrationError",
    "PluginUnloadError",
    "plugin_manager",
)

