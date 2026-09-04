import ollama
from core.config import Config
from core.logger import get_logger

logger = get_logger(__name__)


class OllamaService:
    """
    Handles all communication with the Ollama API.

    No other component should call ollama directly.
    All LLM requests go through this service.
    """

    def __init__(self):
        self.model = Config.OLLAMA_MODEL
        self.host = Config.OLLAMA_HOST
        logger.info("OllamaService initialized. Model: %s | Host: %s", self.model, self.host)

    def chat(self, prompt: str) -> str:
        """
        Sends a prompt to Ollama and returns the response as a string.

        Args:
            prompt: The full prompt to send.

        Returns:
            The model's response as a plain string, or empty string on failure.
        """
        logger.debug("OllamaService sending prompt to model.")

        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            content = response["message"]["content"].strip()
            logger.debug("OllamaService received response.")
            return content

        except Exception as e:
            logger.error("OllamaService failed to get response: %s", e)
            return ""