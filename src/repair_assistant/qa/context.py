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
    citations: list[Citation] = field(default_factory=list)
    retrieval_count: int = 0


def format_label(hit: Hit) -> str:
    cite = hit.publication_number or hit.doc_id
    if hit.revision:
        cite = f"{cite} Rev {hit.revision}"
    if hit.page:
        cite = f"{cite} p.{hit.page}"
    return cite


def format_evidence(hits: list[Hit], *, max_chars: int = 12_000) -> tuple[str, list[Citation]]:
    """Numbered evidence blocks for the LLM prompt."""
    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0
    for i, hit in enumerate(hits, 1):
        text = " ".join(hit.text.split())
        if len(text) > 2000:
            text = text[:1997] + "..."
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
