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
    OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")
    # Reasoning ("thinking") mode for models that support it, e.g. qwen3.
    # Off by default: much faster replies; turn on for harder reasoning tasks.
    OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in ("1", "true", "yes", "on")
    # Context window (tokens) for chat requests. Ollama's small default can silently cut off the
    # start of long prompts (system prompt + memory + web results). 16384 fits a 12 GB GPU with qwen3:8b.
    OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

    # ------------------------------------------------------
    # Web search (WebSearchService, self-hosted SearXNG)
    # ------------------------------------------------------
    WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:8888")
    WEB_MAX_RESULTS = int(os.getenv("WEB_MAX_RESULTS", "5"))
    WEB_FETCH_PAGES = int(os.getenv("WEB_FETCH_PAGES", "2"))   # 0 = snippets only
    WEB_TIMEOUT_SECONDS = float(os.getenv("WEB_TIMEOUT_SECONDS", "8"))

    # ------------------------------------------------------
    # Reminders & background scheduler
    # ------------------------------------------------------
    SCHEDULER_POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", "30"))
    # Localhost port held as a lock by the one process that owns Jarvis' memory
    # (Jarvis Core, or a standalone scheduler/chat). Prevents two writers.
    JARVIS_LOCK_PORT = int(os.getenv("JARVIS_LOCK_PORT", "47831"))
    REMINDER_CATEGORIES_FILE = BASE_DIR / "data" / "reminder_categories.txt"  # private (data/ is gitignored)

    # ------------------------------------------------------
    # Notifications
    # ------------------------------------------------------
    NOTIFY_WINDOWS = os.getenv("NOTIFY_WINDOWS", "true").strip().lower() in ("1", "true", "yes", "on")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")   # secret - only in .env
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    # Messages older than this (sent while Jarvis was offline) are not executed.
    TELEGRAM_MAX_MESSAGE_AGE_MINUTES = int(os.getenv("TELEGRAM_MAX_MESSAGE_AGE_MINUTES", "10"))
    TELEGRAM_STARTUP_MESSAGE = os.getenv("TELEGRAM_STARTUP_MESSAGE", "true").strip().lower() in ("1", "true", "yes", "on")

    # ------------------------------------------------------
    # Jarvis Core local API (terminal client, future desktop UI)
    # ------------------------------------------------------
    # Bound to localhost only - never reachable from the network.
    JARVIS_API_HOST = "127.0.0.1"
    JARVIS_API_PORT = int(os.getenv("JARVIS_API_PORT", "8765"))
    JARVIS_API_TOKEN_FILE = BASE_DIR / "data" / "api_token.txt"  # auto-generated, private
    OLLAMA_STARTUP_WAIT_SECONDS = int(os.getenv("OLLAMA_STARTUP_WAIT_SECONDS", "300"))

    # ------------------------------------------------------
    # Desktop interface (served by the core, shown by clients/desktop.py)
    # ------------------------------------------------------
    UI_DIR = BASE_DIR / "ui"                   # static files (public, no secrets)
    UI_DATA_DIR = BASE_DIR / "data" / "ui"     # private: settings, background, photos
    DESKTOP_HOTKEY = os.getenv("DESKTOP_HOTKEY", "ctrl+alt+j")

    # ------------------------------------------------------
    # Execution limits
    # ------------------------------------------------------
    # Max seconds one agent step may run before the Planner retries it.
    AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "120"))

    # ------------------------------------------------------
    # Long-term memory (VectorService)
    # ------------------------------------------------------
    # Cosine distance cutoff for search hits (0 = identical, 2 = opposite).
    # Lower = stricter. Tune with: python -m services.vector_service --search "..."
    VECTOR_MAX_DISTANCE = float(os.getenv("VECTOR_MAX_DISTANCE", "0.55"))

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
    DOCUMENTS_DIR = DATA_DIR / "documents"
    VECTOR_STORE_DIR = DATA_DIR / "vector_store"

    @classmethod
    def initialize_system(cls):
        """Self-Healing: Verifies and automatically creates missing system directories."""
        system_dirs = [
            cls.LOGS_DIR,
            cls.DATA_DIR,
            cls.TEMPLATES_DIR,
            cls.PROMPTS_DIR,
            cls.AGENTS_DIR,
            cls.SERVICES_DIR,
            cls.DOCUMENTS_DIR,
            cls.VECTOR_STORE_DIR,
            cls.UI_DATA_DIR,
        ]
        
        for directory in system_dirs:
            # Create directories if they don't exist; exist_ok prevents crashing
            directory.mkdir(parents=True, exist_ok=True)


# Execute the self-healing initialization immediately upon import
Config.initialize_system()

# Security & Operations warning if environment file is missing
if not ENV_PATH.exists():
    print(f"[WARNING] .env file not found at {ENV_PATH}. System running on defaults.", file=sys.stderr)