"""
reminder_service.py
====================
User-facing reminders: "remind me to call mom in 20 minutes", "remind me
tomorrow at 5pm to submit the report".

Combines two lower-level building blocks that each solve half the
problem on their own:
    - database.db_manager's `tasks` table — durable storage, so
      reminders survive an app restart (core/scheduler.py's job queue
      is purely in-memory and would otherwise forget everything on quit).
    - core.scheduler.scheduler — the actual background timer that fires
      a notification at the right moment while the app is running.

On startup, `resync_pending_reminders()` re-hydrates the scheduler from
any reminders persisted in the database whose due time hasn't passed
yet, so reminders set in a previous session still fire correctly.

Natural language time parsing is intentionally a lightweight, dependency
-free implementation covering the common spoken patterns ("in N
minutes/hours", "tomorrow [at H(:MM)(am/pm)]", "on <weekday>", "at
H(:MM)(am/pm)") rather than pulling in a full NLP date parser — good
enough for the vast majority of voice reminder requests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from automation.notifications import NotificationError, notify_reminder
from core.logger import get_logger
from core.scheduler import scheduler as default_scheduler
from database import Task, db_manager

logger = get_logger(__name__)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DEFAULT_TIME_OF_DAY = (9, 0)  # 9:00 AM — used when a day is specified without a time

# In-memory map of task_id -> scheduler job_id, so cancel_reminder() can
# also cancel the live scheduler timer, not just mark the DB row. This
# is rebuilt on every startup by resync_pending_reminders(), since
# core.scheduler's jobs don't themselves survive a restart.
_active_job_ids: dict[int, str] = {}


class ReminderServiceError(RuntimeError):
    """Raised when a reminder can't be created (unparseable time) or found."""


@dataclass
class Reminder:
    id: int
    text: str
    due_at: datetime
    status: str  # 'pending', 'completed', 'cancelled'

    @classmethod
    def from_task(cls, task: Task) -> Reminder:
        due = task.due_at_dt or datetime.now(tz=timezone.utc)
        return cls(id=task.id, text=task.title, due_at=due, status=task.status)

    def is_due_soon(self, within_minutes: int = 15) -> bool:
        return self.status == "pending" and timedelta() <= (self.due_at - datetime.now(tz=timezone.utc)) <= timedelta(minutes=within_minutes)


# --------------------------------------------------------------------------- #
# Natural language time parsing
# --------------------------------------------------------------------------- #

_RELATIVE_PATTERN = re.compile(
    r"\bin\s+(?P<amount>\d+)\s*(?P<unit>second|minute|hour|day|week)s?\b", re.IGNORECASE
)
_TIME_OF_DAY_PATTERN = re.compile(
    r"\bat\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?\b", re.IGNORECASE
)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TODAY_PATTERN = re.compile(r"\btoday\b|\btonight\b", re.IGNORECASE)
_WEEKDAY_PATTERN = re.compile(
    r"\bon\s+(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE
)


def parse_natural_time(text: str, base: datetime | None = None) -> datetime:
    """
    Parse a natural-language time expression into a concrete datetime.

    Supported patterns (combinable where sensible):
        - "in 10 minutes", "in 2 hours", "in 3 days"
        - "tomorrow", "tomorrow at 5pm", "tomorrow at 9:30am"
        - "today at 6pm", "tonight at 9"
        - "on monday", "on friday at 2pm"
        - "at 5pm", "at 14:30" (defaults to today, or tomorrow if that
          time has already passed today)

    Args:
        text: The natural language time expression (may be embedded in
            a longer reminder utterance — only the time-related portion
            is matched; the rest is ignored by this function).
        base: Reference "now" to compute relative times from. Defaults
            to the actual current time — overridable for testing.

    Raises:
        ReminderServiceError: if no recognizable time expression is found.
    """
    now = base or datetime.now(tz=timezone.utc)

    relative_match = _RELATIVE_PATTERN.search(text)
    if relative_match:
        amount = int(relative_match.group("amount"))
        unit = relative_match.group("unit").lower()
        delta = {
            "second": timedelta(seconds=amount),
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
        }[unit]
        return now + delta

    target_date = now.date()
    explicit_day = False

    if _TOMORROW_PATTERN.search(text):
        target_date = now.date() + timedelta(days=1)
        explicit_day = True
    elif _TODAY_PATTERN.search(text):
        target_date = now.date()
        explicit_day = True

    weekday_match = _WEEKDAY_PATTERN.search(text)
    if weekday_match:
        target_weekday = _WEEKDAYS.index(weekday_match.group("day").lower())
        days_ahead = (target_weekday - now.weekday()) % 7
        days_ahead = days_ahead or 7  # "on monday" said on a Monday means *next* Monday
        target_date = now.date() + timedelta(days=days_ahead)
        explicit_day = True

    time_match = _TIME_OF_DAY_PATTERN.search(text)
    if time_match:
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        meridiem = (time_match.group("meridiem") or "").lower()

        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        candidate = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)

        if not explicit_day and candidate <= now:
            # "at 5pm" said after 5pm today implicitly means tomorrow.
            candidate += timedelta(days=1)

        return candidate

    if explicit_day:
        # A day was specified ("tomorrow", "on friday") with no explicit
        # time — default to a sensible morning reminder time.
        return datetime.combine(target_date, datetime.min.time()).replace(
            hour=_DEFAULT_TIME_OF_DAY[0], minute=_DEFAULT_TIME_OF_DAY[1]
        )

    raise ReminderServiceError(
        f"Could not understand the time in '{text}'. "
        f"Try phrasing like 'in 10 minutes', 'tomorrow at 5pm', or 'on friday'."
    )


def strip_time_expression(text: str) -> str:
    """
    Remove the recognized time expression from a reminder utterance,
    leaving just the reminder content — e.g. "call mom in 10 minutes"
    -> "call mom". Used so the stored reminder title doesn't awkwardly
    repeat the scheduling phrase.
    """
    cleaned = text
    for pattern in (_RELATIVE_PATTERN, _TIME_OF_DAY_PATTERN, _TOMORROW_PATTERN, _TODAY_PATTERN, _WEEKDAY_PATTERN):
        cleaned = pattern.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.")


# --------------------------------------------------------------------------- #
# Reminder CRUD + scheduling
# --------------------------------------------------------------------------- #

def _fire_reminder(task_id: int, text: str) -> None:
    """Callback invoked by the scheduler when a reminder's time arrives."""
    try:
        notify_reminder(text)
    except NotificationError as exc:
        logger.warning("Could not show desktop notification for reminder %d: %s", task_id, exc)

    try:
        db_manager.update_task_status(task_id, "completed")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark reminder task %d completed: %s", task_id, exc)

    _active_job_ids.pop(task_id, None)
    logger.info("Reminder fired: [%d] %s", task_id, text)


def create_reminder(
    text: str,
    when: str | None = None,
    scheduler=default_scheduler,
) -> Reminder:
    """
    Create and schedule a new reminder.

    Args:
        text: The full reminder utterance, e.g. "call mom in 10 minutes",
            OR just the reminder content if `when` is supplied separately.
        when: Optional explicit time expression, if the caller has
            already separated content from timing (e.g.
            brain/classifier.py extracted them as distinct entities).
            If omitted, the time expression is parsed out of `text` itself.
        scheduler: Injectable scheduler instance (defaults to the shared
            app-wide scheduler) — mainly a testing seam.

    Raises:
        ReminderServiceError: if no valid time could be determined.
    """
    time_source = when if when is not None else text
    due_at = parse_natural_time(time_source)

    reminder_content = strip_time_expression(text) if when is None else text.strip()
    if not reminder_content:
        reminder_content = "Reminder"

    task_id = db_manager.create_task(title=reminder_content, due_at=due_at.isoformat())

    job_id = scheduler.schedule_once(
        run_at=due_at,
        callback=lambda: _fire_reminder(task_id, reminder_content),
        name=f"reminder:{task_id}",
        metadata={"task_id": task_id, "kind": "reminder"},
    )
    _active_job_ids[task_id] = job_id

    logger.info("Created reminder [%d] '%s' due at %s.", task_id, reminder_content, due_at)
    return Reminder(id=task_id, text=reminder_content, due_at=due_at, status="pending")


def list_reminders(include_completed: bool = False) -> list[Reminder]:
    """Return all stored reminders, optionally including completed/cancelled ones."""
    if include_completed:
        pending = db_manager.get_tasks(status="pending")
        completed = db_manager.get_tasks(status="completed")
        cancelled = db_manager.get_tasks(status="cancelled")
        rows = pending + completed + cancelled
    else:
        rows = db_manager.get_tasks(status="pending")

    reminders = [Reminder.from_task(Task.from_row(row)) for row in rows if row.get("due_at")]
    reminders.sort(key=lambda r: r.due_at)
    return reminders


def get_reminder(reminder_id: int) -> Reminder | None:
    row = db_manager.get_task(reminder_id)
    if row is None or not row.get("due_at"):
        return None
    return Reminder.from_task(Task.from_row(row))


def cancel_reminder(reminder_id: int, scheduler=default_scheduler) -> bool:
    """
    Cancel a pending reminder: stops its scheduler timer (if the process
    hasn't restarted since it was created/resynced) and marks it
    cancelled in the database.

    Returns:
        True if a matching pending reminder was found and cancelled,
        False if no such pending reminder exists.
    """
    row = db_manager.get_task(reminder_id)
    if row is None or row.get("status") != "pending":
        return False

    job_id = _active_job_ids.pop(reminder_id, None)
    if job_id:
        scheduler.cancel(job_id)

    db_manager.update_task_status(reminder_id, "cancelled")
    logger.info("Cancelled reminder [%d].", reminder_id)
    return True


def cancel_reminder_by_text(query: str, scheduler=default_scheduler) -> Reminder | None:
    """
    Convenience lookup for voice commands like "cancel the reminder
    about calling mom" — finds the best (case-insensitive substring)
    match among pending reminders and cancels it.

    Returns:
        The cancelled Reminder if a match was found, else None.
    """
    query_lower = query.strip().lower()
    for reminder in list_reminders():
        if query_lower in reminder.text.lower():
            cancel_reminder(reminder.id, scheduler=scheduler)
            return reminder
    return None


def resync_pending_reminders(scheduler=default_scheduler) -> int:
    """
    Re-hydrate the in-memory scheduler from persisted, still-pending
    reminders. Must be called once during app startup (see
    core/startup.py) — without this, reminders created in a previous
    session would silently never fire, since core.scheduler.Scheduler
    itself keeps no state across restarts.

    Reminders whose due time has already passed while the app was
    closed fire immediately (rather than being silently dropped), so
    the user still gets notified, just late with an apologetic framing
    left to the notification content itself.

    Returns:
        The number of reminders successfully re-scheduled.
    """
    _active_job_ids.clear()
    resynced = 0

    for reminder in list_reminders(include_completed=False):
        delay = max(0.0, (reminder.due_at - datetime.now(tz=timezone.utc)).total_seconds())
        job_id = scheduler.schedule_after(
            delay_seconds=delay,
            callback=lambda r=reminder: _fire_reminder(r.id, r.text),
            name=f"reminder:{reminder.id}",
            metadata={"task_id": reminder.id, "kind": "reminder"},
        )
        _active_job_ids[reminder.id] = job_id
        resynced += 1

    logger.info("Resynced %d pending reminder(s) into the scheduler.", resynced)
    return resynced

