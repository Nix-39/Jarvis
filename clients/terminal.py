"""
Terminal chat with Jarvis Core.

A thin client: it does not load any AI models or memory itself. It sends
your questions to the always-running Jarvis Core over the local API and shows
what the second brain is doing while you wait (agent choice, web search,
memory lookups).

Start:  jarvis.bat            (or: .venv\\Scripts\\python -m clients.terminal)
        jarvis.bat --quiet    (hide the live "what Jarvis is doing" lines)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from typing import Any, Optional

import httpx

from core.config import Config
from core.single_instance import lock_is_held

BASE_URL = f"http://{Config.JARVIS_API_HOST}:{Config.JARVIS_API_PORT}"
EXIT_COMMANDS = {"exit", "quit", "avsluta", "hejdå", "hej då"}
STARTUP_WAIT_SECONDS = 600

# Events already shown in another way, or not interesting while waiting.
HIDDEN_EVENTS = {"query.received", "query.completed"}

DIM = "\033[2m"
RESET = "\033[0m"


class CoreUnavailable(Exception):
    pass


class JarvisClient:
    def __init__(self, token: str) -> None:
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = httpx.Client(base_url=BASE_URL, headers=self._headers, timeout=httpx.Timeout(10, read=900))

    def health(self) -> Optional[dict[str, Any]]:
        try:
            return self._http.get("/health", timeout=3).json()
        except httpx.HTTPError:
            return None

    def status(self) -> dict[str, Any]:
        response = self._http.get("/status")
        response.raise_for_status()
        return response.json()

    def chat(self, message: str) -> dict[str, Any]:
        response = self._http.post("/chat", json={"message": message, "channel": "terminal"})
        if response.status_code != 200:
            detail = _detail(response)
            raise CoreUnavailable(detail)
        return response.json()

    def follow_events(self, on_event, stop: threading.Event) -> None:
        """Follow the live event feed (reconnects quietly). Runs in a background thread."""
        last_id = _latest_event_id(self)
        while not stop.is_set():
            try:
                with httpx.Client(base_url=BASE_URL, headers=self._headers, timeout=httpx.Timeout(10, read=60)) as http:
                    with http.stream("GET", "/events/stream", params={"after_id": last_id}) as response:
                        for line in response.iter_lines():
                            if stop.is_set():
                                return
                            if line.startswith("data: "):
                                event = json.loads(line[6:])
                                last_id = max(last_id, int(event.get("id", 0)))
                                on_event(event)
            except Exception:
                stop.wait(3)

    def recent_events(self, after_id: int = 0, limit: int = 1) -> list[dict[str, Any]]:
        response = self._http.get("/events/recent", params={"after_id": after_id, "limit": limit})
        response.raise_for_status()
        return response.json()


def _latest_event_id(client: JarvisClient) -> int:
    try:
        events = client.recent_events(limit=1)
        return int(events[-1]["id"]) if events else 0
    except Exception:
        return 0


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.status_code))
    except ValueError:
        return f"HTTP {response.status_code}"


def read_token() -> Optional[str]:
    try:
        return Config.JARVIS_API_TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def print_not_running() -> None:
    print("Jarvis Core körs inte.")
    print("Starta den i bakgrunden:   .\\scripts\\restart_core.ps1")
    print("eller i ett eget fönster:  .venv\\Scripts\\python -m core.jarvis_core")
    print("Första gången:             .\\scripts\\install_core.ps1")


def wait_until_ready() -> Optional[JarvisClient]:
    """Connect to the core, waiting while it starts up. None if it is not running."""
    deadline = time.monotonic() + STARTUP_WAIT_SECONDS
    announced = False
    while time.monotonic() < deadline:
        token = read_token()
        client = JarvisClient(token) if token else None
        health = client.health() if client else None

        if health and health.get("ready"):
            if announced:
                print()
            return client
        if health is None and not lock_is_held():
            if announced:
                print()
            return None  # nothing is running
        if not announced:
            print("Jarvis startar (väntar på Ollama / synkar minnet)", end="", flush=True)
            announced = True
        else:
            print(".", end="", flush=True)
        time.sleep(2)
    print("\nJarvis Core svarar inte - se logs\\jarvis_core.log.")
    return None


def print_status(client: JarvisClient) -> None:
    s = client.status()

    def mark(value: Optional[bool]) -> str:
        return "-" if value is None else ("OK" if value else "NERE")

    hours, rest = divmod(int(s["uptime_seconds"]), 3600)
    print(f"Igång {hours} h {rest // 60} min | Ollama ({s['model']}): {mark(s['ollama'])} | "
          f"SearXNG: {mark(s['searxng'])} | Påminnelser: {mark(s['scheduler'])} | Telegram: {s['telegram']}")
    for reminder in s.get("upcoming_reminders", []):
        print(f"  • {reminder['due']} - {reminder['text']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Chatta med Jarvis Core")
    parser.add_argument("--quiet", action="store_true", help="visa inte vad Jarvis gör medan du väntar")
    args, _ = parser.parse_known_args()

    if os.name == "nt":
        os.system("")  # turn on ANSI colours in the Windows console

    print("=== JARVIS ===")
    client = wait_until_ready()
    if client is None:
        print_not_running()
        return 1
    print("Ansluten. Skriv din fråga ('/status' visar läget, 'exit' avslutar).")

    waiting = threading.Event()
    stop = threading.Event()

    def show_event(event: dict[str, Any]) -> None:
        if waiting.is_set() and event.get("type") not in HIDDEN_EVENTS:
            print(f"{DIM}  › {event.get('message', '')}{RESET}", flush=True)

    if not args.quiet:
        threading.Thread(target=client.follow_events, args=(show_event, stop), daemon=True).start()

    try:
        while True:
            try:
                user_input = input("\nDu > ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in EXIT_COMMANDS:
                break
            if user_input.lower() == "/status":
                try:
                    print_status(client)
                except Exception:
                    print("Kunde inte hämta status.")
                continue

            waiting.set()
            try:
                reply = client.chat(user_input)
            except KeyboardInterrupt:
                print("\n(avbrutet - Jarvis gör klart frågan i bakgrunden)")
                continue
            except (httpx.HTTPError, CoreUnavailable) as exc:
                print(f"\nKunde inte nå Jarvis Core: {exc}")
                continue
            finally:
                waiting.clear()
            print(f"\nJarvis [{reply['agent']} · {reply['seconds']:.1f}s] >\n{reply['reply']}")
    finally:
        stop.set()

    print("Hej då!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
