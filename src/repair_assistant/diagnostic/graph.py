"""LangGraph workflow: assess safety, retrieve evidence, respond."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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
from repair_assistant.diagnostic.prompts import (
    build_diagnostic_user_prompt,
    window_transcript,
)
from repair_assistant.diagnostic.state import DiagnosticGraphState
from repair_assistant.ingest.store import Database
from repair_assistant.observability.langfuse_tracing import child_observation, update_span
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.prompts import diagnose_system
from repair_assistant.qa.acks import ORPHAN_ACK_IN_DIAGNOSE, is_ack_only_message
from repair_assistant.qa.context import format_evidence, resolve_citations
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.qa.generate import (
    LLMClient,
    OpenAIClient,
    _trace_evidence_prompt,
    _trace_gate,
    iter_answer_tokens,
)
from repair_assistant.qa.parts import related_parts_note
from repair_assistant.qa.structured import (
    bind_generation,
    citations_from_claims,
    claims_as_dicts,
    claims_from_dicts,
)
from repair_assistant.retrieval.search import search
from repair_assistant.safety.gate import gate_answer
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment
from repair_assistant.safety.policy import (
    apply_owner_evidence_policy,
    assess_request,
    block_message,
)
from repair_assistant.safety.stream_gate import may_stream


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


def _has_prior_assistant(messages: list) -> bool:
    return any(isinstance(msg, AIMessage) and msg.content for msg in messages)


def _transcript(messages: list) -> str:
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            lines.append(f"Assistant: {msg.content}")
    return window_transcript(lines)


# Follow-up acknowledgements are detected via repair_assistant.qa.acks.


def _user_texts(messages: list) -> list[str]:
    return [
        str(msg.content)
        for msg in messages
        if isinstance(msg, HumanMessage) and msg.content
    ]


def _session_symptom_anchor(messages: list) -> str:
    """First non-ack user message — the symptom the session is about."""
    for text in _user_texts(messages):
        if not is_ack_only_message(text):
            return text.strip()
    texts = _user_texts(messages)
    return texts[0].strip() if texts else ""


def _retrieval_query(messages: list) -> str:
    """Build a retrieval query from recent user turns (symptom context carries forward).

    Pure acknowledgements ("no issues", "that looks good") must not replace the
    original symptom in the query — otherwise follow-up retrieval drifts and the
    model hops to unrelated TEST # cross-references.
    """
    parts = _user_texts(messages)
    codes: list[str] = []
    for text in parts:
        codes.extend(extract_error_codes(text))

    anchor = _session_symptom_anchor(messages)
    latest = parts[-1].strip() if parts else ""

    if latest and is_ack_only_message(latest) and anchor:
        query = anchor
    else:
        # Prefer non-ack turns so "no error code. machine shuts down" still joins.
        substantive = [p for p in parts if not is_ack_only_message(p)]
        recent = (substantive or parts)[-3:]
        query = " ".join(recent).strip()

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
        from repair_assistant.retrieval.planner import plan_for_query

        latest = _latest_human(state["messages"])
        # Ack with no prior assistant reply → session lost / wrong mode; don't search.
        if is_ack_only_message(latest) and not _has_prior_assistant(state["messages"]):
            return {
                "retrieval_query": latest,
                "evidence_text": "",
                "citations_available": [],
                "retrieval_count": 0,
                "abstained": False,
                "abstain_reason": "orphan_ack",
            }

        query = _retrieval_query(state["messages"])
        appliance = None
        if state.get("appliance_model"):
            appliance = Appliance(
                model=state["appliance_model"],
                serial=state.get("appliance_serial"),
            )
        audience = str(state.get("audience") or Audience.OWNER.value)
        plan = plan_for_query(query, audience=audience)
        result = search(
            db,
            manifest,
            query,
            appliance=appliance,
            limit=retrieval_limit,
            overfetch=overfetch,
            audience=audience,
            plan=plan,
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
        evidence_text, citations = format_evidence(result.hits, manifest=manifest)
        parts = related_parts_note(result.hits, manifest, appliance)
        if parts:
            evidence_text = f"{evidence_text}\n\n{parts}"
        return {
            "retrieval_query": query,
            "evidence_text": evidence_text,
            "citations_available": citations,
            "retrieval_count": len(result.hits),
            "abstained": False,
            "abstain_reason": "",
            "evidence_blocks": {c.index: (c.block_text or c.excerpt or "") for c in citations},
        }

    return retrieve


def _maybe_orphan_ack_reply(state: DiagnosticGraphState) -> dict | None:
    if state.get("abstain_reason") == "orphan_ack" and not state.get("evidence_text"):
        return {
            "messages": [AIMessage(content=ORPHAN_ACK_IN_DIAGNOSE)],
            "abstained": False,
            "abstain_reason": "",
        }
    return None


def make_respond_node(llm: LLMClient):
    def respond(state: DiagnosticGraphState) -> dict:
        orphan = _maybe_orphan_ack_reply(state)
        if orphan is not None:
            return orphan

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
        assessment = apply_owner_evidence_policy(
            assessment, state.get("evidence_text") or ""
        )
        system = diagnose_system()
        if assessment.prompt_directive:
            system = f"{system}\n\n{assessment.prompt_directive}"

        latest = _latest_human(state["messages"])
        anchor = _session_symptom_anchor(state["messages"])
        user_prompt = build_diagnostic_user_prompt(
            appliance_model=state.get("appliance_model"),
            appliance_serial=state.get("appliance_serial"),
            evidence_text=state.get("evidence_text", ""),
            transcript=_transcript(state["messages"]),
            symptom_anchor=anchor,
            ack_followup=is_ack_only_message(latest) and bool(anchor),
        )
        raw = llm.complete(system, user_prompt)
        available = list(state.get("citations_available") or [])
        bound = bind_generation(raw, available)
        if bound.abstained:
            # Ack follow-ups with evidence must continue the path, not abstain.
            if is_ack_only_message(latest) and state.get("evidence_text") and _has_prior_assistant(
                state["messages"]
            ):
                raw = llm.complete(
                    system
                    + "\n\nCRITICAL: The user confirmed prior checks passed. "
                    "Do NOT abstain. Acknowledge briefly and give the next "
                    "checklist category with [n] citations.",
                    user_prompt,
                )
                bound = bind_generation(raw, available)
            if bound.abstained:
                return {
                    "messages": [AIMessage(content=bound.display)],
                    "abstained": True,
                    "abstain_reason": bound.abstain_reason,
                    "claims": claims_as_dicts(bound.claims),
                }

        gated = gate_answer(
            assessment,
            bound.display,
            evidence_text=state.get("evidence_text", ""),
        )
        return {
            "messages": [AIMessage(content=gated.text)],
            "abstained": gated.blocked,
            "abstain_reason": gated.notice if gated.blocked else "",
            "safety_action": gated.action.value,
            "safety_notice": gated.notice,
            "escalated": gated.escalated,
            "prompt_directive": assessment.prompt_directive,
            "claims": claims_as_dicts(bound.claims),
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
    client = llm or OpenAIClient(
        api_key=openai_api_key(), model=llm_model(), prompt_name="diagnose_system"
    )

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

    orphan = _maybe_orphan_ack_reply(state)
    if orphan is not None:
        state = _apply_delta(state, orphan)
        msg = orphan["messages"][0].content
        yield {"type": "token", "text": msg}
        yield _done_payload(state, str(msg))
        return

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
    assessment = apply_owner_evidence_policy(
        assessment, state.get("evidence_text") or ""
    )
    system = diagnose_system()
    if assessment.prompt_directive:
        system = f"{system}\n\n{assessment.prompt_directive}"
    latest = _latest_human(state["messages"])
    anchor = _session_symptom_anchor(state["messages"])
    ack_followup = is_ack_only_message(latest) and bool(anchor)
    user_prompt = build_diagnostic_user_prompt(
        appliance_model=state.get("appliance_model"),
        appliance_serial=state.get("appliance_serial"),
        evidence_text=state.get("evidence_text", ""),
        transcript=_transcript(state["messages"]),
        symptom_anchor=anchor,
        ack_followup=ack_followup,
    )

    # ADR-0028: buffer the structured completion, gate the rendered answer,
    # then emit prose. JSON tokens never reach the client (R1 / ADR-0026).
    raw = "".join(client.stream(system, user_prompt)).strip()
    available = list(state.get("citations_available") or [])
    bound = bind_generation(raw, available)

    if bound.abstained and ack_followup and state.get("evidence_text"):
        retry_system = (
            system
            + "\n\nCRITICAL: The user confirmed prior checks passed. "
            "Do NOT abstain. Acknowledge briefly and give the next "
            "checklist category with [n] citations."
        )
        raw = "".join(client.stream(retry_system, user_prompt)).strip()
        bound = bind_generation(raw, available)

    stream_tokens = not ack_followup and may_stream(assessment)
    if bound.abstained:
        state = _apply_delta(
            state,
            {
                "messages": [AIMessage(content=bound.display)],
                "abstained": True,
                "abstain_reason": bound.abstain_reason,
                "claims": claims_as_dicts(bound.claims),
            },
        )
        yield _done_payload(state, bound.display)
        return

    gated = _trace_gate(assessment, bound.display, state.get("evidence_text", ""))
    if stream_tokens and gated.text and not gated.blocked:
        for piece in iter_answer_tokens(assessment, gated.text):
            yield {"type": "token", "text": piece}
    state = _apply_delta(
        state,
        {
            "messages": [AIMessage(content=gated.text)],
            "abstained": gated.blocked,
            "abstain_reason": gated.notice if gated.blocked else "",
            "safety_action": gated.action.value,
            "safety_notice": gated.notice,
            "escalated": gated.escalated,
            "claims": claims_as_dicts(bound.claims),
        },
    )
    yield _done_payload(state, gated.text)


def retrieve_diagnose_state(
    db: Database,
    manifest: Manifest,
    state: DiagnosticGraphState,
    *,
    retrieval_limit: int,
    overfetch: int,
) -> tuple[DiagnosticGraphState, bool]:
    """Assess safety and retrieve evidence. Returns (state, needs_respond).

    The database is unused after this returns (review R35).
    """
    state = _apply_delta(state, make_assess_node()(state))
    if state.get("safety_action") == SafetyAction.BLOCK.value:
        return _apply_delta(state, make_blocked_node()(state)), False
    retrieve = make_retrieve_node(
        db, manifest, retrieval_limit=retrieval_limit, overfetch=overfetch
    )
    return _apply_delta(state, retrieve(state)), True


def respond_diagnose_state(state: DiagnosticGraphState, llm: LLMClient) -> DiagnosticGraphState:
    """Generate the assistant turn. Must not be called while holding a pool connection."""
    return _apply_delta(state, make_respond_node(llm)(state))


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
    llm = llm or OpenAIClient(
        api_key=openai_api_key(), model=llm_model(), prompt_name="diagnose_system"
    )
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
    available = list(state.get("citations_available") or [])
    cited = citations_from_claims(claims_from_dicts(state.get("claims")), available)
    if cited:
        return cited
    return resolve_citations(answer, available)
