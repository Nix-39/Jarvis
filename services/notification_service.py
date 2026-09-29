"""
NotificationService - delivers messages from Jarvis to the user.

Built as interchangeable CHANNELS, so new delivery routes (Telegram two-way
chat, a future Jarvis mobile app) plug in without changing the scheduler or
agents:

    - WindowsToastChannel: native Windows notification (no extra packages).
    - TelegramChannel:     push to the phone via a private Telegram bot
                           (outbound HTTPS only - no open ports).

Security:
    - Notification text is never interpolated into a command line: the Windows
      toast receives it through environment variables and XML-escapes it.
    - The Telegram token lives only in .env and is never written to logs.

Architecture:
    Scheduler / Agents -> NotificationService -> channels -> user
"""

from __future__ import annotations

import base64
import os
import subprocess
from typing import Optional, Protocol

import httpx

from core.config import Config
from core.logger import get_logger

logger = get_logger(__name__)


class NotificationChannel(Protocol):
    """Contract for every delivery channel."""

    name: str

    def send(self, title: str, message: str) -> bool:
        """Deliver the notification. Return True on success. Must not raise."""
        ...


# ----------------------------------------------------------------------
# Windows toast
# ----------------------------------------------------------------------

# Uses the built-in Windows toast API through Windows PowerShell. The app id is
# PowerShell's registered id, which Windows reliably shows toasts for.
_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = [System.Security.SecurityElement]::Escape($env:JARVIS_TOAST_TITLE)
$body  = [System.Security.SecurityElement]::Escape($env:JARVIS_TOAST_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""

_CREATE_NO_WINDOW = 0x08000000


class WindowsToastChannel:
    name = "windows"

    def send(self, title: str, message: str) -> bool:
        encoded = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
        env = {**os.environ, "JARVIS_TOAST_TITLE": title[:200], "JARVIS_TOAST_BODY": message[:1000]}
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                env=env,
                capture_output=True,
                timeout=20,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            logger.warning("Windows notification failed: %s", exc)
            return False

        if result.returncode != 0:
            logger.warning(
                "Windows notification failed: %s",
                result.stderr.decode("utf-8", errors="replace")[:300],
            )
            return False
        return True


# ----------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------

class TelegramChannel:
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    def send(self, title: str, message: str) -> bool:
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": f"{title}\n{message}"},
                timeout=15,
            )
        except Exception as exc:
            # Never log the URL: it contains the bot token.
            logger.warning("Telegram notification failed: %s", type(exc).__name__)
            return False

        if response.status_code != 200:
            logger.warning("Telegram notification failed: HTTP %s", response.status_code)
            return False
        return True


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------

class NotificationService:
    """Send a notification through every configured channel."""

    def __init__(self, channels: Optional[list[NotificationChannel]] = None) -> None:
        if channels is None:
            channels = []
            if Config.NOTIFY_WINDOWS and os.name == "nt":
                channels.append(WindowsToastChannel())
            if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
                channels.append(TelegramChannel(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID))

        self.channels = channels
        logger.info(
            "NotificationService initialized | channels=%s",
            [channel.name for channel in self.channels] or "none",
        )

    def notify(self, title: str, message: str) -> bool:
        """Deliver through all channels. True if at least one channel succeeded."""
        if not self.channels:
            logger.warning("No notification channel configured: %s - %s", title, message)
            return False

        delivered = [channel.name for channel in self.channels if channel.send(title, message)]
        if delivered:
            logger.info("Notification delivered via %s.", delivered)
        return bool(delivered)
