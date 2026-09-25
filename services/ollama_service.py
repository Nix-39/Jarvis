import re
from typing import Any, Dict, List

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
        self.embed_model = Config.OLLAMA_EMBED_MODEL
        self.host = Config.OLLAMA_HOST
        self.think = Config.OLLAMA_THINK
        self._think_supported = True
        logger.info(
            "OllamaService initialized. Model: %s | Host: %s | Thinking: %s",
            self.model,
            self.host,
            "on" if self.think else "off",
        )

    def chat(self, prompt: str) -> str:
        """
        Sends a prompt to Ollama and returns the response as a string.

        Args:
            prompt: The full prompt to send.

        Returns:
            The model's response as a plain string, or empty string on failure.
        """
        logger.debug("OllamaService sending prompt to model.")

        request: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        }
        if self._think_supported:
            request["think"] = self.think

        try:
            try:
                response = ollama.chat(**request)
            except Exception as e:
                # Models without a thinking mode (e.g. llama3.1) may reject the flag.
                if "think" not in request or "think" not in str(e).lower():
                    raise
                logger.info("Model '%s' has no thinking mode; sending requests without it.", self.model)
                self._think_supported = False
                request.pop("think")
                response = ollama.chat(**request)

            content = self._strip_thinking(response["message"]["content"])
            logger.debug("OllamaService received response.")
            return content

        except Exception as e:
            logger.error("OllamaService failed to get response: %s", e)
            return ""

    @staticmethod
    def _strip_thinking(content: str) -> str:
        """Remove any <think>...</think> block a reasoning model left in its answer."""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Converts texts into embedding vectors using the configured embedding model.

        Unlike chat(), failures are raised instead of swallowed, so callers never
        store empty or invalid vectors.

        Args:
            texts: The texts to embed (batched in a single request).

        Returns:
            One embedding vector per input text, in the same order.

        Raises:
            RuntimeError: If the embedding request fails or returns unexpected data.
        """
        if not texts:
            return []

        logger.debug("OllamaService embedding %s text(s) with %s.", len(texts), self.embed_model)

        try:
            response = ollama.embed(model=self.embed_model, input=texts)
        except Exception as e:
            logger.error(
                "OllamaService failed to create embeddings with '%s': %s "
                "(is the model pulled? run: ollama pull %s)",
                self.embed_model,
                e,
                self.embed_model,
            )
            raise RuntimeError(f"Embedding request failed: {e}") from e

        embeddings = response["embeddings"]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding count mismatch: sent {len(texts)} text(s), got {len(embeddings)} vector(s)."
            )

        return [list(vector) for vector in embeddings]
