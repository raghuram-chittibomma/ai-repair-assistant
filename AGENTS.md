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
`vector_apply_boost`; do not start R11/R18/R20/R22 ranking or R41 feedback UI;
do not invent a held-out retrieval set; do not grow `query_expand.yaml` as
slang; `mine-traces` reports only.

## Commands

Windows PowerShell: separate commands with `;`, never `&&`.

```powershell
uv run pytest
uv run ruff check src tests
python -m repair_assistant.corpus.cli bench-layout --write
```
