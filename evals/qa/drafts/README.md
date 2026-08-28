# Trace-mine analysis (ADR-0023)

`mine-traces --write` writes **only** a timestamped markdown report here
(`mine-report-*.md`). It does **not**:

- edit `smoke-scenarios.yaml` / `candidates.yaml`
- write draft YAML fixture files
- update any mine-state or append durable improvement logs

Review the report. If an **Actionable** item still matters, copy the suggested
YAML into smoke/candidates yourself with `status: ready`, then re-run the
relevant bench.
