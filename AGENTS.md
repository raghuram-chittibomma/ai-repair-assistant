# Agent instructions

Cursor rules in `.cursor/rules/` are the working constraints. This file is the
index. Do not treat chat history as a licence to reopen a settled decision.

## North star

| Doc | Role |
| --- | --- |
| [docs/CHARTER.md](docs/CHARTER.md) | Vision, fixed stack, D8 LAN-only, deviations |
| [docs/adr/README.md](docs/adr/README.md) | Accepted decisions; supersede with a new ADR |
| [docs/architecture/](docs/architecture/) | Current diagrams (01–07) |
| [docs/EVALS.md](docs/EVALS.md) | How to measure a change |
| [docs/ARCHITECTURE_REVIEW_RESPONSE.md](docs/ARCHITECTURE_REVIEW_RESPONSE.md) | Review triage and slice status |

`docs/ARCHITECTURE_REVIEW.md` and `docs/EVAL_FRAMEWORK_GAPS.md` are dated
snapshots. Do not edit them.

## Loop

**Requirement → candidate → measure → ADR → implement → bench.** Do not swap
the stack (Python, Postgres/pgvector, Docker, LangGraph, OpenAI for LLM only,
local BGE embeddings). Manufacturer PDFs stay out of git.

## Standing product freeze

Encoded in `.cursor/rules/standing-decisions.mdc`. In short: keep
`vector_apply_boost`; do not start R11/R20/R22 ranking or R41 feedback UI;
R18 is closed-set diagnose retrieve labels ([ADR-0039](docs/adr/0039-diagnose-retrieve-labels.md)), not slang YAML, a rule-only agent, or free query rewrite;
do not invent a held-out retrieval set; door polarity is compositional
([ADR-0040](docs/adr/0040-door-polarity-grammar.md)); unlock retrieve is
stuck-closed OEM not F5E2 ([ADR-0041](docs/adr/0041-unlock-family-no-fault-code.md));
same-problem rows coalesce into one citation ([ADR-0042](docs/adr/0042-guide1-anchor-and-checklist-coalesce.md));
progress follow-ups reuse the session evidence pack ([ADR-0043](docs/adr/0043-session-evidence-reuse.md));
the diagnose tally is a read-only board view ([ADR-0044](docs/adr/0044-diagnose-session-tally.md)), not R41;
`mine-traces` reports only.

## Commands

Windows PowerShell: separate commands with `;`, never `&&`.

```powershell
uv run pytest
uv run ruff check src tests
python -m repair_assistant.corpus.cli bench-layout --write
```
