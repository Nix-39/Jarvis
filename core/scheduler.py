"""
Jarvis background scheduler - the always-on part of the second brain.

Runs as its own process (no window), independent of the chat:
    - Checks for due reminders every SCHEDULER_POLL_SECONDS and delivers them
      through NotificationService (Windows toast, Telegram).
    - Reminders missed while the computer was off are delivered on start,
      marked as late. Recurring reminders then move to their next future time.
    - Only one scheduler can run at a time (localhost port lock).

Start manually:      .venv\\Scripts\\python -m core.scheduler
Test notification:   .venv\\Scripts\\python -m core.scheduler --test-notification
Run once and exit:   .venv\\Scripts\\python -m core.scheduler --once
Autostart at login:  scripts\\install_scheduler.ps1

Logs go to logs/jarvis_scheduler.log (separate from the chat's jarvis.log).
"""

import os
import sys

# Must be set before core.logger is imported anywhere.
os.environ.setdefault("JARVIS_LOG_FILE", "jarvis_scheduler.log")

# Started with pythonw (no window) there is no console: give logging a sink.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import socket  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Optional  # noqa: E402

from core.clock import format_datetime_sv  # noqa: E402
from core.config import Config  # noqa: E402
from core.logger import get_logger  # noqa: E402
from services.notification_service import NotificationService  # noqa: E402
from services.reminder_service import RECURRENCE_LABELS, ReminderService  # noqa: E402

logger = get_logger(__name__)

LATE_THRESHOLD = timedelta(minutes=5)


class Scheduler:
    """Delivers due reminders. Stateless between checks - SQLite holds all state."""

    def __init__(
        self,
        reminder_service: Optional[ReminderService] = None,
        notification_service: Optional[NotificationService] = None,
    ) -> None:
        self.reminders = reminder_service or ReminderService()
        self.notifications = notification_service or NotificationService()

    def check_once(self, now: Optional[datetime] = None) -> int:
        """Deliver every due reminder. Returns how many were delivered."""
        now_utc = now or datetime.now(timezone.utc)
        delivered = 0

        for reminder in self.reminders.due(now_utc):
            late = now_utc - reminder.due_at > LATE_THRESHOLD
            title = "⏰ Jarvis påminnelse" + (" (försenad)" if late else "")
            message = reminder.text
            if reminder.category:
                message += f"\n[{reminder.category}]"
            if late:
                message += f"\nSkulle ha kommit {format_datetime_sv(reminder.due_at)}."

            if not self.notifications.notify(title, message):
                logger.warning("Reminder %s not delivered; will retry next check.", reminder.id)
                continue

            next_due = self.reminders.mark_fired(reminder, now_utc)
            delivered += 1
            if next_due:
                logger.info(
                    "Reminder %s delivered; next %s (%s).",
                    reminder.id, format_datetime_sv(next_due), RECURRENCE_LABELS[reminder.recurrence],
                )
            else:
                logger.info("Reminder %s delivered and completed.", reminder.id)

        return delivered

    def run_forever(self) -> None:
        logger.info("Scheduler started (poll every %ss).", Config.SCHEDULER_POLL_SECONDS)
        while True:
            try:
                self.check_once()
            except Exception as exc:
                # Never die on a single failure (e.g. database briefly locked).
                logger.error("Scheduler check failed: %s", exc)
            time.sleep(Config.SCHEDULER_POLL_SECONDS)


def _acquire_single_instance_lock() -> Optional[socket.socket]:
    """Bind a localhost port as a process-wide lock. None if another scheduler runs."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", Config.SCHEDULER_LOCK_PORT))
    except OSError:
        lock.close()
        return None
    return lock


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Jarvis background scheduler")
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--test-notification", action="store_true", help="send a test notification and exit")
    args = parser.parse_args()

    if args.test_notification:
        ok = NotificationService().notify("⏰ Jarvis testnotis", "Om du ser den här fungerar notiserna.")
        print("Test notification delivered." if ok else "Test notification FAILED - see logs/jarvis_scheduler.log")
        return

    if args.once:
        print(f"Delivered {Scheduler().check_once()} reminder(s).")
        return

    lock = _acquire_single_instance_lock()
    if lock is None:
        print("Another Jarvis scheduler is already running.")
        logger.info("Another scheduler instance is running; exiting.")
        return

    try:
        Scheduler().run_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
    finally:
        lock.close()


if __name__ == "__main__":
    main()
