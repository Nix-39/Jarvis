"""
CalendarService - Urd, the family calendar.

Bookings for each family member, stored locally in SQLite (same database as the
rest of Yggdrasil's memory). Google Calendar sync plugs in later on top of this:
every event has `source` and `external_id` reserved for that.

Event kinds:
    - "event": an ordinary booking (BVC, kalas, möte, resa, cup ...)
    - "work":  a work shift
    - "match": a referee assignment, with structured details:
        {"sport": "fotboll"|"innebandy", "division": "H4", "home": "Floda",
         "away": "Gunnilse", "role": "AD1", "gather": "14:15",
         "officials": [{"role": "HD", "name": "Anders Andersson"}, ...]}

All-day bookings (`all_day`) span whole days: start is local midnight of the
first day, end is local midnight after the last day. They are shown as banners
across the days they cover (a trip, a course, a cup, "Julian hos oss").

Recurring bookings store a rule and are expanded into occurrences when read:
    {"freq": "weekly"|"biweekly"|"monthly", "parity": ""|"even"|"odd", "until": "YYYY-MM-DD"|""}
"parity" pins a weekly rule to even or odd ISO weeks ("varannan jämn vecka").
Single occurrences can be skipped (`skip_dates`, the occurrence's first day)
without touching the rest of the series; an extra or moved day is simply a new
booking.

Times are stored in UTC; naive datetimes are treated as local time.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Config.DATA_DIR / "jarvis_memory.db"
KINDS = ("event", "work", "match")
SPORTS = ("fotboll", "innebandy")
SPORT_ICONS = {"fotboll": "⚽", "innebandy": "🏑"}
FREQS = ("weekly", "biweekly", "monthly")
PARITIES = ("", "even", "odd")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
MAX_SPAN_DAYS = 62
MAX_OCCURRENCES = 1500
MONTHS_SV = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december")


class CalendarServiceError(Exception):
    pass


def _to_utc_text(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.astimezone()
    return aware.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_midnight(day: date) -> datetime:
    """Local midnight of a day, as an aware datetime (DST-correct)."""
    return datetime.combine(day, time.min).astimezone()


def iso_week(day: date) -> int:
    return day.isocalendar()[1]


def role_short(role: str) -> str:
    """'AD1' -> 'AD', 'HD' -> 'HD' (the title shows the role without its number)."""
    return re.sub(r"\d+$", "", (role or "").strip().upper()) or ""


def match_title(details: dict[str, Any]) -> str:
    """'H4 AD Floda - Gunnilse' - the line used in lists and the calendar grid."""
    parts = [details.get("division", "").strip(), role_short(details.get("role", ""))]
    teams = f"{details.get('home', '').strip()} - {details.get('away', '').strip()}".strip(" -")
    return " ".join(p for p in parts + [teams] if p)


def recurrence_label(rule: dict[str, Any]) -> str:
    """'varannan vecka (jämna veckor) t.o.m. 31 december' - empty for one-off bookings."""
    if not rule:
        return ""
    text = {"weekly": "varje vecka", "biweekly": "varannan vecka", "monthly": "varje månad"}.get(rule.get("freq", ""), "")
    if rule.get("parity"):
        text = "varannan vecka" + (" (jämna veckor)" if rule["parity"] == "even" else " (udda veckor)")
    if rule.get("until"):
        until = date.fromisoformat(rule["until"])
        text += f" t.o.m. {until.day} {MONTHS_SV[until.month - 1]}"
    return text


@dataclass(frozen=True)
class CalendarEvent:
    id: int
    person: str
    kind: str
    title: str
    start_at: datetime
    end_at: Optional[datetime]
    location: str
    details: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    source: str = "local"
    all_day: bool = False
    recurrence: dict[str, Any] = field(default_factory=dict)
    skip_dates: tuple[str, ...] = ()
    occurrence: str = ""          # first day (YYYY-MM-DD) when this is one occurrence of a series

    @property
    def key(self) -> str:
        """Unique reference: '5' for a booking, '5@2026-10-15' for one occurrence of a series."""
        return f"{self.id}@{self.occurrence}" if self.occurrence else str(self.id)

    @property
    def first_day(self) -> date:
        return self.start_at.astimezone().date()

    @property
    def last_day(self) -> date:
        """Last day an all-day booking covers (inclusive)."""
        if self.all_day and self.end_at:
            return self.end_at.astimezone().date() - timedelta(days=1)
        return self.first_day

    @property
    def icon(self) -> str:
        return SPORT_ICONS.get(self.details.get("sport", ""), "") if self.kind == "match" else ""

    @property
    def short(self) -> str:
        """Compact line: '⚽ H4 (AD) Floda - Gunnilse' for matches, else the title."""
        if self.kind != "match":
            return self.title
        d = self.details
        role = role_short(d.get("role", ""))
        teams = f"{d.get('home', '')} - {d.get('away', '')}".strip(" -")
        return " ".join(p for p in (self.icon, d.get("division", ""), f"({role})" if role else "", teams) if p)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start_at"] = self.start_at.isoformat()
        data["end_at"] = self.end_at.isoformat() if self.end_at else None
        data["skip_dates"] = list(self.skip_dates)
        data["icon"] = self.icon
        data["short"] = self.short
        data["key"] = self.key
        data["recurrence_label"] = recurrence_label(self.recurrence)
        return data


class CalendarService:
    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._initialize_schema()
        logger.info("CalendarService initialized (db_path=%s)", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        person: str,
        kind: str,
        title: str,
        start: datetime,
        end: Optional[datetime] = None,
        location: str = "",
        details: Optional[dict[str, Any]] = None,
        all_day: bool = False,
        recurrence: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        details = self._validate(kind, details or {})
        if kind == "match" and not title.strip():
            title = match_title(details)
        title = " ".join(title.split())[:200]
        if not title:
            raise CalendarServiceError("Bokningen saknar titel.")
        start, end = self._check_times(start, end, all_day)
        rule = self._validate_recurrence(recurrence or {}, start, end)
        now = _now_text()
        cursor = self._conn().execute(
            """INSERT INTO calendar_events (person, kind, title, start_at, end_at, location, details, status, source,
                                            all_day, recurrence, skip_dates, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'local', ?, ?, '[]', ?, ?)""",
            (person, kind, title, _to_utc_text(start), _to_utc_text(end) if end else None,
             location.strip()[:200], json.dumps(details, ensure_ascii=False), int(all_day),
             json.dumps(rule) if rule else "", now, now),
        )
        event = self.get(int(cursor.lastrowid))
        logger.info("Calendar event %s created (%s, %s%s).", event.id, kind, event.start_at.isoformat(), ", recurring" if rule else "")
        event_bus.publish("calendar.created", "calendar", f"Ny bokning: {event.short}", event_id=event.id, person=person, kind=kind)
        return event

    def update(self, event_id: int, **fields: Any) -> CalendarEvent:
        current = self.get(event_id)
        if current is None or current.status != "active":
            raise CalendarServiceError("Bokningen finns inte.")
        kind = fields.get("kind", current.kind)
        details = self._validate(kind, fields.get("details", current.details))
        all_day = bool(fields.get("all_day", current.all_day))
        start, end = self._check_times(fields.get("start", current.start_at), fields.get("end", current.end_at), all_day)
        rule = self._validate_recurrence(fields.get("recurrence", current.recurrence), start, end)
        title = fields.get("title") or (match_title(details) if kind == "match" else current.title)
        self._conn().execute(
            """UPDATE calendar_events SET person=?, kind=?, title=?, start_at=?, end_at=?, location=?, details=?,
                      all_day=?, recurrence=?, updated_at=? WHERE id=?""",
            (fields.get("person", current.person), kind, title, _to_utc_text(start), _to_utc_text(end) if end else None,
             fields.get("location", current.location), json.dumps(details, ensure_ascii=False), int(all_day),
             json.dumps(rule) if rule else "", _now_text(), event_id),
        )
        event = self.get(event_id)
        event_bus.publish("calendar.updated", "calendar", f"Ändrad bokning: {event.short}", event_id=event_id)
        return event

    def cancel(self, event_id: int) -> bool:
        """Remove a booking (a whole series for recurring bookings)."""
        event = self.get(event_id)
        cursor = self._conn().execute(
            "UPDATE calendar_events SET status='cancelled', updated_at=? WHERE id=? AND status='active'", (_now_text(), event_id)
        )
        if cursor.rowcount:
            logger.info("Calendar event %s cancelled.", event_id)
            event_bus.publish("calendar.cancelled", "calendar", f"Borttagen bokning: {event.short if event else event_id}", event_id=event_id)
        return cursor.rowcount > 0

    def skip(self, event_id: int, occurrence: date) -> bool:
        """Remove one occurrence of a recurring booking; the rest of the series stays."""
        event = self.get(event_id)
        if event is None or event.status != "active" or not event.recurrence:
            return False
        day = occurrence.isoformat()
        if day in event.skip_dates:
            return False
        skips = sorted(set(event.skip_dates) | {day})
        self._conn().execute(
            "UPDATE calendar_events SET skip_dates=?, updated_at=? WHERE id=?", (json.dumps(skips), _now_text(), event_id)
        )
        logger.info("Calendar event %s: occurrence %s skipped.", event_id, day)
        event_bus.publish("calendar.updated", "calendar", f"Borttaget tillfälle: {event.short} {occurrence.day} {MONTHS_SV[occurrence.month - 1]}", event_id=event_id)
        return True

    def get(self, event_id: int) -> Optional[CalendarEvent]:
        row = self._conn().execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
        return self._row(row) if row else None

    def between(self, start: datetime, end: datetime, person: Optional[str] = None, kind: Optional[str] = None) -> list[CalendarEvent]:
        """
        Active bookings that touch [start, end), soonest first. Recurring bookings
        come back as one CalendarEvent per occurrence (with `occurrence` set);
        multi-day bookings that started earlier but are still going on are included.
        """
        lo, hi = _to_utc_text(start), _to_utc_text(end)
        filters, params = "", []
        if person:
            filters += " AND person = ?"; params.append(person)
        if kind:
            filters += " AND kind = ?"; params.append(kind)
        single = self._conn().execute(
            "SELECT * FROM calendar_events WHERE status='active' AND recurrence='' AND start_at < ? "
            "AND (start_at >= ? OR COALESCE(end_at, start_at) > ?)" + filters + " ORDER BY start_at LIMIT 1000",
            [hi, lo, lo, *params],
        ).fetchall()
        series = self._conn().execute(
            "SELECT * FROM calendar_events WHERE status='active' AND recurrence!='' AND start_at < ?" + filters + " LIMIT 200",
            [hi, *params],
        ).fetchall()
        events = [self._row(r) for r in single]
        for row in series:
            events += self._expand(self._row(row), start, end)
        return sorted(events, key=lambda e: (e.start_at, not e.all_day))

    def upcoming(self, days: int = 14, person: Optional[str] = None) -> list[CalendarEvent]:
        now = datetime.now(timezone.utc)
        return self.between(now - timedelta(hours=12), now + timedelta(days=days), person)

    def series(self, person: Optional[str] = None) -> list[CalendarEvent]:
        """Active recurring bookings (the rules themselves, not occurrences)."""
        sql = "SELECT * FROM calendar_events WHERE status='active' AND recurrence!=''"
        rows = self._conn().execute(sql + (" AND person = ?" if person else "") + " ORDER BY start_at", [person] if person else []).fetchall()
        return [self._row(r) for r in rows]

    # ------------------------------------------------------------------
    # Recurrence
    # ------------------------------------------------------------------

    @staticmethod
    def _expand(event: CalendarEvent, start: datetime, end: datetime) -> list[CalendarEvent]:
        rule = event.recurrence
        base = event.start_at.astimezone().replace(tzinfo=None)               # local wall-clock time
        length = (event.end_at.astimezone().replace(tzinfo=None) - base) if event.end_at else None
        until = date.fromisoformat(rule["until"]) if rule.get("until") else None
        lo = start if start.tzinfo else start.astimezone()
        hi = end if end.tzinfo else end.astimezone()
        skips = set(event.skip_dates)
        out: list[CalendarEvent] = []

        first = 0
        if rule["freq"] != "monthly":   # jump close to the range instead of walking from the series start
            first = max(0, (lo.astimezone().replace(tzinfo=None) - base).days // 7 - 2)
        for k in range(first, first + MAX_OCCURRENCES):
            if rule["freq"] == "monthly":
                month = base.month - 1 + k
                try:
                    day = base.date().replace(year=base.year + month // 12, month=month % 12 + 1)
                except ValueError:      # e.g. the 31st in a short month
                    continue
            else:
                day = base.date() + timedelta(weeks=k)
                if rule.get("parity"):
                    if (iso_week(day) % 2 == 0) != (rule["parity"] == "even"):
                        continue
                elif rule["freq"] == "biweekly" and k % 2:
                    continue
            if until and day > until:
                break
            occ_start = datetime.combine(day, base.time()).astimezone()
            if occ_start >= hi:
                break
            occ_end = (datetime.combine(day, base.time()) + length).astimezone() if length is not None else None
            if occ_start < lo and (occ_end is None or occ_end <= lo):
                continue
            if day.isoformat() in skips:
                continue
            out.append(replace(
                event,
                start_at=occ_start.astimezone(timezone.utc),
                end_at=occ_end.astimezone(timezone.utc) if occ_end else None,
                occurrence=day.isoformat(),
            ))
        return out

    @staticmethod
    def _validate_recurrence(rule: dict[str, Any], start: datetime, end: Optional[datetime]) -> dict[str, Any]:
        if not rule or not rule.get("freq"):
            return {}
        freq = str(rule.get("freq", "")).lower()
        parity = str(rule.get("parity") or "").lower()
        if freq not in FREQS:
            raise CalendarServiceError("Okänd upprepning.")
        if parity not in PARITIES or (parity and freq == "monthly"):
            raise CalendarServiceError("Jämna/udda veckor går bara med veckovis upprepning.")
        if parity:
            freq = "biweekly"
        until = str(rule.get("until") or "")
        if until:
            try:
                until_day = date.fromisoformat(until)
            except ValueError as exc:
                raise CalendarServiceError("Ogiltigt slutdatum för upprepningen.") from exc
            if until_day < start.astimezone().date():
                raise CalendarServiceError("Upprepningen slutar innan den börjar.")
        period = {"weekly": 7, "biweekly": 14, "monthly": 28}[freq]
        if end is not None and end - start > timedelta(days=period):
            raise CalendarServiceError("Bokningen är längre än upprepningen.")
        return {"freq": freq, "parity": parity, "until": until}

    @staticmethod
    def _check_times(start: datetime, end: Optional[datetime], all_day: bool) -> tuple[datetime, Optional[datetime]]:
        if all_day:
            first = start.astimezone().date()          # naive datetimes count as local time
            stop = end.astimezone().date() if end else first + timedelta(days=1)
            if stop <= first:
                stop = first + timedelta(days=1)
            if (stop - first).days > MAX_SPAN_DAYS:
                raise CalendarServiceError(f"En heldagsbokning kan vara högst {MAX_SPAN_DAYS} dagar.")
            return local_midnight(first), local_midnight(stop)
        if end is not None and end <= start:
            raise CalendarServiceError("Sluttiden måste vara efter starttiden.")
        return start, end

    # ------------------------------------------------------------------

    @staticmethod
    def _validate(kind: str, details: dict[str, Any]) -> dict[str, Any]:
        if kind not in KINDS:
            raise CalendarServiceError(f"Okänd bokningstyp '{kind}'.")
        if kind != "match":
            note = str(details.get("note", "")).strip()[:500]
            return {"note": note} if note else {}
        sport = str(details.get("sport", "")).strip().lower()
        if sport not in SPORTS:
            raise CalendarServiceError("Ange om matchen är fotboll eller innebandy.")
        clean = {
            "sport": sport,
            "division": str(details.get("division", "")).strip()[:30],
            "home": str(details.get("home", "")).strip()[:60],
            "away": str(details.get("away", "")).strip()[:60],
            "role": str(details.get("role", "")).strip().upper()[:12],
            "gather": str(details.get("gather", "")).strip(),
            "officials": [],
        }
        if not clean["home"] or not clean["away"]:
            raise CalendarServiceError("Ange hemmalag och bortalag.")
        if clean["gather"] and not TIME_PATTERN.match(clean["gather"]):
            clean["gather"] = ""
        for official in (details.get("officials") or [])[:8]:
            role = str((official or {}).get("role", "")).strip().upper()[:12]
            name = " ".join(str((official or {}).get("name", "")).split())[:60]
            if role and name:
                clean["officials"].append({"role": role, "name": name})
        return clean

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _initialize_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'event',
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT,
                location TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'local',
                external_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_calendar_start ON calendar_events (status, start_at);
            """
        )
        # Columns added after the first version: migrate existing databases in place.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(calendar_events)")}
        for name, ddl in (
            ("all_day", "INTEGER NOT NULL DEFAULT 0"),
            ("recurrence", "TEXT NOT NULL DEFAULT ''"),
            ("skip_dates", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE calendar_events ADD COLUMN {name} {ddl}")
                logger.info("calendar_events: added column %s.", name)

    @staticmethod
    def _row(row: sqlite3.Row) -> CalendarEvent:
        def load(text: Optional[str], default: Any) -> Any:
            try:
                return json.loads(text) if text else default
            except ValueError:
                return default

        return CalendarEvent(
            id=row["id"], person=row["person"], kind=row["kind"], title=row["title"],
            start_at=datetime.fromisoformat(row["start_at"]),
            end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
            location=row["location"], details=load(row["details"], {}), status=row["status"], source=row["source"],
            all_day=bool(row["all_day"]), recurrence=load(row["recurrence"], {}),
            skip_dates=tuple(load(row["skip_dates"], [])),
        )
