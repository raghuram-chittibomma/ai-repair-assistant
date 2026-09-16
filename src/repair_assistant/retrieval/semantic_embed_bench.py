"""Draft bake-off: embed semantic reps vs thin PDF ``source_text`` (not production).

Compares three in-memory / DB arms on a single ``semantic_llm`` document:

* ``semantic_reps`` — vectors already stored on ``kind=semantic_rep`` rows
* ``source_text_windows`` — embed the unit extract split to the BGE budget
* ``source_text_truncate`` — one vector per unit using only the first budget
  tokens (what silent truncation would do)

Query-time search is cosine over normalised BGE vectors (same as pgvector).
Indexing and query wall times are measured; paid OpenAI curator cost for
representations is estimated from token counts (extract path avoids that call).
Production ``search()`` is unchanged.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.ingest.embeddings import Embedder, get_shared_embedder
from repair_assistant.ingest.env import database_url, embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.semantic.env import semantic_llm_model
from repair_assistant.semantic.tokens import DEFAULT_TOKEN_BUDGET, count_tokens

ARMS = (
    "semantic_reps",
    "source_text_windows",
    "source_text_truncate",
)

# Ballpark list prices for curator-cost *estimates* only (USD / 1M tokens).
# Override via fixture file ``openai_price_per_mtok`` if needed. Not billed here.
_DEFAULT_INPUT_PER_MTOK = 2.50
_DEFAULT_OUTPUT_PER_MTOK = 10.00


@dataclass
class VectorRecord:
    """One searchable vector tied back to a semantic unit."""

    unit_key: str
    unit_id: int
    doc_id: str
    publication_number: str | None
    label: str  # chunk_id or synthetic window id
    text: str
    vector: list[float]
    tokens: int
    page_start: int | None = None
    page_end: int | None = None
    rep_kind: str | None = None


@dataclass
class IndexBuildStats:
    arm: str
    records: int
    embed_calls: int
    embed_tokens: int
    wall_ms: float
    reused_db_vectors: int = 0
    units: int = 0
    over_budget_units: int = 0


@dataclass
class QueryResult:
    fixture_id: str
    arm: str
    passed: bool
    hard: bool
    detail: str
    latency_ms: float
    hit_at_k: bool
    mrr: float | None
    first_rank: int | None
    top_keys: list[str] = field(default_factory=list)


@dataclass
class BakeoffReport:
    doc_id: str
    k: int
    budget: int
    embedding_model: str
    index_stats: list[IndexBuildStats]
    query_results: list[QueryResult]
    curator_estimate: dict[str, Any]


def _parse_vector(raw: Any) -> list[float]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    text = str(raw).strip()
    if text.startswith("["):
        return [float(x) for x in text[1:-1].split(",") if x.strip()]
    return [float(x) for x in text.split(",") if x.strip()]


def window_source_text(text: str, *, budget: int = DEFAULT_TOKEN_BUDGET) -> list[str]:
    """Pack paragraphs into windows that fit the embedder budget.

    Falls back to hard character slices when a single paragraph still overflows.
    """
    body = (text or "").strip()
    if not body:
        return []
    if count_tokens(body) <= budget:
        return [body]

    paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [body]

    windows: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            windows.append("\n".join(current))
            current = []

    for para in paragraphs:
        if count_tokens(para) > budget:
            flush()
            # Character-greedy pack under budget.
            start = 0
            while start < len(para):
                lo, hi = start + 1, len(para)
                best = start + 1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    piece = para[start:mid]
                    if count_tokens(piece) <= budget:
                        best = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                windows.append(para[start:best])
                start = best
            continue
        trial = "\n".join([*current, para]) if current else para
        if current and count_tokens(trial) > budget:
            flush()
            current = [para]
        else:
            current.append(para)
    flush()
    return windows


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def search_records(
    query_vec: list[float],
    records: list[VectorRecord],
    *,
    k: int,
) -> list[tuple[float, VectorRecord]]:
    scored = [(_dot(query_vec, r.vector), r) for r in records if r.vector]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Collapse multiple windows/reps of the same unit: keep best score.
    seen: set[str] = set()
    out: list[tuple[float, VectorRecord]] = []
    for score, rec in scored:
        if rec.unit_key in seen:
            continue
        seen.add(rec.unit_key)
        out.append((score, rec))
        if len(out) >= k:
            break
    return out


def load_bakeoff_spec(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (
        root / "evals" / "retrieval" / "experiments" / "semantic_embed_bakeoff.yaml"
    )
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_active_units(db: Database, doc_id: str) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT u.id, u.unit_key, u.title, u.page_start, u.page_end, u.source_text,
               v.doc_id, d.publication_number
        FROM semantic_units u
        JOIN ingestion_versions v ON v.id = u.ingestion_version_id
        LEFT JOIN documents d ON d.doc_id = v.doc_id
        WHERE v.doc_id = %s AND v.status = 'active'
        ORDER BY u.ordinal
        """,
        (doc_id,),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "unit_id": int(row[0]),
                "unit_key": str(row[1]),
                "title": str(row[2] or ""),
                "page_start": row[3],
                "page_end": row[4],
                "source_text": str(row[5] or ""),
                "doc_id": str(row[6]),
                "publication_number": row[7],
            }
        )
    return out


def build_rep_index(db: Database, doc_id: str) -> tuple[list[VectorRecord], IndexBuildStats]:
    t0 = time.perf_counter()
    rows = db.fetchall(
        """
        SELECT chunk_id, unit_id, rep_kind, text, embedding::text,
               publication_number, metadata
        FROM chunks
        WHERE doc_id = %s AND kind = 'semantic_rep' AND embedding IS NOT NULL
        ORDER BY unit_id, rep_kind
        """,
        (doc_id,),
    )
    records: list[VectorRecord] = []
    tokens = 0
    for row in rows:
        meta = row[6] if isinstance(row[6], dict) else {}
        text = str(row[3] or "")
        tok = int(meta.get("rep_tokens") or count_tokens(text))
        tokens += tok
        records.append(
            VectorRecord(
                unit_key=str(meta.get("unit_key") or ""),
                unit_id=int(row[1]),
                doc_id=doc_id,
                publication_number=row[5],
                label=str(row[0]),
                text=text,
                vector=_parse_vector(row[4]),
                tokens=tok,
                page_start=meta.get("page_start"),
                page_end=meta.get("page_end"),
                rep_kind=str(row[2] or ""),
            )
        )
    # Fill missing unit_key from units table if metadata incomplete.
    if any(not r.unit_key for r in records):
        by_id = {
            u["unit_id"]: u["unit_key"]
            for u in _load_active_units(db, doc_id)
        }
        for rec in records:
            if not rec.unit_key:
                rec.unit_key = by_id.get(rec.unit_id, f"unit-{rec.unit_id}")
    wall = (time.perf_counter() - t0) * 1000
    stats = IndexBuildStats(
        arm="semantic_reps",
        records=len(records),
        embed_calls=0,
        embed_tokens=tokens,
        wall_ms=wall,
        reused_db_vectors=len(records),
        units=len({r.unit_id for r in records}),
    )
    return records, stats


def build_source_window_index(
    units: list[dict[str, Any]],
    embedder: Embedder,
    *,
    budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[list[VectorRecord], IndexBuildStats]:
    t0 = time.perf_counter()
    texts: list[str] = []
    meta: list[tuple[dict[str, Any], int, str]] = []
    over = 0
    for unit in units:
        windows = window_source_text(unit["source_text"], budget=budget)
        if count_tokens(unit["source_text"]) > budget:
            over += 1
        for i, win in enumerate(windows):
            texts.append(win)
            meta.append((unit, i, win))
    vectors = embedder.embed(texts) if texts else []
    records: list[VectorRecord] = []
    tok_total = 0
    for (unit, i, win), vec in zip(meta, vectors, strict=True):
        tok = count_tokens(win)
        tok_total += tok
        records.append(
            VectorRecord(
                unit_key=unit["unit_key"],
                unit_id=unit["unit_id"],
                doc_id=unit["doc_id"],
                publication_number=unit.get("publication_number"),
                label=f"{unit['unit_key']}#w{i}",
                text=win,
                vector=vec,
                tokens=tok,
                page_start=unit.get("page_start"),
                page_end=unit.get("page_end"),
            )
        )
    wall = (time.perf_counter() - t0) * 1000
    stats = IndexBuildStats(
        arm="source_text_windows",
        records=len(records),
        embed_calls=len(texts),
        embed_tokens=tok_total,
        wall_ms=wall,
        units=len(units),
        over_budget_units=over,
    )
    return records, stats


def build_source_truncate_index(
    units: list[dict[str, Any]],
    embedder: Embedder,
    *,
    budget: int = DEFAULT_TOKEN_BUDGET,
) -> tuple[list[VectorRecord], IndexBuildStats]:
    t0 = time.perf_counter()
    texts: list[str] = []
    kept_units: list[dict[str, Any]] = []
    over = 0
    for unit in units:
        body = unit["source_text"]
        if not body.strip():
            continue
        if count_tokens(body) <= budget:
            piece = body
        else:
            over += 1
            # First window only — silent truncation analogue.
            piece = window_source_text(body, budget=budget)[0]
        texts.append(piece)
        kept_units.append(unit)
    vectors = embedder.embed(texts) if texts else []
    records: list[VectorRecord] = []
    tok_total = 0
    for unit, text, vec in zip(kept_units, texts, vectors, strict=True):
        tok = count_tokens(text)
        tok_total += tok
        records.append(
            VectorRecord(
                unit_key=unit["unit_key"],
                unit_id=unit["unit_id"],
                doc_id=unit["doc_id"],
                publication_number=unit.get("publication_number"),
                label=f"{unit['unit_key']}#trunc",
                text=text,
                vector=vec,
                tokens=tok,
                page_start=unit.get("page_start"),
                page_end=unit.get("page_end"),
            )
        )
    wall = (time.perf_counter() - t0) * 1000
    stats = IndexBuildStats(
        arm="source_text_truncate",
        records=len(records),
        embed_calls=len(texts),
        embed_tokens=tok_total,
        wall_ms=wall,
        units=len(kept_units),
        over_budget_units=over,
    )
    return records, stats


def _grade(
    fixture: dict[str, Any],
    ranked: list[tuple[float, VectorRecord]],
) -> tuple[bool, str, bool, float | None, int | None, list[str]]:
    top_keys = [rec.unit_key for _, rec in ranked]
    pubs = {str(rec.publication_number) for _, rec in ranked if rec.publication_number}

    def rank_of(label: str) -> int | None:
        for i, key in enumerate(top_keys, 1):
            if key == label:
                return i
        return None

    must = [str(x) for x in (fixture.get("must_cite") or [])]
    must_any = [str(x) for x in (fixture.get("must_cite_any") or [])]
    must_pub = [str(x) for x in (fixture.get("must_cite_any_pub") or [])]

    details: list[str] = []
    ok = True
    ranks: list[int] = []

    for label in must:
        r = rank_of(label)
        if r is None:
            ok = False
            details.append(f"missing {label}")
        else:
            ranks.append(r)

    if must_any:
        any_ranks = [rank_of(label) for label in must_any]
        hit = [r for r in any_ranks if r is not None]
        if not hit:
            ok = False
            details.append(f"missing any of {must_any}")
        else:
            ranks.append(min(hit))

    if must_pub:
        if not any(p in pubs for p in must_pub):
            ok = False
            details.append(f"missing pub {must_pub}")

    first = min(ranks) if ranks else None
    mrr = (1.0 / first) if first else (None if (must or must_any) else None)
    hit = first is not None if (must or must_any) else ok
    detail = "; ".join(details) if details else "ok"
    return ok, detail, hit, mrr, first, top_keys


def estimate_curator_cost(
    units: list[dict[str, Any]],
    rep_records: list[VectorRecord],
    *,
    input_per_mtok: float = _DEFAULT_INPUT_PER_MTOK,
    output_per_mtok: float = _DEFAULT_OUTPUT_PER_MTOK,
) -> dict[str, Any]:
    """Rough USD for one representation pass (not measured API billing)."""
    prompt_tokens = 0
    for unit in units:
        # Mirrors representations.build_user_prompt size (title + body).
        prompt_tokens += count_tokens(
            f"Unit title: {unit.get('title')}\n\nUnit content:\n{unit['source_text']}"
        )
    out_tokens = sum(r.tokens for r in rep_records)
    usd = (prompt_tokens / 1_000_000) * input_per_mtok + (
        out_tokens / 1_000_000
    ) * output_per_mtok
    return {
        "model": semantic_llm_model() or "(SEMANTIC_LLM_MODEL unset)",
        "prompt_tokens_est": prompt_tokens,
        "completion_tokens_est": out_tokens,
        "usd_est": round(usd, 4),
        "price_in_per_mtok": input_per_mtok,
        "price_out_per_mtok": output_per_mtok,
        "note": (
            "Estimate only — extract/window arms skip this curator LLM call. "
            "Local BGE embed cost is $0 for all arms."
        ),
    }


def run_bakeoff(
    *,
    spec_path: Path | None = None,
    embedder: Embedder | None = None,
    budget: int = DEFAULT_TOKEN_BUDGET,
) -> BakeoffReport:
    spec = load_bakeoff_spec(spec_path)
    doc_id = str(spec["doc_id"])
    k = int(spec.get("k") or 5)
    fixtures = list(spec.get("fixtures") or [])
    prices = spec.get("openai_price_per_mtok") or {}
    embedder = embedder or get_shared_embedder(model=embedding_model())

    with Database(database_url()) as db:
        units = _load_active_units(db, doc_id)
        if not units:
            raise RuntimeError(
                f"no active semantic units for {doc_id}; activate a semantic version first"
            )
        rep_records, rep_stats = build_rep_index(db, doc_id)
        win_records, win_stats = build_source_window_index(
            units, embedder, budget=budget
        )
        trunc_records, trunc_stats = build_source_truncate_index(
            units, embedder, budget=budget
        )

    indexes = {
        "semantic_reps": rep_records,
        "source_text_windows": win_records,
        "source_text_truncate": trunc_records,
    }
    index_stats = [rep_stats, win_stats, trunc_stats]
    curator = estimate_curator_cost(
        units,
        rep_records,
        input_per_mtok=float(prices.get("input", _DEFAULT_INPUT_PER_MTOK)),
        output_per_mtok=float(prices.get("output", _DEFAULT_OUTPUT_PER_MTOK)),
    )

    results: list[QueryResult] = []
    for fixture in fixtures:
        q = str(fixture["question"])
        t_embed = time.perf_counter()
        qvec = embedder.embed([q])[0]
        embed_ms = (time.perf_counter() - t_embed) * 1000
        for arm, records in indexes.items():
            t0 = time.perf_counter()
            ranked = search_records(qvec, records, k=k)
            search_ms = (time.perf_counter() - t0) * 1000
            passed, detail, hit, mrr, first, top_keys = _grade(fixture, ranked)
            results.append(
                QueryResult(
                    fixture_id=str(fixture["id"]),
                    arm=arm,
                    passed=passed,
                    hard=bool(fixture.get("hard", True)),
                    detail=detail,
                    latency_ms=embed_ms + search_ms,
                    hit_at_k=hit,
                    mrr=mrr,
                    first_rank=first,
                    top_keys=top_keys,
                )
            )

    return BakeoffReport(
        doc_id=doc_id,
        k=k,
        budget=budget,
        embedding_model=embedder.model,
        index_stats=index_stats,
        query_results=results,
        curator_estimate=curator,
    )


def scorecard_markdown(report: BakeoffReport) -> str:
    lines = [
        "# Semantic embed bake-off (draft)",
        "",
        *scorecard_repro_lines(),
        "",
        f"Document: `{report.doc_id}` · K={report.k} · budget={report.budget} · "
        f"embedder=`{report.embedding_model}`",
        "",
        "Production `search()` unchanged. Experiment fixtures only — not the S4 gate.",
        "Insufficient evidence for a production change (recorded 2026-09-16).",
        "",
        "## Indexing cost (one-time)",
        "",
        "| Arm | units | vectors | embed calls | embed tokens | wall ms | DB reuse |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in report.index_stats:
        lines.append(
            f"| `{s.arm}` | {s.units} | {s.records} | {s.embed_calls} | "
            f"{s.embed_tokens} | {s.wall_ms:.0f} | {s.reused_db_vectors} |"
        )
    c = report.curator_estimate
    lines.extend(
        [
            "",
            "### Curator LLM cost (representations arm only, estimate)",
            "",
            f"- Model: `{c['model']}`",
            f"- Prompt tokens ≈ {c['prompt_tokens_est']:,}",
            f"- Completion tokens ≈ {c['completion_tokens_est']:,}",
            f"- USD ≈ **${c['usd_est']:.4f}** "
            f"(in ${c['price_in_per_mtok']}/MTok, out ${c['price_out_per_mtok']}/MTok)",
            f"- {c['note']}",
            "",
            "Local BGE embedding is **$0** API cost for every arm.",
            "",
            "## Query metrics",
            "",
        ]
    )

    by_arm: dict[str, list[QueryResult]] = {a: [] for a in ARMS}
    for row in report.query_results:
        by_arm.setdefault(row.arm, []).append(row)

    lines.extend(
        [
            "| Arm | hard pass | Hit@K | mean MRR | mean latency ms |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for arm in ARMS:
        rows = by_arm.get(arm) or []
        hard = [r for r in rows if r.hard]
        passed = sum(1 for r in hard if r.passed)
        hit_rate = (
            sum(1 for r in rows if r.hit_at_k) / len(rows) if rows else 0.0
        )
        mrrs = [r.mrr for r in rows if r.mrr is not None]
        mean_mrr = sum(mrrs) / len(mrrs) if mrrs else 0.0
        mean_lat = sum(r.latency_ms for r in rows) / len(rows) if rows else 0.0
        lines.append(
            f"| `{arm}` | {passed}/{len(hard)} | {hit_rate:.2f} | "
            f"{mean_mrr:.3f} | {mean_lat:.1f} |"
        )

    lines.extend(["", "## Per fixture", ""])
    fixture_ids = list(dict.fromkeys(r.fixture_id for r in report.query_results))
    for fid in fixture_ids:
        lines.append(f"### `{fid}`")
        lines.append("")
        lines.append("| Arm | pass | rank | MRR | ms | top unit_keys |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for row in report.query_results:
            if row.fixture_id != fid:
                continue
            mark = "PASS" if row.passed else "FAIL"
            rank = row.first_rank if row.first_rank is not None else "—"
            mrr = f"{row.mrr:.3f}" if row.mrr is not None else "—"
            tops = ", ".join(row.top_keys[:3]) or "—"
            lines.append(
                f"| `{row.arm}` | {mark} | {rank} | {mrr} | "
                f"{row.latency_ms:.1f} | {tops} |"
            )
            if not row.passed:
                lines.append(f"| | _{row.detail}_ | | | | |")
        lines.append("")

    lines.extend(
        [
            "## Reading the result",
            "",
            "- Prefer higher hard pass / Hit@K / MRR at similar latency.",
            "- `source_text_windows` pays more **index** embed time/tokens; "
            "query latency stays comparable (one query embed + cosine).",
            "- `semantic_reps` adds a **paid curator LLM** step once per promote; "
            "extract arms skip that.",
            "- `source_text_truncate` shows the failure mode of embedding a long "
            "extract without windowing.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json(report: BakeoffReport, path: Path) -> None:
    payload = {
        "doc_id": report.doc_id,
        "k": report.k,
        "budget": report.budget,
        "embedding_model": report.embedding_model,
        "index_stats": [s.__dict__ for s in report.index_stats],
        "curator_estimate": report.curator_estimate,
        "query_results": [r.__dict__ for r in report.query_results],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "ARMS",
    "BakeoffReport",
    "run_bakeoff",
    "scorecard_markdown",
    "window_source_text",
    "write_json",
]
