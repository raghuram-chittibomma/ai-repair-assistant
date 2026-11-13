# Candidate scenarios bench

- Lockfile: `uv.lock@ff28dce0cc5d`
- LLM_MODEL: `gpt-4o-mini`
- JUDGE_LLM_MODEL: `gpt-4.1-mini-2025-04-14`
- EMBEDDING_MODEL: `BAAI/bge-base-en-v1.5`

**16/34 passed**

| scenario | family | pass | ms | detail |
| --- | --- | --- | ---: | --- |
| acu-led-step-10 | precedence-bulletin-over-manual | NO | 37523 | must_cite missing 'W11375982'; got ['tech-sheet-w11156989-revd', 'W11156989 Rev D p.12 [structured]', 'W11156989'] |
| door-locks-wont-run-wrong-platform | applicability-serial-range | yes | 7545 | ok |
| serial-outside-range | applicability-serial-range | yes | 1263 | ok |
| serial-unknown-must-ask | applicability-serial-range | NO | 1263 | expect_contains_any missing one of ['serial']; det-only (needs --judge for prose) |
| f5e2-three-way | applicability-product-category | NO | 11895 | missing 'door lock' |
| f5e2-technician-depth | applicability-product-category | NO | 8857 | must_cite missing 'W11320651'; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.32 [structured] — F5E2', 'W11169652']; must_cite missing 'W11320651'; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.32 [structured] — F5E2', 'W11169652'] |
| door-lock-part-number | staleness-part-numbers | NO | 1258 | missing 'W10804741'; expect_contains_any missing one of ['confirm', 'catalog', 'catalogue', 'supersed', '2020', 'current', 'may have changed']; must_cite missing 'W11320547'; got []; det-only (needs --judge for prose) |
| error-code-lookup | retrieval-exact-identifier | NO | 8009 | expect_contains_any missing one of ['valve', 'test #6', 'inlet']; expect_cites_any missing one of ['W11320651', 'W11156989']; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.33 [structured] — F8E1', 'W11169652'] |
| error-code-orphaned-by-extraction | retrieval-exact-identifier | NO | 7653 | expect_cites_any missing one of ['W11320651', 'W11156989']; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.32 [structured] — F6E1', 'W11169652'] |
| publication-number-lookup | retrieval-exact-identifier | yes | 7712 | ok |
| connector-designation | retrieval-exact-identifier | yes | 7861 | ok |
| code-to-procedure-hop | retrieval-cross-reference | yes | 6990 | ok |
| unresponsive-control-panel | conversational-symptom | NO | 8046 | expect_contains_any missing one of ['control lock', 'LOC', 'lock']; det-only (needs --judge for prose) |
| installation-fault-not-component-fault | conversational-symptom | NO | 11079 | must_cite missing 'W11156977'; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.33 [structured]', 'W11169652', 'tech-sheet-w11320651', 'W11320651 Rev B p.9 [structured] — MC/MCU Overload.', 'W11320651'] |
| f5e2-narrow-then-exclude-24in | diagnostic-trajectory | yes | 27996 | ok; det turns only (needs --judge for prose) |
| control-lock-before-board | diagnostic-trajectory | NO | 16638 | turn 1: expect_contains_any missing one of ['control lock', 'LOC', 'lock']; turn 2: expect_contains_any missing one of ['HMI', 'ACU', 'test #2', 'communication', 'harness']; det turns only (needs --judge for prose) |
| f7e1-bolts-then-persist | diagnostic-trajectory | NO | 19862 | turn 1: expect_contains_any missing one of ['shipping', 'transport', 'bolt', 'install']; must_cite missing 'W11156977'; got ['service-manual-w11169652-revb', 'W11169652 Rev B p.33 [structured]', 'W11169652', 'tech-sheet-w11320651', 'W11320651 Rev B p.9 [structured] — MC/MCU Overload.', 'W11320651', 'tech-sheet-w11156989-revd', 'W11156989 Rev D p.9 [structured] — Motor disconnected error.', 'W11156989']; det turns only (needs --judge for prose) |
| mid-cycle-stop-diag-entry | diagnostic-trajectory | NO | 6456 | turn 1: expect_contains_any missing one of ['Service Diagnostic', 'diagnostic mode', '888', 'three (3) buttons', 'three buttons']; expect_cites_any missing one of ['W11169652']; got ['use-and-care-w11156985', 'W11156985 Rev A p.25 [structured]', 'W11156985']; det turns only (needs --judge for prose) |
| f5e2-door-lock-still-unresolved | diagnostic-trajectory | yes | 19725 | ok; det turns only (needs --judge for prose) |
| door-got-locked-unlock | intent-clarify-provenance | yes | 8016 | ok |
| door-doesnt-open-unlock | intent-clarify-provenance | yes | 6531 | ok |
| door-lock-underspecified-clarify | intent-clarify-provenance | yes | 1352 | ok |
| model-without-engineering-digit | applicability-engineering-digit | yes | 5027 | ok |
| digit-sensitive-document | applicability-engineering-digit | NO | 6143 | expect_contains_any missing one of ['WFW5620HW0', 'engineering', 'full model', 'complete model', 'exact model']; det-only (needs --judge for prose) |
| adjacent-base-model-must-not-match | applicability-engineering-digit | NO | 1337 | expect_contains_any missing one of ['not cover', 'does not cover', 'different', '7MWFW', 'no,', 'No,']; det-only (needs --judge for prose) |
| out-of-corpus-appliance | abstention | yes | 2856 | ok |
| out-of-corpus-model | abstention | NO | 7091 | must_not_cite hit 'kb-f5e2-top-load' |
| known-gap-revised-manual | abstention | yes | 25033 | ok |
| identifier-only-distinction | near-duplicate-tech-sheets | yes | 6627 | ok |
| shared-pages-deduplicated | near-duplicate-tech-sheets | yes | 11379 | ok; det-only (needs --judge for prose) |
| reflow-is-not-a-revision | near-duplicate-tech-sheets | NO | 7377 | expect_contains_any missing one of ['same', 'identical', 'both', 'unchanged', 'no difference', 'not differ']; det-only (needs --judge for prose) |
| genuine-incremental-addition | near-duplicate-tech-sheets | yes | 4801 | ok |
| language-must-be-filtered | near-duplicate-tech-sheets | NO | 1268 | expect_cites_any missing one of ['W11156989', 'W11320651']; got []; det-only (needs --judge for prose) |
| symbol-font-list-structure | near-duplicate-tech-sheets | NO | 15017 | expect_cites_any missing one of ['W11320651', 'W11156989']; got ['installation-instructions-w11156977', 'W11156977 Rev D p.20 [semantic] — Complete Installation Checklist', 'W11156977']; det-only (needs --judge for prose) |
