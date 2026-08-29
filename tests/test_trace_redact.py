"""Optional serial redaction for Langfuse payloads (review R44)."""

from __future__ import annotations

from repair_assistant.observability.redact import redact_for_trace


def test_redaction_is_off_by_default(monkeypatch) -> None:
    monkeypatch.setattr("repair_assistant.observability.redact.load_dotenv_files", lambda: None)
    monkeypatch.delenv("REPAIR_TRACE_REDACT_SERIAL", raising=False)
    payload = {"question": "serial CF82012345", "appliance_serial": "CF82012345"}
    assert redact_for_trace(payload) == payload


def test_redacts_serial_field_and_token(monkeypatch) -> None:
    monkeypatch.setattr("repair_assistant.observability.redact.load_dotenv_files", lambda: None)
    monkeypatch.setenv("REPAIR_TRACE_REDACT_SERIAL", "1")
    payload = {
        "question": "Washer CF82012345 will not spin",
        "appliance_serial": "CF82012345",
        "appliance_model": "WFW5620HW0",
    }
    out = redact_for_trace(payload)
    assert out["appliance_serial"] == "[serial]"
    assert "CF82012345" not in out["question"]
    assert "[serial]" in out["question"]
    assert out["appliance_model"] == "WFW5620HW0"


def test_does_not_redact_publication_numbers(monkeypatch) -> None:
    monkeypatch.setattr("repair_assistant.observability.redact.load_dotenv_files", lambda: None)
    monkeypatch.setenv("REPAIR_TRACE_REDACT_SERIAL", "1")
    text = "See W11320651 page 4"
    assert redact_for_trace(text) == text


def test_prepare_trace_value_redacts_after_truncate(monkeypatch) -> None:
    from repair_assistant.observability.langfuse_tracing import prepare_trace_value

    monkeypatch.setattr("repair_assistant.observability.redact.load_dotenv_files", lambda: None)
    monkeypatch.setenv("REPAIR_TRACE_REDACT_SERIAL", "1")
    out = prepare_trace_value({"serial": "AB12345678", "note": "AB12345678 door"})
    assert out["serial"] == "[serial]"
    assert "AB12345678" not in out["note"]
