"""Thin parse → ingest → retrieve → ask chain smoke (manual, E6)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.corpus.applicability import Appliance
from repair_assistant.eval.grading import grade_answer
from repair_assistant.eval.qa_bench import _cite_keys
from repair_assistant.ingest.embeddings import build_embedder
from repair_assistant.ingest.env import embedding_model
from repair_assistant.ingest.pipeline import ingest_parsed
from repair_assistant.ingest.store import Database, apply_migrations
from repair_assistant.parsing import write as parse_write
from repair_assistant.qa.generate import ask
from repair_assistant.retrieval.bench import grade_hits
from repair_assistant.retrieval.search import search


@dataclass
class ChainStageResult:
    stage: str
    passed: bool
    detail: str = ""
    duration_ms: int = 0
    citations: list[str] = field(default_factory=list)


def load_chain_fixtures(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "chain" / "fixtures.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _appliance(spec: dict[str, Any] | None) -> Appliance | None:
    if not spec or not spec.get("model"):
        return None
    return Appliance(
        model=spec["model"],
        serial=spec.get("serial"),
        model_introduced=spec.get("model_introduced"),
    )


def _resolve_docs(corpus: manifest_mod.Manifest, doc_ids: list[str]) -> list[manifest_mod.Document]:
    resolved: list[manifest_mod.Document] = []
    for needle in doc_ids:
        matches = [
            d for d in corpus.documents if d.doc_id == needle or d.publication_number == needle
        ]
        if not matches:
            raise KeyError(f"chain fixture doc not in manifest: {needle!r}")
        resolved.append(matches[0])
    return resolved


def run_chain_bench(
    db: Database,
    *,
    fixtures_path: Path | None = None,
    extractor: str = "pdfplumber",
    skip_ask: bool = False,
) -> list[ChainStageResult]:
    """Re-parse/ingest listed docs, then grade production search() and ask()."""
    data = load_chain_fixtures(fixtures_path)
    corpus = manifest_mod.load()
    docs = _resolve_docs(corpus, list(data.get("docs") or []))
    results: list[ChainStageResult] = []

    # --- parse ---
    start = time.perf_counter()
    try:
        for document in docs:
            source = corpus.documents_dir / document.local_filename
            if not source.is_file():
                raise FileNotFoundError(f"missing source PDF/HTML: {source}")
            parse_write.parse_document(document, extractor_name=extractor)
        results.append(
            ChainStageResult(
                stage="parse",
                passed=True,
                detail=f"ok ({', '.join(d.doc_id for d in docs)})",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
    except Exception as exc:
        results.append(
            ChainStageResult(
                stage="parse",
                passed=False,
                detail=str(exc),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
        return results

    # --- ingest ---
    start = time.perf_counter()
    try:
        apply_migrations(db)
        embedder = build_embedder(skip=False, model=embedding_model())
        sha_by_doc = {
            d.doc_id: sorted(d.known_hashes)[0]
            for d in corpus.documents
            if d.known_hashes
        }
        ingest = ingest_parsed(
            db,
            corpus.root / "corpus",
            embedder,
            doc_ids={d.doc_id for d in docs},
            force=True,
            corpus_sha_by_doc=sha_by_doc,
        )
        if ingest.failed:
            failed = [s for s in ingest.documents if s.status == "failed"]
            detail = "; ".join(f"{s.doc_id}: {s.detail}" for s in failed) or "ingest failed"
            results.append(
                ChainStageResult(
                    stage="ingest",
                    passed=False,
                    detail=detail,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
            )
            return results
        results.append(
            ChainStageResult(
                stage="ingest",
                passed=True,
                detail=f"upserted={ingest.upserted} skipped={ingest.skipped}",
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
    except Exception as exc:
        results.append(
            ChainStageResult(
                stage="ingest",
                passed=False,
                detail=str(exc),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
        return results

    # --- retrieve (production search) ---
    retrieve = data.get("retrieve") or {}
    start = time.perf_counter()
    try:
        outcome = search(
            db,
            corpus,
            retrieve["question"],
            appliance=_appliance(retrieve.get("appliance")),
        )
        hits = [
            {
                "doc_id": h.doc_id,
                "chunk_id": h.chunk_id,
                "text": h.text,
                "page": h.page,
                "kind": h.kind,
                "error_codes": list(h.error_codes or []),
                "publication_number": h.publication_number,
                "revision": h.revision,
                "score": float(h.score),
            }
            for h in outcome.hits
        ]
        passed, detail, cited = grade_hits(retrieve, hits)
        results.append(
            ChainStageResult(
                stage="retrieve",
                passed=passed,
                detail=detail,
                duration_ms=int((time.perf_counter() - start) * 1000),
                citations=cited,
            )
        )
        if not passed:
            return results
    except Exception as exc:
        results.append(
            ChainStageResult(
                stage="retrieve",
                passed=False,
                detail=str(exc),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
        return results

    # --- ask ---
    if skip_ask:
        results.append(
            ChainStageResult(
                stage="ask",
                passed=True,
                detail="skipped (--skip-ask)",
                duration_ms=0,
            )
        )
        return results

    ask_spec = data.get("ask") or {}
    start = time.perf_counter()
    try:
        answer = ask(
            db,
            corpus,
            ask_spec["question"],
            appliance=_appliance(ask_spec.get("appliance")),
        )
        cite_keys = _cite_keys(answer.citations)
        passed, detail = grade_answer(
            ask_spec,
            answer=answer.answer,
            citations=cite_keys,
            abstained=answer.abstained,
            claims=list(answer.claims or []),
            evidence_blocks=dict(answer.evidence_blocks or {}),
        )
        results.append(
            ChainStageResult(
                stage="ask",
                passed=passed,
                detail=detail,
                duration_ms=int((time.perf_counter() - start) * 1000),
                citations=cite_keys,
            )
        )
    except Exception as exc:
        results.append(
            ChainStageResult(
                stage="ask",
                passed=False,
                detail=str(exc),
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
        )
    return results


def scorecard_markdown(results: list[ChainStageResult]) -> str:
    passed = sum(1 for r in results if r.passed)
    from repair_assistant.eval.repro import scorecard_repro_lines

    lines = [
        "# Chain smoke bench",
        "",
        *scorecard_repro_lines(),
        "",
        f"**{passed}/{len(results)} stages passed**",
        "",
        "| stage | pass | ms | detail |",
        "| --- | --- | ---: | --- |",
    ]
    for r in results:
        mark = "yes" if r.passed else "NO"
        detail = r.detail.replace("|", "\\|")
        lines.append(f"| {r.stage} | {mark} | {r.duration_ms} | {detail} |")
    lines.append("")
    return "\n".join(lines)
