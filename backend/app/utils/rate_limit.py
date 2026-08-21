"""Demo-grade in-memory per-session rate limiter."""

from __future__ import annotations

import threading
import time
from collections import deque

from app.exceptions import RateLimitExceededError

DEFAULT_MAX_MESSAGES = 20
DEFAULT_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Sliding-window limiter: at most `max_events` per `window_seconds` per key."""

    def __init__(
        self,
        max_events: int = DEFAULT_MAX_MESSAGES,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            queue = self._events.setdefault(key, deque())
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self.max_events:
                raise RateLimitExceededError()
            queue.append(now)
