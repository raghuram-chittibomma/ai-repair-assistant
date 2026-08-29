"""Held-out adversarial safety set (review R4).

These cases were authored independently of policy.py. The rates are a
measurement, not a pass/fail gate — do not assert a target recall here.
"""

from __future__ import annotations

from repair_assistant.safety.bench import load_adversarial, run_adversarial


def test_adversarial_pack_meets_the_review_size() -> None:
    fixtures = load_adversarial()["fixtures"]
    unsafe = [f for f in fixtures if f["role"] == "unsafe"]
    benign = [f for f in fixtures if f["role"] == "benign"]
    assert len(unsafe) >= 30
    assert len(benign) >= 20
    ids = [f["id"] for f in fixtures]
    assert len(ids) == len(set(ids))
    for fixture in fixtures:
        assert fixture["audience"] == "owner"
        assert fixture["expect_action"] in {"allow", "block", "escalate", "warn"}
        assert fixture["role"] in {"unsafe", "benign"}


def test_adversarial_rates_are_computed() -> None:
    summary = run_adversarial()
    assert summary.unsafe_total >= 30
    assert summary.benign_total >= 20
    assert 0 <= summary.unsafe_caught <= summary.unsafe_total
    assert 0 <= summary.false_escalations <= summary.benign_total
