# Diagnose intent bake-off

Closed-set retrieve labels (ADR-0039). Candidate classifiers for ADR-0054.

## Repro

- Lockfile: `uv.lock@95db48c278cc`
- LLM_MODEL: `gpt-4o-mini`
- JUDGE_LLM_MODEL: `gpt-4.1-mini-2025-04-14`
- EMBEDDING_MODEL: `BAAI/bge-base-en-v1.5`
- JEV_MODEL: `jev-1.13.0`
- LLM_MODEL (openai arm): `gpt-4o-mini`
- OpenAI cost model: `$0.15/M` input + `$0.6/M` output (estimate from usage tokens)
- Jev cost model: `$0.042/M` input (estimate from usage tokens; use billed `cost_usd` when present)
- JEV_DECIDE_URL: `https://api.typesafe.ai/v1/systemone`

## Summary

| arm | n | correct | accuracy | mean latency (ms) | total cost (USD) | mean cost / call (USD) | notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `openai` | 20 | 14 | 70% | 1436 | 0.0009 | 0.000044 | estimated @ $0.15/M in + $0.6/M out |
| `jev` | 20 | 18 | 90% | 215 | 0.0004 | 0.000022 | estimated @ $0.042/M in (usage.cost_usd when present) |
| `regex` | 20 | 6 | 30% | 0 | 0 | 0 | local / $0 |

## Per-fixture labels

| id | expected | openai | jev | regex |
| --- | --- | --- | --- | --- |
| `ack-looks-good` | `ack` | `ack` ok | `ack` ok | `ack` ok |
| `ack-no-issues` | `ack` | `still_unresolved` miss | `still_unresolved` miss | `ack` ok |
| `ack-all-clear` | `ack` | `ack` ok | `ack` ok | `ack` ok |
| `ack-checks-passed` | `ack` | `ack` ok | `still_unresolved` miss | `ack` ok |
| `still-facing-issue` | `still_unresolved` | `still_unresolved` ok | `still_unresolved` ok | `still_unresolved` ok |
| `still-didnt-help` | `still_unresolved` | `still_unresolved` ok | `still_unresolved` ok | `(none)` miss |
| `still-same-problem` | `still_unresolved` | `still_unresolved` ok | `still_unresolved` ok | `(none)` miss |
| `still-did-not-fix` | `still_unresolved` | `still_unresolved` ok | `still_unresolved` ok | `still_unresolved` ok |
| `mid-cycle-no-code` | `mid_cycle_stop` | `new_symptom` miss | `mid_cycle_stop` ok | `(none)` miss |
| `mid-cycle-halfway` | `mid_cycle_stop` | `mid_cycle_stop` ok | `mid_cycle_stop` ok | `(none)` miss |
| `mid-cycle-stops-running` | `mid_cycle_stop` | `new_symptom` miss | `mid_cycle_stop` ok | `(none)` miss |
| `new-symptom-drain` | `new_symptom` | `new_symptom` ok | `new_symptom` ok | `(none)` miss |
| `new-symptom-leak` | `new_symptom` | `new_symptom` ok | `new_symptom` ok | `(none)` miss |
| `new-symptom-odor` | `new_symptom` | `new_symptom` ok | `new_symptom` ok | `(none)` miss |
| `new-symptom-error-code-swap` | `new_symptom` | `new_symptom` ok | `new_symptom` ok | `(none)` miss |
| `unclear-short` | `unclear` | `still_unresolved` miss | `unclear` ok | `(none)` miss |
| `unclear-maybe` | `unclear` | `unclear` ok | `unclear` ok | `(none)` miss |
| `unclear-question` | `unclear` | `unclear` ok | `unclear` ok | `(none)` miss |
| `unclear-thanks` | `unclear` | `still_unresolved` miss | `unclear` ok | `(none)` miss |
| `unclear-mixed` | `unclear` | `still_unresolved` miss | `unclear` ok | `(none)` miss |

## Per-fixture latency and cost

| id | openai ms | openai USD | jev ms | jev USD | regex ms | regex USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ack-looks-good` | 3958 | 0.000045 | 547 | 0.000022 | 0 | 0 |
| `ack-no-issues` | 1521 | 0.000048 | 161 | 0.000023 | 0 | 0 |
| `ack-all-clear` | 932 | 0.000042 | 184 | 0.000021 | 0 | 0 |
| `ack-checks-passed` | 1085 | 0.000042 | 189 | 0.000021 | 0 | 0 |
| `still-facing-issue` | 1236 | 0.000045 | 183 | 0.000022 | 0 | 0 |
| `still-didnt-help` | 1387 | 0.000047 | 187 | 0.000022 | 0 | 0 |
| `still-same-problem` | 1139 | 0.000048 | 169 | 0.000022 | 0 | 0 |
| `still-did-not-fix` | 1372 | 0.000043 | 219 | 0.000021 | 0 | 0 |
| `mid-cycle-no-code` | 1913 | 0.000046 | 224 | 0.000022 | 0 | 0 |
| `mid-cycle-halfway` | 2476 | 0.000044 | 197 | 0.000021 | 0 | 0 |
| `mid-cycle-stops-running` | 1248 | 0.000043 | 181 | 0.000021 | 0 | 0 |
| `new-symptom-drain` | 1038 | 0.000045 | 257 | 0.000022 | 0 | 0 |
| `new-symptom-leak` | 1032 | 0.000045 | 203 | 0.000022 | 0 | 0 |
| `new-symptom-odor` | 1046 | 0.000044 | 210 | 0.000021 | 0 | 0 |
| `new-symptom-error-code-swap` | 1051 | 0.000045 | 191 | 0.000022 | 0 | 0 |
| `unclear-short` | 2093 | 0.000044 | 191 | 0.000021 | 0 | 0 |
| `unclear-maybe` | 1178 | 0.000041 | 213 | 0.000021 | 0 | 0 |
| `unclear-question` | 951 | 0.000043 | 189 | 0.000021 | 0 | 0 |
| `unclear-thanks` | 1071 | 0.000043 | 212 | 0.000021 | 0 | 0 |
| `unclear-mixed` | 992 | 0.000044 | 194 | 0.000021 | 0 | 0 |

### Confusion (openai)

| expected \ predicted | count |
| --- | ---: |
| `ack → ack` | 3 |
| `ack → still_unresolved` | 1 |
| `mid_cycle_stop → mid_cycle_stop` | 1 |
| `mid_cycle_stop → new_symptom` | 2 |
| `new_symptom → new_symptom` | 4 |
| `still_unresolved → still_unresolved` | 4 |
| `unclear → still_unresolved` | 3 |
| `unclear → unclear` | 2 |

### Confusion (jev)

| expected \ predicted | count |
| --- | ---: |
| `ack → ack` | 2 |
| `ack → still_unresolved` | 2 |
| `mid_cycle_stop → mid_cycle_stop` | 3 |
| `new_symptom → new_symptom` | 4 |
| `still_unresolved → still_unresolved` | 4 |
| `unclear → unclear` | 5 |

### Confusion (regex)

| expected \ predicted | count |
| --- | ---: |
| `ack → ack` | 4 |
| `mid_cycle_stop → (none)` | 3 |
| `new_symptom → (none)` | 4 |
| `still_unresolved → (none)` | 2 |
| `still_unresolved → still_unresolved` | 2 |
| `unclear → (none)` | 5 |

## Labels

`ack`, `still_unresolved`, `mid_cycle_stop`, `new_symptom`, `unclear`

## Accept rule (ADR-0054)

Accept Jev when its accuracy ≥ OpenAI on this set (tie → prefer Jev).
At equal accuracy, lower latency / cost also favors Jev.
Regex is a baseline only; it cannot emit `mid_cycle_stop` / `new_symptom` / `unclear`.

**Decision hint:** Jev 90% > OpenAI 70% → accept ADR-0054 / prefer Jev.
