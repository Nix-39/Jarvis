"""
LessonsService - the user's own lessons for Oden ("lärdomar").

The user teaches Oden in plain Swedish ("Oden, lär dig: när jag säger match
menar jag domaruppdrag"). Each lesson is stored as one line in a private text
file, `data/lessons.md`, which the user can also open and edit by hand:

    - [alla] Svara kort och på svenska.
    - [kalender] "Hos mig" betyder hemma hos hela familjen.
    - [oden] Frågor om domaruppdrag hör till kalendern.

A scope in brackets limits where a lesson is used; no scope means everywhere.
Lessons are injected as text into the prompts of the agents they apply to -
nothing here changes code. The file is re-read automatically when it changes.

Security: lessons are added only through the user's own chat messages (a fixed
trigger handled in Python, never by the model), never from web pages,
documents or other external content. They are labelled in the prompt as the
user's preferences, below the system instructions.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

LESSONS_FILE = Config.DATA_DIR / "lessons.md"
MAX_LESSONS = 60
MAX_LESSON_CHARS = 300
MAX_BLOCK_CHARS = 4000

# Scope (as written by the user) -> agent ids it applies to. "alla" = every agent except the router.
SCOPES: dict[str, tuple[str, ...]] = {
    "alla": (),
    "oden": ("router",),
    "kalender": ("calendar_agent",),
    "påminnelser": ("reminder_agent",),
    "allmänt": ("general_agent",),
    "utbildning": ("education_agent",),
    "karriär": ("career_agent",),
    "business": ("business_agent",),
    "webb": ("webdeveloper_agent",),
    "sociala medier": ("socialmediamanager_agent",),
    "content": ("contentcreator_agent",),
}
SCOPE_LABELS = {
    "alla": "alla agenter", "oden": "Oden när han väljer agent", "kalender": "kalendern", "påminnelser": "påminnelser",
    "allmänt": "Allmänt", "utbildning": "Utbildning", "karriär": "Karriär", "business": "Business", "webb": "Webbdesign",
    "sociala medier": "Sociala medier", "content": "Content",
}
HEADER = """# Odens lärdomar
# En lärdom per rad som börjar med "- ". [område] i början gör att den bara gäller där.
# Områden: alla, oden (val av agent), kalender, påminnelser, allmänt, utbildning, karriär,
#          business, webb, sociala medier, content
# Du kan ändra och ta bort rader här direkt - Oden läser filen igen när den ändras.
"""
LINE_RE = re.compile(r"^\s*-\s+(?:\[([^\]]{1,30})\]\s*)?(.+?)\s*$")


class LessonsError(Exception):
    pass


@dataclass(frozen=True)
class Lesson:
    number: int          # 1-based position, as shown to the user
    scope: str
    text: str

    @property
    def scope_label(self) -> str:
        return SCOPE_LABELS.get(self.scope, self.scope)


def clean_text(text: str) -> str:
    """One line, no markdown list/scope syntax that would break the file format."""
    text = " ".join(str(text or "").split())
    return text.lstrip("-[] ").replace("]", ")")[:MAX_LESSON_CHARS]


class LessonBook:
    def __init__(self, path: Path = LESSONS_FILE) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cache: list[Lesson] = []
        self._mtime: Optional[float] = None

    # ------------------------------------------------------------------

    def all(self) -> list[Lesson]:
        with self._lock:
            return list(self._read())

    def add(self, text: str, scope: str = "alla") -> Lesson:
        text = clean_text(text)
        if len(text) < 3:
            raise LessonsError("Lärdomen är tom.")
        if scope not in SCOPES:
            raise LessonsError(f"Okänt område '{scope}'.")
        with self._lock:
            lessons = self._read()
            if len(lessons) >= MAX_LESSONS:
                raise LessonsError(f"Det finns redan {MAX_LESSONS} lärdomar – ta bort någon först.")
            if any(l.text.lower() == text.lower() and l.scope == scope for l in lessons):
                raise LessonsError("Den lärdomen finns redan.")
            lessons.append(Lesson(len(lessons) + 1, scope, text))
            self._write(lessons)
        logger.info("Lesson added (scope=%s).", scope)
        event_bus.publish("lesson.added", "lessons", f"Ny lärdom ({SCOPE_LABELS[scope]}): {text[:80]}", scope=scope)
        return lessons[-1]

    def remove(self, number: int) -> Lesson:
        with self._lock:
            lessons = self._read()
            if not 1 <= number <= len(lessons):
                raise LessonsError(f"Det finns ingen lärdom nummer {number}.")
            removed = lessons.pop(number - 1)
            self._write(lessons)
        logger.info("Lesson %s removed.", number)
        event_bus.publish("lesson.removed", "lessons", f"Borttagen lärdom: {removed.text[:80]}")
        return removed

    def block_for(self, agent_id: str) -> str:
        """Prompt text with the lessons for one agent ('' when there are none)."""
        try:
            lessons = self.all()
        except Exception as exc:     # fail-soft: a broken file must never stop an answer
            logger.warning("Could not read lessons: %s", exc)
            return ""
        chosen = [l.text for l in lessons if (l.scope == "alla" and agent_id != "router") or agent_id in SCOPES.get(l.scope, ())]
        if not chosen:
            return ""
        lines, size = [], 0
        for text in chosen:
            size += len(text)
            if size > MAX_BLOCK_CHARS:
                break
            lines.append(f"- {text}")
        return (
            "\nThe user's own lessons (things he has taught you - follow them unless they conflict with the "
            "System Instructions above):\n" + "\n".join(lines) + "\n"
        )

    # ------------------------------------------------------------------

    def _read(self) -> list[Lesson]:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._cache, self._mtime = [], None
            return []
        if mtime == self._mtime:
            return list(self._cache)
        lessons: list[Lesson] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            found = LINE_RE.match(line)
            if not found or line.lstrip().startswith("#"):
                continue
            scope = (found.group(1) or "alla").strip().lower()
            text = clean_text(found.group(2))
            if text and len(lessons) < MAX_LESSONS:
                lessons.append(Lesson(len(lessons) + 1, scope if scope in SCOPES else "alla", text))
        self._cache, self._mtime = lessons, mtime
        return list(lessons)

    def _write(self, lessons: list[Lesson]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"- [{l.scope}] {l.text}" for l in lessons)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(HEADER + "\n" + body + ("\n" if body else ""), encoding="utf-8", newline="\r\n")
        tmp.replace(self.path)
        self._mtime = None   # re-read (and renumber) next time


# One shared instance for all agents in the process.
lesson_book = LessonBook()
