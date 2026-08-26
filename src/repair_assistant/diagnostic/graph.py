"""LangGraph workflow: assess safety, retrieve evidence, respond."""

from __future__ import annotations

from typing import Any, Iterator

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.corpus.support import (
    ABSTAIN_NO_EVIDENCE,
    ABSTAIN_UNSUPPORTED_MODEL,
    corpus_supports_appliance,
    no_evidence_message,
    unsupported_appliance_message,
)
from repair_assistant.diagnostic.prompts import build_diagnostic_user_prompt
from repair_assistant.prompts import diagnose_system
from repair_assistant.diagnostic.state import DiagnosticGraphState
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.qa.context import citations_from_answer, format_evidence
from repair_assistant.qa.generate import LLMClient, OpenAIClient, _trace_evidence_prompt, _trace_gate
from repair_assistant.observability.langfuse_tracing import child_observation, update_span
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.retrieval.search import search
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment
from repair_assistant.safety.policy import assess_request, block_message


def _latest_ai(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return str(msg.content)
    return ""


def _apply_delta(state: DiagnosticGraphState, delta: dict) -> DiagnosticGraphState:
    new: DiagnosticGraphState = dict(state)  # type: ignore[assignment]
    for key, value in delta.items():
        if key == "messages":
            new["messages"] = [*new.get("messages", []), *value]
        else:
            new[key] = value  # type: ignore[literal-required]
    return new


def _done_payload(
    state: DiagnosticGraphState,
    assistant: str,
    *,
    abstain_code: str = "",
) -> dict[str, Any]:
    abstained = bool(state.get("abstained"))
    cited = [] if abstained else citations_for_turn(state, assistant)
    return {
        "type": "done",
        "assistant_message": assistant,
        "abstained": abstained,
        "abstain_reason": state.get("abstain_reason") or "",
        "abstain_code": abstain_code,
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
        "retrieval_count": int(state.get("retrieval_count") or 0),
        "safety_action": state.get("safety_action", SafetyAction.ALLOW.value),
        "safety_notice": state.get("safety_notice") or "",
        "escalated": bool(state.get("escalated")),
        "_state": state,
    }


def _latest_human(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and msg.content:
            return str(msg.content)
    return ""


def _transcript(messages: list) -> str:
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            lines.append(f"Assistant: {msg.content}")
    return "\n".join(lines)


def _retrieval_query(messages: list) -> str:
    parts: list[str] = []
    codes: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.content:
            text = str(msg.content)
            parts.append(text)
            codes.extend(extract_error_codes(text))
    query = parts[-1] if parts else ""
    if codes:
        unique = sorted(set(codes))
        query = f"{' '.join(unique)} {query}".strip()
    return query


def make_assess_node():
    def assess(state: DiagnosticGraphState) -> dict:
        audience = Audience(state.get("audience") or Audience.OWNER.value)
        question = _latest_human(state["messages"])
        assessment = assess_request(question, audience=audience)
        blocked = assessment.action == SafetyAction.BLOCK
        return {
            "safety_action": assessment.action.value,
            "safety_notice": assessment.reason,
            "safety_rule_id": assessment.rule_id,
            "prompt_directive": assessment.prompt_directive,
            "escalated": blocked or assessment.action == SafetyAction.ESCALATE,
            "abstained": blocked,
            "abstain_reason": assessment.reason if blocked else "",
        }

    return assess


def make_blocked_node():
    def blocked(state: DiagnosticGraphState) -> dict:
        assessment = SafetyAssessment(
            action=SafetyAction.BLOCK,
            rule_id=state.get("safety_rule_id") or "blocked",
            reason=state.get("safety_notice") or "",
            audience=Audience(state.get("audience") or Audience.OWNER.value),
        )
        content = block_message(assessment)
        return {
            "messages": [AIMessage(content=content)],
            "abstained": True,
            "abstain_reason": assessment.reason,
            "escalated": True,
            "retrieval_count": 0,
        }

    return blocked


def make_retrieve_node(db: Database, manifest: Manifest, *, retrieval_limit: int, overfetch: int):
    def retrieve(state: DiagnosticGraphState) -> dict:
        query = _retrieval_query(state["messages"])
        appliance = None
        if state.get("appliance_model"):
            appliance = Appliance(
                model=state["appliance_model"],
                serial=state.get("appliance_serial"),
            )
        result = search(
            db,
            manifest,
            query,
            appliance=appliance,
            limit=retrieval_limit,
            overfetch=overfetch,
        )
        if not result.hits:
            return {
                "retrieval_query": query,
                "evidence_text": "",
                "citations_available": [],
                "retrieval_count": 0,
                "abstained": True,
                "abstain_reason": "No matching manufacturer evidence for this question.",
            }
        evidence_text, citations = format_evidence(result.hits)
        return {
            "retrieval_query": query,
            "evidence_text": evidence_text,
            "citations_available": citations,
            "retrieval_count": len(result.hits),
            "abstained": False,
            "abstain_reason": "",
        }

    return retrieve


def make_respond_node(llm: LLMClient):
    def respond(state: DiagnosticGraphState) -> dict:
        if state.get("abstained") and not state.get("evidence_text"):
            appliance = None
            if state.get("appliance_model"):
                appliance = Appliance(
                    model=state["appliance_model"],
                    serial=state.get("appliance_serial"),
                )
            content = no_evidence_message(appliance)
            return {
                "messages": [AIMessage(content=content)],
                "abstained": True,
                "abstain_reason": "No matching manufacturer evidence for this question.",
            }

        assessment = SafetyAssessment(
            action=SafetyAction(state.get("safety_action") or SafetyAction.ALLOW.value),
            rule_id=state.get("safety_rule_id") or "allow",
            reason=state.get("safety_notice") or "",
            audience=Audience(state.get("audience") or Audience.OWNER.value),
            prompt_directive=state.get("prompt_directive") or "",
        )
        system = diagnose_system()
        if assessment.prompt_directive:
            system = f"{system}\n\n{assessment.prompt_directive}"

        user_prompt = build_diagnostic_user_prompt(
            appliance_model=state.get("appliance_model"),
            appliance_serial=state.get("appliance_serial"),
            evidence_text=state.get("evidence_text", ""),
            transcript=_transcript(state["messages"]),
        )
        raw = llm.complete(system, user_prompt)
        if raw.upper().startswith("ABSTAIN:"):
            reason = raw.split(":", 1)[-1].strip()
            return {
                "messages": [AIMessage(content=raw)],
                "abstained": True,
                "abstain_reason": reason,
            }

        gated = gate_answer(
            assessment,
            raw,
            evidence_text=state.get("evidence_text", ""),
        )
        return {
            "messages": [AIMessage(content=gated.text)],
            "abstained": gated.blocked,
            "abstain_reason": gated.notice if gated.blocked else "",
            "safety_action": gated.action.value,
            "safety_notice": gated.notice,
            "escalated": gated.escalated,
        }

    return respond


def diagnose_turn_stream(
    db: Database,
    manifest: Manifest,
    state: DiagnosticGraphState,
    *,
    llm: OpenAIClient | None = None,
    retrieval_limit: int = 8,
    overfetch: int = 40,
) -> Iterator[dict[str, Any]]:
    """Yield SSE events for one turn: status, token deltas, then done."""
    client = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())

    state = _apply_delta(state, make_assess_node()(state))
    with child_observation(
        "safety_assess",
        input={"message": _latest_human(state["messages"]), "audience": state.get("audience")},
    ) as span:
        update_span(
            span,
            output={
                "action": state.get("safety_action"),
                "rule_id": state.get("safety_rule_id"),
                "reason": state.get("safety_notice"),
                "prompt_directive": state.get("prompt_directive"),
            },
        )
    if state.get("safety_action") == SafetyAction.BLOCK.value:
        state = _apply_delta(state, make_blocked_node()(state))
        yield _done_payload(state, _latest_ai(state["messages"]))
        return

    if state.get("appliance_model"):
        appliance = Appliance(
            model=state["appliance_model"],
            serial=state.get("appliance_serial"),
        )
        if not corpus_supports_appliance(manifest, appliance).supported:
            msg = unsupported_appliance_message(appliance)
            state = _apply_delta(
                state,
                {
                    "messages": [AIMessage(content=msg)],
                    "abstained": True,
                    "abstain_reason": "This model is not covered by our documentation set.",
                },
            )
            yield _done_payload(state, msg, abstain_code=ABSTAIN_UNSUPPORTED_MODEL)
            return

    yield {"type": "status", "phase": "retrieving"}
    state = _apply_delta(
        state,
        make_retrieve_node(db, manifest, retrieval_limit=retrieval_limit, overfetch=overfetch)(state),
    )

    if state.get("abstained") and not state.get("evidence_text"):
        appliance = None
        if state.get("appliance_model"):
            appliance = Appliance(
                model=state["appliance_model"],
                serial=state.get("appliance_serial"),
            )
        msg = no_evidence_message(appliance)
        state = _apply_delta(
            state,
            {
                "messages": [AIMessage(content=msg)],
                "abstained": True,
                "abstain_reason": "No matching manufacturer evidence for this question.",
            },
        )
        yield _done_payload(state, msg, abstain_code=ABSTAIN_NO_EVIDENCE)
        return

    _trace_evidence_prompt(
        state.get("evidence_text", ""),
        retrieval_count=int(state.get("retrieval_count") or 0),
    )
    yield {
        "type": "status",
        "phase": "generating",
        "retrieval_count": int(state.get("retrieval_count") or 0),
    }

    assessment = SafetyAssessment(
        action=SafetyAction(state.get("safety_action") or SafetyAction.ALLOW.value),
        rule_id=state.get("safety_rule_id") or "allow",
        reason=state.get("safety_notice") or "",
        audience=Audience(state.get("audience") or Audience.OWNER.value),
        prompt_directive=state.get("prompt_directive") or "",
    )
    system = diagnose_system()
    if assessment.prompt_directive:
        system = f"{system}\n\n{assessment.prompt_directive}"
    user_prompt = build_diagnostic_user_prompt(
        appliance_model=state.get("appliance_model"),
        appliance_serial=state.get("appliance_serial"),
        evidence_text=state.get("evidence_text", ""),
        transcript=_transcript(state["messages"]),
    )

    parts: list[str] = []
    for delta in client.stream(system, user_prompt):
        parts.append(delta)
        yield {"type": "token", "text": delta}

    raw = "".join(parts).strip()
    if raw.upper().startswith("ABSTAIN:"):
        reason = raw.split(":", 1)[-1].strip()
        state = _apply_delta(
            state,
            {
                "messages": [AIMessage(content=raw)],
                "abstained": True,
                "abstain_reason": reason,
            },
        )
        yield _done_payload(state, raw)
        return

    gated = _trace_gate(assessment, raw, state.get("evidence_text", ""))
    state = _apply_delta(
        state,
        {
            "messages": [AIMessage(content=gated.text)],
            "abstained": gated.blocked,
            "abstain_reason": gated.notice if gated.blocked else "",
            "safety_action": gated.action.value,
            "safety_notice": gated.notice,
            "escalated": gated.escalated,
        },
    )
    yield _done_payload(state, gated.text)


def _route_after_assess(state: DiagnosticGraphState) -> str:
    if state.get("safety_action") == SafetyAction.BLOCK.value:
        return "blocked"
    return "retrieve"


def build_diagnostic_graph(
    db: Database,
    manifest: Manifest,
    *,
    llm: LLMClient | None = None,
    retrieval_limit: int = 8,
    overfetch: int = 40,
):
    llm = llm or OpenAIClient(api_key=openai_api_key(), model=llm_model())
    graph = StateGraph(DiagnosticGraphState)
    graph.add_node("assess", make_assess_node())
    graph.add_node("blocked", make_blocked_node())
    graph.add_node("retrieve", make_retrieve_node(db, manifest, retrieval_limit=retrieval_limit, overfetch=overfetch))
    graph.add_node("respond", make_respond_node(llm))
    graph.add_edge(START, "assess")
    graph.add_conditional_edges("assess", _route_after_assess, {"blocked": "blocked", "retrieve": "retrieve"})
    graph.add_edge("blocked", END)
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


def citations_for_turn(state: DiagnosticGraphState, answer: str) -> list:
    return citations_from_answer(answer, state.get("citations_available") or [])
