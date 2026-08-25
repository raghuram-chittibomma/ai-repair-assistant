"""Retrieve evidence and generate a grounded answer via OpenAI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.store import Database
from repair_assistant.qa.context import (
    AnswerResult,
    Citation,
    citations_from_answer,
    format_evidence,
)
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.retrieval.search import search
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import assess_request, block_message

_SYSTEM = """You are a Whirlpool appliance repair assistant.

Answer the user's question using ONLY the numbered evidence blocks provided.
Every factual claim must be supported by at least one citation like [1] or [2].
Do not use outside knowledge or guess.

If the evidence is insufficient, contradictory for the stated appliance, or does not
address the question, respond with exactly:
ABSTAIN: <one sentence explaining what is missing>

When citing procedures involving live voltage, high voltage, or disassembly, preserve
any technician-only warnings present in the evidence.

When asked which service manual applies to a model, cite the service manual's
publication number (for example W11169652), not a service pointer that mentions it.

When evidence from a knowledge article points to installation instructions for the
root cause, prefer citing those installation instructions for installation-fault answers.
"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class OpenAIClient:
    api_key: str
    model: str

    def complete(self, system: str, user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()


def build_user_prompt(
    question: str,
    appliance: Appliance | None,
    evidence_text: str,
) -> str:
    lines = [f"Question: {question}"]
    if appliance:
        line = f"Appliance model: {appliance.model}"
        if appliance.serial:
            line += f"  Serial: {appliance.serial}"
        lines.append(line)
    lines.append("")
    lines.append("Evidence:")
    lines.append(evidence_text or "(none)")
    return "\n".join(lines)


def ask(
    db: Database,
    manifest: Manifest,
    question: str,
    *,
    appliance: Appliance | None = None,
    audience: Audience = Audience.OWNER,
    retrieval_limit: int = 8,
    overfetch: int = 40,
    llm: LLMClient | None = None,
) -> AnswerResult:
    """Retrieve applicable chunks, then generate a cited answer or abstain."""
    assessment = assess_request(question, audience=audience)
    if assessment.action == SafetyAction.BLOCK:
        return AnswerResult(
            question=question,
            answer=block_message(assessment),
            abstained=True,
            abstain_reason=assessment.reason,
            citations=[],
            retrieval_count=0,
            safety_action=assessment.action.value,
            safety_notice=assessment.reason,
            escalated=True,
        )

    result = search(
        db,
        manifest,
        question,
        appliance=appliance,
        limit=retrieval_limit,
        overfetch=overfetch,
    )

    if not result.hits:
        return AnswerResult(
            question=question,
            answer="",
            abstained=True,
            abstain_reason="No applicable manufacturer evidence was retrieved.",
            citations=[],
            retrieval_count=0,
            safety_action=assessment.action.value,
            safety_notice=assessment.reason,
        )

    evidence_text, available = format_evidence(result.hits)
    system = _SYSTEM
    if assessment.prompt_directive:
        system = f"{_SYSTEM}\n\n{assessment.prompt_directive}"
    llm = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
    raw = llm.complete(system, build_user_prompt(question, appliance, evidence_text))

    if raw.upper().startswith("ABSTAIN:"):
        return AnswerResult(
            question=question,
            answer=raw,
            abstained=True,
            abstain_reason=raw.split(":", 1)[-1].strip(),
            citations=[],
            retrieval_count=len(result.hits),
            safety_action=assessment.action.value,
            safety_notice=assessment.reason,
        )

    gated = gate_answer(assessment, raw, evidence_text=evidence_text)
    cited = [] if gated.blocked else citations_from_answer(gated.text, available)
    return AnswerResult(
        question=question,
        answer=gated.text,
        abstained=gated.blocked,
        abstain_reason=gated.notice if gated.blocked else "",
        citations=cited,
        retrieval_count=len(result.hits),
        safety_action=gated.action.value,
        safety_notice=gated.notice,
        escalated=gated.escalated,
    )


# Re-export for convenience
__all__ = ["AnswerResult", "Citation", "OpenAIClient", "ask", "build_user_prompt"]
