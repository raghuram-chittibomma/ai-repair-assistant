"""Score retrieval strategies against evals/retrieval/fixtures.yaml."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.grading import matches_citation
from repair_assistant.eval.repro import scorecard_repro_lines
from repair_assistant.ingest.env import database_url
from repair_assistant.ingest.store import Database
from repair_assistant.retrieval.rerank import rerank_model_name
from repair_assistant.retrieval.strategies import default_embedder, run_strategy
from repair_assistant.retrieval.synthetic import (
    ensure_synthetic_ingested,
    merge_manifest_with_synthetic,
)


@dataclass
class IRMetrics:
    """Diagnostic IR metrics for one fixture × strategy (top-K).

    Labels come from fixture ``must_cite`` / ``must_cite_any`` (relevant) and
    ``must_not_cite`` (forbidden). Pass/fail remains the release gate; these
    numbers diagnose recall misses, rank, and noise.
    """

    k: int
    hit_at_k: bool | None
    recall_at_k: float | None
    precision_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None
    first_relevant_rank: int | None
    relevant_found: int
    relevant_total: int
    forbidden_in_top_k: int
    unique_retrieved: int


@dataclass
class FixtureResult:
    fixture_id: str
    strategy: str
    passed: bool
    hard: bool
    detail: str = ""
    cited: list[str] = field(default_factory=list)
    metrics: IRMetrics | None = None
    latency_ms: float | None = None


def load_fixtures(path: Path | None = None) -> dict[str, Any]:
    root = manifest_mod.load().root
    path = path or (root / "evals" / "retrieval" / "fixtures.yaml")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _cite_keys(hit: dict) -> set[str]:
    keys = {hit["doc_id"]}
    pub = hit.get("publication_number")
    if pub:
        keys.add(str(pub))
    rev = hit.get("revision")
    if pub and rev:
        keys.add(f"{pub} Rev {str(rev).strip().upper()}")
    return keys


def _matches_label(cited: list[str] | set[str], label: str) -> bool:
    return matches_citation(list(cited), label)


def relevant_labels(fixture: dict) -> set[str]:
    """Explicit ``relevant`` list, else must_cite ∪ must_cite_any."""
    if fixture.get("relevant"):
        return {str(x) for x in fixture["relevant"]}
    labels = {str(x) for x in (fixture.get("must_cite") or [])}
    labels |= {str(x) for x in (fixture.get("must_cite_any") or [])}
    return labels


def forbidden_labels(fixture: dict) -> set[str]:
    return {str(x) for x in (fixture.get("must_not_cite") or [])}


def _target_ranks(fixture: dict, hits: list[dict], *, k: int) -> list[int | None]:
    """1-based rank of each recall target, or None if missing from top-K.

    Each ``must_cite`` label is one target. ``must_cite_any`` is one target
    (best rank among the group). An explicit ``relevant`` list is one target
    per label when the must_* fields are absent.
    """
    top = hits[:k]
    ranks: list[int | None] = []
    must_cite = [str(x) for x in (fixture.get("must_cite") or [])]
    must_any = [str(x) for x in (fixture.get("must_cite_any") or [])]
    for label in must_cite:
        ranks.append(
            next(
                (
                    i
                    for i, row in enumerate(top, start=1)
                    if _matches_label(_cite_keys(row), label)
                ),
                None,
            )
        )
    if must_any:
        ranks.append(
            next(
                (
                    i
                    for i, row in enumerate(top, start=1)
                    if any(_matches_label(_cite_keys(row), label) for label in must_any)
                ),
                None,
            )
        )
    elif not must_cite:
        for label in relevant_labels(fixture):
            ranks.append(
                next(
                    (
                        i
                        for i, row in enumerate(top, start=1)
                        if _matches_label(_cite_keys(row), label)
                    ),
                    None,
                )
            )
    return ranks


def _mrr(ranks: list[int | None]) -> float | None:
    if not ranks:
        return None
    found = [rank for rank in ranks if rank is not None]
    if not found:
        return 0.0
    return 1.0 / min(found)


def _ndcg(ranks: list[int | None], *, k: int) -> float | None:
    if not ranks:
        return None
    found = [rank for rank in ranks if rank is not None]
    dcg = sum(1.0 / math.log2(rank + 1) for rank in found)
    ideal_n = min(len(ranks), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    if idcg == 0:
        return None
    return dcg / idcg


def compute_ir_metrics(fixture: dict, hits: list[dict], *, k: int) -> IRMetrics:
    """Recall@K / Precision@K / Hit@K over fixture-derived labels."""
    top = hits[:k]
    cited: list[str] = []
    seen: set[str] = set()
    for hit in top:
        for key in _cite_keys(hit):
            if key not in seen:
                seen.add(key)
                cited.append(key)

    relevant = relevant_labels(fixture)
    forbidden = forbidden_labels(fixture)
    must_cite = [str(x) for x in (fixture.get("must_cite") or [])]
    must_any = [str(x) for x in (fixture.get("must_cite_any") or [])]

    # Targets: each must_cite label + one group for must_cite_any.
    # If only an explicit ``relevant`` list exists, each label is a target.
    targets_hit = 0
    targets_total = 0
    hit: bool | None

    if must_cite or must_any:
        targets_total = len(must_cite) + (1 if must_any else 0)
        found_required = sum(1 for label in must_cite if _matches_label(cited, label))
        any_ok = (not must_any) or any(_matches_label(cited, label) for label in must_any)
        targets_hit = found_required + (1 if must_any and any_ok else 0)
        hit = (found_required == len(must_cite)) and any_ok
    elif relevant:
        targets_total = len(relevant)
        targets_hit = sum(1 for label in relevant if _matches_label(cited, label))
        hit = targets_hit == targets_total
    else:
        hit = None

    recall = (targets_hit / targets_total) if targets_total else None

    # Precision@K: fraction of unique retrieved docs that match a relevant label.
    seen_docs: list[dict] = []
    seen_ids: set[str] = set()
    for hit_row in top:
        doc_id = hit_row["doc_id"]
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        seen_docs.append(hit_row)

    if seen_docs and relevant:
        relevant_docs = sum(
            1
            for row in seen_docs
            if any(_matches_label(_cite_keys(row), label) for label in relevant)
        )
        precision = relevant_docs / len(seen_docs)
    else:
        precision = None

    forbidden_count = sum(1 for label in forbidden if _matches_label(cited, label))

    ranks = _target_ranks(fixture, hits, k=k)
    found_ranks = [rank for rank in ranks if rank is not None]

    return IRMetrics(
        k=k,
        hit_at_k=hit,
        recall_at_k=recall,
        precision_at_k=precision,
        mrr=_mrr(ranks),
        ndcg_at_k=_ndcg(ranks, k=k),
        first_relevant_rank=min(found_ranks) if found_ranks else None,
        relevant_found=targets_hit,
        relevant_total=targets_total,
        forbidden_in_top_k=forbidden_count,
        unique_retrieved=len(seen_docs),
    )


def grade_hits(fixture: dict, hits: list[dict]) -> tuple[bool, str, list[str]]:
    cited: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        for key in _cite_keys(hit):
            if key not in seen:
                seen.add(key)
                cited.append(key)

    for forbidden in fixture.get("must_not_cite") or []:
        if matches_citation(cited, str(forbidden)):
            return False, f"must_not_cite hit {forbidden!r} in {cited}", cited

    for required in fixture.get("must_cite") or []:
        if not matches_citation(cited, str(required)):
            return False, f"must_cite missing {required!r}; got {cited}", cited

    any_of = fixture.get("must_cite_any") or []
    if any_of and not any(matches_citation(cited, str(req)) for req in any_of):
        return False, f"must_cite_any missing one of {any_of}; got {cited}", cited

    return True, "ok", cited


def run_bakeoff(
    *,
    strategies: list[str] | None = None,
    fixtures_path: Path | None = None,
    k: int | None = None,
    overfetch: int = 40,
) -> list[FixtureResult]:
    data = load_fixtures(fixtures_path)
    corpus = merge_manifest_with_synthetic(manifest_mod.load())
    k = k or int(data.get("k") or 8)
    strategy_ids = strategies or [s["id"] for s in data["strategies"]]
    embedder = default_embedder()
    results: list[FixtureResult] = []

    with Database(database_url()) as db:
        ensure_synthetic_ingested(db, embedder, root=corpus.root)
        for sid in strategy_ids:
            for fixture in data["fixtures"]:
                started = time.perf_counter()
                hits = run_strategy(
                    sid,
                    db,
                    corpus,
                    fixture,
                    k=k,
                    overfetch=overfetch,
                    embedder=embedder,
                )
                latency_ms = (time.perf_counter() - started) * 1000
                ok, detail, cited = grade_hits(fixture, hits)
                metrics = compute_ir_metrics(fixture, hits, k=k)
                results.append(
                    FixtureResult(
                        fixture_id=fixture["id"],
                        strategy=sid,
                        passed=ok,
                        hard=bool(fixture.get("hard")),
                        detail=detail,
                        cited=cited,
                        metrics=metrics,
                        latency_ms=latency_ms,
                    )
                )
    return results


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _fmt_hit(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "yes" if value else "no"


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}"


def scorecard_markdown(results: list[FixtureResult]) -> str:
    strategies = sorted({r.strategy for r in results})
    fixtures = []
    for r in results:
        if r.fixture_id not in fixtures:
            fixtures.append(r.fixture_id)

    lines = [
        "# Retrieval bake-off scorecard",
        "",
        *scorecard_repro_lines(),
        f"- REPAIR_RERANK_MODEL: `{rerank_model_name()}` (bake-off only)",
        "",
        "Generated by `repair-corpus bench-retrieve`. Charter deviation D4.",
        "",
        "Pass/fail is the release gate. IR metrics (Hit@K, Recall@K, Precision@K,",
        "MRR, nDCG@K) are diagnostic - derived from fixture `must_cite` /",
        "`must_cite_any` / `must_not_cite` (optional explicit `relevant`).",
        "Latency is wall time of `run_strategy` only.",
        "",
        "| Fixture | Hard | " + " | ".join(strategies) + " |",
        "| --- | --- | " + " | ".join(["---"] * len(strategies)) + " |",
    ]
    for fid in fixtures:
        hard = next(r.hard for r in results if r.fixture_id == fid)
        cells = []
        for sid in strategies:
            match = next(r for r in results if r.fixture_id == fid and r.strategy == sid)
            cells.append("PASS" if match.passed else "FAIL")
        lines.append(f"| `{fid}` | {'yes' if hard else 'no'} | " + " | ".join(cells) + " |")

    lines.extend(["", "## Hard-fixture summary", ""])
    for sid in strategies:
        hard = [r for r in results if r.strategy == sid and r.hard]
        passed = sum(1 for r in hard if r.passed)
        lines.append(f"- **{sid}**: {passed}/{len(hard)} hard fixtures passed")

    lines.extend(
        [
            "",
            "## IR metrics (diagnostic)",
            "",
            "| Strategy | Fixture | Hit@K | Recall@K | Precision@K | MRR | nDCG@K | Forbidden@K |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for sid in strategies:
        for fid in fixtures:
            match = next(r for r in results if r.fixture_id == fid and r.strategy == sid)
            m = match.metrics
            if m is None:
                lines.append(f"| `{sid}` | `{fid}` | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            lines.append(
                f"| `{sid}` | `{fid}` | {_fmt_hit(m.hit_at_k)} | "
                f"{_fmt_pct(m.recall_at_k)} | {_fmt_pct(m.precision_at_k)} | "
                f"{_fmt_pct(m.mrr)} | {_fmt_pct(m.ndcg_at_k)} | "
                f"{m.forbidden_in_top_k} |"
            )

    lines.extend(["", "### Strategy means (fixtures with labeled relevant docs)", ""])
    for sid in strategies:
        with_recall = [
            r.metrics.recall_at_k
            for r in results
            if r.strategy == sid and r.metrics and r.metrics.recall_at_k is not None
        ]
        with_prec = [
            r.metrics.precision_at_k
            for r in results
            if r.strategy == sid and r.metrics and r.metrics.precision_at_k is not None
        ]
        mean_r = sum(with_recall) / len(with_recall) if with_recall else None
        mean_p = sum(with_prec) / len(with_prec) if with_prec else None
        with_mrr = [
            r.metrics.mrr
            for r in results
            if r.strategy == sid and r.metrics and r.metrics.mrr is not None
        ]
        with_ndcg = [
            r.metrics.ndcg_at_k
            for r in results
            if r.strategy == sid and r.metrics and r.metrics.ndcg_at_k is not None
        ]
        mean_mrr = sum(with_mrr) / len(with_mrr) if with_mrr else None
        mean_ndcg = sum(with_ndcg) / len(with_ndcg) if with_ndcg else None
        hits = [
            r
            for r in results
            if r.strategy == sid and r.metrics and r.metrics.hit_at_k is not None
        ]
        hit_rate = (
            sum(1 for r in hits if r.metrics and r.metrics.hit_at_k) / len(hits)
            if hits
            else None
        )
        lines.append(
            f"- **{sid}**: Hit@K {_fmt_pct(hit_rate)}, "
            f"mean Recall@K {_fmt_pct(mean_r)}, "
            f"mean Precision@K {_fmt_pct(mean_p)}, "
            f"mean MRR {_fmt_pct(mean_mrr)}, "
            f"mean nDCG@K {_fmt_pct(mean_ndcg)} "
            f"(n={len(with_recall)} labeled)"
        )

    lines.extend(["", "## Latency (run_strategy, ms)", ""])
    for sid in strategies:
        samples = sorted(
            r.latency_ms
            for r in results
            if r.strategy == sid and r.latency_ms is not None
        )
        if not samples:
            lines.append(f"- **{sid}**: n/a")
            continue
        mean = sum(samples) / len(samples)
        p50 = samples[len(samples) // 2]
        p95 = samples[max(0, math.ceil(0.95 * len(samples)) - 1)]
        lines.append(
            f"- **{sid}**: mean {_fmt_ms(mean)}, p50 {_fmt_ms(p50)}, "
            f"p95 {_fmt_ms(p95)} (n={len(samples)})"
        )

    lines.extend(["", "## Failures", ""])
    fails = [r for r in results if not r.passed]
    if not fails:
        lines.append("_None._")
    else:
        for r in fails:
            lines.append(f"- `{r.strategy}` / `{r.fixture_id}`: {r.detail}")
    lines.append("")
    return "\n".join(lines)
