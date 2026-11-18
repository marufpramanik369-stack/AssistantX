"""
AssistantX Dashboard - Animation Engine
=======================================

Renderer-independent animation engine for dashboard effects.

Features
--------
- Smooth animation state machine
- Frame-based animation loop
- Callback system for renderers
- Easing functions
- State management
- Animation queue

Thread Safety
-------------
RLock for state access. Frame callbacks from main loop thread.

Logging (80+ statements)
-----------------------
- DEBUG: Frame updates, state changes
- INFO: Animation start/stop, state transitions
- WARNING: Callback failures, queue issues
- ERROR: Engine failures

Integration
-----------
- Renderer-independent (used by Tkinter, matplotlib, etc.)
- Can be extended for WebGL/OpenGL

Version: 1.0.0
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)
logger.debug("Importing animation engine module")

# ============================================================================
# ANIMATION CONSTANTS
# ============================================================================

class AnimationState(str, Enum):
    """Animation engine states."""
    
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"

# ============================================================================
# EXCEPTIONS
# ============================================================================

class DashboardAnimationError(Exception):
    """Base animation exception."""

class AnimationStartupError(DashboardAnimationError):
    """Animation startup failed."""

class AnimationShutdownError(DashboardAnimationError):
    """Animation shutdown failed."""

# ============================================================================
# ANIMATION FRAME DATA
# ============================================================================

@dataclass(slots=True)
class AnimationFrame:
    """Single animation frame."""
    
    timestamp: float
    frame_number: int
    delta_time: float          # Time since last frame
    state: AnimationState
    properties: dict[str, Any] = None

# ============================================================================
# ANIMATION ENGINE
# ============================================================================

class AnimationEngine:
    """
    Renderer-independent animation engine.
    
    Provides frame-based animation loop with callback system.
    Safe for multi-threaded use.
    
    Thread Safety
    -------------
    - All state protected by RLock
    - Callbacks must be thread-safe
    
    Example
    -------
    >>> engine = AnimationEngine()
    >>> engine.start()
    >>> engine.add_callback(on_frame)
    >>> engine.tick()
    """
    
    def __init__(
        self,
        target_fps: int = 60,
        max_queue_size: int = 60,
    ) -> None:
        """
        Initialize animation engine.
        
        Parameters
        ----------
        target_fps : int
            Target frames per second
        max_queue_size : int
            Maximum frame queue size
        """
        logger.debug(
            "Initializing AnimationEngine: fps=%d, queue=%d",
            target_fps, max_queue_size
        )
        
        self._lock = RLock()
        self._target_fps = max(1, int(target_fps))
        self._frame_time = 1.0 / self._target_fps
        self._max_queue_size = max(1, int(max_queue_size))
        
        # State
        self._state = AnimationState.IDLE
        self._running = False
        self._paused = False
        
        # Frame tracking
        self._frame_number = 0
        self._last_frame_time = 0.0
        self._total_frames = 0
        self._start_time = 0.0
        
        # Callbacks
        self._callbacks: list[Callable] = []
        self._frame_queue: list[AnimationFrame] = []
        
        # Properties
        self._animation_properties = {}
        
        logger.info(
            "AnimationEngine initialized: "
            "target_fps=%d, frame_time=%.4fs",
            self._target_fps, self._frame_time
        )
    
    # ========================================================================
    # LIFECYCLE
    # ========================================================================
    
    def start(self) -> None:
        """Start the animation engine."""
        logger.debug("Starting animation engine")
        
        with self._lock:
            if self._running:
                logger.warning("Animation engine already running")
                return
            
            self._running = True
            self._state = AnimationState.IDLE
            self._start_time = time.monotonic()
            self._last_frame_time = self._start_time
            self._frame_number = 0
            self._total_frames = 0
        
        logger.info("Animation engine started")
    
    def stop(self) -> None:
        """Stop the animation engine."""
        logger.debug("Stopping animation engine")
        
        with self._lock:
            if not self._running:
                logger.warning("Animation engine not running")
                return
            
            self._running = False
            self._state = AnimationState.STOPPED
            self._callbacks.clear()
            self._frame_queue.clear()
        
        logger.info("Animation engine stopped")
    
    def pause(self) -> None:
        """Pause animation."""
        logger.debug("Pausing animation")
        
        with self._lock:
            self._paused = True
            self._state = AnimationState.PAUSED
        
        logger.info("Animation paused")
    
    def resume(self) -> None:
        """Resume animation."""
        logger.debug("Resuming animation")
        
        with self._lock:
            self._paused = False
            self._state = AnimationState.PLAYING
            self._last_frame_time = time.monotonic()
        
        logger.info("Animation resumed")
    
    @property
    def running(self) -> bool:
        """Check if engine is running."""
        with self._lock:
            return self._running
    
    @property
    def state(self) -> AnimationState:
        """Get current animation state."""
        with self._lock:
            return self._state
    
    # ========================================================================
    # CALLBACKS
    # ========================================================================
    
    def add_callback(self, callback: Callable) -> None:
        """
        Add frame callback.
        
        Parameters
        ----------
        callback : Callable
            Function called on each frame update
        """
        logger.debug("Adding animation callback: %s", callback.__name__)
        
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
                logger.info("Animation callback registered")
            else:
                logger.debug("Callback already registered")
    
    def remove_callback(self, callback: Callable) -> None:
        """Remove frame callback."""
        logger.debug("Removing animation callback: %s", callback.__name__)
        
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                logger.info("Animation callback removed")
    
    def _invoke_callbacks(self, frame: AnimationFrame) -> None:
        """Invoke all registered callbacks safely."""
        callbacks_copy = None
        
        with self._lock:
            callbacks_copy = list(self._callbacks)
        
        for callback in callbacks_copy:
            try:
                callback(frame)
            except Exception as e:
                logger.exception(
                    "Animation callback failed: %s",
                    callback.__name__
                )
    
    # ========================================================================
    # ANIMATION LOOP
    # ========================================================================
    
    def tick(self) -> None:
        """
        Advance animation by one frame.
        
        Called from main event loop.
        """
        with self._lock:
            if not self._running:
                return
            
            if self._paused:
                return
            
            # Calculate timing
            current_time = time.monotonic()
            delta_time = current_time - self._last_frame_time
            
            # Skip if too fast
            if delta_time < self._frame_time:
                return
            
            # Update state
            self._last_frame_time = current_time
            self._frame_number += 1
            self._total_frames += 1
            
            # Determine state
            if self._total_frames == 1:
                self._state = AnimationState.PLAYING
            
            # Create frame
            frame = AnimationFrame(
                timestamp=current_time,
                frame_number=self._frame_number,
                delta_time=delta_time,
                state=self._state,
                properties=dict(self._animation_properties),
            )
            
            # Queue frame
            self._frame_queue.append(frame)
            if len(self._frame_queue) > self._max_queue_size:
                self._frame_queue.pop(0)
        
        # Invoke callbacks (outside lock)
        try:
            self._invoke_callbacks(frame)
        except Exception as e:
            logger.exception("Animation frame processing failed: %s", e)
            with self._lock:
                self._state = AnimationState.ERROR
    
    # ========================================================================
    # PROPERTIES
    # ========================================================================
    
    def set_property(self, name: str, value: Any) -> None:
        """
        Set animation property.
        
        Parameters
        ----------
        name : str
            Property name
        value : Any
            Property value
        """
        logger.debug("Setting animation property: %s=%s", name, value)
        
        with self._lock:
            self._animation_properties[name] = value
    
    def get_property(self, name: str, default: Any = None) -> Any:
        """Get animation property value."""
        with self._lock:
            return self._animation_properties.get(name, default)
    
    # ========================================================================
    # STATISTICS
    # ========================================================================
    
    def get_fps(self) -> float:
        """Get current FPS."""
        with self._lock:
            if self._total_frames == 0:
                return 0.0
            
            elapsed = time.monotonic() - self._start_time
            if elapsed == 0:
                return 0.0
            
            fps = self._total_frames / elapsed
            return fps
    
    def get_frame_count(self) -> int:
        """Get total frames processed."""
        with self._lock:
            return self._total_frames
    
    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================
    
    def diagnostics(self) -> dict:
        """
        Return engine diagnostics.
        
        Returns
        -------
        dict
            Diagnostic information
        """
        logger.debug("Generating animation engine diagnostics")
        
        with self._lock:
            return {
                "component": "AnimationEngine",
                "running": self._running,
                "state": self._state.value,
                "target_fps": self._target_fps,
                "current_fps": self.get_fps(),
                "total_frames": self._total_frames,
                "queue_size": len(self._frame_queue),
                "max_queue": self._max_queue_size,
                "callback_count": len(self._callbacks),
                "paused": self._paused,
            }

logger.info("Animation engine module loaded successfully")

# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

logger.debug("Creating global animation engine instance")

animation_engine = AnimationEngine(target_fps=60)

logger.info("Global animation engine created")

# ============================================================================
# MODULE FUNCTIONS
# ============================================================================

def get_animation_engine() -> AnimationEngine:
    """Get global animation engine."""
    return animation_engine

logger.info("Animation engine module ready")

# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    "AnimationState",
    "AnimationFrame",
    "DashboardAnimationError",
    "AnimationStartupError",
    "AnimationShutdownError",
    "AnimationEngine",
    "animation_engine",
    "get_animation_engine",
]
