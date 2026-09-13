from __future__ import annotations

import queue
import threading
from typing import Any


class WebEventBroker:
    """Small in-process fan-out broker for browser refresh signals.

    Events are intentionally tiny notifications. REST remains authoritative for
    measurements and other application state. Each subscriber has a bounded
    queue so a slow/disconnected browser cannot grow server memory.
    """

    def __init__(self, max_queue: int = 32) -> None:
        self.max_queue = max(1, int(max_queue))
        self._subscribers: set[queue.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self.max_queue)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        with self._lock:
            targets = tuple(self._subscribers)

        for target in targets:
            if target.full():
                try:
                    target.get_nowait()
                except queue.Empty:
                    pass
            try:
                target.put_nowait(payload)
            except queue.Full:
                # Another producer may have filled the queue between the two
                # operations. Dropping one refresh signal is safe because the
                # browser refetches authoritative state from REST.
                pass
