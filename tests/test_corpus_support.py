"""Tests for corpus coverage checks and support messages."""

from __future__ import annotations

from pathlib import Path

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.corpus.support import (
    ABSTAIN_UNSUPPORTED_MODEL,
    corpus_supports_appliance,
    unsupported_appliance_message,
)


def _manifest() -> Manifest:
    doc = Document(
        data={
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech sheet",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
        path=Path("tech-sheet-w11320651.yaml"),
    )
    return Manifest(documents=[doc])


def test_corpus_supports_known_model() -> None:
    result = corpus_supports_appliance(_manifest(), Appliance(model="WFW5620HW0"))
    assert result.supported
    assert result.applicable_documents == 1


def test_corpus_rejects_unknown_model() -> None:
    result = corpus_supports_appliance(_manifest(), Appliance(model="WTW4816FW0"))
    assert not result.supported
    assert result.code == ABSTAIN_UNSUPPORTED_MODEL


def test_unsupported_message_mentions_customer_care() -> None:
    msg = unsupported_appliance_message(Appliance(model="WTW9999XX0"))
    assert "WTW9999XX0" in msg
    assert "Whirlpool Customer Care" in msg
    assert "whirlpool.com/support" in msg
