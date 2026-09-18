"""Answer models and evidence formatting for grounded Q&A."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.corpus.precedence_drift import newer_revision_note
from repair_assistant.parsing.page_classify import evidence_cites_unread_figure
from repair_assistant.retrieval.search import Hit

FIGURE_UNREADABLE_NOTE = (
    "Note: this assistant cannot read figures or wiring diagrams. "
    "If a cited procedure refers to a figure, consult that graphic in the source document."
)
FIGURE_ATTACHED_NOTE = (
    "Note: a page image is attached for one or more evidence blocks that "
    "cite a figure. Use the image for location and orientation only; cite [n]; "
    "do not invent pin numbers, voltages, or hold times that are not in the "
    "cited modality (structured text or Attachment for evidence [n])."
)

_CITE_REF = re.compile(r"\[(\d+)\]")


def layout_from_hit(hit: Hit) -> tuple[dict | None, float | None, float | None]:
    """Table-row bbox from chunk metadata; omit unless complete and sane."""
    meta = getattr(hit, "metadata", None) or {}
    raw = meta.get("bbox") if isinstance(meta, dict) else None
    if not isinstance(raw, dict):
        return None, None, None
    try:
        box = {key: float(raw[key]) for key in ("x0", "y0", "x1", "y1")}
        width = float(meta["page_width"])
        height = float(meta["page_height"])
    except (KeyError, TypeError, ValueError):
        return None, None, None
    if box["x1"] <= box["x0"] or box["y1"] <= box["y0"] or width <= 0 or height <= 0:
        return None, None, None
    return box, width, height


@dataclass(frozen=True)
class Citation:
    index: int
    doc_id: str
    chunk_id: str
    label: str
    page: int | None
    excerpt: str
    block_text: str = ""
    bbox: dict | None = None
    page_width: float | None = None
    page_height: float | None = None


@dataclass
class AnswerResult:
    question: str
    answer: str
    abstained: bool
    abstain_reason: str = ""
    abstain_code: str = ""
    citations: list[Citation] = field(default_factory=list)
    claims: list = field(default_factory=list)
    evidence_blocks: dict[int, str] = field(default_factory=dict)
    retrieval_count: int = 0
    safety_action: str = "allow"
    safety_notice: str = ""
    escalated: bool = False
    figure_pages: list[dict] = field(default_factory=list)


def evidence_blocks_from_citations(citations: list[Citation]) -> dict[int, str]:
    """Map 1-based evidence index to the prompt block the model saw."""
    return {c.index: (c.block_text or c.excerpt or "") for c in citations}


def unit_page_label(hit: Hit) -> str:
    """Page range for a semantic unit, which may cover several pages."""
    meta = getattr(hit, "metadata", None) or {}
    if not isinstance(meta, dict):
        return ""
    label = meta.get("page_label")
    if isinstance(label, str) and label:
        return label
    start, end = meta.get("page_start"), meta.get("page_end")
    if start is None:
        return ""
    if end is None or end == start:
        return f"p.{start}"
    return f"pp.{start}-{end}"


def format_label(hit: Hit) -> str:
    cite = hit.publication_number or hit.doc_id
    if hit.revision:
        cite = f"{cite} Rev {hit.revision}"
    pages = unit_page_label(hit) if getattr(hit, "is_semantic_unit", False) else ""
    if pages:
        cite = f"{cite} {pages}"
    elif hit.page:
        cite = f"{cite} p.{hit.page}"
    cite = f"{cite} [{_ingestion_tag(hit)}]"
    if getattr(hit, "is_semantic_unit", False):
        title = str((hit.metadata or {}).get("unit_title") or "").strip()
        if title:
            return f"{cite} — {title[:64]}"
    detail = _label_detail(hit.text or "")
    if detail:
        cite = f"{cite} — {detail}"
    return cite


def _ingestion_tag(hit: Hit) -> str:
    """Short marker for citation UI: semantic (LLM units) vs structured ingest."""
    if getattr(hit, "is_semantic_unit", False):
        return "semantic"
    strategy = str(getattr(hit, "strategy", None) or "").strip()
    if strategy == "semantic_llm":
        return "semantic"
    if strategy == "structured" or not strategy:
        return "structured"
    return strategy


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


def evidence_text(hit: Hit, *, query: str = "") -> str:
    """Full stored text for one hit (audit ledger / attach-failure fallback).

    Pack-level budgets (``REPAIR_EVIDENCE_MAX_CHARS``) still apply in
    :func:`format_evidence`. For semantic units with a successful PDF/raster
    attach, the prompt fence shows a stub instead (ADR-0051); this helper
    still returns the full extract. ``query`` is kept for call-site
    compatibility.
    """
    del query  # no per-hit windowing (ADR-0050)
    return (hit.text or "").strip()


def _unit_locator(hit: Hit) -> str:
    """Stable unit id/type string for semantic stubs."""
    meta = hit.metadata if isinstance(hit.metadata, dict) else {}
    unit_key = str(meta.get("unit_key") or hit.chunk_id or "").strip() or "unit"
    unit_type = str(meta.get("unit_type") or "unit").strip() or "unit"
    return f"{unit_key} ({unit_type})"


def semantic_stub_body(hit: Hit, index: int) -> str:
    """Locator-only fence body when the PDF/raster attachment is primary."""
    label = format_label(hit)
    return (
        f"[{index}] {label}\n"
        f"modality: semantic_pdf\n"
        f"unit: {_unit_locator(hit)}\n"
        f"Authority for [{index}]: attached PDF page-range (or page images) "
        f"labeled [{index}].\n"
        f"Do not invent content not visible in that attachment."
    )


def semantic_fallback_body(hit: Hit, index: int, text: str) -> str:
    """Full extract when PDF/raster attach failed for this cite."""
    label = format_label(hit)
    return (
        f"[{index}] {label}\n"
        f"modality: semantic_text_fallback\n"
        f"Note: PDF/raster attach failed for [{index}]; "
        f"authority is the extract below.\n"
        f"{text}"
    )


def structured_prompt_body(hit: Hit, index: int, text: str) -> str:
    """Full structured chunk text with modality tag."""
    label = format_label(hit)
    return f"[{index}] {label}\nmodality: structured_text\n{text}"


def _prompt_body_for_hit(
    hit: Hit,
    index: int,
    full_text: str,
    *,
    semantic_attached_indexes: set[int] | frozenset[int] | None,
) -> str:
    """Fence body for one hit. Citations keep full_text separately (ADR-0051)."""
    if not getattr(hit, "is_semantic_unit", False):
        return structured_prompt_body(hit, index, full_text)
    # None = optimistic stub (pre-attach). Explicit set = stub only when attached.
    use_stub = (
        semantic_attached_indexes is None
        or index in semantic_attached_indexes
    )
    if use_stub:
        return semantic_stub_body(hit, index)
    return semantic_fallback_body(hit, index, full_text)


def _pack_cost(hit: Hit, full_text: str) -> int:
    """Budget cost: stub length for semantic units so extracts do not crowd out."""
    label_len = len(format_label(hit))
    if getattr(hit, "is_semantic_unit", False):
        # Index is unknown at selection time; stub length is stable aside from [n].
        stub = semantic_stub_body(hit, 1)
        return len(stub) + 8
    return len(full_text) + label_len + 8 + len("modality: structured_text\n")


def _pack_order(hits: list[Hit]) -> list[Hit]:
    """Keep the top hit first; among the rest, prefer rows that can highlight.

    A large semantic unit can consume most of the evidence budget. Without this
    reorder, a same-page prose banner often fills the remainder and drops the
    table-row that carries the PDF bbox overlay.
    """
    if len(hits) < 2:
        return list(hits)
    head, *rest = hits
    with_layout: list[Hit] = []
    without: list[Hit] = []
    for hit in rest:
        box, _, _ = layout_from_hit(hit)
        (with_layout if box is not None else without).append(hit)
    return [head, *with_layout, *without]


def format_evidence(
    hits: list[Hit],
    *,
    query: str = "",
    max_chars: int | None = None,
    manifest=None,
    attached_indexes: set[int] | frozenset[int] | None = None,
    semantic_attached_indexes: set[int] | frozenset[int] | None = None,
) -> tuple[str, list[Citation]]:
    """Numbered evidence blocks for the LLM prompt.

    Hits arrive best-first. When a character budget applies, a block that does
    not fit is dropped whole and the next one is tried, so a large semantic
    unit costs the lowest-ranked evidence rather than costing half of itself.
    The single exception is the top-ranked hit, which is always included:
    answering from nothing is worse than one oversize block, and truncating it
    is the failure this whole design exists to avoid.

    After that top hit, layout-bearing table rows are tried before plain prose
    so the source-page overlay still lights up when both compete for the
    leftover budget.

    Semantic units (ADR-0051): the fence shows a locator stub when PDF/raster
    attach succeeds (or optimistically when ``semantic_attached_indexes`` is
    None). ``Citation.block_text`` always keeps the full ``source_text`` for
    UI, audit, and claim groundedness. Attach failure falls back to full text
    for that ``[n]`` only.

    ``max_chars`` defaults to :func:`repair_assistant.qa.env.evidence_max_chars`
    (``REPAIR_EVIDENCE_MAX_CHARS``). Unset or ``0`` means no cap.
    """
    from repair_assistant.qa.env import evidence_max_chars

    budget = evidence_max_chars() if max_chars is None else max_chars
    selected: list[tuple[Hit, str]] = []
    used = 0
    for hit in _pack_order(hits):
        text = evidence_text(hit, query=query)
        cost = _pack_cost(hit, text)
        if (
            selected
            and budget is not None
            and used + cost > budget
        ):
            continue
        selected.append((hit, text))
        used += cost

    blocks: list[str] = []
    citations: list[Citation] = []
    for index, (hit, text) in enumerate(selected, 1):
        label = format_label(hit)
        blocks.append(
            _prompt_body_for_hit(
                hit,
                index,
                text,
                semantic_attached_indexes=semantic_attached_indexes,
            )
        )
        bbox, page_width, page_height = layout_from_hit(hit)
        citations.append(
            Citation(
                index=index,
                doc_id=hit.doc_id,
                chunk_id=hit.chunk_id,
                label=label,
                page=hit.page,
                excerpt=text[:280],
                block_text=text,
                bbox=bbox,
                page_width=page_width,
                page_height=page_height,
            )
        )
    if not blocks:
        return "", citations
    body = wrap_evidence("\n\n".join(blocks))
    cited_hits = [hit for hit, _ in selected]
    notes: list[str] = []
    attached = {int(i) for i in (attached_indexes or ())}
    if attached:
        notes.append(FIGURE_ATTACHED_NOTE)
    unread_missing = any(
        evidence_cites_unread_figure(hit.text) and cite.index not in attached
        for cite, hit in zip(citations, cited_hits, strict=False)
    )
    if unread_missing:
        notes.append(FIGURE_UNREADABLE_NOTE)
    if manifest is not None:
        stale = newer_revision_note(cited_hits, manifest)
        if stale:
            notes.append(stale)
    if notes:
        return f"{body}\n\n" + "\n".join(notes), citations
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
