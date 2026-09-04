from pathlib import Path
from core.config import Config
from core.logger import get_logger

logger = get_logger(__name__)


class PromptLoader:
    """
    Handles all prompt file loading for the entire system.

    No component should read prompt files directly.
    All prompt access goes through this service.
    """

    def __init__(self):
        self.prompts_dir = Config.PROMPTS_DIR
        logger.info("PromptLoader initialized. Prompts directory: %s", self.prompts_dir)

    def load(self, filename: str) -> str:
        """
        Loads a prompt file from the prompts directory.

        Args:
            filename: Name of the prompt file, e.g. 'router.txt'

        Returns:
            The prompt content as a string.

        Raises:
            FileNotFoundError: If the prompt file does not exist.
        """
        prompt_path = self.prompts_dir / filename

        if not prompt_path.exists():
            logger.error("Prompt file not found: %s", prompt_path)
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        content = prompt_path.read_text(encoding="utf-8")
        logger.debug("Prompt loaded: %s", filename)
        return content