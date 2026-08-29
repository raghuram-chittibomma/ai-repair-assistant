"""Audience claim logging (review R2). Verification is a non-goal."""

from __future__ import annotations

import logging

from repair_assistant.safety.audience_claim import (
    TECHNICIAN_ATTESTATION_NOTICE,
    record_audience_claim,
)
from repair_assistant.safety.models import Audience


def test_owner_claim_is_unverified_and_not_attested() -> None:
    meta = record_audience_claim(Audience.OWNER)
    assert meta == {
        "audience": "owner",
        "audience_verified": False,
        "technician_attested": False,
    }


def test_technician_claim_is_logged_and_never_verified(caplog) -> None:
    caplog.set_level(logging.INFO, logger="repair_assistant.safety")
    meta = record_audience_claim(
        Audience.TECHNICIAN, attested=True, source="ui"
    )
    assert meta["audience"] == "technician"
    assert meta["audience_verified"] is False
    assert meta["technician_attested"] is True
    assert "audience_claim" in caplog.text
    assert "attested=True" in caplog.text
    assert "verified=false" in caplog.text
    assert "source=ui" in caplog.text


def test_technician_without_attestation_stays_unverified() -> None:
    meta = record_audience_claim("technician")
    assert meta["audience_verified"] is False
    assert meta["technician_attested"] is False


def test_attestation_notice_names_the_limit() -> None:
    assert "not verified" in TECHNICIAN_ATTESTATION_NOTICE.lower()
    assert "TEST" in TECHNICIAN_ATTESTATION_NOTICE


def test_ask_request_accepts_attestation_flag() -> None:
    from repair_assistant.api.schemas import AskRequest

    body = AskRequest(question="F5E2", audience="technician", technician_attested=True)
    assert body.audience == "technician"
    assert body.technician_attested is True
    assert AskRequest(question="F5E2").technician_attested is False
