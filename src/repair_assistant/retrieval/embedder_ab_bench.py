"""Experiment: BGE-base (production) vs Jasper-Token-Compression-600M (not production).

Baseline reuses Postgres ``active_chunks`` vectors + ``vector_apply_boost``.
Jasper builds an in-memory / disk-cached index of the same chunk texts, then
runs the same code_fetch ∪ vector overfetch → ``filter_and_rank`` path.

Does not change ``EMBEDDING_MODEL`` or rewrite pgvector.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.ingest.env import database_url, embedding_model
from repair_assistant.ingest.store import Database
from repair_assistant.parsing.error_codes import extract_error_codes
from repair_assistant.retrieval.bench import (
    FixtureResult,
    compute_ir_metrics,
    grade_hits,
    load_fixtures,
)
from repair_assistant.retrieval.rank import filter_and_rank
from repair_assistant.retrieval.search import code_fetch, merge_hits
from repair_assistant.retrieval.strategies import (
    _appliance,
    _hits_from_ranked,
    default_embedder,
    run_strategy,
)
from repair_assistant.retrieval.synthetic import (
    ensure_synthetic_ingested,
    merge_manifest_with_synthetic,
)

JASPER_MODEL_ID = "infgrad/Jasper-Token-Compression-600M"
BGE_ARM = "bge_vector_apply_boost"
JASPER_ARM = "jasper_vector_apply_boost"
ARMS = (BGE_ARM, JASPER_ARM)


@dataclass
class IndexBuildStats:
    arm: str
    chunks: int
    dims: int
    embed_wall_ms: float
    cache_hit: bool
    model: str
    notes: str = ""


@dataclass
class BakeoffReport:
    k: int
    overfetch: int
    index_stats: list[IndexBuildStats]
    results: list[FixtureResult]
    jasper_model: str = JASPER_MODEL_ID
    bge_model: str = ""


def _cache_dir(root: Path) -> Path:
    # gitignored drafts/ — large float caches must not enter git
    path = root / "evals" / "retrieval" / "drafts" / "jasper_ab_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _corpus_fingerprint(rows: list[tuple[Any, ...]]) -> str:
    h = hashlib.sha256()
    for doc_id, chunk_id, text, *_rest in rows:
        h.update(str(doc_id).encode())
        h.update(b"\0")
        h.update(str(chunk_id).encode())
        h.update(b"\0")
        h.update((text or "").encode("utf-8", errors="replace"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def _load_chunk_rows(db: Database, *, include_synthetic: bool) -> list[tuple[Any, ...]]:
    synth = "" if include_synthetic else "AND doc_id NOT LIKE 'synth-%%'"
    return list(
        db.fetchall(
            f"""
            SELECT doc_id, chunk_id, text, page, kind, error_codes,
                   publication_number, revision
            FROM active_chunks
            WHERE embedding IS NOT NULL
            {synth}
            ORDER BY doc_id, chunk_id
            """
        )
    )


def _row_to_hit(row: tuple[Any, ...], score: float) -> dict[str, Any]:
    return {
        "doc_id": row[0],
        "chunk_id": row[1],
        "text": row[2],
        "page": row[3],
        "kind": row[4],
        "error_codes": list(row[5] or []),
        "publication_number": row[6],
        "revision": row[7],
        "score": float(score),
    }


def _load_jasper_model(*, device: str = "cpu"):
    import torch
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        JASPER_MODEL_ID,
        model_kwargs={
            "torch_dtype": torch.bfloat16 if device != "cpu" else torch.float32,
            "attn_implementation": "sdpa",
            "trust_remote_code": True,
        },
        trust_remote_code=True,
        tokenizer_kwargs={"padding_side": "left"},
        device=device,
    )


def build_jasper_index(
    rows: list[tuple[Any, ...]],
    *,
    root: Path,
    compression_ratio: float = 0.5,
    batch_size: int = 8,
    device: str = "cpu",
) -> tuple[np.ndarray, IndexBuildStats]:
    """Embed chunk texts with Jasper; resume from disk cache when fingerprint matches."""
    cache = _cache_dir(root)
    fp = _corpus_fingerprint(rows)
    meta_path = cache / f"jasper_{fp}.json"
    vec_path = cache / f"jasper_{fp}.npy"

    if meta_path.is_file() and vec_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        vectors = np.load(vec_path)
        if (
            int(meta.get("chunks", -1)) == len(rows)
            and int(meta.get("dims", -1)) == int(vectors.shape[1])
            and abs(float(meta.get("compression_ratio", -1)) - compression_ratio) < 1e-6
        ):
            return vectors, IndexBuildStats(
                arm=JASPER_ARM,
                chunks=len(rows),
                dims=int(vectors.shape[1]),
                embed_wall_ms=0.0,
                cache_hit=True,
                model=JASPER_MODEL_ID,
                notes=f"cache {vec_path.name}",
            )

    model = _load_jasper_model(device=device)
    texts = [str(r[2] or "") for r in rows]
    t0 = time.perf_counter()
    # Document side: no query prompt (HF card).
    encoded = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
        compression_ratio=compression_ratio,
    )
    wall_ms = (time.perf_counter() - t0) * 1000
    vectors = np.asarray(encoded, dtype=np.float32)
    np.save(vec_path, vectors)
    meta_path.write_text(
        json.dumps(
            {
                "model": JASPER_MODEL_ID,
                "chunks": len(rows),
                "dims": int(vectors.shape[1]),
                "compression_ratio": compression_ratio,
                "fingerprint": fp,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return vectors, IndexBuildStats(
        arm=JASPER_ARM,
        chunks=len(rows),
        dims=int(vectors.shape[1]),
        embed_wall_ms=wall_ms,
        cache_hit=False,
        model=JASPER_MODEL_ID,
        notes=f"wrote {vec_path.name}",
    )


def jasper_vector_fetch(
    query: str,
    rows: list[tuple[Any, ...]],
    matrix: np.ndarray,
    model: Any,
    *,
    limit: int,
    compression_ratio: float = 0.5,
) -> list[dict[str, Any]]:
    q = model.encode(
        [query],
        prompt_name="query",
        normalize_embeddings=True,
        convert_to_numpy=True,
        compression_ratio=compression_ratio,
    )[0]
    q = np.asarray(q, dtype=np.float32)
    scores = matrix @ q  # both L2-normalised → cosine
    if limit >= len(scores):
        order = np.argsort(-scores)
    else:
        # partial top-k
        idx = np.argpartition(-scores, limit)[:limit]
        order = idx[np.argsort(-scores[idx])]
    return [_row_to_hit(rows[i], float(scores[i])) for i in order]


def run_jasper_strategy(
    db: Database,
    manifest: Any,
    fixture: dict[str, Any],
    *,
    rows: list[tuple[Any, ...]],
    matrix: np.ndarray,
    model: Any,
    k: int,
    overfetch: int,
    compression_ratio: float,
) -> list[dict[str, Any]]:
    query = fixture["question"]
    appliance = _appliance(fixture.get("appliance"))
    codes = extract_error_codes(query)
    vector_hits = jasper_vector_fetch(
        query,
        rows,
        matrix,
        model,
        limit=max(overfetch, k),
        compression_ratio=compression_ratio,
    )
    raw = merge_hits(code_fetch(db, codes), vector_hits)
    ranked = filter_and_rank(
        raw, manifest, appliance, limit=k, query=query, query_error_codes=codes
    )
    return _hits_from_ranked(ranked)


def run_bakeoff(
    *,
    fixtures_path: Path | None = None,
    k: int | None = None,
    overfetch: int = 40,
    compression_ratio: float = 0.5,
    batch_size: int = 8,
    include_synthetic: bool = True,
    device: str = "cpu",
) -> BakeoffReport:
    data = load_fixtures(fixtures_path)
    corpus = merge_manifest_with_synthetic(manifest_mod.load())
    k = k or int(data.get("k") or 8)
    bge = default_embedder()
    results: list[FixtureResult] = []

    with Database(database_url()) as db:
        if include_synthetic:
            ensure_synthetic_ingested(db, bge, root=corpus.root)
        rows = _load_chunk_rows(db, include_synthetic=include_synthetic)
        if not rows:
            raise RuntimeError("no active_chunks with embeddings; ingest first")

        matrix, jasper_stats = build_jasper_index(
            rows,
            root=corpus.root,
            compression_ratio=compression_ratio,
            batch_size=batch_size,
            device=device,
        )
        jasper_model = _load_jasper_model(device=device)

        bge_stats = IndexBuildStats(
            arm=BGE_ARM,
            chunks=len(rows),
            dims=768,
            embed_wall_ms=0.0,
            cache_hit=True,
            model=embedding_model(),
            notes="Postgres active_chunks vectors (production)",
        )

        # --- BGE baseline (existing strategy) ---
        for fixture in data["fixtures"]:
            started = time.perf_counter()
            hits = run_strategy(
                "vector_apply_boost",
                db,
                corpus,
                fixture,
                k=k,
                overfetch=overfetch,
                embedder=bge,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            ok, detail, cited = grade_hits(fixture, hits)
            results.append(
                FixtureResult(
                    fixture_id=fixture["id"],
                    strategy=BGE_ARM,
                    passed=ok,
                    hard=bool(fixture.get("hard")),
                    detail=detail,
                    cited=cited,
                    metrics=compute_ir_metrics(fixture, hits, k=k),
                    latency_ms=latency_ms,
                )
            )

        # --- Jasper arm ---
        for fixture in data["fixtures"]:
            started = time.perf_counter()
            hits = run_jasper_strategy(
                db,
                corpus,
                fixture,
                rows=rows,
                matrix=matrix,
                model=jasper_model,
                k=k,
                overfetch=overfetch,
                compression_ratio=compression_ratio,
            )
            latency_ms = (time.perf_counter() - started) * 1000
            ok, detail, cited = grade_hits(fixture, hits)
            results.append(
                FixtureResult(
                    fixture_id=fixture["id"],
                    strategy=JASPER_ARM,
                    passed=ok,
                    hard=bool(fixture.get("hard")),
                    detail=detail,
                    cited=cited,
                    metrics=compute_ir_metrics(fixture, hits, k=k),
                    latency_ms=latency_ms,
                )
            )

    return BakeoffReport(
        k=k,
        overfetch=overfetch,
        index_stats=[bge_stats, jasper_stats],
        results=results,
        bge_model=embedding_model(),
    )


def scorecard_markdown(report: BakeoffReport) -> str:
    lines = [
        "# Embedder A/B: BGE-base vs Jasper-Token-Compression-600M",
        "",
        *scorecard_repro_lines(),
        "",
        f"K={report.k} · overfetch={report.overfetch} · "
        f"BGE=`{report.bge_model}` · Jasper=`{report.jasper_model}`",
        "",
        "Production `search()` / `EMBEDDING_MODEL` **unchanged**. "
        "Jasper index is experimental (in-memory + drafts cache).",
        "Insufficient evidence for a production change until hard-pass and "
        "IR metrics clearly beat the baseline.",
        "",
        "## Indexing cost (one-time)",
        "",
        "| Arm | chunks | dims | embed wall ms | cache | model | notes |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for s in report.index_stats:
        lines.append(
            f"| `{s.arm}` | {s.chunks} | {s.dims} | {s.embed_wall_ms:.0f} | "
            f"{'hit' if s.cache_hit else 'miss'} | `{s.model}` | {s.notes} |"
        )
    lines.extend(
        [
            "",
            "Local embed API cost is **$0** for both arms. Jasper is ~0.6B params "
            "(heavier CPU than BGE-base ~110M) and emits **2048-d** vectors.",
            "",
            "## Hard-fixture summary",
            "",
        ]
    )

    for arm in ARMS:
        hard = [r for r in report.results if r.strategy == arm and r.hard]
        passed = sum(1 for r in hard if r.passed)
        lines.append(f"- **`{arm}`**: {passed}/{len(hard)} hard fixtures passed")

    lines.extend(["", "## Aggregate IR + latency", "", "| Arm | Hit@K | mean MRR | mean nDCG@K | mean Prec@K | mean lat ms |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for arm in ARMS:
        rows = [r for r in report.results if r.strategy == arm]

        hits = [
            1.0 if r.metrics and r.metrics.hit_at_k else 0.0
            for r in rows
            if r.metrics and r.metrics.hit_at_k is not None
        ]
        hit_rate = sum(hits) / len(hits) if hits else 0.0
        mrrs = [
            float(r.metrics.mrr)
            for r in rows
            if r.metrics and r.metrics.mrr is not None
        ]
        ndcgs = [
            float(r.metrics.ndcg_at_k)
            for r in rows
            if r.metrics and r.metrics.ndcg_at_k is not None
        ]
        precs = [
            float(r.metrics.precision_at_k)
            for r in rows
            if r.metrics and r.metrics.precision_at_k is not None
        ]
        lats = [r.latency_ms for r in rows if r.latency_ms is not None]
        lines.append(
            f"| `{arm}` | {hit_rate:.2f} | "
            f"{(sum(mrrs)/len(mrrs) if mrrs else 0):.3f} | "
            f"{(sum(ndcgs)/len(ndcgs) if ndcgs else 0):.3f} | "
            f"{(sum(precs)/len(precs) if precs else 0):.3f} | "
            f"{(sum(lats)/len(lats) if lats else 0):.0f} |"
        )

    # Per-fixture pivot
    fixture_ids = list(dict.fromkeys(r.fixture_id for r in report.results))
    lines.extend(["", "## Per fixture (pass / rank signals)", ""])
    for fid in fixture_ids:
        hard = next(
            (r.hard for r in report.results if r.fixture_id == fid), False
        )
        lines.append(f"### `{fid}`" + (" (hard)" if hard else ""))
        lines.append("")
        lines.append("| Arm | pass | Hit@K | MRR | lat ms | detail |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for arm in ARMS:
            row = next(
                r for r in report.results if r.fixture_id == fid and r.strategy == arm
            )
            mark = "PASS" if row.passed else "FAIL"
            hit = (
                "yes"
                if row.metrics and row.metrics.hit_at_k
                else ("no" if row.metrics and row.metrics.hit_at_k is not None else "n/a")
            )
            mrr = (
                f"{row.metrics.mrr:.3f}"
                if row.metrics and row.metrics.mrr is not None
                else "n/a"
            )
            lat = f"{row.latency_ms:.0f}" if row.latency_ms is not None else "n/a"
            detail = row.detail if not row.passed else "ok"
            lines.append(
                f"| `{arm}` | {mark} | {hit} | {mrr} | {lat} | {detail} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Reading the result",
            "",
            "- Prefer equal-or-better hard pass **and** better MRR/nDCG before "
            "considering a cutover.",
            "- Jasper needs a full re-ingest + 2048-d pgvector migration to "
            "ship; this bake-off does not do that.",
            "- Query latency includes Jasper encode on CPU; BGE uses the warm "
            "local model + Postgres HNSW.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json(report: BakeoffReport, path: Path) -> None:
    payload = {
        "k": report.k,
        "overfetch": report.overfetch,
        "bge_model": report.bge_model,
        "jasper_model": report.jasper_model,
        "index_stats": [s.__dict__ for s in report.index_stats],
        "results": [
            {
                "fixture_id": r.fixture_id,
                "strategy": r.strategy,
                "passed": r.passed,
                "hard": r.hard,
                "detail": r.detail,
                "cited": r.cited,
                "latency_ms": r.latency_ms,
                "metrics": None
                if r.metrics is None
                else {
                    "hit_at_k": r.metrics.hit_at_k,
                    "mrr": r.metrics.mrr,
                    "ndcg_at_k": r.metrics.ndcg_at_k,
                    "precision_at_k": r.metrics.precision_at_k,
                    "recall_at_k": r.metrics.recall_at_k,
                },
            }
            for r in report.results
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "ARMS",
    "BakeoffReport",
    "JASPER_MODEL_ID",
    "run_bakeoff",
    "scorecard_markdown",
    "write_json",
]
