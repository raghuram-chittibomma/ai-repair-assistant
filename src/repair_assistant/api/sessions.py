"""In-memory multi-turn diagnose sessions (not durable across restarts)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.diagnostic.session import DiagnosticSession
from repair_assistant.safety.models import Audience

DEFAULT_SESSION_TTL_SECONDS = 3600
DEFAULT_SESSION_MAX = 32


@dataclass
class _Entry:
    session: DiagnosticSession
    last_access: float


class SessionStore:
    """Volatile diagnose sessions with TTL and max-size eviction (Phase 10 / 1A)."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        max_sessions: int = DEFAULT_SESSION_MAX,
    ) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _Entry] = {}
        self._ttl_seconds = max(0, int(ttl_seconds))
        self._max_sessions = max(1, int(max_sessions))

    def get_or_create(
        self,
        session_id: str | None,
        *,
        manifest: Manifest,
        appliance: Appliance,
        audience: Audience,
        retrieval_limit: int,
        overfetch: int,
    ) -> tuple[str, DiagnosticSession]:
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            if session_id:
                entry = self._sessions.get(session_id)
                if entry is None:
                    raise KeyError(session_id)
                entry.last_access = now
                return session_id, entry.session

            sid = str(uuid.uuid4())
            while len(self._sessions) >= self._max_sessions:
                self._evict_oldest_locked()
            session = DiagnosticSession(
                manifest,
                appliance=appliance,
                audience=audience,
                retrieval_limit=retrieval_limit,
                overfetch=overfetch,
                session_id=sid,
            )
            self._sessions[sid] = _Entry(session=session, last_access=now)
            return sid, session

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
