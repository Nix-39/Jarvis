from typing import Any, Dict, Optional

from core.logger import get_logger
from services.memory_service import (
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_SESSION_ID,
    MemoryService,
    format_conversation_history,
)
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader
from services.vector_service import VectorService

logger = get_logger(__name__)


class WebDeveloperAgent:
    """
    WebDeveloperAgent handles technical web development requests related to
    WordPress, Elementor, web technologies, hosting, performance, security,
    and AI integrations.
    """

    AGENT_ID: str = "webdeveloper_agent"

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        vector_service: Optional[VectorService] = None,
    ):
        self.llm = OllamaService()
        self.prompt_loader = PromptLoader()
        self.memory = memory_service or MemoryService()
        self.vector = vector_service or VectorService(
            memory_service=self.memory, ollama_service=self.llm
        )

        # Pre-load the system prompt during initialization
        self.system_prompt = self.prompt_loader.load("webdeveloper_agent.txt")

        logger.info("WebDeveloperAgent initialized successfully.")

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        """
        Main entry point matching the Agent protocol.

        Args:
            action: The action to perform (e.g. "execute").
            payload: Dictionary containing parameters, must include "message".

        Returns:
            The generated response from the local LLM.
        """
        logger.info("WebDeveloperAgent received action '%s'", action)

        user_message = payload.get("message", "").strip()

        if not user_message:
            logger.warning("Empty message received in WebDeveloperAgent payload.")
            return "WebDeveloperAgent received an empty message."

        history = self.memory.get_session_messages(
            session_id=DEFAULT_SESSION_ID,
            agent_id=self.AGENT_ID,
            limit=DEFAULT_CONTEXT_LIMIT,
        )
        conversation_context = format_conversation_history(history)

        # Long-term memory: relevant older messages (all agents) + documents.
        # Fetched before saving the current message so it can't match itself.
        background_context = self.vector.build_context(
            user_message, exclude_message_ids=[msg.id for msg in history]
        )

        self.memory.save_message(
            DEFAULT_SESSION_ID, role="user", content=user_message, agent_id=self.AGENT_ID
        )

        full_prompt = f"""
System Instructions:
{self.system_prompt}

Relevant bakgrund (från långtidsminnet – använd bara om det är relevant för frågan):
{background_context}

Tidigare konversation:
{conversation_context}

User Request:
"{user_message}"

Provide your professional technical response:
"""

        logger.debug("Sending prompt to Ollama via OllamaService...")

        response = self.llm.chat(full_prompt)

        if not response:
            logger.error("Failed to get response from OllamaService.")
            return "Error: WebDeveloperAgent was unable to generate a response."

        self.memory.save_message(
            DEFAULT_SESSION_ID, role="agent", content=response, agent_id=self.AGENT_ID
        )

        logger.info("WebDeveloperAgent successfully processed the request.")
        return response


if __name__ == "__main__":
    print("=== TESTING WEB DEVELOPER AGENT ===")

    agent = WebDeveloperAgent()

    test_payload = {
        "message": (
            "Hur kan jag optimera en WordPress-webbplats byggd med Elementor "
            "för bättre prestanda och Core Web Vitals?"
        )
    }

    reply = agent.handle(action="execute", payload=test_payload)

    print("\nResponse from Agent:")
    print(reply)