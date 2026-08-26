"""Offline checks for the chain-smoke fixture (E6)."""

from __future__ import annotations

import yaml

from repair_assistant.corpus import manifest as manifest_mod
from repair_assistant.eval.chain_bench import load_chain_fixtures


def test_chain_fixture_docs_resolve_and_stages_are_complete():
    data = load_chain_fixtures()
    corpus = manifest_mod.load()
    docs = list(data.get("docs") or [])
    assert docs, "chain fixtures need at least one doc"

    for needle in docs:
        matches = [
            d for d in corpus.documents if d.doc_id == needle or d.publication_number == needle
        ]
        assert matches, f"chain doc {needle!r} missing from manifest"
        source = corpus.documents_dir / matches[0].local_filename
        assert source.is_file(), f"chain source missing on disk: {source}"

    retrieve = data.get("retrieve") or {}
    ask = data.get("ask") or {}
    assert retrieve.get("question") and (
        retrieve.get("must_cite") or retrieve.get("must_cite_any")
    )
    assert ask.get("question") and (
        ask.get("expect_cites_any") or ask.get("must_cite") or ask.get("expect_contains")
    )


def test_chain_fixture_file_lives_under_evals():
    root = manifest_mod.load().root
    path = root / "evals" / "chain" / "fixtures.yaml"
    assert path.is_file()
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert data["version"] == 1
