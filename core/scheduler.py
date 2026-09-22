"""
core.scheduler
==============

Lightweight, thread-safe background scheduler for AssistantX.

Features
--------
- One-time jobs
- Delayed jobs
- Recurring jobs
- Job cancellation
- Job rescheduling
- Job inspection
- Thread-safe operations
- Fast scheduler wake-up when new jobs are added
- Graceful start/stop
- Callback exception isolation
- Event-bus integration
- Optional persistent job metadata
- Scheduler diagnostics

The scheduler intentionally avoids heavy dependencies such as APScheduler.

Example
-------

    from core.scheduler import scheduler

    scheduler.start()

    job_id = scheduler.schedule_after(
        10,
        callback=lambda: print("Hello"),
        name="hello",
    )

    scheduler.cancel(job_id)

"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from core.event_bus import Events, event_bus
from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Types
# ============================================================================

Callback = Callable[[], None]

_counter = itertools.count()


# ============================================================================
# Constants
# ============================================================================

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_STOP_TIMEOUT = 3.0

MIN_POLL_INTERVAL = 0.05
MAX_POLL_INTERVAL = 60.0

MIN_INTERVAL_SECONDS = 0.05


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
# Job state
# ============================================================================


class JobStatus(str, Enum):
    """Current state of a scheduled job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ============================================================================
# Scheduled job
# ============================================================================


@dataclass(order=True)
class ScheduledJob:
    """
    Internal heap entry.

    ``sort_index`` is the UNIX timestamp used for heap ordering.
    ``tie_breaker`` guarantees deterministic ordering when timestamps match.
    """

    sort_index: float
    tie_breaker: int = field(compare=True)

    id: str = field(
        compare=False,
        default_factory=lambda: str(uuid.uuid4()),
    )

    name: str = field(
        compare=False,
        default="",
    )

    callback: Callback | None = field(
        compare=False,
        default=None,
        repr=False,
    )

    recurring: bool = field(
        compare=False,
        default=False,
    )

    interval_seconds: float = field(
        compare=False,
        default=0.0,
    )

    cancelled: bool = field(
        compare=False,
        default=False,
    )

    status: JobStatus = field(
        compare=False,
        default=JobStatus.PENDING,
    )

    metadata: dict[str, Any] = field(
        compare=False,
        default_factory=dict,
    )

    created_at: float = field(
        compare=False,
        default_factory=time.time,
    )

    run_count: int = field(
        compare=False,
        default=0,
    )

    last_run_at: float | None = field(
        compare=False,
        default=None,
    )

    last_error: str | None = field(
        compare=False,
        default=None,
    )

    # Used to determine whether a stale heap entry should be ignored.
    generation: int = field(
        compare=False,
        default=0,
    )


# ============================================================================
# Public job information
# ============================================================================


@dataclass(frozen=True)
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
    last_run_at: datetime | None
    last_error: str | None
    metadata: dict[str, Any]


# ============================================================================
# Scheduler
# ============================================================================


class Scheduler:
    """
    Thread-safe background scheduler.

    A single daemon worker thread processes scheduled jobs.

    Jobs are stored in a min-heap, giving efficient retrieval of the
    next due job.
    """

    def __init__(
        self,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL,
        *,
        stop_timeout: float = DEFAULT_STOP_TIMEOUT,
    ) -> None:

        if not (
            MIN_POLL_INTERVAL
            <= poll_interval_seconds
            <= MAX_POLL_INTERVAL
        ):
            raise SchedulerValidationError(
                f"poll_interval_seconds must be between "
                f"{MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL}."
            )

        if stop_timeout <= 0:
            raise SchedulerValidationError(
                "stop_timeout must be greater than zero."
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

        self._poll_interval = float(
            poll_interval_seconds
        )

        self._stop_timeout = float(
            stop_timeout
        )

        self._thread: threading.Thread | None = None

        self._running = False
        self._stopping = False

        self._started_at: float | None = None

        self._executed_count = 0
        self._failed_count = 0
        self._cancelled_count = 0

    # ========================================================================
    # Lifecycle
    # ========================================================================

    def start(self) -> None:
        """
        Start the scheduler worker.

        Safe to call multiple times.
        """

        with self._lock:

            if self._running:
                logger.debug(
                    "Scheduler already running."
                )
                return

            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                logger.debug(
                    "Scheduler worker thread is already alive."
                )
                self._running = True
                return

            self._stop_event.clear()
            self._wake_event.clear()

            self._stopping = False
            self._running = True

            self._started_at = time.time()

            self._thread = threading.Thread(
                target=self._run_loop,
                name="AssistantX-Scheduler",
                daemon=True,
            )

            self._thread.start()

        logger.info(
            "Scheduler started "
            "(poll interval=%.2fs).",
            self._poll_interval,
        )

    def stop(
        self,
        *,
        timeout: float | None = None,
    ) -> None:
        """
        Gracefully stop the scheduler.

        Running callbacks are not forcibly terminated.
        """

        with self._lock:

            if not self._running:
                logger.debug(
                    "Scheduler is already stopped."
                )
                return

            self._stopping = True

            self._stop_event.set()
            self._wake_event.set()

            thread = self._thread

        if thread is not None:
            thread.join(
                timeout=(
                    timeout
                    if timeout is not None
                    else self._stop_timeout
                )
            )

        with self._lock:
            self._running = False
            self._stopping = False
            self._thread = None

        logger.info(
            "Scheduler stopped."
        )

    def is_running(self) -> bool:
        """Return True when scheduler worker is active."""

        with self._lock:
            return self._running

    @property
    def running(self) -> bool:
        """Backward-compatible running property."""

        return self.is_running()

    # ========================================================================
    # Worker loop
    # ========================================================================

    def _run_loop(self) -> None:
        """Main scheduler worker loop."""

        logger.debug(
            "Scheduler worker loop started."
        )

        while not self._stop_event.is_set():

            try:
                wait_time = self._process_due_jobs()
            except Exception:
                logger.exception(
                    "Unexpected error in scheduler worker loop."
                )
                wait_time = self._poll_interval

            self._wake_event.wait(
                timeout=wait_time
            )

            self._wake_event.clear()

        logger.debug(
            "Scheduler worker loop exited."
        )

    def _process_due_jobs(self) -> float:
        """
        Execute all jobs that are currently due.

        Returns the recommended time until the next wake-up.
        """

        now = time.time()

        due_jobs: list[
            ScheduledJob
        ] = []

        with self._lock:

            while self._heap:

                run_at, _, job_id, generation = (
                    self._heap[0]
                )

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

                # Ignore stale heap entries.
                if generation != job.generation:
                    continue

                if job.cancelled:
                    self._remove_job_locked(
                        job.id
                    )
                    continue

                if job.status is not JobStatus.PENDING:
                    continue

                job.status = JobStatus.RUNNING

                due_jobs.append(job)

                if job.recurring:

                    # Schedule the next occurrence relative to the
                    # previous scheduled time rather than callback
                    # completion time to reduce long-term drift.
                    next_run = (
                        job.sort_index
                        + job.interval_seconds
                    )

                    # If the scheduler was asleep for a long time,
                    # don't execute dozens of missed recurring events.
                    while next_run <= now:
                        next_run += (
                            job.interval_seconds
                        )

                    job.sort_index = next_run
                    job.tie_breaker = next(
                        _counter
                    )
                    job.generation += 1
                    job.status = JobStatus.PENDING

                    heapq.heappush(
                        self._heap,
                        (
                            job.sort_index,
                            job.tie_breaker,
                            job.id,
                            job.generation,
                        ),
                    )

                else:
                    # One-shot job is removed after it has been claimed.
                    self._jobs_by_id.pop(
                        job.id,
                        None,
                    )

        for job in due_jobs:
            self._execute(job)

        return self._get_next_wait_time()

    def _get_next_wait_time(self) -> float:
        """
        Calculate how long the worker should sleep.
        """

        with self._lock:

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
    # Job execution
    # ========================================================================

    def _execute(
        self,
        job: ScheduledJob,
    ) -> None:
        """Execute a scheduled callback safely."""

        logger.info(
            "Running scheduled job '%s' (id=%s).",
            job.name or job.id,
            job.id,
        )

        job.last_run_at = time.time()
        job.run_count += 1

        try:
            event_bus.emit(
                Events.REMINDER_DUE,
                {
                    "id": job.id,
                    "name": job.name,
                    "metadata": dict(
                        job.metadata
                    ),
                    "recurring": job.recurring,
                },
            )

        except Exception:
            logger.exception(
                "Failed to emit REMINDER_DUE event "
                "for job '%s'.",
                job.name or job.id,
            )

        if job.callback is None:

            with self._lock:
                if job.recurring:
                    job.status = JobStatus.PENDING
                else:
                    job.status = JobStatus.COMPLETED

                self._executed_count += 1

            return

        try:

            job.callback()

            with self._lock:

                if job.recurring:
                    job.status = JobStatus.PENDING
                else:
                    job.status = JobStatus.COMPLETED

                self._executed_count += 1

            logger.debug(
                "Scheduled job '%s' completed.",
                job.name or job.id,
            )

        except Exception as exc:

            with self._lock:

                job.last_error = (
                    f"{type(exc).__name__}: {exc}"
                )

                self._failed_count += 1

                if job.recurring:
                    # Recurring jobs remain active after a failed run.
                    job.status = JobStatus.PENDING
                else:
                    job.status = JobStatus.FAILED

            logger.exception(
                "Scheduled job '%s' failed.",
                job.name or job.id,
            )

    # ========================================================================
    # Scheduling
    # ========================================================================

    def schedule_once(
        self,
        run_at: datetime,
        callback: Callback | None = None,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Schedule a one-time job.

        Returns
        -------
        str
            Job ID.
        """

        if not isinstance(
            run_at,
            datetime,
        ):
            raise SchedulerValidationError(
                "run_at must be a datetime."
            )

        if run_at.tzinfo is None:
            logger.debug(
                "Received naive datetime; "
                "interpreting it using local system time."
            )

        name = self._validate_name(
            name
        )

        job = ScheduledJob(
            sort_index=run_at.timestamp(),
            tie_breaker=next(_counter),
            name=name,
            callback=callback,
            recurring=False,
            metadata=dict(
                metadata or {}
            ),
        )

        self._add_job(
            job
        )

        self._emit_task_scheduled(
            job,
            run_at,
        )

        logger.info(
            "Scheduled one-off job '%s' for %s.",
            name or job.id,
            run_at.isoformat(),
        )

        return job.id

    def schedule_after(
        self,
        delay_seconds: float,
        callback: Callback | None = None,
        name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Schedule a one-time job after a delay.
        """

        self._validate_delay(
            delay_seconds
        )

        return self.schedule_once(
            datetime.now().astimezone()
            + __import__(
                "datetime"
            ).timedelta(
                seconds=delay_seconds
            ),
            callback=callback,
            name=name,
            metadata=metadata,
        )

    def schedule_recurring(
        self,
        interval_seconds: float,
        callback: Callback | None = None,
        name: str = "",
        start_immediately: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Schedule a recurring job.

        Parameters
        ----------
        interval_seconds:
            Seconds between executions.

        start_immediately:
            If True, first execution occurs immediately.
            Otherwise it occurs after one interval.
        """

        self._validate_interval(
            interval_seconds
        )

        name = self._validate_name(
            name
        )

        now = time.time()

        first_run = (
            now
            if start_immediately
            else now + interval_seconds
        )

        job = ScheduledJob(
            sort_index=first_run,
            tie_breaker=next(_counter),
            name=name,
            callback=callback,
            recurring=True,
            interval_seconds=float(
                interval_seconds
            ),
            metadata=dict(
                metadata or {}
            ),
        )

        self._add_job(
            job
        )

        logger.info(
            "Scheduled recurring job '%s' "
            "every %.2fs.",
            name or job.id,
            interval_seconds,
        )

        try:
            event_bus.emit(
                Events.TASK_SCHEDULED,
                {
                    "id": job.id,
                    "name": name,
                    "run_at": datetime.fromtimestamp(
                        first_run,
                        tz=timezone.utc,
                    ).isoformat(),
                    "recurring": True,
                    "interval_seconds": interval_seconds,
                },
            )
        except Exception:
            logger.exception(
                "Failed to emit TASK_SCHEDULED "
                "event for job '%s'.",
                job.name or job.id,
            )

        return job.id

    # ========================================================================
    # Internal add/remove
    # ========================================================================

    def _add_job(
        self,
        job: ScheduledJob,
    ) -> None:
        """Add a job to the scheduler."""

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

            # Wake the worker immediately so a newly-added job does
            # not have to wait for the normal polling interval.
            self._wake_event.set()

    def _remove_job_locked(
        self,
        job_id: str,
    ) -> None:
        """Remove job from lookup table while lock is held."""

        self._jobs_by_id.pop(
            job_id,
            None,
        )

    # ========================================================================
    # Cancellation
    # ========================================================================

    def cancel(
        self,
        job_id: str,
    ) -> bool:
        """
        Cancel a pending job.

        Returns True if a job was found and cancelled.
        """

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

        logger.info(
            "Cancelled scheduled job %s.",
            job_id,
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
        """
        Move an existing pending job to a new execution time.

        Returns True when successful.
        """

        job_id = self._validate_job_id(
            job_id
        )

        if not isinstance(
            run_at,
            datetime,
        ):
            raise SchedulerValidationError(
                "run_at must be a datetime."
            )

        with self._lock:

            job = self._jobs_by_id.get(
                job_id
            )

            if job is None:
                return False

            if job.status is not JobStatus.PENDING:
                return False

            job.sort_index = run_at.timestamp()
            job.tie_breaker = next(
                _counter
            )

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

        logger.info(
            "Rescheduled job '%s' for %s.",
            job.name or job.id,
            run_at.isoformat(),
        )

        return True

    # ========================================================================
    # Inspection
    # ========================================================================

    def get_job(
        self,
        job_id: str,
    ) -> JobInfo | None:
        """Return information about a job."""

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
        """
        Return pending jobs as dictionaries.

        Kept compatible with the original API.
        """

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
            {
                "id": job.id,
                "name": job.name,
                "run_at": datetime.fromtimestamp(
                    job.sort_index,
                    tz=timezone.utc,
                ).isoformat(),
                "recurring": job.recurring,
                "interval_seconds": (
                    job.interval_seconds
                ),
                "status": job.status.value,
                "run_count": job.run_count,
                "metadata": dict(
                    job.metadata
                ),
            }
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
            self._job_to_info(job)
            for job in jobs
        ]

    def job_count(self) -> int:
        """Return number of currently tracked jobs."""

        with self._lock:
            return len(
                self._jobs_by_id
            )

    # ========================================================================
    # Statistics
    # ========================================================================

    @property
    def poll_interval(self) -> float:
        """Return configured poll interval."""

        return self._poll_interval

    def stats(self) -> dict[str, Any]:
        """Return scheduler statistics."""

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
                "executed_count": (
                    self._executed_count
                ),
                "failed_count": (
                    self._failed_count
                ),
                "cancelled_count": (
                    self._cancelled_count
                ),
                "poll_interval": (
                    self._poll_interval
                ),
                "started_at": (
                    datetime.fromtimestamp(
                        self._started_at,
                        tz=timezone.utc,
                    ).isoformat()
                    if self._started_at
                    else None
                ),
            }

    def diagnostics(self) -> dict[str, Any]:
        """Return detailed scheduler diagnostics."""

        data = self.stats()

        data.update(
            {
                "module": "core.scheduler",
                "thread_alive": bool(
                    self._thread
                    and self._thread.is_alive()
                ),
                "worker_name": (
                    self._thread.name
                    if self._thread
                    else None
                ),
            }
        )

        return data

    # ========================================================================
    # Validation
    # ========================================================================

    @staticmethod
    def _validate_job_id(
        job_id: str,
    ) -> str:

        if not isinstance(
            job_id,
            str,
        ):
            raise SchedulerValidationError(
                "job_id must be a string."
            )

        job_id = job_id.strip()

        if not job_id:
            raise SchedulerValidationError(
                "job_id cannot be empty."
            )

        return job_id

    @staticmethod
    def _validate_name(
        name: str,
    ) -> str:

        if name is None:
            return ""

        if not isinstance(
            name,
            str,
        ):
            raise SchedulerValidationError(
                "Job name must be a string."
            )

        return name.strip()

    @staticmethod
    def _validate_delay(
        delay_seconds: float,
    ) -> None:

        if isinstance(
            delay_seconds,
            bool,
        ):
            raise SchedulerValidationError(
                "delay_seconds must be numeric."
            )

        try:
            value = float(
                delay_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                "delay_seconds must be numeric."
            ) from exc

        if value < 0:
            raise SchedulerValidationError(
                "delay_seconds cannot be negative."
            )

    @staticmethod
    def _validate_interval(
        interval_seconds: float,
    ) -> None:

        if isinstance(
            interval_seconds,
            bool,
        ):
            raise SchedulerValidationError(
                "interval_seconds must be numeric."
            )

        try:
            value = float(
                interval_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SchedulerValidationError(
                "interval_seconds must be numeric."
            ) from exc

        if value < MIN_INTERVAL_SECONDS:
            raise SchedulerValidationError(
                f"interval_seconds must be at least "
                f"{MIN_INTERVAL_SECONDS}."
            )

    # ========================================================================
    # Helpers
    # ========================================================================

    @staticmethod
    def _job_to_info(
        job: ScheduledJob,
    ) -> JobInfo:

        return JobInfo(
            id=job.id,
            name=job.name,
            run_at=datetime.fromtimestamp(
                job.sort_index
            ).astimezone(),
            recurring=job.recurring,
            interval_seconds=job.interval_seconds,
            status=job.status,
            created_at=datetime.fromtimestamp(
                job.created_at
            ).astimezone(),
            run_count=job.run_count,
            last_run_at=(
                datetime.fromtimestamp(
                    job.last_run_at
                ).astimezone()
                if job.last_run_at
                else None
            ),
            last_error=job.last_error,
            metadata=dict(
                job.metadata
            ),
        )

    @staticmethod
    def _emit_task_scheduled(
        job: ScheduledJob,
        run_at: datetime,
    ) -> None:

        try:
            event_bus.emit(
                Events.TASK_SCHEDULED,
                {
                    "id": job.id,
                    "name": job.name,
                    "run_at": run_at.isoformat(),
                    "recurring": job.recurring,
                    "interval_seconds": (
                        job.interval_seconds
                    ),
                },
            )

        except Exception:
            logger.exception(
                "Failed to emit TASK_SCHEDULED event "
                "for job '%s'.",
                job.name or job.id,
            )


# ============================================================================
# Module-level singleton
# ============================================================================


scheduler = Scheduler()


# ============================================================================
# Convenience functions
# ============================================================================


def schedule_once(
    run_at: datetime,
    callback: Callback | None = None,
    name: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Schedule a one-time job using the global scheduler."""

    return scheduler.schedule_once(
        run_at,
        callback,
        name,
        metadata,
    )


def schedule_after(
    delay_seconds: float,
    callback: Callback | None = None,
    name: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Schedule a delayed job using the global scheduler."""

    return scheduler.schedule_after(
        delay_seconds,
        callback,
        name,
        metadata,
    )


def schedule_recurring(
    interval_seconds: float,
    callback: Callback | None = None,
    name: str = "",
    start_immediately: bool = False,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Schedule a recurring job using the global scheduler."""

    return scheduler.schedule_recurring(
        interval_seconds,
        callback,
        name,
        start_immediately,
        metadata,
    )


def cancel_job(
    job_id: str,
) -> bool:
    """Cancel a global scheduler job."""

    return scheduler.cancel(
        job_id
    )


def get_scheduler() -> Scheduler:
    """Return the global Scheduler instance."""

    return scheduler


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "JobInfo",
    "JobNotFoundError",
    "JobStatus",
    "ScheduledJob",
    # Core
    "Scheduler",
    # Exceptions
    "SchedulerError",
    "SchedulerStateError",
    "SchedulerValidationError",
    "cancel_job",
    "get_scheduler",
    "schedule_after",
    # Convenience API
    "schedule_once",
    "schedule_recurring",
    # Singleton
    "scheduler",
]
