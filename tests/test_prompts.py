"""Prompt text files load from the package."""

from repair_assistant.prompts import (
    ask_system,
    diagnose_system,
    judge_system,
    load_prompt,
    safety_escalate,
    safety_technician,
    safety_warn,
)


def test_load_prompt_files() -> None:
    assert "Whirlpool appliance repair assistant" in ask_system()
    diag = diagnose_system()
    assert "diagnostic assistant" in diag
    assert "Clarifying vs abstaining" in diag
    assert "Do NOT use the ABSTAIN: prefix" in diag
    assert "MUST include the concrete steps" in diag or "MUST quote the concrete steps" in diag
    assert "Do not invent button sequences" in diag
    assert '"passed"' in judge_system()
    assert "live-voltage" in safety_escalate()
    assert "disconnect-power" in safety_warn()
    assert "qualified appliance service personnel" in safety_technician()
    assert load_prompt("ask_system") == ask_system()
