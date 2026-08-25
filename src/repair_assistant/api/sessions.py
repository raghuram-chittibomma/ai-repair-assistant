"""In-memory multi-turn diagnose sessions (not durable across restarts)."""

from __future__ import annotations

import threading
import uuid

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.diagnostic.session import DiagnosticSession
from repair_assistant.safety.models import Audience


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, DiagnosticSession] = {}

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
        with self._lock:
            if session_id and session_id in self._sessions:
                return session_id, self._sessions[session_id]
            sid = session_id or str(uuid.uuid4())
            session = DiagnosticSession(
                manifest,
                appliance=appliance,
                audience=audience,
                retrieval_limit=retrieval_limit,
                overfetch=overfetch,
            )
            self._sessions[sid] = session
            return sid, session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)
