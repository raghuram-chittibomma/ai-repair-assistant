"""Lockfile + dated model stamps for scorecard headers (review R37)."""

from repair_assistant.eval.repro import lockfile_stamp, scorecard_repro_lines
from repair_assistant.qa.env import DEFAULT_LLM_MODEL
from repair_assistant.safety.bench import SafetyBenchResult, scorecard_markdown


def test_default_llm_model_is_a_dated_snapshot() -> None:
    assert DEFAULT_LLM_MODEL == "gpt-4o-mini-2024-07-18"
    assert DEFAULT_LLM_MODEL != "gpt-4o-mini"


def test_lockfile_stamp_reads_committed_uv_lock() -> None:
    stamp = lockfile_stamp()
    assert stamp.startswith("uv.lock@")
    assert len(stamp) > len("uv.lock@")


def test_scorecard_header_includes_repro_stamps() -> None:
    md = scorecard_markdown(
        [SafetyBenchResult(fixture_id="x", passed=True, hard=True, detail="ok")]
    )
    header = "\n".join(scorecard_repro_lines())
    assert header in md
    assert "Lockfile:" in md
    assert "LLM_MODEL:" in md
    assert "EMBEDDING_MODEL:" in md
