"""Column-aware reading order for two-column PDF pages (ADR-0024)."""

from __future__ import annotations

from typing import Any


def detect_partition_x(page: Any, words: list[dict] | None = None) -> float | None:
    """Return x-coordinate of vertical partition, or None if single-column."""
    words = words if words is not None else (page.extract_words() or [])
    if len(words) < 40:
        return None

    page_width = float(getattr(page, "width", 612) or 612)
    mid = page_width / 2

    # pdfplumber vertical rules (partition lines).
    for line in page.lines or []:
        if abs(line["x0"] - line["x1"]) < 2 and (line["bottom"] - line["top"]) > 80:
            x = float(line["x0"])
            if page_width * 0.25 < x < page_width * 0.75:
                return x

    left = sum(1 for w in words if w["x0"] < mid - 20)
    right = sum(1 for w in words if w["x0"] > mid + 20)
    if left >= 30 and right >= 30:
        return mid

    return None


def _words_to_lines(words: list[dict], *, line_tol: float = 3.0) -> list[str]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None

    for word in sorted_words:
        top = float(word["top"])
        if current_top is None or abs(top - current_top) <= line_tol:
            current.append(word)
            if current_top is None:
                current_top = top
        else:
            lines.append(current)
            current = [word]
            current_top = top
    if current:
        lines.append(current)

    out: list[str] = []
    for group in lines:
        group.sort(key=lambda w: w["x0"])
        out.append(" ".join(w["text"] for w in group))
    return out


def _chars_to_lines(chars: list[dict], *, line_tol: float = 3.0) -> list[str]:
    if not chars:
        return []
    sorted_chars = sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"]))
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None

    for char in sorted_chars:
        top = float(char["top"])
        if current_top is None or abs(top - current_top) <= line_tol:
            current.append(char)
            if current_top is None:
                current_top = top
        else:
            lines.append(current)
            current = [char]
            current_top = top
    if current:
        lines.append(current)

    out: list[str] = []
    for group in lines:
        group.sort(key=lambda c: c["x0"])
        out.append("".join(c["text"] for c in group))
    return out


def reorder_page_text(page: Any) -> tuple[str, bool, float | None]:
    """Left column top-to-bottom, then right column. Returns (text, reordered, partition_x)."""
    words = page.extract_words() or []
    partition = detect_partition_x(page, words)
    if partition is None:
        return (page.extract_text() or ""), False, None

    chars = page.chars or []
    if chars:
        left_chars = [c for c in chars if c["x0"] < partition - 5]
        right_chars = [c for c in chars if c["x0"] >= partition - 5]
        left_lines = _chars_to_lines(left_chars)
        right_lines = _chars_to_lines(right_chars)
    else:
        left_words = [w for w in words if w["x0"] < partition - 5]
        right_words = [w for w in words if w["x0"] >= partition - 5]
        left_lines = _words_to_lines(left_words)
        right_lines = _words_to_lines(right_words)

    text = "\n".join(left_lines + ([""] if left_lines and right_lines else []) + right_lines)
    return text, True, partition


__all__ = ["detect_partition_x", "reorder_page_text"]
