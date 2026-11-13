"""Solver, promotion pack, and release actions. No OpenAI and no Postgres."""

from __future__ import annotations

import pytest

from repair_assistant.reasoning.bench import run_bench
from repair_assistant.reasoning.formula import FormulaError, parse_formula
from repair_assistant.reasoning.models import Formalization, Policy, RewriteDraft
from repair_assistant.reasoning.policy import PolicyError, load_answer_invariants, load_policy
from repair_assistant.reasoning.release import apply_policy_release
from repair_assistant.reasoning.solver import check_policy
from repair_assistant.reasoning.translator import agree, parse_formalization


class _Cite:
    def __init__(self, index: int) -> None:
        self.index = index


class _Scripted:
    def __init__(self, items: list[Formalization]) -> None:
        self.items = list(items)

    def translate(self, question: str, answer: str, policy) -> list[Formalization]:
        del question, answer, policy
        if not self.items:
            raise AssertionError("translator called more times than scripted")
        return [self.items.pop(0)]


def _formal(**kwargs) -> Formalization:
    base = {"confidence": 1.0, "ambiguous": False}
    base.update(kwargs)
    return Formalization(**base)


def test_oversized_policy_is_too_complex() -> None:
    policy = load_answer_invariants()
    huge = Policy(policy.id, policy.version, policy.variables, policy.rules * 30)
    finding = check_policy(huge, {"doorPolarity": "STUCK_LOCKED"}, {"prescribesLockSideTest": True})
    assert finding.outcome == "too_complex"
    assert finding.reason == "rule_cap"


def test_completeness_check_reports_a_claim_the_facts_leave_open() -> None:
    from repair_assistant.reasoning.solver import undecided_claims

    policy = load_answer_invariants()
    kept = {"stuck-locked-not-lock-test", "non-negative-reading"}
    lock_only = tuple(r for r in policy.rules if r.id in kept)
    gaps = undecided_claims(Policy(policy.id, policy.version, policy.variables, lock_only))
    assert "prescribesUnlockSideTest" in gaps
    assert gaps["prescribesUnlockSideTest"]["doorPolarity"] in {"STUCK_LOCKED", "WILL_NOT_LOCK"}
    assert undecided_claims(policy) == {}


def test_translation_with_a_claim_in_the_premises_fails_closed() -> None:
    formal = parse_formalization(
        {
            "premises": [{"name": "prescribesLockSideTest", "value": "true"}],
            "claims": [],
            "untranslated": [],
            "ambiguous": False,
        },
        load_answer_invariants(),
    )
    assert formal.ambiguous is True
    assert "claim" in formal.reason


def test_named_ambiguity_asks_the_user_question_not_the_translator_contract() -> None:
    formal = parse_formalization(
        {"premises": [], "claims": [], "untranslated": [], "ambiguous": ["doorPolarity"]},
        load_answer_invariants(),
    )
    release = apply_policy_release(
        question="Something is off with the door.",
        answer="Run the door-will-not-lock test [1].",
        translator=_Scripted([formal]),
    )
    assert release.reasoning["outcome"] == "translation_ambiguous"
    assert "stuck locked so it will not open" in release.text
    assert "STUCK_LOCKED when" not in release.text


def test_empty_ambiguity_list_is_not_ambiguous() -> None:
    formal = parse_formalization(
        {"premises": [], "claims": [], "untranslated": [], "ambiguous": []},
        load_answer_invariants(),
    )
    assert formal.ambiguous is False
    assert formal.pre_solve == "no_translations"


def test_response_schema_admits_only_policy_names_by_role() -> None:
    from repair_assistant.reasoning.translator import response_format

    schema = response_format(load_answer_invariants())["json_schema"]["schema"]["properties"]

    def branches(key: str) -> dict[str, dict]:
        return {
            b["properties"]["name"]["enum"][0]: b["properties"]["value"]
            for b in schema[key]["items"]["anyOf"]
        }

    premises = branches("premises")
    claims = branches("claims")
    assert list(premises) == ["doorPolarity", "meterReading"]
    assert list(claims) == ["prescribesLockSideTest", "prescribesUnlockSideTest", "quotedReading"]
    assert premises["doorPolarity"]["enum"] == ["STUCK_LOCKED", "WILL_NOT_LOCK", "UNKNOWN"]
    assert premises["meterReading"]["pattern"] == "^-?[0-9]+$"
    assert claims["prescribesLockSideTest"]["enum"] == ["true"]


def test_door_claims_without_a_door_fact_are_not_checked() -> None:
    text = "F5E2 means the door did not lock; check the latch [1]."
    formal = parse_formalization(
        {
            "premises": [],
            "claims": [{"name": "prescribesLockSideTest", "value": "true", "text": text}],
            "untranslated": [],
            "ambiguous": [],
        },
        load_answer_invariants(),
    )
    assert formal.claims == {}
    assert formal.untranslated == [text]
    assert formal.pre_solve == "no_translations"


def test_a_false_bool_claim_is_an_omission_not_a_claim() -> None:
    formal = parse_formalization(
        {
            "premises": [{"name": "doorPolarity", "value": "STUCK_LOCKED"}],
            "claims": [{"name": "prescribesUnlockSideTest", "value": "false", "text": "Reset it."}],
            "untranslated": [],
            "ambiguous": [],
        },
        load_answer_invariants(),
    )
    assert formal.claims == {}
    release = apply_policy_release(
        question="The door is stuck locked.", answer="Reset it.", translator=_Scripted([formal])
    )
    assert release.reasoning["outcome"] == "no_translations"
    assert release.text == "Reset it."


def test_quote_claims_without_a_stated_reading_are_left_untranslated() -> None:
    spec = "Each pin reads 6 to 20 ohms [1]."
    formal = parse_formalization(
        {
            "premises": [],
            "claims": [
                {"name": "quotedReading", "value": "6", "text": spec},
                {"name": "quotedReading", "value": "20", "text": spec},
            ],
            "untranslated": [],
            "ambiguous": ["quotedReading"],
        },
        load_answer_invariants(),
    )
    assert formal.ambiguous is False
    assert formal.claims == {}
    assert formal.untranslated == [spec]
    assert formal.pre_solve == "no_translations"


def test_quote_claim_is_checked_once_the_reading_is_stated() -> None:
    formal = parse_formalization(
        {
            "premises": [{"name": "meterReading", "value": "12"}],
            "claims": [{"name": "quotedReading", "value": "21", "text": "Your 21 ohm reading"}],
            "untranslated": [],
            "ambiguous": [],
        },
        load_answer_invariants(),
    )
    assert formal.claims == {"quotedReading": 21}
    finding = check_policy(load_answer_invariants(), formal.premises, formal.claims)
    assert finding.outcome == "invalid"


def test_policy_requires_must_name_a_fact(tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "id: p\nversion: 1\nvariables:\n"
        "  - {name: c, type: bool, role: claim, description: d, requires: missing}\n"
        "rules:\n  - {id: r, expr: c}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="requires"):
        load_policy(path)


def test_policy_rejects_an_ask_question_on_a_claim(tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_text(
        "id: p\nversion: 1\nvariables:\n"
        "  - {name: c, type: bool, role: claim, description: d, ask: Which one}\n"
        "rules:\n  - {id: r, expr: c}\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="ask"):
        load_policy(path)


def test_correct_unlock_answer_ships_unchanged() -> None:
    answer = "Run the unlock-side continuity test [1]."
    translator = _Scripted(
        [
            _formal(
                premises={"doorPolarity": "STUCK_LOCKED"},
                claims={"prescribesUnlockSideTest": True},
            )
        ]
    )
    release = apply_policy_release(
        question="The door will not unlock.", answer=answer, translator=translator
    )
    assert release.reasoning["outcome"] == "valid"
    assert release.mutates is False
    assert release.text == answer


def test_unstated_polarity_asks_for_the_door_fact() -> None:
    translator = _Scripted([_formal(claims={"prescribesLockSideTest": True})])
    release = apply_policy_release(
        question="What should I test?",
        answer="Run the lock-side test.",
        translator=translator,
    )
    assert release.reasoning["outcome"] == "satisfiable"
    assert "stuck locked so it will not open" in release.text


def test_formula_rejects_unknown_operator() -> None:
    try:
        parse_formula("(bogus x)")
    except FormulaError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("expected FormulaError")


def test_promotion_pack_matches_published_policy() -> None:
    results = run_bench()
    failed = [item for item in results if not item.passed]
    assert not failed
    policy = load_answer_invariants()
    assert policy.id == "answer-invariants"
    assert policy.version == 1


def test_missing_translator_leaves_the_answer() -> None:
    release = apply_policy_release(
        question="The door will not open.",
        answer="Run the lock-side test.",
        translator=None,
    )
    assert release.mutates is False
    assert release.text == "Run the lock-side test."
    assert release.reasoning["outcome"] == "skipped"
    assert release.reasoning["reason"] == "no_translator"


def test_invalid_claim_is_rewritten_once_when_the_recheck_is_valid() -> None:
    translator = _Scripted(
        [
            _formal(premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesLockSideTest": True}),
            _formal(premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesUnlockSideTest": True}),
        ]
    )
    calls: list[str] = []

    def rewrite(addendum: str) -> RewriteDraft:
        calls.append(addendum)
        return RewriteDraft(text="Use the stuck-door row [1].", citations=[_Cite(1)])

    release = apply_policy_release(
        question="The door will not open.",
        answer="Run the lock-side test.",
        translator=translator,
        rewrite=rewrite,
    )
    assert calls and "stuck-locked-not-lock-test" in calls[0]
    assert release.mutates is True
    assert release.text == "Use the stuck-door row [1]."
    assert release.abstained is False
    assert release.reasoning["outcome"] == "valid"
    assert release.reasoning["rewritten"] is True
    assert not translator.items


def test_still_invalid_rewrite_is_withheld_and_keeps_a_cited_span() -> None:
    translator = _Scripted(
        [
            _formal(
                premises={"doorPolarity": "STUCK_LOCKED"},
                claims={"prescribesLockSideTest": True},
                untranslated=["Owner step [1]."],
            ),
            _formal(premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesLockSideTest": True}),
        ]
    )
    release = apply_policy_release(
        question="The door will not open.",
        answer="Run the lock-side test.",
        translator=translator,
        rewrite=lambda _addendum: "Run the lock-side test again.",
        citations=[_Cite(1), _Cite(2)],
    )
    assert release.abstained is False
    assert "stuck-locked-not-lock-test" in release.text
    assert "Owner step [1]." in release.text
    assert "Run the lock-side test again." not in release.text
    assert [item.index for item in release.citations or []] == [1]


def test_unknown_polarity_asks_which_way_the_door_fails() -> None:
    translator = _Scripted(
        [
            _formal(
                premises={"doorPolarity": "UNKNOWN"},
                claims={"prescribesLockSideTest": True},
            )
        ]
    )
    release = apply_policy_release(
        question="The door is wrong.",
        answer="Run the lock-side test.",
        translator=translator,
        rewrite=lambda _addendum: "should not be called",
    )
    assert release.mutates is True
    assert release.abstained is False
    assert "stuck locked so it will not open" in release.text
    assert release.reasoning["outcome"] == "satisfiable"
    assert release.citations == []


def test_negative_reading_is_not_served() -> None:
    translator = _Scripted(
        [
            _formal(premises={"meterReading": -1}, claims={"quotedReading": -1}),
        ]
    )
    release = apply_policy_release(
        question="The meter says -1.",
        answer="Your -1 reading is fine.",
        translator=translator,
    )
    assert release.abstained is True
    assert release.reasoning["outcome"] == "impossible"
    assert "non-negative-reading" in release.text


def test_untranslated_answer_is_left_on_the_citation_path() -> None:
    translator = _Scripted([_formal(untranslated=["Check the hose [1]."])])
    release = apply_policy_release(
        question="Water on the floor.",
        answer="Check the hose [1].",
        translator=translator,
    )
    assert release.mutates is False
    assert release.text == "Check the hose [1]."
    assert release.reasoning["outcome"] == "no_translations"


def test_schema_invalid_translation_is_not_stated_as_fact() -> None:
    policy = load_answer_invariants()
    formal = parse_formalization(
        {
            "premises": [{"name": "notAVariable", "value": "true"}],
            "claims": [],
            "untranslated": [],
            "ambiguous": False,
        },
        policy,
    )
    assert formal.ambiguous is True
    release = apply_policy_release(
        question="Hello",
        answer="Yes.",
        translator=_Scripted([formal]),
    )
    assert release.mutates is True
    assert release.text != "Yes."
    assert release.reasoning["outcome"] == "translation_ambiguous"


def test_disagreeing_translators_are_ambiguous() -> None:
    agreed = agree(
        [
            _formal(premises={"doorPolarity": "STUCK_LOCKED"}, claims={"prescribesUnlockSideTest": True}),
            _formal(premises={"doorPolarity": "WILL_NOT_LOCK"}, claims={"prescribesUnlockSideTest": True}),
        ]
    )
    assert agreed.ambiguous is True
    assert agreed.reason == "translators_disagreed"
