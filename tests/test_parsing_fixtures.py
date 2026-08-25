"""Fixture registry tests that do not require manufacturer PDFs."""

from pathlib import Path

from repair_assistant.parsing import bench


def test_fixtures_file_is_well_formed():
    data = bench.load_fixtures()
    assert data["version"] == 1
    ids = [f["id"] for f in data["fixtures"]]
    assert ids == [
        "error-codes-bound",
        "pua-list-markers",
        "near-dup-stable",
        "reflow-not-delta",
        "tsp-trilingual",
        "mhtml-decode",
    ]
    assert "F6E1" in data["error_codes_w11320651b"]
    assert "F6E1" in data["must_bind"]


def test_scorecard_markdown_renders():
    fake = [
        bench.FixtureResult(
            fixture_id="error-codes-bound",
            extractor="pypdf",
            strategy="naive_fixed",
            passed=False,
            asserts=[bench.AssertResult("codes_bound", False, "unbound=['F6E1']")],
        )
    ]
    md = bench.scorecard_markdown(fake)
    assert "FAIL" in md
    assert "pypdf" in md


def test_committed_scorecard_exists():
    root = Path(__file__).resolve().parents[1]
    scorecard = root / "evals" / "parsing" / "results" / "scorecard.md"
    assert scorecard.is_file()
    text = scorecard.read_text(encoding="utf-8")
    assert "pdfplumber" in text
    assert "error-codes-bound" in text
