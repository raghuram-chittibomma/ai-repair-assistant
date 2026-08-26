"""Tests for eval run-log pruning (E9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from repair_assistant.eval.run_log_prune import apply_prune, plan_prune


def test_plan_prune_keep_per_prefix(tmp_path: Path) -> None:
    names = [
        "20260101T000000Z.json",
        "20260102T000000Z.json",
        "20260103T000000Z.json",
        "candidates-20260101T000000Z.json",
        "candidates-20260102T000000Z.json",
    ]
    base = 1_700_000_000.0
    for i, name in enumerate(names):
        path = tmp_path / name
        path.write_text("{}", encoding="utf-8")
        # Higher index = newer
        import os

        os.utime(path, (base + i, base + i))

    plan = plan_prune(tmp_path, keep=1)
    keep_names = {p.name for p in plan.keep}
    assert keep_names == {"20260103T000000Z.json", "candidates-20260102T000000Z.json"}
    assert len(plan.delete) == 3


def test_plan_prune_requires_rule() -> None:
    with pytest.raises(ValueError, match="keep"):
        plan_prune(keep=None, older_than_days=None)


def test_apply_prune_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text("{}", encoding="utf-8")
    plan = plan_prune(tmp_path, keep=0)
    removed = apply_prune(plan, dry_run=True)
    assert path in removed
    assert path.is_file()
    apply_prune(plan, dry_run=False)
    assert not path.is_file()
