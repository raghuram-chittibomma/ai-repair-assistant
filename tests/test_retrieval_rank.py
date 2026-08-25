"""Unit tests for Phase 4 ranking / error-code extraction (no Postgres)."""

from __future__ import annotations

from pathlib import Path

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Document, Manifest
from repair_assistant.retrieval.rank import filter_and_rank
from repair_assistant.retrieval.search import extract_error_codes


def _doc(doc_id: str, data: dict) -> Document:
    return Document(data=data, path=Path(f"{doc_id}.yaml"))


def test_extract_error_codes() -> None:
    assert extract_error_codes("door F5E1 and f7e1") == ["F5E1", "F7E1"]
    assert extract_error_codes("no codes here") == []


def test_filter_drops_inapplicable_and_boosts_correcting_bulletin() -> None:
    manual = _doc(
        "service-manual-w11169652",
        {
            "doc_id": "service-manual-w11169652",
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
    bulletin = _doc(
        "tsp-w11375982",
        {
            "doc_id": "tsp-w11375982",
            "title": "TSP",
            "doc_type": "technical_service_pointer",
            "publication_number": "W11375982",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_pointer"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
            "relationships": [
                {"type": "corrects", "target": "W11169652"},
            ],
        },
    )
    wrong_platform = _doc(
        "tsp-w11395614",
        {
            "doc_id": "tsp-w11395614",
            "title": "24in door lock",
            "doc_type": "technical_service_pointer",
            "publication_number": "W11395614",
            "corpus": {"role": "negative"},
            "authority": {"tier": "service_pointer"},
            "applicability": {
                "models": ["WFC8090GX*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[manual, bulletin, wrong_platform])
    hits = [
        {
            "doc_id": "tsp-w11395614",
            "chunk_id": "a",
            "text": "door locks but will not run",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11395614",
            "revision": None,
            "score": 0.95,
        },
        {
            "doc_id": "service-manual-w11169652",
            "chunk_id": "b",
            "text": "ACU power check step 10",
            "page": 44,
            "kind": "procedure",
            "error_codes": [],
            "publication_number": "W11169652",
            "revision": "A",
            "score": 0.90,
        },
        {
            "doc_id": "tsp-w11375982",
            "chunk_id": "c",
            "text": "incorrect information in service manual step 10",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11375982",
            "revision": None,
            "score": 0.88,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
    )
    ids = [h.doc_id for h in ranked]
    assert "tsp-w11395614" not in ids
    assert ids[0] == "tsp-w11375982"
    assert ranked[0].final_score > ranked[1].final_score


def test_bibliographic_query_prefers_service_manual_over_tsp() -> None:
    manual = _doc(
        "service-manual-w11169652-revb",
        {
            "doc_id": "service-manual-w11169652-revb",
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
    bulletin = _doc(
        "tsp-w11375982",
        {
            "doc_id": "tsp-w11375982",
            "title": "TSP",
            "doc_type": "technical_service_pointer",
            "publication_number": "W11375982",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_pointer"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
            "relationships": [{"type": "corrects", "target": "W11169652"}],
        },
    )
    manifest = Manifest(documents=[manual, bulletin])
    hits = [
        {
            "doc_id": "tsp-w11375982",
            "chunk_id": "a",
            "text": "Service Manual (W11169652) regarding the ACU Diagnostic LED",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11375982",
            "revision": None,
            "score": 0.92,
        },
        {
            "doc_id": "service-manual-w11169652-revb",
            "chunk_id": "b",
            "text": "27 inch front load washer service manual WFW5620HW",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11169652",
            "revision": "B",
            "score": 0.88,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW"),
        limit=5,
        query="What service manual covers a WFW5620HW?",
    )
    assert ranked[0].doc_id == "service-manual-w11169652-revb"


def test_installation_query_boosts_referenced_install_guide() -> None:
    kb = _doc(
        "kb-f7e1-front-load",
        {
            "doc_id": "kb-f7e1-front-load",
            "title": "F7 E1",
            "doc_type": "knowledge_article",
            "publication_number": None,
            "corpus": {"role": "applicable"},
            "authority": {"tier": "support_article"},
            "applicability": {
                "models": ["WFW*"],
                "serial_ranges": [{"scope": "all"}],
            },
            "relationships": [{"type": "references", "target": "W11156977"}],
        },
    )
    install = _doc(
        "installation-instructions-w11156977",
        {
            "doc_id": "installation-instructions-w11156977",
            "title": "Installation",
            "doc_type": "installation_instructions",
            "publication_number": "W11156977",
            "corpus": {"role": "applicable"},
            "authority": {"tier": "owner_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manual = _doc(
        "service-manual-w11169652-revb",
        {
            "doc_id": "service-manual-w11169652-revb",
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
    manifest = Manifest(documents=[kb, install, manual])
    hits = [
        {
            "doc_id": "kb-f7e1-front-load",
            "chunk_id": "kb",
            "text": "F7 E1 motor speed error from shipping bolts",
            "page": None,
            "kind": "article",
            "error_codes": ["F7E1"],
            "publication_number": None,
            "revision": None,
            "score": 1.0,
        },
        {
            "doc_id": "service-manual-w11169652-revb",
            "chunk_id": "manual",
            "text": "F7E1 motor control fault troubleshooting",
            "page": 10,
            "kind": "prose",
            "error_codes": ["F7E1"],
            "publication_number": "W11169652",
            "revision": "B",
            "score": 1.0,
        },
        {
            "doc_id": "installation-instructions-w11156977",
            "chunk_id": "inst",
            "text": "Remove all four shipping bolts before first use",
            "page": 3,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11156977",
            "revision": "D",
            "score": 0.85,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="My new washer shakes violently and shows F7 E1 during the spin cycle.",
        query_error_codes=["F7E1"],
    )
    pubs = [h.publication_number for h in ranked]
    assert pubs[0] == "W11156977"
