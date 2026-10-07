"""
ReminderService - persistent reminders for Jarvis, stored in SQLite.

Shares the Jarvis database (data/jarvis_memory.db) with MemoryService, so the
chat process (which creates reminders) and the background scheduler (which
delivers them) always see the same data. SQLite in WAL mode handles the two
processes safely.

Times:
    - Stored as UTC ISO strings (fixed format, so they sort and compare as text).
    - Recurrence is calculated in LOCAL time, so "every day at 08:00" stays at
      08:00 across daylight-saving changes.

Reserved for later:
    - `calendar_event_id` links a reminder to an event once CalendarService exists.

Architecture:
    ReminderAgent / Scheduler -> ReminderService -> SQLite
"""

from __future__ import annotations

import calendar
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Config.DATA_DIR / "jarvis_memory.db"
RECURRENCES = ("none", "daily", "weekdays", "weekly", "monthly")
RECURRENCE_LABELS = {
    "none": "en gång",
    "daily": "varje dag",
    "weekdays": "varje vardag",
    "weekly": "varje vecka",
    "monthly": "varje månad",
}
DEFAULT_CATEGORIES = [
    "# Kategorier för påminnelser (och senare kalendern). En per rad.",
    "# Lägg gärna till egna, t.ex. ett namn per barn. Filen är privat (data/ pushas aldrig).",
    "Privat",
    "Familj",
    "VerkstadsFlow",
    "Skola",
    "Jobb",
]


def _to_utc_text(moment: datetime) -> str:
    """Normalize any aware/naive-local datetime to a fixed-format UTC string."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _utc_now_text() -> str:
    return _to_utc_text(datetime.now(timezone.utc))


@dataclass(frozen=True)
class Reminder:
    """A stored reminder. `due_at` is the next occurrence (aware, UTC)."""

    id: int
    text: str
    due_at: datetime
    recurrence: str
    category: str
    status: str
    calendar_event_id: Optional[str]
    created_at: str
    last_fired_at: Optional[str]

    @property
    def due_local(self) -> datetime:
        return self.due_at.astimezone()


class ReminderServiceError(Exception):
    """Raised for invalid reminder operations."""


class ReminderService:
    """Create, list, cancel and fire reminders. Thread-safe (one connection per thread)."""

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._initialize_schema()
        self._ensure_categories_file()
        logger.info("ReminderService initialized (db_path=%s)", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        text: str,
        due: datetime,
        recurrence: str = "none",
        category: str = "",
    ) -> Reminder:
        """Store a new reminder. `due` may be naive (treated as local time) or aware."""
        text = " ".join(text.split())
        if not text:
            raise ReminderServiceError("Reminder text cannot be empty.")
        if recurrence not in RECURRENCES:
            raise ReminderServiceError(f"Invalid recurrence '{recurrence}'.")

        due_aware = due if due.tzinfo else due.astimezone()
        if recurrence == "none" and due_aware <= datetime.now(timezone.utc):
            raise ReminderServiceError("The time has already passed.")

        conn = self._conn()
        cursor = conn.execute(
            """
            INSERT INTO reminders (text, due_at, recurrence, category, status, created_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (text, _to_utc_text(due_aware), recurrence, category.strip(), _utc_now_text()),
        )
        reminder = self.get(int(cursor.lastrowid))
        logger.info("Reminder %s created (due %s, %s).", reminder.id, reminder.due_at.isoformat(), recurrence)
        event_bus.publish(
            "reminder.created", "reminders", f"Ny påminnelse: {reminder.text}",
            reminder_id=reminder.id, due_at=reminder.due_at.isoformat(),
            recurrence=recurrence, category=reminder.category,
        )
        return reminder

    def get(self, reminder_id: int) -> Optional[Reminder]:
        row = self._conn().execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return self._row_to_reminder(row) if row else None

    def list_upcoming(self, limit: int = 25) -> list[Reminder]:
        """Active reminders, soonest first."""
        rows = self._conn().execute(
            "SELECT * FROM reminders WHERE status = 'active' ORDER BY due_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def cancel(self, reminder_id: int) -> bool:
        reminder = self.get(reminder_id)
        cursor = self._conn().execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'active'",
            (reminder_id,),
        )
        if cursor.rowcount:
            logger.info("Reminder %s cancelled.", reminder_id)
            event_bus.publish("reminder.cancelled", "reminders", f"Borttagen påminnelse: {reminder.text if reminder else reminder_id}", reminder_id=reminder_id)
        return bool(cursor.rowcount)

    def due(self, now: Optional[datetime] = None) -> list[Reminder]:
        """Active reminders whose time has come (including ones missed while the PC was off)."""
        moment = _to_utc_text(now or datetime.now(timezone.utc))
        rows = self._conn().execute(
            "SELECT * FROM reminders WHERE status = 'active' AND due_at <= ? ORDER BY due_at ASC",
            (moment,),
        ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def mark_fired(self, reminder: Reminder, now: Optional[datetime] = None) -> Optional[datetime]:
        """
        Record that a reminder was delivered. One-off reminders become 'done';
        recurring ones move to their next FUTURE occurrence (missed occurrences
        are skipped, not delivered in a burst). Returns the next due time, if any.
        """
        now_utc = now or datetime.now(timezone.utc)
        conn = self._conn()

        if reminder.recurrence == "none":
            conn.execute(
                "UPDATE reminders SET status = 'done', last_fired_at = ? WHERE id = ?",
                (_to_utc_text(now_utc), reminder.id),
            )
            return None

        next_due = next_occurrence(reminder.due_local, reminder.recurrence)
        while next_due <= now_utc:
            next_due = next_occurrence(next_due, reminder.recurrence)

        conn.execute(
            "UPDATE reminders SET due_at = ?, last_fired_at = ? WHERE id = ?",
            (_to_utc_text(next_due), _to_utc_text(now_utc), reminder.id),
        )
        return next_due

    def categories(self) -> list[str]:
        """Categories from data/reminder_categories.txt (comment lines ignored)."""
        try:
            lines = Config.REMINDER_CATEGORIES_FILE.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return []
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

    def close(self) -> None:
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            self._local.connection = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.connection = conn
        return conn

    def _initialize_schema(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                text               TEXT NOT NULL,
                due_at             TEXT NOT NULL,
                recurrence         TEXT NOT NULL DEFAULT 'none'
                                   CHECK (recurrence IN ('none','daily','weekdays','weekly','monthly')),
                category           TEXT NOT NULL DEFAULT '',
                status             TEXT NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active','done','cancelled')),
                calendar_event_id  TEXT,
                created_at         TEXT NOT NULL,
                last_fired_at      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders (status, due_at);
            """
        )

    @staticmethod
    def _ensure_categories_file() -> None:
        path = Config.REMINDER_CATEGORIES_FILE
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(DEFAULT_CATEGORIES) + "\n", encoding="utf-8")

    @staticmethod
    def _row_to_reminder(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            text=row["text"],
            due_at=datetime.fromisoformat(row["due_at"]),
            recurrence=row["recurrence"],
            category=row["category"],
            status=row["status"],
            calendar_event_id=row["calendar_event_id"],
            created_at=row["created_at"],
            last_fired_at=row["last_fired_at"],
        )


def next_occurrence(previous: datetime, recurrence: str) -> datetime:
    """
    Next occurrence after `previous`, calculated in local wall-clock time so the
    hour stays the same across daylight-saving changes. Returns an aware datetime.
    """
    local = previous.astimezone().replace(tzinfo=None)  # naive local wall-clock time

    if recurrence == "daily":
        candidate = local + timedelta(days=1)
    elif recurrence == "weekdays":
        candidate = local + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    elif recurrence == "weekly":
        candidate = local + timedelta(weeks=1)
    elif recurrence == "monthly":
        year = local.year + (local.month // 12)
        month = local.month % 12 + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        candidate = local.replace(year=year, month=month, day=day)
    else:
        raise ReminderServiceError(f"'{recurrence}' does not repeat.")

    return candidate.astimezone()  # interpret as local time -> aware
