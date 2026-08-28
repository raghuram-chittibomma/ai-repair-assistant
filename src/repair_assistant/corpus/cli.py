"""``repair-corpus`` -- inspect and verify the local manufacturer corpus.

There is deliberately no ``fetch`` or ``download`` command. Whirlpool's Terms of
Use prohibit automated retrieval from their sites, so documents are acquired by
the user through their own browser and this tool's job is to say precisely what
is missing and confirm that what is present is what the manifest describes.

The pattern is borrowed from Nixpkgs ``requireFile`` and MAME's software lists:
declare by identifier and hash, refuse to fetch, explain how to obtain.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import identity, pinning
from . import manifest as manifest_mod
from .applicability import Appliance, document_applies

# --- presentation -----------------------------------------------------------

_COLOURS = {
    "ok": "green",
    "missing": "yellow",
    "mismatch": "red",
    "unpinned": "cyan",
    "drift": "magenta",
    "skipped": "bright_black",
    "failed": "red",
}


def _echo_status(status: str, label: str, detail: str = "") -> None:
    tag = click.style(f"{status:<9}", fg=_COLOURS.get(status, "white"), bold=True)
    click.echo(f"{tag} {label}{'  ' + detail if detail else ''}")


def _load() -> manifest_mod.Manifest:
    try:
        return manifest_mod.load()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


def _document_state(doc: manifest_mod.Document, documents_dir: Path) -> tuple[str, Path | None]:
    """One of ok / drift / mismatch / unpinned / missing, plus the local path.

    ``drift`` is reserved for documents whose bytes are not reproducible across
    acquisitions (see ``identity.content_volatile``). Calling that a mismatch
    would report corruption that did not happen.
    """
    path = documents_dir / doc.local_filename
    if not path.is_file():
        return "missing", None
    if not doc.known_hashes:
        return "unpinned", path
    if identity.sha256_file(path) in doc.known_hashes:
        return "ok", path
    return ("drift" if doc.content_volatile else "mismatch"), path


# --- commands ---------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="ai-repair-assistant")
def main() -> None:
    """Inspect and verify the local manufacturer document corpus."""


@main.command()
def status() -> None:
    """Show which documents are present and which still need acquiring."""
    corpus = _load()
    documents_dir = corpus.documents_dir

    counts = dict.fromkeys(("ok", "missing", "mismatch", "unpinned", "drift"), 0)
    missing: list[manifest_mod.Document] = []

    for doc in sorted(corpus.documents, key=lambda d: (d.doc_type, d.doc_id)):
        state, _ = _document_state(doc, documents_dir)
        counts[state] += 1
        label = f"{doc.doc_type:<28} {doc.citation:<16} {doc.title}"
        _echo_status(state, label)
        if state == "missing":
            missing.append(doc)

    click.echo()
    click.echo(
        f"{counts['ok']} verified, {counts['unpinned']} present but not yet pinned, "
        f"{counts['drift']} drifted, {counts['mismatch']} mismatched, "
        f"{counts['missing']} missing of {len(corpus.documents)} documents."
    )

    if missing:
        click.echo()
        click.secho("How to obtain the missing documents", bold=True)
        click.echo(
            "This tool does not download them. See docs/corpus/ACQUISITION.md "
            "and docs/CORPUS_LICENSING.md.\n"
        )
        for doc in missing:
            click.secho(f"  {doc.citation} - {doc.title}", bold=True)
            click.echo(f"      method:  {doc.provenance.get('access_method', 'unknown')}")
            url = doc.provenance.get("source_url")
            url_status = doc.provenance.get("url_status")
            if url:
                suffix = f"  [{url_status}]" if url_status else ""
                click.echo(f"      url:     {url}{suffix}")
            else:
                click.echo("      url:     search by model number - see ACQUISITION.md")
            click.echo(f"      save as: corpus/documents/{doc.local_filename}")
            expected = doc.known_hashes
            click.echo(
                f"      sha256:  {next(iter(expected))}" if expected
                else "      sha256:  not yet pinned; run 'repair-corpus pin' after acquiring"
            )
            if notes := doc.provenance.get("access_notes"):
                click.echo(f"      note:    {' '.join(notes.split())}")
            click.echo()

    if corpus.excluded:
        click.secho(
            f"{len(corpus.excluded)} document(s) are known to exist but are not obtainable; "
            "see corpus/manifest/_excluded.yaml",
            fg="bright_black",
        )


@main.command()
@click.option("--strict", is_flag=True, help="Treat unpinned and missing documents as failures.")
def verify(strict: bool) -> None:
    """Hash local documents and check them against the manifest."""
    corpus = _load()
    documents_dir = corpus.documents_dir
    failures = 0
    present = 0

    for doc in sorted(corpus.documents, key=lambda d: d.doc_id):
        state, path = _document_state(doc, documents_dir)
        present += state != "missing"

        if state == "ok":
            _echo_status("ok", doc.citation)
        elif state == "missing":
            _echo_status("missing", doc.citation, f"expected corpus/documents/{doc.local_filename}")
            failures += strict
        elif state == "unpinned":
            facts = identity.inspect(path)
            _echo_status(
                "unpinned", doc.citation,
                f"sha256={facts.sha256[:16]}... pages={facts.page_count} "
                f"({facts.bytes:,} bytes)",
            )
            failures += strict
        elif state == "drift":
            _echo_status("drift", doc.citation, "bytes differ from every pinned instance")
            click.echo(
                "          expected: this document is marked content_volatile, so a "
                "byte change does not imply the content changed."
            )
        else:
            actual = identity.sha256_file(path)
            _echo_status("mismatch", doc.citation, f"got {actual[:16]}...")
            click.echo(
                "          this file is not any instance the manifest knows about. "
                "It may be a different edition, a different source, or corrupted."
            )
            failures += 1

    # Files sitting in corpus/documents that nothing in the manifest expects.
    # A stray is usually a typo in a filename, which would otherwise look
    # identical to the document simply not having been acquired.
    if documents_dir.is_dir():
        expected = {d.local_filename for d in corpus.documents} | {"README.md"}
        for stray in sorted(documents_dir.iterdir()):
            if stray.is_file() and stray.name not in expected and not stray.name.startswith("."):
                _echo_status(
                    "mismatch", stray.name, "present locally but not described by the manifest"
                )

    click.echo()
    if failures:
        click.secho(f"{failures} problem(s) found.", fg="red", bold=True)
        sys.exit(1)
    if not present:
        # Vacuously consistent is not the same as verified, and saying
        # "consistent" here would read as reassurance nobody has earned.
        click.secho(
            "No documents acquired yet, so there was nothing to verify. "
            "Run 'repair-corpus status' to see how to obtain them.",
            fg="yellow",
        )
        return
    click.secho(
        f"{present} of {len(corpus.documents)} documents present and consistent "
        "with the manifest.",
        fg="green", bold=True,
    )


@main.command()
def validate() -> None:
    """Validate the manifest itself. Used by CI."""
    corpus = _load()
    problems = manifest_mod.validate(corpus)

    for problem in problems:
        click.secho(f"  {problem}", fg="red")

    if problems:
        click.secho(f"\n{len(problems)} manifest problem(s).", fg="red", bold=True)
        sys.exit(1)

    click.secho(
        f"Manifest valid: {len(corpus.documents)} documents, "
        f"{len(corpus.excluded)} recorded as unobtainable.",
        fg="green", bold=True,
    )


@main.command()
@click.argument("needle")
def show(needle: str) -> None:
    """Show full metadata for a document, by publication number, id, or title."""
    corpus = _load()
    matches = corpus.find(needle)
    if not matches:
        raise click.ClickException(f"nothing in the manifest matches {needle!r}")

    for doc in matches:
        click.secho(f"\n{doc.citation}  {doc.title}", bold=True)
        click.echo(yaml_dump(doc.data))


@main.command()
@click.option("--model", required=True, help="Appliance model, e.g. WFW5620HW0")
@click.option("--serial", default=None, help="Serial number, e.g. CF81512345")
@click.option("--introduced", type=int, default=None,
              help="Year the model line was introduced; disambiguates the serial year code.")
def applies(model: str, serial: str | None, introduced: int | None) -> None:
    """Show which documents apply to a specific appliance, and why not for the rest.

    This is the corpus's core claim made checkable: relevance and applicability
    are different things.
    """
    corpus = _load()
    appliance = Appliance(model=model, serial=serial, model_introduced=introduced)

    applicable, inapplicable = [], []
    for doc in corpus.documents:
        result = document_applies(doc.data, appliance)
        (applicable if result.applies else inapplicable).append((doc, result))

    click.secho(f"\nApplies to {model}" + (f" / {serial}" if serial else ""), bold=True)
    for doc, result in sorted(applicable, key=lambda x: x[0].doc_type):
        click.secho(f"  {doc.citation:<16} {doc.title}", fg="green")
        click.secho(f"  {'':<16} {result.reason}", fg="bright_black")

    click.secho("\nDoes not apply", bold=True)
    for doc, result in sorted(inapplicable, key=lambda x: x[0].doc_type):
        click.secho(f"  {doc.citation:<16} {doc.title}", fg="yellow")
        click.secho(f"  {'':<16} {result.reason}", fg="bright_black")
    click.echo()


@main.command()
@click.option("--format", "fmt", type=click.Choice(["croissant", "json"]), default="croissant")
def export(fmt: str) -> None:
    """Export the manifest for interoperability. Emits metadata only, never content."""
    from .export import to_croissant

    corpus = _load()
    payload = to_croissant(corpus) if fmt == "croissant" else [d.data for d in corpus.documents]
    click.echo(json.dumps(payload, indent=2))


@main.command()
@click.argument("source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--apply/--dry-run", default=False,
              help="Actually move the files. Defaults to a dry run.")
@click.option("--copy", is_flag=True, help="Copy instead of moving, leaving the source intact.")
def intake(source: Path, apply: bool, copy: bool) -> None:
    """Identify downloaded documents in SOURCE and file them into the corpus.

    Works out which manifest entry each download is, from its filename and the
    publication number printed in it, then renames it to the expected name.
    Nothing is downloaded: this only sorts what you already have.
    """
    from . import intake as intake_mod

    corpus = _load()
    matches = intake_mod.plan(corpus, source)

    if not matches:
        raise click.ClickException(f"no PDF or HTML files found in {source}")

    documents_dir = corpus.documents_dir
    filed, skipped, blocked = 0, 0, 0
    claimed: dict[str, Path] = {}

    for match in matches:
        name = match.candidate.path.name

        if match.document is None:
            _echo_status("mismatch", name, match.reason)
            blocked += 1
            continue

        target = documents_dir / match.target_name

        if match.target_name in claimed:
            _echo_status(
                "mismatch", name,
                f"would overwrite {match.target_name}, already claimed by "
                f"{claimed[match.target_name].name}",
            )
            blocked += 1
            continue

        if match.revision_conflict:
            # Filing under the wrong revision silently corrupts logical identity,
            # which is the one thing the manifest exists to get right.
            _echo_status("mismatch", name, match.revision_conflict)
            click.echo(f"          would have filed as {match.target_name}; not filing")
            blocked += 1
            continue

        if target.exists() and identity.sha256_file(target) == identity.sha256_file(
            match.candidate.path
        ):
            _echo_status("ok", name, f"already filed as {match.target_name}")
            skipped += 1
            continue

        claimed[match.target_name] = match.candidate.path
        verb = "copy" if copy else "move"
        _echo_status("ok", name, f"{verb} -> corpus/documents/{match.target_name}")
        click.secho(f"          {match.reason}", fg="bright_black")

        if apply:
            import shutil

            documents_dir.mkdir(parents=True, exist_ok=True)
            if copy:
                shutil.copy2(match.candidate.path, target)
            else:
                shutil.move(str(match.candidate.path), str(target))
        filed += 1

    click.echo()
    if apply:
        click.secho(f"Filed {filed}, skipped {skipped}, blocked {blocked}.", bold=True)
        click.echo("Next: repair-corpus verify, then repair-corpus pin --write")
    else:
        click.secho(
            f"Dry run: {filed} would be filed, {skipped} already present, {blocked} blocked.",
            bold=True,
        )
        click.echo("Re-run with --apply to move them.")

    if blocked:
        click.secho(
            "\nBlocked files need a decision before filing. A revision mismatch usually "
            "means the manifest needs updating, not that the download is wrong.",
            fg="yellow",
        )


@main.command()
@click.option("--write/--dry-run", default=False,
              help="Write the computed hashes back into the manifest.")
def pin(write: bool) -> None:
    """Record hashes for documents that are present but not yet pinned.

    Trust-on-first-use: the values are computed from whatever you acquired, so
    review the resulting diff before committing it.
    """
    corpus = _load()
    documents_dir = corpus.documents_dir
    pinned = 0

    for doc in sorted(corpus.documents, key=lambda d: d.doc_id):
        state, path = _document_state(doc, documents_dir)
        if state != "unpinned":
            continue

        facts = identity.inspect(path)
        instance = {
            "sha256": facts.sha256,
            "bytes": facts.bytes,
            "acquired_from": doc.provenance.get("access_method", "user_supplied"),
        }
        if facts.page_count:
            instance["page_count"] = facts.page_count
        if facts.pdf_producer:
            instance["pdf_producer"] = facts.pdf_producer

        click.secho(f"{doc.citation}", bold=True)
        click.echo(f"  sha256 {facts.sha256}")
        click.echo(f"  bytes  {facts.bytes:,}   pages {facts.page_count}")
        if facts.looks_scanned:
            click.secho("  no text layer detected - this looks like a scan", fg="yellow")

        if write:
            canonical = identity.canonical_sha256(path)
            try:
                pinning.pin_file(
                    doc.path,
                    instance=instance,
                    canonical_sha256=canonical,
                    canonicalizer=identity.canonicalizer_version() if canonical else None,
                )
            except pinning.PinError as exc:
                raise click.ClickException(
                    f"{doc.path.name}: {exc}. Pinning edits the identity block in place "
                    "to preserve the surrounding commentary, so that block must be present "
                    "and conventionally formatted."
                ) from exc
        pinned += 1

    if not pinned:
        click.echo("Nothing to pin.")
    elif not write:
        click.echo(f"\n{pinned} document(s) would be pinned. Re-run with --write to apply.")


@main.command("bench-parse")
@click.option(
    "--extractor",
    "extractors",
    multiple=True,
    help="Extractor to score (repeatable). Default: pypdf, pdfplumber, pymupdf. "
    "Pass docling explicitly for the experimental Docling bake-off.",
)
@click.option(
    "--write/--no-write",
    default=True,
    help="Write evals/parsing/results/scorecard.md",
)
def bench_parse(extractors: tuple[str, ...], write: bool) -> None:
    """Score extractor+chunker candidates against parsing fixtures."""
    from repair_assistant.parsing import bench

    results = bench.run_bakeoff(extractors=list(extractors) or None)
    card = bench.scorecard_markdown(results)
    click.echo(card)

    if write:
        corpus = _load()
        out = corpus.root / "evals" / "parsing" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.md").write_text(card, encoding="utf-8", newline="\n")
        click.echo(f"Wrote {out / 'scorecard.md'}")

    hard = {"error-codes-bound", "pua-list-markers"}
    structured = [
        r
        for r in results
        if r.extractor != "pypdf" and r.fixture_id in hard and not r.skipped
    ]
    baseline = [
        r
        for r in results
        if r.extractor == "pypdf" and r.fixture_id in hard and not r.skipped
    ]
    if baseline and any(r.passed for r in baseline if r.fixture_id == "error-codes-bound"):
        click.secho(
            "warning: pypdf baseline unexpectedly passed error-codes-bound",
            fg="yellow",
        )
    if structured and not any(
        r.passed for r in structured if r.fixture_id == "error-codes-bound"
    ):
        raise click.ClickException(
            "no structured extractor passed error-codes-bound; see scorecard"
        )


@main.command("parse")
@click.argument("doc_id", required=False)
@click.option("--all", "parse_all", is_flag=True, help="Parse every held document.")
@click.option(
    "--extractor",
    default="hybrid",
    show_default=True,
    help="Extractor for PDFs (see ADR-0024; hybrid is production default).",
)
def parse_cmd(doc_id: str | None, parse_all: bool, extractor: str) -> None:
    """Extract and chunk documents into corpus/parsed/<doc_id>/chunks.jsonl."""
    from repair_assistant.parsing import write as parse_write

    corpus = _load()
    if parse_all == bool(doc_id):
        raise click.ClickException("pass a doc_id or --all")

    targets = (
        list(corpus.documents)
        if parse_all
        else [d for d in corpus.documents if d.doc_id == doc_id or d.publication_number == doc_id]
    )
    if not targets:
        raise click.ClickException(f"nothing in the manifest matches {doc_id!r}")

    written = 0
    for document in targets:
        path = corpus.documents_dir / document.local_filename
        if not path.is_file():
            _echo_status("missing", document.citation, document.local_filename)
            continue
        try:
            out = parse_write.parse_document(document, extractor_name=extractor)
        except Exception as exc:
            _echo_status("mismatch", document.citation, str(exc))
            continue
        _echo_status("ok", document.citation, str(out.relative_to(corpus.root)))
        written += 1
    click.echo(f"Wrote chunks for {written} document(s).")


@main.command("audit-chunks")
@click.argument("doc_id", required=False)
@click.option("--all", "audit_all", is_flag=True, help="Audit every corpus/parsed document.")
@click.option(
    "--repair/--no-repair",
    default=False,
    help="Apply at most one safe repair pass (ADR-0022); default audit-only.",
)
def audit_chunks_cmd(doc_id: str | None, audit_all: bool, repair: bool) -> None:
    """Audit (and optionally repair once) existing corpus/parsed JSONL chunks."""
    import json
    from pathlib import Path

    from repair_assistant.parsing.chunk_quality import audit_and_improve, audit_chunks
    from repair_assistant.parsing.models import Chunk
    from repair_assistant.parsing.write import parsed_dir

    corpus = _load()
    if audit_all == bool(doc_id):
        raise click.ClickException("pass a doc_id or --all")

    root = parsed_dir(corpus.root)
    if audit_all:
        targets = sorted(p.parent.name for p in root.glob("*/chunks.jsonl"))
    else:
        targets = [doc_id] if (root / doc_id / "chunks.jsonl").is_file() else []
        if not targets:
            raise click.ClickException(f"no chunks.jsonl for {doc_id!r} under {root}")

    for did in targets:
        path = root / did / "chunks.jsonl"
        chunks: list[Chunk] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            data.pop("content_hash", None)
            chunks.append(Chunk(**{k: data[k] for k in data if k in Chunk.__dataclass_fields__}))
        if repair:
            chunks, report = audit_and_improve(chunks)
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for chunk in chunks:
                    handle.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")
        else:
            report = audit_chunks(chunks)
            report.stop_reason = "audit_only"
        quality_path = root / did / "chunk_quality.json"
        quality_path.write_text(
            json.dumps({"doc_id": did, **report.to_json()}, indent=2) + "\n",
            encoding="utf-8",
        )
        crit = sum(1 for f in report.findings if f.severity == "critical")
        _echo_status(
            "ok" if crit == 0 else "mismatch",
            did,
            f"{report.stop_reason} findings={len(report.findings)} critical={crit}",
        )


@main.command("db-migrate")
def db_migrate_cmd() -> None:
    """Apply Postgres / pgvector schema migrations (Phase 3)."""
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database, apply_migrations

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    with Database(url) as db:
        applied = apply_migrations(db)
    if applied:
        for version in applied:
            click.echo(f"Applied {version}")
    else:
        click.echo("Schema already up to date.")


@main.command("ingest")
@click.argument("doc_id", required=False)
@click.option("--all", "ingest_all", is_flag=True, help="Ingest every corpus/parsed document.")
@click.option("--force", is_flag=True, help="Re-upsert even when content fingerprint matches.")
@click.option(
    "--skip-embed",
    is_flag=True,
    help="Load text only; leave embedding columns NULL.",
)
def ingest_cmd(doc_id: str | None, ingest_all: bool, force: bool, skip_embed: bool) -> None:
    """Load corpus/parsed JSONL into Postgres and embed new/changed chunks."""
    from repair_assistant.ingest.embeddings import build_embedder
    from repair_assistant.ingest.env import database_url, embedding_model
    from repair_assistant.ingest.pipeline import ingest_parsed
    from repair_assistant.ingest.store import Database, apply_migrations

    if ingest_all == bool(doc_id):
        raise click.ClickException("pass a doc_id or --all")

    try:
        url = database_url()
        embedder = build_embedder(skip=skip_embed, model=embedding_model())
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    corpus = _load()
    doc_ids: set[str] | None = None
    if doc_id:
        matches = [
            d for d in corpus.documents if d.doc_id == doc_id or d.publication_number == doc_id
        ]
        if matches:
            doc_ids = {d.doc_id for d in matches}
        else:
            doc_ids = {doc_id}

    sha_by_doc: dict[str, str] = {}
    for d in corpus.documents:
        if d.known_hashes:
            sha_by_doc[d.doc_id] = sorted(d.known_hashes)[0]

    with Database(url) as db:
        apply_migrations(db)
        result = ingest_parsed(
            db,
            corpus.root / "corpus",
            embedder,
            doc_ids=doc_ids,
            force=force,
            corpus_sha_by_doc=sha_by_doc,
        )

    for stats in result.documents:
        detail = stats.detail
        if stats.status == "upserted":
            detail = detail or f"{stats.chunks} chunks, {stats.embedded} embedded"
        _echo_status(stats.status if stats.status != "upserted" else "ok", stats.doc_id, detail)

    click.echo()
    click.echo(
        f"Ingested {result.upserted}, skipped {result.skipped}, failed {result.failed}."
    )
    if result.failed:
        raise SystemExit(1)


@main.command("bench-retrieve")
@click.option("--write/--no-write", default=False, help="Write scorecard under evals/retrieval/results/")
@click.option("--k", default=None, type=int, help="Override top-K (default from fixtures.yaml).")
def bench_retrieve_cmd(write: bool, k: int | None) -> None:
    """Score retrieval strategies against evals/retrieval/fixtures.yaml (needs live DB)."""
    from repair_assistant.retrieval import bench as retrieve_bench

    try:
        results = retrieve_bench.run_bakeoff(k=k)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    card = retrieve_bench.scorecard_markdown(results)
    click.echo(card)
    if write:
        corpus = _load()
        out = corpus.root / "evals" / "retrieval" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.md").write_text(card, encoding="utf-8", newline="\n")
        click.echo(f"Wrote {out / 'scorecard.md'}")

    hard_fails = [r for r in results if r.hard and not r.passed]
    # Interim baseline must clear hard fixtures; bake-off records who wins.
    boost = [r for r in results if r.strategy == "vector_apply_boost" and r.hard]
    if boost and not any(r.passed for r in boost):
        raise click.ClickException(
            "vector_apply_boost failed all hard fixtures; see scorecard"
        )


@main.command("search")
@click.argument("query")
@click.option("--model", default=None, help="Appliance model for applicability filter.")
@click.option("--serial", default=None, help="Serial number for range checks.")
@click.option("--limit", default=8, show_default=True, type=int, help="Hits to return.")
@click.option(
    "--overfetch",
    default=40,
    show_default=True,
    type=int,
    help="Vector neighbours to fetch before applicability filter.",
)
def search_cmd(query: str, model: str | None, serial: str | None, limit: int, overfetch: int) -> None:
    """Semantic search over ingested chunks (Phase 4)."""
    from repair_assistant.corpus.applicability import Appliance
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database
    from repair_assistant.retrieval.search import search

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    appliance = Appliance(model=model, serial=serial) if model else None
    corpus = _load()
    with Database(url) as db:
        result = search(
            db,
            corpus,
            query,
            appliance=appliance,
            limit=limit,
            overfetch=overfetch,
        )

    click.secho(f"Query: {result.query}", bold=True)
    if appliance:
        click.echo(f"Appliance: {appliance.model}" + (f" / {appliance.serial}" if appliance.serial else ""))
    click.echo(
        f"Fetched {result.fetched} neighbours; "
        f"showing {len(result.hits)}"
        + (f" (filtered out {result.filtered_out})" if result.filtered_out else "")
    )
    click.echo()
    for i, hit in enumerate(result.hits, 1):
        cite = hit.publication_number or hit.doc_id
        if hit.revision:
            cite = f"{cite} Rev {hit.revision}"
        page = f" p.{hit.page}" if hit.page else ""
        codes = f" [{', '.join(hit.error_codes)}]" if hit.error_codes else ""
        click.secho(f"{i}. {cite}{page}{codes}  score={hit.score:.3f}", bold=True)
        click.echo(f"   {hit.doc_id} / {hit.chunk_id}")
        if hit.apply_reason:
            click.secho(f"   {hit.apply_reason}", fg="bright_black")
        preview = " ".join(hit.text.split())
        if len(preview) > 280:
            preview = preview[:277] + "..."
        click.echo(f"   {preview}")
        click.echo()


def _echo_safety(*, action: str, notice: str, escalated: bool) -> None:
    if action != "allow" or notice or escalated:
        label = f"Safety: {action}"
        if escalated:
            label += " (escalated)"
        click.secho(label, fg="yellow", bold=True)
        if notice:
            click.echo(notice)


@main.command("ask")
@click.argument("question")
@click.option("--model", default=None, help="Appliance model for applicability filter.")
@click.option("--serial", default=None, help="Serial number for range checks.")
@click.option(
    "--audience",
    type=click.Choice(["owner", "technician"]),
    default="owner",
    show_default=True,
    help="Who the answer is for — controls safety policy (Phase 7).",
)
@click.option("--limit", default=8, show_default=True, type=int, help="Evidence chunks to pass to the LLM.")
@click.option(
    "--overfetch",
    default=40,
    show_default=True,
    type=int,
    help="Vector neighbours to fetch before applicability filter.",
)
def ask_cmd(
    question: str,
    model: str | None,
    serial: str | None,
    audience: str,
    limit: int,
    overfetch: int,
) -> None:
    """Grounded repair Q&A over retrieved manufacturer evidence (Phase 5)."""
    from repair_assistant.corpus.applicability import Appliance
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database
    from repair_assistant.qa.generate import ask
    from repair_assistant.safety.models import Audience

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    appliance = Appliance(model=model, serial=serial) if model else None
    corpus = _load()
    with Database(url) as db:
        try:
            result = ask(
                db,
                corpus,
                question,
                appliance=appliance,
                audience=Audience(audience),
                retrieval_limit=limit,
                overfetch=overfetch,
            )
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    click.secho(f"Question: {result.question}", bold=True)
    if appliance:
        click.echo(
            f"Appliance: {appliance.model}"
            + (f" / {appliance.serial}" if appliance.serial else "")
        )
    click.echo(f"Retrieved {result.retrieval_count} chunk(s)")
    click.echo()
    _echo_safety(
        action=result.safety_action,
        notice=result.safety_notice,
        escalated=result.escalated,
    )
    if result.safety_notice:
        click.echo()

    if result.abstained:
        click.secho("Abstained", fg="yellow", bold=True)
        if result.answer:
            click.echo(result.answer)
        elif result.abstain_reason:
            click.echo(result.abstain_reason)
        return

    click.secho("Answer", bold=True)
    click.echo(result.answer)
    if result.citations:
        click.echo()
        click.secho("Sources", bold=True)
        for cite in result.citations:
            click.echo(f"  [{cite.index}] {cite.label}")
            click.secho(f"      {cite.doc_id} / {cite.chunk_id}", fg="bright_black")


@main.command("diagnose")
@click.argument("message", required=False)
@click.option("--model", required=True, help="Appliance model, e.g. WFW5620HW0")
@click.option("--serial", default=None, help="Serial number for range checks.")
@click.option(
    "--audience",
    type=click.Choice(["owner", "technician"]),
    default="owner",
    show_default=True,
    help="Who the session is for — controls safety policy (Phase 7).",
)
@click.option("--limit", default=8, show_default=True, type=int, help="Evidence chunks per turn.")
@click.option(
    "--overfetch",
    default=40,
    show_default=True,
    type=int,
    help="Vector neighbours to fetch before applicability filter.",
)
def diagnose_cmd(
    message: str | None,
    model: str,
    serial: str | None,
    audience: str,
    limit: int,
    overfetch: int,
) -> None:
    """Multi-turn grounded troubleshooting (Phase 6 LangGraph)."""
    import uuid

    from repair_assistant.corpus.applicability import Appliance
    from repair_assistant.diagnostic.session import DiagnosticSession
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database
    from repair_assistant.safety.models import Audience

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    appliance = Appliance(model=model, serial=serial)
    corpus = _load()

    def _print_turn(result) -> None:
        click.secho(f"\nTurn {result.turn}", bold=True)
        click.echo(f"You: {result.user_message}")
        if result.abstained:
            click.secho("Assistant (abstained):", fg="yellow", bold=True)
            click.echo(result.abstain_reason or result.assistant_message)
        else:
            click.secho("Assistant:", bold=True)
            click.echo(result.assistant_message)
        click.echo(f"(retrieved {result.retrieval_count} chunk(s))")
        _echo_safety(
            action=result.safety_action,
            notice=result.safety_notice,
            escalated=result.escalated,
        )
        if result.citations:
            click.secho("Sources:", bold=True)
            for cite in result.citations:
                click.echo(f"  [{cite.index}] {cite.label}")
                click.secho(f"      {cite.doc_id} / {cite.chunk_id}", fg="bright_black")

    with Database(url) as db:
        session = DiagnosticSession(
            corpus,
            appliance=appliance,
            audience=Audience(audience),
            retrieval_limit=limit,
            overfetch=overfetch,
            session_id=str(uuid.uuid4()),
        )

        if message:
            try:
                _print_turn(session.send(db, message))
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc
            return

        click.secho(
            f"Diagnostic session for {model}"
            + (f" / {serial}" if serial else "")
            + " — type 'quit' or 'exit' to end.",
            bold=True,
        )
        while True:
            try:
                user = click.prompt("\nYou", prompt_suffix="> ")
            except (EOFError, KeyboardInterrupt):
                click.echo()
                break
            stripped = user.strip()
            if not stripped:
                continue
            if stripped.lower() in {"quit", "exit", "q"}:
                break
            try:
                _print_turn(session.send(db, stripped))
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc


@main.command("bench-chain")
@click.option("--write/--no-write", default=False, help="Write scorecard under evals/chain/results/")
@click.option(
    "--extractor",
    default="pdfplumber",
    show_default=True,
    help="Extractor for PDFs (same as parse).",
)
@click.option(
    "--skip-ask",
    is_flag=True,
    help="Stop after retrieve (no OpenAI); still runs parse→ingest→search.",
)
def bench_chain_cmd(write: bool, extractor: str, skip_ask: bool) -> None:
    """Thin parse->ingest->retrieve->ask smoke (manual; needs DB + embeddings)."""
    from repair_assistant.eval.chain_bench import run_chain_bench, scorecard_markdown
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    with Database(url) as db:
        try:
            results = run_chain_bench(db, extractor=extractor, skip_ask=skip_ask)
        except (KeyError, RuntimeError) as exc:
            raise click.ClickException(str(exc)) from exc

    card = scorecard_markdown(results)
    click.echo(card)

    if write:
        corpus = _load()
        out = corpus.root / "evals" / "chain" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.md").write_text(card, encoding="utf-8", newline="\n")
        click.echo(f"Wrote {out / 'scorecard.md'}")

    if any(not r.passed for r in results):
        raise click.ClickException("chain smoke failed; see scorecard")


@main.command("bench-qa")
@click.option("--write/--no-write", default=False, help="Write scorecard and JSON run log.")
@click.option("--scenario", "scenario_ids", multiple=True, help="Run only these scenario id(s).")
@click.option(
    "--judge/--no-judge",
    default=False,
    help="After deterministic grading, LLM-judge prose expect/fails_if (extra OpenAI cost).",
)
def bench_qa_cmd(write: bool, scenario_ids: tuple[str, ...], judge: bool) -> None:
    """Run live Q&A smoke scenarios (needs DB + OPENAI_API_KEY)."""
    from datetime import UTC, datetime

    from repair_assistant.eval.qa_bench import run_smoke_bench, scorecard_markdown, write_run_log
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    ids = set(scenario_ids) if scenario_ids else None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with Database(url) as db:
        try:
            results = run_smoke_bench(
                db, scenario_ids=ids, use_judge=judge, eval_run_id=stamp
            )
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    card = scorecard_markdown(results)
    click.echo(card)

    if write:
        corpus = _load()
        out = corpus.root / "evals" / "qa" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.md").write_text(card, encoding="utf-8", newline="\n")
        log_path = out / "runs" / f"{stamp}.json"
        write_run_log(results, log_path)
        click.echo(f"Wrote {out / 'scorecard.md'}")
        click.echo(f"Wrote {log_path}")

    if any(not r.passed for r in results):
        raise click.ClickException("one or more Q&A smoke scenarios failed; see scorecard")


@main.command("bench-candidates")
@click.option("--write/--no-write", default=False, help="Write scorecard and JSON run log.")
@click.option("--scenario", "scenario_ids", multiple=True, help="Run only these scenario id(s).")
@click.option(
    "--judge/--no-judge",
    default=False,
    help="After deterministic grading, LLM-judge prose expect/fails_if (extra OpenAI cost).",
)
def bench_candidates_cmd(write: bool, scenario_ids: tuple[str, ...], judge: bool) -> None:
    """Run live ask() against ready evals/scenarios/candidates.yaml (needs DB + OpenAI)."""
    from datetime import UTC, datetime

    from repair_assistant.eval.candidates_bench import (
        run_candidates_bench,
        scorecard_markdown,
        to_qa_results,
    )
    from repair_assistant.eval.qa_bench import write_run_log
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database

    try:
        url = database_url()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    ids = set(scenario_ids) if scenario_ids else None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"candidates-{stamp}"
    with Database(url) as db:
        try:
            results = run_candidates_bench(
                db, scenario_ids=ids, use_judge=judge, eval_run_id=run_id
            )
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    card = scorecard_markdown(results)
    click.echo(card)

    if write:
        corpus = _load()
        out = corpus.root / "evals" / "qa" / "results"
        out.mkdir(parents=True, exist_ok=True)
        (out / "candidates-scorecard.md").write_text(card, encoding="utf-8", newline="\n")
        log_path = out / "runs" / f"{run_id}.json"
        write_run_log(to_qa_results(results), log_path)
        click.echo(f"Wrote {out / 'candidates-scorecard.md'}")
        click.echo(f"Wrote {log_path}")

    if any(not r.passed for r in results):
        raise click.ClickException("one or more candidate scenarios failed; see scorecard")


@main.command("prune-eval-runs")
@click.option("--keep", type=int, default=None, help="Keep newest N JSON logs per prefix.")
@click.option(
    "--older-than-days",
    type=int,
    default=None,
    help="Delete JSON logs older than this many days (by mtime).",
)
@click.option(
    "--dry-run/--execute",
    default=True,
    help="Dry-run lists deletions; --execute removes them (manual only).",
)
def prune_eval_runs_cmd(keep: int | None, older_than_days: int | None, dry_run: bool) -> None:
    """Prune evals/qa/results/runs/*.json (E9; never scheduled)."""
    from repair_assistant.eval.run_log_prune import apply_prune, plan_prune, runs_dir

    try:
        plan = plan_prune(keep=keep, older_than_days=older_than_days)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Runs dir: {runs_dir()}")
    click.echo(f"Keep {len(plan.keep)}, delete {len(plan.delete)} ({'dry-run' if dry_run else 'execute'})")
    for path in plan.delete:
        click.echo(f"  delete {path.name}")
    removed = apply_prune(plan, dry_run=dry_run)
    if dry_run and removed:
        click.echo("Re-run with --execute to delete.")
    elif not dry_run:
        click.echo(f"Removed {len(removed)} file(s).")


@main.command("bench-judge-calibrate")
@click.option("--write/--no-write", default=False, help="Write scorecard under evals/qa/results/")
def bench_judge_calibrate_cmd(write: bool) -> None:
    """Score frozen judge-calibration.yaml cases (OpenAI; no DB / ask)."""
    from repair_assistant.eval.judge_calibrate import (
        load_calibration,
        run_calibration,
        scorecard_markdown,
    )
    from repair_assistant.qa.env import llm_model, openai_api_key
    from repair_assistant.qa.generate import OpenAIClient

    try:
        key = openai_api_key()
        model = llm_model()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    cases = load_calibration()
    results = run_calibration(cases, llm=OpenAIClient(api_key=key, model=model))
    card = scorecard_markdown(results)
    click.echo(card)

    if write:
        corpus = _load()
        out = corpus.root / "evals" / "qa" / "results"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "judge-calibration-scorecard.md"
        path.write_text(card, encoding="utf-8", newline="\n")
        click.echo(f"Wrote {path}")

    if any(not r.agreed for r in results):
        raise click.ClickException("judge calibration disagreement; see scorecard")


@main.command("promote-eval")
@click.option(
    "--run",
    "run_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
    help="Path to a bench JSON run log under evals/qa/results/runs/.",
)
@click.option("--scenario", "scenario_id", required=True, help="Failed scenario id to promote.")
@click.option(
    "--write/--no-write",
    default=False,
    help="Write draft under candidates-grading.yaml scenarios.<id>.draft.",
)
@click.option("--force", is_flag=True, help="Replace an existing draft for this scenario.")
def promote_eval_cmd(run_path: Path, scenario_id: str, write: bool, force: bool) -> None:
    """Draft a grading-overlay stub from a failed bench run (manual review)."""
    from repair_assistant.eval.promote import promote_failure

    try:
        text, written = promote_failure(
            Path(run_path),
            scenario_id,
            write=write,
            force=force,
        )
    except (KeyError, ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(text)
    if written is not None:
        click.echo(f"Wrote draft under {written} → scenarios.{scenario_id}.draft")
        click.echo("Review the draft, promote useful keys to the live overlay, then delete .draft.")


@main.command("mine-traces")
@click.option(
    "--since",
    default="7d",
    show_default=True,
    help="Look back window (e.g. 7d, 24h, 30m).",
)
@click.option("--limit", default=50, show_default=True, help="Max Langfuse traces to fetch.")
@click.option(
    "--write/--no-write",
    default=False,
    help="Write analysis report under evals/qa/drafts/ (no fixture/state changes).",
)
@click.option(
    "--include-unstamped",
    is_flag=True,
    help="Include traces missing app_git_sha (still subject to replay).",
)
@click.option(
    "--since-sha",
    default=None,
    help="Only keep traces stamped with this short git SHA.",
)
@click.option(
    "--no-replay",
    is_flag=True,
    help="Skip replay gate (not recommended; drafts may reopen fixed bugs).",
)
def mine_traces_cmd(
    since: str,
    limit: int,
    write: bool,
    include_unstamped: bool,
    since_sha: str | None,
    no_replay: bool,
) -> None:
    """Mine Langfuse ask/diagnose traces into a reviewable analysis report (ADR-0023).

    Replays candidates on current code so pre-fix traces become resolved_stale.
    ``--write`` only writes a markdown report; it never edits live fixtures.
    """
    from repair_assistant.eval.mine_traces import (
        fetch_langfuse_traces,
        parse_since,
        run_mine,
    )
    from repair_assistant.ingest.env import database_url
    from repair_assistant.ingest.store import Database
    from repair_assistant.observability.langfuse_tracing import tracing_enabled

    if not tracing_enabled():
        raise click.ClickException(
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required for mine-traces."
        )
    try:
        cutoff = parse_since(since)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Fetching Langfuse traces since {cutoff.isoformat()} (limit={limit})…")
    try:
        records = fetch_langfuse_traces(since=cutoff, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Langfuse fetch failed: {exc}") from exc
    click.echo(f"Fetched {len(records)} trace record(s).")

    db = None
    if not no_replay:
        try:
            db = Database(database_url())
        except Exception as exc:  # noqa: BLE001
            raise click.ClickException(
                f"Replay needs DATABASE_URL / Postgres: {exc}"
            ) from exc

    try:
        result = run_mine(
            records,
            write=write,
            require_git_sha=not include_unstamped,
            include_unstamped=include_unstamped,
            since_sha=since_sha,
            replay=not no_replay,
            db=db,
        )
    finally:
        if db is not None:
            db.close()

    counts: dict[str, int] = {}
    for o in result.outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
        click.echo(
            f"  {o.status:16} trace={o.trace_id[:12]}… "
            f"codes={o.failure_codes or '-'} {o.detail}"
        )
    click.echo("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if write and result.report_path:
        click.echo(f"Wrote analysis report: {result.report_path}")
        click.echo("No live fixtures or mine-state were modified.")
    else:
        click.echo("Dry run — pass --write to save the analysis report.")


@main.command("bench-safety")
def bench_safety_cmd() -> None:
    """Run deterministic safety-policy checks against evals/safety/fixtures.yaml."""
    from repair_assistant.safety.bench import run_bench, scorecard_markdown

    results = run_bench()
    card = scorecard_markdown(results)
    click.echo(card)
    if any(r.hard and not r.passed for r in results):
        raise click.ClickException("safety bench failed hard fixtures; see output above")


def yaml_dump(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)


if __name__ == "__main__":  # pragma: no cover
    main()
