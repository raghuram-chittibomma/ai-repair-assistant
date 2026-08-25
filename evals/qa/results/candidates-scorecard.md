# Candidate scenarios bench

**20/24 passed**

| scenario | family | pass | ms | detail |
| --- | --- | --- | ---: | --- |
| acu-led-step-10 | precedence-bulletin-over-manual | yes | 19830 | ok |
| door-locks-wont-run-wrong-platform | applicability-serial-range | yes | 4905 | ok |
| serial-inside-range | applicability-serial-range | NO | 2047 | must_cite missing 'W11395614'; got [] |
| serial-outside-range | applicability-serial-range | yes | 1312 | ok |
| serial-unknown-must-ask | applicability-serial-range | yes | 1010 | ok |
| f5e2-three-way | applicability-product-category | NO | 2760 | must_cite missing 'kb-f5e2-front-load'; got ['service-manual-w11169652-revb', 'W11169652', 'service-manual-w11169652', 'W11169652', 'tech-sheet-w11156989-revd', 'W11156989', 'tech-sheet-w11320651', 'W11320651']; must_cite missing 'kb-f5e2-front-load'; got ['service-manual-w11169652-revb', 'W11169652', 'service-manual-w11169652', 'W11169652', 'tech-sheet-w11156989-revd', 'W11156989', 'tech-sheet-w11320651', 'W11320651'] |
| door-lock-part-number | staleness-part-numbers | yes | 2016 | ok |
| error-code-lookup | retrieval-exact-identifier | yes | 2844 | ok |
| error-code-orphaned-by-extraction | retrieval-exact-identifier | yes | 3210 | ok |
| publication-number-lookup | retrieval-exact-identifier | yes | 2321 | ok |
| unresponsive-control-panel | conversational-symptom | yes | 3041 | ok |
| installation-fault-not-component-fault | conversational-symptom | yes | 2880 | ok |
| model-without-engineering-digit | applicability-engineering-digit | yes | 2368 | ok |
| digit-sensitive-document | applicability-engineering-digit | yes | 1789 | ok |
| adjacent-base-model-must-not-match | applicability-engineering-digit | yes | 1030 | ok |
| out-of-corpus-appliance | abstention | NO | 2336 | fails_if matched 'samsung' |
| out-of-corpus-model | abstention | yes | 1900 | ok |
| known-gap-revised-manual | abstention | NO | 3722 | must_cite missing 'W11169652'; got ['tsp-w11375982', 'W11375982', 'tsp-w11375982', 'W11375982'] |
| identifier-only-distinction | near-duplicate-tech-sheets | yes | 2377 | ok |
| shared-pages-deduplicated | near-duplicate-tech-sheets | yes | 4059 | ok |
| reflow-is-not-a-revision | near-duplicate-tech-sheets | yes | 2017 | ok |
| genuine-incremental-addition | near-duplicate-tech-sheets | yes | 3646 | ok |
| language-must-be-filtered | near-duplicate-tech-sheets | yes | 2742 | ok |
| symbol-font-list-structure | near-duplicate-tech-sheets | yes | 1745 | ok |
