"""Prompts for multi-turn grounded diagnostics.

System text lives in ``repair_assistant/prompts/diagnose_system.txt``.
"""

from __future__ import annotations


def build_diagnostic_user_prompt(
    *,
    appliance_model: str | None,
    appliance_serial: str | None,
    evidence_text: str,
    transcript: str,
) -> str:
    lines: list[str] = []
    if appliance_model:
        line = f"Appliance model: {appliance_model}"
        if appliance_serial:
            line += f"  Serial: {appliance_serial}"
        lines.append(line)
    lines.append("")
    lines.append("Conversation so far:")
    lines.append(transcript or "(start of session)")
    lines.append("")
    lines.append("Evidence for this turn:")
    lines.append(evidence_text or "(none)")
    return "\n".join(lines)
