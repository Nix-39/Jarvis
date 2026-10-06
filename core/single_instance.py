"""
Single-instance lock for the process that owns Jarvis' memory.

Only ONE process may write the long-term memory (ChromaDB) and deliver
reminders at a time. That process - normally Jarvis Core - binds a localhost
port as a lock. The port is never listened on, so nothing can connect to it;
the operating system simply refuses a second bind while the first process
lives, and releases it automatically if the process crashes.
"""

from __future__ import annotations

import socket
from typing import Optional

from core.config import Config


def acquire_lock() -> Optional[socket.socket]:
    """Take the lock. Returns the socket (keep it open) or None if another Jarvis process holds it."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: forbid any port sharing
        lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        lock.bind(("127.0.0.1", Config.JARVIS_LOCK_PORT))
    except OSError:
        lock.close()
        return None
    return lock


def lock_is_held() -> bool:
    """True if some Jarvis process (core, scheduler or debug chat) currently runs."""
    lock = acquire_lock()
    if lock is None:
        return True
    lock.close()
    return False
