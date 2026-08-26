"""Corpus coverage checks and owner-facing support messages."""

from __future__ import annotations

from dataclasses import dataclass

from repair_assistant.corpus.applicability import Appliance, document_applies
from repair_assistant.corpus.manifest import Manifest

ABSTAIN_UNSUPPORTED_MODEL = "unsupported_model"
ABSTAIN_NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True)
class CorpusSupportResult:
    """Whether the held manifest covers an appliance at all."""

    supported: bool
    applicable_documents: int
    code: str
    detail: str


def corpus_supports_appliance(manifest: Manifest, appliance: Appliance) -> CorpusSupportResult:
    """True when at least one manifest document applies to the appliance."""
    count = 0
    for doc in manifest.documents:
        if document_applies(doc.data, appliance).applies:
            count += 1
    if count == 0:
        return CorpusSupportResult(
            supported=False,
            applicable_documents=0,
            code=ABSTAIN_UNSUPPORTED_MODEL,
            detail=f"no manifest document applies to model {appliance.model}",
        )
    return CorpusSupportResult(
        supported=True,
        applicable_documents=count,
        code="ok",
        detail=f"{count} manifest document(s) apply",
    )


def unsupported_appliance_message(appliance: Appliance) -> str:
    """Owner-facing message when the model is outside the corpus."""
    serial_hint = ""
    if appliance.serial:
        serial_hint = f" (serial {appliance.serial})"
    return (
        f"We don't have Whirlpool manufacturer service documentation for model "
        f"{appliance.model}{serial_hint} in this assistant.\n\n"
        "Check the model number on your appliance rating plate or door frame "
        "(often near the serial label).\n\n"
        "For repair help on this machine, contact Whirlpool Customer Care with "
        "your model and serial number, or visit whirlpool.com/support."
    )


def no_evidence_message(appliance: Appliance | None) -> str:
    """Owner-facing message when the model is covered but retrieval found nothing."""
    if appliance:
        return (
            f"No applicable manufacturer evidence was found for this question "
            f"on model {appliance.model}. Try rephrasing, include an error code "
            f"if one is displayed, or contact Whirlpool Customer Care with your "
            f"model and serial number."
        )
    return (
        "No applicable manufacturer evidence was retrieved. Specify an appliance "
        "model or rephrase your question."
    )


__all__ = [
    "ABSTAIN_NO_EVIDENCE",
    "ABSTAIN_UNSUPPORTED_MODEL",
    "CorpusSupportResult",
    "corpus_supports_appliance",
    "no_evidence_message",
    "unsupported_appliance_message",
]
