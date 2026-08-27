"""Retrieval planner: intent → embed query, codes, hops (agent control loop)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repair_assistant.retrieval.intent import QueryIntent, extract_intent
from repair_assistant.retrieval.query_expand import expansion_phrases_for_polarity

# Shared with rank polarity heuristics (OEM wording).
_UNLOCK_EVIDENCE = re.compile(
    r"will not unlock|won'?t unlock|door will not unlock|add garment|"
    r"door locks when cycle|f5\s*e2|lock failure",
    re.I,
)
_WRONG_UNLOCK_POLARITY = re.compile(
    r"door won'?t lock|door will not lock|ensure that door is completely closed|"
    r"door not closed",
    re.I,
)

_CLARIFY_EVIDENCE = (
    "I found mixed guidance about locking vs unlocking. "
    "Is the door stuck closed (won't open), or will it not lock to start a cycle? "
    "Any error code on the display?"
)


@dataclass(frozen=True)
class RetrievalPlan:
    """Executable retrieval program derived from intent."""

    embed_query: str
    user_codes: tuple[str, ...] = ()
    # Retrieval hints only — never treat as confirmed on-appliance codes.
    plan_codes: tuple[str, ...] = ()
    audience: str = "owner"
    # Channels / hops. ``graph`` is reserved for a future GraphRAG step.
    hops: tuple[str, ...] = ("vector", "code", "xref")
    intent: QueryIntent | None = None
    enable_graph_hop: bool = False  # placeholder — not wired yet

    @property
    def codes(self) -> tuple[str, ...]:
        """Union used for code_fetch (user + plan hints)."""
        return tuple(dict.fromkeys([*self.user_codes, *self.plan_codes]))


@dataclass(frozen=True)
class EvidenceFit:
    ok: bool
    clarify_question: str | None = None


def suggest_plan_codes(intent: QueryIntent) -> tuple[str, ...]:
    """Topic-driven retrieval code hints (not user-reported).

    Add new topic→code mappings here as evals justify them; keep them out of
    answer assertions via ``user_codes`` vs ``plan_codes`` provenance.
    """
    suggested: list[str] = []
    user = {c.upper() for c in intent.user_codes}
    if intent.door_polarity == "unlock" and "F5E2" not in user:
        suggested.append("F5E2")
    return tuple(dict.fromkeys(suggested))


def plan_retrieval(intent: QueryIntent) -> RetrievalPlan:
    """Build a retrieval plan from structured intent (no free-form guessing)."""
    q = intent.raw_query
    phrases = expansion_phrases_for_polarity(intent.door_polarity)
    embed = f"{q} {phrases}".strip() if phrases else q

    plan_codes = suggest_plan_codes(intent)

    hops: list[str] = ["vector", "code", "connector", "xref"]
    if intent.door_polarity:
        hops.append("polarity_expand")
    # Future: when structured xref fails, enable GraphRAG / entity graph hop.
    enable_graph = False
    if enable_graph:
        hops.append("graph")

    return RetrievalPlan(
        embed_query=embed,
        user_codes=tuple(intent.user_codes),
        plan_codes=plan_codes,
        audience=intent.audience,
        hops=tuple(hops),
        intent=intent,
        enable_graph_hop=enable_graph,
    )


def plan_for_query(question: str, *, audience: str | None = None) -> RetrievalPlan:
    return plan_retrieval(extract_intent(question, audience=audience))


def check_evidence_fit(intent: QueryIntent, hit_texts: list[str]) -> EvidenceFit:
    """Gate: refuse to answer when top evidence conflicts with intent polarity."""
    if intent.door_polarity != "unlock" or not hit_texts:
        return EvidenceFit(ok=True)

    top = hit_texts[:5]
    unlock_hits = sum(1 for t in top if _UNLOCK_EVIDENCE.search(t or ""))
    wrong_only = sum(
        1
        for t in top
        if _WRONG_UNLOCK_POLARITY.search(t or "") and not _UNLOCK_EVIDENCE.search(t or "")
    )
    if wrong_only >= 2 and unlock_hits == 0:
        return EvidenceFit(ok=False, clarify_question=_CLARIFY_EVIDENCE)
    return EvidenceFit(ok=True)


def plan_to_dict(plan: RetrievalPlan) -> dict:
    from repair_assistant.retrieval.intent import intent_to_dict

    return {
        "embed_query": plan.embed_query,
        "user_codes": list(plan.user_codes),
        "plan_codes": list(plan.plan_codes),
        "codes": list(plan.codes),
        "audience": plan.audience,
        "hops": list(plan.hops),
        "enable_graph_hop": plan.enable_graph_hop,
        "intent": intent_to_dict(plan.intent) if plan.intent else None,
    }


def provenance_prompt_block(*, user_codes: tuple[str, ...], plan_codes: tuple[str, ...]) -> str:
    """Inject into the user prompt so the LLM sees code provenance every turn."""
    user = ", ".join(user_codes) if user_codes else "(none)"
    planned = ", ".join(plan_codes) if plan_codes else "(none)"
    return (
        "Code provenance:\n"
        f"- Reported by user (may state as on-appliance): {user}\n"
        f"- Suggested for retrieval only (do NOT state as confirmed on the "
        f"appliance; you may say 'If you see CODE…' with citations): {planned}"
    )


__all__ = [
    "EvidenceFit",
    "RetrievalPlan",
    "check_evidence_fit",
    "plan_for_query",
    "plan_retrieval",
    "plan_to_dict",
    "provenance_prompt_block",
    "suggest_plan_codes",
]
