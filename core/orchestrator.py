# core/orchestrator.py

"""
Orchestrator module for the Jarvis Agent Operating System.

Serves as the main system entry point coordinating the end-to-end execution pipeline:
User Request -> Intent Classification (Router) -> Category Mapping -> Execution Planning (Planner) -> Agent Execution.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Final, Optional

from core.events import event_bus
from core.logger import get_logger
from core.planner import Agent, Planner, PlannerResult
from core.router import Router
from services.memory_service import MemoryService
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader
from services.reminder_service import ReminderService
from services.vector_service import VectorService
from services.web_search_service import WebSearchService

from agents.business_agent import BusinessAgent
from agents.career_agent import CareerAgent
from agents.contentcreator_agent import ContentCreatorAgent
from agents.education_agent import EducationAgent
from agents.general_agent import GeneralAgent
from agents.reminder_agent import ReminderAgent
from agents.socialmediamanager_agent import SocialMediaManagerAgent
from agents.webdeveloper_agent import WebDeveloperAgent

logger = get_logger(__name__)

# Short replies that answer an agent's pending question ("ja", "nej", "kl 11 istället").
_REPLY_START = re.compile(
    r"^\s*(ja|japp|jajamän|jo|jepp|ok|okej|okey|kör|gör det|stämmer|korrekt|precis|absolut|visst|"
    r"perfekt|yes|nej|nä|nää|nope|no|avbryt|stopp|glöm det|strunta i det|ändra|hellre)\b",
    re.IGNORECASE,
)
_REPLY_CORRECTION = re.compile(
    r"\d|\bkl\b|imorgon|idag|ikväll|istället|måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag",
    re.IGNORECASE,
)
_PENDING_TTL = timedelta(minutes=15)


class JarvisOrchestrator:
    """
    Main orchestration engine for Jarvis.

    Coordinates intent classification routing, category-to-agent mapping,
    and structured execution planning across all registered specialist agents.
    """

    # Explicit immutable mapping between Router categories and registered Agent IDs in Planner
    CATEGORY_TO_AGENT_MAP: Final[Dict[str, str]] = {
        "business": "business_agent",
        "career": "career_agent",
        "web_development": "webdeveloper_agent",
        "education": "education_agent",
        "general": "general_agent",
        "social_media": "socialmediamanager_agent",
        "content_creation": "contentcreator_agent",
        "reminders": "reminder_agent",
    }

    DEFAULT_AGENT_ID: str = "general_agent"

    def __init__(
        self,
        ollama_service: Optional[OllamaService] = None,
        prompt_loader: Optional[PromptLoader] = None,
        memory_service: Optional[MemoryService] = None,
        vector_service: Optional[VectorService] = None,
        web_service: Optional[WebSearchService] = None,
        reminder_service: Optional[ReminderService] = None,
    ) -> None:
        """
        Initialize the Orchestrator with infrastructure services, router, and registered agents.

        :param ollama_service: Optional OllamaService instance. Self-initialized if None.
        :param prompt_loader: Optional PromptLoader instance. Self-initialized if None.
        :param memory_service: Optional MemoryService instance. Self-initialized if None.
        :param vector_service: Optional VectorService instance. Self-initialized if None.
        :param web_service: Optional WebSearchService instance. Self-initialized if None.
        :param reminder_service: Optional ReminderService instance. Self-initialized if None.
        """
        logger.info("Initializing Jarvis Orchestrator pipeline...")

        self.ollama_service = ollama_service or OllamaService()
        self.prompt_loader = prompt_loader or PromptLoader()
        self.memory_service = memory_service or MemoryService()
        self.vector_service = vector_service or VectorService(
            memory_service=self.memory_service,
            ollama_service=self.ollama_service,
        )
        self.web_service = web_service or WebSearchService(ollama_service=self.ollama_service)
        self.reminder_service = reminder_service or ReminderService()
        if self.web_service.enabled and not self.web_service.is_available():
            logger.warning(
                "SearXNG is not reachable at %s - answers will lack live web information. "
                "Start it with: docker compose up -d (in docker/searxng).",
                self.web_service.searxng_url,
            )

        # 1. Initialize Router with shared infrastructure services
        self.router = Router(
            ollama_service=self.ollama_service,
            prompt_loader=self.prompt_loader,
        )

        # 2. Instantiate and register all 7 specialist agents matching exact snapshot naming
        self.agent_registry: Dict[str, Agent] = {
            "business_agent": BusinessAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "career_agent": CareerAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "webdeveloper_agent": WebDeveloperAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "education_agent": EducationAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "general_agent": GeneralAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "socialmediamanager_agent": SocialMediaManagerAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
            "reminder_agent": ReminderAgent(
                memory_service=self.memory_service,
                reminder_service=self.reminder_service,
                ollama_service=self.ollama_service,
            ),
            "contentcreator_agent": ContentCreatorAgent(
                memory_service=self.memory_service,
                vector_service=self.vector_service,
                web_service=self.web_service,
            ),
        }

        # 3. Initialize Planner with the validated agent registry
        self.planner = Planner(agent_registry=self.agent_registry)

        # 4. Bring long-term memory up to date before handling requests.
        #    Runs outside the Planner's per-step timeout, so bulk indexing of
        #    new documents happens here instead of during a user request.
        self.vector_service.sync_all()

        logger.info(
            "Jarvis Orchestrator fully online | registered_agents=%s",
            list(self.agent_registry.keys()),
        )

    def process_query(self, user_message: str, channel: str = "terminal") -> PlannerResult:
        """
        Process a user query through the complete execution pipeline:
        Router Intent Classification -> Category Mapping -> Planner Execution -> Result.

        :param user_message: Raw input text query from the user.
        :param channel: Where the query came from ("terminal", "telegram", "ui") - for the event feed.
        :return: Immutable PlannerResult containing execution metadata and final response.
        """
        # Format clean display preview for single-line audit logging
        preview = user_message.strip() if user_message else ""
        display_input = preview[:50] + ("..." if len(preview) > 50 else "")
        logger.info(f"Processing user query: '{display_input}'")
        event_bus.publish(
            "query.received", "orchestrator", f"Ny fråga via {channel}: {display_input}", channel=channel
        )

        # Step 0: A short reply to an agent that is waiting for confirmation goes
        #         straight back to that agent (e.g. "ja" after a reminder proposal).
        pending_agent_id = self._agent_awaiting_reply(user_message)
        if pending_agent_id:
            logger.info(f"Routing reply to agent awaiting confirmation: '{pending_agent_id}'.")
            event_bus.publish(
                "agent.selected", "orchestrator", f"Svar på väntande fråga → {pending_agent_id}",
                agent=pending_agent_id, category=None, reason="pending_reply",
            )
            return self._run(pending_agent_id, user_message)

        # Step 1: Classify request intent category via Router
        category = self.router.classify_intent(user_message)

        # Step 2: Map intent category to target Agent ID
        target_agent_id = self.CATEGORY_TO_AGENT_MAP.get(category, self.DEFAULT_AGENT_ID)

        # Zero Trust defense: Verify that the target agent ID actually exists in the registry
        if target_agent_id not in self.agent_registry:
            logger.error(
                f"Mapped agent ID '{target_agent_id}' not found in registry. "
                f"Falling back to default agent '{self.DEFAULT_AGENT_ID}'."
            )
            target_agent_id = self.DEFAULT_AGENT_ID

        logger.info(f"Routed category '{category}' mapped to target agent '{target_agent_id}'.")
        event_bus.publish(
            "agent.selected", "orchestrator", f"Kategori '{category}' → {target_agent_id}",
            agent=target_agent_id, category=category, reason="router",
        )

        # Step 3: Pass execution plan to Planner
        return self._run(target_agent_id, user_message)

    def _run(self, agent_id: str, user_message: str) -> PlannerResult:
        """Run the agent through the Planner and report the outcome on the event feed."""
        started = time.monotonic()
        result = self.planner.run(target_agent=agent_id, user_message=user_message)
        seconds = round(time.monotonic() - started, 1)
        event_bus.publish(
            "query.completed", "orchestrator",
            f"{agent_id} svarade på {seconds}s" if result.success else f"{agent_id} misslyckades",
            agent=agent_id, success=result.success, seconds=seconds,
        )
        return result

    def _agent_awaiting_reply(self, user_message: str) -> Optional[str]:
        """
        Return the agent that has a fresh pending proposal (state key
        '<agent_id>.pending') if the message looks like a reply to it.
        """
        message = (user_message or "").strip()
        looks_like_reply = bool(_REPLY_START.match(message)) or (
            len(message.split()) <= 8 and bool(_REPLY_CORRECTION.search(message))
        )
        if not looks_like_reply:
            return None

        for agent_id in self.agent_registry:
            pending = self.memory_service.get_state(f"{agent_id}.pending")
            if not isinstance(pending, dict):
                continue
            try:
                created = datetime.fromisoformat(pending["created"])
            except (KeyError, ValueError):
                continue
            if datetime.now(timezone.utc) - created <= _PENDING_TTL:
                return agent_id
        return None


if __name__ == "__main__":
    # Standalone debug chat:  python -m core.orchestrator [--verbose]
    # Normal use goes through Jarvis Core (jarvis.bat -> clients.terminal). This
    # mode refuses to start while the core runs: two processes writing the same
    # long-term memory (ChromaDB) at once can corrupt it.
    import logging
    import sys

    from core.single_instance import acquire_lock

    instance_lock = acquire_lock()
    if instance_lock is None:
        print("Jarvis Core körs redan i bakgrunden - använd jarvis.bat istället.")
        print("(Felsökningsläget kan bara köras när Jarvis Core är stoppad.)")
        sys.exit(0)

    EXIT_COMMANDS = {"exit", "quit", "avsluta", "hejdå", "hej då"}

    # Keep the terminal readable: console shows warnings/errors only unless --verbose.
    # Full INFO logs are still written to logs/jarvis.log.
    if "--verbose" not in sys.argv:
        for handler in logging.getLogger("jarvis").handlers:
            if type(handler) is logging.StreamHandler:
                handler.setLevel(logging.WARNING)

    print("=== JARVIS (felsökningsläge, utan Jarvis Core) ===")
    print("Startar och synkar långtidsminnet...")
    orchestrator = JarvisOrchestrator()
    print("Redo. Skriv din fråga ('exit' eller Ctrl+C avslutar).")

    while True:
        try:
            user_input = input("\nDu > ").strip()
            if not user_input:
                continue
            if user_input.lower() in EXIT_COMMANDS:
                break

            result = orchestrator.process_query(user_input, channel="debug")
            print(
                f"\nJarvis [{result.agent_used} · {result.execution_time_seconds:.1f}s] >\n"
                f"{result.final_response}"
            )
        except (KeyboardInterrupt, EOFError):
            print()
            break

    print("Hej då!")