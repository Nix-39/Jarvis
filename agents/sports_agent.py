"""
SportsAgent - lets the user choose which leagues the sports ticker shows.

    "Oden, lägg till Premier League i resultaten"
    "ta bort NHL från resultaten"
    "vilka ligor finns?" / "vilka ligor visar du?"

Like LessonsAgent it uses no language model: fixed patterns in Python, so the
setting can only be changed by the user's own message. Changing which leagues
are shown is harmless and easy to undo, so it is done directly without a
confirmation step.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

from core.logger import get_logger
from services.memory_service import DEFAULT_SESSION_ID, MemoryService
from services.sports_service import CATALOG, MAX_LEAGUES, find_league

logger = get_logger(__name__)

_ODEN = r"^\s*(?:hej\s+)?(?:oden[\s,:!.-]+)?"
_RESULTS = r"(?:sport)?(?:resultat(?:en|listan|raden|baren)?|tickern)"
ADD_RE = re.compile(_ODEN + r"(?:lägg till|lägg in|visa)\s+(?P<name>.+?)\s+(?:i|på|till|bland)\s+" + _RESULTS + r"\s*[.!]*\s*$", re.IGNORECASE)
REMOVE_RE = re.compile(_ODEN + r"(?:ta bort|sluta visa|dölj|plocka bort)\s+(?P<name>.+?)\s+(?:från|ur|i|bland)\s+" + _RESULTS + r"\s*[.!]*\s*$", re.IGNORECASE)
LIST_RE = re.compile(_ODEN + r"(?:vilka ligor\b.*|(?:visa|lista) (?:alla )?ligor.*)$", re.IGNORECASE)


class SportsAgent:
    AGENT_ID: str = "sports_agent"

    def __init__(
        self,
        get_leagues: Callable[[], list[str]],
        set_leagues: Callable[[list[str]], Any],
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self.get_leagues = get_leagues
        self.set_leagues = set_leagues
        self.memory = memory_service or MemoryService()
        logger.info("SportsAgent initialized successfully.")

    @staticmethod
    def is_command(message: str) -> bool:
        return bool(ADD_RE.match(message) or REMOVE_RE.match(message) or LIST_RE.match(message))

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        message = str(payload.get("message", "")).strip()
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=message, agent_id=self.AGENT_ID)
        try:
            reply = self._respond(message)
        except Exception as exc:
            logger.error("SportsAgent failed: %s", exc)
            reply = "Något gick fel när jag skulle ändra resultatlistan."
        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply

    def _respond(self, message: str) -> str:
        current = [k for k in self.get_leagues() if k in CATALOG]
        found = ADD_RE.match(message)
        if found:
            league = find_league(found.group("name"))
            if league is None:
                return f"Jag känner inte till \"{found.group('name').strip()}\". {self._available()}"
            if league.key in current:
                return f"{league.name} finns redan i resultaten."
            if len(current) >= MAX_LEAGUES:
                return f"Resultatraden har redan {MAX_LEAGUES} ligor – ta bort någon först."
            self.set_leagues(current + [league.key])
            return f"Klart – {league.name} är tillagd i resultaten. Resultaten dyker upp inom en minut."
        found = REMOVE_RE.match(message)
        if found:
            league = find_league(found.group("name"))
            if league is None or league.key not in current:
                shown = ", ".join(CATALOG[k].name for k in current) or "inga"
                return f"Den ligan finns inte i resultaten. Just nu visas: {shown}."
            self.set_leagues([k for k in current if k != league.key])
            return f"{league.name} är borttagen från resultaten."
        shown = ", ".join(CATALOG[k].name for k in current) or "inga ligor"
        return f"Resultatraden visar: {shown}.\n{self._available()}"

    @staticmethod
    def _available() -> str:
        groups: dict[str, list[str]] = {}
        for league in CATALOG.values():
            groups.setdefault(league.group, []).append(league.name)
        return "Ligor jag kan visa:\n" + "\n".join(f"• {g}: {', '.join(names)}" for g, names in groups.items()) + \
            "\n\nDu kan också lägga till och ta bort ligor i menyn längst ner till vänster i resultatraden."
