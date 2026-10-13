"""
BriefingService - the morning briefing, on request ("Nexus, morgonbriefing").

Collects what the rest of the system already knows and writes it with fixed
templates (no language model, so times and results are always right):

    🌤 Väder          today in the home place, rain alert
    📅 Idag/Imorgon   the family's bookings and reminders, referee matches with assembly time
    ★ Favoritlagen    results since yesterday, today's games, team headlines
    🌍 Världen        the biggest stories (covered by several news sources), with links
    ⚠ System          only when something is wrong (backup, Ollama, web search, voice)

Three forms of the same briefing: sections for the card in the window, text for
the chat/Telegram (links only for Telegram) and a short spoken version.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from core.logger import get_logger

logger = get_logger(__name__)

WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september",
          "oktober", "november", "december")


@dataclass
class Line:
    text: str
    url: str = ""
    source: str = ""


@dataclass
class Section:
    key: str
    icon: str
    title: str
    lines: list[Line] = field(default_factory=list)


@dataclass
class Briefing:
    title: str
    greeting: str
    sections: list[Section]
    created: str
    spoken: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def text(self, links: bool = False) -> str:
        out = [self.greeting]
        for section in self.sections:
            out.append("")
            out.append(f"{section.icon} {section.title}")
            for line in section.lines:
                out.append(f"• {line.text}" + (f" ({line.source})" if line.source else ""))
                if links and line.url:
                    out.append(f"  {line.url}")
        return "\n".join(out)


def hhmm(moment: datetime) -> str:
    return moment.astimezone().strftime("%H:%M")


class BriefingService:
    def __init__(
        self,
        weather: Callable[[], dict[str, Any]],
        calendar: Any,
        reminders: Any,
        people: Callable[[], list[dict[str, str]]],
        person_for: Callable[[str, str], str],
        sports: Any,
        news: Any,
        problems: Callable[[], list[str]],
    ) -> None:
        self.weather, self.calendar, self.reminders = weather, calendar, reminders
        self.people, self.person_for, self.sports, self.news, self.problems = people, person_for, sports, news, problems
        self.last: Optional[Briefing] = None

    def build(self, now: Optional[datetime] = None) -> Briefing:
        now = (now or datetime.now()).astimezone()
        day = f"{WEEKDAYS[now.weekday()]} {now.day} {MONTHS[now.month - 1]}"
        hello = "God morgon" if now.hour < 10 else "Hej" if now.hour < 18 else "God kväll"
        sections: list[Section] = []
        spoken: list[str] = [f"{hello}!"]
        for build in (self._weather, self._family, self._sports, self._world, self._system):
            try:
                section, say = build(now)
            except Exception as exc:            # one broken part never stops the briefing
                logger.warning("Briefing part %s failed: %s", build.__name__, exc)
                continue
            if section and section.lines:
                sections.append(section)
            spoken += say
        if sections:
            spoken.append("Resten står på skärmen.")
        briefing = Briefing(title=f"{hello.upper()} · {day.upper()}", greeting=f"{hello}! Det är {day}.",
                            sections=sections, created=now.isoformat(timespec="minutes"), spoken=" ".join(spoken))
        self.last = briefing
        return briefing

    # ------------------------------------------------------------------

    def _weather(self, now: datetime) -> tuple[Optional[Section], list[str]]:
        w = self.weather() or {}
        if not w.get("ok"):
            return None, []
        today = (w.get("days") or [{}])[0]
        n = w.get("now") or {}
        text = f"{w.get('place', '')}: nu {n.get('temp')}°, {str(n.get('text', '')).lower()}"
        if today.get("min") is not None:
            text += f". Idag {today['min']}–{today['max']}°"
        if n.get("wind", 0) >= 8:
            text += f", blåsigt ({n['wind']} m/s)"
        lines = [Line(text + ".")]
        alert = w.get("alert")
        if alert:
            lines.append(Line(alert["text"] + "."))
        say = [f"Det är {n.get('temp')} grader och {str(n.get('text', '')).lower()}"
               + (f", idag mellan {today['min']} och {today['max']} grader." if today.get("min") is not None else ".")]
        if alert:
            say.append(alert["text"].split(" · ")[0].replace("ca ", "cirka ") + ".")
        return Section("weather", "🌤", "Väder", lines), say

    def _family(self, now: datetime) -> tuple[Optional[Section], list[str]]:
        people = self.people()
        names = {p["id"]: p["name"] for p in people}
        me = people[0]["id"] if people else ""
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days = {"Idag": (start, start + timedelta(days=1)), "Imorgon": (start + timedelta(days=1), start + timedelta(days=2))}
        reminders = [r for r in self.reminders.list_upcoming(limit=60) if r.due_at < (start + timedelta(days=2)).astimezone(timezone.utc)]
        lines: list[Line] = []
        say: list[str] = []
        for label, (a, b) in days.items():
            per: dict[str, list[tuple[datetime, str, str]]] = {}     # person -> (start, text, spoken)
            for e in self.calendar.between(a.astimezone(timezone.utc), b.astimezone(timezone.utc)):
                if label == "Imorgon" and e.all_day and e.start_at.astimezone() < a:
                    continue                  # a multi-day booking already shown under Idag
                per.setdefault(e.person, []).append((e.start_at, self._event_text(e, a), self._event_spoken(e)))
            for r in reminders:
                due = r.due_at.astimezone()
                if a <= due < b:
                    per.setdefault(self.person_for(r.category, r.text), []).append(
                        (r.due_at, f"⏰ {r.text} {hhmm(r.due_at)}", f"en påminnelse om {r.text} klockan {hhmm(r.due_at)}"))
            order = [p["id"] for p in people] + [k for k in per if k not in names]
            items = [(pid, sorted(per[pid], key=lambda x: x[0])) for pid in order if pid in per]
            if not items:
                if label == "Idag":
                    lines.append(Line("Idag: inget inbokat."))
                continue
            for pid, entries in items:
                texts = [t for _, t, _ in entries]
                who = "Du" if pid == me else names.get(pid, pid)
                joined = " · ".join(texts)
                named = who != "Du" and len(texts) == 1 and who.lower() in joined.lower()   # "Julian hos oss"
                lines.append(Line(f"{label} – {joined}" if named else f"{label} – {who}: {joined}"))
            if label == "Idag":
                for pid, entries in items[:3]:
                    who = "Du har" if pid == me else f"{names.get(pid, pid)} har"
                    say.append(f"{who} {entries[0][2]}" + (f" och {len(entries) - 1} sak till" if len(entries) > 1 else "") + ".")
        if not say:
            say.append("Inget är inbokat idag.")
        return Section("family", "📅", "Familjen", lines), say

    @staticmethod
    def _event_text(e: Any, day_start: datetime) -> str:
        if e.all_day:
            last = (e.end_at - timedelta(days=1)).astimezone() if e.end_at else e.start_at.astimezone()
            if last.date() > day_start.date():
                return f"{e.short} (t.o.m. {WEEKDAYS[last.weekday()][:3]} {last.day}/{last.month})"
            return f"{e.short} (heldag)"
        text = f"{e.short} {hhmm(e.start_at)}"
        if e.end_at and e.kind != "match":
            text += f"–{hhmm(e.end_at)}"
        gather = (e.details or {}).get("gather")
        if e.kind == "match" and gather:
            text += f" (samling {gather})"
        if e.location and e.kind != "match":
            text += f", {e.location}"
        return text

    @staticmethod
    def _event_spoken(e: Any) -> str:
        if e.kind == "match":
            d = e.details or {}
            gather = f", samling {d['gather']}" if d.get("gather") else ""
            return f"domaruppdrag, {d.get('home', '')} mot {d.get('away', '')} klockan {hhmm(e.start_at)}{gather}"
        if e.all_day:
            return e.title
        return f"{e.title} klockan {hhmm(e.start_at)}"

    def _sports(self, now: datetime) -> tuple[Optional[Section], list[str]]:
        if not self.sports.favorites():
            return None, []
        lines: list[Line] = []
        say: list[str] = []
        since = (now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)).astimezone(timezone.utc)   # yesterday and today
        for r in self.sports.favorite_results(since):
            when = "Igår" if datetime.fromisoformat(r["start"]).astimezone().date() < now.date() else "Idag"
            lines.append(Line(f"{when}: {r['text']} · {r['league_name']}"))
            say.append(spoken_result(r))
        for g in self.sports.snapshot().get("favorites", []):
            start = datetime.fromisoformat(g["start"]).astimezone()
            if g["state"] == "in":
                lines.append(Line(f"Pågår: {g['home']['short']} – {g['away']['short']} · {g['league_name']}"))
            elif g["state"] == "pre" and start.date() == now.date():
                lines.append(Line(f"Idag {start:%H:%M}: {g['home']['short']} – {g['away']['short']} · {g['league_name']}"))
                if len(say) < 4:
                    say.append(f"{g['home']['short']} möter {g['away']['short']} klockan {start:%H:%M}.")
        for n in self.news.recent((now - timedelta(hours=20)).astimezone(timezone.utc))[:3]:
            lines.append(Line(f"📰 {n['title']}", n["url"], n["source"]))
        if say:
            say = ["Dina lag:"] + say[:3]
        return Section("sports", "★", "Favoritlagen", lines), say

    def _world(self, now: datetime) -> tuple[Optional[Section], list[str]]:
        top = self.news.world_top(4)
        lines = [Line(n["title"], n["url"], n["source"]) for n in top]
        say = [f"I världen: {top[0]['title'].rstrip('.')}."] if top else []
        return Section("world", "🌍", "Världen", lines), say

    def _system(self, now: datetime) -> tuple[Optional[Section], list[str]]:
        problems = self.problems()
        if not problems:
            return None, []
        first = problems[0].rstrip(".")
        return Section("system", "⚠", "System", [Line(p) for p in problems]), [f"Obs: {first[0].lower()}{first[1:]}."]


def spoken_result(r: dict[str, Any]) -> str:
    """'Frölunda vann mot Luleå med 3 mot 2 efter förlängning.'"""
    h, a = r["home"], r["away"]
    hs, as_ = int(h.get("score") or 0), int(a.get("score") or 0)
    extra = " efter förlängning" if "ÖT" in r.get("status", "") else " efter straffar" if "str" in r.get("status", "") else ""
    if hs == as_:
        return f"{h['short']} och {a['short']} spelade {hs} mot {as_}."
    win, lose, ws, ls = (h, a, hs, as_) if hs > as_ else (a, h, as_, hs)
    return f"{win['short']} vann mot {lose['short']} med {ws} mot {ls}{extra}."
