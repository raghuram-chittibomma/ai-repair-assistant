"""Policy release on the ask and diagnose paths with a scripted translator (ADR-0055)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from repair_assistant.corpus.support import CorpusSupportResult
from repair_assistant.diagnostic.graph import (
    _policy_question,
    diagnose_turn_stream,
    respond_diagnose_state,
)
from repair_assistant.qa.context import Citation
from repair_assistant.qa.generate import AskPrep, complete_ask, stream_from_prep
from repair_assistant.reasoning.models import Formalization
from repair_assistant.retrieval.search import Hit, SearchResult
from repair_assistant.safety.models import Audience, SafetyAction, SafetyAssessment

LOCK_TEST = "Run the door will not lock test [1]."
STUCK_ROW = "Use the door will not unlock steps [2]."


def _json_answer(text: str, index: int) -> str:
    return json.dumps(
        {
            "abstained": False,
            "abstain_reason": "",
            "answer": text,
            "claims": [{"text": text, "evidence_index": index}],
        }
    )


def _formal(**kwargs) -> Formalization:
    return Formalization(confidence=1.0, ambiguous=False, **kwargs)


UNLOCK_LOCK_TEST = _formal(
    premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesLockSideTest": True}
)
UNLOCK_UNLOCK_TEST = _formal(
    premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesUnlockSideTest": True}
)


class ScriptedTranslator:
    def __init__(self, *items: Formalization | Exception) -> None:
        self.items = list(items)
        self.questions: list[str] = []
        self.answers: list[str] = []

    def translate(self, question: str, answer: str, policy) -> list[Formalization]:
        del policy
        self.questions.append(question)
        self.answers.append(answer)
        if not self.items:
            raise AssertionError("translator called more times than scripted")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return [item]


class ScriptedLLM:
    """Returns scripted completions and records each call."""

    model = "fake"

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, **kwargs) -> str:
        self.calls.append({"system": system, "user": user, **kwargs})
        if not self.outputs:
            raise AssertionError("LLM called more times than scripted")
        return self.outputs.pop(0)

    def stream(self, system: str, user: str, **kwargs):
        text = self.complete(system, user, **kwargs)
        for i in range(0, len(text), 7):
            yield text[i : i + 7]


@pytest.fixture
def use_translator(monkeypatch):
    def install(translator: ScriptedTranslator) -> ScriptedTranslator:
        monkeypatch.setattr(
            "repair_assistant.reasoning.translator.translator_for_llm",
            lambda _llm: translator,
        )
        return translator

    return install


def _cites() -> list[Citation]:
    return [
        Citation(index=i, doc_id=f"doc-{i}", chunk_id=f"c{i}", label=f"L{i}", page=i,
                 excerpt=f"e{i}", block_text=f"block {i}")
        for i in (1, 2)
    ]


def _assessment() -> SafetyAssessment:
    return SafetyAssessment(
        action=SafetyAction.ALLOW,
        rule_id="allow",
        reason="",
        audience=Audience.OWNER,
    )


def _prep(**kwargs) -> AskPrep:
    base = dict(
        question="The door will not open.",
        appliance=None,
        assessment=_assessment(),
        available=_cites(),
        system="sys",
        user_prompt="user",
    )
    base.update(kwargs)
    return AskPrep(**base)


class _Attach:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def cleanup(self) -> None:
        self.log.append("cleanup")


def test_ask_valid_claim_ships_unchanged(use_translator) -> None:
    translator = use_translator(ScriptedTranslator(UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(STUCK_ROW, 2))
    result = complete_ask(_prep(), llm=llm)
    assert result.answer == STUCK_ROW
    assert [c.index for c in result.citations] == [2]
    assert result.reasoning["outcome"] == "valid"
    assert result.reasoning["rules"] == ["stuck-locked-uses-unlock-test"]
    assert len(llm.calls) == 1
    assert translator.questions == ["The door will not open."]


def test_ask_invalid_claim_is_rewritten_once(use_translator) -> None:
    translator = use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(STUCK_ROW, 2))
    result = complete_ask(_prep(), llm=llm)
    assert result.answer == STUCK_ROW
    assert result.abstained is False
    assert [c.index for c in result.citations] == [2]
    assert [c.text for c in result.claims] == [STUCK_ROW]
    assert result.reasoning["outcome"] == "valid"
    assert result.reasoning["rewritten"] is True
    assert len(llm.calls) == 2
    assert "stuck-locked-not-lock-test" in llm.calls[1]["system"]
    assert translator.answers == [LOCK_TEST, STUCK_ROW]


def test_ask_still_invalid_after_rewrite_is_withheld(use_translator) -> None:
    use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_LOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(LOCK_TEST, 1))
    result = complete_ask(_prep(), llm=llm)
    assert result.abstained is True
    assert "lock test" not in result.answer.lower()
    assert "stuck-locked-not-lock-test" in result.answer
    assert result.citations == []
    assert result.claims == []
    assert result.reasoning["outcome"] == "invalid"
    assert len(llm.calls) == 2


def test_ask_under_determined_claim_becomes_a_question(use_translator) -> None:
    use_translator(
        ScriptedTranslator(
            _formal(premises={"doorPolarity": "UNKNOWN"}, claims={"prescribesLockSideTest": True})
        )
    )
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1))
    result = complete_ask(_prep(question="Something is wrong with the door."), llm=llm)
    assert result.abstained is False
    assert result.citations == []
    assert "stuck locked so it will not open" in result.answer
    assert result.reasoning["outcome"] == "satisfiable"
    assert len(llm.calls) == 1


def test_ask_safety_replacement_is_not_rechecked(use_translator) -> None:
    translator = use_translator(ScriptedTranslator())
    llm = ScriptedLLM(
        json.dumps(
            {"abstained": False, "abstain_reason": "", "answer": "Step 1: remove the panel.",
             "claims": [{"text": "Step 1: remove the panel.", "evidence_index": None}]}
        )
    )
    result = complete_ask(_prep(), llm=llm)
    assert result.abstained is True
    assert result.reasoning == {"outcome": "skipped", "reason": "safety_gate"}
    assert translator.questions == []


def test_ask_translator_failure_leaves_the_answer(use_translator) -> None:
    use_translator(ScriptedTranslator(RuntimeError("timeout")))
    llm = ScriptedLLM(_json_answer(STUCK_ROW, 2))
    result = complete_ask(_prep(), llm=llm)
    assert result.answer == STUCK_ROW
    assert [c.index for c in result.citations] == [2]
    assert result.reasoning["outcome"] == "skipped"
    assert result.reasoning["reason"] == "translator_error"
    assert isinstance(result.reasoning["duration_ms"], int)


def test_ask_rewrite_keeps_pdf_evidence_until_the_check_finishes(use_translator) -> None:
    log: list[str] = []

    class Translator(ScriptedTranslator):
        def translate(self, question, answer, policy):
            log.append("translate")
            return super().translate(question, answer, policy)

    use_translator(Translator(UNLOCK_LOCK_TEST, UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(STUCK_ROW, 2))
    pdf = Path("slice.pdf")
    result = complete_ask(
        _prep(evidence_pdfs=[pdf], _evidence_attach=_Attach(log)),
        llm=llm,
    )
    assert result.answer == STUCK_ROW
    assert llm.calls[1]["pdf_paths"] == [pdf]
    assert log == ["translate", "translate", "cleanup"]


def test_ask_cleans_pdf_evidence_when_generation_fails(use_translator) -> None:
    from repair_assistant.qa.generate import LLMTimeoutError

    log: list[str] = []
    use_translator(ScriptedTranslator())

    class FailingLLM(ScriptedLLM):
        def complete(self, system, user, **kwargs):
            raise LLMTimeoutError("slow")

    result = complete_ask(
        _prep(evidence_pdfs=[Path("slice.pdf")], _evidence_attach=_Attach(log)),
        llm=FailingLLM(),
    )
    assert log == ["cleanup"]
    assert result.reasoning is None


def test_ask_stream_only_emits_the_released_answer(use_translator) -> None:
    use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(STUCK_ROW, 2))
    events = list(stream_from_prep(_prep(), llm=llm))  # type: ignore[arg-type]
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    done = events[-1]
    assert streamed == STUCK_ROW
    assert "lock test" not in streamed.lower()
    assert done["type"] == "done"
    assert done["answer"] == STUCK_ROW
    assert done["reasoning"]["rewritten"] is True
    assert [c["index"] for c in done["citations"]] == [2]


def test_ask_stream_withheld_answer_emits_no_tokens(use_translator) -> None:
    use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_LOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(LOCK_TEST, 1))
    events = list(stream_from_prep(_prep(), llm=llm))  # type: ignore[arg-type]
    assert [e["type"] for e in events] == ["done"]
    assert events[-1]["abstained"] is True
    assert events[-1]["reasoning"]["outcome"] == "invalid"


def _diagnose_state(messages: list, **extra) -> dict:
    state = {
        "messages": messages,
        "appliance_model": "WFW5620HW0",
        "appliance_serial": None,
        "audience": Audience.OWNER.value,
        "retrieval_query": "Door will not open.",
        "evidence_text": "[1] block 1\n[2] block 2",
        "citations_available": _cites(),
        "retrieval_count": 2,
        "abstained": False,
        "abstain_reason": "",
        "safety_action": SafetyAction.ALLOW.value,
        "safety_notice": "",
        "safety_rule_id": "allow",
        "prompt_directive": "",
        "escalated": False,
    }
    state.update(extra)
    return state


def test_policy_question_uses_latest_message_on_a_new_symptom() -> None:
    state = _diagnose_state([HumanMessage(content="The door will not open.")])
    assert _policy_question(state, "The door will not open.") == "The door will not open."


def test_policy_question_carries_the_current_span_on_a_progress_turn() -> None:
    state = _diagnose_state(
        [
            HumanMessage(content="The door will not open."),
            AIMessage(content=STUCK_ROW),
            HumanMessage(content="still stuck"),
        ],
        retrieve_label="still_unresolved",
        diagnostic={
            "step": 1,
            "symptom_anchor": "The door will not open.",
            "symptom_path": [{"text": "Door will not lock.", "since_step": 1}],
        },
    )
    assert _policy_question(state, "still stuck") == "Door will not lock.\nstill stuck"


def test_diagnose_progress_turn_checks_with_the_session_symptom(use_translator) -> None:
    translator = use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(STUCK_ROW, 2))
    state = _diagnose_state(
        [
            HumanMessage(content="The door will not open."),
            AIMessage(content="Check the door [2]."),
            HumanMessage(content="still stuck"),
        ],
        retrieve_label="still_unresolved",
    )
    out = respond_diagnose_state(state, llm)  # type: ignore[arg-type]
    assert translator.questions[0].startswith("The door will not open.")
    assert translator.questions[0].endswith("still stuck")
    assert out["messages"][-1].content == STUCK_ROW
    assert out["reasoning"]["rewritten"] is True
    assert out["claims"][0]["evidence_index"] == 2


def test_diagnose_withheld_claim_does_not_reach_the_transcript(use_translator) -> None:
    use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_LOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(LOCK_TEST, 1))
    state = _diagnose_state([HumanMessage(content="The door will not open.")])
    out = respond_diagnose_state(state, llm)  # type: ignore[arg-type]
    assert out["abstained"] is True
    assert "lock test" not in out["messages"][-1].content.lower()
    assert out["reasoning"]["outcome"] == "invalid"


def test_diagnose_stream_only_emits_the_released_answer(use_translator) -> None:
    use_translator(ScriptedTranslator(UNLOCK_LOCK_TEST, UNLOCK_UNLOCK_TEST))
    llm = ScriptedLLM(_json_answer(LOCK_TEST, 1), _json_answer(STUCK_ROW, 2))
    hits = [
        Hit(doc_id=f"doc-{i}", chunk_id=f"c{i}", text=f"door will not unlock {i}", page=i,
            kind="prose", error_codes=[], publication_number="W1", revision="A", score=0.9)
        for i in (1, 2)
    ]
    start = _diagnose_state(
        [HumanMessage(content="The door will not open.")],
        evidence_text="",
        citations_available=[],
        retrieval_count=0,
    )
    with (
        patch("repair_assistant.diagnostic.graph.corpus_supports_appliance") as support,
        patch("repair_assistant.diagnostic.graph.search") as search,
    ):
        support.return_value = CorpusSupportResult(True, 1, "ok", "1 doc")
        search.return_value = SearchResult(query="door", hits=hits, fetched=2, filtered_out=0)
        events = list(
            diagnose_turn_stream(MagicMock(), MagicMock(), start, llm=llm)  # type: ignore[arg-type]
        )
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    done = events[-1]
    assert done["type"] == "done"
    assert "lock test" not in streamed.lower()
    assert done["assistant_message"] == streamed
    assert done["reasoning"]["rewritten"] is True
