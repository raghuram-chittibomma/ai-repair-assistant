"""Tests for identifying and filing downloaded documents.

The cases here are the ones that actually occur. Whirlpool's asset CDN serves
some documents from URLs ending ``/_jcr_content/renditions/original``, so the
browser saves them as ``original.pdf`` with no publication number in the name at
all -- identification has to come from inside the file.
"""

from __future__ import annotations

import pytest

from repair_assistant.corpus import intake
from repair_assistant.corpus import manifest as manifest_mod

pikepdf = pytest.importorskip("pikepdf")


def _pdf_with_text(path, text):
    """A PDF whose text is genuinely extractable.

    A content stream alone is not enough: without a font resource the text
    operators produce no extractable text, which silently makes any test of
    content-based identification vacuous.
    """
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.contents_add(pikepdf.Stream(pdf, f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()))
    pdf.save(str(path))
    return path


@pytest.fixture(scope="module")
def corpus():
    return manifest_mod.load()


def test_the_fixture_actually_produces_extractable_text(tmp_path):
    """Guard the guard: if this breaks, the tests below become meaningless."""
    path = _pdf_with_text(tmp_path / "probe.pdf", "W11533288A")
    numbers, _, sample = intake._pdf_signals(path)
    assert "W11533288" in numbers, f"extraction produced {sample!r}"


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "numbers", "revision"),
    [
        ("service-manual-w11169652-reva-27in-front-load-washers.pdf", {"W11169652"}, "A"),
        ("tech-sheet-w11320651-rev-b.pdf", {"W11320651"}, "B"),
        ("service-pointer-W11395614.pdf", {"W11395614"}, None),
        ("service-pointer-w11533288-reva.pdf", {"W11533288"}, "A"),
        ("W11320547C.pdf", {"W11320547"}, "C"),
        ("original.pdf", set(), None),
        ("F5_E2_-_Error_Code.html", set(), None),
    ],
)
def test_filename_signals(filename, numbers, revision):
    assert intake._from_filename(filename) == (numbers, revision)


def test_longer_numbers_are_not_truncated_into_false_matches():
    """A 9-digit number must not be read as an 8-digit publication number."""
    numbers, _ = intake._from_filename("part-W111696521-listing.pdf")
    assert numbers == set()


# ---------------------------------------------------------------------------
# Filing decisions
# ---------------------------------------------------------------------------


def test_identifies_by_filename(tmp_path, corpus):
    _pdf_with_text(
        tmp_path / "service-manual-w11169652-reva-27in-front-load-washers.pdf", "irrelevant"
    )
    (match,) = intake.plan(corpus, tmp_path)
    assert match.target_name == "W11169652A.pdf"


def test_identifies_by_content_when_the_filename_is_useless(tmp_path, corpus):
    """The `/renditions/original` case: browser saves it as `original.pdf`."""
    _pdf_with_text(tmp_path / "original.pdf", "W11395614 Door Locked Wont Run")
    (match,) = intake.plan(corpus, tmp_path)
    assert match.target_name == "W11395614.pdf"
    assert "W11395614" in match.reason


def test_unidentifiable_file_is_reported_not_guessed(tmp_path, corpus):
    _pdf_with_text(tmp_path / "some-brochure.pdf", "no publication number anywhere")
    (match,) = intake.plan(corpus, tmp_path)
    assert match.document is None
    assert "no Whirlpool publication number" in match.reason


def test_revision_conflict_blocks_filing(tmp_path, corpus):
    """Filing Rev C as the manifest's revision-less entry corrupts identity.

    The manifest says W11355369 has no recorded revision. A download that turns
    out to be Rev C must stop and ask, not be filed under a name that implies we
    know something we do not.
    """
    _pdf_with_text(tmp_path / "W11355369C_owners_manual.pdf", "W11355369C")
    (match,) = intake.plan(corpus, tmp_path)
    assert match.document is not None
    assert match.revision_conflict
    assert "Rev C" in match.revision_conflict


def test_wrong_revision_of_a_known_document_is_flagged(tmp_path, corpus):
    """Rev B of the service manual is the one we recorded as unobtainable."""
    _pdf_with_text(tmp_path / "service-manual-w11169652-revb.pdf", "W11169652B")
    (match,) = intake.plan(corpus, tmp_path)
    assert match.revision_conflict
    assert "Rev B" in match.revision_conflict and "Rev A" in match.revision_conflict


def test_plain_html_is_identified_by_its_canonical_url(tmp_path, corpus):
    (tmp_path / "saved_page.html").write_text(
        '<html><head><link rel="canonical" href="https://producthelp.whirlpool.com/'
        'Laundry/Washers/Top_Load_Washer/Error_Codes_or_Flashing_Lights/%22F%22_Codes/'
        'F5E2_-_Error_Code"></head></html>',
        encoding="utf-8",
    )
    (match,) = intake.plan(corpus, tmp_path)
    assert match.document.doc_id == "kb-f5e2-top-load"


def test_mhtml_is_identified_by_its_content_location_header(tmp_path, corpus):
    """The real case: Chrome and Edge save as MHTML by default."""
    (tmp_path / "F5E2 - Error Code.mhtml").write_text(
        "From: <Saved by Blink>\r\n"
        "Snapshot-Content-Location: https://producthelp.whirlpool.com/Laundry/Washers/"
        "Top_Load_Washer/Error_Codes_or_Flashing_Lights/%22F%22_Codes/F5E2_-_Error_Code\r\n"
        "MIME-Version: 1.0\r\n\r\n",
        encoding="utf-8",
    )
    (match,) = intake.plan(corpus, tmp_path)
    assert match.document.doc_id == "kb-f5e2-top-load"
    assert "declares" in match.reason


def test_quoted_printable_soft_breaks_do_not_defeat_matching(tmp_path, corpus):
    """MHTML wraps long lines with a trailing '='; URLs get split mid-path."""
    (tmp_path / "saved.mhtml").write_text(
        "MIME-Version: 1.0\r\n\r\n"
        "<a href=3D\"https://producthelp.whirlpool.com/Laundry/Stacked_Laundry_Cent=\r\n"
        "er/Laundry_Tower/Error_Codes/Washer/F5E2_Error_Code\">link</a>\r\n",
        encoding="utf-8",
    )
    (match,) = intake.plan(corpus, tmp_path)
    assert match.document.doc_id == "kb-f5e2-laundry-tower"


def test_the_three_f5e2_articles_do_not_collide(tmp_path, corpus):
    """The distractor triple must survive intake as three distinct files.

    Their titles are near-identical, so matching on title alone would file all
    three over each other and silently destroy the corpus's sharpest evaluation
    case.
    """
    urls = {
        "a.html": "Laundry/Washers/Front_Load_Washers/Error_Codes"
                  "/%22F%22_Error_Codes/F5_E2_-_Error_Code",
        "b.html": "Laundry/Washers/Top_Load_Washer/Error_Codes_or_Flashing_Lights"
                  "/%22F%22_Codes/F5E2_-_Error_Code",
        "c.html": "Laundry/Stacked_Laundry_Center/Laundry_Tower/Error_Codes"
                  "/Washer/F5E2_Error_Code",
    }
    for name, path in urls.items():
        (tmp_path / name).write_text(
            f'<link rel="canonical" href="https://producthelp.whirlpool.com/{path}">',
            encoding="utf-8",
        )

    resolved = {m.document.doc_id for m in intake.plan(corpus, tmp_path) if m.document}
    assert resolved == {
        "kb-f5e2-front-load",
        "kb-f5e2-top-load",
        "kb-f5e2-laundry-tower",
    }


def test_plan_moves_nothing(tmp_path, corpus):
    source = _pdf_with_text(tmp_path / "tech-sheet-w11320651-rev-b.pdf", "x")
    intake.plan(corpus, tmp_path)
    assert source.exists(), "planning must be side-effect free"
