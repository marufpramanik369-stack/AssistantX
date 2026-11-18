"""core/reminders.py - timed reminders for JEROX (prayer, sleep) plus game mode."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

# ---------------- Edit these when times change ----------------
PRAYERS = [
    ("Fajr", "05:30"),
    ("Dhuhr", "13:15"),
    ("Asr", "16:10"),
    ("Maghrib", "17:25"),
    ("Isha", "18:20"),
]
PRAYER_LEAD_MIN = 15
SLEEP_REMINDER = "00:30"
GAME_MODE_TIMEOUT_MIN = 120
CHECK_EVERY_SEC = 15
LATE_GRACE_MIN = 5   # if the app was busy/closed, skip reminders older than this
# ---------------------------------------------------------------


@dataclass(frozen=True)
class Reminder:
    key: str
    kind: str        # "prayer" or "sleep"
    name: str
    due: datetime    # when to fire
    clock: str       # jamaat time (prayer) or reminder time (sleep), "HH:MM"


def _at(day: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def pretty_time(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def reminders_for(day: datetime) -> list[Reminder]:
    out = []
    for name, hhmm in PRAYERS:
        due = _at(day, hhmm) - timedelta(minutes=PRAYER_LEAD_MIN)
        out.append(Reminder(f"prayer:{name}:{day:%Y-%m-%d}", "prayer", name, due, hhmm))
    out.append(Reminder(f"sleep:{day:%Y-%m-%d}", "sleep", "Sleep",
                        _at(day, SLEEP_REMINDER), SLEEP_REMINDER))
    return out


def ai_prompt(r: Reminder) -> str:
    """Instruction sent to JEROX so it words the reminder itself (in Bangla, per profile)."""
    if r.kind == "prayer":
        return (
            "[Automatic reminder, not typed by the user] Remind Maruf in Bangla, in one or two "
            f"short warm friendly sentences, that the {r.name} congregation (jamaat) at his mosque "
            f"starts at {pretty_time(r.clock)}, which is {PRAYER_LEAD_MIN} minutes from now. "
            "Say nothing else."
        )
    return (
        "[Automatic reminder, not typed by the user] Remind Maruf in Bangla, in one or two short "
        f"caring sentences, that it is about {pretty_time(r.clock)} and he should go to sleep soon. "
        "Say nothing else."
    )


def fallback_text(r: Reminder) -> str:
    if r.kind == "prayer":
        return f"Maruf, {r.name} jamaat is at {pretty_time(r.clock)}, in {PRAYER_LEAD_MIN} minutes."
    return f"Maruf, it is about {pretty_time(r.clock)}. Time to go to sleep."


class ReminderScheduler:
    def __init__(self, on_fire: Callable[[Reminder], None],
                 now_func: Callable[[], datetime] = datetime.now) -> None:
        self._on_fire = on_fire
        self._now = now_func
        self._fired: set[str] = set()
        self._game_until: Optional[datetime] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ----- game mode -----
    def set_game_mode(self, on: bool) -> None:
        with self._lock:
            self._game_until = (
                self._now() + timedelta(minutes=GAME_MODE_TIMEOUT_MIN) if on else None
            )

    @property
    def game_mode(self) -> bool:
        with self._lock:
            if self._game_until is None:
                return False
            if self._now() >= self._game_until:
                self._game_until = None
                return False
            return True

    # ----- scheduling -----
    def tick(self) -> None:
        now = self._now()
        game = self.game_mode
        if len(self._fired) > 200:
            self._fired.clear()
        for r in reminders_for(now):
            if r.key in self._fired:
                continue
            if not (r.due <= now < r.due + timedelta(minutes=LATE_GRACE_MIN)):
                continue
            self._fired.add(r.key)
            if game and r.kind != "prayer":
                continue   # game mode: only prayer reminders get through
            try:
                self._on_fire(r)
            except Exception:
                pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(CHECK_EVERY_SEC):
                try:
                    self.tick()
                except Exception:
                    pass

        self._thread = threading.Thread(target=loop, daemon=True, name="jerox-reminders")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


if __name__ == "__main__":
    # Self-test with a fake clock (nothing is spoken).
    clock = [datetime(2026, 11, 15, 5, 14)]
    fired: list[str] = []
    s = ReminderScheduler(lambda r: fired.append(r.key), now_func=lambda: clock[0])

    def at(h: int, m: int) -> None:
        clock[0] = clock[0].replace(hour=h, minute=m)
        s.tick()

    at(5, 14); at(5, 15); at(5, 16)                 # Fajr fires once at 5:15
    at(0, 29); s.set_game_mode(True); at(0, 30)     # sleep reminder muted in game mode
    at(17, 9); s.set_game_mode(True); at(17, 10)    # Maghrib still fires in game mode
    s.set_game_mode(False); at(12, 59); at(13, 0)   # Dhuhr fires at 1:00 pm
    expected = ["prayer:Fajr:2026-11-15", "prayer:Maghrib:2026-11-15", "prayer:Dhuhr:2026-11-15"]
    print("FIRED:", fired)
    print("TEST PASSED" if fired == expected else "TEST FAILED")
