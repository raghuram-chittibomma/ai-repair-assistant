"""Retrieve evidence and generate a grounded answer via OpenAI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.ingest.store import Database
from repair_assistant.observability.langfuse_tracing import observation, update_span
from repair_assistant.prompts import ask_system
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


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class StreamingLLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...

    def stream(self, system: str, user: str) -> Any: ...


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

    def stream(self, system: str, user: str):
        """Yield text deltas from OpenAI chat completions."""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            stream=True,
        )
        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text


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
    model_name = getattr(llm, "model", None) if llm is not None else None
    if model_name is None:
        try:
            model_name = llm_model()
        except Exception:
            model_name = None
    meta = {
        "audience": audience.value,
        "appliance_model": appliance.model if appliance else None,
        "appliance_serial": appliance.serial if appliance else None,
        "llm_model": model_name,
    }
    started = time.perf_counter()
    with observation("ask", input={"question": question}, metadata=meta) as span:
        outcome = _ask_impl(
            db,
            manifest,
            question,
            appliance=appliance,
            audience=audience,
            retrieval_limit=retrieval_limit,
            overfetch=overfetch,
            llm=llm,
        )
        update_span(
            span,
            output={
                "abstained": outcome.abstained,
                "answer_preview": (outcome.answer or "")[:500],
                "citations": [c.label for c in outcome.citations],
                "retrieval_count": outcome.retrieval_count,
                "safety_action": outcome.safety_action,
                "escalated": outcome.escalated,
            },
            metadata={
                **meta,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "abstain_reason": outcome.abstain_reason,
            },
        )
        return outcome


def _ask_impl(
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

    evidence_text, available = format_evidence(result.hits, query=question)
    system = ask_system()
    if assessment.prompt_directive:
        system = f"{system}\n\n{assessment.prompt_directive}"
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


def ask_stream(
    db: Database,
    manifest: Manifest,
    question: str,
    *,
    appliance: Appliance | None = None,
    audience: Audience = Audience.OWNER,
    retrieval_limit: int = 8,
    overfetch: int = 40,
    llm: OpenAIClient | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield SSE-friendly events: status, token deltas, then done."""
    assessment = assess_request(question, audience=audience)
    if assessment.action == SafetyAction.BLOCK:
        yield {
            "type": "done",
            "question": question,
            "answer": block_message(assessment),
            "abstained": True,
            "abstain_reason": assessment.reason,
            "citations": [],
            "retrieval_count": 0,
            "safety_action": assessment.action.value,
            "safety_notice": assessment.reason,
            "escalated": True,
        }
        return

    yield {"type": "status", "phase": "retrieving"}
    result = search(
        db,
        manifest,
        question,
        appliance=appliance,
        limit=retrieval_limit,
        overfetch=overfetch,
    )
    if not result.hits:
        yield {
            "type": "done",
            "question": question,
            "answer": "",
            "abstained": True,
            "abstain_reason": "No applicable manufacturer evidence was retrieved.",
            "citations": [],
            "retrieval_count": 0,
            "safety_action": assessment.action.value,
            "safety_notice": assessment.reason,
            "escalated": False,
        }
        return

    evidence_text, available = format_evidence(result.hits, query=question)
    system = ask_system()
    if assessment.prompt_directive:
        system = f"{system}\n\n{assessment.prompt_directive}"
    client = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
    yield {
        "type": "status",
        "phase": "generating",
        "retrieval_count": len(result.hits),
    }

    parts: list[str] = []
    for delta in client.stream(system, build_user_prompt(question, appliance, evidence_text)):
        parts.append(delta)
        yield {"type": "token", "text": delta}

    raw = "".join(parts).strip()
    if raw.upper().startswith("ABSTAIN:"):
        yield {
            "type": "done",
            "question": question,
            "answer": raw,
            "abstained": True,
            "abstain_reason": raw.split(":", 1)[-1].strip(),
            "citations": [],
            "retrieval_count": len(result.hits),
            "safety_action": assessment.action.value,
            "safety_notice": assessment.reason,
            "escalated": False,
        }
        return

    gated = gate_answer(assessment, raw, evidence_text=evidence_text)
    cited = [] if gated.blocked else citations_from_answer(gated.text, available)
    yield {
        "type": "done",
        "question": question,
        "answer": gated.text,
        "abstained": gated.blocked,
        "abstain_reason": gated.notice if gated.blocked else "",
        "citations": [
            {
                "index": c.index,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "label": c.label,
                "page": c.page,
            }
            for c in cited
        ],
        "retrieval_count": len(result.hits),
        "safety_action": gated.action.value,
        "safety_notice": gated.notice,
        "escalated": gated.escalated,
    }


__all__ = [
    "AnswerResult",
    "Citation",
    "OpenAIClient",
    "ask",
    "ask_stream",
    "build_user_prompt",
]
