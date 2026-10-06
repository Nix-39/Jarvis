"""
Event bus - a live feed of what Jarvis is doing.

Every component can publish small events ("routed to business_agent",
"web search: elpris SE3", "reminder delivered"). The Jarvis Core exposes them
through its local API, so a visual interface can show the second brain at work
in real time - including background work nobody asked for.

Design:
    - In-process, thread-safe, never raises (observability must not break Jarvis).
    - Keeps the most recent events in memory for late joiners.
    - Each subscriber gets its own bounded queue; a slow subscriber loses its
      oldest events instead of blocking publishers.

Usage:
    from core.events import event_bus
    event_bus.publish("websearch.query", "web_search", "Söker: elpris SE3", query="elpris SE3")
"""

from __future__ import annotations

import itertools
import queue
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class Event:
    id: int
    ts: str
    type: str          # e.g. "query.received", "agent.selected", "reminder.delivered"
    source: str        # component, e.g. "orchestrator", "web_search", "telegram"
    message: str       # short human-readable description (Swedish)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    def __init__(self, history_size: int = 500, subscriber_queue_size: int = 1000) -> None:
        self._lock = threading.Lock()
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: list[queue.Queue] = []
        self._ids = itertools.count(1)
        self._queue_size = subscriber_queue_size

    def publish(self, type: str, source: str, message: str, **data: Any) -> Optional[Event]:
        """Record an event and fan it out to subscribers. Never raises."""
        try:
            event = Event(
                id=next(self._ids),
                ts=datetime.now(timezone.utc).isoformat(),
                type=type,
                source=source,
                message=message[:500],
                data=data,
            )
            with self._lock:
                self._history.append(event)
                subscribers = list(self._subscribers)
            for subscriber in subscribers:
                self._offer(subscriber, event)
            return event
        except Exception:
            return None

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def recent(self, after_id: int = 0, limit: int = 200) -> list[Event]:
        with self._lock:
            events = [event for event in self._history if event.id > after_id]
        return events[-limit:]

    @staticmethod
    def _offer(subscriber: queue.Queue, event: Event) -> None:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()  # drop the oldest
                subscriber.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass


# One bus per process.
event_bus = EventBus()
