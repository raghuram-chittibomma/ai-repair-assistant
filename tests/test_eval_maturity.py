"""Unit tests for LLM-as-judge and promote-eval (no live API)."""

from __future__ import annotations

import json
from pathlib import Path

from repair_assistant.eval.grading import grade_answer
from repair_assistant.eval.llm_judge import (
    grade_with_optional_judge,
    judge_answer,
    needs_llm_judge,
)
from repair_assistant.eval.promote import draft_overlay, promote_failure


class FakeJudge:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.payload


def test_needs_llm_judge_only_for_prose() -> None:
    assert not needs_llm_judge({"expect_contains": ["door"]})
    assert needs_llm_judge({"expect": "Must mention TEST #4"})
    assert needs_llm_judge({"fails_if": "Mentions lid lock"})


def test_judge_parses_json_and_fenced_payload() -> None:
    scenario = {"id": "x", "expect": "Door lock procedure", "fails_if": "Lid lock"}
    llm = FakeJudge('{"passed": true, "reason": "mentions TEST #4"}')
    verdict = judge_answer(
        scenario,
        answer="See TEST #4 door lock.",
        citations=["W11320651"],
        abstained=False,
        llm=llm,
    )
    assert verdict.passed
    assert "TEST #4" in verdict.reason

    llm2 = FakeJudge('```json\n{"passed": false, "reason": "talks about lid"}\n```')
    verdict2 = judge_answer(
        scenario,
        answer="Lid lock fault.",
        citations=[],
        abstained=False,
        llm=llm2,
    )
    assert not verdict2.passed


def test_grade_with_optional_judge_skips_when_disabled_or_det_fails() -> None:
    scenario = {
        "id": "x",
        "expect": "Must hop to TEST #10a",
        "expect_contains": ["temperature"],
    }
    llm = FakeJudge('{"passed": false, "reason": "should not run"}')

    passed, detail = grade_with_optional_judge(
        scenario,
        answer="See TEST #10a page 19.",
        citations=[],
        abstained=False,
        use_judge=True,
        llm=llm,
        deterministic_grade=grade_answer,
    )
    assert not passed
    assert "temperature" in detail
    assert llm.calls == 0

    passed, detail = grade_with_optional_judge(
        scenario,
        answer="Check wash temperature sensor resistance.",
        citations=["W11320651"],
        abstained=False,
        use_judge=False,
        llm=llm,
        deterministic_grade=grade_answer,
    )
    assert passed
    assert detail == "ok"
    assert llm.calls == 0


def test_grade_with_optional_judge_can_fail_after_det_pass() -> None:
    scenario = {
        "id": "x",
        "expect": "Must include measured values from TEST #10a",
        "expect_contains": ["temperature"],
    }
    llm = FakeJudge('{"passed": false, "reason": "no measured values"}')
    passed, detail = grade_with_optional_judge(
        scenario,
        answer="Check wash temperature sensor.",
        citations=["W11320651"],
        abstained=False,
        use_judge=True,
        llm=llm,
        deterministic_grade=grade_answer,
    )
    assert not passed
    assert detail.startswith("judge:")
    assert llm.calls == 1


def test_promote_failure_draft(tmp_path: Path) -> None:
    run = {
        "timestamp": "2026-08-26T00:00:00+00:00",
        "results": [
            {
                "scenario_id": "demo-fail",
                "passed": False,
                "detail": "must_cite missing 'W11320651'; got []",
                "answer": "F3E2 means something vague about TEST #10a.",
                "citations": [],
                "abstained": False,
            }
        ],
    }
    run_path = tmp_path / "candidates-demo.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    text, written = promote_failure(run_path, "demo-fail", write=False)
    assert "demo-fail" in text
    assert "W11320651" in text
    assert written is None

    draft = draft_overlay("demo-fail", run["results"][0], run_label=run_path.name)
    assert draft["must_cite"] == ["W11320651"]
    assert "F3E2" in draft["suggested_fails_if_contains"] or "TEST" in str(
        draft.get("suggested_fails_if_contains")
    )
