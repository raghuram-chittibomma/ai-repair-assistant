"""Bounded chunk quality audit and safe auto-repair (ADR-0022).

Straight-line improve: audit → at most one repair pass → re-audit → stop.
Never a while-loop; never re-extract or re-chunk.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from repair_assistant.parsing.models import Chunk

MAX_REPAIR_PASSES = 1

# Findings that are reported but never auto-repaired.
FLAG_ONLY_CODES = frozenset(
    {
        "error_code_unbound",
        "oversized_prose",
        "empty_or_garbage_headers",
    }
)

_GARBAGE_HEADER_RE = re.compile(r"^(col(?:umn)?\s*\d+|unnamed:?\s*\d*)$", re.IGNORECASE)
_ALPHA_RE = re.compile(r"[A-Za-z]")


@dataclass
class Finding:
    code: str
    severity: str
    chunk_id: str
    detail: str = ""
    repairable: bool = False


@dataclass
class QualityReport:
    findings: list[Finding] = field(default_factory=list)
    repairs_applied: list[dict[str, str]] = field(default_factory=list)
    stop_reason: str = "clean"
    repair_passes: int = 0

    def counts_by_code(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.code] = out.get(f.code, 0) + 1
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "stop_reason": self.stop_reason,
            "repair_passes": self.repair_passes,
            "counts": self.counts_by_code(),
            "critical_count": sum(1 for f in self.findings if f.severity == "critical"),
            "findings": [asdict(f) for f in self.findings[:80]],
            "repairs_applied": list(self.repairs_applied),
        }


def fingerprint(chunks: list[Chunk]) -> str:
    pairs = sorted(f"{c.chunk_id}:{c.content_hash()}" for c in chunks)
    return "|".join(pairs)


def _body(chunk: Chunk) -> str:
    return str(chunk.metadata.get("body_text") or chunk.text)


def _headers(chunk: Chunk) -> list[str]:
    raw = chunk.metadata.get("headers") or chunk.metadata.get("table_headers") or []
    return [str(h) for h in raw]


def _already_repaired(chunk: Chunk, code: str) -> bool:
    repairs = chunk.metadata.get("quality", {}).get("repairs") or []
    return any(isinstance(r, dict) and r.get("code") == code for r in repairs)


def _record_repair(chunk: Chunk, code: str, action: str) -> None:
    quality = dict(chunk.metadata.get("quality") or {})
    repairs = list(quality.get("repairs") or [])
    repairs.append({"code": code, "action": action})
    quality["repairs"] = repairs
    chunk.metadata["quality"] = quality


def _is_opaque_numeric(text: str) -> bool:
    stripped = text.strip()
    if not stripped or not any(ch.isdigit() for ch in stripped):
        return False
    letters = len(_ALPHA_RE.findall(stripped))
    return letters < 8


def _headers_missing_from_text(chunk: Chunk) -> bool:
    headers = [h for h in _headers(chunk) if h and h.strip()]
    if not headers:
        return False
    text = chunk.text or ""
    return any(h not in text for h in headers)


def _garbage_headers(headers: list[str]) -> bool:
    if not headers:
        return True
    cleaned = [h.strip() for h in headers]
    if not any(cleaned):
        return True
    return all(not h or _GARBAGE_HEADER_RE.match(h) for h in cleaned)


def audit_chunks(chunks: list[Chunk]) -> QualityReport:
    """Scan chunks for quality findings. Pure — does not mutate."""
    findings: list[Finding] = []
    table_codes = {c for ch in chunks if ch.kind == "table_row" for c in ch.error_codes}

    for chunk in chunks:
        headers = _headers(chunk)
        body = _body(chunk)

        if chunk.kind == "table_row":
            if _garbage_headers(headers):
                findings.append(
                    Finding(
                        code="empty_or_garbage_headers",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="table headers blank or placeholder",
                        repairable=False,
                    )
                )
            elif _headers_missing_from_text(chunk):
                findings.append(
                    Finding(
                        code="headers_in_meta_not_text",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="headers in metadata but not in text",
                        repairable=True,
                    )
                )

            if _is_opaque_numeric(body) and not _is_opaque_numeric(chunk.text):
                pass  # already enriched
            elif _is_opaque_numeric(chunk.text) and headers and not _garbage_headers(headers):
                findings.append(
                    Finding(
                        code="opaque_numeric_row",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="mostly numeric table row lacks labels in text",
                        repairable=True,
                    )
                )
            elif _is_opaque_numeric(chunk.text) and _garbage_headers(headers):
                findings.append(
                    Finding(
                        code="opaque_numeric_row",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="opaque numeric row without usable headers",
                        repairable=False,
                    )
                )

            if chunk.error_codes:
                parts = [p.strip() for p in body.split("|") if p.strip()]
                # Code-only row (single cell / code equals body) — flag, do not merge.
                if len(parts) < 2 or body.strip() in set(chunk.error_codes):
                    findings.append(
                        Finding(
                            code="error_code_unbound",
                            severity="critical",
                            chunk_id=chunk.chunk_id,
                            detail="error code row has little/no remedy text",
                            repairable=False,
                        )
                    )

        if not chunk.metadata.get("section_path") and chunk.kind in {
            "prose",
            "procedure",
            "table_row",
        }:
            # Informational when we cannot know if a heading existed; repair only
            # if metadata already has a pending section_title proposal.
            if chunk.metadata.get("section_title_proposal"):
                findings.append(
                    Finding(
                        code="missing_section_path",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="section proposal not yet applied",
                        repairable=True,
                    )
                )

        if chunk.kind in {"prose", "procedure", "table_row", "heading"}:
            doc_label = chunk.metadata.get("doc_title") or chunk.publication_number
            if doc_label and str(doc_label) not in (chunk.text or ""):
                findings.append(
                    Finding(
                        code="missing_doc_context",
                        severity="info",
                        chunk_id=chunk.chunk_id,
                        detail="document label not present in text",
                        repairable=True,
                    )
                )

        if chunk.kind != "table_row" and chunk.error_codes:
            if set(chunk.error_codes) <= table_codes and len(_body(chunk)) < 120:
                findings.append(
                    Finding(
                        code="duplicate_table_as_prose",
                        severity="warning",
                        chunk_id=chunk.chunk_id,
                        detail="prose duplicates table_row error codes",
                        repairable=True,
                    )
                )

        if chunk.kind in {"prose", "procedure"} and len(_body(chunk)) > 4000:
            findings.append(
                Finding(
                    code="oversized_prose",
                    severity="info",
                    chunk_id=chunk.chunk_id,
                    detail=f"body length {len(_body(chunk))}",
                    repairable=False,
                )
            )

    return QualityReport(findings=findings)


def _rebuild_text(chunk: Chunk) -> str:
    """Rebuild display/embed text from body + ancestry metadata."""
    from repair_assistant.parsing.chunker import format_contextual_text

    headers = _headers(chunk)
    section_path = chunk.metadata.get("section_path") or []
    section = section_path[-1] if section_path else chunk.metadata.get("section_title_proposal")
    doc_title = chunk.metadata.get("doc_title")
    return format_contextual_text(
        body=_body(chunk),
        doc_title=doc_title if isinstance(doc_title, str) else None,
        publication_number=chunk.publication_number,
        revision=chunk.revision,
        section=section if isinstance(section, str) else None,
        headers=headers or None,
        kind=chunk.kind,
    )


def repair_chunks(chunks: list[Chunk], report: QualityReport) -> list[Chunk]:
    """Apply safe repairs for repairable findings in ``report`` only."""
    by_id = {c.chunk_id: c for c in chunks}
    drop_ids: set[str] = set()

    for finding in report.findings:
        if not finding.repairable or finding.code in FLAG_ONLY_CODES:
            continue
        chunk = by_id.get(finding.chunk_id)
        if chunk is None or _already_repaired(chunk, finding.code):
            continue

        if finding.code == "duplicate_table_as_prose":
            drop_ids.add(chunk.chunk_id)
            _record_repair(chunk, finding.code, "drop_duplicate_prose")
            continue

        if finding.code in {
            "headers_in_meta_not_text",
            "opaque_numeric_row",
            "missing_doc_context",
            "missing_section_path",
        }:
            if finding.code == "missing_section_path":
                proposal = chunk.metadata.get("section_title_proposal")
                if proposal:
                    path = list(chunk.metadata.get("section_path") or [])
                    if proposal not in path:
                        path.append(str(proposal))
                    chunk.metadata["section_path"] = path

            chunk.text = _rebuild_text(chunk)
            # chunk_id is derived from text at creation; keep stable id for repair path
            _record_repair(chunk, finding.code, "rebuild_contextual_text")

    if drop_ids:
        return [c for c in chunks if c.chunk_id not in drop_ids]
    return chunks


def audit_and_improve(chunks: list[Chunk]) -> tuple[list[Chunk], QualityReport]:
    """Bounded improve: at most one repair pass, then always stop."""
    report_0 = audit_chunks(chunks)
    repairable = [f for f in report_0.findings if f.repairable]
    if not repairable:
        reason = "clean" if not report_0.findings else "no_repairable"
        report_0.stop_reason = reason
        report_0.repair_passes = 0
        return chunks, report_0

    before = fingerprint(chunks)
    repaired = repair_chunks(chunks, report_0)
    applied = []
    for c in repaired:
        for r in (c.metadata.get("quality") or {}).get("repairs") or []:
            if isinstance(r, dict):
                applied.append({"chunk_id": c.chunk_id, **r})
    # Dedupe applied list to this pass only (new repairs): compare to empty baseline
    # by re-reading — repairs_applied = those recorded during this call.
    report_0.repairs_applied = applied
    report_0.repair_passes = MAX_REPAIR_PASSES

    if fingerprint(repaired) == before:
        report_0.stop_reason = "no_progress"
        return repaired, report_0

    report_1 = audit_chunks(repaired)
    report_1.repairs_applied = applied
    report_1.repair_passes = MAX_REPAIR_PASSES

    # Ineffective: a repairable code we attempted still present on same chunk.
    attempted = {(a["chunk_id"], a["code"]) for a in applied}
    still = {
        (f.chunk_id, f.code)
        for f in report_1.findings
        if f.repairable and (f.chunk_id, f.code) in attempted
    }
    if still:
        report_1.stop_reason = "repair_ineffective"
    else:
        report_1.stop_reason = "after_one_repair"
    return repaired, report_1


__all__ = [
    "FLAG_ONLY_CODES",
    "MAX_REPAIR_PASSES",
    "Finding",
    "QualityReport",
    "audit_and_improve",
    "audit_chunks",
    "fingerprint",
    "repair_chunks",
]
