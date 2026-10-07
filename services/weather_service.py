"""
WeatherService - the weather at home from SMHI's open data.

Source: SMHI's point forecast API SNOW1gv1 (replaced PMP3gv2 in 2026):
    https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/<lon>/lat/<lat>/data.json
Hourly steps for the first ~3 days, then 6/12-hour steps out to 10 days. No key.

A background thread in Jarvis Core fetches the forecast every 30 minutes and
turns it into what the interface shows: the weather now, a rain alert for the
next 12 hours, an hourly strip for the next 24 hours and five days. The place
is a personal setting (data/ui/settings.json: weather.name/lat/lon), default
Gunnilse in Göteborg.

The response is untrusted input: fixed host, timeout, size cap, numbers are
range-checked before use.
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx

from core.events import event_bus
from core.logger import get_logger

logger = get_logger(__name__)

API = "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon}/lat/{lat}/data.json"
REFRESH_SECONDS = 1800
RETRY_SECONDS = 300
MAX_BYTES = 3 * 1024 * 1024
RAIN_MM = 0.2                 # mm in an hour that counts as rain
MISSING = 9999

# SMHI weather symbols 1-27 -> (Swedish text, icon key used by the interface)
SYMBOLS: dict[int, tuple[str, str]] = {
    1: ("Klart", "sun"), 2: ("Lätt molnighet", "sun"), 3: ("Halvklart", "part"), 4: ("Molnigt", "part"),
    5: ("Mycket moln", "cloud"), 6: ("Mulet", "cloud"), 7: ("Dimma", "fog"),
    8: ("Lätta regnskurar", "rain"), 9: ("Regnskurar", "rain"), 10: ("Kraftiga regnskurar", "rain"),
    11: ("Åskskurar", "thunder"), 12: ("Lätta skurar av snöblandat regn", "sleet"), 13: ("Skurar av snöblandat regn", "sleet"),
    14: ("Kraftiga skurar av snöblandat regn", "sleet"), 15: ("Lätta snöbyar", "snow"), 16: ("Snöbyar", "snow"),
    17: ("Kraftiga snöbyar", "snow"), 18: ("Lätt regn", "rain"), 19: ("Regn", "rain"), 20: ("Kraftigt regn", "rain"),
    21: ("Åska", "thunder"), 22: ("Lätt snöblandat regn", "sleet"), 23: ("Snöblandat regn", "sleet"),
    24: ("Kraftigt snöblandat regn", "sleet"), 25: ("Lätt snöfall", "snow"), 26: ("Snöfall", "snow"), 27: ("Kraftigt snöfall", "snow"),
}
COMPASS = ("N", "NO", "O", "SO", "S", "SV", "V", "NV")
WEEKDAYS = ("Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön")


class WeatherService:
    def __init__(self, place_provider: Callable[[], dict[str, Any]], client: Optional[httpx.Client] = None) -> None:
        self.place_provider = place_provider
        self._client = client or httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "Yggdrasil/1.0"})
        self._lock = threading.Lock()
        self._data: Optional[dict[str, Any]] = None
        self._error: Optional[str] = None
        self._wake = threading.Event()

    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._data is None:
                return {"ok": False, "error": self._error or "Väderdata hämtas…", "place": self.place_provider().get("name", "")}
            return {"ok": True, **self._data, "error": self._error}

    def refresh(self) -> None:
        place = self.place_provider()
        lat, lon = float(place["lat"]), float(place["lon"])
        url = API.format(lon=f"{lon:.4f}".rstrip("0").rstrip("."), lat=f"{lat:.4f}".rstrip("0").rstrip("."))
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ValueError("response too large")
        data = summarize(httpx.Response(200, content=body).json(), place.get("name", ""))
        with self._lock:
            changed = self._data is None or self._data.get("now") != data.get("now") or self._data.get("alert") != data.get("alert")
            self._data, self._error = data, None
        if changed:
            event_bus.publish("weather.updated", "weather", f"Vädret i {data['place']}: {data['now']['temp']}°, {data['now']['text'].lower()}")

    def wake(self) -> None:
        self._wake.set()

    def run_forever(self, stop: threading.Event) -> None:
        if stop.wait(5):
            return
        while not stop.is_set():
            wait = REFRESH_SECONDS
            try:
                self.refresh()
            except Exception as exc:
                logger.warning("Weather refresh failed: %s", exc)
                with self._lock:
                    self._error = "Kunde inte hämta vädret från SMHI just nu."
                wait = RETRY_SECONDS
            self._wake.clear()
            deadline = datetime.now() + timedelta(seconds=wait)
            while datetime.now() < deadline:
                if stop.wait(2):
                    return
                if self._wake.is_set():
                    break


# ----------------------------------------------------------------------
# Turning the SMHI forecast into what the interface shows
# ----------------------------------------------------------------------

def _num(data: dict[str, Any], key: str, low: float, high: float) -> Optional[float]:
    try:
        value = float(data.get(key))
    except (TypeError, ValueError):
        return None
    return value if value != MISSING and low <= value <= high else None


def _point(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = item.get("data") or {}
    try:
        time = datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
        start = datetime.fromisoformat(str(item.get("intervalParametersStartTime") or item["time"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    temp = _num(data, "air_temperature", -60, 60)
    if temp is None:
        return None
    symbol = int(_num(data, "symbol_code", 1, 27) or 0)
    return {
        "time": time, "hours": max(1.0, (time - start).total_seconds() / 3600),
        "temp": temp, "symbol": symbol,
        "wind": _num(data, "wind_speed", 0, 80) or 0.0, "gust": _num(data, "wind_speed_of_gust", 0, 100),
        "dir": _num(data, "wind_from_direction", 0, 360),
        "rain": _num(data, "precipitation_amount_mean", 0, 500) or 0.0,
        "rain_max": _num(data, "precipitation_amount_max", 0, 500) or 0.0,
        "rain_prob": _num(data, "probability_of_precipitation", 0, 100) or 0.0,
    }


def feels_like(temp: float, wind: float) -> float:
    """SMHI's wind chill (effektiv temperatur) for cold, windy weather; otherwise the temperature."""
    if temp > 10 or wind < 2:
        return temp
    v = wind * 3.6
    return 13.12 + 0.6215 * temp - 11.37 * v ** 0.16 + 0.3965 * temp * v ** 0.16


def compass(degrees: Optional[float]) -> str:
    return "" if degrees is None else COMPASS[int((degrees + 22.5) // 45) % 8]


def icon(symbol: int, moment: datetime) -> str:
    key = SYMBOLS.get(symbol, ("", "cloud"))[1]
    local_hour = moment.astimezone().hour
    if key in ("sun", "part") and (local_hour >= 20 or local_hour < 6):
        return "moon" if key == "sun" else "moonpart"
    return key


def summarize(raw: dict[str, Any], place: str) -> dict[str, Any]:
    points = [p for p in (_point(i) for i in raw.get("timeSeries") or []) if p]
    if not points:
        raise ValueError("no forecast points")
    now_utc = datetime.now(timezone.utc)
    points = [p for p in points if p["time"] >= now_utc - timedelta(minutes=59)] or points[-1:]
    cur = points[0]
    hourly = [p for p in points if p["hours"] <= 1.01][:24]

    now = {
        "temp": round(cur["temp"]), "feels": round(feels_like(cur["temp"], cur["wind"])),
        "text": SYMBOLS.get(cur["symbol"], ("–", ""))[0], "icon": icon(cur["symbol"], cur["time"]),
        "wind": round(cur["wind"]), "gust": round(cur["gust"]) if cur["gust"] is not None else None, "dir": compass(cur["dir"]),
    }
    hours = [{
        "time": (p["time"] - timedelta(hours=1)).isoformat(),   # label = start of the hour the values cover
        "temp": round(p["temp"]), "icon": icon(p["symbol"], p["time"]),
        "text": SYMBOLS.get(p["symbol"], ("", ""))[0], "rain": round(p["rain"], 1),
    } for p in hourly]
    return {
        "place": place, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "approved": str(raw.get("referenceTime") or raw.get("approvedTime") or ""),
        "now": now, "alert": rain_alert(hourly[:12]), "hours": hours, "days": days(points),
    }


def rain_alert(hours: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """'Regn från ca 15:00 till 18:00, totalt ca 6 mm' for the next 12 hours (None if dry)."""
    wet = [p for p in hours if p["rain"] >= RAIN_MM]
    if not wet:
        return None
    first = wet[0]
    end = first
    for p in hours[hours.index(first):]:
        if p["rain"] < RAIN_MM:
            break
        end = p
    total = sum(p["rain"] for p in hours[hours.index(first):hours.index(end) + 1])
    kind = SYMBOLS.get(first["symbol"], ("", "rain"))[1]
    word = {"snow": "Snö", "sleet": "Snöblandat regn", "thunder": "Åskregn"}.get(kind, "Regn")
    start_local = (first["time"] - timedelta(hours=1)).astimezone()     # the hour *ending* at time
    end_local = end["time"].astimezone()
    starts_now = first is hours[0]
    return {
        "kind": kind, "starts_now": starts_now,
        "start": start_local.strftime("%H:%M"), "end": end_local.strftime("%H:%M"), "mm": round(total, 1),
        "text": (f"{word} nu, uppehåll ca {end_local:%H:%M}" if starts_now else f"{word} från ca {start_local:%H:%M} till {end_local:%H:%M}")
                + (f" · totalt ca {total:.0f} mm" if total >= 1 else ""),
        "badge": f"{word.split()[0].lower()} {'nu' if starts_now else start_local.strftime('%H:%M')}",
    }


def days(points: list[dict[str, Any]], count: int = 5) -> list[dict[str, Any]]:
    by_day: dict[Any, list[dict[str, Any]]] = {}
    for p in points:
        by_day.setdefault(p["time"].astimezone().date(), []).append(p)
    today = datetime.now().astimezone().date()
    out = []
    for day in sorted(by_day)[:count]:
        items = by_day[day]
        daytime = [p for p in items if 9 <= p["time"].astimezone().hour <= 18] or items
        symbol = Counter(p["symbol"] for p in daytime).most_common(1)[0][0]
        noonish = min(daytime, key=lambda p: abs(p["time"].astimezone().hour - 13))
        rain = sum(p["rain"] for p in items if p["hours"] <= 1.01)   # hourly part only - later steps are coarse
        wet = any(p["rain"] >= RAIN_MM or p["rain_prob"] >= 60 for p in items)
        wind = max(p["wind"] for p in items)
        out.append({
            "date": day.isoformat(),
            "label": "Idag" if day == today else "Imorgon" if day == today + timedelta(days=1) else WEEKDAYS[day.weekday()],
            "min": round(min(p["temp"] for p in items)), "max": round(max(p["temp"] for p in items)),
            "icon": icon(symbol, noonish["time"]), "text": SYMBOLS.get(symbol, ("", ""))[0],
            "note": ("Blåsigt" if wind >= 10 else "") or (f"{rain:.0f} mm" if rain >= 1 else "Regn" if wet else ""),
        })
    return out
