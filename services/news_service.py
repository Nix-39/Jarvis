"""
NewsService - headlines about the user's favourite teams.

Reads a few sports news feeds (RSS) every 15 minutes and keeps the items that
mention a favourite team (sports.favorites in the interface settings). A new
match is published as a "news.favorite" event - a notification in the interface,
never read aloud and held back in match mode - and the latest matches are
listed in the sports panel and used by the morning briefing.

Feeds: SVT Sport, Expressen Sport, Sportbladet (Aftonbladet) and ESPN (NHL, NFL,
football). Fixed hosts only, timeouts and a size cap; the XML is untrusted, so
documents with a DTD/entities are refused before parsing and every text is
stripped of markup and shortened. Links are only kept when they point to the
feed's own site.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

# name, feed URL, hosts its article links may point to
FEEDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("SVT Sport", "https://www.svt.se/sport/rss.xml", ("www.svt.se", "svt.se")),
    ("Expressen", "https://feeds.expressen.se/sport/", ("www.expressen.se", "expressen.se")),
    ("Sportbladet", "https://rss.aftonbladet.se/rss2/small/pages/sections/sportbladet/", ("www.aftonbladet.se", "aftonbladet.se")),
    ("ESPN", "https://www.espn.com/espn/rss/nhl/news", ("www.espn.com", "espn.com")),
    ("ESPN", "https://www.espn.com/espn/rss/nfl/news", ("www.espn.com", "espn.com")),
    ("ESPN", "https://www.espn.com/espn/rss/soccer/news", ("www.espn.com", "espn.com")),
)
FEED_HOSTS = {urlparse(url).hostname for _, url, _ in FEEDS}
REFRESH_SECONDS = 900
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_AGE = timedelta(hours=48)
KEEP = 40
SEEN_FILE = Config.DATA_DIR / "cache" / "news_seen.json"
USER_AGENT = "Yggdrasil/1.0 (personal news reader)"

# Extra names the press uses for a team (the favourite's own name always counts).
# Only names that are hard to confuse with other teams.
ALIASES: dict[str, tuple[str, ...]] = {
    "frölunda": ("frölunda", "frölundas"),
    "djurgården": ("djurgården", "djurgårdens", "dif"),
    "vegas golden knights": ("golden knights", "vegas golden knights"),
    "detroit red wings": ("red wings", "detroit red wings"),
    "new england patriots": ("patriots", "new england patriots"),
    "barcelona": ("barcelona", "barça", "barca"),
    "nottingham forest": ("nottingham forest", "forest"),
}


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    team: str
    published: str          # ISO, UTC
    summary: str = ""


def keywords(team: str) -> tuple[str, ...]:
    key = " ".join(team.lower().split())
    return tuple(dict.fromkeys((key,) + ALIASES.get(key, ())))


def mentions(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", low) for w in words)


def clean(text: str, limit: int) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(str(text or "")))
    return " ".join(plain.split())[:limit]


class NewsService:
    def __init__(self, favorites_provider: Callable[[], list[dict[str, str]]],
                 paused_provider: Optional[Callable[[], bool]] = None,
                 client: Optional[httpx.Client] = None, seen_file: Path = SEEN_FILE) -> None:
        self.favorites_provider = favorites_provider
        self.paused_provider = paused_provider or (lambda: False)
        self._client = client or httpx.Client(timeout=10, follow_redirects=False, headers={"User-Agent": USER_AGENT})
        self._seen_file = Path(seen_file)
        self._seen: list[str] = self._load_seen()
        self._first_run = not self._seen
        self._items: list[NewsItem] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()

    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(i) for i in self._items]

    def recent(self, since: datetime) -> list[dict[str, Any]]:
        """Matched headlines published after `since` (for the morning briefing)."""
        return [i for i in self.snapshot() if datetime.fromisoformat(i["published"]) >= since]

    def wake(self) -> None:
        self._wake.set()

    def run_forever(self, stop: threading.Event) -> None:
        if stop.wait(30):
            return
        while not stop.is_set():
            try:
                self.refresh()
            except Exception as exc:
                logger.exception("News thread error: %s", exc)
            self._wake.clear()
            deadline = time.monotonic() + REFRESH_SECONDS
            while time.monotonic() < deadline:
                if stop.wait(2):
                    return
                if self._wake.is_set():
                    break

    def refresh(self) -> None:
        teams = list(dict.fromkeys(f.get("team", "") for f in self.favorites_provider() if f.get("team")))
        if not teams:
            with self._lock:
                self._items = []
            return
        found: dict[str, NewsItem] = {}
        for source, url, hosts in FEEDS:
            try:
                for item in self._read(url, source, hosts):
                    for team in teams:
                        if mentions(f"{item.title} {item.summary}", keywords(team)):
                            found.setdefault(item.url, NewsItem(**{**asdict(item), "team": team}))
                            break
            except Exception as exc:
                logger.warning("News feed %s failed: %s", source, exc)
                with self._lock:          # keep what this feed gave last time
                    for old in self._items:
                        if old.source == source and old.team in teams:
                            found.setdefault(old.url, old)
        items = sorted(found.values(), key=lambda i: i.published, reverse=True)[:KEEP]
        new = [i for i in items if i.url not in self._seen]
        with self._lock:
            self._items = items
        if new:
            self._seen = (self._seen + [i.url for i in new])[-500:]
            self._save_seen()
        if self._first_run:          # do not announce everything that is already there
            self._first_run = False
            return
        if self.paused_provider():
            return
        for item in reversed(new[:5]):
            event_bus.publish("news.favorite", "news", f"📰 {item.team}: {item.title}",
                              url=item.url, feed=item.source, team=item.team)

    # ------------------------------------------------------------------

    def _read(self, url: str, source: str, hosts: tuple[str, ...]) -> list[NewsItem]:
        if urlparse(url).hostname not in FEED_HOSTS:
            raise ValueError("host not allowed")
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_FEED_BYTES:
                    raise ValueError("feed too large")
        if b"<!DOCTYPE" in body[:4096].upper() or b"<!ENTITY" in body.upper():
            raise ValueError("feed with DTD refused")
        root = ET.fromstring(body)
        now = datetime.now(timezone.utc)
        out = []
        for node in root.iter("item"):
            title = clean(node.findtext("title"), 200)
            link = (node.findtext("link") or "").strip()
            parsed = urlparse(link)
            if not title or parsed.scheme != "https" or parsed.hostname not in hosts:
                continue
            try:
                published = parsedate_to_datetime(node.findtext("pubDate") or "")
                published = (published if published.tzinfo else published.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
            except (TypeError, ValueError):
                published = now
            if now - published > MAX_AGE:
                continue
            out.append(NewsItem(title, link[:500], source, "", published.isoformat(timespec="seconds"),
                                clean(node.findtext("description"), 300)))
        return out

    def _load_seen(self) -> list[str]:
        try:
            data = json.loads(self._seen_file.read_text(encoding="utf-8"))
            return [str(u) for u in data][-500:] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_seen(self) -> None:
        try:
            self._seen_file.parent.mkdir(parents=True, exist_ok=True)
            self._seen_file.write_text(json.dumps(self._seen), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not save seen news: %s", exc)
