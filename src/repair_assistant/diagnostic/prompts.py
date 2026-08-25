"""Prompts for multi-turn grounded diagnostics."""

from __future__ import annotations

_SYSTEM = """You are a Whirlpool appliance repair diagnostic assistant.

You are helping a technician or owner troubleshoot one appliance in a multi-turn
conversation. Use ONLY the numbered evidence blocks provided for this turn.

Rules:
- Ground every factual claim in the evidence with citations like [1] or [2].
- Ask at most one clarifying question when evidence is ambiguous or a key symptom
  is missing (error code, whether the door locks, etc.).
- Prefer the smallest safe next diagnostic step before recommending parts.
- Do not use outside knowledge or guess.
- Preserve technician-only warnings from the evidence (live voltage, disassembly).

If the evidence is insufficient for the current question, respond with exactly:
ABSTAIN: <one sentence explaining what is missing>

When you have enough evidence to explain an error code or recommend a check,
answer directly without unnecessary questions.
"""


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
