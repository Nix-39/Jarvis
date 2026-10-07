"""
Yggdrasil desktop app - the visual interface for Jarvis Core.

A thin window around the interface that the core serves on 127.0.0.1:
    - own window (WebView2 / Edge engine) with the Yggdrasil icon,
    - icon in the system tray; closing the window only hides it,
    - global hotkey (default Ctrl+Alt+J) that brings the window up with the
      cursor in "Fråga Oden…",
    - starts hidden at login (--hidden), opened from the desktop shortcut.

Security:
    - The API token is handed to the page through pywebview's JS bridge, so only
      this window can use the API - not other web pages or programs.
    - The global hotkey uses Windows' RegisterHotKey: Windows reports only that
      one key combination to us. No keyboard hook, nothing else is seen.
    - External links open in the normal browser, and only for an allowlist of sites.

Start:  .venv\\Scripts\\pythonw -m clients.desktop  [--hidden]
Install shortcut + autostart:  .\\scripts\\install_desktop.ps1
"""

import os
import sys

os.environ.setdefault("JARVIS_LOG_FILE", "yggdrasil_desktop.log")
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import argparse  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import httpx  # noqa: E402

from core.config import Config  # noqa: E402
from core.logger import get_logger  # noqa: E402

logger = get_logger("clients.desktop")

APP_NAME = "Yggdrasil"
BASE_URL = f"http://{Config.JARVIS_API_HOST}:{Config.JARVIS_API_PORT}"
UI_URL = f"{BASE_URL}/app/"
ICON_ICO = Config.UI_DIR / "assets" / "yggdrasil.ico"
ICON_PNG = Config.UI_DIR / "assets" / "yggdrasil.png"
DESKTOP_PORT = int(os.getenv("DESKTOP_PORT", "47832"))   # single instance + "show" signal (localhost only)
ALLOWED_LINK_HOSTS = {"www.espn.com", "espn.com", "www.shl.se", "www.hockeyallsvenskan.se", "www.thesportsdb.com", "mail.google.com", "calendar.google.com", "www.smhi.se"}

LOADING_HTML = """<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#040404;
font-family:Segoe UI,sans-serif;color:#a6987a;letter-spacing:.14em"><div style="text-align:center">
<div style="font:800 44px Segoe UI;letter-spacing:.34em;color:#f0b43c;text-shadow:0 0 14px rgba(240,180,60,.7)">YGGDRASIL</div>
<p>Väntar på kärnan…</p></div></body></html>"""


class Bridge:
    """Methods the page can call through window.pywebview.api."""

    def get_token(self) -> str:
        try:
            return Config.JARVIS_API_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def open_url(self, url: str) -> bool:
        parsed = urlparse(str(url))
        if parsed.scheme == "https" and parsed.hostname in ALLOWED_LINK_HOSTS:
            webbrowser.open(parsed.geturl())
            return True
        logger.warning("Blocked opening a non-allowlisted link.")
        return False


class DesktopApp:
    def __init__(self, start_hidden: bool) -> None:
        import webview

        self.webview = webview
        self.quitting = False
        self.window = webview.create_window(
            APP_NAME, html=LOADING_HTML, js_api=Bridge(), width=1600, height=950, min_size=(1200, 760),
            background_color="#040404", hidden=start_hidden, text_select=True,
        )
        self.window.events.closing += self._on_closing
        self.tray = None

    # ------------------------------------------------------------------

    def run(self, listener: socket.socket) -> None:
        threading.Thread(target=self._serve_show_requests, args=(listener,), daemon=True, name="desktop-signal").start()
        threading.Thread(target=self._load_when_core_ready, daemon=True, name="desktop-wait").start()
        threading.Thread(target=self._hotkey_loop, daemon=True, name="desktop-hotkey").start()
        self._start_tray()
        icon = str(ICON_ICO) if ICON_ICO.exists() else None
        self.webview.start(icon=icon, private_mode=True)   # blocks until quit
        if self.tray:
            self.tray.stop()

    def show(self) -> None:
        try:
            self.window.show()
            self.window.restore()
            self.window.on_top = True        # bring to front on Windows...
            self.window.on_top = False       # ...without staying on top
            self.window.evaluate_js("window.ygg && window.ygg.focusAsk()")
        except Exception as exc:
            logger.warning("Could not show window: %s", exc)

    def quit(self) -> None:
        self.quitting = True
        try:
            self.window.destroy()
        except Exception:
            os._exit(0)

    # ------------------------------------------------------------------

    def _on_closing(self):
        if self.quitting:
            return True
        self.window.hide()        # keep running in the tray
        return False              # cancel the close

    def _load_when_core_ready(self) -> None:
        while not self.quitting:
            try:
                if httpx.get(f"{BASE_URL}/health", timeout=2).status_code == 200:
                    self.window.load_url(UI_URL)
                    return
            except Exception:
                pass
            time.sleep(2)

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image
        except ImportError:
            logger.warning("pystray/Pillow missing - no tray icon.")
            return
        try:
            image = Image.open(ICON_PNG) if ICON_PNG.exists() else Image.new("RGB", (64, 64), (240, 180, 60))
            menu = pystray.Menu(
                pystray.MenuItem(f"Visa {APP_NAME}", lambda: self.show(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Avsluta fönstret", lambda: self.quit()),
            )
            self.tray = pystray.Icon("yggdrasil", image, APP_NAME, menu)
            self.tray.run_detached()
        except Exception as exc:
            logger.warning("Tray icon failed: %s", exc)

    def _serve_show_requests(self, listener: socket.socket) -> None:
        """A second launch (desktop shortcut) asks this instance to show itself."""
        listener.listen(2)
        while not self.quitting:
            try:
                conn, _ = listener.accept()
                with conn:
                    conn.settimeout(1)
                    if conn.recv(16).strip() == b"SHOW":
                        self.show()
            except Exception:
                time.sleep(0.2)

    def _hotkey_loop(self) -> None:
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        mods, vk = parse_hotkey(Config.DESKTOP_HOTKEY)
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, mods | 0x4000, vk):   # 0x4000 = MOD_NOREPEAT
            logger.warning("Hotkey %s is used by another program.", Config.DESKTOP_HOTKEY)
            return
        logger.info("Global hotkey %s registered.", Config.DESKTOP_HOTKEY)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:   # WM_HOTKEY
                self.show()


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+j' -> (MOD_CONTROL|MOD_ALT, VK_J)."""
    mod_bits = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
    mods, vk = 0, 0
    for part in text.lower().replace(" ", "").split("+"):
        if part in mod_bits:
            mods |= mod_bits[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])   # F1 = 0x70
    if not vk:
        raise ValueError(f"Invalid hotkey: {text}")
    return mods, vk


def main() -> int:
    parser = argparse.ArgumentParser(description="Yggdrasil desktop app")
    parser.add_argument("--hidden", action="store_true", help="start in the tray (used at login)")
    args = parser.parse_args()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind(("127.0.0.1", DESKTOP_PORT))
    except OSError:
        # Already running: ask that window to come forward, then exit.
        listener.close()
        if not args.hidden:
            try:
                with socket.create_connection(("127.0.0.1", DESKTOP_PORT), timeout=2) as s:
                    s.sendall(b"SHOW\n")
            except OSError:
                pass
        return 0

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Yggdrasil.Desktop")
        except Exception:
            pass

    logger.info("Desktop app starting%s.", " hidden" if args.hidden else "")
    DesktopApp(start_hidden=args.hidden).run(listener)
    logger.info("Desktop app closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
