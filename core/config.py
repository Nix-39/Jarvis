import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ==========================================================
# Project paths
# ==========================================================
# Resolve the absolute path to the root directory (C:\jarvis)
BASE_DIR = Path(__file__).resolve().parent.parent

# Define path to the environment variable file
ENV_PATH = BASE_DIR / ".env"

# Load environment variables securely from the absolute path
load_dotenv(dotenv_path=ENV_PATH)


class Config:
    """Central configuration class for the AI OS.
    
    Manages environment variable validation, project paths, and system-wide
    settings, preventing duplication across agents and services.
    """
    
    # ------------------------------------------------------
    # Environment settings
    # ------------------------------------------------------
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

    # ------------------------------------------------------
    # AI Engine settings (Ollama)
    # ------------------------------------------------------
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    # ------------------------------------------------------
    # System logging
    # ------------------------------------------------------
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # ------------------------------------------------------
    # Unified project directories
    # ------------------------------------------------------
    LOGS_DIR = BASE_DIR / "logs"
    DATA_DIR = BASE_DIR / "data"
    TEMPLATES_DIR = BASE_DIR / "templates"
    PROMPTS_DIR = BASE_DIR / "prompts"
    AGENTS_DIR = BASE_DIR / "agents"
    SERVICES_DIR = BASE_DIR / "services"

    @classmethod
    def initialize_system(cls):
        """Self-Healing: Verifies and automatically creates missing system directories."""
        system_dirs = [
            cls.LOGS_DIR,
            cls.DATA_DIR,
            cls.TEMPLATES_DIR,
            cls.PROMPTS_DIR,
            cls.AGENTS_DIR,
            cls.SERVICES_DIR
        ]
        
        for directory in system_dirs:
            # Create directories if they don't exist; exist_ok prevents crashing
            directory.mkdir(parents=True, exist_ok=True)


# Execute the self-healing initialization immediately upon import
Config.initialize_system()

# Security & Operations warning if environment file is missing
if not ENV_PATH.exists():
    print(f"[WARNING] .env file not found at {ENV_PATH}. System running on defaults.", file=sys.stderr)