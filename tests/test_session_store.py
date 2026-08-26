"""SessionStore TTL / max eviction (Phase 10)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from repair_assistant.api.sessions import SessionStore
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.safety.models import Audience


@pytest.fixture
def store() -> SessionStore:
    return SessionStore(ttl_seconds=1, max_sessions=2)


def _create(store: SessionStore, session_id: str | None = None):
    with patch("repair_assistant.api.sessions.DiagnosticSession") as cls:
        cls.return_value = MagicMock()
        return store.get_or_create(
            session_id,
            manifest=MagicMock(),
            appliance=Appliance(model="WFW5620HW0"),
            audience=Audience.OWNER,
            retrieval_limit=8,
            overfetch=40,
        )


def test_unknown_session_raises(store: SessionStore) -> None:
    with pytest.raises(KeyError):
        _create(store, "missing")


def test_ttl_evicts_idle_session(store: SessionStore) -> None:
    sid, _ = _create(store)
    assert store.count() == 1
    time.sleep(1.1)
    assert store.count() == 0
    with pytest.raises(KeyError):
        _create(store, sid)


def test_max_sessions_evicts_oldest(store: SessionStore) -> None:
    sid1, _ = _create(store)
    time.sleep(0.02)
    sid2, _ = _create(store)
    time.sleep(0.02)
    sid3, _ = _create(store)
    assert store.count() == 2
    with pytest.raises(KeyError):
        _create(store, sid1)
    # newest two remain
    sid2b, _ = _create(store, sid2)
    assert sid2b == sid2
    sid3b, _ = _create(store, sid3)
    assert sid3b == sid3
