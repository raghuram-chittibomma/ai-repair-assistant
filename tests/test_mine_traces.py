"""Unit tests for Phase 11 mine-traces (ADR-0023) — no live Langfuse."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from repair_assistant.eval.mine_traces import (
    TraceRecord,
    classify_trace,
    filter_traces,
    fingerprint,
    normalize_question,
    parse_since,
    run_mine,
    trace_record_from_api,
)
from repair_assistant.observability import langfuse_tracing as tracing
from repair_assistant.qa.context import AnswerResult


def test_parse_since_days() -> None:
    from datetime import datetime

    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    cut = parse_since("7d", now=now)
    assert (now - cut).days == 7


def test_normalize_and_fingerprint() -> None:
    assert normalize_question("  Door  Got   Locked ") == "door got locked"
    assert fingerprint("wrong_polarity", "Door Got Locked") == fingerprint(
        "wrong_polarity", "door got locked"
    )


def test_classify_invented_diag_entry() -> None:
    rec = TraceRecord(
        trace_id="t1",
        name="diagnose",
        timestamp="",
        question="stops after 10 minutes",
        answer=(
            "Enter diagnostic mode:\n"
            "1. Turn the cycle selector knob to the \"Off\" position.\n"
            "2. Turn to \"Normal\".\n"
            "3. Press Start/Pause for 3 seconds."
        ),
        citations=["tech-sheet-w11320651"],
        app_git_sha="abc",
    )
    assert "invented_diag_entry" in classify_trace(rec)


def test_classify_wrong_polarity() -> None:
    rec = TraceRecord(
        trace_id="t2",
        name="ask",
        timestamp="",
        question="door got locked",
        answer="Ensure that door is completely closed so it will lock.",
        app_git_sha="abc",
    )
    assert "wrong_polarity" in classify_trace(rec)


def test_filter_requires_git_sha() -> None:
    stamped = TraceRecord(
        trace_id="a",
        name="ask",
        timestamp="",
        question="q",
        answer="a",
        app_git_sha="deadbeef",
    )
    unstamped = TraceRecord(
        trace_id="b",
        name="ask",
        timestamp="",
        question="q",
        answer="a",
        app_git_sha=None,
    )
    kept = filter_traces([stamped, unstamped], require_git_sha=True)
    assert [r.trace_id for r in kept] == ["a"]
    kept2 = filter_traces(
        [stamped, unstamped], require_git_sha=True, include_unstamped=True
    )
    assert len(kept2) == 2


def test_trace_record_from_api_dict() -> None:
    rec = trace_record_from_api(
        {
            "id": "tid-1",
            "name": "ask",
            "timestamp": "2026-08-27T00:00:00Z",
            "input": {"question": "door got locked"},
            "output": {
                "answer": "Try unlock steps [1].",
                "citations": [{"doc_id": "use-and-care-w11156985"}],
            },
            "metadata": {"app_git_sha": "abc123"},
        }
    )
    assert rec is not None
    assert rec.question == "door got locked"
    assert rec.app_git_sha == "abc123"
    assert "use-and-care-w11156985" in rec.citations


def test_trace_record_parses_v2_string_io_and_preview() -> None:
    rec = trace_record_from_api(
        {
            "id": "tid-2",
            "name": "ask",
            "timestamp": "2026-08-27T00:00:00Z",
            "input": '{"question": "Why is my washer purple?"}',
            "output": (
                '{"abstained": true, "answer_preview": "ABSTAIN: no evidence.", '
                '"citations": ["W11320651 Rev A p.1"]}'
            ),
            "metadata": {"app_git_sha": 1.472e101},
        }
    )
    assert rec is not None
    assert rec.question.startswith("Why is my washer")
    assert rec.answer.startswith("ABSTAIN:")
    assert rec.app_git_sha and rec.app_git_sha.startswith("numeric-corrupt:")
    assert any("W11320651" in c for c in rec.citations)


def test_replay_pass_marks_resolved_stale(tmp_path: Path) -> None:
    """Old bad answer + current good ask_fn → resolved_stale; report only when write."""
    rec = TraceRecord(
        trace_id="old-midcycle",
        name="diagnose",
        timestamp="",
        question="stops after 10 minutes no error code",
        answer=(
            "Turn the cycle selector knob to Off then Normal and hold Start/Pause "
            "for 3 seconds to enter diagnostic mode."
        ),
        citations=["tech-sheet-w11320651"],
        app_git_sha="oldsha",
    )

    from repair_assistant.qa.context import Citation

    def good_ask2(_q: str) -> AnswerResult:
        return AnswerResult(
            question=_q,
            answer=(
                "Activate Service Diagnostic mode: standby, wait 30 seconds, "
                "select any three (3) buttons except POWER, repeat sequence, "
                "888 on display [1]."
            ),
            abstained=False,
            citations=[
                Citation(
                    index=1,
                    doc_id="service-manual-w11169652-revb",
                    chunk_id="c1",
                    label="W11169652 Rev B p.22",
                    page=22,
                    excerpt="Activating",
                )
            ],
        )

    result = run_mine(
        [rec],
        write=True,
        out_dir=tmp_path,
        include_unstamped=False,
        ask_fn=good_ask2,
        skip_replay=False,
    )
    assert any(o.status == "resolved_stale" for o in result.outcomes)
    assert result.report_path
    assert Path(result.report_path).is_file()
    assert "resolved_stale" in Path(result.report_path).read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*-trace-*.yaml"))
    assert not (tmp_path / "mine-state.json").exists()


def test_replay_fail_writes_analysis_report(tmp_path: Path) -> None:
    rec = TraceRecord(
        trace_id="live-bad",
        name="ask",
        timestamp="",
        question="door got locked XYZUNIQUE",
        answer="Ensure that door is completely closed so it will lock.",
        app_git_sha="newsha",
    )

    def still_bad(_q: str) -> AnswerResult:
        return AnswerResult(
            question=_q,
            answer="Ensure that door is completely closed so it will lock.",
            abstained=False,
            citations=[],
        )

    result = run_mine(
        [rec],
        write=True,
        out_dir=tmp_path,
        ask_fn=still_bad,
    )
    assert any(o.status == "actionable" for o in result.outcomes)
    assert result.report_path
    text = Path(result.report_path).read_text(encoding="utf-8")
    assert "Actionable" in text
    assert "wrong_polarity" in text
    assert "```yaml" in text
    assert not list(tmp_path.glob("*-trace-*.yaml"))
    assert not (tmp_path / "mine-state.json").exists()
    assert not (tmp_path / "improvements.md").exists()


def test_observation_merges_stamp_metadata(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("REPAIR_APP_GIT_SHA", "stampsha")
    tracing._app_git_sha = None  # reset cache
    tracing._langfuse_client = None

    fake_span = type("S", (), {"trace_id": "t", "id": "s", "end": lambda self: None})()
    calls: list[dict] = []

    class FakeClient:
        def start_observation(self, **kwargs):
            calls.append(kwargs)
            return fake_span

        def flush(self):
            return None

    monkeypatch.setattr(tracing, "_client", lambda: FakeClient())
    with tracing.observation("ask", input={"question": "hi"}):
        pass
    assert calls
    meta = calls[0]["metadata"]
    assert meta.get("app_git_sha") == "stampsha"
    assert "app_started_at" in meta
