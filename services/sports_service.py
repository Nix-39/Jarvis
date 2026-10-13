"""
SportsService - results and upcoming games for the sports ticker.

Two swappable providers behind one small Game model:
    - ESPN's public scoreboard JSON (site.api.espn.com, no key) for most leagues:
      Allsvenskan, Premier League, Champions League, NHL, NBA ...
    - TheSportsDB (free public key) for leagues ESPN does not cover, e.g. SHL.

Which leagues are shown is a personal setting (data/ui/settings.json,
`sports.leagues`) that the user changes by telling Nexus ("lägg till Premier
League i resultaten"). A background thread in Jarvis Core refreshes the chosen
leagues (every 10 minutes, every minute while a game is live) and caches the
team logos locally, so the interface never talks to the internet itself.

Favourite teams (`sports.favorites`) are followed in their leagues even when a
league is not in the ticker: when one of their games starts, the score changes
or it ends, a "sports.favorite" event is published (shown as a notification in
the interface, never read aloud). "Match mode" (`sports.paused_until`) holds the
notifications back and the interface hides live scores, so nothing gets ahead of
a delayed broadcast. The results also feed the morning briefing.

SHL live: TheSportsDB's free key has no live scores. With an API-Sports key
(API_SPORTS_KEY in .env, free plan 100 requests/day) SHL games are polled every
two minutes while one is on, and the live score is laid over TheSportsDB's data.

Everything from these APIs is untrusted: only fixed hosts are contacted, sizes
and timeouts are capped, logos are checked by their magic bytes, and the
interface escapes every text it shows.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx

from core.config import Config
from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

LOGO_DIR = Config.DATA_DIR / "cache" / "logos"
API_HOSTS = {"site.api.espn.com", "www.thesportsdb.com"}
APISPORTS_HOST = "v1.hockey.api-sports.io"
APISPORTS_CACHE = Config.DATA_DIR / "cache" / "apisports.json"
APISPORTS_DAILY_MAX = 90                 # free plan: 100 requests/day - keep a margin
SHL_POLL_SECONDS = 110
HOCKEY = {"shl", "hockeyallsvenskan", "sdhl", "nhl", "liiga", "khl", "del", "nationalleague"}
LOGO_HOSTS = {"a.espncdn.com", "r2.thesportsdb.com", "www.thesportsdb.com"}
SPORTSDB_KEY = "123"                     # TheSportsDB's free public key
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_LOGO_BYTES = 512 * 1024
REFRESH_SECONDS = 600
LIVE_REFRESH_SECONDS = 60
UPCOMING_DAYS = 14
USER_AGENT = "Yggdrasil/1.0 (personal dashboard)"


@dataclass(frozen=True)
class League:
    key: str
    name: str
    aliases: tuple[str, ...]
    group: str = "Fotboll"   # heading in the "add league" list
    espn: str = ""           # "soccer/swe.1"
    sportsdb: int = 0        # TheSportsDB league id
    web: str = ""            # page opened for games without their own link


def _espn(key: str, name: str, aliases: tuple[str, ...], slug: str, group: str = "Fotboll") -> League:
    sport, code = slug.split("/")
    web = (f"https://www.espn.com/soccer/scoreboard/_/league/{code}" if sport == "soccer"
           else f"https://www.espn.com/{code}/scoreboard")
    return League(key, name, aliases, group, espn=slug, web=web)


def _sdb(key: str, name: str, aliases: tuple[str, ...], league_id: int, group: str, web: str = "") -> League:
    return League(key, name, aliases, group, sportsdb=league_id, web=web or f"https://www.thesportsdb.com/league/{league_id}")


# Leagues Nexus knows. Add more here - the key is what the settings store.
CATALOG: dict[str, League] = {l.key: l for l in (
    # Sweden
    _espn("allsvenskan", "Allsvenskan", ("allsvenskan", "allsvenska"), "soccer/swe.1", "Sverige"),
    _espn("superettan", "Superettan", ("superettan",), "soccer/swe.2", "Sverige"),
    _sdb("damallsvenskan", "Damallsvenskan", ("damallsvenskan",), 5209, "Sverige"),
    _sdb("svenskacupen", "Svenska Cupen", ("svenska cupen", "cupen"), 4756, "Sverige"),
    _sdb("div1s", "Division 1 Södra", ("division 1 södra", "div 1 södra", "ettan södra"), 4845, "Sverige"),
    _sdb("div1n", "Division 1 Norra", ("division 1 norra", "div 1 norra", "ettan norra"), 4674, "Sverige"),
    _sdb("shl", "SHL", ("shl", "svenska hockeyligan", "hockeyligan"), 4419, "Sverige", "https://www.shl.se/"),
    _sdb("hockeyallsvenskan", "HockeyAllsvenskan", ("hockeyallsvenskan", "hockeyallsvenska"), 5162, "Sverige", "https://www.hockeyallsvenskan.se/"),
    _sdb("sdhl", "SDHL", ("sdhl", "damhockey", "dam-shl"), 5158, "Sverige"),
    # Football abroad
    _espn("premier", "Premier League", ("premier league", "premier", "engelska ligan", "pl"), "soccer/eng.1"),
    _espn("championship", "Championship", ("championship", "engelska championship"), "soccer/eng.2"),
    _espn("facup", "FA-cupen", ("fa-cupen", "fa cupen", "fa cup"), "soccer/eng.fa"),
    _espn("laliga", "La Liga", ("la liga", "laliga", "spanska ligan"), "soccer/esp.1"),
    _espn("seriea", "Serie A", ("serie a", "italienska ligan"), "soccer/ita.1"),
    _espn("bundesliga", "Bundesliga", ("bundesliga", "tyska ligan"), "soccer/ger.1"),
    _espn("ligue1", "Ligue 1", ("ligue 1", "franska ligan"), "soccer/fra.1"),
    _espn("eredivisie", "Eredivisie", ("eredivisie", "holländska ligan"), "soccer/ned.1"),
    _espn("primeira", "Primeira Liga", ("primeira liga", "portugisiska ligan"), "soccer/por.1"),
    _espn("scotland", "Skotska Premiership", ("skotska ligan", "scottish premiership", "skotska premiership"), "soccer/sco.1"),
    _espn("superligaen", "Superligaen", ("superligaen", "danska ligan"), "soccer/den.1"),
    _espn("eliteserien", "Eliteserien", ("eliteserien", "norska ligan"), "soccer/nor.1"),
    _espn("mls", "MLS", ("mls",), "soccer/usa.1"),
    _espn("cl", "Champions League", ("champions league", "cl", "mästarligan"), "soccer/uefa.champions", "Europa & landslag"),
    _espn("el", "Europa League", ("europa league", "el"), "soccer/uefa.europa", "Europa & landslag"),
    _espn("ecl", "Conference League", ("conference league", "ecl"), "soccer/uefa.europa.conf", "Europa & landslag"),
    _espn("nations", "Nations League", ("nations league",), "soccer/uefa.nations", "Europa & landslag"),
    _espn("vm", "Fotbolls-VM", ("vm", "fotbolls-vm", "world cup"), "soccer/fifa.world", "Europa & landslag"),
    _espn("vmkval", "VM-kval (Europa)", ("vm-kval", "vm kval"), "soccer/fifa.worldq.uefa", "Europa & landslag"),
    _espn("em", "Fotbolls-EM", ("em", "fotbolls-em", "euro"), "soccer/uefa.euro", "Europa & landslag"),
    # Hockey abroad
    _espn("nhl", "NHL", ("nhl",), "hockey/nhl", "Hockey"),
    _sdb("liiga", "Liiga", ("liiga", "finska ligan", "fm-ligan"), 4931, "Hockey"),
    _sdb("khl", "KHL", ("khl",), 4920, "Hockey"),
    _sdb("del", "DEL", ("del", "tyska hockeyligan"), 4925, "Hockey"),
    _sdb("nationalleague", "National League", ("national league", "schweiziska ligan"), 4934, "Hockey"),
    # Other sports
    _espn("nba", "NBA", ("nba",), "basketball/nba", "Övrigt"),
    _espn("wnba", "WNBA", ("wnba",), "basketball/wnba", "Övrigt"),
    _espn("nfl", "NFL", ("nfl", "amerikansk fotboll"), "football/nfl", "Övrigt"),
    _espn("mlb", "MLB", ("mlb", "baseboll"), "baseball/mlb", "Övrigt"),
)}
MAX_LEAGUES = 30
DEFAULT_LEAGUES = ["shl", "allsvenskan"]

# Short names for SHL teams (TheSportsDB has no short names on the free key).
SHL_SHORT = {
    "Brynäs IF": "Brynäs", "Djurgårdens IF": "Djurgården", "Färjestad BK": "Färjestad", "Frölunda HC": "Frölunda",
    "HV71": "HV71", "IF Björklöven": "Björklöven", "Linköpings HC": "Linköping", "Luleå HF": "Luleå",
    "Malmö Redhawks": "Malmö", "Örebro HK": "Örebro", "Rögle BK": "Rögle", "Skellefteå AIK": "Skellefteå",
    "Timrå IK": "Timrå", "Växjö Lakers": "Växjö", "Leksands IF": "Leksand", "IK Oskarshamn": "Oskarshamn",
}


def find_league(text: str) -> Optional[League]:
    wanted = " ".join(text.lower().split())
    for league in CATALOG.values():
        if wanted == league.key or wanted == league.name.lower() or wanted in league.aliases:
            return league
    return None


@dataclass
class Team:
    name: str
    short: str
    score: Optional[str] = None
    winner: bool = False
    logo: str = ""          # local file name in the logo cache ("" = none)


@dataclass
class Game:
    id: str
    league: str
    start: str               # ISO, UTC
    state: str               # "pre" | "in" | "post"
    status: str              # Swedish: "Slut", "Slut (ÖT)", "63'", ...
    home: Team
    away: Team
    url: str = ""


@dataclass
class LeagueResult:
    key: str
    name: str
    web: str
    games: list[Game] = field(default_factory=list)
    updated: Optional[str] = None
    error: Optional[str] = None


class SportsService:
    def __init__(self, leagues_provider: Callable[[], list[str]], logo_dir: Path = LOGO_DIR,
                 client: Optional[httpx.Client] = None,
                 favorites_provider: Optional[Callable[[], list[dict[str, str]]]] = None,
                 paused_provider: Optional[Callable[[], bool]] = None,
                 apisports_key: Optional[str] = None) -> None:
        self.leagues_provider = leagues_provider
        self.favorites_provider = favorites_provider or (lambda: [])
        self.paused_provider = paused_provider or (lambda: False)
        self.logo_dir = Path(logo_dir)
        self.logo_dir.mkdir(parents=True, exist_ok=True)
        self._client = client or httpx.Client(timeout=10, follow_redirects=False, headers={"User-Agent": USER_AGENT})
        self._lock = threading.Lock()
        self._cache: dict[str, LeagueResult] = {}
        self._wake = threading.Event()
        self._bad_logos: set[str] = set()   # logos that failed this session - not retried
        self._fav_state: dict[str, tuple] = {}          # game -> (state, home score, away score) last seen
        self._fav_ready = False                         # no notifications for what is already there at start
        self.feed: deque = deque(maxlen=40)             # favourite notifications, newest last
        key = Config.API_SPORTS_KEY if apisports_key is None else apisports_key
        self.shl_live = ShlLive(key, self._client) if key else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def leagues(self) -> list[str]:
        return [k for k in self.leagues_provider() if k in CATALOG]

    def favorites(self) -> list[dict[str, str]]:
        return [f for f in self.favorites_provider() if f.get("league") in CATALOG]

    def fetch_keys(self) -> list[str]:
        """The ticker's leagues plus the leagues of favourite teams."""
        return list(dict.fromkeys(self.leagues() + [f["league"] for f in self.favorites()]))

    def snapshot(self) -> dict[str, Any]:
        """Cached results for the chosen leagues + favourite games (never blocks on the network)."""
        favs = self.favorites()
        mark = lambda g: {**asdict(g), "fav": is_favorite(g, favs)}
        with self._lock:
            out = []
            for key in self.leagues():
                result = self._cache.get(key) or LeagueResult(key, CATALOG[key].name, CATALOG[key].web)
                out.append({**asdict(result), "games": [mark(g) for g in result.games]})
            fav_games = sorted((g for r in self._cache.values() for g in r.games if is_favorite(g, favs)), key=lambda g: g.start)
            return {
                "leagues": out,
                "favorites": [{**mark(g), "league_name": CATALOG[g.league].name} for g in fav_games],
                "favorite_teams": favs,
                "feed": list(self.feed)[-20:],
                "paused": self.paused_provider(),
                "live_note": self.shl_live.note if self.shl_live else "",
            }

    def team_leagues(self, team: str) -> list[str]:
        """Leagues among the fetched ones where a team with this name plays (for "lägg till X som favoritlag")."""
        wanted = fold(team)
        with self._lock:
            return [key for key, r in self._cache.items()
                    if wanted and any(wanted in fold(t.name) or wanted == fold(t.short) for g in r.games for t in (g.home, g.away))]

    def favorite_results(self, since: datetime) -> list[dict[str, Any]]:
        """Finished favourite games that started after `since` (for the morning briefing)."""
        favs = self.favorites()
        with self._lock:
            games = [g for r in self._cache.values() for g in r.games
                     if g.state == "post" and is_favorite(g, favs) and _parse_utc(g.start) >= since]
        return [{**asdict(g), "league_name": CATALOG[g.league].name, "text": result_text(g)} for g in sorted(games, key=lambda g: g.start)]

    def refresh(self, keys: Optional[list[str]] = None) -> None:
        changed = False
        for key in keys or self.fetch_keys():
            league = CATALOG[key]
            try:
                games = self._fetch_espn(league) if league.espn else self._fetch_sportsdb(league)
                if key == "shl" and self.shl_live is not None:
                    self.shl_live.overlay(games)
                result = LeagueResult(key, league.name, league.web, games, datetime.now(timezone.utc).isoformat(timespec="seconds"))
            except Exception as exc:
                logger.warning("Sports refresh failed for %s: %s", key, exc)
                old = self._cache.get(key)
                result = old or LeagueResult(key, league.name, league.web)
                result.error = "Kunde inte hämta resultat just nu."
            with self._lock:
                old = self._cache.get(key)
                changed |= old is None or [asdict(g) for g in old.games] != [asdict(g) for g in result.games]
                self._cache[key] = result
        if changed:
            event_bus.publish("sports.updated", "sports", "Nya sportresultat")
        self._check_favorites()

    def _check_favorites(self) -> None:
        """Notify when a favourite team's game starts, the score changes or it ends (not in match mode)."""
        favs, paused = self.favorites(), self.paused_provider()
        with self._lock:
            games = [g for r in self._cache.values() for g in r.games if is_favorite(g, favs)]
        for g in games:
            key = f"{g.league}:{g.id}"
            now = (g.state, g.home.score, g.away.score)
            before = self._fav_state.get(key)
            self._fav_state[key] = now
            if before is None or not self._fav_ready or paused or before == now:
                continue
            kind = ""
            if now[0] == "post" and before[0] != "post":
                kind = "final"
            elif now[0] == "in" and before[0] == "pre":
                kind = "start"
            elif now[0] == "in" and before[0] == "in" and now[1:] != before[1:]:
                kind = "score"
            if kind:
                text = notice_text(g, kind)
                self.feed.append({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
                                  "text": text, "league": g.league, "game": g.id})
                event_bus.publish("sports.favorite", "sports", text, kind=kind, league=g.league, game=g.id)
        self._fav_ready = True

    def wake(self) -> None:
        """Refresh now (e.g. after a league was added)."""
        self._wake.set()

    def run_forever(self, stop: threading.Event) -> None:
        if stop.wait(15):
            return
        while not stop.is_set():
            try:
                self.refresh()
            except Exception as exc:   # never let the thread die
                logger.exception("Sports thread error: %s", exc)
            live = any(g.state == "in" for r in list(self._cache.values()) for g in r.games) or \
                (self.shl_live is not None and self.shl_live.window(self._cache.get("shl")))
            self._wake.clear()
            if self._wait(stop, LIVE_REFRESH_SECONDS if live else REFRESH_SECONDS):
                return

    def logo_path(self, name: str) -> Optional[Path]:
        if not re.fullmatch(r"[0-9a-f]{20}\.(png|jpg|webp)", name):
            return None
        path = self.logo_dir / name
        return path if path.is_file() else None

    # ------------------------------------------------------------------
    # ESPN
    # ------------------------------------------------------------------

    def _fetch_espn(self, league: League) -> list[Game]:
        """
        The scoreboard has no date ranges: without parameters it returns the
        current/next game day, and ?dates=YYYYMMDD one day. The league calendar
        in that response lists every game day, so the latest played round (up to
        3 game days) and the next game days are fetched on top.
        """
        base = f"https://site.api.espn.com/apis/site/v2/sports/{league.espn}/scoreboard"
        first = self._get_json(base, {})
        events = list(first.get("events") or [])
        today = datetime.now().date()
        shown = str((first.get("day") or {}).get("date") or "")[:10]
        days = _calendar_days(first)
        if days:
            played = [d for d in days if d < today.isoformat()]
            latest = played[-1] if played else ""
            past = [d for d in played if latest and d >= (date_from(latest) - timedelta(days=3)).isoformat()][-3:]
            ahead = [d for d in days if d >= today.isoformat() and d != shown][:2]
            extra = past + ahead
        else:   # e.g. NFL weeks: just yesterday and the day before
            extra = [(today - timedelta(days=n)).isoformat() for n in (1, 2)]
        for day in extra:
            if day != shown:
                events += self._get_json(base, {"dates": day.replace("-", "")}).get("events") or []
        data = {"events": list({str(e.get("id")): e for e in events}.values())}
        games = []
        for event in data.get("events") or []:
            try:
                comp = (event.get("competitions") or [{}])[0]
                sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
                if "home" not in sides or "away" not in sides:
                    continue
                status = (event.get("status") or {}).get("type") or {}
                state = status.get("state") if status.get("state") in ("pre", "in", "post") else "pre"
                link = next((l.get("href") for l in event.get("links") or [] if _allowed_link(l.get("href", ""))), league.web)
                games.append(Game(
                    id=str(event.get("id", ""))[:20], league=league.key, start=_iso(event.get("date")),
                    state=state, status=_espn_status(state, status),
                    home=self._espn_team(sides["home"], state), away=self._espn_team(sides["away"], state), url=link,
                ))
            except (TypeError, ValueError, AttributeError) as exc:
                logger.debug("Skipping malformed ESPN event: %s", exc)
        return sorted(games, key=lambda g: g.start)

    def _espn_team(self, side: dict[str, Any], state: str) -> Team:
        team = side.get("team") or {}
        name = str(team.get("displayName") or team.get("name") or "?")[:60]
        return Team(
            name=name, short=str(team.get("shortDisplayName") or team.get("abbreviation") or name)[:24],
            score=str(side.get("score"))[:4] if state != "pre" and side.get("score") is not None else None,
            winner=bool(side.get("winner")), logo=self._logo(team.get("logo", "")),
        )

    # ------------------------------------------------------------------
    # TheSportsDB
    # ------------------------------------------------------------------

    def _fetch_sportsdb(self, league: League) -> list[Game]:
        base = f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}"
        latest = (self._get_json(f"{base}/eventspastleague.php", {"id": str(league.sportsdb)}).get("events") or [{}])[0]
        season, round_no = latest.get("strSeason"), int(latest.get("intRound") or 0)
        if not season or not round_no:
            return []
        # The latest played round (results) and the next rounds (upcoming games).
        events = []
        for r in (round_no, round_no + 1, round_no + 2):
            events += self._get_json(f"{base}/eventsround.php", {"id": str(league.sportsdb), "r": str(r), "s": season}).get("events") or []
        now = datetime.now(timezone.utc)
        games = []
        for e in events:
            try:
                start = _sportsdb_start(e)
                if start > now + timedelta(days=UPCOMING_DAYS):
                    continue
                code = str(e.get("strStatus") or "").upper()
                hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
                state = "post" if code in ("FT", "AOT", "AP", "PEN", "AET", "MATCH FINISHED") else \
                        "pre" if code in ("", "NS", "NOT STARTED", "TBD", "POSTPONED", "PST") or hs is None else "in"
                home_won = state == "post" and hs is not None and as_ is not None and int(hs) > int(as_)
                away_won = state == "post" and hs is not None and as_ is not None and int(as_) > int(hs)
                games.append(Game(
                    id=str(e.get("idEvent", ""))[:20], league=league.key, start=start.isoformat(timespec="seconds"),
                    state=state, status=_sportsdb_status(state, code),
                    home=Team(str(e.get("strHomeTeam"))[:60], _short(str(e.get("strHomeTeam"))), None if state == "pre" else str(hs),
                              home_won, self._logo(e.get("strHomeTeamBadge") or "")),
                    away=Team(str(e.get("strAwayTeam"))[:60], _short(str(e.get("strAwayTeam"))), None if state == "pre" else str(as_),
                              away_won, self._logo(e.get("strAwayTeamBadge") or "")),
                    url=league.web,
                ))
            except (TypeError, ValueError) as exc:
                logger.debug("Skipping malformed TheSportsDB event: %s", exc)
        games = sorted({g.id: g for g in games}.values(), key=lambda g: g.start)
        upcoming = [g for g in games if g.state == "pre"]
        next_day = upcoming[0].start[:10] if upcoming else ""
        # Results of the latest round + the next game day (not three rounds of upcoming games).
        return [g for g in games if g.state != "pre" or g.start[:10] == next_day]

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    def _get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        if urlparse(url).hostname not in API_HOSTS:
            raise ValueError("host not allowed")
        with self._client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_JSON_BYTES:
                    raise ValueError("response too large")
        data = httpx.Response(200, content=body).json()
        return data if isinstance(data, dict) else {}

    def _logo(self, url: str) -> str:
        """Download a team logo once into the local cache; returns its file name or ''."""
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or parsed.hostname not in LOGO_HOSTS:
            return ""
        digest = hashlib.sha1(parsed.geturl().encode()).hexdigest()[:20]
        for ext in ("png", "jpg", "webp"):
            if (self.logo_dir / f"{digest}.{ext}").is_file():
                return f"{digest}.{ext}"
        if digest in self._bad_logos:
            return ""
        try:
            response = self._client.get(parsed.geturl())
            response.raise_for_status()
            data = response.content
            if len(data) > MAX_LOGO_BYTES:
                self._bad_logos.add(digest)
                return ""
            ext = "png" if data.startswith(b"\x89PNG") else "jpg" if data.startswith(b"\xff\xd8\xff") else \
                  "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""
            if not ext:
                self._bad_logos.add(digest)
                return ""
            (self.logo_dir / f"{digest}.{ext}").write_bytes(data)
            return f"{digest}.{ext}"
        except Exception as exc:
            logger.debug("Logo download failed: %s", exc)
            self._bad_logos.add(digest)
            return ""

    def _wait(self, stop: threading.Event, seconds: float) -> bool:
        """Sleep until the next refresh, a wake-up or shutdown. Returns True on shutdown."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop.wait(1):
                return True
            if self._wake.is_set():
                return False
        return False


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def date_from(text: str):
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _calendar_days(data: dict[str, Any]) -> list[str]:
    """Game days (YYYY-MM-DD) from an ESPN scoreboard's league calendar; [] when it is not a plain day list."""
    try:
        calendar = (data.get("leagues") or [{}])[0].get("calendar") or []
    except (AttributeError, IndexError, TypeError):
        return []
    days = sorted({str(item)[:10] for item in calendar if isinstance(item, str) and re.match(r"\d{4}-\d{2}-\d{2}", item)})
    return days


def _allowed_link(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ("www.espn.com", "espn.com")


def _iso(value: Any) -> str:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _espn_status(state: str, status: dict[str, Any]) -> str:
    detail = str(status.get("shortDetail") or status.get("detail") or "")[:20]
    if state == "pre":
        return ""
    if state == "in":
        return "Paus" if detail.upper() in ("HT", "HALFTIME") else detail
    upper = detail.upper()
    if "PEN" in upper or "SO" in upper.split("/"):
        return "Slut (str)"
    if "OT" in upper or "AET" in upper:
        return "Slut (ÖT)"
    return "Slut"


def _sportsdb_start(event: dict[str, Any]) -> datetime:
    stamp = event.get("strTimestamp")
    if stamp:
        return _parse_utc(stamp)
    return _parse_utc(f"{event.get('dateEvent')}T{event.get('strTime') or '00:00:00'}")


def _parse_utc(text: str) -> datetime:
    moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _sportsdb_status(state: str, code: str) -> str:
    if state == "pre":
        return ""
    if state == "post":
        return "Slut (ÖT)" if code in ("AOT", "AET") else "Slut (str)" if code in ("AP", "PEN") else "Slut"
    return {"1P": "P1", "2P": "P2", "3P": "P3", "OT": "ÖT", "HT": "Paus"}.get(code, code[:8] or "Pågår")


def _short(name: str) -> str:
    if name in SHL_SHORT:
        return SHL_SHORT[name]
    words = [w for w in name.split() if w.upper() not in ("IF", "IK", "HC", "BK", "HF", "HK", "AIK", "FF", "FC", "SK")]
    return (" ".join(words) or name)[:24]


# ----------------------------------------------------------------------
# Favourites
# ----------------------------------------------------------------------

def fold(text: str) -> str:
    """'Frölunda HC' -> 'frolundahc': lower case, no accents, letters and digits only."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def is_favorite(game: Game, favorites: list[dict[str, str]]) -> bool:
    for fav in favorites:
        if fav.get("league") != game.league:
            continue
        wanted = fold(fav.get("team", ""))
        if wanted and any(wanted in fold(t.name) or wanted == fold(t.short) for t in (game.home, game.away)):
            return True
    return False


def sport_icon(league: str) -> str:
    return "🏒" if league in HOCKEY else "🏈" if league == "nfl" else "🏀" if league in ("nba", "wnba") else \
        "⚾" if league == "mlb" else "⚽"


def result_text(g: Game) -> str:
    extra = " (ÖT)" if "ÖT" in g.status else " (str)" if "str" in g.status else ""
    return f"{g.home.short} {g.home.score or 0}–{g.away.score or 0} {g.away.short}{extra}"


def notice_text(g: Game, kind: str) -> str:
    icon, league = sport_icon(g.league), CATALOG[g.league].name
    if kind == "start":
        return f"{icon} {g.home.short} – {g.away.short} har börjat ({league})"
    if kind == "final":
        return f"{icon} Slut: {result_text(g)} · {league}"
    goal = "Mål! " if g.league in HOCKEY or CATALOG[g.league].espn.startswith("soccer") else "Ny ställning: "
    return f"{icon} {goal}{g.home.short} {g.home.score or 0}–{g.away.score or 0} {g.away.short}" + (f" · {g.status}" if g.status else "")


# ----------------------------------------------------------------------
# SHL live scores from API-Sports (optional, needs API_SPORTS_KEY)
# ----------------------------------------------------------------------

APISPORTS_STATUS = {  # short code -> (state, Swedish status)
    "NS": ("pre", ""), "P1": ("in", "P1"), "P2": ("in", "P2"), "P3": ("in", "P3"), "OT": ("in", "ÖT"),
    "PT": ("in", "Straffar"), "BT": ("in", "Paus"), "FT": ("post", "Slut"), "AOT": ("post", "Slut (ÖT)"),
    "AP": ("post", "Slut (str)"), "AW": ("post", "Slut"),
}
GENERIC_WORDS = {"if", "ik", "hc", "bk", "hf", "hk", "aik", "sk", "ff", "fc"}


def team_key(name: str) -> str:
    """Comparable key for one SHL team across providers: first real word, folded, 5 letters."""
    words = [w for w in re.split(r"[\s-]+", str(name or "")) if fold(w) and fold(w) not in GENERIC_WORDS]
    return fold(words[0])[:5] if words else fold(name)[:5]


class ShlLive:
    """Polls API-Sports for today's SHL games while one is on and lays the live score over the games."""

    def __init__(self, key: str, client: httpx.Client, cache_file: Path = APISPORTS_CACHE) -> None:
        self._key = key
        self._client = client
        self._cache_file = Path(cache_file)
        self._last = 0.0
        self._latest: dict[str, dict[str, Any]] = {}
        self._day = ""
        self._used = 0
        self._off_until = ""          # local date - after a plan/quota error
        self.note = ""

    @staticmethod
    def window(result: Optional[LeagueResult]) -> bool:
        """True while an SHL game could be on (5 min before the start until 4 h after)."""
        if result is None:
            return False
        now = datetime.now(timezone.utc)
        return any(g.state != "post" and _parse_utc(g.start) - timedelta(minutes=5) <= now <= _parse_utc(g.start) + timedelta(hours=4)
                   for g in result.games)

    def overlay(self, games: list[Game]) -> None:
        self._apply_all(games)                       # what we already know (polls are 2 min apart)
        if self.window(LeagueResult("shl", "SHL", "", games)) and time.monotonic() - self._last >= SHL_POLL_SECONDS:
            self._poll()
            self._apply_all(games)

    def _apply_all(self, games: list[Game]) -> None:
        for g in games:
            found = self._latest.get(team_key(g.home.name))
            if found and str(found.get("date", ""))[:10] == g.start[:10] or found and abs(
                    (_parse_utc(str(found.get("date"))) - _parse_utc(g.start)).total_seconds()) < 6 * 3600:
                self._apply(g, found)

    def _poll(self) -> None:
        today = datetime.now().date().isoformat()
        if self._day != today:
            self._day, self._used = today, 0
        if self._off_until and self._off_until >= today:
            return
        if self._used >= APISPORTS_DAILY_MAX:
            self.note = "Dagens kvot för SHL live är slut – resultaten kommer efter matcherna."
            return
        self._last = time.monotonic()
        try:
            league_id, season = self._league()
            data = self._get("/games", {"league": str(league_id), "season": str(season), "date": today, "timezone": "Europe/Stockholm"})
        except Exception as exc:
            logger.warning("SHL live (API-Sports) failed: %s", exc)
            return
        self._latest = {}
        for item in data.get("response") or []:
            try:
                self._latest[team_key(item["teams"]["home"]["name"])] = item
            except (KeyError, TypeError):
                continue
        self.note = ""

    def _apply(self, game: Game, item: dict[str, Any]) -> None:
        code = str((item.get("status") or {}).get("short") or "").upper()
        if code not in APISPORTS_STATUS:
            return
        state, status = APISPORTS_STATUS[code]
        scores = item.get("scores") or {}
        hs, as_ = scores.get("home"), scores.get("away")
        if state != "pre" and (hs is None or as_ is None):
            return
        game.state, game.status = state, status
        game.home.score = None if state == "pre" else str(int(hs))
        game.away.score = None if state == "pre" else str(int(as_))
        game.home.winner = state == "post" and int(hs) > int(as_)
        game.away.winner = state == "post" and int(as_) > int(hs)

    def _league(self) -> tuple[int, int]:
        """SHL's league id and current season at API-Sports, looked up once a month and cached."""
        try:
            cached = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if cached.get("checked", "") >= (datetime.now().date() - timedelta(days=30)).isoformat():
                return int(cached["league"]), int(cached["season"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        data = self._get("/leagues", {"country": "Sweden"})
        for item in data.get("response") or []:
            if str(item.get("name", "")).strip().upper() == "SHL":
                seasons = item.get("seasons") or []
                current = next((s for s in seasons if s.get("current")), seasons[-1] if seasons else {})
                league_id, season = int(item["id"]), int(current.get("season"))
                self._cache_file.parent.mkdir(parents=True, exist_ok=True)
                self._cache_file.write_text(json.dumps({"league": league_id, "season": season,
                                                        "checked": datetime.now().date().isoformat()}), encoding="utf-8")
                return league_id, season
        raise ValueError("SHL not found at API-Sports")

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        self._used += 1
        url = f"https://{APISPORTS_HOST}{path}"
        with self._client.stream("GET", url, params=params, headers={"x-apisports-key": self._key}) as response:
            response.raise_for_status()
            remaining = response.headers.get("x-ratelimit-requests-remaining")
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_JSON_BYTES:
                    raise ValueError("response too large")
        data = httpx.Response(200, content=body).json()
        data = data if isinstance(data, dict) else {}
        errors = data.get("errors")
        if errors:   # e.g. {"plan": "Free plans do not have access to this season"} or a bad key
            message = "; ".join(f"{v}" for v in (errors.values() if isinstance(errors, dict) else errors))[:200]
            self._off_until = datetime.now().date().isoformat()
            self.note = f"SHL live är avstängt idag: {message}"
            logger.warning("API-Sports refused the request: %s", message)
            raise ValueError(message)
        if remaining is not None and remaining.isdigit() and int(remaining) < 3:
            self._off_until = datetime.now().date().isoformat()
        return data
