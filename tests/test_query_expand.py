"""Tests for door-lock polarity query expansion and ranking."""

from __future__ import annotations

from pathlib import Path

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.retrieval.query_expand import door_lock_polarity, expand_retrieval_query
from repair_assistant.retrieval.rank import filter_and_rank


def _doc(doc_id: str, data: dict) -> Document:
    return Document(data=data, path=Path(f"{doc_id}.yaml"))


def test_door_lock_polarity_stuck_vs_wont_lock() -> None:
    assert door_lock_polarity("door got locked") == "unlock"
    assert door_lock_polarity("door won't open") == "unlock"
    assert door_lock_polarity("door will not unlock") == "unlock"
    assert door_lock_polarity("door won't lock") == "lock"
    assert door_lock_polarity("door will not lock to start") == "lock"
    assert door_lock_polarity("F5E2 on display") is None


def test_expand_retrieval_query_adds_unlock_phrases() -> None:
    expanded = expand_retrieval_query("door got locked")
    assert expanded.startswith("door got locked")
    assert "will not unlock" in expanded.lower()
    assert "F5E2" in expanded
    # Must not pull the opposite symptom into the expand string as primary.
    assert "Door Won't Lock" not in expanded


def test_unlock_polarity_prefers_unlock_evidence_over_wont_lock() -> None:
    owners = _doc(
        "use-and-care",
        {
            "doc_id": "use-and-care",
            "title": "Use and Care",
            "doc_type": "owners_manual",
            "publication_number": "W11156985",
            "corpus": {"role": "primary"},
            "authority": {"tier": "customer"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manual = _doc(
        "service-manual",
        {
            "doc_id": "service-manual",
            "title": "Service Manual",
            "doc_type": "service_manual",
            "publication_number": "W11169652",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[owners, manual])
    hits = [
        {
            "doc_id": "service-manual",
            "chunk_id": "wont-lock",
            "text": "Problem: Door Won't Lock | Possible Cause: Door not closed. "
            "Ensure that door is completely closed.",
            "page": 34,
            "kind": "table_row",
            "error_codes": [],
            "publication_number": "W11169652",
            "revision": "B",
            "score": 0.90,
        },
        {
            "doc_id": "use-and-care",
            "chunk_id": "unlock",
            "text": "If you experience: Door will not unlock | Possible Causes: "
            "Door locks when cycle has started. | Solution: If the Add Garment "
            "light is lit, touch START/PAUSE once.",
            "page": 26,
            "kind": "table_row",
            "error_codes": [],
            "publication_number": "W11156985",
            "revision": "A",
            "score": 0.45,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=2,
        query="door got locked",
        audience="owner",
    )
    assert ranked
    assert ranked[0].chunk_id == "unlock"
    assert ranked[0].final_score > ranked[1].final_score
