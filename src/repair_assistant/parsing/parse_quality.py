"""Deterministic parse-quality signals (ADR-0024).

Generic Whirlpool-style signals live here. Document/page-specific marker lists
live in ``config/parsing/quality_overrides.yaml`` — never hardcode publication
numbers or absolute page indexes in Python.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .models import Table
from .table_context import is_troubleshooting_matrix, iter_contextual_rows

_REV_RE = re.compile(r"W\d{8}\s*([A-Z])\b|(W\d{8})([A-Z])(?:\.|$)", re.I)


@dataclass
class PageAudit:
    page: int
    layout_kind: str
    prose_source: str
    flags: list[str] = field(default_factory=list)
    retried: bool = False

    def suspect(self) -> bool:
        return bool(self.flags)


@dataclass(frozen=True)
class QualityOverride:
    """Config-driven expectations for one document page."""

    id: str
    phrase_markers: tuple[str, ...] = ()
    expect_steps: tuple[int, ...] = ()


def phrase_order_monotonic(text: str, markers: list[str]) -> bool:
    """True when every found marker appears in listed order."""
    positions: list[int] = []
    lower = text.lower()
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            positions.append(idx)
    if len(positions) < 2:
        return True
    return positions == sorted(positions)


def numbered_steps_present(text: str, steps: list[int]) -> list[int]:
    """Return step numbers from ``steps`` missing as ``N. `` prefixes."""
    missing: list[int] = []
    for n in steps:
        if not re.search(rf"(?:^|\n){n}\.\s", text, re.M):
            missing.append(n)
    return missing


def infer_contiguous_steps(text: str, *, min_span: int = 5) -> list[int] | None:
    """Infer ``1..N`` step expectations from procedure-like numbered prefixes.

    Family-generic: any page with a contiguous numbered procedure span can flag
    missing mid-steps without a doc-specific override.
    """
    found = sorted(
        {int(m.group(1)) for m in re.finditer(r"(?:^|\n)(\d+)\.\s", text)}
    )
    if len(found) < min_span:
        return None
    lo, hi = found[0], found[-1]
    if lo > 3 or (hi - lo + 1) < min_span:
        return None
    return list(range(lo, hi + 1))


def table_column_variance(tables: list[Table]) -> bool:
    """True when row widths vary widely within a table."""
    for table in tables:
        if not table.rows:
            continue
        width = max(len(table.headers), 3)
        counts = [len([c for c in row.cells if c.strip()]) for row in table.rows]
        if not counts:
            continue
        if max(counts) - min(counts) >= 2 and max(counts) >= 3:
            return True
        short = sum(1 for c in counts if c < width - 1)
        if short >= max(3, len(counts) // 2):
            return True
    return False


def matrix_missing_data_rows(tables: list[Table]) -> bool:
    for table in tables:
        if not is_troubleshooting_matrix(table.headers):
            continue
        data = [r for r in iter_contextual_rows(table) if r.role == "data"]
        if not data and table.rows:
            return True
    return False


def audit_page(
    *,
    page: int,
    text: str,
    tables: list[Table],
    layout_kind: str,
    prose_source: str,
    phrase_markers: list[str] | None = None,
    expect_steps: list[int] | None = None,
) -> PageAudit:
    flags: list[str] = []

    markers = phrase_markers or []
    if markers and not phrase_order_monotonic(text, markers):
        flags.append("reading_order_suspect")

    steps = expect_steps
    if steps is None and layout_kind == "multi_column":
        steps = infer_contiguous_steps(text)
    if steps:
        missing = numbered_steps_present(text, list(steps))
        if missing:
            flags.append("reading_order_suspect")

    if table_column_variance(tables):
        flags.append("table_structure_suspect")

    if matrix_missing_data_rows(tables):
        flags.append("matrix_no_data_rows")

    if layout_kind == "multi_column" and prose_source in {"pdfplumber"}:
        flags.append("reading_order_suspect")

    return PageAudit(
        page=page,
        layout_kind=layout_kind,
        prose_source=prose_source,
        flags=sorted(set(flags)),
    )


def default_overrides_path() -> Path:
    env = os.environ.get("REPAIR_PARSE_QUALITY_CONFIG", "").strip()
    if env:
        return Path(env)
    # Repo layout: <root>/config/parsing/quality_overrides.yaml
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "parsing" / "quality_overrides.yaml"
        if candidate.is_file():
            return candidate
    return here.parents[3] / "config" / "parsing" / "quality_overrides.yaml"


@lru_cache(maxsize=4)
def _load_override_rows(path_str: str) -> tuple[dict, ...]:
    path = Path(path_str)
    if not path.is_file():
        return ()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = payload.get("overrides") or []
    return tuple(rows) if isinstance(rows, list) else ()


def _basename_revision(name: str) -> str | None:
    m = _REV_RE.search(name.replace("_", " "))
    if not m:
        return None
    return (m.group(1) or m.group(3) or "").upper() or None


def _match_override(
    row: dict,
    *,
    path: Path,
    page: int,
    doc_id: str | None,
) -> bool:
    match = row.get("match") or {}
    if not isinstance(match, dict) or not match:
        return False
    name = path.name
    stem = path.stem

    if "page" in match and int(match["page"]) != page:
        return False
    if "doc_id" in match and (doc_id or "") != str(match["doc_id"]):
        return False
    if "filename" in match and str(match["filename"]).lower() not in name.lower():
        return False
    if "publication_number" in match:
        pub = str(match["publication_number"]).upper()
        if pub not in name.upper() and pub not in stem.upper():
            return False
    if "revision" in match:
        want = str(match["revision"]).upper()
        got = _basename_revision(name) or _basename_revision(stem)
        if got != want:
            return False
    return True


def quality_override_for(
    path: Path | str,
    page: int,
    *,
    doc_id: str | None = None,
    config_path: Path | str | None = None,
) -> QualityOverride | None:
    """Return the first matching config override for this document page."""
    path = Path(path)
    cfg = Path(config_path) if config_path else default_overrides_path()
    for row in _load_override_rows(str(cfg.resolve())):
        if not isinstance(row, dict):
            continue
        if not _match_override(row, path=path, page=page, doc_id=doc_id):
            continue
        markers = tuple(str(m) for m in (row.get("phrase_markers") or []))
        steps_raw = row.get("expect_steps") or []
        steps = tuple(int(s) for s in steps_raw)
        return QualityOverride(
            id=str(row.get("id") or "override"),
            phrase_markers=markers,
            expect_steps=steps,
        )
    return None


def clear_quality_override_cache() -> None:
    _load_override_rows.cache_clear()


__all__ = [
    "PageAudit",
    "QualityOverride",
    "audit_page",
    "phrase_order_monotonic",
    "numbered_steps_present",
    "infer_contiguous_steps",
    "quality_override_for",
    "default_overrides_path",
    "clear_quality_override_cache",
]
