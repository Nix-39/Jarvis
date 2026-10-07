"""
LessonsAgent - lets the user teach Oden in plain Swedish.

    "Oden, lär dig: när jag säger match menar jag domaruppdrag"   -> proposal, "ja" saves
    "bara kalendern" / "gäller alla"                              -> changes where it applies
    "vad har du lärt dig?"                                        -> numbered list
    "glöm lärdom 3"                                               -> proposal, "ja" removes

Deliberately without a language model: the commands are recognised by fixed
patterns in Python, so web pages, documents or a confused model can never add
lessons. Everything is confirmed before it is saved (pending state
`lessons_agent.pending`, 15 minutes). The lessons themselves are used by the
other agents through `services.lessons_service.lesson_book`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.logger import get_logger
from services.lessons_service import SCOPE_LABELS, SCOPES, LessonBook, LessonsError, clean_text, lesson_book
from services.memory_service import DEFAULT_SESSION_ID, MemoryService

logger = get_logger(__name__)

PENDING_TTL = timedelta(minutes=15)
_ODEN = r"^\s*(?:hej\s+)?(?:oden[\s,:!.-]+)?"
ADD_RE = re.compile(_ODEN + r"(?:lär dig|ny lärdom|lärdom)\b[\s:,.-]*(?P<text>.+)$", re.IGNORECASE | re.DOTALL)
LIST_RE = re.compile(_ODEN + r"(?:vad har du lärt dig|visa (?:dina |mina )?lärdomar|(?:dina |mina )?lärdomar)\s*[?.!]*\s*$", re.IGNORECASE)
REMOVE_RE = re.compile(_ODEN + r"(?:glöm|ta bort|radera)\s+lärdom(?:en)?\s*(?:nr\.?|nummer)?\s*(?P<num>\d{1,3})\b", re.IGNORECASE)
YES_RE = re.compile(r"^\s*(ja|japp|jo|jepp|ok|okej|kör|stämmer|spara|perfekt|yes)\b", re.IGNORECASE)
NO_RE = re.compile(r"^\s*(nej|nä|avbryt|stopp|glöm det|no)[\s.!]*$", re.IGNORECASE)

# Words the user may use for a scope, in a correction ("bara kalendern") or a prefix ("[kalender] ...").
SCOPE_WORDS: dict[str, str] = {
    "alla": "alla", "allt": "alla", "överallt": "alla", "oden": "oden", "agentval": "oden",
    "kalender": "kalender", "kalendern": "kalender", "urd": "kalender", "planering": "kalender",
    "påminnelser": "påminnelser", "påminnelse": "påminnelser", "påminnelserna": "påminnelser",
    "allmänt": "allmänt", "utbildning": "utbildning", "karriär": "karriär", "business": "business",
    "webb": "webb", "webbdesign": "webb", "sociala medier": "sociala medier", "content": "content",
}
_SCOPE_ALT = "|".join(re.escape(w) for w in sorted(SCOPE_WORDS, key=len, reverse=True))
SCOPE_REPLY_RE = re.compile(
    r"^\s*(?:nej[,.!]?\s*)?(?:den\s+)?(?:ska\s+)?(?:bara|endast|gäller|gälla|gäll)?\s*(?:bara|endast|för|i|till)?\s*"
    rf"(?:{_SCOPE_ALT})\s*[.!]*\s*$", re.IGNORECASE)
SCOPE_HINTS = (("kalender", re.compile(r"kalender|bokning|schema|veckovy|dagvy", re.I)),
               ("påminnelser", re.compile(r"påminn", re.I)))


def find_scope(text: str) -> Optional[str]:
    lowered = f" {text.lower()} "
    for word in sorted(SCOPE_WORDS, key=len, reverse=True):
        if re.search(rf"(?<![\wåäö]){re.escape(word)}(?![\wåäö])", lowered):
            return SCOPE_WORDS[word]
    return None


class LessonsAgent:
    AGENT_ID: str = "lessons_agent"
    PENDING_KEY: str = "lessons_agent.pending"

    def __init__(self, memory_service: Optional[MemoryService] = None, book: Optional[LessonBook] = None):
        self.memory = memory_service or MemoryService()
        self.book = book or lesson_book
        logger.info("LessonsAgent initialized successfully.")

    # ------------------------------------------------------------------
    # Routing helpers (used by the Orchestrator before the Router)
    # ------------------------------------------------------------------

    @staticmethod
    def is_command(message: str) -> bool:
        return bool(ADD_RE.match(message) or LIST_RE.match(message) or REMOVE_RE.match(message))

    @staticmethod
    def is_scope_reply(message: str) -> bool:
        """'bara kalendern', 'gäller alla', 'nej, den ska gälla Oden' - a correction to a pending lesson."""
        return bool(SCOPE_REPLY_RE.match(message))

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        message = str(payload.get("message", "")).strip()
        if not message:
            return "LessonsAgent received an empty message."
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=message, agent_id=self.AGENT_ID)
        try:
            reply = self._respond(message)
        except Exception as exc:
            logger.error("LessonsAgent failed: %s", exc)
            reply = "Något gick fel med lärdomarna. Du kan också öppna data\\lessons.md och skriva direkt där."
        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply

    def _respond(self, message: str) -> str:
        pending = self._load_pending()
        if pending and YES_RE.match(message) and len(message.split()) <= 4:
            self._clear_pending()
            return self._execute(pending)
        if pending and NO_RE.match(message):
            self._clear_pending()
            return "Okej, jag sparar ingenting."

        if LIST_RE.match(message):
            return self._list()
        found = REMOVE_RE.match(message)
        if found:
            return self._propose_remove(int(found.group("num")))
        found = ADD_RE.match(message)
        if found:
            return self._propose_add(found.group("text"))
        if pending and pending.get("action") == "add" and self.is_scope_reply(message):
            pending["scope"] = find_scope(message)
            pending["created"] = datetime.now(timezone.utc).isoformat()
            self._save_pending(pending)
            return self._card(pending)
        return ('Säg till exempel "Oden, lär dig: när jag säger match menar jag domaruppdrag", '
                '"vad har du lärt dig?" eller "glöm lärdom 2".')

    # ------------------------------------------------------------------

    def _propose_add(self, raw: str) -> str:
        text, scope = raw.strip(), None
        prefix = re.match(r"^[\[(]([^\])]{1,20})[\])]\s*:?\s*(.+)$", text, re.DOTALL) or re.match(r"^([a-zåäö ]{3,16}):\s*(.+)$", text, re.I | re.DOTALL)
        if prefix and prefix.group(1).strip().lower() in SCOPE_WORDS:
            scope, text = SCOPE_WORDS[prefix.group(1).strip().lower()], prefix.group(2)
        if scope is None:
            scope = next((name for name, pattern in SCOPE_HINTS if pattern.search(text)), "alla")
        text = clean_text(re.sub(r"^(?:att|om att)\s+", "", text.strip(), flags=re.IGNORECASE))
        text = text[:1].upper() + text[1:]
        if len(text) < 3:
            return "Vad ska jag lära mig? Skriv lärdomen efter \"lär dig:\"."
        pending = {"action": "add", "text": text, "scope": scope, "created": datetime.now(timezone.utc).isoformat()}
        self._save_pending(pending)
        return self._card(pending)

    def _card(self, pending: Dict[str, Any]) -> str:
        return (f"Jag sparar lärdomen:\n• {pending['text']}\n• Gäller: {SCOPE_LABELS[pending['scope']]}\n\n"
                "Stämmer det? Svara ja eller nej – eller ändra var den gäller, t.ex. \"bara kalendern\" eller \"gäller alla\".")

    def _propose_remove(self, number: int) -> str:
        lessons = self.book.all()
        if not 1 <= number <= len(lessons):
            return f"Det finns ingen lärdom nummer {number}." + (" " + self._list() if lessons else "")
        lesson = lessons[number - 1]
        self._save_pending({"action": "remove", "number": number, "text": lesson.text, "created": datetime.now(timezone.utc).isoformat()})
        return f"Ska jag glömma lärdom {number}?\n• {lesson.text} ({lesson.scope_label})\n\nSvara ja eller nej."

    def _list(self) -> str:
        lessons = self.book.all()
        if not lessons:
            return 'Jag har inga lärdomar än. Lär mig något med "Oden, lär dig: ...".'
        lines = [f"{l.number}. {l.text} ({l.scope_label})" for l in lessons]
        return "Det här har du lärt mig:\n" + "\n".join(lines) + '\n\nSäg "glöm lärdom 2" för att ta bort en.'

    def _execute(self, pending: Dict[str, Any]) -> str:
        try:
            if pending.get("action") == "add":
                lesson = self.book.add(pending["text"], pending["scope"])
                return f"Sparat som lärdom {lesson.number}. Jag använder den från och med nu ({lesson.scope_label})."
            if pending.get("action") == "remove":
                current = self.book.all()
                number = int(pending["number"])
                if number > len(current) or current[number - 1].text != pending.get("text"):
                    return "Listan har ändrats sedan dess – säg \"vad har du lärt dig?\" och försök igen."
                self.book.remove(number)
                return f"Glömt: {pending['text']}"
        except LessonsError as exc:
            return str(exc)
        return "Det fanns inget att bekräfta."

    # ------------------------------------------------------------------

    def _load_pending(self) -> Optional[Dict[str, Any]]:
        pending = self.memory.get_state(self.PENDING_KEY)
        if not isinstance(pending, dict) or pending.get("scope", "alla") not in SCOPES:
            return None
        try:
            created = datetime.fromisoformat(pending["created"])
        except (KeyError, ValueError):
            return None
        if datetime.now(timezone.utc) - created > PENDING_TTL:
            self._clear_pending()
            return None
        return pending

    def has_pending(self) -> bool:
        return self._load_pending() is not None

    def _save_pending(self, pending: Dict[str, Any]) -> None:
        self.memory.set_state(self.PENDING_KEY, pending)

    def _clear_pending(self) -> None:
        self.memory.set_state(self.PENDING_KEY, None)
