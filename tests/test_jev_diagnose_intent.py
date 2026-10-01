"""Jev decide client + diagnose intent bake-off (ADR-0054) — offline tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from repair_assistant.diagnostic.intent import classify_diagnose_turn, parse_diagnose_label
from repair_assistant.diagnostic.intent_bench import (
    load_fixtures,
    regex_diagnose_label,
    scorecard_markdown,
)
from repair_assistant.diagnostic.jev import (
    LABEL_CRITERIA,
    build_decide_body,
    live_jev_intent_complete,
    parse_retrieve_label_answer,
)
from repair_assistant.qa.structured import DIAGNOSE_INTENT_LABELS


def test_label_criteria_cover_closed_set() -> None:
    assert set(LABEL_CRITERIA) == set(DIAGNOSE_INTENT_LABELS)
    body = build_decide_body(state="board\n\nConversation so far:\nok")
    criteria = body["questions"]["retrieve_label"]["criteria"]
    assert set(criteria) == set(DIAGNOSE_INTENT_LABELS)


def test_parse_retrieve_label_answer_respects_confidence() -> None:
    payload = {
        "answers": {
            "retrieve_label": {
                "type": "choice",
                "choice": "ack",
                "confidence": 0.4,
                "probabilities": {"ack": 0.4},
            }
        }
    }
    assert parse_retrieve_label_answer(payload, min_confidence=0.0) == "ack"
    assert parse_retrieve_label_answer(payload, min_confidence=0.5) is None
    assert parse_retrieve_label_answer({"answers": {}}, min_confidence=0.0) is None
    bad = {
        "answers": {
            "retrieve_label": {
                "type": "choice",
                "choice": "rewrite this",
                "confidence": 1.0,
            }
        }
    }
    assert parse_retrieve_label_answer(bad, min_confidence=0.0) is None


def test_live_jev_intent_complete_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_decide(state: str, **_kwargs):
        assert "Conversation so far" in state or state
        return {
            "answers": {
                "retrieve_label": {
                    "type": "choice",
                    "choice": "still_unresolved",
                    "confidence": 0.91,
                }
            }
        }

    monkeypatch.setattr(
        "repair_assistant.diagnostic.jev.decide", fake_decide
    )
    monkeypatch.setattr(
        "repair_assistant.diagnostic.jev.jev_min_confidence", lambda: 0.0
    )
    raw = live_jev_intent_complete("system unused", "board\n\nConversation so far:\nUser: still facing the issue")
    assert parse_diagnose_label(raw) == "still_unresolved"


def test_classify_diagnose_turn_with_jev_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "repair_assistant.diagnostic.jev.decide",
        lambda *_a, **_k: {
            "answers": {
                "retrieve_label": {
                    "type": "choice",
                    "choice": "new_symptom",
                    "confidence": 0.88,
                }
            }
        },
    )
    monkeypatch.setattr(
        "repair_assistant.diagnostic.jev.jev_min_confidence", lambda: 0.0
    )
    label = classify_diagnose_turn(
        board_text="symptom: F5E2",
        transcript="User: now it leaks\n",
        complete=live_jev_intent_complete,
    )
    assert label == "new_symptom"


def test_intent_fixtures_load_and_cover_all_labels() -> None:
    fixtures = load_fixtures()
    assert len(fixtures) >= 15
    labels = {str(f["label"]) for f in fixtures}
    assert labels == set(DIAGNOSE_INTENT_LABELS)
    for fix in fixtures:
        assert fix["id"]
        assert fix["board"].strip()
        assert fix["transcript"].strip()
        assert fix["label"] in DIAGNOSE_INTENT_LABELS


def test_regex_baseline_ack_and_unresolved() -> None:
    ack = regex_diagnose_label(
        board_text="x",
        transcript="User: door issue\nAssistant: check\nUser: looks good\n",
    )
    assert ack == "ack"
    unresolved = regex_diagnose_label(
        board_text="x",
        transcript=(
            "User: F5E2\nAssistant: check lock\n"
            "User: checked but still facing the issue\n"
        ),
    )
    assert unresolved == "still_unresolved"
    miss = regex_diagnose_label(
        board_text="x",
        transcript="User: F5E2\nAssistant: check\nUser: now it leaks\n",
    )
    assert miss is None


def test_scorecard_markdown_skipped_arm() -> None:
    from repair_assistant.diagnostic.intent_bench import ArmSummary, CaseResult

    arms = [
        ArmSummary(name="openai", skipped="OPENAI_API_KEY unset"),
        ArmSummary(
            name="regex",
            results=[
                CaseResult(
                    fixture_id="ack-looks-good",
                    expected="ack",
                    predicted="ack",
                    latency_ms=0.1,
                )
            ],
        ),
    ]
    md = scorecard_markdown(arms)
    assert "skipped: OPENAI_API_KEY unset" in md
    assert "`regex`" in md
    assert "Accept rule" in md
    assert "total cost (USD)" in md
    assert "mean latency (ms)" in md
    assert "mean cost / call (USD)" in md


def test_session_prefers_jev_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from repair_assistant.diagnostic import session as session_mod
    from repair_assistant.diagnostic.jev import live_jev_intent_complete

    monkeypatch.setenv("JEV_API_KEY", "jv_live_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fn = session_mod._session_classify_turn(None)
    assert fn is live_jev_intent_complete


def test_session_falls_back_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from repair_assistant.diagnostic import session as session_mod
    from repair_assistant.diagnostic.intent import live_intent_complete

    # Empty (not deleted) so load_dotenv_files will not refill from .env.local.
    monkeypatch.setenv("JEV_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fn = session_mod._session_classify_turn(None)
    assert fn is live_intent_complete


def test_session_no_keys_means_regex_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from repair_assistant.diagnostic import session as session_mod

    monkeypatch.setenv("JEV_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert session_mod._session_classify_turn(None) is None
    assert session_mod._session_classify_turn(MagicMock()) is None
