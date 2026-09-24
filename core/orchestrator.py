# core/orchestrator.py

"""
Orchestrator module for the Jarvis Agent Operating System.

Serves as the main system entry point coordinating the end-to-end execution pipeline:
User Request -> Intent Classification (Router) -> Category Mapping -> Execution Planning (Planner) -> Agent Execution.
"""

from typing import Dict, Final, Optional

from core.logger import get_logger
from core.planner import Agent, Planner, PlannerResult
from core.router import Router
from services.memory_service import MemoryService
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader

from agents.business_agent import BusinessAgent
from agents.career_agent import CareerAgent
from agents.contentcreator_agent import ContentCreatorAgent
from agents.education_agent import EducationAgent
from agents.general_agent import GeneralAgent
from agents.socialmediamanager_agent import SocialMediaManagerAgent
from agents.webdeveloper_agent import WebDeveloperAgent

logger = get_logger(__name__)


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
    }

    DEFAULT_AGENT_ID: str = "general_agent"

    def __init__(
        self,
        ollama_service: Optional[OllamaService] = None,
        prompt_loader: Optional[PromptLoader] = None,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        """
        Initialize the Orchestrator with infrastructure services, router, and registered agents.

        :param ollama_service: Optional OllamaService instance. Self-initialized if None.
        :param prompt_loader: Optional PromptLoader instance. Self-initialized if None.
        :param memory_service: Optional MemoryService instance. Self-initialized if None.
        """
        logger.info("Initializing Jarvis Orchestrator pipeline...")

        self.ollama_service = ollama_service or OllamaService()
        self.prompt_loader = prompt_loader or PromptLoader()
        self.memory_service = memory_service or MemoryService()

        # 1. Initialize Router with shared infrastructure services
        self.router = Router(
            ollama_service=self.ollama_service,
            prompt_loader=self.prompt_loader,
        )

        # 2. Instantiate and register all 7 specialist agents matching exact snapshot naming
        self.agent_registry: Dict[str, Agent] = {
            "business_agent": BusinessAgent(memory_service=self.memory_service),
            "career_agent": CareerAgent(memory_service=self.memory_service),
            "webdeveloper_agent": WebDeveloperAgent(memory_service=self.memory_service),
            "education_agent": EducationAgent(memory_service=self.memory_service),
            "general_agent": GeneralAgent(memory_service=self.memory_service),
            "socialmediamanager_agent": SocialMediaManagerAgent(memory_service=self.memory_service),
            "contentcreator_agent": ContentCreatorAgent(memory_service=self.memory_service),
        }

        # 3. Initialize Planner with the validated agent registry
        self.planner = Planner(agent_registry=self.agent_registry)

        logger.info(
            "Jarvis Orchestrator fully online | registered_agents=%s",
            list(self.agent_registry.keys()),
        )

    def process_query(self, user_message: str) -> PlannerResult:
        """
        Process a user query through the complete execution pipeline:
        Router Intent Classification -> Category Mapping -> Planner Execution -> Result.

        :param user_message: Raw input text query from the user.
        :return: Immutable PlannerResult containing execution metadata and final response.
        """
        # Format clean display preview for single-line audit logging
        preview = user_message.strip() if user_message else ""
        display_input = preview[:50] + ("..." if len(preview) > 50 else "")
        logger.info(f"Processing user query: '{display_input}'")

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

        # Step 3: Pass execution plan to Planner
        return self.planner.run(target_agent=target_agent_id, user_message=user_message)


if __name__ == "__main__":
    # Integration test verifying the end-to-end orchestration pipeline
    print("=== JARVIS SYSTEM INTEGRATION TEST ===")

    orchestrator = JarvisOrchestrator()

    test_query = "Hur skapar jag en prisstrategi för min bilverkstadsagent i VerkstadsFlow?"
    print(f"\nUser > {test_query}")

    res = orchestrator.process_query(test_query)

    print("\n=== EXECUTION RESULT ===")
    print(f"Plan ID: {res.plan_id}")
    print(f"Agent Used: {res.agent_used}")
    print(f"Success: {res.success}")
    print(f"Execution Time: {res.execution_time_seconds:.2f}s")
    print(f"Response:\n{res.final_response}")
    print("=" * 50)