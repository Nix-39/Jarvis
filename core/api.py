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
    GET  /health          {"status": "ok", "ready": bool, "ui": version}   (no token)
    GET  /status          uptime, Ollama, SearXNG, Telegram, reminders
    POST /chat            {"message": "..."} -> {"reply", "agent", "seconds", "success"}
    GET  /events/recent   ?after_id=0&limit=200 -> recent events
    GET  /events/stream   live events (Server-Sent Events)

Desktop interface (static files under /app are public - they contain no data;
everything personal goes through the token-protected endpoints below):
    GET  /app/...                         the interface itself
    GET  /agents, /history, /system, /memory/stats, /reminders/upcoming
    GET|PATCH /settings                   display names, people, background, sound
    GET  /documents/folders, PUT /documents?folder=&name=   (raw file body)
    GET|PUT|DELETE /assets/background, GET|PUT /people/{id}/photo   (raw image body)
    GET  /backup/status, POST /backup/run
    GET  /calendar/events?start=&end=, DELETE /calendar/events/{id}[?occurrence=YYYY-MM-DD], DELETE /reminders/{id}
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import queue
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

import re
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from core.config import Config
from core.events import Event, event_bus
from core.logger import get_logger

if TYPE_CHECKING:
    from core.jarvis_core import JarvisCore

logger = get_logger(__name__)

SSE_HEARTBEAT_SECONDS = 15
SSE_POLL_SECONDS = 0.25
DOC_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
FOLDER_PART = re.compile(r"^[\w\- åäöÅÄÖ]{1,40}$")
CSP = ("default-src 'self'; img-src 'self' data: blob: https://a.espncdn.com; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CSP
        return response
    expected = f"Bearer {token}".encode("utf-8")

    def require_token(authorization: str = Header(default="")) -> None:
        if not hmac.compare_digest(authorization.encode("utf-8"), expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    authorized = [Depends(require_token)]

    ui_version = _ui_version()

    @app.get("/health")
    def health() -> dict[str, Any]:
        # "ui" changes when the interface files change, so an open window reloads itself.
        return {"status": "ok", "ready": core.ready, "ui": ui_version}

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

    _add_desktop_routes(app, core, authorized)
    return app


# ----------------------------------------------------------------------
# Desktop interface
# ----------------------------------------------------------------------

class _RevalidatingStaticFiles(StaticFiles):
    """Static UI files that the window always revalidates, so updates show up after a reload."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _ui_version() -> str:
    """Short fingerprint of the interface files (names, sizes, modification times)."""
    digest = hashlib.sha256()
    if Config.UI_DIR.is_dir():
        for path in sorted(Config.UI_DIR.rglob("*")):
            if path.is_file():
                stat = path.stat()
                digest.update(f"{path.relative_to(Config.UI_DIR)}|{stat.st_size}|{stat.st_mtime_ns}".encode())
    return digest.hexdigest()[:12]


def _add_desktop_routes(app: FastAPI, core: "JarvisCore", authorized: list) -> None:
    settings_service = core.ui_settings

    if Config.UI_DIR.is_dir():
        app.mount("/app", _RevalidatingStaticFiles(directory=Config.UI_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    def orchestrator():
        if core.orchestrator is None:
            raise HTTPException(status_code=503, detail="Jarvis startar fortfarande.")
        return core.orchestrator

    @app.get("/agents", dependencies=authorized)
    def agents() -> list[dict[str, str]]:
        return settings_service.agents(list(orchestrator().agent_registry))

    @app.get("/settings", dependencies=authorized)
    def get_settings() -> dict[str, Any]:
        return settings_service.get().model_dump()

    @app.patch("/settings", dependencies=authorized)
    def patch_settings(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return settings_service.update(patch).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"Ogiltig inställning: {exc.errors()[0].get('msg', '')}") from exc

    @app.get("/history", dependencies=authorized)
    def history(limit: int = Query(40, ge=1, le=200), before_id: Optional[int] = Query(None, ge=1)) -> list[dict[str, Any]]:
        messages = orchestrator().memory_service.get_recent_messages(limit=limit, before_id=before_id)
        return [{"id": m.id, "role": m.role, "content": m.content, "agent_id": m.agent_id, "created_at": m.created_at} for m in messages]

    @app.get("/system", dependencies=authorized)
    def system() -> dict[str, Any]:
        return core.system_monitor.snapshot()

    @app.get("/memory/stats", dependencies=authorized)
    def memory_stats() -> dict[str, Any]:
        orch = orchestrator()
        try:
            stats = orch.vector_service.stats()
        except Exception:
            stats = {}
        return {"conversations": orch.memory_service.count_messages(), "document_chunks": stats.get("document_chunks"), "documents": stats.get("documents")}

    @app.get("/reminders/upcoming", dependencies=authorized)
    def upcoming(days: int = Query(7, ge=1, le=120)) -> list[dict[str, Any]]:
        from services.reminder_service import RECURRENCE_LABELS

        until = datetime.now(timezone.utc) + timedelta(days=days)
        out = []
        for r in core.reminders.list_upcoming(limit=500):
            if r.due_at > until:
                break
            out.append({"id": r.id, "text": r.text, "due": r.due_at.isoformat(), "category": r.category,
                        "recurrence": r.recurrence, "recurrence_label": "" if r.recurrence == "none" else RECURRENCE_LABELS[r.recurrence],
                        "person": settings_service.person_for(r.category, r.text)})
        return out

    @app.get("/calendar/events", dependencies=authorized)
    def calendar_events(start: str = Query(..., max_length=40), end: str = Query(..., max_length=40)) -> list[dict[str, Any]]:
        try:
            lo, hi = datetime.fromisoformat(start), datetime.fromisoformat(end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Ogiltigt datum.") from exc
        if hi - lo > timedelta(days=400):
            raise HTTPException(status_code=400, detail="För stort intervall.")
        return [e.to_dict() for e in core.calendar.between(lo, hi)]

    @app.get("/backup/status", dependencies=authorized)
    def backup_status() -> dict[str, Any]:
        return core.backup.status()

    @app.post("/backup/run", dependencies=authorized)
    def backup_run() -> dict[str, Any]:
        """Start a backup now (in the background - progress comes as backup.* events)."""
        if core.backup.running:
            return {"started": False, "reason": "En backup körs redan."}
        problem = core.backup.problem()
        if problem:
            raise HTTPException(status_code=409, detail=problem)

        def worker() -> None:
            try:
                core.backup.run("ui")
            except Exception:
                pass   # logged and published as backup.failed

        threading.Thread(target=worker, name="jarvis-backup-now", daemon=True).start()
        return {"started": True}

    @app.delete("/reminders/{reminder_id}", dependencies=authorized)
    def delete_reminder(reminder_id: int) -> dict[str, bool]:
        if not core.reminders.cancel(reminder_id):
            raise HTTPException(status_code=404, detail="Påminnelsen finns inte.")
        return {"ok": True}

    @app.delete("/calendar/events/{event_id}", dependencies=authorized)
    def delete_calendar_event(event_id: int, occurrence: str = Query("", max_length=10)) -> Response:
        """Remove a booking (a whole series), or with ?occurrence=YYYY-MM-DD one occurrence of a series."""
        if occurrence:
            try:
                day = date.fromisoformat(occurrence)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Ogiltigt datum.") from exc
            removed = core.calendar.skip(event_id, day)
        else:
            removed = core.calendar.cancel(event_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Bokningen finns inte.")
        return Response(status_code=204)

    @app.get("/documents/folders", dependencies=authorized)
    def document_folders() -> list[str]:
        base = Config.DOCUMENTS_DIR
        folders = sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_dir() and len(p.relative_to(base).parts) <= 3)
        return folders[:200]

    @app.put("/documents", dependencies=authorized)
    async def put_document(request: Request, folder: str = Query(..., max_length=120), name: str = Query(..., max_length=160)) -> dict[str, str]:
        target_dir = _safe_document_folder(folder)
        filename = _safe_filename(name)
        if Path(filename).suffix.lower() not in DOC_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Bara txt, md, pdf och docx kan läras in.")
        data = await _read_body(request, MAX_DOCUMENT_BYTES)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_path(target_dir / filename)
        target.write_bytes(data)
        rel = str(target.relative_to(Config.DOCUMENTS_DIR)).replace("\\", "/")
        logger.info("Document saved from desktop: %s (%s bytes)", rel, len(data))
        event_bus.publish("memory.document_added", "long_term_memory", f"Nytt dokument: {rel}", path=rel)
        orch = core.orchestrator
        if orch is not None:
            threading.Thread(target=orch.vector_service.sync_all, kwargs={"blocking": False}, daemon=True).start()
        return {"path": rel}

    @app.get("/assets/background", dependencies=authorized)
    def get_background() -> FileResponse:
        found = settings_service.find_image("background")
        if not found:
            raise HTTPException(status_code=404, detail="Ingen bakgrundsbild.")
        return FileResponse(found[0], media_type=found[1], headers={"Cache-Control": "no-store"})

    @app.put("/assets/background", dependencies=authorized)
    async def put_background(request: Request) -> dict[str, str]:
        from services.ui_settings import MAX_BACKGROUND_BYTES
        try:
            return {"file": settings_service.save_image("background", await _read_body(request, MAX_BACKGROUND_BYTES), MAX_BACKGROUND_BYTES)}
        except ValueError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc

    @app.delete("/assets/background", dependencies=authorized)
    def delete_background() -> Response:
        settings_service.delete_image("background")
        return Response(status_code=204)

    def person_id(pid: str) -> str:
        if pid not in {p.id for p in settings_service.get().people}:
            raise HTTPException(status_code=404, detail="Okänd person.")
        return pid

    @app.get("/people/photos", dependencies=authorized)
    def photos() -> list[str]:
        return [p.id for p in settings_service.get().people if settings_service.find_image(f"people/{p.id}")]

    @app.get("/people/{pid}/photo", dependencies=authorized)
    def get_photo(pid: str) -> FileResponse:
        found = settings_service.find_image(f"people/{person_id(pid)}")
        if not found:
            raise HTTPException(status_code=404, detail="Ingen bild.")
        return FileResponse(found[0], media_type=found[1], headers={"Cache-Control": "no-store"})

    @app.put("/people/{pid}/photo", dependencies=authorized)
    async def put_photo(pid: str, request: Request) -> dict[str, str]:
        from services.ui_settings import MAX_PHOTO_BYTES
        name = f"people/{person_id(pid)}"
        try:
            return {"file": settings_service.save_image(name, await _read_body(request, MAX_PHOTO_BYTES), MAX_PHOTO_BYTES)}
        except ValueError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc


async def _read_body(request: Request, limit: int) -> bytes:
    """Read a raw request body, refusing anything larger than `limit`."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="Filen är för stor.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="Filen är för stor.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(status_code=400, detail="Tom fil.")
    return b"".join(chunks)


def _safe_document_folder(folder: str) -> Path:
    """Resolve a user-chosen folder strictly inside data/documents (no '..', no absolute paths)."""
    parts = [p.strip() for p in folder.replace("\\", "/").split("/") if p.strip()]
    if not parts or len(parts) > 3 or any(p in (".", "..") or not FOLDER_PART.match(p) for p in parts):
        raise HTTPException(status_code=400, detail="Ogiltigt mappnamn.")
    base = Config.DOCUMENTS_DIR.resolve()
    target = base.joinpath(*parts).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="Ogiltigt mappnamn.")
    return target


def _safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"/\\|?*').strip(" .")
    if not name:
        raise HTTPException(status_code=400, detail="Ogiltigt filnamn.")
    return name[:120]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="För många filer med samma namn.")


def _format_sse(event: Event) -> str:
    return f"id: {event.id}\ndata: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
