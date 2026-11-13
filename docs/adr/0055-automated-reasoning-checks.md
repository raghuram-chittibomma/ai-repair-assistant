# ADR-0055: SMT policy check on the answer path

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

Citation faithfulness ([ADR-0029](0029-claim-groundedness.md)) asks whether a
sentence is supported by the manual block it cites. That lexical check drops
tokens shorter than three characters and treats `not` as a stopword, so a
threshold or a negation can still look supported.

A second question is policy entailment: given the facts in the turn, does a
claim follow from rules the product owns? Embeddings and an LLM judge guess.
A satisfiability solver does not, once the claim is a formula over a fixed
vocabulary.

This check is additional. It does not replace retrieval, applicability,
lexical groundedness, or the safety regex gate.

## Decision

1. **Scope.** After `gate_answer`, on ask and on diagnose turns that generate.
   If the safety gate already replaced the answer, the solver does not run.
   Claims the policy does not translate stay on the citation path
   ([ADR-0029](0029-claim-groundedness.md)). Safety regex stays the CI safety
   gate ([ADR-0014](0014-safety-policy.md), [ADR-0032](0032-safety-classifier-union.md)).
   Applicability stays in retrieval.
2. **Policy.** `config/reasoning/answer_invariants.yaml` is the published
   version (`id`, integer `version`). Variables are bool, int, real, or enum.
   Each variable has a role: a `fact` is something the user states, a
   `claim` is something the answer asserts. A fact enum may name an
   `unknown` value (the topic came up, the fact did not) and may carry an
   `ask` question shown to the user when the fact is missing. A claim may
   name the fact it is about (`requires`); until the user states that fact,
   the claim goes to untranslated text instead of the solver, so a manual
   figure is not checked as if it were the user's reading, and a door claim
   is not checked on a turn that never described the door. A boolean claim
   is affirmative only: the translator records what the answer says, never
   what it leaves out. A check on "do not run X" needs its own claim. The
   `description` is the translator contract and is never shown to the user.
   Rules are an allowlisted if-then formula. The loader parses that allowlist
   into a Z3 term. It does not evaluate formula text. Manufacturer PDFs are
   not mined into rules, and no rule states a manual figure.
3. **Promotion.** `repair-corpus bench-reasoning` runs
   `evals/reasoning/fixtures.yaml`. The file names the policy version. A
   mismatch or a wrong verdict fails the command. Those scenarios are formal
   assignments, so the gate needs no model. Pytest runs the same pack.
   The gate also proves completeness: with every fact known (and not its
   `unknown` value), the rules decide each claim. Two copies of the rules
   share the facts and duplicate the claims; a claim is decided when the
   copies cannot disagree on it. Without this, a correct answer comes back
   `satisfiable` and is turned into a question. `satisfiable` therefore
   means a user fact is missing, never a gap in the rules.
4. **Translation.** One structured OpenAI call at `temperature=0`. The
   strict response schema has one branch per variable: premises admit only
   fact names, claims only claim names, and each value is typed (an enum
   list for bool and enum, a digit pattern for int and real). `ambiguous`
   lists the variables the turn addresses in two ways. The model cannot
   name a variable the policy does not have or put a fault code in a
   reading; an off-topic turn returns empty lists and is `no_translations`.
   Enum values say what the user means (`STUCK_LOCKED`, `WILL_NOT_LOCK`),
   and descriptions reuse the door idioms of
   [ADR-0040](0040-door-polarity-grammar.md), so "door got locked" is not
   read as a lock failure. The `Translator` interface returns a list so a later
   second translator can require agreement without changing the solver.
   This slice calls one translator. Confidence is 1.0 only when every name,
   role, enum, and type matches. Otherwise the result is `translation_ambiguous`
   or `no_translations`. An injected test model is not a translator: the
   check is skipped and the trace says `no_translator`. A transport failure
   is skipped as `translator_error` so a second-call outage does not replace
   the answer. A parsed but schema-invalid assignment fails closed.
   `repair-corpus bench-reasoning --translate` runs the live translator on
   `evals/reasoning/translation_probe.yaml`. That probe is reported, not a
   gate.
   On a diagnose progress turn ("still not working"), the translated
   question is the current symptom span plus the latest message, so the
   premise is the problem under work ([ADR-0046](0046-current-span-protocol.md)).
5. **Solver.** Local Z3, quantifier-free, with a timeout. `R` and `P`
   unsatisfiable → `impossible`. Else `R` and `P` and not `C` unsatisfiable →
   `valid`. Else `R` and `P` and `C` unsatisfiable → `invalid`. Else
   `satisfiable`. Timeout or an oversized formula → `too_complex`. Several
   claims take the worst of `too_complex`, `impossible`, `invalid`,
   `satisfiable`, `valid`. Soundness stops at the translation.
6. **Release.** `valid` ships, with the supporting rule ids and a model on
   the result. `invalid` is rewritten once; the prompt gets the contradicting
   rules and the counterexample. The rewrite is translated and solved again.
   Only `valid` ships. Anything else drops the contradicted claim. Cited
   untranslated text may remain. `satisfiable` and `translation_ambiguous`
   become a clarifying question built from the missing fact's `ask`, and
   are not stated as fact. `impossible` says the facts conflict.
   `no_translations` leaves the answer alone. Evidence attachments (page
   rasters, PDFs) live until the release finishes, so the rewrite sees the
   same evidence as the draft. On the streaming path the draft is held until
   the release decides, then the released text goes through the existing
   stream gate ([ADR-0026](0026-streaming-safety-gate.md)). Withheld text is
   never streamed. The `done` event carries `reasoning` with `duration_ms`.
7. **Charter.** Z3 is a local library. The translator reuses the existing
   opt-in OpenAI path. No stack deviation.

## Consequences

- A covered claim can be rewritten, withheld, or turned into a question.
- Untranslated procedure text is not proved and is not blocked by this check.
- Translation can still be wrong. A schema-valid wrong assignment yields a
  confident verdict. The promotion pack does not measure that step; the
  translation probe samples it by hand.
- A covered turn pays a second OpenAI call (and a third and fourth on a
  rewrite). The trace and the response carry `duration_ms`.
- A new rule must keep every claim decided, or `bench-reasoning` fails.
- No second translator, no policy service, and no formalization of cited
  manual spans in this slice.

## Measured (2026-11-13, `gpt-4o-mini`)

- `bench-reasoning`: 16/16 (policy version, three completeness rows, twelve
  scenarios). Translation probe: 16/16 (policy version + 15 natural turns) on
  three consecutive runs.
- Live `bench-qa` 7/10 and `bench-candidates` 16/34, the same as HEAD without
  the check run the same afternoon. Of 40 answers that reached the check,
  none were mutated: 33 `no_translations`, 6 `valid`, 1 skipped by the safety
  gate. The two scenarios that flipped between runs were `no_translations`,
  so the generator varied, not the release.
- Earlier live runs in the same session found five ways a translation
  replaced a correct answer, each fixed above and now a probe case: an
  invented variable name, a fault code or LED pattern in an integer
  variable, "door got locked" read as a lock failure, a manual resistance
  range read as the user's reading, and an omitted test recorded as a
  `false` claim.
- Check latency per generated answer: p50 about 3.0 s, p90 about 5.0 s, max
  6.5 s (one extra OpenAI call; no rewrite fired).

## Alternatives considered

| | Advisory findings only | LLM-as-judge for the same rules | SMT release rule |
| --- | --- | --- | --- |
| Contradicted claim can ship | Yes | Yes, probabilistically | No, after one rewrite |
| Thresholds and negation | Reported only | Guessed | Proved when the translation is right |
| Choice | Rejected | Rejected | **Accepted** |
