"""
Clock helpers for Jarvis.

Language models have no clock and "live" in their training period, so every
agent prompt gets the current local date and time from here.
"""

from datetime import datetime

_WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
_MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli",
           "augusti", "september", "oktober", "november", "december")


def current_datetime_text() -> str:
    """Return e.g. 'måndag 28 september 2026, kl. 14:03 (vecka 40)' in local time."""
    now = datetime.now().astimezone()
    week = now.isocalendar().week
    return (
        f"{_WEEKDAYS[now.weekday()]} {now.day} {_MONTHS[now.month - 1]} {now.year}, "
        f"kl. {now:%H:%M} (vecka {week})"
    )
