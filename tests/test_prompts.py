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
    assert "diagnostic assistant" in diagnose_system()
    assert '"passed"' in judge_system()
    assert "live-voltage" in safety_escalate()
    assert "disconnect-power" in safety_warn()
    assert "qualified appliance service personnel" in safety_technician()
    assert load_prompt("ask_system") == ask_system()
