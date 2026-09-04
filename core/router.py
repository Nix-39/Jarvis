# core/router.py

"""
Router module for the Jarvis Agent Operating System.

The Router is responsible solely for intent classification. It analyzes incoming
user requests using a local LLM and returns a validated category identifier.
It contains no business logic, agent instantiation, or orchestrator mapping.
"""

from typing import Dict, Tuple
from core.logger import get_logger
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader

logger = get_logger(__name__)


class Router:
    """
    Classify user requests and return a validated category identifier.

    Delegates intent classification to a local LLM via OllamaService, validates
    the response against an ordered whitelist of supported categories, and ensures
    deterministic fallback behavior with comprehensive audit logging.
    """

    # Deterministic ordered tuple of official category identifiers
    VALID_CATEGORIES: Tuple[str, ...] = (
        "business",
        "career",
        "web_development",
        "education",
        "general",
        "social_media",
        "content_creation",
    )

    # Controlled whitelist mapping prompt variations/shorthands to canonical categories
    CATEGORY_ALIASES: Dict[str, str] = {
        "web_developer": "web_development",
        "development": "web_development",
        "web_dev": "web_development",
        "social_media_manager": "social_media",
        "content_creator": "content_creation",
    }

    DEFAULT_CATEGORY: str = "general"

    def __init__(
        self,
        ollama_service: OllamaService,
        prompt_loader: PromptLoader,
    ) -> None:
        """
        Initialize the Router with required infrastructure services.

        :param ollama_service: Service for executing LLM completion requests.
        :param prompt_loader: Service for loading system prompts from file.
        """
        self.ollama_service = ollama_service
        self.prompt_loader = prompt_loader

    def classify_intent(self, user_input: str) -> str:
        """
        Classify a user request to determine the appropriate category.

        Loads the router classification prompt, queries the local LLM via OllamaService,
        and validates the returned category against supported identifiers.

        :param user_input: Raw text request from the user.
        :return: Validated category identifier.
        """
        if not user_input or not user_input.strip():
            logger.warning("Received empty user input. Falling back to default category.")
            return self.DEFAULT_CATEGORY

        try:
            # Synchronized with PromptLoader.load()
            system_prompt = self.prompt_loader.load("router.txt")

            # Formatted prompt structure matching standard agent implementation
            full_prompt = (
                f"System Instructions:\n{system_prompt}\n\n"
                f"User Request:\n\"{user_input.strip()}\"\n\n"
                f"Classification:"
            )

            # Synchronized with OllamaService.chat()
            raw_response = self.ollama_service.chat(full_prompt)

            category = self._clean_and_validate_response(raw_response)

            # Clean and format display string for single-line audit logging
            preview = user_input.strip()
            display_input = preview[:50] + ("..." if len(preview) > 50 else "")

            logger.info(f"Classified request as '{category}' for input: '{display_input}'")
            return category

        except Exception as e:
            logger.error(
                f"Error during intent classification: {e}. "
                f"Falling back to default category '{self.DEFAULT_CATEGORY}'."
            )
            return self.DEFAULT_CATEGORY

    def _clean_and_validate_response(self, raw_response: str) -> str:
        """
        Normalize and validate the LLM response string.

        Replaces punctuation with whitespace to prevent token merging, tokenizes
        the output into discrete words, normalizes aliases, and validates against
        the supported category list.

        :param raw_response: Raw response string from the LLM.
        :return: Validated category identifier.
        """
        if not raw_response or not raw_response.strip():
            logger.warning(
                "Received empty classification response from LLM. "
                f"Falling back to default category '{self.DEFAULT_CATEGORY}'."
            )
            return self.DEFAULT_CATEGORY

        cleaned = raw_response.strip().lower()

        # Replace punctuation and special whitespace with space to isolate tokens safely
        for char in ['"', "'", '`', '*', '#', '.', ',', ':', ';', '!', '?', '[', ']', '(', ')', '{', '}', '\n', '\r', '\t']:
            cleaned = cleaned.replace(char, ' ')

        # Tokenize response into discrete words
        tokens = cleaned.split()
        if not tokens:
            logger.warning(
                f"No structural tokens extracted from response: raw='{raw_response.strip()}'. "
                f"Falling back to default category '{self.DEFAULT_CATEGORY}'."
            )
            return self.DEFAULT_CATEGORY

        # Normalize tokens via explicit alias mapping
        normalized_tokens = [self.CATEGORY_ALIASES.get(token, token) for token in tokens]

        # Primary check: Test the first extracted token
        first_token = normalized_tokens[0]
        if first_token in self.VALID_CATEGORIES:
            return first_token

        # Secondary check: Search remaining tokens deterministically for valid category
        for token in normalized_tokens:
            if token in self.VALID_CATEGORIES:
                logger.info(f"Extracted valid category '{token}' from normalized LLM output.")
                return token

        # Traceability warning for unclassifiable LLM outputs
        logger.warning(
            f"Model returned unclassifiable output. Raw='{raw_response.strip()}', "
            f"Cleaned='{cleaned}'. Falling back to default category '{self.DEFAULT_CATEGORY}'."
        )
        return self.DEFAULT_CATEGORY