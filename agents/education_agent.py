from typing import Any, Dict

from core.logger import get_logger
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader

logger = get_logger(__name__)


class EducationAgent:
    """
    EducationAgent handles requests related to personalized learning,
    study plans, practical labs, and skill assessments.
    """

    def __init__(self):
        self.llm = OllamaService()
        self.prompt_loader = PromptLoader()
        # Pre-load the system prompt during initialization
        self.system_prompt = self.prompt_loader.load("education_agent.txt")
        logger.info("EducationAgent initialized successfully.")

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        """
        Main entry point matching the Agent protocol.
        
        Args:
            action: The action to perform (e.g., "execute").
            payload: Dictionary containing parameters, must include "message".
        
        Returns:
            The generated response from the local LLM.
        """
        logger.info("EducationAgent received action '%s'", action)
        
        user_message = payload.get("message", "").strip()
        if not user_message:
            logger.warning("Empty message received in EducationAgent payload.")
            return "EducationAgent received an empty message."

        # Format the prompt for the LLM using our pre-loaded system rules
        full_prompt = f"""
System Instructions:
{self.system_prompt}

User Request:
"{user_message}"

Provide your professional educational response:
"""
        
        logger.debug("Sending prompt to Ollama via OllamaService...")
        response = self.llm.chat(full_prompt)
        
        if not response:
            logger.error("Failed to get response from OllamaService.")
            return "Error: EducationAgent was unable to generate a response."

        logger.info("EducationAgent successfully processed the request.")
        return response


if __name__ == "__main__":
    # Simple integration test to run the agent standalone
    print("=== TESTING EDUCATION AGENT ===")
    
    # Ensure PYTHONPATH is set in your terminal when testing
    agent = EducationAgent()
    test_payload = {
        "message": "Skapa en grundläggande labbyta för att lära mig OWASP Top 10 SQL Injection på ett säkert sätt."
    }
    
    reply = agent.handle(action="execute", payload=test_payload)
    print("\nResponse from Agent:")
    print(reply)