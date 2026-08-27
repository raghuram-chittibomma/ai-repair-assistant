"""Bounded chunk quality audit / repair (ADR-0022)."""

from __future__ import annotations

from repair_assistant.parsing.chunk_quality import (
    MAX_REPAIR_PASSES,
    audit_and_improve,
    audit_chunks,
    fingerprint,
)
from repair_assistant.parsing.models import Chunk


def _row(
    *,
    text: str,
    headers: list[str] | None = None,
    body: str | None = None,
    chunk_id: str = "p20-table_row-abc",
    error_codes: list[str] | None = None,
    publication_number: str | None = "W11169652",
) -> Chunk:
    meta: dict = {"body_text": body if body is not None else text}
    if headers is not None:
        meta["headers"] = headers
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        page=20,
        kind="table_row",
        error_codes=error_codes or [],
        publication_number=publication_number,
        revision="B",
        metadata=meta,
    )


def test_headers_in_meta_not_text_repaired_once():
    chunk = _row(
        text="70 | 21 | 3.4",
        body="70 | 21 | 3.4",
        headers=["Temp F", "Temp C", "Resistance kOhm"],
    )
    report0 = audit_chunks([chunk])
    assert any(f.code == "headers_in_meta_not_text" for f in report0.findings)

    improved, report1 = audit_and_improve([chunk])
    assert report1.repair_passes == MAX_REPAIR_PASSES
    assert report1.stop_reason in {"after_one_repair", "repair_ineffective"}
    assert "Temp F" in improved[0].text
    assert "70" in improved[0].text

    # Second improve must be a no-op (no further repair pass).
    fp = fingerprint(improved)
    again, report2 = audit_and_improve(improved)
    assert fingerprint(again) == fp
    assert report2.repair_passes == 0
    assert report2.stop_reason in {"clean", "no_repairable"}


def test_opaque_numeric_with_headers_is_repairable():
    chunk = _row(
        text="14 | -10 | 111.6",
        body="14 | -10 | 111.6",
        headers=["Temp F", "Temp C", "Resistance kOhm"],
    )
    _improved, report = audit_and_improve([chunk])
    assert report.repair_passes <= MAX_REPAIR_PASSES
    assert "Temp F" in _improved[0].text or report.stop_reason == "no_progress"


def test_error_code_unbound_is_flag_only_no_loop():
    chunk = _row(
        text="F6E1",
        body="F6E1",
        headers=["Error Code"],
        error_codes=["F6E1"],
        chunk_id="p8-table_row-codeonly",
    )
    improved, report = audit_and_improve([chunk])
    assert any(f.code == "error_code_unbound" for f in report.findings)
    assert all(f.code != "error_code_unbound" or not f.repairable for f in report.findings)
    # Body not paraphrased / merged.
    assert improved[0].metadata.get("body_text") == "F6E1"
    assert report.repair_passes <= MAX_REPAIR_PASSES


def test_audit_and_improve_call_budget():
    """Straight-line: never more than one repair; fingerprint stable on re-run."""
    chunk = _row(
        text="32 | 0 | 65.5",
        body="32 | 0 | 65.5",
        headers=["Temp F", "Temp C", "Resistance kOhm"],
    )
    a, r1 = audit_and_improve([chunk])
    assert r1.repair_passes <= 1
    b, r2 = audit_and_improve(a)
    assert r2.repair_passes == 0
    assert fingerprint(a) == fingerprint(b)
