"""Thread-safe in-memory session store with lazy TTL expiry."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config import get_settings
from app.exceptions import SessionExpiredError, SessionNotFoundError
from app.memory.schemas import SessionMemory

NowFn = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    """Dict-backed store. Full merge/conflict rules arrive in Stage 05."""

    def __init__(
        self,
        ttl_minutes: int | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        settings = get_settings()
        self._ttl = timedelta(minutes=ttl_minutes or settings.session_ttl_minutes)
        self._now = now_fn or _utc_now
        self._sessions: dict[str, SessionMemory] = {}
        self._expired_ids: set[str] = set()
        self._lock = threading.RLock()

    def create(self, channel: str) -> SessionMemory:
        self._sweep()
        now = self._now()
        session = SessionMemory(
            session_id=str(uuid.uuid4()),
            channel=channel,
            created_at=now,
            last_active_at=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str, *, touch: bool = True) -> SessionMemory:
        self._sweep()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                if session_id in self._expired_ids:
                    raise SessionExpiredError()
                raise SessionNotFoundError()
            if self._is_expired(session):
                self._mark_expired(session_id)
                raise SessionExpiredError()
            if touch:
                session.last_active_at = self._now()
            return session

    def save(self, session: SessionMemory) -> None:
        with self._lock:
            session.last_active_at = self._now()
            self._sessions[session.session_id] = session
            self._expired_ids.discard(session.session_id)

    def _is_expired(self, session: SessionMemory) -> bool:
        return self._now() - session.last_active_at > self._ttl

    def _mark_expired(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._expired_ids.add(session_id)

    def _sweep(self) -> None:
        with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for session_id in expired:
                self._mark_expired(session_id)
