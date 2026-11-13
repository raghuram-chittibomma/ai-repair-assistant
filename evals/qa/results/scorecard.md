# Q&A smoke bench

- Lockfile: `uv.lock@ff28dce0cc5d`
- LLM_MODEL: `gpt-4o-mini`
- JUDGE_LLM_MODEL: `gpt-4.1-mini-2025-04-14`
- EMBEDDING_MODEL: `BAAI/bge-base-en-v1.5`

**7/10 passed**

| scenario | command | pass | ms | ungrounded | detail |
| --- | --- | --- | ---: | ---: | --- |
| f5e2-meaning | ask | NO | 21188 | 1/2 | missing 'door lock' |
| f5e2-door-locks-wont-start | diagnose | yes | 27353 | 0/1 | ok |
| acu-led-step-10 | ask | NO | 20294 | 0/2 | expect_cites_any missing one of ['W11375982']; got ['tech-sheet-w11156989-revd', 'W11156989 Rev D p.12 [structured]', 'W11156989'] |
| door-locks-wont-run-no-wrong-bulletin | ask | yes | 7889 | 0/1 | ok |
| unknown-error-abstain | ask | yes | 3066 | n/a | ok |
| mid-cycle-stop-diag-entry | diagnose | NO | 8347 | 1/2 | turn 1: expect_contains_any missing one of ['Service Diagnostic', 'diagnostic mode', '888', 'three (3) buttons', 'three buttons']; expect_cites_any missing one of ['W11169652']; got ['use-and-care-w11156985', 'W11156985 Rev A p.25 [structured]', 'W11156985', 'use-and-care-w11156985', 'W11156985 Rev A p.24 [structured]', 'W11156985'] |
| f5e2-door-lock-still-unresolved | diagnose | yes | 19615 | 1/1 | ok |
| door-got-locked-unlock | ask | yes | 7571 | 1/1 | ok |
| door-doesnt-open-unlock | ask | yes | 6801 | 0/1 | ok |
| door-lock-underspecified-clarify | ask | yes | 1352 | n/a | ok |

## Groundedness (review R27)

Mean unsupported-claim rate: 0.38 (n=8 scenarios with checkable claims).
Hard fail is zero token overlap between a claim and its cited block.
