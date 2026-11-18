"""
AssistantX Dashboard - AI Core Panel
===================================

AI model status and performance monitoring.

Features
--------
- Active model name display
- Inference load percentage
- Token usage (input/output)
- Inference speed (tokens/sec)
- Model health status
- Last inference time
- Queue length display

Thread Safety
-------------
Updates from core.assistant singleton.
UI updates via schedule_ui_task().

Logging (70+ statements)
-----------------------
- DEBUG: Metric fetching, updates
- INFO: Model changes
- WARNING: High load conditions
- ERROR: Model unavailable

Integration
-----------
- base_panel: BasePanel inheritance
- core.assistant: AI assistant instance
- widgets: StatDisplay, ProgressBar, StatusIndicator
- dashboard_config: Colors

Version: 1.0.0
"""

from __future__ import annotations

from core import command_router
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing ai_core_panel module")


# ============================================================================
# IMPORTS
# ============================================================================

try:
    import tkinter as tk
except ImportError as e:
    logger.error("Tkinter import failed: %s", e)
    raise

try:
    from .base_panel import (
        BasePanel,
        PanelConfig,
        RefreshMode,
    )
    logger.debug("BasePanel imported")
except ImportError as e:
    logger.error("BasePanel import failed: %s", e)
    raise

try:
    from dashboard.widgets import (
        StatDisplay,
        ProgressBar,
        StatusIndicator,
    )
    logger.debug("Dashboard widgets imported")
except ImportError as e:
    logger.warning("Dashboard widgets not available: %s", e)

try:
    from core import event_bus, command_router
    logger.debug("Core event_bus and command_router imported")
except ImportError as e:
    logger.warning("Core imports not available: %s", e)
    event_bus = None
    command_router = None

try:
    from dashboard.dashboard_config import (
        COLOR_SUCCESS,
        COLOR_WARNING,
        COLOR_ERROR,
        COLOR_MUTED,
        COLOR_ACCENT,
    )
    logger.debug("Dashboard config imported")
except ImportError as e:
    logger.warning("Dashboard config not available: %s", e)
    COLOR_SUCCESS = "#39D98A"
    COLOR_WARNING = "#F5B942"
    COLOR_ERROR = "#FF5C7A"
    COLOR_MUTED = "#8D9AB3"
    COLOR_ACCENT = "#6C8CFF"

# ============================================================================
# CONSTANTS
# ============================================================================

LOAD_WARNING_THRESHOLD = 60.0
LOAD_ERROR_THRESHOLD = 80.0

# ============================================================================
# AI CORE PANEL
# ============================================================================

class AICorePanel(BasePanel):
    """
    AI Core status monitoring panel.
    
    Displays
    --------
    - Model: Active model name
    - Load: Inference load %
    - Speed: Tokens/sec
    - Tokens: In/out counts
    - Health: Status indicator
    - Queue: Pending requests
    
    Refresh: Every 500ms
    
    Example
    -------
    >>> config = PanelConfig(
    ...     title="AI CORE",
    ...     refresh_interval_ms=500,
    ... )
    >>> panel = AICorePanel(parent, config)
    >>> panel.initialize()
    >>> panel.pack(fill="both")
    """
    _assistant_instance: Optional[Any] = None

    

    def __init__(
        self,
        parent: tk.Widget,
        config: Optional[PanelConfig] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialize AI core panel.
        
        Parameters
        ----------
        parent : tk.Widget
            Parent widget
        config : PanelConfig, optional
            Panel configuration
        """
        if config is None:
            config = PanelConfig(
                title="AI CORE",
                refresh_mode=RefreshMode.PERIODIC,
                refresh_interval_ms=500,
            )
        
        logger.debug("Initializing AICorePanel")
        
        super().__init__(parent, config, **kwargs)
        
        # AI state
        self.last_tokens_in = 0
        self.last_tokens_out = 0
        self.last_update_time = time.time()
        self.assistant_unavailable_logged = False  # Prevent warning spam
        
        logger.debug("AICorePanel initialized")

    

    def on_initialize(self) -> None:
        """Create panel widgets."""
        logger.info("Initializing AICorePanel UI")
        
        # Row 1: Model
        model_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        model_frame.pack(fill="x", padx=12, pady=6)
        
        model_label = tk.Label(
            model_frame,
            text="MODEL",
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_ACCENT,
            bg=self.bg_color,
        )
        model_label.pack(anchor="w")
        
        stat1 = StatDisplay(model_frame, "Active", "Loading...", color=COLOR_MUTED)
        stat1.pack(fill="x")
        self.widgets["model_name"] = stat1
        
        stat2 = StatDisplay(model_frame, "Provider", "Unknown", color=COLOR_MUTED)
        stat2.pack(fill="x")
        self.widgets["model_provider"] = stat2
        
        logger.debug("Model section created")
        
        # Separator
        sep1 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep1.pack(fill="x", padx=12, pady=6)
        
        # Row 2: Load
        load_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        load_frame.pack(fill="x", padx=12, pady=6)
        
        load_label = tk.Label(
            load_frame,
            text="LOAD",
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_ACCENT,
            bg=self.bg_color,
        )
        load_label.pack(anchor="w")
        
        stat3 = StatDisplay(load_frame, "Inference", "0%", color=COLOR_MUTED)
        stat3.pack(fill="x")
        self.widgets["load_percent"] = stat3
        
        stat4 = StatDisplay(load_frame, "Speed", "0 t/s", color=COLOR_MUTED)
        stat4.pack(fill="x")
        self.widgets["inference_speed"] = stat4
        
        load_bar = ProgressBar(
            load_frame,
            value=0.0,
            max_value=100.0,
            height=6,
            fill_color=COLOR_ACCENT,
        )
        load_bar.pack(fill="x", pady=(4, 0))
        self.widgets["load_bar"] = load_bar
        
        logger.debug("Load section created")
        
        # Separator
        sep2 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep2.pack(fill="x", padx=12, pady=6)
        
        # Row 3: Tokens
        token_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        token_frame.pack(fill="x", padx=12, pady=6)
        
        token_label = tk.Label(
            token_frame,
            text="TOKENS",
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_ACCENT,
            bg=self.bg_color,
        )
        token_label.pack(anchor="w")
        
        stat5 = StatDisplay(token_frame, "Input", "0", color=COLOR_MUTED)
        stat5.pack(fill="x")
        self.widgets["tokens_in"] = stat5
        
        stat6 = StatDisplay(token_frame, "Output", "0", color=COLOR_MUTED)
        stat6.pack(fill="x")
        self.widgets["tokens_out"] = stat6
        
        stat7 = StatDisplay(token_frame, "Queue", "0 pending", color=COLOR_MUTED)
        stat7.pack(fill="x")
        self.widgets["queue_length"] = stat7
        
        logger.debug("Token section created")
        
        # Separator
        sep3 = tk.Frame(self.content_frame, height=1, bg="#26324A")
        sep3.pack(fill="x", padx=12, pady=6)
        
        # Row 4: Status
        status_frame = tk.Frame(self.content_frame, bg=self.bg_color)
        status_frame.pack(fill="x", padx=12, pady=6)
        
        status_label = tk.Label(
            status_frame,
            text="STATUS",
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_ACCENT,
            bg=self.bg_color,
        )
        status_label.pack(anchor="w", pady=(0, 4))
        
        indicator = StatusIndicator(
            status_frame,
            text="READY",
            color=COLOR_SUCCESS,
        )
        indicator.pack(anchor="w")
        self.widgets["status_indicator"] = indicator
        
        logger.debug("Status section created")
        logger.info("AICorePanel UI created successfully")
    

    def on_refresh(self) -> None:
        """Update AI metrics."""
        logger.debug("Refreshing AICorePanel metrics")
        
        try:
            # Try to get assistant instance
            assistant = self._get_assistant()
            
            if assistant is None:
                # Only log once to avoid spam
                if not self.assistant_unavailable_logged:
                    logger.info("Assistant instance not available - showing offline mode")
                    self.assistant_unavailable_logged = True
                
                self.update_stat("model_name", "Offline", COLOR_WARNING)
                self.update_stat("model_provider", "—", COLOR_MUTED)
                self.update_stat("load_percent", "0%", COLOR_MUTED)
                self.update_stat("inference_speed", "— t/s", COLOR_MUTED)
                return
            
            # Reset unavailable flag when assistant comes back online
            if self.assistant_unavailable_logged:
                logger.info("Assistant instance is now available")
                self.assistant_unavailable_logged = False
            
            # Model name
            model_name = getattr(assistant, "model_name", "Unknown")
            logger.debug("Current model: %s", model_name)
            self.update_stat("model_name", model_name, COLOR_SUCCESS)
            
            # Provider
            provider = getattr(assistant, "provider", "Unknown")
            self.update_stat("model_provider", provider, COLOR_MUTED)
            
            # Load & speed
            load = self._calculate_load(assistant)
            speed = self._calculate_speed(assistant)
            
            logger.debug("AI Load: %.1f%%, Speed: %.1f t/s", load, speed)
            
            load_color = self._color_for_load(load)
            self.update_stat("load_percent", f"{load:.1f}%", load_color)
            self.update_stat("inference_speed", f"{speed:.1f} t/s", COLOR_MUTED)
            self.update_progress("load_bar", load)
            
            # Tokens
            try:
                history = getattr(assistant, "history", None)
                if history is not None:
                    tokens_in = getattr(history, "total_input_tokens", 0)
                    tokens_out = getattr(history, "total_output_tokens", 0)
                    
                    logger.debug("Tokens: in=%d, out=%d", tokens_in, tokens_out)
                    
                    self.update_stat("tokens_in", str(tokens_in))
                    self.update_stat("tokens_out", str(tokens_out))
                    
                    self.last_tokens_in = tokens_in
                    self.last_tokens_out = tokens_out
            except Exception as e:
                logger.warning("Could not read token counts: %s", e)
            
            # Queue
            queue_len = self._get_queue_length(assistant)
            self.update_stat("queue_length", f"{queue_len} pending")
            
            # Status
            is_healthy = load < LOAD_WARNING_THRESHOLD
            indicator = self.widgets.get("status_indicator")
            if indicator is not None:
                if is_healthy:
                    indicator.set_status("READY", COLOR_SUCCESS)
                else:
                    indicator.set_status("BUSY", COLOR_WARNING)
            
            logger.debug("AICorePanel refresh complete")
            
        except Exception as e:
            logger.error("AICorePanel refresh failed: %s", e)
            self.metrics.error_count += 1

    
    def on_cleanup(self) -> None:
        """Cleanup AI core panel."""
        logger.info("Cleaning up AICorePanel")
        logger.debug("AICorePanel cleanup complete")

    @staticmethod
    def _get_assistant() -> Optional[Any]:
        """
        Get the shared AssistantX assistant instance.

        The assistant is created at most once by this panel and then
        reused across refresh cycles. This prevents repeated AI provider
        initialization and unnecessary resource consumption.
        """
        try:
            # ------------------------------------------------------------
            # 1. Return the cached shared assistant if available.
            # ------------------------------------------------------------

            cached_assistant = getattr(
                AICorePanel,
                "_assistant_instance",
                None,
            )

            if cached_assistant is not None:
                return cached_assistant

            # ------------------------------------------------------------
            # 2. Try the command router.
            # ------------------------------------------------------------

            try:
                from core import command_router

                assistant = getattr(
                    command_router,
                    "_assistant",
                    None,
                )

                if assistant is not None:
                    AICorePanel._assistant_instance = assistant

                    logger.debug(
                        "Assistant retrieved from command_router"
                    )

                    return assistant

            except (
                ImportError,
                AttributeError,
            ):
                pass

            # ------------------------------------------------------------
            # 3. Create the default assistant only once.
            # ------------------------------------------------------------

            try:
                from core import (
                    create_default_assistant,
                    is_bootstrapped,
                )

                if is_bootstrapped():
                    assistant = create_default_assistant()

                    AICorePanel._assistant_instance = assistant

                    logger.info(
                        "Shared Assistant instance created "
                        "for AICorePanel"
                    )

                    return assistant

            except Exception as exc:
                logger.debug(
                    "Could not create assistant: %s",
                    exc,
                )

            # ------------------------------------------------------------
            # 4. Try the event bus.
            # ------------------------------------------------------------

            try:
                from core import event_bus

                assistant = getattr(
                    event_bus,
                    "_assistant",
                    None,
                )

                if assistant is not None:
                    AICorePanel._assistant_instance = assistant

                    logger.debug(
                        "Assistant retrieved from event_bus"
                    )

                    return assistant

            except (
                ImportError,
                AttributeError,
            ):
                pass

            logger.debug(
                "No assistant instance found in any context"
            )

            return None

        except Exception as exc:
            logger.debug(
                "Error getting assistant: %s",
                exc,
            )

            return None


        except Exception as e:
            logger.debug("Error getting assistant: %s", e)
            return None

    
    @staticmethod
    def _calculate_load(assistant: Any) -> float:
        """
        Calculate inference load percentage.
        
        Parameters
        ----------
        assistant : Any
            Assistant instance
        
        Returns
        -------
        float
            Load 0-100%
        """
        try:
            # Try to get from event bus singleton
            from core import event_bus
            
            if event_bus is None:
                return 0.0
            
            # Count pending events
            pending = len(getattr(event_bus, "_queue", []))
            
            # Simple heuristic: 0-50 events = 0-100% load
            load = min(100.0, (pending / 50.0) * 100)
            return load
            
        except Exception as e:
            logger.debug("Could not calculate load: %s", e)
            return 0.0
    
    @staticmethod
    def _calculate_speed(assistant: Any) -> float:
        """
        Calculate inference speed (tokens/sec).
        
        Parameters
        ----------
        assistant : Any
            Assistant instance
        
        Returns
        -------
        float
            Tokens per second
        """
        try:
            # Placeholder: would need timing data from assistant
            # For now, return 0
            return 0.0
        except Exception as e:
            logger.debug("Could not calculate speed: %s", e)
            return 0.0
    
    @staticmethod
    def _get_queue_length(assistant: Any) -> int:
        """
        Get pending request queue length.
        
        Parameters
        ----------
        assistant : Any
            Assistant instance
        
        Returns
        -------
        int
            Queue length
        """
        try:
            from core import event_bus
            if event_bus is None:
                return 0
            # Get pending events count
            pending = len(getattr(event_bus, "_queue", []))
            return pending
        except Exception as e:
            logger.debug("Could not get queue length: %s", e)
            return 0
    
    @staticmethod
    def _color_for_load(load: float) -> str:
        """Get color based on load percentage."""
        if load >= LOAD_ERROR_THRESHOLD:
            return COLOR_ERROR
        elif load >= LOAD_WARNING_THRESHOLD:
            return COLOR_WARNING
        else:
            return COLOR_SUCCESS

# ============================================================================
# EXPORTS
# ============================================================================

logger.info("AI core panel module loaded successfully")















__all__ = [
    "AICorePanel",
]
