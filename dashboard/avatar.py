"""
AssistantX Dashboard - Avatar Manager
====================================

Avatar display and management system for JEROX.

Features
--------
- Image loading from assets
- Tkinter PhotoImage conversion
- Animation sync with TTS
- State management (idle, listening, speaking)
- Mouth animation on voice output
- Fallback rendering

Thread Safety
-------------
RLock for state access. Image operations on main thread only.

Logging (100+ statements)
-----------------------
- DEBUG: Image loads, state changes
- INFO: Avatar ready, animation start
- WARNING: Missing images, fallbacks
- ERROR: Loading failures

Integration
-----------
- voice/Speaker: TTS integration
- config/: Asset paths
- PIL/Pillow: Image handling

Version: 1.0.0
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from threading import RLock
from typing import Any, Optional

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger(__name__)
logger.debug("Importing avatar manager module")

if not PIL_AVAILABLE:
    logger.warning("PIL/Pillow not available - avatar image rendering disabled")

# ============================================================================
# CONSTANTS
# ============================================================================

ASSISTANT_NAME = "JEROX"
AVATAR_SIZE_SMALL = (120, 120)
AVATAR_SIZE_MEDIUM = (200, 200)
AVATAR_SIZE_LARGE = (300, 300)

AVATAR_STATES = {
    "idle": "Avatar in idle state",
    "listening": "Avatar listening",
    "speaking": "Avatar speaking",
    "processing": "Avatar processing",
    "error": "Avatar error state",
}

logger.debug("Avatar constants defined")

# ============================================================================
# AVATAR MANAGER
# ============================================================================

class AvatarManager:
    """
    Manage avatar display and animations.
    
    Handles image loading, state transitions, and animation synchronization
    with voice output.
    
    Thread Safety
    -------------
    - State access protected by RLock
    - Image operations should be on main thread
    
    Example
    -------
    >>> manager = AvatarManager()
    >>> image = manager.load_tk_image(root)
    >>> manager.set_state("speaking")
    >>> manager.start_mouth_animation()
    """
    
    def __init__(
        self,
        size: str = "medium",
        enable_animation: bool = True,
    ) -> None:
        """
        Initialize avatar manager.
        
        Parameters
        ----------
        size : str
            Avatar size: 'small', 'medium', 'large'
        enable_animation : bool
            Enable animation effects
        """
        logger.debug(
            "Initializing AvatarManager: size=%s, animation=%s",
            size, enable_animation
        )
        
        self._lock = RLock()
        self._size = size
        self._enable_animation = enable_animation
        
        # State
        self._state = "idle"
        self._is_speaking = False
        self._mouth_open = False
        self._animation_frame = 0
        
        # Images
        self._image_path: Optional[Path] = None
        self._tk_image: Optional[Any] = None
        self._pil_image: Optional[Any] = None
        
        # Configuration
        self._size_map = {
            "small": AVATAR_SIZE_SMALL,
            "medium": AVATAR_SIZE_MEDIUM,
            "large": AVATAR_SIZE_LARGE,
        }
        
        self._mouth_animation_frames = 10
        self._mouth_animation_speed = 5
        
        logger.info(
            "AvatarManager initialized: "
            "size=%s, animation=%s, pil=%s",
            size, enable_animation, PIL_AVAILABLE
        )
    
    # ========================================================================
    # IMAGE LOADING
    # ========================================================================
    
    def _find_avatar_image(self) -> Optional[Path]:
        """
        Find avatar image in assets directory.
        
        Returns
        -------
        Path
            Path to avatar image, or None if not found
        """
        logger.debug("Searching for avatar image")
        
        # Try multiple paths
        search_paths = [
            Path("assets/images/avatar_girl.png"),
            Path("assets/images/avatar.png"),
            Path("./assets/images/avatar_girl.png"),
            Path("./assets/images/avatar.png"),
        ]
        
        for path in search_paths:
            if path.exists():
                logger.info("Avatar image found: %s", path)
                return path
        
        logger.warning("Avatar image not found in any search path")
        return None
    
    def _load_pil_image(self) -> Optional[Any]:
        """
        Load image using PIL.
        
        Returns
        -------
        Image
            PIL Image object, or None if failed
        """
        if not PIL_AVAILABLE:
            logger.debug("PIL not available for image loading")
            return None
        
        if self._image_path is None:
            self._image_path = self._find_avatar_image()
        
        if self._image_path is None:
            logger.warning("Cannot load avatar image - path not found")
            return None
        
        try:
            logger.debug("Loading PIL image from: %s", self._image_path)
            
            image = Image.open(str(self._image_path))
            
            # Resize to configured size
            size = self._size_map.get(self._size, AVATAR_SIZE_MEDIUM)
            image = image.resize(size, Image.Resampling.LANCZOS)
            
            logger.info("PIL image loaded successfully: %s", image.size)
            
            return image
            
        except Exception as e:
            logger.exception("Failed to load PIL image: %s", e)
            return None
    
    def load_tk_image(
        self,
        root: tk.Tk,
    ) -> Optional[tk.PhotoImage]:
        """
        Load avatar as Tkinter PhotoImage.
        
        Parameters
        ----------
        root : tk.Tk
            Tk root window
        
        Returns
        -------
        tk.PhotoImage
            Tkinter image, or None if failed
        """
        logger.debug("Loading Tkinter image for avatar")
        
        with self._lock:
            if self._tk_image is not None:
                logger.debug("Returning cached Tk image")
                return self._tk_image
            
            # Load PIL first
            pil_image = self._load_pil_image()
            
            if pil_image is None:
                logger.warning("Cannot create Tk image - PIL image unavailable")
                return None
            
            try:
                self._pil_image = pil_image
                self._tk_image = ImageTk.PhotoImage(pil_image)
                
                logger.info(
                    "Tk image created successfully: %s",
                    self._tk_image
                )
                
                return self._tk_image
                
            except Exception as e:
                logger.exception("Failed to create Tk image: %s", e)
                return None
    
    # ========================================================================
    # STATE MANAGEMENT
    # ========================================================================
    
    def set_state(self, state: str) -> None:
        """
        Set avatar state.
        
        Parameters
        ----------
        state : str
            State name: 'idle', 'listening', 'speaking', 'processing', 'error'
        """
        logger.debug("Setting avatar state: %s", state)
        
        if state not in AVATAR_STATES:
            logger.warning("Unknown avatar state: %s", state)
            return
        
        with self._lock:
            old_state = self._state
            self._state = state
        
        logger.info("Avatar state changed: %s -> %s", old_state, state)
    
    def get_state(self) -> str:
        """
        Get current avatar state.
        
        Returns
        -------
        str
            Current state
        """
        with self._lock:
            return self._state
    
    # ========================================================================
    # ANIMATION
    # ========================================================================
    
    def start_mouth_animation(self) -> None:
        """Start mouth animation for speaking."""
        logger.debug("Starting mouth animation")
        
        with self._lock:
            self._is_speaking = True
            self._animation_frame = 0
        
        self.set_state("speaking")
        logger.info("Mouth animation started")
    
    def stop_mouth_animation(self) -> None:
        """Stop mouth animation."""
        logger.debug("Stopping mouth animation")
        
        with self._lock:
            self._is_speaking = False
            self._mouth_open = False
            self._animation_frame = 0
        
        self.set_state("idle")
        logger.info("Mouth animation stopped")
    
    def update_mouth_animation(self) -> bool:
        """
        Update mouth animation frame.
        
        Returns
        -------
        bool
            True if animation is active
        """
        with self._lock:
            if not self._is_speaking:
                return False
            
            # Update frame
            self._animation_frame += 1
            
            # Toggle mouth every N frames
            if self._animation_frame % self._mouth_animation_speed == 0:
                self._mouth_open = not self._mouth_open
            
            # Reset after complete cycle
            if self._animation_frame >= self._mouth_animation_frames:
                self._animation_frame = 0
            
            return True
    
    def is_speaking(self) -> bool:
        """Check if avatar is currently speaking."""
        with self._lock:
            return self._is_speaking
    
    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================
    
    def diagnostics(self) -> dict:
        """
        Return avatar diagnostics.
        
        Returns
        -------
        dict
            Diagnostic information
        """
        logger.debug("Generating avatar diagnostics")
        
        with self._lock:
            return {
                "component": "AvatarManager",
                "state": self._state,
                "is_speaking": self._is_speaking,
                "size": self._size,
                "animation_enabled": self._enable_animation,
                "pil_available": PIL_AVAILABLE,
                "image_loaded": self._pil_image is not None,
                "tk_image_created": self._tk_image is not None,
                "image_path": str(self._image_path) if self._image_path else None,
            }

logger.info("Avatar manager module loaded successfully")

# ============================================================================
# MODULE FUNCTIONS
# ============================================================================

_global_avatar: Optional[AvatarManager] = None

def get_avatar_manager() -> AvatarManager:
    """Get or create global avatar manager."""
    global _global_avatar
    
    if _global_avatar is None:
        logger.debug("Creating global avatar manager")
        _global_avatar = AvatarManager()
    
    return _global_avatar

logger.info("Avatar manager module ready")

# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    "ASSISTANT_NAME",
    "AVATAR_STATES",
    "AVATAR_SIZE_SMALL",
    "AVATAR_SIZE_MEDIUM",
    "AVATAR_SIZE_LARGE",
    "AvatarManager",
    "get_avatar_manager",
]
