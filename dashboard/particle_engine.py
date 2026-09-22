"""
dashboard.particle_engine
=========================

Professional particle engine for AssistantX dashboard UI.

Features
--------
- Tkinter Canvas based
- Floating particles
- Smooth animation
- Mouse attraction / repulsion
- Optional particle connections
- Particle opacity simulation through layered circles
- Configurable particle count
- FPS limiting
- Reduced-motion mode
- Pause / resume
- Start / stop / restart
- Runtime statistics
- Diagnostics
- Safe widget destruction handling
- No external dependency

Typical usage
-------------

    from dashboard.particle_engine import (
        ParticleEngine,
        ParticleEngineConfig,
    )

    config = ParticleEngineConfig(
        particle_count=35,
        connection_enabled=True,
    )

    engine = ParticleEngine(
        canvas,
        config=config,
    )

    engine.start()
"""

from __future__ import annotations

import contextlib
import math
import random
import time
import tkinter as tk
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Any

# ============================================================================
# Exceptions
# ============================================================================


class ParticleEngineError(Exception):
    """Base exception for particle engine errors."""


class ParticleEngineConfigurationError(ParticleEngineError):
    """Raised when particle configuration is invalid."""


class ParticleEngineStateError(ParticleEngineError):
    """Raised when an operation is invalid for the current state."""


# ============================================================================
# Enums
# ============================================================================


class ParticleEngineState(str, Enum):
    """Runtime state of the particle engine."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    DESTROYED = "destroyed"


class MouseInteraction(str, Enum):
    """Mouse interaction mode."""

    NONE = "none"
    ATTRACT = "attract"
    REPEL = "repel"


# ============================================================================
# Configuration
# ============================================================================


@dataclass(frozen=True)
class ParticleEngineConfig:
    """Particle engine configuration."""

    particle_count: int = 35

    min_radius: float = 1.0
    max_radius: float = 2.5

    min_speed: float = 0.15
    max_speed: float = 0.55

    particle_color: str = "#5B8CFF"
    secondary_particle_color: str = "#7C9EFF"

    background_color: str = "#111111"

    connection_enabled: bool = True
    connection_distance: float = 130.0
    connection_alpha_steps: int = 4

    mouse_interaction: MouseInteraction = MouseInteraction.ATTRACT
    mouse_radius: float = 160.0
    mouse_force: float = 0.025

    edge_padding: float = 10.0

    fps: int = 60

    reduced_motion: bool = False

    random_seed: int | None = None

    auto_resize: bool = True

    def __post_init__(self) -> None:
        if self.particle_count < 0:
            raise ParticleEngineConfigurationError(
                "particle_count cannot be negative."
            )

        if self.min_radius <= 0:
            raise ParticleEngineConfigurationError(
                "min_radius must be greater than zero."
            )

        if self.max_radius < self.min_radius:
            raise ParticleEngineConfigurationError(
                "max_radius cannot be smaller than min_radius."
            )

        if self.min_speed < 0:
            raise ParticleEngineConfigurationError(
                "min_speed cannot be negative."
            )

        if self.max_speed < self.min_speed:
            raise ParticleEngineConfigurationError(
                "max_speed cannot be smaller than min_speed."
            )

        if self.connection_distance < 0:
            raise ParticleEngineConfigurationError(
                "connection_distance cannot be negative."
            )

        if self.mouse_radius < 0:
            raise ParticleEngineConfigurationError(
                "mouse_radius cannot be negative."
            )

        if self.fps <= 0:
            raise ParticleEngineConfigurationError(
                "fps must be greater than zero."
            )

        if self.connection_alpha_steps < 1:
            raise ParticleEngineConfigurationError(
                "connection_alpha_steps must be at least 1."
            )


# ============================================================================
# Particle Model
# ============================================================================


@dataclass
class Particle:
    """Internal particle representation."""

    x: float
    y: float

    vx: float
    vy: float

    radius: float

    color: str

    phase: float = 0.0
    pulse_speed: float = 0.01

    canvas_id: int | None = None
    glow_ids: tuple[int, ...] = ()

    active: bool = True


@dataclass
class ParticleStats:
    """Runtime statistics."""

    frames: int = 0
    particles_created: int = 0
    particles_removed: int = 0
    mouse_events: int = 0
    connection_lines: int = 0

    start_count: int = 0
    stop_count: int = 0
    pause_count: int = 0

    total_frame_time: float = 0.0

    @property
    def average_fps(self) -> float:
        if self.total_frame_time <= 0:
            return 0.0

        return self.frames / self.total_frame_time


# ============================================================================
# Color Utilities
# ============================================================================


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to RGB."""

    value = value.strip().lstrip("#")

    if len(value) != 6:
        raise ValueError(
            f"Invalid hex color: {value!r}"
        )

    try:
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid hex color: {value!r}"
        ) from exc


def rgb_to_hex(
    rgb: tuple[int, int, int],
) -> str:
    """Convert RGB to #RRGGBB."""

    r, g, b = (
        max(0, min(255, int(value)))
        for value in rgb
    )

    return f"#{r:02X}{g:02X}{b:02X}"


def blend_colors(
    first: str,
    second: str,
    ratio: float,
) -> str:
    """Blend two colors."""

    ratio = max(0.0, min(1.0, ratio))

    a = hex_to_rgb(first)
    b = hex_to_rgb(second)

    result = tuple(
        round(
            x + (y - x) * ratio
        )
        for x, y in zip(a, b, strict=True)
    )

    return rgb_to_hex(result)


def darken_color(
    color: str,
    amount: float,
) -> str:
    """Darken a color."""

    amount = max(0.0, min(1.0, amount))

    rgb = hex_to_rgb(color)

    return rgb_to_hex(
        tuple(
            round(channel * (1.0 - amount))
            for channel in rgb
        )
    )


# ============================================================================
# Particle Engine
# ============================================================================


class ParticleEngine:
    """
    Professional particle engine for a Tkinter Canvas.

    Parameters
    ----------
    canvas:
        Tkinter Canvas used as rendering surface.

    config:
        ParticleEngineConfig instance.
    """

    def __init__(
        self,
        canvas: tk.Canvas,
        config: ParticleEngineConfig | None = None,
    ) -> None:
        if canvas is None:
            raise ParticleEngineConfigurationError(
                "canvas cannot be None."
            )

        self._canvas = canvas
        self._config = config or ParticleEngineConfig()

        self._lock = RLock()

        self._state = ParticleEngineState.STOPPED
        self._particles: list[Particle] = []

        self._after_id: str | None = None

        self._width = 1
        self._height = 1

        self._mouse_x: float | None = None
        self._mouse_y: float | None = None

        self._last_frame_time: float | None = None

        self._stats = ParticleStats()

        self._random = random.Random(
            self._config.random_seed
        )

        self._bindings_created = False

        self._initialize_canvas()
        self._bind_events()
        self._create_particles()

    # ----------------------------------------------------------------------
    # Initialization
    # ----------------------------------------------------------------------

    def _initialize_canvas(self) -> None:
        try:
            self._canvas.configure(
                bg=self._config.background_color,
                highlightthickness=0,
                bd=0,
            )
        except tk.TclError as exc:
            raise ParticleEngineConfigurationError(
                "Invalid Tkinter Canvas."
            ) from exc

        self._update_dimensions()

    def _bind_events(self) -> None:
        if self._bindings_created:
            return

        try:
            self._canvas.bind(
                "<Motion>",
                self._on_mouse_motion,
                add="+",
            )

            self._canvas.bind(
                "<Leave>",
                self._on_mouse_leave,
                add="+",
            )

            if self._config.auto_resize:
                self._canvas.bind(
                    "<Configure>",
                    self._on_configure,
                    add="+",
                )

            self._bindings_created = True

        except tk.TclError:
            pass

    # ----------------------------------------------------------------------
    # Dimensions
    # ----------------------------------------------------------------------

    def _update_dimensions(self) -> None:
        try:
            width = self._canvas.winfo_width()
            height = self._canvas.winfo_height()

            self._width = max(
                1,
                width,
            )

            self._height = max(
                1,
                height,
            )
        except tk.TclError:
            self._width = 1
            self._height = 1

    def _on_configure(
        self,
        _event: tk.Event,
    ) -> None:
        if self._state == ParticleEngineState.DESTROYED:
            return

        self._update_dimensions()

    # ----------------------------------------------------------------------
    # Particle Creation
    # ----------------------------------------------------------------------

    def _create_particles(self) -> None:
        with self._lock:
            self._delete_particles()

            for _ in range(
                self._config.particle_count
            ):
                particle = self._new_particle()

                self._particles.append(
                    particle
                )

                self._stats.particles_created += 1

    def _new_particle(
        self,
        x: float | None = None,
        y: float | None = None,
    ) -> Particle:
        cfg = self._config

        padding = cfg.edge_padding

        if x is None:
            x = self._random.uniform(
                padding,
                max(
                    padding,
                    self._width - padding,
                ),
            )

        if y is None:
            y = self._random.uniform(
                padding,
                max(
                    padding,
                    self._height - padding,
                ),
            )

        angle = self._random.uniform(
            0,
            math.tau,
        )

        speed = self._random.uniform(
            cfg.min_speed,
            cfg.max_speed,
        )

        radius = self._random.uniform(
            cfg.min_radius,
            cfg.max_radius,
        )

        color = (
            cfg.particle_color
            if self._random.random() < 0.7
            else cfg.secondary_particle_color
        )

        return Particle(
            x=x,
            y=y,
            vx=math.cos(angle) * speed,
            vy=math.sin(angle) * speed,
            radius=radius,
            color=color,
            phase=self._random.uniform(
                0,
                math.tau,
            ),
            pulse_speed=self._random.uniform(
                0.005,
                0.02,
            ),
        )

    # ----------------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------------

    def _render_particle(
        self,
        particle: Particle,
    ) -> None:
        if not particle.active:
            return

        try:
            # Main particle.
            if particle.canvas_id is None:
                particle.canvas_id = self._canvas.create_oval(
                    0,
                    0,
                    0,
                    0,
                    fill=particle.color,
                    outline="",
                )

            pulse = (
                math.sin(
                    particle.phase
                ) + 1
            ) * 0.5

            radius = particle.radius * (
                0.85 + pulse * 0.25
            )

            self._canvas.coords(
                particle.canvas_id,
                particle.x - radius,
                particle.y - radius,
                particle.x + radius,
                particle.y + radius,
            )

            # Subtle glow layers.
            if not particle.glow_ids:
                glow_colors = (
                    darken_color(
                        particle.color,
                        0.25,
                    ),
                    darken_color(
                        particle.color,
                        0.45,
                    ),
                )

                ids = []

                for color in glow_colors:
                    item_id = self._canvas.create_oval(
                        0,
                        0,
                        0,
                        0,
                        fill=color,
                        outline="",
                    )

                    ids.append(item_id)

                particle.glow_ids = tuple(ids)

            glow_sizes = (
                radius * 2.5,
                radius * 4.0,
            )

            for item_id, size in zip(
                particle.glow_ids,
                glow_sizes,
                strict=True,
            ):
                half = size / 2

                self._canvas.coords(
                    item_id,
                    particle.x - half,
                    particle.y - half,
                    particle.x + half,
                    particle.y + half,
                )

            # Keep glow behind main particle.
            for item_id in particle.glow_ids:
                self._canvas.tag_lower(
                    item_id
                )

            self._canvas.tag_raise(
                particle.canvas_id
            )

        except tk.TclError:
            particle.active = False

    # ----------------------------------------------------------------------
    # Connections
    # ----------------------------------------------------------------------

    def _render_connections(self) -> None:
        if not self._config.connection_enabled:
            return

        try:
            # Remove old connection layer.
            self._canvas.delete(
                "particle_connection"
            )

            distance_limit = (
                self._config.connection_distance
            )

            line_count = 0

            particles = self._particles

            for index, first in enumerate(
                particles
            ):
                if not first.active:
                    continue

                for second in particles[
                    index + 1:
                ]:
                    if not second.active:
                        continue

                    dx = second.x - first.x
                    dy = second.y - first.y

                    distance = math.sqrt(
                        dx * dx + dy * dy
                    )

                    if distance > distance_limit:
                        continue

                    strength = (
                        1.0
                        - distance
                        / distance_limit
                    )

                    width = max(
                        0.3,
                        strength * 1.2,
                    )

                    color = blend_colors(
                        first.color,
                        second.color,
                        0.5,
                    )

                    line_id = self._canvas.create_line(
                        first.x,
                        first.y,
                        second.x,
                        second.y,
                        fill=color,
                        width=width,
                        tags="particle_connection",
                    )

                    self._canvas.tag_lower(
                        line_id
                    )

                    line_count += 1

            self._stats.connection_lines = (
                line_count
            )

        except tk.TclError:
            pass

    # ----------------------------------------------------------------------
    # Physics
    # ----------------------------------------------------------------------

    def _update_particles(
        self,
        delta_time: float,
    ) -> None:
        cfg = self._config

        # Normalize delta to avoid huge jumps.
        delta = min(
            max(delta_time, 0.0),
            0.05,
        )

        for particle in self._particles:
            if not particle.active:
                continue

            particle.phase += (
                particle.pulse_speed
                * delta
                * 60
            )

            if not cfg.reduced_motion:
                particle.x += (
                    particle.vx
                    * delta
                    * 60
                )

                particle.y += (
                    particle.vy
                    * delta
                    * 60
                )

                self._apply_mouse_force(
                    particle,
                    delta,
                )

                self._apply_edges(
                    particle
                )

    def _apply_mouse_force(
        self,
        particle: Particle,
        delta_time: float,
    ) -> None:
        if (
            self._config.mouse_interaction
            == MouseInteraction.NONE
        ):
            return

        if (
            self._mouse_x is None
            or self._mouse_y is None
        ):
            return

        dx = (
            self._mouse_x
            - particle.x
        )

        dy = (
            self._mouse_y
            - particle.y
        )

        distance_sq = (
            dx * dx
            + dy * dy
        )

        radius = self._config.mouse_radius

        if distance_sq <= 0:
            return

        if distance_sq > radius * radius:
            return

        distance = math.sqrt(
            distance_sq
        )

        if distance <= 0:
            return

        strength = (
            1.0
            - distance / radius
        )

        force = (
            self._config.mouse_force
            * strength
            * delta_time
            * 60
        )

        direction = 1.0

        if (
            self._config.mouse_interaction
            == MouseInteraction.REPEL
        ):
            direction = -1.0

        particle.vx += (
            dx / distance
            * force
            * direction
        )

        particle.vy += (
            dy / distance
            * force
            * direction
        )

        # Keep velocity bounded.
        speed = math.sqrt(
            particle.vx * particle.vx
            + particle.vy * particle.vy
        )

        max_speed = (
            self._config.max_speed * 2.0
        )

        if speed > max_speed:
            particle.vx = (
                particle.vx
                / speed
                * max_speed
            )

            particle.vy = (
                particle.vy
                / speed
                * max_speed
            )

    def _apply_edges(
        self,
        particle: Particle,
    ) -> None:
        padding = self._config.edge_padding

        if particle.x < padding:
            particle.x = padding
            particle.vx = abs(
                particle.vx
            )

        elif particle.x > self._width - padding:
            particle.x = (
                self._width - padding
            )
            particle.vx = -abs(
                particle.vx
            )

        if particle.y < padding:
            particle.y = padding
            particle.vy = abs(
                particle.vy
            )

        elif particle.y > self._height - padding:
            particle.y = (
                self._height - padding
            )
            particle.vy = -abs(
                particle.vy
            )

    # ----------------------------------------------------------------------
    # Mouse
    # ----------------------------------------------------------------------

    def _on_mouse_motion(
        self,
        event: tk.Event,
    ) -> None:
        if self._state == ParticleEngineState.DESTROYED:
            return

        self._mouse_x = float(
            event.x
        )

        self._mouse_y = float(
            event.y
        )

        with self._lock:
            self._stats.mouse_events += 1

    def _on_mouse_leave(
        self,
        _event: tk.Event,
    ) -> None:
        self._mouse_x = None
        self._mouse_y = None

    # ----------------------------------------------------------------------
    # Animation Loop
    # ----------------------------------------------------------------------

    def _schedule_next_frame(self) -> None:
        if self._state != ParticleEngineState.RUNNING:
            return

        delay = max(
            1,
            round(
                1000
                / self._config.fps
            ),
        )

        try:
            self._after_id = self._canvas.after(
                delay,
                self._frame,
            )
        except tk.TclError:
            self._state = ParticleEngineState.DESTROYED

    def _frame(self) -> None:
        if self._state != ParticleEngineState.RUNNING:
            return

        started = time.perf_counter()

        try:
            now = time.perf_counter()

            if self._last_frame_time is None:
                delta = 1.0 / self._config.fps
            else:
                delta = (
                    now
                    - self._last_frame_time
                )

            self._last_frame_time = now

            self._update_dimensions()
            self._update_particles(delta)

            for particle in self._particles:
                self._render_particle(
                    particle
                )

            self._render_connections()

            elapsed = (
                time.perf_counter()
                - started
            )

            with self._lock:
                self._stats.frames += 1
                self._stats.total_frame_time += (
                    elapsed
                )

            self._schedule_next_frame()

        except tk.TclError:
            self.stop()

    # ----------------------------------------------------------------------
    # Public Lifecycle
    # ----------------------------------------------------------------------

    def start(self) -> None:
        """Start particle animation."""

        if self._state == ParticleEngineState.DESTROYED:
            raise ParticleEngineStateError(
                "Cannot start a destroyed ParticleEngine."
            )

        if self._state == ParticleEngineState.RUNNING:
            return

        self._state = ParticleEngineState.RUNNING

        self._last_frame_time = (
            time.perf_counter()
        )

        with self._lock:
            self._stats.start_count += 1

        self._schedule_next_frame()

    def stop(self) -> None:
        """Stop particle animation."""

        if self._state == ParticleEngineState.DESTROYED:
            return

        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._canvas.after_cancel(
                    self._after_id
                )

            self._after_id = None

        self._state = ParticleEngineState.STOPPED

        with self._lock:
            self._stats.stop_count += 1

    def pause(self) -> None:
        """Pause animation."""

        if self._state != ParticleEngineState.RUNNING:
            return

        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self._canvas.after_cancel(
                    self._after_id
                )

            self._after_id = None

        self._state = ParticleEngineState.PAUSED

        with self._lock:
            self._stats.pause_count += 1

    def resume(self) -> None:
        """Resume paused animation."""

        if self._state != ParticleEngineState.PAUSED:
            return

        self._state = ParticleEngineState.RUNNING

        self._last_frame_time = (
            time.perf_counter()
        )

        self._schedule_next_frame()

    def restart(self) -> None:
        """Restart particle engine."""

        if self._state == ParticleEngineState.DESTROYED:
            raise ParticleEngineStateError(
                "Cannot restart a destroyed engine."
            )

        self.stop()
        self.reset()
        self.start()

    # ----------------------------------------------------------------------
    # Particle Management
    # ----------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all particles."""

        if self._state == ParticleEngineState.DESTROYED:
            return

        self._create_particles()

        for particle in self._particles:
            self._render_particle(
                particle
            )

    def add_particle(
        self,
        x: float | None = None,
        y: float | None = None,
    ) -> Particle:
        """Add one particle."""

        if self._state == ParticleEngineState.DESTROYED:
            raise ParticleEngineStateError(
                "Cannot add particles to destroyed engine."
            )

        particle = self._new_particle(
            x=x,
            y=y,
        )

        with self._lock:
            self._particles.append(
                particle
            )
            self._stats.particles_created += 1

        self._render_particle(
            particle
        )

        return particle

    def remove_particle(
        self,
        particle: Particle,
    ) -> bool:
        """Remove a specific particle."""

        with self._lock:
            if particle not in self._particles:
                return False

            self._delete_particle(
                particle
            )

            self._particles.remove(
                particle
            )

            self._stats.particles_removed += 1

        return True

    def _delete_particle(
        self,
        particle: Particle,
    ) -> None:
        try:
            if particle.canvas_id is not None:
                self._canvas.delete(
                    particle.canvas_id
                )

            for item_id in particle.glow_ids:
                self._canvas.delete(
                    item_id
                )

        except tk.TclError:
            pass

        particle.canvas_id = None
        particle.glow_ids = ()
        particle.active = False

    def _delete_particles(self) -> None:
        for particle in self._particles:
            self._delete_particle(
                particle
            )

        self._particles.clear()

        with contextlib.suppress(tk.TclError):
            self._canvas.delete(
                "particle_connection"
            )

    # ----------------------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------------------

    @property
    def config(self) -> ParticleEngineConfig:
        """Return current configuration."""

        return self._config

    @property
    def state(self) -> ParticleEngineState:
        """Return current engine state."""

        return self._state

    @property
    def particles(self) -> tuple[Particle, ...]:
        """Return immutable particle snapshot."""

        with self._lock:
            return tuple(
                self._particles
            )

    def set_reduced_motion(
        self,
        enabled: bool,
    ) -> None:
        """Enable or disable reduced motion."""

        cfg = self._config

        self._config = ParticleEngineConfig(
            **{
                **cfg.__dict__,
                "reduced_motion": bool(
                    enabled
                ),
            }
        )

    def set_mouse_interaction(
        self,
        mode: MouseInteraction | str,
    ) -> None:
        """Change mouse interaction mode."""

        if not isinstance(
            mode,
            MouseInteraction,
        ):
            try:
                mode = MouseInteraction(
                    str(mode).lower()
                )
            except ValueError as exc:
                raise ValueError(
                    f"Invalid mouse interaction: {mode}"
                ) from exc

        cfg = self._config

        self._config = ParticleEngineConfig(
            **{
                **cfg.__dict__,
                "mouse_interaction": mode,
            }
        )

    def set_particle_count(
        self,
        count: int,
    ) -> None:
        """Change particle count."""

        if count < 0:
            raise ValueError(
                "count cannot be negative."
            )

        cfg = self._config

        self._config = ParticleEngineConfig(
            **{
                **cfg.__dict__,
                "particle_count": count,
            }
        )

        current = len(
            self._particles
        )

        if count > current:
            for _ in range(count - current):
                self.add_particle()

        elif count < current:
            for particle in self._particles[
                count:
            ]:
                self._delete_particle(
                    particle
                )

            del self._particles[count:]

    # ----------------------------------------------------------------------
    # Visibility
    # ----------------------------------------------------------------------

    def show(self) -> None:
        """Show particles."""

        with contextlib.suppress(tk.TclError):
            self._canvas.itemconfigure(
                "all",
                state="normal",
            )

    def hide(self) -> None:
        """Hide particles."""

        with contextlib.suppress(tk.TclError):
            self._canvas.itemconfigure(
                "all",
                state="hidden",
            )

    # ----------------------------------------------------------------------
    # Statistics
    # ----------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return runtime statistics."""

        with self._lock:
            frames = self._stats.frames
            total_time = (
                self._stats.total_frame_time
            )

            return {
                "state": self._state.value,
                "frames": frames,
                "particles": len(
                    self._particles
                ),
                "particles_created": (
                    self._stats.particles_created
                ),
                "particles_removed": (
                    self._stats.particles_removed
                ),
                "mouse_events": (
                    self._stats.mouse_events
                ),
                "connection_lines": (
                    self._stats.connection_lines
                ),
                "start_count": (
                    self._stats.start_count
                ),
                "stop_count": (
                    self._stats.stop_count
                ),
                "pause_count": (
                    self._stats.pause_count
                ),
                "average_frame_ms": (
                    round(
                        (
                            total_time
                            / frames
                            * 1000
                        )
                        if frames
                        else 0.0,
                        3,
                    )
                ),
                "average_fps": round(
                    self._stats.average_fps,
                    2,
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return complete diagnostics."""

        return {
            "component": "ParticleEngine",
            "state": self._state.value,
            "destroyed": self._state
            == ParticleEngineState.DESTROYED,
            "canvas_size": {
                "width": self._width,
                "height": self._height,
            },
            "particle_count": len(
                self._particles
            ),
            "target_particle_count": (
                self._config.particle_count
            ),
            "fps_limit": self._config.fps,
            "connection_enabled": (
                self._config.connection_enabled
            ),
            "mouse_interaction": (
                self._config.mouse_interaction.value
            ),
            "reduced_motion": (
                self._config.reduced_motion
            ),
            "stats": self.stats(),
        }

    # ----------------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------------

    def shutdown(self) -> None:
        """Completely shutdown the engine."""

        if self._state == ParticleEngineState.DESTROYED:
            return

        self.stop()

        with self._lock:
            self._delete_particles()

        self._mouse_x = None
        self._mouse_y = None

        self._state = ParticleEngineState.DESTROYED


# ============================================================================
# Factory
# ============================================================================


def create_particle_engine(
    canvas: tk.Canvas,
    **kwargs: Any,
) -> ParticleEngine:
    """
    Convenience factory.

    Example
    -------
        engine = create_particle_engine(
            canvas,
            particle_count=40,
        )
    """

    config_keys = {
        "particle_count",
        "min_radius",
        "max_radius",
        "min_speed",
        "max_speed",
        "particle_color",
        "secondary_particle_color",
        "background_color",
        "connection_enabled",
        "connection_distance",
        "connection_alpha_steps",
        "mouse_interaction",
        "mouse_radius",
        "mouse_force",
        "edge_padding",
        "fps",
        "reduced_motion",
        "random_seed",
        "auto_resize",
    }

    config_data = {
        key: value
        for key, value in kwargs.items()
        if key in config_keys
    }

    config = ParticleEngineConfig(
        **config_data
    )

    return ParticleEngine(
        canvas,
        config=config,
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "MouseInteraction",
    "Particle",
    "ParticleEngine",
    "ParticleEngineConfig",
    "ParticleEngineConfigurationError",
    "ParticleEngineError",
    "ParticleEngineState",
    "ParticleEngineStateError",
    "ParticleStats",
    "blend_colors",
    "create_particle_engine",
    "darken_color",
    "hex_to_rgb",
    "rgb_to_hex",
]
