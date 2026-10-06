"""
Local HTTP API for Jarvis Core.

The terminal client - and later the desktop interface - talk to the always-running
core through this API instead of starting their own copy of Jarvis.

Security:
    - Bound to 127.0.0.1 only (see Config.JARVIS_API_HOST): not reachable from
      the network, so no firewall rule or open port is involved.
    - Every endpoint except /health requires a bearer token. The token is
      generated on first start and stored in data/api_token.txt (private,
      gitignored). This stops other programs and web pages running on the same
      computer from talking to Jarvis.
    - Host header must be 127.0.0.1/localhost (blocks DNS-rebinding attacks
      from web pages). No CORS: browsers on other origins are refused.
    - No interactive docs / OpenAPI schema are served.

Endpoints:
    GET  /health          {"status": "ok", "ready": bool}       (no token)
    GET  /status          uptime, Ollama, SearXNG, Telegram, reminders
    POST /chat            {"message": "..."} -> {"reply", "agent", "seconds", "success"}
    GET  /events/recent   ?after_id=0&limit=200 -> recent events
    GET  /events/stream   live events (Server-Sent Events)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import queue
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core.config import Config
from core.events import Event, event_bus
from core.logger import get_logger

if TYPE_CHECKING:
    from core.jarvis_core import JarvisCore

logger = get_logger(__name__)

SSE_HEARTBEAT_SECONDS = 15
SSE_POLL_SECONDS = 0.25


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    channel: str = Field(default="terminal", pattern=r"^[a-z_]{1,20}$")


class ChatResponse(BaseModel):
    reply: str
    agent: str
    seconds: float
    success: bool


def load_or_create_token(path: Path = Config.JARVIS_API_TOKEN_FILE) -> str:
    """Read the API token, creating a new random one on first start."""
    try:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except FileNotFoundError:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    logger.info("Created a new API token in %s.", path.name)
    return token


def create_app(
    core: "JarvisCore",
    token: str,
    shutting_down: Optional[Callable[[], bool]] = None,
) -> FastAPI:
    """
    :param shutting_down: Returns True when the server is stopping, so open
                          event streams end at once instead of being cancelled.
    """
    is_closing = shutting_down or (lambda: False)
    app = FastAPI(title="Jarvis Core", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    expected = f"Bearer {token}".encode("utf-8")

    def require_token(authorization: str = Header(default="")) -> None:
        if not hmac.compare_digest(authorization.encode("utf-8"), expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    authorized = [Depends(require_token)]

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "ready": core.ready}

    @app.get("/status", dependencies=authorized)
    def status() -> dict[str, Any]:
        return core.status()

    @app.post("/chat", dependencies=authorized, response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        if not core.ready:
            raise HTTPException(status_code=503, detail="Jarvis startar fortfarande.")
        try:
            result = core.ask(request.message, channel=request.channel)
        except Exception as exc:
            logger.error("Chat request failed: %s", exc)
            raise HTTPException(status_code=500, detail="Jarvis kunde inte svara.") from exc
        return ChatResponse(
            reply=result.final_response,
            agent=result.agent_used,
            seconds=round(result.execution_time_seconds, 1),
            success=result.success,
        )

    @app.get("/events/recent", dependencies=authorized)
    def recent_events(
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return [event.to_dict() for event in event_bus.recent(after_id, limit)]

    @app.get("/events/stream", dependencies=authorized)
    async def stream_events(request: Request, after_id: int = Query(default=0, ge=0)) -> StreamingResponse:
        # Subscribe first, then replay history, so nothing falls in between.
        subscriber = event_bus.subscribe()

        async def generate():
            last_id = after_id
            idle = 0.0
            try:
                for event in event_bus.recent(after_id, limit=500):
                    last_id = event.id
                    yield _format_sse(event)
                while not is_closing() and not await request.is_disconnected():
                    try:
                        event = subscriber.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(SSE_POLL_SECONDS)
                        idle += SSE_POLL_SECONDS
                        if idle >= SSE_HEARTBEAT_SECONDS:
                            idle = 0.0
                            yield ": ping\n\n"
                        continue
                    if event.id <= last_id:
                        continue  # already sent from history
                    last_id = event.id
                    idle = 0.0
                    yield _format_sse(event)
            finally:
                event_bus.unsubscribe(subscriber)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _format_sse(event: Event) -> str:
    return f"id: {event.id}\ndata: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
