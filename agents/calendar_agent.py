"""
CalendarAgent (Urd) - books, lists and cancels events in the family calendar
through natural language, always with an explicit confirmation before anything
is saved or removed.

Supports ordinary bookings, work shifts, referee matches (football / floorball)
with division, teams, own role, assembly time and the rest of the referee crew,
all-day bookings spanning several days (a trip, a course, a cup) and recurring
bookings ("Julian är hos oss torsdag-söndag varannan jämn vecka").

Same safety model as ReminderAgent: the LLM only produces a structured proposal;
validated Python code computes dates, weeks and recurrences and writes to the
database after the user says "ja". Pending proposals and open questions live in
`calendar_agent.pending`, so the Orchestrator routes the user's answer
("ja", "nej", "vecka 42", "AD2 heter Johan") back here.

Reminders are shown in the same family calendar, so Urd also lists them and can
remove them (ids prefixed with "r", e.g. "r4"). One occurrence of a recurring
booking is referenced as "<id>@<first day>", e.g. "5@2026-10-29".
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from core.clock import current_datetime_text
from core.logger import get_logger
from services.calendar_service import (
    SPORT_ICONS, CalendarEvent, CalendarService, CalendarServiceError, iso_week, local_midnight, match_title, recurrence_label,
)
from services.memory_service import DEFAULT_CONTEXT_LIMIT, DEFAULT_SESSION_ID, MemoryService, format_conversation_history
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader
from services.reminder_service import Reminder, ReminderService

logger = get_logger(__name__)

PENDING_TTL = timedelta(minutes=15)
YES_PATTERN = re.compile(r"^\s*(ja|japp|jajamän|jo|jepp|ok|okej|okey|kör|gör det|stämmer|korrekt|precis|absolut|visst|perfekt|yes)\b", re.IGNORECASE)
NO_PATTERN = re.compile(r"^\s*(nej|nä|nää|nope|avbryt|stopp|glöm det|strunta i det|no)[\s.!]*$", re.IGNORECASE)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
MATCH_MINUTES = {"fotboll": 120, "innebandy": 90}
FREQ_ALIASES = {"weekly": "weekly", "biweekly": "biweekly", "monthly": "monthly",
                "varje vecka": "weekly", "varannan vecka": "biweekly", "varje månad": "monthly"}
WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december")
DATE_TABLE_DAYS = 42

Person = Dict[str, str]   # {"id", "name", "full_name"}


def day_name(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"


def day_text(moment: datetime) -> str:
    return day_name(moment.astimezone().date())


def hm(moment: Optional[datetime]) -> str:
    return moment.astimezone().strftime("%H:%M") if moment else ""


def span_text(first: date, last: date) -> str:
    return day_name(first) if first == last else f"{day_name(first)} – {day_name(last)}"


def when_text(e: CalendarEvent) -> str:
    """'torsdag 15 oktober – söndag 18 oktober (heldag)' or 'fredag 9 oktober kl. 19:15'."""
    if e.all_day:
        return f"{span_text(e.first_day, e.last_day)} (heldag)"
    end = f"–{hm(e.end_at)}" if e.end_at and e.kind != "match" else ""
    return f"{day_text(e.start_at)} kl. {hm(e.start_at)}{end}"


def labeled(title: str, name: str, sep: str = " – ") -> str:
    """'Gothia Cup – Nix', but just 'Julian' when the title already names the person."""
    if name and name.lower() in title.lower():
        return title
    return f"{name}{sep}{title}" if sep == ": " else f"{title}{sep}{name}"


def _parse_day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


class CalendarAgent:
    AGENT_ID: str = "calendar_agent"
    PENDING_KEY: str = "calendar_agent.pending"

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        calendar_service: Optional[CalendarService] = None,
        ollama_service: Optional[OllamaService] = None,
        people_provider: Optional[Callable[[], list[Person]]] = None,
        reminder_service: Optional[ReminderService] = None,
    ):
        self.llm = ollama_service or OllamaService()
        self.memory = memory_service or MemoryService()
        self.calendar = calendar_service or CalendarService()
        self.reminders = reminder_service
        self.people_provider = people_provider or (lambda: [{"id": "nix", "name": "Nix", "full_name": ""}])
        self.system_prompt = PromptLoader().load("calendar_agent.txt")
        logger.info("CalendarAgent initialized successfully.")

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        user_message = payload.get("message", "").strip()
        if not user_message:
            return "CalendarAgent received an empty message."
        history = self.memory.get_session_messages(session_id=DEFAULT_SESSION_ID, agent_id=self.AGENT_ID, limit=DEFAULT_CONTEXT_LIMIT)
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=user_message, agent_id=self.AGENT_ID)
        try:
            reply = self._respond(user_message, history)
        except Exception as exc:
            logger.error("CalendarAgent failed: %s", exc)
            reply = "Något gick fel med kalendern. Försök gärna igen med datum och tid."
        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply

    # ------------------------------------------------------------------

    def _respond(self, user_message: str, history) -> str:
        pending = self._load_pending()
        confirmable = bool(pending) and pending.get("action") in ("create", "cancel")
        if confirmable and len(user_message.split()) <= 5 and YES_PATTERN.match(user_message):
            self._clear_pending()
            return self._execute(pending)
        if pending and NO_PATTERN.match(user_message):
            self._clear_pending()
            return "Okej, då låter jag kalendern vara som den är."

        parsed = self._parse(user_message, history, pending)
        kind = parsed.get("action")
        if kind == "create":
            return self._propose_create(parsed)
        if kind == "cancel":
            return self._propose_cancel(parsed)
        if kind == "list":
            self._clear_pending()
            return self._answer_list(parsed)
        return self._ask(str(parsed.get("question") or "").strip() or "Vad vill du lägga in i kalendern, och när?")

    def _ask(self, question: str, draft: Optional[Dict[str, Any]] = None) -> str:
        """Ask a follow-up question and keep the conversation here until it is answered."""
        self._save_pending({"action": "clarify", "question": question, "draft": draft or {},
                            "created": datetime.now(timezone.utc).isoformat()})
        return question

    # ---------------- create ----------------

    def _propose_create(self, p: Dict[str, Any]) -> str:
        people = self.people_provider()
        ids = {x["id"] for x in people}
        kind = p.get("kind") if p.get("kind") in ("event", "work", "match") else "event"
        person = p.get("person") if p.get("person") in ids else people[0]["id"]
        day = _parse_day(p.get("date"))
        if day is None:
            return self._ask("Vilken dag gäller det?", p)
        last = _parse_day(p.get("end_date")) or day
        all_day = bool(p.get("all_day")) or last != day
        if last < day:
            return self._ask("Slutdagen är före startdagen – vilka dagar gäller det?", p)

        rule = self._rule(p.get("repeat") or {})
        if rule.get("parity"):                     # start in a week of the right parity
            while (iso_week(day) % 2 == 0) != (rule["parity"] == "even"):
                day += timedelta(weeks=1)
                last += timedelta(weeks=1)

        details: Dict[str, Any] = {}
        title = " ".join(str(p.get("title") or "").split())
        if all_day:
            if kind == "match":                    # a whole cup/tournament: one banner, not every game
                kind = "event"
            start, end = local_midnight(day), local_midnight(last + timedelta(days=1))
            if end <= datetime.now().astimezone() and not rule:
                return self._ask(f"{span_text(day, last)} har redan varit. Vilka dagar menar du?", p)
            if not title:
                return self._ask("Vad ska det stå på markeringen?", p)
        else:
            start_text, end_text = str(p.get("start") or "").strip(), str(p.get("end") or "").strip()
            if not TIME_RE.match(start_text):
                return self._ask("Vilken tid börjar det? (Eller är det en heldag?)" if kind != "match" else "Vilken tid är avspark/matchstart?", p)
            start = datetime.fromisoformat(f"{day.isoformat()}T{start_text.zfill(5)}").astimezone()
            end = None
            if TIME_RE.match(end_text):
                end = datetime.fromisoformat(f"{day.isoformat()}T{end_text.zfill(5)}").astimezone()
                if end <= start:
                    end += timedelta(days=1)   # e.g. a night shift 22:00-06:00
            if start <= datetime.now(timezone.utc) - timedelta(hours=1) and not rule:
                return self._ask(f"{day_text(start)} kl. {hm(start)} har redan varit. Vilken dag menar du?", p)
            if kind == "match":
                m = p.get("match") or {}
                sport = str(m.get("sport") or "").lower()
                if sport not in SPORT_ICONS:
                    return self._ask("Är det fotboll eller innebandy?", p)
                if not m.get("home") or not m.get("away"):
                    return self._ask("Vilka lag möts?", p)
                details = {k: m.get(k, "") for k in ("sport", "division", "home", "away", "role", "gather")}
                details["officials"] = self._crew(m, person, people)
                title = match_title(details)
                if end is None:
                    end = start + timedelta(minutes=MATCH_MINUTES[sport])
            elif not title:
                return self._ask("Vad ska bokningen heta?", p)

        pending = {
            "action": "create", "kind": kind, "person": person, "title": title, "all_day": all_day,
            "start": start.isoformat(), "end": end.isoformat() if end else None,
            "location": " ".join(str(p.get("location") or "").split()), "details": details, "recurrence": rule,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._save_pending(pending)
        who = next(x["name"] for x in people if x["id"] == person)
        return "Jag lägger in:\n\n" + self._card(pending, who) + "\n\nStämmer det? Svara ja eller nej, eller säg vad som ska ändras."

    @staticmethod
    def _rule(repeat: Dict[str, Any]) -> Dict[str, Any]:
        freq = FREQ_ALIASES.get(str(repeat.get("freq") or "").strip().lower(), "")
        if not freq:
            return {}
        parity = str(repeat.get("parity") or "").strip().lower()
        parity = parity if parity in ("even", "odd") and freq != "monthly" else ""
        until = _parse_day(repeat.get("until"))
        return {"freq": "biweekly" if parity else freq, "parity": parity, "until": until.isoformat() if until else ""}

    def _crew(self, m: Dict[str, Any], person: str, people: list[Person]) -> list[Dict[str, str]]:
        """The full referee crew, with the user's own role and name included."""
        crew = [{"role": str(o.get("role", "")).upper(), "name": str(o.get("name", "")).strip()} for o in (m.get("officials") or []) if isinstance(o, dict)]
        me = next(x for x in people if x["id"] == person)
        my_name = me.get("full_name") or me["name"]
        my_role = str(m.get("role") or "").upper()
        if my_role and not any(c["role"] == my_role for c in crew):
            crew.append({"role": my_role, "name": my_name})
        order = {"HD": 0, "AD1": 1, "AD": 1, "AD2": 2, "4:E DOMARE": 3}
        return sorted([c for c in crew if c["role"] and c["name"]], key=lambda c: order.get(c["role"], 9))

    def _card(self, e: Dict[str, Any], who: str) -> str:
        start = datetime.fromisoformat(e["start"]); end = datetime.fromisoformat(e["end"]) if e.get("end") else None
        repeat = f"Återkommer {recurrence_label(e['recurrence'])}" if e.get("recurrence") else ""
        if e["kind"] == "match":
            d = e["details"]
            lines = [f"{SPORT_ICONS.get(d.get('sport'), '')} {match_title(d)}".strip()]
            if e.get("location"):
                lines.append(e["location"])
            lines.append(f"{day_text(start)}" + (f" · samling {d['gather']}" if d.get("gather") else "") + f" · start {hm(start)}")
            lines += [f"{c['role']}: {c['name']}" for c in d.get("officials", [])]
            return "\n".join(lines + ([repeat] if repeat else []))
        if e.get("all_day"):
            first, last = start.astimezone().date(), end.astimezone().date() - timedelta(days=1)
            lines = [f"• {labeled(e['title'], who)}", f"• {span_text(first, last)} (heldag)"]
        else:
            lines = [f"• {labeled(e['title'], who)}", f"• {day_text(start)} kl. {hm(start)}" + (f"–{hm(end)}" if end else "")]
        if e.get("location"):
            lines.append(f"• {e['location']}")
        if repeat:
            lines.append(f"• {repeat}")
        return "\n".join(lines)

    # ---------------- cancel ----------------

    def _propose_cancel(self, p: Dict[str, Any]) -> str:
        upcoming = self.calendar.upcoming(days=120)
        occurrences = {e.key: e for e in upcoming if e.occurrence}
        singles = {e.id: e for e in upcoming if not e.occurrence}
        series = {s.id: s for s in self.calendar.series()}
        reminders = {r.id: r for r in self._upcoming_reminders(days=120)}
        ids: list[int] = []
        skips: list[list[Any]] = []
        reminder_ids: list[int] = []
        lines: list[str] = []
        for raw in p.get("event_ids") or []:
            text = str(raw).strip().lower()
            if text.startswith("r") and text[1:].isdigit() and int(text[1:]) in reminders:
                reminder_ids.append(int(text[1:])); lines.append(f"• {self._reminder_line(reminders[int(text[1:])])}")
            elif text in occurrences:
                e = occurrences[text]
                skips.append([e.id, e.occurrence]); lines.append(f"• {self._line(e)} (bara detta tillfälle)")
            elif text.isdigit() and int(text) in series:
                ids.append(int(text)); lines.append(f"• {self._series_line(series[int(text)])} – hela serien")
            elif text.isdigit() and int(text) in singles:
                ids.append(int(text)); lines.append(f"• {self._line(singles[int(text)])}")
        if not lines:
            return "Jag hittar ingen sådan bokning eller påminnelse."
        self._save_pending({"action": "cancel", "ids": ids, "skips": skips, "reminder_ids": reminder_ids,
                            "created": datetime.now(timezone.utc).isoformat()})
        return "Ska jag ta bort:\n" + "\n".join(lines) + "\n\nSvara ja eller nej."

    # ---------------- list ----------------

    def _answer_list(self, p: Dict[str, Any]) -> str:
        people = {x["id"]: x["name"] for x in self.people_provider()}
        person = p.get("list_person") if p.get("list_person") in people else None
        kind = p.get("list_kind") if p.get("list_kind") in ("event", "work", "match") else None
        start = _parse_day(p.get("list_from")) or date.today()
        end = _parse_day(p.get("list_to")) or start + timedelta(days=6)
        lo, hi = local_midnight(start), local_midnight(end + timedelta(days=1))
        events = self.calendar.between(lo, hi, person=person, kind=kind)
        first = next(iter(people), None)
        reminders = [r for r in self._upcoming_reminders(days=400) if lo <= r.due_at < hi] if kind is None and person in (None, first) else []
        span = span_text(start, end)
        if not events and not reminders:
            who = people.get(person, "Ni")
            return f"{who} har inget {'pass' if kind == 'work' else 'inplanerat'} {span}." if person else f"Inget inplanerat {span}."
        timed = [e for e in events if not e.all_day]
        if kind == "work" and person and start == end and len(timed) == 1:
            e = timed[0]
            return f"{people[person]} jobbar {hm(e.start_at)}–{hm(e.end_at)} {day_text(e.start_at)}." if e.end_at else f"{people[person]} jobbar från {hm(e.start_at)} {day_text(e.start_at)}."
        rows = [(e.start_at, f"• {when_text(e)} – {e.short if person else labeled(e.short, people.get(e.person, e.person), ': ')}") for e in events]
        rows += [(r.due_at, f"• {day_text(r.due_at)} kl. {hm(r.due_at)} – ⏰ {r.text} (påminnelse)") for r in reminders]
        return f"{span[0].upper() + span[1:]}:\n" + "\n".join(line for _, line in sorted(rows, key=lambda x: x[0]))

    # ---------------- execute ----------------

    def _execute(self, pending: Dict[str, Any]) -> str:
        if pending.get("action") == "create":
            try:
                event = self.calendar.add(
                    person=pending["person"], kind=pending["kind"], title=pending["title"],
                    start=datetime.fromisoformat(pending["start"]),
                    end=datetime.fromisoformat(pending["end"]) if pending.get("end") else None,
                    location=pending.get("location", ""), details=pending.get("details") or {},
                    all_day=bool(pending.get("all_day")), recurrence=pending.get("recurrence") or {},
                )
            except CalendarServiceError as exc:
                return f"Jag kunde inte lägga in bokningen: {exc}"
            repeat = f", och återkommer {recurrence_label(event.recurrence)}" if event.recurrence else ""
            return f"Klart! {event.short} ligger i kalendern {when_text(event)}{repeat}."
        if pending.get("action") == "cancel":
            done = [i for i in pending.get("ids", []) if self.calendar.cancel(i)]
            done += [i for i, day in pending.get("skips", []) if self.calendar.skip(i, date.fromisoformat(day))]
            if self.reminders is not None:
                done += [i for i in pending.get("reminder_ids", []) if self.reminders.cancel(i)]
            return "Borttaget ur kalendern." if done else "Det var redan borttaget."
        return "Det fanns inget att bekräfta."

    # ---------------- LLM ----------------

    def _parse(self, user_message: str, history, pending: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        people = self.people_provider()
        people_text = "\n".join(f"- {x['id']}: {x['name']}" + (f" ({x['full_name']})" if x.get("full_name") else "") for x in people)
        lines = [f"id {s.id}: {self._series_line(s)} (HELA SERIEN)" for s in self.calendar.series()[:20]]
        lines += [f"id {e.key}: {self._line(e)}" for e in self.calendar.upcoming(days=60)[:60]]
        lines += [f"id r{r.id}: {self._reminder_line(r)}" for r in self._upcoming_reminders(days=60)[:40]]
        upcoming = "\n".join(lines) or "(inga)"
        today = date.today()
        dates = "\n".join(
            f"{d.isoformat()} {WEEKDAYS[d.weekday()]} v{iso_week(d)}" + (" (idag)" if d == today else "")
            for d in (today + timedelta(days=i) for i in range(DATE_TABLE_DAYS))
        )
        prompt = f"""
System Instructions:
{self.system_prompt}

Current date and time: {current_datetime_text()} (ISO: {datetime.now().astimezone():%Y-%m-%d %H:%M}, week {iso_week(today)})

Date lookup (use it - never compute weekdays or week numbers yourself):
{dates}

Family members:
{people_text}

Upcoming bookings:
{upcoming}

Pending proposal or open question:
{json.dumps(pending, ensure_ascii=False) if pending else "(ingen)"}

Recent conversation:
{format_conversation_history(history)}

User message:
"{user_message}"

JSON:
"""
        raw = self.llm.chat(prompt)
        found = re.search(r"\{.*\}", raw or "", flags=re.DOTALL)
        if not found:
            logger.warning("CalendarAgent got non-JSON output from the model.")
            return {"action": "clarify"}
        try:
            data = json.loads(found.group(0))
        except json.JSONDecodeError:
            logger.warning("CalendarAgent could not parse model JSON.")
            return {"action": "clarify"}
        return data if isinstance(data, dict) else {"action": "clarify"}

    # ---------------- helpers ----------------

    def _name(self, pid: str) -> str:
        return {x["id"]: x["name"] for x in self.people_provider()}.get(pid, pid)

    def _line(self, e: CalendarEvent) -> str:
        return f"{labeled(e.short, self._name(e.person), ': ')} – {when_text(e)}"

    def _series_line(self, s: CalendarEvent) -> str:
        if s.all_day:
            days = WEEKDAYS[s.first_day.weekday()] + ("" if s.first_day == s.last_day else f"–{WEEKDAYS[s.last_day.weekday()]}")
        else:
            days = f"{WEEKDAYS[s.first_day.weekday()]} kl. {hm(s.start_at)}"
        return f"{labeled(s.short, self._name(s.person), ': ')} – {days}, {recurrence_label(s.recurrence)}"

    def _reminder_line(self, r: Reminder) -> str:
        return f"⏰ {r.text} – {day_text(r.due_at)} kl. {hm(r.due_at)} (påminnelse)"

    def _upcoming_reminders(self, days: int) -> list[Reminder]:
        if self.reminders is None:
            return []
        until = datetime.now(timezone.utc) + timedelta(days=days)
        try:
            return [r for r in self.reminders.list_upcoming(limit=200) if r.due_at <= until]
        except Exception as exc:   # fail-soft: the calendar works without reminders
            logger.warning("CalendarAgent could not read reminders: %s", exc)
            return []

    def _load_pending(self) -> Optional[Dict[str, Any]]:
        pending = self.memory.get_state(self.PENDING_KEY)
        if not isinstance(pending, dict):
            return None
        try:
            created = datetime.fromisoformat(pending["created"])
        except (KeyError, ValueError):
            return None
        if datetime.now(timezone.utc) - created > PENDING_TTL:
            self._clear_pending()
            return None
        return pending

    def _save_pending(self, pending: Dict[str, Any]) -> None:
        self.memory.set_state(self.PENDING_KEY, pending)

    def _clear_pending(self) -> None:
        self.memory.set_state(self.PENDING_KEY, None)
