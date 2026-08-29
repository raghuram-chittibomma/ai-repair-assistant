# ADR-0025 — Deferred scope: multi-user, product outcome, and curation at scale

- Status: Proposed
- Date: 2026-08-29
- Charter: constraint **D8** (deployment scope); cross-phase
- Responds to: [ARCHITECTURE_REVIEW.md](../ARCHITECTURE_REVIEW.md) R2, R6, R32,
  R34, R42, R47 — triaged in
  [ARCHITECTURE_REVIEW_RESPONSE.md](../ARCHITECTURE_REVIEW_RESPONSE.md)

## Context

An external review recorded 48 findings. Most are accepted and scheduled. A
subset is different in kind: the code is exactly as described, but the condition
that makes it a defect does not exist. Charter **D8** scopes this project to a
single-user LAN deployment; the corpus is one product family and roughly 20
documents; there is no user population.

Recording each of those as its own ADR would imply six independent decisions.
There is one decision — *stay inside D8* — with six consequences.

The review's own secondary theme is the reason this ADR is worth writing at all:

> The project is well-reasoned about decisions it **made** and under-instrumented
> about decisions it **deferred**. Deferred items are documented honestly in ADRs,
> but nothing detects the moment a deferral becomes a defect.

A deferral without a detector is the failure this ADR exists to avoid. Every entry
below therefore carries a **reopen trigger** and, where one is cheap, a
**detector** that makes the trigger announce itself rather than waiting to be
remembered.

Note that R32 is **not** a new deferral. ADR-0021 already recorded "Postgres
session durability remains deferred (single-user LAN; multi-user later)." This ADR
restates it only to attach a trigger and detector, which ADR-0021 did not.

## Options

| Topic | Options | Choice |
| --- | --- | --- |
| Granularity | One ADR per finding vs one consolidated scope ADR vs leave them in the gap doc | **One consolidated ADR** — the findings share a single cause (D8), and six records would overstate the number of decisions |
| Framing | "Backlog, not yet done" vs "deferred with a trigger" vs "permanent non-goal" | **Trigger-bearing deferral**, and separately an explicit **non-goal** list for the three that will never be built |
| Detection | Rely on periodic re-review vs cheap automated detectors where possible | **Detectors where cheap**, re-review otherwise — an undetected deferral is the defect being fixed here |
| Alternative | Fix them now instead | **Rejected** — each adds durable complexity (multi-tenancy, accounts, curation tooling) to serve conditions that do not exist, and the review's rules of engagement warn against exactly this |

## Deferred, with reopen triggers

| Finding | Deferred | Safe today because | Reopen trigger | Detector |
| --- | --- | --- | --- | --- |
| **R6** | Session ownership binding. Sessions are UUID4-keyed with no caller association, so any holder of an id can continue that diagnosis | One operator on a LAN, and the id is never transmitted off-host | The API serves more than one person, or is reachable beyond the LAN | Startup warning when auth is unset **and** the bind address is not loopback (lands with R5 in slice 1) |
| **R32** | Postgres-backed sessions. In-memory, `DEFAULT_SESSION_MAX = 32`, LRU-evicted, lost on restart. Already deferred in ADR-0021 | One concurrent session in practice; 32 is ~32× headroom | `REPAIR_SESSION_MAX` is raised, more than one API worker is configured, or R42 history is built | Startup warning if the configured worker count exceeds 1, since process-local state is silently wrong at that point |
| **R47** | Manifest curation tooling — LLM-assisted bootstrap, drift detection between a manifest entry and its document, and a curation cost model | ~20 documents, ~100 lines of hand-authored YAML each, and the quality is high | The corpus passes ~50 documents, or a second brand is added | `repair-corpus status` emits a notice above the document threshold, so the corpus itself announces the trigger |
| **R42** (partial) | Accounts, saved appliances, and cross-session history | No users, and no authentication story under D8 | A decision to serve real users | None needed — this is a deliberate product decision, not a drift risk |

R42's remaining half is **not** deferred: linking a concluded diagnosis to the
part number in the already-indexed parts list (`parts-list-w11320547`) is cheap and
scheduled in slice 7 of the response document. The deferral covers only accounts
and history.

## Permanent non-goals

These are not deferrals. No trigger will make them correct, so they should stop
appearing as gaps.

| Finding | Non-goal | Reason |
| --- | --- | --- |
| **R2** | Verifying that a caller is a qualified technician | No mechanism exists for a self-hosted appliance-repair assistant to attest professional status. The achievable actions — logging the claim and an explicit attestation interstitial — are accepted and scheduled in slice 7, and are the whole available action space |
| **R34** | Serving Spanish or French users | Prompts, UI, safety patterns, and evals are English-only, and localising all four is a product programme, not a feature. The review is right that the current state is the worst of both, so the *cost* side is being removed: non-English chunks stop being embedded, which reclaims index weight the product cannot use |
| **R30** (partial) | Inter-annotator agreement statistics on the judge calibration pack | A single developer cannot produce a second independent annotation. Judge-model diversity and an abstention option are accepted instead |

## Consequences

- Six review findings move out of the backlog and into a recorded scope boundary.
  They are no longer open work, and they are no longer silently absent either.
- Three detectors are added as follow-on tasks (loopback/auth startup warning,
  worker-count warning, corpus-size notice). Each is a few lines and each converts
  a remembered condition into an announced one. **If these are not built, this ADR
  is worth materially less than it appears** — it becomes the same undetected
  deferral it was written to fix.
- Anything reopening one of these triggers should supersede this ADR rather than
  amend it, per the immutability rule in the ADR index.
- This ADR **affirms** D8 rather than deviating from it, so no row is added to the
  charter's Deviations register.
- Scope note for readers of the review: this ADR covers only the findings listed
  above. R11, R20, R31, and R33 are *accepted* work in slices 6 and 7 of the
  response document and are deliberately excluded here — deferring them would be
  using this ADR to avoid the review's substance.
