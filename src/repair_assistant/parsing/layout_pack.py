"""Score ingested chunks against evals/parsing/layout-pack.yaml."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod

_APOSTROPHE = str.maketrans({"\u2019": "'", "\u2018": "'"})


@dataclass
class AssertResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PageResult:
    page_id: str
    pdf_page: int
    printed: str
    expect_class: str
    passed: bool
    asserts: list[AssertResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    observed_class: str | None = None


def load_layout_pack(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "parsing" / "layout-pack.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _norm(text: str) -> str:
    return (text or "").translate(_APOSTROPHE)


def _fold(text: str) -> str:
    return _norm(text).lower().replace("'", "")


def _page_blob(records: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for rec in records:
        parts.append(rec.get("text") or "")
        meta = rec.get("metadata") or {}
        parts.append(meta.get("body_text") or "")
    return _norm("\n".join(parts))


def _sections(records: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for rec in records:
        path = (rec.get("metadata") or {}).get("section_path") or []
        if isinstance(path, list):
            out.extend(str(p) for p in path if p)
        elif path:
            out.append(str(path))
    return out


def _run_assert(
    spec: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    blob: str,
    sections: list[str],
    observed_class: str | None,
) -> AssertResult:
    kind = spec.get("type") or "unknown"
    if kind == "phrase_present":
        missing = [p for p in spec.get("phrases") or [] if _fold(p) not in _fold(blob)]
        return AssertResult(
            kind,
            not missing,
            f"missing={missing}" if missing else "ok",
        )
    if kind == "phrase_absent":
        hits = [p for p in spec.get("phrases") or [] if _fold(p) in _fold(blob)]
        return AssertResult(
            kind,
            not hits,
            f"found={hits}" if hits else "ok",
        )
    if kind == "section_not_like":
        pattern = spec.get("pattern") or ""
        cre = re.compile(pattern, re.I | re.S)
        hits = [s for s in sections if cre.search(s)]
        return AssertResult(
            kind,
            not hits,
            f"matched={hits[:3]}" if hits else "ok",
        )
    if kind == "min_table_rows":
        n = sum(1 for r in records if r.get("kind") == "table_row")
        need = int(spec.get("min") or 0)
        return AssertResult(kind, n >= need, f"table_rows={n} min={need}")
    if kind == "max_prose_chunks":
        n = sum(1 for r in records if r.get("kind") in {"prose", "heading", "procedure"})
        cap = int(spec.get("max") or 0)
        return AssertResult(kind, n <= cap, f"prose_chunks={n} max={cap}")
    if kind == "expect_class":
        if not observed_class:
            return AssertResult(kind, True, "skipped: no parse_audit layout_kind")
        allowed = spec.get("classes") or [spec.get("class")]
        allowed = [c for c in allowed if c]
        ok = observed_class in allowed
        return AssertResult(kind, ok, f"observed={observed_class} allowed={allowed}")
    return AssertResult(kind, False, "unknown assert type")


def score_page(
    page_spec: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    layout_by_page: dict[int, str] | None = None,
) -> PageResult:
    pdf_page = int(page_spec["pdf_page"])
    expect_class = str(page_spec.get("class") or "")
    observed = (layout_by_page or {}).get(pdf_page)
    records = [c for c in chunks if c.get("page") == pdf_page]
    blob = _page_blob(records)
    sections = _sections(records)
    asserts = [
        _run_assert(
            a,
            records=records,
            blob=blob,
            sections=sections,
            observed_class=observed,
        )
        for a in (page_spec.get("asserts") or [])
    ]
    if page_spec.get("check_class") and expect_class and observed:
        asserts.append(
            _run_assert(
                {"type": "expect_class", "class": expect_class},
                records=records,
                blob=blob,
                sections=sections,
                observed_class=observed,
            )
        )
    passed = all(a.passed for a in asserts) if asserts else True
    return PageResult(
        page_id=str(page_spec.get("id") or pdf_page),
        pdf_page=pdf_page,
        printed=str(page_spec.get("printed") or ""),
        expect_class=expect_class,
        passed=passed,
        asserts=asserts,
        observed_class=observed,
    )


def load_chunks_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_layout_kinds(parse_audit_path: Path) -> dict[int, str]:
    if not parse_audit_path.is_file():
        return {}
    data = json.loads(parse_audit_path.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for audit in data.get("page_audits") or []:
        page = audit.get("page")
        kind = audit.get("layout_kind")
        if page is not None and kind:
            out[int(page)] = str(kind)
    return out


def run_layout_pack(
    *,
    pack_path: Path | None = None,
    parsed_dir: Path | None = None,
) -> list[PageResult]:
    pack = load_layout_pack(pack_path)
    corpus = manifest_mod.load()
    doc_id = pack["doc_id"]
    dest = parsed_dir or (corpus.root / "corpus" / "parsed" / doc_id)
    chunks_path = dest / "chunks.jsonl"
    if not chunks_path.is_file():
        return [
            PageResult(
                page_id="missing",
                pdf_page=0,
                printed="",
                expect_class="",
                passed=False,
                skipped=True,
                skip_reason=f"no {chunks_path}",
            )
        ]
    chunks = load_chunks_jsonl(chunks_path)
    layout_by_page = load_layout_kinds(dest / "parse_audit.json")
    return [score_page(spec, chunks, layout_by_page=layout_by_page) for spec in pack["pages"]]


def scorecard_markdown(results: list[PageResult]) -> str:
    lines = [
        "# Layout-pack scorecard",
        "",
        "| Page | Printed | PDF | Class (expect / observed) | Result | Detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r.skipped:
            lines.append(
                f"| {r.page_id} | {r.printed} | {r.pdf_page} | — | SKIP | {r.skip_reason} |"
            )
            continue
        failed = [a for a in r.asserts if not a.passed]
        detail = "; ".join(f"{a.name}:{a.detail}" for a in failed) or "ok"
        observed = r.observed_class or "—"
        mark = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| {r.page_id} | {r.printed} | {r.pdf_page} | "
            f"{r.expect_class} / {observed} | {mark} | {detail} |"
        )
    passed = sum(1 for r in results if r.passed and not r.skipped)
    total = sum(1 for r in results if not r.skipped)
    lines.extend(["", f"**{passed}/{total}** pages passed."])
    return "\n".join(lines) + "\n"


__all__ = [
    "PageResult",
    "load_layout_pack",
    "run_layout_pack",
    "score_page",
    "scorecard_markdown",
]
