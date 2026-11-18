"""
AssistantX Dashboard - System Monitor
=====================================

Real-time system performance monitoring for the AssistantX dashboard.

Features
--------
- CPU usage monitoring
- Memory/RAM usage
- Disk usage
- Network bandwidth
- Temperature when available
- Process count
- History tracking
- Background monitoring
- Threshold alerts
- Thread-safe lifecycle
- Dashboard integration

Thread Safety
-------------
All mutable state is protected by RLock.

Dashboard Lifecycle
-------------------
The monitor supports:

    start()
    stop()
    _start_monitoring()
    _stop_monitoring()

The private lifecycle methods are kept for compatibility with
dashboard_core.py.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from threading import RLock
from typing import Optional


# ============================================================================
# OPTIONAL DEPENDENCY
# ============================================================================

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    PSUTIL_AVAILABLE = False


logger = logging.getLogger(__name__)

if not PSUTIL_AVAILABLE:
    logger.warning(
        "psutil not available - system monitoring disabled"
    )


# ============================================================================
# DATA STRUCTURES
# ============================================================================


@dataclass(slots=True)
class SystemSnapshot:
    """Snapshot of system metrics at a point in time."""

    timestamp: float
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_available: Optional[int] = None
    disk_percent: Optional[float] = None
    network_upload_bytes: Optional[float] = None
    network_download_bytes: Optional[float] = None
    temperature_celsius: Optional[float] = None
    gpu_percent: Optional[float] = None
    process_count: Optional[int] = None

    def __str__(self) -> str:
        """Return a readable snapshot summary."""

        cpu = (
            f"{self.cpu_percent:.1f}%"
            if self.cpu_percent is not None
            else "N/A"
        )

        memory = (
            f"{self.memory_percent:.1f}%"
            if self.memory_percent is not None
            else "N/A"
        )

        disk = (
            f"{self.disk_percent:.1f}%"
            if self.disk_percent is not None
            else "N/A"
        )

        return (
            "SystemSnapshot("
            f"cpu={cpu}, "
            f"mem={memory}, "
            f"disk={disk}"
            ")"
        )


# ============================================================================
# SYSTEM MONITOR
# ============================================================================


class SystemMonitor:
    """
    Real-time system performance monitor.

    Supports both manual snapshots and background monitoring.

    Manual:
        monitor.snapshot()

    Background:
        monitor.start()
        monitor.stop()

    Compatibility:
        _start_monitoring()
        _stop_monitoring()

    Thread Safety
    -------------
    All mutable state is protected by RLock.
    """

    def __init__(
        self,
        history_size: int = 60,
        update_interval: float = 1.0,
    ) -> None:
        """Initialize the system monitor."""

        logger.debug(
            "Initializing SystemMonitor: "
            "history_size=%d, update_interval=%.2f",
            history_size,
            update_interval,
        )

        self._lock = RLock()

        self._history_size = max(1, int(history_size))
        self._update_interval = max(
            0.1,
            float(update_interval),
        )

        self._last_update = 0.0
        self._last_network_io = None
        self._snapshots: list[SystemSnapshot] = []

        # Thresholds
        self._cpu_alert_threshold = 90.0
        self._memory_alert_threshold = 85.0
        self._disk_alert_threshold = 90.0

        # Background monitoring lifecycle
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        logger.info(
            "SystemMonitor initialized: "
            "history=%d, interval=%.2fs, psutil=%s",
            self._history_size,
            self._update_interval,
            PSUTIL_AVAILABLE,
        )

    # ========================================================================
    # LIFECYCLE
    # ========================================================================

    @property
    def is_running(self) -> bool:
        """Return True when background monitoring is active."""

        with self._lock:
            return self._running

    def start(self) -> bool:
        """
        Start background system monitoring.

        Returns
        -------
        bool
            True when monitoring is running after the call.
        """

        return self._start_monitoring()

    def stop(self, timeout: float = 2.0) -> bool:
        """
        Stop background system monitoring.

        Parameters
        ----------
        timeout:
            Maximum time to wait for the worker thread.

        Returns
        -------
        bool
            True when monitoring is stopped.
        """

        return self._stop_monitoring(timeout=timeout)

    def _start_monitoring(self) -> bool:
        """
        Start the background monitoring worker.

        This method intentionally exists as a compatibility API for
        dashboard_core.py.
        """

        with self._lock:
            if self._running:
                logger.debug(
                    "SystemMonitor already running"
                )
                return True

            if not PSUTIL_AVAILABLE:
                logger.warning(
                    "SystemMonitor cannot start: psutil unavailable"
                )
                return False

            self._stop_event.clear()

            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="AssistantX-SystemMonitor",
                daemon=True,
            )

            self._running = True

            thread = self._monitor_thread

            logger.info(
                "SystemMonitor background monitoring starting"
            )

        try:
            thread.start()
            return True

        except Exception:
            with self._lock:
                self._running = False
                self._monitor_thread = None

            logger.exception(
                "Failed to start SystemMonitor worker"
            )

            return False

    def _stop_monitoring(
        self,
        *,
        timeout: float = 2.0,
    ) -> bool:
        """
        Stop the background monitoring worker.

        This method intentionally exists as a compatibility API for
        dashboard_core.py.
        """

        with self._lock:
            if not self._running:
                logger.debug(
                    "SystemMonitor already stopped"
                )
                return True

            self._stop_event.set()

            thread = self._monitor_thread

        if thread is not None and thread.is_alive():
            if thread is not threading.current_thread():
                thread.join(
                    timeout=max(0.0, float(timeout))
                )

        with self._lock:
            self._running = False

            if (
                self._monitor_thread is not None
                and not self._monitor_thread.is_alive()
            ):
                self._monitor_thread = None

        logger.info(
            "SystemMonitor background monitoring stopped"
        )

        return True

    def _monitor_loop(self) -> None:
        """Background worker loop."""

        logger.debug(
            "SystemMonitor worker loop started"
        )

        try:
            while not self._stop_event.is_set():
                started = time.monotonic()

                try:
                    self.snapshot()

                except Exception:
                    logger.exception(
                        "Unhandled error during system monitor tick"
                    )

                elapsed = time.monotonic() - started

                wait_time = max(
                    0.05,
                    self._update_interval - elapsed,
                )

                self._stop_event.wait(wait_time)

        finally:
            with self._lock:
                self._running = False

            logger.debug(
                "SystemMonitor worker loop exited"
            )

    # ========================================================================
    # METRICS
    # ========================================================================

    def _get_cpu_percent(self) -> Optional[float]:
        """Get CPU usage percentage."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None

        try:
            percent = psutil.cpu_percent(interval=0.1)

            logger.debug(
                "CPU: %.1f%%",
                percent,
            )

            return float(percent)

        except Exception as exc:
            logger.debug(
                "CPU metric failed: %s",
                exc,
            )

            return None

    def _get_memory_info(
        self,
    ) -> tuple[Optional[float], Optional[int]]:
        """Get memory usage percentage and available bytes."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None, None

        try:
            memory = psutil.virtual_memory()

            percent = float(memory.percent)
            available = int(memory.available)

            logger.debug(
                "Memory: %.1f%% (%d bytes available)",
                percent,
                available,
            )

            return percent, available

        except Exception as exc:
            logger.debug(
                "Memory metric failed: %s",
                exc,
            )

            return None, None

    def _get_disk_info(self) -> Optional[float]:
        """Get disk usage percentage."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None

        try:
            # Windows-safe system drive.
            system_drive = os.environ.get(
                "SystemDrive",
                "C:",
            )

            disk = psutil.disk_usage(
                system_drive + "\\"
            )

            percent = float(disk.percent)

            logger.debug(
                "Disk: %.1f%%",
                percent,
            )

            return percent

        except Exception as exc:
            logger.debug(
                "Disk metric failed: %s",
                exc,
            )

            return None

    def _get_network_info(
        self,
    ) -> tuple[Optional[float], Optional[float]]:
        """Get network bandwidth in bytes/sec."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None, None

        try:
            current_io = psutil.net_io_counters()

            if current_io is None:
                return None, None

            if self._last_network_io is None:
                self._last_network_io = current_io

                return 0.0, 0.0

            interval = max(
                0.1,
                self._update_interval,
            )

            upload = (
                current_io.bytes_sent
                - self._last_network_io.bytes_sent
            ) / interval

            download = (
                current_io.bytes_recv
                - self._last_network_io.bytes_recv
            ) / interval

            self._last_network_io = current_io

            logger.debug(
                "Network: up=%.1f KB/s, down=%.1f KB/s",
                upload / 1024,
                download / 1024,
            )

            return (
                float(max(0.0, upload)),
                float(max(0.0, download)),
            )

        except Exception as exc:
            logger.debug(
                "Network metric failed: %s",
                exc,
            )

            return None, None

    def _get_temperature(self) -> Optional[float]:
        """Get system temperature when supported."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None

        try:
            if not hasattr(
                psutil,
                "sensors_temperatures",
            ):
                return None

            temps = psutil.sensors_temperatures()

            if not temps:
                return None

            # Common Linux sensor name.
            if "coretemp" in temps:
                entries = temps["coretemp"]

                if entries:
                    temp = entries[0].current

                    logger.debug(
                        "Temperature: %.1f°C",
                        temp,
                    )

                    return float(temp)

            # Generic fallback.
            for entries in temps.values():
                if entries:
                    temp = entries[0].current

                    logger.debug(
                        "Temperature: %.1f°C",
                        temp,
                    )

                    return float(temp)

            return None

        except Exception as exc:
            logger.debug(
                "Temperature metric failed: %s",
                exc,
            )

            return None

    def _get_process_count(self) -> Optional[int]:
        """Get current process count."""

        if not PSUTIL_AVAILABLE or psutil is None:
            return None

        try:
            count = len(psutil.pids())

            logger.debug(
                "Process count: %d",
                count,
            )

            return count

        except Exception as exc:
            logger.debug(
                "Process count failed: %s",
                exc,
            )

            return None

    # ========================================================================
    # SNAPSHOT
    # ========================================================================

    def snapshot(self) -> SystemSnapshot:
        """
        Collect a current system metrics snapshot.

        Results are throttled according to update_interval.
        """

        logger.debug(
            "Taking system snapshot"
        )

        with self._lock:
            current_time = time.monotonic()

            # Throttle repeated requests.
            if (
                current_time - self._last_update
                < self._update_interval
            ):
                logger.debug(
                    "Snapshot throttled"
                )

                if self._snapshots:
                    return self._snapshots[-1]

            self._last_update = current_time

            # Collect metrics.
            cpu = self._get_cpu_percent()

            (
                memory_percent,
                memory_available,
            ) = self._get_memory_info()

            disk = self._get_disk_info()

            (
                upload,
                download,
            ) = self._get_network_info()

            temperature = self._get_temperature()

            processes = self._get_process_count()

            snap = SystemSnapshot(
                timestamp=current_time,
                cpu_percent=cpu,
                memory_percent=memory_percent,
                memory_available=memory_available,
                disk_percent=disk,
                network_upload_bytes=upload,
                network_download_bytes=download,
                temperature_celsius=temperature,
                process_count=processes,
            )

            # Store history.
            self._snapshots.append(snap)

            if len(self._snapshots) > self._history_size:
                self._snapshots.pop(0)

            logger.debug(
                "Snapshot captured: %s",
                snap,
            )

            self._check_thresholds(snap)

            return snap

    # ========================================================================
    # ALERTS
    # ========================================================================

    def _check_thresholds(
        self,
        snap: SystemSnapshot,
    ) -> None:
        """Check system metrics against alert thresholds."""

        if (
            snap.cpu_percent is not None
            and snap.cpu_percent
            > self._cpu_alert_threshold
        ):
            logger.warning(
                "CPU usage high: %.1f%% "
                "(threshold: %.1f%%)",
                snap.cpu_percent,
                self._cpu_alert_threshold,
            )

        if (
            snap.memory_percent is not None
            and snap.memory_percent
            > self._memory_alert_threshold
        ):
            logger.warning(
                "Memory usage high: %.1f%% "
                "(threshold: %.1f%%)",
                snap.memory_percent,
                self._memory_alert_threshold,
            )

        if (
            snap.disk_percent is not None
            and snap.disk_percent
            > self._disk_alert_threshold
        ):
            logger.warning(
                "Disk usage high: %.1f%% "
                "(threshold: %.1f%%)",
                snap.disk_percent,
                self._disk_alert_threshold,
            )

    # ========================================================================
    # HISTORY
    # ========================================================================

    def get_history(self) -> list[SystemSnapshot]:
        """Return a copy of the measurement history."""

        with self._lock:
            return list(self._snapshots)

    def clear_history(self) -> None:
        """Clear measurement history."""

        with self._lock:
            self._snapshots.clear()
            self._last_network_io = None

            logger.info(
                "System monitor history cleared"
            )

    # ========================================================================
    # STATISTICS
    # ========================================================================

    def get_average_cpu(self) -> Optional[float]:
        """Get average CPU usage from history."""

        with self._lock:
            values = [
                snapshot.cpu_percent
                for snapshot in self._snapshots
                if snapshot.cpu_percent is not None
            ]

            if not values:
                return None

            average = sum(values) / len(values)

            logger.debug(
                "Average CPU: %.1f%%",
                average,
            )

            return float(average)

    def get_peak_cpu(self) -> Optional[float]:
        """Get peak CPU usage from history."""

        with self._lock:
            values = [
                snapshot.cpu_percent
                for snapshot in self._snapshots
                if snapshot.cpu_percent is not None
            ]

            if not values:
                return None

            peak = max(values)

            logger.debug(
                "Peak CPU: %.1f%%",
                peak,
            )

            return float(peak)

    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================

    def diagnostics(self) -> dict:
        """Return detailed monitor diagnostics."""

        logger.debug(
            "Generating system monitor diagnostics"
        )

        with self._lock:
            latest = (
                self._snapshots[-1]
                if self._snapshots
                else None
            )

            return {
                "component": "SystemMonitor",
                "healthy": (
                    PSUTIL_AVAILABLE
                    and self._running
                ),
                "available": PSUTIL_AVAILABLE,
                "psutil_available": PSUTIL_AVAILABLE,
                "running": self._running,
                "thread_alive": bool(
                    self._monitor_thread
                    and self._monitor_thread.is_alive()
                ),
                "history_size": len(
                    self._snapshots
                ),
                "max_history": self._history_size,
                "update_interval": self._update_interval,
                "latest": (
                    {
                        "timestamp": latest.timestamp,
                        "cpu_percent": latest.cpu_percent,
                        "memory_percent": latest.memory_percent,
                        "disk_percent": latest.disk_percent,
                        "network_upload_bytes": (
                            latest.network_upload_bytes
                        ),
                        "network_download_bytes": (
                            latest.network_download_bytes
                        ),
                        "temperature_celsius": (
                            latest.temperature_celsius
                        ),
                        "process_count": (
                            latest.process_count
                        ),
                    }
                    if latest
                    else None
                ),
                "averages": {
                    "cpu": self.get_average_cpu(),
                },
                "peaks": {
                    "cpu": self.get_peak_cpu(),
                },
            }


# ============================================================================
# GLOBAL MONITOR
# ============================================================================


_global_monitor: Optional[SystemMonitor] = None
_global_monitor_lock = RLock()


def get_monitor() -> SystemMonitor:
    """Get or create the global SystemMonitor instance."""

    global _global_monitor

    with _global_monitor_lock:
        if _global_monitor is None:
            logger.debug(
                "Creating global system monitor"
            )

            _global_monitor = SystemMonitor()

        return _global_monitor


def start_monitor() -> bool:
    """Start the global system monitor."""

    return get_monitor().start()


def stop_monitor() -> bool:
    """Stop the global system monitor."""

    return get_monitor().stop()


def system_monitor_diagnostics() -> dict:
    """Return diagnostics for the global monitor."""

    return get_monitor().diagnostics()


# ============================================================================
# MODULE EXPORTS
# ============================================================================


__all__ = [
    "PSUTIL_AVAILABLE",
    "SystemSnapshot",
    "SystemMonitor",
    "get_monitor",
    "start_monitor",
    "stop_monitor",
    "system_monitor_diagnostics",
]


logger.info(
    "System monitor module loaded successfully"
)
