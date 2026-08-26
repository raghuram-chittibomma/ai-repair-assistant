"""Tests for the candidate evaluation scenarios.

The seeds are only useful if they stay honest. A scenario that cites a document
the corpus does not contain, or that asserts a model the manifest says is out of
scope, is worse than no scenario at all: it will be implemented in a later phase
and quietly assert the wrong thing.
"""

from __future__ import annotations

import pytest
import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance, document_applies

VALID_STATUSES = {"ready", "needs_document", "needs_authoring", "deferred"}
CITATION_KEYS = ("must_cite", "must_not_cite", "must_not_cite_as_current")


@pytest.fixture(scope="module")
def corpus():
    return manifest_mod.load()


@pytest.fixture(scope="module")
def seeds(corpus):
    path = corpus.root / "evals" / "scenarios" / "candidates.yaml"
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _all_scenarios(seeds):
    for family in seeds["families"]:
        for scenario in family["scenarios"]:
            yield family, scenario


def test_the_families_the_corpus_revealed_are_all_present(seeds):
    """Pinned so that deleting a family is a deliberate act, not an accident.

    ``near-duplicate-tech-sheets`` differs from the rest in provenance: the
    others were reasoned from research before the documents arrived, that one was
    measured from the files afterwards. Both kinds belong here.
    """
    ids = {f["id"] for f in seeds["families"]}
    assert ids == {
        "near-duplicate-tech-sheets",
        "precedence-bulletin-over-manual",
        "applicability-serial-range",
        "applicability-product-category",
        "precedence-revision-and-supersession",
        "staleness-part-numbers",
        "retrieval-exact-identifier",
        "retrieval-cross-reference",
        "conversational-symptom",
        "diagnostic-trajectory",
        "applicability-engineering-digit",
        "abstention",
    }


def test_scenario_ids_are_unique(seeds):
    ids = [s["id"] for _, s in _all_scenarios(seeds)]
    assert len(ids) == len(set(ids))


def test_every_scenario_is_well_formed(seeds):
    for family, scenario in _all_scenarios(seeds):
        where = f"{family['id']}/{scenario['id']}"
        assert scenario["status"] in VALID_STATUSES, where
        assert scenario.get("expect"), f"{where} has no expected behaviour"


def test_every_family_explains_why_it_exists(seeds):
    for family in seeds["families"]:
        assert len(family["why"].strip()) > 60, family["id"]


def test_cited_documents_exist_in_the_manifest(seeds, corpus):
    """A scenario must not reference a document the corpus does not describe.

    Excluded entries count: a scenario can name a known gap (status
    needs_document) without pretending the file is held.
    """
    known = {d.doc_id for d in corpus.documents}
    known |= {d.publication_number for d in corpus.documents if d.publication_number}
    known |= {
        e["publication_number"]
        for e in corpus.excluded
        if e.get("publication_number")
    }

    for family, scenario in _all_scenarios(seeds):
        for key in CITATION_KEYS:
            for reference in scenario.get(key) or []:
                assert reference in known, (
                    f"{family['id']}/{scenario['id']}: {key} names {reference!r}, "
                    "which is not in the manifest or exclusion list"
                )


def test_positive_citations_actually_apply_to_the_stated_appliance(seeds, corpus):
    """`must_cite` must be consistent with the manifest's own applicability data.

    Catches the subtle authoring error of demanding a citation that the
    applicability rules would correctly exclude. Scenarios waiting on an
    unacquired document are skipped — there is nothing to apply yet.
    """
    for family, scenario in _all_scenarios(seeds):
        if scenario.get("status") == "needs_document":
            continue
        appliance_spec = scenario.get("appliance")
        if not appliance_spec:
            continue
        appliance = Appliance(**appliance_spec)

        for reference in scenario.get("must_cite") or []:
            matches = [
                d for d in corpus.documents
                if d.doc_id == reference or d.publication_number == reference
            ]
            assert matches, reference
            assert any(document_applies(d.data, appliance).applies for d in matches), (
                f"{family['id']}/{scenario['id']}: must_cite {reference} but it does "
                f"not apply to {appliance.model}"
            )


def test_negative_citations_are_genuinely_inapplicable(seeds, corpus):
    """`must_not_cite` must be excluded by applicability, not merely undesirable.

    `must_not_cite_as_current` is the separate case: those documents DO apply and
    are excluded by supersession instead, so they are deliberately not checked
    here.
    """
    for family, scenario in _all_scenarios(seeds):
        appliance_spec = scenario.get("appliance")
        if not appliance_spec:
            continue
        appliance = Appliance(**appliance_spec)

        for reference in scenario.get("must_not_cite") or []:
            matches = [
                d for d in corpus.documents
                if d.doc_id == reference or d.publication_number == reference
            ]
            assert matches, reference
            assert not any(document_applies(d.data, appliance).applies for d in matches), (
                f"{family['id']}/{scenario['id']}: must_not_cite {reference}, but the "
                f"manifest says it applies to {appliance.model}"
            )


def test_superseded_citations_do_apply_but_are_replaced(seeds, corpus):
    """The `must_not_cite_as_current` cases must have a supersession edge.

    Otherwise there is nothing in the data for a later phase to reason from, and
    the scenario is asserting a preference rather than a documented fact.
    """
    for family, scenario in _all_scenarios(seeds):
        for reference in scenario.get("must_not_cite_as_current") or []:
            matches = [
                d for d in corpus.documents
                if d.doc_id == reference or d.publication_number == reference
            ]
            assert matches, reference
            assert any(
                d.relationships("superseded_by") or d.relationships("corrected_by")
                for d in matches
            ), (
                f"{family['id']}/{scenario['id']}: {reference} is marked not-current "
                "but has no superseded_by or corrected_by relationship"
            )


def test_the_anchor_model_is_the_one_the_corpus_was_built_for(seeds):
    assert seeds["anchor_model"] == "WFW5620HW0"


def test_enough_ready_scenarios_to_be_useful(seeds):
    ready = [s for _, s in _all_scenarios(seeds) if s["status"] == "ready"]
    assert len(ready) >= 12


def test_every_ready_scenario_has_deterministic_grading(seeds):
    """E2: ready scenarios must not be prose-empty (auto-pass without --judge).

    Overlay: evals/qa/candidates-grading.yaml. Prose-heavy cases may also set
    requires_judge: true — that does not replace a det rule.
    """
    from repair_assistant.eval.candidates_bench import (
        _merge_scenario,
        load_grading_overlay,
    )
    from repair_assistant.eval.grading import has_deterministic_grading

    grading = load_grading_overlay()
    bare: list[str] = []
    for _family, scenario in _all_scenarios(seeds):
        if scenario.get("status") != "ready":
            continue
        if not scenario.get("question"):
            continue
        merged = _merge_scenario(scenario, grading.get(scenario["id"], {}))
        if not has_deterministic_grading(merged):
            bare.append(scenario["id"])
    assert not bare, (
        "ready scenarios missing deterministic grading (overlay or inline): "
        + ", ".join(bare)
    )
