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
    # KB may still appear, but must not outrank the install guide.
    assert ranked[0].final_score >= next(
        h.final_score for h in ranked if h.doc_id == "kb-f7e1-front-load"
    )


def test_revision_manual_query_prefers_matching_rev_over_tsp() -> None:
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
            "text": "incorrect information in W11169652 Test #1 ACU power check step 10",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11375982",
            "revision": None,
            "score": 0.94,
        },
        {
            "doc_id": "service-manual-w11169652-revb",
            "chunk_id": "b",
            "text": "ACU diagnostic LED blinks rapidly then 0.5s on / 0.5s off",
            "page": 44,
            "kind": "procedure",
            "error_codes": [],
            "publication_number": "W11169652",
            "revision": "B",
            "score": 0.90,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="What does revision B of the service manual say about the ACU LED?",
    )
    assert ranked[0].doc_id == "service-manual-w11169652-revb"


def test_superseded_doc_demoted_vs_superseding_twin() -> None:
    old = _doc(
        "synth-owners-manual-v1",
        {
            "doc_id": "synth-owners-manual-v1",
            "title": "Old U&C",
            "doc_type": "use_and_care",
            "publication_number": "SYNTH-UC-100",
            "corpus": {"role": "synthetic_eval"},
            "authority": {"tier": "owner_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
            "relationships": [{"type": "superseded_by", "target": "SYNTH-UC-200"}],
        },
    )
    new = _doc(
        "synth-owners-manual-v2",
        {
            "doc_id": "synth-owners-manual-v2",
            "title": "New U&C",
            "doc_type": "use_and_care",
            "publication_number": "SYNTH-UC-200",
            "corpus": {"role": "synthetic_eval"},
            "authority": {"tier": "owner_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
            "relationships": [{"type": "supersedes", "target": "SYNTH-UC-100"}],
        },
    )
    manifest = Manifest(documents=[old, new])
    hits = [
        {
            "doc_id": "synth-owners-manual-v1",
            "chunk_id": "a",
            "text": "cleaning the washer drum use Affresh",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "SYNTH-UC-100",
            "revision": "A",
            "score": 0.92,
        },
        {
            "doc_id": "synth-owners-manual-v2",
            "chunk_id": "b",
            "text": "cleaning the washer drum leave the door ajar Affresh",
            "page": 1,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "SYNTH-UC-200",
            "revision": "A",
            "score": 0.91,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="What does the owner's manual say about cleaning the washer drum?",
    )
    assert ranked[0].doc_id == "synth-owners-manual-v2"
    assert ranked[0].final_score > ranked[1].final_score


def test_named_publication_prefers_exact_pub_over_near_dup() -> None:
    a = _doc(
        "tech-sheet-w11320651",
        {
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech Sheet A",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    b = _doc(
        "tech-sheet-w11156989",
        {
            "doc_id": "tech-sheet-w11156989",
            "title": "Tech Sheet B",
            "doc_type": "tech_sheet",
            "publication_number": "W11156989",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[a, b])
    hits = [
        {
            "doc_id": "tech-sheet-w11156989",
            "chunk_id": "b",
            "text": "IMPORTANT SAFETY NOTICE For Technicians only",
            "page": 1,
            "kind": "heading",
            "error_codes": [],
            "publication_number": "W11156989",
            "revision": "A",
            "score": 0.90,
        },
        {
            "doc_id": "tech-sheet-w11320651",
            "chunk_id": "a",
            "text": "IMPORTANT SAFETY NOTICE For Technicians only",
            "page": 1,
            "kind": "heading",
            "error_codes": [],
            "publication_number": "W11320651",
            "revision": "B",
            "score": 0.89,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="What does the safety notice on page 1 of W11320651 say?",
    )
    assert ranked[0].publication_number == "W11320651"
    assert all(h.publication_number == "W11320651" for h in ranked)


def test_technician_depth_prefers_tech_sheet_over_kb() -> None:
    kb = _doc(
        "kb-f5e2-front-load",
        {
            "doc_id": "kb-f5e2-front-load",
            "title": "F5E2 FAQ",
            "doc_type": "knowledge_article",
            "corpus": {"role": "primary"},
            "authority": {"tier": "consumer"},
            "applicability": {
                "models": ["WFW*"],
                "product_category": "front_load_washer_27in",
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    sheet = _doc(
        "tech-sheet-w11320651",
        {
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech Sheet",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[kb, sheet])
    hits = [
        {
            "doc_id": "kb-f5e2-front-load",
            "chunk_id": "a",
            "text": "F5E2 door lock error close the door",
            "page": 1,
            "kind": "article",
            "error_codes": ["F5E2"],
            "publication_number": None,
            "revision": None,
            "score": 1.0,
        },
        {
            "doc_id": "tech-sheet-w11320651",
            "chunk_id": "b",
            "text": "F5E2 Lock failure. See TEST #4: Door Lock System",
            "page": 8,
            "kind": "table_row",
            "error_codes": ["F5E2"],
            "publication_number": "W11320651",
            "revision": "B",
            "score": 1.0,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="F5 E2 on a WFW5620HW0 - the door will not lock. What should I check?",
        query_error_codes=["F5E2"],
    )
    assert ranked[0].doc_id == "tech-sheet-w11320651"
    assert all(h.doc_id != "kb-f5e2-front-load" for h in ranked[:1])


def test_consumer_f5e2_meaning_still_allows_kb() -> None:
    kb = _doc(
        "kb-f5e2-front-load",
        {
            "doc_id": "kb-f5e2-front-load",
            "title": "F5E2 FAQ",
            "doc_type": "knowledge_article",
            "corpus": {"role": "primary"},
            "authority": {"tier": "consumer"},
            "applicability": {
                "models": ["WFW*"],
                "product_category": "front_load_washer_27in",
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[kb])
    hits = [
        {
            "doc_id": "kb-f5e2-front-load",
            "chunk_id": "a",
            "text": "F5E2 means door lock",
            "page": 1,
            "kind": "article",
            "error_codes": ["F5E2"],
            "publication_number": None,
            "revision": None,
            "score": 0.8,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="What does error code F5E2 mean on my front-load washer?",
        query_error_codes=["F5E2"],
    )
    assert ranked[0].doc_id == "kb-f5e2-front-load"
    assert ranked[0].authority_boost >= 0.4


def test_part_number_query_is_not_treated_as_named_publication() -> None:
    from repair_assistant.retrieval.rank import queried_publications

    assert queried_publications("Is part number W10804741 the door lock?") == set()
    assert queried_publications("What does the safety notice on page 1 of W11320651 say?") == {
        "W11320651"
    }
    assert queried_publications("Is W11320547 the parts list for my WFW5622HW0?") == {
        "W11320547"
    }


def test_owner_audience_prefers_owner_docs_when_available() -> None:
    use_care = _doc(
        "use-and-care-w11156985",
        {
            "doc_id": "use-and-care-w11156985",
            "title": "Use & Care",
            "doc_type": "owners_manual",
            "publication_number": "W11156985",
            "corpus": {"role": "primary"},
            "authority": {"tier": "owner_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    tech = _doc(
        "tech-sheet-w11320651",
        {
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech Sheet",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["WFW5620HW*", "CFW4084HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[use_care, tech])
    hits = [
        {
            "doc_id": "tech-sheet-w11320651",
            "chunk_id": "t1",
            "text": "Not cleaning clothes. Verify load is not bunched.",
            "page": 11,
            "kind": "table_row",
            "error_codes": [],
            "publication_number": "W11320651",
            "revision": "B",
            "score": 0.95,
        },
        {
            "doc_id": "use-and-care-w11156985",
            "chunk_id": "u1",
            "text": "Clothes are not clean. Use HE detergent.",
            "page": 12,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11156985",
            "revision": "A",
            "score": 0.80,
        },
    ]
    owner_ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="not washing properly",
        audience="owner",
    )
    assert owner_ranked
    assert all(h.doc_id == "use-and-care-w11156985" for h in owner_ranked)

    tech_ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="WFW5620HW0"),
        limit=5,
        query="not washing properly",
        audience="technician",
    )
    assert {h.doc_id for h in tech_ranked} >= {
        "use-and-care-w11156985",
        "tech-sheet-w11320651",
    }


def test_owner_audience_falls_back_when_no_owner_docs() -> None:
    tech = _doc(
        "tech-sheet-w11320651",
        {
            "doc_id": "tech-sheet-w11320651",
            "title": "Tech Sheet",
            "doc_type": "tech_sheet",
            "publication_number": "W11320651",
            "corpus": {"role": "primary"},
            "authority": {"tier": "service_literature"},
            "applicability": {
                "models": ["CFW4084HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    # Owner manual exists but does not apply to CFW4084HW.
    use_care = _doc(
        "use-and-care-w11156985",
        {
            "doc_id": "use-and-care-w11156985",
            "title": "Use & Care",
            "doc_type": "owners_manual",
            "publication_number": "W11156985",
            "corpus": {"role": "primary"},
            "authority": {"tier": "owner_literature"},
            "applicability": {
                "models": ["WFW5620HW*"],
                "serial_ranges": [{"scope": "all"}],
            },
        },
    )
    manifest = Manifest(documents=[use_care, tech])
    hits = [
        {
            "doc_id": "tech-sheet-w11320651",
            "chunk_id": "t1",
            "text": "Not cleaning clothes.",
            "page": 11,
            "kind": "table_row",
            "error_codes": [],
            "publication_number": "W11320651",
            "revision": "B",
            "score": 0.9,
        },
        {
            "doc_id": "use-and-care-w11156985",
            "chunk_id": "u1",
            "text": "Clothes are not clean.",
            "page": 12,
            "kind": "prose",
            "error_codes": [],
            "publication_number": "W11156985",
            "revision": "A",
            "score": 0.85,
        },
    ]
    ranked = filter_and_rank(
        hits,
        manifest,
        Appliance(model="CFW4084HW"),
        limit=5,
        query="not washing properly",
        audience="owner",
    )
    assert ranked
    assert ranked[0].doc_id == "tech-sheet-w11320651"
    assert all(h.doc_id != "use-and-care-w11156985" for h in ranked)



