"""Interactive diagnostic session over LangGraph."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.corpus.support import (
    ABSTAIN_UNSUPPORTED_MODEL,
    corpus_supports_appliance,
    unsupported_appliance_message,
)
from repair_assistant.diagnostic.board import merge_from_raw
from repair_assistant.diagnostic.graph import (
    citations_for_turn,
    diagnose_turn_stream,
    respond_diagnose_state,
    retrieve_diagnose_state,
)
from repair_assistant.diagnostic.state import DiagnosticGraphState, TurnResult
from repair_assistant.ingest.store import Database
from repair_assistant.observability.langfuse_tracing import observation, update_span
from repair_assistant.prompts import prompt_stamp
from repair_assistant.qa.env import llm_model, openai_api_key
from repair_assistant.qa.generate import LLMClient, OpenAIClient
from repair_assistant.qa.structured import claims_from_dicts
from repair_assistant.safety.audience_claim import record_audience_claim
from repair_assistant.safety.models import Audience, SafetyAction

DEFAULT_SESSION_MAX_TURNS = 24


class SessionTurnLimitError(ValueError):
    """The session has used its allowed turns; start a new chat (review R7)."""

    status_code = 400
    client_message = "This session has reached the turn limit. Start a new chat."


class DiagnosticSession:
    """Multi-turn grounded troubleshooting for one appliance."""

    def __init__(
        self,
        manifest: Manifest,
        *,
        appliance: Appliance | None = None,
        audience: Audience = Audience.OWNER,
        llm: LLMClient | None = None,
        retrieval_limit: int = 8,
        overfetch: int = 40,
        session_id: str | None = None,
        max_turns: int = DEFAULT_SESSION_MAX_TURNS,
        technician_attested: bool = False,
    ) -> None:
        self._manifest = manifest
        self._session_id = session_id
        self._llm = llm
        self._retrieval_limit = retrieval_limit
        self._overfetch = overfetch
        self._max_turns = max(1, int(max_turns))
        self._technician_attested = technician_attested
        self._state: DiagnosticGraphState = {
            "messages": [],
            "appliance_model": appliance.model if appliance else None,
            "appliance_serial": appliance.serial if appliance else None,
            "audience": audience.value,
            "retrieval_query": "",
            "evidence_text": "",
            "citations_available": [],
            "retrieval_count": 0,
            "abstained": False,
            "abstain_reason": "",
            "safety_action": SafetyAction.ALLOW.value,
            "safety_notice": "",
            "safety_rule_id": "allow",
            "prompt_directive": "",
            "escalated": False,
        }
        self._turn = 0

    @property
    def turn_count(self) -> int:
        return self._turn

    @property
    def max_turns(self) -> int:
        return self._max_turns

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _ensure_turn_allowed(self) -> None:
        if self._turn >= self._max_turns:
            raise SessionTurnLimitError(SessionTurnLimitError.client_message)

    def send(self, db: Database, user_message: str) -> TurnResult:
        """Process one user message and return the assistant turn."""

        @contextmanager
        def already_open() -> Iterator[Database]:
            yield db

        return self.send_releasing(already_open, user_message)

    def send_releasing(
        self,
        factory: Callable[[], Any],
        user_message: str,
    ) -> TurnResult:
        """Retrieve under ``factory()``; generate after that connection is released.

        CLI ``send()`` passes an already-open connection. The API passes the
        pool factory so generation does not pin a pooled client (review R35).
        """
        self._ensure_turn_allowed()
        self._turn += 1
        meta = {
            "turn": self._turn,
            "appliance_model": self._state.get("appliance_model"),
            **record_audience_claim(
                str(self._state.get("audience") or Audience.OWNER.value),
                attested=self._technician_attested,
                source="diagnose",
            ),
            **prompt_stamp("diagnose_system"),
        }
        started = time.perf_counter()
        with observation(
            "diagnose",
            input={"user_message": user_message, "turn": self._turn},
            metadata=meta,
            session_id=self._session_id,
        ) as span:
            if self._state.get("appliance_model"):
                appliance = Appliance(
                    model=self._state["appliance_model"],
                    serial=self._state.get("appliance_serial"),
                )
                if not corpus_supports_appliance(self._manifest, appliance).supported:
                    msg = unsupported_appliance_message(appliance)
                    self._state["messages"] = [
                        *self._state["messages"],
                        HumanMessage(content=user_message),
                        AIMessage(content=msg),
                    ]
                    board = merge_from_raw(
                        self._state.get("diagnostic"),
                        step=self._turn,
                        symptom_anchor=user_message,
                        user_message=user_message,
                        phase_hint="close",
                    )
                    self._state["diagnostic"] = board.as_dict()
                    turn = TurnResult(
                        user_message=user_message,
                        assistant_message=msg,
                        abstained=True,
                        abstain_reason="This model is not covered by our documentation set.",
                        abstain_code=ABSTAIN_UNSUPPORTED_MODEL,
                        turn=self._turn,
                        diagnostic=board.as_dict(),
                    )
                    update_span(
                        span,
                        output={
                            "abstained": True,
                            "answer_preview": msg[:500],
                            "abstain_code": ABSTAIN_UNSUPPORTED_MODEL,
                        },
                        metadata={
                            **meta,
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                        },
                    )
                    return turn

            invoke_state: DiagnosticGraphState = {
                **self._state,
                "messages": [*self._state["messages"], HumanMessage(content=user_message)],
            }
            with factory() as db:
                pending, needs_respond = retrieve_diagnose_state(
                    db,
                    self._manifest,
                    invoke_state,
                    retrieval_limit=self._retrieval_limit,
                    overfetch=self._overfetch,
                )
            if needs_respond:
                llm = self._llm or OpenAIClient(
                    api_key=openai_api_key(),
                    model=llm_model(),
                    prompt_name="diagnose_system",
                )
                pending = respond_diagnose_state(pending, llm)
            self._state = pending

            assistant = ""
            for msg in reversed(pending["messages"]):
                if isinstance(msg, AIMessage):
                    assistant = str(msg.content)
                    break

            cited = [] if pending.get("abstained") else citations_for_turn(pending, assistant)
            turn = TurnResult(
                user_message=user_message,
                assistant_message=assistant,
                abstained=bool(pending.get("abstained")),
                abstain_reason=pending.get("abstain_reason", ""),
                citations=cited,
                retrieval_count=int(pending.get("retrieval_count") or 0),
                turn=self._turn,
                safety_action=pending.get("safety_action", SafetyAction.ALLOW.value),
                safety_notice=pending.get("safety_notice", ""),
                escalated=bool(pending.get("escalated")),
                claims=claims_from_dicts(pending.get("claims")),
                evidence_blocks=dict(pending.get("evidence_blocks") or {}),
                diagnostic=dict(pending.get("diagnostic") or {}),
            )
            update_span(
                span,
                output={
                    "abstained": turn.abstained,
                    "answer_preview": (turn.assistant_message or "")[:500],
                    "citations": [c.label for c in turn.citations],
                    "retrieval_count": turn.retrieval_count,
                    "safety_action": turn.safety_action,
                    "escalated": turn.escalated,
                    "diagnostic_phase": (turn.diagnostic or {}).get("phase"),
                    "diagnostic_step": (turn.diagnostic or {}).get("step"),
                },
                metadata={
                    **meta,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "abstain_reason": turn.abstain_reason,
                },
            )
            return turn

    def send_stream(self, db: Database, user_message: str) -> Iterator[dict[str, Any]]:
        """Process one user message and yield SSE-friendly events."""
        self._ensure_turn_allowed()
        self._turn += 1
        meta = {
            "turn": self._turn,
            "appliance_model": self._state.get("appliance_model"),
            **record_audience_claim(
                str(self._state.get("audience") or Audience.OWNER.value),
                attested=self._technician_attested,
                source="diagnose_stream",
            ),
            **prompt_stamp("diagnose_system"),
        }
        started = time.perf_counter()
        with observation(
            "diagnose",
            input={"user_message": user_message, "turn": self._turn, "stream": True},
            metadata=meta,
            session_id=self._session_id,
        ) as span:
            invoke_state: DiagnosticGraphState = {
                **self._state,
                "messages": [*self._state["messages"], HumanMessage(content=user_message)],
            }
            final: dict[str, Any] | None = None
            for event in diagnose_turn_stream(
                db,
                self._manifest,
                invoke_state,
                llm=self._llm,  # type: ignore[arg-type]
                retrieval_limit=self._retrieval_limit,
                overfetch=self._overfetch,
            ):
                if event.get("type") == "done":
                    state = event.pop("_state")
                    self._state = state
                    assistant = event.get("assistant_message") or ""
                    event["turn"] = self._turn
                    final = event
                    update_span(
                        span,
                        output={
                            "abstained": event.get("abstained"),
                            "answer_preview": assistant[:500],
                            "citations": [
                                c["label"] for c in event.get("citations") or [] if isinstance(c, dict)
                            ],
                            "retrieval_count": event.get("retrieval_count"),
                            "safety_action": event.get("safety_action"),
                            "escalated": event.get("escalated"),
                            "diagnostic_phase": (event.get("diagnostic") or {}).get("phase"),
                            "diagnostic_step": (event.get("diagnostic") or {}).get("step"),
                        },
                        metadata={
                            **meta,
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                            "abstain_reason": event.get("abstain_reason"),
                        },
                    )
                yield event
            if final is None:
                update_span(span, metadata={**meta, "duration_ms": int((time.perf_counter() - started) * 1000)})
