"""
UiSettingsService - personal settings for the desktop interface.

Stored as JSON in data/ui/settings.json (private, gitignored): display names
(system, orchestrator, agents), family members and their colours, background
image tuning, sound levels and small UI preferences. Everything is validated,
so a hand-edited file with a typo falls back to defaults instead of breaking
the interface.

Images (background, profile photos) live next to it in data/ui/ and are
validated by their magic bytes - only PNG, JPEG and WebP are accepted.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from core.config import Config
from core.logger import get_logger

logger = get_logger(__name__)

SETTINGS_FILE = "settings.json"
ID_PATTERN = r"^[a-z0-9_]{1,24}$"
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": ("png", "image/png"), b"\xff\xd8\xff": ("jpg", "image/jpeg")}
MAX_BACKGROUND_BYTES = 15 * 1024 * 1024
MAX_PHOTO_BYTES = 8 * 1024 * 1024

# Agent id -> (default display name, icon). Order = order in the agent row.
DEFAULT_AGENTS: dict[str, tuple[str, str]] = {
    "general_agent": ("Allmänt", "general"),
    "education_agent": ("Utbildning", "education"),
    "career_agent": ("Karriär", "career"),
    "business_agent": ("Business", "business"),
    "webdeveloper_agent": ("Webbdesign", "webdev"),
    "socialmediamanager_agent": ("Sociala medier", "social"),
    "contentcreator_agent": ("Content", "content"),
}


class Person(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=30)
    color: str = Field(pattern=COLOR_PATTERN)
    full_name: str = Field("", max_length=60)   # used e.g. in referee crews ("AD1: Förnamn Efternamn")


class Background(BaseModel):
    strength: int = Field(24, ge=0, le=100)
    size: int = Field(99, ge=60, le=160)
    x: int = Field(-6, ge=-40, le=40)
    y: int = Field(-6, ge=-40, le=40)
    dim: int = Field(29, ge=0, le=90)
    edge_width: int = Field(14, ge=2, le=45)
    edge_strength: int = Field(100, ge=0, le=100)


class Sound(BaseModel):
    master_mute: bool = False
    levels: dict[str, int] = Field(default_factory=lambda: {"voice": 80, "reply": 40, "reminder": 70, "mail": 30, "fx": 0})
    muted: dict[str, bool] = Field(default_factory=dict)

    @field_validator("levels")
    @classmethod
    def _clamp(cls, value: dict[str, int]) -> dict[str, int]:
        return {k[:20]: max(0, min(100, int(v))) for k, v in list(value.items())[:20]}


class UiSettings(BaseModel):
    system_name: str = Field("Yggdrasil", min_length=1, max_length=30)
    orchestrator_name: str = Field("Oden", min_length=1, max_length=30)
    planner_name: str = Field("Planering", min_length=1, max_length=30)
    agent_order: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENTS))
    agent_names: dict[str, str] = Field(default_factory=dict)   # overrides, e.g. Norse names
    people: list[Person] = Field(default_factory=lambda: [
        Person(id="nix", name="Nix", color="#f0b43c"),
        Person(id="natta", name="Natta", color="#b98cff"),
        Person(id="julian", name="Julian", color="#6fb8ff"),
        Person(id="james", name="James", color="#7fdc8a"),
        Person(id="neo", name="Neo", color="#ff6b6b"),
    ])
    background: Background = Field(default_factory=Background)
    sound: Sound = Field(default_factory=Sound)
    show_steps: bool = True

    @field_validator("people")
    @classmethod
    def _unique_people(cls, value: list[Person]) -> list[Person]:
        ids = [p.id for p in value]
        if len(ids) != len(set(ids)) or len(ids) > 12:
            raise ValueError("people must have unique ids (max 12)")
        return value


class UiSettingsService:
    def __init__(self, directory: Path = Config.UI_DATA_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "people").mkdir(exist_ok=True)
        self._path = self.dir / SETTINGS_FILE
        self._lock = threading.Lock()
        self._settings = self._load()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get(self) -> UiSettings:
        return self._settings

    def update(self, patch: dict[str, Any]) -> UiSettings:
        """Merge a partial update, validate the result and save it."""
        with self._lock:
            merged = _deep_merge(self._settings.model_dump(), patch)
            settings = UiSettings.model_validate(merged)   # raises ValidationError on bad input
            self._settings = settings
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            return settings

    def agents(self, registered: list[str]) -> list[dict[str, str]]:
        """Agents for the agent row, in display order, with display names and icons."""
        s = self._settings
        order = [a for a in s.agent_order if a in registered and a in DEFAULT_AGENTS]
        order += [a for a in DEFAULT_AGENTS if a in registered and a not in order]
        return [{"id": a, "name": s.agent_names.get(a, DEFAULT_AGENTS[a][0]), "icon": DEFAULT_AGENTS[a][1]} for a in order]

    def person_for(self, category: str, text: str = "") -> str:
        """Which family member a reminder belongs to (category or text naming a person)."""
        people = self._settings.people
        haystack = f"{category} {text}".lower()
        for person in people:
            if re.search(rf"\b{re.escape(person.name.lower())}\b", haystack):
                return person.id
        return people[0].id if people else "nix"

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def save_image(self, name: str, data: bytes, max_bytes: int) -> str:
        """Validate and store an image as data/ui/<name>.<ext>. Returns the file name."""
        if len(data) > max_bytes:
            raise ValueError(f"Bilden är större än {max_bytes // 2**20} MB.")
        kind = image_kind(data)
        if kind is None:
            raise ValueError("Bara PNG, JPEG och WebP stöds.")
        self.delete_image(name)
        target = self.dir / f"{name}.{kind[0]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target.name

    def find_image(self, name: str) -> Optional[tuple[Path, str]]:
        for ext, media in (("png", "image/png"), ("jpg", "image/jpeg"), ("webp", "image/webp")):
            path = self.dir / f"{name}.{ext}"
            if path.is_file():
                return path, media
        return None

    def delete_image(self, name: str) -> None:
        for ext in ("png", "jpg", "webp"):
            (self.dir / f"{name}.{ext}").unlink(missing_ok=True)

    # ------------------------------------------------------------------

    def _load(self) -> UiSettings:
        if not self._path.exists():
            return UiSettings()
        try:
            return UiSettings.model_validate(json.loads(self._path.read_text(encoding="utf-8")))
        except (ValidationError, ValueError) as exc:
            logger.warning("Invalid %s, using defaults: %s", self._path.name, str(exc)[:300])
            return UiSettings()


def image_kind(data: bytes) -> Optional[tuple[str, str]]:
    for magic, kind in IMAGE_TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key not in ("agent_names",):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
