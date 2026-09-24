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

logger = get_logger(__name__)


class ContentCreatorAgent:
    """
    ContentCreatorAgent handles the generation of high-quality written content,
    SEO articles, affiliate copy, scripts, and newsletters for Robin's brands.
    """

    AGENT_ID: str = "contentcreator_agent"

    def __init__(self, memory_service: Optional[MemoryService] = None):
        self.llm = OllamaService()
        self.prompt_loader = PromptLoader()
        self.memory = memory_service or MemoryService()
        # Pre-load the system prompt during initialization
        self.system_prompt = self.prompt_loader.load("contentcreator_agent.txt")
        logger.info("ContentCreatorAgent initialized successfully.")

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        """
        Main entry point matching the Agent protocol.
        
        Args:
            action: The action to perform (e.g., "execute").
            payload: Dictionary containing parameters, must include "message".
        
        Returns:
            The generated response from the local LLM.
        """
        logger.info("ContentCreatorAgent received action '%s'", action)
        
        user_message = payload.get("message", "").strip()
        if not user_message:
            logger.warning("Empty message received in ContentCreatorAgent payload.")
            return "ContentCreatorAgent received an empty message."

        # Format the prompt for the LLM using our pre-loaded system rules
        history = self.memory.get_session_messages(
            session_id=DEFAULT_SESSION_ID,
            agent_id=self.AGENT_ID,
            limit=DEFAULT_CONTEXT_LIMIT,
        )
        conversation_context = format_conversation_history(history)

        self.memory.save_message(
            DEFAULT_SESSION_ID, role="user", content=user_message, agent_id=self.AGENT_ID
        )

        full_prompt = f"""
System Instructions:
{self.system_prompt}

Tidigare konversation:
{conversation_context}

User Request:
"{user_message}"

Provide your professional creative response:
"""
        
        logger.debug("Sending prompt to Ollama via OllamaService...")
        response = self.llm.chat(full_prompt)
        
        if not response:
            logger.error("Failed to get response from OllamaService.")
            return "Error: ContentCreatorAgent was unable to generate a response."

        self.memory.save_message(
            DEFAULT_SESSION_ID, role="agent", content=response, agent_id=self.AGENT_ID
        )

        logger.info("ContentCreatorAgent successfully processed the request.")
        return response


if __name__ == "__main__":
    # Simple integration test to run the agent standalone
    print("=== TESTING CONTENT CREATOR AGENT ===")
    
    # Ensure PYTHONPATH is set in your terminal when testing
    agent = ContentCreatorAgent()
    
    # Test case requesting an affiliate-focused SEO intro for The AI Duck
    test_payload = {
        "message": (
            "För 'The AI Duck' (engelska): Skriv en engagerande och SEO-optimerad introduktion "
            "till en bloggpost som handlar om varför man behöver en VPN 2026. Fokusera på "
            "hur användare spåras av ISP:er och annonsörer. Inkludera en tydlig CTA för en affiliate-länk."
        )
    }
    
    reply = agent.handle(action="execute", payload=test_payload)
    print("\nResponse from Agent:")
    print(reply)