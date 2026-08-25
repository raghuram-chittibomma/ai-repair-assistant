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

from . import identity
from . import manifest as manifest_mod
from .applicability import Appliance, document_applies

# --- presentation -----------------------------------------------------------

_COLOURS = {
    "ok": "green",
    "missing": "yellow",
    "mismatch": "red",
    "unpinned": "cyan",
    "drift": "magenta",
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
            data = doc.data
            data.setdefault("identity", {}).setdefault("instances", []).append(instance)
            canonical = identity.canonical_sha256(path)
            if canonical:
                data["identity"]["canonical_sha256"] = canonical
                data["identity"]["canonicalizer"] = identity.canonicalizer_version()
            doc.path.write_text(yaml_dump(data), encoding="utf-8")
        pinned += 1

    if not pinned:
        click.echo("Nothing to pin.")
    elif not write:
        click.echo(f"\n{pinned} document(s) would be pinned. Re-run with --write to apply.")


def yaml_dump(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)


if __name__ == "__main__":  # pragma: no cover
    main()
