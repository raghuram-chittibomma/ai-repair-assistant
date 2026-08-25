"""Interactive diagnostic session over LangGraph."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from repair_assistant.corpus.applicability import Appliance
from repair_assistant.corpus.manifest import Manifest
from repair_assistant.diagnostic.graph import build_diagnostic_graph, citations_for_turn
from repair_assistant.diagnostic.state import DiagnosticGraphState, TurnResult
from repair_assistant.ingest.store import Database
from repair_assistant.qa.generate import LLMClient


class DiagnosticSession:
    """Multi-turn grounded troubleshooting for one appliance."""

    def __init__(
        self,
        db: Database,
        manifest: Manifest,
        *,
        appliance: Appliance | None = None,
        llm: LLMClient | None = None,
        retrieval_limit: int = 8,
        overfetch: int = 40,
    ) -> None:
        self._graph = build_diagnostic_graph(
            db,
            manifest,
            llm=llm,
            retrieval_limit=retrieval_limit,
            overfetch=overfetch,
        )
        self._state: DiagnosticGraphState = {
            "messages": [],
            "appliance_model": appliance.model if appliance else None,
            "appliance_serial": appliance.serial if appliance else None,
            "retrieval_query": "",
            "evidence_text": "",
            "citations_available": [],
            "retrieval_count": 0,
            "abstained": False,
            "abstain_reason": "",
        }
        self._turn = 0

    @property
    def turn_count(self) -> int:
        return self._turn

    def send(self, user_message: str) -> TurnResult:
        """Process one user message and return the assistant turn."""
        self._turn += 1
        invoke_state: DiagnosticGraphState = {
            **self._state,
            "messages": [*self._state["messages"], HumanMessage(content=user_message)],
        }
        result = self._graph.invoke(invoke_state)
        self._state = result

        assistant = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                assistant = str(msg.content)
                break

        cited = [] if result.get("abstained") else citations_for_turn(result, assistant)
        return TurnResult(
            user_message=user_message,
            assistant_message=assistant,
            abstained=bool(result.get("abstained")),
            abstain_reason=result.get("abstain_reason", ""),
            citations=cited,
            retrieval_count=int(result.get("retrieval_count") or 0),
            turn=self._turn,
        )
