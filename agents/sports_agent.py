"""
SportsAgent - the sports ticker, favourite teams and match mode, by talking.

    "Nexus, lägg till Premier League i resultaten" / "ta bort NHL från resultaten"
    "vilka ligor finns?" / "vilka ligor visar du?"
    "lägg till Frölunda i SHL som favoritlag" / "ta bort Barcelona från favoriterna"
    "vilka favoritlag har jag?"
    "pausa resultaten" / "matchläge"  ->  no notifications, live scores hidden
    "resultaten igen" / "avsluta matchläge"

Like LessonsAgent it uses no language model: fixed patterns in Python, so the
settings can only be changed by the user's own message. Everything here is
harmless and easy to undo, so it is done directly without a confirmation step.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.logger import get_logger
from services.memory_service import DEFAULT_SESSION_ID, MemoryService
from services.sports_service import CATALOG, MAX_LEAGUES, find_league, fold

logger = get_logger(__name__)

_NAME = r"^\s*(?:hej\s+)?(?:(?:nexus|oden)[\s,:!.-]+)?"
_RESULTS = r"(?:sport)?(?:resultat(?:en|listan|raden|baren)?|tickern)"
_FAVS = r"(?:mina\s+|bland\s+)?favorit(?:lag|er|erna|lagen|laget)?"
ADD_RE = re.compile(_NAME + r"(?:lägg till|lägg in|visa)\s+(?P<name>.+?)\s+(?:i|på|till|bland)\s+" + _RESULTS + r"\s*[.!]*\s*$", re.IGNORECASE)
REMOVE_RE = re.compile(_NAME + r"(?:ta bort|sluta visa|dölj|plocka bort)\s+(?P<name>.+?)\s+(?:från|ur|i|bland)\s+" + _RESULTS + r"\s*[.!]*\s*$", re.IGNORECASE)
LIST_RE = re.compile(_NAME + r"(?:vilka ligor\b.*|(?:visa|lista) (?:alla )?ligor.*)$", re.IGNORECASE)
FAV_ADD_RE = re.compile(_NAME + r"(?:lägg till|lägg in|följ|bevaka)\s+(?P<name>.+?)(?:\s+(?:som|bland|i|till)\s+" + _FAVS + r")?\s*[.!]*\s*$", re.IGNORECASE)
FAV_REMOVE_RE = re.compile(_NAME + r"(?:ta bort|sluta följa|sluta bevaka)\s+(?P<name>.+?)(?:\s+(?:från|ur|som|bland)\s+" + _FAVS + r")?\s*[.!]*\s*$", re.IGNORECASE)
FAV_LIST_RE = re.compile(_NAME + r"(?:vilka (?:är )?(?:mina )?favoritlag.*|(?:visa |lista )?mina favoritlag.*|vilka lag följer (?:du|jag).*)$", re.IGNORECASE)
PAUSE_RE = re.compile(_NAME + r"(?:pausa (?:sport)?resultaten|matchläge(?: på)?|starta matchläge|slå på matchläge|inga (?:sport)?resultat(?: nu| ikväll)?|stäng av (?:sport)?(?:resultaten|notiserna|resultatnotiserna))\s*[.!]*\s*$", re.IGNORECASE)
RESUME_RE = re.compile(_NAME + r"(?:(?:slå på|sätt på|starta|visa) (?:sport)?resultaten igen|(?:sport)?resultaten igen|avsluta matchläge(?:t)?|stäng av matchläge(?:t)?|matchläge av)\s*[.!]*\s*$", re.IGNORECASE)


def split_team_league(text: str) -> tuple[str, Optional[Any]]:
    """'Djurgården i SHL' / 'Frölunda shl' / 'Barcelona La Liga' -> ('Djurgården', <League shl>)."""
    words = text.strip(" .!?").split()
    for n in (3, 2, 1):                       # league named at the end
        if len(words) > n:
            league = find_league(" ".join(words[-n:]))
            if league:
                team = words[:-n]
                if team and team[-1].lower() in ("i", "från", "in"):
                    team = team[:-1]
                return " ".join(team), league
    return " ".join(words), None


class SportsAgent:
    AGENT_ID: str = "sports_agent"

    def __init__(self, control: Any, memory_service: Optional[MemoryService] = None) -> None:
        """
        :param control: object with leagues(), set_leagues(list), favorites(), set_favorites(list),
                        set_pause(bool) -> str (until, "HH:MM"), find_team_leagues(team) -> list[str]
        """
        self.control = control
        self.memory = memory_service or MemoryService()
        logger.info("SportsAgent initialized successfully.")

    @staticmethod
    def is_command(message: str) -> bool:
        if any(r.match(message) for r in (ADD_RE, REMOVE_RE, LIST_RE, FAV_LIST_RE, PAUSE_RE, RESUME_RE)):
            return True
        # "lägg till X som favoritlag" - only with the word favorit, so other "lägg till ..." / "följ upp ..." go elsewhere
        return bool(re.search(r"favorit", message, re.IGNORECASE) and (FAV_ADD_RE.match(message) or FAV_REMOVE_RE.match(message)))

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        message = str(payload.get("message", "")).strip()
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=message, agent_id=self.AGENT_ID)
        try:
            reply = self._respond(message)
        except Exception as exc:
            logger.error("SportsAgent failed: %s", exc)
            reply = "Något gick fel när jag skulle ändra sportinställningarna."
        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply

    def _respond(self, message: str) -> str:
        if PAUSE_RE.match(message):
            until = self.control.set_pause(True)
            return f"Matchläge på – inga resultatnotiser och live-ställningar döljs till {until}. Säg \"resultaten igen\" när du vill ha dem tillbaka."
        if RESUME_RE.match(message):
            self.control.set_pause(False)
            return "Matchläget är av – resultat och notiser visas igen."
        if FAV_LIST_RE.match(message):
            return self._list_favorites()
        if ADD_RE.match(message) or REMOVE_RE.match(message) or LIST_RE.match(message):
            return self._leagues(message)
        found = FAV_REMOVE_RE.match(message)
        if found:
            return self._remove_favorite(found.group("name"))
        found = FAV_ADD_RE.match(message)
        if found:
            return self._add_favorite(found.group("name"))
        return self._list_favorites()

    # ------------------------------------------------------------------
    # Favourites
    # ------------------------------------------------------------------

    def _add_favorite(self, text: str) -> str:
        team, league = split_team_league(text)
        team = " ".join(team.split())
        if len(team) < 2:
            return 'Vilket lag? Säg till exempel "lägg till Frölunda i SHL som favoritlag".'
        if league is None:
            leagues = self.control.find_team_leagues(team)
            if len(leagues) == 1:
                league = CATALOG[leagues[0]]
            else:
                hint = f" (jag hittar {team} i {', '.join(CATALOG[k].name for k in leagues)})" if leagues else ""
                return f'Vilken liga spelar {team} i{hint}? Säg till exempel "lägg till {team} i SHL som favoritlag".'
        favorites = list(self.control.favorites())
        if any(fold(f["team"]) == fold(team) and f["league"] == league.key for f in favorites):
            return f"{team} ({league.name}) är redan ett favoritlag."
        if len(favorites) >= 20:
            return "Du har redan 20 favoritlag – ta bort något först."
        self.control.set_favorites(favorites + [{"team": team, "league": league.key}])
        return (f"Klart – {team} ({league.name}) är ett favoritlag. Du får en notis när de börjar spela, "
                f"vid mål och när matchen är slut, och nyheter om laget.")

    def _remove_favorite(self, text: str) -> str:
        team, league = split_team_league(text)
        favorites = list(self.control.favorites())
        keep = [f for f in favorites if not (fold(f["team"]) == fold(team) and (league is None or f["league"] == league.key))]
        if len(keep) == len(favorites):
            return f"{team.strip()} finns inte bland favoritlagen. {self._list_favorites()}"
        self.control.set_favorites(keep)
        return f"{team.strip()} är borttaget från favoritlagen."

    def _list_favorites(self) -> str:
        favorites = self.control.favorites()
        if not favorites:
            return 'Du har inga favoritlag än. Säg till exempel "lägg till Frölunda i SHL som favoritlag".'
        return "Dina favoritlag:\n" + "\n".join(f"• {f['team']} ({CATALOG[f['league']].name})" for f in favorites if f["league"] in CATALOG)

    # ------------------------------------------------------------------
    # Ticker leagues
    # ------------------------------------------------------------------

    def _leagues(self, message: str) -> str:
        current = [k for k in self.control.leagues() if k in CATALOG]
        found = ADD_RE.match(message)
        if found:
            league = find_league(found.group("name"))
            if league is None:
                return f"Jag känner inte till \"{found.group('name').strip()}\". {self._available()}"
            if league.key in current:
                return f"{league.name} finns redan i resultaten."
            if len(current) >= MAX_LEAGUES:
                return f"Resultatraden har redan {MAX_LEAGUES} ligor – ta bort någon först."
            self.control.set_leagues(current + [league.key])
            return f"Klart – {league.name} är tillagd i resultaten. Resultaten dyker upp inom en minut."
        found = REMOVE_RE.match(message)
        if found:
            league = find_league(found.group("name"))
            if league is None or league.key not in current:
                shown = ", ".join(CATALOG[k].name for k in current) or "inga"
                return f"Den ligan finns inte i resultaten. Just nu visas: {shown}."
            self.control.set_leagues([k for k in current if k != league.key])
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
