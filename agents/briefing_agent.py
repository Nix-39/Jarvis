"""
BriefingAgent - the morning briefing, only when the user asks for it.

    "Nexus, morgonbriefing" / "briefing" / "god morgon Nexus" / "vad händer idag?"

No language model: fixed patterns pick the command and BriefingService writes
the briefing from facts with templates. The reply is the briefing as text (with
links when asked from Telegram); a "briefing.ready" event carries the sections
for the card in the window, and Jarvis Core reads the short spoken version.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.events import event_bus
from core.logger import get_logger
from services.memory_service import DEFAULT_SESSION_ID, MemoryService

logger = get_logger(__name__)

_NAME = r"(?:(?:hej|god\s+morgon)\s+)?(?:(?:nexus|oden)[\s,:!.-]*)?"
BRIEFING_RE = re.compile(
    r"^\s*" + _NAME + r"(?:(?:ge mig |kör |visa |läs upp |starta )?(?:en |min |dagens )?(?:morgon)?(?:briefing|briefingen|rapport)"
    r"|morgonbriefing(?:en)?|morgonrapport(?:en)?|vad händer idag|vad är på gång idag|vad har vi idag|hur ser dagen ut)"
    r"(?:\s+(?:nexus|tack|idag))?\s*[?.!]*\s*$", re.IGNORECASE)
GOOD_MORNING_RE = re.compile(r"^\s*god\s*morgon(?:\s+(?:nexus|oden))?\s*[!.]*\s*$", re.IGNORECASE)


class BriefingAgent:
    AGENT_ID: str = "briefing_agent"

    def __init__(self, briefing_service: Any, memory_service: Optional[MemoryService] = None) -> None:
        self.briefing = briefing_service
        self.memory = memory_service or MemoryService()
        self.channel = "terminal"          # set by the Orchestrator before each run (links only for Telegram)
        logger.info("BriefingAgent initialized successfully.")

    @staticmethod
    def is_command(message: str) -> bool:
        return bool(BRIEFING_RE.match(message) or GOOD_MORNING_RE.match(message))

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        message = str(payload.get("message", "")).strip()
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=message, agent_id=self.AGENT_ID)
        try:
            briefing = self.briefing.build()
            event_bus.publish("briefing.ready", "briefing", briefing.title, briefing=briefing.to_dict())
            reply = briefing.text(links=self.channel == "telegram")
        except Exception as exc:
            logger.exception("Briefing failed: %s", exc)
            reply = "Jag kunde inte sätta ihop briefingen just nu."
        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply
