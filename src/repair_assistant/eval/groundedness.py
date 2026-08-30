"""Claim-level lexical groundedness (review R27 / ADR-0029).

A claim is *supported* when its content tokens appear in the cited evidence
block (or the claim is a near-substring of that block). Zero overlap against a
cited block is a hard fail — that is the invented-procedure-plus-valid-[n] case.
Paraphrase misses are counted in the unsupported rate and do not fail the gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from repair_assistant.qa.structured import Claim

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "have",
        "has",
        "not",
        "but",
        "you",
        "your",
        "may",
        "can",
        "should",
        "then",
        "than",
        "into",
        "onto",
        "over",
        "under",
        "after",
        "before",
        "when",
        "what",
        "which",
        "there",
        "their",
        "them",
        "they",
        "also",
        "only",
        "just",
        "any",
        "all",
        "see",
        "use",
        "using",
    }
)
_PROCEDURAL = re.compile(
    r"\b(test|check|measure|replace|disconnect|remove|install|torque|vac|ohm|"
    r"inspect|unplug|bypass|jumper)\b",
    re.I,
)
_GENERIC = frozenset(
    {
        "door",
        "lock",
        "washer",
        "fault",
        "error",
        "code",
        "control",
        "switch",
        "cycle",
        "drain",
        "pump",
    }
)


@dataclass
class ClaimSupport:
    text: str
    evidence_index: int | None
    supported: bool
    hard_fail: bool
    reason: str


@dataclass
class GroundednessReport:
    checked: int = 0
    supported: int = 0
    unsupported: int = 0
    hard_unsupported: int = 0
    details: list[ClaimSupport] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        """Unsupported / checked. None when nothing was checkable."""
        if self.checked == 0:
            return None
        return self.unsupported / self.checked


def content_tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def claim_supported_by(claim_text: str, evidence: str) -> bool:
    claim = (claim_text or "").strip()
    block = (evidence or "").strip()
    if not claim:
        return True
    if not block:
        return False
    folded = _normalize(claim)
    haystack = _normalize(block)
    if len(folded) >= 12 and folded in haystack:
        return True
    tokens = content_tokens(claim)
    if not tokens:
        return True
    overlap = tokens & content_tokens(block)
    if len(tokens) <= 3:
        return overlap == tokens
    return len(overlap) / len(tokens) >= 0.6


def _should_check(claim: Claim) -> bool:
    if claim.evidence_index is not None:
        return True
    text = claim.text or ""
    return bool(_PROCEDURAL.search(text)) and len(content_tokens(text)) >= 4


def score_claims(
    claims: list[Claim],
    evidence_blocks: dict[int, str],
) -> GroundednessReport:
    report = GroundednessReport()
    for claim in claims:
        if not _should_check(claim):
            continue
        report.checked += 1
        idx = claim.evidence_index
        if idx is None:
            row = ClaimSupport(
                text=claim.text,
                evidence_index=None,
                supported=False,
                hard_fail=True,
                reason="uncited procedural claim",
            )
        else:
            block = evidence_blocks.get(idx) or ""
            if not block:
                row = ClaimSupport(
                    text=claim.text,
                    evidence_index=idx,
                    supported=False,
                    hard_fail=True,
                    reason=f"no evidence block [{idx}]",
                )
            elif claim_supported_by(claim.text, block):
                row = ClaimSupport(
                    text=claim.text,
                    evidence_index=idx,
                    supported=True,
                    hard_fail=False,
                    reason="ok",
                )
            else:
                tokens = content_tokens(claim.text)
                found = content_tokens(block)
                overlap = tokens & found
                specific = tokens - _GENERIC
                hard = len(overlap) == 0 or bool(specific and not (specific & found))
                row = ClaimSupport(
                    text=claim.text,
                    evidence_index=idx,
                    supported=False,
                    hard_fail=hard,
                    reason="no supporting tokens in cited block"
                    if hard
                    else "weak lexical support",
                )
        report.details.append(row)
        if row.supported:
            report.supported += 1
        else:
            report.unsupported += 1
            if row.hard_fail:
                report.hard_unsupported += 1
    return report


def format_evidence_for_judge(evidence_blocks: dict[int, str], *, max_chars: int = 4000) -> str:
    if not evidence_blocks:
        return ""
    parts: list[str] = []
    used = 0
    for idx in sorted(evidence_blocks):
        block = f"[{idx}] {evidence_blocks[idx]}"
        if used and used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def groundedness_failure_detail(report: GroundednessReport) -> str | None:
    hard = [d for d in report.details if d.hard_fail]
    if not hard:
        return None
    bits = [f"{d.reason}: {d.text[:80]!r}" for d in hard[:3]]
    return "ungrounded: " + "; ".join(bits)
