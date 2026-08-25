"""Tests for the real manifest and its guarantees.

These run against the actual corpus manifest, not fixtures. If someone adds a
document that breaks the licensing guarantee or points a relationship at a
publication nobody has heard of, these fail.
"""

from __future__ import annotations

import copy

import pytest

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance, document_applies


@pytest.fixture(scope="module")
def corpus():
    return manifest_mod.load()


def test_manifest_is_valid(corpus):
    problems = manifest_mod.validate(corpus)
    assert problems == [], "\n".join(problems)


def test_corpus_is_small_and_deliberate(corpus):
    """Phase 1's objective is not to maximise the number of files."""
    assert 10 <= len(corpus.documents) <= 30


def test_no_document_claims_to_be_redistributable(corpus):
    for document in corpus.documents:
        assert document.provenance["redistributable"] is False, document.doc_id
        assert document.provenance["license"] not in manifest_mod.REDISTRIBUTABLE_SPDX


def test_licensing_guard_catches_a_bad_entry(corpus):
    """The guarantee is enforced, not merely stated."""
    poisoned = copy.deepcopy(corpus)
    poisoned.documents = list(corpus.documents)
    bad = copy.deepcopy(corpus.documents[0].data)
    bad["provenance"]["license"] = "MIT"
    poisoned.documents[0] = manifest_mod.Document(data=bad, path=corpus.documents[0].path)

    problems = manifest_mod.validate(poisoned)
    assert any("implies redistribution is permitted" in p for p in problems)


def test_every_document_explains_why_it_is_here(corpus):
    for document in corpus.documents:
        rationale = document.data["corpus"]["rationale"].strip()
        assert len(rationale) > 40, f"{document.doc_id} has a thin rationale"


def test_corpus_contains_deliberate_distractors(corpus):
    """A corpus of only-correct documents cannot measure applicability."""
    roles = [d.role for d in corpus.documents]
    assert roles.count("distractor") >= 3
    assert roles.count("applicable") >= 8


def test_relationship_targets_resolve(corpus):
    known = corpus.known_publication_numbers()
    for document in corpus.documents:
        for relationship in document.relationships():
            assert relationship["target"] in known, (
                f"{document.doc_id} -> {relationship['target']}"
            )


# ---------------------------------------------------------------------------
# The corpus's headline claims, asserted against the real manifest
# ---------------------------------------------------------------------------


def test_the_precedence_edge_is_recorded(corpus):
    """TSP W11375982 corrects service manual W11169652 at a named location."""
    tsp = corpus.by_publication("W11375982")[0]
    corrections = tsp.relationships("corrects")
    targets = {c["target"] for c in corrections}
    assert "W11169652" in targets

    edge = next(c for c in corrections if c["target"] == "W11169652")
    assert "Step 10" in edge["locator"]

    # And the manual records the reciprocal edge, so precedence is discoverable
    # from either direction.
    manual = corpus.by_publication("W11169652", "A")[0]
    assert any(r["target"] == "W11375982" for r in manual.relationships("corrected_by"))


def test_owners_manual_supersession_crosses_publication_numbers(corpus):
    """Supersession is not always a revision-letter bump."""
    old = corpus.by_publication("W11156985", "A")[0]
    edge = old.relationships("superseded_by")[0]
    assert edge["target"] == "W11355369"
    assert old.publication_number != edge["target"]


def test_service_manual_covers_the_whole_l97_platform(corpus):
    manual = corpus.by_publication("W11169652", "A")[0]
    models = manual.data["applicability"]["models"]
    assert len(models) == 23
    assert "WFW5620HW*" in models
    assert "IFW5900HW*" in models  # Inglis, Canada
    assert "NFW5800HW*" in models  # Amana


def test_parts_list_is_scoped_to_a_single_engineering_digit(corpus):
    """The narrowest applicability in the corpus, contrasting with the manual."""
    parts = corpus.by_publication("W11320547", "C")[0]
    assert parts.data["applicability"]["models"] == ["WFW5620HW0"]


def test_anchor_model_applicability_split(corpus):
    """Every distractor must be excluded, and every applicable document kept."""
    anchor = Appliance(model="WFW5620HW0")

    for document in corpus.documents:
        result = document_applies(document.data, anchor)
        if document.role == "distractor" and document.doc_id != "use-and-care-w11156985":
            assert not result.applies, f"{document.doc_id} should not apply: {result.reason}"
        elif document.role == "applicable":
            assert result.applies, f"{document.doc_id} should apply: {result.reason}"


def test_superseded_document_still_applies_by_model(corpus):
    """Supersession is a separate axis from applicability, and must not be conflated.

    The old Use & Care guide genuinely covers this model. It is the wrong
    document to cite because something replaced it, not because it does not
    apply. Collapsing the two would make the distinction untestable.
    """
    old = corpus.by_publication("W11156985", "A")[0]
    assert document_applies(old.data, Appliance(model="WFW5620HW0")).applies
    assert old.role == "distractor"
    assert old.relationships("superseded_by")


def test_f5e2_articles_are_separated_by_product_category(corpus):
    """Three near-identical articles; only the front-load one applies."""
    anchor = Appliance(model="WFW5620HW0")
    f5e2 = [d for d in corpus.documents if "f5e2" in d.doc_id]
    assert len(f5e2) == 3

    applying = [d for d in f5e2 if document_applies(d.data, anchor).applies]
    assert [d.doc_id for d in applying] == ["kb-f5e2-front-load"]


def test_browser_saved_pages_are_marked_volatile(corpus):
    """Hash mismatch on a browser-saved page must not be reported as corruption.

    MindTouch pages embed session tokens, render timestamps and analytics tags,
    so two saves of an unchanged page differ. Pinning them strictly would make
    `verify` report corruption that did not happen, which is worse than saying
    nothing.

    Asserted on "not a PDF" rather than on a specific extension, because the
    saved format is whatever the browser produced -- it was .html when this was
    written and became .mhtml once the documents actually arrived.
    """
    archives = [d for d in corpus.documents if not d.local_filename.endswith(".pdf")]
    assert len(archives) == 6
    for document in archives:
        assert document.content_volatile, document.doc_id

    # PDFs are byte-stable once acquired and must stay strictly verified.
    for document in corpus.documents:
        if document.local_filename.endswith(".pdf"):
            assert not document.content_volatile, document.doc_id


def test_gaps_are_recorded_rather_than_silent(corpus):
    """A known-missing document is different from a document nobody knew about."""
    assert corpus.excluded
    revised_manual = [
        e for e in corpus.excluded
        if e.get("publication_number") == "W11169652" and e.get("revision") == "B"
    ]
    assert revised_manual, "the revised service manual must be recorded as a known gap"
    assert revised_manual[0]["reason"]
    assert revised_manual[0]["evidence"]
