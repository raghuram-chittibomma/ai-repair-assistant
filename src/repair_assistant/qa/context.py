"""Answer models and evidence formatting for grounded Q&A."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.parsing.page_classify import evidence_cites_unread_figure
from repair_assistant.retrieval.search import Hit

FIGURE_UNREADABLE_NOTE = (
    "Note: this assistant cannot read figures or wiring diagrams. "
    "If a cited procedure refers to a figure, consult that graphic in the source document."
)

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
    detail = _label_detail(hit.text or "")
    if detail:
        cite = f"{cite} — {detail}"
    return cite


def _label_detail(text: str) -> str:
    """Disambiguate same-page matrix / error-code rows in citation labels."""
    group = re.search(r"Table group:\s*([^\n|]+)", text, re.I)
    problem = re.search(r"(?:^|\n|\|)\s*Problem:\s*([^\n|]+)", text, re.I)
    parts: list[str] = []
    if group:
        parts.append(group.group(1).strip()[:48])
    if problem:
        p = re.sub(r"\s*\(.*$", "", problem.group(1).strip())[:48]
        if p and all(p.upper() not in existing.upper() for existing in parts):
            parts.append(p)
    if parts:
        return " / ".join(parts)
    # Error-code table rows: "Error Code: F0E2"
    code_m = re.search(r"Error Code:\s*([A-Z0-9]+)", text, re.I)
    if code_m:
        return code_m.group(1).upper()
    from repair_assistant.parsing.error_codes import extract_error_codes

    codes = extract_error_codes(text)
    if len(codes) == 1:
        return codes[0]
    return ""


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


EVIDENCE_BEGIN = "<<<MANUFACTURER_EVIDENCE>>>"
EVIDENCE_END = "<<<END_MANUFACTURER_EVIDENCE>>>"


def wrap_evidence(text: str) -> str:
    """Fence retrieved text so the model treats it as data, not instructions."""
    body = text.strip() if text else "(none)"
    return f"{EVIDENCE_BEGIN}\n{body}\n{EVIDENCE_END}"


def fence_evidence(text: str) -> str:
    """Wrap evidence unless it is already delimited."""
    raw = text or ""
    if EVIDENCE_BEGIN in raw:
        return raw
    return wrap_evidence(raw)


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
    if not blocks:
        return "", citations
    body = wrap_evidence("\n\n".join(blocks))
    cited_hits = hits[: len(citations)]
    if any(evidence_cites_unread_figure(h.text) for h in cited_hits):
        return f"{body}\n\n{FIGURE_UNREADABLE_NOTE}", citations
    return body, citations


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


def _label_theme(label: str) -> str:
    """Theme fragment after an em dash, e.g. 'Not cleaning clothes'."""
    if "—" in label:
        return label.split("—", 1)[1].strip().rstrip(".")
    if " - " in label:
        return label.split(" - ", 1)[1].strip().rstrip(".")
    return ""


def _label_themes(label: str) -> list[str]:
    """Matchable fragments from a citation label (group, problem, full theme)."""
    theme = _label_theme(label)
    if not theme:
        return []
    parts = [p.strip() for p in theme.split("/") if p.strip()]
    out: list[str] = []
    for part in parts:
        if len(part) >= 6:
            out.append(part)
    if len(theme) >= 6 and theme not in out:
        out.append(theme)
    return out


def citations_by_label_mention(answer: str, available: list[Citation]) -> list[Citation]:
    """When the model names a category but omits [n], match citation label themes."""
    text = (answer or "").lower()
    if not text.strip() or text.lstrip().upper().startswith("ABSTAIN:"):
        return []
    out: list[Citation] = []
    seen: set[int] = set()
    for cite in available:
        themes = _label_themes(cite.label)
        # Prefer the most specific (usually problem) segment: last path part.
        for theme in reversed(themes):
            if theme.lower() in text and cite.index not in seen:
                seen.add(cite.index)
                out.append(cite)
                break
    return out


def resolve_citations(answer: str, available: list[Citation]) -> list[Citation]:
    """Prefer explicit [n] markers; fall back to label themes named in the answer."""
    cited = citations_from_answer(answer, available)
    if cited:
        return cited
    return citations_by_label_mention(answer, available)
