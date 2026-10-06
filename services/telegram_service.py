"""
TelegramService - two-way chat with Jarvis from the phone.

Uses Telegram's long polling (getUpdates): Jarvis asks Telegram for new
messages over an outgoing HTTPS connection. Nothing listens for incoming
connections, so no port is opened on the computer or the router.

Security:
    - Only the chat in TELEGRAM_CHAT_ID is answered. Everyone else is ignored
      (and logged), even if they find the bot's username.
    - Setup mode: with a token but no chat id, a private /start message is
      answered with that chat's id - nothing else - so the owner can finish
      the setup. No questions are executed in setup mode.
    - The bot token lives only in .env and is never written to logs (it is
      part of every request URL, so URLs and raw exceptions are never logged).
    - Messages that waited while Jarvis was offline are not executed
      ("remind me in 10 minutes" sent 5 hours ago would be wrong); the user is
      asked to send them again instead.
    - Message offsets are saved before a message is handled, so a crash can
      never make Jarvis execute the same message twice.

Architecture:
    Telegram <-> TelegramService (long polling thread) -> Jarvis Core -> Orchestrator
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 30            # how long Telegram holds a getUpdates request open
MAX_MESSAGE_CHARS = 4000             # Telegram's hard limit is 4096
OFFSET_STATE_KEY = "telegram.offset"

HELP_TEXT = (
    "Hej! Jag är Jarvis. Skriv vad du vill ha hjälp med, till exempel:\n"
    "• påminn mig att ringa verkstaden imorgon kl 10\n"
    "• vad kostar elen i SE3 idag?\n\n"
    "Kommandon:\n"
    "/status - hur Jarvis mår just nu\n"
    "/hjalp - den här texten"
)
NON_TEXT_REPLY = "Jag kan bara läsa text än så länge - skriv gärna din fråga."


class TelegramError(Exception):
    """A Telegram API call failed. Never contains the token."""

    def __init__(self, method: str, status: Optional[int], description: str = "") -> None:
        self.status = status
        super().__init__(f"Telegram {method} failed: HTTP {status} {description}".strip())


class TelegramService:
    """Long-polling Telegram bot that forwards the owner's messages to Jarvis."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        on_message: Callable[[str], str],
        on_status: Callable[[], str],
        memory_service: Any = None,
        client: Optional[httpx.Client] = None,
        max_message_age_minutes: int = Config.TELEGRAM_MAX_MESSAGE_AGE_MINUTES,
    ) -> None:
        """
        :param on_message: Called with the owner's text; returns Jarvis' answer.
        :param on_status:  Returns a short status text for /status.
        :param memory_service: Optional - persists the update offset across restarts.
        """
        if not bot_token:
            raise ValueError("A Telegram bot token is required.")
        self._token = bot_token
        self._chat_id = str(chat_id).strip()
        self._on_message = on_message
        self._on_status = on_status
        self._memory = memory_service
        self._client = client or httpx.Client(timeout=httpx.Timeout(15, read=POLL_TIMEOUT_SECONDS + 15))
        self._max_age_seconds = max_message_age_minutes * 60
        self._offset: Optional[int] = self._load_offset()

    @property
    def setup_mode(self) -> bool:
        return not self._chat_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, stop: threading.Event) -> None:
        """Poll for messages until `stop` is set. Never raises."""
        if self.setup_mode:
            logger.warning(
                "Telegram in setup mode: send /start to your bot to get your chat id, "
                "then set TELEGRAM_CHAT_ID in .env and restart Jarvis Core."
            )
        else:
            logger.info("Telegram bot listening for messages.")

        backoff = 1.0
        while not stop.is_set():
            try:
                updates = self.poll_once()
                backoff = 1.0
            except TelegramError as exc:
                if exc.status == 401:
                    logger.error("Telegram rejected the bot token (HTTP 401). Check TELEGRAM_BOT_TOKEN in .env.")
                    stop.wait(600)
                    continue
                if exc.status == 409:
                    logger.error("Telegram conflict (HTTP 409): another program is polling this bot.")
                else:
                    logger.warning("%s", exc)
                stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except Exception as exc:
                # Network down, DNS, timeouts... Only the type: messages could contain the URL.
                logger.warning("Telegram polling failed (%s); retrying in %.0fs.", type(exc).__name__, backoff)
                stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue

            for update in updates:
                if stop.is_set():
                    break
                self.handle_update(update)

        logger.info("Telegram bot stopped.")

    def poll_once(self) -> list[dict[str, Any]]:
        """Fetch new updates and advance the offset (before handling - at most once)."""
        payload: dict[str, Any] = {"timeout": POLL_TIMEOUT_SECONDS, "allowed_updates": ["message"]}
        if self._offset is not None:
            payload["offset"] = self._offset
        updates = self._call("getUpdates", payload) or []
        if updates:
            self._offset = max(int(update["update_id"]) for update in updates) + 1
            self._save_offset()
        return updates

    def handle_update(self, update: dict[str, Any]) -> None:
        """Handle one update. Never raises."""
        try:
            self._handle(update)
        except Exception as exc:
            logger.error("Could not handle Telegram message: %s", type(exc).__name__)

    def send_text(self, text: str, chat_id: Optional[str] = None) -> bool:
        """Send a (possibly long) text to the owner. True on success. Never raises."""
        target = chat_id or self._chat_id
        if not target:
            return False
        try:
            for part in split_message(text):
                self._call("sendMessage", {"chat_id": target, "text": part})
            return True
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc if isinstance(exc, TelegramError) else type(exc).__name__)
            return False

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _handle(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))

        if self.setup_mode:
            if chat.get("type") == "private":
                logger.warning("Telegram setup: message from chat id %s - put it in TELEGRAM_CHAT_ID in .env.", chat_id)
                self.send_text(
                    f"Hej! Ditt chat-id är {chat_id}\n\n"
                    f"Lägg in TELEGRAM_CHAT_ID={chat_id} i .env och starta om Jarvis Core.",
                    chat_id=chat_id,
                )
            return

        if chat_id != self._chat_id:
            sender = (message.get("from") or {}).get("username") or "okänd"
            logger.warning("Ignored Telegram message from unknown chat %s (@%s).", chat_id, sender)
            event_bus.publish(
                "security.rejected", "telegram", "Okänd avsändare på Telegram ignorerades",
                chat_id=chat_id,
            )
            return

        sent_at = datetime.fromtimestamp(int(message.get("date", 0)), timezone.utc)
        if time.time() - sent_at.timestamp() > self._max_age_seconds:
            local = sent_at.astimezone().strftime("%d/%m kl %H:%M")
            logger.info("Skipped Telegram message sent while offline (%s).", local)
            self.send_text(
                f"Jag var offline när du skrev det här ({local}), så jag har inte gjort något med det. "
                "Skicka det igen om det fortfarande gäller."
            )
            return

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            self.send_text(NON_TEXT_REPLY)
            return
        text = text.strip()

        if text.startswith("/"):
            self._handle_command(text)
            return

        done = threading.Event()
        typing = threading.Thread(target=self._show_typing, args=(done,), daemon=True, name="telegram-typing")
        typing.start()
        try:
            answer = self._on_message(text)
        except Exception as exc:
            logger.error("Jarvis failed to answer a Telegram message: %s", exc)
            answer = "Något gick fel när jag skulle svara. Försök igen om en stund."
        finally:
            done.set()
        self.send_text(answer or "(tomt svar)")

    def _handle_command(self, text: str) -> None:
        command = text.split()[0].split("@")[0].lower()
        if command == "/status":
            try:
                self.send_text(self._on_status())
            except Exception as exc:
                logger.error("Status for Telegram failed: %s", exc)
                self.send_text("Kunde inte hämta status just nu.")
        else:  # /start, /hjalp, /help and unknown commands
            self.send_text(HELP_TEXT)

    def _show_typing(self, done: threading.Event) -> None:
        """Keep the 'typing...' indicator alive (it expires after ~5 s) until done."""
        while not done.is_set():
            try:
                self._call("sendChatAction", {"chat_id": self._chat_id, "action": "typing"})
            except Exception:
                pass  # cosmetic only
            done.wait(4.5)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        # The URL contains the token: it must never reach a log or an exception message.
        response = self._client.post(f"{API_BASE}/bot{self._token}/{method}", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or not body.get("ok"):
            description = str(body.get("description", ""))[:200].replace(self._token, "***")
            raise TelegramError(method, response.status_code, description)
        return body.get("result")

    # ------------------------------------------------------------------
    # Offset persistence
    # ------------------------------------------------------------------

    def _load_offset(self) -> Optional[int]:
        if self._memory is None:
            return None
        try:
            value = self._memory.get_state(OFFSET_STATE_KEY)
            return int(value) if value is not None else None
        except Exception:
            return None

    def _save_offset(self) -> None:
        if self._memory is None or self._offset is None:
            return
        try:
            self._memory.set_state(OFFSET_STATE_KEY, self._offset)
        except Exception as exc:
            logger.warning("Could not save Telegram offset: %s", exc)


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split a long answer into Telegram-sized parts, preferring paragraph and line breaks."""
    text = text.strip() or "(tomt svar)"
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    parts.append(text)
    return parts
