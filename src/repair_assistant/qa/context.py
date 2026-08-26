"""Answer models and evidence formatting for grounded Q&A."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.retrieval.search import Hit

_CITE_REF = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class Citation:
    index: int
    doc_id: str
    chunk_id: str
    label: str
    page: int | None
    excerpt: str


@dataclass
class AnswerResult:
    question: str
    answer: str
    abstained: bool
    abstain_reason: str = ""
    abstain_code: str = ""
    citations: list[Citation] = field(default_factory=list)
    retrieval_count: int = 0
    safety_action: str = "allow"
    safety_notice: str = ""
    escalated: bool = False


def format_label(hit: Hit) -> str:
    cite = hit.publication_number or hit.doc_id
    if hit.revision:
        cite = f"{cite} Rev {hit.revision}"
    if hit.page:
        cite = f"{cite} p.{hit.page}"
    return cite


def _excerpt(text: str, *, max_len: int = 2000, query: str = "") -> str:
    """Prefer a query-relevant window when truncating long procedure chunks."""
    normalized = " ".join(text.split())
    if len(normalized) <= max_len:
        return normalized

    needles: list[str] = []
    query_l = query.lower()
    for term in (
        "status led",
        "diagnostic led",
        "acu led",
        "step 10",
        "blink",
        "acu power check",
        "shipping bolt",
        "transport bolt",
    ):
        if term in query_l or term in normalized.lower():
            needles.append(term)

    for needle in needles:
        pos = normalized.lower().find(needle)
        if pos < 0:
            continue
        start = max(0, pos - max_len // 3)
        end = min(len(normalized), start + max_len)
        snippet = normalized[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(normalized):
            snippet = snippet + "..."
        return snippet

    return normalized[: max_len - 3] + "..."


def format_evidence(
    hits: list[Hit],
    *,
    query: str = "",
    max_chars: int = 12_000,
) -> tuple[str, list[Citation]]:
    """Numbered evidence blocks for the LLM prompt."""
    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0
    for i, hit in enumerate(hits, 1):
        text = _excerpt(hit.text, query=query)
        block = f"[{i}] {format_label(hit)}\n{text}"
        if used + len(block) > max_chars and citations:
            break
        blocks.append(block)
        used += len(block)
        citations.append(
            Citation(
                index=i,
                doc_id=hit.doc_id,
                chunk_id=hit.chunk_id,
                label=format_label(hit),
                page=hit.page,
                excerpt=text[:280],
            )
        )
    return "\n\n".join(blocks), citations


def citations_from_answer(answer: str, available: list[Citation]) -> list[Citation]:
    """Map [1], [2] references in the model output to Citation rows."""
    by_index = {c.index: c for c in available}
    seen: set[int] = set()
    out: list[Citation] = []
    for match in _CITE_REF.finditer(answer):
        idx = int(match.group(1))
        if idx in by_index and idx not in seen:
            seen.add(idx)
            out.append(by_index[idx])
    return out
