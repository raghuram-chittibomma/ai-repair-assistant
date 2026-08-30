"""Claim-level lexical groundedness (review R27). No OpenAI."""

from __future__ import annotations

from repair_assistant.eval.grading import grade_answer
from repair_assistant.eval.groundedness import claim_supported_by, score_claims
from repair_assistant.eval.llm_judge import build_judge_user_prompt
from repair_assistant.qa.structured import Claim


def test_invented_procedure_with_valid_index_fails() -> None:
    claims = [Claim(text="Bypass the door lock with a jumper wire", evidence_index=1)]
    blocks = {1: "F5E2 indicates the door lock switch is open. Check the strike."}
    report = score_claims(claims, blocks)
    assert report.hard_unsupported == 1
    assert report.rate == 1.0

    passed, detail = grade_answer(
        {"must_cite": ["W11320651"]},
        answer="Bypass the door lock with a jumper wire [1].",
        citations=["W11320651"],
        abstained=False,
        claims=claims,
        evidence_blocks=blocks,
    )
    assert not passed
    assert "ungrounded" in detail


def test_claim_supported_by_shared_tokens() -> None:
    evidence = "F5E2 indicates the main control cannot detect the door lock is closed."
    assert claim_supported_by("F5E2 is a door lock fault", evidence)
    report = score_claims(
        [Claim(text="F5E2 is a door lock fault", evidence_index=1)],
        {1: evidence},
    )
    assert report.unsupported == 0
    passed, _ = grade_answer(
        {},
        answer="F5E2 is a door lock fault [1].",
        citations=["W11320651"],
        abstained=False,
        claims=[Claim(text="F5E2 is a door lock fault", evidence_index=1)],
        evidence_blocks={1: evidence},
    )
    assert passed


def test_weak_paraphrase_counts_but_does_not_hard_fail() -> None:
    claims = [
        Claim(
            text="Inspect the housing gasket after every filter service on the washer",
            evidence_index=1,
        )
    ]
    blocks = {1: "Clear the drain pump filter if the washer is slow to drain."}
    report = score_claims(claims, blocks)
    assert report.unsupported == 1
    assert report.hard_unsupported == 0
    passed, _ = grade_answer(
        {},
        answer="x",
        citations=["W11320651"],
        abstained=False,
        claims=claims,
        evidence_blocks=blocks,
    )
    assert passed


def test_judge_prompt_includes_evidence() -> None:
    prompt = build_judge_user_prompt(
        {"id": "x", "question": "What is F5E2?", "expect": "door lock"},
        answer="Door lock fault [1].",
        citations=["W11320651"],
        abstained=False,
        evidence_text="[1] F5E2 door lock switch",
    )
    assert "Evidence:" in prompt
    assert "F5E2 door lock switch" in prompt
