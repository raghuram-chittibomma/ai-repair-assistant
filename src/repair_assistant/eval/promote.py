"""Promote failed bench runs into grading-overlay drafts (manual review)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.candidates_bench import load_candidates


def load_run_log(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)
    if not isinstance(data, dict) or "results" not in data:
        raise ValueError(f"not a bench run log: {path}")
    return data


def find_result(run: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    for row in run.get("results") or []:
        if row.get("scenario_id") == scenario_id:
            return row
    raise KeyError(f"scenario {scenario_id!r} not in run log")


def _scenario_lookup(scenario_id: str) -> dict[str, Any] | None:
    data = load_candidates()
    for family in data.get("families") or []:
        for scenario in family.get("scenarios") or []:
            if scenario.get("id") == scenario_id:
                merged = dict(scenario)
                merged["_family_id"] = family["id"]
                return merged
    return None


def _phrase_candidates(answer: str, *, limit: int = 6) -> list[str]:
    """Heuristic substrings an operator may want as fails_if_contains drafts."""
    text = re.sub(r"\s+", " ", answer or "").strip()
    if not text:
        return []
    # Prefer short distinctive noun phrases / code tokens.
    tokens = re.findall(r"\b(?:F\dE\d|W\d{8}|TEST #\d+[a-z]?|[A-Za-z][A-Za-z0-9-]{3,})\b", text)
    seen: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in {s.lower() for s in seen}:
            continue
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


def draft_overlay(
    scenario_id: str,
    result: dict[str, Any],
    *,
    run_label: str,
) -> dict[str, Any]:
    """Build a grading-overlay draft for human review (not auto-applied blindly)."""
    scenario = _scenario_lookup(scenario_id) or {}
    detail = str(result.get("detail") or "")
    answer = str(result.get("answer") or "")
    draft: dict[str, Any] = {
        "promoted_from": run_label,
        "fail_detail": detail,
        "note": (
            "Draft from a failed bench run. Review before treating as a hard gate. "
            "Move useful keys into the live overlay entry and delete this draft."
        ),
    }
    if scenario.get("expect"):
        draft["expect_note"] = scenario["expect"]
    if scenario.get("fails_if"):
        draft["fails_if_note"] = scenario["fails_if"]

    # Parse deterministic miss hints into starter lists.
    cite_missing = re.findall(r"must_cite missing '([^']+)'", detail)
    if cite_missing:
        draft["must_cite"] = sorted(set(cite_missing))
    expect_missing = re.findall(r"(?<!must_cite )missing '([^']+)'", detail)
    if expect_missing:
        draft["expect_contains"] = list(dict.fromkeys(expect_missing))
    any_missing = re.findall(r"expect_contains_any missing one of (\[[^\]]+\])", detail)
    if any_missing:
        draft["expect_contains_any_hint"] = any_missing[0]

    phrases = _phrase_candidates(answer)
    if phrases and not result.get("passed") and not result.get("abstained"):
        draft["suggested_fails_if_contains"] = phrases[:4]

    draft["answer_excerpt"] = answer[:400]
    return draft


def render_overlay_yaml(scenario_id: str, draft: dict[str, Any]) -> str:
    payload = {scenario_id: draft}
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=88)


def default_grading_path() -> Path:
    return manifest_mod.load().root / "evals" / "qa" / "candidates-grading.yaml"


def merge_draft_into_grading(
    scenario_id: str,
    draft: dict[str, Any],
    *,
    grading_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Write draft under scenarios.<id>.draft (does not overwrite live overlay keys)."""
    path = grading_path or default_grading_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {"version": 1}
    if not isinstance(data, dict):
        data = {"version": 1}
    scenarios = data.setdefault("scenarios", {})
    if not isinstance(scenarios, dict):
        raise ValueError("candidates-grading.yaml scenarios must be a mapping")
    existing = scenarios.get(scenario_id)
    if isinstance(existing, dict) and existing and not force:
        # Keep live keys; nest draft alongside.
        if "draft" in existing and not force:
            raise FileExistsError(
                f"{scenario_id} already has a draft; pass --force to replace"
            )
        existing = dict(existing)
        existing["draft"] = draft
        scenarios[scenario_id] = existing
    else:
        scenarios[scenario_id] = {"draft": draft}
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
        newline="\n",
    )
    return path


def promote_failure(
    run_path: Path,
    scenario_id: str,
    *,
    write: bool = False,
    force: bool = False,
    grading_path: Path | None = None,
) -> tuple[str, Path | None]:
    run = load_run_log(run_path)
    result = find_result(run, scenario_id)
    if result.get("passed"):
        raise ValueError(f"{scenario_id} passed in this run; nothing to promote")
    label = run_path.name
    draft = draft_overlay(scenario_id, result, run_label=label)
    text = render_overlay_yaml(scenario_id, draft)
    written: Path | None = None
    if write:
        written = merge_draft_into_grading(
            scenario_id,
            draft,
            grading_path=grading_path,
            force=force,
        )
    return text, written
