"""Pinning must not damage the manifest.

The manifest is a reasoning document that happens to be machine-readable. Its
comments explain why each document earns its place, and they are the deliverable
-- a corpus nobody can explain is not an authoritative corpus. These tests exist
because the obvious implementation (load YAML, mutate, dump) deletes all of it,
which is easy to do and hard to notice in a four-hundred-line diff.
"""

import pytest
import yaml

from repair_assistant.corpus import pinning

ENTRY = """\
doc_id: tsp-w11533288
publication_number: W11533288
revision: A
languages: [en-US]

applicability:
  brands: [Maytag, Whirlpool]
  serial_ranges:
    - start: CX10xxxx
      end: CX27xxxx
  # The distinguishing feature of this bulletin: applicability turns on firmware
  # version, not only on model or serial. SC.02 exhibits the fault; SC.03 fixes it.
  software_versions: ["SC.02", "SC.03"]

identity:
  canonical_sha256: null
  canonicalizer: null
  instances: []

corpus:
  role: distractor
  rationale: >-
    Kept because it is a near-miss: same fault family, wrong product category.
"""

INSTANCE = {
    "sha256": "a" * 64,
    "bytes": 254_486,
    "acquired_from": "oem_public_pdf",
    "pages": 1,
    "pdf_producer": "Adobe PDF Library 15.0",
    "first_seen": "2026-08-25",
}


@pytest.fixture
def pinned():
    return pinning.apply_pin(
        ENTRY,
        instance=INSTANCE,
        canonical_sha256="b" * 64,
        canonicalizer="pikepdf-10.12.0/qpdf-12.3.2",
    )


def test_comments_survive(pinned):
    assert "The distinguishing feature of this bulletin" in pinned
    assert "SC.02 exhibits the fault; SC.03 fixes it." in pinned


def test_untouched_lines_are_byte_identical(pinned):
    """Everything outside the identity block must be unchanged, not merely equivalent.

    Semantic equality is not enough: a reviewer reads the diff, and reflowed
    lists or requoted scalars bury the three lines that actually changed.
    """
    before = ENTRY.split("\n")
    after = pinned.split("\n")
    changed = set(before).symmetric_difference(after)

    assert "languages: [en-US]" not in changed
    assert "  brands: [Maytag, Whirlpool]" not in changed
    assert '  software_versions: ["SC.02", "SC.03"]' not in changed
    assert "    - start: CX10xxxx" not in changed


def test_diff_is_small(pinned):
    """A pin should be reviewable at a glance."""
    added = [
        line
        for line in pinned.split("\n")
        if line not in ENTRY.split("\n") and line.strip()
    ]
    # canonical_sha256, canonicalizer, instances:, plus six instance fields.
    assert len(added) <= 10, added


def test_values_land_where_expected(pinned):
    data = yaml.safe_load(pinned)
    assert data["identity"]["canonical_sha256"] == "b" * 64
    assert data["identity"]["canonicalizer"] == "pikepdf-10.12.0/qpdf-12.3.2"
    (instance,) = data["identity"]["instances"]
    assert instance == INSTANCE


def test_result_is_still_valid_yaml_with_intent_preserved(pinned):
    data = yaml.safe_load(pinned)
    assert data["applicability"]["software_versions"] == ["SC.02", "SC.03"]
    assert data["applicability"]["serial_ranges"] == [{"start": "CX10xxxx", "end": "CX27xxxx"}]
    assert data["doc_id"] == "tsp-w11533288"


def test_second_pin_appends_rather_than_replaces(pinned):
    """Re-acquiring the same document records another instance of one edition."""
    second = dict(INSTANCE, sha256="c" * 64, first_seen="2026-09-01")
    twice = pinning.apply_pin(pinned, instance=second)

    instances = yaml.safe_load(twice)["identity"]["instances"]
    assert [i["sha256"] for i in instances] == ["a" * 64, "c" * 64]
    assert "The distinguishing feature of this bulletin" in twice


def test_volatile_entry_records_instance_without_claiming_a_canonical_hash(pinned):
    """MHTML has no canonical edition hash; the instance is still worth recording."""
    volatile = pinning.apply_pin(ENTRY, instance=INSTANCE, canonical_sha256=None)
    data = yaml.safe_load(volatile)
    assert data["identity"]["canonical_sha256"] is None
    assert len(data["identity"]["instances"]) == 1


def test_missing_identity_block_is_refused():
    with pytest.raises(pinning.PinError):
        pinning.apply_pin("doc_id: x\n", instance=INSTANCE)
