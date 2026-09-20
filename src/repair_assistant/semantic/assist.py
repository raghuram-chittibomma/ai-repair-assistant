"""Specialist assist for overview / facts / questions curation (ADR-0053).

Assist turns attach the unit's native PDF page-range (or page rasters when
scanned) plus document/unit context so layout and spatial cues inform suggestions.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from repair_assistant.api.assist_sessions import AssistSession, AssistTurn
from repair_assistant.prompts import corpus_assist_system, prompt_digest
from repair_assistant.qa.page_images import PageImage
from repair_assistant.semantic.env import semantic_llm_model
from repair_assistant.semantic.schema import ASSIST_RESPONSE_FORMAT
from repair_assistant.semantic.units import SemanticUnit

_log = logging.getLogger("repair_assistant.semantic.assist")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
MAX_SOURCE_CHARS = 24_000
MAX_TRANSCRIPT_CHARS = 12_000
#: Cap rasters for scanned-unit assist (same family as generate).
DEFAULT_ASSIST_MAX_PAGES = 8


class AssistClient(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        *,
        pdf_path: Path | str | None = None,
        images: list[PageImage] | None = None,
    ) -> str: ...


class AssistError(RuntimeError):
    """Assist model returned unusable JSON."""


@dataclass(frozen=True)
class DocumentContext:
    """Short bibliographic context for the assist prompt."""

    doc_id: str
    title: str = ""
    doc_type: str = ""
    publication_number: str = ""
    revision: str = ""


@dataclass(frozen=True)
class AssistSuggestion:
    rationale: str
    overview: str
    facts: list[str]
    questions: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rationale": self.rationale,
            "overview": self.overview,
            "facts": list(self.facts),
            "questions": list(self.questions),
        }


@dataclass
class AssistAttachments:
    """Temp PDF slice and/or page rasters for one assist turn."""

    pdf_path: Path | None = None
    images: list[PageImage] | None = None
    modality: str = "none"  # pdf | vision | none
    temp_dir: Path | None = None

    def cleanup(self) -> None:
        if self.pdf_path is not None:
            try:
                self.pdf_path.unlink(missing_ok=True)
            except OSError:
                _log.warning("Could not delete assist PDF %s", self.pdf_path)
        if self.temp_dir is not None:
            with contextlib.suppress(OSError):
                self.temp_dir.rmdir()


def build_assist_client(*, model: str | None = None) -> AssistClient:
    from repair_assistant.qa.generate import OpenAIClient
    from repair_assistant.semantic.env import (
        semantic_llm_base_url,
        semantic_openai_api_key,
    )

    return OpenAIClient(
        api_key=semantic_openai_api_key(),
        model=model or semantic_llm_model(),
        prompt_name="corpus_assist_system",
        response_format=ASSIST_RESPONSE_FORMAT,
        base_url=semantic_llm_base_url(),
    )


def parse_assist_response(raw: str) -> AssistSuggestion:
    text = _FENCE.sub("", (raw or "").strip())
    if not text:
        raise AssistError("assist returned nothing")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssistError(f"assist output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssistError("assist output is not a JSON object")

    def _str_list(key: str) -> list[str]:
        raw_items = payload.get(key)
        if raw_items is None:
            return []
        if not isinstance(raw_items, list):
            raise AssistError(f"{key} must be an array")
        return [str(i).strip() for i in raw_items if str(i).strip()]

    return AssistSuggestion(
        rationale=str(payload.get("rationale") or "").strip(),
        overview=str(payload.get("overview") or "").strip(),
        facts=_str_list("facts"),
        questions=_str_list("questions"),
    )


def prepare_unit_attachments(
    *,
    pdf_path: Path | None,
    unit: SemanticUnit,
    doc_id: str,
    looks_scanned: bool,
    raster_loader: Callable[[str, int], Path | None] | None = None,
    max_pages: int = DEFAULT_ASSIST_MAX_PAGES,
) -> AssistAttachments:
    """Build a native PDF page-range or page rasters for the unit span."""
    start = unit.page_start
    end = unit.page_end if unit.page_end is not None else start
    if start is None or end is None or int(start) < 1 or int(end) < int(start):
        return AssistAttachments(modality="none")
    start_i, end_i = int(start), int(end)

    if looks_scanned:
        if raster_loader is None:
            return AssistAttachments(modality="none")
        images: list[PageImage] = []
        for page in range(start_i, end_i + 1):
            if len(images) >= max_pages:
                break
            cache = raster_loader(doc_id, page)
            if cache is None or not cache.is_file():
                continue
            images.append(
                PageImage(
                    index=len(images) + 1,
                    doc_id=doc_id,
                    page=page,
                    jpeg_bytes=cache.read_bytes(),
                )
            )
        if not images:
            return AssistAttachments(modality="none")
        return AssistAttachments(images=images, modality="vision")

    if pdf_path is None or not Path(pdf_path).is_file():
        return AssistAttachments(modality="none")

    from repair_assistant.semantic.pdf_extract import write_pdf_part

    temp_dir = Path(tempfile.mkdtemp(prefix="corpus-assist-pdf-"))
    dest = temp_dir / f"unit-{unit.unit_key}-p{start_i}-{end_i}.pdf"
    try:
        write_pdf_part(Path(pdf_path), start_page=start_i, end_page=end_i, dest=dest)
    except Exception:  # noqa: BLE001
        _log.warning(
            "Assist PDF slice failed for %s pp.%s-%s",
            unit.unit_key,
            start_i,
            end_i,
            exc_info=True,
        )
        with contextlib.suppress(OSError):
            temp_dir.rmdir()
        return AssistAttachments(modality="none")
    return AssistAttachments(pdf_path=dest, modality="pdf", temp_dir=temp_dir)


def _draft_block(draft: dict[str, Any] | None) -> str:
    if not draft:
        return "(no local draft provided)"
    overview = str(draft.get("overview") or "").strip()
    facts = draft.get("facts")
    questions = draft.get("questions")
    if isinstance(facts, str):
        fact_lines = [ln.strip() for ln in facts.splitlines() if ln.strip()]
    elif isinstance(facts, list):
        fact_lines = [str(x).strip() for x in facts if str(x).strip()]
    else:
        fact_lines = []
    if isinstance(questions, str):
        q_lines = [ln.strip() for ln in questions.splitlines() if ln.strip()]
    elif isinstance(questions, list):
        q_lines = [str(x).strip() for x in questions if str(x).strip()]
    else:
        q_lines = []
    lines = ["overview:", overview or "(empty)", "", "facts:"]
    if fact_lines:
        lines.extend(f"- {f}" for f in fact_lines)
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("questions:")
    if q_lines:
        lines.extend(f"- {q}" for q in q_lines)
    else:
        lines.append("(none)")
    return "\n".join(lines)


def _transcript_block(session: AssistSession) -> str:
    if not session.turns:
        return "(no prior turns)"
    parts: list[str] = []
    for turn in session.turns[-20:]:
        label = "Reviewer" if turn.role == "user" else "Assistant"
        unit = f" [{turn.unit_key}]" if turn.unit_key else ""
        parts.append(f"{label}{unit}: {turn.content}")
    text = "\n".join(parts)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[-MAX_TRANSCRIPT_CHARS:].lstrip()
        text = "[transcript truncated]\n" + text
    return text


def build_user_prompt(
    *,
    unit: SemanticUnit,
    message: str,
    draft: dict[str, Any] | None,
    session: AssistSession,
    document: DocumentContext | None = None,
    attachment_modality: str = "none",
) -> str:
    body = unit.source_text or ""
    if len(body) > MAX_SOURCE_CHARS:
        body = body[:MAX_SOURCE_CHARS].rstrip() + "\n[unit continues]"
    doc = document or DocumentContext(doc_id=session.doc_id)
    attach_note = {
        "pdf": (
            "A native PDF page-range file for this unit is attached. "
            "Prefer layout visible in that PDF (tables, figures, spatial "
            "grouping) over the thin source_text extract when they differ."
        ),
        "vision": (
            "Page image rasters for this unit are attached (scanned PDF). "
            "Prefer what is visible in those images over the thin source_text "
            "extract when they differ."
        ),
        "none": (
            "No PDF/raster attachment could be prepared; use source_text only."
        ),
    }.get(attachment_modality, "")

    lines = [
        "Document context:",
        f"  doc_id: {doc.doc_id}",
        f"  title: {doc.title or '(unknown)'}",
        f"  doc_type: {doc.doc_type or '(unknown)'}",
        f"  publication: {doc.publication_number or '(none)'}",
        f"  revision: {doc.revision or '(none)'}",
        f"  curation_version: {session.version}",
        "",
        "Unit context:",
        f"  unit_key: {unit.unit_key}",
        f"  title: {unit.title or '(untitled)'}",
        f"  unit_type: {unit.unit_type}",
        f"  pages: {unit.page_label or '(unknown)'}",
        f"  page_start: {unit.page_start}",
        f"  page_end: {unit.page_end}",
        f"  start_y: {unit.start_y}",
        f"  end_y: {unit.end_y}",
        f"  attachment: {attachment_modality}",
        "",
        attach_note,
        "",
        "Current local draft (may be unsaved):",
        _draft_block(draft),
        "",
        "Prior conversation in this assist session:",
        _transcript_block(session),
        "",
        "Reviewer request:",
        (message or "").strip() or "(empty)",
        "",
        "Unit source_text (thin extract — secondary to attached PDF/images when present):",
        body,
    ]
    return "\n".join(lines)


def _invoke_assist(
    llm: AssistClient,
    system: str,
    user: str,
    *,
    attachments: AssistAttachments,
) -> str:
    kwargs: dict[str, Any] = {}
    if attachments.modality == "pdf" and attachments.pdf_path is not None:
        kwargs["pdf_path"] = attachments.pdf_path
    if attachments.modality == "vision" and attachments.images:
        kwargs["images"] = attachments.images
    try:
        return llm.complete(system, user, **kwargs)
    except TypeError:
        return llm.complete(system, user)  # type: ignore[call-arg]


def run_assist_turn(
    *,
    session: AssistSession,
    unit: SemanticUnit,
    message: str,
    draft: dict[str, Any] | None,
    llm: AssistClient,
    document: DocumentContext | None = None,
    attachments: AssistAttachments | None = None,
) -> AssistSuggestion:
    """Call the assist model and append both turns to the session."""
    session.unit_key = unit.unit_key
    user_text = (message or "").strip()
    prior = AssistSession(
        session_id=session.session_id,
        doc_id=session.doc_id,
        version=session.version,
        unit_key=session.unit_key,
        turns=list(session.turns),
    )
    atts = attachments or AssistAttachments(modality="none")
    system = corpus_assist_system()
    user = build_user_prompt(
        unit=unit,
        message=user_text,
        draft=draft,
        session=prior,
        document=document,
        attachment_modality=atts.modality,
    )
    try:
        raw = _invoke_assist(llm, system, user, attachments=atts)
    finally:
        atts.cleanup()
    suggestion = parse_assist_response(raw)
    session.append(
        AssistTurn(role="user", content=user_text, unit_key=unit.unit_key)
    )
    session.append(
        AssistTurn(
            role="assistant",
            content=suggestion.rationale or raw.strip()[:500],
            unit_key=unit.unit_key,
            suggestions=suggestion.as_dict(),
        )
    )
    return suggestion


def assist_prompt_version() -> str:
    return prompt_digest("corpus_assist_system")


__all__ = [
    "AssistAttachments",
    "AssistClient",
    "AssistError",
    "AssistSuggestion",
    "DocumentContext",
    "assist_prompt_version",
    "build_assist_client",
    "build_user_prompt",
    "parse_assist_response",
    "prepare_unit_attachments",
    "run_assist_turn",
]
