"""Tests for document integrity and the three-layer identity model."""

from __future__ import annotations

import hashlib

import pytest

from repair_assistant.corpus import identity

pikepdf = pytest.importorskip("pikepdf", reason="canonicalisation requires pikepdf")


def _make_pdf(path, *, text="ACU Power Check Step 10", pages=2):
    """A small PDF whose pages carry a real content stream."""
    pdf = pikepdf.new()
    for index in range(pages):
        page = pdf.add_blank_page(page_size=(612, 792))
        page.contents_add(
            pikepdf.Stream(pdf, f"BT 72 720 Td ({text} p{index}) Tj ET".encode())
        )
    pdf.save(str(path))
    return path


@pytest.fixture
def sample_pdf(tmp_path):
    return _make_pdf(tmp_path / "sample.pdf")


@pytest.fixture
def blank_pdf(tmp_path):
    """A PDF with no content streams at all, standing in for a scan."""
    path = tmp_path / "blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(str(path))
    return path


def test_sha256_matches_hashlib(tmp_path):
    path = tmp_path / "doc.bin"
    payload = b"W11169652A"
    path.write_bytes(payload)
    assert identity.sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_inspect_reports_page_count_and_size(sample_pdf):
    facts = identity.inspect(sample_pdf)
    assert facts.is_pdf
    assert facts.page_count == 2
    assert facts.bytes == sample_pdf.stat().st_size
    assert len(facts.sha256) == 64


def test_pages_without_a_text_layer_are_flagged(blank_pdf):
    """The scan heuristic Phase 2 needs in order to know when OCR is required."""
    assert identity.inspect(blank_pdf).looks_scanned is True


def test_raw_hashes_diverge_for_identical_content(tmp_path, sample_pdf):
    """The reason a single hash per document is not enough.

    Re-saving a PDF changes its bytes without changing anything a reader would
    notice: the trailer /ID is derived partly from file path and size, and dates
    and producer metadata are rewritten. Two people obtaining the same manual
    from two places will legitimately hold different bytes.
    """
    resaved = tmp_path / "resaved.pdf"
    with pikepdf.open(str(sample_pdf)) as pdf:
        pdf.save(str(resaved), deterministic_id=False)

    assert identity.sha256_file(sample_pdf) != identity.sha256_file(resaved)


def test_canonical_hash_survives_a_resave(tmp_path, sample_pdf):
    """Layer 2 recognises the same edition across sources, where layer 3 cannot."""
    resaved = tmp_path / "resaved.pdf"
    with pikepdf.open(str(sample_pdf)) as pdf:
        with pdf.open_metadata() as meta:
            meta["dc:title"] = "a title that did not exist before"
        pdf.docinfo["/Producer"] = "some other toolchain"
        pdf.save(str(resaved), deterministic_id=False)

    original = identity.canonical_sha256(sample_pdf)
    assert original is not None
    assert identity.sha256_file(sample_pdf) != identity.sha256_file(resaved)
    assert original == identity.canonical_sha256(resaved)


def test_canonical_hash_distinguishes_different_content(tmp_path):
    """It must not be so forgiving that two different editions collide."""
    rev_a = _make_pdf(tmp_path / "a.pdf", text="the original wording")
    rev_b = _make_pdf(tmp_path / "b.pdf", text="the corrected wording")
    assert identity.canonical_sha256(rev_a) != identity.canonical_sha256(rev_b)


def test_canonical_hash_distinguishes_page_count(tmp_path):
    short = _make_pdf(tmp_path / "short.pdf", pages=2)
    long = _make_pdf(tmp_path / "long.pdf", pages=3)
    assert identity.canonical_sha256(short) != identity.canonical_sha256(long)


def test_canonicalizer_version_is_recorded(sample_pdf):
    """Canonical hashes are only reproducible within a toolchain version.

    That is why the manifest stores the producing toolchain next to the hash
    rather than treating the canonical hash as universally stable.
    """
    version = identity.canonicalizer_version()
    assert version and "pikepdf" in version and "qpdf" in version


def test_non_pdf_has_no_canonical_hash(tmp_path):
    path = tmp_path / "article.html"
    path.write_text("<html><body>F5 E2</body></html>", encoding="utf-8")

    facts = identity.inspect(path)
    assert not facts.is_pdf
    assert facts.page_count is None
    assert identity.canonical_sha256(path) is None


def test_corrupt_pdf_does_not_raise(tmp_path):
    """Aggregator and scanner output is frequently malformed; degrade, don't crash."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf")

    facts = identity.inspect(path)
    assert len(facts.sha256) == 64
    assert facts.page_count is None
