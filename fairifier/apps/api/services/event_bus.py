"""In-process event bus for SSE streaming."""

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class WorkflowEvent:
    """A single event in the SSE stream."""

    event_type: str  # log | progress | stage_change | completed | error
    project_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse(self) -> str:
        payload = json.dumps(
            asdict(self), ensure_ascii=False
        )
        return f"event: {self.event_type}\ndata: {payload}\n\n"


@dataclass
class _Subscriber:
    """Async queue bound to the event loop that owns it."""

    queue: asyncio.Queue[WorkflowEvent]
    loop: asyncio.AbstractEventLoop


class EventBus:
    """Fan-out event bus.

    Producers call ``publish()``, consumers iterate
    via ``subscribe()``.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[_Subscriber]] = {}
        self._history: Dict[str, Deque[WorkflowEvent]] = defaultdict(
            lambda: deque(maxlen=100)
        )
        self._lock = threading.Lock()

    def subscribe(
        self, project_id: str
    ) -> asyncio.Queue[WorkflowEvent]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[WorkflowEvent] = asyncio.Queue()
        subscriber = _Subscriber(queue=q, loop=loop)
        with self._lock:
            self._subscribers.setdefault(
                project_id, []
            ).append(subscriber)
            history = list(self._history.get(project_id, ()))
        for event in history:
            q.put_nowait(event)
        return q

    def unsubscribe(
        self,
        project_id: str,
        q: asyncio.Queue[WorkflowEvent],
    ) -> None:
        with self._lock:
            subs = self._subscribers.get(project_id, [])
            self._subscribers[project_id] = [
                sub for sub in subs if sub.queue is not q
            ]
            if not self._subscribers[project_id]:
                self._subscribers.pop(project_id, None)

    async def publish(
        self, event: WorkflowEvent
    ) -> None:
        with self._lock:
            self._history[event.project_id].append(event)
            subscribers = list(
                self._subscribers.get(event.project_id, [])
            )
        for sub in subscribers:
            await sub.queue.put(event)

    def publish_sync(
        self, event: WorkflowEvent
    ) -> None:
        """Thread-safe publish from synchronous code."""
        with self._lock:
            self._history[event.project_id].append(event)
            subscribers = list(
                self._subscribers.get(event.project_id, [])
            )
        for sub in subscribers:
            try:
                sub.loop.call_soon_threadsafe(
                    sub.queue.put_nowait, event
                )
            except (RuntimeError, asyncio.QueueFull):
                logger.warning(
                    "SSE queue full for %s"
                    " -- dropping event",
                    event.project_id,
                )


event_bus = EventBus()
