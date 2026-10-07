"""
Jarvis Core - the always-running brain.

One background process (no window) owns everything that must exist only once:
    - the Orchestrator with its agents and long-term memory (ChromaDB is not
      safe to write from several processes, so there is exactly one owner),
    - the reminder scheduler (thread),
    - the Telegram bot (thread, outgoing long polling - no open ports),
    - the local API on 127.0.0.1 that the terminal client and the future
      desktop interface talk to,
    - the event feed that shows the second brain at work.

Questions from every channel are answered one at a time, in arrival order.

Start at login:   scripts\\install_core.ps1   (Task Scheduler task "Jarvis Core")
Run in a window:  .venv\\Scripts\\python -m core.jarvis_core   (shows the log live)
Chat with it:     jarvis.bat

Logs go to logs/jarvis_core.log.
"""

import os
import sys

# Must be set before core.logger is imported anywhere.
os.environ.setdefault("JARVIS_LOG_FILE", "jarvis_core.log")

# Started with pythonw (no window) there is no console: give logging a sink.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Optional  # noqa: E402

import httpx  # noqa: E402

from core.clock import format_datetime_sv  # noqa: E402
from core.config import Config  # noqa: E402
from core.events import event_bus  # noqa: E402
from core.logger import get_logger  # noqa: E402
from core.single_instance import acquire_lock  # noqa: E402

logger = get_logger("core.jarvis_core")


class CoreNotReady(RuntimeError):
    """Raised when a question arrives before the Orchestrator has started."""


class JarvisCore:
    """Owns the long-lived parts of Jarvis and answers questions from all channels."""

    def __init__(
        self,
        reminder_service: Any = None,
        notification_service: Any = None,
    ) -> None:
        from core.scheduler import Scheduler
        from services.notification_service import NotificationService
        from services.backup_service import BackupService
        from services.calendar_service import CalendarService
        from services.reminder_service import ReminderService
        from services.sports_service import SportsService
        from services.weather_service import WeatherService
        from services.system_monitor import SystemMonitor
        from services.ui_settings import UiSettingsService

        self.started_at = datetime.now(timezone.utc)
        self.reminders = reminder_service or ReminderService()
        self.notifications = notification_service or NotificationService()
        self.scheduler = Scheduler(self.reminders, self.notifications)
        self.ui_settings = UiSettingsService()
        self.calendar = CalendarService()
        self.system_monitor = SystemMonitor()
        self.backup = BackupService(notify=self.notifications.notify)
        self.sports = SportsService(lambda: self.ui_settings.get().sports.leagues)
        self.weather = WeatherService(lambda: self.ui_settings.get().weather.model_dump())
        self.orchestrator: Any = None
        self.telegram: Any = None
        self.ready = False
        self.startup_error: Optional[str] = None

        self._query_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_scheduler(self) -> None:
        """Reminders first: they need neither Ollama nor the vector index."""
        self._start_thread("scheduler", self.scheduler.run_forever, self._stop)
        self._start_thread("backup", self.backup.run_forever, self._stop)
        self._start_thread("sports", self.sports.run_forever, self._stop)
        self._start_thread("weather", self.weather.run_forever, self._stop)

    def start_brain(self, orchestrator: Any = None) -> None:
        """Wait for Ollama, start the Orchestrator and the Telegram bot. Raises on fatal errors."""
        event_bus.publish("core.starting", "core", "Jarvis startar...")
        if orchestrator is None:
            if not wait_for_ollama(Config.OLLAMA_HOST, Config.OLLAMA_STARTUP_WAIT_SECONDS, self._stop):
                logger.warning("Ollama did not answer within %ss - starting anyway.", Config.OLLAMA_STARTUP_WAIT_SECONDS)
            from core.orchestrator import JarvisOrchestrator

            event_bus.publish("core.starting", "core", "Laddar agenter och synkar långtidsminnet...")
            orchestrator = JarvisOrchestrator(
                reminder_service=self.reminders,
                calendar_service=self.calendar,
                people_provider=self.people,
                sports_leagues=(lambda: self.ui_settings.get().sports.leagues, self.set_sports_leagues),
            )
        self.orchestrator = orchestrator

        if Config.TELEGRAM_BOT_TOKEN:
            from services.telegram_service import TelegramService

            self.telegram = TelegramService(
                bot_token=Config.TELEGRAM_BOT_TOKEN,
                chat_id=Config.TELEGRAM_CHAT_ID,
                on_message=lambda text: self.ask(text, channel="telegram").final_response,
                on_status=self.status_text,
                memory_service=self.orchestrator.memory_service,
            )
            self._start_thread("telegram", self.telegram.run, self._stop)
        else:
            logger.info("Telegram not configured (TELEGRAM_BOT_TOKEN empty) - phone chat disabled.")

        self.ready = True
        logger.info("Jarvis Core is online.")
        event_bus.publish("core.online", "core", "Jarvis är online")
        if self.telegram and not self.telegram.setup_mode and Config.TELEGRAM_STARTUP_MESSAGE:
            self.telegram.send_text("🟢 Jarvis är online")

    def set_sports_leagues(self, leagues: list[str]) -> None:
        """Change the ticker's leagues (from SportsAgent) and fetch the new ones right away."""
        self.ui_settings.update({"sports": {"leagues": leagues}})
        event_bus.publish("sports.leagues", "sports", "Resultatlistan ändrad", leagues=leagues)
        self.sports.wake()

    def people(self) -> list[dict[str, str]]:
        """Family members (id, name, full name) for the calendar agent."""
        return [{"id": p.id, "name": p.name, "full_name": p.full_name} for p in self.ui_settings.get().people]

    def stop(self) -> None:
        self._stop.set()
        self.ready = False
        event_bus.publish("core.offline", "core", "Jarvis stängs av")
        logger.info("Jarvis Core stopped.")

    def _start_thread(self, name: str, target: Any, *args: Any) -> None:
        thread = threading.Thread(target=target, args=args, name=f"jarvis-{name}", daemon=True)
        thread.start()
        self._threads[name] = thread

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    def ask(self, message: str, channel: str = "terminal") -> Any:
        """Answer one question. Questions from all channels run one at a time."""
        if self.orchestrator is None:
            raise CoreNotReady("Jarvis is still starting.")
        if not self._query_lock.acquire(blocking=False):
            event_bus.publish("query.queued", "core", f"Fråga via {channel} väntar på sin tur", channel=channel)
            self._query_lock.acquire()
        try:
            return self.orchestrator.process_query(message, channel=channel)
        finally:
            self._query_lock.release()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        uptime = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        upcoming = []
        try:
            upcoming = self.reminders.list_upcoming(limit=5)
        except Exception as exc:
            logger.warning("Could not list reminders for status: %s", exc)

        web = getattr(self.orchestrator, "web_service", None)
        searxng: Optional[bool] = None
        if web is not None and web.enabled:
            searxng = web.is_available()

        if self.telegram is None:
            telegram = "av"
        elif self.telegram.setup_mode:
            telegram = "inställning (TELEGRAM_CHAT_ID saknas)"
        else:
            telegram = "på" if self._thread_alive("telegram") else "stoppad"

        return {
            "ready": self.ready,
            "startup_error": self.startup_error,
            "uptime_seconds": uptime,
            "ollama": ollama_is_up(Config.OLLAMA_HOST),
            "model": Config.OLLAMA_MODEL,
            "searxng": searxng,
            "telegram": telegram,
            "scheduler": self._thread_alive("scheduler"),
            "backup": self.backup.status(),
            "busy": self._query_lock.locked(),
            "upcoming_reminders": [
                {"id": r.id, "text": r.text, "due": format_datetime_sv(r.due_at), "category": r.category}
                for r in upcoming
            ],
        }

    def status_text(self) -> str:
        s = self.status()
        hours, rest = divmod(s["uptime_seconds"], 3600)

        def mark(value: Optional[bool]) -> str:
            return "–" if value is None else ("✅" if value else "❌")

        lines = [
            "🧠 Jarvis status",
            f"Igång: {hours} h {rest // 60} min" + (" (startar fortfarande)" if not s["ready"] else ""),
            f"Ollama ({s['model']}): {mark(s['ollama'])}",
            f"Webbsök (SearXNG): {mark(s['searxng'])}",
            f"Påminnelser: {mark(s['scheduler'])}",
            f"Telegram: {s['telegram']}",
            "Backup: " + backup_text(s["backup"]),
        ]
        if s["upcoming_reminders"]:
            lines.append("\nKommande påminnelser:")
            lines += [f"• {r['due']} – {r['text']}" for r in s["upcoming_reminders"]]
        else:
            lines.append("\nInga kommande påminnelser.")
        return "\n".join(lines)

    def _thread_alive(self, name: str) -> bool:
        thread = self._threads.get(name)
        return bool(thread and thread.is_alive())


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def backup_text(b: dict[str, Any]) -> str:
    if not b["configured"]:
        return "av"
    if b["last_error"]:
        return f"❌ {b['last_error']}"
    if not b["last_backup"]:
        return "ingen än"
    when = datetime.fromisoformat(b["last_backup"])
    return f"✅ {format_datetime_sv(when.astimezone())} ({b['count']} sparade)"


def ollama_is_up(host: str) -> bool:
    try:
        return httpx.get(f"{host.rstrip('/')}/api/version", timeout=2).status_code == 200
    except Exception:
        return False


def wait_for_ollama(host: str, max_wait_seconds: float, stop: threading.Event) -> bool:
    """At login Ollama may start after Jarvis. Wait for it instead of failing."""
    deadline = time.monotonic() + max_wait_seconds
    announced = False
    while not stop.is_set():
        if ollama_is_up(host):
            return True
        if not announced:
            logger.info("Waiting for Ollama at %s ...", host)
            event_bus.publish("core.starting", "core", "Väntar på Ollama...")
            announced = True
        if time.monotonic() >= deadline:
            return False
        stop.wait(3)
    return False


def _route_library_logs() -> None:
    """Send uvicorn warnings to Jarvis' log; keep chatty HTTP libraries quiet."""
    jarvis_handlers = logging.getLogger("jarvis").handlers
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = list(jarvis_handlers)
    uvicorn_logger.setLevel(logging.WARNING)
    uvicorn_logger.propagate = False
    # httpx logs every request URL at INFO - the Telegram URL contains the bot token.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> int:
    lock = acquire_lock()
    if lock is None:
        print("Jarvis Core (or the standalone scheduler/debug chat) is already running.")
        logger.info("Another Jarvis process holds the lock; exiting.")
        return 0

    import uvicorn

    from core.api import create_app, load_or_create_token

    _route_library_logs()
    logger.info("Jarvis Core starting (API on http://%s:%s).", Config.JARVIS_API_HOST, Config.JARVIS_API_PORT)

    core = JarvisCore()
    core.start_scheduler()

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(core, load_or_create_token(), shutting_down=lambda: server.should_exit),
            host=Config.JARVIS_API_HOST,
            port=Config.JARVIS_API_PORT,
            log_config=None,
            access_log=False,
            server_header=False,
            date_header=False,
            timeout_graceful_shutdown=3,
        )
    )
    exit_code = 0

    def start_brain() -> None:
        nonlocal exit_code
        try:
            core.start_brain()
        except Exception as exc:
            logger.exception("Jarvis Core failed to start: %s", exc)
            core.startup_error = str(exc)
            event_bus.publish("core.failed", "core", "Jarvis kunde inte starta - se loggen")
            exit_code = 1
            server.should_exit = True  # let Task Scheduler restart us

    threading.Thread(target=start_brain, name="jarvis-startup", daemon=True).start()

    try:
        server.run()  # blocks until Ctrl+C / shutdown
    except KeyboardInterrupt:
        pass  # uvicorn re-raises the Ctrl+C it already handled
    except SystemExit as exc:  # uvicorn exits like this if the port is taken
        logger.error("Local API could not start on port %s (in use?).", Config.JARVIS_API_PORT)
        exit_code = int(exc.code or 1)
    finally:
        core.stop()
        lock.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
