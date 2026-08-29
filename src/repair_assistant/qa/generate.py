"""Retrieve evidence and generate a grounded answer via OpenAI."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.corpus.support import (
    ABSTAIN_NO_EVIDENCE,
    ABSTAIN_UNSUPPORTED_MODEL,
    corpus_supports_appliance,
    no_evidence_message,
    unsupported_appliance_message,
)
from repair_assistant.ingest.store import Database
from repair_assistant.observability.langfuse_tracing import (
    child_observation,
    generation,
    observation,
    update_span,
)
from repair_assistant.prompts import ask_system
from repair_assistant.qa.acks import ACK_IN_ASK_MODE, is_ack_only_message
from repair_assistant.qa.context import (
    AnswerResult,
    Citation,
    citations_from_answer,
    format_evidence,
    format_label,
)
from repair_assistant.qa.env import llm_model, llm_timeout_seconds, openai_api_key
from repair_assistant.retrieval.search import search
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction
from repair_assistant.safety.policy import (
    apply_owner_evidence_policy,
    assess_request,
    block_message,
)
from repair_assistant.safety.stream_gate import StreamGate, may_stream


class LLMTimeoutError(TimeoutError):
    """OpenAI request exceeded LLM_TIMEOUT_SECONDS (or client timeout)."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class StreamingLLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...

    def stream(self, system: str, user: str) -> Any: ...


@dataclass
class OpenAIClient:
    api_key: str
    model: str
    timeout: float | None = None

    def _timeout_seconds(self) -> float:
        if self.timeout is not None:
            return float(self.timeout)
        return llm_timeout_seconds()

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self.api_key, timeout=self._timeout_seconds())

    def complete(self, system: str, user: str) -> str:
        from openai import APITimeoutError

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        with generation(
            "llm",
            model=self.model,
            input={"messages": messages},
        ) as span:
            client = self._client()
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2,
                )
            except APITimeoutError as exc:
                raise LLMTimeoutError(
                    f"OpenAI request timed out after {self._timeout_seconds():g}s"
                ) from exc
            text = (response.choices[0].message.content or "").strip()
            update_span(span, output={"content": text})
            return text

    def stream(self, system: str, user: str):
        """Yield text deltas from OpenAI chat completions."""
        from openai import APITimeoutError

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        with generation(
            "llm",
            model=self.model,
            input={"messages": messages, "stream": True},
        ) as span:
            client = self._client()
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.2,
                    stream=True,
                )
                parts: list[str] = []
                for chunk in response:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    text = getattr(delta, "content", None) if delta is not None else None
                    if text:
                        parts.append(text)
                        yield text
                update_span(span, output={"content": "".join(parts).strip()})
            except APITimeoutError as exc:
                raise LLMTimeoutError(
                    f"OpenAI request timed out after {self._timeout_seconds():g}s"
                ) from exc


def build_user_prompt(
    question: str,
    appliance: Appliance | None,
    evidence_text: str,
    *,
    user_codes: tuple[str, ...] | list[str] | None = None,
    plan_codes: tuple[str, ...] | list[str] | None = None,
) -> str:
    from repair_assistant.retrieval.planner import provenance_prompt_block

    lines = [f"Question: {question}"]
    if appliance:
        line = f"Appliance model: {appliance.model}"
        if appliance.serial:
            line += f"  Serial: {appliance.serial}"
        lines.append(line)
    uc = tuple(user_codes or ())
    pc = tuple(plan_codes or ())
    if uc or pc:
        lines.append("")
        lines.append(provenance_prompt_block(user_codes=uc, plan_codes=pc))
    lines.append("")
    lines.append("Evidence:")
    lines.append(evidence_text or "(none)")
    return "\n".join(lines)


def _unsupported_appliance_answer(
    question: str,
    appliance: Appliance,
    *,
    assessment,
) -> AnswerResult:
    msg = unsupported_appliance_message(appliance)
    return AnswerResult(
        question=question,
        answer=msg,
        abstained=True,
        abstain_reason="This model is not covered by our documentation set.",
        abstain_code=ABSTAIN_UNSUPPORTED_MODEL,
        citations=[],
        retrieval_count=0,
        safety_action=assessment.action.value,
        safety_notice=assessment.reason,
    )


def _no_evidence_answer(question: str, appliance: Appliance | None, *, assessment) -> AnswerResult:
    msg = no_evidence_message(appliance)
    return AnswerResult(
        question=question,
        answer=msg,
        abstained=True,
        abstain_reason="No matching manufacturer evidence for this question.",
        abstain_code=ABSTAIN_NO_EVIDENCE,
        citations=[],
        retrieval_count=0,
        safety_action=assessment.action.value,
        safety_notice=assessment.reason,
    )


def _stream_done_unsupported(question: str, appliance: Appliance, *, assessment) -> dict[str, Any]:
    msg = unsupported_appliance_message(appliance)
    return {
        "type": "done",
        "question": question,
        "answer": msg,
        "abstained": True,
        "abstain_reason": "This model is not covered by our documentation set.",
        "abstain_code": ABSTAIN_UNSUPPORTED_MODEL,
        "citations": [],
        "retrieval_count": 0,
        "safety_action": assessment.action.value,
        "safety_notice": assessment.reason,
        "escalated": False,
    }


def _stream_done_no_evidence(question: str, appliance: Appliance | None, *, assessment) -> dict[str, Any]:
    msg = no_evidence_message(appliance)
    return {
        "type": "done",
        "question": question,
        "answer": msg,
        "abstained": True,
        "abstain_reason": "No matching manufacturer evidence for this question.",
        "abstain_code": ABSTAIN_NO_EVIDENCE,
        "citations": [],
        "retrieval_count": 0,
        "safety_action": assessment.action.value,
        "safety_notice": assessment.reason,
        "escalated": False,
    }


def _trace_safety_assess(question: str, audience: Audience, assessment) -> None:
    with child_observation(
        "safety_assess",
        input={"question": question, "audience": audience.value},
    ) as span:
        update_span(
            span,
            output={
                "action": assessment.action.value,
                "rule_id": assessment.rule_id,
                "reason": assessment.reason,
                "prompt_directive": assessment.prompt_directive,
            },
        )


def _trace_evidence(hits, *, query: str) -> tuple[str, list[Citation]]:
    evidence_text, available = format_evidence(hits, query=query)
    _trace_evidence_prompt(
        evidence_text,
        retrieval_count=len(hits),
        labels=[format_label(h) for h in hits],
    )
    return evidence_text, available


def _trace_evidence_prompt(
    evidence_text: str,
    *,
    retrieval_count: int,
    labels: list[str] | None = None,
) -> None:
    with child_observation(
        "evidence",
        input={"retrieval_count": retrieval_count},
        metadata={"citation_labels": labels or []},
    ) as span:
        update_span(span, output={"evidence_text": evidence_text})


def _trace_gate(assessment, raw: str, evidence_text: str):
    gated = gate_answer(assessment, raw, evidence_text=evidence_text)
    with child_observation(
        "safety_gate",
        input={"raw_answer_preview": raw[:500]},
    ) as span:
        update_span(
            span,
            output={
                "blocked": gated.blocked,
                "action": gated.action.value,
                "notice": gated.notice,
                "escalated": gated.escalated,
                "text_preview": gated.text[:500],
            },
        )
    return gated


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



def _clarification_result(question: str, clarify: str, *, assessment) -> AnswerResult:
    return AnswerResult(
        question=question,
        answer=clarify,
        abstained=False,
        abstain_reason="",
        abstain_code="clarify",
        citations=[],
        retrieval_count=0,
        safety_action=assessment.action.value,
        safety_notice=assessment.reason,
        escalated=False,
    )


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
    from repair_assistant.retrieval.intent import extract_intent, intent_to_dict
    from repair_assistant.retrieval.planner import (
        check_evidence_fit,
        plan_retrieval,
        plan_to_dict,
    )

    assessment = assess_request(question, audience=audience)
    _trace_safety_assess(question, audience, assessment)
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

    if appliance is not None and not corpus_supports_appliance(manifest, appliance).supported:
        return _unsupported_appliance_answer(question, appliance, assessment=assessment)

    if is_ack_only_message(question):
        return _clarification_result(question, ACK_IN_ASK_MODE, assessment=assessment)

    intent = extract_intent(question, audience=audience.value)
    if intent.needs_clarification and intent.clarify_question:
        with child_observation(
            "intent",
            input={"question": question},
            metadata={"audience": audience.value},
        ) as span:
            update_span(span, output=intent_to_dict(intent))
        return _clarification_result(question, intent.clarify_question, assessment=assessment)

    plan = plan_retrieval(intent)
    with child_observation(
        "retrieval_plan",
        input={"question": question},
        metadata={"audience": audience.value},
    ) as span:
        update_span(span, output=plan_to_dict(plan))

    result = search(
        db,
        manifest,
        question,
        appliance=appliance,
        limit=retrieval_limit,
        overfetch=overfetch,
        audience=audience.value,
        plan=plan,
    )

    if not result.hits:
        return _no_evidence_answer(question, appliance, assessment=assessment)

    fit = check_evidence_fit(intent, [h.text for h in result.hits])
    if not fit.ok and fit.clarify_question:
        return _clarification_result(question, fit.clarify_question, assessment=assessment)

    evidence_text, available = _trace_evidence(result.hits, query=question)
    assessment = apply_owner_evidence_policy(assessment, evidence_text)
    system = ask_system()
    if assessment.prompt_directive:
        system = f"{system}\n\n{assessment.prompt_directive}"
    llm = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
    user_prompt = build_user_prompt(
        question,
        appliance,
        evidence_text,
        user_codes=plan.user_codes,
        plan_codes=plan.plan_codes,
    )
    raw = llm.complete(system, user_prompt)

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
            escalated=False,
        )

    gated = _trace_gate(assessment, raw, evidence_text)
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
        "stream": True,
    }
    started = time.perf_counter()

    def _events() -> Iterator[dict[str, Any]]:
        assessment = assess_request(question, audience=audience)
        _trace_safety_assess(question, audience, assessment)
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

        if appliance is not None and not corpus_supports_appliance(manifest, appliance).supported:
            yield _stream_done_unsupported(question, appliance, assessment=assessment)
            return

        if is_ack_only_message(question):
            yield {
                "type": "done",
                "question": question,
                "answer": ACK_IN_ASK_MODE,
                "abstained": False,
                "abstain_reason": "",
                "abstain_code": "clarify",
                "citations": [],
                "retrieval_count": 0,
                "safety_action": assessment.action.value,
                "safety_notice": assessment.reason,
                "escalated": False,
            }
            return

        from repair_assistant.retrieval.intent import extract_intent, intent_to_dict
        from repair_assistant.retrieval.planner import (
            check_evidence_fit,
            plan_retrieval,
            plan_to_dict,
        )

        intent = extract_intent(question, audience=audience.value)
        if intent.needs_clarification and intent.clarify_question:
            with child_observation(
                "intent",
                input={"question": question},
                metadata={"audience": audience.value},
            ) as span:
                update_span(span, output=intent_to_dict(intent))
            yield {
                "type": "done",
                "question": question,
                "answer": intent.clarify_question,
                "abstained": False,
                "abstain_reason": "",
                "abstain_code": "clarify",
                "citations": [],
                "retrieval_count": 0,
                "safety_action": assessment.action.value,
                "safety_notice": assessment.reason,
                "escalated": False,
            }
            return

        plan = plan_retrieval(intent)
        with child_observation(
            "retrieval_plan",
            input={"question": question},
            metadata={"audience": audience.value},
        ) as span:
            update_span(span, output=plan_to_dict(plan))

        yield {"type": "status", "phase": "retrieving"}
        result = search(
            db,
            manifest,
            question,
            appliance=appliance,
            limit=retrieval_limit,
            overfetch=overfetch,
            audience=audience.value,
            plan=plan,
        )
        if not result.hits:
            yield _stream_done_no_evidence(question, appliance, assessment=assessment)
            return

        fit = check_evidence_fit(intent, [h.text for h in result.hits])
        if not fit.ok and fit.clarify_question:
            yield {
                "type": "done",
                "question": question,
                "answer": fit.clarify_question,
                "abstained": False,
                "abstain_reason": "",
                "abstain_code": "clarify",
                "citations": [],
                "retrieval_count": len(result.hits),
                "safety_action": assessment.action.value,
                "safety_notice": assessment.reason,
                "escalated": False,
            }
            return

        evidence_text, available = _trace_evidence(result.hits, query=question)
        assessment = apply_owner_evidence_policy(assessment, evidence_text)
        system = ask_system()
        if assessment.prompt_directive:
            system = f"{system}\n\n{assessment.prompt_directive}"
        client = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
        user_prompt = build_user_prompt(
            question,
            appliance,
            evidence_text,
            user_codes=plan.user_codes,
            plan_codes=plan.plan_codes,
        )
        yield {
            "type": "status",
            "phase": "generating",
            "retrieval_count": len(result.hits),
        }

        # R1: never emit a token the post-LLM gate has not cleared. When the
        # assessment already decides the outcome, withhold tokens entirely.
        stream_tokens = may_stream(assessment)
        stream_gate = StreamGate(assessment)
        for delta in client.stream(system, user_prompt):
            safe = stream_gate.push(delta)
            if safe and stream_tokens:
                yield {"type": "token", "text": safe}
        tail = stream_gate.finish()
        if tail and stream_tokens:
            yield {"type": "token", "text": tail}

        raw = stream_gate.accumulated.strip()
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

        gated = _trace_gate(assessment, raw, evidence_text)
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

    with observation("ask", input={"question": question, "stream": True}, metadata=meta) as span:
        final: dict[str, Any] | None = None
        for event in _events():
            if event.get("type") == "done":
                final = event
            yield event
        if final is not None:
            update_span(
                span,
                output={
                    "abstained": final.get("abstained"),
                    "answer_preview": (final.get("answer") or "")[:500],
                    "citations": [
                        c.get("label") for c in final.get("citations") or [] if isinstance(c, dict)
                    ],
                    "retrieval_count": final.get("retrieval_count"),
                    "safety_action": final.get("safety_action"),
                    "escalated": final.get("escalated"),
                },
                metadata={
                    **meta,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "abstain_reason": final.get("abstain_reason"),
                },
            )


__all__ = [
    "AnswerResult",
    "Citation",
    "LLMTimeoutError",
    "OpenAIClient",
    "ask",
    "ask_stream",
    "build_user_prompt",
]
