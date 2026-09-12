# ADR-0040: Door polarity is compositional, not a slang list

## Status

Accepted. Refines the door-polarity half of
[ADR-0034](0034-diagnose-nlu-split.md) without superseding it. Does not
open unconstrained query rewrite or ranking R11 / R20 / R22.

## Context

Unlock vs lock is a real literature split (`Door will not unlock` vs
`Door Won't Lock`). Retrieval only demotes the lock table when polarity
is `unlock`. That label came from enumerating `when_user_says` strings.

`door won't open` matched. `door doesn't open` did not — same meaning,
missing contraction — so BGE ranked the lock table and the model cited
TEST #4 / “ensure the door is closed.”

Adding `doesn't open` to YAML would fix one utterance and invite the next
(`isn't opening`, `can't get the door open`). That is the slang-dictionary
path ADR-0034 rejected. A classify call that returns `lock` | `unlock`
would also work, but it is an extra LLM hop for a closed English
negation, and ask-path retrieve must stay offline-capable.

## Options

| | A — Add the missing phrases | B — Closed-set polarity classify | C — Negation × lemma grammar |
| --- | --- | --- | --- |
| Covers `doesn't` / `isn't` / `can't get … open` | One row each | Yes, if the label set holds | Yes, after contraction fold |
| Grows `query_expand.yaml` as slang | Yes | No | No |
| Extra LLM call / API key | No | Yes, every ask | No |
| OEM `add_to_search` stays curator-owned | Yes | Yes | Yes |
| Choice | Rejected | Rejected (cost; ask must work without a key) | **Accepted** |

## Decision

1. **Polarity is grammar.** Fold contractions (`doesn't` → `does not`),
   then match negation + `{open, opening, unlock, unlocking}` vs
   infinitive `{lock, latch}` / `not locking`. Both fire → `None`
   (clarify), same as today.
2. **Do not treat `is not locked` as lock.** That is an adjective state,
   not “will not latch.”
3. **YAML keeps OEM expand and non-compositional idioms only**
   (`got locked`, `stuck locked`, `failed to lock`). Productive
   contractions do not belong in `when_user_says`.
4. **`add_to_search` must still appear in the literature.** Unlock
   family contents after this ADR are [ADR-0041](0041-unlock-family-no-fault-code.md)
   (no F5E2 / lock failure). The model still does not write the search query.
5. **Rank boosts / diagnose labels are unchanged.** Once polarity is
   `unlock`, existing unlock boosts and lock-table demotes apply.

## Consequences

- `door doesn't open` expands like `door won't open` and demotes
  `Door Won't Lock`.
- New everyday variants that are still negation + those lemmas do not
  need a YAML row.
- Idioms that are not negation + verb still need a curator line.
- Mid-cycle stop stays YAML `when_user_says` / `phrase_pairs` (different
  construction; not this ADR).

**Charter:** evidence-driven architecture; no stack deviation. OpenAI
stays LLM-only. No new required cloud dependency.
