from typing import Any, Dict

from core.logger import get_logger
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader

logger = get_logger(__name__)


class BusinessAgent:
    """
    BusinessAgent handles requests related to web design, B2B sales, clients,
    and business operations for Nix Studio and Verkstadsflow.
    """

    def __init__(self):
        self.llm = OllamaService()
        self.prompt_loader = PromptLoader()
        # Pre-load the system prompt during initialization
        self.system_prompt = self.prompt_loader.load("business_agent.txt")
        logger.info("BusinessAgent initialized successfully.")

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        """
        Main entry point matching the Agent protocol.
        
        Args:
            action: The action to perform (e.g., "execute").
            payload: Dictionary containing parameters, must include "message".
        
        Returns:
            The generated response from the local LLM.
        """
        logger.info("BusinessAgent received action '%s'", action)
        
        user_message = payload.get("message", "").strip()
        if not user_message:
            logger.warning("Empty message received in BusinessAgent payload.")
            return "BusinessAgent received an empty message."

        # Format the prompt for the LLM using our pre-loaded system rules
        full_prompt = f"""
System Instructions:
{self.system_prompt}

User Request:
"{user_message}"

Provide your professional response:
"""
        
        logger.debug("Sending prompt to Ollama via OllamaService...")
        response = self.llm.chat(full_prompt)
        
        if not response:
            logger.error("Failed to get response from OllamaService.")
            return "Error: BusinessAgent was unable to generate a response."

        logger.info("BusinessAgent successfully processed the request.")
        return response


if __name__ == "__main__":
    # Simple integration test to run the agent standalone
    print("=== TESTING BUSINESS AGENT ===")
    
    # Set PYTHONPATH in terminal beforehand if needed
    agent = BusinessAgent()
    test_payload = {
        "message": "Hur kan Verkstadsflow hjälpa mina bilverkstadskunder?"
    }
    
    reply = agent.handle(action="execute", payload=test_payload)
    print("\nResponse from Agent:")
    print(reply)