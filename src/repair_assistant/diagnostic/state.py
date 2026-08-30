"""Diagnostic state carried across LangGraph turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from repair_assistant.qa.context import Citation


class DiagnosticGraphState(TypedDict):
    """LangGraph state for one diagnostic turn."""

    messages: Annotated[list[AnyMessage], add_messages]
    appliance_model: str | None
    appliance_serial: str | None
    audience: str
    retrieval_query: str
    evidence_text: str
    citations_available: list[Citation]
    retrieval_count: int
    abstained: bool
    abstain_reason: str
    safety_action: str
    safety_notice: str
    safety_rule_id: str
    prompt_directive: str
    escalated: bool
    claims: NotRequired[list[dict]]
    evidence_blocks: NotRequired[dict[int, str]]


@dataclass
class TurnResult:
    """Outcome of one user message in a diagnostic session."""

    user_message: str
    assistant_message: str
    abstained: bool
    abstain_reason: str = ""
    abstain_code: str = ""
    citations: list[Citation] = field(default_factory=list)
    retrieval_count: int = 0
    turn: int = 0
    safety_action: str = "allow"
    safety_notice: str = ""
    escalated: bool = False
    claims: list = field(default_factory=list)
    evidence_blocks: dict[int, str] = field(default_factory=dict)
