"""
scheduler.py
============
Lightweight background scheduler for reminders and periodic/one-off
tasks, without requiring a heavy dependency like APScheduler (though
this module's API is intentionally similar, so swapping later is easy).

Two kinds of scheduled work are supported:
    - `schedule_once(run_at, callback)` — fire once at a specific datetime.
    - `schedule_recurring(interval_seconds, callback)` — fire repeatedly.

A single background daemon thread polls a min-heap of pending jobs once
per second. This is more than precise enough for a personal assistant
(reminders, periodic cache cleanup, etc.) without the overhead of a full
cron-style engine.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from config.constants import TASKS_JSON
from core.event_bus import Events, event_bus
from core.logger import get_logger
from core.utils import now_iso, read_json, write_json

logger = get_logger(__name__)

Callback = Callable[[], None]

_counter = itertools.count()  # tie-breaker for heap entries with equal timestamps


@dataclass(order=True)
class ScheduledJob:
    """
    An internal heap entry. `sort_index` (the run timestamp) is what the
    heap orders by; everything else is excluded from comparison via
    `field(compare=False)`.
    """

    sort_index: float
    tie_breaker: int = field(compare=True)
    id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4()))
    name: str = field(compare=False, default="")
    callback: Optional[Callback] = field(compare=False, default=None)
    recurring: bool = field(compare=False, default=False)
    interval_seconds: float = field(compare=False, default=0.0)
    cancelled: bool = field(compare=False, default=False)
    metadata: dict = field(compare=False, default_factory=dict)


class Scheduler:
    """Thread-safe background job scheduler."""

    def __init__(self, poll_interval_seconds: float = 1.0) -> None:
        self._heap: list[ScheduledJob] = []
        self._jobs_by_id: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        """Start the background polling thread. Safe to call once at startup."""
        if self._thread and self._thread.is_alive():
            logger.debug("Scheduler already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="scheduler", daemon=True)
        self._thread.start()
        logger.info("Scheduler started (poll interval=%.1fs).", self._poll_interval)

    def stop(self) -> None:
        """Signal the background thread to stop and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self._poll_interval + 1)
        logger.info("Scheduler stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._process_due_jobs()
            self._stop_event.wait(self._poll_interval)

    def _process_due_jobs(self) -> None:
        now_ts = time.time()
        due_jobs: list[ScheduledJob] = []

        with self._lock:
            while self._heap and self._heap[0].sort_index <= now_ts:
                job = heapq.heappop(self._heap)
                if job.cancelled:
                    self._jobs_by_id.pop(job.id, None)
                    continue
                due_jobs.append(job)

                if job.recurring:
                    job.sort_index = now_ts + job.interval_seconds
                    job.tie_breaker = next(_counter)
                    heapq.heappush(self._heap, job)
                else:
                    self._jobs_by_id.pop(job.id, None)

        for job in due_jobs:
            self._execute(job)

    def _execute(self, job: ScheduledJob) -> None:
        logger.info("Running scheduled job '%s' (id=%s).", job.name or job.id, job.id)
        event_bus.emit(Events.REMINDER_DUE, {"id": job.id, "name": job.name, "metadata": job.metadata})
        if job.callback:
            try:
                job.callback()
            except Exception:  # noqa: BLE001
                logger.exception("Scheduled job '%s' raised an exception.", job.name or job.id)

    # -- scheduling API ------------------------------------------------------ #

    def schedule_once(
        self,
        run_at: datetime,
        callback: Optional[Callback] = None,
        name: str = "",
        metadata: Optional[dict] = None,
    ) -> str:
        """Schedule `callback` to run once at the given datetime. Returns job id."""
        job = ScheduledJob(
            sort_index=run_at.timestamp(),
            tie_breaker=next(_counter),
            name=name,
            callback=callback,
            recurring=False,
            metadata=metadata or {},
        )
        self._add_job(job)
        event_bus.emit(Events.TASK_SCHEDULED, {"id": job.id, "name": name, "run_at": run_at.isoformat()})
        logger.info("Scheduled one-off job '%s' for %s.", name or job.id, run_at)
        return job.id

    def schedule_after(
        self,
        delay_seconds: float,
        callback: Optional[Callback] = None,
        name: str = "",
        metadata: Optional[dict] = None,
    ) -> str:
        """Convenience wrapper: schedule `callback` to run `delay_seconds` from now."""
        return self.schedule_once(
            datetime.now() + timedelta(seconds=delay_seconds), callback, name, metadata
        )

    def schedule_recurring(
        self,
        interval_seconds: float,
        callback: Optional[Callback] = None,
        name: str = "",
        start_immediately: bool = False,
        metadata: Optional[dict] = None,
    ) -> str:
        """Schedule `callback` to run every `interval_seconds`. Returns job id."""
        first_run = time.time() if start_immediately else time.time() + interval_seconds
        job = ScheduledJob(
            sort_index=first_run,
            tie_breaker=next(_counter),
            name=name,
            callback=callback,
            recurring=True,
            interval_seconds=interval_seconds,
            metadata=metadata or {},
        )
        self._add_job(job)
        logger.info("Scheduled recurring job '%s' every %.1fs.", name or job.id, interval_seconds)
        return job.id

    def _add_job(self, job: ScheduledJob) -> None:
        with self._lock:
            heapq.heappush(self._heap, job)
            self._jobs_by_id[job.id] = job

    def cancel(self, job_id: str) -> bool:
        """
        Cancel a pending job by id. The entry is lazily removed from the
        heap on its next pop (marking cancelled avoids O(n) heap surgery).
        """
        with self._lock:
            job = self._jobs_by_id.get(job_id)
            if job:
                job.cancelled = True
                del self._jobs_by_id[job_id]
                logger.info("Cancelled scheduled job %s.", job_id)
                return True
        return False

    def pending_jobs(self) -> list[dict]:
        """Return a snapshot of currently pending (non-cancelled) jobs."""
        with self._lock:
            return [
                {
                    "id": j.id,
                    "name": j.name,
                    "run_at": datetime.fromtimestamp(j.sort_index).isoformat(),
                    "recurring": j.recurring,
                }
                for j in self._jobs_by_id.values()
                if not j.cancelled
            ]


# Module-level singleton.
scheduler: Scheduler = Scheduler()
