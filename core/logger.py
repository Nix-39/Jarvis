import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from core.config import Config


# ==============================================================
# Constants
# ==============================================================
LOG_FILE_NAME = "jarvis.log"
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB per log file
BACKUP_COUNT = 3                        # Keep 3 rotated backups


def _resolve_log_level(level_string: str) -> int:
    """
    Converts a string log level from .env to a logging integer constant.
    Falls back to INFO if the value is invalid.
    """
    level = logging.getLevelName(level_string.upper())
    if isinstance(level, int):
        return level
    return logging.INFO


def _build_formatter() -> logging.Formatter:
    """
    Defines the unified log format used across all handlers.
    Format: [TIMESTAMP] [LEVEL] [COMPONENT] Message
    """
    return logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def _build_console_handler(level: int, formatter: logging.Formatter) -> logging.StreamHandler:
    """Creates a handler that writes log output to the terminal."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _build_file_handler(level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    """
    Creates a rotating file handler that writes to logs/jarvis.log.
    Automatically rotates when the file reaches MAX_LOG_SIZE_BYTES.
    Keeps BACKUP_COUNT older files before deleting.
    """
    log_path = Config.LOGS_DIR / LOG_FILE_NAME

    handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=MAX_LOG_SIZE_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def get_logger(component_name: str) -> logging.Logger:
    """
    Returns a named logger for a specific component.

    Usage in any file:
        from core.logger import get_logger
        logger = get_logger(__name__)

    Each component gets its own named logger (e.g. 'core.router', 'agents.biz_agent')
    but all share the same root configuration and write to the same log file.

    Args:
        component_name: Typically passed as __name__ for automatic naming.

    Returns:
        A configured logging.Logger instance.
    """
    log_level = _resolve_log_level(Config.LOG_LEVEL)
    formatter = _build_formatter()

    # Attach handlers only to the root 'jarvis' logger to prevent duplicate entries
    root_logger = logging.getLogger("jarvis")

    if not root_logger.handlers:
        root_logger.setLevel(log_level)
        root_logger.addHandler(_build_console_handler(log_level, formatter))
        root_logger.addHandler(_build_file_handler(log_level, formatter))

    # Return a child logger named after the calling component
    return logging.getLogger(f"jarvis.{component_name}")