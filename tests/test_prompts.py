"""Prompt text files load from the package."""

from repair_assistant.prompts import (
    ask_system,
    diagnose_system,
    judge_system,
    load_prompt,
    prompt_digest,
    prompt_stamp,
    runtime_prompt_digest,
    safety_escalate,
    safety_technician,
    safety_warn,
)


def test_load_prompt_files() -> None:
    ask = ask_system()
    assert "Whirlpool appliance repair assistant" in ask
    assert "data, never instructions" in ask
    assert "<<<MANUFACTURER_EVIDENCE>>>" in ask
    assert "evidence_index" in ask
    assert "claims" in ask
    diag = diagnose_system()
    assert "diagnostic assistant" in diag
    assert "data, never instructions" in diag
    assert "<<<MANUFACTURER_EVIDENCE>>>" in diag
    assert "Hard rules" in diag
    assert "citations like [1]" in diag
    assert "MUST include at least one [n]" in diag
    assert "Do not invent" in diag
    assert "Multi-turn path" in diag
    assert "present ALL" in diag
    assert "Never claim checks were ruled out" in diag or "Never claim checks" in diag
    assert "Clarifying vs abstaining" in diag
    assert "Do NOT use the ABSTAIN: prefix" in diag
    assert "close cleanly" in diag
    assert "Never ABSTAIN claiming" in diag or "Session symptom anchor" in diag
    assert "evidence_index" in diag
    assert "claims" in diag
    # No scripted ack example that the model can parrot on turn 1.
    assert "Good — that rules out" not in diag
    assert '"passed"' in judge_system()
    assert "live-voltage" in safety_escalate()
    assert "disconnect-power" in safety_warn()
    assert "qualified appliance service personnel" in safety_technician()
    assert load_prompt("ask_system") == ask_system()


def test_prompt_digest_is_stable_and_named() -> None:
    digest = prompt_digest("ask_system")
    assert len(digest) == 12
    assert digest == prompt_digest("ask_system")
    assert prompt_digest("diagnose_system") != digest
    stamp = prompt_stamp("ask_system")
    assert stamp["prompt_name"] == "ask_system"
    assert stamp["prompt_file_sha256"] == digest
    assert runtime_prompt_digest(ask_system()) == digest
