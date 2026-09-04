from typing import Any, Dict

from core.logger import get_logger
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader

logger = get_logger(__name__)


class WebDeveloperAgent:
    """
    WebDeveloperAgent handles technical web development requests related to
    WordPress, Elementor, web technologies, hosting, performance, security,
    and AI integrations.
    """

    def __init__(self):
        self.llm = OllamaService()
        self.prompt_loader = PromptLoader()

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

        full_prompt = f"""
System Instructions:
{self.system_prompt}

User Request:
"{user_message}"

Provide your professional technical response:
"""

        logger.debug("Sending prompt to Ollama via OllamaService...")

        response = self.llm.chat(full_prompt)

        if not response:
            logger.error("Failed to get response from OllamaService.")
            return "Error: WebDeveloperAgent was unable to generate a response."

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