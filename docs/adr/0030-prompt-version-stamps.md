# ADR-0030: Prompt files stay source of truth; Langfuse holds a labeled snapshot

## Status

Accepted — review R24 (Reduce). Automated prompt evals stay a manual
`bench-qa` / `bench-candidates` run (need an OpenAI key).

## Context

Prompts are git-committed `.txt` files. Their only test asserted substrings.
Langfuse can version prompts and link them to traces, but pulling live text
from Langfuse would break offline CI and make git no longer the reviewable
source.

## Decision

1. **Files remain the source of truth.** `load_prompt` always reads the
   package `.txt`. Generation never fetches prompt bodies from Langfuse.
2. **Every generation span** is stamped with `prompt_name`,
   `prompt_file_sha256` (file bytes), and `prompt_sha256` (the system string
   actually sent, including safety directives).
3. **When Langfuse keys are set**, the first use of a named prompt upserts
   that file into Langfuse (`labels=["production"]`) so the UI has a version
   history. Sync failures are logged and ignored.
4. **Quality gate** for a prompt edit is still a human `bench-qa --write`
   (and `--judge` when prose criteria apply). No CI prompt eval.

**Charter:** no deviation. Tracing stays opt-in (ADR-0018).

## Consequences

- A prompt edit changes the file hash on the next trace without a Langfuse
  UI click.
- Langfuse Prompt versions exist only on machines that have keys set and
  have run a generation since the edit.
- Automated A/B prompt evals are out of scope until a key is available in
  a scheduled job.
