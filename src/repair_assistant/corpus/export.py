"""Export the manifest as Croissant JSON-LD.

Croissant (MLCommons) is a schema.org-based vocabulary for describing datasets
whose files live elsewhere, which matches this corpus exactly. It is an *export*
target rather than the source format: its RecordSet machinery is aimed at
tabular data we do not have, and hand-written YAML reviews far better in a pull
request. See docs/adr/0001-corpus-manifest-format.md.

The export contains metadata only. No document content is ever emitted.
"""

from __future__ import annotations

from typing import Any

CONTEXT = {
    "@vocab": "https://schema.org/",
    "cr": "http://mlcommons.org/croissant/",
    "sc": "https://schema.org/",
    "dct": "http://purl.org/dc/terms/",
    "citeAs": "cr:citeAs",
    "contentUrl": "sc:contentUrl",
    "encodingFormat": "sc:encodingFormat",
    "sha256": "sc:sha256",
}


def _file_object(document) -> dict[str, Any]:
    provenance = document.provenance
    identity = document.data.get("identity") or {}
    instances = identity.get("instances") or []

    obj: dict[str, Any] = {
        "@type": "cr:FileObject",
        "@id": document.doc_id,
        "name": document.doc_id,
        "description": document.title,
        "encodingFormat": (
            "text/html" if document.local_filename.endswith(".html") else "application/pdf"
        ),
        "citeAs": document.citation,
        "dct:type": document.doc_type,
        "sc:license": provenance.get("license", "NOASSERTION"),
    }

    if url := provenance.get("source_url"):
        obj["contentUrl"] = url
    if instances and instances[0].get("sha256"):
        obj["sha256"] = instances[0]["sha256"]
    if published := (document.data.get("temporal") or {}).get("publication_date"):
        obj["dct:issued"] = published

    applicability = document.data.get("applicability") or {}
    if models := applicability.get("models"):
        obj["keywords"] = list(models)

    return obj


def to_croissant(manifest) -> dict[str, Any]:
    """Render the manifest as a Croissant dataset description."""
    return {
        "@context": CONTEXT,
        "@type": "sc:Dataset",
        "name": "whirlpool-wfw5620hw0-repair-corpus",
        "description": (
            "Manifest describing authoritative Whirlpool manufacturer documentation for "
            "the WFW5620H front-load washer family. Metadata only: the documents "
            "themselves are copyrighted and are not distributed."
        ),
        "conformsTo": "http://mlcommons.org/croissant/1.0",
        "sc:license": "LicenseRef-Whirlpool-Proprietary",
        "distribution": [_file_object(d) for d in manifest.documents],
    }
