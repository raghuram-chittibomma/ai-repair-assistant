"""Attach pdfplumber word-span rectangles to prose chunks (ADR-0038)."""

from __future__ import annotations

from repair_assistant.parsing.models import BBox, Word
from repair_assistant.parsing.pua import map_pua
from repair_assistant.parsing.table_bbox import BBOX_SPACE

MIN_TOKENS = 8
MIN_CHARS = 40
CLUSTER_GAP_RATIO = 0.25
SKIP_LAYOUT_KINDS = frozenset({"figure", "schematic", "toc"})


def normalize_prose(text: str) -> str:
    return " ".join(map_pua(text or "").split())


def words_from_pdfplumber(page: object) -> list[Word]:
    """In-memory word list from extract_words(); empty on failure."""
    try:
        raw = page.extract_words() or []
    except Exception:
        return []
    out: list[Word] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = map_pua(str(item.get("text") or "")).strip()
        if not text:
            continue
        try:
            x0 = float(item["x0"])
            x1 = float(item["x1"])
            # extract_words() uses top/bottom; y0/y1 appear on raw chars.
            y0 = float(item["top"] if "top" in item else item["y0"])
            y1 = float(item["bottom"] if "bottom" in item else item["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        out.append(Word(text=text, x0=x0, y0=y0, x1=x1, y1=y1))
    return out


def _haystack(words: list[Word]) -> tuple[str, list[tuple[int, int, int]]]:
    """Collapsed word string plus (start, end, word_index) spans."""
    parts: list[str] = []
    offsets: list[tuple[int, int, int]] = []
    pos = 0
    for index, word in enumerate(words):
        token = normalize_prose(word.text)
        if not token:
            continue
        if parts:
            pos += 1
        start = pos
        parts.append(token)
        pos += len(token)
        offsets.append((start, pos, index))
    return " ".join(parts), offsets


def _one_cluster(words: list[Word], page_width: float) -> bool:
    if len(words) < 2:
        return bool(words)
    gap = CLUSTER_GAP_RATIO * page_width
    ordered = sorted(words, key=lambda w: (w.x0, w.y0))
    prev_x1 = ordered[0].x1
    for word in ordered[1:]:
        if word.x0 - prev_x1 > gap:
            return False
        prev_x1 = max(prev_x1, word.x1)
    return True


def _union(words: list[Word]) -> BBox | None:
    if not words:
        return None
    return BBox(
        x0=min(w.x0 for w in words),
        y0=min(w.y0 for w in words),
        x1=max(w.x1 for w in words),
        y1=max(w.y1 for w in words),
    )


def match_span_bbox(
    body: str,
    words: list[Word],
    page_width: float | None,
    page_height: float | None = None,
    *,
    layout_kind: str | None = None,
    min_tokens: int = MIN_TOKENS,
    min_chars: int = MIN_CHARS,
    require_cluster: bool = True,
) -> BBox | None:
    """Unique contiguous word-span in one x-cluster, or None."""
    del page_height
    if (layout_kind or "") in SKIP_LAYOUT_KINDS:
        return None
    width = float(page_width or 0)
    if width <= 0 or not words:
        return None
    needle = normalize_prose(body)
    tokens = needle.split()
    if not needle or (len(tokens) < min_tokens and len(needle) < min_chars):
        return None
    haystack, offsets = _haystack(words)
    if not haystack:
        return None
    hits: list[list[int]] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        end = idx + len(needle)
        span = [i for s, e, i in offsets if e > idx and s < end]
        if span:
            hits.append(span)
        start = idx + 1
        if len(hits) > 1:
            return None
    if len(hits) != 1:
        return None
    span_words = [words[i] for i in hits[0]]
    if require_cluster and not _one_cluster(span_words, width):
        return None
    return _union(span_words)


def span_layout_metadata(
    bbox: BBox | None,
    page_width: float | None,
    page_height: float | None,
) -> dict:
    """Chunk metadata keys for a prose span (empty when geometry is missing)."""
    out: dict = {}
    if page_width and page_height:
        out["page_width"] = float(page_width)
        out["page_height"] = float(page_height)
    if bbox is None:
        return out
    out["bbox"] = bbox.to_dict()
    out["bbox_space"] = BBOX_SPACE
    return out


def attach_prose_layout(
    meta: dict,
    page: object,
    body: str,
    *,
    min_tokens: int = MIN_TOKENS,
    min_chars: int = MIN_CHARS,
    require_cluster: bool = True,
) -> None:
    """Merge bbox onto prose/procedure/heading metadata when the span is unique."""
    kind = getattr(page, "layout_kind", None)
    box = match_span_bbox(
        body,
        list(getattr(page, "words", None) or []),
        getattr(page, "page_width", None),
        getattr(page, "page_height", None),
        layout_kind=kind,
        min_tokens=min_tokens,
        min_chars=min_chars,
        require_cluster=require_cluster,
    )
    if box is None:
        return
    meta.update(
        span_layout_metadata(
            box,
            getattr(page, "page_width", None),
            getattr(page, "page_height", None),
        )
    )


def attach_table_row_prose_layout(
    meta: dict,
    page: object,
    *,
    cause: str,
    checks: str,
    body: str,
) -> None:
    """Unique cause/check cell spans when there is no find_tables() row box.

    Guide #1 cells are shorter than ADR-0038 prose, and a row spans columns, so
    the one-cluster rule would refuse a real table row. Still no box unless the
    needle is unique on the page.
    """
    width = getattr(page, "page_width", None)
    height = getattr(page, "page_height", None)
    if width and height:
        meta.setdefault("page_width", float(width))
        meta.setdefault("page_height", float(height))
    words = list(getattr(page, "words", None) or [])
    kind = getattr(page, "layout_kind", None)
    boxes: list[BBox] = []
    for needle in (cause, checks):
        text = (needle or "").strip()
        if not text:
            continue
        box = match_span_bbox(
            text,
            words,
            width,
            height,
            layout_kind=kind,
            min_tokens=2,
            min_chars=8,
            require_cluster=True,
        )
        if box is not None:
            boxes.append(box)
    if not boxes:
        box = match_span_bbox(
            (body or "").strip(),
            words,
            width,
            height,
            layout_kind=kind,
            require_cluster=False,
        )
        if box is not None:
            boxes.append(box)
    if not boxes:
        return
    union = BBox(
        x0=min(b.x0 for b in boxes),
        y0=min(b.y0 for b in boxes),
        x1=max(b.x1 for b in boxes),
        y1=max(b.y1 for b in boxes),
    )
    meta.update(span_layout_metadata(union, width, height))


__all__ = [
    "CLUSTER_GAP_RATIO",
    "MIN_CHARS",
    "MIN_TOKENS",
    "SKIP_LAYOUT_KINDS",
    "attach_prose_layout",
    "attach_table_row_prose_layout",
    "match_span_bbox",
    "normalize_prose",
    "span_layout_metadata",
    "words_from_pdfplumber",
]
