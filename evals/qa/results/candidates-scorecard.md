# Candidate scenarios bench

**22/24 passed**

| scenario | family | pass | ms | detail |
| --- | --- | --- | ---: | --- |
| acu-led-step-10 | precedence-bulletin-over-manual | yes | 15509 | ok |
| door-locks-wont-run-wrong-platform | applicability-serial-range | yes | 7111 | ok |
| serial-inside-range | applicability-serial-range | NO | 1811 | must_cite missing 'W11395614'; got [] |
| serial-outside-range | applicability-serial-range | yes | 1524 | ok |
| serial-unknown-must-ask | applicability-serial-range | yes | 1207 | ok |
| f5e2-three-way | applicability-product-category | NO | 3258 | must_cite missing 'kb-f5e2-front-load'; got ['service-manual-w11169652-revb', 'W11169652', 'kb-error-codes-front-load', 'kb-error-codes-front-load']; must_cite missing 'kb-f5e2-front-load'; got ['service-manual-w11169652-revb', 'W11169652', 'kb-error-codes-front-load', 'kb-error-codes-front-load'] |
| door-lock-part-number | staleness-part-numbers | yes | 2857 | ok |
| error-code-lookup | retrieval-exact-identifier | yes | 3749 | ok |
| error-code-orphaned-by-extraction | retrieval-exact-identifier | yes | 3640 | ok |
| publication-number-lookup | retrieval-exact-identifier | yes | 2516 | ok |
| unresponsive-control-panel | conversational-symptom | yes | 5302 | ok |
| installation-fault-not-component-fault | conversational-symptom | yes | 5330 | ok |
| model-without-engineering-digit | applicability-engineering-digit | yes | 2284 | ok |
| digit-sensitive-document | applicability-engineering-digit | yes | 2225 | ok |
| adjacent-base-model-must-not-match | applicability-engineering-digit | yes | 1210 | ok |
| out-of-corpus-appliance | abstention | yes | 1983 | ok |
| out-of-corpus-model | abstention | yes | 3236 | ok |
| known-gap-revised-manual | abstention | yes | 7895 | ok |
| identifier-only-distinction | near-duplicate-tech-sheets | yes | 2910 | ok |
| shared-pages-deduplicated | near-duplicate-tech-sheets | yes | 3623 | ok |
| reflow-is-not-a-revision | near-duplicate-tech-sheets | yes | 2253 | ok |
| genuine-incremental-addition | near-duplicate-tech-sheets | yes | 4614 | ok |
| language-must-be-filtered | near-duplicate-tech-sheets | yes | 4050 | ok |
| symbol-font-list-structure | near-duplicate-tech-sheets | yes | 2040 | ok |
