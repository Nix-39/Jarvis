"""
ReminderAgent - creates, lists and cancels reminders through natural language,
always with an explicit confirmation step before anything is saved or removed.

Flow:
    1. The LLM turns the message into ONE structured action (JSON).
    2. Python validates it and proposes it to the user
       ("Ska jag lägga in den? ja/nej, eller säg vad som ska ändras").
    3. The proposal is stored as pending state (`reminder_agent.pending`).
       The Orchestrator routes short replies ("ja", "nej", "kl 11 istället")
       back here while a proposal is pending.
    4. "ja" executes, "nej" discards, anything else is treated as a correction.

The LLM never writes to the database - only validated Python code does.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.clock import current_datetime_text, format_datetime_sv
from core.logger import get_logger
from services.memory_service import (
    DEFAULT_CONTEXT_LIMIT,
    DEFAULT_SESSION_ID,
    MemoryService,
    format_conversation_history,
)
from services.ollama_service import OllamaService
from services.prompt_loader import PromptLoader
from services.reminder_service import (
    RECURRENCE_LABELS,
    RECURRENCES,
    Reminder,
    ReminderService,
    ReminderServiceError,
)

logger = get_logger(__name__)

PENDING_TTL = timedelta(minutes=15)
YES_PATTERN = re.compile(
    r"^\s*(ja|japp|jajamän|jo|jepp|ok|okej|okey|kör|gör det|stämmer|korrekt|precis|absolut|visst|perfekt|yes)\b",
    re.IGNORECASE,
)
NO_PATTERN = re.compile(
    r"^\s*(nej|nä|nää|nope|avbryt|stopp|glöm det|strunta i det|no)[\s.!]*$",
    re.IGNORECASE,
)


class ReminderAgent:
    """Natural-language reminder management with confirmation."""

    AGENT_ID: str = "reminder_agent"
    PENDING_KEY: str = "reminder_agent.pending"

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        reminder_service: Optional[ReminderService] = None,
        ollama_service: Optional[OllamaService] = None,
    ):
        self.llm = ollama_service or OllamaService()
        self.prompt_loader = PromptLoader()
        self.memory = memory_service or MemoryService()
        self.reminders = reminder_service or ReminderService()
        self.system_prompt = self.prompt_loader.load("reminder_agent.txt")
        logger.info("ReminderAgent initialized successfully.")

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        logger.info("ReminderAgent received action '%s'", action)

        user_message = payload.get("message", "").strip()
        if not user_message:
            return "ReminderAgent received an empty message."

        history = self.memory.get_session_messages(
            session_id=DEFAULT_SESSION_ID, agent_id=self.AGENT_ID, limit=DEFAULT_CONTEXT_LIMIT
        )
        self.memory.save_message(DEFAULT_SESSION_ID, role="user", content=user_message, agent_id=self.AGENT_ID)

        try:
            reply = self._respond(user_message, history)
        except Exception as exc:
            logger.error("ReminderAgent failed: %s", exc)
            reply = "Något gick fel när jag hanterade påminnelsen. Försök gärna igen med datum och tid."

        self.memory.save_message(DEFAULT_SESSION_ID, role="agent", content=reply, agent_id=self.AGENT_ID)
        return reply

    # ------------------------------------------------------------------
    # Conversation logic
    # ------------------------------------------------------------------

    def _respond(self, user_message: str, history) -> str:
        pending = self._load_pending()

        if pending and len(user_message.split()) <= 5 and YES_PATTERN.match(user_message):
            self._clear_pending()
            return self._execute(pending)

        if pending and NO_PATTERN.match(user_message):
            self._clear_pending()
            return "Okej, jag lägger inte in något."

        parsed = self._parse(user_message, history, pending)
        kind = parsed.get("action")

        if kind == "list":
            self._clear_pending()
            return self._format_list(self.reminders.list_upcoming())

        if kind == "create":
            return self._propose_create(parsed)

        if kind == "cancel":
            return self._propose_cancel(parsed)

        question = str(parsed.get("question") or "").strip()
        return question or "Vad vill du att jag ska påminna dig om, och när?"

    def _propose_create(self, parsed: Dict[str, Any]) -> str:
        text = " ".join(str(parsed.get("text") or "").split())
        if not text:
            return "Vad vill du bli påmind om?"

        date_text = str(parsed.get("date") or "").strip()
        time_text = str(parsed.get("time") or "").strip()
        assumed_time = bool(parsed.get("assumed_time"))
        if date_text and not time_text:
            time_text, assumed_time = "09:00", True
        try:
            due = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
        except ValueError:
            return f"När vill du bli påmind om \"{text}\"? Ange gärna dag och tid."

        due = due.astimezone()  # interpret as local time
        recurrence = parsed.get("recurrence") if parsed.get("recurrence") in RECURRENCES else "none"
        if recurrence == "none" and due <= datetime.now(timezone.utc):
            return f"{format_datetime_sv(due)} har redan passerat. Vilken tid menar du?"

        category = self._match_category(str(parsed.get("category") or ""))
        pending = {
            "action": "create",
            "text": text,
            "due_local": due.isoformat(),
            "recurrence": recurrence,
            "category": category,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._save_pending(pending)

        lines = ["Jag lägger in den här påminnelsen:", f"• {text}", f"• {format_datetime_sv(due)}"]
        if assumed_time:
            lines[-1] += " (jag antog kl. 09:00 eftersom ingen tid angavs)"
        if recurrence != "none":
            lines.append(f"• Upprepas {RECURRENCE_LABELS[recurrence]}")
        lines.append(f"• Kategori: {category or '–'}")
        lines.append("\nStämmer det? Svara ja eller nej, eller säg vad som ska ändras.")
        return "\n".join(lines)

    def _propose_cancel(self, parsed: Dict[str, Any]) -> str:
        active = {r.id: r for r in self.reminders.list_upcoming(limit=100)}
        ids = [int(i) for i in parsed.get("reminder_ids") or [] if str(i).isdigit() and int(i) in active]
        if not ids:
            return "Jag hittar ingen sådan påminnelse. " + self._format_list(list(active.values()))

        self._save_pending({
            "action": "cancel",
            "ids": ids,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        lines = ["Ska jag ta bort:"] + [f"• {self._describe(active[i])}" for i in ids]
        lines.append("\nSvara ja eller nej.")
        return "\n".join(lines)

    def _execute(self, pending: Dict[str, Any]) -> str:
        if pending.get("action") == "create":
            try:
                reminder = self.reminders.add(
                    text=pending["text"],
                    due=datetime.fromisoformat(pending["due_local"]),
                    recurrence=pending.get("recurrence", "none"),
                    category=pending.get("category", ""),
                )
            except ReminderServiceError as exc:
                return f"Jag kunde inte lägga in påminnelsen: {exc}"
            return f"Klart! Jag påminner dig {self._describe(reminder, with_text=False)}: {reminder.text}."

        if pending.get("action") == "cancel":
            removed = [i for i in pending.get("ids", []) if self.reminders.cancel(i)]
            return "Borttaget." if removed else "Påminnelsen var redan borta."

        return "Det fanns inget att bekräfta."

    # ------------------------------------------------------------------
    # LLM parsing
    # ------------------------------------------------------------------

    def _parse(self, user_message: str, history, pending: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        active = self.reminders.list_upcoming(limit=50)
        active_text = "\n".join(f"id {r.id}: {self._describe(r)}" for r in active) or "(inga)"
        categories = ", ".join(self.reminders.categories()) or "(inga)"
        pending_text = json.dumps(pending, ensure_ascii=False) if pending else "(ingen)"

        prompt = f"""
System Instructions:
{self.system_prompt}

Current date and time: {current_datetime_text()} (ISO: {datetime.now().astimezone():%Y-%m-%d %H:%M})

Available categories: {categories}

Active reminders:
{active_text}

Pending proposal awaiting the user's confirmation:
{pending_text}

Recent conversation:
{format_conversation_history(history)}

User message:
"{user_message}"

JSON:
"""
        raw = self.llm.chat(prompt)
        match = re.search(r"\{.*\}", raw or "", flags=re.DOTALL)
        if not match:
            logger.warning("ReminderAgent got non-JSON output from the model.")
            return {"action": "clarify"}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("ReminderAgent could not parse model JSON.")
            return {"action": "clarify"}
        return data if isinstance(data, dict) else {"action": "clarify"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _match_category(self, candidate: str) -> str:
        wanted = candidate.strip().lower()
        for category in self.reminders.categories():
            if category.lower() == wanted:
                return category
        return ""

    def _format_list(self, reminders: list[Reminder]) -> str:
        if not reminders:
            return "Du har inga aktiva påminnelser."
        return "Dina påminnelser:\n" + "\n".join(f"• {self._describe(r)}" for r in reminders)

    @staticmethod
    def _describe(reminder: Reminder, with_text: bool = True) -> str:
        parts = [format_datetime_sv(reminder.due_at)]
        if reminder.recurrence != "none":
            parts.append(f"({RECURRENCE_LABELS[reminder.recurrence]})")
        if reminder.category:
            parts.append(f"[{reminder.category}]")
        when = " ".join(parts)
        return f"{reminder.text} – {when}" if with_text else when

    def _load_pending(self) -> Optional[Dict[str, Any]]:
        pending = self.memory.get_state(self.PENDING_KEY)
        if not isinstance(pending, dict):
            return None
        try:
            created = datetime.fromisoformat(pending["created"])
        except (KeyError, ValueError):
            return None
        if datetime.now(timezone.utc) - created > PENDING_TTL:
            self._clear_pending()
            return None
        return pending

    def _save_pending(self, pending: Dict[str, Any]) -> None:
        self.memory.set_state(self.PENDING_KEY, pending)

    def _clear_pending(self) -> None:
        self.memory.set_state(self.PENDING_KEY, None)
