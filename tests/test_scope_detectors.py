"""ADR-0025 deferral detectors."""

from __future__ import annotations

from repair_assistant.observability.scope_detectors import (
    configured_worker_count,
    curation_scale_notice,
    worker_count_warning,
)


def test_worker_count_warning_silent_at_one(monkeypatch) -> None:
    monkeypatch.delenv("REPAIR_API_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert configured_worker_count() == 1
    assert worker_count_warning(1) is None


def test_worker_count_warning_fires_above_one(monkeypatch) -> None:
    monkeypatch.setenv("REPAIR_API_WORKERS", "4")
    assert configured_worker_count() == 4
    text = worker_count_warning()
    assert text is not None
    assert "R32" in text
    assert "4" in text


def test_curation_scale_notice_threshold() -> None:
    assert curation_scale_notice(20) is None
    assert curation_scale_notice(50) is None
    text = curation_scale_notice(51)
    assert text is not None
    assert "51" in text
    assert "R47" in text
