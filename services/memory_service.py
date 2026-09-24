"""
MemoryService - persistent storage for sessions, conversation history,
and simple key-value state, backed by SQLite.

Scope (v1), per SNAPSHOT.md:
    - SQLite initialization and schema management
    - Session creation and retrieval
    - Conversation history logging (messages)
    - Key-value user/agent state storage
    - Thread-safe database access (one connection per thread, WAL mode)

Explicitly out of scope (reserved for VectorService):
    - Vector embeddings
    - Semantic search
    - Unstructured document retrieval / RAG

Agents must never talk to sqlite3 directly - they go through this service,
same as OllamaService and PromptLoader (Agent -> MemoryService -> SQLite).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from core.config import Config

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Config.DATA_DIR / "jarvis_memory.db"
DEFAULT_SESSION_ID = "default"
DEFAULT_CONTEXT_LIMIT = 8  # last N messages (~4 exchanges) used as conversation context in agent prompts


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Message:
    """A single logged conversation message."""

    id: int
    session_id: str
    role: str
    content: str
    agent_id: Optional[str]
    context: Optional[str]
    metadata: dict[str, Any]
    created_at: str


def format_conversation_history(messages: list[Message]) -> str:
    """
    Format a list of Messages into a readable transcript block, suitable
    for inserting into an agent's prompt as short-term conversation context.
    """
    if not messages:
        return "(Ingen tidigare konversation.)"

    lines = []
    for msg in messages:
        speaker = "User" if msg.role == "user" else "Agent"
        lines.append(f"{speaker}: {msg.content}")
    return "\n".join(lines)


class MemoryServiceError(Exception):
    """Raised for MemoryService-specific failures."""


class MemoryService:
    """
    Thread-safe SQLite-backed memory store for Jarvis.

    One connection is opened per thread (threading.local) with SQLite's
    WAL journal mode enabled, so multiple threads can read concurrently
    while a write is in progress. All public methods are safe to call
    from any thread.
    """

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialize_schema()
        logger.info("MemoryService initialized (db_path=%s)", self._db_path)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return this thread's SQLite connection, creating it if needed."""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                timeout=30.0,
                isolation_level=None,  # autocommit; transactions are explicit below
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.connection = conn
        return conn

    def close(self) -> None:
        """Close this thread's connection, if one is open."""
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            self._local.connection = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _initialize_schema(self) -> None:
        """Create tables and indexes if they do not already exist."""
        with self._init_lock:
            conn = self._get_connection()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    role        TEXT NOT NULL CHECK (role IN ('user', 'agent')),
                    content     TEXT NOT NULL,
                    agent_id    TEXT,
                    context     TEXT,
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    created_at  TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                    ON messages (session_id);
                CREATE INDEX IF NOT EXISTS idx_messages_agent_id
                    ON messages (agent_id);
                CREATE INDEX IF NOT EXISTS idx_messages_context
                    ON messages (context);

                CREATE TABLE IF NOT EXISTS user_state (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, session_id: str = DEFAULT_SESSION_ID) -> str:
        """
        Create a session if it does not already exist, and return its id.

        Idempotent - calling this again with the same session_id is safe
        and will not overwrite the existing created_at timestamp.
        """
        conn = self._get_connection()
        now = _utc_now_iso()
        try:
            conn.execute(
                """
                INSERT INTO sessions (id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (session_id, now, now),
            )
        except sqlite3.Error as exc:
            raise MemoryServiceError(
                f"Failed to create session '{session_id}': {exc}"
            ) from exc
        return session_id

    def get_session(
        self, session_id: str = DEFAULT_SESSION_ID
    ) -> Optional[dict[str, Any]]:
        """Return a session's metadata, or None if it does not exist."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT id, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def _touch_session(self, conn: sqlite3.Connection, session_id: str) -> None:
        """Update a session's updated_at timestamp. Caller manages the transaction."""
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_utc_now_iso(), session_id),
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: Optional[str] = None,
        context: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        """
        Log a message to a session's conversation history.

        Creates the session first if it does not already exist, so callers
        do not need to call create_session() explicitly beforehand.
        Returns the new message's id.
        """
        if role not in ("user", "agent"):
            raise MemoryServiceError(
                f"Invalid role '{role}': must be 'user' or 'agent'"
            )

        conn = self._get_connection()
        now = _utc_now_iso()
        metadata_json = json.dumps(metadata or {})

        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO sessions (id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (session_id, now, now),
            )
            cursor = conn.execute(
                """
                INSERT INTO messages
                    (session_id, role, content, agent_id, context, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, agent_id, context, metadata_json, now),
            )
            self._touch_session(conn, session_id)
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            raise MemoryServiceError(f"Failed to save message: {exc}") from exc

        return int(cursor.lastrowid)

    def get_session_messages(
        self,
        session_id: str = DEFAULT_SESSION_ID,
        agent_id: Optional[str] = None,
        context: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[Message]:
        """
        Return messages for a session, oldest first.

        Optionally narrow the result to a specific agent_id and/or context
        tag, and/or cap it to the most recent `limit` messages.
        """
        conn = self._get_connection()
        conditions = ["session_id = ?"]
        params: list[Any] = [session_id]

        if agent_id is not None:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if context is not None:
            conditions.append("context = ?")
            params.append(context)

        where_clause = " AND ".join(conditions)

        if limit is not None:
            # Take the most recent `limit` rows, then restore chronological order.
            query = (
                f"SELECT * FROM messages WHERE {where_clause} "
                "ORDER BY id DESC LIMIT ?"
            )
            rows = conn.execute(query, [*params, limit]).fetchall()
            rows = list(reversed(rows))
        else:
            query = f"SELECT * FROM messages WHERE {where_clause} ORDER BY id ASC"
            rows = conn.execute(query, params).fetchall()

        return [
            Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                agent_id=row["agent_id"],
                context=row["context"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Key-value state (namespace keys yourself, e.g. "business_agent.active_client")
    # ------------------------------------------------------------------

    def set_state(self, key: str, value: Any) -> None:
        """
        Store a value under a key.

        `value` is JSON-encoded, so it may be a string, number, bool, list,
        or dict. Namespace keys by caller to avoid collisions between
        agents, e.g. "business_agent.active_client".
        """
        conn = self._get_connection()
        value_json = json.dumps(value)
        now = _utc_now_iso()
        try:
            conn.execute(
                """
                INSERT INTO user_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, now),
            )
        except sqlite3.Error as exc:
            raise MemoryServiceError(
                f"Failed to set state for key '{key}': {exc}"
            ) from exc

    def get_state(self, key: str, default: Any = None) -> Any:
        """Return the value stored under a key, or `default` if not set."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT value FROM user_state WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])


if __name__ == "__main__":
    # Smoke test - verifies the service end-to-end, same spirit as the
    # existing `python -m core.orchestrator` verification pattern.
    logging.basicConfig(level=logging.INFO)

    memory = MemoryService()

    session_id = memory.create_session(DEFAULT_SESSION_ID)
    print(f"Session: {memory.get_session(session_id)}")

    memory.save_message(session_id, role="user", content="Hej Jarvis!")
    memory.save_message(
        session_id,
        role="agent",
        content="Hej Nix! Hur kan jag hjälpa dig idag?",
        agent_id="general_agent",
    )
    memory.save_message(
        session_id,
        role="agent",
        content="Ny hemsida planerad för kund X.",
        agent_id="business_agent",
        context="kund_x",
        metadata={"stage": "planning"},
    )

    print("\nAll messages:")
    for msg in memory.get_session_messages(session_id):
        print(f"  [{msg.role:>5}/{msg.agent_id}] {msg.content}")

    print("\nMessages tagged 'kund_x':")
    for msg in memory.get_session_messages(session_id, context="kund_x"):
        print(f"  [{msg.role:>5}/{msg.agent_id}] {msg.content}")

    memory.set_state("business_agent.active_client", "kund_x")
    print(f"\nState: {memory.get_state('business_agent.active_client')}")
    print(f"Missing key default: {memory.get_state('nonexistent.key', default='n/a')}")

    memory.close()
    print("\nSmoke test complete.")