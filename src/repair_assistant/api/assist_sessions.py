"""In-memory corpus assist sessions (ADR-0053).

Volatile across API restarts — same pattern as diagnose SessionStore.
Scoped to curation of overview / facts / questions for one doc version.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_ASSIST_TTL_SECONDS = 3600
DEFAULT_ASSIST_MAX_SESSIONS = 32
DEFAULT_ASSIST_MAX_TURNS = 40


@dataclass
class AssistTurn:
    role: str  # user | assistant
    content: str
    unit_key: str = ""
    suggestions: dict[str, Any] | None = None


@dataclass
class AssistSession:
    session_id: str
    doc_id: str
    version: int
    unit_key: str | None = None
    turns: list[AssistTurn] = field(default_factory=list)

    def append(self, turn: AssistTurn) -> None:
        self.turns.append(turn)
        if len(self.turns) > DEFAULT_ASSIST_MAX_TURNS * 2:
            self.turns = self.turns[-(DEFAULT_ASSIST_MAX_TURNS * 2) :]


@dataclass
class _Entry:
    session: AssistSession
    last_access: float


class AssistSessionStore:
    """Volatile assist sessions with TTL and max-size eviction."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_ASSIST_TTL_SECONDS,
        max_sessions: int = DEFAULT_ASSIST_MAX_SESSIONS,
    ) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _Entry] = {}
        self._ttl_seconds = max(0, int(ttl_seconds))
        self._max_sessions = max(1, int(max_sessions))

    def create(
        self,
        *,
        doc_id: str,
        version: int,
        unit_key: str | None = None,
    ) -> AssistSession:
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            while len(self._sessions) >= self._max_sessions:
                self._evict_oldest_locked()
            sid = str(uuid.uuid4())
            session = AssistSession(
                session_id=sid,
                doc_id=doc_id,
                version=version,
                unit_key=unit_key,
            )
            self._sessions[sid] = _Entry(session=session, last_access=now)
            return session

    def get(self, session_id: str) -> AssistSession:
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            entry = self._sessions.get(session_id)
            if entry is None:
                raise KeyError(session_id)
            entry.last_access = now
            return entry.session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            self._evict_locked(time.monotonic())
            return len(self._sessions)

    def _evict_locked(self, now: float) -> None:
        if self._ttl_seconds <= 0:
            return
        expired = [
            sid
            for sid, entry in self._sessions.items()
            if now - entry.last_access > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    def _evict_oldest_locked(self) -> None:
        if not self._sessions:
            return
        oldest = min(self._sessions.items(), key=lambda item: item[1].last_access)
        del self._sessions[oldest[0]]
