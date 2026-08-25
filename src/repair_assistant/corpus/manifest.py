"""Loading and validating the corpus manifest.

The manifest is the source of truth for what the corpus contains. It lives in
git, is reviewed in diffs, and describes documents that are deliberately absent
from the repository. See docs/CORPUS_LICENSING.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

# SPDX identifiers that would imply a manufacturer document may be redistributed.
# Any of these appearing in the manifest is a bug, and CI treats it as one.
REDISTRIBUTABLE_SPDX = frozenset(
    {
        "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0",
        "CC-BY-4.0", "CC-BY-SA-4.0", "GPL-3.0-only", "GPL-3.0-or-later",
        "LGPL-3.0-only", "MPL-2.0", "Unlicense", "ISC",
    }
)


def repo_root(start: Path | None = None) -> Path:
    """Walk upwards to the directory containing corpus/manifest-schema.json."""
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "corpus" / "manifest-schema.json").is_file():
            return candidate
    raise FileNotFoundError(
        "could not locate the repository root (no corpus/manifest-schema.json found)"
    )


@dataclass(frozen=True)
class Document:
    """One manifest entry."""

    data: dict
    path: Path

    @property
    def doc_id(self) -> str:
        return self.data["doc_id"]

    @property
    def publication_number(self) -> str | None:
        return self.data.get("publication_number")

    @property
    def revision(self) -> str | None:
        return self.data.get("revision")

    @property
    def title(self) -> str:
        return self.data["title"]

    @property
    def doc_type(self) -> str:
        return self.data["doc_type"]

    @property
    def role(self) -> str:
        return self.data["corpus"]["role"]

    @property
    def provenance(self) -> dict:
        return self.data.get("provenance", {})

    @property
    def local_filename(self) -> str:
        """Expected filename under corpus/documents/."""
        explicit = self.provenance.get("local_filename")
        if explicit:
            return explicit
        stem = self.publication_number or self.doc_id
        return f"{stem}{self.revision or ''}.pdf"

    @property
    def instances(self) -> list[dict]:
        return (self.data.get("identity") or {}).get("instances") or []

    @property
    def content_volatile(self) -> bool:
        """Whether this document's bytes are reproducible across acquisitions."""
        return bool((self.data.get("identity") or {}).get("content_volatile", False))

    @property
    def known_hashes(self) -> set[str]:
        return {i["sha256"] for i in self.instances if i.get("sha256")}

    @property
    def citation(self) -> str:
        """How this document should be named in a citation.

        Published literature cites by publication number and revision, which is
        what a technician would look up. Knowledge-base articles have no
        publication number, so the manifest's own slug is used: it is short and
        stable, whereas the MindTouch path is neither.
        """
        if self.publication_number:
            rev = f" Rev {self.revision}" if self.revision else ""
            return f"{self.publication_number}{rev}"
        return self.doc_id

    def relationships(self, kind: str | None = None) -> list[dict]:
        rels = self.data.get("relationships") or []
        return [r for r in rels if kind is None or r.get("type") == kind]


@dataclass
class Manifest:
    documents: list[Document] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    root: Path = field(default_factory=repo_root)

    @property
    def documents_dir(self) -> Path:
        return self.root / "corpus" / "documents"

    @cached_property
    def by_doc_id(self) -> dict[str, Document]:
        return {d.doc_id: d for d in self.documents}

    def by_publication(self, number: str, revision: str | None = None) -> list[Document]:
        return [
            d for d in self.documents
            if d.publication_number == number
            and (revision is None or d.revision == revision)
        ]

    def known_publication_numbers(self) -> set[str]:
        """Publication numbers in the manifest or explicitly recorded as absent."""
        known = {d.publication_number for d in self.documents if d.publication_number}
        known |= {e["publication_number"] for e in self.excluded if e.get("publication_number")}
        return known

    def find(self, needle: str) -> list[Document]:
        needle = needle.strip().lower()
        return [
            d for d in self.documents
            if needle in d.doc_id.lower()
            or (d.publication_number or "").lower() == needle
            or needle in d.title.lower()
        ]


def _normalise_dates(data: dict) -> dict:
    """Render date-ish YAML scalars as strings.

    YAML resolves ``2019-12-14`` to a ``datetime.date`` and ``2020`` to an int.
    Both are reasonable YAML behaviour and both are a nuisance here, because the
    manifest deliberately allows year-only and year-month precision -- a service
    pointer dated "June 2019" has no day, and inventing one would be a small
    fabrication. Normalising to strings on load keeps the files pleasant to write
    by hand while giving the schema a single type to check.
    """
    import datetime as _dt

    temporal = data.get("temporal")
    if not isinstance(temporal, dict):
        return data

    for key, value in list(temporal.items()):
        if isinstance(value, _dt.datetime):
            temporal[key] = value.date().isoformat()
        elif isinstance(value, _dt.date):
            temporal[key] = value.isoformat()
        elif isinstance(value, int):
            temporal[key] = str(value)
    return data


def load(root: Path | None = None) -> Manifest:
    """Read every manifest entry plus the exclusion list."""
    root = root or repo_root()
    manifest_dir = root / "corpus" / "manifest"

    documents: list[Document] = []
    for path in sorted(manifest_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if data is None:
            raise ValueError(f"{path.name} is empty")
        documents.append(Document(data=_normalise_dates(data), path=path))

    excluded: list[dict] = []
    excluded_path = manifest_dir / "_excluded.yaml"
    if excluded_path.is_file():
        with open(excluded_path, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        excluded = payload.get("excluded") or []

    return Manifest(documents=documents, excluded=excluded, root=root)


def load_schema(root: Path | None = None) -> dict:
    root = root or repo_root()
    with open(root / "corpus" / "manifest-schema.json", encoding="utf-8") as handle:
        return json.load(handle)


def validate(manifest: Manifest) -> list[str]:
    """Validate the manifest. Returns a list of problems; empty means valid.

    Covers three classes of error: schema violations, cross-entry integrity
    (duplicate ids, dangling relationship targets), and the licensing guarantee
    that no entry claims a manufacturer document is redistributable.
    """
    from jsonschema import Draft202012Validator

    problems: list[str] = []
    validator = Draft202012Validator(load_schema(manifest.root))

    seen_ids: dict[str, Path] = {}
    seen_editions: dict[tuple[str, str | None], Path] = {}

    for document in manifest.documents:
        name = document.path.name

        for error in sorted(validator.iter_errors(document.data), key=lambda e: e.path):
            location = "/".join(str(p) for p in error.path) or "(root)"
            problems.append(f"{name}: schema: {location}: {error.message}")

        if document.doc_id in seen_ids:
            problems.append(
                f"{name}: duplicate doc_id {document.doc_id!r} "
                f"(also in {seen_ids[document.doc_id].name})"
            )
        seen_ids[document.doc_id] = document.path

        if document.publication_number:
            edition = (document.publication_number, document.revision)
            if edition in seen_editions:
                problems.append(
                    f"{name}: duplicate edition {document.citation} "
                    f"(also in {seen_editions[edition].name})"
                )
            seen_editions[edition] = document.path

        # The licensing guarantee, enforced rather than documented.
        licence = document.provenance.get("license", "")
        if licence in REDISTRIBUTABLE_SPDX:
            problems.append(
                f"{name}: license {licence!r} implies redistribution is permitted. "
                "Manufacturer documents must use a LicenseRef-* identifier or NOASSERTION."
            )
        if document.provenance.get("redistributable") is True:
            problems.append(f"{name}: redistributable must be false for manufacturer documents")

    # Relationship targets must resolve, otherwise precedence reasoning silently
    # dead-ends. Targets may point at excluded documents: that is the point of
    # keeping an exclusion list.
    known = manifest.known_publication_numbers()
    for document in manifest.documents:
        for relationship in document.relationships():
            target = relationship.get("target")
            if target and target not in known:
                problems.append(
                    f"{document.path.name}: relationship {relationship.get('type')} "
                    f"points at unknown publication {target!r}; add it to the manifest "
                    "or to _excluded.yaml"
                )

    return problems
