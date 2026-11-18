"""
core/scheduler.py — Production-Grade Thread-Safe Background Scheduler
======================================================================

Lightweight, dependency-free background scheduler for AssistantX.

Features
--------
- One-time jobs
- Delayed jobs
- Recurring jobs
- Cancellation
- Rescheduling
- Thread-safe public API
- Min-heap scheduling
- Generation-based stale-entry invalidation
- Graceful worker shutdown
- Callback exception isolation
- EventBus integration
- Runtime diagnostics
- Scheduler statistics
- Safe restart after a completed shutdown
- No callback execution while scheduler locks are held

Architecture
------------

    Scheduler
        │
        ├── Job registry
        │
        ├── Min-heap
        │      └── (run_at, tie_breaker, job_id, generation)
        │
        ├── Worker thread
        │
        ├── Wake event
        │
        └── Stop event

Lifecycle
---------

    STOPPED
       │
       ▼
    RUNNING
       │
       ▼
    STOPPING
       │
       ▼
    STOPPED

Job lifecycle
-------------

    PENDING
       │
       ▼
    RUNNING
       │
       ├── success ──> COMPLETED   (one-time)
       │
       ├── failure ──> FAILED      (one-time)
       │
       └── recurring ──> PENDING

Cancellation
------------

    PENDING ──> CANCELLED

Recurring jobs
--------------

Recurring jobs are scheduled from their previous planned execution time.
If the worker is delayed and multiple occurrences are missed, missed
occurrences are skipped and the next future occurrence is scheduled.

Thread safety
-------------

All scheduler state mutations are protected by RLock.

Callbacks are NEVER executed while the scheduler lock is held.

Shutdown
--------

stop() requests graceful termination and waits for the worker thread.
Callbacks cannot be forcibly terminated. If a callback exceeds the
shutdown timeout, the worker remains alive until the callback returns.
A subsequent start() is blocked until the previous worker exits.

EventBus events
---------------

    Events.TASK_SCHEDULED
    Events.REMINDER_DUE

Public compatibility
--------------------

The module preserves the existing AssistantX scheduler API:

    scheduler
    Scheduler
    ScheduledJob
    JobInfo
    JobStatus
    schedule_once()
    schedule_after()
    schedule_recurring()
    cancel_job()
    get_scheduler()
"""

from __future__ import annotations

import heapq
import itertools
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


# ============================================================================
# Constants
# ============================================================================

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_STOP_TIMEOUT = 3.0

MIN_POLL_INTERVAL = 0.05
MAX_POLL_INTERVAL = 60.0

MIN_INTERVAL_SECONDS = 0.05

WORKER_THREAD_NAME = "AssistantX-Scheduler"

Callback = Callable[[], None]

_counter = itertools.count()


# ============================================================================
# Exceptions
# ============================================================================


class SchedulerError(Exception):
    """Base exception for scheduler errors."""


class SchedulerValidationError(SchedulerError):
    """Raised when scheduler input is invalid."""


class SchedulerStateError(SchedulerError):
    """Raised when an operation is invalid for the current state."""


class JobNotFoundError(SchedulerError):
    """Raised when a requested job does not exist."""


# ============================================================================
# Job Status
# ============================================================================


class JobStatus(str, Enum):
    """Current state of a scheduled job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ============================================================================
# Internal Scheduled Job
# ============================================================================


@dataclass(slots=True)
class ScheduledJob:
    """
    Internal scheduler job representation.

    Heap ordering is stored separately in heap tuples, rather than relying
    on dataclass ordering. This keeps mutable job fields out of heap
    comparisons.
    """

    sort_index: float

    tie_breaker: int = field(
        default_factory=lambda: next(_counter)
    )

    id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    name: str = ""

    callback: Optional[Callback] = field(
        default=None,
        repr=False,
    )

    recurring: bool = False

    interval_seconds: float = 0.0

    cancelled: bool = False

    status: JobStatus = JobStatus.PENDING

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    created_at: float = field(
        default_factory=time.time
    )

    run_count: int = 0

    last_run_at: Optional[float] = None

    last_error: Optional[str] = None

    generation: int = 0


# ============================================================================
# Public Job Information
# ============================================================================


@dataclass(frozen=True, slots=True)
class JobInfo:
    """Read-only public representation of a scheduled job."""

    id: str
    name: str
    run_at: datetime
    recurring: bool
    interval_seconds: float
    status: JobStatus
    created_at: datetime
    run_count: int
    last_run_at: Optional[datetime]
    last_error: Optional[str]
    metadata: dict[str, Any]


# ============================================================================
# Scheduler
# ============================================================================


class Scheduler:
    """
    Thread-safe background job scheduler.

    Parameters
    ----------
    poll_interval_seconds:
        Maximum polling interval when no earlier wake-up is required.

    stop_timeout:
        Maximum amount of time stop() waits for the worker thread.
    """

    def __init__(
        self,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL,
        *,
        stop_timeout: float = DEFAULT_STOP_TIMEOUT,
    ) -> None:
        self._poll_interval = self._validate_poll_interval(
            poll_interval_seconds
        )

        self._stop_timeout = self._validate_positive(
            stop_timeout,
            "stop_timeout",
        )

        self._heap: list[
            tuple[float, int, str, int]
        ] = []

        self._jobs_by_id: dict[
            str,
            ScheduledJob,
        ] = {}

        self._lock = threading.RLock()

        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

        self._thread: Optional[threading.Thread] = None

        self._running = False
        self._stopping = False

        self._started_at: Optional[float] = None
        self._stopped_at: Optional[float] = None

        self._executed_count = 0
        self._failed_count = 0
        self._cancelled_count = 0

        self._logger().debug(
            "Scheduler initialized: poll_interval=%.2f, stop_timeout=%.2f",
            self._poll_interval,
            self._stop_timeout,
        )

    # ========================================================================
    # Logging / EventBus
    # ========================================================================

    @staticmethod
    def _logger():
        """
        Lazily return the AssistantX scheduler logger.

        This prevents scheduler import from configuring logging before
        core.startup.bootstrap_app() has had a chance to configure it.
        """
        from core.logger import get_logger

        return get_logger(__name__)

    @staticmethod
    def _emit_event(
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Safely emit an AssistantX EventBus event."""
        try:
            from core.event_bus import event_bus

            event_bus.emit(
                event_name,
                payload,
            )
        except Exception as exc:
            Scheduler._logger().warning(
                "Failed to emit scheduler event '%s': %s",
                event_name,
                exc,
                exc_info=True,
            )

    # ========================================================================
    # Lifecycle
    # ========================================================================

    def start(self) -> None:
        """
        Start the scheduler worker.

        Safe to call repeatedly while already running.

        Raises
        ------
        SchedulerStateError
            If an older worker thread is still alive after a timed-out stop.
        """
        with self._lock:
            if self._running:
                self._logger().debug(
                    "Scheduler already running."
                )
                return

            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                raise SchedulerStateError(
                    "Previous scheduler worker is still running. "
                    "Wait for it to exit before restarting."
                )

            self._stop_event.clear()
            self._wake_event.clear()

            self._stopping = False
            self._running = True

            self._started_at = time.time()
            self._stopped_at = None

            worker = threading.Thread(
                target=self._run_loop,
                name=WORKER_THREAD_NAME,
                daemon=True,
            )

            self._thread = worker

            worker.start()

        self._logger().info(
            "Scheduler started (poll_interval=%.2fs)",
            self._poll_interval,
        )

    def stop(
        self,
        *,
        timeout: Optional[float] = None,
    ) -> None:
        """
        Gracefully stop the scheduler.

        Running callbacks cannot be forcibly terminated. If the worker
        remains alive after timeout, the scheduler keeps its thread reference
        and refuses an unsafe immediate restart.
        """
        with self._lock:
            thread = self._thread

            if not self._running:
                if (
                    thread is not None
                    and thread.is_alive()
                ):
                    self._logger().warning(
                        "Scheduler worker is still alive while scheduler "
                        "is marked stopped."
                    )
                else:
                    self._logger().debug(
                        "Scheduler already stopped."
                    )
                return

            self._stopping = True

            self._stop_event.set()
            self._wake_event.set()

        wait_timeout = (
            self._stop_timeout
            if timeout is None
            else self._validate_positive(
                timeout,
                "timeout",
            )
        )

        if thread is not None:
            self._logger().debug(
                "Waiting for scheduler worker "
                "(timeout=%.2fs)",
                wait_timeout,
            )

            thread.join(
                timeout=wait_timeout
            )

        with self._lock:
            worker_alive = bool(
                self._thread
                and self._thread.is_alive()
            )

            if worker_alive:
                self._running = False
                self._stopping = False

                self._logger().warning(
                    "Scheduler worker did not stop within %.2fs. "
                    "It will remain alive until its callback returns.",
                    wait_timeout,
                )

                return

            self._running = False
            self._stopping = False
            self._thread = None
            self._stopped_at = time.time()

        self._logger().info(
            "Scheduler stopped."
        )

    def is_running(self) -> bool:
        """Return True when scheduler is actively running."""
        with self._lock:
            return self._running

    @property
    def running(self) -> bool:
        """Backward-compatible running property."""
        return self.is_running()

    @property
    def stopping(self) -> bool:
        """Return True while scheduler shutdown is in progress."""
        with self._lock:
            return self._stopping

    # ========================================================================
    # Worker Loop
    # ========================================================================

    def _run_loop(self) -> None:
        """Run the scheduler worker until stop is requested."""
        logger = self._logger()

        logger.debug(
            "Scheduler worker loop started."
        )

        try:
            while not self._stop_event.is_set():
                try:
                    wait_time = self._process_due_jobs()
                except Exception:
                    logger.exception(
                        "Unexpected error in scheduler worker loop."
                    )
                    wait_time = self._poll_interval

                self._wake_event.wait(
                    timeout=max(
                        0.0,
                        wait_time,
                    )
                )

                self._wake_event.clear()

        finally:
            with self._lock:
                self._running = False
                self._stopping = False

                if (
                    self._thread is threading.current_thread()
                ):
                    self._thread = None

                self._stopped_at = time.time()

            logger.debug(
                "Scheduler worker loop exited."
            )

    def _process_due_jobs(self) -> float:
        """
        Collect due jobs and execute them outside the scheduler lock.
        """
        now = time.time()

        due_jobs: list[ScheduledJob] = []

        with self._lock:
            while self._heap:
                (
                    run_at,
                    _tie_breaker,
                    job_id,
                    generation,
                ) = self._heap[0]

                if run_at > now:
                    break

                heapq.heappop(
                    self._heap
                )

                job = self._jobs_by_id.get(
                    job_id
                )

                if job is None:
                    continue

                if generation != job.generation:
                    continue

                if job.cancelled:
                    self._jobs_by_id.pop(
                        job.id,
                        None,
                    )
                    continue

                if job.status is not JobStatus.PENDING:
                    continue

                job.status = JobStatus.RUNNING
                due_jobs.append(job)

        for job in due_jobs:
            self._execute(
                job
            )

        return self._get_next_wait_time()

    def _get_next_wait_time(self) -> float:
        """Return seconds until the next scheduled job."""
        with self._lock:
            while self._heap:
                (
                    run_at,
                    _tie_breaker,
                    job_id,
                    generation,
                ) = self._heap[0]

                job = self._jobs_by_id.get(
                    job_id
                )

                if job is None:
                    heapq.heappop(
                        self._heap
                    )
                    continue

                if generation != job.generation:
                    heapq.heappop(
                        self._heap
                    )
                    continue

                if job.cancelled:
                    heapq.heappop(
                        self._heap
                    )
                    continue

                break

            if not self._heap:
                return self._poll_interval

            next_run = self._heap[0][0]

        delay = next_run - time.time()

        if delay <= 0:
            return 0.0

        return min(
            delay,
            self._poll_interval,
        )

    # ========================================================================
    # Job Execution
    # ========================================================================

    def _execute(
        self,
        job: ScheduledJob,
    ) -> None:
        """Execute one callback safely."""
        logger = self._logger()

        logger.info(
            "Executing scheduled job: '%s' (id=%s)",
            job.name or job.id,
            job.id[:8],
        )

        job.last_run_at = time.time()
        job.run_count += 1

        self._emit_event(
            self._events().REMINDER_DUE,
            {
                "id": job.id,
                "name": job.name,
                "metadata": dict(job.metadata),
                "recurring": job.recurring,
                "run_count": job.run_count,
            },
        )

        callback_error: Optional[str] = None

        if job.callback is not None:
            try:
                job.callback()

            except Exception as exc:
                callback_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                logger.error(
                    "Job callback failed: '%s' "
                    "(id=%s, error=%s)",
                    job.name or job.id,
                    job.id[:8],
                    callback_error,
                    exc_info=True,
                )

        with self._lock:
            if callback_error is not None:
                job.last_error = callback_error
                self._failed_count += 1

                if job.recurring:
                    if not job.cancelled:
                        job.status = JobStatus.PENDING
                    else:
                        job.status = JobStatus.CANCELLED
                else:
                    job.status = JobStatus.FAILED

            else:
                self._executed_count += 1

                if job.recurring:
                    if job.cancelled:
                        job.status = JobStatus.CANCELLED
                    else:
                        job.status = JobStatus.PENDING
                else:
                    job.status = JobStatus.COMPLETED

        if callback_error is None:
            logger.info(
                "Job completed successfully: '%s' "
                "(id=%s, count=%d)",
                job.name or job.id,
                job.id[:8],
                job.run_count,
            )

        if not job.recurring:
            with self._lock:
                self._jobs_by_id.pop(
                    job.id,
                    None,
                )

        elif job.cancelled:
            with self._lock:
                self._jobs_by_id.pop(
                    job.id,
                    None,
                )

    # ========================================================================
    # Scheduling
    # ========================================================================

    def schedule_once(
        self,
        run_at: datetime,
        callback: Optional[Callback] = None,
        name: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a one-time job at a specific datetime."""
        if not isinstance(
            run_at,
            datetime,
        ):
            raise SchedulerValidationError(
                "run_at must be datetime "
                f"(got {type(run_at).__name__})"
            )

        run_at_utc = self._to_utc(
            run_at
        )

        job = ScheduledJob(
            sort_index=run_at_utc.timestamp(),
            tie_breaker=next(_counter),
            name=self._validate_name(name),
            callback=self._validate_callback(callback),
            recurring=False,
            metadata=self._copy_metadata(metadata),
        )

        self._add_job(
            job
        )

        self._emit_event(
            self._events().TASK_SCHEDULED,
            self._scheduled_payload(
                job
            ),
        )

        self._logger().info(
            "Scheduled one-time job: '%s' for %s (id=%s)",
            job.name or job.id,
            run_at_utc.isoformat(),
            job.id[:8],
        )

        return job.id

    def schedule_after(
        self,
        delay_seconds: float,
        callback: Optional[Callback] = None,
        name: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a one-time job after a delay."""
        delay = self._validate_delay(
            delay_seconds
        )

        run_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=delay)
        )

        return self.schedule_once(
            run_at,
            callback=callback,
            name=name,
            metadata=metadata,
        )

    def schedule_recurring(
        self,
        interval_seconds: float,
        callback: Optional[Callback] = None,
        name: str = "",
        start_immediately: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a recurring job."""
        interval = self._validate_interval(
            interval_seconds
        )

        first_run = time.time()

        if not start_immediately:
            first_run += interval

        job = ScheduledJob(
            sort_index=first_run,
            tie_breaker=next(_counter),
            name=self._validate_name(name),
            callback=self._validate_callback(callback),
            recurring=True,
            interval_seconds=interval,
            metadata=self._copy_metadata(metadata),
        )

        self._add_job(
            job
        )

        self._emit_event(
            self._events().TASK_SCHEDULED,
            self._scheduled_payload(
                job
            ),
        )

        self._logger().info(
            "Scheduled recurring job: '%s' every %.2fs (id=%s)",
            job.name or job.id,
            interval,
            job.id[:8],
        )

        return job.id

    # ========================================================================
    # Internal Job Management
    # ========================================================================

    def _add_job(
        self,
        job: ScheduledJob,
    ) -> None:
        """Add a job to the registry and heap."""
        with self._lock:
            if job.id in self._jobs_by_id:
                raise SchedulerError(
                    f"Duplicate job ID: {job.id}"
                )

            self._jobs_by_id[
                job.id
            ] = job

            heapq.heappush(
                self._heap,
                (
                    job.sort_index,
                    job.tie_breaker,
                    job.id,
                    job.generation,
                ),
            )

            self._wake_event.set()

    # ========================================================================
    # Cancellation
    # ========================================================================

    def cancel(
        self,
        job_id: str,
    ) -> bool:
        """Cancel a pending or recurring job."""
        job_id = self._validate_job_id(
            job_id
        )

        with self._lock:
            job = self._jobs_by_id.get(
                job_id
            )

            if job is None:
                return False

            if job.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                return False

            job.cancelled = True
            job.status = JobStatus.CANCELLED

            self._jobs_by_id.pop(
                job_id,
                None,
            )

            self._cancelled_count += 1

            self._wake_event.set()

        self._logger().info(
            "Job cancelled: '%s' (id=%s)",
            job.name or job.id,
            job.id[:8],
        )

        return True

    # ========================================================================
    # Rescheduling
    # ========================================================================

    def reschedule(
        self,
        job_id: str,
        run_at: datetime,
    ) -> bool:
        """Reschedule a pending job."""
        job_id = self._validate_job_id(
            job_id
        )

        if not isinstance(
            run_at,
            datetime,
        ):
            raise SchedulerValidationError(
                "run_at must be datetime "
                f"(got {type(run_at).__name__})"
            )

        run_at_utc = self._to_utc(
            run_at
        )

        with self._lock:
            job = self._jobs_by_id.get(
                job_id
            )

            if job is None:
                return False

            if job.status is not JobStatus.PENDING:
                return False

            if job.cancelled:
                return False

            old_run_at = job.sort_index

            job.sort_index = run_at_utc.timestamp()
            job.tie_breaker = next(_counter)
            job.generation += 1

            heapq.heappush(
                self._heap,
                (
                    job.sort_index,
                    job.tie_breaker,
                    job.id,
                    job.generation,
                ),
            )

            self._wake_event.set()

        self._logger().info(
            "Job rescheduled: '%s' (id=%s, old_delay=%.2fs, new_run=%s)",
            job.name or job.id,
            job.id[:8],
            old_run_at - time.time(),
            run_at_utc.isoformat(),
        )

        return True

    # ========================================================================
    # Inspection
    # ========================================================================

    def get_job(
        self,
        job_id: str,
    ) -> Optional[JobInfo]:
        """Return a snapshot of a tracked job."""
        job_id = self._validate_job_id(
            job_id
        )

        with self._lock:
            job = self._jobs_by_id.get(
                job_id
            )

            if job is None:
                return None

            return self._job_to_info(
                job
            )

    def pending_jobs(
        self,
    ) -> list[dict[str, Any]]:
        """Return pending/running jobs in dictionary format."""
        with self._lock:
            jobs = [
                job
                for job in self._jobs_by_id.values()
                if (
                    not job.cancelled
                    and job.status
                    in {
                        JobStatus.PENDING,
                        JobStatus.RUNNING,
                    }
                )
            ]

        jobs.sort(
            key=lambda job: job.sort_index
        )

        return [
            self._job_to_dict(
                job
            )
            for job in jobs
        ]

    def list_jobs(
        self,
    ) -> list[JobInfo]:
        """Return all currently tracked jobs."""
        with self._lock:
            jobs = list(
                self._jobs_by_id.values()
            )

        jobs.sort(
            key=lambda job: job.sort_index
        )

        return [
            self._job_to_info(
                job
            )
            for job in jobs
        ]

    def job_count(self) -> int:
        """Return the number of currently tracked jobs."""
        with self._lock:
            return len(
                self._jobs_by_id
            )

    # ========================================================================
    # Statistics
    # ========================================================================

    @property
    def poll_interval(self) -> float:
        """Return scheduler polling interval."""
        return self._poll_interval

    @property
    def stop_timeout(self) -> float:
        """Return configured shutdown timeout."""
        return self._stop_timeout

    def stats(self) -> dict[str, Any]:
        """Return scheduler runtime statistics."""
        with self._lock:
            return {
                "running": self._running,
                "stopping": self._stopping,
                "job_count": len(
                    self._jobs_by_id
                ),
                "heap_size": len(
                    self._heap
                ),
                "executed_count": self._executed_count,
                "failed_count": self._failed_count,
                "cancelled_count": self._cancelled_count,
                "poll_interval": self._poll_interval,
                "stop_timeout": self._stop_timeout,
                "started_at": self._timestamp_iso(
                    self._started_at
                ),
                "stopped_at": self._timestamp_iso(
                    self._stopped_at
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed scheduler diagnostics."""
        with self._lock:
            thread = self._thread

            return {
                "module": "core.scheduler",
                "running": self._running,
                "stopping": self._stopping,
                "job_count": len(
                    self._jobs_by_id
                ),
                "heap_size": len(
                    self._heap
                ),
                "executed_count": self._executed_count,
                "failed_count": self._failed_count,
                "cancelled_count": self._cancelled_count,
                "poll_interval": self._poll_interval,
                "stop_timeout": self._stop_timeout,
                "started_at": self._timestamp_iso(
                    self._started_at
                ),
                "stopped_at": self._timestamp_iso(
                    self._stopped_at
                ),
                "thread_alive": bool(
                    thread
                    and thread.is_alive()
                ),
                "worker_name": (
                    thread.name
                    if thread is not None
                    else None
                ),
            }

    # ========================================================================
    # Validation
    # ========================================================================

    @staticmethod
    def _validate_poll_interval(
        value: float,
    ) -> float:
        if isinstance(
            value,
            bool,
        ):
            raise SchedulerValidationError(
                "poll_interval_seconds must be numeric."
            )

        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                "poll_interval_seconds must be numeric."
            ) from exc

        if not math.isfinite(numeric):
            raise SchedulerValidationError(
                "poll_interval_seconds must be finite."
            )

        if not (
            MIN_POLL_INTERVAL
            <= numeric
            <= MAX_POLL_INTERVAL
        ):
            raise SchedulerValidationError(
                f"poll_interval_seconds must be between "
                f"{MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} "
                f"(got {numeric})."
            )

        return numeric

    @staticmethod
    def _validate_positive(
        value: float,
        field_name: str,
    ) -> float:
        if isinstance(
            value,
            bool,
        ):
            raise SchedulerValidationError(
                f"{field_name} must be numeric."
            )

        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                f"{field_name} must be numeric."
            ) from exc

        if not math.isfinite(numeric) or numeric <= 0:
            raise SchedulerValidationError(
                f"{field_name} must be > 0."
            )

        return numeric

    @staticmethod
    def _validate_delay(
        value: float,
    ) -> float:
        if isinstance(
            value,
            bool,
        ):
            raise SchedulerValidationError(
                "delay_seconds must be numeric."
            )

        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                "delay_seconds must be numeric."
            ) from exc

        if not math.isfinite(numeric):
            raise SchedulerValidationError(
                "delay_seconds must be finite."
            )

        if numeric < 0:
            raise SchedulerValidationError(
                f"delay_seconds cannot be negative "
                f"(got {numeric})."
            )

        return numeric

    @staticmethod
    def _validate_interval(
        value: float,
    ) -> float:
        if isinstance(
            value,
            bool,
        ):
            raise SchedulerValidationError(
                "interval_seconds must be numeric."
            )

        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                "interval_seconds must be numeric."
            ) from exc

        if not math.isfinite(numeric):
            raise SchedulerValidationError(
                "interval_seconds must be finite."
            )

        if numeric < MIN_INTERVAL_SECONDS:
            raise SchedulerValidationError(
                f"interval_seconds must be >= "
                f"{MIN_INTERVAL_SECONDS}s "
                f"(got {numeric})."
            )

        return numeric

    @staticmethod
    def _validate_job_id(
        job_id: str,
    ) -> str:
        if not isinstance(
            job_id,
            str,
        ):
            raise SchedulerValidationError(
                f"job_id must be str "
                f"(got {type(job_id).__name__})."
            )

        value = job_id.strip()

        if not value:
            raise SchedulerValidationError(
                "job_id cannot be empty."
            )

        return value

    @staticmethod
    def _validate_name(
        name: Optional[str],
    ) -> str:
        if name is None:
            return ""

        if not isinstance(
            name,
            str,
        ):
            raise SchedulerValidationError(
                f"Job name must be str "
                f"(got {type(name).__name__})."
            )

        return name.strip()

    @staticmethod
    def _validate_callback(
        callback: Optional[Callback],
    ) -> Optional[Callback]:
        if callback is None:
            return None

        if not callable(callback):
            raise SchedulerValidationError(
                "callback must be callable or None."
            )

        return callback

    @staticmethod
    def _copy_metadata(
        metadata: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if metadata is None:
            return {}

        if not isinstance(
            metadata,
            dict,
        ):
            raise SchedulerValidationError(
                "metadata must be a dictionary or None."
            )

        return dict(metadata)

    # ========================================================================
    # Helpers
    # ========================================================================

    @staticmethod
    def _to_utc(
        value: datetime,
    ) -> datetime:
        """
        Normalize datetime to timezone-aware UTC.

        Naive datetimes are interpreted as local system time, matching
        Python's standard timestamp behavior, then converted to UTC.
        """
        if value.tzinfo is None:
            local = value.astimezone()
            return local.astimezone(
                timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _timestamp_iso(
        value: Optional[float],
    ) -> Optional[str]:
        if value is None:
            return None

        return datetime.fromtimestamp(
            value,
            tz=timezone.utc,
        ).isoformat()

    @staticmethod
    def _events():
        from core.event_bus import Events

        return Events

    @staticmethod
    def _job_to_info(
        job: ScheduledJob,
    ) -> JobInfo:
        return JobInfo(
            id=job.id,
            name=job.name,
            run_at=datetime.fromtimestamp(
                job.sort_index,
                tz=timezone.utc,
            ),
            recurring=job.recurring,
            interval_seconds=job.interval_seconds,
            status=job.status,
            created_at=datetime.fromtimestamp(
                job.created_at,
                tz=timezone.utc,
            ),
            run_count=job.run_count,
            last_run_at=(
                datetime.fromtimestamp(
                    job.last_run_at,
                    tz=timezone.utc,
                )
                if job.last_run_at is not None
                else None
            ),
            last_error=job.last_error,
            metadata=dict(
                job.metadata
            ),
        )

    @staticmethod
    def _job_to_dict(
        job: ScheduledJob,
    ) -> dict[str, Any]:
        return {
            "id": job.id,
            "name": job.name,
            "run_at": datetime.fromtimestamp(
                job.sort_index,
                tz=timezone.utc,
            ).isoformat(),
            "recurring": job.recurring,
            "interval_seconds": job.interval_seconds,
            "status": job.status.value,
            "run_count": job.run_count,
            "last_run_at": (
                datetime.fromtimestamp(
                    job.last_run_at,
                    tz=timezone.utc,
                ).isoformat()
                if job.last_run_at is not None
                else None
            ),
            "last_error": job.last_error,
            "metadata": dict(
                job.metadata
            ),
        }

    @staticmethod
    def _scheduled_payload(
        job: ScheduledJob,
    ) -> dict[str, Any]:
        return {
            "id": job.id,
            "name": job.name,
            "run_at": datetime.fromtimestamp(
                job.sort_index,
                tz=timezone.utc,
            ).isoformat(),
            "recurring": job.recurring,
            "interval_seconds": job.interval_seconds,
            "metadata": dict(
                job.metadata
            ),
        }


# ============================================================================
# Global Singleton
# ============================================================================

scheduler = Scheduler()


Scheduler._logger().info(
    "Global scheduler initialized: poll_interval=%.2f",
    scheduler.poll_interval,
)


# ============================================================================
# Convenience Functions
# ============================================================================


def schedule_once(
    run_at: datetime,
    callback: Optional[Callback] = None,
    name: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Schedule a one-time global job."""
    return scheduler.schedule_once(
        run_at,
        callback=callback,
        name=name,
        metadata=metadata,
    )


def schedule_after(
    delay_seconds: float,
    callback: Optional[Callback] = None,
    name: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Schedule a delayed global job."""
    return scheduler.schedule_after(
        delay_seconds,
        callback=callback,
        name=name,
        metadata=metadata,
    )


def schedule_recurring(
    interval_seconds: float,
    callback: Optional[Callback] = None,
    name: str = "",
    start_immediately: bool = False,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Schedule a recurring global job."""
    return scheduler.schedule_recurring(
        interval_seconds,
        callback=callback,
        name=name,
        start_immediately=start_immediately,
        metadata=metadata,
    )


def cancel_job(
    job_id: str,
) -> bool:
    """Cancel a global scheduler job."""
    return scheduler.cancel(
        job_id
    )


def get_scheduler() -> Scheduler:
    """Return the global scheduler singleton."""
    return scheduler


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_STOP_TIMEOUT",
    "MIN_POLL_INTERVAL",
    "MAX_POLL_INTERVAL",
    "MIN_INTERVAL_SECONDS",
    "JobInfo",
    "JobStatus",
    "Scheduler",
    "ScheduledJob",
    "JobNotFoundError",
    "SchedulerError",
    "SchedulerStateError",
    "SchedulerValidationError",
    "scheduler",
    "cancel_job",
    "get_scheduler",
    "schedule_after",
    "schedule_once",
    "schedule_recurring",
]
