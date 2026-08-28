"""Mine Langfuse traces into a reviewable analysis report (ADR-0023 / Phase 11).

Stale-trace control: stamp filter + time window + **replay on current code**.
``--write`` only emits an analysis file under ``evals/qa/drafts/`` — no live
fixture edits, no auto-promote, no persistent mine-state.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.eval.candidates_bench import load_candidates
from repair_assistant.eval.grading import grade_answer
from repair_assistant.ingest.env import load_dotenv_files
from repair_assistant.qa.context import AnswerResult
from repair_assistant.qa.generate import ask
from repair_assistant.retrieval.intent import extract_intent
from repair_assistant.retrieval.query_expand import door_lock_polarity

DEFAULT_DRAFTS_DIR = Path("evals/qa/drafts")

_WS = re.compile(r"\s+")
_ABSTAIN = re.compile(r"^ABSTAIN:\s*(.*)$", re.I | re.M)
_INVENTED_KNOB = re.compile(
    r"cycle selector|turn the cycle|to the \"Off\"|to \"Normal\"|"
    r"Start/Pause.{0,40}3 seconds",
    re.I,
)
_DIAG_WORDS = re.compile(r"diagnostic|service diagnostic", re.I)
_PROCEDURAL = re.compile(
    r"\b(follow these steps|press and hold|enter the|activate)\b",
    re.I,
)
_F5E2_ASSERTED = re.compile(
    r"\b(you have|showing|display shows|error code)\s+F5\s*E?2\b|"
    r"\bF5\s*E?2\s+(is|means|indicates)\b",
    re.I,
)


@dataclass
class TraceRecord:
    """Normalized view of one Langfuse ask/diagnose interaction."""

    trace_id: str
    name: str
    timestamp: str
    question: str
    answer: str
    turns: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    abstained: bool = False
    abstain_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    app_git_sha: str | None = None


@dataclass
class MineOutcome:
    trace_id: str
    failure_codes: list[str]
    status: str  # actionable | resolved_stale | skipped | covered
    detail: str = ""
    fingerprint: str = ""
    question: str = ""
    suggested_yaml: str | None = None


@dataclass
class MineRunResult:
    outcomes: list[MineOutcome]
    report_path: str | None = None
    stamp: str = ""


def drafts_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / DEFAULT_DRAFTS_DIR


def normalize_question(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def fingerprint(failure_code: str, question: str) -> str:
    return f"{failure_code}|{normalize_question(question)}"


def parse_since(spec: str, *, now: datetime | None = None) -> datetime:
    """Parse ``7d`` / ``24h`` / ``30m`` into a timezone-aware cutoff."""
    now = now or datetime.now(UTC)
    raw = (spec or "7d").strip().lower()
    m = re.fullmatch(r"(\d+)\s*([dhm])", raw)
    if not m:
        raise ValueError(f"invalid --since {spec!r}; use e.g. 7d, 24h, 30m")
    n = int(m.group(1))
    unit = m.group(2)
    delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[
        unit
    ]
    return now - delta


def classify_trace(rec: TraceRecord) -> list[str]:
    """Rule-based failure tags from the recorded answer (candidates for replay)."""
    codes: list[str] = []
    q = rec.question or ""
    answer = rec.answer or ""
    intent = extract_intent(q)

    if _INVENTED_KNOB.search(answer) and _DIAG_WORDS.search(answer):
        codes.append("invented_diag_entry")

    if answer.upper().lstrip().startswith("ABSTAIN:") and (
        intent.needs_clarification
        or "error code" in answer.lower()
        or "door lock" in answer.lower()
    ):
        codes.append("clarify_as_abstain")

    polarity = door_lock_polarity(q)
    if polarity == "unlock" and re.search(
        r"won'?t lock|will not lock|door not closed|Ensure that door is completely closed",
        answer,
        re.I,
    ):
        codes.append("wrong_polarity")

    if intent.needs_clarification and not answer.upper().lstrip().startswith("ABSTAIN:"):
        # Procedural jump without clarify
        if re.search(r"test\s*#\s*4|replace the door lock", answer, re.I):
            codes.append("skip_clarify")

    if _PROCEDURAL.search(answer) and not rec.citations and not rec.abstained:
        codes.append("empty_cites_procedure")

    if _F5E2_ASSERTED.search(answer) and "F5E2" not in (q.upper()) and "F5 E2" not in q.upper():
        if "if " not in answer.lower()[:80]:
            codes.append("plan_code_as_fact")

    return list(dict.fromkeys(codes))


def grading_for_failure(code: str, rec: TraceRecord) -> dict[str, Any]:
    """Light deterministic keys used for replay and draft stubs."""
    if code == "invented_diag_entry":
        return {
            "expect_cites_any": ["W11169652"],
            "expect_contains_any": [
                "Service Diagnostic",
                "diagnostic mode",
                "888",
                "three (3) buttons",
                "three buttons",
            ],
            "fails_if_contains": ["cycle selector", 'to "Normal"'],
        }
    if code == "wrong_polarity":
        return {
            "expect_contains_any": ["unlock", "open", "Add Garment", "pause"],
            "fails_if_contains": [
                "won't lock",
                "will not lock",
                "Ensure that door is completely closed",
            ],
        }
    if code in {"clarify_as_abstain", "skip_clarify"}:
        return {
            "expect_contains_any": ["stuck", "unlock", "lock", "F5E2", "open", "closed"],
            "fails_if_contains": ["replace the door lock", "test #4", "TEST #4"],
        }
    if code == "empty_cites_procedure":
        return {
            "expect_cites_any": ["W11169652", "W11320651", "W11156989", "W11156985"],
            "fails_if_contains": ["follow these steps"],
        }
    if code == "plan_code_as_fact":
        return {
            "expect_contains_any": ["If", "if you", "possible", "may"],
            "fails_if_contains": ["you have F5E2", "showing F5E2"],
        }
    return {"expect_contains_any": [rec.question[:20]] if rec.question else ["."]}


def ready_question_norms() -> set[str]:
    """Normalized questions already covered by ready candidates or smoke (read-only)."""
    norms: set[str] = set()
    smoke = Path("evals/qa/smoke-scenarios.yaml")
    if smoke.is_file():
        data = yaml.safe_load(smoke.read_text(encoding="utf-8")) or {}
        for sc in data.get("scenarios") or []:
            if sc.get("question"):
                norms.add(normalize_question(sc["question"]))
            for turn in sc.get("turns") or []:
                norms.add(normalize_question(str(turn)))
    try:
        cands = load_candidates()
    except Exception:
        return norms
    for family in cands.get("families") or []:
        for sc in family.get("scenarios") or []:
            if sc.get("status") != "ready":
                continue
            if sc.get("question"):
                norms.add(normalize_question(sc["question"]))
            for turn in sc.get("turns") or []:
                norms.add(normalize_question(str(turn)))
    return norms


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_git_sha(value: Any) -> str | None:
    """Normalize Langfuse metadata SHA (strings, or float corruption of short SHAs)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        # Short SHAs like 1472e98 were parsed as scientific notation — mark stamped
        # but do not pretend we recovered the original hex.
        return f"numeric-corrupt:{value:.6g}"
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None


def _metadata_from_obj(obj: Any) -> dict[str, Any]:
    meta = getattr(obj, "metadata", None)
    if isinstance(meta, dict):
        return dict(meta)
    if isinstance(obj, dict):
        m = obj.get("metadata")
        return dict(m) if isinstance(m, dict) else {}
    return {}


def trace_record_from_api(trace: Any, observations: list[Any] | None = None) -> TraceRecord | None:
    """Build a TraceRecord from Langfuse trace + optional observation list."""
    if isinstance(trace, dict):
        tid = str(trace.get("id") or "")
        name = str(trace.get("name") or "")
        ts = str(trace.get("timestamp") or trace.get("createdAt") or "")
        inp = _parse_jsonish(trace.get("input"))
        out = _parse_jsonish(trace.get("output"))
        meta = dict(trace.get("metadata") or {})
    else:
        tid = str(getattr(trace, "id", "") or "")
        name = str(getattr(trace, "name", "") or "")
        ts = str(getattr(trace, "timestamp", "") or getattr(trace, "created_at", "") or "")
        inp = _parse_jsonish(getattr(trace, "input", None))
        out = _parse_jsonish(getattr(trace, "output", None))
        meta = _metadata_from_obj(trace)

    if not tid:
        return None

    question = ""
    answer = ""
    turns: list[str] = []
    citations: list[str] = []
    abstained = False
    abstain_code = ""

    if isinstance(inp, dict):
        question = str(
            inp.get("question")
            or inp.get("user_message")
            or inp.get("message")
            or ""
        )
        if inp.get("turns"):
            turns = [str(t) for t in inp["turns"]]
    elif isinstance(inp, str):
        question = inp

    if isinstance(out, dict):
        answer = str(
            out.get("answer")
            or out.get("answer_preview")
            or out.get("assistant_message")
            or out.get("content")
            or ""
        )
        abstained = bool(out.get("abstained"))
        abstain_code = str(out.get("abstain_code") or "")
        cites = out.get("citations") or []
        if isinstance(cites, list):
            for c in cites:
                if isinstance(c, dict):
                    citations.append(
                        str(
                            c.get("doc_id")
                            or c.get("label")
                            or c.get("publication_number")
                            or ""
                        )
                    )
                else:
                    citations.append(str(c))
    elif isinstance(out, str):
        answer = out

    # Fall back to observation payloads.
    for obs in observations or []:
        ometa = _metadata_from_obj(obs)
        meta.update({k: v for k, v in ometa.items() if k not in meta})
        o_in = _parse_jsonish(
            getattr(obs, "input", None) if not isinstance(obs, dict) else obs.get("input")
        )
        o_out = _parse_jsonish(
            getattr(obs, "output", None) if not isinstance(obs, dict) else obs.get("output")
        )
        o_name = str(
            getattr(obs, "name", "") if not isinstance(obs, dict) else obs.get("name") or ""
        )
        if not question and isinstance(o_in, dict):
            question = str(
                o_in.get("question") or o_in.get("user_message") or o_in.get("message") or ""
            )
        if not answer and isinstance(o_out, dict):
            answer = str(
                o_out.get("answer")
                or o_out.get("answer_preview")
                or o_out.get("content")
                or o_out.get("assistant_message")
                or ""
            )
            if o_out.get("citations"):
                for c in o_out["citations"]:
                    if isinstance(c, dict):
                        citations.append(str(c.get("doc_id") or ""))
                    else:
                        citations.append(str(c))
        if o_name in {"ask", "diagnose"} and not name:
            name = o_name

    if not question and not answer:
        return None
    if not name:
        name = "ask"

    sha = _coerce_git_sha(meta.get("app_git_sha"))
    return TraceRecord(
        trace_id=tid,
        name=name,
        timestamp=ts,
        question=question or (turns[0] if turns else ""),
        answer=answer,
        turns=turns,
        citations=[c for c in citations if c],
        abstained=abstained,
        abstain_code=abstain_code,
        metadata=meta,
        app_git_sha=sha,
    )


def _observation_to_trace_dict(obs: Any, *, name_hint: str) -> dict[str, Any]:
    if isinstance(obs, dict):
        tid = str(obs.get("trace_id") or obs.get("traceId") or "")
        ts = str(obs.get("start_time") or obs.get("startTime") or obs.get("created_at") or "")
        meta = dict(obs.get("metadata") or {})
        return {
            "id": tid,
            "name": str(obs.get("name") or obs.get("trace_name") or name_hint),
            "timestamp": ts,
            "input": obs.get("input"),
            "output": obs.get("output"),
            "metadata": meta,
        }
    tid = str(getattr(obs, "trace_id", "") or "")
    ts = str(
        getattr(obs, "start_time", "")
        or getattr(obs, "created_at", "")
        or ""
    )
    return {
        "id": tid,
        "name": str(getattr(obs, "name", None) or getattr(obs, "trace_name", None) or name_hint),
        "timestamp": ts,
        "input": getattr(obs, "input", None),
        "output": getattr(obs, "output", None),
        "metadata": _metadata_from_obj(obs),
    }


def fetch_langfuse_traces(*, since: datetime, limit: int = 50) -> list[TraceRecord]:
    """Fetch recent ask/diagnose roots via Langfuse Observations API v2.

    Langfuse v4 ``events_only`` deployments 404 the legacy ``/traces`` list API.
    """
    load_dotenv_files()
    from langfuse import Langfuse

    host = (os.environ.get("LANGFUSE_HOST") or "http://localhost:3000").strip()
    client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"].strip(),
        secret_key=os.environ["LANGFUSE_SECRET_KEY"].strip(),
        host=host,
    )

    # Prefer root ask/diagnose observations; fields must request io+metadata.
    fields = "core,io,metadata"
    # Split budget so diagnose is not starved when ask volume is high.
    per_name = max(1, (limit + 1) // 2)
    seen: set[str] = set()
    records: list[TraceRecord] = []

    for name in ("ask", "diagnose"):
        try:
            page = client.api.observations.get_many(
                limit=per_name,
                from_start_time=since,
                name=name,
                fields=fields,
                is_root_observation=True,
            )
        except Exception:
            # Older SDKs / servers may not support is_root_observation.
            page = client.api.observations.get_many(
                limit=per_name,
                from_start_time=since,
                name=name,
                fields=fields,
            )
        for obs in list(getattr(page, "data", None) or []):
            payload = _observation_to_trace_dict(obs, name_hint=name)
            tid = payload.get("id") or ""
            if not tid or tid in seen:
                continue
            rec = trace_record_from_api(payload)
            if not rec:
                continue
            # Ensure command name even when observation.name is null in v4.
            if rec.name not in {"ask", "diagnose"}:
                rec.name = name
            seen.add(tid)
            records.append(rec)

    # Newest first when timestamps are present.
    def _ts_key(rec: TraceRecord) -> str:
        return rec.timestamp or ""

    records.sort(key=_ts_key, reverse=True)
    return records[:limit]


def filter_traces(
    records: list[TraceRecord],
    *,
    require_git_sha: bool = True,
    since_sha: str | None = None,
    include_unstamped: bool = False,
) -> list[TraceRecord]:
    kept: list[TraceRecord] = []
    for rec in records:
        if require_git_sha and not include_unstamped and not rec.app_git_sha:
            continue
        if since_sha and rec.app_git_sha and rec.app_git_sha != since_sha:
            continue
        kept.append(rec)
    return kept


def _citation_strings(result: AnswerResult) -> list[str]:
    out: list[str] = []
    for c in result.citations or []:
        out.append(getattr(c, "doc_id", "") or "")
        label = getattr(c, "label", "") or ""
        if label:
            out.append(label)
    return [x for x in out if x]


def replay_still_fails(
    rec: TraceRecord,
    failure_code: str,
    *,
    ask_fn: Callable[..., AnswerResult] | None = None,
    db: Any = None,
) -> tuple[bool, str]:
    """Return (still_fails, detail) using current ask() path by default."""
    grades = grading_for_failure(failure_code, rec)
    question = rec.question
    appliance = Appliance(model="WFW5620HW0")

    if ask_fn is not None:
        result = ask_fn(question)
    else:
        if db is None:
            raise RuntimeError("replay requires db or ask_fn")
        result = ask(
            db,
            manifest_mod.load(),
            question,
            appliance=appliance,
        )

    passed, detail = grade_answer(
        grades,
        answer=result.answer,
        citations=_citation_strings(result),
        abstained=result.abstained,
    )
    return (not passed), detail or ("pass" if passed else "fail")


def build_draft_yaml(
    rec: TraceRecord,
    failure_code: str,
    *,
    stamp: str,
) -> dict[str, Any]:
    """Suggested fixture stub for the analysis report (not written as a live file)."""
    grades = grading_for_failure(failure_code, rec)
    sid = f"draft-{failure_code}-{rec.trace_id[:8]}"
    return {
        "version": 1,
        "status": "draft",
        "note": (
            "Suggested by mine-traces analysis. Copy into smoke-scenarios "
            "or candidates.yaml with status: ready only after human review."
        ),
        "promoted_from_trace": rec.trace_id,
        "failure_code": failure_code,
        "mined_at": stamp,
        "app_git_sha_at_trace": rec.app_git_sha,
        "scenarios": [
            {
                "id": sid,
                "command": "ask" if rec.name != "diagnose" else "diagnose",
                "question": rec.question if rec.name != "diagnose" else None,
                "turns": rec.turns or ([rec.question] if rec.question else None),
                "appliance": {"model": "WFW5620HW0"},
                **grades,
            }
        ],
    }


def format_mine_report(outcomes: list[MineOutcome], *, stamp: str) -> str:
    """Human-readable analysis; the only durable artifact when ``--write`` is set."""
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1

    lines = [
        f"# mine-traces analysis ({stamp})",
        "",
        "Read-only review artifact (ADR-0023). This file does **not** change live",
        "eval fixtures, prompts, or Langfuse. Take actions below only if you choose.",
        "",
        "## Summary",
        "",
    ]
    if counts:
        lines.append(", ".join(f"**{k}**={v}" for k, v in sorted(counts.items())))
    else:
        lines.append("No traces after filters.")
    lines.append("")

    sections = [
        (
            "actionable",
            "## Actionable (still fails on current code)",
            "Consider promoting a fixture by hand from the suggested YAML.",
        ),
        (
            "resolved_stale",
            "## Resolved stale (fixed on replay — no action needed)",
            "Historical traces; current path already passes light grading.",
        ),
        (
            "covered",
            "## Already covered by ready fixtures",
            "A ready smoke/candidate question already matches.",
        ),
        (
            "skipped",
            "## Skipped",
            "No failure rules fired, or fingerprint already noted in this run.",
        ),
    ]
    for status, heading, blurb in sections:
        group = [o for o in outcomes if o.status == status]
        lines.extend([heading, "", blurb, ""])
        if not group:
            lines.extend(["_(none)_", ""])
            continue
        for o in group:
            codes = ", ".join(o.failure_codes) or "—"
            q = (o.question or "")[:120]
            lines.append(f"- **trace** `{o.trace_id}` · codes=`{codes}` · {o.detail}")
            if q:
                lines.append(f"  - question: {q!r}")
            if o.fingerprint:
                lines.append(f"  - fingerprint: `{o.fingerprint}`")
            if o.suggested_yaml:
                lines.extend(["", "```yaml", o.suggested_yaml.rstrip(), "```", ""])
            else:
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_mine_report(
    outcomes: list[MineOutcome],
    *,
    out_dir: Path,
    stamp: str,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mine-report-{stamp}.md"
    path.write_text(format_mine_report(outcomes, stamp=stamp), encoding="utf-8")
    return path


def run_mine(
    records: list[TraceRecord],
    *,
    write: bool = False,
    out_dir: Path | None = None,
    require_git_sha: bool = True,
    include_unstamped: bool = False,
    since_sha: str | None = None,
    replay: bool = True,
    ask_fn: Callable[..., AnswerResult] | None = None,
    db: Any = None,
    skip_replay: bool = False,
) -> MineRunResult:
    """Classify → dedupe → replay → analysis report (optional).

    Never mutates live fixtures or mine-state. ``skip_replay`` is for unit tests.
    """
    out = drafts_dir() if out_dir is None else out_dir
    ready_q = ready_question_norms()
    seen_fps: set[str] = set()

    filtered = filter_traces(
        records,
        require_git_sha=require_git_sha,
        since_sha=since_sha,
        include_unstamped=include_unstamped,
    )
    outcomes: list[MineOutcome] = []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    for rec in filtered:
        codes = classify_trace(rec)
        if not codes:
            outcomes.append(
                MineOutcome(
                    rec.trace_id,
                    [],
                    "skipped",
                    detail="no failure rules",
                    question=rec.question,
                )
            )
            continue

        for code in codes:
            fp = fingerprint(code, rec.question)
            if fp in seen_fps:
                outcomes.append(
                    MineOutcome(
                        rec.trace_id,
                        [code],
                        "skipped",
                        detail="fingerprint already noted in this run",
                        fingerprint=fp,
                        question=rec.question,
                    )
                )
                continue
            if normalize_question(rec.question) in ready_q:
                seen_fps.add(fp)
                outcomes.append(
                    MineOutcome(
                        rec.trace_id,
                        [code],
                        "covered",
                        detail="ready fixture already covers question",
                        fingerprint=fp,
                        question=rec.question,
                    )
                )
                continue

            do_replay = replay and not skip_replay
            if do_replay:
                still_fails, detail = replay_still_fails(
                    rec, code, ask_fn=ask_fn, db=db
                )
            else:
                still_fails, detail = True, "replay skipped"

            if not still_fails:
                seen_fps.add(fp)
                outcomes.append(
                    MineOutcome(
                        rec.trace_id,
                        [code],
                        "resolved_stale",
                        detail=detail,
                        fingerprint=fp,
                        question=rec.question,
                    )
                )
                continue

            payload = build_draft_yaml(rec, code, stamp=stamp)
            for sc in payload["scenarios"]:
                for k in list(sc.keys()):
                    if sc[k] is None:
                        del sc[k]
            suggested = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
            seen_fps.add(fp)
            outcomes.append(
                MineOutcome(
                    rec.trace_id,
                    [code],
                    "actionable",
                    detail=detail,
                    fingerprint=fp,
                    question=rec.question,
                    suggested_yaml=suggested,
                )
            )

    report_path: str | None = None
    if write:
        path = write_mine_report(outcomes, out_dir=out, stamp=stamp)
        report_path = str(path)

    return MineRunResult(outcomes=outcomes, report_path=report_path, stamp=stamp)


__all__ = [
    "MineOutcome",
    "MineRunResult",
    "TraceRecord",
    "build_draft_yaml",
    "classify_trace",
    "fetch_langfuse_traces",
    "filter_traces",
    "fingerprint",
    "format_mine_report",
    "grading_for_failure",
    "normalize_question",
    "parse_since",
    "replay_still_fails",
    "run_mine",
    "trace_record_from_api",
    "write_mine_report",
]
